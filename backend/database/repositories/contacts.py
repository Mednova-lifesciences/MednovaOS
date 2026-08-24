from __future__ import annotations

from typing import Any

from backend.database.repositories.base import BaseRepository
from backend.models import Contact


class ContactRepository(BaseRepository[Contact]):
    table_name = "crm_contacts"
    model_class = Contact
    search_fields = ["full_name", "role", "department", "email", "phone", "source"]


__all__ = ["ContactRepository"]
