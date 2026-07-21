import sqlite3
from pathlib import Path
p = Path('database/nafdac_intelligence.db').resolve()
print('DB_EXISTS', p.exists())
conn = sqlite3.connect(p)
cur = conn.cursor()
rows = cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
print('TABLES')
for (name,) in rows:
    if 'crm' in name.lower() or name in {'products','applicants','manufacturers','categories','dosage_forms','routes','sync_history','product_changes','renewal_alerts','watchlist','search_cache'}:
        print(name)
conn.close()
