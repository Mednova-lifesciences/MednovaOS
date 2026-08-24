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


def test_crm_service_fuzzy_company_matching_reuses_existing_company(tmp_path, monkeypatch):
    db_path = tmp_path / "crm-fuzzy-match.sqlite"
    monkeypatch.setenv("MEDNOVA_DB_PATH", str(db_path))

    import app as app_module
    app_module = importlib.reload(app_module)

    from backend.services.crm_service import CRMService
    from backend.database.repositories import CompanyRepository

    company_repo = CompanyRepository()
    company_repo.create({
        "company_name": "Acme Pharma",
        "country": "Nigeria",
        "source": "Green Book",
        "created_at": "2025-01-01T00:00:00Z",
    })

    crm_service = CRMService()
    existing = crm_service._find_existing_company("Acme Pharmaceuticals")
    assert existing is not None
    assert (existing.company_name if hasattr(existing, "company_name") else existing.get("company_name")) == "Acme Pharma"

    another = crm_service._find_existing_company("Acme Health Care Ltd")
    assert another is None or (another.company_name if hasattr(another, "company_name") else another.get("company_name")) != "Acme Pharma"
