# CRM Implementation Roadmap

## Purpose

This document converts the CRM production audit into a phased execution plan for the next stage of development. It is the implementation blueprint for the CRM workstream and is intended to be used as the single source of truth for sequencing, scope, and delivery priorities.

## Guiding Principles

- Keep the existing MedNovaOS platform as the operational backbone and source of truth.
- Treat the CRM as a business workflow layer rather than a standalone UI shell.
- Build in thin, testable slices so each phase produces usable value.
- Prefer persistence, workflow state, and user accountability over visual polish.
- Do not introduce major architectural changes until the core CRM data model and permissions model are in place.

---

# Phase 1 – Foundation

This phase must be completed before any wider CRM workflow can be trusted.

## Task 1.1 – Complete the CRM database schema

### Description

Create the missing relational tables for the core CRM domain, including contacts, tasks, deals, emails, documents, audit logs, users, and workflow state. Ensure every entity has timestamps, ownership fields, source references, and status fields.

### Why it matters

The current CRM layer is too thin to support real operational workflows. A complete schema is the prerequisite for persistent CRM use.

### Dependencies

None. This is the first dependency for the rest of the roadmap.

### Estimated Complexity

Very Large

### Business Impact

Critical

---

## Task 1.2 – Implement authentication and session handling

### Description

Introduce a real authentication layer for the CRM experience, including sign-in, session management, password handling, and session expiry. Ensure user context is available across the UI and backend.

### Why it matters

Without user identity, the CRM cannot safely support ownership, responsibility, auditability, or role-based access.

### Dependencies

Database schema completion and a user/account model.

### Estimated Complexity

Large

### Business Impact

Critical

---

## Task 1.3 – Implement role-based access control

### Description

Define user roles such as admin, sales, medical affairs, regulatory affairs, and viewer. Secure CRM entities and operations so each role can only access what it should.

### Why it matters

The CRM will eventually handle sensitive account, contact, and communication data. Access control is essential for compliance and operational safety.

### Dependencies

Authentication and the CRM user model.

### Estimated Complexity

Large

### Business Impact

Critical

---

## Task 1.4 – Establish backend API contracts for CRM entities

### Description

Create a consistent backend API layer for companies, contacts, tasks, notes, deals, activities, emails, and reports. Define create, read, update, delete, list, and search behavior for each entity.

### Why it matters

The frontend should not depend on ad hoc data shaping or inconsistent endpoints. A stable contract will reduce churn and simplify future work.

### Dependencies

CRM schema, authentication, and role-based access control.

### Estimated Complexity

Large

### Business Impact

High

---

## Task 1.5 – Create a shared CRM data synchronization layer

### Description

Build the shared sync service that moves data from MedNovaOS into CRM entities while preserving relationships to products, opportunities, manufacturers, applicants, and company profiles.

### Why it matters

The CRM should not be a disconnected data island. It needs a dependable bridge to the existing MedNovaOS data model.

### Dependencies

CRM schema and the backend API contracts.

### Estimated Complexity

Large

### Business Impact

High

---

# Phase 2 – CRM Core

This phase makes the CRM operational for day-to-day business use.

## Task 2.1 – Build the company lifecycle workflow

### Description

Implement full company create, read, update, delete, search, and relationship management. The company record should include ownership, status, notes, linked products, linked opportunities, and related activities.

### Why it matters

Companies are the core entity of the CRM. Everything else should be attached to them.

### Dependencies

Phase 1 schema, authentication, and API contracts.

### Estimated Complexity

Large

### Business Impact

Critical

---

## Task 2.2 – Implement company profile enrichment

### Description

Make the company profile a true operational workspace with structured sections for overview, related products, contacts, tasks, notes, opportunities, deals, timeline, and status history.

### Why it matters

The company profile is where commercial teams make decisions. It must be more than a summary page.

### Dependencies

Company lifecycle workflow and CRM API contracts.

### Estimated Complexity

Large

### Business Impact

High

---

## Task 2.3 – Build contact management

### Description

Implement first-class CRM contacts with fields for name, role, department, email, phone, social profiles, owner, source, and relationship status. Contacts should be linked to companies and searchable.

### Why it matters

Contacts are the bridge between the company and every business action. This is essential for outreach, follow-up, and account execution.

### Dependencies

CRM schema and company lifecycle workflow.

### Estimated Complexity

Large

### Business Impact

Critical

---

