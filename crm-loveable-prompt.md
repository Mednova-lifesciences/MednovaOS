# MedNovaOS Rebuild Specification for CRM and Regulatory Intelligence

## 1. Product Purpose

This repository is a hybrid product that combines a legacy regulatory-intelligence workflow with a newer CRM/workflow layer. The goal of the product is to help MedNova Lifesciences monitor regulatory and commercial opportunities, discover companies, enrich them with intelligence, and manage commercial follow-up through a CRM workspace.

The implementation should be treated as a single operating system with two major subsystems:

1. Legacy regulatory intelligence and product discovery
2. A newer CRM layer for business development operations

The CRM is not a disconnected standalone app. It is intended to be the operational layer that sits on top of the intelligence, product, and opportunity data already present in the system.

## 2. Product Scope

The rebuilt application must support the following user-facing capabilities:

- Browse products, manufacturers, applicants, regulatory opportunities, and renewal signals
- Create and maintain CRM companies from discovered opportunities
- Manage company-level contacts, tasks, activities, notes, deals, and outreach emails
- Generate and persist company-level and operations-level reports
- Run intelligence enrichment using website analysis and Tavily search
- Send outreach drafts and emails through an email provider integration
- Expose dashboard metrics and company/portfolio analytics
- Support both local development via SQLite and production-style Supabase-backed persistence

## 3. High-Level Architecture

### 3.1 Backend

The backend is a Flask application served from app.py. It should remain the central server layer and host route handlers for legacy pages, CRM API routes, health endpoints, and admin/sync endpoints.

The backend should be structured around:

- Flask route handlers in app.py
- Service objects under backend/services
- Repository abstractions under backend/database/repositories
- A database abstraction layer under backend/database/db.py
- Typed domain models under backend/models.py
- Shared utilities under backend/utils.py and backend/logging_utils.py

### 3.2 Frontend

The frontend is a React + TypeScript application under mednova-grow-hub. It uses TanStack Router, React Query, Tailwind CSS, and a shadcn-style component system. The UI should be implemented as a CRM workspace that feels integrated with the platform rather than bolted on.

### 3.3 Data layer

The application should support dual persistence semantics:

- Supabase PostgreSQL for production or cloud-backed environments
- SQLite fallback for local development and compatibility

The production design intent is to use PostgreSQL-backed tables for CRM entities. The current codebase already uses a database abstraction layer to abstract this away.

## 4. Core Business Workflow

The canonical workflow is:

1. Discover or ingest a company or opportunity from legacy product/regulatory data
2. Create or enrich a CRM company record
3. Generate intelligence for the company
4. Create contacts, tasks, notes, and deals
5. Draft/send outreach emails
6. Persist activities and reports
7. Track outcome through the pipeline

The expected user flow is:

- Green Book or regulatory intelligence produces a company/opportunity context
- The user adds the company to CRM
- CRM company appears immediately with intelligence data
- Business development follows up with outreach, meetings, tasks, and pipeline updates
- Reports and dashboards summarize the progress

## 5. Module Specifications

### 5.1 Dashboard

Purpose:

- Give a high-level operational overview of the CRM and pipeline

Required view elements:

- KPI cards for companies added, leads, active opportunities, won clients, tasks due, meetings scheduled, pipeline value
- Recent activity or timeline-style overview
- Summary of pending follow-up and upcoming deadlines

Required data sources:

- Company count
- Deal count by stage
- Task count by completion and due-date status
- Summary metrics from the API envelope or service layer

### 5.2 Companies

Purpose:

- Provide the main company inventory for CRM users

Expected behavior:

- List companies with searchable, filterable, sortable rows
- Display company name, country, opportunity score, status, portfolio summary, last activity, and next follow-up
- Open a company detail route for deeper interaction

Required data fields:

- id
- company_name
- country
- opportunity_score
- portfolio_summary
- source
- opportunity_status
- pipeline_stage
- report_context
- registration_numbers
- dosage_forms
- therapeutic_areas
- registration_dates
- created_at
- updated_at

### 5.3 Company Profile

