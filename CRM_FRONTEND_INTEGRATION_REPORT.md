# CRM frontend integration report

## Summary
The Lovable CRM frontend is now consuming the live Flask-backed CRM APIs for the core company workflow experience. The UI shell remains intact, but the data layer now points at the real backend rather than the old mock seed service.

## What is now connected
- Shared API layer: [mednova-grow-hub/src/lib/api/index.ts](mednova-grow-hub/src/lib/api/index.ts)
  - Loads company, contact, activity, task, note, deal, email, and product data from the Flask backend.
  - Normalizes payloads from the backend into the frontend’s expected CRM model.
  - Exposes create and completion helpers for contacts, tasks, notes, and task completion.

- Dashboard and list pages:
  - [mednova-grow-hub/src/routes/index.tsx](mednova-grow-hub/src/routes/index.tsx)
  - [mednova-grow-hub/src/routes/companies.index.tsx](mednova-grow-hub/src/routes/companies.index.tsx)
  - [mednova-grow-hub/src/routes/contacts.tsx](mednova-grow-hub/src/routes/contacts.tsx)
  - [mednova-grow-hub/src/routes/tasks.tsx](mednova-grow-hub/src/routes/tasks.tsx)
  - [mednova-grow-hub/src/routes/activities.tsx](mednova-grow-hub/src/routes/activities.tsx)
  - [mednova-grow-hub/src/routes/deals.tsx](mednova-grow-hub/src/routes/deals.tsx)
  - [mednova-grow-hub/src/routes/emails.tsx](mednova-grow-hub/src/routes/emails.tsx)
  - [mednova-grow-hub/src/routes/reports.tsx](mednova-grow-hub/src/routes/reports.tsx)

- Company profile experience:
  - [mednova-grow-hub/src/routes/companies.$companyId.tsx](mednova-grow-hub/src/routes/companies.$companyId.tsx)
  - Uses the live company detail endpoint for company metadata, contacts, products, tasks, notes, and activity timeline.

## Backend endpoints used
- GET /api/crm/companies/<company_id>
- POST /api/crm/companies/<company_id>/contacts
- POST /api/crm/companies/<company_id>/tasks
- POST /api/crm/companies/<company_id>/notes
- POST /api/crm/companies/<company_id>/tasks/<task_id>/complete
- GET /api/growhub/crm/data (fallback envelope loader)

## What still uses placeholder content
- Deal and email panels remain intentionally lightweight because the current backend contract does not expose richer deal/email CRUD flows.
- The profile page still keeps the existing UI shell and does not add new backend features; it simply renders the data returned by the current API.

## What can be removed next
- The old mock seed module at [mednova-grow-hub/src/lib/mock-data/index.ts](mednova-grow-hub/src/lib/mock-data/index.ts) is no longer part of the live path and can be removed once the remaining route text and legacy references are cleaned up.
- Any dead mock-specific imports or comments can be removed in a follow-up cleanup pass.

## Validation
- Backend workflow regression tests: passed.
- Frontend build: passed via npm run build in the mednova-grow-hub workspace.
