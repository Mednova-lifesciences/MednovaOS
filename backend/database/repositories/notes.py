from __future__ import annotations

from backend.database.repositories.base import BaseRepository
from backend.models import Report


class NoteRepository(BaseRepository[dict]):
    table_name = "crm_notes"
    model_class = None
    search_fields = ["body"]


__all__ = ["NoteRepository"]
