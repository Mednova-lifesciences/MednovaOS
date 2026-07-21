import requests, re, json
from pprint import pprint

url = 'https://greenbook.nafdac.gov.ng/'
s = requests.Session()
s.headers.update({
    'User-Agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36',
    'Accept':'application/json, text/plain, */*',
    'X-Requested-With':'XMLHttpRequest',
    'Referer':'https://greenbook.nafdac.gov.ng/'
})
payload = {
    'draw': '1',
    'columns[0][data]':'product_name',
    'columns[0][name]':'product_name',
    'columns[0][searchable]':'true',
    'columns[0][orderable]':'true',
    'columns[0][search][value]':'',
    'columns[0][search][regex]':'false',
    'start':'0',
    'length':'10',
    'search[value]':'',
    'search[regex]':'false',
    'order[0][column]':'0',
    'order[0][dir]':'asc',
    'search_ingredient':'',
}
r = s.get(url, params=payload, timeout=30)
print('status', r.status_code)
print('final_url', r.url)
print('content-type', r.headers.get('content-type'))
print('text-start', r.text[:2000])
try:
    j = r.json()
    print('json-keys', list(j.keys())[:20])
    print('data-len', len(j.get('data', [])))
    print('first-item', j.get('data', [{}])[0] if j.get('data') else None)
except Exception as e:
    print('json-error', e)
