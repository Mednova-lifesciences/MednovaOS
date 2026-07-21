from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Any


def _normalize_company_name(value: str) -> str:
    return (value or "").strip().lower()


def _coerce_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    return []


def _serialize_list(values: list[str]) -> str:
    return ", ".join(values)


def _company_payload_from_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "company_name": row["company_name"],
        "country": row["country"],
        "opportunity_score": row["opportunity_score"],
        "portfolio_summary": row["portfolio_summary"],
        "source": row["source"],
        "registration_numbers": _coerce_list(row["registration_numbers"]),
        "dosage_forms": _coerce_list(row["dosage_forms"]),
        "therapeutic_areas": _coerce_list(row["therapeutic_areas"]),
        "registration_dates": _coerce_list(row["registration_dates"]),
    }


def add_activity(conn: sqlite3.Connection, crm_company_id: int, activity_type: str, title: str, body: str) -> int:
    cursor = conn.execute(
        "INSERT INTO crm_activities (crm_company_id, activity_type, title, body) VALUES (?, ?, ?, ?)",
        (crm_company_id, activity_type, title, body),
    )
    return int(cursor.lastrowid)


def add_note(conn: sqlite3.Connection, crm_company_id: int, body: str) -> int:
    cursor = conn.execute(
        "INSERT INTO crm_notes (crm_company_id, body) VALUES (?, ?)",
        (crm_company_id, body),
    )
    return int(cursor.lastrowid)


