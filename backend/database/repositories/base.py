from __future__ import annotations

from dataclasses import is_dataclass, fields
from typing import Any, Generic, Iterable, List, Optional, TypeVar

from backend.database.db import SupabaseDB, get_db
from backend.utils import PaginationResult, paginate_list

T = TypeVar("T")


class BaseRepository(Generic[T]):
    table_name: str = ""
    model_class: type[T] | None = None
    search_fields: list[str] = []

    def __init__(self, db: SupabaseDB | None = None) -> None:
        self.db = db or get_db()
        if not self.table_name:
            raise ValueError("Repository must set table_name")

    def _row_to_model(self, row: dict | None) -> T | dict | None:
        if row is None:
            return None
        if self.model_class is None:
            return row
        if is_dataclass(self.model_class):
            field_names = {field.name for field in fields(self.model_class)}
            filtered = {k: v for k, v in row.items() if k in field_names}
            return self.model_class(**filtered)  # type: ignore[arg-type]
        return self.model_class(**row)  # type: ignore[call-arg]

    def get_by_id(self, entity_id: Any) -> T | None:
        row = self.db.get_by_id(self.table_name, entity_id)
        return self._row_to_model(row)

    def list(
        self,
        filters: dict | None = None,
        order: str | None = None,
        limit: int | None = None,
        offset: int | None = None,
    ) -> list[T]:
        rows = self.db.table_select(
            self.table_name,
            filters=filters,
            order=order,
            limit=limit,
            offset=offset,
        )
        return [self._row_to_model(row) for row in rows]

    def create(self, payload: dict[str, Any]) -> T | dict:
        row = self.db.insert(self.table_name, payload)
        return self._row_to_model(row)

    def update(self, entity_id: Any, payload: dict[str, Any]) -> T | dict:
        row = self.db.update(self.table_name, entity_id, payload)
        return self._row_to_model(row)

    def delete(self, entity_id: Any) -> bool:
        response = self.db.delete(self.table_name, entity_id)
        return getattr(response, "status_code", 0) in {200, 204}

    def exists(self, filters: dict | None = None) -> bool:
        return bool(self.db.count(self.table_name, filters=filters))

    def search(
        self,
        query: str,
        filters: dict | None = None,
        order: str | None = None,
        limit: int | None = None,
        offset: int | None = None,
    ) -> list[T]:
        if not query or not self.search_fields:
            return self.list(filters=filters, order=order, limit=limit, offset=offset)

        found: list[T] = []
        seen_ids: set[Any] = set()
        for field in self.search_fields:
            field_filters = dict(filters or {})
            field_filters[field] = ("ilike", f"%{query}%")
            rows = self.db.table_select(
                self.table_name,
                filters=field_filters,
                order=order,
                limit=limit,
                offset=offset,
            )
            for row in rows:
                entity = self._row_to_model(row)
                entity_id = getattr(entity, "id", None) if hasattr(entity, "id") else row.get("id")
                if entity_id not in seen_ids:
                    seen_ids.add(entity_id)
                    found.append(entity)
        return found

    def upsert(self, payload: dict[str, Any], on_conflict: str | None = None) -> T | dict:
        row = self.db.upsert(self.table_name, payload, on_conflict=on_conflict)
        return self._row_to_model(row)

    def paginate(
        self,
        page: int = 1,
        per_page: int = 20,
        filters: dict | None = None,
        order: str | None = None,
    ) -> PaginationResult[T]:
        total = self.db.count(self.table_name, filters=filters)
        offset = (max(page, 1) - 1) * per_page
        items = self.list(filters=filters, order=order, limit=per_page, offset=offset)
        return paginate_list(items, page, per_page, total=total)
