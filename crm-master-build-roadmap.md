# CRM Master Build Roadmap

## Purpose

This document is the single-source implementation roadmap for turning the imported CRM into a native MedNovaOS CRM module. It is based on the actual current state of the Flask application, the SQLite schema, the Opportunities workflow, the existing report drawer, the shared templates, and the imported CRM’s UI structure.

## 1. Implementation Phases

## Phase 1 — Core Integration

### Goal

Make CRM a real part of MedNovaOS rather than a separate mock experience.

### What needs building

- Connect Opportunities → CRM
- Replace mock CRM data with real data
- Create CRM data persistence layer
- Build CRM navigation integration
- Create a first CRM company record from an existing opportunity
- Prevent duplicate CRM companies
- Establish a shared company identity between MedNovaOS and CRM

### Status by item

- Existing: Opportunities workflow, shared navigation, Flask app, SQLite database
- Needs modification: Opportunities page to trigger CRM creation, shared navigation styling, CRM landing route
- Missing entirely: CRM persistence, server-side company creation, duplicate prevention, real CRM company list
- Can be reused: Existing company/product data from SQLite, current report flow, base template
- Must be rewritten: Imported CRM mock-data layer

### Estimated effort

- Medium

### Dependencies

- Database schema for CRM entities
- Backend service layer for CRM company creation
- UI flow from Opportunities → CRM

---

## Phase 2 — Data Model and Persistence

### Goal

Create a durable backend model for CRM records while preserving existing MedNovaOS data as the source of truth.

### What needs building

- CRM companies table
- CRM contacts table
- CRM activities table
- CRM tasks table
- CRM notes table
- CRM deals/pipeline table
- CRM emails table
- CRM company linkage to existing MedNovaOS entities
- Company source tracking
- Report linkage storage
- Opportunity score storage

### Database review

#### Existing tables that can be reused

- manufacturers
- applicants
- products
- categories
- dosage_forms
- routes
- sync_history
- renewal_alerts
- watchlist
- product_changes

#### Tables that should be extended

- None of the existing tables are CRM-native, but the current companies can be represented by combining applicants/manufacturers/products data.

#### New tables required

- crm_companies
- crm_contacts
- crm_activities
- crm_tasks
- crm_notes
- crm_deals
- crm_emails
- crm_company_links

### Recommended relationships

- crm_companies
  - one-to-many with crm_contacts
  - one-to-many with crm_activities
  - one-to-many with crm_tasks
  - one-to-many with crm_notes
  - one-to-many with crm_deals
  - one-to-many with crm_emails
  - optional many-to-many with products via crm_company_links
- crm_company_links
  - links crm_companies to existing MedNovaOS entities such as manufacturers, applicants, and products

### Status by item

- Existing: Products and company-related tables in SQLite
- Needs modification: None yet; the schema needs extension rather than modification
- Missing entirely: All CRM tables and relationships
- Can be reused: Existing product/company identity data
- Must be rewritten: Any mock CRM data model from the imported CRM

### Estimated effort

- High

### Dependencies

- Clear decision on source-of-truth architecture
- Agreement that existing product data is canonical and CRM data is supplemental

---

## Phase 3 — Contacts and Relationship Management

### Goal

Support the business development workflow around people and accounts.

### What needs building

- Contact list screen
- Contact creation flow
- Contact editing flow
- Contact-to-company association
- Contact status and role fields
- Optional contact enrichment strategy
- Empty state when no contacts are found
- Contact search and filtering

### UI changes

- Contacts screen should be data-bound rather than static
- Company profile sidebar must load actual contacts from backend
- Contact cards should show role, email, phone, LinkedIn, and notes

### API changes

- GET /api/crm/companies/<id>/contacts
- POST /api/crm/contacts
- PUT /api/crm/contacts/<id>
- DELETE /api/crm/contacts/<id>

### Search strategy

- Search contacts by name, role, company, and email
- Filter by company and department

### Missing features

- No existing contact storage for CRM contacts
- No contact discovery pipeline
- No contact source tracking

### Status by item

- Existing: Imported CRM UI for contacts
- Needs modification: UI to bind to real data and forms
- Missing entirely: Persistence, CRUD endpoints, search/filter handling
- Can be reused: Contact fields from imported CRM mock schema
- Must be rewritten: Mock contact data source

