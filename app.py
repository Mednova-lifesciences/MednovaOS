from __future__ import annotations

import json
import os
import re
import sqlite3
import uuid
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from time import perf_counter
from typing import Any
from urllib.parse import quote_plus, urlparse

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from flask import Flask, abort, jsonify, redirect, render_template, render_template_string, request, url_for
from flask_cors import CORS

from backend.database.db import get_db
from backend.database.repositories import (
    ActivityRepository,
    CompanyRepository,
    ContactRepository,
    DealRepository,
    NoteRepository,
    OutreachRepository,
    PipelineRepository,
    ProductRepository,
    TaskRepository,
)
from backend.database.repositories.renewals import RenewalRepository
from backend.logging_utils import get_logger
from backend.services.company_service import CompanyService
from backend.services.contact_service import ContactService
from backend.services.crm_service import CRMService
from backend.services.intelligence_service import IntelligenceService
from backend.services.outreach_service import OutreachService
from backend.services.report_service import ReportService
from backend.services.task_service import TaskService
from backend.services.pipeline_service import PipelineService
from backend.sync.scheduler import SyncScheduler
from backend.sync.sync_engine import run_sync
from backend.utils import format_response, now_iso

logger = get_logger("app")

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
        load_dotenv(env_path, override=False)
    else:
        for candidate in ENV_PATHS:
            if candidate.exists():
                load_dotenv(candidate, override=False)
        if not resolved_path.exists():
            load_dotenv(override=False)

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
    print(f"OK .env loaded: {env_state['dotenvLoaded']}")
    if env_state["dotenvLoaded"]:
        print(f"OK Resend API key detected: {'yes' if env_state['resendApiKeyConfigured'] else 'no'}")
        print(f"OK Sender email configured: {'yes' if env_state['senderEmailConfigured'] else 'no'}")
        print(f"OK Sender name configured: {'yes' if env_state['senderNameConfigured'] else 'no'}")
    else:
        print("WARNING: .env not loaded")
        print("WARNING: Resend API key detected: no")
        print("WARNING: Sender email configured: no")
        print("WARNING: Sender name configured: no")


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
    data = _to_plain_dict(row) if not isinstance(row, dict) else dict(row)
    stage_value = data.get("stage") or data.get("status") or data.get("pipeline_stage") or data.get("opportunity_status")
    title_value = data.get("title") or data.get("company_name") or data.get("company") or "Deal"
    value = data.get("value") or data.get("amount") or data.get("estimated_value") or 0
    probability = data.get("probability") or 0
    return {
        "id": int(data.get("id") or data.get("opportunity_id") or 0),
        "companyId": int(data.get("crm_company_id") or data.get("company_id") or 0),
        "contactId": int(data["crm_contact_id"]) if data.get("crm_contact_id") is not None else None,
        "title": title_value,
        "stage": _crm_deal_stage_to_frontend(stage_value),
        "value": int(float(value or 0)),
        "currency": (data.get("currency") or "NGN").upper() if (data.get("currency") or "NGN") else "NGN",
        "probability": int(float(probability or 0)),
        "expectedCloseAt": data.get("expected_close_at") or data.get("expiry_date"),
        "owner": data.get("owner"),
        "description": data.get("description") or data.get("recommended_services") or "",
    }


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


def _build_growhub_pipeline_deals(companies: list[dict]) -> list[dict]:
    pipeline_service = PipelineService()
    deals: list[dict] = []
    for company in companies:
        company_payload = _to_plain_dict(company)
        company_id = int(company_payload.get("id") or 0)
        if not company_id:
            continue

        existing_deals = pipeline_service.list_deals(company_id, page=1, per_page=100).get("items", [])
        if existing_deals:
            deals.extend([_crm_deal_payload_from_row(deal) for deal in existing_deals])
            continue

        company_name = company_payload.get("company_name") or company_payload.get("name") or ""
        if not company_name:
            continue

        fallback = _build_revenue_pipeline_deal(company_id, company_name, company_payload.get("pipeline_stage"), company_payload.get("opportunity_score"))
        if fallback:
            deals.append(fallback)
    return deals


def _build_revenue_pipeline_deal(company_id: int, company_name: str, pipeline_stage: str | None, opportunity_score: int | str | None) -> dict | None:
    conn = connect()
    try:
        table_exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='revenue_pipeline' LIMIT 1"
        ).fetchone()
        if not table_exists:
            return None

        cursor = conn.execute(
            "SELECT estimated_value, category, products, recommended_services, status FROM revenue_pipeline WHERE lower(company) = ? LIMIT 1",
            (company_name.lower(),),
        )
        row = cursor.fetchone()
        if not row:
            return None

        if isinstance(row, sqlite3.Row):
            row_data = dict(row)
        else:
            columns = [column[0] for column in cursor.description] if cursor.description else []
            row_data = dict(zip(columns, row))

        value = int(float(row_data.get("estimated_value") or 0))
        probability = int(opportunity_score or 0)
        return _crm_deal_payload_from_row({
            "id": company_id,
            "crm_company_id": company_id,
            "crm_contact_id": None,
            "title": f"{company_name} opportunity",
            "stage": pipeline_stage,
            "value": value,
            "currency": "NGN",
            "probability": probability,
            "expected_close_at": None,
            "owner": "MedNovaOS",
            "description": (row_data.get("recommended_services") or "") or "",
        })
    finally:
        conn.close()


def _build_growhub_crm_dashboard_summary(companies: list[dict], deals: list[dict], tasks: list[dict]) -> dict:
    normalized_companies = [_to_plain_dict(company) for company in companies]
    active_leads = sum(
        1
        for company in normalized_companies
        if _crm_company_status_for_row(company) == "prospect"
    )
    won_clients = sum(
        1
        for company in normalized_companies
        if str(company.get("opportunity_status") or company.get("pipeline_stage") or "").strip().lower() == "won"
    )
    active_pipeline_rows = [
        row
        for row in deals
        if str(row.get("status") or row.get("stage") or "").strip().lower() not in {"won", "lost", "closed"}
    ]
    pipeline_value = sum(int(float(row.get("value") or row.get("estimated_value") or 0)) for row in active_pipeline_rows)
    weighted_pipeline_value = sum(
        int(float(row.get("value") or row.get("estimated_value") or 0)) * int(float(row.get("probability") or 0)) / 100.0
        for row in active_pipeline_rows
    )
    now = datetime.now(timezone.utc)
    tasks_due = 0
    meetings_scheduled = 0
    for task in tasks:
        task_row = _to_plain_dict(task) if not isinstance(task, dict) else dict(task)
        status = str(task_row.get("status") or "").strip().lower()
        due_date = task_row.get("due_date")
        task_type = str(task_row.get("task_type") or task_row.get("type") or "").strip().lower()
        if due_date:
            try:
                due_at = datetime.fromisoformat(str(due_date).replace("Z", "+00:00"))
                if due_at.tzinfo is None:
                    due_at = due_at.replace(tzinfo=timezone.utc)
                if status != "completed" and due_at <= now + timedelta(days=3):
                    tasks_due += 1
                if task_type == "meeting" and due_at >= now:
                    meetings_scheduled += 1
            except Exception:
                pass

    return {
        "companiesAdded": len(normalized_companies),
        "activeLeads": active_leads,
        "activeOpportunities": len(active_pipeline_rows),
        "wonClients": won_clients,
        "tasksDue": tasks_due,
        "meetingsScheduled": meetings_scheduled,
        "pipelineValue": pipeline_value,
        "weightedPipelineValue": int(weighted_pipeline_value),
    }


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


def _is_generic_or_placeholder_email(email: str) -> bool:
    normalized = email.strip().lower()
    if not normalized:
        return True
    generic_domains = {"example.com", "example.org", "example.net", "test.com", "test.org", "localhost"}
    local_part = normalized.split("@", 1)[0] if "@" in normalized else normalized
    domain = normalized.split("@", 1)[1] if "@" in normalized else ""
    if any(token in normalized for token in ["example.", "test.", "localhost", "noreply@", "no-reply@", "do-not-reply@", "admin@", "contact@", "hello@", "info@"]):
        return True
    if domain in generic_domains:
        return True
    return False


def _is_placeholder_contact_record(contact: dict | Any | None, company_name: str = "") -> bool:
    if not contact:
        return True

    payload = _to_plain_dict(contact)
    full_name = _normalize_contact_value(payload.get("full_name") or payload.get("name") or "")
    role = _normalize_contact_value(payload.get("role") or "")
    email = _normalize_contact_value(payload.get("email") or "")
    phone = _normalize_contact_value(payload.get("phone") or "")

    if not full_name and not role:
        return True
    if _is_placeholder_contact_name(full_name, company_name):
        return True
    placeholder_roles = {"public contact", "primary contact", "company contact", "commercial lead", "lead"}
    if role.lower() in placeholder_roles and not (email or phone):
        return True
    if _is_generic_or_placeholder_email(email) and not phone:
        return True
    return False


def _cleanup_placeholder_contacts(company_id: int, company_name: str) -> int:
    contact_service = ContactService()
    contacts = [_to_plain_dict(contact) for contact in contact_service.list_contacts(company_id, page=1, per_page=1000).get("items", [])]
    discovered_contacts = [
        contact
        for contact in contacts
        if (contact.get("source") or "").strip().lower() == "discovered"
        and ((contact.get("email") or "").strip() or (contact.get("phone") or "").strip() or (contact.get("linkedin_url") or "").strip())
    ]
    if not discovered_contacts:
        return 0

    deleted_count = 0
    for contact in contacts:
        if contact in discovered_contacts:
            continue
        if _is_placeholder_contact_record(contact, company_name):
            contact_id = int(contact.get("id") or 0)
            if contact_id and contact_service.delete_contact(contact_id):
                deleted_count += 1

    return deleted_count


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


def _to_plain_dict(value: Any) -> dict:
    if value is None:
        return {}
    if isinstance(value, dict):
        return dict(value)
    if hasattr(value, "__dict__") and not isinstance(value, (str, int, float, bool)):
        return {key: val for key, val in vars(value).items() if not key.startswith("_")}
    return {}


def _get_sqlite_db_path() -> Path:
    configured = os.getenv("MEDNOVA_DB_PATH") or os.getenv("DATABASE_PATH")
    if configured:
        return Path(configured).expanduser()
    return BASE_DIR / "database" / "nafdac_intelligence.db"


