import sqlite3
from pathlib import Path
p = Path('database/nafdac_intelligence.db')
conn = sqlite3.connect(p)
conn.row_factory = sqlite3.Row
for name in ['crm_companies','crm_contacts','crm_tasks','crm_activities','crm_notes','crm_deals']:
    row = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone()
    print('TABLE', name, 'exists=', bool(row))
    if row:
        print(conn.execute(f'PRAGMA table_info({name})').fetchall())
        print('COUNT', conn.execute(f'SELECT COUNT(*) as c FROM {name}').fetchone()['c'])
conn.close()
