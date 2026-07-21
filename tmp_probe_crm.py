import requests
resp = requests.get('http://127.0.0.1:5000/api/growhub/crm/data', timeout=10)
print(resp.status_code)
print(resp.text[:2000])
