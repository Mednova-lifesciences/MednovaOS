import json
import sqlite3
import urllib.request

conn = sqlite3.connect('database/nafdac_intelligence.db')
conn.row_factory = sqlite3.Row
row = conn.execute('SELECT id, crm_company_id, title, stage FROM crm_deals ORDER BY id LIMIT 1').fetchone()
print('row', tuple(row))
if row is None:
    raise SystemExit(0)
req = urllib.request.Request(
    f"http://127.0.0.1:5000/api/crm/companies/{row['crm_company_id']}/deals/{row['id']}",
    data=json.dumps({'stage': 'qualified'}).encode(),
    headers={'Content-Type': 'application/json'},
    method='PATCH',
)
with urllib.request.urlopen(req) as resp:
    print('status', resp.status)
    print(resp.read().decode())
print('after', conn.execute('SELECT stage FROM crm_deals WHERE id = ?', (row['id'],)).fetchone()['stage'])
conn.close()
