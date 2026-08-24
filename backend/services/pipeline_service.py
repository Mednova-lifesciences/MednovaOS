from __future__ import annotations

from typing import Any, Optional

from backend.database.repositories import DealRepository, PipelineRepository
from backend.logging_utils import get_logger
from backend.models import Deal
from backend.utils import now_iso

logger = get_logger("pipeline_service")


class PipelineService:
    def __init__(self, deal_repo: Optional[DealRepository] = None, pipeline_repo: Optional[PipelineRepository] = None):
        self.deal_repo = deal_repo or DealRepository()
        self.pipeline_repo = pipeline_repo or PipelineRepository()

    def list_deals(self, company_id: int | None = None, page: int = 1, per_page: int = 20) -> dict:
        filters = {"crm_company_id": company_id} if company_id else None
        result = self.deal_repo.paginate(page=page, per_page=per_page, filters=filters, order="created_at.desc")
        return {
            "items": result.items,
            "total": result.total,
            "page": result.page,
            "per_page": result.per_page,
            "pages": result.pages,
        }

    def create_deal(self, company_id: int, payload: dict[str, Any]) -> Deal | dict:
        logger.info("Creating deal for company: id=%s", company_id)
        payload["crm_company_id"] = company_id
        payload["created_at"] = now_iso()
        return self.deal_repo.create(payload)

    def update_deal(self, deal_id: int, payload: dict[str, Any]) -> Deal | dict:
        logger.info("Updating deal: id=%s", deal_id)
        payload["updated_at"] = now_iso()
        return self.deal_repo.update(deal_id, payload)

    def delete_deal(self, deal_id: int) -> bool:
        logger.info("Deleting deal: id=%s", deal_id)
        return self.deal_repo.delete(deal_id)

    def list_pipeline(self, page: int = 1, per_page: int = 20) -> dict:
        result = self.pipeline_repo.paginate(page=page, per_page=per_page, order="updated_at.desc")
        return {
            "items": result.items,
            "total": result.total,
            "page": result.page,
            "per_page": result.per_page,
            "pages": result.pages,
        }
