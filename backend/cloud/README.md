# Cloud mirror layer

This package adds a Supabase mirror for the existing SQLite sync pipeline.

## What is included
- `supabase_client.py` loads `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` from `.env` and creates an authenticated Supabase client.
- `sync_to_supabase.py` syncs SQLite rows into Supabase tables for products, manufacturers, applicants, renewal alerts, opportunities, and sync history.
- The Flask app exposes `/admin/cloud-sync` and `/admin/cloud-sync/status` without changing the existing UI or SQLite workflow.

## How to run

```bash
python backend/cloud/sync_to_supabase.py
```

## How to test

```bash
curl -X POST http://127.0.0.1:5000/admin/cloud-sync
curl http://127.0.0.1:5000/admin/cloud-sync/status
```

> The remote Supabase tables must already exist in the target project for the mirror sync to insert rows successfully.
