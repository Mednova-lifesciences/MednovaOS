import importlib
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_growhub_crm_data_persists_pipeline_deals_for_companies_without_existing_deals(tmp_path, monkeypatch):
    db_path = tmp_path / "pipeline.sqlite"
    monkeypatch.setenv("MEDNOVA_DB_PATH", str(db_path))

    import app as app_module
    app_module = importlib.reload(app_module)

    client = app_module.app.test_client()
    create_response = client.post(
        "/api/crm/companies/from-opportunity",
        json={"company_name": "Pipeline Test", "source": "Green Book"},
    )
    assert create_response.status_code == 200
    company_id = create_response.get_json()["company_id"]

    response = client.get("/api/growhub/crm/data")
    assert response.status_code == 200
    payload = response.get_json()

    deals = [deal for deal in payload["deals"] if deal["companyId"] == company_id]
    assert deals
    assert all(int(deal["id"]) > 0 for deal in deals)

    with sqlite3.connect(db_path) as conn:
        rows = conn.execute("SELECT id FROM crm_deals WHERE crm_company_id = ?", (company_id,)).fetchall()

    assert rows


def test_growhub_crm_data_does_not_duplicate_existing_deals(tmp_path, monkeypatch):
    db_path = tmp_path / "pipeline-duplicates.sqlite"
    monkeypatch.setenv("MEDNOVA_DB_PATH", str(db_path))

    import app as app_module
    app_module = importlib.reload(app_module)

    client = app_module.app.test_client()
    create_response = client.post(
        "/api/crm/companies/from-opportunity",
        json={"company_name": "Duplicate Deal Co", "source": "Green Book"},
    )
    assert create_response.status_code == 200
    company_id = create_response.get_json()["company_id"]

    create_deal_response = client.post(
        f"/api/crm/companies/{company_id}/deals",
        json={"title": "Duplicate check", "stage": "lead", "value": 250},
    )
    assert create_deal_response.status_code == 200

    response = client.get("/api/growhub/crm/data")
    assert response.status_code == 200
    payload = response.get_json()

    company_deals = [deal for deal in payload["deals"] if deal["companyId"] == company_id]
    deal_ids = [deal["id"] for deal in company_deals]
    assert len(deal_ids) == len(set(deal_ids))


def test_growhub_crm_data_sorts_deals_by_recent_activity(tmp_path, monkeypatch):
    db_path = tmp_path / "pipeline-ordering.sqlite"
    monkeypatch.setenv("MEDNOVA_DB_PATH", str(db_path))

    import app as app_module
    app_module = importlib.reload(app_module)

    client = app_module.app.test_client()
    create_response = client.post(
        "/api/crm/companies/from-opportunity",
        json={"company_name": "Ordering Deal Co", "source": "Green Book"},
    )
    assert create_response.status_code == 200
    company_id = create_response.get_json()["company_id"]

    create_deal_response = client.post(
        f"/api/crm/companies/{company_id}/deals",
        json={"title": "Older deal", "stage": "lead", "value": 100},
    )
    assert create_deal_response.status_code == 200
    older_deal_id = create_deal_response.get_json()["deal"]["id"]

    create_second_response = client.post(
        f"/api/crm/companies/{company_id}/deals",
        json={"title": "Newer deal", "stage": "lead", "value": 200},
    )
    assert create_second_response.status_code == 200
    newer_deal_id = create_second_response.get_json()["deal"]["id"]

    move_response = client.patch(
        f"/api/crm/companies/{company_id}/deals/{newer_deal_id}",
        json={"stage": "qualified"},
    )
    assert move_response.status_code == 200

    response = client.get("/api/growhub/crm/data")
    assert response.status_code == 200
    payload = response.get_json()

    company_deals = [deal for deal in payload["deals"] if deal["companyId"] == company_id]
    first_ids = [deal["id"] for deal in company_deals[:2]]
    assert newer_deal_id in first_ids
    assert older_deal_id not in first_ids[:1]
