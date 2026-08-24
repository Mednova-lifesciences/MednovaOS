from __future__ import annotations

import json
import logging
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .supabase_client import get_supabase

ROOT_DIR = Path(__file__).resolve().parents[2]
LOG_DIR = ROOT_DIR / "logs"
LOG_PATH = LOG_DIR / "cloud_sync.log"
_LAST_CLOUD_SYNC_SUMMARY: dict[str, Any] = {}


def _use_file_logging() -> bool:
    if os.getenv("MEDNOVA_ENV", "").lower() == "production" or os.getenv("FLASK_ENV", "").lower() == "production":
        return False

    explicit = (os.getenv("LOG_TO_FILE") or "").strip().lower()
    if explicit:
        return explicit in {"1", "true", "yes", "y"}
    env = os.getenv("MEDNOVA_ENV", "").lower() or os.getenv("FLASK_ENV", "").lower()
    return env != "production"

logger = logging.getLogger("cloud_sync")
logger.setLevel(logging.INFO)
if not logger.handlers:
    if _use_file_logging():
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(LOG_PATH)
    else:
        handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)


class SupabaseSyncError(RuntimeError):
    pass


def _connect_sqlite(db_path: str | Path | None = None) -> sqlite3.Connection:
    default_db = ROOT_DIR / "database" / "nafdac_intelligence.db"
    configured = db_path or os.getenv("MEDNOVA_DB_PATH") or os.getenv("DATABASE_PATH")
    path = Path(configured) if configured else default_db
    path = path.expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table_name,)).fetchone()
    return row is not None