## Task 2.4 – Implement activity and timeline recording

### Description

Create a shared timeline engine that records company creation, contact updates, task changes, deal moves, email events, note creation, report generation, and follow-up actions.

### Why it matters

A CRM becomes trustworthy when users can see what happened, when it happened, and by whom.

### Dependencies

CRM schema, API contracts, and entity event hooks.

### Estimated Complexity

Medium

### Business Impact

High

---

## Task 2.5 – Implement tasks and notes

### Description

Add persistent tasks with ownership, due dates, status, priority, and completion tracking. Add note creation, editing, linking, and visibility rules.

### Why it matters

Tasks and notes are the operational glue for commercial execution.

### Dependencies

CRM schema and user ownership model.

### Estimated Complexity

Medium

### Business Impact

High

---

## Task 2.6 – Implement deal and pipeline management

### Description

Introduce a structured deal model with stage progression, probability, expected value, close date, owner, associated company, contacts, and activities. Support pipeline movement and win/loss tracking.

### Why it matters

Operational CRM value depends on moving opportunities through a defined commercial process.

### Dependencies

Company lifecycle workflow, task system, and activity timeline.

### Estimated Complexity

Large

### Business Impact

Critical

---

# Phase 3 – Opportunity Workflow

This phase connects the Green Book and opportunity data to actual CRM business execution.

## Task 3.1 – Implement opportunity intake from Green Book data

### Description

Create a consistent process for turning Green Book and product intelligence into an opportunity record with source context, company linkage, products involved, and an initial priority score.

### Why it matters

The CRM should be able to act on the same intelligence already available in MedNovaOS rather than operating on disconnected data.

### Dependencies

CRM schema, company lifecycle workflow, and sync layer.

### Estimated Complexity

Large

### Business Impact

Critical

---

## Task 3.2 – Implement report generation and persistence

### Description

Replace the current static or mock report experience with a real report object that can be created, saved, linked to a company or opportunity, and reused in later workflows.

### Why it matters

Reports are a key handoff artifact between intelligence analysis and business development execution.

### Dependencies

Opportunity intake and CRM entity schema.

### Estimated Complexity

Large

### Business Impact

High

---

## Task 3.3 – Implement opportunity-to-company conversion

### Description

Build a workflow that converts an opportunity into a CRM company and creates initial company context, timeline entries, tasks, and an initial owner or follow-up state.

### Why it matters

This is the critical transition from insight to action.

### Dependencies

Opportunity intake, company lifecycle workflow, tasks, and timeline.

### Estimated Complexity

Medium

### Business Impact

Critical

---

## Task 3.4 – Implement workflow state progression

### Description

Define the lifecycle states for opportunity-to-client progression, such as discovered, qualified, contacted, meeting scheduled, proposal sent, negotiation, won, and lost.

### Why it matters

Without explicit workflow states, the business process will remain ambiguous and difficult to manage.

### Dependencies

Deal model, tasks, and activities.

### Estimated Complexity

Medium

### Business Impact

High

---

## Task 3.5 – Generate initial follow-up tasks from opportunities

### Description

When an opportunity is created or converted, the system should automatically create the first tasks and timeline records that guide the business development team to the next action.

### Why it matters

A CRM becomes useful when it removes manual setup and drives the next best action.

### Dependencies

Opportunity intake, task system, and timeline engine.

### Estimated Complexity

Medium

### Business Impact

High

---

# Phase 4 – Contact Intelligence

This phase defines how the CRM should discover and enrich contact information from external and internal sources.

## Task 4.1 – Build a contact discovery orchestration layer

### Description

Create a discovery service that accepts a target company and orchestrates the process of searching public and private sources for relevant contacts. The service should return candidate contacts with confidence scores and source provenance.

### Why it matters

The CRM must move from static account lists to live commercial intelligence.

### Dependencies

CRM schema, company records, and external source adapters.

### Estimated Complexity

Large

### Business Impact

High

---

## Task 4.2 – Add source-specific discovery adapters

### Description

Implement adapters for the following source classes:

- Public websites
- LinkedIn
- Company websites
- Official contact pages
- General enquiry emails
- Business development emails
- Medical Affairs
- Regulatory Affairs
- Pharmacovigilance
- Quality Assurance
- Commercial
- Procurement
- Medical Directors

The system should normalize extracted contact information into a common CRM contact format.

### Why it matters

Each source has different data availability and format. A common normalization layer prevents fragmented contact data.

