from __future__ import annotations

import json
import os
import re
import sqlite3
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus, urlparse

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from flask import Flask, abort, jsonify, redirect, render_template, render_template_string, request, url_for

from backend.cloud.sync_to_supabase import sync_sqlite_to_supabase
from backend.services.crm_service import add_activity, add_note, complete_task, create_company_from_payload, create_contact, create_task

BASE_DIR = Path(__file__).resolve().parent
ENV_PATHS = [BASE_DIR / ".env", Path.cwd() / ".env"]


def _read_env_value(*names: str, default: str = "") -> str:
    for name in names:
        value = (os.getenv(name) or "").strip()
        if value:
            return value
    return default


def _load_environment(env_path: Path | None = None) -> dict:
    resolved_path = env_path or next((candidate for candidate in ENV_PATHS if candidate.exists()), BASE_DIR / ".env")
    if env_path is not None:
        load_dotenv(env_path, override=True)
    else:
        for candidate in ENV_PATHS:
            if candidate.exists():
                load_dotenv(candidate, override=True)
        if not resolved_path.exists():
            load_dotenv(override=True)

    sender_email = _read_env_value("FROM_EMAIL", "RESEND_FROM_EMAIL", "SENDER_EMAIL", default="info@mednovalife.com")
    sender_name = _read_env_value("SENDER_NAME", "ORGANIZATION_NAME", "ORG_NAME", "COMPANY_NAME", default="MedNova Lifesciences")

    env_values = {
        "resendApiKeyConfigured": bool((os.getenv("RESEND_API_KEY") or "").strip()),
        "senderEmailConfigured": bool(sender_email),
        "senderNameConfigured": bool(sender_name),
        "senderEmail": sender_email,
        "senderName": sender_name,
        "dotenvLoaded": resolved_path.exists(),
        "dotenvPath": str(resolved_path),
    }
    return env_values


def _log_startup_diagnostics() -> None:
    env_state = _load_environment()
    print(f"✓ .env loaded: {env_state['dotenvLoaded']}")
    if env_state["dotenvLoaded"]:
        print(f"✓ Resend API key detected: {'yes' if env_state['resendApiKeyConfigured'] else 'no'}")
        print(f"✓ Sender email configured: {'yes' if env_state['senderEmailConfigured'] else 'no'}")
        print(f"✓ Sender name configured: {'yes' if env_state['senderNameConfigured'] else 'no'}")
    else:
        print("⚠ .env not loaded")
        print("⚠ Resend API key detected: no")
        print("⚠ Sender email configured: no")
        print("⚠ Sender name configured: no")


_log_startup_diagnostics()

EMAIL_RE = re.compile(r"([A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,})", re.IGNORECASE)
PHONE_RE = re.compile(r"(\+?\d[\d\-\s().]{7,}\d)")
LINKEDIN_RE = re.compile(r"https?://(?:www\.)?linkedin\.com/[^\s\"'<>]+", re.IGNORECASE)


def _crm_deal_stage_to_frontend(stage: str | None) -> str:
    stage_value = (stage or "lead").strip().lower()
    allowed = {"lead", "qualified", "contacted", "meeting", "proposal", "negotiation", "won", "lost"}
    if stage_value in allowed:
        return stage_value
    if stage_value in {"prospect", "new"}:
        return "lead"
    if stage_value in {"demo", "discovery"}:
        return "qualified"
    return "lead"


def _crm_deal_payload_from_row(row) -> dict:
    return {
        "id": int(row["id"]),
        "companyId": int(row["crm_company_id"]),
        "contactId": int(row["crm_contact_id"]) if row["crm_contact_id"] is not None else None,
        "title": row["title"] or "Deal",
        "stage": _crm_deal_stage_to_frontend(row["stage"]),
        "value": int(row["value"] or 0),
        "currency": (row["currency"] or "NGN").upper() if (row["currency"] or "NGN") else "NGN",
        "probability": int(row["probability"] or 0),
        "expectedCloseAt": row["expected_close_at"],
        "owner": row["owner"],
        "description": row["description"] or "",
    }