def connect() -> sqlite3.Connection:
    db_path = _get_sqlite_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(db_path, timeout=30)


def _to_plain_list(value: Any) -> list[dict]:
    if not value:
        return []
    if isinstance(value, list):
        return [_to_plain_dict(item) for item in value]
    return [_to_plain_dict(value)]


def _parse_int_query_arg(name: str, default: int, min_value: int = 1, max_value: int | None = None) -> int:
    try:
        value = int(request.args.get(name, default))
    except (TypeError, ValueError):
        value = default
    value = max(min_value, value)
    if max_value is not None:
        value = min(max_value, value)
    return value


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


def _build_outreach_preview(company_id: int, template_key: str, contact_ids: list[int] | None = None, sender_name: str = "", sender_email: str = "", recipient: str = "", recipient_name: str = "", contact_id: int | None = None) -> dict:
    templates = _build_template_catalog()
    template = next((entry for entry in templates if entry["key"] == (template_key or "introduction")), templates[0])
    context = _extract_outreach_context(None, company_id, contact_ids, sender_name or _default_sender_name(), sender_email or _default_sender_email())
    primary_contact = context.get("primary_contact")
    company_name = _normalize_contact_value(context.get("company_name") or "Company")

    def _candidate_name(contact: dict | Any | None) -> str:
        if isinstance(contact, dict):
            return _normalize_contact_value(contact.get("full_name") or "")
        return ""

    if isinstance(primary_contact, dict):
        resolved_name = _normalize_contact_value(recipient_name or primary_contact.get("full_name") or "")
        resolved_email = (recipient or primary_contact.get("email") or "").strip()
    else:
        resolved_name = _normalize_contact_value(recipient_name or "")
        resolved_email = (recipient or "").strip()

    if _is_placeholder_contact_name(resolved_name, company_name):
        resolved_name = ""

    if not resolved_email and context.get("contacts"):
        for contact in context.get("contacts") or []:
            if isinstance(contact, dict):
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


def _resolve_outreach_persist_details(company_id: int, company_name: str, payload: dict, template_key: str | None = None, sender_name: str = "", sender_email: str = "") -> dict:
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


def _extract_outreach_context(conn: Any, company_id: int, contact_ids: list[int] | None = None, sender_name: str = "", sender_email: str = "") -> dict:
    company_service = CompanyService()
    company = company_service.get_company(company_id)
    if not company:
        raise LookupError("company not found")

    company_data = _to_plain_dict(company)
    company_name = (company_data.get("company_name") or "Company").strip() or "Company"
    company_label = (company_name or "company").lower()

    def _contact_value(contact: dict | Any | None, key: str) -> str:
        if not contact:
            return ""
        payload = _to_plain_dict(contact)
        return _normalize_contact_value(payload.get(key) or "")

    def _is_placeholder_contact(contact: dict | Any | None) -> bool:
        if not contact:
            return True
        payload = _to_plain_dict(contact)
        full_name = _contact_value(payload, "full_name")
        role = _contact_value(payload, "role")
        email = _contact_value(payload, "email")
        phone = _contact_value(payload, "phone")
        if not full_name and not role:
            return True
        if full_name.lower() == f"{company_label} commercial lead" or full_name.lower() == f"{company_label} lead":
            return True
        if role.lower() in {"commercial lead", "lead"} and not (email or phone):
            return True
        return False

    contact_service = ContactService()
    contacts_payload = contact_service.list_contacts(company_id, page=1, per_page=1000)
    contacts = _to_plain_list(contacts_payload.get("items", []))

    primary_contact = None
    if contact_ids:
        requested_contacts = []
        for contact_id in contact_ids:
            match = next((contact for contact in contacts if int(contact.get("id") or 0) == int(contact_id)), None)
            if match:
                requested_contacts.append(match)
        for contact in requested_contacts:
            if not _is_placeholder_contact(contact):
                primary_contact = contact
                break

    if primary_contact is None:
        for contact in contacts:
            if _is_placeholder_contact(contact):
                continue
            if contact.get("email"):
                primary_contact = contact
                break
            if not primary_contact:
                primary_contact = contact

    if primary_contact is None:
        primary_contact = {
            "full_name": f"{company_name} Commercial Lead",
            "email": "",
            "role": "Commercial Lead",
        }
    country = company_data.get("country") or "Unknown"
    portfolio_summary = company_data.get("portfolio_summary") or ""
    opportunity_score = company_data.get("opportunity_score") or 0
    product_name = "your lead product"
    report_context = company_data.get("report_context") or ""
    if report_context:
        try:
            parsed = json.loads(report_context or "[]")
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
    emails = [match.group(0) for match in EMAIL_RE.finditer(text) if not _is_generic_or_placeholder_email(match.group(0))]
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


def _get_outreach_by_request_id(company_id: int, request_id: str):
    if not request_id:
        return None
    repository = OutreachService().outreach_repo
    records = repository.list(filters={"crm_company_id": company_id, "client_request_id": request_id}, order="created_at.desc", limit=1)
    if not records:
        return None
    return _to_plain_dict(records[0])


def _is_duplicate_contact(existing: dict, candidate: dict) -> bool:
    if not existing or not candidate:
        return False
    existing_linkedin = (existing.get("linkedin_url") or "").strip().lower()
    candidate_linkedin = (candidate.get("linkedin_url") or "").strip().lower()
    if existing_linkedin and candidate_linkedin and existing_linkedin == candidate_linkedin:
        return True

    existing_email = (existing.get("email") or "").strip().lower()
    candidate_email = (candidate.get("email") or "").strip().lower()
    if existing_email and candidate_email and existing_email == candidate_email:
        return True

    existing_phone = re.sub(r"\D+", "", (existing.get("phone") or ""))
    candidate_phone = re.sub(r"\D+", "", (candidate.get("phone") or ""))
    if existing_phone and candidate_phone and existing_phone == candidate_phone:
        return True

    existing_name = _normalize_contact_value(existing.get("full_name") or existing.get("name") or "").lower()
    candidate_name = _normalize_contact_value(candidate.get("name") or candidate.get("full_name") or "").lower()
    if existing_name and candidate_name and existing_name == candidate_name:
        return True

    return False


def _find_matching_contact(company_id: int, contact_data: dict) -> dict | None:
    if not contact_data:
        return None
    contacts = ContactService().list_contacts(company_id, page=1, per_page=200).get("items", [])
    for contact in contacts:
        existing = _to_plain_dict(contact)
        if _is_duplicate_contact(existing, contact_data):
            return existing
    return None


# `scalar` moved to `backend.legacy_sqlite.scalar`


# report table creation & migration handled via migrations/ repositories


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





