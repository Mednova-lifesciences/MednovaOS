from __future__ import annotations

from typing import Any

from backend.database.repositories.base import BaseRepository
from backend.models import Company


class CompanyRepository(BaseRepository[Company]):
    table_name = "crm_companies"
    model_class = Company
    search_fields = [
        "company_name",
        "country",
        "source",
        "portfolio_summary",
        "opportunity_status",
        "pipeline_stage",
    ]

    def _allow_local_sqlite(self) -> bool:
        return not self.db.client and self.db._has_local_db_override()

    def _require_supabase_client(self):
        if not self.db.client and not self._allow_local_sqlite():
            raise RuntimeError("Supabase is required for CRM company operations")

    def upsert(self, payload: dict[str, Any], on_conflict: str | None = "company_name") -> Company | dict:
        return super().upsert(payload, on_conflict=on_conflict)


__all__ = ["CompanyRepository"]