### Dependencies

Discovery orchestration layer.

### Estimated Complexity

Very Large

### Business Impact

High

---

## Task 4.3 – Implement contact review and enrichment workflow

### Description

Add a review flow where discovered contacts can be approved, rejected, merged, or manually edited before being committed to the CRM. Include owner assignment, confidence levels, and evidence notes.

### Why it matters

Contact discovery quality will be inconsistent across sources. Human review prevents bad data from corrupting the CRM.

### Dependencies

Discovery adapters and CRM contact model.

### Estimated Complexity

Medium

### Business Impact

High

---

## Task 4.4 – Build a contact enrichment and deduplication layer

### Description

Deduplicate contacts across multiple sources and enrich them with role, department, and organizational context. The system should avoid creating duplicate records for the same person or company.

### Why it matters

A CRM becomes unreliable if it stores duplicated or inconsistent contact data.

### Dependencies

Contact model and discovery adapters.

### Estimated Complexity

Medium

### Business Impact

High

---

# Phase 5 – AI

This phase layers intelligence onto the CRM rather than treating AI as a visual add-on.

## Task 5.1 – Implement regulatory intelligence report generation

### Description

Create a structured reporting service that turns MedNovaOS regulatory and product data into concise, explainable regulatory intelligence reports for companies and opportunities.

### Why it matters

Regulatory context is a core differentiator for MedNovaOS and should be surfaced in the CRM workflow.

### Dependencies

Opportunity intake, company records, and report persistence.

### Estimated Complexity

Large

### Business Impact

High

---

## Task 5.2 – Implement executive summary generation

### Description

Generate company and opportunity summaries that explain the current situation, priorities, likely next steps, and recommended engagement approach.

### Why it matters

Commercial users need concise insight rather than raw data.

### Dependencies

Opportunity intake, company profile data, and report persistence.

### Estimated Complexity

Medium

### Business Impact

High

---

## Task 5.3 – Implement email drafting assistance

### Description

Create an AI-assisted email drafting workflow that uses company context, opportunity context, and prior interactions to produce a draft message that can be reviewed and edited.

### Why it matters

Email drafting is one of the most valuable workflows in CRM adoption, and it is currently only a placeholder concept.

### Dependencies

Company and contact models, email system, and report context.

### Estimated Complexity

Large

### Business Impact

High

---

## Task 5.4 – Implement opportunity scoring and recommendation engine

### Description

Build a scoring model that evaluates an opportunity or company using structured factors such as product relevance, regulatory readiness, company fit, and engagement history. Produce suggested next actions.

### Why it matters

The CRM should help teams prioritize limited time and attention.

### Dependencies

Opportunity intake and CRM data model.

### Estimated Complexity

Large

### Business Impact

High

---

## Task 5.5 – Implement service recommendations and next best actions

### Description

Recommend the most suitable next actions for the current account state, such as outreach, follow-up, meeting request, regulatory report share, or proposal preparation.

### Why it matters

AI value is highest when it helps humans take action quickly.

### Dependencies

Opportunity scoring, activity timeline, and task model.

### Estimated Complexity

Medium

### Business Impact

High

---

## Task 5.6 – Implement portfolio analysis for account planning

### Description

Create analysis views for a company’s portfolio, product relevance, and regulatory context so account teams can understand where the company fits within the broader MedNova offering.

### Why it matters

This creates strategic value beyond one-off opportunity handling.

### Dependencies

Product and company relationship data.

### Estimated Complexity

Medium

### Business Impact

Medium

---

# Phase 6 – Email System

This phase makes the CRM operational for sustained client communication.

## Task 6.1 – Build the email workflow foundation

### Description

Define the end-to-end lifecycle for communication: company → find contacts → generate email → edit draft → approve → send → track replies → follow-up → meeting → client conversion.

### Why it matters

A CRM is incomplete without a reliable communication loop.

### Dependencies

Contacts, companies, timeline, and task system.

### Estimated Complexity

Very Large

### Business Impact

Critical

---

## Task 6.2 – Implement email drafting and approval flow

### Description

Support the creation of drafts from company context, contact context, opportunity context, and prior interactions. Add approval and revision states before send.

### Why it matters

Email quality and governance matter for commercial execution and compliance.

### Dependencies

Email workflow foundation and AI drafting assistance.

### Estimated Complexity

Large

### Business Impact

High

---

## Task 6.3 – Implement outbound sending and delivery tracking

