import requests
resp = requests.get('http://127.0.0.1:5000/api/growhub/crm/data', timeout=10)
payload = resp.json()
print('keys', sorted(payload.keys()))
for key in ['companies','contacts','activities','tasks','notes','deals','emails','products']:
    print(key, len(payload.get(key, [])))
print('first company', payload.get('companies', [{}])[0] if payload.get('companies') else None)
