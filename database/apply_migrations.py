from __future__ import annotations

import sqlite3
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
MIGRATIONS_DIR = BASE_DIR / "migrations"


def _ensure_schema_migrations_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )


def _table_columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()}


def _ensure_column(conn: sqlite3.Connection, table_name: str, column_name: str, column_def: str) -> None:
    if column_name in _table_columns(conn, table_name):
        return
    conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_def}")


def _apply_crm_schema_alignment_migration(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS crm_companies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_name TEXT NOT NULL,
            country TEXT,
            opportunity_score INTEGER DEFAULT 0,
            portfolio_summary TEXT,
            source TEXT,
            report_context TEXT,
            greenbook_products_json TEXT,
            registration_numbers TEXT,
            dosage_forms TEXT,
            therapeutic_areas TEXT,
            registration_dates TEXT,
            opportunity_status TEXT DEFAULT 'New',
            pipeline_stage TEXT DEFAULT 'Lead',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (company_name)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS crm_activities (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            crm_company_id INTEGER NOT NULL,
            activity_type TEXT NOT NULL,
            title TEXT NOT NULL,
            body TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (crm_company_id) REFERENCES crm_companies(id) ON DELETE CASCADE
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS crm_notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            crm_company_id INTEGER NOT NULL,
            body TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (crm_company_id) REFERENCES crm_companies(id) ON DELETE CASCADE
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS crm_contacts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            crm_company_id INTEGER NOT NULL,
            full_name TEXT NOT NULL,
            role TEXT,
            department TEXT,
            email TEXT,
            phone TEXT,
            source TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            source_url TEXT,
            discovered_at TEXT,
            confidence_score REAL,
            verification_status TEXT,
            website TEXT,
            linkedin_url TEXT,
            notes TEXT,
            FOREIGN KEY (crm_company_id) REFERENCES crm_companies(id) ON DELETE CASCADE
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS crm_tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            crm_company_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            description TEXT,
            task_type TEXT NOT NULL DEFAULT 'follow-up',
            status TEXT NOT NULL DEFAULT 'pending',
            priority TEXT NOT NULL DEFAULT 'medium',
            due_date TEXT,
            assigned_to TEXT,
            completed_at TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (crm_company_id) REFERENCES crm_companies(id) ON DELETE CASCADE
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS crm_deals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            crm_company_id INTEGER NOT NULL,
            crm_contact_id INTEGER,
            title TEXT NOT NULL,
            stage TEXT NOT NULL DEFAULT 'lead',
            value NUMERIC NOT NULL DEFAULT 0,
            currency TEXT NOT NULL DEFAULT 'USD',
            probability INTEGER NOT NULL DEFAULT 0,
            expected_close_at TEXT,
            owner TEXT,
            description TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (crm_company_id) REFERENCES crm_companies(id) ON DELETE CASCADE,
            FOREIGN KEY (crm_contact_id) REFERENCES crm_contacts(id) ON DELETE SET NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS crm_outreach_emails (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            crm_company_id INTEGER NOT NULL,
            crm_contact_id INTEGER,
            template_key TEXT,
            template_name TEXT,
            subject TEXT NOT NULL,
            body TEXT NOT NULL,
            recipient TEXT,
            recipient_name TEXT,
            sender_name TEXT,
            sender_email TEXT,
            from_email TEXT,
            company_name TEXT,
            contact_name TEXT,
            status TEXT NOT NULL DEFAULT 'draft',
            direction TEXT NOT NULL DEFAULT 'outbound',
            message_id TEXT,
            error_message TEXT,
            client_request_id TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            sent_at TEXT,
            FOREIGN KEY (crm_company_id) REFERENCES crm_companies(id) ON DELETE CASCADE,
            FOREIGN KEY (crm_contact_id) REFERENCES crm_contacts(id) ON DELETE SET NULL
        )
        """
    )

    _ensure_column(conn, "crm_companies", "opportunity_status", "TEXT DEFAULT 'New'")
    _ensure_column(conn, "crm_companies", "pipeline_stage", "TEXT DEFAULT 'Lead'")
    _ensure_column(conn, "crm_contacts", "source_url", "TEXT")
    _ensure_column(conn, "crm_contacts", "discovered_at", "TEXT")
    _ensure_column(conn, "crm_contacts", "confidence_score", "REAL")
    _ensure_column(conn, "crm_contacts", "verification_status", "TEXT")
    _ensure_column(conn, "crm_contacts", "website", "TEXT")
    _ensure_column(conn, "crm_contacts", "linkedin_url", "TEXT")
    _ensure_column(conn, "crm_contacts", "notes", "TEXT")
    _ensure_column(conn, "crm_outreach_emails", "template_key", "TEXT")
    _ensure_column(conn, "crm_outreach_emails", "template_name", "TEXT")
    _ensure_column(conn, "crm_outreach_emails", "recipient_name", "TEXT")
    _ensure_column(conn, "crm_outreach_emails", "sender_name", "TEXT")
    _ensure_column(conn, "crm_outreach_emails", "sender_email", "TEXT")
    _ensure_column(conn, "crm_outreach_emails", "from_email", "TEXT")
    _ensure_column(conn, "crm_outreach_emails", "company_name", "TEXT")
    _ensure_column(conn, "crm_outreach_emails", "contact_name", "TEXT")
    _ensure_column(conn, "crm_outreach_emails", "message_id", "TEXT")
    _ensure_column(conn, "crm_outreach_emails", "error_message", "TEXT")
    _ensure_column(conn, "crm_outreach_emails", "client_request_id", "TEXT")

    for index_sql in [
        "CREATE INDEX IF NOT EXISTS idx_crm_contacts_company_id ON crm_contacts(crm_company_id)",
        "CREATE INDEX IF NOT EXISTS idx_crm_tasks_company_id ON crm_tasks(crm_company_id)",
        "CREATE INDEX IF NOT EXISTS idx_crm_tasks_status ON crm_tasks(status)",
        "CREATE INDEX IF NOT EXISTS idx_crm_tasks_due_date ON crm_tasks(due_date)",
        "CREATE INDEX IF NOT EXISTS idx_crm_activities_company_id ON crm_activities(crm_company_id)",
        "CREATE INDEX IF NOT EXISTS idx_crm_notes_company_id ON crm_notes(crm_company_id)",
        "CREATE INDEX IF NOT EXISTS idx_crm_deals_company_id ON crm_deals(crm_company_id)",
        "CREATE INDEX IF NOT EXISTS idx_crm_deals_stage ON crm_deals(stage)",
        "CREATE INDEX IF NOT EXISTS idx_crm_deals_owner ON crm_deals(owner)",
        "CREATE INDEX IF NOT EXISTS idx_crm_outreach_company ON crm_outreach_emails(crm_company_id)",
        "CREATE INDEX IF NOT EXISTS idx_crm_outreach_status ON crm_outreach_emails(status)",
        "CREATE INDEX IF NOT EXISTS idx_crm_outreach_created ON crm_outreach_emails(created_at)",
    ]:
        conn.execute(index_sql)


def apply_migrations(db_path: str | Path | None = None) -> None:
    database_path = Path(db_path or BASE_DIR / "nafdac_intelligence.db")
    conn = sqlite3.connect(database_path, timeout=30.0)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 30000")
    conn.execute("PRAGMA journal_mode = WAL")
    try:
        _ensure_schema_migrations_table(conn)
        for migration_path in sorted(MIGRATIONS_DIR.glob("*.sql")):
            applied = conn.execute("SELECT 1 FROM schema_migrations WHERE name = ?", (migration_path.name,)).fetchone()
            if applied:
                continue
            if migration_path.name == "005_crm_schema_alignment.sql":
                _apply_crm_schema_alignment_migration(conn)
            else:
                conn.executescript(migration_path.read_text(encoding="utf-8"))
            conn.execute("INSERT INTO schema_migrations (name) VALUES (?)", (migration_path.name,))
            conn.commit()
    finally:
        conn.close()