Purpose:

- Act as the primary workspace for each company relationship

Required sections:

- Company information
- Intelligence summary
- Opportunity score and portfolio summary
- Contacts
- Activities
- Tasks
- Notes
- Deals/pipeline
- Emails/outreach history
- Reports
- Timeline

Required interactions:

- Add contacts
- Add tasks
- Add notes
- Create deals
- Generate reports
- Launch email draft/send flows
- Refresh intelligence

### 5.4 Contacts

Purpose:

- Manage the people associated with each company

Required fields:

- full_name
- role
- department
- email
- phone
- linkedin_url
- website
- source
- source_url
- confidence_score
- verification_status

Expected features:

- Manual contact creation
- Contact discovery from public web sources via Tavily and web scraping
- Contact enrichment and placeholder cleanup
- Display of discovered source attribution

### 5.5 Activities

Purpose:

- Maintain a timeline of company events

Activity types expected by the current implementation:

- company
- contact
- task
- email
- deal
- research
- note
- pipeline

Activities should be generated automatically when:

- company is created
- contact is added
- task is created or completed
- deal is created or moved
- email is drafted, sent, or failed
- note is created
- intelligence is refreshed

### 5.6 Tasks

Purpose:

- Track follow-up actions and obligations

Required fields:

- title
- task_type
- description
- status
- priority
- due_date
- assigned_to
- completed_at

Supported task types:

- follow-up
- call
- meeting
- deadline
- proposal

Expected actions:

- create
- edit
- complete
- reopen
- delete

### 5.7 Notes

Purpose:

- Capture internal notes for company context

Required fields:

- body
- created_at
- author or system metadata

Expected behavior:

- Notes should be company-scoped
- Each new note should also create an activity timeline entry

### 5.8 Deals and Pipeline

Purpose:

- Track commercial opportunity progression

Required stages:

- lead
- qualified
- contacted
- meeting
- proposal
- negotiation
- won
- lost

Required fields:

- title
- stage
- value
- currency
- probability
- expected_close_at
- owner
- description
- crm_contact_id

Expected behavior:

- Create and update deals
- Move deals between stages
- Record deal lifecycle events as activities
- Support a kanban-style board or table-based pipeline view

### 5.9 Outreach and Emails

Purpose:

- Support personalized outbound communication to CRM contacts

Required capabilities:

- Compose email drafts from templates
- Pre-fill recipient, sender, and company context
- Save drafts
- Send emails
- Persist sent and failed messages
- Display email history

Required data fields:

- crm_company_id
- crm_contact_id
- template_key
- template_name
- subject
- body
- recipient
- recipient_name
- sender_name
- sender_email
- from_email
- company_name
- contact_name
- status
- message_id
- error_message
- sent_at

Expected statuses:

- draft
- sent
- failed

Template behavior:

- The system should support multiple templates such as introduction, follow-up, proposal, and meeting invitation
- Templates should be selected by a key and rendered with company context

### 5.10 Reports

Purpose:

- Generate executive summaries and operating reports

Report types:

- company report
- operations report

Required outputs:

- Executive summary text
- Recommended services or actions
- Opportunity assessment
- Risk assessment
- Action plan
- Export to markdown, docx, or pdf-like text content

Expected behavior:

- Save generated reports to the persistence layer
- List report history per company and globally
- Make report content visible in the UI

### 5.11 Intelligence

Purpose:

- Enrich companies with external context and give commercial insight

Required inputs:

- company name
- country
- website
- contact data
- existing CRM signals

Required outputs:

- company profile summary
- services or potential areas of commercial relevance
- Tavily results and insights
- website analysis signals
- business opportunity score and explanation
- cache metadata and refresh status

Expected behavior:

- Search the web for company-specific information
- Use website content to infer capabilities and relevant services
- Store intelligence in a separate CRM intelligence record
- Allow manual refresh

## 6. Data Model Requirements

### 6.1 CRM company record

Represent each CRM company with the following semantic fields:

