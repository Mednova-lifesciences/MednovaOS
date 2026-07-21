import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import app


def test_opportunities_page_renders_filters_and_expanded_actions():
    client = app.test_client()
    response = client.get('/opportunities')
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert 'Revenue Opportunities' in body
    assert 'Search company' in body
    assert 'name="estimated_value"' in body
    assert 'Commercial Actions' in body
    assert 'products-table' in body
    assert 'data-action="generate-report"' in body
    assert 'data-action="add-to-crm"' in body
    assert 'id="report-drawer"' in body
    assert 'id="crm-success-toast"' in body
    assert 'href="/crm"' in body
    assert 'aria-hidden="true"' in body
    assert 'Generate Report' in body
    assert 'Add Opportunity' in body


def test_crm_page_redirects_to_frontend():
    client = app.test_client()
    response = client.get('/crm', follow_redirects=False)
    assert response.status_code == 302
    assert response.headers['Location'] == 'http://127.0.0.1:5173'
