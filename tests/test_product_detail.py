import os
import sqlite3
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import app


def test_product_detail_populates_lookup_fields():
    conn = sqlite3.connect(os.path.join(os.path.dirname(__file__), '..', 'database', 'nafdac_intelligence.db'))
    try:
        product_id = conn.execute('SELECT id FROM products ORDER BY id LIMIT 1').fetchone()[0]
    finally:
        conn.close()

    client = app.test_client()
    response = client.get(f'/products/{product_id}')
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert 'NAFDAC number' in body
    assert 'Applicant' in body
    assert 'Manufacturer' in body
    assert 'Category' in body
