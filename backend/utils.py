from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Generic, Iterable, List, Optional, TypeVar

T = TypeVar("T")


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def ensure_dict(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return value
    if hasattr(value, "dict"):
        return value.dict()
    if hasattr(value, "to_dict"):
        return value.to_dict()
    return {"value": value}


@dataclass
class PaginationResult(Generic[T]):
    items: List[T]
    total: int
    page: int
    per_page: int
    pages: int


def paginate_list(items: Iterable[T], page: int = 1, per_page: int = 20, total: int | None = None) -> PaginationResult[T]:
    page = max(1, page)
    per_page = max(1, per_page)
    items_list = list(items)
    total_count = total if total is not None else len(items_list)
    start = (page - 1) * per_page
    end = start + per_page
    return PaginationResult(
        items=items_list[start:end],
        total=total_count,
        page=page,
        per_page=per_page,
        pages=max(1, (total_count + per_page - 1) // per_page),
    )


def build_filters(filters: dict | None = None) -> dict:
    return {k: v for k, v in (filters or {}).items() if v is not None}


def format_response(data: Any = None, success: bool = True, message: str | None = None) -> dict:
    response: dict[str, Any] = {"success": success}
    if message is not None:
        response["message"] = message
    if data is not None:
        response["data"] = data
    return response
