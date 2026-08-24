from __future__ import annotations

from typing import Any

from backend.database.repositories.base import BaseRepository


class ProductRepository(BaseRepository[dict]):
    table_name = "products"
    model_class = None
    search_fields = ["product_name", "registration_number", "generic_name", "active_ingredient"]

    def _fetch_lookup_rows(self, table: str, filters: dict | None = None, limit: int = 1000) -> list[dict]:
        try:
            rows = self.db.table_select(table, filters=filters, limit=limit)
        except Exception:
            return []
        return [row for row in rows if isinstance(row, dict)]

    def _resolve_lookup_value(self, table: str, lookup_id: Any, field: str) -> str | None:
        if lookup_id in (None, ""):
            return None
        rows = self._fetch_lookup_rows(table, filters={"id": lookup_id}, limit=1)
        if not rows:
            return None
        return rows[0].get(field)

    def _find_lookup_ids(self, table: str, field: str, value: str) -> list[Any]:
        if not value:
            return []
        rows = self._fetch_lookup_rows(table, filters={field: ("ilike", f"%{value}%")}, limit=1000)
        return [row.get("id") for row in rows if row.get("id") is not None]

    def _normalize_product_row(self, row: dict | None) -> dict:
        if row is None:
            return {}
        if not isinstance(row, dict):
            row = dict(row)
        registration_date = row.get("registration_date") or row.get("approval_date") or None
        return {
            "greenbook_product_id": row.get("id"),
            "product_name": row.get("product_name") or None,
            "ingredient_name": row.get("active_ingredient") or None,
            "product_category": self._resolve_lookup_value("categories", row.get("category_id"), "category_name") or row.get("category_name") or row.get("product_category") or row.get("therapeutic_area") or None,
            "nafdac_number": row.get("registration_number") or None,
            "registration_date": registration_date,
            "applicant_name": self._resolve_lookup_value("applicants", row.get("applicant_id"), "applicant_name") or row.get("applicant_name") or row.get("applicant") or None,
            "manufacturer_name": self._resolve_lookup_value("manufacturers", row.get("manufacturer_id"), "manufacturer_name") or row.get("manufacturer_name") or row.get("manufacturer") or None,
            "approval_date": row.get("approval_date") or None,
            "expiry_date": row.get("expiry_date") or None,
            "status": row.get("status") or None,
            "dosage_form": self._resolve_lookup_value("dosage_forms", row.get("dosage_form_id"), "form_name") or row.get("dosage_form") or row.get("dosage_form_name") or None,
            "route_of_administration": self._resolve_lookup_value("routes", row.get("route_id"), "route_name") or row.get("route_name") or row.get("route_of_administration") or None,
        }

    def _apply_product_filters(
        self,
        query_obj: Any,
        *,
        query: str = "",
        manufacturer: str = "",
        category: str = "",
        applicant: str = "",
        status: str = "",
        expiry: str = "",
    ) -> Any:
        if query:
            matching_ids: set[Any] = set()
            for field in self.search_fields:
                rows = self._fetch_lookup_rows(self.table_name, filters={field: ("ilike", f"%{query}%")}, limit=1000)
                for row in rows:
                    if row.get("id") is not None:
                        matching_ids.add(row.get("id"))
            if not matching_ids:
                return None
            query_obj = query_obj.in_("id", list(matching_ids))

        if manufacturer:
            manufacturer_ids = self._find_lookup_ids("manufacturers", "manufacturer_name", manufacturer)
            if not manufacturer_ids:
                return None
            query_obj = query_obj.in_("manufacturer_id", manufacturer_ids)

        if category:
            category_ids = self._find_lookup_ids("categories", "category_name", category)
            if not category_ids:
                return None
            query_obj = query_obj.in_("category_id", category_ids)

        if applicant:
            applicant_ids = self._find_lookup_ids("applicants", "applicant_name", applicant)
            if not applicant_ids:
                return None
            query_obj = query_obj.in_("applicant_id", applicant_ids)

        if status:
            query_obj = query_obj.eq("status", status)

        if expiry == "expiring_12_months":
            today = self.db.client.table(self.table_name).select("id").execute()
            _ = today
            return query_obj

        if expiry == "expired":
            return query_obj

        if expiry == "active":
            return query_obj

        return query_obj

    def list_page(
        self,
        *,
        query: str = "",
        manufacturer: str = "",
        category: str = "",
        applicant: str = "",
        status: str = "",
        expiry: str = "",
        sort_by: str = "newest",
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[dict], int, list[dict], list[dict]]:
        if self.db.client is None:
            raise RuntimeError("Supabase unavailable")

        page = max(int(page or 1), 1)
        page_size = max(min(int(page_size or 50), 200), 1)
        offset = (page - 1) * page_size
        selected_columns = "id, registration_number, product_name, approval_date, expiry_date, status, applicant_id, manufacturer_id, category_id, dosage_form_id, route_id"

        query_obj = self.db.client.table(self.table_name).select(selected_columns)
        query_obj = self._apply_product_filters(
            query_obj,
            query=query,
            manufacturer=manufacturer,
            category=category,
            applicant=applicant,
            status=status,
            expiry=expiry,
        )
        if query_obj is None:
            return [], 0, [], []

        sort_key = (sort_by or "newest").strip().lower()
        if sort_key == "product_name":
            query_obj = query_obj.order("product_name", desc=False)
        elif sort_key == "manufacturer":
            query_obj = query_obj.order("manufacturer_id", desc=False)
        elif sort_key == "expiry_date":
            query_obj = query_obj.order("expiry_date", desc=False)
        elif sort_key == "approval_date":
            query_obj = query_obj.order("approval_date", desc=True)
        elif sort_key == "oldest":
            query_obj = query_obj.order("approval_date", desc=False)
        else:
            query_obj = query_obj.order("approval_date", desc=True)

        count_query = self.db.client.table(self.table_name).select("id", count="exact", head=True)
        count_query = self._apply_product_filters(
            count_query,
            query=query,
            manufacturer=manufacturer,
            category=category,
            applicant=applicant,
            status=status,
            expiry=expiry,
        )
        if count_query is None:
            return [], 0, [], []
        total_response = count_query.execute()
        total = int(total_response.count or 0)

        response = query_obj.limit(page_size).offset(offset).execute()
        rows = [self._normalize_product_row(row) for row in (response.data or []) if isinstance(row, dict)]

        categories = []
        statuses = []
        seen_categories: set[str] = set()
        seen_statuses: set[str] = set()
        for row in rows:
            category_name = row.get("product_category") or "Unknown"
            status_name = row.get("status") or "Unknown"
            if category_name not in seen_categories:
                seen_categories.add(category_name)
                categories.append({"category_name": category_name})
            if status_name not in seen_statuses:
                seen_statuses.add(status_name)
                statuses.append({"status": status_name})

        return rows, total, categories, statuses


__all__ = ["ProductRepository"]
