"""One-shot migration script: copy SQLite CRM tables into Supabase Postgres.

USAGE:
  python migrate_sqlite_to_supabase.py /path/to/sqlite.db

This script is idempotent: it will skip rows already present in Supabase (by id or unique fields).
It preserves IDs when present.
Requires SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY in env.
"""

import os
import sqlite3
import sys
from supabase import create_client


def get_supabase():
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set in the environment")
    return create_client(url, key)


def upsert_rows(supabase, table, rows, unique_key=None):
    # Insert rows one-by-one using upsert (on conflict) where possible.
    for row in rows:
        payload = dict(row)
        # If id exists, try insert with id; supabase REST will accept it.
        try:
            # Use upsert via insert with on_conflict if supported by supabase client
            resp = supabase.table(table).upsert(payload, on_conflict=unique_key).execute()
        except Exception:
            # fallback to insert
            resp = supabase.table(table).insert(payload).execute()
        if resp.error:
            print(f"Warning: upsert {table} id={payload.get('id')} error: {resp.error}")


def migrate(sqlite_path: str):
    supabase = get_supabase()
    conn = sqlite3.connect(sqlite_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    mapping = [
        ("crm_companies", "SELECT * FROM crm_companies", "company_name"),
        ("crm_activities", "SELECT * FROM crm_activities", None),
        ("crm_notes", "SELECT * FROM crm_notes", None),
        ("crm_contacts", "SELECT * FROM crm_contacts", None),
        ("crm_tasks", "SELECT * FROM crm_tasks", None),
        ("crm_deals", "SELECT * FROM crm_deals", None),
        ("crm_outreach_emails", "SELECT * FROM crm_outreach_emails", None),
    ]

    for table, sql, unique in mapping:
        try:
            cur.execute(sql)
            rows = [dict(r) for r in cur.fetchall()]
        except sqlite3.OperationalError as e:
            print(f"Skipping {table}: {e}")
            continue
        print(f"Migrating {len(rows)} rows into {table}...")
        upsert_rows(supabase, table, rows, unique_key=unique)

    conn.close()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python migrate_sqlite_to_supabase.py /path/to/sqlite.db")
        sys.exit(2)
    migrate(sys.argv[1])