### Description

Add integrated outbound send support, status tracking, and delivery/engagement metadata. Capture failures and retries.

### Why it matters

The CRM must know whether outreach was delivered and whether action is needed.

### Dependencies

Email drafting and approval flow.

### Estimated Complexity

Large

### Business Impact

High

---

## Task 6.4 – Implement reply handling and follow-up automation

### Description

Capture replies, classify their intent, create follow-up tasks, and trigger meeting or proposal next steps automatically where appropriate.

### Why it matters

Communication should create action, not just history.

### Dependencies

Outbound sending and timeline engine.

### Estimated Complexity

Large

### Business Impact

High

---

## Task 6.5 – Implement meeting and client progression tracking

### Description

Allow email and workflow outcomes to progress the account toward a meeting, proposal, or client conversion. Track each historical step as a business event.

### Why it matters

The CRM should represent the real commercial progression of an account, not just contact records.

### Dependencies

Deal model and workflow state progression.

### Estimated Complexity

Medium

### Business Impact

High

---

# Phase 7 – Reporting

This phase converts CRM activity into usable management reporting.

## Task 7.1 – Build CRM analytics foundation

### Description

Create a reporting layer for company activity, task completion, outreach volume, pipeline movement, and engagement trends.

### Why it matters

Managers need explicit visibility into execution quality and pipeline health.

### Dependencies

CRM data model and activity timeline.

### Estimated Complexity

Large

### Business Impact

High

---

## Task 7.2 – Implement sales dashboard

### Description

Build a dashboard for active opportunities, pipeline stages, forecasted value, owner activity, and deal movement.

### Why it matters

Commercial leaders need fast visibility into current momentum and risk.

### Dependencies

Deal and activity models.

### Estimated Complexity

Medium

### Business Impact

High

---

## Task 7.3 – Implement opportunity dashboard

### Description

Present opportunities by company, product, region, stage, and priority, with trends and owner summaries.

### Why it matters

Opportunity prioritization depends on a clear operating view.

### Dependencies

Opportunity intake and CRM analytics foundation.

### Estimated Complexity

Medium

### Business Impact

High

---

## Task 7.4 – Implement PV, regulatory, and cross-functional dashboards

### Description

Create role-specific views for Pharmacovigilance, regulatory teams, and other functions that need intelligence from the CRM and the underlying MedNovaOS data.

### Why it matters

A CRM for MedNova should support cross-functional needs, not just sales.

### Dependencies

Analytics foundation and role-based access control.

### Estimated Complexity

Large

### Business Impact

Medium

---

## Task 7.5 – Implement export, print, and PDF workflows

### Description

Allow users to export CRM lists, company profiles, reports, and opportunity summaries to CSV, PDF, or printable layouts.

### Why it matters

CRM outputs are often required for internal review, external sharing, or account planning.

### Dependencies

Reporting layer and report persistence.

### Estimated Complexity

Medium

### Business Impact

Medium

---

# Phase 8 – Polish

This phase ensures the CRM can be used confidently in production.

## Task 8.1 – Improve performance and caching

### Description

Optimize database queries, reduce repeated data shaping, and add caching where it materially improves page loads and dashboard responsiveness.

### Why it matters

The CRM will become slow and frustrating if the data layer is not optimized early.

### Dependencies

CRM data model and API layer.

### Estimated Complexity

Medium

### Business Impact

High

---

## Task 8.2 – Improve responsive behavior and accessibility

### Description

Make the CRM usable and accessible on different screen sizes and for users with assistive needs.

### Why it matters

Production systems must work well in real-world conditions.

### Dependencies

Frontend implementation and UI refinement.

### Estimated Complexity

Medium

### Business Impact

High

---

## Task 8.3 – Strengthen error handling and empty states

### Description

Add clear error states, loading states, retry flows, and empty-state messaging so users understand what is happening when data is missing or incomplete.

### Why it matters

A polished CRM reduces uncertainty and support overhead.

### Dependencies

Core CRM workflows and frontend integration.

### Estimated Complexity

Small

### Business Impact

Medium

---

## Task 8.4 – Implement notifications and activity alerts

### Description

Add in-app notifications and alerting for tasks due soon, opportunities updated, email replies received, and workflow changes.

### Why it matters

Commercial teams need timely nudges to keep work moving.

### Dependencies

Tasks, timeline, and activity engine.

### Estimated Complexity

Medium

