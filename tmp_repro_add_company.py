import app as app_module
client = app_module.app.test_client()
resp = client.post('/api/crm/companies/from-opportunity', json={'company_name':'Acme Pharmaceuticals','company':'Acme Pharmaceuticals','source':'Green Book'})
print(resp.status_code)
print(resp.get_json())