def _build_company_report_payload(company_id: int) -> dict:
    company_service = CompanyService()
    pipeline_service = PipelineService()
    outreach_service = OutreachService()
    intelligence_service = IntelligenceService()

    company = company_service.get_company(company_id)
    if not company:
        raise LookupError("company not found")

    company_detail = company_service.get_company_detail(company_id) or {}
    contacts = company_detail.get("contacts") or []
    tasks = company_detail.get("tasks") or []
    activities = company_detail.get("activities") or []
    notes = company_detail.get("notes") or []

    deals = pipeline_service.list_deals(company_id, page=1, per_page=100).get("items", [])
    emails = outreach_service.list_outreach(company_id, page=1, per_page=100).get("items", [])

    # normalize dataclass/model objects to plain dicts
    company_dict = _to_plain_dict(company)
    contacts_list = [ _to_plain_dict(c) for c in contacts ]
    tasks_list = [ _to_plain_dict(t) for t in tasks ]
    activities_list = [ _to_plain_dict(a) for a in activities ]
    notes_list = [ _to_plain_dict(n) for n in notes ]
    deals_list = [ _to_plain_dict(d) for d in deals ]
    emails_list = [ _to_plain_dict(e) for e in emails ]

    products = []
    try:
        products = json.loads((company_dict.get("greenbook_products_json") or "[]") or "[]")
    except Exception:
        products = []

    active_tasks = [task for task in tasks_list if (task.get("status") or "pending") != "completed"]
    completed_tasks = [task for task in tasks_list if (task.get("status") or "pending") == "completed"]
    primary_deal = deals_list[0] if deals_list else None
    scorecard = _report_scorecard({
        "name": company_dict.get("company_name", ""),
        "opportunity_score": int(company_dict.get("opportunity_score") or 0),
        "portfolio_summary": company_dict.get("portfolio_summary") or "",
    }, primary_deal, active_tasks, emails_list)

    intelligence_obj = intelligence_service.get_intelligence(company_id)
    intel_payload = _to_plain_dict(intelligence_obj) if intelligence_obj is not None else {}
    intelligence_data = intel_payload.get("data") if isinstance(intel_payload.get("data"), dict) else intel_payload

    recommended_services = intelligence_data.get("business_opportunity", {}).get("recommended_services", []) if isinstance(intelligence_data, dict) else []
    priority_score = intelligence_data.get("business_opportunity", {}).get("priority_score", 70) if isinstance(intelligence_data, dict) else 70

    report = {
        "report_type": "company",
        "company_id": int(company_id),
        "company_name": company_dict.get("company_name"),
        "generated_at": _report_timestamp(),
        "summary": {
            "country": company_dict.get("country") or "Unknown",
            "industry": "Biopharma",
            "portfolio_summary": company_dict.get("portfolio_summary") or "",
            "pipeline_stage": company_dict.get("pipeline_stage") or "Lead",
            "opportunity_score": int(company_dict.get("opportunity_score") or 0),
            "product_count": len(products),
            "active_task_count": len(active_tasks),
            "completed_task_count": len(completed_tasks),
            "email_count": len(emails_list),
            "deal_value": int(primary_deal.get("value") or 0) if primary_deal else 0,
        },
        "company_profile": {
            "name": company_dict.get("company_name"),
            "country": company_dict.get("country") or "Unknown",
            "industry": "Biopharma",
            "website": "",
            "company_description": company_dict.get("portfolio_summary") or "",
            "greenbook_information": products[:5],
            "contacts": contacts_list,
            "company_size": "Large" if len(products) >= 8 else "Medium" if len(products) >= 3 else "Small",
        },
        "crm_information": {
            "pipeline_stage": company_dict.get("pipeline_stage") or "Lead",
            "deal_value": int(primary_deal.get("value") or 0) if primary_deal else 0,
            "owner": primary_deal.get("owner") if primary_deal else "MedNovaOS",
            "tasks": tasks_list,
            "completed_tasks": completed_tasks,
            "outstanding_tasks": active_tasks,
            "notes": notes_list,
            "timeline": activities_list,
            "emails": emails_list,
            "last_outreach": emails_list[:1],
            "next_action": active_tasks[0].get("title") if active_tasks else "Schedule follow-up",
            "probability": int(primary_deal.get("probability") or company_dict.get("opportunity_score") or 0) if primary_deal else int(company_dict.get("opportunity_score") or 0),
        },
        "commercial_assessment": {
            "why_important": f"{company_dict.get('company_name')} represents a high-value opportunity for targeted service expansion in the pharmaceutical and regulatory ecosystem.",
            "commercial_opportunity": "The company is positioned to benefit from regulatory, pharmacovigilance, medical writing, and medical information support.",
            "strategic_fit": "The profile aligns with MedNovaOS capabilities in lifecycle management, compliance, and cross-functional execution.",
            "estimated_value": int(primary_deal.get("value") or (company_dict.get("opportunity_score") or 0) * 10000) if primary_deal else int((company_dict.get("opportunity_score") or 0) * 10000),
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
        "executive_summary": f"{company_dict.get('company_name')} presents a credible growth opportunity supported by clear pipeline momentum and a strong service-fit profile, with public intelligence indicating focused commercial and regulatory priorities.",
        "company_overview": {
            "company_profile": intelligence_data.get("company_profile", {}) if isinstance(intelligence_data, dict) else {},
            "industry_position": "Commercially relevant growth account with measurable expansion potential and public signals of operational maturity.",
            "recent_news": (intelligence_data.get("company_profile", {}) or {}).get("recent_news", []) if isinstance(intelligence_data, dict) else [],
            "strategic_developments": (intelligence_data.get("company_profile", {}) or {}).get("strategic_initiatives", []) if isinstance(intelligence_data, dict) else [],
        },
        "website_analysis": intelligence_data.get("website_analysis", {}) if isinstance(intelligence_data, dict) else {},
        "tavily_insights": intelligence_data.get("tavily_insights", {}) if isinstance(intelligence_data, dict) else {},
        "commercial_opportunity": {
            "priority_score": priority_score,
            "recommended_services": recommended_services,
            "rationale": (intelligence_data.get("business_opportunity", {}) or {}).get("explanation", "Deterministic service recommendations derived from structured signals.") if isinstance(intelligence_data, dict) else "",
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
        "intelligence": intelligence_data,
    }
    return report


def _build_operations_report_payload() -> dict:
    company_service = CompanyService()
    task_service = TaskService()
    pipeline_service = PipelineService()
    outreach_service = OutreachService()

    companies = company_service.list_companies(page=1, per_page=15).get("items", [])
    tasks = task_service.list_tasks(page=1, per_page=20).get("items", [])
    deals = pipeline_service.list_deals(page=1, per_page=20).get("items", [])
    emails = outreach_service.list_outreach(None, page=1, per_page=20).get("items", [])
    activities = CompanyService().company_repo.list(order="created_at.desc", limit=20)

    # normalize
    companies_list = [_to_plain_dict(c) for c in companies]
    tasks_list = [_to_plain_dict(t) for t in tasks]
    deals_list = [_to_plain_dict(d) for d in deals]
    emails_list = [_to_plain_dict(e) for e in emails]
    activities_list = [_to_plain_dict(a) for a in activities]

    pipeline_value = sum(int(d.get("value") or 0) for d in deals_list if (d.get("stage") or "lead") != "lost")
    pending_tasks = [t for t in tasks_list if (t.get("status") or "pending") != "completed"]
    completed_tasks = [t for t in tasks_list if (t.get("status") or "pending") == "completed"]

    return {
        "report_type": "operations",
        "generated_at": _report_timestamp(),
        "summary": {
            "companies": len(companies_list),
            "pipeline_value": pipeline_value,
            "pending_tasks": len(pending_tasks),
            "completed_tasks": len(completed_tasks),
            "email_count": len(emails_list),
            "activity_count": len(activities_list),
        },
        "executive_summary": "The operations pipeline remains healthy with growing account momentum and strong follow-up discipline.",
        "pipeline_health": {
            "active_opportunities": len([d for d in deals_list if (d.get("stage") or "lead") not in {"won", "lost"}]),
            "lead_conversion": 64,
            "team_performance": 78,
        },
        "kpis": {
            "completed_tasks": len(completed_tasks),
            "pending_tasks": len(pending_tasks),
            "upcoming_deadlines": len([task for task in pending_tasks if task.get("due_date")]),
            "recent_outreach": len(emails_list),
            "company_growth": len(companies_list),
        },
        "top_opportunities": deals_list[:5],
        "lost_opportunities": [d for d in deals_list if (d.get("stage") or "lead") == "lost"],
        "lead_sources": [{"source": "Green Book", "count": len(companies_list)}],
        "greenbook_updates": [{"topic": "Portfolio refresh", "status": "Updated"}],
        "recent_crm_activity": activities_list[:10],
        "tasks": tasks_list,
        "companies": companies_list,
        "emails": emails_list,
    }


def _persist_report(conn: Any, company_id: int | None, report_type: str, report_name: str, report_data: dict, executive_summary: str | None = None) -> dict:
    return {
        "id": 0,
        "crm_company_id": company_id,
        "company_id": company_id,
        "report_type": report_type,
        "report_name": report_name,
        "version": "1.0",
        "generated_by": "MedNovaOS",
        "generated_at": _report_timestamp(),
        "report_data": report_data,
        "executive_summary": executive_summary,
        "status": "generated",
        "metadata": {"report_type": report_type, "company_id": company_id},
    }


def _load_reports(conn: Any, company_id: int | None = None) -> list[dict]:
    return []


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


def _build_growhub_company_payloads(companies: list[dict] | None = None) -> list[dict]:
    company_rows = companies or CompanyService().list_companies(page=1, per_page=100).get("items", [])
    payloads = []
    for row in company_rows:
        company = _to_plain_dict(row)
        created_at = company.get("created_at") or company.get("updated_at") or now_iso()
        payloads.append({
            "id": int(company.get("id") or 0),
            "name": company.get("company_name") or company.get("name") or "Unknown company",
            "industry": "Biopharma",
            "country": company.get("country") or "Unknown",
            "website": company.get("website") or "",
            "status": (company.get("opportunity_status") or company.get("pipeline_stage") or "prospect").lower(),
            "opportunityScore": int(company.get("opportunity_score") or 0),
            "portfolioSummary": company.get("portfolio_summary") or "",
            "source": company.get("source") or "CRM",
            "pipelineStage": company.get("pipeline_stage") or "Lead",
            "regulatoryReportId": None,
            "lastActivityAt": created_at,
            "nextFollowUpAt": None,
            "createdAt": created_at,
        })
    return payloads


def _build_growhub_related_payloads(companies: list[dict] | None = None) -> dict:
    company_repo = CompanyRepository()
    contact_repo = ContactRepository()
    activity_repo = ActivityRepository()
    task_repo = TaskRepository()
    note_repo = NoteRepository()
    deal_repo = DealRepository()

    company_rows = companies or CompanyService().list_companies(page=1, per_page=100).get("items", [])
    all_companies = company_repo.list(order="created_at.desc")
    all_tasks = task_repo.list(order="due_date.asc")
    all_activities = activity_repo.list(order="created_at.desc")
    all_contacts = contact_repo.list(order="created_at.desc")
    all_notes = note_repo.list(order="created_at.desc")
    existing_deals = deal_repo.list(order="created_at.desc")

    company_payloads = _build_growhub_company_payloads(company_rows)
    contacts = [_to_plain_dict(item) for item in all_contacts]
    activities = [_to_plain_dict(item) for item in all_activities]
    tasks = [_to_plain_dict(item) for item in all_tasks]
    notes = [_to_plain_dict(item) for item in all_notes]
    emails = []
    products = []

    for company in company_rows:
        company_payload = _to_plain_dict(company)
        company_id = int(company_payload.get("id") or 0)
        if not company_id:
            continue
        emails.extend([_to_plain_dict(item) for item in OutreachService().list_outreach(company_id, page=1, per_page=100).get("items", [])])

    deals = _build_growhub_pipeline_deals(company_rows)

    return {
        "companies": company_payloads,
        "contacts": contacts,
        "activities": activities,
        "tasks": tasks,
        "notes": notes,
        "deals": deals,
        "emails": emails,
        "products": products,
        "summary": _build_growhub_crm_dashboard_summary(all_companies, deals, all_tasks),
    }


def _validate_startup_config() -> None:
    # In migrated deployments we require Supabase credentials instead of a local SQLite path.
    if os.getenv("MEDNOVA_ENV", "").lower() == "production":
        if not os.getenv("SUPABASE_URL") or not os.getenv("SUPABASE_SERVICE_ROLE_KEY"):
            raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set in production for Supabase-backed deployments.")
        if not os.getenv("SYNC_CRON_SECRET"):
            raise RuntimeError("SYNC_CRON_SECRET must be configured in production to protect cron endpoints.")




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


def _build_company_payload_from_products(products: list[dict], company_name: str | None = None) -> dict:
    normalized_products = [dict(product) if isinstance(product, dict) else _to_plain_dict(product) for product in products]
    therapeutic_areas = sorted({product.get("therapeutic_area") or product.get("category_name") for product in normalized_products if product.get("therapeutic_area") or product.get("category_name")})
    registration_numbers = sorted({product.get("registration_number") for product in normalized_products if product.get("registration_number")})
    dosage_forms = sorted({product.get("dosage_form") for product in normalized_products if product.get("dosage_form")})
    registration_dates = sorted([product.get("approval_date") for product in normalized_products if product.get("approval_date")])
    opportunity_score = _calc_opportunity_score(normalized_products)
    return {
        "company_name": company_name or "Unknown company",
        "country": next((product.get("country") for product in normalized_products if product.get("country")), "Unknown"),
        "product_count": len(normalized_products),
        "portfolio_summary": f"{len(normalized_products)} registered product(s) across {len(therapeutic_areas)} therapeutic area(s).",
        "opportunity_score": opportunity_score,
        "products": normalized_products,
        "therapeutic_areas": therapeutic_areas,
        "registration_numbers": registration_numbers,
        "dosage_forms": dosage_forms,
        "registration_dates": registration_dates,
    }


ALLOWED_CORS_ORIGINS = {
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:5175",
    "http://127.0.0.1:5175",
}

app = Flask(__name__)
CORS(
    app,
    resources={
        r"/api/*": {
            "origins": sorted(ALLOWED_CORS_ORIGINS),
            "methods": ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
            "allow_headers": ["Content-Type", "Authorization"],
        }
    },
    supports_credentials=True,
    automatic_options=True,
)
_validate_startup_config()

SYNC_SCHEDULER_ENABLED = os.getenv("SYNC_SCHEDULER_ENABLED", "false").strip().lower() == "true"
if SYNC_SCHEDULER_ENABLED:
    scheduler = SyncScheduler(app)
    scheduler.start()


def _verify_cron_secret() -> bool:
    secret = (os.getenv("SYNC_CRON_SECRET") or "").strip()
    if not secret:
        return os.getenv("MEDNOVA_ENV", "").strip().lower() != "production"
    return request.headers.get("X-Cron-Secret", "").strip() == secret


def _cors_origin_allowed(origin: str | None) -> str | None:
    if not origin:
        return None
    parsed = urlparse(origin)
    allowed_hosts = {"localhost:5173", "127.0.0.1:5173", "localhost:5175", "127.0.0.1:5175"}
    if parsed.scheme in {"http", "https"} and parsed.netloc in allowed_hosts:
        return origin
    return None


@app.after_request
def _apply_api_cors_headers(response):
    if request.path.startswith("/api/"):
        origin = _cors_origin_allowed(request.headers.get("Origin"))
        if origin:
            response.headers.setdefault("Access-Control-Allow-Origin", origin)
            response.headers.setdefault("Access-Control-Allow-Credentials", "true")
            response.headers.setdefault("Access-Control-Allow-Methods", "GET, POST, PUT, PATCH, DELETE, OPTIONS")
            response.headers.setdefault("Access-Control-Allow-Headers", "Content-Type, Authorization")
    return response


@app.template_filter("money")
def money(value):
    try:
        return f"₦{float(value):,.0f}"
    except (TypeError, ValueError):
        return "₦0"


@app.template_filter("format_date")
def format_date(value: Any) -> str:
    parsed = _parse_dashboard_date(value)
    if parsed is None:
        return ""
    return parsed.strftime("%d %b %Y")


def _safe_dashboard_metric(label: str, callback, default: Any = "N/A") -> Any:
    try:
        return callback()
    except Exception:
        logger.exception("Legacy dashboard metric failed: %s", label)
        return default


def _parse_dashboard_date(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text.replace(" ", "T"))
    except ValueError:
        return None


@app.route("/")
def dashboard():
    return legacy_dashboard()


@app.route("/dashboard")
@app.route("/legacy-dashboard")
def legacy_dashboard():
    product_repo = ProductRepository()
    company_repo = CompanyRepository()
    pipeline_repo = PipelineRepository()
    db_backend = "Supabase" if get_db().client is not None else "SQLite"

    products_rows = _safe_dashboard_metric("products", lambda: product_repo.list(limit=10000), default=[])
    product_count = _safe_dashboard_metric("product_count", lambda: product_repo.db.count(product_repo.table_name), default="N/A")
    manufacturer_values = _safe_dashboard_metric(
        "manufacturer_count",
        lambda: {
            row.get("manufacturer_name") or row.get("manufacturer_id")
            for row in products_rows
            if isinstance(row, dict) and (row.get("manufacturer_name") or row.get("manufacturer_id"))
        },
        default=set(),
    )
    manufacturers_count = len(manufacturer_values) if isinstance(manufacturer_values, set) else "N/A"

    pipeline_rows = _safe_dashboard_metric("pipeline_rows", lambda: pipeline_repo.list(limit=10000), default=[])
    opportunities_count = _safe_dashboard_metric("opportunities_count", lambda: len(pipeline_rows), default="N/A")
    pipeline_value = _safe_dashboard_metric(
        "pipeline_value",
        lambda: sum(float(row.get("estimated_value") or 0) for row in pipeline_rows if isinstance(row, dict)),
        default="N/A",
    )

    now = datetime.now(timezone.utc)
    expiring_count = _safe_dashboard_metric(
        "expiring_count",
        lambda: sum(
            1
            for row in products_rows
            if isinstance(row, dict)
            and (row.get("expiry_date") or "")
            and (row.get("status") or "").lower() not in {"expired", "revoked", "withdrawn"}
            and (parsed := _parse_dashboard_date(row.get("expiry_date"))) is not None
            and parsed >= now.replace(tzinfo=None)
            and parsed <= (now.replace(tzinfo=None) + timedelta(days=365))
        ),
        default="N/A",
    )

    top_accounts = _safe_dashboard_metric(
        "top_accounts",
        lambda: [
            {
                "company": row.get("company") or "Unknown",
                "category": row.get("category") or "Uncategorized",
                "products": row.get("products") or "0",
                "estimated_value": row.get("estimated_value") or 0,
                "recommended_services": row.get("recommended_services") or "—",
                "status": row.get("status") or "unknown",
            }
            for row in sorted(pipeline_rows, key=lambda item: float(item.get("estimated_value") or 0), reverse=True)[:8]
            if isinstance(row, dict)
        ],
        default=[],
    )

    categories = _safe_dashboard_metric(
        "categories",
        lambda: [
            {"category": category, "product_count": count}
            for category, count in sorted(
                ((entry[0], entry[1]) for entry in defaultdict(int, ((row.get("category") or "Uncategorized", 1) for row in pipeline_rows if isinstance(row, dict))).items()),
                key=lambda item: item[1],
                reverse=True,
            )[:8]
        ],
        default=[],
    )

    renewals = _safe_dashboard_metric(
        "renewals",
        lambda: [
            {
                "company": row.get("manufacturer_name") or row.get("manufacturer_id") or row.get("product_name") or "Unknown",
                "expiring_products": 1,
            }
            for row in products_rows
            if isinstance(row, dict)
            and (row.get("expiry_date") or "")
            and (parsed := _parse_dashboard_date(row.get("expiry_date"))) is not None
            and parsed >= now.replace(tzinfo=None)
            and parsed <= (now.replace(tzinfo=None) + timedelta(days=365))
        ][:8],
        default=[],
    )

    last_sync_payload = None
    try:
        sync_rows = get_db().table_select("sync_history", order="id.desc", limit=1)
        if sync_rows:
            last_sync_payload = dict(sync_rows[0])
    except Exception:
        logger.exception("Legacy dashboard sync history lookup failed")
        last_sync_payload = None

    print(f"Products: {product_count}")
    print(f"Manufacturers: {manufacturers_count}")
    print(f"Revenue Pipeline: {opportunities_count}")
    print(f"Pipeline Value: {pipeline_value}")
    print(f"Renewals: {expiring_count}")

    return render_template(
        "dashboard.html",
        manufacturers=manufacturers_count,
        products=product_count,
        opportunities=opportunities_count,
        pipeline_value=pipeline_value,
        expiring=expiring_count,
        last_sync_payload=last_sync_payload,
        top_accounts=top_accounts,
        categories=categories,
        renewals=renewals,
        db=db_backend,
    )


def _build_products_page_context(repo: ProductRepository, q: str, manufacturer: str, category: str, applicant: str, status: str, expiry: str, sort_by: str, page: int, page_size: int) -> tuple[list[dict], int, list[dict], list[dict], int, int]:
    rows, total, categories, statuses = repo.list_page(
        query=q,
        manufacturer=manufacturer,
        category=category,
        applicant=applicant,
        status=status,
        expiry=expiry,
        sort_by=sort_by,
        page=page,
        page_size=page_size,
    )
    return rows, total, categories, statuses, max(int(page or 1), 1), max(min(int(page_size or 50), 200), 1)


@app.route("/products")
def products():
    start_time = perf_counter()
    repo = ProductRepository()
    q = request.args.get("q", "", type=str)
    manufacturer = request.args.get("manufacturer", "", type=str)
    category = request.args.get("category", "", type=str)
    applicant = request.args.get("applicant", "", type=str)
    status = request.args.get("status", "", type=str)
    expiry = request.args.get("expiry", "", type=str)
    sort_by = request.args.get("sort", "", type=str)
    page = request.args.get("page", 1, type=int)
    page_size = request.args.get("page_size", 50, type=int)

    try:
        rows, total, categories, statuses, page, page_size = _build_products_page_context(
            repo,
            q=q,
            manufacturer=manufacturer,
            category=category,
            applicant=applicant,
            status=status,
            expiry=expiry,
            sort_by=sort_by,
            page=page,
            page_size=page_size,
        )
    except Exception:
        logger.exception("Products page failed")
        rows = []
        total = 0
        categories = []
        statuses = []
        page = max(page or 1, 1)
        page_size = max(page_size or 50, 50)

    elapsed_ms = (perf_counter() - start_time) * 1000
    print(f"Products loaded: {total}")
    print(f"Returned: {len(rows)}")
    print(f"Current page: {page}")
    print(f"Execution time: {elapsed_ms:.2f}ms")

    if not rows and not categories and not statuses and total == 0:
        error_message = "Unable to load products."
    else:
        error_message = ""

    return render_template(
        "products.html",
        rows=rows,
        q=q,
        manufacturer=manufacturer,
        category=category,
        applicant=applicant,
        status=status,
        expiry=expiry,
        sort=sort_by,
        categories=categories,
        statuses=statuses,
        total=total,
        page=page,
        size=page_size,
        error_message=error_message,
    )


@app.route("/products/<int:pid>")
def product_detail(pid):
    repo = ProductRepository()
    row = repo.get_by_id(pid)
    if not row:
        abort(404)
    product = _to_plain_dict(row)
    return render_template("product_detail.html", product={
        **product,
        "product_category": product.get("category_name") or product.get("product_category") or product.get("therapeutic_area") or "",
        "nafdac_number": product.get("registration_number") or product.get("nafdac_number") or product.get("nafdac_product_id") or "",
        "applicant_name": product.get("applicant_name") or product.get("manufacturer_name") or "",
        "manufacturer_name": product.get("manufacturer_name") or product.get("applicant_name") or "",
        "dosage_form": product.get("dosage_form") or product.get("dosage_form_name") or "",
        "route_of_administration": product.get("route_of_administration") or product.get("route_name") or "",
        "strength": product.get("strength") or "",
        "approval_date": product.get("approval_date") or "",
        "expiry_date": product.get("expiry_date") or "",
        "status": product.get("status") or "",
        "pack_size": product.get("pack_size") or "",
        "composition": product.get("composition") or "",
    })


@app.route("/opportunities")
def opportunities():
    page = max(int(request.args.get("page", 1, type=int) or 1), 1)
    page_size = max(min(int(request.args.get("page_size", 50, type=int) or 50), 200), 1)
    filters = {
        "q": request.args.get("q", "", type=str),
        "status": request.args.get("status", "", type=str),
        "priority": request.args.get("priority", "", type=str),
        "probability": request.args.get("probability", "", type=str),
        "estimated_value": request.args.get("estimated_value", "", type=str),
        "category": request.args.get("category", "", type=str),
        "service": request.args.get("service", "", type=str),
        "manufacturer": request.args.get("manufacturer", "", type=str),
        "sort_by": request.args.get("sort_by", "", type=str),
    }

    started_at = perf_counter()
    rows, total, categories, statuses, services, manufacturers, summary = [], 0, [], [], [], [], {
        "total_opportunities": 0,
        "high_priority": 0,
        "closing_soon": 0,
        "total_pipeline_value": 0.0,
        "average_opportunity_value": 0.0,
    }
    error_message = ""

    try:
        rows, total, categories, statuses, services, manufacturers, summary = PipelineRepository().list_page(
            query=filters.get("q", ""),
            status=filters.get("status", ""),
            priority=filters.get("priority", ""),
            probability=filters.get("probability", ""),
            estimated_value=filters.get("estimated_value", ""),
            category=filters.get("category", ""),
            service=filters.get("service", ""),
            manufacturer=filters.get("manufacturer", ""),
            sort_by=filters.get("sort_by", ""),
            page=page,
            page_size=page_size,
        )
    except Exception:
        logger.exception("Unable to load opportunities from revenue_pipeline")
        error_message = "Unable to load opportunities."

    elapsed_ms = (perf_counter() - started_at) * 1000
    print(f"Revenue Pipeline Rows: {total}")
    print(f"Returned: {len(rows)}")
    print(f"Current Page: {page}")
    print(f"Execution Time: {elapsed_ms:.2f}ms")

    return render_template(
        "opportunities.html",
        rows=rows,
        q=filters.get("q", ""),
        status=filters.get("status", ""),
        priority=filters.get("priority", ""),
        probability=filters.get("probability", ""),
        estimated_value=filters.get("estimated_value", ""),
        category=filters.get("category", ""),
        service=filters.get("service", ""),
        manufacturer=filters.get("manufacturer", ""),
        sort_by=filters.get("sort_by", ""),
        categories=categories,
        statuses=statuses,
        services=services,
        manufacturers=manufacturers,
        total=total,
        page=page,
        page_size=page_size,
        summary=summary,
        error_message=error_message,
    )


@app.route("/renewals")
def renewal_watch():
    error_message = None
    started_at = perf_counter()
    months = max(int(request.args.get("months", 12)), 1)
    page = max(int(request.args.get("page", 1)), 1)
    page_size = max(min(int(request.args.get("page_size", 100)), 1000), 1)
    rows = []
    total = 0
    summary = {}
    try:
        repo = RenewalRepository()
        rows, total, summary = repo.list_page(months=months, page=page, page_size=page_size, query=request.args.get("q", ""))
    except Exception:
        logger.exception("Unable to load renewals from products")
        error_message = "Unable to load renewals."

    elapsed_ms = (perf_counter() - started_at) * 1000
    print(f"Renewal Rows: {total}")
    print(f"Returned: {len(rows)}")
    print(f"Current Page: {page}")
    print(f"Execution Time: {elapsed_ms:.2f}ms")

    return render_template(
        "renewals.html",
        rows=rows,
        months=months,
        total=total,
        page=page,
        page_size=page_size,
        summary=summary,
        error_message=error_message,
    )


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
    page = _parse_int_query_arg("page", 1, min_value=1)
    per_page = _parse_int_query_arg("per_page", 100, min_value=1, max_value=500)
    query = (request.args.get("q") or "").strip()

    service = CompanyService()
    if query:
        companies_payload = service.search_companies(query, page=page, per_page=per_page)
        companies = companies_payload.get("items", [])
    else:
        companies = service.list_companies(page=page, per_page=per_page).get("items", [])

    return jsonify(_build_growhub_company_payloads(companies))


@app.route("/api/growhub/crm/data")
def growhub_crm_data():
    page = _parse_int_query_arg("page", 1, min_value=1)
    per_page = _parse_int_query_arg("per_page", 100, min_value=1, max_value=500)
    query = (request.args.get("q") or "").strip()

    service = CompanyService()
    if query:
        companies_payload = service.search_companies(query, page=page, per_page=per_page)
        companies = companies_payload.get("items", [])
    else:
        companies = service.list_companies(page=page, per_page=per_page).get("items", [])

    return jsonify({"success": True, **_build_growhub_related_payloads(companies)})


@app.route("/api/crm/companies/<int:company_id>")
def crm_company_detail_json(company_id):
    """Get company detail with related data (contacts, tasks, notes, activities)."""
    try:
        service = CompanyService()
        detail = service.get_company_detail(company_id)

        if not detail:
            abort(404)

        logger.info("Retrieved company detail for company_id=%d", company_id)

        company_name = _normalize_contact_value((detail.get("company") or {}).get("company_name") or "")
        contacts = detail.get("contacts") or []
        normalized_contacts = [_to_plain_dict(contact) for contact in contacts]
        valid_contacts = [contact for contact in normalized_contacts if not _is_placeholder_contact_record(contact, company_name)]
        if valid_contacts:
            contacts = valid_contacts

        # Preserve response structure exactly
        return jsonify({
            "company": detail.get("company") or {},
            "products": detail.get("products") or [],
            "activities": detail.get("activities") or [],
            "notes": detail.get("notes") or [],
            "contacts": contacts,
            "tasks": detail.get("tasks") or [],
        })
    except Exception as e:
        logger.error("Error retrieving company detail: %s", str(e))
        abort(500)


@app.route("/crm/companies/<int:company_id>")
def crm_company_detail(company_id):
    return redirect(f"{_crm_frontend_target()}/companies/{company_id}")


@app.route("/crm/companies/<int:company_id>/outreach", methods=["GET", "POST"])
def crm_company_outreach(company_id):
    company = CompanyService().get_company(company_id)
    if not company:
        abort(404)

    contacts_payload = ContactService().list_contacts(company_id, page=1, per_page=100)
    contacts = contacts_payload.get("items", [])
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
        preview_data = _build_outreach_preview(company_id, template_key, contact_ids, sender_name, sender_email, recipient, recipient_name, int(contact_id) if str(contact_id).strip() else None)
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
        _to_plain_dict(row)
        for row in OutreachService().list_outreach(company_id, page=1, per_page=10).get("items", [])
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


@app.route("/api/crm/companies/<int:company_id>/pipeline-stage", methods=["PATCH"])
def update_company_pipeline_stage(company_id):
    """Update company pipeline stage."""
    payload = request.get_json(silent=True) or {}
    stage_value = payload.get("pipelineStage") or payload.get("stage")
    if not stage_value:
        return jsonify({"error": "pipelineStage is required"}), 400

    try:
        service = CompanyService()
        stage = _crm_deal_stage_to_frontend(stage_value)
        updated = service.update_company(company_id, {"pipeline_stage": stage.title()})
        service.add_activity(company_id, "pipeline", "Pipeline stage updated", f"Updated pipeline stage to {stage.title()} for {(getattr(updated, 'company_name', None) or (updated.get('company_name') if isinstance(updated, dict) else 'company'))}")
        logger.info("Updated pipeline stage for company_id=%d to %s", company_id, stage.title())
        return jsonify({"success": True, "company": updated if isinstance(updated, dict) else vars(updated)})
    except LookupError:
        abort(404)
    except Exception as e:
        logger.error("Error updating pipeline stage: %s", str(e))
        return jsonify({"error": str(e)}), 400


@app.route("/api/crm/companies/<int:company_id>/contacts/discover", methods=["POST"])
def discover_company_contacts(company_id):
    company = CompanyService().get_company(company_id)
    if not company:
        abort(404)

    company_name = getattr(company, "company_name", None) if company else None
    company_name = company_name or (company.get("company_name") if isinstance(company, dict) else "")
    search_query = company_name or ""
    if not search_query:
        return jsonify({"error": "Company name is required for discovery."}), 400

    CompanyService().add_activity(company_id, "research", "Contact discovery started", f"Started contact discovery for {company_name}")
    logger.info("Contact discovery started for company_id=%s name=%s", company_id, company_name)
    contact_service = ContactService()
    imported_count = 0
    updated_count = 0
    duplicates_skipped = 0
    discovered_contacts: list[dict] = []

    try:
        intelligence_service = IntelligenceService()
        search_query, tavily_payload = intelligence_service.search_company_contacts(company_id)
        if tavily_payload is None:
            logger.error("Contact discovery failed: Tavily search failed for company_id=%s query=%s", company_id, search_query)
            message = intelligence_service.last_tavily_error or "Contact discovery provider failed."
            return jsonify({"error": message}), 502

        results = tavily_payload.get("results") if isinstance(tavily_payload, dict) else []
        if not isinstance(results, list):
            results = []

        logger.info("Tavily returned %d results for company='%s' query='%s'", len(results), company_name, search_query)

        for result in results:
            url = result.get("url") or ""
            if not url:
                continue
            html_response = requests.get(url, timeout=10)
            html_response.raise_for_status()
            details = _extract_contact_details_from_html(url, html_response.text, company_name)
            if not details.get("email") and not details.get("phone"):
                continue

            existing = _find_matching_contact(company_id, details)
            if existing:
                duplicates_skipped += 1
                if existing.get("source") == "discovered":
                    update_payload = {}
                    if details.get("email") and not existing.get("email"):
                        update_payload["email"] = details["email"]
                    if details.get("phone") and not existing.get("phone"):
                        update_payload["phone"] = details["phone"]
                    if details.get("linkedin_url") and not existing.get("linkedin_url"):
                        update_payload["linkedin_url"] = details["linkedin_url"]
                    if details.get("role") and not existing.get("role"):
                        update_payload["role"] = details["role"]
                    if details.get("name") and not existing.get("full_name"):
                        update_payload["full_name"] = details["name"]
                    if update_payload:
                        ContactService().update_contact(int(existing.get("id") or 0), {
                            **update_payload,
                            "updated_at": now_iso(),
                        })
                        updated_count += 1
                continue

            logger.info("Saving discovered contact for company '%s': name=%s email=%s phone=%s", company_name, details.get("name") or "<unknown>", details.get("email") or "", details.get("phone") or "")
            created = contact_service.create_contact(company_id, {
                "full_name": details.get("name") or "Public Contact",
                "role": details.get("role") or "Public contact",
                "email": details.get("email"),
                "phone": details.get("phone"),
                "website": details.get("website"),
                "source": "discovered",
                "source_url": details.get("source_url"),
                "linkedin_url": details.get("linkedin_url"),
                "created_at": now_iso(),
            })
            created_dict = _to_plain_dict(created)
            discovered_contacts.append(created_dict)
            imported_count += 1
            logger.info("Saved contact id=%s name=%s email=%s", created_dict.get("id"), created_dict.get("full_name"), created_dict.get("email"))

        placeholder_cleanup_count = 0
        if discovered_contacts or updated_count or duplicates_skipped:
            placeholder_cleanup_count = _cleanup_placeholder_contacts(company_id, company_name)

        # If Tavily returned nothing, create a single placeholder contact
        if imported_count == 0 and updated_count == 0 and duplicates_skipped == 0:
            existing = [_to_plain_dict(c) for c in contact_service.list_contacts(company_id, page=1, per_page=1000).get("items", [])]
            has_placeholder = any(((c.get("source") or "").strip().lower() == "placeholder") or _is_placeholder_contact_record(c, company_name) for c in existing)
            if not has_placeholder:
                logger.info("No contacts discovered for company '%s'; creating placeholder contact", company_name)
                placeholder = contact_service.create_contact(company_id, {
                    "full_name": f"{company_name} contact" if company_name else "No contact found",
                    "role": "Unknown",
                    "email": None,
                    "phone": None,
                    "website": None,
                    "source": "placeholder",
                    "enrichment_status": "failed",
                    "created_at": now_iso(),
                })
                logger.info("Created placeholder contact for company_id=%s id=%s", company_id, getattr(placeholder, 'id', (placeholder.get('id') if isinstance(placeholder, dict) else None)))

        logger.info(
            "Contact discovery summary company_id=%s company_name=%s search_query=%s imported=%d updated=%d duplicates_skipped=%d placeholder_cleanup=%d",
            company_id,
            company_name,
            search_query,
            imported_count,
            updated_count,
            duplicates_skipped,
            placeholder_cleanup_count,
        )

        CompanyService().add_activity(company_id, "research", "Contacts imported", f"Imported {imported_count} contacts for {company_name}")
        CompanyService().add_activity(company_id, "research", "Enrichment completed", f"Completed contact discovery for {company_name}")
        contacts_payload = ContactService().list_contacts(company_id, page=1, per_page=1000)
        contacts = [_to_plain_dict(contact) for contact in contacts_payload.get("items", [])]
        return jsonify({
            "success": True,
            "contacts": contacts,
            "imported_count": imported_count,
            "updated_count": updated_count,
            "duplicates_skipped": duplicates_skipped,
        })
    except requests.exceptions.Timeout:
        return jsonify({"error": "The contact discovery provider could not be reached in time."}), 502
    except requests.RequestException as exc:
        return jsonify({"error": f"Contact discovery failed: {str(exc)}"}), 502
    except Exception as exc:
        logger.exception("Contact discovery error: %s", exc)
        return jsonify({"error": f"Contact discovery failed: {str(exc)}"}), 502


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

    company = CompanyService().get_company(company_id)
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
    preview_data = _build_outreach_preview(company_id, payload.get("template_key") or "introduction", contact_ids, sender_name, sender_email, recipient, recipient_name, contact_id)
    CompanyService().add_activity(company_id, "email", "Email drafted", f"Drafted {preview_data['template']} for {company.company_name if hasattr(company, 'company_name') else company.get('company_name')}")
    return jsonify({"success": True, "subject": preview_data["subject"], "body": preview_data["body"], "recipient": preview_data["recipient"], "recipientName": preview_data["recipient_name"], "senderName": preview_data["sender_name"], "senderEmail": preview_data["sender_email"], "template": preview_data["template"], "contact_count": len(contact_ids), "warning": preview_data.get("warning_message")})


@app.route("/api/crm/companies/<int:company_id>/outreach/drafts", methods=["POST"])
def save_outreach_draft(company_id):
    payload = _coerce_request_payload()
    subject = (payload.get("subject") or "Draft email").strip()
    body = (payload.get("body") or "").strip()
    if not subject or not body:
        return jsonify({"error": "subject and body are required"}), 400

    company = CompanyService().get_company(company_id)
    if not company:
        abort(404)

    details = _resolve_outreach_persist_details(company_id, company.company_name if hasattr(company, 'company_name') else company.get('company_name'), payload, template_key=payload.get("template_key") or "introduction", sender_name=(payload.get("sender_name") or _default_sender_name()).strip(), sender_email=(payload.get("sender_email") or _default_sender_email()).strip())
    body_with_signature = _append_signature(details["body"], sender_name=details["sender_name"], sender_email=details["sender_email"])
    draft_id = payload.get("id")
    request_id = details.get("request_id")
    service = OutreachService()
    existing = _get_outreach_by_request_id(company_id, request_id) if request_id else None

    if draft_id:
        updated = service.update_outreach(int(draft_id), {
            "subject": details["subject"],
            "body": body_with_signature,
            "recipient": details["recipient"],
            "recipient_name": details["recipient_name"],
            "sender_name": details["sender_name"],
            "sender_email": details["sender_email"],
            "template_key": details["template_key"],
            "template_name": details["template_name"],
            "company_name": details["company_name"],
            "contact_name": details["contact_name"],
            "crm_contact_id": details["contact_id"],
            "client_request_id": request_id,
        })
        row = _to_plain_dict(updated)
        row_id = int(row.get("id") or 0)
        CompanyService().add_activity(company_id, "email", "Draft updated", f"Updated draft for {company.company_name if hasattr(company, 'company_name') else company.get('company_name')}")
    elif existing:
        updated = service.update_outreach(int(existing.get("id") or 0), {
            "subject": details["subject"],
            "body": body_with_signature,
            "recipient": details["recipient"],
            "recipient_name": details["recipient_name"],
            "sender_name": details["sender_name"],
            "sender_email": details["sender_email"],
            "template_key": details["template_key"],
            "template_name": details["template_name"],
            "company_name": details["company_name"],
            "contact_name": details["contact_name"],
            "crm_contact_id": details["contact_id"],
            "client_request_id": request_id,
        })
        row = _to_plain_dict(updated)
        row_id = int(row.get("id") or 0)
        CompanyService().add_activity(company_id, "email", "Draft updated", f"Updated draft for {company.company_name if hasattr(company, 'company_name') else company.get('company_name')}")
    else:
        created = service.create_outreach(company_id, {
            "crm_company_id": company_id,
            "crm_contact_id": details["contact_id"],
            "template_key": details["template_key"],
            "template_name": details["template_name"],
            "subject": details["subject"],
            "body": body_with_signature,
            "recipient": details["recipient"],
            "recipient_name": details["recipient_name"],
            "sender_name": details["sender_name"],
            "sender_email": details["sender_email"],
            "company_name": details["company_name"],
            "contact_name": details["contact_name"],
            "status": "draft",
            "client_request_id": request_id,
        })
        row = _to_plain_dict(created)
        row_id = int(row.get("id") or 0)
        CompanyService().add_activity(company_id, "email", "Email drafted", f"Saved draft for {company.company_name if hasattr(company, 'company_name') else company.get('company_name')}")

    return jsonify({"success": True, "draft_id": row_id, "status": "draft"})


@app.route("/api/crm/companies/<int:company_id>/outreach/send", methods=["POST"])
def send_outreach_email(company_id):
    payload = _coerce_request_payload()
    subject = (payload.get("subject") or "Email").strip()
    body = (payload.get("body") or "").strip()
    recipient = (payload.get("recipient") or "").strip()
    if not subject or not body:
        return jsonify({"success": False, "error": "subject and body are required"}), 400

    company = CompanyService().get_company(company_id)
    if not company:
        abort(404)

    details = _resolve_outreach_persist_details(company_id, company.company_name if hasattr(company, 'company_name') else company.get('company_name'), payload, template_key=payload.get("template_key") or "introduction", sender_name=(payload.get("sender_name") or _default_sender_name()).strip(), sender_email=(payload.get("sender_email") or _default_sender_email()).strip())
    sender_name = details["sender_name"]
    sender_email = details["sender_email"]
    from_email = (payload.get("from_email") or _default_from_email()).strip()
    request_id = details.get("request_id")
    service = OutreachService()
    existing = _get_outreach_by_request_id(company_id, request_id) if request_id else None
    if existing and (existing.get("status") if isinstance(existing, dict) else getattr(existing, "status", None)) == "sent":
        return jsonify({"success": True, "status": "sent", "email_id": int(existing.get("id") or 0), "message_id": existing.get("message_id"), "duplicate": True})

    body_with_signature = _append_signature(details["body"], sender_name=sender_name, sender_email=sender_email)
    success, message_id, error_message = _send_via_resend(details["subject"], body_with_signature, details["recipient"], from_email, sender_name, sender_email)
    status = "sent" if success else "failed"

    if existing:
        updated = service.update_outreach(int(existing.get("id") or 0), {
            "crm_contact_id": details["contact_id"],
            "template_key": details["template_key"],
            "template_name": details["template_name"],
            "subject": details["subject"],
            "body": body_with_signature,
            "recipient": details["recipient"],
            "recipient_name": details["recipient_name"],
            "sender_name": sender_name,
            "sender_email": sender_email,
            "from_email": from_email,
            "company_name": details["company_name"],
            "contact_name": details["contact_name"],
            "status": status,
            "message_id": message_id,
            "error_message": error_message,
            "client_request_id": request_id,
            "sent_at": now_iso(),
        })
        row = _to_plain_dict(updated)
    else:
        created = service.create_outreach(company_id, {
            "crm_company_id": company_id,
            "crm_contact_id": details["contact_id"],
            "template_key": details["template_key"],
            "template_name": details["template_name"],
            "subject": details["subject"],
            "body": body_with_signature,
            "recipient": details["recipient"],
            "recipient_name": details["recipient_name"],
            "sender_name": sender_name,
            "sender_email": sender_email,
            "from_email": from_email,
            "company_name": details["company_name"],
            "contact_name": details["contact_name"],
            "status": status,
            "message_id": message_id,
            "error_message": error_message,
            "client_request_id": request_id,
            "sent_at": now_iso(),
        })
        row = _to_plain_dict(created)

    row_id = int(row.get("id") or 0)

    if success:
        CompanyService().add_activity(company_id, "email", "Email sent", f"Sent outreach email for {company.company_name if hasattr(company, 'company_name') else company.get('company_name')}")
    else:
        CompanyService().add_activity(company_id, "email", "Email failed", f"Failed to send outreach email for {company.company_name if hasattr(company, 'company_name') else company.get('company_name')}: {error_message}")
    return jsonify({"success": success, "status": status, "email_id": row_id, "message_id": message_id, "error": error_message})


@app.route("/api/crm/companies/<int:company_id>/outreach/history")
def get_outreach_history(company_id):
    company = CompanyService().get_company(company_id)
    if not company:
        abort(404)
    items = []
    for row in OutreachService().list_outreach(company_id, page=1, per_page=100).get("items", []):
        item = _to_plain_dict(row)
        items.append({
            "id": int(item.get("id") or 0),
            "companyId": int(item.get("crm_company_id") or company_id),
            "contactId": int(item.get("crm_contact_id")) if item.get("crm_contact_id") is not None else None,
            "templateKey": item.get("template_key"),
            "templateName": item.get("template_name") or item.get("template_key"),
            "subject": item.get("subject"),
            "body": item.get("body"),
            "recipient": item.get("recipient"),
            "recipientName": item.get("recipient_name"),
            "senderName": item.get("sender_name"),
            "senderEmail": item.get("sender_email"),
            "fromEmail": item.get("from_email"),
            "companyName": item.get("company_name"),
            "contactName": item.get("contact_name"),
            "status": item.get("status"),
            "messageId": item.get("message_id"),
            "errorMessage": item.get("error_message"),
            "createdAt": item.get("created_at"),
            "updatedAt": item.get("updated_at"),
            "sentAt": item.get("sent_at"),
        })
    return jsonify({"success": True, "items": items})


@app.route("/api/crm/contacts/outreach/summary")
def get_contact_outreach_summary():
    repo = OutreachRepository()
    rows = repo.list(filters={"crm_contact_id": ("neq", None)}, order="created_at.desc", limit=100)
    latest_by_contact = {}
    for row in rows:
        item = _to_plain_dict(row)
        contact_id = int(item.get("crm_contact_id") or 0)
        if not contact_id:
            continue
        if contact_id not in latest_by_contact:
            latest_by_contact[contact_id] = {
                "contactId": contact_id,
                "status": item.get("status"),
                "subject": item.get("subject"),
                "sentAt": item.get("created_at"),
            }
    return jsonify({"success": True, "items": list(latest_by_contact.values())})


@app.route("/api/crm/companies/<int:company_id>/contacts", methods=["POST"])
def add_company_contact(company_id):
    payload = request.get_json(silent=True) or {}
    full_name = (payload.get("full_name") or payload.get("name") or "Primary Contact").strip()
    if not full_name:
        return jsonify({"error": "full_name is required"}), 400

    company = CompanyService().get_company(company_id)
    if not company:
        abort(404)

    service = ContactService()
    contact = service.create_contact(company_id, payload)
    logger.info("Added contact %s for company_id=%d", full_name, company_id)
    return jsonify({"success": True, "contact": contact if isinstance(contact, dict) else vars(contact)})


@app.route("/api/crm/companies/<int:company_id>/tasks", methods=["POST"])
def add_company_task(company_id):
    payload = request.get_json(silent=True) or {}
    title = (payload.get("title") or payload.get("name") or "Follow up").strip()
    if not title:
        return jsonify({"error": "title is required"}), 400

    company = CompanyService().get_company(company_id)
    if not company:
        abort(404)

    service = TaskService()
    task = service.create_task(company_id, payload)
    logger.info("Assigned task %s for company_id=%d", title, company_id)
    return jsonify({"success": True, "task": task if isinstance(task, dict) else vars(task)})


@app.route("/api/crm/companies/<int:company_id>/notes", methods=["POST"])
def add_company_note(company_id):
    """Create a note for a company."""
    payload = request.get_json(silent=True) or {}
    body = (payload.get("body") or "").strip()
    if not body:
        return jsonify({"error": "body is required"}), 400

    company = CompanyService().get_company(company_id)
    if not company:
        abort(404)

    try:
        service = CompanyService()
        note = service.add_note(company_id, body)
        logger.info("Added note to company_id=%d", company_id)
        return jsonify({"success": True, "note": note if isinstance(note, dict) else vars(note)})
    except Exception as e:
        logger.error("Error adding note: %s", str(e))
        return jsonify({"error": str(e)}), 400


@app.route("/api/crm/companies/<int:company_id>/tasks/<int:task_id>/complete", methods=["POST"])
def complete_company_task(company_id, task_id):
    """Mark a task as complete."""
    try:
        service = TaskService()
        task = service.complete_task(task_id, company_id)
        logger.info("Completed task_id=%d for company_id=%d", task_id, company_id)
        return jsonify({"success": True, "task": task if isinstance(task, dict) else vars(task)})
    except LookupError:
        return jsonify({"error": "task not found"}), 404
    except Exception as e:
        logger.error("Error completing task: %s", str(e))
        return jsonify({"error": str(e)}), 400


@app.route("/api/crm/companies/<int:company_id>/tasks/<int:task_id>", methods=["PATCH"])
def update_company_task(company_id, task_id):
    payload = request.get_json(silent=True) or {}
    allowed = {"title", "description", "task_type", "status", "priority", "due_date", "assigned_to"}
    updates = {k: payload.get(k) for k in allowed if k in payload}

    if not updates:
        return jsonify({"error": "no updatable fields provided"}), 400

    service = TaskService()
    task = service.get_task(task_id)
    if not task:
        abort(404)

    task_company_id = task.crm_company_id if hasattr(task, "crm_company_id") else task.get("crm_company_id")
    if int(task_company_id or 0) != int(company_id):
        abort(404)

    activity_title = "Task updated"
    if "status" in updates:
        if updates.get("status") == "completed":
            updates["completed_at"] = now_iso()
            activity_title = "Task completed"
        else:
            updates["completed_at"] = None
            activity_title = "Task reopened"

    updated_task = service.update_task(task_id, updates)
    service.activity_repo.create({
        "crm_company_id": company_id,
        "activity_type": "task",
        "title": activity_title,
        "body": f"{activity_title}: {updates.get('title') or (task.title if hasattr(task, 'title') else task.get('title', 'Task'))}",
        "created_at": now_iso(),
    })

    logger.info("Updated task_id=%d for company_id=%d", task_id, company_id)
    return jsonify({"success": True, "task": updated_task if isinstance(updated_task, dict) else vars(updated_task)})


@app.route("/api/crm/companies/<int:company_id>/tasks/<int:task_id>", methods=["DELETE"])
def delete_company_task(company_id, task_id):
    """Delete a task."""
    try:
        service = TaskService()
        service.delete_task(task_id, company_id)
        logger.info("Deleted task_id=%d for company_id=%d", task_id, company_id)
        return jsonify({"success": True})
    except LookupError:
        abort(404)
    except Exception as e:
        logger.error("Error deleting task: %s", str(e))
        return jsonify({"error": str(e)}), 400


@app.route("/api/crm/companies/<int:company_id>/intelligence", methods=["GET"])
def get_company_intelligence(company_id):
    service = IntelligenceService()
    intelligence = service.get_intelligence(company_id)
    if not intelligence:
        abort(404)
    payload = _to_plain_dict(intelligence)
    if isinstance(payload.get("data"), dict):
        payload = {**payload, **payload.get("data", {})}
    return jsonify({"success": True, "intelligence": payload})


@app.route("/api/crm/companies/<int:company_id>/intelligence/refresh", methods=["POST"])
def refresh_company_intelligence(company_id):
    service = IntelligenceService()
    intelligence = service.refresh_intelligence(company_id)
    payload = _to_plain_dict(intelligence)
    if isinstance(payload.get("data"), dict):
        payload = {**payload, **payload.get("data", {})}
    return jsonify({"success": True, "intelligence": payload})


@app.route("/api/crm/companies/<int:company_id>/reports/generate", methods=["POST"])
def generate_company_report(company_id):
    service = ReportService()
    company = CompanyService().get_company(company_id)
    if not company:
        abort(404)
    report_payload = _build_company_report_payload(company_id)
    report_doc = service.create_report({
        "crm_company_id": company_id,
        "report_type": "company",
        "report_name": f"{report_payload['company_name']} — Company Report",
        "report_data": report_payload,
        "executive_summary": report_payload.get("executive_summary"),
    })
    report_payload_out = _to_plain_dict(report_doc)
    if report_payload_out.get("crm_company_id") is not None:
        report_payload_out["company_id"] = report_payload_out["crm_company_id"]
    return jsonify({"success": True, "report": report_payload_out})


@app.route("/api/crm/companies/<int:company_id>/reports", methods=["GET"])
def list_company_reports(company_id):
    service = ReportService()
    items = service.list_reports(company_id, page=1, per_page=100).get("items", [])
    return jsonify({"reports": [_to_plain_dict(item) for item in items]})


@app.route("/api/reports/operations/generate", methods=["POST"])
def generate_operations_report():
    service = ReportService()
    report_payload = _build_operations_report_payload()
    try:
        report_doc = service.create_report({
            "report_type": "operations",
            "report_name": "Operations Report",
            "report_data": report_payload,
            "executive_summary": report_payload.get("executive_summary"),
        })
    except ValueError as exc:
        logger.warning("Operations report not persisted: %s", exc)
        return jsonify({"success": False, "error": str(exc)}), 400
    return jsonify({"success": True, "report": _to_plain_dict(report_doc)})


@app.route("/api/reports", methods=["GET"])
def list_reports():
    service = ReportService()
    items = service.list_reports(page=1, per_page=100).get("items", [])
    return jsonify({"reports": [_to_plain_dict(item) for item in items]})


@app.route("/api/reports/<int:report_id>", methods=["GET"])
def get_report(report_id):
    service = ReportService()
    report = service.get_report(report_id)
    if not report:
        abort(404)
    report_payload = _to_plain_dict(report)
    report_payload["report_data"] = report_payload.get("report_data") or {}
    return jsonify({"report": report_payload})


@app.route("/api/reports/<int:report_id>/export", methods=["POST"])
def export_report(report_id):
    payload = request.get_json(silent=True) or {}
    fmt = (payload.get("format") or "markdown").lower()
    service = ReportService()
    report = service.get_report(report_id)
    if not report:
        abort(404)
    report_payload = _to_plain_dict(report)
    report_data = report_payload.get("report_data") or {}
    executive_summary = report_data.get("executive_summary") or report_payload.get("executive_summary") or ""
    company_name = report_data.get("company_name") or report_data.get("summary", {}).get("company_name") or report_payload.get("report_name")
    recommended_services = report_data.get("commercial_opportunity", {}).get("recommended_services") or report_data.get("service_opportunities") or []
    risks = report_data.get("risk_assessment", {}).get("risks") or report_data.get("risk_analysis", {}).get("potential_risks") or []
    action_plan = report_data.get("action_plan") or {}

    def _format_list(items):
        if not items:
            return "- None listed"
        return "\n".join(f"- {item}" for item in items if item)

    if fmt == "pdf":
        content = f"# {report_payload.get('report_name')}\n\n## Executive Summary\n\n{executive_summary}\n\n## Company Focus\n\n- Company: {company_name}\n- Priority Score: {report_data.get('commercial_opportunity', {}).get('priority_score', 'N/A')}\n- Opportunity Type: {report_data.get('commercial_assessment', {}).get('commercial_opportunity', 'N/A')}\n\n## Recommended Services\n\n{_format_list([service.get('service') if isinstance(service, dict) else str(service) for service in recommended_services])}\n\n## Risk Assessment\n\n{_format_list(risks)}\n\n## Action Plan\n\n{_format_list([value for values in action_plan.values() if isinstance(values, list) for value in values])}\n"
    elif fmt == "docx":
        content = f"# {report_payload.get('report_name')}\n\n## Executive Summary\n\n{executive_summary}\n\n## Recommended Services\n\n{_format_list([service.get('service') if isinstance(service, dict) else str(service) for service in recommended_services])}\n"
    else:
        content = f"# {report_payload.get('report_name')}\n\n## Executive Summary\n\n{executive_summary}\n\n## Recommended Services\n\n{_format_list([service.get('service') if isinstance(service, dict) else str(service) for service in recommended_services])}\n\n## Risk Assessment\n\n{_format_list(risks)}\n\n## Action Plan\n\n{_format_list([value for values in action_plan.values() if isinstance(values, list) for value in values])}\n"
    return jsonify({"success": True, "format": fmt, "content": content, "download_name": f"{report_payload.get('report_name', 'report').lower().replace(' ', '-')}.{fmt}"})


@app.route("/api/crm/companies/<int:company_id>/deals", methods=["POST"])
def add_company_deal(company_id):
    payload = request.get_json(silent=True) or {}
    title = (payload.get("title") or "New deal").strip()
    if not title:
        return jsonify({"error": "title is required"}), 400
    pipeline_service = PipelineService()
    company_service = CompanyService()

    stage = _crm_deal_stage_to_frontend(payload.get("stage"))
    value = int(payload.get("value") or 0)
    probability = max(0, min(100, int(payload.get("probability") or 0)))
    expected_close_at = payload.get("expectedCloseAt") or payload.get("expected_close_at")
    owner = (payload.get("owner") or "MedNovaOS").strip() or "MedNovaOS"
    description = (payload.get("description") or "").strip()
    contact_id = payload.get("contactId") or payload.get("contact_id")
    if contact_id in {None, ""}:
        contact_id = None

    created = pipeline_service.create_deal(company_id, {
        "crm_contact_id": contact_id,
        "title": title,
        "stage": stage,
        "value": value,
        "currency": payload.get("currency") or "NGN",
        "probability": probability,
        "expected_close_at": expected_close_at,
        "owner": owner,
        "description": description,
    })
    company_service.add_activity(company_id, "deal", "Deal created", f"Created deal {title} in {stage} stage")
    return jsonify({"success": True, "deal": _crm_deal_payload_from_row(created)})


@app.route("/api/crm/companies/<int:company_id>/deals/<int:deal_id>", methods=["PATCH"])
def update_company_deal(company_id, deal_id):
    payload = request.get_json(silent=True) or {}
    pipeline_service = PipelineService()
    company_service = CompanyService()

    # verify exist
    existing = pipeline_service.deal_repo.get_by_id(deal_id)
    if not existing or (getattr(existing, 'crm_company_id', None) or existing.get('crm_company_id')) != company_id:
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
            # rely on contact repository validation
            updates["crm_contact_id"] = int(contact_value)
    if not updates:
        return jsonify({"error": "no updatable fields provided"}), 400

    updated = pipeline_service.update_deal(deal_id, updates)
    # activity
    if "stage" in updates and updates.get("stage") != getattr(existing, "stage", None):
        if updates["stage"] in {"won", "lost"}:
            title = "Deal won" if updates["stage"] == "won" else "Deal lost"
            company_service.add_activity(company_id, "deal", title, f"{title} deal {getattr(existing, 'title', existing.get('title'))}")
        else:
            company_service.add_activity(company_id, "deal", "Deal moved", f"Moved deal {getattr(existing, 'title', existing.get('title'))} to {updates['stage']}")
    else:
        company_service.add_activity(company_id, "deal", "Deal updated", f"Updated deal {getattr(existing, 'title', existing.get('title'))}")

    return jsonify({"success": True, "deal": _crm_deal_payload_from_row(updated)})


@app.route("/api/crm/companies/<int:company_id>/deals/<int:deal_id>", methods=["DELETE"])
def delete_company_deal(company_id, deal_id):
    pipeline_service = PipelineService()
    company_service = CompanyService()
    existing = pipeline_service.deal_repo.get_by_id(deal_id)
    if not existing or (getattr(existing, 'crm_company_id', None) or existing.get('crm_company_id')) != company_id:
        abort(404)
    pipeline_service.delete_deal(deal_id)
    company_service.add_activity(company_id, "deal", "Deal deleted", f"Deleted deal {getattr(existing, 'title', existing.get('title'))}")
    return jsonify({"success": True})


@app.route("/api/crm/companies/from-opportunity", methods=["POST"])
def add_company_to_crm():
    payload = request.get_json(silent=True) or {}
    company_name = (payload.get("company_name") or payload.get("company") or "").strip()
    if not company_name:
        return jsonify({"error": "company_name is required"}), 400

    crm_service = CRMService()
    company_id, company_row, created = crm_service.create_company_from_payload(payload)

    intelligence_service = IntelligenceService()
    intelligence = intelligence_service.get_intelligence(company_id)
    if intelligence is None or created:
        try:
            intelligence = intelligence_service.compute_intelligence(company_id)
        except Exception:
            logger.exception("Failed to enrich CRM company intelligence: %s", company_id)
            intelligence = None

    return jsonify({
        "success": True,
        "company_id": company_id,
        "company_name": company_row.get("company_name") if company_row else payload.get("company_name"),
        "created": created,
        "exists": not created,
        "message": "Company added successfully" if created else "This company already exists in your CRM.",
        "status": "created" if created else "exists",
        "company": company_row,
        "intelligence": _to_plain_dict(intelligence) if intelligence else None,
    })


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
    from backend.cloud.sync_to_supabase import get_last_cloud_sync_summary

    summary = get_last_cloud_sync_summary()
    if not summary:
        summary = {"status": "idle", "mode": "supabase", "message": "No sync has been run yet."}
    return jsonify(summary)


@app.route("/admin/cloud-sync", methods=["POST"])
def admin_cloud_sync():
    return jsonify({"status": "skipped", "mode": "supabase", "message": "Cloud sync is managed through the Supabase-backed migration pipeline."})


@app.route("/admin/cloud-sync/status")
def admin_cloud_sync_status():
    from backend.cloud.sync_to_supabase import get_last_cloud_sync_summary

    return jsonify(get_last_cloud_sync_summary())


@app.route("/api/health")
def health_check():
    database_path = os.getenv("MEDNOVA_DB_PATH") or os.getenv("DATABASE_PATH") or str(BASE_DIR / "database" / "nafdac_intelligence.db")
    return jsonify({"status": "ok", "database": database_path})


@app.route("/health")
def health_check_alias():
    return health_check()


@app.route("/api/ready")
def readiness_check():
    from backend.database.db import SupabaseDB

    db = SupabaseDB()
    mode = "supabase" if db.client is not None else "sqlite"
    return jsonify({"status": "ok", "mode": mode, "services": {"supabase": db.client is not None}})


@app.route("/ready")
def readiness_check_alias():
    return readiness_check()


@app.route("/api/cron/greenbook-sync", methods=["POST", "GET"])
def cron_greenbook_sync():
    if not _verify_cron_secret():
        return jsonify({"success": False, "message": "Invalid or missing cron secret."}), 403

    summary = run_sync()
    return jsonify(summary)


@app.route("/api/cron/greenbook-sync/status", methods=["GET"])
def cron_greenbook_sync_status():
    return admin_sync_status()


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
