from __future__ import annotations

from typing import Any, Optional

from backend.database.repositories import CompanyRepository, ContactRepository, TaskRepository, ActivityRepository, NoteRepository
from backend.logging_utils import get_logger
from backend.models import Company, Contact, Task
from backend.utils import now_iso

logger = get_logger("company_service")


class CompanyService:
    def __init__(
        self,
        company_repo: Optional[CompanyRepository] = None,
        contact_repo: Optional[ContactRepository] = None,
        task_repo: Optional[TaskRepository] = None,
        activity_repo: Optional[ActivityRepository] = None,
        note_repo: Optional[NoteRepository] = None,
    ):
        self.company_repo = company_repo or CompanyRepository()
        self.contact_repo = contact_repo or ContactRepository()
        self.task_repo = task_repo or TaskRepository()
        self.activity_repo = activity_repo or ActivityRepository()
        self.note_repo = note_repo or NoteRepository()

    def get_company(self, company_id: int) -> Company | None:
        return self.company_repo.get_by_id(company_id)

    def list_companies(self, page: int = 1, per_page: int = 20, filters: dict | None = None) -> dict:
        result = self.company_repo.paginate(page=page, per_page=per_page, filters=filters, order="created_at.desc")
        return {
            "items": result.items,
            "total": result.total,
            "page": result.page,
            "per_page": result.per_page,
            "pages": result.pages,
        }

    def search_companies(self, query: str, page: int = 1, per_page: int = 20) -> dict:
        results = self.company_repo.search(query, order="created_at.desc")
        start = (max(page, 1) - 1) * per_page
        end = start + per_page
        paginated = results[start:end]
        return {
            "items": paginated,
            "total": len(results),
            "page": page,
            "per_page": per_page,
            "pages": max(1, (len(results) + per_page - 1) // per_page),
        }

    def create_company(self, payload: dict[str, Any]) -> Company | dict:
        normalized_payload = dict(payload or {})
        if not normalized_payload.get("company_name") and normalized_payload.get("company"):
            normalized_payload["company_name"] = normalized_payload["company"]

        logger.info("Creating company: %s", normalized_payload.get("company_name"))
        company_name = (normalized_payload.get("company_name") or "").strip()
        if not company_name:
            raise ValueError("company_name is required")

        normalized_payload["created_at"] = now_iso()
        company = self.company_repo.create(normalized_payload)

        if isinstance(company, dict):
            company_id = company.get("id")
        else:
            company_id = company.id

        # Add initial activity
        self.activity_repo.create({
            "crm_company_id": company_id,
            "activity_type": "company",
            "title": "Company created",
            "body": f"Created company: {company_name}",
            "created_at": now_iso(),
        })

        # Add primary contact if not present
        if not self.contact_repo.exists({"crm_company_id": company_id}):
            self.contact_repo.create({
                "crm_company_id": company_id,
                "full_name": f"{company_name} Commercial Lead",
                "role": "Commercial Lead",
                "department": "Business Development",
                "email": "",
                "phone": "",
                "source": normalized_payload.get("source") or "CRM",
                "created_at": now_iso(),
            })

        # Add initial task if not present
        if not self.task_repo.exists({"crm_company_id": company_id}):
            self.task_repo.create({
                "crm_company_id": company_id,
                "title": f"Review opportunity for {company_name}",
                "task_type": "follow-up",
                "status": "pending",
                "priority": "medium",
                "description": "Initial follow-up generated from the opportunity workflow.",
                "assigned_to": "MedNovaOS",
                "due_date": now_iso(),
                "created_at": now_iso(),
            })

        logger.info("Company created: id=%s", company_id)
        return company

    def update_company(self, company_id: int, payload: dict[str, Any]) -> Company | dict:
        logger.info("Updating company: id=%s", company_id)
        payload["updated_at"] = now_iso()
        return self.company_repo.update(company_id, payload)

    def delete_company(self, company_id: int) -> bool:
        logger.info("Deleting company: id=%s", company_id)
        return self.company_repo.delete(company_id)

    def get_company_detail(self, company_id: int) -> dict | None:
        logger.info("Getting company detail: id=%s", company_id)
        company = self.company_repo.get_by_id(company_id)
        if not company:
            return None

        contacts = self.contact_repo.list(filters={"crm_company_id": company_id}, order="created_at.desc")
        tasks = self.task_repo.list(filters={"crm_company_id": company_id}, order="due_date.asc")
        activities = self.activity_repo.list(filters={"crm_company_id": company_id}, order="created_at.desc")
        notes = self.note_repo.list(filters={"crm_company_id": company_id}, order="created_at.desc")

        return {
            "company": company,
            "contacts": contacts,
            "tasks": tasks,
            "activities": activities,
            "notes": notes,
        }

    def add_activity(self, company_id: int, activity_type: str, title: str, body: str) -> dict:
        logger.info("Adding activity to company: id=%s type=%s", company_id, activity_type)
        return self.activity_repo.create({
            "crm_company_id": company_id,
            "activity_type": activity_type,
            "title": title,
            "body": body,
            "created_at": now_iso(),
        })

    def add_note(self, company_id: int, body: str) -> dict:
        logger.info("Adding note to company: id=%s", company_id)
        note = self.note_repo.create({
            "crm_company_id": company_id,
            "body": body,
            "created_at": now_iso(),
        })
        self.add_activity(
            company_id,
            "note",
            "Note created",
            f"Added note: {body[:120]}",
        )
        return note