- company_name
- country
- opportunity_score
- portfolio_summary
- source
- registration_numbers
- dosage_forms
- therapeutic_areas
- registration_dates
- opportunity_status
- pipeline_stage
- report_context
- greenbook_products_json
- created_at
- updated_at

### 6.2 Contact record

- crm_company_id
- full_name
- role
- department
- email
- phone
- source
- source_url
- linkedin_url
- website
- created_at
- updated_at

### 6.3 Task record

- crm_company_id
- title
- description
- task_type
- status
- priority
- due_date
- assigned_to
- created_at
- updated_at
- completed_at

### 6.4 Deal record

- crm_company_id
- crm_contact_id
- title
- stage
- value
- currency
- probability
- expected_close_at
- owner
- description
- created_at
- updated_at

### 6.5 Activity record

- crm_company_id
- activity_type
- title
- body
- created_at
- updated_at

### 6.6 Note record

- crm_company_id
- body
- created_at
- updated_at

### 6.7 Report record

- crm_company_id
- report_type
- report_name
- report_data
- executive_summary
- created_at
- updated_at

### 6.8 Outreach record

- crm_company_id
- crm_contact_id
- template_key
- template_name
- subject
- body
- recipient
- recipient_name
- sender_name
- sender_email
- from_email
- company_name
- contact_name
- status
- message_id
- error_message
- client_request_id
- sent_at
- created_at
- updated_at

## 7. Database Schema and Persistence Requirements

The application uses a hybrid data layer that should be preserved in the rebuild. The expected tables include the legacy product/regulatory tables plus CRM-specific tables.

### 7.1 Legacy tables

The base schema should continue to support:

- manufacturers
- applicants
- products
- ingredients
- categories
- dosage forms
- routes
- renewal alerts
- opportunities
- sync history
- product changes
- watchlist
- search cache

### 7.2 CRM tables

The CRM implementation should use:

- crm_companies
- crm_contacts
- crm_tasks
- crm_activities
- crm_notes
- crm_deals
- crm_company_intelligence
- crm_reports
- crm_outreach_emails

### 7.3 Storage behavior

- CRM tables should be available through the repository layer even when Supabase is unavailable
- The system should support fallback to SQLite for local runs
- JSON payloads such as report_data and search_results_json should be stored as JSON text or JSON-compatible payloads depending on the storage engine
- Migrations should be applied in a deterministic order

## 8. API Surface

The rebuilt application should preserve or reimplement the following routes.

### 8.1 Core CRM routes

- GET /api/growhub/crm/companies
- GET /api/growhub/crm/data
- GET /api/crm/companies/<company_id>
- GET /crm/companies/<company_id>
- POST /api/crm/companies/from-opportunity
- PATCH /api/crm/companies/<company_id>/pipeline-stage
- POST /api/crm/companies/<company_id>/contacts/discover

### 8.2 Contact, task, note routes

- POST /api/crm/companies/<company_id>/contacts
- POST /api/crm/companies/<company_id>/tasks
- POST /api/crm/companies/<company_id>/notes
- POST /api/crm/companies/<company_id>/tasks/<task_id>/complete
- PATCH /api/crm/companies/<company_id>/tasks/<task_id>
- DELETE /api/crm/companies/<company_id>/tasks/<task_id>

### 8.3 Intelligence and report routes

- GET /api/crm/companies/<company_id>/intelligence
- POST /api/crm/companies/<company_id>/intelligence/refresh
- POST /api/crm/companies/<company_id>/reports/generate
- GET /api/crm/companies/<company_id>/reports
- POST /api/reports/operations/generate
- GET /api/reports
- GET /api/reports/<report_id>
- POST /api/reports/<report_id>/export

### 8.4 Deal routes

- POST /api/crm/companies/<company_id>/deals
- PATCH /api/crm/companies/<company_id>/deals/<deal_id>
- DELETE /api/crm/companies/<company_id>/deals/<deal_id>

### 8.5 Outreach routes

- GET /api/outreach/status
- GET /api/crm/outreach/templates
- POST /api/crm/companies/<company_id>/outreach/build
- POST /api/crm/companies/<company_id>/outreach/drafts
- POST /api/crm/companies/<company_id>/outreach/send
- GET /api/crm/companies/<company_id>/outreach/history
- GET /api/crm/contacts/outreach/summary

