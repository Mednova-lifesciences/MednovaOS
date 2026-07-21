import importlib


def test_company_creation_persists_contacts_and_tasks(tmp_path, monkeypatch):
    db_path = tmp_path / "crm-backbone.sqlite"
    monkeypatch.setenv("MEDNOVA_DB_PATH", str(db_path))

    import app as app_module
    app_module = importlib.reload(app_module)

    client = app_module.app.test_client()

    payload = {
        "company_name": "Acme Pharma",
        "country": "Nigeria",
        "opportunity_score": 84,
        "portfolio_summary": "Portfolio with multiple product registrations",
        "source": "Green Book",
        "registration_numbers": ["NAFDAC-001"],
        "dosage_forms": ["Tablet"],
        "registration_dates": ["2024-01-01"],
        "notes": "Initial opportunity from Green Book",
    }

    response = client.post("/api/crm/companies/from-opportunity", json=payload)
    assert response.status_code == 200
    data = response.get_json()
    company_id = data["company_id"]

    with app_module.connect() as conn:
        contacts = conn.execute("SELECT id FROM crm_contacts WHERE crm_company_id = ?", (company_id,)).fetchall()
        tasks = conn.execute("SELECT id FROM crm_tasks WHERE crm_company_id = ?", (company_id,)).fetchall()

    assert len(contacts) >= 1
    assert len(tasks) >= 1