def _normalize(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return json.loads(json.dumps(value, default=str, sort_keys=True))
    return value


def _ensure_crm_reports_invalid_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS crm_reports_invalid (
            id INTEGER PRIMARY KEY,
            crm_company_id INTEGER,
            report_type TEXT,
            report_name TEXT,
            report_data TEXT,
            executive_summary TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            quarantined_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )


def _company_exists(conn: sqlite3.Connection, company_id: Any) -> bool:
    if company_id is None:
        return False
    try:
        row = conn.execute("SELECT 1 FROM crm_companies WHERE id = ?", (company_id,)).fetchone()
        return row is not None
    except Exception:
        return False


def _row_to_dict(row: Any, columns: list[str]) -> dict[str, Any]:
    if isinstance(row, sqlite3.Row):
        return dict(row)
    if isinstance(row, dict):
        return dict(row)
    try:
        return dict(row)
    except Exception:
        return {column: row[idx] for idx, column in enumerate(columns)}


def _normalize_company_id(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _extract_company_candidates(payload: Any) -> tuple[set[int], set[str]]:
    candidates_id: set[int] = set()
    candidates_name: set[str] = set()

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            for key, nested_value in value.items():
                normalized_key = str(key).lower()
                if normalized_key in {"company_id", "crm_company_id"}:
                    company_id = _normalize_company_id(nested_value)
                    if company_id is not None:
                        candidates_id.add(company_id)
                elif normalized_key == "company_name" and isinstance(nested_value, str) and nested_value.strip():
                    candidates_name.add(nested_value.strip())
                walk(nested_value)
        elif isinstance(value, list):
            for element in value:
                walk(element)

    walk(payload)
    return candidates_id, candidates_name


def _find_company_id_from_candidates(conn: sqlite3.Connection, candidate_ids: set[int], candidate_names: set[str]) -> int | None:
    if len(candidate_ids) == 1:
        company_id = next(iter(candidate_ids))
        if _company_exists(conn, company_id):
            return company_id
    elif len(candidate_ids) > 1:
        for candidate_id in candidate_ids:
            if _company_exists(conn, candidate_id):
                return candidate_id

    if len(candidate_names) == 1:
        company_name = next(iter(candidate_names))
        row = conn.execute(
            "SELECT id FROM crm_companies WHERE lower(company_name) = lower(?) LIMIT 1",
            (company_name,),
        ).fetchone()
        if row:
            return row[0]

    return None


def _recover_or_quarantine_crm_reports(conn: sqlite3.Connection) -> tuple[int, int, list[int], list[int]]:
    if not _table_exists(conn, "crm_reports"):
        return 0, 0, [], []
    _ensure_crm_reports_invalid_table(conn)
    try:
        orphan_rows = conn.execute(
            "SELECT * FROM crm_reports WHERE crm_company_id IS NULL"
        ).fetchall()
    except sqlite3.OperationalError:
        return 0, 0, [], []
    recovered = 0
    quarantined = 0
    recovered_ids: list[int] = []
    quarantined_ids: list[int] = []
    for row in orphan_rows:
        row_dict = _row_to_dict(row, list(row.keys()) if hasattr(row, 'keys') else [])
        payload: dict[str, Any] = {}
        report_data = row_dict.get("report_data")
        if isinstance(report_data, str) and report_data:
            try:
                payload = json.loads(report_data)
            except Exception:
                payload = {}
        elif isinstance(report_data, dict):
            payload = report_data

        candidate_ids, candidate_names = _extract_company_candidates(payload)
        company_id = _normalize_company_id(payload.get("company_id") or payload.get("crm_company_id"))
        if company_id is None:
            company_id = _find_company_id_from_candidates(conn, candidate_ids, candidate_names)

        if company_id is not None and _company_exists(conn, company_id):
            conn.execute(
                "UPDATE crm_reports SET crm_company_id = ? WHERE id = ?",
                (company_id, row_dict["id"]),
            )
            recovered += 1
            recovered_ids.append(row_dict["id"])
            continue

        conn.execute(
            "INSERT OR REPLACE INTO crm_reports_invalid (id, crm_company_id, report_type, report_name, report_data, executive_summary, created_at, updated_at, quarantined_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)",
            (
                row_dict["id"],
                None,
                row_dict.get("report_type"),
                row_dict.get("report_name"),
                row_dict.get("report_data"),
                row_dict.get("executive_summary"),
                row_dict.get("created_at"),
                row_dict.get("updated_at"),
            ),
        )
        conn.execute("DELETE FROM crm_reports WHERE id = ?", (row_dict["id"],))
        quarantined += 1
        quarantined_ids.append(row_dict["id"])

    if orphan_rows:
        conn.commit()
    return recovered, quarantined, recovered_ids, quarantined_ids


def _canonical_payload(row: dict[str, Any]) -> dict[str, Any]:
    payload = dict(row)
    payload = {key: _normalize(value) for key, value in payload.items() if value is not None}
    return payload


def _translate_payload_for_table(table_name: str, payload: dict[str, Any]) -> dict[str, Any]:
    if table_name != "opportunities":
        return payload
    translated = dict(payload)
    if "category" in translated and "opportunity_type" not in translated:
        translated["opportunity_type"] = translated.pop("category")
    if "opportunity_type" in translated and "category" in translated:
        translated.pop("category")
    return translated


def _filter_payload(payload: dict[str, Any], allowed_columns: set[str] | None = None) -> dict[str, Any]:
    if not allowed_columns:
        return payload
    return {key: value for key, value in payload.items() if key in allowed_columns}


def _ensure_remote_table(client: Any, table_name: str) -> bool:
    try:
        client.table(table_name).select("id").limit(1).execute()
        return True
    except Exception as exc:
        error_text = str(exc)
        if "Could not find the table" not in error_text and "does not exist" not in error_text:
            raise
        logger.warning("remote table %s does not exist yet: %s", table_name, error_text)
        return False


def _upsert_rows(client: Any, table_name: str, rows: list[dict[str, Any]], key_field: str, allowed_columns: set[str] | None = None) -> tuple[int, int, int, list[dict[str, Any]]]:
    added = 0
    updated = 0
    unchanged = 0
    failed = []
    if not rows:
        return added, updated, unchanged, failed

    filtered_rows = []
    for row in rows:
        payload = _canonical_payload(row)
        payload = _translate_payload_for_table(table_name, payload)
        payload = _filter_payload(payload, allowed_columns)
        identifier = payload.get(key_field)
        if not identifier and key_field != "id":
            continue
        if key_field == "id" and payload.get("id") is None:
            continue
        filtered_rows.append((payload, identifier))

    if not filtered_rows:
        return added, updated, unchanged, failed

    if table_name == "crm_reports":
        for payload, _ in filtered_rows:
            for attempt in range(4):
                try:
                    upsert_response = client.table(table_name).upsert([payload], on_conflict=key_field).execute()
                    if getattr(upsert_response, "data", None) is not None:
                        added += 1
                    else:
                        failed.append({"table": table_name, "row": payload, "error": f"upsert_empty:{getattr(upsert_response, 'status_code', '')}:{getattr(upsert_response, 'text', '')}"})
                    break
                except Exception as exc:  # pragma: no cover - defensive path
                    if attempt < 3:
                        continue
                    failed.append({"table": table_name, "row": payload, "error": str(exc)})
        return added, updated, unchanged, failed

    for start in range(0, len(filtered_rows), 10):
        chunk = filtered_rows[start:start + 10]
        upsert_rows = [payload for payload, _ in chunk]
        for attempt in range(4):
            try:
                upsert_response = client.table(table_name).upsert(upsert_rows, on_conflict=key_field).execute()
                if getattr(upsert_response, "data", None) is not None:
                    added += len(upsert_rows)
                else:
                    failed.extend({"table": table_name, "row": payload, "error": f"upsert_empty:{getattr(upsert_response, 'status_code', '')}:{getattr(upsert_response, 'text', '')}"} for payload, _ in chunk)
                break
            except Exception as exc:  # pragma: no cover - defensive path
                if attempt < 3:
                    continue
                failed.extend({"table": table_name, "row": payload, "error": str(exc)} for payload, _ in chunk)
    return added, updated, unchanged, failed


def _get_available_columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
    try:
        rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
        return {row[1] for row in rows}
    except Exception:
        return set()


def _filter_rows_for_table(table_name: str, rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if table_name != "crm_reports":
        return rows, []

    valid_rows: list[dict[str, Any]] = []
    skipped_rows: list[dict[str, Any]] = []
    for row in rows:
        if row.get("crm_company_id") is None:
            skipped_rows.append(row)
        else:
            valid_rows.append(row)
    return valid_rows, skipped_rows


def _build_sync_query(table_name: str, columns: set[str]) -> str:
    if table_name == "products":
        available_columns = [col for col in [
            "id", "registration_number", "product_name", "generic_name", "active_ingredient", "strength",
            "dosage_form_id", "route_id", "category_id", "atc_code", "description", "pack_size",
            "composition", "approval_date", "expiry_date", "status", "applicant_id", "manufacturer_id",
            "source_last_updated", "synced_at", "created_at", "updated_at"
        ] if col in columns or col == "id"]
        if not available_columns:
            return "SELECT * FROM products"
        return f"SELECT {', '.join(available_columns)} FROM products"
    if table_name == "manufacturers":
        available_columns = [col for col in ["id", "nafdac_manufacturer_id", "manufacturer_name", "country", "address", "created_at", "updated_at"] if col in columns or col == "id"]
        if not available_columns:
            return "SELECT * FROM manufacturers"
        return f"SELECT {', '.join(available_columns)} FROM manufacturers"
    if table_name == "applicants":
        available_columns = [col for col in ["id", "nafdac_applicant_id", "applicant_name", "address", "created_at", "updated_at"] if col in columns or col == "id"]
        if not available_columns:
            return "SELECT * FROM applicants"
        return f"SELECT {', '.join(available_columns)} FROM applicants"
    if table_name == "renewal_alerts":
        available_columns = [col for col in ["id", "product_id", "expiry_date", "days_remaining", "alert_level", "created_at", "updated_at"] if col in columns or col == "id"]
        if not available_columns:
            return "SELECT * FROM renewal_alerts"
        return f"SELECT {', '.join(available_columns)} FROM renewal_alerts"
    if table_name == "opportunities":
        available_columns = [col for col in ["id", "product_id", "title", "description", "category", "created_at", "updated_at"] if col in columns or col == "id"]
        if not available_columns:
            return "SELECT * FROM opportunities"
        return f"SELECT {', '.join(available_columns)} FROM opportunities"
    if table_name == "sync_history":
        available_columns = [col for col in ["id", "started_at", "finished_at", "status", "products_added", "products_updated", "products_removed", "duration_seconds", "error_message"] if col in columns or col == "id"]
        if not available_columns:
            return "SELECT * FROM sync_history"
        return f"SELECT {', '.join(available_columns)} FROM sync_history"
    return f"SELECT * FROM {table_name}"


def _allowed_columns_for_table(table_name: str) -> set[str] | None:
    if table_name == "products":
        return {"id", "registration_number", "product_name", "generic_name", "active_ingredient", "strength", "dosage_form_id", "route_id", "category_id", "atc_code", "description", "pack_size", "composition", "approval_date", "expiry_date", "status", "applicant_id", "manufacturer_id", "source_last_updated", "synced_at", "created_at", "updated_at"}
    if table_name == "manufacturers":
        return {"id", "nafdac_manufacturer_id", "manufacturer_name", "country", "address", "created_at", "updated_at"}
    if table_name == "applicants":
        return {"id", "nafdac_applicant_id", "applicant_name", "address", "created_at", "updated_at"}
    if table_name == "renewal_alerts":
        return {"id", "product_id", "expiry_date", "days_remaining", "alert_level", "created_at", "updated_at"}
    if table_name == "opportunities":
        return {"id", "product_id", "title", "description", "opportunity_type", "created_at", "updated_at"}
    if table_name == "crm_companies":
        return {"id", "company_name", "country", "opportunity_score", "portfolio_summary", "source", "report_context", "greenbook_products_json", "registration_numbers", "dosage_forms", "therapeutic_areas", "registration_dates", "opportunity_status", "pipeline_stage", "created_at", "updated_at"}
    if table_name == "crm_contacts":
        return {"id", "crm_company_id", "full_name", "role", "department", "email", "phone", "source", "created_at", "updated_at", "source_url", "discovered_at", "confidence_score", "verification_status", "website", "linkedin_url", "notes"}
    if table_name == "crm_deals":
        return {"id", "crm_company_id", "crm_contact_id", "title", "stage", "value", "currency", "probability", "expected_close_at", "owner", "description", "created_at", "updated_at"}
    if table_name == "crm_tasks":
        return {"id", "crm_company_id", "title", "description", "task_type", "status", "priority", "due_date", "assigned_to", "completed_at", "created_at", "updated_at"}
    if table_name == "crm_notes":
        return {"id", "crm_company_id", "body", "created_at"}
    if table_name == "crm_outreach_emails":
        return {"id", "crm_company_id", "crm_contact_id", "template_key", "template_name", "subject", "body", "recipient", "recipient_name", "sender_name", "sender_email", "from_email", "company_name", "contact_name", "status", "direction", "message_id", "error_message", "client_request_id", "created_at", "updated_at", "sent_at"}
    if table_name == "crm_company_intelligence":
        return {"id", "crm_company_id", "data", "search_results_json", "search_date", "search_status", "last_refresh", "source_summary", "created_at", "updated_at"}
    if table_name == "crm_reports":
        return {"id", "crm_company_id", "report_type", "report_name", "report_data", "executive_summary", "created_at", "updated_at"}
    if table_name == "settings":
        return {"id", "key", "value", "created_at", "updated_at"}
    if table_name == "sync_history":
        return {"id", "started_at", "finished_at", "status", "products_added", "products_updated", "products_removed", "duration_seconds", "error_message"}
    return None


def sync_sqlite_to_supabase(db_path: str | Path | None = None) -> dict[str, Any]:
    started_at = datetime.now(timezone.utc)
    logger.info("cloud sync start")
    summary: dict[str, Any] = {
        "status": "success",
        "added": 0,
        "updated": 0,
        "unchanged": 0,
        "failed": 0,
        "processed": 0,
        "crm_reports_synced": 0,
        "crm_reports_recovered": 0,
        "crm_reports_quarantined": 0,
        "skipped": 0,
        "duration_seconds": 0,
        "errors": [],
    }
    skipped_tables = 0
    processed_tables = 0

    conn = _connect_sqlite(db_path)
    try:
        client = get_supabase()
        recovered, quarantined, recovered_ids, quarantined_ids = _recover_or_quarantine_crm_reports(conn)
        summary["crm_reports_recovered"] = recovered
        summary["crm_reports_recovered_ids"] = recovered_ids
        summary["crm_reports_quarantined"] += quarantined
        summary["crm_reports_quarantined_ids"] = quarantined_ids
        if recovered or quarantined:
            logger.info(
                "crm_reports cleanup: recovered=%s quarantined=%s recovered_ids=%s quarantined_ids=%s",
                recovered,
                quarantined,
                recovered_ids,
                quarantined_ids,
            )

        tables = [
            ("products", "registration_number"),
            ("crm_companies", "id"),
            ("crm_contacts", "id"),
            ("crm_deals", "id"),
            ("crm_tasks", "id"),
            ("crm_notes", "id"),
            ("crm_outreach_emails", "id"),
            ("crm_company_intelligence", "id"),
            ("revenue_pipeline", "id"),
            ("crm_reports", "id"),
            ("settings", "id"),
            ("manufacturers", "manufacturer_name"),
            ("applicants", "applicant_name"),
            ("renewal_alerts", "id"),
            ("opportunities", "id"),
            ("sync_history", "id"),
        ]

        summary["tables"] = {}
        summary["skipped"] = 0
        failed_tables: list[str] = []

        for table_name, key_field in tables:
            if not _table_exists(conn, table_name):
                logger.warning("skipping missing table %s", table_name)
                summary["tables"][table_name] = 0
                failed_tables.append(table_name)
                continue
            processed_tables += 1
            columns = _get_available_columns(conn, table_name)
            query = _build_sync_query(table_name, columns)
            try:
                if not _ensure_remote_table(client, table_name):
                    skipped_tables += 1
                    failed_tables.append(table_name)
                    logger.warning("skipping %s because the remote table is not available", table_name)
                    continue
            except Exception as exc:
                summary["failed"] += 1
                summary["errors"].append({"table": table_name, "error": str(exc)})
                failed_tables.append(table_name)
                logger.warning("failed remote table check for %s: %s", table_name, exc)
                continue

            try:
                cursor = conn.execute(query)
                columns = [column[0] for column in cursor.description or []]
                rows = [dict(zip(columns, row)) for row in cursor.fetchall()]
            except Exception as exc:
                logger.warning("could not read rows from %s using query %s: %s", table_name, query, exc)
                summary["failed"] += 1
                summary["errors"].append({"table": table_name, "error": str(exc)})
                failed_tables.append(table_name)
                continue
            if table_name == "products" and key_field == "registration_number":
                rows = [row for row in rows if row.get("registration_number")]

            total_rows = len(rows)
            rows, skipped_rows = _filter_rows_for_table(table_name, rows)
            summary["skipped"] += len(skipped_rows)
            if table_name == "crm_reports":
                for skipped_row in skipped_rows:
                    logger.warning(
                        "Skipping crm_report %s because crm_company_id is NULL",
                        skipped_row.get("id"),
                    )
                    summary["errors"].append({
                        "table": table_name,
                        "row_id": skipped_row.get("id"),
                        "error": "skipped row because crm_company_id is missing",
                    })

            added, updated, unchanged, failed = _upsert_rows(client, table_name, rows, key_field, allowed_columns=_allowed_columns_for_table(table_name))
            summary["tables"][table_name] = len(rows)
            summary["processed"] += len(rows)
            summary["added"] += added
            summary["updated"] += updated
            summary["unchanged"] += unchanged
            summary["failed"] += len(failed)
            summary["errors"].extend(failed)
            if table_name == "crm_reports":
                summary["crm_reports_synced"] = len(rows) - len(failed)
            if failed:
                failed_tables.append(table_name)
            logger.info("table=%s processed=%s added=%s updated=%s unchanged=%s failed=%s skipped=%s", table_name, len(rows), added, updated, unchanged, len(failed), len(skipped_rows))

        counts = {}
        for table_name, _ in tables:
            counts[table_name] = _count_supabase(client, table_name)
        summary["counts"] = counts
        summary["failed_tables"] = sorted(set(failed_tables))

        summary["counts_match"] = all(
            counts.get(table_name, 0) == _count_sqlite(conn, table_name)
            for table_name, _ in tables if _table_exists(conn, table_name)
        )
        summary["total_errors"] = len(summary["errors"])
        if skipped_tables and processed_tables and skipped_tables == processed_tables:
            summary["status"] = "skipped"
        elif summary["failed_tables"] and summary["status"] == "success":
            summary["status"] = "partial"
    except Exception as exc:  # pragma: no cover - defensive path
        summary["status"] = "failed"
        summary["failed"] += 1
        summary["errors"].append({"error": str(exc)})
        logger.exception("cloud sync failed: %s", exc)
    finally:
        finished_at = datetime.now(timezone.utc)
        duration = int((finished_at - started_at).total_seconds())
        summary["duration_seconds"] = duration
        global _LAST_CLOUD_SYNC_SUMMARY
        _LAST_CLOUD_SYNC_SUMMARY = summary
        logger.info("cloud sync finish duration=%s summary=%s", duration, json.dumps(summary, default=str))
        conn.close()
    return summary


def get_last_cloud_sync_summary() -> dict[str, Any]:
    return dict(_LAST_CLOUD_SYNC_SUMMARY)


def _count_sqlite(conn: sqlite3.Connection, table_name: str) -> int:
    return int(conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0] or 0)


def _count_supabase(client: Any, table_name: str) -> int:
    try:
        response = client.table(table_name).select("id", count="exact").execute()
        return int(getattr(response, "count", len(response.data or [])) or 0)
    except Exception:
        return 0


if __name__ == "__main__":
    summary = sync_sqlite_to_supabase()
    print(f"Products synced: {summary.get('tables', {}).get('products', 0)}")
    print(f"CRM Companies synced: {summary.get('tables', {}).get('crm_companies', 0)}")
    print(f"Revenue Pipeline synced: {summary.get('tables', {}).get('revenue_pipeline', 0)}")
    print(f"CRM Reports synced: {summary.get('crm_reports_synced', 0)}")
    print(f"CRM Reports recovered: {summary.get('crm_reports_recovered', 0)}")
    print(f"CRM Reports quarantined: {summary.get('crm_reports_quarantined', 0)}")
    print(f"Total Errors: {summary.get('total_errors', 0)}")
