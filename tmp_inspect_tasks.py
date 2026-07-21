import json
import sqlite3
from pathlib import Path

root = Path(r"c:/Users/DELL/Downloads/mednova_os_web 6/mednova_os_web 6")
db = root / "database" / "nafdac_intelligence.db"
conn = sqlite3.connect(db)
conn.row_factory = sqlite3.Row
print('crm_tasks_exists', conn.execute("select name from sqlite_master where type='table' and name='crm_tasks'").fetchone() is not None)
print('columns', [row[1] for row in conn.execute('pragma table_info(crm_tasks)')])
rows = conn.execute('select * from crm_tasks limit 5').fetchall()
print(json.dumps([dict(r) for r in rows], indent=2, default=str))
conn.close()
