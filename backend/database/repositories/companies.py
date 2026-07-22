from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from backend.database.db import SupabaseDB


db = SupabaseDB()


def _coerce_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    return []


def get_company(company_id: int) -> dict | None:
    return db.get_by_id("crm_companies", company_id)


def get_company_detail(company_id: int) -> dict:
    company = get_company(company_id)
    if not company:
        return None

    # products stored as JSON in greenbook_products_json
    products = []
    try:
        products = company.get("greenbook_products_json") or "[]"
        import json

        products = json.loads(products) if isinstance(products, str) else products
    except Exception:
        products = []

    activities = db.table_select("crm_activities", filters={"crm_company_id": company_id}, order="created_at.desc")
    notes = db.table_select("crm_notes", filters={"crm_company_id": company_id}, order="created_at.desc")
    contacts = db.table_select("crm_contacts", filters={"crm_company_id": company_id}, order="created_at.desc")
    tasks = db.table_select("crm_tasks", filters={"crm_company_id": company_id}, order="created_at.desc")

    return {
        "company": company,
        "products": products,
        "activities": activities,
        "notes": notes,
        "contacts": contacts,
        "tasks": tasks,
    }


def create_company_from_payload(payload_data: dict[str, Any]) -> tuple[int, dict, bool]:
    company_name = (payload_data.get("company_name") or payload_data.get("company") or "").strip()
    if not company_name:
        raise ValueError("company_name is required")

    normalized = company_name.strip().lower()
    # naive search: fetch small set then match
    existing_rows = db.table_select("crm_companies")
    existing = None
    for row in existing_rows:
        if (row.get("company_name") or "").strip().lower() == normalized:
            existing = row
            break

    payload = {
        "company_name": company_name,
        "country": payload_data.get("country") or "Unknown",
        "opportunity_score": int(payload_data.get("opportunity_score") or 0),
        "portfolio_summary": payload_data.get("portfolio_summary") or "",
        "source": payload_data.get("source") or "Green Book",
        "registration_numbers": ", ".join(_coerce_list(payload_data.get("registration_numbers") or [])),
        "dosage_forms": ", ".join(_coerce_list(payload_data.get("dosage_forms") or [])),
        "therapeutic_areas": ", ".join(_coerce_list(payload_data.get("therapeutic_areas") or [])),
        "registration_dates": ", ".join(_coerce_list(payload_data.get("registration_dates") or [])),
    }

    created = False
    if existing:
        company_id = existing["id"]
        update_payload = {
            "country": payload["country"],
            "opportunity_score": payload["opportunity_score"],
            "portfolio_summary": payload["portfolio_summary"],
            "source": payload["source"],
            "report_context": payload_data.get("report_context") or "",
            "greenbook_products_json": payload_data.get("greenbook_products_json") or "[]",
            "registration_numbers": payload["registration_numbers"],
            "dosage_forms": payload["dosage_forms"],
            "therapeutic_areas": payload["therapeutic_areas"],
            "registration_dates": payload["registration_dates"],
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        db.update("crm_companies", company_id, update_payload)
    else:
        insert_payload = {
            "company_name": payload["company_name"],
            "country": payload["country"],
            "opportunity_score": payload["opportunity_score"],
            "portfolio_summary": payload["portfolio_summary"],
            "source": payload["source"],
            "report_context": payload_data.get("report_context") or "",
            "greenbook_products_json": payload_data.get("greenbook_products_json") or "[]",
            "registration_numbers": payload["registration_numbers"],
            "dosage_forms": payload["dosage_forms"],
            "therapeutic_areas": payload["therapeutic_areas"],
            "registration_dates": payload["registration_dates"],
            "opportunity_status": payload_data.get("status") or "New",
            "pipeline_stage": payload_data.get("pipeline_stage") or "Lead",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        inserted = db.insert("crm_companies", insert_payload)
        company_id = int(inserted["id"]) if inserted and "id" in inserted else None
        created = True

    # add an initial activity and note if provided
    db.insert("crm_activities", {"crm_company_id": company_id, "activity_type": "company", "title": "Company created", "body": f"Imported from {payload['source']} for {company_name}", "created_at": datetime.now(timezone.utc).isoformat()})
    note_body = (payload_data.get("notes") or "").strip()
    if note_body:
        db.insert("crm_notes", {"crm_company_id": company_id, "body": note_body, "created_at": datetime.now(timezone.utc).isoformat()})

    # ensure primary contact and task
    contacts = db.table_select("crm_contacts", filters={"crm_company_id": company_id}, limit=1)
    if not contacts:
        db.insert("crm_contacts", {"crm_company_id": company_id, "full_name": f"{company_name} Commercial Lead", "role": "Commercial Lead", "department": "Business Development", "email": "", "phone": "", "source": payload["source"], "created_at": datetime.now(timezone.utc).isoformat()})
    tasks = db.table_select("crm_tasks", filters={"crm_company_id": company_id}, limit=1)
    if not tasks:
        due_date = datetime.now(timezone.utc).isoformat()
        db.insert("crm_tasks", {"crm_company_id": company_id, "title": f"Review opportunity for {company_name}", "task_type": "follow-up", "due_date": due_date, "assigned_to": "MedNovaOS", "status": "pending", "priority": "medium", "description": "Initial follow-up generated from the opportunity workflow.", "created_at": datetime.now(timezone.utc).isoformat()})

    company_row = db.get_by_id("crm_companies", company_id)
    return company_id, company_row, created


def add_activity(crm_company_id: int, activity_type: str, title: str, body: str) -> int:
    row = db.insert("crm_activities", {"crm_company_id": crm_company_id, "activity_type": activity_type, "title": title, "body": body, "created_at": datetime.now(timezone.utc).isoformat()})
    return int(row["id"]) if row and "id" in row else None


def add_note(crm_company_id: int, body: str) -> int:
    row = db.insert("crm_notes", {"crm_company_id": crm_company_id, "body": body, "created_at": datetime.now(timezone.utc).isoformat()})
    return int(row["id"]) if row and "id" in row else None


def create_contact(crm_company_id: int, contact_data: dict[str, Any]) -> int:
    full_name = (contact_data.get("full_name") or contact_data.get("name") or "Primary Contact").strip()
    role = (contact_data.get("role") or contact_data.get("position") or "Primary contact").strip()
    department = (contact_data.get("department") or "Business Development").strip()
    email = (contact_data.get("email") or "").strip()
    phone = (contact_data.get("phone") or "").strip()
    source = (contact_data.get("source") or "CRM").strip()
    row = db.insert("crm_contacts", {"crm_company_id": crm_company_id, "full_name": full_name, "role": role, "department": department, "email": email, "phone": phone, "source": source, "created_at": datetime.now(timezone.utc).isoformat()})
    return int(row["id"]) if row and "id" in row else None


def create_task(crm_company_id: int, task_data: dict[str, Any]) -> int:
    title = (task_data.get("title") or task_data.get("name") or "Follow up").strip()
    task_type = (task_data.get("task_type") or task_data.get("type") or "follow-up").strip()
    description = (task_data.get("description") or "").strip()
    due_date = task_data.get("due_date") or task_data.get("dueDate") or None
    assigned_to = (task_data.get("assigned_to") or task_data.get("assignee") or "MedNovaOS").strip()
    status = (task_data.get("status") or "pending").strip()
    priority = (task_data.get("priority") or "medium").strip()
    row = db.insert("crm_tasks", {"crm_company_id": crm_company_id, "title": title, "description": description, "task_type": task_type, "status": status, "priority": priority, "due_date": due_date, "assigned_to": assigned_to, "created_at": datetime.now(timezone.utc).isoformat()})
    return int(row["id"]) if row and "id" in row else None


def complete_task(crm_company_id: int, task_id: int) -> dict:
    task = db.get_by_id("crm_tasks", task_id)
    if not task or int(task.get("crm_company_id") or 0) != int(crm_company_id):
        raise LookupError("task not found")
    now = datetime.now(timezone.utc).isoformat()
    db.update("crm_tasks", task_id, {"status": "completed", "completed_at": now, "updated_at": now})
    add_activity(crm_company_id, "task", "Task completed", f"Completed task: {task.get('title')}")
    return db.get_by_id("crm_tasks", task_id)
