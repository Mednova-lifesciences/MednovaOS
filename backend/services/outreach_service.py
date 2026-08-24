from __future__ import annotations

from typing import Any, Optional

from backend.database.repositories import OutreachRepository, ActivityRepository
from backend.logging_utils import get_logger
from backend.models import OutreachEmail
from backend.utils import now_iso

logger = get_logger("outreach_service")


class OutreachService:
    def __init__(self, outreach_repo: Optional[OutreachRepository] = None, activity_repo: Optional[ActivityRepository] = None):
        self.outreach_repo = outreach_repo or OutreachRepository()
        self.activity_repo = activity_repo or ActivityRepository()

    def get_outreach(self, email_id: int) -> OutreachEmail | None:
        return self.outreach_repo.get_by_id(email_id)

    def list_outreach(self, company_id: int, page: int = 1, per_page: int = 20) -> dict:
        result = self.outreach_repo.paginate(
            page=page,
            per_page=per_page,
            filters={"crm_company_id": company_id},
            order="created_at.desc",
        )
        return {
            "items": result.items,
            "total": result.total,
            "page": result.page,
            "per_page": result.per_page,
            "pages": result.pages,
        }

    def create_outreach(self, company_id: int, payload: dict[str, Any]) -> OutreachEmail | dict:
        logger.info("Creating outreach for company: id=%s", company_id)
        payload["crm_company_id"] = company_id
        payload["created_at"] = now_iso()
        outreach = self.outreach_repo.create(payload)

        if isinstance(outreach, dict):
            subject = outreach.get("subject", "Unknown")
        else:
            subject = outreach.subject

        self.activity_repo.create({
            "crm_company_id": company_id,
            "activity_type": "outreach",
            "title": "Outreach email created",
            "body": f"Created outreach: {subject}",
            "created_at": now_iso(),
        })

        return outreach

    def update_outreach(self, email_id: int, payload: dict[str, Any]) -> OutreachEmail | dict:
        logger.info("Updating outreach: id=%s", email_id)
        payload["updated_at"] = now_iso()
        return self.outreach_repo.update(email_id, payload)

    def delete_outreach(self, email_id: int) -> bool:
        logger.info("Deleting outreach: id=%s", email_id)
        return self.outreach_repo.delete(email_id)

    def send_outreach(self, email_id: int, company_id: int) -> bool:
        logger.info("Sending outreach: id=%s", email_id)
        now = now_iso()
        self.outreach_repo.update(email_id, {
            "status": "sent",
            "updated_at": now,
        })

        self.activity_repo.create({
            "crm_company_id": company_id,
            "activity_type": "outreach",
            "title": "Outreach email sent",
            "body": "Outreach email was sent successfully",
            "created_at": now,
        })

        return True