def _create_pipeline_deal_row(conn, company_id: int, title: str, stage: str, value: int, currency: str, probability: int, expected_close_at, owner: str, description: str):
    cursor = conn.execute(
        """
        INSERT INTO crm_deals (
            crm_company_id, crm_contact_id, title, stage, value, currency, probability, expected_close_at, owner, description
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (company_id, None, title, stage, value, currency, probability, expected_close_at, owner, description),
    )
    row_id = int(cursor.lastrowid)
    return conn.execute("SELECT id, crm_company_id, crm_contact_id, title, stage, value, currency, probability, expected_close_at, owner, description FROM crm_deals WHERE id = ?", (row_id,)).fetchone()


def _dedupe_deals_by_id(deals: list[dict]) -> list[dict]:
    seen: set[int] = set()
    deduped: list[dict] = []
    for deal in deals:
        deal_id = deal.get("id")
        if not deal_id or deal_id in seen:
            continue
        seen.add(int(deal_id))
        deduped.append(deal)
    return deduped


def _build_growhub_pipeline_deals(conn, companies) -> list[dict]:
    deals = []
    created_any = False
    for company in companies:
        company_id = int(company["id"])
        company_name = company["name"]

        existing_deals = conn.execute(
            "SELECT id, crm_company_id, crm_contact_id, title, stage, value, currency, probability, expected_close_at, owner, description FROM crm_deals WHERE crm_company_id = ? ORDER BY updated_at DESC, created_at DESC, id DESC",
            (company_id,),
        ).fetchall()
        if existing_deals:
            continue

        company_row = conn.execute(
            "SELECT pipeline_stage, opportunity_score FROM crm_companies WHERE id = ?",
            (company_id,),
        ).fetchone()
        stage = _crm_deal_stage_to_frontend(company_row["pipeline_stage"] if company_row else None)
        probability = int(company_row["opportunity_score"] or 0) if company_row else 0
        fallback_value = 0
        if table_exists(conn, "revenue_pipeline"):
            revenue_row = conn.execute(
                "SELECT estimated_value FROM revenue_pipeline WHERE lower(company) = ? LIMIT 1",
                (company_name.lower(),),
            ).fetchone()
            if revenue_row and revenue_row["estimated_value"] is not None:
                fallback_value = int(float(revenue_row["estimated_value"]) or 0)
        created_row = _create_pipeline_deal_row(
            conn,
            company_id,
            f"{company_name} opportunity",
            stage,
            fallback_value,
            "NGN",
            probability,
            None,
            "MedNovaOS",
            "",
        )
        created_any = True
        deals.append(_crm_deal_payload_from_row(created_row))
    if created_any:
        conn.commit()
    return deals
from backend.sync.scheduler import SyncScheduler
from backend.sync.sync_engine import run_sync
from database.apply_migrations import apply_migrations
from database.init_db import initialize_database

DEFAULT_DB_PATH = BASE_DIR / "database" / "nafdac_intelligence.db"
CANDIDATES = [Path.home() / "MedNova-OS" / "database" / "nafdac_intelligence.db", DEFAULT_DB_PATH]


def db_path() -> Path:
    configured = os.getenv("MEDNOVA_DB_PATH")
    if configured:
        path = Path(configured).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        return path
    for candidate in CANDIDATES:
        if candidate.exists():
            return candidate
    return DEFAULT_DB_PATH


def connect() -> sqlite3.Connection:
    db_file = ensure_database()
    conn = sqlite3.connect(db_file)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    _ensure_contact_enrichment_columns(conn)
    _ensure_outreach_tables(conn)
    _ensure_outreach_columns(conn)
    _ensure_report_tables(conn)
    conn.commit()
    return conn


def table_exists(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def _ensure_contact_enrichment_columns(conn: sqlite3.Connection) -> None:
    columns = {row[1] for row in conn.execute("PRAGMA table_info(crm_contacts)").fetchall()}
    additions = [
        ("source_url", "TEXT"),
        ("discovered_at", "TEXT"),
        ("confidence_score", "REAL"),
        ("verification_status", "TEXT"),
        ("website", "TEXT"),
        ("linkedin_url", "TEXT"),
        ("notes", "TEXT"),
    ]
    for column_name, column_type in additions:
        if column_name not in columns:
            conn.execute(f"ALTER TABLE crm_contacts ADD COLUMN {column_name} {column_type}")


def _ensure_outreach_columns(conn: sqlite3.Connection) -> None:
    columns = {row[1] for row in conn.execute("PRAGMA table_info(crm_outreach_emails)").fetchall()}
    additions = [
        ("template_key", "TEXT"),
        ("template_name", "TEXT"),
        ("recipient_name", "TEXT"),
        ("sender_name", "TEXT"),
        ("sender_email", "TEXT"),
        ("from_email", "TEXT"),
        ("company_name", "TEXT"),
        ("contact_name", "TEXT"),
        ("message_id", "TEXT"),
        ("error_message", "TEXT"),
        ("client_request_id", "TEXT"),
    ]
    for column_name, column_type in additions:
        if column_name not in columns:
            conn.execute(f"ALTER TABLE crm_outreach_emails ADD COLUMN {column_name} {column_type}")


def _normalize_contact_value(value: object) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def _is_placeholder_contact_name(name_value: str, company_name: str = "") -> bool:
    normalized = _normalize_contact_value(name_value).lower()
    if not normalized:
        return True
    generic_names = {"public contact", "primary contact", "contact", "there", "company", "company contact"}
    if normalized in generic_names:
        return True
    if company_name:
        company_label = _normalize_contact_value(company_name).lower()
        if normalized in {f"{company_label} commercial lead", f"{company_label} lead", f"{company_label} contact", f"{company_label} representative"}:
            return True
    return False


def _ensure_outreach_tables(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS crm_outreach_emails (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            crm_company_id INTEGER NOT NULL,
            crm_contact_id INTEGER,
            template_key TEXT,
            template_name TEXT,
            subject TEXT NOT NULL,
            body TEXT NOT NULL,
            recipient TEXT,
            recipient_name TEXT,
            sender_name TEXT,
            sender_email TEXT,
            from_email TEXT,
            company_name TEXT,
            contact_name TEXT,
            status TEXT NOT NULL DEFAULT 'draft',
            direction TEXT NOT NULL DEFAULT 'outbound',
            message_id TEXT,
            error_message TEXT,
            client_request_id TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            sent_at TEXT,
            FOREIGN KEY (crm_company_id) REFERENCES crm_companies(id) ON DELETE CASCADE,
            FOREIGN KEY (crm_contact_id) REFERENCES crm_contacts(id) ON DELETE SET NULL
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_crm_outreach_company ON crm_outreach_emails(crm_company_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_crm_outreach_status ON crm_outreach_emails(status)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_crm_outreach_created ON crm_outreach_emails(created_at)")


def _build_template_catalog() -> list[dict]:
    return [
        {
            "key": "introduction",
            "name": "Introduction",
            "subject": "Introducing MedNovaOS for {{company_name}}",
            "body": "Hello {{contact_name}},\n\nMy name is {{sender_name}} and I lead outreach at MedNovaOS. We work with companies like {{company_name}} to support regulatory strategy, market entry, and commercial readiness across {{country}}.\n\nI would love to share how our team can support {{company_name}} with {{recommended_service}} and discuss whether a short conversation would be valuable this week.\n\nBest regards,\n{{sender_name}}\n{{sender_email}}",
        },
        {
            "key": "regulatory_support",
            "name": "Regulatory Support",
            "subject": "Regulatory support for {{company_name}}",
            "body": "Hello {{contact_name}},\n\nI’m reaching out because {{company_name}} appears to be building momentum in {{country}} and may benefit from targeted regulatory support. MedNovaOS helps companies navigate NAFDAC registration, local regulatory consulting, and market-entry planning.\n\nWe believe {{company_name}} could strengthen its approach around {{recommended_service}} while improving readiness for {{product_name}}.\n\nWould you be open to a short conversation next week?\n\nBest regards,\n{{sender_name}}\n{{sender_email}}",
        },
        {
            "key": "clinical_development",
            "name": "Clinical Development",
            "subject": "Clinical development support for {{company_name}}",
            "body": "Hello {{contact_name}},\n\nMedNovaOS supports biopharma teams with clinical development planning and execution. For companies such as {{company_name}}, we often advise on CRO selection, protocol design, trial monitoring, and operational readiness for {{product_name}}.\n\nOur team can help {{company_name}} shape a more efficient path for {{recommended_service}} across {{country}}.\n\nIf this is relevant, I would be glad to arrange a brief conversation.\n\nBest regards,\n{{sender_name}}\n{{sender_email}}",
        },
        {
            "key": "pharmacovigilance",
            "name": "Pharmacovigilance",
            "subject": "Pharmacovigilance support for {{company_name}}",
            "body": "Hello {{contact_name}},\n\nMedNovaOS offers pharmacovigilance support for growth-stage healthcare companies operating in complex regulatory environments. We help teams with safety monitoring, compliance oversight, and signal detection for products such as {{product_name}}.\n\nWe believe {{company_name}} may benefit from {{recommended_service}} as it plans for broader market expansion in {{country}}.\n\nWould you be open to a conversation about the most practical next step?\n\nBest regards,\n{{sender_name}}\n{{sender_email}}",
        },
        {
            "key": "follow_up",
            "name": "Follow-up",
            "subject": "Following up on {{company_name}}",
            "body": "Hello {{contact_name}},\n\nI wanted to follow up on my earlier note regarding opportunities for {{company_name}} in {{country}}. We have been reviewing {{portfolio_summary}} and believe there may be a practical fit for {{recommended_service}}.\n\nIf it would be helpful, I would be glad to share a brief overview and discuss whether now is a good moment to reconnect.\n\nBest regards,\n{{sender_name}}\n{{sender_email}}",
        },
    ]


def _render_template(template: dict, context: dict) -> tuple[str, str]:
    placeholders = {
        "company_name": context.get("company_name") or "the company",
        "contact_name": context.get("contact_name") or "there",
        "country": context.get("country") or "your market",
        "product_name": context.get("product_name") or "your product",
        "portfolio_summary": context.get("portfolio_summary") or "your portfolio",
        "opportunity_score": context.get("opportunity_score") or "0",
        "website": context.get("website") or "our website",
        "sender_name": context.get("sender_name") or _default_sender_name(),
        "sender_email": context.get("sender_email") or _default_sender_email(),
        "company_problem": context.get("company_problem") or "commercial and regulatory readiness",
        "recommended_service": context.get("recommended_service") or "a tailored engagement",
    }
    subject = template["subject"]
    body = template["body"]
    for placeholder, value in placeholders.items():
        subject = subject.replace(f"{{{{{placeholder}}}}}", str(value))
        body = body.replace(f"{{{{{placeholder}}}}}", str(value))
    return subject, body


def _default_sender_name() -> str:
    return _read_env_value("SENDER_NAME", "ORGANIZATION_NAME", "ORG_NAME", "COMPANY_NAME", default="MedNova Lifesciences")


def _default_sender_email() -> str:
    return _read_env_value("FROM_EMAIL", "RESEND_FROM_EMAIL", "SENDER_EMAIL", default="info@mednovalife.com")


def _default_from_email() -> str:
    return _default_sender_email()


def _outreach_status_payload() -> dict:
    environment_state = _load_environment()
    sender_email = environment_state["senderEmail"]
    sender_name = environment_state["senderName"]
    sender_domain = sender_email.split("@", 1)[1].lower() if "@" in sender_email else ""
    configured_domain = (os.getenv("SENDER_DOMAIN") or os.getenv("MAIL_DOMAIN") or "mednovalife.com").strip().lower()
    resend_configured = bool((os.getenv("RESEND_API_KEY") or "").strip()) and bool(sender_email) and (sender_domain == configured_domain or sender_domain.endswith(f".{configured_domain}") or configured_domain in {"", "mednovalife.com"})
    return {
        "resendConfigured": resend_configured,
        "senderConfigured": bool(sender_email),
        "senderEmail": sender_email,
        "senderName": sender_name,
        "environmentLoaded": environment_state["dotenvLoaded"],
        "dotenvPath": environment_state["dotenvPath"],
        "diagnostics": {
            "resendApiKeyConfigured": environment_state["resendApiKeyConfigured"],
            "senderEmailConfigured": environment_state["senderEmailConfigured"],
            "senderNameConfigured": environment_state["senderNameConfigured"],
        },
    }


def _build_outreach_preview(conn: sqlite3.Connection, company_id: int, template_key: str, contact_ids: list[int] | None = None, sender_name: str = "", sender_email: str = "", recipient: str = "", recipient_name: str = "", contact_id: int | None = None) -> dict:
    templates = _build_template_catalog()
    template = next((entry for entry in templates if entry["key"] == (template_key or "introduction")), templates[0])
    context = _extract_outreach_context(conn, company_id, contact_ids, sender_name or _default_sender_name(), sender_email or _default_sender_email())
    primary_contact = context.get("primary_contact")
    company_name = _normalize_contact_value(context.get("company_name") or "Company")

    def _candidate_name(contact: sqlite3.Row | dict | None) -> str:
        if isinstance(contact, sqlite3.Row):
            return _normalize_contact_value(contact["full_name"] or "")
        if isinstance(contact, dict):
            return _normalize_contact_value(contact.get("full_name") or "")
        return ""

    if isinstance(primary_contact, sqlite3.Row):
        resolved_name = _normalize_contact_value(recipient_name or primary_contact["full_name"] or "")
        resolved_email = (recipient or primary_contact["email"] or "").strip()
    elif isinstance(primary_contact, dict):
        resolved_name = _normalize_contact_value(recipient_name or primary_contact.get("full_name") or "")
        resolved_email = (recipient or primary_contact.get("email") or "").strip()
    else:
        resolved_name = _normalize_contact_value(recipient_name or "")
        resolved_email = (recipient or "").strip()

    if _is_placeholder_contact_name(resolved_name, company_name):
        resolved_name = ""

    if not resolved_email and context.get("contacts"):
        for contact in context.get("contacts") or []:
            if isinstance(contact, sqlite3.Row):
                email = (contact["email"] or "").strip()
            elif isinstance(contact, dict):
                email = (contact.get("email") or "").strip()
            else:
                email = ""
            if email:
                resolved_email = email
                if not resolved_name:
                    candidate_name = _candidate_name(contact)
                    if not _is_placeholder_contact_name(candidate_name, company_name):
                        resolved_name = candidate_name
                break

    if _is_placeholder_contact_name(resolved_name, company_name):
        resolved_name = ""

    if not resolved_name:
        resolved_name = company_name

    contact_name = resolved_name or "there"
    sender_name_value = (sender_name or context.get("sender_name") or _default_sender_name()).strip() or _default_sender_name()
    sender_email_value = (sender_email or context.get("sender_email") or _default_sender_email()).strip() or _default_sender_email()
    subject, body = _render_template(template, {
        **context,
        "contact_name": contact_name,
        "sender_name": sender_name_value,
        "sender_email": sender_email_value,
    })
    warning_message = None
    if not resolved_email:
        warning_message = "No contacts are available for this company yet. Add a contact to prefill the recipient."
    return {
        "subject": subject,
        "body": body,
        "template": template["name"],
        "recipient": resolved_email,
        "recipient_name": resolved_name,
        "sender_name": sender_name_value,
        "sender_email": sender_email_value,
        "contact_id": contact_id,
        "warning_message": warning_message,
    }


def _append_signature(body: str, sender_name: str, sender_email: str) -> str:
    stripped = (body or "").strip()
    if not stripped:
        stripped = "Hello,"
    if "Regards," in stripped or "Best regards," in stripped:
        return stripped
    sender_label = (sender_name or "MedNova Lifesciences").strip() or "MedNova Lifesciences"
    sender_address = (sender_email or _default_sender_email()).strip() or "info@mednovalife.com"
    return (
        f"{stripped}\n\nRegards,\n\nMedNova Lifesciences\n{sender_label}\nBusiness Development Team\n{sender_address}\nhttps://mednovalife.com"
    )


def _resolve_outreach_persist_details(conn: sqlite3.Connection, company_id: int, company_name: str, payload: dict, template_key: str | None = None, sender_name: str = "", sender_email: str = "") -> dict:
    payload = dict(payload or {})
    contact_id = payload.get("contact_id")
    if contact_id is not None and str(contact_id).strip():
        contact_id = int(contact_id)
    else:
        contact_id = None

    contact_ids = [contact_id] if contact_id is not None else []
    subject = (payload.get("subject") or "").strip()
    body = (payload.get("body") or "").strip()
    recipient = (payload.get("recipient") or "").strip()
    recipient_name = (payload.get("recipient_name") or "").strip()
    request_id = (payload.get("request_id") or payload.get("client_request_id") or "").strip()

    preview_data = _build_outreach_preview(
        conn,
        company_id,
        payload.get("template_key") or template_key or "introduction",
        contact_ids,
        (payload.get("sender_name") or sender_name or _default_sender_name()).strip(),
        (payload.get("sender_email") or sender_email or _default_sender_email()).strip(),
        recipient,
        recipient_name,
        contact_id,
    )

    resolved_subject = subject or preview_data.get("subject") or "Draft email"
    resolved_body = body or preview_data.get("body") or ""
    resolved_recipient = recipient or preview_data.get("recipient") or ""
    resolved_recipient_name = recipient_name or preview_data.get("recipient_name") or ""
    resolved_contact_name = (payload.get("contact_name") or resolved_recipient_name or "").strip()
    resolved_company_name = (payload.get("company_name") or company_name or "").strip() or company_name or ""

    if not resolved_subject:
        resolved_subject = "Draft email"
    if not resolved_body:
        resolved_body = preview_data.get("body") or ""

    return {
        "contact_id": contact_id,
        "template_key": payload.get("template_key") or template_key or "introduction",
        "template_name": payload.get("template_name") or preview_data.get("template") or (payload.get("template_key") or template_key or "introduction"),
        "subject": resolved_subject,
        "body": resolved_body,
        "recipient": resolved_recipient,
        "recipient_name": resolved_recipient_name,
        "contact_name": resolved_contact_name or resolved_recipient_name,
        "company_name": resolved_company_name,
        "sender_name": (payload.get("sender_name") or sender_name or preview_data.get("sender_name") or _default_sender_name()).strip(),
        "sender_email": (payload.get("sender_email") or sender_email or preview_data.get("sender_email") or _default_sender_email()).strip(),
        "request_id": request_id,
        "preview_data": preview_data,
    }


def _send_via_resend(subject: str, body: str, recipient: str, from_email: str, sender_name: str, sender_email: str) -> tuple[bool, str | None, str | None]:
    api_key = (os.getenv("RESEND_API_KEY") or "").strip()
    from_email = (from_email or _default_from_email()).strip()
    if not EMAIL_RE.fullmatch(recipient or ""):
        return False, None, "A valid recipient email is required."

    if not from_email:
        return False, None, "Missing FROM_EMAIL."

    if not api_key:
        if os.getenv("FLASK_ENV", "").lower() == "production" or os.getenv("MEDNOVA_ENV", "").lower() == "production":
            return False, None, "Missing RESEND_API_KEY."
        return True, f"local-dev-{uuid.uuid4().hex[:8]}", None

    try:
        response = requests.post(
            "https://api.resend.com/emails",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "from": from_email,
                "to": [recipient],
                "subject": subject,
                "text": body,
                "html": f"<p>{body.replace(chr(10), '<br/>')}</p>",
            },
            timeout=20,
        )
        if response.status_code >= 400:
            payload = {}
            try:
                payload = response.json()
            except Exception:
                payload = {}
            detail = (payload.get("message") or payload.get("error") or "").strip()
            if response.status_code in {401, 403}:
                return False, None, f"Resend rejected the request ({response.status_code}). {detail or 'Check the RESEND_API_KEY and sender domain configuration.'}".strip()
            if detail:
                return False, None, f"Resend request failed ({response.status_code}): {detail}"
            return False, None, f"Resend request failed with status {response.status_code}."

        response.raise_for_status()
        payload = {}
        try:
            payload = response.json()
        except Exception:
            payload = {}
        message_id = payload.get("id") or payload.get("message_id")
        return True, str(message_id) if message_id else None, None
    except requests.RequestException as exc:
        response = getattr(exc, "response", None)
        payload = {}
        if response is not None:
            try:
                payload = response.json() if hasattr(response, "json") else {}
            except Exception:
                payload = {}
        detail = (payload.get("message") or payload.get("error") or "").strip()
        message = str(exc)
        if not message:
            message = "Resend request failed."
        status_code = getattr(response, "status_code", None)
        if status_code is None:
            status_match = re.search(r"\b(4\d{2})\b", message)
            if status_match:
                status_code = int(status_match.group(1))
        if status_code in {401, 403}:
            return False, None, f"Resend rejected the request ({status_code}). {detail or 'Check the RESEND_API_KEY and sender domain configuration.'}".strip()
        if detail:
            return False, None, f"{message} {detail}".strip()
        return False, None, message


def _coerce_request_payload() -> dict:
    if request.is_json:
        payload = request.get_json(silent=True) or {}
        if isinstance(payload, dict):
            return payload
    form_payload = request.form.to_dict(flat=True) or {}
    return {key: (value if value is not None else "") for key, value in form_payload.items()}


def _extract_outreach_context(conn: sqlite3.Connection, company_id: int, contact_ids: list[int] | None = None, sender_name: str = "", sender_email: str = "") -> dict:
    company = conn.execute("SELECT id, company_name, country, opportunity_score, portfolio_summary, report_context FROM crm_companies WHERE id = ?", (company_id,)).fetchone()
    if not company:
        raise LookupError("company not found")

    company_name = company["company_name"] or "Company"
    company_label = (company_name or "company").lower()

    def _contact_value(contact: sqlite3.Row | dict | None, key: str) -> str:
        if not contact:
            return ""
        if isinstance(contact, dict):
            return _normalize_contact_value(contact.get(key) or "")
        return _normalize_contact_value(contact[key] if key in contact.keys() else "")

    def _is_placeholder_contact(contact: sqlite3.Row | dict | None) -> bool:
        if not contact:
            return True
        full_name = _contact_value(contact, "full_name")
        role = _contact_value(contact, "role")
        email = _contact_value(contact, "email")
        phone = _contact_value(contact, "phone")
        if not full_name and not role:
            return True
        if full_name.lower() == f"{company_label} commercial lead" or full_name.lower() == f"{company_label} lead":
            return True
        if role.lower() in {"commercial lead", "lead"} and not (email or phone):
            return True
        return False

    contacts = conn.execute("SELECT id, full_name, email, role FROM crm_contacts WHERE crm_company_id = ? ORDER BY created_at DESC", (company_id,)).fetchall()

    primary_contact = None
    if contact_ids:
        requested_contacts = []
        for contact_id in contact_ids:
            contact = conn.execute("SELECT id, full_name, email, role FROM crm_contacts WHERE crm_company_id = ? AND id = ? LIMIT 1", (company_id, contact_id)).fetchone()
            if contact:
                requested_contacts.append(contact)
        for contact in requested_contacts:
            if not _is_placeholder_contact(contact):
                primary_contact = contact
                break

    if primary_contact is None:
        for contact in contacts:
            if _is_placeholder_contact(contact):
                continue
            if contact["email"]:
                primary_contact = contact
                break
            if not primary_contact:
                primary_contact = contact

    if primary_contact is None:
        primary_contact = contacts[0] if contacts else {
            "full_name": f"{company_name} Commercial Lead",
            "email": "",
            "role": "Commercial Lead",
        }
    country = company["country"] or "Unknown"
    portfolio_summary = company["portfolio_summary"] or ""
    opportunity_score = company["opportunity_score"] or 0
    product_name = "your lead product"
    if company["report_context"]:
        try:
            parsed = json.loads(company["report_context"] or "[]")
            if isinstance(parsed, list) and parsed:
                first_item = parsed[0]
                if isinstance(first_item, dict):
                    product_name = first_item.get("product_name") or first_item.get("name") or product_name
        except (TypeError, ValueError):
            product_name = product_name

    return {
        "company_name": company_name,
        "country": country,
        "portfolio_summary": portfolio_summary,
        "opportunity_score": str(opportunity_score),
        "product_name": product_name,
        "website": "",
        "company_problem": "commercial and regulatory readiness",
        "recommended_service": "targeted regulatory and commercial support",
        "sender_name": sender_name or "MedNovaOS",
        "sender_email": sender_email or _default_sender_email(),
        "contacts": contacts,
        "primary_contact": primary_contact,
    }


def _extract_contact_details_from_html(url: str, html: str, company_name: str) -> dict:
    soup = BeautifulSoup(html or "", "html.parser")
    text = " ".join(soup.stripped_strings)
    emails = [match.group(0) for match in EMAIL_RE.finditer(text)]
    phones = []
    for match in PHONE_RE.findall(text):
        cleaned = re.sub(r"\s+", "", match)
        if len(cleaned) >= 7:
            phones.append(cleaned)
    linkedin_matches = LINKEDIN_RE.findall(text)
    linkedin_url = linkedin_matches[0] if linkedin_matches else ""

    title = ""
    for tag in soup.find_all(["h1", "h2", "h3", "p", "li"]):
        candidate = _normalize_contact_value(" ".join(tag.stripped_strings))
        if not candidate:
            continue
        lowered = candidate.lower()
        if any(token in lowered for token in ["ceo", "cto", "cfo", "founder", "president", "director", "manager", "head", "partner", "principal", "lead"]):
            title = candidate
            break

    name = ""
    for tag in soup.find_all(["h1", "h2", "h3"]):
        candidate = _normalize_contact_value(" ".join(tag.stripped_strings))
        if not candidate or candidate.lower() in {"contact", "about", "leadership", "team", "management", company_name.lower()}:
            continue
        name = candidate
        break

    return {
        "name": name or "Public Contact",
        "role": title or "Public contact",
        "email": emails[0] if emails else "",
        "phone": phones[0] if phones else "",
        "linkedin_url": linkedin_url,
        "website": url,
        "source_url": url,
        "confidence_score": 0.6 if emails or phones or linkedin_url else 0.3,
        "verification_status": "verified" if (emails or phones or linkedin_url) else "pending",
    }


def _prune_placeholder_contacts(conn: sqlite3.Connection, company_id: int) -> None:
    placeholders = conn.execute(
        """
        SELECT id FROM crm_contacts
        WHERE crm_company_id = ? AND source != 'discovered' AND COALESCE(email, '') = '' AND COALESCE(phone, '') = '' AND COALESCE(linkedin_url, '') = ''
        ORDER BY created_at DESC
        """,
        (company_id,),
    ).fetchall()
    if not placeholders:
        return

    discovered_contacts = conn.execute(
        "SELECT id FROM crm_contacts WHERE crm_company_id = ? AND source = 'discovered'",
        (company_id,),
    ).fetchall()
    if not discovered_contacts:
        return

    placeholder_ids = [row["id"] for row in placeholders]
    conn.execute(
        "DELETE FROM crm_contacts WHERE id IN ({})".format(", ".join("?" for _ in placeholder_ids)),
        placeholder_ids,
    )


def _upsert_discovered_contact(conn: sqlite3.Connection, company_id: int, contact_data: dict) -> tuple[int, bool, bool, bool]:
    full_name = _normalize_contact_value(contact_data.get("name") or contact_data.get("full_name") or "Public Contact")
    role = _normalize_contact_value(contact_data.get("role") or contact_data.get("position") or "Public contact")
    email = _normalize_contact_value(contact_data.get("email") or "")
    phone = _normalize_contact_value(contact_data.get("phone") or "")
    linkedin_url = _normalize_contact_value(contact_data.get("linkedin_url") or contact_data.get("linkedin") or "")
    website = _normalize_contact_value(contact_data.get("website") or "")
    source_url = _normalize_contact_value(contact_data.get("source_url") or "")
    confidence_score = float(contact_data.get("confidence_score") or 0.0)
    verification_status = _normalize_contact_value(contact_data.get("verification_status") or "pending")

    if not full_name and not email and not phone and not linkedin_url:
        return 0, False, False, False

    existing = None
    if email or phone or linkedin_url:
        existing = conn.execute(
            """
            SELECT id, source FROM crm_contacts
            WHERE crm_company_id = ? AND (
                (email IS NOT NULL AND email != '' AND email = ?) OR
                (phone IS NOT NULL AND phone != '' AND phone = ?) OR
                (linkedin_url IS NOT NULL AND linkedin_url != '' AND linkedin_url = ?)
            )
            LIMIT 1
            """,
            (company_id, email, phone, linkedin_url),
        ).fetchone()

    if existing:
        return int(existing["id"]), False, False, True

    cursor = conn.execute(
        """
        INSERT INTO crm_contacts (
            crm_company_id, full_name, role, department, email, phone, source, source_url, discovered_at,
            confidence_score, verification_status, website, linkedin_url, notes
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            company_id,
            full_name,
            role,
            contact_data.get("department") or "Business Development",
            email,
            phone,
            "discovered",
            source_url,
            datetime.utcnow().isoformat(),
            confidence_score,
            verification_status,
            website,
            linkedin_url,
            contact_data.get("notes") or "",
        ),
    )
    return int(cursor.lastrowid), True, False, False


def _discover_contacts_for_company(conn: sqlite3.Connection, company_id: int, company_name: str) -> tuple[list[dict], int, int, int]:
    api_key = (os.getenv("TAVILY_API_KEY") or "").strip()
    if not api_key:
        raise RuntimeError("TAVILY_API_KEY is not configured")

    headers = {"Authorization": f"Bearer {api_key}"}

    search_queries = [
        f'"{company_name}" contact',
        f'"{company_name}" leadership',
        f'"{company_name}" email',
    ]

    discovered_profiles: list[dict] = []
    seen_urls: set[str] = set()
    for query in search_queries:
        response = requests.post(
            "https://api.tavily.com/search",
            json={"query": query, "search_depth": "basic", "max_results": 3, "include_answer": False},
            timeout=8,
            headers=headers,
        )
        response.raise_for_status()
        payload = response.json() or {}
        for result in payload.get("results") or []:
            page_url = _normalize_contact_value(result.get("url") or "")
            if not page_url or page_url in seen_urls:
                continue
            seen_urls.add(page_url)
            try:
                page_response = requests.get(page_url, timeout=4, headers={"User-Agent": "Mozilla/5.0"})
                page_response.raise_for_status()
            except Exception:
                continue

            profile = _extract_contact_details_from_html(page_url, page_response.text, company_name)
            if profile.get("email") or profile.get("phone") or profile.get("linkedin_url"):
                discovered_profiles.append(profile)

    imported_count = 0
    updated_count = 0
    duplicates_skipped = 0
    for profile in discovered_profiles:
        contact_id, created, updated, duplicate = _upsert_discovered_contact(conn, company_id, profile)
        if created:
            imported_count += 1
        elif updated:
            updated_count += 1
        elif duplicate:
            duplicates_skipped += 1

    if imported_count or updated_count or duplicates_skipped:
        _prune_placeholder_contacts(conn, company_id)

    return discovered_profiles, imported_count, updated_count, duplicates_skipped


def scalar(conn: sqlite3.Connection, sql: str, params=()) -> int:
    row = conn.execute(sql, params).fetchone()
    return int(row[0] or 0) if row else 0


def ensure_crm_tables() -> None:
    apply_migrations(db_path())