### 8.6 Admin and health routes

- POST /admin/sync
- POST /api/dashboard/sync/greenbook
- GET /admin/sync/status
- POST /admin/cloud-sync
- GET /admin/cloud-sync/status
- GET /api/health
- GET /health
- GET /api/ready
- GET /ready
- POST or GET /api/cron/greenbook-sync
- GET /api/cron/greenbook-sync/status

## 9. Frontend Route Inventory

The React application should expose the following front-end routes:

- /dashboard
- /companies
- /companies/:companyId
- /contacts
- /tasks
- /deals
- /emails
- /reports
- /settings

The route structure should support:

- list views for companies, contacts, tasks, deals, and reports
- detail pages for individual companies
- nested data retrieval from the API adapter layer

## 10. Frontend Implementation Guidance

### 10.1 Visual system

The CRM experience should use:

- a clean white or neutral background
- polished cards with soft borders
- strong spacing and hierarchy
- status badges for pipeline and task states
- professional typography
- compact tables for dense business data
- responsive layouts for desktop and tablet usage

### 10.2 Interaction model

- Use clear list/detail patterns for company management
- Use cards and sections instead of dense full-page forms for most workflows
- Avoid disconnected “app-like” UI; make the CRM feel like an extension of the platform
- Keep actions close to the object they affect

### 10.3 Shared frontend architecture

The frontend should be organized around:

- route pages in mednova-grow-hub/src/routes
- shared layout components in mednova-grow-hub/src/components
- API normalization utilities in mednova-grow-hub/src/lib/api
- formatting and helper utilities under mednova-grow-hub/src/lib
- shared styles in mednova-grow-hub/src/styles.css

## 11. Service Layer Responsibilities

The rebuild should preserve service-orientation instead of putting logic directly into routes.

### 11.1 CompanyService

Responsibilities:

- create, update, list, search, and detail company records
- create initial activity, task, and contact scaffolding for new companies
- add activities and notes

### 11.2 ContactService

Responsibilities:

- create, update, delete contacts
- produce activity feed entries for contact-related events

### 11.3 TaskService

Responsibilities:

- create, update, complete, reopen, and delete tasks
- enforce company scoping for task operations

### 11.4 PipelineService

Responsibilities:

- create, update, delete deals
- manage deal and pipeline records

### 11.5 OutreachService

Responsibilities:

- create, update, and list outreach emails
- track draft/sent/failed status

### 11.6 IntelligenceService

Responsibilities:

- query Tavily and public sources
- build company search queries
- analyze public content
- generate intelligence profiles and recommendations
- cache and refresh results

### 11.7 ReportService

Responsibilities:

- create and persist reports
- list report history
- format export content

### 11.8 CRMService

Responsibilities:

- act as an orchestrator for company creation and compatibility with older workflows
- de-duplicate company creation using fuzzy matching logic
- support legacy payload compatibility

## 12. Business Rules

### 12.1 Company creation

- A company can be created from a payload with company_name or company
- If a similar company already exists, the system should avoid duplicate creation where possible
- New company creation should create at least one activity, one initial task, and one primary contact placeholder

### 12.2 Contact discovery

- Discovery should not fail silently if provider is unavailable
- If no contacts are discovered, the system should create a placeholder contact rather than leave the company without any contact scaffolding
- Discovered contacts should be associated with source metadata whenever available

### 12.3 Tasks

- Completed tasks should be marked with completed_at and reflected in the UI
- Reopening a completed task should clear completed_at and restore pending state
- A task must belong to the company in the route path or it should be rejected

### 12.4 Deals

- Deal stages should be normalized to the internal stage vocabulary
- Probability should remain within 0–100
- Value should be numeric and should default to 0 if missing

### 12.5 Outreach

- Subject and body are required for draft/save operations
- Email sending should record success or failure and persist message metadata
- Duplicate send behavior should be handled gracefully

