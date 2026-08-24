from __future__ import annotations

from typing import Any, Optional

from backend.database.repositories import (
    CompanyRepository,
    ContactRepository,
    TaskRepository,
    ActivityRepository,
    NoteRepository,
    DealRepository,
)
from backend.logging_utils import get_logger
from backend.models import Company
from backend.services.company_service import CompanyService
from backend.services.contact_service import ContactService
from backend.services.task_service import TaskService
from backend.utils import now_iso
from difflib import SequenceMatcher
import re

logger = get_logger("crm_service")


class CRMService:
    """Orchestrator service for CRM operations."""

    def __init__(
        self,
        company_repo: Optional[CompanyRepository] = None,
        contact_repo: Optional[ContactRepository] = None,
        task_repo: Optional[TaskRepository] = None,
        activity_repo: Optional[ActivityRepository] = None,
        note_repo: Optional[NoteRepository] = None,
        deal_repo: Optional[DealRepository] = None,
    ):
        self.company_service = CompanyService(company_repo, contact_repo, task_repo, activity_repo, note_repo)
        self.contact_service = ContactService(contact_repo, activity_repo)
        self.task_service = TaskService(task_repo, activity_repo)

    _GENERIC_COMPANY_TERMS = {
        "limited",
        "ltd",
        "plc",
        "company",
        "co",
        "inc",
        "corporation",
        "corp",
        "laboratories",
        "laboratory",
        "labs",
        "industries",
        "industry",
        "services",
        "service",
        "group",
        "international",
        "nigeria",
        "africa",
        "products",
        "solutions",
        "medical",
        "research",
        "systems",
    }

    _NORMALIZED_COMPANY_TOKEN_EQUIVALENTS = {
        "pharma": "pharmaceutical",
        "pharmaceuticals": "pharmaceutical",
        "co": "company",
        "corp": "corporation",
        "ltd": "limited",
        "intl": "international",
        "int": "international",
        "healthcare": "health care",
    }

    def _normalize_company_name(self, company_name: str) -> str:
        normalized = re.sub(r"[^a-z0-9]+", " ", (company_name or "").lower()).strip()
        normalized = normalized.replace("healthcare", "health care")
        tokens = []
        for token in normalized.split():
            if not token:
                continue
            token = self._NORMALIZED_COMPANY_TOKEN_EQUIVALENTS.get(token, token)
            if token in self._GENERIC_COMPANY_TERMS:
                continue
            tokens.append(token)
        return " ".join(tokens)

    def _company_name_similarity(self, source: str, candidate: str) -> float:
        source_tokens = source.split()
        candidate_tokens = candidate.split()
        source_set = set(source_tokens)
        candidate_set = set(candidate_tokens)

        if source_set == candidate_set:
            return 1.0

        common_tokens = source_set & candidate_set
        overlap_score = len(common_tokens) / max(1, max(len(source_set), len(candidate_set)))
        ratio_score = SequenceMatcher(None, source, candidate).ratio()
        return max(overlap_score, ratio_score)

    def _is_fuzzy_company_match(self, source: str, candidate: str) -> bool:
        if not source or not candidate:
            return False

        normalized_source = self._normalize_company_name(source)
        normalized_candidate = self._normalize_company_name(candidate)
        if not normalized_source or not normalized_candidate:
            return False

        if normalized_source == normalized_candidate:
            return True

        source_tokens = normalized_source.split()
        candidate_tokens = normalized_candidate.split()
        if not source_tokens or not candidate_tokens:
            return False

        source_set = set(source_tokens)
        candidate_set = set(candidate_tokens)
        common_tokens = source_set & candidate_set
        if not common_tokens:
            return False

        if source_set == candidate_set:
            return True

        if len(common_tokens) >= 2:
            return True

        if len(source_tokens) == 1 and len(candidate_tokens) == 1:
            return common_tokens == source_set

        similarity = self._company_name_similarity(normalized_source, normalized_candidate)
        return similarity >= 0.85

    def _find_existing_company(self, company_name: str) -> Company | dict | None:
        if not company_name:
            return None

        exact_matches = self.company_service.company_repo.list(filters={"company_name": company_name}, limit=1)
        if exact_matches:
            return exact_matches[0]

        fuzzy_matches = self.company_service.company_repo.list(filters={"company_name": ("ilike", company_name)}, limit=1)
        if fuzzy_matches:
            return fuzzy_matches[0]

        normalized_query = self._normalize_company_name(company_name)
        if not normalized_query:
            return None

        all_companies = self.company_service.company_repo.list(limit=2000)
        best_match = None
        best_score = 0.0
        query_tokens = normalized_query.split()
        for existing in all_companies:
            existing_name = existing.company_name if hasattr(existing, "company_name") else existing.get("company_name")
            existing_normalized = self._normalize_company_name(existing_name)
            if not existing_normalized:
                continue

            if normalized_query == existing_normalized:
                return existing

            if self._is_fuzzy_company_match(company_name, existing_name):
                score = self._company_name_similarity(normalized_query, existing_normalized)
                if score > best_score:
                    best_score = score
                    best_match = existing

        if best_match and best_score >= 0.85:
            return best_match

        return None

    def create_company_from_payload(self, payload: dict[str, Any]) -> tuple[int, dict, bool]:
        """
        Create a company from a payload (for Green Book sync compatibility).
        Returns (company_id, company_dict, created).
        """
        normalized_payload = dict(payload or {})
        if not normalized_payload.get("company_name") and normalized_payload.get("company"):
            normalized_payload["company_name"] = normalized_payload["company"]

        logger.info("Creating company from payload: %s", normalized_payload.get("company_name"))
        company_name = (normalized_payload.get("company_name") or "").strip()
        if not company_name:
            raise ValueError("company_name is required")

        existing = self._find_existing_company(company_name)
        if existing:
            company_id = existing.id if hasattr(existing, "id") else existing.get("id")
            company_dict = existing if isinstance(existing, dict) else vars(existing)

            # Update existing CRM company with any new intelligence or opportunity metadata from the payload.
            updates = {
                key: value
                for key, value in normalized_payload.items()
                if key in {
                    "country",
                    "opportunity_score",
                    "portfolio_summary",
                    "source",
                    "greenbook_products_json",
                    "registration_numbers",
                    "dosage_forms",
                    "therapeutic_areas",
                    "registration_dates",
                    "opportunity_status",
                    "pipeline_stage",
                }
                and value not in (None, "")
            }
            if updates:
                try:
                    self.company_service.update_company(company_id, updates)
                    existing_updated = self.company_service.get_company(company_id)
                    company_dict = existing_updated if isinstance(existing_updated, dict) else vars(existing_updated)
                except Exception:
                    pass

            return company_id, company_dict, False

        company = self.company_service.create_company(normalized_payload)
        company_id = company.get("id") if isinstance(company, dict) else company.id
        company_dict = company if isinstance(company, dict) else vars(company)

        return company_id, company_dict, True

    def add_activity(self, company_id: int, activity_type: str, title: str, body: str) -> int:
        """Add activity (backward-compatible wrapper)."""
        activity = self.company_service.add_activity(company_id, activity_type, title, body)
        return activity.get("id") if isinstance(activity, dict) else activity.id

    def add_note(self, company_id: int, body: str) -> int:
        """Add note (backward-compatible wrapper)."""
        note = self.company_service.add_note(company_id, body)
        return note.get("id") if isinstance(note, dict) else note.id

    def create_contact(self, company_id: int, contact_data: dict[str, Any]) -> int:
        """Create contact (backward-compatible wrapper)."""
        contact = self.contact_service.create_contact(company_id, contact_data)
        return contact.get("id") if isinstance(contact, dict) else contact.id

    def create_task(self, company_id: int, task_data: dict[str, Any]) -> int:
        """Create task (backward-compatible wrapper)."""
        task = self.task_service.create_task(company_id, task_data)
        return task.get("id") if isinstance(task, dict) else task.id

    def complete_task(self, company_id: int, task_id: int):
        """Complete task (backward-compatible wrapper)."""
        return self.task_service.complete_task(task_id, company_id)

