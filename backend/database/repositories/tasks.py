from __future__ import annotations

from typing import Any

from backend.database.repositories.base import BaseRepository
from backend.models import Task


class TaskRepository(BaseRepository[Task]):
    table_name = "crm_tasks"
    model_class = Task
    search_fields = ["title", "description", "task_type", "status", "priority", "assigned_to"]


__all__ = ["TaskRepository"]