### 12.6 Reports

- Report generation should create a persisted record where possible
- Export content should be deterministic enough to be used in markdown or text delivery flows

## 13. Environment and Configuration Requirements

The rebuild should support the following environment variables:

- SUPABASE_URL
- SUPABASE_SERVICE_ROLE_KEY
- MEDNOVA_DB_PATH or DATABASE_PATH
- TAVILY_API_KEY
- RESEND_API_KEY
- FROM_EMAIL
- VITE_API_BASE_URL

Expected local development behavior:

- If Supabase keys are missing, the system should still function in local mode using SQLite-backed CRM tables where possible
- The frontend should default to http://127.0.0.1:5000 in local development unless overridden by VITE_API_BASE_URL

## 14. Rebuild Implementation Plan

### Phase 1: Foundation

- Preserve the Flask entrypoints and route behavior
- Ensure the service/repository pattern is intact
- Recreate or preserve the API contract expected by the React app

### Phase 2: CRM feature parity

- Implement company list and detail flows
- Implement contacts, tasks, notes, and activities
- Implement deals and pipeline stages

### Phase 3: Intelligence and outreach

- Implement Tavily-driven intelligence enrichment
- Implement outreach templates and draft/send persistence
- Implement company report generation and export

### Phase 4: UI polish and production hardening

- Improve data loading states, edge cases, and validation feedback
- Add more robust error handling and observability
- Add authentication and access controls if required by the deployment target

## 15. Important Implementation Notes

This repository already contains the architectural skeleton needed to rebuild the product. The most important thing is not to create a brand-new app from scratch; instead, the rebuild should preserve the repository’s current intent:

- the Flask app remains the backend hub
- the services carry the business logic
- the repositories isolate persistence
- the React app provides the CRM surface
- the legacy regulatory modules remain part of the larger platform

The rebuild should therefore prioritize fidelity to the existing domain model and user flows rather than inventing an unrelated CRM experience.

## 16. Current Implementation Contract as Observed in the Repository

The following section captures the implementation details that are already present in the codebase so the rebuild can preserve them exactly.

### 16.1 Backend entrypoint inventory

The current Flask app in [app.py](app.py) is the central backend hub. It serves both the legacy regulatory UI and the CRM/workflow layer. The rebuild should preserve the following route groups:

- Legacy pages:
  - GET /, /dashboard, /legacy-dashboard
  - GET /products, /products/<pid>
  - GET /opportunities, /renewals
  - GET /crm, /growhub, /mednova-grow-hub
- CRM shell redirection and detail routes:
  - GET /crm/companies
  - GET /crm/companies/<company_id>
  - GET /api/growhub/crm/companies
  - GET /api/growhub/crm/data
  - GET /api/crm/companies/<company_id>
- CRM mutation routes:
  - POST /api/crm/companies/from-opportunity
  - PATCH /api/crm/companies/<company_id>/pipeline-stage
  - POST /api/crm/companies/<company_id>/contacts/discover
  - POST /api/crm/companies/<company_id>/contacts
  - POST /api/crm/companies/<company_id>/tasks
  - POST /api/crm/companies/<company_id>/notes
  - POST /api/crm/companies/<company_id>/tasks/<task_id>/complete
  - PATCH /api/crm/companies/<company_id>/tasks/<task_id>
  - DELETE /api/crm/companies/<company_id>/tasks/<task_id>
  - POST /api/crm/companies/<company_id>/deals
  - PATCH /api/crm/companies/<company_id>/deals/<deal_id>
  - DELETE /api/crm/companies/<company_id>/deals/<deal_id>
- Intelligence and reporting routes:
  - GET /api/crm/companies/<company_id>/intelligence
  - POST /api/crm/companies/<company_id>/intelligence/refresh
  - POST /api/crm/companies/<company_id>/reports/generate
  - GET /api/crm/companies/<company_id>/reports
  - POST /api/reports/operations/generate
  - GET /api/reports
  - GET /api/reports/<report_id>
  - POST /api/reports/<report_id>/export
