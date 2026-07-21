import importlib


def test_company_and_operations_reports_generate_and_persist(tmp_path, monkeypatch):
    db_path = tmp_path / "reports.sqlite"
    monkeypatch.setenv("MEDNOVA_DB_PATH", str(db_path))

    import app as app_module
    app_module = importlib.reload(app_module)

    client = app_module.app.test_client()

    create_company = client.post(
        "/api/crm/companies/from-opportunity",
        json={
            "company": "Report Test Pharma",
            "country": "Nigeria",
            "opportunity_score": 88,
            "portfolio_summary": "High-value opportunity for global expansion",
            "source": "Green Book",
        },
    )
    assert create_company.status_code == 200
    company_id = create_company.get_json()["company_id"]

    task_response = client.post(
        f"/api/crm/companies/{company_id}/tasks",
        json={
            "title": "Prepare regulatory dossier",
            "description": "Gather regulatory materials",
            "assigned_to": "Jane",
            "due_date": "2026-07-25",
            "priority": "high",
        },
    )
    assert task_response.status_code == 200

    company_report = client.post(f"/api/crm/companies/{company_id}/reports/generate")
    assert company_report.status_code == 200
    company_payload = company_report.get_json()
    assert company_payload["success"] is True
    assert company_payload["report"]["report_type"] == "company"
    assert company_payload["report"]["company_id"] == company_id

    history_response = client.get(f"/api/crm/companies/{company_id}/reports")
    assert history_response.status_code == 200
    assert len(history_response.get_json()["reports"]) >= 1

    ops_report = client.post("/api/reports/operations/generate")
    assert ops_report.status_code == 200
    ops_payload = ops_report.get_json()
    assert ops_payload["success"] is True
    assert ops_payload["report"]["report_type"] == "operations"

    export_response = client.post(
        f"/api/reports/{ops_payload['report']['id']}/export",
        json={"format": "markdown"},
    )
    assert export_response.status_code == 200
    assert export_response.get_json()["success"] is True
    export_content = export_response.get_json()["content"]
    assert "Executive Summary" in export_content
    assert "Recommended Services" in export_content


def test_company_intelligence_refresh_builds_structured_profile(tmp_path, monkeypatch):
    db_path = tmp_path / "intel.sqlite"
    monkeypatch.setenv("MEDNOVA_DB_PATH", str(db_path))

    import app as app_module
    app_module = importlib.reload(app_module)

    client = app_module.app.test_client()

    create_company = client.post(
        "/api/crm/companies/from-opportunity",
        json={
            "company": "NovaBio Labs",
            "country": "Kenya",
            "opportunity_score": 79,
            "portfolio_summary": "Clinical services and local manufacturing capability",
            "source": "Green Book",
        },
    )
    assert create_company.status_code == 200
    company_id = create_company.get_json()["company_id"]

    refresh_response = client.post(f"/api/crm/companies/{company_id}/intelligence/refresh")
    assert refresh_response.status_code == 200
    intelligence_payload = refresh_response.get_json()
    assert intelligence_payload["success"] is True
    assert intelligence_payload["intelligence"]["company_profile"]["name"] == "NovaBio Labs"
    assert "services" in intelligence_payload["intelligence"]
