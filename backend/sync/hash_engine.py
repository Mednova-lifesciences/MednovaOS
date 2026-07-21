from __future__ import annotations

import hashlib
import json
from typing import Any


def build_product_hash(record: dict[str, Any]) -> str:
    payload = {
        "product_name": record.get("product_name"),
        "registration_number": record.get("registration_number"),
        "manufacturer": record.get("manufacturer_name"),
        "applicant": record.get("applicant_name"),
        "ingredient": record.get("active_ingredient"),
        "category": record.get("category_name"),
        "dosage_form": record.get("dosage_form_name"),
        "route": record.get("route_name"),
        "approval_date": record.get("approval_date"),
        "expiry_date": record.get("expiry_date"),
        "composition": record.get("composition"),
        "status": record.get("status"),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()