- Outreach routes:
  - GET /api/outreach/status
  - GET /api/crm/outreach/templates
  - POST /api/crm/companies/<company_id>/outreach/build
  - POST /api/crm/companies/<company_id>/outreach/drafts
  - POST /api/crm/companies/<company_id>/outreach/send
  - GET /api/crm/companies/<company_id>/outreach/history
  - GET /api/crm/contacts/outreach/summary
- Admin and health routes:
  - POST /admin/sync
  - POST /api/dashboard/sync/greenbook
  - GET /admin/sync/status
  - POST /admin/cloud-sync
  - GET /admin/cloud-sync/status
  - GET /api/health, /health, /api/ready, /ready
  - POST or GET /api/cron/greenbook-sync and GET /api/cron/greenbook-sync/status

### 16.2 Backend service responsibilities

The rebuild should preserve the service-oriented structure already present in the repository:

- CompanyService
  - Creates companies from payloads and auto-scaffolds initial activities, contacts, and tasks
  - Exposes list/search/detail/update/delete operations
  - Supports company detail enrichment with notes and activities
- ContactService
  - Creates and updates contacts for a company
  - Logs contact-related activities
  - Supports listing and search
- TaskService
  - Creates, edits, completes, reopens, and deletes tasks
  - Enforces company ownership when completing or editing tasks
- PipelineService
  - Creates, updates, deletes, and lists deals
  - Supports a pipeline-style overview
- OutreachService
  - Persists outreach drafts/sends and exposes history
  - Tracks status and activity feed entries
- IntelligenceService
  - Builds the search query from company name and website
  - Calls Tavily, parses results, and analyzes public websites
  - Persists intelligence payloads and caches them by company/query
- ReportService
  - Creates persisted report records and exports them to markdown-like text content
- CRMService
  - Acts as the compatibility layer for legacy payloads and company creation flows
  - Implements fuzzy duplicate detection using normalized company-name matching

### 16.3 Data contract and field mapping

The current frontend and backend do not use the same exact field names in every place. The rebuild should preserve this mapping layer or reimplement it explicitly.

#### Company field mapping

The current frontend expects these names from the shared API adapter:

- id
- name
- industry
- country
- website
- status
- opportunityScore
- portfolioSummary
- source
- regulatoryReportId
- lastActivityAt
- nextFollowUpAt
- createdAt

The backend stores the canonical CRM company values in the repository layer using names such as:

- company_name
- country
- opportunity_score
- portfolio_summary
- source
- registration_numbers
- dosage_forms
- therapeutic_areas
- registration_dates
- opportunity_status
- pipeline_stage
- report_context
- greenbook_products_json
- created_at
- updated_at

The API adapter translates between the two shapes.

#### Contact field mapping

Frontend contact shape:

- id
- companyId
- name
- position
- department
- email
- phone
- linkedin
- notes
- source
- sourceUrl
- discoveredAt
- confidenceScore
- verificationStatus
- website

Backend record shape:

- crm_company_id
- full_name
- role
- department
- email
- phone
- linkedin_url
- website
- source
- source_url
- created_at
- updated_at

#### Task field mapping

Frontend task shape:

- id
- companyId
- title
- type
- dueDate
- done
- assignee
- completedAt
- description
- priority

Backend task shape:

- crm_company_id
- title
- task_type
- due_date
- status
- assigned_to
- completed_at
- description
- priority

#### Deal field mapping

Frontend deal shape:

- id
- companyId
- title
- stage
- value
- currency
- probability
- expectedCloseAt

Backend deal shape:

- crm_company_id
- crm_contact_id
- title
- stage
- value
- currency
- probability
- expected_close_at
- owner
- description

#### Outreach field mapping

The frontend expects the response envelope for outreach history to use names such as:

- companyId
- contactId
- templateKey
- templateName
- recipientName
- senderName
- senderEmail
- companyName
- contactName
- status
- sentAt

The backend persists these in CRM tables with snake_case fields such as:

- crm_company_id
- crm_contact_id
- template_key
- template_name
- recipient
- recipient_name
- sender_name
- sender_email
- from_email
- company_name
- contact_name
- status
- message_id
- error_message
- sent_at

