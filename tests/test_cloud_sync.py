import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.cloud import sync_to_supabase


def test_sync_marks_as_skipped_when_remote_tables_are_unavailable(monkeypatch, tmp_path):
    db_path = tmp_path / "test.sqlite"
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("CREATE TABLE products (id INTEGER PRIMARY KEY, registration_number TEXT)")
        conn.execute("CREATE TABLE manufacturers (id INTEGER PRIMARY KEY, manufacturer_name TEXT)")
        conn.execute("CREATE TABLE applicants (id INTEGER PRIMARY KEY, applicant_name TEXT)")
        conn.execute("CREATE TABLE renewal_alerts (id INTEGER PRIMARY KEY, product_id INTEGER)")
        conn.execute("CREATE TABLE opportunities (id INTEGER PRIMARY KEY, product_id INTEGER)")
        conn.execute("CREATE TABLE sync_history (id INTEGER PRIMARY KEY, started_at TEXT)")
        conn.commit()
    finally:
        conn.close()

    monkeypatch.setattr(sync_to_supabase, "_connect_sqlite", lambda db_path=None: sqlite3.connect(db_path))
    monkeypatch.setattr(sync_to_supabase, "_table_exists", lambda conn, table_name: True)
    monkeypatch.setattr(sync_to_supabase, "_ensure_remote_table", lambda client, table_name: False)
    monkeypatch.setattr(sync_to_supabase, "get_supabase", lambda: object())
    monkeypatch.setattr(sync_to_supabase, "_count_supabase", lambda client, table_name: 0)
    monkeypatch.setattr(sync_to_supabase, "_count_sqlite", lambda conn, table_name: 0)

    summary = sync_to_supabase.sync_sqlite_to_supabase(db_path)

    assert summary["status"] == "skipped"
    assert summary["processed"] == 0
    assert summary["failed"] == 0


def test_sync_uses_available_columns_when_schema_differs(monkeypatch, tmp_path):
    db_path = tmp_path / "test.sqlite"
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("CREATE TABLE products (id INTEGER PRIMARY KEY, registration_number TEXT)")
        conn.execute("CREATE TABLE manufacturers (id INTEGER PRIMARY KEY, manufacturer_name TEXT)")
        conn.execute("CREATE TABLE applicants (id INTEGER PRIMARY KEY, applicant_name TEXT)")
        conn.execute("CREATE TABLE renewal_alerts (id INTEGER PRIMARY KEY, product_id INTEGER, created_at TEXT, updated_at TEXT)")
        conn.execute("CREATE TABLE opportunities (id INTEGER PRIMARY KEY, product_id INTEGER, title TEXT, description TEXT, category TEXT, created_at TEXT, updated_at TEXT)")
        conn.execute("CREATE TABLE sync_history (id INTEGER PRIMARY KEY, started_at TEXT)")
        conn.execute("INSERT INTO products (id, registration_number) VALUES (1, 'ABC')")
        conn.execute("INSERT INTO manufacturers (id, manufacturer_name) VALUES (1, 'Acme')")
        conn.execute("INSERT INTO applicants (id, applicant_name) VALUES (1, 'Applicant')")
        conn.execute("INSERT INTO renewal_alerts (id, product_id, created_at, updated_at) VALUES (1, 1, 'now', 'now')")
        conn.execute("INSERT INTO opportunities (id, product_id, title, description, category, created_at, updated_at) VALUES (1, 1, 'Title', 'Desc', 'Cat', 'now', 'now')")
        conn.execute("INSERT INTO sync_history (id, started_at) VALUES (1, 'now')")
        conn.commit()
    finally:
        conn.close()

    class FakeTable:
        def __init__(self, table_name):
            self.table_name = table_name

        def select(self, *args, **kwargs):
            return self

        def in_(self, *args, **kwargs):
            return self

        def limit(self, *args, **kwargs):
            return self

        def execute(self):
            return type("Response", (), {"data": [], "count": 0, "status_code": 200, "text": ""})()

        def upsert(self, rows, on_conflict=None):
            self.upsert_rows = rows
            return self

    class FakeClient:
        def __init__(self):
            self.tables = {}

        def table(self, table_name):
            if table_name not in self.tables:
                self.tables[table_name] = FakeTable(table_name)
            return self.tables[table_name]

    fake_client = FakeClient()

    monkeypatch.setattr(sync_to_supabase, "_connect_sqlite", lambda db_path=None: sqlite3.connect(db_path))
    monkeypatch.setattr(sync_to_supabase, "_table_exists", lambda conn, table_name: True)
    monkeypatch.setattr(sync_to_supabase, "_ensure_remote_table", lambda client, table_name: True)
    monkeypatch.setattr(sync_to_supabase, "get_supabase", lambda: fake_client)
    monkeypatch.setattr(sync_to_supabase, "_count_supabase", lambda client, table_name: 0)
    monkeypatch.setattr(sync_to_supabase, "_count_sqlite", lambda conn, table_name: 0)

    summary = sync_to_supabase.sync_sqlite_to_supabase(db_path)

    assert summary["status"] == "success"
    assert summary["processed"] >= 1
    opportunities_rows = fake_client.tables["opportunities"].upsert_rows
    assert opportunities_rows[0]["title"] == "Title"
    assert opportunities_rows[0]["opportunity_type"] == "Cat"
    assert "category" not in opportunities_rows[0]
