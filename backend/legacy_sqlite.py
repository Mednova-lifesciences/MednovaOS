from __future__ import annotations

import sqlite3
from pathlib import Path
from datetime import datetime, timezone
import os
from database.init_db import initialize_database
from database.apply_migrations import apply_migrations
from flask import render_template, request, abort, jsonify
from typing import Any
import json

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = BASE_DIR / "database" / "nafdac_intelligence.db"


def _get_setting_value(name: str, fallback: str | None = None) -> str | None:
    return (os.getenv(name) or os.getenv("DATABASE_PATH") or fallback or "").strip() or None


def db_path() -> Path:
    configured = _get_setting_value("MEDNOVA_DB_PATH")
    if configured:
        path = Path(configured).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        return path
    return DEFAULT_DB_PATH


def connect() -> sqlite3.Connection:
    db_file = db_path()
    conn = sqlite3.connect(db_file, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def table_exists(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def _ensure_contact_enrichment_columns(conn: sqlite3.Connection) -> None:
    columns = {row[1] for row in conn.execute("PRAGMA table_info(crm_contacts)").fetchall()}
    additions = [
        ("source_url", "TEXT"),
        ("discovered_at", "TEXT"),
        ("confidence_score", "REAL"),
        ("verification_status", "TEXT"),
        ("website", "TEXT"),
        ("linkedin_url", "TEXT"),
        ("notes", "TEXT"),
    ]
    for column_name, column_type in additions:
        if column_name not in columns:
            conn.execute(f"ALTER TABLE crm_contacts ADD COLUMN {column_name} {column_type}")


def _ensure_outreach_columns(conn: sqlite3.Connection) -> None:
    columns = {row[1] for row in conn.execute("PRAGMA table_info(crm_outreach_emails)").fetchall()}
    additions = [
        ("template_key", "TEXT"),
        ("template_name", "TEXT"),
        ("recipient_name", "TEXT"),
        ("sender_name", "TEXT"),
        ("sender_email", "TEXT"),
        ("from_email", "TEXT"),
        ("company_name", "TEXT"),
        ("contact_name", "TEXT"),
        ("message_id", "TEXT"),
        ("error_message", "TEXT"),
        ("client_request_id", "TEXT"),
    ]
    for column_name, column_type in additions:
        if column_name not in columns:
            conn.execute(f"ALTER TABLE crm_outreach_emails ADD COLUMN {column_name} {column_type}")


def _ensure_outreach_tables(conn: sqlite3.Connection) -> None:
    # minimal placeholder: ensure table exists if migrations are not applied
    conn.execute(
        "CREATE TABLE IF NOT EXISTS crm_outreach_emails (id INTEGER PRIMARY KEY AUTOINCREMENT, crm_company_id INTEGER, recipient TEXT, subject TEXT, body TEXT, created_at TEXT)"
    )


def scalar(conn: sqlite3.Connection, sql: str, params=()) -> int:
    row = conn.execute(sql, params).fetchone()
    return int(row[0] or 0) if row else 0


def _validate_existing_database(db_file: Path) -> None:
    with sqlite3.connect(db_file, timeout=30) as conn:
        if not conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='products'").fetchone():
            raise RuntimeError(f"Existing database at {db_file} is missing required base tables.")

        expected_columns = {"nafdac_product_id", "registration_number", "dosage_form_id", "route_id", "category_id"}
        actual_columns = {row[1] for row in conn.execute("PRAGMA table_info(products)").fetchall()}
        if not expected_columns.issubset(actual_columns):
            raise RuntimeError(
                f"Existing database at {db_file} does not contain the expected products columns: {sorted(expected_columns)}. "
                "Do not reinitialize a production database automatically."
            )


def ensure_database() -> Path:
    db_file = db_path()
    db_file.parent.mkdir(parents=True, exist_ok=True)
    if not db_file.exists():
        initialize_database(db_file)
        apply_migrations(db_file)
        return db_file

    _validate_existing_database(db_file)
    apply_migrations(db_file)
    return db_file


def dashboard_view():
    conn = connect()
    try:
        manufacturers = scalar(conn, "SELECT COUNT(*) FROM manufacturers")
        products = scalar(conn, "SELECT COUNT(*) FROM products")
        if table_exists(conn, "revenue_pipeline"):
            opportunities = scalar(conn, "SELECT COUNT(*) FROM revenue_pipeline")
            pipeline_value = scalar(conn, "SELECT COALESCE(SUM(estimated_value), 0) FROM revenue_pipeline")
            top_accounts = conn.execute(
                "SELECT company, category, products, estimated_value, recommended_services, status FROM revenue_pipeline ORDER BY estimated_value DESC, products DESC LIMIT 25"
            ).fetchall()
        else:
            opportunities = 0
            pipeline_value = 0
            top_accounts = []
        expiring = scalar(
            conn,
            "SELECT COUNT(*) FROM products WHERE expiry_date IS NOT NULL AND date(expiry_date) BETWEEN date('now') AND date('now', '+12 months')",
        )
        categories = conn.execute(
            "SELECT COALESCE(c.category_name, 'Unknown') AS category, COUNT(p.id) AS product_count FROM products p LEFT JOIN categories c ON c.id = p.category_id GROUP BY c.category_name ORDER BY product_count DESC"
        ).fetchall()
        renewals = conn.execute(
            "SELECT COALESCE(a.applicant_name, m.manufacturer_name, 'Not provided') AS company, COUNT(*) AS expiring_products FROM products p LEFT JOIN applicants a ON a.id = p.applicant_id LEFT JOIN manufacturers m ON m.id = p.manufacturer_id WHERE p.expiry_date IS NOT NULL AND date(p.expiry_date) BETWEEN date('now') AND date('now', '+12 months') GROUP BY company ORDER BY expiring_products DESC LIMIT 20"
        ).fetchall()
        latest_sync = conn.execute(
            "SELECT started_at, finished_at, status, products_added, products_updated, products_removed, duration_seconds, error_message FROM sync_history ORDER BY id DESC LIMIT 1"
        ).fetchone()
        last_sync_payload = None
        if latest_sync:
            last_sync_payload = {
                "started_at": latest_sync["started_at"],
                "finished_at": latest_sync["finished_at"],
                "status": latest_sync["status"] or "unknown",
                "products_added": int(latest_sync["products_added"] or 0),
                "products_updated": int(latest_sync["products_updated"] or 0),
                "products_removed": int(latest_sync["products_removed"] or 0),
                "duration_seconds": int(latest_sync["duration_seconds"] or 0),
                "error_message": latest_sync["error_message"],
            }
        return render_template(
            "dashboard.html",
            manufacturers=manufacturers,
            products=products,
            opportunities=opportunities,
            pipeline_value=pipeline_value,
            expiring=expiring,
            categories=categories,
            top_accounts=top_accounts,
            renewals=renewals,
            db=str(db_path()),
            last_sync_payload=last_sync_payload,
        )
    finally:
        conn.close()


def products_view():
    q = request.args.get("q", "").strip()
    category = request.args.get("category", "").strip()
    status = request.args.get("status", "").strip()
    page = max(request.args.get("page", 1, type=int), 1)
    size = 50
    offset = (page - 1) * size

    where = ["1=1"]
    params = []
    if q:
        like = f"%{q}%"
        where.append("(p.product_name LIKE ? OR p.active_ingredient LIKE ? OR p.registration_number LIKE ? OR a.applicant_name LIKE ? OR m.manufacturer_name LIKE ?)")
        params.extend([like] * 5)
    if category:
        where.append("c.category_name = ?")
        params.append(category)
    if status:
        where.append("p.status = ?")
        params.append(status)

    where_clause = " AND ".join(where)
    conn = connect()
    try:
        total = scalar(
            conn,
            f"SELECT COUNT(*) FROM products p LEFT JOIN applicants a ON a.id = p.applicant_id LEFT JOIN manufacturers m ON m.id = p.manufacturer_id LEFT JOIN categories c ON c.id = p.category_id WHERE {where_clause}",
            tuple(params),
        )
        rows = conn.execute(
            f"SELECT p.id AS greenbook_product_id, p.product_name, p.active_ingredient AS ingredient_name, c.category_name AS product_category, p.registration_number AS nafdac_number, a.applicant_name, m.manufacturer_name, p.approval_date, p.expiry_date, p.status FROM products p LEFT JOIN applicants a ON a.id = p.applicant_id LEFT JOIN manufacturers m ON m.id = p.manufacturer_id LEFT JOIN categories c ON c.id = p.category_id WHERE {where_clause} ORDER BY p.approval_date DESC, p.product_name LIMIT ? OFFSET ?",
            tuple(params + [size, offset]),
        ).fetchall()
        categories = conn.execute("SELECT DISTINCT c.category_name AS category_name FROM products p LEFT JOIN categories c ON c.id = p.category_id WHERE c.category_name IS NOT NULL ORDER BY c.category_name").fetchall()
        statuses = conn.execute("SELECT DISTINCT status FROM products WHERE status IS NOT NULL ORDER BY status").fetchall()
        return render_template("products.html", rows=rows, q=q, category=category, status=status, categories=categories, statuses=statuses, total=total, page=page, size=size)
    finally:
        conn.close()


def product_detail_view(pid: int):
    conn = connect()
    try:
        row = conn.execute(
            """
            SELECT
                p.id,
                p.nafdac_product_id,
                p.registration_number AS nafdac_number,
                p.product_name,
                p.generic_name,
                p.active_ingredient,
                p.strength,
                p.pack_size,
                p.composition,
                p.approval_date,
                p.expiry_date,
                p.status,
                p.description,
                p.source_last_updated,
                c.category_name AS product_category,
                a.applicant_name,
                m.manufacturer_name,
                df.form_name AS dosage_form,
                r.route_name AS route_of_administration,
                p.source_last_updated
            FROM products p
            LEFT JOIN categories c ON c.id = p.category_id
            LEFT JOIN applicants a ON a.id = p.applicant_id
            LEFT JOIN manufacturers m ON m.id = p.manufacturer_id
            LEFT JOIN dosage_forms df ON df.id = p.dosage_form_id
            LEFT JOIN routes r ON r.id = p.route_id
            WHERE p.id = ?
            """,
            (pid,),
        ).fetchone()
        if not row:
            abort(404)
        return render_template("product_detail.html", product=row)
    finally:
        conn.close()


def opportunities_view(filters: dict):
    conn = connect()
    try:
        rows = _build_opportunity_rows(conn, filters)
        categories = conn.execute(
            "SELECT DISTINCT c.category_name AS category_name FROM products p LEFT JOIN categories c ON c.id = p.category_id WHERE c.category_name IS NOT NULL ORDER BY c.category_name"
        ).fetchall()
        statuses = conn.execute(
            "SELECT DISTINCT status FROM products WHERE status IS NOT NULL ORDER BY status"
        ).fetchall()
        return render_template(
            "opportunities.html",
            rows=rows,
            q=filters.get("q"),
            product_category=filters.get("product_category"),
            registration_status=filters.get("registration_status"),
            estimated_value=filters.get("estimated_value"),
            sort_by=filters.get("sort_by"),
            categories=categories,
            statuses=statuses,
        )
    finally:
        conn.close()


def renewal_watch_view(months: int):
    conn = connect()
    try:
        rows = conn.execute(
            "SELECT product_name, registration_number AS nafdac_number, c.category_name AS product_category, a.applicant_name, m.manufacturer_name, expiry_date, status FROM products p LEFT JOIN applicants a ON a.id = p.applicant_id LEFT JOIN manufacturers m ON m.id = p.manufacturer_id LEFT JOIN categories c ON c.id = p.category_id WHERE p.expiry_date IS NOT NULL AND date(p.expiry_date) BETWEEN date('now') AND date('now', ?) ORDER BY date(p.expiry_date), a.applicant_name LIMIT 1000",
            (f"+{months} months",),
        ).fetchall()
        return render_template("renewals.html", rows=rows, months=months)
    finally:
        conn.close()


def growhub_crm_companies_api():
    conn = connect()
    try:
        return jsonify(_build_growhub_company_payloads(conn))
    finally:
        conn.close()


def growhub_crm_data_api():
    conn = connect()
    try:
        companies = _build_growhub_company_payloads(conn)
        payload = _build_growhub_related_payloads(conn, companies)
        return jsonify(payload)
    finally:
        conn.close()


def create_pipeline_deal_row(company_id: int, title: str, stage: str, value: int, currency: str, probability: int, expected_close_at, owner: str, description: str):
    conn = connect()
    try:
        cursor = conn.execute(
            """
            INSERT INTO crm_deals (
                crm_company_id, crm_contact_id, title, stage, value, currency, probability, expected_close_at, owner, description
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (company_id, None, title, stage, value, currency, probability, expected_close_at, owner, description),
        )
        row_id = int(cursor.lastrowid)
        return conn.execute("SELECT id, crm_company_id, crm_contact_id, title, stage, value, currency, probability, expected_close_at, owner, description FROM crm_deals WHERE id = ?", (row_id,)).fetchone()
    finally:
        conn.close()


def build_growhub_pipeline_deals(companies) -> list[dict]:
    conn = connect()
    try:
        deals = []
        created_any = False
        for company in companies:
            company_id = int(company["id"])
            company_name = company["name"]

            existing_deals = conn.execute(
                "SELECT id, crm_company_id, crm_contact_id, title, stage, value, currency, probability, expected_close_at, owner, description FROM crm_deals WHERE crm_company_id = ? ORDER BY updated_at DESC, created_at DESC, id DESC",
                (company_id,),
            ).fetchall()
            if existing_deals:
                continue

            company_row = conn.execute(
                "SELECT pipeline_stage, opportunity_score FROM crm_companies WHERE id = ?",
                (company_id,),
            ).fetchone()
            stage = _crm_deal_stage_to_frontend(company_row["pipeline_stage"] if company_row else None)
            probability = int(company_row["opportunity_score"] or 0) if company_row else 0
            fallback_value = 0
            if table_exists(conn, "revenue_pipeline"):
                revenue_row = conn.execute(
                    "SELECT estimated_value FROM revenue_pipeline WHERE lower(company) = ? LIMIT 1",
                    (company_name.lower(),),
                ).fetchone()
                if revenue_row and revenue_row["estimated_value"] is not None:
                    fallback_value = int(float(revenue_row["estimated_value"]) or 0)
            created_row = create_pipeline_deal_row(
                company_id,
                f"{company_name} opportunity",
                stage,
                fallback_value,
                "NGN",
                probability,
                None,
                "MedNovaOS",
                "",
            )
            created_any = True
            deals.append(_crm_deal_payload_from_row(created_row))
        if created_any:
            conn.commit()
        return deals
    finally:
        conn.close()


def admin_sync_status_view():
    conn = connect()
    try:
        last_sync = conn.execute("SELECT started_at, status, products_added, products_updated, products_removed, duration_seconds, error_message FROM sync_history ORDER BY id DESC LIMIT 1").fetchone()
        product_count = conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]
        return jsonify({
            "last_sync": dict(last_sync) if last_sync else None,
            "running": False,
            "failed": bool(last_sync and last_sync["status"] == "failed"),
            "products": product_count,
            "last_duration": int(last_sync["duration_seconds"] or 0) if last_sync else 0,
            "database_size": 0,
        })
    finally:
        conn.close()


def readiness_check_view():
    try:
        db_file = db_path()
        conn = sqlite3.connect(db_file, timeout=5)
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("SELECT 1")
        conn.close()
        return jsonify({"status": "ready", "database": str(db_file)})
    except Exception as exc:
        return jsonify({"status": "error", "message": str(exc)}), 503
