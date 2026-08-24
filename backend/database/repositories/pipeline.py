from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from backend.database.repositories.base import BaseRepository


class PipelineRepository(BaseRepository[dict]):
    table_name = "revenue_pipeline"
    model_class = None
    search_fields = ["company", "category", "recommended_services", "status"]

    def _normalize_row(self, row: dict | None) -> dict:
        if row is None:
            return {}
        if not isinstance(row, dict):
            row = dict(row)

        estimated_value = row.get("estimated_value") or 0
        try:
            estimated_value = float(estimated_value)
        except (TypeError, ValueError):
            estimated_value = 0.0

        status = str(row.get("status") or "").strip() or "unknown"
        priority = self._derive_priority(estimated_value, status)
        probability = self._derive_probability(estimated_value, status)
        created_at = row.get("created_at") or row.get("updated_at")
        updated_at = row.get("updated_at") or row.get("created_at")
        expiry_date = self._resolve_expiry_date(row)

        return {
            "opportunity_id": row.get("id"),
            "company_name": row.get("company") or "Unknown company",
            "manufacturer_name": row.get("manufacturer_name") or row.get("company") or "Unknown manufacturer",
            "product_name": row.get("products") or None,
            "category": row.get("category") or None,
            "service_type": row.get("recommended_services") or None,
            "estimated_value": estimated_value,
            "probability": probability,
            "priority": priority,
            "expiry_date": expiry_date,
            "opportunity_status": status,
            "recommendation": row.get("recommended_services") or None,
            "created_at": created_at,
            "updated_at": updated_at,
            "company": row.get("company"),
            "products": row.get("products"),
            "recommended_services": row.get("recommended_services"),
            "status": status,
        }

    def _resolve_expiry_date(self, row: dict) -> str | None:
        for key in ("expiry_date", "expiration_date", "expiry", "renewal_date", "renewal_expiry", "registration_expiry", "expiration", "valid_until", "end_date", "expires_on"):
            value = row.get(key)
            if value not in (None, "", [], {}):
                return str(value)
        return None

    def _derive_priority(self, estimated_value: float, status: str) -> str:
        status_value = (status or "").strip().lower()
        if status_value in {"won", "closed", "lost"}:
            return "low"
        if estimated_value >= 5_000_000 or status_value in {"urgent", "high"}:
            return "high"
        if estimated_value >= 1_000_000 or status_value in {"active", "pending"}:
            return "medium"
        return "low"

    def _derive_probability(self, estimated_value: float, status: str) -> int:
        status_value = (status or "").strip().lower()
        if status_value == "won":
            return 100
        if status_value in {"closed", "lost"}:
            return 0
        if estimated_value >= 5_000_000:
            return 80
        if estimated_value >= 1_000_000:
            return 60
        return 40

    def _matches_search(self, row: dict, query: str) -> bool:
        query_text = (query or "").strip().lower()
        if not query_text:
            return True
        haystack = " ".join([
            str(row.get("company_name") or ""),
            str(row.get("manufacturer_name") or ""),
            str(row.get("product_name") or ""),
            str(row.get("category") or ""),
            str(row.get("service_type") or ""),
            str(row.get("opportunity_status") or ""),
            str(row.get("recommendation") or ""),
        ]).lower()
        return query_text in haystack

    def _is_closing_soon(self, row: dict) -> bool:
        updated_at = row.get("updated_at") or row.get("created_at")
        if not updated_at:
            return False
        try:
            if isinstance(updated_at, str):
                updated_at = updated_at.replace("Z", "+00:00")
                parsed = datetime.fromisoformat(updated_at)
            else:
                parsed = updated_at
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return (datetime.now(timezone.utc) - parsed.astimezone(timezone.utc)).days <= 30
        except Exception:
            return False

    def list_page(
        self,
        *,
        query: str = "",
        status: str = "",
        priority: str = "",
        probability: str = "",
        estimated_value: str = "",
        category: str = "",
        service: str = "",
        manufacturer: str = "",
        sort_by: str = "newest",
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[dict], int, list[dict], list[dict], list[dict], list[dict], dict[str, Any]]:
        print("Opportunity query: SELECT * FROM revenue_pipeline ORDER BY estimated_value DESC")
        rows = [self._normalize_row(row) for row in self.list(order="estimated_value.desc") if isinstance(row, dict)]

        if query:
            rows = [row for row in rows if self._matches_search(row, query)]
        if status:
            rows = [row for row in rows if (row.get("opportunity_status") or "").lower() == status.lower()]
        if priority:
            rows = [row for row in rows if (row.get("priority") or "").lower() == priority.lower()]
        if probability:
            lower_prob = str(probability).lower()
            if lower_prob in {"low", "medium", "high"}:
                thresholds = {"low": (0, 49), "medium": (50, 79), "high": (80, 100)}
                minimum, maximum = thresholds[lower_prob]
                rows = [row for row in rows if minimum <= int(row.get("probability") or 0) <= maximum]
            else:
                try:
                    numeric_probability = int(float(probability))
                    rows = [row for row in rows if int(row.get("probability") or 0) == numeric_probability]
                except ValueError:
                    rows = [row for row in rows]
        if estimated_value:
            rows = [
                row
                for row in rows
                if (
                    (estimated_value == "lt_5m" and float(row.get("estimated_value") or 0) < 5_000_000)
                    or (estimated_value == "5m_10m" and 5_000_000 <= float(row.get("estimated_value") or 0) <= 10_000_000)
                    or (estimated_value == "gt_10m" and float(row.get("estimated_value") or 0) > 10_000_000)
                )
            ]
        if category:
            rows = [row for row in rows if (row.get("category") or "").lower() == category.lower()]
        if service:
            rows = [row for row in rows if (row.get("service_type") or "").lower().find(service.lower()) >= 0]
        if manufacturer:
            rows = [row for row in rows if (row.get("manufacturer_name") or "").lower().find(manufacturer.lower()) >= 0]

        sort_key = (sort_by or "estimated_value").strip().lower()
        if sort_key == "estimated_value":
            rows.sort(key=lambda row: (float(row.get("estimated_value") or 0), str(row.get("company_name") or "").lower()), reverse=True)
        elif sort_key == "probability":
            rows.sort(key=lambda row: (row.get("probability") or 0, float(row.get("estimated_value") or 0)), reverse=True)
        elif sort_key == "expiry_date":
            rows.sort(key=lambda row: (str(row.get("expiry_date") or ""), float(row.get("estimated_value") or 0)), reverse=True)
        elif sort_key == "company":
            rows.sort(key=lambda row: (str(row.get("company_name") or "").lower(), float(row.get("estimated_value") or 0)), reverse=True)
        elif sort_key == "oldest":
            rows.sort(key=lambda row: (str(row.get("created_at") or ""), float(row.get("estimated_value") or 0)))
        else:
            rows.sort(key=lambda row: (float(row.get("estimated_value") or 0), str(row.get("created_at") or "")), reverse=True)

        total = len(rows)
        page = max(int(page or 1), 1)
        page_size = max(min(int(page_size or 50), 200), 1)
        start = (page - 1) * page_size
        page_rows = rows[start:start + page_size]

        categories = sorted({str(row.get("category") or "").strip() for row in rows if row.get("category")})
        statuses = sorted({str(row.get("opportunity_status") or "").strip() for row in rows if row.get("opportunity_status")})
        services = sorted({str(row.get("service_type") or "").strip() for row in rows if row.get("service_type")})
        manufacturers = sorted({str(row.get("manufacturer_name") or "").strip() for row in rows if row.get("manufacturer_name")})

        summary = {
            "total_opportunities": total,
            "high_priority": sum(1 for row in rows if (row.get("priority") or "").lower() == "high"),
            "closing_soon": sum(1 for row in rows if self._is_closing_soon(row)),
            "total_pipeline_value": round(sum(float(row.get("estimated_value") or 0) for row in rows), 2),
            "average_opportunity_value": round((sum(float(row.get("estimated_value") or 0) for row in rows) / total) if total else 0, 2),
        }

        return page_rows, total, categories, statuses, services, manufacturers, summary


__all__ = ["PipelineRepository"]
