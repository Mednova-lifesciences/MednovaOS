from __future__ import annotations

from typing import Any, Optional

from backend.database.repositories import TaskRepository, ActivityRepository
from backend.logging_utils import get_logger
from backend.models import Task
from backend.utils import now_iso

logger = get_logger("task_service")


class TaskService:
    def __init__(self, task_repo: Optional[TaskRepository] = None, activity_repo: Optional[ActivityRepository] = None):
        self.task_repo = task_repo or TaskRepository()
        self.activity_repo = activity_repo or ActivityRepository()

    def get_task(self, task_id: int) -> Task | None:
        return self.task_repo.get_by_id(task_id)

    def list_tasks(self, company_id: int | None = None, page: int = 1, per_page: int = 20) -> dict:
        filters = {"crm_company_id": company_id} if company_id else None
        result = self.task_repo.paginate(page=page, per_page=per_page, filters=filters, order="due_date.asc")
        return {
            "items": result.items,
            "total": result.total,
            "page": result.page,
            "per_page": result.per_page,
            "pages": result.pages,
        }

    def search_tasks(self, query: str, page: int = 1, per_page: int = 20) -> dict:
        results = self.task_repo.search(query, order="due_date.asc")
        paginated = results[(page - 1) * per_page : page * per_page]
        return {
            "items": paginated,
            "total": len(results),
            "page": page,
            "per_page": per_page,
            "pages": max(1, (len(results) + per_page - 1) // per_page),
        }

    def create_task(self, company_id: int, payload: dict[str, Any]) -> Task | dict:
        logger.info("Creating task for company: id=%s", company_id)
        payload["crm_company_id"] = company_id
        payload["created_at"] = now_iso()
        task = self.task_repo.create(payload)

        if isinstance(task, dict):
            task_title = task.get("title", "Unknown")
        else:
            task_title = task.title

        self.activity_repo.create({
            "crm_company_id": company_id,
            "activity_type": "task",
            "title": "Task assigned",
            "body": f"Assigned task: {task_title}",
            "created_at": now_iso(),
        })

        return task

    def update_task(self, task_id: int, payload: dict[str, Any]) -> Task | dict:
        logger.info("Updating task: id=%s", task_id)
        payload["updated_at"] = now_iso()
        return self.task_repo.update(task_id, payload)

    def delete_task(self, task_id: int, company_id: int) -> bool:
        logger.info("Deleting task: id=%s for company_id=%s", task_id, company_id)
        task = self.get_task(task_id)
        if not task:
            raise LookupError("task not found")

        task_company_id = task.crm_company_id if hasattr(task, "crm_company_id") else task.get("crm_company_id")
        if int(task_company_id or 0) != int(company_id):
            raise LookupError("task not found")

        return self.task_repo.delete(task_id)

    def complete_task(self, task_id: int, company_id: int) -> Task | dict:
        logger.info("Completing task: id=%s for company_id=%s", task_id, company_id)
        task = self.get_task(task_id)
        if not task:
            raise LookupError("task not found")

        task_company_id = task.crm_company_id if hasattr(task, "crm_company_id") else task.get("crm_company_id")
        if int(task_company_id or 0) != int(company_id):
            raise LookupError("task not found")

        now = now_iso()
        updated_task = self.task_repo.update(task_id, {
            "status": "completed",
            "completed_at": now,
            "updated_at": now,
        })

        task_title = updated_task.get("title", "Unknown") if isinstance(updated_task, dict) else updated_task.title

        self.activity_repo.create({
            "crm_company_id": company_id,
            "activity_type": "task",
            "title": "Task completed",
            "body": f"Completed task: {task_title}",
            "created_at": now,
        })

        return updated_task