### Estimated effort

- Medium

### Dependencies

- CRM contact database tables
- Backend CRUD endpoints

---

## Phase 4 — Business Development Workflow

### Goal

Turn the CRM into a working follow-up workspace for commercial teams.

### What needs building

- Activity timeline
- Task management
- Follow-up scheduling
- Deal/pipeline tracking
- Email logging
- Notes and timeline updates
- Status changes for companies
- Company lifecycle progression

### Core features

- Add activity entries when a report is generated
- Add activity entries when a company is moved into CRM
- Create follow-up tasks from company detail view
- Track deal stages from lead to won/lost
- Log notes and meetings
- Show recent activity in the company profile

### UI changes

- Company profile tabs for activities, tasks, deals, emails, notes, files
- Sidebar showing company metadata and next follow-up
- Timeline rendering from real backend data

### API changes

- GET /api/crm/companies/<id>/activities
- POST /api/crm/activities
- GET /api/crm/companies/<id>/tasks
- POST /api/crm/tasks
- GET /api/crm/companies/<id>/deals
- POST /api/crm/deals
- GET /api/crm/companies/<id>/notes
- POST /api/crm/notes

### Status by item

- Existing: Imported CRM routes and screen structure
- Needs modification: Replace mock data and wire the screen to live backend data
- Missing entirely: Real activity/task/deal persistence and workflow actions
- Can be reused: UI structure and route layout from imported CRM
- Must be rewritten: Mock data service layer

### Estimated effort

- High

### Dependencies

- CRM persistence tables
- Activity/task/deal CRUD routes
- User interaction patterns from the current app

---

## Phase 5 — Green Book and Report Integration

### Goal

Connect the existing regulatory intelligence flow to the CRM in a seamless way.

### What needs building

- Opportunities page should create or link a CRM company
- Generate Report should be tied to the CRM company record
- Company detail view should display the report context
- CRM company profile should show relevant products and opportunity indicators
- “Add to CRM” should create a company record with context from current opportunity data
- Report generation should become a first-class CRM activity entry

### Existing workflow review

Current flow:

- Green Book data is discovered through the existing product and opportunity logic
- Opportunities page groups companies by product portfolio
- The opportunities page contains a report drawer and CRM action buttons
- The current report drawer is front-end-only and generates static mock content
- The Add to CRM button only shows a success toast

### Required integration behavior

1. Green Book data is reviewed on the Opportunities page.
2. User clicks Generate Report.
3. Report content is generated from actual product and company context.
4. User clicks Add to CRM.
5. The system creates or updates a CRM company record.
6. The CRM company profile opens with the report context and linked products.
7. Business development follow-up begins from that company profile.

### UI changes

- Replace hardcoded report content with real data-derived report section
- Make the Add to CRM action persist data rather than only displaying a toast
- Link the CRM action to a company profile page or detail view

### API changes

- POST /api/crm/companies/from-opportunity
- GET /api/crm/companies/<id>/report-context

### Status by item

- Existing: Opportunities page, report drawer, existing product/company data
- Needs modification: Report generation logic, CRM action handler, opportunity company context mapping
- Missing entirely: Backend persistence and report-to-company linking
- Can be reused: Product and company aggregation logic from the current opportunities route
- Must be rewritten: Mock report UI and toast-only CRM action

### Estimated effort

- High

### Dependencies

- CRM company persistence
- Report generation service
- Opportunity-to-company mapping logic

---

## Phase 6 — Reporting and Analytics

### Goal

Make CRM useful for management and business development teams.

### What needs building

- Dashboard KPIs using live CRM data
- Companies added metric
- Leads metric
- Active opportunities metric
- Won clients metric
- Tasks due metric
- Meetings scheduled metric
- Pipeline value metric
- Report export or PDF generation
- Pipeline overview

### UI changes

- Replace imported CRM dashboard placeholder logic with live backend data
- Generate charts or summary cards from stored CRM data

### API changes

- GET /api/crm/dashboard
- GET /api/crm/reports

### Missing features

- No CRM reporting layer exists yet
- No dashboard data service exists yet

