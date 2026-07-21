from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from flask import Flask, abort, jsonify, render_template, request

from backend.cloud.sync_to_supabase import sync_sqlite_to_supabase
from backend.sync.scheduler import SyncScheduler
from backend.sync.sync_engine import run_sync
from database.init_db import initialize_database

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = BASE_DIR / "database" / "nafdac_intelligence.db"
CANDIDATES = [Path.home() / "MedNova-OS" / "database" / "nafdac_intelligence.db", DEFAULT_DB_PATH]


def db_path() -> Path:
    configured = os.getenv("MEDNOVA_DB_PATH")
    if configured:
        path = Path(configured).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        return path
    for candidate in CANDIDATES:
        if candidate.exists():
            return candidate
    return DEFAULT_DB_PATH


def connect() -> sqlite3.Connection:
    db_file = ensure_database()
    conn = sqlite3.connect(db_file)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def table_exists(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def scalar(conn: sqlite3.Connection, sql: str, params=()) -> int:
    row = conn.execute(sql, params).fetchone()
    return int(row[0] or 0) if row else 0


def ensure_database() -> Path:
    db_file = db_path()
    db_file.parent.mkdir(parents=True, exist_ok=True)
    if not db_file.exists():
        initialize_database(db_file)
        return db_file

    with sqlite3.connect(db_file) as conn:
        products_table = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='products'").fetchone()
        if not products_table:
            initialize_database(db_file)
            return db_file

        expected_columns = {"nafdac_product_id", "registration_number", "dosage_form_id", "route_id", "category_id"}
        actual_columns = {row[1] for row in conn.execute("PRAGMA table_info(products)").fetchall()}
        if not expected_columns.issubset(actual_columns):
            initialize_database(db_file)
    return db_file


app = Flask(__name__, template_folder="templates", static_folder="static")
ensure_database()
scheduler = SyncScheduler(app)
scheduler.start()


@app.template_filter("money")
def money(value):
    try:
        return f"₦{float(value):,.0f}"
    except (TypeError, ValueError):
        return "₦0"


@app.route("/")
def dashboard():
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
        )
    finally:
        conn.close()


@app.route("/products")
def products():
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


@app.route("/products/<int:pid>")
def product_detail(pid):
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
                r.route_name AS route_of_administration
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


@app.route("/opportunities")
def opportunities():
    conn = connect()
    try:
        rows = conn.execute("SELECT company, category, products, estimated_value, recommended_services, status FROM revenue_pipeline ORDER BY estimated_value DESC, products DESC").fetchall() if table_exists(conn, "revenue_pipeline") else []
        return render_template("opportunities.html", rows=rows)
    finally:
        conn.close()


@app.route("/renewals")
def renewal_watch():
    months = min(max(request.args.get("months", 12, type=int), 1), 60)
    conn = connect()
    try:
        rows = conn.execute(
            "SELECT product_name, registration_number AS nafdac_number, c.category_name AS product_category, a.applicant_name, m.manufacturer_name, expiry_date, status FROM products p LEFT JOIN applicants a ON a.id = p.applicant_id LEFT JOIN manufacturers m ON m.id = p.manufacturer_id LEFT JOIN categories c ON c.id = p.category_id WHERE p.expiry_date IS NOT NULL AND date(p.expiry_date) BETWEEN date('now') AND date('now', ?) ORDER BY date(p.expiry_date), a.applicant_name LIMIT 1000",
            (f"+{months} months",),
        ).fetchall()
        return render_template("renewals.html", rows=rows, months=months)
    finally:
        conn.close()


@app.route("/admin/sync", methods=["POST"])
def admin_sync():
    summary = run_sync()
    return jsonify(summary)


@app.route("/admin/sync/status")
def admin_sync_status():
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


@app.route("/admin/cloud-sync", methods=["POST"])
def admin_cloud_sync():
    summary = sync_sqlite_to_supabase()
    return jsonify(summary)


@app.route("/admin/cloud-sync/status")
def admin_cloud_sync_status():
    from backend.cloud.sync_to_supabase import get_last_cloud_sync_summary

    return jsonify(get_last_cloud_sync_summary())


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
