import importlib
import sqlite3
import sys
from pathlib import Path

import requests

from database.apply_migrations import apply_migrations

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _create_company(client, company_name="Acme Bio"):
    create_response = client.post(
        "/api/crm/companies/from-opportunity",
        json={
            "company_name": company_name,
            "source": "Green Book",
        },
    )
    assert create_response.status_code == 200
    return create_response.get_json()["company_id"]


def _create_contact(client, company_id):
    response = client.post(
        f"/api/crm/companies/{company_id}/contacts",
        json={
            "full_name": "Jane Doe",
            "role": "Head of BD",
            "email": "jane@example.com",
            "phone": "+1-555-0100",
            "source": "CRM",
        },
    )
    assert response.status_code == 200
    return response.get_json()["contact"]


def test_crm_schema_migration_adds_outreach_columns_and_supports_insert(tmp_path):
    db_path = tmp_path / "legacy-schema.sqlite"
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE crm_outreach_emails (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            crm_company_id INTEGER NOT NULL,
            crm_contact_id INTEGER,
            subject TEXT NOT NULL,
            body TEXT NOT NULL,
            recipient TEXT,
            sender_name TEXT,
            sender_email TEXT,
            status TEXT NOT NULL DEFAULT 'draft',
            direction TEXT NOT NULL DEFAULT 'outbound',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            sent_at TEXT
        )
        """
    )
    conn.commit()
    conn.close()

    apply_migrations(db_path)

    conn = sqlite3.connect(db_path)
    columns = {row[1] for row in conn.execute("PRAGMA table_info(crm_outreach_emails)").fetchall()}
    assert "template_name" in columns
    assert "recipient_name" in columns
    assert "from_email" in columns
    assert "company_name" in columns
    assert "contact_name" in columns
    assert "message_id" in columns
    assert "error_message" in columns
    assert "client_request_id" in columns

    conn.execute(
        """
        INSERT INTO crm_outreach_emails (
            crm_company_id, crm_contact_id, subject, body, recipient, sender_name, sender_email, status, template_name, recipient_name, from_email, company_name, contact_name, message_id, error_message, client_request_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (1, 2, "Legacy subject", "Legacy body", "jane@example.com", "Ada", "ada@mednovaos.com", "sent", "follow_up", "Jane Doe", "info@mednovalife.com", "Legacy Co", "Jane Doe", "msg_legacy", "", "req_legacy"),
    )
    conn.commit()
    row = conn.execute(
        "SELECT template_name, recipient_name, from_email, company_name, contact_name, message_id, client_request_id FROM crm_outreach_emails WHERE id = 1"
    ).fetchone()
    assert row == ("follow_up", "Jane Doe", "info@mednovalife.com", "Legacy Co", "Jane Doe", "msg_legacy", "req_legacy")
    conn.close()