### Status by item

- Existing: CRM dashboard route and KPI concept in imported CRM
- Needs modification: Replace static/mock calculations
- Missing entirely: Backend dashboard aggregation and reports
- Can be reused: KPI definitions from imported CRM route structure
- Must be rewritten: Mock KPI data layer

### Estimated effort

- Medium

### Dependencies

- CRM persistence tables and data ingestion

---

## Phase 7 — AI and Content Assistance

### Goal

Add intelligent flows on top of the CRM foundation.

### What needs building

- AI-assisted email drafting
- Personalized outreach email generation
- Opportunity scoring explanation
- Company insight summarization
- Contact enrichment suggestions
- Report generation refinement

### What should be built first

- Email generation using existing company/product context
- Activity logging for generated emails
- Simple templated drafting before introducing a large AI service

### Status by item

- Existing: Imported CRM includes email and report concepts
- Needs modification: Backend support and data source wiring
- Missing entirely: AI service abstraction and generation workflow
- Can be reused: Existing product and report context data
- Must be rewritten: UI-only placeholder interactions

### Estimated effort

- Medium to High

### Dependencies

- CRM company and report linkage
- External AI service decision

---

## Phase 8 — Security and Governance

### Goal

Ensure the CRM can be used safely and responsibly within MedNovaOS.

### What needs building

- Authentication integration if/when auth is introduced
- Authorization rules for CRM objects
- Session management alignment with existing app
- Input validation for forms and payloads
- SQL injection protection through parameterized queries
- CSRF protection for state-changing forms
- File upload restrictions if attachments are added later
- Email sending safeguards and rate limiting
- Audit trail for changes

### Status by item

- Existing: Flask app already uses direct SQL queries and no formal auth layer
- Needs modification: Introduce explicit request validation and access control patterns
- Missing entirely: Authorization and secure form handling conventions
- Can be reused: Existing Flask app structure
- Must be rewritten: Any future CRM endpoints should follow a secure pattern from the outset

### Estimated effort

- Medium

### Dependencies

- Backend endpoint layer design

---

## 2. Feature Status Matrix

| Feature                    | Existing            | Needs modification | Missing entirely | Can be reused | Must be rewritten |
| -------------------------- | ------------------- | ------------------ | ---------------- | ------------- | ----------------- |
| CRM navigation             | Yes                 | Yes                | No               | Yes           | No                |
| Opportunities → CRM action | Partial             | Yes                | No               | Yes           | Yes               |
| Company report drawer      | Yes                 | Yes                | No               | Yes           | Yes               |
| CRM landing page           | Yes                 | Yes                | No               | Yes           | No                |
| CRM companies list         | No                  | No                 | Yes              | No            | Yes               |
| CRM company detail         | Yes in imported CRM | Yes                | No               | Yes           | Yes               |
| Contacts module            | Yes in imported CRM | Yes                | No               | Yes           | Yes               |
| Tasks module               | Yes in imported CRM | Yes                | No               | Yes           | Yes               |
| Activities timeline        | Yes in imported CRM | Yes                | No               | Yes           | Yes               |
| Deals/pipeline             | Yes in imported CRM | Yes                | No               | Yes           | Yes               |
| Emails module              | Yes in imported CRM | Yes                | No               | Yes           | Yes               |
| Reports module             | Yes in imported CRM | Yes                | No               | Yes           | Yes               |
| Dashboard metrics          | Yes in imported CRM | Yes                | No               | Yes           | Yes               |
| Database tables            | Partial             | Yes                | Yes              | Yes           | No                |
| Backend API layer          | Partial             | Yes                | Yes              | Yes           | No                |
| Duplicate prevention       | No                  | No                 | Yes              | No            | Yes               |
| Report-to-company linking  | No                  | No                 | Yes              | No            | Yes               |
| Product-to-company linking | Partial via SQLite  | Yes                | No               | Yes           | No                |

---

## 3. Database Review

### Existing tables that should stay as-is

- manufacturers
- applicants
- products
- categories
- dosage_forms
- routes
- sync_history

### Existing tables that can support CRM context

- products can continue to be the source of portfolio and regulatory data.
- applicants and manufacturers can provide the base company identity.
- watchlist and renewal_alerts can potentially feed business development prioritization later.