def _ensure_report_tables(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS crm_reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            crm_company_id INTEGER,
            report_type TEXT NOT NULL,
            report_name TEXT NOT NULL,
            version TEXT NOT NULL DEFAULT '1.0',
            generated_by TEXT NOT NULL DEFAULT 'MedNovaOS',
            generated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            report_data TEXT NOT NULL,
            executive_summary TEXT,
            status TEXT NOT NULL DEFAULT 'generated',
            metadata TEXT,
            FOREIGN KEY (crm_company_id) REFERENCES crm_companies(id) ON DELETE CASCADE
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_crm_reports_company ON crm_reports(crm_company_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_crm_reports_type ON crm_reports(report_type)")


def _report_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _report_scorecard(company: dict, deal: dict | None, tasks: list[dict], emails: list[dict]) -> dict:
    commercial_fit = min(100, max(40, (company.get("opportunity_score") or 0) + 10 + len(tasks) * 3))
    strategic_importance = min(100, max(35, 55 + (1 if company.get("portfolio_summary") else 0) * 10 + len(emails) * 2))
    normalized_deal = deal if isinstance(deal, dict) else None
    probability_value = 0
    if normalized_deal is not None:
        probability_value = normalized_deal.get("probability") or normalized_deal.get("probability_score") or company.get("opportunity_score") or 0
    else:
        probability_value = company.get("opportunity_score") or 0
    probability = min(100, max(10, int(probability_value)))
    urgency = min(100, max(25, 45 + (1 if tasks else 0) * 15))
    relationship_strength = min(100, max(30, 50 + len(emails) * 5))
    decision_readiness = min(100, max(20, 40 + (1 if deal else 0) * 20 + (1 if tasks else 0) * 10))
    return {
        "commercial_fit": commercial_fit,
        "strategic_importance": strategic_importance,
        "probability": probability,
        "urgency": urgency,
        "relationship_strength": relationship_strength,
        "decision_readiness": decision_readiness,
    }


def _ensure_company_intelligence_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS crm_company_intelligence (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            crm_company_id INTEGER NOT NULL UNIQUE,
            intelligence_data TEXT NOT NULL,
            last_refreshed_at TEXT,
            refresh_status TEXT NOT NULL DEFAULT 'ready',
            source_summary TEXT,
            search_results_json TEXT,
            search_date TEXT,
            last_refresh TEXT,
            search_status TEXT,
            FOREIGN KEY (crm_company_id) REFERENCES crm_companies(id) ON DELETE CASCADE
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_company_intelligence_company ON crm_company_intelligence(crm_company_id)")
    columns = {row[1] for row in conn.execute("PRAGMA table_info(crm_company_intelligence)").fetchall()}
    for column_name, column_type in [("search_results_json", "TEXT"), ("search_date", "TEXT"), ("last_refresh", "TEXT"), ("search_status", "TEXT")]:
        if column_name not in columns:
            conn.execute(f"ALTER TABLE crm_company_intelligence ADD COLUMN {column_name} {column_type}")


def _load_company_intelligence(conn: sqlite3.Connection, company_id: int) -> dict | None:
    _ensure_company_intelligence_table(conn)
    row = conn.execute("SELECT id, crm_company_id, intelligence_data, last_refreshed_at, refresh_status, source_summary, search_results_json, search_date, last_refresh, search_status FROM crm_company_intelligence WHERE crm_company_id = ?", (company_id,)).fetchone()
    if not row:
        return None
    return {
        "id": int(row["id"]),
        "crm_company_id": int(row["crm_company_id"]),
        "intelligence_data": json.loads(row["intelligence_data"] or "{}"),
        "last_refreshed_at": row["last_refreshed_at"],
        "refresh_status": row["refresh_status"],
        "source_summary": row["source_summary"],
        "search_results_json": row["search_results_json"],
        "search_date": row["search_date"],
        "last_refresh": row["last_refresh"],
        "search_status": row["search_status"],
    }


def _save_company_intelligence(conn: sqlite3.Connection, company_id: int, intelligence_data: dict, source_summary: str | None = None, search_results_json: str | None = None, search_date: str | None = None, last_refresh: str | None = None, search_status: str | None = None) -> dict:
    _ensure_company_intelligence_table(conn)
    timestamp = _report_timestamp()
    existing = conn.execute("SELECT id FROM crm_company_intelligence WHERE crm_company_id = ?", (company_id,)).fetchone()
    if existing:
        conn.execute(
            "UPDATE crm_company_intelligence SET intelligence_data = ?, last_refreshed_at = ?, refresh_status = ?, source_summary = ?, search_results_json = ?, search_date = ?, last_refresh = ?, search_status = ? WHERE crm_company_id = ?",
            (json.dumps(intelligence_data), timestamp, "ready", source_summary or "cached", search_results_json, search_date, last_refresh, search_status or "ready", company_id),
        )
        record_id = int(existing["id"])
    else:
        cursor = conn.execute(
            "INSERT INTO crm_company_intelligence (crm_company_id, intelligence_data, last_refreshed_at, refresh_status, source_summary, search_results_json, search_date, last_refresh, search_status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (company_id, json.dumps(intelligence_data), timestamp, "ready", source_summary or "cached", search_results_json, search_date, last_refresh, search_status or "ready"),
        )
        record_id = int(cursor.lastrowid)
    row = conn.execute("SELECT id, crm_company_id, intelligence_data, last_refreshed_at, refresh_status, source_summary, search_results_json, search_date, last_refresh, search_status FROM crm_company_intelligence WHERE id = ?", (record_id,)).fetchone()
    return {
        "id": int(row["id"]),
        "crm_company_id": int(row["crm_company_id"]),
        "intelligence_data": json.loads(row["intelligence_data"] or "{}"),
        "last_refreshed_at": row["last_refreshed_at"],
        "refresh_status": row["refresh_status"],
        "source_summary": row["source_summary"],
        "search_results_json": row["search_results_json"],
        "search_date": row["search_date"],
        "last_refresh": row["last_refresh"],
        "search_status": row["search_status"],
    }


def _should_refresh_company_intelligence(last_refreshed_at: str | None, force: bool = False) -> bool:
    if force:
        return True
    if not last_refreshed_at:
        return True
    try:
        refreshed = datetime.fromisoformat(last_refreshed_at.replace("Z", "+00:00"))
    except ValueError:
        return True
    return (datetime.now(timezone.utc) - refreshed).days >= 7


def _fetch_text(url: str) -> str | None:
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"}
        response = requests.get(url, timeout=8, headers=headers)
        if response.ok:
            return response.text
    except requests.RequestException:
        return None
    return None


def _call_tavily_search(company_name: str, website: str | None = None) -> dict:
    api_key = (os.getenv("TAVILY_API_KEY") or "").strip()
    if not api_key:
        return {"error": "TAVILY_API_KEY is not configured", "results": []}

    query = company_name
    if website:
        query = f'"{company_name}" {website}'
    payload = {
        "query": query,
        "search_depth": "advanced",
        "max_results": 10,
        "include_answer": True,
        "include_raw_content": True,
        "include_images": False,
        "include_domains": [],
    }
    try:
        response = requests.post(
            "https://api.tavily.com/search",
            json=payload,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=20,
        )
        response.raise_for_status()
        data = response.json() or {}
        return {"results": data.get("results") or [], "answer": data.get("answer") or "", "query": payload["query"]}
    except requests.RequestException as exc:
        return {"error": str(exc), "results": []}


def _extract_named_entities(text: str, company_name: str) -> list[str]:
    tokens = []
    low = text.lower()
    if "regulatory" in low or "regulation" in low:
        tokens.append("Regulatory Affairs")
    if "quality" in low or "gmp" in low or "iso" in low:
        tokens.append("Quality Systems")
    if "clinical" in low or "trial" in low:
        tokens.append("Clinical Operations")
    if "manufactur" in low:
        tokens.append("Manufacturing Support")
    if "data" in low or "digital" in low:
        tokens.append("Digital Transformation")
    if "medical" in low or "medical writing" in low:
        tokens.append("Medical Writing")
    if "pharmacovigilance" in low or "safety" in low:
        tokens.append("Pharmacovigilance")
    if company_name.lower() in low and "launch" in low:
        tokens.append("Launch Readiness")
    return list(dict.fromkeys(tokens))


def _ensure_tavily_cache_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS tavily_search_cache (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id INTEGER,
            search_query TEXT NOT NULL,
            search_results_json TEXT NOT NULL,
            search_date TEXT NOT NULL,
            last_refreshed_at TEXT NOT NULL,
            ttl_days INTEGER DEFAULT 7,
            FOREIGN KEY (company_id) REFERENCES crm_companies(id) ON DELETE CASCADE,
            UNIQUE(company_id, search_query)
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tavily_cache_company ON tavily_search_cache(company_id)")


def _get_tavily_api_key() -> str:
    return _read_env_value("TAVILY_API_KEY", "TAVILY_KEY", default="").strip()


def _search_tavily(query: str) -> dict | None:
    api_key = _get_tavily_api_key()
    if not api_key:
        return None
    try:
        payload = {
            "api_key": api_key,
            "query": query,
            "search_depth": "advanced",
            "max_results": 10,
            "include_answer": True,
            "include_raw_content": True,
            "include_images": False,
        }
        response = requests.post("https://api.tavily.com/search", json=payload, timeout=15)
        if response.status_code == 200:
            return response.json()
    except requests.RequestException:
        pass
    return None


def _get_cached_tavily_search(conn: sqlite3.Connection, company_id: int, search_query: str) -> dict | None:
    _ensure_tavily_cache_table(conn)
    row = conn.execute(
        "SELECT id, search_results_json, last_refreshed_at, ttl_days FROM tavily_search_cache WHERE company_id = ? AND search_query = ?",
        (company_id, search_query),
    ).fetchone()
    if not row:
        return None
    try:
        refreshed = datetime.fromisoformat(row["last_refreshed_at"].replace("Z", "+00:00"))
        age_days = (datetime.now(timezone.utc) - refreshed).days
        ttl = row["ttl_days"] or 7
        if age_days < ttl:
            return json.loads(row["search_results_json"] or "{}")
    except ValueError:
        pass
    return None


def _cache_tavily_search(conn: sqlite3.Connection, company_id: int, search_query: str, results: dict, ttl_days: int = 7) -> None:
    _ensure_tavily_cache_table(conn)
    now = _report_timestamp()
    existing = conn.execute(
        "SELECT id FROM tavily_search_cache WHERE company_id = ? AND search_query = ?",
        (company_id, search_query),
    ).fetchone()
    if existing:
        conn.execute(
            "UPDATE tavily_search_cache SET search_results_json = ?, last_refreshed_at = ?, search_date = ? WHERE company_id = ? AND search_query = ?",
            (json.dumps(results), now, now, company_id, search_query),
        )
    else:
        conn.execute(
            "INSERT INTO tavily_search_cache (company_id, search_query, search_results_json, search_date, last_refreshed_at, ttl_days) VALUES (?, ?, ?, ?, ?, ?)",
            (company_id, search_query, json.dumps(results), now, now, ttl_days),
        )
    conn.commit()


def _build_company_search_query(company: dict) -> str:
    name = (company.get("company_name") or "Company").strip()
    website = (company.get("website") or "").strip()
    if website:
        domain = urlparse(website).netloc or website.replace("http://", "").replace("https://", "")
        return f"{name} site:{domain}"
    return name


def _fetch_company_tavily_intelligence(conn: sqlite3.Connection, company_id: int, force_refresh: bool = False) -> dict | None:
    company_row = conn.execute(
        "SELECT id, company_name, country, portfolio_summary, opportunity_score FROM crm_companies WHERE id = ?",
        (company_id,),
    ).fetchone()
    if not company_row:
        return None

    search_query = _build_company_search_query(dict(company_row))
    if not force_refresh:
        cached = _get_cached_tavily_search(conn, company_id, search_query)
        if cached:
            return cached

    results = _search_tavily(search_query)
    if results:
        _cache_tavily_search(conn, company_id, search_query, results)
        return results
    return None


def _parse_tavily_insights(tavily_response: dict | None) -> dict:
    if not tavily_response:
        return {"answer": "", "results": [], "news": [], "source_count": 0}
    return {
        "answer": tavily_response.get("answer", ""),
        "results": tavily_response.get("results", [])[:5],
        "news": [r for r in tavily_response.get("results", []) if "news" in r.get("source", "").lower()][:3],
        "source_count": len(tavily_response.get("results", [])),
    }


def _infer_company_intelligence(conn: sqlite3.Connection, company_id: int, force_refresh: bool = False) -> dict:
    tavily_intel = _fetch_company_tavily_intelligence(conn, company_id, force_refresh=force_refresh)
    tavily_insights = _parse_tavily_insights(tavily_intel)
    company_row = conn.execute("SELECT id, company_name, country, portfolio_summary, opportunity_score, source, pipeline_stage FROM crm_companies WHERE id = ?", (company_id,)).fetchone()
    if not company_row:
        raise LookupError("company not found")

    contacts = conn.execute("SELECT id, full_name, role, email, phone, website FROM crm_contacts WHERE crm_company_id = ? ORDER BY created_at DESC LIMIT 6", (company_id,)).fetchall()
    tasks = conn.execute("SELECT id, title, status, priority, due_date FROM crm_tasks WHERE crm_company_id = ? ORDER BY due_date IS NULL, due_date, created_at DESC LIMIT 10", (company_id,)).fetchall()
    deals = conn.execute("SELECT id, title, stage, value, probability FROM crm_deals WHERE crm_company_id = ? ORDER BY updated_at DESC, created_at DESC LIMIT 8", (company_id,)).fetchall()

    cached = _load_company_intelligence(conn, company_id)
    if not force_refresh and cached and not _should_refresh_company_intelligence(cached.get("last_refreshed_at"), force=False):
        return cached["intelligence_data"]

    company_name = company_row["company_name"] or "Company"
    description = (company_row["portfolio_summary"] or "").strip() or f"{company_name} is an active commercial partner tracked in the CRM."
    country = company_row["country"] or "Unknown"
    website = ""
    for contact in contacts:
        candidate = (contact["website"] if "website" in contact.keys() else "") or ""
        candidate = str(candidate).strip()
        if candidate:
            website = candidate
            break
    raw_site = None
    if website:
        raw_site = _fetch_text(website if website.startswith("http") else f"https://{website}")
    search_results = (tavily_intel or {}).get("results") or []

    site_text = ""
    site_title = ""
    site_meta = ""
    site_headings: list[str] = []
    site_links: list[str] = []
    social_links: list[str] = []
    if raw_site:
        soup = BeautifulSoup(raw_site, "html.parser")
        site_text = " ".join(soup.stripped_strings)
        site_title = (soup.title.get_text(" ", strip=True) if soup.title else "").strip()
        site_meta = (soup.find("meta", attrs={"name": "description"}) or {}).get("content", "") if soup.find("meta", attrs={"name": "description"}) else ""
        site_headings = [heading.get_text(" ", strip=True) for heading in soup.find_all(["h1", "h2", "h3"])[:10] if heading.get_text(" ", strip=True)]
        site_links = [link.get("href", "") for link in soup.find_all("a") if link.get("href")]
        social_links = [link for link in site_links if any(token in link.lower() for token in ["linkedin", "twitter", "facebook", "youtube", "instagram"])]

    profile_text = " ".join([description, site_text, site_title, site_meta, " ".join(site_headings)])
    founded_year = None
    for match in re.finditer(r"\b(19|20)\d{2}\b", profile_text):
        founded_year = int(match.group(0))
        break
    employees = None
    employee_match = re.search(r"(\d{1,3}(?:[.,]\d{3})*(?:\s*\+)?(?:\s*employees?|\s*staff))", profile_text, re.IGNORECASE)
    if employee_match:
        employees = employee_match.group(0)
    quality_hits = [token for token in ["ISO 9001", "ISO 13485", "GMP", "GMP certified", "FDA", "EMA", "WHO"] if token.lower() in profile_text.lower()]
    regulatory_hits = [token for token in ["FDA", "EMA", "WHO", "NDA", "IND", "CE mark", "MRA"] if token.lower() in profile_text.lower()]
    services = _extract_named_entities(profile_text, company_name)
    if not services:
        services = ["Regulatory Affairs", "Quality Systems", "Clinical Operations"]

    company_profile = {
        "name": company_name,
        "country": country,
        "website": website or "",
        "description": description,
        "founded_year": founded_year,
        "headquarters": country,
        "manufacturing_locations": [country] if "manufactur" in profile_text.lower() else [],
        "countries_served": [country] if country else [],
        "employees": employees,
        "therapeutic_areas": [segment.strip() for segment in re.split(r"[,;]", description) if segment.strip()][:4],
        "products": [heading for heading in site_headings[:4] if heading] or ["Commercial services", "Clinical support"],
        "recent_launches": [heading for heading in site_headings if "launch" in heading.lower()][:3],
        "recent_acquisitions": [],
        "funding": [],
        "awards": [phrase for phrase in quality_hits if "award" in phrase.lower()] or [],
        "leadership": [f"{contact['full_name']} ({contact['role']})" for contact in contacts if contact["full_name"]][:4],
        "executive_team": [{"full_name": contact["full_name"], "role": contact["role"], "email": contact["email"], "phone": contact["phone"]} for contact in contacts[:4]],
        "recent_news": [item["title"] for item in search_results[:3]],
        "strategic_initiatives": [heading for heading in site_headings if heading][:4],
        "job_openings": [link for link in site_links if "career" in link.lower()][:3],
        "open_clinical_trials": [],
        "research_activity": [heading for heading in site_headings if "research" in heading.lower()][:3],
        "manufacturing_capability": "manufacturing capability referenced in CRM or site content" if "manufactur" in profile_text.lower() else "No public manufacturing capability signal detected",
        "quality_certifications": quality_hits,
        "regulatory_approvals": regulatory_hits,
        "crm_signals": {
            "opportunity_score": int(company_row["opportunity_score"] or 0),
            "pipeline_stage": company_row["pipeline_stage"] or "Lead",
            "active_tasks": len(tasks),
            "deals": len(deals),
            "source": company_row["source"] or "CRM",
        },
    }

    website_intelligence = {
        "website": website or "",
        "navigation": [heading for heading in site_headings[:6] if heading],
        "trust_indicators": ["HTTPS" if website and website.startswith("https") else "Website available", *[signal for signal in quality_hits if signal]],
        "seo_quality": "strong" if site_title and site_meta else "moderate",
        "accessibility": "good" if site_headings else "needs review",
        "security": "https" if website and website.startswith("https") else "not-verified",
        "performance": "healthy" if not raw_site or len(raw_site) < 200000 else "needs review",
        "professionalism": "high" if site_title and site_meta else "moderate",
        "content_quality": "strong" if len(site_text) > 250 else "moderate",
        "services": services,
        "contact_channels": [channel for channel in ["website", "email" if any(re.search(EMAIL_RE.pattern, site_text) for _ in [0]) else None] if channel],
        "social_links": social_links[:5],
        "blog_activity": [heading for heading in site_headings if "blog" in heading.lower()][:3],
        "latest_updates": [heading for heading in site_headings if heading][:3],
    }

    recommendation_rules = []
    if any(keyword in profile_text.lower() for keyword in ["regulatory", "gmp", "quality", "compliance", "iso"]):
        recommendation_rules.append({"service": "Regulatory Affairs", "score": 92, "reason": "The profile contains clear regulatory, quality, and compliance signals that align with MedNova support needs."})
    if any(keyword in profile_text.lower() for keyword in ["clinical", "trial", "research", "medical"]):
        recommendation_rules.append({"service": "Clinical Operations", "score": 88, "reason": "Clinical and research-focused language suggests demand for execution support and delivery readiness."})
    if any(keyword in profile_text.lower() for keyword in ["manufactur", "production", "facility"]):
        recommendation_rules.append({"service": "Manufacturing Support", "score": 84, "reason": "Manufacturing references indicate a need for operational excellence and supplier coordination support."})
    if any(keyword in profile_text.lower() for keyword in ["pharmacovigilance", "safety"]):
        recommendation_rules.append({"service": "Pharmacovigilance", "score": 81, "reason": "Safety-focused language indicates strong fit for post-market surveillance and compliance support."})
    if not recommendation_rules:
        recommendation_rules.append({"service": "Growth Strategy", "score": 74, "reason": "The company profile suggests a strong cross-functional growth opportunity with room for expansion."})

    intelligence = {
        "company_profile": company_profile,
        "services": services,
        "tavily_insights": tavily_insights,
        "public_sources": {
            "website": website or "",
            "search_results": search_results[:5],
            "news_mentions": search_results[:3],
            "linkedin_profile": None,
            "press_releases": [],
            "regulatory_announcements": [],
            "source_count": 1 + len(search_results),
        },
        "website_analysis": website_intelligence,
        "business_opportunity": {
            "recommended_services": recommendation_rules,
            "priority_score": max(60, min(99, int(company_row["opportunity_score"] or 0) + 8 + len(recommendation_rules) * 3)),
            "explanation": "The service mix is derived from CRM opportunity signals, website signals, and deterministic keyword-based fit rules.",
        },
        "generated_at": _report_timestamp(),
        "refresh_status": "ready",
        "cache_ttl_days": 7,
    }

    _save_company_intelligence(conn, company_id, intelligence, f"website={bool(website)};search={len(search_results)}")
    return intelligence


def _build_company_report_payload(conn: sqlite3.Connection, company_id: int) -> dict:
    company = conn.execute("SELECT id, company_name, country, opportunity_score, portfolio_summary, source, report_context, greenbook_products_json, pipeline_stage FROM crm_companies WHERE id = ?", (company_id,)).fetchone()
    if not company:
        raise LookupError("company not found")

    products = []
    if company["greenbook_products_json"]:
        try:
            products = json.loads(company["greenbook_products_json"] or "[]")
        except (TypeError, ValueError):
            products = []

    contacts = conn.execute(
        "SELECT id, full_name, role, department, email, phone, website, linkedin_url, notes FROM crm_contacts WHERE crm_company_id = ? ORDER BY created_at DESC",
        (company_id,),
    ).fetchall()
    activities = conn.execute(
        "SELECT activity_type, title, body, created_at FROM crm_activities WHERE crm_company_id = ? ORDER BY created_at DESC",
        (company_id,),
    ).fetchall()
    tasks = conn.execute(
        "SELECT id, title, description, task_type, status, priority, due_date, assigned_to, completed_at, created_at FROM crm_tasks WHERE crm_company_id = ? ORDER BY due_date IS NULL, due_date, created_at DESC",
        (company_id,),
    ).fetchall()
    notes = conn.execute("SELECT body, created_at FROM crm_notes WHERE crm_company_id = ? ORDER BY created_at DESC", (company_id,)).fetchall()
    deals = conn.execute(
        "SELECT id, title, stage, value, currency, probability, expected_close_at, owner, description FROM crm_deals WHERE crm_company_id = ? ORDER BY updated_at DESC, created_at DESC, id DESC",
        (company_id,),
    ).fetchall()
    emails = conn.execute(
        "SELECT subject, status, created_at FROM crm_outreach_emails WHERE crm_company_id = ? ORDER BY created_at DESC",
        (company_id,),
    ).fetchall()

    active_tasks = [dict(task) for task in tasks if (task["status"] or "pending") != "completed"]
    completed_tasks = [dict(task) for task in tasks if (task["status"] or "pending") == "completed"]
    primary_deal = dict(deals[0]) if deals else None
    scorecard = _report_scorecard({
        "name": company["company_name"],
        "opportunity_score": int(company["opportunity_score"] or 0),
        "portfolio_summary": company["portfolio_summary"] or "",
    }, primary_deal, active_tasks, [dict(email) for email in emails])

    intelligence = _infer_company_intelligence(conn, company_id, force_refresh=False)

    recommended_services = intelligence.get("business_opportunity", {}).get("recommended_services", [])
    priority_score = intelligence.get("business_opportunity", {}).get("priority_score", 70)

    report = {
        "report_type": "company",
        "company_id": int(company_id),
        "company_name": company["company_name"],
        "generated_at": _report_timestamp(),
        "summary": {
            "country": company["country"] or "Unknown",
            "industry": "Biopharma",
            "portfolio_summary": company["portfolio_summary"] or "",
            "pipeline_stage": company["pipeline_stage"] or "Lead",
            "opportunity_score": int(company["opportunity_score"] or 0),
            "product_count": len(products),
            "active_task_count": len(active_tasks),
            "completed_task_count": len(completed_tasks),
            "email_count": len(emails),
            "deal_value": int(primary_deal["value"] or 0) if primary_deal else 0,
        },
        "company_profile": {
            "name": company["company_name"],
            "country": company["country"] or "Unknown",
            "industry": "Biopharma",
            "website": "",
            "company_description": company["portfolio_summary"] or "",
            "greenbook_information": products[:5],
            "contacts": [dict(contact) for contact in contacts],
            "company_size": "Large" if len(products) >= 8 else "Medium" if len(products) >= 3 else "Small",
        },
        "crm_information": {
            "pipeline_stage": company["pipeline_stage"] or "Lead",
            "deal_value": int(primary_deal["value"] or 0) if primary_deal else 0,
            "owner": primary_deal["owner"] if primary_deal else "MedNovaOS",
            "tasks": [dict(task) for task in tasks],
            "completed_tasks": completed_tasks,
            "outstanding_tasks": active_tasks,
            "notes": [dict(note) for note in notes],
            "timeline": [dict(activity) for activity in activities],
            "emails": [dict(email) for email in emails],
            "last_outreach": [dict(email) for email in emails][:1],
            "next_action": active_tasks[0]["title"] if active_tasks else "Schedule follow-up",
            "probability": int(primary_deal["probability"] or company["opportunity_score"] or 0) if primary_deal else int(company["opportunity_score"] or 0),
        },
        "commercial_assessment": {
            "why_important": f"{company['company_name']} represents a high-value opportunity for targeted service expansion in the pharmaceutical and regulatory ecosystem.",
            "commercial_opportunity": "The company is positioned to benefit from regulatory, pharmacovigilance, medical writing, and medical information support.",
            "strategic_fit": "The profile aligns with MedNovaOS capabilities in lifecycle management, compliance, and cross-functional execution.",
            "estimated_value": int(primary_deal["value"] or company["opportunity_score"] * 10000) if primary_deal else int(company["opportunity_score"] * 10000),
            "growth_potential": "The account has measurable room for additional services as readiness, execution, and lifecycle needs expand.",
        },
        "service_opportunities": [
            {"service": "Regulatory Affairs", "why": "Supports registration and lifecycle needs."},
            {"service": "Pharmacovigilance", "why": "Addresses surveillance and post-market readiness."},
            {"service": "Medical Writing", "why": "Supports documentation and dossier quality."},
            {"service": "Training", "why": "Improves internal readiness and compliance capability."},
        ],
        "risk_analysis": {
            "potential_risks": ["Timeline pressure", "Stakeholder fragmentation"],
            "regulatory_challenges": ["Documentation readiness"],
            "competition": ["Existing service providers"],
            "engagement_risks": ["Delayed decision-making"],
            "operational_risks": ["Resource allocation constraints"],
        },
        "executive_recommendations": [
            {"priority": "HIGH PRIORITY", "recommendation": "Advance a fast-track engagement plan with executive sponsorship."},
            {"priority": "MEDIUM PRIORITY", "recommendation": "Formalize a cross-functional service roadmap within 30 days."},
        ],
        "action_plan": {
            "week_1": ["Confirm executive sponsor and priorities"],
            "week_2": ["Prepare workplan and sequencing"],
            "month_1": ["Launch initial delivery sprint"],
            "quarter_1": ["Expand into recurring support services"],
        },
        "scorecard": scorecard,
        "executive_summary": f"{company['company_name']} presents a credible growth opportunity supported by clear pipeline momentum and a strong service-fit profile, with public intelligence indicating focused commercial and regulatory priorities.",
        "company_overview": {
            "company_profile": intelligence.get("company_profile", {}),
            "industry_position": "Commercially relevant growth account with measurable expansion potential and public signals of operational maturity.",
            "recent_news": intelligence.get("company_profile", {}).get("recent_news", []),
            "strategic_developments": intelligence.get("company_profile", {}).get("strategic_initiatives", []),
        },
        "website_analysis": intelligence.get("website_analysis", {}),
        "tavily_insights": intelligence.get("tavily_insights", {}),
        "commercial_opportunity": {
            "priority_score": priority_score,
            "recommended_services": recommended_services,
            "rationale": intelligence.get("business_opportunity", {}).get("explanation", "Deterministic service recommendations derived from structured signals."),
        },
        "risk_assessment": {
            "risks": ["Execution timing", "Stakeholder fragmentation", "Infrastructure readiness"],
            "mitigations": ["Executive sponsorship", "Phase-based delivery", "Structured KPI tracking"],
        },
        "swot": {
            "strengths": ["Clear commercial interest", "Service-fit alignment"],
            "weaknesses": ["Limited public data depth", "Potential follow-through risk"],
            "opportunities": ["Expand into regulatory and clinical support"],
            "threats": ["Competitive service providers", "Decision delays"],
        },
        "action_plan": {
            "week_1": ["Validate executive sponsor and business need"],
            "week_2": ["Prepare tailored MedNova service proposition"],
            "month_1": ["Launch first engagement sprint"],
        },
        "intelligence": intelligence,
    }
    return report


def _build_operations_report_payload(conn: sqlite3.Connection) -> dict:
    companies = conn.execute("SELECT id, company_name, opportunity_score, pipeline_stage FROM crm_companies ORDER BY created_at DESC LIMIT 15").fetchall()
    tasks = conn.execute("SELECT title, status, due_date, priority FROM crm_tasks ORDER BY due_date IS NULL, due_date, created_at DESC LIMIT 20").fetchall()
    deals = conn.execute("SELECT title, stage, value, probability FROM crm_deals ORDER BY updated_at DESC, created_at DESC LIMIT 20").fetchall()
    emails = conn.execute("SELECT subject, status, created_at FROM crm_outreach_emails ORDER BY created_at DESC LIMIT 20").fetchall()
    activities = conn.execute("SELECT title, body, created_at FROM crm_activities ORDER BY created_at DESC LIMIT 20").fetchall()

    pipeline_value = sum(int(deal["value"] or 0) for deal in deals if (deal["stage"] or "lead") != "lost")
    pending_tasks = [dict(task) for task in tasks if (task["status"] or "pending") != "completed"]
    completed_tasks = [dict(task) for task in tasks if (task["status"] or "pending") == "completed"]

    return {
        "report_type": "operations",
        "generated_at": _report_timestamp(),
        "summary": {
            "companies": len(companies),
            "pipeline_value": pipeline_value,
            "pending_tasks": len(pending_tasks),
            "completed_tasks": len(completed_tasks),
            "email_count": len(emails),
            "activity_count": len(activities),
        },
        "executive_summary": "The operations pipeline remains healthy with growing account momentum and strong follow-up discipline.",
        "pipeline_health": {
            "active_opportunities": len([deal for deal in deals if (deal["stage"] or "lead") not in {"won", "lost"}]),
            "lead_conversion": 64,
            "team_performance": 78,
        },
        "kpis": {
            "completed_tasks": len(completed_tasks),
            "pending_tasks": len(pending_tasks),
            "upcoming_deadlines": len([task for task in pending_tasks if task.get("due_date")]),
            "recent_outreach": len(emails),
            "company_growth": len(companies),
        },
        "top_opportunities": [dict(deal) for deal in deals[:5]],
        "lost_opportunities": [dict(deal) for deal in deals if (deal["stage"] or "lead") == "lost"],
        "lead_sources": [{"source": "Green Book", "count": len(companies)}],
        "greenbook_updates": [{"topic": "Portfolio refresh", "status": "Updated"}],
        "recent_crm_activity": [dict(activity) for activity in activities[:10]],
        "tasks": [dict(task) for task in tasks],
        "companies": [dict(company) for company in companies],
        "emails": [dict(email) for email in emails],
    }


def _persist_report(conn: sqlite3.Connection, company_id: int | None, report_type: str, report_name: str, report_data: dict, executive_summary: str | None = None) -> dict:
    _ensure_report_tables(conn)
    cursor = conn.execute(
        """
        INSERT INTO crm_reports (crm_company_id, report_type, report_name, version, generated_by, generated_at, report_data, executive_summary, status, metadata)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            company_id,
            report_type,
            report_name,
            "1.0",
            "MedNovaOS",
            _report_timestamp(),
            json.dumps(report_data),
            executive_summary,
            "generated",
            json.dumps({"report_type": report_type, "company_id": company_id}),
        ),
    )
    report_id = int(cursor.lastrowid)
    row = conn.execute("SELECT id, crm_company_id, report_type, report_name, version, generated_by, generated_at, report_data, executive_summary, status, metadata FROM crm_reports WHERE id = ?", (report_id,)).fetchone()
    return {
        "id": int(row["id"]),
        "crm_company_id": int(row["crm_company_id"]) if row["crm_company_id"] is not None else None,
        "company_id": int(row["crm_company_id"]) if row["crm_company_id"] is not None else None,
        "report_type": row["report_type"],
        "report_name": row["report_name"],
        "version": row["version"],
        "generated_by": row["generated_by"],
        "generated_at": row["generated_at"],
        "report_data": json.loads(row["report_data"] or "{}"),
        "executive_summary": row["executive_summary"],
        "status": row["status"],
        "metadata": json.loads(row["metadata"] or "{}"),
    }


def _load_reports(conn: sqlite3.Connection, company_id: int | None = None) -> list[dict]:
    _ensure_report_tables(conn)
    if company_id is None:
        rows = conn.execute("SELECT id, crm_company_id, report_type, report_name, version, generated_by, generated_at, report_data, executive_summary, status, metadata FROM crm_reports ORDER BY generated_at DESC, id DESC").fetchall()
    else:
        rows = conn.execute("SELECT id, crm_company_id, report_type, report_name, version, generated_by, generated_at, report_data, executive_summary, status, metadata FROM crm_reports WHERE crm_company_id = ? ORDER BY generated_at DESC, id DESC", (company_id,)).fetchall()
    return [
        {
            "id": int(row["id"]),
            "crm_company_id": int(row["crm_company_id"]) if row["crm_company_id"] is not None else None,
            "company_id": int(row["crm_company_id"]) if row["crm_company_id"] is not None else None,
            "report_type": row["report_type"],
            "report_name": row["report_name"],
            "version": row["version"],
            "generated_by": row["generated_by"],
            "generated_at": row["generated_at"],
            "report_data": json.loads(row["report_data"] or "{}"),
            "executive_summary": row["executive_summary"],
            "status": row["status"],
            "metadata": json.loads(row["metadata"] or "{}"),
        }
        for row in rows
    ]


def _slugify_company_name(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (value or "").strip().lower()).strip("-")
    return slug or "company"


def _crm_frontend_target() -> str:
    configured = os.getenv("MEDNOVA_CRM_FRONTEND_URL", "").strip()
    return configured or "http://127.0.0.1:5175"


def _row_to_dict(row):
    return dict(row) if row is not None else None


def _crm_company_status_for_row(row) -> str:
    status = (row["opportunity_status"] or "").strip().lower()
    if status in {"engaged", "qualified", "client", "active", "won"}:
        return "engaged"
    if status in {"dormant", "inactive", "lost"}:
        return "dormant"
    return "prospect"


def _build_growhub_company_payloads(conn) -> list[dict]:
    rows = conn.execute(
        """
        SELECT id, company_name, country, opportunity_score, portfolio_summary, source,
               opportunity_status, pipeline_stage, created_at, updated_at
        FROM crm_companies
        ORDER BY created_at DESC, id DESC
        """
    ).fetchall()

    companies = []
    for row in rows:
        company_name = row["company_name"] or "Unknown company"
        created_at = row["created_at"] or row["updated_at"] or datetime.utcnow().isoformat()
        companies.append({
            "id": int(row["id"]),
            "name": company_name,
            "industry": "Biopharma",
            "country": row["country"] or "Unknown",
            "website": "",
            "status": _crm_company_status_for_row(row),
            "opportunityScore": int(row["opportunity_score"] or 0),
            "portfolioSummary": row["portfolio_summary"] or "",
            "source": row["source"] or "CRM",
            "pipelineStage": row["pipeline_stage"] or "Lead",
            "regulatoryReportId": None,
            "lastActivityAt": created_at,
            "nextFollowUpAt": None,
            "createdAt": created_at,
        })
    return companies


def _build_growhub_related_payloads(conn, companies):
    contacts = []
    activities = []
    tasks = []
    notes = []
    deals = []
    emails = []
    products = []

    for company in companies:
        company_id = int(company["id"])
        company_name = company["name"]

        company_row = conn.execute(
            "SELECT greenbook_products_json, pipeline_stage, opportunity_score FROM crm_companies WHERE id = ?",
            (company_id,),
        ).fetchone()
        product_payload = []
        if company_row and company_row["greenbook_products_json"]:
            try:
                product_payload = json.loads(company_row["greenbook_products_json"] or "[]")
            except (TypeError, ValueError):
                product_payload = []

        contact_rows = conn.execute(
            "SELECT id, full_name, role, department, email, phone, source, created_at, source_url, discovered_at, confidence_score, verification_status, website, linkedin_url, notes FROM crm_contacts WHERE crm_company_id = ? ORDER BY created_at DESC",
            (company_id,),
        ).fetchall()
        for row in contact_rows:
            contacts.append({
                "id": int(row["id"]),
                "companyId": company_id,
                "name": row["full_name"] or "Primary Contact",
                "position": row["role"] or "Primary contact",
                "department": row["department"] or "Business Development",
                "email": row["email"] or "",
                "phone": row["phone"] or "",
                "linkedin": row["linkedin_url"] or "",
                "notes": row["notes"] or row["source"] or "CRM",
                "source": row["source"] or "CRM",
                "sourceUrl": row["source_url"] or "",
                "discoveredAt": row["discovered_at"] or "",
                "confidenceScore": row["confidence_score"] or 0,
                "verificationStatus": row["verification_status"] or "pending",
                "website": row["website"] or "",
            })

        activity_rows = conn.execute(
            "SELECT id, activity_type, title, body, created_at FROM crm_activities WHERE crm_company_id = ? ORDER BY created_at DESC",
            (company_id,),
        ).fetchall()
        for row in activity_rows:
            activities.append({
                "id": int(row["id"]),
                "companyId": company_id,
                "type": (row["activity_type"] or "note") if row["activity_type"] else "note",
                "title": row["title"] or "Activity",
                "body": row["body"] or "",
                "at": row["created_at"] or company["createdAt"],
                "author": "MedNovaOS",
            })

        task_rows = conn.execute(
            "SELECT id, title, task_type, status, due_date, assigned_to, completed_at, description, priority FROM crm_tasks WHERE crm_company_id = ? ORDER BY CASE WHEN status = 'completed' THEN 0 ELSE 1 END, CASE WHEN status = 'completed' THEN completed_at END DESC, due_date IS NULL, due_date, created_at DESC",
            (company_id,),
        ).fetchall()
        for row in task_rows:
            tasks.append({
                "id": int(row["id"]),
                "companyId": company_id,
                "title": row["title"] or "Follow-up",
                "type": row["task_type"] or "follow-up",
                "dueDate": row["due_date"] or company["lastActivityAt"],
                "done": (row["status"] or "pending") == "completed",
                "assignee": row["assigned_to"] or "MedNovaOS",
                "completedAt": row["completed_at"] or "",
                "description": row["description"] or "",
                "priority": row["priority"] or "medium",
            })

        note_rows = conn.execute(
            "SELECT id, body, created_at FROM crm_notes WHERE crm_company_id = ? ORDER BY created_at DESC",
            (company_id,),
        ).fetchall()
        for row in note_rows:
            notes.append({
                "id": int(row["id"]),
                "companyId": company_id,
                "body": row["body"] or "",
                "at": row["created_at"] or company["createdAt"],
                "author": "MedNovaOS",
            })

        for product in product_payload:
            products.append({
                "id": f"{company_id}-{product.get('product_name') or product.get('name') or 'product'}",
                "companyId": company_id,
                "name": product.get("product_name") or product.get("name") or "Product",
                "category": product.get("category") or product.get("therapeutic_area") or "Uncategorized",
                "approvals": int(product.get("approvals") or 1),
            })

        deal_rows = conn.execute(
            "SELECT id, crm_company_id, crm_contact_id, title, stage, value, currency, probability, expected_close_at, owner, description FROM crm_deals WHERE crm_company_id = ? ORDER BY updated_at DESC, created_at DESC, id DESC",
            (company_id,),
        ).fetchall()
        for row in deal_rows:
            deals.append(_crm_deal_payload_from_row(row))

    fallback_deals = _build_growhub_pipeline_deals(conn, companies)
    deals.extend(fallback_deals)
    deals = _dedupe_deals_by_id(deals)
    deals.sort(key=lambda deal: (-(int(deal.get("id") or 0)), deal.get("stage", "") or ""))

    outreach_rows = conn.execute(
        """
        SELECT id, crm_company_id, crm_contact_id, template_key, template_name, subject, body, recipient, recipient_name, sender_name, sender_email, company_name, contact_name, status, created_at, updated_at, sent_at
        FROM crm_outreach_emails
        ORDER BY created_at DESC, id DESC
        """
    ).fetchall()
    for row in outreach_rows:
        emails.append({
            "id": int(row["id"]),
            "companyId": int(row["crm_company_id"]),
            "contactId": int(row["crm_contact_id"]) if row["crm_contact_id"] is not None else None,
            "subject": row["subject"] or "Email",
            "body": row["body"] or "",
            "status": (row["status"] or "draft") if (row["status"] or "draft") in {"draft", "sent", "failed"} else "draft",
            "recipient": row["recipient"] or "",
            "recipientName": row["recipient_name"] or row["contact_name"] or "",
            "contactName": row["contact_name"] or row["recipient_name"] or "",
            "companyName": row["company_name"] or "",
            "templateKey": row["template_key"] or "",
            "templateName": row["template_name"] or row["template_key"] or "",
            "at": row["sent_at"] or row["updated_at"] or row["created_at"] or "",
        })

    return {
        "companies": companies,
        "contacts": contacts,
        "activities": activities,
        "tasks": tasks,
        "notes": notes,
        "deals": deals,
        "emails": emails,
        "products": products,
    }


def ensure_database() -> Path:
    db_file = db_path()
    db_file.parent.mkdir(parents=True, exist_ok=True)
    if not db_file.exists():
        initialize_database(db_file)
        apply_migrations(db_file)
        return db_file

    with sqlite3.connect(db_file) as conn:
        products_table = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='products'").fetchone()
        if not products_table:
            initialize_database(db_file)
            apply_migrations(db_file)
            return db_file

        expected_columns = {"nafdac_product_id", "registration_number", "dosage_form_id", "route_id", "category_id"}
        actual_columns = {row[1] for row in conn.execute("PRAGMA table_info(products)").fetchall()}
        if not expected_columns.issubset(actual_columns):
            initialize_database(db_file)
            apply_migrations(db_file)
            return db_file

    apply_migrations(db_file)
    return db_file


def _parse_date(value):
    if not value:
        return None
    try:
        if isinstance(value, str):
            value = value.replace("Z", "+00:00")
            return datetime.fromisoformat(value)
    except ValueError:
        return None
    return value


def _calc_opportunity_score(products):
    if not products:
        return 0
    product_count = len(products)
    categories = {p.get("category_name") for p in products if p.get("category_name")}
    latest_date = max((p.get("approval_date") for p in products if p.get("approval_date")), default=None, key=lambda item: item or "")
    latest_dt = _parse_date(latest_date)
    days_since = 0
    if latest_dt:
        days_since = max(0, (datetime.now() - latest_dt).days)
    recency_score = max(0, min(25, 25 - int(days_since / 365 * 25)))
    product_score = min(35, product_count * 5)
    category_score = min(20, len(categories) * 6)
    diversity_score = min(20, max(0, product_count - 2) * 3)
    size_score = min(10, max(0, product_count - 5) * 2)
    return min(100, round(product_score + category_score + recency_score + diversity_score + size_score))


def _derive_company_size(product_count):
    if product_count >= 8:
        return "Large"
    if product_count >= 3:
        return "Medium"
    return "Small"


def _normalize_company_name(value):
    return (value or "").strip().lower()


def _build_crm_company_payload(conn, company_name):
    normalized_name = _normalize_company_name(company_name)
    rows = conn.execute(
        """
        SELECT
            COALESCE(a.applicant_name, m.manufacturer_name, 'Unknown company') AS company_name,
            COALESCE(m.country, 'Unknown') AS country,
            p.product_name,
            p.registration_number,
            df.form_name AS dosage_form,
            c.category_name AS therapeutic_area,
            p.approval_date,
            p.status,
            p.source_last_updated
        FROM products p
        LEFT JOIN applicants a ON a.id = p.applicant_id
        LEFT JOIN manufacturers m ON m.id = p.manufacturer_id
        LEFT JOIN categories c ON c.id = p.category_id
        LEFT JOIN dosage_forms df ON df.id = p.dosage_form_id
        WHERE LOWER(COALESCE(a.applicant_name, m.manufacturer_name, '')) = ?
           OR LOWER(COALESCE(a.applicant_name, m.manufacturer_name, '')) LIKE ?
           OR LOWER(COALESCE(p.product_name, '')) LIKE ?
        ORDER BY p.approval_date DESC, p.product_name
        """,
        (normalized_name, f"%{normalized_name}%", f"%{normalized_name}%"),
    ).fetchall()

    products = []
    for row in rows:
        products.append({
            "product_name": row["product_name"],
            "registration_number": row["registration_number"],
            "dosage_form": row["dosage_form"],
            "therapeutic_area": row["therapeutic_area"],
            "approval_date": row["approval_date"],
            "status": row["status"],
            "source_last_updated": row["source_last_updated"],
        })

    therapeutic_areas = sorted({p["therapeutic_area"] for p in products if p["therapeutic_area"]})
    registration_numbers = sorted({p["registration_number"] for p in products if p["registration_number"]})
    dosage_forms = sorted({p["dosage_form"] for p in products if p["dosage_form"]})
    registration_dates = sorted([p["approval_date"] for p in products if p["approval_date"]])
    opportunity_score = _calc_opportunity_score([
        {"category_name": p["therapeutic_area"], "approval_date": p["approval_date"]}
        for p in products
    ])

    return {
        "company_name": company_name.strip() or (rows[0]["company_name"] if rows else "Unknown company"),
        "country": rows[0]["country"] if rows else "Unknown",
        "product_count": len(products),
        "portfolio_summary": f"{len(products)} registered product(s) across {len(therapeutic_areas)} therapeutic area(s).",
        "opportunity_score": opportunity_score,
        "products": products,
        "therapeutic_areas": therapeutic_areas,
        "registration_numbers": registration_numbers,
        "dosage_forms": dosage_forms,
        "registration_dates": registration_dates,
    }


def _upsert_crm_company(conn, company_name, payload_data=None):
    payload_data = dict(payload_data or {})
    payload_data.setdefault("company_name", company_name)
    payload_data.setdefault("company", company_name)
    payload_data.setdefault("source", "Green Book")
    payload_data.setdefault("status", "New")
    payload_data.setdefault("pipeline_stage", "Lead")

    if not payload_data.get("report_context"):
        payload_data["report_context"] = json.dumps(_build_crm_company_payload(conn, company_name)["products"])
    if not payload_data.get("greenbook_products_json"):
        payload_data["greenbook_products_json"] = payload_data["report_context"]

    company_id, payload, created = create_company_from_payload(conn, payload_data)
    return company_id, payload, created


def _build_opportunity_rows(conn, filters):
    where = ["1=1"]
    params = []

    if filters.get("q"):
        like = f"%{filters['q']}%"
        where.append("(COALESCE(a.applicant_name, m.manufacturer_name, 'Unknown company') LIKE ? OR p.product_name LIKE ? OR p.registration_number LIKE ?)")
        params.extend([like, like, like])
    if filters.get("country"):
        where.append("COALESCE(m.country, 'Unknown') = ?")
        params.append(filters["country"])
    if filters.get("manufacturer"):
        where.append("COALESCE(a.applicant_name, m.manufacturer_name, 'Unknown company') = ?")
        params.append(filters["manufacturer"])
    if filters.get("product_category"):
        where.append("c.category_name = ?")
        params.append(filters["product_category"])
    if filters.get("therapeutic_area"):
        where.append("c.category_name = ?")
        params.append(filters["therapeutic_area"])
    if filters.get("registration_status"):
        where.append("p.status = ?")
        params.append(filters["registration_status"])
    if filters.get("registration_year"):
        where.append("strftime('%Y', p.approval_date) = ?")
        params.append(filters["registration_year"])
    if filters.get("product_count_range"):
        if filters["product_count_range"] == "1-3":
            where.append("(SELECT COUNT(*) FROM products p2 LEFT JOIN applicants a2 ON a2.id = p2.applicant_id LEFT JOIN manufacturers m2 ON m2.id = p2.manufacturer_id WHERE COALESCE(a2.applicant_name, m2.manufacturer_name, 'Unknown company') = COALESCE(a.applicant_name, m.manufacturer_name, 'Unknown company')) BETWEEN 1 AND 3")
        elif filters["product_count_range"] == "4-8":
            where.append("(SELECT COUNT(*) FROM products p2 LEFT JOIN applicants a2 ON a2.id = p2.applicant_id LEFT JOIN manufacturers m2 ON m2.id = p2.manufacturer_id WHERE COALESCE(a2.applicant_name, m2.manufacturer_name, 'Unknown company') = COALESCE(a.applicant_name, m.manufacturer_name, 'Unknown company')) BETWEEN 4 AND 8")
        elif filters["product_count_range"] == "9+":
            where.append("(SELECT COUNT(*) FROM products p2 LEFT JOIN applicants a2 ON a2.id = p2.applicant_id LEFT JOIN manufacturers m2 ON m2.id = p2.manufacturer_id WHERE COALESCE(a2.applicant_name, m2.manufacturer_name, 'Unknown company') = COALESCE(a.applicant_name, m.manufacturer_name, 'Unknown company')) >= 9")
    if filters.get("company_size"):
        size_bucket = filters["company_size"]
        if size_bucket == "small":
            where.append("(SELECT COUNT(*) FROM products p2 LEFT JOIN applicants a2 ON a2.id = p2.applicant_id LEFT JOIN manufacturers m2 ON m2.id = p2.manufacturer_id WHERE COALESCE(a2.applicant_name, m2.manufacturer_name, 'Unknown company') = COALESCE(a.applicant_name, m.manufacturer_name, 'Unknown company')) BETWEEN 1 AND 2")
        elif size_bucket == "medium":
            where.append("(SELECT COUNT(*) FROM products p2 LEFT JOIN applicants a2 ON a2.id = p2.applicant_id LEFT JOIN manufacturers m2 ON m2.id = p2.manufacturer_id WHERE COALESCE(a2.applicant_name, m2.manufacturer_name, 'Unknown company') = COALESCE(a.applicant_name, m.manufacturer_name, 'Unknown company')) BETWEEN 3 AND 8")
        else:
            where.append("(SELECT COUNT(*) FROM products p2 LEFT JOIN applicants a2 ON a2.id = p2.applicant_id LEFT JOIN manufacturers m2 ON m2.id = p2.manufacturer_id WHERE COALESCE(a2.applicant_name, m2.manufacturer_name, 'Unknown company') = COALESCE(a.applicant_name, m.manufacturer_name, 'Unknown company')) >= 9")
    if filters.get("opportunity_score"):
        min_score = int(filters["opportunity_score"])
        where.append("0 = 0")
    if filters.get("last_updated"):
        if filters["last_updated"] == "30":
            where.append("p.source_last_updated IS NOT NULL AND date(p.source_last_updated) >= date('now', '-30 days')")
        elif filters["last_updated"] == "90":
            where.append("p.source_last_updated IS NOT NULL AND date(p.source_last_updated) >= date('now', '-90 days')")
        elif filters["last_updated"] == "365":
            where.append("p.source_last_updated IS NOT NULL AND date(p.source_last_updated) >= date('now', '-365 days')")

    query = """
        SELECT
            p.id,
            p.product_name,
            p.registration_number,
            p.strength,
            p.status,
            p.approval_date,
            p.source_last_updated,
            c.category_name,
            df.form_name AS dosage_form,
            COALESCE(a.applicant_name, m.manufacturer_name, 'Unknown company') AS company_name,
            COALESCE(m.country, 'Unknown') AS country
        FROM products p
        LEFT JOIN applicants a ON a.id = p.applicant_id
        LEFT JOIN manufacturers m ON m.id = p.manufacturer_id
        LEFT JOIN categories c ON c.id = p.category_id
        LEFT JOIN dosage_forms df ON df.id = p.dosage_form_id
        WHERE {where_clause}
        ORDER BY p.approval_date DESC, p.product_name
    """.format(where_clause=" AND ".join(where))

    rows = conn.execute(query, tuple(params)).fetchall()

    grouped = defaultdict(list)
    for row in rows:
        company_name = row["company_name"] or "Unknown company"
        grouped[company_name].append({
            "id": row["id"],
            "product_name": row["product_name"],
            "registration_number": row["registration_number"],
            "strength": row["strength"],
            "status": row["status"] or "Unknown",
            "approval_date": row["approval_date"],
            "source_last_updated": row["source_last_updated"],
            "category_name": row["category_name"],
            "dosage_form": row["dosage_form"],
            "country": row["country"] or "Unknown",
        })

    companies = []
    for company_name, products in grouped.items():
        product_count = len(products)
        categories = [p["category_name"] for p in products if p.get("category_name")]
        latest_update = max((p.get("source_last_updated") for p in products if p.get("source_last_updated")), default=None, key=lambda item: item or "")
        latest_approval = max((p.get("approval_date") for p in products if p.get("approval_date")), default=None, key=lambda item: item or "")
        latest_dt = _parse_date(latest_update or latest_approval)
        score = _calc_opportunity_score(products)
        companies.append({
            "id": company_name.lower().replace(" ", "-") + f"-{product_count}",
            "company": company_name,
            "country": next((p["country"] for p in products if p.get("country")), "Unknown"),
            "products": products,
            "product_count": product_count,
            "therapeutic_areas": sorted(set(categories)),
            "registration_status": sorted({p["status"] for p in products})[0] if products else "Unknown",
            "registration_year": _parse_date(latest_approval).year if latest_approval and _parse_date(latest_approval) else None,
            "last_updated": latest_update or latest_approval,
            "company_size": _derive_company_size(product_count),
            "opportunity_score": score,
            "estimated_value": product_count * 1250000,
            "recommended_services": ["Regulatory Intelligence", "PV Support", "Clinical Development"],
            "status": "Monitor" if score >= 70 else "Priority" if score >= 50 else "Watch",
        })

    if filters.get("opportunity_score"):
        min_score = int(filters["opportunity_score"])
        companies = [company for company in companies if company["opportunity_score"] >= min_score]

    if filters.get("estimated_value"):
        value_bucket = filters["estimated_value"]
        if value_bucket == "lt_5m":
            companies = [company for company in companies if company["estimated_value"] < 5_000_000]
        elif value_bucket == "5m_10m":
            companies = [company for company in companies if 5_000_000 <= company["estimated_value"] <= 10_000_000]
        elif value_bucket == "gt_10m":
            companies = [company for company in companies if company["estimated_value"] > 10_000_000]

    sort_by = filters.get("sort_by", "score")
    if sort_by == "company":
        companies.sort(key=lambda company: company["company"].lower())
    elif sort_by == "products":
        companies.sort(key=lambda company: company["product_count"], reverse=True)
    elif sort_by == "registration":
        companies.sort(key=lambda company: company["registration_year"] or 0, reverse=True)
    elif sort_by == "updated":
        companies.sort(key=lambda company: company["last_updated"] or "", reverse=True)
    elif sort_by == "alphabetical":
        companies.sort(key=lambda company: company["company"].lower())
    else:
        companies.sort(key=lambda company: company["opportunity_score"], reverse=True)

    return companies


app = Flask(__name__)
ensure_database()
ensure_crm_tables()
scheduler = SyncScheduler(app)
scheduler.start()

ALLOWED_CORS_ORIGINS = {
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:5175",
    "http://127.0.0.1:5175",
}


def _cors_origin_allowed(origin: str | None) -> str | None:
    if not origin:
        return None
    parsed = urlparse(origin)
    allowed_hosts = {"localhost:5173", "127.0.0.1:5173", "localhost:5175", "127.0.0.1:5175"}
    if parsed.scheme in {"http", "https"} and parsed.netloc in allowed_hosts:
        return origin
    return None


@app.before_request
def handle_cors_preflight():
    origin = request.headers.get("Origin")
    if request.method == "OPTIONS" and origin:
        allowed_origin = _cors_origin_allowed(origin)
        if allowed_origin:
            response = jsonify({"ok": True})
            response.headers["Access-Control-Allow-Origin"] = allowed_origin
            # allow common mutation verbs used by the frontend
            response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS, PATCH, PUT, DELETE"
            response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
            response.headers["Access-Control-Max-Age"] = "600"
            response.status_code = 200
            return response


@app.after_request
def add_cors_headers(response):
    origin = request.headers.get("Origin")
    allowed_origin = _cors_origin_allowed(origin)
    if allowed_origin:
        response.headers["Access-Control-Allow-Origin"] = allowed_origin
        response.headers["Access-Control-Allow-Credentials"] = "true"
        response.headers["Vary"] = "Origin"
    return response


@app.template_filter("money")
def money(value):
    try:
        return f"₦{float(value):,.0f}"
    except (TypeError, ValueError):
        return "₦0"


@app.route("/")
def dashboard():
    conn = connect()
    try:
        manufacturers = scalar(conn, "SELECT COUNT(*) FROM manufacturers")
        products = scalar(conn, "SELECT COUNT(*) FROM products")
        if table_exists(conn, "revenue_pipeline"):
            opportunities = scalar(conn, "SELECT COUNT(*) FROM revenue_pipeline")
            pipeline_value = scalar(conn, "SELECT COALESCE(SUM(estimated_value), 0) FROM revenue_pipeline")
            top_accounts = conn.execute(
                "SELECT company, category, products, estimated_value, recommended_services, status FROM revenue_pipeline ORDER BY estimated_value DESC, products DESC LIMIT 25"
            ).fetchall()
        else:
            opportunities = 0
            pipeline_value = 0
            top_accounts = []
        expiring = scalar(
            conn,
            "SELECT COUNT(*) FROM products WHERE expiry_date IS NOT NULL AND date(expiry_date) BETWEEN date('now') AND date('now', '+12 months')",
        )
        categories = conn.execute(
            "SELECT COALESCE(c.category_name, 'Unknown') AS category, COUNT(p.id) AS product_count FROM products p LEFT JOIN categories c ON c.id = p.category_id GROUP BY c.category_name ORDER BY product_count DESC"
        ).fetchall()
        renewals = conn.execute(
            "SELECT COALESCE(a.applicant_name, m.manufacturer_name, 'Not provided') AS company, COUNT(*) AS expiring_products FROM products p LEFT JOIN applicants a ON a.id = p.applicant_id LEFT JOIN manufacturers m ON m.id = p.manufacturer_id WHERE p.expiry_date IS NOT NULL AND date(p.expiry_date) BETWEEN date('now') AND date('now', '+12 months') GROUP BY company ORDER BY expiring_products DESC LIMIT 20"
        ).fetchall()
        latest_sync = conn.execute(
            "SELECT started_at, finished_at, status, products_added, products_updated, products_removed, duration_seconds, error_message FROM sync_history ORDER BY id DESC LIMIT 1"
        ).fetchone()
        last_sync_payload = None
        if latest_sync:
            last_sync_payload = {
                "started_at": latest_sync["started_at"],
                "finished_at": latest_sync["finished_at"],
                "status": latest_sync["status"] or "unknown",
                "products_added": int(latest_sync["products_added"] or 0),
                "products_updated": int(latest_sync["products_updated"] or 0),
                "products_removed": int(latest_sync["products_removed"] or 0),
                "duration_seconds": int(latest_sync["duration_seconds"] or 0),
                "error_message": latest_sync["error_message"],
            }
        return render_template(
            "dashboard.html",
            manufacturers=manufacturers,
            products=products,
            opportunities=opportunities,
            pipeline_value=pipeline_value,
            expiring=expiring,
            categories=categories,
            top_accounts=top_accounts,
            renewals=renewals,
            db=str(db_path()),
            last_sync_payload=last_sync_payload,
        )
    finally:
        conn.close()


@app.route("/products")
def products():
    q = request.args.get("q", "").strip()
    category = request.args.get("category", "").strip()
    status = request.args.get("status", "").strip()
    page = max(request.args.get("page", 1, type=int), 1)
    size = 50
    offset = (page - 1) * size

    where = ["1=1"]
    params = []
    if q:
        like = f"%{q}%"
        where.append("(p.product_name LIKE ? OR p.active_ingredient LIKE ? OR p.registration_number LIKE ? OR a.applicant_name LIKE ? OR m.manufacturer_name LIKE ?)")
        params.extend([like] * 5)
    if category:
        where.append("c.category_name = ?")
        params.append(category)
    if status:
        where.append("p.status = ?")
        params.append(status)

    where_clause = " AND ".join(where)
    conn = connect()
    try:
        total = scalar(
            conn,
            f"SELECT COUNT(*) FROM products p LEFT JOIN applicants a ON a.id = p.applicant_id LEFT JOIN manufacturers m ON m.id = p.manufacturer_id LEFT JOIN categories c ON c.id = p.category_id WHERE {where_clause}",
            tuple(params),
        )
        rows = conn.execute(
            f"SELECT p.id AS greenbook_product_id, p.product_name, p.active_ingredient AS ingredient_name, c.category_name AS product_category, p.registration_number AS nafdac_number, a.applicant_name, m.manufacturer_name, p.approval_date, p.expiry_date, p.status FROM products p LEFT JOIN applicants a ON a.id = p.applicant_id LEFT JOIN manufacturers m ON m.id = p.manufacturer_id LEFT JOIN categories c ON c.id = p.category_id WHERE {where_clause} ORDER BY p.approval_date DESC, p.product_name LIMIT ? OFFSET ?",
            tuple(params + [size, offset]),
        ).fetchall()
        categories = conn.execute("SELECT DISTINCT c.category_name AS category_name FROM products p LEFT JOIN categories c ON c.id = p.category_id WHERE c.category_name IS NOT NULL ORDER BY c.category_name").fetchall()
        statuses = conn.execute("SELECT DISTINCT status FROM products WHERE status IS NOT NULL ORDER BY status").fetchall()
        return render_template("products.html", rows=rows, q=q, category=category, status=status, categories=categories, statuses=statuses, total=total, page=page, size=size)
    finally:
        conn.close()


@app.route("/products/<int:pid>")
def product_detail(pid):
    conn = connect()
    try:
        row = conn.execute(
            """
            SELECT
                p.id,
                p.nafdac_product_id,
                p.registration_number AS nafdac_number,
                p.product_name,
                p.generic_name,
                p.active_ingredient,
                p.strength,
                p.pack_size,
                p.composition,
                p.approval_date,
                p.expiry_date,
                p.status,
                p.description,
                p.source_last_updated,
                c.category_name AS product_category,
                a.applicant_name,
                m.manufacturer_name,
                df.form_name AS dosage_form,
                r.route_name AS route_of_administration,
                p.source_last_updated
            FROM products p
            LEFT JOIN categories c ON c.id = p.category_id
            LEFT JOIN applicants a ON a.id = p.applicant_id
            LEFT JOIN manufacturers m ON m.id = p.manufacturer_id
            LEFT JOIN dosage_forms df ON df.id = p.dosage_form_id
            LEFT JOIN routes r ON r.id = p.route_id
            WHERE p.id = ?
            """,
            (pid,),
        ).fetchone()
        if not row:
            abort(404)
        return render_template("product_detail.html", product=row)
    finally:
        conn.close()


@app.route("/opportunities")
def opportunities():
    q = request.args.get("q", "").strip()
    product_category = request.args.get("product_category", "").strip()
    registration_status = request.args.get("registration_status", "").strip()
    estimated_value = request.args.get("estimated_value", "").strip()
    sort_by = request.args.get("sort_by", "score").strip()

    filters = {
        "q": q,
        "product_category": product_category,
        "registration_status": registration_status,
        "estimated_value": estimated_value,
        "sort_by": sort_by,
    }

    conn = connect()
    try:
        rows = _build_opportunity_rows(conn, filters)
        categories = conn.execute(
            "SELECT DISTINCT c.category_name AS category_name FROM products p LEFT JOIN categories c ON c.id = p.category_id WHERE c.category_name IS NOT NULL ORDER BY c.category_name"
        ).fetchall()
        statuses = conn.execute(
            "SELECT DISTINCT status FROM products WHERE status IS NOT NULL ORDER BY status"
        ).fetchall()
        return render_template(
            "opportunities.html",
            rows=rows,
            q=q,
            product_category=product_category,
            registration_status=registration_status,
            estimated_value=estimated_value,
            sort_by=sort_by,
            categories=categories,
            statuses=statuses,
        )
    finally:
        conn.close()


@app.route("/renewals")
def renewal_watch():
    months = min(max(request.args.get("months", 12, type=int), 1), 60)
    conn = connect()
    try:
        rows = conn.execute(
            "SELECT product_name, registration_number AS nafdac_number, c.category_name AS product_category, a.applicant_name, m.manufacturer_name, expiry_date, status FROM products p LEFT JOIN applicants a ON a.id = p.applicant_id LEFT JOIN manufacturers m ON m.id = p.manufacturer_id LEFT JOIN categories c ON c.id = p.category_id WHERE p.expiry_date IS NOT NULL AND date(p.expiry_date) BETWEEN date('now') AND date('now', ?) ORDER BY date(p.expiry_date), a.applicant_name LIMIT 1000",
            (f"+{months} months",),
        ).fetchall()
        return render_template("renewals.html", rows=rows, months=months)
    finally:
        conn.close()


@app.route("/crm")
def crm():
    return redirect(_crm_frontend_target())


@app.route("/growhub")
def growhub_dashboard():
    return redirect(_crm_frontend_target())


@app.route("/mednova-grow-hub")
def growhub_proxy():
    return redirect(_crm_frontend_target())


@app.route("/crm/companies")
def crm_companies():
    return redirect(_crm_frontend_target() + "/companies")


@app.route("/api/growhub/crm/companies")
def growhub_crm_companies():
    conn = connect()
    try:
        return jsonify(_build_growhub_company_payloads(conn))
    finally:
        conn.close()


@app.route("/api/growhub/crm/data")
def growhub_crm_data():
    conn = connect()
    try:
        companies = _build_growhub_company_payloads(conn)
        payload = _build_growhub_related_payloads(conn, companies)
        return jsonify(payload)
    finally:
        conn.close()


@app.route("/api/crm/companies/<int:company_id>")
def crm_company_detail_json(company_id):
    conn = connect()
    try:
        company = conn.execute("SELECT * FROM crm_companies WHERE id = ?", (company_id,)).fetchone()
        if not company:
            abort(404)

        products = json.loads(company["greenbook_products_json"] or "[]") if company["greenbook_products_json"] else []
        activities = [
            _row_to_dict(row)
            for row in conn.execute(
                "SELECT activity_type, title, body, created_at FROM crm_activities WHERE crm_company_id = ? ORDER BY created_at DESC",
                (company_id,),
            ).fetchall()
        ]
        notes = [
            _row_to_dict(row)
            for row in conn.execute(
                "SELECT id, body, created_at FROM crm_notes WHERE crm_company_id = ? ORDER BY created_at DESC",
                (company_id,),
            ).fetchall()
        ]
        contacts = [
            _row_to_dict(row)
            for row in conn.execute(
                "SELECT id, full_name, role, department, email, phone, source, created_at, source_url, discovered_at, confidence_score, verification_status, website, linkedin_url, notes FROM crm_contacts WHERE crm_company_id = ? ORDER BY created_at DESC",
                (company_id,),
            ).fetchall()
        ]
        tasks = [
            _row_to_dict(row)
            for row in conn.execute(
                "SELECT id, title, description, task_type, status, priority, due_date, assigned_to, completed_at, created_at FROM crm_tasks WHERE crm_company_id = ? ORDER BY due_date IS NULL, due_date, created_at DESC",
                (company_id,),
            ).fetchall()
        ]

        return jsonify({
            "company": _row_to_dict(company),
            "products": products,
            "activities": activities,
            "notes": notes,
            "contacts": contacts,
            "tasks": tasks,
        })
    finally:
        conn.close()


@app.route("/crm/companies/<int:company_id>")
def crm_company_detail(company_id):
    return redirect(f"{_crm_frontend_target()}/companies/{company_id}")


@app.route("/crm/companies/<int:company_id>/outreach", methods=["GET", "POST"])
def crm_company_outreach(company_id):
    conn = connect()
    try:
        company = conn.execute("SELECT id, company_name, country, opportunity_score, opportunity_status, pipeline_stage, source, portfolio_summary, registration_numbers, dosage_forms, therapeutic_areas, registration_dates FROM crm_companies WHERE id = ?", (company_id,)).fetchone()
        if not company:
            abort(404)

        contacts = conn.execute(
            "SELECT id, full_name, role, department, email, phone FROM crm_contacts WHERE crm_company_id = ? ORDER BY created_at DESC",
            (company_id,),
        ).fetchall()
        templates = _build_template_catalog()
        preview = None
        history = []
        initial_subject = ""
        initial_body = ""
        recipient = ""
        recipient_name = ""
        sender_name = _default_sender_name()
        sender_email = _default_sender_email()
        warning_message = None
        preview_error = None
        draft_id = None
        resend_status = _outreach_status_payload()
        resend_warning_message = None
        if not resend_status.get("resendConfigured"):
            diagnostics = resend_status.get("diagnostics") or {}
            if not diagnostics.get("resendApiKeyConfigured"):
                resend_warning_message = "Missing RESEND_API_KEY."
            elif not diagnostics.get("senderEmailConfigured"):
                resend_warning_message = "Missing FROM_EMAIL."
            else:
                resend_warning_message = "Resend configuration is incomplete."

        payload = _coerce_request_payload() if request.method == "POST" else {}
        contact_id = payload.get("contact_id") or ""
        template_key = payload.get("template_key") or "introduction"
        sender_name = (payload.get("sender_name") or sender_name).strip()
        sender_email = (payload.get("sender_email") or sender_email).strip()
        recipient = (payload.get("recipient") or "").strip()
        recipient_name = (payload.get("recipient_name") or "").strip()
        contact_ids = [int(contact_id)] if str(contact_id).strip() else []

        try:
            preview_data = _build_outreach_preview(conn, company_id, template_key, contact_ids, sender_name, sender_email, recipient, recipient_name, int(contact_id) if str(contact_id).strip() else None)
            initial_subject = preview_data["subject"]
            initial_body = preview_data["body"]
            recipient = preview_data["recipient"]
            recipient_name = preview_data["recipient_name"]
            sender_name = preview_data["sender_name"]
            sender_email = preview_data["sender_email"]
            preview = {"subject": preview_data["subject"], "body": preview_data["body"]}
            warning_message = preview_data.get("warning_message")
        except Exception as exc:
            preview_error = str(exc)

        history = [
            _row_to_dict(row)
            for row in conn.execute(
                "SELECT id, subject, body, status, created_at FROM crm_outreach_emails WHERE crm_company_id = ? ORDER BY created_at DESC LIMIT 10",
                (company_id,),
            ).fetchall()
        ]

        return render_template(
            "crm_outreach.html",
            company=company,
            contacts=contacts,
            templates=templates,
            preview=preview,
            history=history,
            initial_subject=initial_subject,
            initial_body=initial_body,
            recipient=recipient,
            recipient_name=recipient_name,
            sender_name=sender_name,
            sender_email=sender_email,
            warning_message=warning_message,
            preview_error=preview_error,
            draft_id=draft_id,
            resendConfigured=resend_status["resendConfigured"],
            senderConfigured=resend_status["senderConfigured"],
            senderEmail=resend_status["senderEmail"],
            environmentLoaded=resend_status["environmentLoaded"],
            resend_warning_message=resend_warning_message,
        )
    finally:
        conn.close()


@app.route("/api/crm/companies/<int:company_id>/pipeline-stage", methods=["PATCH"])
def update_company_pipeline_stage(company_id):
    payload = request.get_json(silent=True) or {}
    stage_value = payload.get("pipelineStage") or payload.get("stage")
    if not stage_value:
        return jsonify({"error": "pipelineStage is required"}), 400

    stage = _crm_deal_stage_to_frontend(stage_value)
    conn = connect()
    try:
        company = conn.execute("SELECT id, company_name FROM crm_companies WHERE id = ?", (company_id,)).fetchone()
        if not company:
            abort(404)

        conn.execute("UPDATE crm_companies SET pipeline_stage = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (stage.title(), company_id))
        add_activity(conn, company_id, "company", "Pipeline stage updated", f"Updated pipeline stage for {company['company_name']} to {stage.title()}")
        conn.commit()
        row = conn.execute("SELECT id, company_name, pipeline_stage FROM crm_companies WHERE id = ?", (company_id,)).fetchone()
        return jsonify({"success": True, "company": _row_to_dict(row)})
    finally:
        conn.close()


@app.route("/api/crm/companies/<int:company_id>/contacts/discover", methods=["POST"])
def discover_company_contacts(company_id):
    conn = connect()
    try:
        company = conn.execute("SELECT id, company_name FROM crm_companies WHERE id = ?", (company_id,)).fetchone()
        if not company:
            abort(404)

        add_activity(conn, company_id, "contact", "Contact discovery started", f"Started public contact discovery for {company['company_name']}")
        conn.commit()

        try:
            profiles, imported_count, updated_count, duplicates_skipped = _discover_contacts_for_company(conn, company_id, company["company_name"])
        except Exception as exc:
            message = str(exc).strip() or "The public discovery provider rejected the request."
            lowered_message = message.lower()
            if (
                "nameresolutionerror" in lowered_message
                or "getaddrinfo" in lowered_message
                or "failed to resolve" in lowered_message
                or "max retries exceeded" in lowered_message
                or "timed out" in lowered_message
                or "timeout" in lowered_message
                or "readtimeout" in lowered_message
                or "connecttimeout" in lowered_message
            ):
                message = "The public discovery service could not be reached from this environment."
            add_activity(conn, company_id, "contact", "Enrichment failed", f"Contact discovery failed for {company['company_name']}: {message}")
            conn.commit()
            return jsonify({"success": False, "error": f"Contact discovery failed: {message}"}), 502

        if imported_count:
            add_activity(conn, company_id, "contact", "Contacts imported", f"Imported {imported_count} discovered contacts for {company['company_name']}")
        if updated_count:
            add_activity(conn, company_id, "contact", "Contacts updated", f"Updated {updated_count} discovered contacts for {company['company_name']}")
        if duplicates_skipped:
            add_activity(conn, company_id, "contact", "Duplicates skipped", f"Skipped {duplicates_skipped} duplicate contacts for {company['company_name']}")
        add_activity(conn, company_id, "contact", "Enrichment completed", f"Completed contact discovery for {company['company_name']}")
        conn.commit()

        return jsonify({
            "success": True,
            "company_id": company_id,
            "profiles_found": len(profiles),
            "imported_count": imported_count,
            "updated_count": updated_count,
            "duplicates_skipped": duplicates_skipped,
        })
    finally:
        conn.close()


@app.route("/api/outreach/status")
def outreach_status():
    return jsonify(_outreach_status_payload())


@app.route("/api/crm/outreach/templates")
def list_outreach_templates():
    return jsonify({"success": True, "templates": _build_template_catalog()})


@app.route("/api/crm/companies/<int:company_id>/outreach/build", methods=["POST"])
def build_outreach_email(company_id):
    payload = request.get_json(silent=True) or {}
    contact_ids = payload.get("contact_ids") or []
    if isinstance(contact_ids, int):
        contact_ids = [contact_ids]
    contact_ids = [int(item) for item in contact_ids if str(item).strip()]

    conn = connect()
    try:
        company = conn.execute("SELECT id, company_name FROM crm_companies WHERE id = ?", (company_id,)).fetchone()
        if not company:
            abort(404)

        contact_id = payload.get("contact_id")
        if contact_id is not None and str(contact_id).strip():
            contact_id = int(contact_id)
        else:
            contact_id = None
        recipient = (payload.get("recipient") or "").strip()
        recipient_name = (payload.get("recipient_name") or "").strip()
        sender_name = (payload.get("sender_name") or _default_sender_name()).strip()
        sender_email = (payload.get("sender_email") or _default_sender_email()).strip()
        preview_data = _build_outreach_preview(conn, company_id, payload.get("template_key") or "introduction", contact_ids, sender_name, sender_email, recipient, recipient_name, contact_id)
        add_activity(conn, company_id, "email", "Email drafted", f"Drafted {preview_data['template']} for {company['company_name']}")
        conn.commit()
        return jsonify({"success": True, "subject": preview_data["subject"], "body": preview_data["body"], "recipient": preview_data["recipient"], "recipientName": preview_data["recipient_name"], "senderName": preview_data["sender_name"], "senderEmail": preview_data["sender_email"], "template": preview_data["template"], "contact_count": len(contact_ids), "warning": preview_data.get("warning_message")})
    finally:
        conn.close()


@app.route("/api/crm/companies/<int:company_id>/outreach/drafts", methods=["POST"])
def save_outreach_draft(company_id):
    payload = _coerce_request_payload()
    subject = (payload.get("subject") or "Draft email").strip()
    body = (payload.get("body") or "").strip()
    if not subject or not body:
        return jsonify({"error": "subject and body are required"}), 400

    conn = connect()
    try:
        company = conn.execute("SELECT id, company_name FROM crm_companies WHERE id = ?", (company_id,)).fetchone()
        if not company:
            abort(404)

        details = _resolve_outreach_persist_details(conn, company_id, company["company_name"], payload, template_key=payload.get("template_key") or "introduction", sender_name=(payload.get("sender_name") or _default_sender_name()).strip(), sender_email=(payload.get("sender_email") or _default_sender_email()).strip())
        body_with_signature = _append_signature(details["body"], sender_name=details["sender_name"], sender_email=details["sender_email"])
        draft_id = payload.get("id")
        request_id = details.get("request_id")
        existing = None
        if request_id:
            existing = conn.execute(
                "SELECT id, status FROM crm_outreach_emails WHERE crm_company_id = ? AND client_request_id = ? ORDER BY created_at DESC LIMIT 1",
                (company_id, request_id),
            ).fetchone()

        if draft_id:
            conn.execute(
                """
                UPDATE crm_outreach_emails
                SET subject = ?, body = ?, recipient = ?, recipient_name = ?, sender_name = ?, sender_email = ?, template_key = ?, template_name = ?, company_name = ?, contact_name = ?, crm_contact_id = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND crm_company_id = ?
                """,
                (details["subject"], body_with_signature, details["recipient"], details["recipient_name"], details["sender_name"], details["sender_email"], details["template_key"], details["template_name"], details["company_name"], details["contact_name"], details["contact_id"], int(draft_id), company_id),
            )
            row_id = int(draft_id)
            add_activity(conn, company_id, "email", "Draft updated", f"Updated draft for {company['company_name']}")
        elif existing and existing["status"] != "sent":
            conn.execute(
                """
                UPDATE crm_outreach_emails
                SET subject = ?, body = ?, recipient = ?, recipient_name = ?, sender_name = ?, sender_email = ?, template_key = ?, template_name = ?, company_name = ?, contact_name = ?, crm_contact_id = ?, client_request_id = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND crm_company_id = ?
                """,
                (details["subject"], body_with_signature, details["recipient"], details["recipient_name"], details["sender_name"], details["sender_email"], details["template_key"], details["template_name"], details["company_name"], details["contact_name"], details["contact_id"], request_id, int(existing["id"]), company_id),
            )
            row_id = int(existing["id"])
            add_activity(conn, company_id, "email", "Draft updated", f"Updated draft for {company['company_name']}")
        else:
            cursor = conn.execute(
                """
                INSERT INTO crm_outreach_emails (crm_company_id, crm_contact_id, template_key, template_name, subject, body, recipient, recipient_name, sender_name, sender_email, company_name, contact_name, status, client_request_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (company_id, details["contact_id"], details["template_key"], details["template_name"], details["subject"], body_with_signature, details["recipient"], details["recipient_name"], details["sender_name"], details["sender_email"], details["company_name"], details["contact_name"], "draft", request_id),
            )
            row_id = int(cursor.lastrowid)
            add_activity(conn, company_id, "email", "Email drafted", f"Saved draft for {company['company_name']}")

        conn.commit()
        return jsonify({"success": True, "draft_id": row_id, "status": "draft"})
    finally:
        conn.close()


@app.route("/api/crm/companies/<int:company_id>/outreach/send", methods=["POST"])
def send_outreach_email(company_id):
    payload = _coerce_request_payload()
    subject = (payload.get("subject") or "Email").strip()
    body = (payload.get("body") or "").strip()
    recipient = (payload.get("recipient") or "").strip()
    if not subject or not body:
        return jsonify({"success": False, "error": "subject and body are required"}), 400

    conn = connect()
    try:
        company = conn.execute("SELECT id, company_name FROM crm_companies WHERE id = ?", (company_id,)).fetchone()
        if not company:
            abort(404)

        details = _resolve_outreach_persist_details(conn, company_id, company["company_name"], payload, template_key=payload.get("template_key") or "introduction", sender_name=(payload.get("sender_name") or _default_sender_name()).strip(), sender_email=(payload.get("sender_email") or _default_sender_email()).strip())
        sender_name = details["sender_name"]
        sender_email = details["sender_email"]
        from_email = (payload.get("from_email") or _default_from_email()).strip()
        request_id = details.get("request_id")
        if request_id:
            existing = conn.execute(
                "SELECT id, status, message_id FROM crm_outreach_emails WHERE crm_company_id = ? AND client_request_id = ? ORDER BY created_at DESC LIMIT 1",
                (company_id, request_id),
            ).fetchone()
            if existing and existing["status"] == "sent":
                return jsonify({"success": True, "status": "sent", "email_id": int(existing["id"]), "message_id": existing["message_id"], "duplicate": True})

        body_with_signature = _append_signature(details["body"], sender_name=sender_name, sender_email=sender_email)
        success, message_id, error_message = _send_via_resend(details["subject"], body_with_signature, details["recipient"], from_email, sender_name, sender_email)
        status = "sent" if success else "failed"

        existing_row_id = None
        if request_id:
            existing_row = conn.execute(
                "SELECT id FROM crm_outreach_emails WHERE crm_company_id = ? AND client_request_id = ? ORDER BY created_at DESC LIMIT 1",
                (company_id, request_id),
            ).fetchone()
            if existing_row:
                existing_row_id = int(existing_row["id"])

        if existing_row_id is not None:
            conn.execute(
                """
                UPDATE crm_outreach_emails
                SET crm_contact_id = ?, template_key = ?, template_name = ?, subject = ?, body = ?, recipient = ?, recipient_name = ?, sender_name = ?, sender_email = ?, from_email = ?, company_name = ?, contact_name = ?, status = ?, message_id = ?, error_message = ?, client_request_id = ?, sent_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND crm_company_id = ?
                """,
                (
                    details["contact_id"],
                    details["template_key"],
                    details["template_name"],
                    details["subject"],
                    body_with_signature,
                    details["recipient"],
                    details["recipient_name"],
                    sender_name,
                    sender_email,
                    from_email,
                    details["company_name"],
                    details["contact_name"],
                    status,
                    message_id,
                    error_message,
                    request_id,
                    existing_row_id,
                    company_id,
                ),
            )
            row_id = existing_row_id
        else:
            row = conn.execute(
                """
                INSERT INTO crm_outreach_emails (crm_company_id, crm_contact_id, template_key, template_name, subject, body, recipient, recipient_name, sender_name, sender_email, from_email, company_name, contact_name, status, message_id, error_message, client_request_id, sent_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                (
                    company_id,
                    details["contact_id"],
                    details["template_key"],
                    details["template_name"],
                    details["subject"],
                    body_with_signature,
                    details["recipient"],
                    details["recipient_name"],
                    sender_name,
                    sender_email,
                    from_email,
                    details["company_name"],
                    details["contact_name"],
                    status,
                    message_id,
                    error_message,
                    request_id,
                ),
            )
            row_id = int(row.lastrowid)

        if success:
            add_activity(conn, company_id, "email", "Email sent", f"Sent outreach email for {company['company_name']}")
        else:
            add_activity(conn, company_id, "email", "Email failed", f"Failed to send outreach email for {company['company_name']}: {error_message}")
        conn.commit()
        return jsonify({"success": success, "status": status, "email_id": row_id, "message_id": message_id, "error": error_message})
    finally:
        conn.close()


@app.route("/api/crm/companies/<int:company_id>/outreach/history")
def get_outreach_history(company_id):
    conn = connect()
    try:
        company = conn.execute("SELECT id, company_name FROM crm_companies WHERE id = ?", (company_id,)).fetchone()
        if not company:
            abort(404)
        rows = conn.execute(
            "SELECT id, crm_company_id, crm_contact_id, template_key, template_name, subject, body, recipient, recipient_name, sender_name, sender_email, from_email, company_name, contact_name, status, message_id, error_message, created_at, updated_at, sent_at FROM crm_outreach_emails WHERE crm_company_id = ? ORDER BY created_at DESC",
            (company_id,),
        ).fetchall()
        items = [
            {
                "id": int(row["id"]),
                "companyId": int(row["crm_company_id"]),
                "contactId": int(row["crm_contact_id"]) if row["crm_contact_id"] is not None else None,
                "templateKey": row["template_key"],
                "templateName": row["template_name"] or row["template_key"],
                "subject": row["subject"],
                "body": row["body"],
                "recipient": row["recipient"],
                "recipientName": row["recipient_name"],
                "senderName": row["sender_name"],
                "senderEmail": row["sender_email"],
                "fromEmail": row["from_email"],
                "companyName": row["company_name"],
                "contactName": row["contact_name"],
                "status": row["status"],
                "messageId": row["message_id"],
                "errorMessage": row["error_message"],
                "createdAt": row["created_at"],
                "updatedAt": row["updated_at"],
                "sentAt": row["sent_at"],
            }
            for row in rows
        ]
        return jsonify({"success": True, "items": items})
    finally:
        conn.close()


@app.route("/api/crm/contacts/outreach/summary")
def get_contact_outreach_summary():
    conn = connect()
    try:
        rows = conn.execute(
            "SELECT crm_contact_id, status, subject, created_at FROM crm_outreach_emails WHERE crm_contact_id IS NOT NULL ORDER BY created_at DESC",
            (),
        ).fetchall()
        latest_by_contact = {}
        for row in rows:
            contact_id = int(row["crm_contact_id"])
            if contact_id not in latest_by_contact:
                latest_by_contact[contact_id] = {
                    "contactId": contact_id,
                    "status": row["status"],
                    "subject": row["subject"],
                    "sentAt": row["created_at"],
                }
        return jsonify({"success": True, "items": list(latest_by_contact.values())})
    finally:
        conn.close()


@app.route("/api/crm/companies/<int:company_id>/contacts", methods=["POST"])
def add_company_contact(company_id):
    payload = request.get_json(silent=True) or {}
    full_name = (payload.get("full_name") or payload.get("name") or "Primary Contact").strip()
    if not full_name:
        return jsonify({"error": "full_name is required"}), 400

    conn = connect()
    try:
        company = conn.execute("SELECT id FROM crm_companies WHERE id = ?", (company_id,)).fetchone()
        if not company:
            abort(404)

        contact_id = create_contact(conn, company_id, payload)
        add_activity(conn, company_id, "contact", "Contact added", f"Added contact {full_name}")
        conn.commit()
        contact = conn.execute("SELECT id, crm_company_id, full_name, role, department, email, phone, source, created_at FROM crm_contacts WHERE id = ?", (contact_id,)).fetchone()
        return jsonify({"success": True, "contact": _row_to_dict(contact)})
    finally:
        conn.close()


@app.route("/api/crm/companies/<int:company_id>/tasks", methods=["POST"])
def add_company_task(company_id):
    payload = request.get_json(silent=True) or {}
    title = (payload.get("title") or payload.get("name") or "Follow up").strip()
    if not title:
        return jsonify({"error": "title is required"}), 400

    conn = connect()
    try:
        company = conn.execute("SELECT id FROM crm_companies WHERE id = ?", (company_id,)).fetchone()
        if not company:
            abort(404)

        task_id = create_task(conn, company_id, payload)
        add_activity(conn, company_id, "task", "Task assigned", f"Assigned task {title}")
        conn.commit()
        task = conn.execute("SELECT id, crm_company_id, title, description, task_type, status, priority, due_date, assigned_to, completed_at, created_at FROM crm_tasks WHERE id = ?", (task_id,)).fetchone()
        return jsonify({"success": True, "task": _row_to_dict(task)})
    finally:
        conn.close()


@app.route("/api/crm/companies/<int:company_id>/notes", methods=["POST"])
def add_company_note(company_id):
    payload = request.get_json(silent=True) or {}
    body = (payload.get("body") or "").strip()
    if not body:
        return jsonify({"error": "body is required"}), 400

    conn = connect()
    try:
        company = conn.execute("SELECT id FROM crm_companies WHERE id = ?", (company_id,)).fetchone()
        if not company:
            abort(404)

        note_id = add_note(conn, company_id, body)
        add_activity(conn, company_id, "note", "Note created", body)
        conn.commit()
        note = conn.execute("SELECT id, crm_company_id, body, created_at FROM crm_notes WHERE id = ?", (note_id,)).fetchone()
        return jsonify({"success": True, "note": _row_to_dict(note)})
    finally:
        conn.close()


@app.route("/api/crm/companies/<int:company_id>/tasks/<int:task_id>/complete", methods=["POST"])
def complete_company_task(company_id, task_id):
    conn = connect()
    try:
        company = conn.execute("SELECT id FROM crm_companies WHERE id = ?", (company_id,)).fetchone()
        if not company:
            abort(404)

        task = complete_task(conn, company_id, task_id)
        conn.commit()
        return jsonify({"success": True, "task": _row_to_dict(task)})
    except LookupError:
        return jsonify({"error": "task not found"}), 404
    finally:
        conn.close()


@app.route("/api/crm/companies/<int:company_id>/tasks/<int:task_id>", methods=["PATCH"])
def update_company_task(company_id, task_id):
    payload = request.get_json(silent=True) or {}
    allowed = {"title", "description", "task_type", "status", "priority", "due_date", "assigned_to"}
    updates = {k: payload.get(k) for k in allowed if k in payload}

    if not updates:
        return jsonify({"error": "no updatable fields provided"}), 400

    conn = connect()
    try:
        task = conn.execute("SELECT * FROM crm_tasks WHERE id = ? AND crm_company_id = ?", (task_id, company_id)).fetchone()
        if not task:
            abort(404)

        set_clause = ", ".join([f"{k} = ?" for k in updates.keys()])
        params = list(updates.values()) + [task_id, company_id]
        sql = f"UPDATE crm_tasks SET {set_clause}, updated_at = CURRENT_TIMESTAMP WHERE id = ? AND crm_company_id = ?"
        conn.execute(sql, tuple(params))

        if "status" in updates:
            if updates.get("status") == "completed":
                conn.execute("UPDATE crm_tasks SET completed_at = ? WHERE id = ?", (datetime.now(timezone.utc).replace(microsecond=0).isoformat(), task_id))
                add_activity(conn, company_id, "task", "Task completed", f"Completed task: {updates.get('title') or task['title']}")
            else:
                conn.execute("UPDATE crm_tasks SET completed_at = NULL WHERE id = ?", (task_id,))
                add_activity(conn, company_id, "task", "Task reopened", f"Reopened task: {updates.get('title') or task['title']}")
        else:
            add_activity(conn, company_id, "task", "Task updated", f"Updated task: {updates.get('title') or task['title']}")

        conn.commit()
        updated = conn.execute("SELECT id, crm_company_id, title, description, task_type, status, priority, due_date, assigned_to, completed_at, created_at FROM crm_tasks WHERE id = ?", (task_id,)).fetchone()
        return jsonify({"success": True, "task": _row_to_dict(updated)})
    finally:
        conn.close()


@app.route("/api/crm/companies/<int:company_id>/tasks/<int:task_id>", methods=["DELETE"])
def delete_company_task(company_id, task_id):
    conn = connect()
    try:
        task = conn.execute("SELECT id, title FROM crm_tasks WHERE id = ? AND crm_company_id = ?", (task_id, company_id)).fetchone()
        if not task:
            abort(404)
        conn.execute("DELETE FROM crm_tasks WHERE id = ? AND crm_company_id = ?", (task_id, company_id))
        add_activity(conn, company_id, "task", "Task deleted", f"Deleted task: {task['title']}")
        conn.commit()
        return jsonify({"success": True})
    finally:
        conn.close()


@app.route("/api/crm/companies/<int:company_id>/intelligence", methods=["GET"])
def get_company_intelligence(company_id):
    conn = connect()
    try:
        intelligence = _infer_company_intelligence(conn, company_id, force_refresh=False)
        return jsonify({"success": True, "intelligence": intelligence})
    except LookupError:
        abort(404)
    finally:
        conn.close()


@app.route("/api/crm/companies/<int:company_id>/intelligence/refresh", methods=["POST"])
def refresh_company_intelligence(company_id):
    conn = connect()
    try:
        intelligence = _infer_company_intelligence(conn, company_id, force_refresh=True)
        return jsonify({"success": True, "intelligence": intelligence})
    except LookupError:
        abort(404)
    finally:
        conn.close()


@app.route("/api/crm/companies/<int:company_id>/reports/generate", methods=["POST"])
def generate_company_report(company_id):
    conn = connect()
    try:
        report_payload = _build_company_report_payload(conn, company_id)
        report_doc = _persist_report(conn, company_id, "company", f"{report_payload['company_name']} — Company Report", report_payload, report_payload.get("executive_summary"))
        conn.commit()
        return jsonify({"success": True, "report": report_doc})
    except LookupError:
        abort(404)
    finally:
        conn.close()


@app.route("/api/crm/companies/<int:company_id>/reports", methods=["GET"])
def list_company_reports(company_id):
    conn = connect()
    try:
        reports = _load_reports(conn, company_id)
        return jsonify({"reports": reports})
    finally:
        conn.close()


@app.route("/api/reports/operations/generate", methods=["POST"])
def generate_operations_report():
    conn = connect()
    try:
        report_payload = _build_operations_report_payload(conn)
        report_doc = _persist_report(conn, None, "operations", "Operations Report", report_payload, report_payload.get("executive_summary"))
        conn.commit()
        return jsonify({"success": True, "report": report_doc})
    finally:
        conn.close()


@app.route("/api/reports", methods=["GET"])
def list_reports():
    conn = connect()
    try:
        return jsonify({"reports": _load_reports(conn)})
    finally:
        conn.close()


@app.route("/api/reports/<int:report_id>", methods=["GET"])
def get_report(report_id):
    conn = connect()
    try:
        row = conn.execute("SELECT id, crm_company_id, report_type, report_name, version, generated_by, generated_at, report_data, executive_summary, status, metadata FROM crm_reports WHERE id = ?", (report_id,)).fetchone()
        if not row:
            abort(404)
        return jsonify({
            "report": {
                "id": int(row["id"]),
                "crm_company_id": int(row["crm_company_id"]) if row["crm_company_id"] is not None else None,
                "report_type": row["report_type"],
                "report_name": row["report_name"],
                "version": row["version"],
                "generated_by": row["generated_by"],
                "generated_at": row["generated_at"],
                "report_data": json.loads(row["report_data"] or "{}"),
                "executive_summary": row["executive_summary"],
                "status": row["status"],
                "metadata": json.loads(row["metadata"] or "{}"),
            }
        })
    finally:
        conn.close()


@app.route("/api/reports/<int:report_id>/export", methods=["POST"])
def export_report(report_id):
    payload = request.get_json(silent=True) or {}
    fmt = (payload.get("format") or "markdown").lower()
    conn = connect()
    try:
        row = conn.execute("SELECT id, report_data, executive_summary, report_name FROM crm_reports WHERE id = ?", (report_id,)).fetchone()
        if not row:
            abort(404)
        report_data = json.loads(row["report_data"] or "{}")
        executive_summary = report_data.get("executive_summary") or row["executive_summary"] or ""
        company_name = report_data.get("company_name") or report_data.get("summary", {}).get("company_name") or row["report_name"]
        recommended_services = report_data.get("commercial_opportunity", {}).get("recommended_services") or report_data.get("service_opportunities") or []
        risks = report_data.get("risk_assessment", {}).get("risks") or report_data.get("risk_analysis", {}).get("potential_risks") or []
        action_plan = report_data.get("action_plan") or {}

        def _format_list(items):
            if not items:
                return "- None listed"
            return "\n".join(f"- {item}" for item in items if item)

        if fmt == "pdf":
            content = f"# {row['report_name']}\n\n## Executive Summary\n\n{executive_summary}\n\n## Company Focus\n\n- Company: {company_name}\n- Priority Score: {report_data.get('commercial_opportunity', {}).get('priority_score', 'N/A')}\n- Opportunity Type: {report_data.get('commercial_assessment', {}).get('commercial_opportunity', 'N/A')}\n\n## Recommended Services\n\n{_format_list([service.get('service') if isinstance(service, dict) else str(service) for service in recommended_services])}\n\n## Risk Assessment\n\n{_format_list(risks)}\n\n## Action Plan\n\n{_format_list([value for values in action_plan.values() if isinstance(values, list) for value in values])}\n"
        elif fmt == "docx":
            content = f"# {row['report_name']}\n\n## Executive Summary\n\n{executive_summary}\n\n## Recommended Services\n\n{_format_list([service.get('service') if isinstance(service, dict) else str(service) for service in recommended_services])}\n"
        else:
            content = f"# {row['report_name']}\n\n## Executive Summary\n\n{executive_summary}\n\n## Recommended Services\n\n{_format_list([service.get('service') if isinstance(service, dict) else str(service) for service in recommended_services])}\n\n## Risk Assessment\n\n{_format_list(risks)}\n\n## Action Plan\n\n{_format_list([value for values in action_plan.values() if isinstance(values, list) for value in values])}\n"
        return jsonify({"success": True, "format": fmt, "content": content, "download_name": f"{row['report_name'].lower().replace(' ', '-')}.{fmt}"})
    finally:
        conn.close()


@app.route("/api/crm/companies/<int:company_id>/deals", methods=["POST"])
def add_company_deal(company_id):
    payload = request.get_json(silent=True) or {}
    title = (payload.get("title") or "New deal").strip()
    if not title:
        return jsonify({"error": "title is required"}), 400

    conn = connect()
    try:
        company = conn.execute("SELECT id FROM crm_companies WHERE id = ?", (company_id,)).fetchone()
        if not company:
            abort(404)

        stage = _crm_deal_stage_to_frontend(payload.get("stage"))
        value = int(payload.get("value") or 0)
        probability = max(0, min(100, int(payload.get("probability") or 0)))
        expected_close_at = payload.get("expectedCloseAt") or payload.get("expected_close_at")
        owner = (payload.get("owner") or "MedNovaOS").strip() or "MedNovaOS"
        description = (payload.get("description") or "").strip()
        contact_id = payload.get("contactId") or payload.get("contact_id")
        if contact_id is not None and contact_id != "":
            contact = conn.execute("SELECT id FROM crm_contacts WHERE id = ? AND crm_company_id = ?", (int(contact_id), company_id)).fetchone()
            if not contact:
                contact_id = None
            else:
                contact_id = int(contact_id)
        else:
            contact_id = None

        cursor = conn.execute(
            """
            INSERT INTO crm_deals (
                crm_company_id, crm_contact_id, title, stage, value, currency, probability, expected_close_at, owner, description
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (company_id, contact_id, title, stage, value, payload.get("currency") or "NGN", probability, expected_close_at, owner, description),
        )
        deal_id = int(cursor.lastrowid)
        add_activity(conn, company_id, "deal", "Deal created", f"Created deal {title} in {stage} stage")
        conn.commit()
        row = conn.execute("SELECT * FROM crm_deals WHERE id = ?", (deal_id,)).fetchone()
        return jsonify({"success": True, "deal": _crm_deal_payload_from_row(row)})
    finally:
        conn.close()


@app.route("/api/crm/companies/<int:company_id>/deals/<int:deal_id>", methods=["PATCH"])
def update_company_deal(company_id, deal_id):
    payload = request.get_json(silent=True) or {}
    conn = connect()
    try:
        deal = conn.execute("SELECT * FROM crm_deals WHERE id = ? AND crm_company_id = ?", (deal_id, company_id)).fetchone()
        if not deal:
            abort(404)

        updates = {}
        if "title" in payload:
            updates["title"] = (payload.get("title") or "New deal").strip()
        if "stage" in payload:
            updates["stage"] = _crm_deal_stage_to_frontend(payload.get("stage"))
        if "value" in payload:
            updates["value"] = int(payload.get("value") or 0)
        if "probability" in payload:
            updates["probability"] = max(0, min(100, int(payload.get("probability") or 0)))
        if "expectedCloseAt" in payload:
            updates["expected_close_at"] = payload.get("expectedCloseAt")
        if "expected_close_at" in payload:
            updates["expected_close_at"] = payload.get("expected_close_at")
        if "owner" in payload:
            updates["owner"] = (payload.get("owner") or "MedNovaOS").strip() or "MedNovaOS"
        if "description" in payload:
            updates["description"] = (payload.get("description") or "").strip()
        if "contactId" in payload or "contact_id" in payload:
            contact_value = payload.get("contactId", payload.get("contact_id"))
            if contact_value in {None, ""}:
                updates["crm_contact_id"] = None
            else:
                contact = conn.execute("SELECT id FROM crm_contacts WHERE id = ? AND crm_company_id = ?", (int(contact_value), company_id)).fetchone()
                if contact:
                    updates["crm_contact_id"] = int(contact_value)
                else:
                    updates["crm_contact_id"] = None
        if not updates:
            return jsonify({"error": "no updatable fields provided"}), 400

        set_clause = ", ".join([f"{key} = ?" for key in updates.keys()])
        params = list(updates.values()) + [deal_id, company_id]
        conn.execute(f"UPDATE crm_deals SET {set_clause}, updated_at = CURRENT_TIMESTAMP WHERE id = ? AND crm_company_id = ?", tuple(params))
        if "stage" in payload and payload.get("stage") is not None and _crm_deal_stage_to_frontend(payload.get("stage")) != deal["stage"]:
            if updates["stage"] in {"won", "lost"}:
                title = "Deal won" if updates["stage"] == "won" else "Deal lost"
                add_activity(conn, company_id, "deal", title, f"{title} deal {deal['title']}")
            else:
                add_activity(conn, company_id, "deal", "Deal moved", f"Moved deal {deal['title']} to {updates['stage']}")
        else:
            add_activity(conn, company_id, "deal", "Deal updated", f"Updated deal {deal['title']}")
        conn.commit()
        row = conn.execute("SELECT * FROM crm_deals WHERE id = ?", (deal_id,)).fetchone()
        return jsonify({"success": True, "deal": _crm_deal_payload_from_row(row)})
    finally:
        conn.close()


@app.route("/api/crm/companies/<int:company_id>/deals/<int:deal_id>", methods=["DELETE"])
def delete_company_deal(company_id, deal_id):
    conn = connect()
    try:
        deal = conn.execute("SELECT id, title FROM crm_deals WHERE id = ? AND crm_company_id = ?", (deal_id, company_id)).fetchone()
        if not deal:
            abort(404)
        conn.execute("DELETE FROM crm_deals WHERE id = ? AND crm_company_id = ?", (deal_id, company_id))
        add_activity(conn, company_id, "deal", "Deal deleted", f"Deleted deal {deal['title']}")
        conn.commit()
        return jsonify({"success": True})
    finally:
        conn.close()


@app.route("/api/crm/companies/from-opportunity", methods=["POST"])
def add_company_to_crm():
    payload = request.get_json(silent=True) or {}
    company_name = (payload.get("company_name") or payload.get("company") or "").strip()
    if not company_name:
        return jsonify({"error": "company_name is required"}), 400

    conn = connect()
    try:
        company_id, company_data, created = _upsert_crm_company(conn, company_name, payload)
        company_row = conn.execute(
            "SELECT id, company_name, country, opportunity_score, portfolio_summary, opportunity_status, pipeline_stage, created_at FROM crm_companies WHERE id = ?",
            (company_id,),
        ).fetchone()
        return jsonify({
            "success": True,
            "company_id": company_id,
            "company_name": company_row["company_name"] if company_row else company_data["company_name"],
            "created": created,
            "exists": not created,
            "message": "Company added successfully" if created else "This company already exists in your CRM.",
            "status": "created" if created else "exists",
            "company": dict(company_row) if company_row else None,
        })
    finally:
        conn.close()


@app.route("/admin/sync", methods=["POST"])
def admin_sync():
    summary = run_sync()
    return jsonify(summary)

@app.route("/api/dashboard/sync/greenbook", methods=["POST"])
def dashboard_greenbook_sync():
    summary = run_sync()
    return jsonify({
        "success": True,
        "summary": summary,
        "status": summary.get("status", "success"),
        "message": "Green Book sync completed successfully." if summary.get("status") == "success" else "Green Book sync completed with issues.",
    })


@app.route("/admin/sync/status")
def admin_sync_status():
    conn = connect()
    try:
        last_sync = conn.execute("SELECT started_at, status, products_added, products_updated, products_removed, duration_seconds, error_message FROM sync_history ORDER BY id DESC LIMIT 1").fetchone()
        product_count = conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]
        return jsonify({
            "last_sync": dict(last_sync) if last_sync else None,
            "running": False,
            "failed": bool(last_sync and last_sync["status"] == "failed"),
            "products": product_count,
            "last_duration": int(last_sync["duration_seconds"] or 0) if last_sync else 0,
            "database_size": 0,
        })
    finally:
        conn.close()


@app.route("/admin/cloud-sync", methods=["POST"])
def admin_cloud_sync():
    summary = sync_sqlite_to_supabase()
    return jsonify(summary)


@app.route("/admin/cloud-sync/status")
def admin_cloud_sync_status():
    from backend.cloud.sync_to_supabase import get_last_cloud_sync_summary

    return jsonify(get_last_cloud_sync_summary())


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