def test_outreach_environment_loader_reads_dotenv_values(tmp_path, monkeypatch):
    dotenv_path = tmp_path / ".env"
    dotenv_path.write_text(
        "RESEND_API_KEY=test-key\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    import app as app_module
    app_module = importlib.reload(app_module)

    payload = app_module._load_environment(dotenv_path)
    assert payload["resendApiKeyConfigured"] is True
    assert payload["senderEmail"] == "info@mednovalife.com"
    assert payload["senderNameConfigured"] is True


def test_outreach_templates_render_with_company_data(tmp_path, monkeypatch):
    db_path = tmp_path / "outreach.sqlite"
    monkeypatch.setenv("MEDNOVA_DB_PATH", str(db_path))

    import app as app_module
    app_module = importlib.reload(app_module)

    client = app_module.app.test_client()
    company_id = _create_company(client, "Nova Therapeutics")
    _create_contact(client, company_id)

    templates_response = client.get("/api/crm/outreach/templates")
    assert templates_response.status_code == 200
    templates = templates_response.get_json()["templates"]
    assert len(templates) >= 5

    build_response = client.post(
        f"/api/crm/companies/{company_id}/outreach/build",
        json={
            "contact_ids": [1],
            "template_key": "introduction",
            "sender_name": "Ada Lovelace",
            "sender_email": "ada@mednovaos.com",
        },
    )
    assert build_response.status_code == 200
    payload = build_response.get_json()
    assert payload["success"] is True
    assert "Nova Therapeutics" in payload["subject"]
    assert "Hello Jane Doe" in payload["body"]
    assert "ada@mednovaos.com" in payload["body"]


def test_company_outreach_page_renders_contact_and_template_options(tmp_path, monkeypatch):
    db_path = tmp_path / "outreach-ui.sqlite"
    monkeypatch.setenv("MEDNOVA_DB_PATH", str(db_path))

    import app as app_module
    app_module = importlib.reload(app_module)

    client = app_module.app.test_client()
    company_id = _create_company(client, "Northwind Bio")
    _create_contact(client, company_id)

    response = client.get(f"/crm/companies/{company_id}/outreach")
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Outreach Campaign" in body
    assert "Jane Doe" in body
    assert "Introduction" in body
    assert 'name="recipient"' in body
    assert 'name="subject"' in body
    assert 'name="body"' in body
    assert "Save draft" in body
    assert "Send email" in body


def test_outreach_page_renders_send_feedback_ui(tmp_path, monkeypatch):
    db_path = tmp_path / "outreach-ui-state.sqlite"
    monkeypatch.setenv("MEDNOVA_DB_PATH", str(db_path))

    import app as app_module
    app_module = importlib.reload(app_module)

    client = app_module.app.test_client()
    company_id = _create_company(client, "Feedback Bio")
    _create_contact(client, company_id)

    response = client.get(f"/crm/companies/{company_id}/outreach")
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert 'id="send-email-button"' in body
    assert 'id="outreach-feedback"' in body
    assert 'Activity Timeline' in body
    assert 'Recent outreach' in body


def test_outreach_draft_and_send_persist_and_log_activity(tmp_path, monkeypatch):
    db_path = tmp_path / "outreach-send.sqlite"
    monkeypatch.setenv("MEDNOVA_DB_PATH", str(db_path))

    import app as app_module
    app_module = importlib.reload(app_module)

    monkeypatch.setattr(app_module.requests, "post", lambda *args, **kwargs: type("Response", (), {"ok": True, "status_code": 200, "json": lambda self: {"id": "msg_123"}, "raise_for_status": lambda self: None})())

    client = app_module.app.test_client()
    company_id = _create_company(client, "Northwind Bio")
    _create_contact(client, company_id)

    draft_response = client.post(
        f"/api/crm/companies/{company_id}/outreach/drafts",
        json={
            "subject": "Draft outreach",
            "body": "This is a saved draft.",
            "template_key": "follow_up",
            "recipient": "jane@mednovalife.com",
            "sender_name": "Ada",
            "sender_email": "ada@mednovaos.com",
        },
    )
    assert draft_response.status_code == 200
    draft_payload = draft_response.get_json()
    assert draft_payload["success"] is True

    send_response = client.post(
        f"/api/crm/companies/{company_id}/outreach/send",
        json={
            "subject": "Sent outreach",
            "body": "This was sent.",
            "template_key": "regulatory_support",
            "recipient": "jane@mednovalife.com",
            "sender_name": "Ada",
            "sender_email": "ada@mednovaos.com",
        },
    )
    assert send_response.status_code == 200
    sent_payload = send_response.get_json()
    assert sent_payload["success"] is True
    assert sent_payload["status"] == "sent"

    history_response = client.get(f"/api/crm/companies/{company_id}/outreach/history")
    assert history_response.status_code == 200
    history = history_response.get_json()["items"]
    assert len(history) >= 2

    company_response = client.get(f"/api/crm/companies/{company_id}")
    activities = company_response.get_json()["activities"]
    titles = {item["title"] for item in activities}
    assert "Email drafted" in titles
    assert "Email sent" in titles


def test_resend_provider_rejections_are_reported_as_actionable_errors(monkeypatch):
    import app as app_module

    class FakeResponse:
        status_code = 403

        def json(self):
            return {"message": "invalid API key"}

    def fake_post(*args, **kwargs):
        raise requests.HTTPError("403 Client Error: Forbidden") from None

    monkeypatch.setattr(app_module.requests, "post", fake_post)
    monkeypatch.setenv("RESEND_API_KEY", "test-key")
    monkeypatch.setenv("FROM_EMAIL", "info@mednovalife.com")

    success, message_id, error_message = app_module._send_via_resend("Subject", "Body", "user@example.com", "info@mednovalife.com", "Ada", "ada@mednovaos.com")

    assert success is False
    assert message_id is None
    assert "Resend rejected the request" in error_message
    assert "invalid API key" in error_message or "RESEND_API_KEY" in error_message


def test_outreach_form_payloads_support_draft_and_send(tmp_path, monkeypatch):
    db_path = tmp_path / "form-outreach.sqlite"
    monkeypatch.setenv("MEDNOVA_DB_PATH", str(db_path))

    import app as app_module
    app_module = importlib.reload(app_module)

    monkeypatch.setattr(app_module.requests, "post", lambda *args, **kwargs: type("Response", (), {"ok": True, "status_code": 200, "json": lambda self: {"id": "msg_123"}, "raise_for_status": lambda self: None})())

    client = app_module.app.test_client()
    company_id = _create_company(client, "Form Bio")
    _create_contact(client, company_id)

    draft_response = client.post(
        f"/api/crm/companies/{company_id}/outreach/drafts",
        data={
            "subject": "Form draft",
            "body": "Saved from the compose form.",
            "template_key": "follow_up",
            "recipient": "jane@mednovalife.com",
            "sender_name": "Ada",
            "sender_email": "ada@mednovaos.com",
        },
        content_type="application/x-www-form-urlencoded",
    )
    assert draft_response.status_code == 200
    assert draft_response.get_json()["success"] is True

    send_response = client.post(
        f"/api/crm/companies/{company_id}/outreach/send",
        data={
            "subject": "Form send",
            "body": "Sent from the compose form.",
            "template_key": "regulatory_support",
            "recipient": "jane@mednovalife.com",
            "sender_name": "Ada",
            "sender_email": "ada@mednovaos.com",
        },
        content_type="application/x-www-form-urlencoded",
    )
    assert send_response.status_code == 200
    assert send_response.get_json()["success"] is True


def test_outreach_draft_reuses_request_id_and_persists_contact_details(tmp_path, monkeypatch):
    db_path = tmp_path / "request-id-outreach.sqlite"
    monkeypatch.setenv("MEDNOVA_DB_PATH", str(db_path))

    import app as app_module
    app_module = importlib.reload(app_module)

    client = app_module.app.test_client()
    company_id = _create_company(client, "Request Bio")
    contact = _create_contact(client, company_id)

    first_response = client.post(
        f"/api/crm/companies/{company_id}/outreach/drafts",
        json={
            "subject": "First draft",
            "body": "Initial body",
            "template_key": "follow_up",
            "contact_id": contact["id"],
            "request_id": "req-123",
        },
    )
    assert first_response.status_code == 200
    first_payload = first_response.get_json()

    second_response = client.post(
        f"/api/crm/companies/{company_id}/outreach/drafts",
        json={
            "subject": "Second draft",
            "body": "Updated body",
            "template_key": "follow_up",
            "contact_id": contact["id"],
            "request_id": "req-123",
        },
    )
    assert second_response.status_code == 200
    second_payload = second_response.get_json()
    assert second_payload["draft_id"] == first_payload["draft_id"]

    history_response = client.get(f"/api/crm/companies/{company_id}/outreach/history")
    history = history_response.get_json()["items"]
    latest = history[0]
    assert latest["recipient"] == contact["email"]
    assert latest["recipientName"] == contact["full_name"]
    assert latest["contactName"] == contact["full_name"]


def test_outreach_send_reuses_existing_record_for_same_request_id(tmp_path, monkeypatch):
    db_path = tmp_path / "reuse-request-id.sqlite"
    monkeypatch.setenv("MEDNOVA_DB_PATH", str(db_path))

    import app as app_module
    app_module = importlib.reload(app_module)

    monkeypatch.setattr(app_module.requests, "post", lambda *args, **kwargs: type("Response", (), {"ok": True, "status_code": 200, "json": lambda self: {"id": "msg_123"}, "raise_for_status": lambda self: None})())

    client = app_module.app.test_client()
    company_id = _create_company(client, "Reuse Bio")
    contact = _create_contact(client, company_id)

    draft_response = client.post(
        f"/api/crm/companies/{company_id}/outreach/drafts",
        json={
            "subject": "Reusable draft",
            "body": "Initial body",
            "template_key": "follow_up",
            "contact_id": contact["id"],
            "request_id": "req-dup-123",
            "recipient": contact["email"],
            "recipient_name": contact["full_name"],
            "company_name": "Reuse Bio",
            "contact_name": contact["full_name"],
        },
    )
    assert draft_response.status_code == 200

    send_response = client.post(
        f"/api/crm/companies/{company_id}/outreach/send",
        json={
            "subject": "Reusable draft",
            "body": "Initial body",
            "template_key": "follow_up",
            "contact_id": contact["id"],
            "request_id": "req-dup-123",
            "recipient": contact["email"],
            "recipient_name": contact["full_name"],
            "company_name": "Reuse Bio",
            "contact_name": contact["full_name"],
        },
    )
    assert send_response.status_code == 200
    assert send_response.get_json()["success"] is True

    history_response = client.get(f"/api/crm/companies/{company_id}/outreach/history")
    history = history_response.get_json()["items"]
    assert len(history) == 1
    assert history[0]["recipient"] == contact["email"]
    assert history[0]["recipientName"] == contact["full_name"]
    assert history[0]["contactName"] == contact["full_name"]


def test_outreach_composer_preloads_contact_and_sender_defaults(tmp_path, monkeypatch):
    db_path = tmp_path / "composer-defaults.sqlite"
    monkeypatch.setenv("MEDNOVA_DB_PATH", str(db_path))

    import app as app_module
    app_module = importlib.reload(app_module)

    client = app_module.app.test_client()
    company_id = _create_company(client, "Composer Bio")
    _create_contact(client, company_id)

    response = client.get(f"/crm/companies/{company_id}/outreach")
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "jane@example.com" in body
    assert "MedNova Lifesciences" in body
    assert "info@mednovalife.com" in body
    assert "Introducing" in body or "Subject" in body


def test_outreach_status_reports_resend_configuration(tmp_path, monkeypatch):
    db_path = tmp_path / "outreach-status.sqlite"
    monkeypatch.setenv("MEDNOVA_DB_PATH", str(db_path))
    monkeypatch.setenv("RESEND_API_KEY", "test-key")
    monkeypatch.delenv("FROM_EMAIL", raising=False)

    import app as app_module
    app_module = importlib.reload(app_module)

    client = app_module.app.test_client()
    response = client.get("/api/outreach/status")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["resendConfigured"] is True
    assert payload["senderConfigured"] is True
    assert payload["senderEmail"] == "info@mednovalife.com"
    assert payload["environmentLoaded"] is True


def test_outreach_build_uses_company_name_when_contact_name_is_placeholder(tmp_path, monkeypatch):
    db_path = tmp_path / "placeholder-recipient.sqlite"
    monkeypatch.setenv("MEDNOVA_DB_PATH", str(db_path))

    import app as app_module
    app_module = importlib.reload(app_module)

    client = app_module.app.test_client()
    company_id = _create_company(client, "Placeholder Bio")
    client.post(
        f"/api/crm/companies/{company_id}/contacts",
        json={
            "full_name": "Public Contact",
            "role": "Public contact",
            "email": "jane@example.com",
            "phone": "+1-555-0100",
            "source": "CRM",
        },
    )

    response = client.post(
        f"/api/crm/companies/{company_id}/outreach/build",
        json={"template_key": "introduction"},
    )
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["recipientName"] == "Placeholder Bio"


def test_resend_send_uses_signature_and_logs_failure(tmp_path, monkeypatch):
    db_path = tmp_path / "resend.sqlite"
    monkeypatch.setenv("MEDNOVA_DB_PATH", str(db_path))
    monkeypatch.setenv("RESEND_API_KEY", "test-key")
    monkeypatch.setenv("CONSULTATION_EMAIL", "info@mednovalife.com")

    import app as app_module
    app_module = importlib.reload(app_module)

    monkeypatch.setattr(app_module.requests, "post", lambda *args, **kwargs: type("Response", (), {"ok": True, "status_code": 200, "json": lambda self: {"id": "msg_123"}, "raise_for_status": lambda self: None})())

    client = app_module.app.test_client()
    company_id = _create_company(client, "Resend Bio")
    _create_contact(client, company_id)

    response = client.post(
        f"/api/crm/companies/{company_id}/outreach/send",
        json={
            "subject": "Real outreach",
            "body": "This is a real send.",
            "template_key": "introduction",
            "recipient": "jane@example.com",
            "sender_name": "Ada",
            "sender_email": "ada@mednovaos.com",
        },
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["success"] is True
    assert payload["status"] == "sent"
    assert payload["message_id"] == "msg_123"

    history_response = client.get(f"/api/crm/companies/{company_id}/outreach/history")
    history = history_response.get_json()["items"]
    latest = history[0]
    assert latest["status"] == "sent"
    assert "MedNova Lifesciences" in latest["body"]
    assert latest["recipient"] == "jane@example.com"


def test_resend_send_surfaces_provider_errors(tmp_path, monkeypatch):
    db_path = tmp_path / "resend-errors.sqlite"
    monkeypatch.setenv("MEDNOVA_DB_PATH", str(db_path))
    monkeypatch.setenv("RESEND_API_KEY", "test-key")
    monkeypatch.setenv("CONSULTATION_EMAIL", "info@mednovalife.com")

    import app as app_module
    app_module = importlib.reload(app_module)

    def raise_request_error(*args, **kwargs):
        raise requests.exceptions.RequestException("provider rejected recipient")

    monkeypatch.setattr(app_module.requests, "post", raise_request_error)

    client = app_module.app.test_client()
    company_id = _create_company(client, "Resend Failure Bio")
    _create_contact(client, company_id)

    response = client.post(
        f"/api/crm/companies/{company_id}/outreach/send",
        json={
            "subject": "Failed outreach",
            "body": "This should surface the provider error.",
            "template_key": "introduction",
            "recipient": "jane@example.com",
            "sender_name": "Ada",
            "sender_email": "ada@mednovaos.com",
        },
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["success"] is False
    assert payload["status"] == "failed"
    assert "provider rejected recipient" in payload["error"]
