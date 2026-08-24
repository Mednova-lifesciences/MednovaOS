import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import app
from backend.database.repositories.pipeline import PipelineRepository


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


def test_pipeline_repository_maps_expiry_columns():
    repo = PipelineRepository()
    normalized = repo._normalize_row({
        "id": 1,
        "company": "Acme Pharma",
        "estimated_value": 500000,
        "expiration_date": "2035-01-01",
    })
    assert normalized["expiry_date"] == "2035-01-01"


def test_opportunities_page_uses_live_revenue_pipeline_rows():
    pipeline_rows = PipelineRepository().list(limit=5)
    assert pipeline_rows, 'expected revenue_pipeline data'

    client = app.test_client()
    response = client.get('/opportunities?page=1&page_size=5')
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert pipeline_rows[0].get('company') in body


def test_pipeline_repository_orders_by_estimated_value_desc():
    repo = PipelineRepository()
    rows, total, _, _, _, _, _ = repo.list_page(page=1, page_size=5)
    assert total >= 2
    assert rows[0]["estimated_value"] >= rows[1]["estimated_value"]


def test_crm_page_redirects_to_frontend():
    client = app.test_client()
    response = client.get('/crm', follow_redirects=False)
    assert response.status_code == 302
    assert response.headers['Location'].startswith('http://127.0.0.1:')
