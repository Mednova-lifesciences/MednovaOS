# Architecture Overview

## Summary
The legacy MedNova platform is a Flask-based regulatory intelligence application centered on product portfolio visibility, renewal risk tracking, opportunity monitoring, and sync health.

## Runtime Shape
- Flask handles the request layer and server-rendered page responses.
- Jinja templates render the dashboard and module views.
- Repository modules provide normalized data access for products, renewals, and opportunities.
- The sync layer ingests Green Book data, updates the local database, and optionally sends rows to Supabase.

## Major Areas
- [06-architecture.md](06-architecture.md) — detailed architecture and module boundaries
- [07-technical-stack.md](07-technical-stack.md) — runtime and dependency choices
- [08-data-model-and-schema.md](08-data-model-and-schema.md) — entities and schema structure
- [11-greenbook-sync-and-data-ingestion.md](11-greenbook-sync-and-data-ingestion.md) — ingestion workflow

## Scope Guardrail
This architecture document remains focused on the legacy MedNova platform and does not include CRM workflows or sales automation modules.
