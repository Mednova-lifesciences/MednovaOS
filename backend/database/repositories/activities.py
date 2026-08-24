from __future__ import annotations

from backend.database.repositories.base import BaseRepository
from backend.models import Intelligence


class ActivityRepository(BaseRepository[dict]):
    table_name = "crm_activities"
    model_class = None
    search_fields = ["title", "body", "activity_type"]


__all__ = ["ActivityRepository"]
