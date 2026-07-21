import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.sync.greenbook_client import GreenBookClient


def test_extract_product_uses_datatables_payload_fields():
    payload = {
        "product_id": 123,
        "product_name": "Test Product",
        "NAFDAC": "03-1234",
        "product_category": {"name": "Medical devices"},
        "ingredient": {"ingredient_name": "Paracetamol"},
        "form": {"name": "Tablet"},
        "route": {"name": "Oral"},
        "applicant": {"name": "Acme Ltd"},
        "approval_date": "2024-01-01",
        "expiry_date": "2030-01-01",
        "status": "Active",
        "product_description": "A test product",
        "pack_size": "10 tabs",
        "composition": "Active ingredient",
        "updated_at": "2024-01-02",
    }

    record = GreenBookClient().extract_product(payload)

    assert record["registration_number"] == "03-1234"
    assert record["product_name"] == "Test Product"
    assert record["category"] == "Medical devices"
    assert record["active_ingredient"] == "Paracetamol"
    assert record["dosage_form"] == "Tablet"
    assert record["route"] == "Oral"
    assert record["applicant"] == "Acme Ltd"
    assert record["description"] == "A test product"
    assert record["source_last_updated"] == "2024-01-02"


def test_extract_product_falls_back_to_applicant_for_manufacturer():
    payload = {
        "product_id": 456,
        "product_name": "Fallback Product",
        "NAFDAC": "03-9999",
        "applicant": {"name": "Acme Ltd"},
        "approval_date": "2024-01-01",
        "expiry_date": "2030-01-01",
        "status": "Active",
    }

    record = GreenBookClient().extract_product(payload)

    assert record["manufacturer"] == "Acme Ltd"
