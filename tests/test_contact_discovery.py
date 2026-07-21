import importlib
import sys
from pathlib import Path

import pytest
import requests

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class FakeResponse:
    def __init__(self, payload=None, text="", status_code=200):
        self._payload = payload
        self.text = text
        self.status_code = status_code

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError("request failed")


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


def test_contact_discovery_enriches_company_and_logs_activities(tmp_path, monkeypatch):
    db_path = tmp_path / "contact-discovery.sqlite"
    monkeypatch.setenv("MEDNOVA_DB_PATH", str(db_path))

    import app as app_module
    app_module = importlib.reload(app_module)

    client = app_module.app.test_client()
    company_id = _create_company(client, "Acme Bio")

    def fake_post(url, json=None, timeout=None, headers=None):
        assert url == "https://api.tavily.com/search"
        return FakeResponse(
            payload={
                "results": [
                    {"url": "https://acmebio.com/contact", "title": "Contact us", "content": "Reach us at jane@acmebio.com or +1-555-0100"},
                    {"url": "https://acmebio.com/leadership", "title": "Leadership", "content": "Jane Doe CEO"},
                ]
            }
        )

    def fake_get(url, timeout=None, headers=None):
        if url.endswith("/contact"):
            return FakeResponse(text="<html><body><a href='mailto:jane@acmebio.com'>jane@acmebio.com</a><p>+1-555-0100</p></body></html>")
        return FakeResponse(text="<html><body><h2>Jane Doe</h2><p>Chief Executive Officer</p></body></html>")

    monkeypatch.setattr(app_module.requests, "post", fake_post)
    monkeypatch.setattr(app_module.requests, "get", fake_get)

    response = client.post(f"/api/crm/companies/{company_id}/contacts/discover")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["success"] is True
    assert payload["imported_count"] >= 1

    detail_response = client.get(f"/api/crm/companies/{company_id}")
    payload = detail_response.get_json()
    contacts = payload["contacts"]
    assert any(contact["email"] == "jane@acmebio.com" for contact in contacts)
    assert any(contact["source"] == "discovered" for contact in contacts)

    activities = payload["activities"]
    titles = {item["title"] for item in activities}
    assert "Contact discovery started" in titles
    assert "Contacts imported" in titles
    assert "Enrichment completed" in titles


def test_contact_discovery_skips_duplicates_and_updates_existing_discovered_contact(tmp_path, monkeypatch):
    db_path = tmp_path / "contact-duplicates.sqlite"
    monkeypatch.setenv("MEDNOVA_DB_PATH", str(db_path))

    import app as app_module
    app_module = importlib.reload(app_module)

    client = app_module.app.test_client()
    company_id = _create_company(client, "Northwind Labs")

    existing = client.post(
        f"/api/crm/companies/{company_id}/contacts",
        json={
            "full_name": "Existing Discovery",
            "email": "dup@example.com",
            "phone": "+1-555-2222",
            "source": "discovered",
        },
    )
    assert existing.status_code == 200

    def fake_post(url, json=None, timeout=None, headers=None):
        return FakeResponse(payload={"results": [{"url": "https://northwindlabs.com", "title": "Northwind", "content": "dup@example.com +1-555-2222"}]})

    def fake_get(url, timeout=None, headers=None):
        return FakeResponse(text="<html><body><a href='mailto:dup@example.com'>dup@example.com</a><p>+1-555-2222</p></body></html>")

    monkeypatch.setattr(app_module.requests, "post", fake_post)
    monkeypatch.setattr(app_module.requests, "get", fake_get)

    response = client.post(f"/api/crm/companies/{company_id}/contacts/discover")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["duplicates_skipped"] >= 1

    detail_response = client.get(f"/api/crm/companies/{company_id}")
    contacts = detail_response.get_json()["contacts"]
    assert len(contacts) == 1
    assert contacts[0]["source"] == "discovered"


def test_contact_discovery_handles_provider_failure(tmp_path, monkeypatch):
    db_path = tmp_path / "contact-failure.sqlite"
    monkeypatch.setenv("MEDNOVA_DB_PATH", str(db_path))

    import app as app_module
    app_module = importlib.reload(app_module)

    client = app_module.app.test_client()
    company_id = _create_company(client, "Broken Bio")

    def fake_post(url, json=None, timeout=None, headers=None):
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(app_module.requests, "post", fake_post)

    response = client.post(f"/api/crm/companies/{company_id}/contacts/discover")
    assert response.status_code == 502
    assert "failed" in response.get_json()["error"].lower()


def test_contact_discovery_handles_timeout_errors_with_friendly_message(tmp_path, monkeypatch):
    db_path = tmp_path / "contact-timeout.sqlite"
    monkeypatch.setenv("MEDNOVA_DB_PATH", str(db_path))

    import app as app_module
    app_module = importlib.reload(app_module)

    client = app_module.app.test_client()
    company_id = _create_company(client, "Timeout Bio")

    def fake_post(url, json=None, timeout=None, headers=None):
        raise requests.exceptions.Timeout("timed out")

    monkeypatch.setattr(app_module.requests, "post", fake_post)

    response = client.post(f"/api/crm/companies/{company_id}/contacts/discover")
    assert response.status_code == 502
    assert "could not be reached" in response.get_json()["error"].lower()


def test_contact_discovery_handles_multiple_companies(tmp_path, monkeypatch):
    db_path = tmp_path / "contact-multi.sqlite"
    monkeypatch.setenv("MEDNOVA_DB_PATH", str(db_path))

    import app as app_module
    app_module = importlib.reload(app_module)

    client = app_module.app.test_client()
    first_id = _create_company(client, "Alpha Labs")
    second_id = _create_company(client, "Beta Labs")

    def fake_post(url, json=None, timeout=None, headers=None):
        return FakeResponse(payload={"results": [{"url": "https://example.com/contact", "title": "Contact", "content": "info@example.com"}]})

    def fake_get(url, timeout=None, headers=None):
        return FakeResponse(text="<html><body><a href='mailto:info@example.com'>info@example.com</a></body></html>")

    monkeypatch.setattr(app_module.requests, "post", fake_post)
    monkeypatch.setattr(app_module.requests, "get", fake_get)

    response = client.post(f"/api/crm/companies/{first_id}/contacts/discover")
    assert response.status_code == 200
    second_response = client.post(f"/api/crm/companies/{second_id}/contacts/discover")
    assert second_response.status_code == 200
    assert second_response.get_json()["imported_count"] >= 1
