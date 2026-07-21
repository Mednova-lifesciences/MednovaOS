import importlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_add_to_crm_creates_company_and_prevents_duplicates(tmp_path, monkeypatch):
    db_path = tmp_path / "crm-test.sqlite"
    monkeypatch.setenv("MEDNOVA_DB_PATH", str(db_path))

    import app as app_module
    app_module = importlib.reload(app_module)

    client = app_module.app.test_client()

    payload = {
        "company": "Test Pharma",
        "country": "Nigeria",
        "opportunity_score": 84,
        "product_count": 4,
        "therapeutic_areas": ["Oncology", "Cardiology"],
        "status": "Priority",
        "portfolio_summary": "Portfolio with multiple product registrations",
        "source": "Green Book",
        "registration_numbers": ["NAFDAC-001"],
        "dosage_forms": ["Tablet"],
        "registration_dates": ["2024-01-01"],
        "notes": "Initial opportunity from Green Book",
    }

    first_response = client.post("/api/crm/companies/from-opportunity", json=payload)
    assert first_response.status_code == 200
    first_data = first_response.get_json()
    assert first_data["success"] is True
    assert first_data["company_id"] is not None

    second_response = client.post("/api/crm/companies/from-opportunity", json=payload)
    assert second_response.status_code == 200
    second_data = second_response.get_json()
    assert second_data["company_id"] == first_data["company_id"]

    list_response = client.get("/crm/companies", follow_redirects=False)
    # The application redirects CRM UI routes to the Lovable CRM frontend
    assert list_response.status_code == 302
    assert list_response.headers["Location"] == app_module._crm_frontend_target() + "/companies"
