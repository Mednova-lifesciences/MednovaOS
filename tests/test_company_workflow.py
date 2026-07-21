import importlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_company_workflow_supports_contacts_tasks_notes_and_timeline(tmp_path, monkeypatch):
    db_path = tmp_path / "crm-workflow.sqlite"
    monkeypatch.setenv("MEDNOVA_DB_PATH", str(db_path))

    import app as app_module
    app_module = importlib.reload(app_module)

    client = app_module.app.test_client()

    create_response = client.post(
        "/api/crm/companies/from-opportunity",
        json={
            "company": "Workflow Pharma",
            "country": "Nigeria",
            "opportunity_score": 88,
            "portfolio_summary": "Portfolio with a strong follow-up plan",
            "source": "Green Book",
            "notes": "Initial opportunity identified",
        },
    )
    assert create_response.status_code == 200
    company_id = create_response.get_json()["company_id"]

    contact_response = client.post(
        f"/api/crm/companies/{company_id}/contacts",
        json={
            "full_name": "Ada Lovelace",
            "role": "Head of BD",
            "department": "Business Development",
            "email": "ada@example.com",
        },
    )
    assert contact_response.status_code == 200
    contact_payload = contact_response.get_json()
    assert contact_payload["contact"]["full_name"] == "Ada Lovelace"

    task_response = client.post(
        f"/api/crm/companies/{company_id}/tasks",
        json={
            "title": "Schedule discovery call",
            "description": "Discuss upcoming regulatory plans",
            "assigned_to": "Jane",
            "due_date": "2026-01-15",
            "priority": "high",
        },
    )
    assert task_response.status_code == 200
    task_payload = task_response.get_json()
    assert task_payload["task"]["title"] == "Schedule discovery call"

    note_response = client.post(
        f"/api/crm/companies/{company_id}/notes",
        json={"body": "Initial account note for the workflow"},
    )
    assert note_response.status_code == 200
    note_payload = note_response.get_json()
    assert note_payload["note"]["body"] == "Initial account note for the workflow"

    detail_response = client.get(f"/api/crm/companies/{company_id}")
    assert detail_response.status_code == 200
    detail_payload = detail_response.get_json()

    contact_names = {item["full_name"] for item in detail_payload["contacts"]}
    assert "Ada Lovelace" in contact_names

    task_titles = {item["title"] for item in detail_payload["tasks"]}
    assert "Schedule discovery call" in task_titles

    note_bodies = {item["body"] for item in detail_payload["notes"]}
    assert "Initial account note for the workflow" in note_bodies

    timeline_titles = {item["title"] for item in detail_payload["activities"]}
    assert "Company created" in timeline_titles
    assert "Contact added" in timeline_titles
    assert "Task assigned" in timeline_titles
    assert "Note created" in timeline_titles

    complete_response = client.post(f"/api/crm/companies/{company_id}/tasks/{task_payload['task']['id']}/complete")
    assert complete_response.status_code == 200
    completed_payload = complete_response.get_json()
    assert completed_payload["task"]["status"] == "completed"

    follow_up_response = client.get(f"/api/crm/companies/{company_id}")
    follow_up_payload = follow_up_response.get_json()
    completed_task = next(item for item in follow_up_payload["tasks"] if item["id"] == task_payload["task"]["id"])
    assert completed_task["status"] == "completed"

    duplicate_response = client.post(
        "/api/crm/companies/from-opportunity",
        json={
            "company": "Workflow Pharma",
            "company_name": "Workflow Pharma",
            "source": "Green Book",
        },
    )
    assert duplicate_response.status_code == 200
    duplicate_payload = duplicate_response.get_json()
    assert duplicate_payload["status"] == "exists"
    assert duplicate_payload["created"] is False
    assert duplicate_payload["company_id"] == company_id
