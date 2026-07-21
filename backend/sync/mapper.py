from __future__ import annotations

from typing import Any


class GreenBookMapper:
    @staticmethod
    def to_internal_record(raw: dict[str, Any]) -> dict[str, Any]:
        return {
            "source_product_id": raw.get("product_id"),
            "registration_number": raw.get("registration_number"),
            "product_name": raw.get("product_name"),
            "generic_name": raw.get("product_name"),
            "active_ingredient": raw.get("active_ingredient"),
            "strength": raw.get("strength"),
            "dosage_form_name": raw.get("dosage_form"),
            "route_name": raw.get("route"),
            "category_name": raw.get("category"),
            "description": raw.get("description"),
            "pack_size": raw.get("pack_size"),
            "composition": raw.get("composition"),
            "approval_date": raw.get("approval_date"),
            "expiry_date": raw.get("expiry_date"),
            "status": raw.get("status"),
            "manufacturer_name": raw.get("manufacturer"),
            "applicant_name": raw.get("applicant"),
            "source_last_updated": raw.get("source_last_updated"),
        }
