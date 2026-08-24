from __future__ import annotations

from typing import Any
import json

from backend.database.repositories.base import BaseRepository
from backend.models import Intelligence


class IntelligenceRepository(BaseRepository[Intelligence]):
    table_name = "crm_company_intelligence"
    model_class = Intelligence
    search_fields = ["search_status", "source_summary"]

    def get_by_company_id(self, company_id: int) -> Intelligence | None:
        rows = self.list(filters={"crm_company_id": company_id}, limit=1)
        return rows[0] if rows else None

    def upsert_by_company_id(self, payload: dict[str, Any], on_conflict: str | None = "crm_company_id") -> Intelligence | dict:
        return self.upsert(payload, on_conflict=on_conflict)

    # tavily search cache helpers
    def get_tavily_cache(self, company_id: int, search_query: str) -> dict | None:
        rows = self.db.table_select("tavily_search_cache", filters={"company_id": company_id, "search_query": search_query}, limit=1)
        return rows[0] if rows else None

    def upsert_tavily_cache(self, company_id: int, search_query: str, results: dict, ttl_days: int = 7) -> dict:
        now = __import__("backend.utils", fromlist=["now_iso"]).now_iso()
        existing = self.get_tavily_cache(company_id, search_query)
        payload = {
            "company_id": company_id,
            "search_query": search_query,
            "search_results_json": json.dumps(results),
            "search_date": now,
            "last_refreshed_at": now,
            "ttl_days": ttl_days,
        }
        if existing:
            # update the existing row
            return self.db.update("tavily_search_cache", existing.get("id"), payload)
        return self.db.insert("tavily_search_cache", payload)


__all__ = ["IntelligenceRepository"]
