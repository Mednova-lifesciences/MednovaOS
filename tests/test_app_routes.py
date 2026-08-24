import os
import re
import sys

os.environ.setdefault("MEDNOVA_ENV", "test")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import app


def test_ready_endpoint_reports_supabase_mode():
    client = app.test_client()
    response = client.get("/api/ready")

    assert response.status_code == 200
    data = response.get_json()
    assert data["status"] == "ok"
    assert data["mode"] == "supabase"


def test_legacy_dashboard_uses_live_expiring_count():
    client = app.test_client()
    response = client.get("/legacy-dashboard")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Expiring in 12 months" in html
    assert re.search(r"<strong>\d+</strong>", html) is not None


def test_products_page_uses_live_repository_total():
    client = app.test_client()
    response = client.get("/products")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "8742 products" in html