### Business Impact

Medium

---

## Task 8.5 – Harden security and auditability

### Description

Add logging, audit trails, permission validation, and defensive input handling across the CRM stack.

### Why it matters

A production CRM must be trustworthy, governable, and auditable.

### Dependencies

Authentication, authorization, and CRM entity operations.

### Estimated Complexity

Large

### Business Impact

Critical

---

## Task 8.6 – Expand automated testing and regression coverage

### Description

Add end-to-end and regression tests for company workflows, contact management, email flow, task lifecycle, pipeline movement, and report generation.

### Why it matters

The CRM will become too complex to maintain safely without strong automated coverage.

### Dependencies

Completed CRM workflows and API layer.

### Estimated Complexity

Medium

### Business Impact

High

---

# Recommended Execution Order

The roadmap should be executed in the following order:

1. Phase 1 – Foundation
2. Phase 2 – CRM Core
3. Phase 3 – Opportunity Workflow
4. Phase 6 – Email System
5. Phase 4 – Contact Intelligence
6. Phase 5 – AI
7. Phase 7 – Reporting
8. Phase 8 – Polish

This sequence prioritizes the capabilities that unlock the rest of the system.

---

# Prioritized Implementation Table

| Priority | Feature                                       | Complexity | Business Impact |
| -------- | --------------------------------------------- | ---------- | --------------- |
| 1        | Complete CRM database schema                  | Very Large | Critical        |
| 2        | Authentication and session handling           | Large      | Critical        |
| 3        | Role-based access control                     | Large      | Critical        |
| 4        | Company lifecycle workflow                    | Large      | Critical        |
| 5        | Contact management                            | Large      | Critical        |
| 6        | Opportunity-to-company conversion             | Medium     | Critical        |
| 7        | Deal and pipeline management                  | Large      | Critical        |
| 8        | Activity and timeline recording               | Medium     | High            |
| 9        | Tasks and notes                               | Medium     | High            |
| 10       | Opportunity intake from Green Book data       | Large      | Critical        |
| 11       | Report generation and persistence             | Large      | High            |
| 12       | Email workflow foundation                     | Very Large | Critical        |
| 13       | Contact discovery orchestration               | Large      | High            |
| 14       | Email drafting and approval flow              | Large      | High            |
| 15       | Opportunity scoring and recommendation engine | Large      | High            |
| 16       | Regulatory intelligence report generation     | Large      | High            |
| 17       | CRM analytics foundation                      | Large      | High            |
| 18       | Security hardening and auditability           | Large      | Critical        |
| 19       | Export, print, and PDF workflows              | Medium     | Medium          |
| 20       | Performance and caching                       | Medium     | High            |

---

# Recommended Next Build

## Single highest-value slice

### Authenticated company and contact management backbone

This is the single highest-value implementation slice to build next because it unlocks the most important operational behavior in the CRM with the least amount of unnecessary complexity. Once a company can be created, owned, updated, linked to contacts, and followed by tasks and activity history, the rest of the CRM becomes far more credible and useful.

### Why this slice matters most

- It creates the core business object model for the CRM.
- It enables real ownership, accountability, and workflow progression.
- It provides the foundation for later features such as outreach, deals, timeline logging, and reporting.
- It is the smallest slice that makes the CRM feel operational rather than decorative.

### Files likely to be touched

- [app.py](app.py)
- [backend/routes/**init**.py](backend/routes/__init__.py)
- [backend/services/**init**.py](backend/services/__init__.py)
- [database/schema.sql](database/schema.sql)
- [database/apply_migrations.py](database/apply_migrations.py)
- [database/init_db.py](database/init_db.py)
- [templates/base.html](templates/base.html)
- [templates/dashboard.html](templates/dashboard.html)
- [templates/opportunities.html](templates/opportunities.html)
- [templates/renewals.html](templates/renewals.html)
- [backend/sync/sync_engine.py](backend/sync/sync_engine.py)
- [backend/sync/mapper.py](backend/sync/mapper.py)
- [backend/cloud/supabase_client.py](backend/cloud/supabase_client.py)

### What this slice should deliver

- Secure company creation and editing
- Secure contact creation and linking
- Task creation and ownership
- Timeline entry creation
- Basic company profile persistence
- API endpoints for read/write operations
- Role-aware access to company and contact data

This is the best next milestone because it delivers a real working CRM core without overcommitting to AI, email, or reporting features too early.
