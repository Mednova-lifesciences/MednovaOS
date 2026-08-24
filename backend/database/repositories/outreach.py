from __future__ import annotations

from typing import Any

from backend.database.repositories.base import BaseRepository
from backend.models import OutreachEmail


class OutreachRepository(BaseRepository[OutreachEmail]):
    table_name = "crm_outreach_emails"
    model_class = OutreachEmail
    search_fields = ["subject", "body", "status"]


__all__ = ["OutreachRepository"]
