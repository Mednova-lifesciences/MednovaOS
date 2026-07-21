import importlib
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_growhub_crm_api_exposes_crm_companies_created_from_opportunity(tmp_path, monkeypatch):
    db_path = tmp_path / "growhub-crm.sqlite"
    monkeypatch.setenv("MEDNOVA_DB_PATH", str(db_path))

    import app as app_module
    app_module = importlib.reload(app_module)

    client = app_module.app.test_client()
    create_response = client.post(
        "/api/crm/companies/from-opportunity",
        json={
            "company_name": "CRM Test Pharma",
            "company": "CRM Test Pharma",
            "country": "Nigeria",
            "opportunity_score": 82,
            "portfolio_summary": "Added through CRM workflow",
            "source": "Green Book",
        },
    )

    assert create_response.status_code == 200
    payload = create_response.get_json()
    assert payload["success"] is True
    assert payload["company_id"] == 1

    companies_response = client.get("/api/growhub/crm/companies")
    assert companies_response.status_code == 200
    companies_payload = companies_response.get_json()
    assert len(companies_payload) == 1
    assert companies_payload[0]["name"] == "CRM Test Pharma"
    assert companies_payload[0]["source"] == "Green Book"

    envelope_response = client.get("/api/growhub/crm/data")
    assert envelope_response.status_code == 200
    envelope_payload = envelope_response.get_json()
    assert envelope_payload["companies"][0]["name"] == "CRM Test Pharma"


def test_crm_api_supports_cors_for_vite_frontend(tmp_path, monkeypatch):
    db_path = tmp_path / "cors-crm.sqlite"
    monkeypatch.setenv("MEDNOVA_DB_PATH", str(db_path))

    import app as app_module
    app_module = importlib.reload(app_module)

    client = app_module.app.test_client()

    response = client.get(
        "/api/growhub/crm/data",
        headers={"Origin": "http://127.0.0.1:5175"},
    )
    assert response.status_code == 200
    assert response.headers["Access-Control-Allow-Origin"] == "http://127.0.0.1:5175"

    preflight = client.options(
        "/api/growhub/crm/data",
        headers={
            "Origin": "http://127.0.0.1:5175",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "Content-Type",
        },
    )
    assert preflight.status_code == 200
    assert preflight.headers["Access-Control-Allow-Origin"] == "http://127.0.0.1:5175"
    assert "GET" in preflight.headers["Access-Control-Allow-Methods"]


def test_company_pipeline_stage_updates_persist_and_log_activity(tmp_path, monkeypatch):
    db_path = tmp_path / "pipeline-stage.sqlite"
    monkeypatch.setenv("MEDNOVA_DB_PATH", str(db_path))

    import app as app_module
    app_module = importlib.reload(app_module)

    client = app_module.app.test_client()
    create_response = client.post(
        "/api/crm/companies/from-opportunity",
        json={
            "company_name": "Pipeline Pharma",
            "source": "Green Book",
        },
    )

    assert create_response.status_code == 200
    company_id = create_response.get_json()["company_id"]

    update_response = client.patch(
        f"/api/crm/companies/{company_id}/pipeline-stage",
        json={"pipelineStage": "proposal"},
    )
    assert update_response.status_code == 200

    envelope_response = client.get("/api/growhub/crm/data")
    assert envelope_response.status_code == 200
    envelope_payload = envelope_response.get_json()
    updated_company = next(item for item in envelope_payload["companies"] if item["id"] == company_id)
    assert updated_company["pipelineStage"] == "Proposal"

    detail_response = client.get(f"/api/crm/companies/{company_id}")
    assert detail_response.status_code == 200
    detail_payload = detail_response.get_json()
    activity_titles = {item["title"] for item in detail_payload["activities"]}
    assert "Pipeline stage updated" in activity_titles


def test_growhub_pipeline_uses_revenue_pipeline_estimate_for_deal_value(tmp_path, monkeypatch):
    db_path = tmp_path / "pipeline-value.sqlite"
    monkeypatch.setenv("MEDNOVA_DB_PATH", str(db_path))

    import app as app_module
    app_module = importlib.reload(app_module)

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS revenue_pipeline (company TEXT, category TEXT, products INTEGER, estimated_value REAL, recommended_services TEXT, status TEXT)"
        )
        conn.execute(
            "INSERT INTO revenue_pipeline (company, category, products, estimated_value, recommended_services, status) VALUES (?, ?, ?, ?, ?, ?)",
            ("Pipeline Pharma", "Oncology", 3, 4_500_000, "Regulatory Intelligence", "Priority"),
        )
        conn.commit()

    client = app_module.app.test_client()
    create_response = client.post(
        "/api/crm/companies/from-opportunity",
        json={
            "company_name": "Pipeline Pharma",
            "source": "Green Book",
        },
    )

    assert create_response.status_code == 200
    company_id = create_response.get_json()["company_id"]

    envelope_response = client.get("/api/growhub/crm/data")
    assert envelope_response.status_code == 200
    envelope_payload = envelope_response.get_json()
    deal = next(item for item in envelope_payload["deals"] if item["companyId"] == company_id)
    assert deal["value"] == 4_500_000
    assert deal["currency"] == "NGN"


def test_crm_routes_redirect_to_configured_frontend(monkeypatch):
    monkeypatch.setenv("MEDNOVA_CRM_FRONTEND_URL", "http://127.0.0.1:5173")

    import app as app_module
    app_module = importlib.reload(app_module)

    client = app_module.app.test_client()

    for path in ["/crm", "/growhub"]:
        response = client.get(path, follow_redirects=False)
        assert response.status_code == 302
        assert response.headers["Location"] == "http://127.0.0.1:5173"


def test_crm_routes_use_default_frontend_when_unconfigured(monkeypatch):
    monkeypatch.delenv("MEDNOVA_CRM_FRONTEND_URL", raising=False)

    import app as app_module
    app_module = importlib.reload(app_module)

    client = app_module.app.test_client()

    response = client.get("/crm", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["Location"] == "http://127.0.0.1:5175"
