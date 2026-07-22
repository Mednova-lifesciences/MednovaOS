import os, tempfile, sqlite3, importlib
p = tempfile.NamedTemporaryFile(suffix='.sqlite', delete=False)
path = p.name
p.close()
print('DB PATH', path)
os.environ['MEDNOVA_DB_PATH'] = path
import app as app_module
importlib.reload(app_module)
# inspect crm_companies
with sqlite3.connect(path) as conn:
    try:
        rows = conn.execute('SELECT id, company_name FROM crm_companies').fetchall()
    except Exception as e:
        print('ERROR', e)
        rows = []
print('ROWS BEFORE', rows)
# call endpoint to create company
client = app_module.app.test_client()
resp = client.post('/api/crm/companies/from-opportunity', json={'company':'Test Co','company_name':'Test Co'})
print('STATUS', resp.status_code)
print('JSON', resp.get_json())
with sqlite3.connect(path) as conn:
    rows_after = conn.execute('SELECT id, company_name FROM crm_companies').fetchall()
print('ROWS AFTER', rows_after)
