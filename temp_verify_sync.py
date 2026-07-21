from backend.cloud.sync_to_supabase import sync_sqlite_to_supabase
from backend.cloud.supabase_client import get_supabase
import json

summary = sync_sqlite_to_supabase()
client = get_supabase()
print('SUMMARY')
print(json.dumps(summary, indent=2))
print('COUNTS')
for table in ['products','manufacturers','applicants','renewal_alerts','opportunities','sync_history']:
    try:
        resp = client.table(table).select('id', count='exact').execute()
        print(table, getattr(resp, 'count', len(resp.data or [])))
    except Exception as exc:
        print(table, 'ERR', exc)
