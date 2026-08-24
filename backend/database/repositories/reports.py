from __future__ import annotations

from typing import Any

from backend.database.repositories.base import BaseRepository
from backend.models import Report


class ReportRepository(BaseRepository[Report]):
    table_name = "crm_reports"
    model_class = Report
    search_fields = ["report_type", "report_name", "executive_summary"]

    def list_reports(self, company_id: int) -> list[Report]:
        return self.list(filters={"crm_company_id": company_id}, order="created_at.desc")


__all__ = ["ReportRepository"]
