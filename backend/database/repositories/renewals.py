from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from backend.database.repositories.base import BaseRepository
from backend.database.repositories.products import ProductRepository
from backend.logging_utils import get_logger


class RenewalRepository(BaseRepository[dict]):
    table_name = "products"
    model_class = None
    search_fields = ["product_name", "registration_number", "generic_name", "active_ingredient"]

    def _normalize_row(self, row: dict | None) -> dict:
        if row is None:
            return {}
        if not isinstance(row, dict):
            row = dict(row)

        return {
            "renewal_id": row.get("id"),
            "product_name": row.get("product_name") or None,
            "nafdac_number": row.get("registration_number") or None,
            "product_category": row.get("category_name") or row.get("product_category") or None,
            "applicant_name": row.get("applicant_name") or None,
            "manufacturer_name": row.get("manufacturer_name") or None,
            "expiry_date": row.get("expiry_date") or None,
            "status": row.get("status") or None,
            "created_at": row.get("created_at") or row.get("approval_date") or None,
        }

    def list_page(
        self,
        *,
        months: int = 12,
        page: int = 1,
        page_size: int = 100,
        query: str = "",
    ) -> tuple[list[dict], int, dict]:
        if self.db.client is None:
            raise RuntimeError("Supabase unavailable")

        page = max(int(page or 1), 1)
        page_size = max(min(int(page_size or 100), 1000), 1)
        offset = (page - 1) * page_size

        today = datetime.utcnow().date()
        # approximate month window using 31 days per month to avoid extra deps
        end_date = (today + timedelta(days=months * 31)).isoformat()
        start_date = today.isoformat()

        selected_columns = (
            "id, registration_number, product_name, approval_date, expiry_date, status, applicant_id, manufacturer_id, category_id"
        )

        query_obj = self.db.client.table(self.table_name).select(selected_columns)
        # apply date window
        query_obj = query_obj.gte("expiry_date", start_date).lte("expiry_date", end_date)

        # optional search across product fields
        if query:
            # Supabase doesn't support complex OR across multiple fields easily here; fallback to server-side filtering
            # keep query on product_name when provided
            query_obj = query_obj.ilike("product_name", f"%{query}%")

        # ordering by expiry ascending
        query_obj = query_obj.order("expiry_date", desc=False)

        count_query = self.db.client.table(self.table_name).select("id", count="exact", head=True)
        count_query = count_query.gte("expiry_date", start_date).lte("expiry_date", end_date)

        total_resp = count_query.execute()
        total = int(total_resp.count or 0)

        resp = query_obj.limit(page_size).offset(offset).execute()
        raw_rows = [row for row in (resp.data or []) if isinstance(row, dict)]

        product_repo = ProductRepository(self.db)
        logger = get_logger("renewals.repository")

        rows: list[dict] = []
        for row in raw_rows:
            normalized = product_repo._normalize_product_row(row)
            # build output expected by template
            out = {
                "company": row.get("company") or normalized.get("applicant_name") or normalized.get("manufacturer_name"),
                "manufacturer": normalized.get("manufacturer_name"),
                "product_name": normalized.get("product_name"),
                "category": normalized.get("product_category"),
                "product_category": normalized.get("product_category"),
                "applicant": normalized.get("applicant_name"),
                "applicant_name": normalized.get("applicant_name"),
                "nafdac_number": normalized.get("nafdac_number"),
                "service_type": row.get("recommended_services") or row.get("service_type") or None,
                "estimated_value": row.get("estimated_value") or None,
                "probability": row.get("probability") or None,
                "expiry_date": normalized.get("expiry_date"),
                "status": normalized.get("status"),
            }
            # Log missing lookups with product id
            prod_id = row.get("id")
            if not out.get("product_category"):
                logger.warning("Missing category for product id=%s", prod_id)
            if not out.get("applicant_name"):
                logger.warning("Missing applicant for product id=%s", prod_id)

            rows.append(out)

        summary = {"total": total}
        return rows, total, summary


__all__ = ["RenewalRepository"]