### New CRM tables that are required

- crm_companies
- crm_contacts
- crm_activities
- crm_tasks
- crm_notes
- crm_deals
- crm_emails
- crm_company_links

### Recommended schema relationships

#### crm_companies

- id
- name
- industry
- country
- website
- status
- opportunity_score
- portfolio_summary
- source
- report_reference
- created_at
- updated_at

#### crm_contacts

- id
- crm_company_id
- name
- position
- department
- email
- phone
- linkedin
- notes
- source
- created_at
- updated_at

#### crm_activities

- id
- crm_company_id
- type
- title
- body
- occurred_at
- author
- created_at

#### crm_tasks

- id
- crm_company_id
- title
- type
- due_at
- completed
- assignee
- created_at
- updated_at

#### crm_notes

- id
- crm_company_id
- body
- author
- created_at

#### crm_deals

- id
- crm_company_id
- title
- stage
- value
- currency
- probability
- expected_close_at
- created_at
- updated_at

#### crm_emails

- id
- crm_company_id
- crm_contact_id
- subject
- body
- status
- sent_at
- created_at

#### crm_company_links

- id
- crm_company_id
- entity_type
- entity_id
- relationship_type
- created_at

### Relationship recommendation

The CRM should not duplicate core product data. Instead, it should link to existing MedNovaOS entities through crm_company_links while storing business-development-specific records in the CRM tables.

---

## 4. API Review

### Existing Flask endpoints that are reusable

- GET /products
- GET /products/<id>
- GET /opportunities
- GET /renewals
- GET /admin/sync/status
- GET /admin/cloud-sync/status

These are valuable because they already provide the product and opportunity context that the CRM needs.

### Existing endpoints that need extension

- GET /opportunities should provide enough data for CRM promotion and report generation.
- The existing /crm route should evolve into a real CRM landing page and dashboard.

### Missing endpoints required for CRM

- GET /api/crm/companies
- GET /api/crm/companies/<id>
- POST /api/crm/companies
- POST /api/crm/companies/from-opportunity
- GET /api/crm/companies/<id>/contacts
- POST /api/crm/contacts
- GET /api/crm/companies/<id>/activities
- POST /api/crm/activities
- GET /api/crm/companies/<id>/tasks
- POST /api/crm/tasks
- GET /api/crm/companies/<id>/deals
- POST /api/crm/deals
- GET /api/crm/companies/<id>/notes
- POST /api/crm/notes
- GET /api/crm/dashboard
- GET /api/crm/reports

### Recommended routing approach

Keep the existing Flask style and use JSON API endpoints for CRM interaction. The server-rendered templates can remain the primary UI mechanism initially, and JSON endpoints can support richer interactions later.

---

## 5. UI Review

### Screens that are already present

- CRM landing page in [templates/crm.html](templates/crm.html)
- Opportunities page in [templates/opportunities.html](templates/opportunities.html)
- Base navigation in [templates/base.html](templates/base.html)

### Screens from the imported CRM that are conceptually ready

- Companies list
- Company profile
- Contacts
- Activities
- Tasks
- Deals
- Emails
- Reports
- Settings

### Screens that are finished

- The imported CRM route structure is well defined conceptually.
- The UI shell and component organization are already present.

### Screens that need data binding

- All CRM screens need to be wired to real backend data.

### Screens that need redesign

- The current CRM placeholder page should be expanded into a real native MedNovaOS CRM experience.
- The current Opportunities page should be upgraded from a mock report drawer and toast-only CRM action to a true workflow.

### Screens that still contain mock data

- The imported CRM’s mock-data layer in [mednova-grow-hub/src/lib/mock-data/index.ts](mednova-grow-hub/src/lib/mock-data/index.ts)
- The report drawer content in [templates/opportunities.html](templates/opportunities.html)
- The CRM landing template in [templates/crm.html](templates/crm.html)

---

## 6. Green Book Integration Review

### Current user journey

The existing flow is already close to the desired CRM workflow:

- Review products and opportunities
- Inspect company-level portfolio patterns
- Generate a report
- Add company to CRM
- Manage follow-up

### Required behavior

#### Generate Report