def create_contact(conn: sqlite3.Connection, crm_company_id: int, contact_data: dict[str, Any]) -> int:
    full_name = (contact_data.get("full_name") or contact_data.get("name") or "Primary Contact").strip()
    role = (contact_data.get("role") or contact_data.get("position") or "Primary contact").strip()
    department = (contact_data.get("department") or "Business Development").strip()
    email = (contact_data.get("email") or "").strip()
    phone = (contact_data.get("phone") or "").strip()
    source = (contact_data.get("source") or "CRM").strip()
    cursor = conn.execute(
        """
        INSERT INTO crm_contacts (
            crm_company_id, full_name, role, department, email, phone, source
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (crm_company_id, full_name, role, department, email, phone, source),
    )
    return int(cursor.lastrowid)


def create_task(conn: sqlite3.Connection, crm_company_id: int, task_data: dict[str, Any]) -> int:
    title = (task_data.get("title") or task_data.get("name") or "Follow up").strip()
    task_type = (task_data.get("task_type") or task_data.get("type") or "follow-up").strip()
    description = (task_data.get("description") or "").strip()
    due_date = task_data.get("due_date") or task_data.get("dueDate") or None
    assigned_to = (task_data.get("assigned_to") or task_data.get("assignee") or "MedNovaOS").strip()
    status = (task_data.get("status") or "pending").strip()
    priority = (task_data.get("priority") or "medium").strip()
    cursor = conn.execute(
        """
        INSERT INTO crm_tasks (
            crm_company_id, title, description, task_type, status, priority, due_date, assigned_to
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (crm_company_id, title, description, task_type, status, priority, due_date, assigned_to),
    )
    return int(cursor.lastrowid)


def complete_task(conn: sqlite3.Connection, crm_company_id: int, task_id: int) -> sqlite3.Row:
    task = conn.execute(
        "SELECT * FROM crm_tasks WHERE id = ? AND crm_company_id = ?",
        (task_id, crm_company_id),
    ).fetchone()
    if not task:
        raise LookupError("task not found")

    conn.execute(
        "UPDATE crm_tasks SET status = ?, completed_at = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ? AND crm_company_id = ?",
        ("completed", datetime.now(timezone.utc).replace(microsecond=0).isoformat(), task_id, crm_company_id),
    )
    add_activity(conn, crm_company_id, "task", "Task completed", f"Completed task: {task['title']}")
    return conn.execute("SELECT * FROM crm_tasks WHERE id = ?", (task_id,)).fetchone()


def list_contacts(conn: sqlite3.Connection, crm_company_id: int | None = None) -> list[sqlite3.Row]:
    if crm_company_id is None:
        return conn.execute(
            "SELECT * FROM crm_contacts ORDER BY created_at DESC"
        ).fetchall()
    return conn.execute(
        "SELECT * FROM crm_contacts WHERE crm_company_id = ? ORDER BY created_at DESC",
        (crm_company_id,),
    ).fetchall()


def list_tasks(conn: sqlite3.Connection, crm_company_id: int | None = None) -> list[sqlite3.Row]:
    if crm_company_id is None:
        return conn.execute(
            "SELECT * FROM crm_tasks ORDER BY due_date IS NULL, due_date, created_at DESC"
        ).fetchall()
    return conn.execute(
        "SELECT * FROM crm_tasks WHERE crm_company_id = ? ORDER BY due_date IS NULL, due_date, created_at DESC",
        (crm_company_id,),
    ).fetchall()


def create_company_from_payload(conn: sqlite3.Connection, payload_data: dict[str, Any]) -> tuple[int, dict[str, Any], bool]:
    company_name = (payload_data.get("company_name") or payload_data.get("company") or "").strip()
    if not company_name:
        raise ValueError("company_name is required")

    normalized_name = _normalize_company_name(company_name)
    existing = conn.execute(
        "SELECT id, company_name, country, opportunity_score, portfolio_summary, source, report_context, greenbook_products_json, registration_numbers, dosage_forms, therapeutic_areas, registration_dates FROM crm_companies WHERE LOWER(company_name) = ? LIMIT 1",
        (normalized_name,),
    ).fetchone()

    payload = {
        "company_name": company_name,
        "country": payload_data.get("country") or "Unknown",
        "opportunity_score": int(payload_data.get("opportunity_score") or 0),
        "portfolio_summary": payload_data.get("portfolio_summary") or "",
        "source": payload_data.get("source") or "Green Book",
        "registration_numbers": _coerce_list(payload_data.get("registration_numbers") or []),
        "dosage_forms": _coerce_list(payload_data.get("dosage_forms") or []),
        "therapeutic_areas": _coerce_list(payload_data.get("therapeutic_areas") or []),
        "registration_dates": _coerce_list(payload_data.get("registration_dates") or []),
    }

    if existing:
        company_id = existing["id"]
        conn.execute(
            """
            UPDATE crm_companies
            SET country = ?, opportunity_score = ?, portfolio_summary = ?, source = ?, report_context = ?,
                greenbook_products_json = ?, registration_numbers = ?, dosage_forms = ?, therapeutic_areas = ?,
                registration_dates = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                payload["country"],
                payload["opportunity_score"],
                payload["portfolio_summary"],
                payload["source"],
                payload_data.get("report_context") or "",
                payload_data.get("greenbook_products_json") or "[]",
                _serialize_list(payload["registration_numbers"]),
                _serialize_list(payload["dosage_forms"]),
                _serialize_list(payload["therapeutic_areas"]),
                _serialize_list(payload["registration_dates"]),
                company_id,
            ),
        )
        created = False
    else:
        conn.execute(
            """
            INSERT INTO crm_companies (
                company_name, country, opportunity_score, portfolio_summary, source,
                report_context, greenbook_products_json, registration_numbers, dosage_forms,
                therapeutic_areas, registration_dates, opportunity_status, pipeline_stage
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload["company_name"],
                payload["country"],
                payload["opportunity_score"],
                payload["portfolio_summary"],
                payload["source"],
                payload_data.get("report_context") or "",
                payload_data.get("greenbook_products_json") or "[]",
                _serialize_list(payload["registration_numbers"]),
                _serialize_list(payload["dosage_forms"]),
                _serialize_list(payload["therapeutic_areas"]),
                _serialize_list(payload["registration_dates"]),
                payload_data.get("status") or "New",
                payload_data.get("pipeline_stage") or "Lead",
            ),
        )
        company_id = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
        created = True

    add_activity(conn, company_id, "company", "Company created", f"Imported from {payload['source']} for {company_name}")

    note_body = (payload_data.get("notes") or "").strip()
    if note_body:
        add_note(conn, company_id, note_body)

    existing_contact = conn.execute("SELECT id FROM crm_contacts WHERE crm_company_id = ? LIMIT 1", (company_id,)).fetchone()
    if not existing_contact:
        create_contact(
            conn,
            company_id,
            {
                "full_name": f"{company_name} Commercial Lead",
                "role": "Commercial Lead",
                "department": "Business Development",
                "email": "",
                "phone": "",
                "source": payload["source"],
            },
        )

    existing_task = conn.execute("SELECT id FROM crm_tasks WHERE crm_company_id = ? LIMIT 1", (company_id,)).fetchone()
    if not existing_task:
        create_task(
            conn,
            company_id,
            {
                "title": f"Review opportunity for {company_name}",
                "task_type": "follow-up",
                "due_date": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
                "assigned_to": "MedNovaOS",
                "status": "pending",
                "priority": "medium",
                "description": "Initial follow-up generated from the opportunity workflow.",
            },
        )

    conn.commit()
    return company_id, payload, created