### 16.4 Frontend route inventory and responsibilities

The React app under [mednova-grow-hub/src/routes](mednova-grow-hub/src/routes) already exposes the following screen surface:

- /dashboard
  - Summary KPIs, activity feed, and operational overview
- /companies
  - Inventory of CRM companies with list and filtering affordances
- /companies/$companyId
  - Company detail workspace with report generation, intelligence refresh, tasks, notes, and contact sections
- /contacts
  - Contact inventory with manual creation and contact discovery CTA
- /tasks
  - Task board/list with create, edit, complete, and reopen flows
- /deals
  - Deal pipeline with drag-and-drop stage movement and inline editing
- /emails
  - Outreach composer with save-as-draft and send flows
- /reports
  - Report history and export interface
- /settings
  - Configuration and account-level settings shell

The shared API adapter in [mednova-grow-hub/src/lib/api/index.ts](mednova-grow-hub/src/lib/api/index.ts) is the contract layer. Rebuilds should preserve these helper functions and their expected semantics:

- buildApiUrl
- useCrmData
- useCompanyDetail
- createContact
- discoverContacts
- createTask
- updateTask
- completeTask
- createDeal
- updateDeal
- deleteDeal
- createOutreachDraft
- saveOutreachDraft
- sendOutreachEmail
- loadOutreachTemplates
- getOutreachHistory

### 16.5 Persistence and fallback behavior

The current persistence model is intentionally hybrid and should remain part of the rebuild:

- Supabase PostgreSQL is the preferred production path if keys are configured
- SQLite is used as a fallback when Supabase is unavailable or when operating on CRM-only tables
- The database abstraction in [backend/database/db.py](backend/database/db.py) routes CRM tables to SQLite when Supabase is unavailable
- The repository layer should not expose raw DB differences to the services
- JSON payloads such as report_data, search_results_json, or nested intelligence payloads should be stored as JSON-compatible data or serialized text depending on the storage engine

### 16.6 UI and interaction details that matter

The rebuild should preserve the following presentational and interaction patterns:

- White/neutral surfaces with soft borders and polished cards
- Dense tables for contacts, tasks, and reports
- Sidebar-based company detail views with tabbed sections
- Modal task detail dialogs on the company profile page
- Drill-down from company inventory to company profile
- Context-prefilled outreach composer that is launched from the company profile and carries company/contact details in the query string
- Report export buttons that trigger download or print actions from the browser
- Placeholder filtering logic for contact discovery so obviously bogus contacts are not surfaced as active data

### 16.7 Current implementation quirks to preserve until a redesign is approved

The current repository contains a few behaviors that are unusual but should be preserved if fidelity matters:

- The frontend defaults to http://127.0.0.1:5000 in development unless VITE_API_BASE_URL is set
- The API adapter silently retries the fallback host if the primary request fails
- The company detail API strips placeholder contacts from the response before returning them to the UI
- Contact discovery creates a placeholder contact if no real contact is found rather than returning an empty state
- The front-end uses a task.done boolean and completedAt timestamp while the backend uses status and completed_at; the translation layer must remain intact
- Deal stages are normalized to a closed vocabulary of lead, qualified, contacted, meeting, proposal, negotiation, won, and lost
- Report export is implemented as text output rather than a true PDF generator in the current codebase
- Activities are generated automatically for company creation, task completion, deal changes, note creation, and outreach events

## 17. Rebuild Priority Order

If the rebuild is going to be implemented in another framework, the work should proceed in this order:

1. Recreate the backend API contract and route behavior first
2. Recreate the service layer and repository abstraction next
3. Recreate the CRM data model and persistence fallback layer
4. Rebuild the core company, contact, task, deal, and outreach flows
5. Rebuild the company detail and dashboard screens
6. Rebuild intelligence and reporting features
7. Polish the UI and harden error handling

The most important principle is that this repository already contains a coherent skeleton for the product. The rebuild should preserve that skeleton rather than invent a new experience from scratch.
