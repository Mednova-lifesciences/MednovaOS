from __future__ import annotations

from typing import Any, Optional

from backend.database.repositories import ContactRepository, ActivityRepository
from backend.logging_utils import get_logger
from backend.models import Contact
from backend.utils import now_iso

logger = get_logger("contact_service")


class ContactService:
    def __init__(self, contact_repo: Optional[ContactRepository] = None, activity_repo: Optional[ActivityRepository] = None):
        self.contact_repo = contact_repo or ContactRepository()
        self.activity_repo = activity_repo or ActivityRepository()

    def get_contact(self, contact_id: int) -> Contact | None:
        return self.contact_repo.get_by_id(contact_id)

    def list_contacts(self, company_id: int | None = None, page: int = 1, per_page: int = 20) -> dict:
        filters = {"crm_company_id": company_id} if company_id else None
        result = self.contact_repo.paginate(page=page, per_page=per_page, filters=filters, order="created_at.desc")
        return {
            "items": result.items,
            "total": result.total,
            "page": result.page,
            "per_page": result.per_page,
            "pages": result.pages,
        }

    def search_contacts(self, query: str, page: int = 1, per_page: int = 20) -> dict:
        results = self.contact_repo.search(query, order="created_at.desc")
        paginated = results[(page - 1) * per_page : page * per_page]
        return {
            "items": paginated,
            "total": len(results),
            "page": page,
            "per_page": per_page,
            "pages": max(1, (len(results) + per_page - 1) // per_page),
        }

    def create_contact(self, company_id: int, payload: dict[str, Any]) -> Contact | dict:
        logger.info("Creating contact for company: id=%s", company_id)
        payload["crm_company_id"] = company_id
        payload["created_at"] = now_iso()
        contact = self.contact_repo.create(payload)

        # Log activity
        if isinstance(contact, dict):
            contact_name = contact.get("full_name", "Unknown")
        else:
            contact_name = contact.full_name

        self.activity_repo.create({
            "crm_company_id": company_id,
            "activity_type": "contact",
            "title": "Contact added",
            "body": f"Added contact: {contact_name}",
            "created_at": now_iso(),
        })

        return contact

    def update_contact(self, contact_id: int, payload: dict[str, Any]) -> Contact | dict:
        logger.info("Updating contact: id=%s", contact_id)
        payload["updated_at"] = now_iso()
        return self.contact_repo.update(contact_id, payload)

    def delete_contact(self, contact_id: int) -> bool:
        logger.info("Deleting contact: id=%s", contact_id)
        return self.contact_repo.delete(contact_id)
