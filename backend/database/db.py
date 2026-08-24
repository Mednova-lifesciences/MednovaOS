from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Any

from supabase import create_client

from database.apply_migrations import apply_migrations
from database.init_db import initialize_database


def get_supabase_client():
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set in the environment")
    return create_client(url, key)


class SupabaseDB:
    def __init__(self):
        self.client = None
        try:
            self.client = get_supabase_client()
        except Exception:
            self.client = None

        self.sqlite_path = self._get_sqlite_path()
        self.sqlite_conn: sqlite3.Connection | None = None
        self._ensure_sqlite_ready()

    def _get_sqlite_path(self) -> Path:
        configured = os.getenv("MEDNOVA_DB_PATH") or os.getenv("DATABASE_PATH")
        if configured:
            return Path(configured).expanduser()
        return Path(__file__).resolve().parents[2] / "database" / "nafdac_intelligence.db"

    def _is_supabase_only_table(self, table: str) -> bool:
        return str(table).lower() in {
            "crm_companies",
            "crm_contacts",
            "crm_tasks",
            "crm_meetings",
            "crm_activities",
            "crm_notes",
            "crm_deals",
            "crm_company_intelligence",
            "crm_reports",
            "crm_outreach_emails",
        }

    def _ensure_sqlite_ready(self) -> None:
        self.sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.sqlite_path.exists():
            initialize_database(self.sqlite_path)
        apply_migrations(self.sqlite_path)
        if self.sqlite_conn is None:
            self.sqlite_conn = sqlite3.connect(self.sqlite_path, timeout=30.0, check_same_thread=False)
            self.sqlite_conn.row_factory = sqlite3.Row
            self.sqlite_conn.execute("PRAGMA foreign_keys = ON")

    def _apply_filters(self, q, filters: dict | None = None):
        if not filters:
            return q
        for key, value in filters.items():
            if isinstance(value, tuple) and len(value) == 2:
                operator, val = value
                if operator == "ilike":
                    q = q.ilike(key, val)
                elif operator == "neq":
                    q = q.neq(key, val)
                elif operator == "gt":
                    q = q.gt(key, val)
                elif operator == "gte":
                    q = q.gte(key, val)
                elif operator == "lt":
                    q = q.lt(key, val)
                elif operator == "lte":
                    q = q.lte(key, val)
                else:
                    q = q.eq(key, val)
            else:
                q = q.eq(key, value)
        return q

    def _should_use_sqlite(self, table: str, exc: Exception | None = None) -> bool:
        if self.client is None:
            return not self._is_supabase_only_table(table)
        if self._is_supabase_only_table(table):
            return False
        if exc is None:
            return False
        message = str(exc).lower()
        return (
            "pgrst205" in message
            or "pgrst100" in message
            or "could not find the table" in message
            or "does not exist" in message
            or "undefinedtable" in message
            or "json could not be generated" in message
            or "json_invalid" in message
            or "failed to parse order" in message
            or "404" in message
            or "unexpected status" in message
            or "unexpected \"a\"" in message
        )

    def _sqlite_where_clause(self, filters: dict | None = None) -> tuple[str, list[Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if not filters:
            return "", params
        for key, value in filters.items():
            if isinstance(value, tuple) and len(value) == 2:
                operator, val = value
                if operator == "ilike":
                    clauses.append(f"{key} LIKE ?")
                    params.append(f"%{val}%")
                elif operator == "neq":
                    clauses.append(f"{key} != ?")
                    params.append(val)
                elif operator == "gt":
                    clauses.append(f"{key} > ?")
                    params.append(val)
                elif operator == "gte":
                    clauses.append(f"{key} >= ?")
                    params.append(val)
                elif operator == "lt":
                    clauses.append(f"{key} < ?")
                    params.append(val)
                elif operator == "lte":
                    clauses.append(f"{key} <= ?")
                    params.append(val)
                else:
                    clauses.append(f"{key} = ?")
                    params.append(val)
            else:
                clauses.append(f"{key} = ?")
                params.append(value)
        return (" AND ".join(clauses), params)

    def _normalize_order(self, order: str | None) -> tuple[str | None, bool | None]:
        if not order:
            return None, None
        order = order.strip()
        if not order:
            return None, None
        if order.endswith(".desc"):
            return order[:-5], True
        if order.endswith(".asc"):
            return order[:-4], False
        if order.lower().endswith(" desc"):
            return order[:-5].strip(), True
        if order.lower().endswith(" asc"):
            return order[:-4].strip(), False
        return order, None

    def _apply_order(self, q, order: str | None):
        if not order:
            return q
        field, descending = self._normalize_order(order)
        if field is None:
            return q
        if descending is None:
            return q.order(field)
        return q.order(field, desc=descending)

    def _sqlite_order_clause(self, order: str | None) -> str:
        if not order:
            return ""
        field = order
        direction = "ASC"
        if field.endswith(".desc"):
            field = field[:-5]
            direction = "DESC"
        elif field.endswith(".asc"):
            field = field[:-4]
            direction = "ASC"
        return f" ORDER BY {field} {direction}"

    def _sqlite_table_columns(self, table: str) -> set[str]:
        if self.sqlite_conn is None:
            self._ensure_sqlite_ready()
        rows = self.sqlite_conn.execute(f"PRAGMA table_info({table})").fetchall()
        return {row[1] for row in rows}

    def _deserialize_sqlite_row(self, table: str, row: sqlite3.Row | dict | None) -> dict:
        if row is None:
            return {}
        result = dict(row) if not isinstance(row, dict) else dict(row)
        for key, value in result.items():
            if isinstance(value, str) and (key.endswith("_json") or key in {"data", "report_data", "search_results_json"}):
                try:
                    result[key] = __import__("json").loads(value)
                except Exception:
                    pass
        return result

    def _normalize_sqlite_payload(self, table: str, payload: dict) -> dict:
        normalized = dict(payload or {})
        if table == "crm_companies" and "company_name" not in normalized and "company" in normalized:
            normalized["company_name"] = normalized["company"]
        if table == "crm_companies" and "company" in normalized:
            normalized.pop("company", None)

        available_columns = self._sqlite_table_columns(table)
        filtered = {}
        for key, value in normalized.items():
            if key not in available_columns:
                continue
            if isinstance(value, (dict, list)):
                try:
                    filtered[key] = __import__("json").dumps(value)
                except Exception:
                    filtered[key] = str(value)
            else:
                filtered[key] = value

        if "updated_at" in available_columns and "updated_at" not in filtered and "created_at" in filtered:
            filtered["updated_at"] = filtered["created_at"]
        return filtered

    def _sqlite_select(self, table: str, filters: dict | None = None, order: str | None = None, limit: int | None = None, offset: int | None = None):
        where_clause, params = self._sqlite_where_clause(filters)
        if where_clause:
            where_clause = f" WHERE {where_clause}"
        sql = f"SELECT * FROM {table}{where_clause}"
        sql += self._sqlite_order_clause(order)
        if limit is not None:
            sql += f" LIMIT {limit}"
        if offset is not None:
            sql += f" OFFSET {offset}"
        cursor = self.sqlite_conn.execute(sql, params)
        return [self._deserialize_sqlite_row(table, row) for row in cursor.fetchall()]

    def _sqlite_count(self, table: str, filters: dict | None = None) -> int:
        where_clause, params = self._sqlite_where_clause(filters)
        if where_clause:
            where_clause = f" WHERE {where_clause}"
        cursor = self.sqlite_conn.execute(f"SELECT COUNT(*) AS count FROM {table}{where_clause}", params)
        row = cursor.fetchone()
        return int(row[0] if row else 0)

    def table_select(
        self,
        table: str,
        filters: dict | None = None,
        order: str | None = None,
        limit: int | None = None,
        offset: int | None = None,
    ):
        if self.client is not None:
            try:
                q = self.client.table(table).select("*")
                q = self._apply_filters(q, filters)
                q = self._apply_order(q, order)
                if limit is not None:
                    q = q.limit(limit)
                if offset is not None:
                    q = q.offset(offset)
                resp = q.execute()
                return resp.data or []
            except Exception as exc:
                if not self._should_use_sqlite(table, exc):
                    raise
        if self._is_supabase_only_table(table):
            raise RuntimeError(f"Supabase is required for CRM table '{table}'")
        return self._sqlite_select(table, filters=filters, order=order, limit=limit, offset=offset)

    def get_by_id(self, table: str, id: Any):
        if self.client is not None:
            try:
                resp = self.client.table(table).select("*").eq("id", id).limit(1).execute()
                data = resp.data or []
                return data[0] if data else None
            except Exception as exc:
                if not self._should_use_sqlite(table, exc):
                    raise
        if self._is_supabase_only_table(table):
            raise RuntimeError(f"Supabase is required for CRM table '{table}'")
        cursor = self.sqlite_conn.execute(f"SELECT * FROM {table} WHERE id = ? LIMIT 1", (id,))
        row = cursor.fetchone()
        return self._deserialize_sqlite_row(table, row) if row is not None else None

    def insert(self, table: str, payload: dict):
        if self.client is not None:
            try:
                resp = self.client.table(table).insert(payload).execute()
                data = resp.data or []
                return data[0] if data else None
            except Exception as exc:
                if not self._should_use_sqlite(table, exc):
                    raise
        if self._is_supabase_only_table(table):
            raise RuntimeError(f"Supabase is required for CRM table '{table}'")
        payload = self._normalize_sqlite_payload(table, payload)
        columns = [key for key in payload.keys()]
        placeholders = ", ".join("?" for _ in columns)
        values = [payload[key] for key in columns]
        cursor = self.sqlite_conn.execute(f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders})", values)
        self.sqlite_conn.commit()
        row_id = cursor.lastrowid
        return self.get_by_id(table, row_id)

    def update(self, table: str, id: Any, payload: dict):
        if self.client is not None:
            try:
                resp = self.client.table(table).update(payload).eq("id", id).execute()
                data = resp.data or []
                return data[0] if data else None
            except Exception as exc:
                if not self._should_use_sqlite(table, exc):
                    raise
        if self._is_supabase_only_table(table):
            raise RuntimeError(f"Supabase is required for CRM table '{table}'")
        payload = self._normalize_sqlite_payload(table, dict(payload))
        payload["updated_at"] = payload.get("updated_at") or payload.get("created_at")
        assignments = ", ".join(f"{key} = ?" for key in payload.keys())
        values = [payload[key] for key in payload.keys()] + [id]
        self.sqlite_conn.execute(f"UPDATE {table} SET {assignments} WHERE id = ?", values)
        self.sqlite_conn.commit()
        return self.get_by_id(table, id)

    def delete(self, table: str, id: Any):
        if self.client is not None:
            try:
                resp = self.client.table(table).delete().eq("id", id).execute()
                return resp
            except Exception as exc:
                if not self._should_use_sqlite(table, exc):
                    raise
        if self._is_supabase_only_table(table):
            raise RuntimeError(f"Supabase is required for CRM table '{table}'")
        self.sqlite_conn.execute(f"DELETE FROM {table} WHERE id = ?", (id,))
        self.sqlite_conn.commit()
        return type("Response", (), {"status_code": 200})()

    def count(self, table: str, filters: dict | None = None) -> int:
        if self.client is not None:
            try:
                q = self.client.table(table).select("id", count="exact", head=True)
                q = self._apply_filters(q, filters)
                resp = q.execute()
                return int(resp.count or 0)
            except Exception as exc:
                if not self._should_use_sqlite(table, exc):
                    raise
        if self._is_supabase_only_table(table):
            raise RuntimeError(f"Supabase is required for CRM table '{table}'")
        return self._sqlite_count(table, filters=filters)

    def upsert(self, table: str, payload: dict, on_conflict: str | None = None):
        if self.client is not None:
            try:
                q = self.client.table(table).upsert(payload, on_conflict=on_conflict or "")
                resp = q.execute()
                data = resp.data or []
                return data[0] if data else None
            except Exception as exc:
                if not self._should_use_sqlite(table, exc):
                    raise
        if self._is_supabase_only_table(table):
            raise RuntimeError(f"Supabase is required for CRM table '{table}'")
        payload = self._normalize_sqlite_payload(table, payload)
        columns = [key for key in payload.keys()]
        values = [payload[key] for key in columns]
        conflict_target = on_conflict or "id"
        assignments = ", ".join(f"{key} = excluded.{key}" for key in columns if key != "id")
        sql = (
            f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)}) "
            f"ON CONFLICT({conflict_target}) DO UPDATE SET {assignments}"
        )
        if not assignments:
            sql = f"INSERT OR REPLACE INTO {table} ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})"
        cursor = self.sqlite_conn.execute(sql, values)
        self.sqlite_conn.commit()
        row_id = cursor.lastrowid
        return self.get_by_id(table, row_id)


# Singleton instance for application use
_DB_INSTANCE: SupabaseDB | None = None


def _current_sqlite_path() -> Path:
    configured = os.getenv("MEDNOVA_DB_PATH") or os.getenv("DATABASE_PATH")
    if configured:
        return Path(configured).expanduser()
    return Path(__file__).resolve().parents[2] / "database" / "nafdac_intelligence.db"


def get_db() -> SupabaseDB:
    global _DB_INSTANCE
    current_path = _current_sqlite_path()
    if _DB_INSTANCE is None or _DB_INSTANCE.sqlite_path != current_path:
        _DB_INSTANCE = SupabaseDB()
    return _DB_INSTANCE
