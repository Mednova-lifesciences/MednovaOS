from __future__ import annotations

from typing import Any

from backend.database.repositories.base import BaseRepository
from backend.models import Deal


class DealRepository(BaseRepository[Deal]):
    table_name = "crm_deals"
    model_class = Deal
    search_fields = ["title", "stage", "status"]


__all__ = ["DealRepository"]
