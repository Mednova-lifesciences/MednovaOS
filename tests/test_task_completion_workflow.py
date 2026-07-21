import importlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_task_reopen_clears_completion_timestamp(tmp_path, monkeypatch):
    db_path = tmp_path / "crm-task-workflow.sqlite"
    monkeypatch.setenv("MEDNOVA_DB_PATH", str(db_path))

    import app as app_module
    app_module = importlib.reload(app_module)

    client = app_module.app.test_client()

    create_response = client.post(
        "/api/crm/companies/from-opportunity",
        json={
            "company": "Task Workflow Pharma",
            "country": "Nigeria",
            "opportunity_score": 77,
            "portfolio_summary": "Opportunity with a completion workflow",
            "source": "Green Book",
        },
    )
    assert create_response.status_code == 200
    company_id = create_response.get_json()["company_id"]

    task_response = client.post(
        f"/api/crm/companies/{company_id}/tasks",
        json={
            "title": "Follow up with the regulatory team",
            "description": "Discuss next submission milestone",
            "assigned_to": "Jane",
            "due_date": "2026-07-25",
            "priority": "high",
        },
    )
    assert task_response.status_code == 200
    task_id = task_response.get_json()["task"]["id"]

    complete_response = client.post(f"/api/crm/companies/{company_id}/tasks/{task_id}/complete")
    assert complete_response.status_code == 200
    completed_payload = complete_response.get_json()
    assert completed_payload["task"]["status"] == "completed"
    assert completed_payload["task"]["completed_at"]

    reopen_response = client.patch(
        f"/api/crm/companies/{company_id}/tasks/{task_id}",
        json={"status": "pending"},
    )
    assert reopen_response.status_code == 200
    reopened_payload = reopen_response.get_json()
    assert reopened_payload["task"]["status"] == "pending"
    assert reopened_payload["task"]["completed_at"] is None
