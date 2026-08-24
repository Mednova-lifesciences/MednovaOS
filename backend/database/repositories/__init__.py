from backend.database.repositories.activities import ActivityRepository
from backend.database.repositories.companies import CompanyRepository
from backend.database.repositories.contacts import ContactRepository
from backend.database.repositories.deals import DealRepository
from backend.database.repositories.intelligence import IntelligenceRepository
from backend.database.repositories.notes import NoteRepository
from backend.database.repositories.outreach import OutreachRepository
from backend.database.repositories.pipeline import PipelineRepository
from backend.database.repositories.products import ProductRepository
from backend.database.repositories.reports import ReportRepository
from backend.database.repositories.settings import SettingRepository
from backend.database.repositories.tasks import TaskRepository

__all__ = [
    "ActivityRepository",
    "CompanyRepository",
    "ContactRepository",
    "DealRepository",
    "IntelligenceRepository",
    "NoteRepository",
    "OutreachRepository",
    "PipelineRepository",
    "ProductRepository",
    "ReportRepository",
    "SettingRepository",
    "TaskRepository",
]
