from __future__ import annotations

import os
from typing import Any

from supabase import create_client


def get_supabase_client():
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set in the environment")
    return create_client(url, key)


class SupabaseDB:
    def __init__(self):
        self.client = get_supabase_client()

    def table_select(self, table: str, filters: dict | None = None, order: str | None = None, limit: int | None = None):
        q = self.client.table(table).select("*")
        if filters:
            for k, v in filters.items():
                # simple equality filter
                q = q.eq(k, v)
        if order:
            # PostgREST ordering: e.g. "created_at.desc"
            q = q.order(order)
        if limit:
            q = q.limit(limit)
        resp = q.execute()
        return resp.data or []

    def get_by_id(self, table: str, id: Any):
        resp = self.client.table(table).select("*").eq("id", id).limit(1).execute()
        data = resp.data or []
        return data[0] if data else None

    def insert(self, table: str, payload: dict):
        resp = self.client.table(table).insert(payload).execute()
        data = resp.data or []
        return data[0] if data else None

    def update(self, table: str, id: Any, payload: dict):
        resp = self.client.table(table).update(payload).eq("id", id).execute()
        data = resp.data or []
        return data[0] if data else None

    def delete(self, table: str, id: Any):
        resp = self.client.table(table).delete().eq("id", id).execute()
        return resp
