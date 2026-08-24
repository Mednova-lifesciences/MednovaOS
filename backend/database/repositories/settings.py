from __future__ import annotations

from typing import Any

from backend.database.repositories.base import BaseRepository
from backend.models import Setting


class SettingRepository(BaseRepository[Setting]):
    table_name = "settings"
    model_class = Setting
    search_fields = ["key", "value"]


__all__ = ["SettingRepository"]