- Should use actual product data from the current opportunity context
- Should be based on products, categories, status, approval dates, and company profile
- Should be stored or referenced in CRM if the company is promoted

#### Add to CRM

- Should create or update a CRM company record
- Should capture the opportunity context and selected company name
- Should preserve the report context
- Should redirect or navigate to the CRM company profile

#### Company Details

- Should show customer/company context from MedNovaOS data
- Should include related products and opportunity score
- Should link to report and CRM activity

#### Products

- Should appear under the CRM company profile as related products
- Should come from existing product data rather than a separate dataset

#### Commercial Actions

- Should become real workflow actions: add contact, create task, log note, create deal, draft email

### Recommended user journey

Green Book
↓
Company opportunity review
↓
Generate Report
↓
Add to CRM
↓
CRM company created
↓
Business Development follow-up
↓
Email drafting
↓
Activity tracking
↓
Deal pipeline
↓
Reports

---

## 7. Contact Discovery Review

### Recommended architecture

The CRM should start with a simple and maintainable contact strategy:

#### Free sources

- Company websites
- Public regulatory filings
- Public press releases
- Company directories

#### Paid APIs

- Optional later-stage enrichment services for verified contact data
- Should be isolated behind a service interface so they can be swapped

#### Manual entry

- Should be the default workflow for the first implementation
- Recommended because the data source is currently incomplete and quality varies

#### LinkedIn

- Optional enrichment only
- Should not be the primary source in the first version

#### Company websites

- Useful for basic contact pages and generic inquiry addresses
- Can be used as an enrichment source but should be treated as secondary

#### Regulatory databases

- Useful for company identity and corporate data but not necessarily direct contact data

#### Email verification services

- Useful once a contact list is created
- Best added after the core CRM workflow is working

### When no contacts are found

The CRM should show a clear empty state and offer:

- Add a contact manually
- Add a note about missing contact data
- Schedule a follow-up task to find a contact later

---

## 8. Security Review

### Authentication

- No authentication layer currently exists in the Flask app.
- If authentication is introduced later, CRM endpoints should use the same session/auth flow as the rest of MedNovaOS.

### Authorization

- CRM records should be restricted to the appropriate role or user group when auth is added.
- The initial implementation can keep the system internal-only and rely on deployment-level access controls.

### Session management

- If the app adds a login flow, CRM actions must use that session context rather than anonymous posting.

### Input validation

- All CRM forms and JSON payloads should validate required fields before writing to SQLite.
- Company names, emails, task dates, and deal data should be validated explicitly.

### SQL injection risks

- The current app mostly uses parameterized queries, which is good.
- Any new CRM endpoints must continue to use parameterized queries.

### CSRF

- If forms are used for state-changing actions, CSRF protection should be added.
- For JSON API endpoints, the same defensive pattern should be applied once auth is introduced.

### File uploads

- Not required for the first implementation. If attachments are added later, uploads should be restricted and scanned.

### Email sending

- Email sending should be opt-in and guarded by feature flags.
- Drafted emails should be stored before sending.

### Rate limiting

- If enrichment or AI features are added, rate limiting should be implemented to avoid abuse and accidental cost spikes.

---

## 9. Recommended Implementation Order

### Critical

- Create the CRM persistence layer and link it to existing MedNovaOS entities
- Implement the Opportunities → CRM promotion flow
- Replace mock CRM data with live data from the backend
- Build the first company detail and company list experience

### High Priority

- Build contacts, tasks, and activities modules
- Connect the report drawer to actual company context and CRM records
- Build the dashboard and reporting foundation

### Medium Priority

- Add deals/pipeline management
- Add notes and timeline features
- Add email drafting and logging

### Nice to Have

- Full AI email drafting
- Advanced enrichment and contact discovery
- PDF/export features
- Rich file attachments and full timeline automation

---

## 10. What Should Be Built Next

The next implementation slice should be:

1. CRM database tables and backend service layer
2. A simple company creation flow from the Opportunities page
3. A basic CRM companies list and company detail view
4. Contact and task creation for a company
5. Activity logging when a company is promoted into CRM

That sequence delivers the most important user value first and establishes a foundation for later reporting, AI, and enrichment features.
