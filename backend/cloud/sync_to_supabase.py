from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .supabase_client import get_supabase

ROOT_DIR = Path(__file__).resolve().parents[2]
LOG_DIR = ROOT_DIR / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_PATH = LOG_DIR / "cloud_sync.log"
_LAST_CLOUD_SYNC_SUMMARY: dict[str, Any] = {}

logger = logging.getLogger("cloud_sync")
logger.setLevel(logging.INFO)
if not logger.handlers:
    handler = logging.FileHandler(LOG_PATH)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)


class SupabaseSyncError(RuntimeError):
    pass


def _connect_sqlite(db_path: str | Path | None = None) -> sqlite3.Connection:
    default_db = ROOT_DIR / "database" / "nafdac_intelligence.db"
    path = Path(db_path or default_db)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table_name,)).fetchone()
    return row is not None


def _normalize(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return json.loads(json.dumps(value, default=str, sort_keys=True))
    return value


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
        "duration_seconds": 0,
        "errors": [],
    }
    skipped_tables = 0
    processed_tables = 0

    conn = _connect_sqlite(db_path)
    try:
        client = get_supabase()
        tables = [
            ("products", "registration_number"),
            ("manufacturers", "manufacturer_name"),
            ("applicants", "applicant_name"),
            ("renewal_alerts", "id"),
            ("opportunities", "id"),
            ("sync_history", "id"),
        ]

        for table_name, key_field in tables:
            if not _table_exists(conn, table_name):
                logger.warning("skipping missing table %s", table_name)
                continue
            processed_tables += 1
            columns = _get_available_columns(conn, table_name)
            query = _build_sync_query(table_name, columns)
            if not _ensure_remote_table(client, table_name):
                skipped_tables += 1
                logger.warning("skipping %s because the remote table is not available", table_name)
                continue
            try:
                cursor = conn.execute(query)
                columns = [column[0] for column in cursor.description or []]
                rows = [dict(zip(columns, row)) for row in cursor.fetchall()]
            except Exception as exc:
                logger.warning("could not read rows from %s using query %s: %s", table_name, query, exc)
                summary["failed"] += 1
                summary["errors"].append({"table": table_name, "error": str(exc)})
                continue
            summary["processed"] += len(rows)
            if table_name == "products" and key_field == "registration_number":
                rows = [row for row in rows if row.get("registration_number")]
            added, updated, unchanged, failed = _upsert_rows(client, table_name, rows, key_field, allowed_columns=_allowed_columns_for_table(table_name))
            summary["added"] += added
            summary["updated"] += updated
            summary["unchanged"] += unchanged
            summary["failed"] += len(failed)
            summary["errors"].extend(failed)
            logger.info("table=%s processed=%s added=%s updated=%s unchanged=%s failed=%s", table_name, len(rows), added, updated, unchanged, len(failed))

        compare = {
            "products": _count_supabase(client, "products"),
            "manufacturers": _count_supabase(client, "manufacturers"),
            "applicants": _count_supabase(client, "applicants"),
            "renewals": _count_supabase(client, "renewal_alerts"),
            "sync_history": _count_supabase(client, "sync_history"),
        }
        summary["compare"] = compare
        summary["counts_match"] = all(
            compare[key] == _count_sqlite(conn, table_name)
            for key, table_name in [("products", "products"), ("manufacturers", "manufacturers"), ("applicants", "applicants"), ("renewals", "renewal_alerts"), ("sync_history", "sync_history")]
        )
        if skipped_tables and processed_tables and skipped_tables == processed_tables:
            summary["status"] = "skipped"
        elif skipped_tables and summary["status"] == "success":
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
    print(json.dumps(sync_sqlite_to_supabase(), indent=2))
