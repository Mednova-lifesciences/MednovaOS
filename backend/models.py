from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional


@dataclass
class Company:
    id: Optional[int] = None
    company_name: str = ""
    country: str = ""
    opportunity_score: int = 0
    portfolio_summary: str = ""
    source: str = ""
    registration_numbers: str = ""
    dosage_forms: str = ""
    therapeutic_areas: str = ""
    registration_dates: str = ""
    opportunity_status: Optional[str] = None
    pipeline_stage: Optional[str] = None
    report_context: Optional[str] = None
    greenbook_products_json: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


@dataclass
class Contact:
    id: Optional[int] = None
    crm_company_id: Optional[int] = None
    full_name: str = ""
    role: str = ""
    department: str = ""
    email: str = ""
    phone: str = ""
    source: str = ""
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


@dataclass
class Task:
    id: Optional[int] = None
    crm_company_id: Optional[int] = None
    title: str = ""
    description: str = ""
    task_type: str = ""
    status: str = ""
    priority: str = ""
    due_date: Optional[str] = None
    assigned_to: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    completed_at: Optional[str] = None


@dataclass
class Deal:
    id: Optional[int] = None
    crm_company_id: Optional[int] = None
    title: str = ""
    amount: Optional[float] = None
    stage: Optional[str] = None
    status: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


@dataclass
class Report:
    id: Optional[int] = None
    crm_company_id: Optional[int] = None
    report_type: str = ""
    report_name: str = ""
    report_data: Optional[Dict[str, Any]] = field(default_factory=dict)
    executive_summary: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


@dataclass
class Intelligence:
    id: Optional[int] = None
    crm_company_id: Optional[int] = None
    data: Optional[Dict[str, Any]] = field(default_factory=dict)
    search_results_json: Optional[str] = None
    search_date: Optional[str] = None
    search_status: Optional[str] = None
    last_refresh: Optional[str] = None
    source_summary: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


@dataclass
class OutreachEmail:
    id: Optional[int] = None
    crm_company_id: Optional[int] = None
    crm_contact_id: Optional[int] = None
    template_key: str = ""
    template_name: str = ""
    subject: str = ""
    body: str = ""
    recipient: str = ""
    recipient_name: str = ""
    sender_name: str = ""
    sender_email: str = ""
    from_email: str = ""
    company_name: str = ""
    contact_name: str = ""
    status: str = ""
    message_id: str = ""
    error_message: str = ""
    client_request_id: str = ""
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    sent_at: Optional[str] = None


@dataclass
class Setting:
    id: Optional[int] = None
    key: str = ""
    value: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
