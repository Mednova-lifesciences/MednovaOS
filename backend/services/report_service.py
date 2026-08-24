from __future__ import annotations

from typing import Any, Optional

from backend.database.repositories import ReportRepository
from backend.logging_utils import get_logger
from backend.models import Report
from backend.utils import now_iso

logger = get_logger("report_service")


class ReportService:
    def __init__(self, report_repo: Optional[ReportRepository] = None):
        self.report_repo = report_repo or ReportRepository()

    def get_report(self, report_id: int) -> Report | None:
        return self.report_repo.get_by_id(report_id)

    def list_reports(self, company_id: int | None = None, page: int = 1, per_page: int = 20) -> dict:
        filters = {"crm_company_id": company_id} if company_id else None
        result = self.report_repo.paginate(page=page, per_page=per_page, filters=filters, order="created_at.desc")
        return {
            "items": result.items,
            "total": result.total,
            "page": result.page,
            "per_page": result.per_page,
            "pages": result.pages,
        }

    def create_report(self, payload: dict[str, Any]) -> Report | dict:
        logger.info("Creating report: type=%s", payload.get("report_type"))
        payload["created_at"] = now_iso()
        payload["crm_company_id"] = payload.get("crm_company_id") or payload.get("company_id")
        if payload.get("crm_company_id") is None:
            message = "crm_company_id is required to create crm_reports"
            logger.warning(message)
            raise ValueError(message)
        return self.report_repo.create(payload)

    def update_report(self, report_id: int, payload: dict[str, Any]) -> Report | dict:
        logger.info("Updating report: id=%s", report_id)
        payload["updated_at"] = now_iso()
        return self.report_repo.update(report_id, payload)

    def delete_report(self, report_id: int) -> bool:
        logger.info("Deleting report: id=%s", report_id)
        return self.report_repo.delete(report_id)
