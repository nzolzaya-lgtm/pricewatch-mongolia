"""Download an NSO PxWeb table and publish validated, reproducible data files.

Nothing is fabricated or carried forward. Missing and zero source values remain
unavailable for basket calculations. Run from any working directory with Python.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request, urlopen
import time
import csv
import gzip
import hashlib
import io
import json
import os
import requests
import sys

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'data'
CACHE = ROOT / '.fetch_cache'
SESSION = requests.Session()
RETRIEVAL_TIMES = {}
TABLE = 'DT_NSO_0600_019V1.px'
API = 'https://data.1212.mn/api/v1/{lang}/NSO/' + quote('Economy, environment/Consumer Price Index/' + TABLE, safe='/')
SOURCE_PAGE = 'https://data.1212.mn/pxweb/en/NSO/NSO__Economy,%20environment__Consumer%20Price%20Index/' + TABLE + '/'

# Short display names and units describe the source's exact commodities; the
# untouched English and Mongolian labels are also retained in the catalogue.
PRODUCTS = {
 '0': ('Rice', 'Grains & bread', 'kg', True),
 '1': ('Sliced bread', 'Grains & bread', 'piece', True),
 '2': ('Flour · first grade', 'Grains & bread', 'kg', True),
 '3': ('Flour · second grade', 'Grains & bread', 'kg', True),
 '4': ('Millet', 'Grains & bread', 'kg', True),
 '5': ('Beef · bone-in', 'Meat & poultry', 'kg', True),
 '6': ('Beef · boneless', 'Meat & poultry', 'kg', True),
 '7': ('Mutton · bone-in', 'Meat & poultry', 'kg', True),
 '8': ('Goat meat · bone-in', 'Meat & poultry', 'kg', True),
 '9': ('Chicken thigh', 'Meat & poultry', 'kg', True),
 '10': ('Horse meat · bone-in', 'Meat & poultry', 'kg', True),
 '11': ('Cow milk · plain', 'Dairy & eggs', 'litre', True),
 '12': ('Milk · carton', 'Dairy & eggs', 'litre', True),
 '13': ('Plain yogurt', 'Dairy & eggs', 'litre', True),
 '14': ('Egg', 'Dairy & eggs', 'piece', True),
 '15': ('Vegetable oil', 'Pantry', 'litre', True),
 '16': ('Orange', 'Fruit & vegetables', 'kg', True),
 '17': ('Yellow apples', 'Fruit & vegetables', 'kg', True),
 '18': ('Raisins', 'Fruit & vegetables', 'kg', True),
 '19': ('Cabbage', 'Fruit & vegetables', 'kg', True),
 '20': ('Tomatoes', 'Fruit & vegetables', 'kg', True),
 '21': ('Sweet pepper', 'Fruit & vegetables', 'kg', True),
 '22': ('Carrots', 'Fruit & vegetables', 'kg', True),
 '23': ('Onion', 'Fruit & vegetables', 'kg', True),
 '24': ('Garlic', 'Fruit & vegetables', 'bulb', True),
 '25': ('Potato · domestic', 'Fruit & vegetables', 'kg', True),
 '26': ('Sugar', 'Pantry', 'kg', True),
 '27': ('Vodka · 0.75 litre', 'Other goods', 'bottle', False),
 '28': ('Beer · 0.5 litre', 'Other goods', 'bottle', False),
 '29': ('Cigarettes · imported', 'Other goods', 'source unit', False),
 '30': ('Cigarettes · domestic', 'Other goods', 'source unit', False),
 '31': ('Cement', 'Household & fuel', 'bag', False),
 '32': ('Fuelwood', 'Household & fuel', 'sack', False),
 '33': ('Laundry soap', 'Household & fuel', 'source unit', False),
 '34': ('Washing powder · 800 g', 'Household & fuel', 'pack', False),
 '35': ('Dishwashing liquid · 500 ml', 'Household & fuel', 'bottle', False),
 '36': ('Matches · 10 boxes', 'Household & fuel', '10-box pack', False),
 '37': ('AI-92 gasoline', 'Household & fuel', 'litre', False),
 '38': ('Diesel fuel', 'Household & fuel', 'litre', False),
 '39': ('Canteen food', 'Services', 'source meal', False),
 '40': ('Men’s haircut', 'Services', 'haircut', False),
 '41': ('Women’s simple haircut', 'Services', 'haircut', False),
 '42': ('Soap', 'Household & fuel', 'source unit', False),
}


def fetch(url, query=None):
    key = hashlib.sha256((url + json.dumps(query, ensure_ascii=False)).encode()).hexdigest()
    CACHE.mkdir(exist_ok=True)
    cached = CACHE / (key + '.json')
    if cached.exists():
        print('Using a completed response from this retrieval cache.', flush=True)
        RETRIEVAL_TIMES[key] = datetime.fromtimestamp(cached.stat().st_mtime, timezone.utc)
        return cached.read_bytes()
    for attempt in range(2):
        try:
            print(('GET ' if query is None else 'POST ') + url, flush=True)
            response = SESSION.get(url, timeout=(15, 45)) if query is None else SESSION.post(url, json=query, timeout=(15, 45))
            response.raise_for_status()
            raw = response.content
            json.loads(raw)
            atomic_write(cached, raw)
            RETRIEVAL_TIMES[key] = datetime.now(timezone.utc)
            return raw
        except (requests.RequestException, json.JSONDecodeError):
            if attempt: raise
            print('Retrying a temporary source request failure.', flush=True)
            time.sleep(1)


def encode_json(value):
    return json.dumps(value, ensure_ascii=False, indent=2).encode('utf-8')


def atomic_write(path, data):
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_bytes(data)
    os.replace(temp, path)


def build_snapshot():
    DATA.mkdir(parents=True, exist_ok=True)
    meta_raw = fetch(API.format(lang='en'))
    meta = json.loads(meta_raw)
    mn_raw = fetch(API.format(lang='mn'))
    mn = json.loads(mn_raw)
    variables = meta['variables']
    by_label = {v['text']: v for v in variables}
    region_var, product_var, month_var = (by_label[n] for n in ('Region', 'Goods and services', 'Month'))
    # The source contains broad-region aggregates and a second Ulaanbaatar
    # heading. Only the 22 three-digit administrative entries are compared.
    region_codes = [c for c in region_var['values'] if len(c) == 3]
    assert len(region_codes) == 22 and '511' in region_codes
    selected = {region_var['code']: region_codes}
    query = {'query': [{'code': v['code'], 'selection': {'filter': 'item', 'values': selected.get(v['code'], v['values'])}} for v in variables], 'response': {'format': 'json'}}
    raw = fetch(API.format(lang='en'), query)
    source = json.loads(raw)
    if 'data' not in source or 'columns' not in source:
        raise ValueError('NSO returned an unexpected table response; existing files are untouched.')
    dimensions = [c['code'] for c in source['columns'] if c['type'] != 'c']
    lookups = {v['code']: dict(zip(v['values'], v['valueTexts'])) for v in variables}
    mn_lookups = {v['code']: dict(zip(v['values'], v['valueTexts'])) for v in mn['variables']}
    rows, seen, counts = [], set(), Counter()
    for item in source['data']:
        keys = dict(zip(dimensions, item['key']))
        rc, pc, mc = (keys[v['code']] for v in (region_var, product_var, month_var))
        month = lookups[month_var['code']][mc]
        identity = (rc, pc, month)
        if identity in seen:
            raise ValueError(f'Duplicate source observation: {identity}')
        seen.add(identity)
        value = item['values'][0]
        amount = ''
        try:
            number = Decimal(str(value))
            if not number.is_finite(): status = 'missing'
            elif number <= 0: status = 'nonpositive_source_value'
            else:
                status = 'observed'
                amount = format(number, 'f')
        except (InvalidOperation, ValueError, TypeError):
            status = 'missing'
        counts[status] += 1
        rows.append({'region_code': rc, 'product_code': pc, 'month': month, 'price_mnt': amount, 'value_status': status})
    expected = len(region_codes) * len(product_var['values']) * len(month_var['values'])
    if len(rows) != expected or not counts['observed']:
        raise ValueError(f'Incomplete source grid ({len(rows)} rows, expected {expected}); existing files are untouched.')
    rows.sort(key=lambda r: (r['month'], r['region_code'], int(r['product_code'])))
    buf = io.StringIO(newline='')
    writer = csv.DictWriter(buf, fieldnames=list(rows[0]))
    writer.writeheader(); writer.writerows(rows)
    csv_raw = buf.getvalue().encode('utf-8')
    catalogue = {'regions': [], 'products': []}
    for code in region_codes:
        name = lookups[region_var['code']][code].strip()
        catalogue['regions'].append({'code': code, 'name': name, 'name_mn': mn_lookups[region_var['code']].get(code, name).strip()})
    for code, source_label in lookups[product_var['code']].items():
        name, category, unit, food = PRODUCTS[code]
        catalogue['products'].append({'code': code, 'name': name, 'name_mn': mn_lookups[product_var['code']].get(code, source_label).strip(), 'source_label': source_label.strip(), 'category': category, 'unit': unit, 'grocery': food})
    catalogue['products'].sort(key=lambda p: (not p['grocery'], p['category'], p['name']))
    catalogue['regions'].sort(key=lambda r: r['name'])
    observed_months = sorted({r['month'] for r in rows if r['value_status'] == 'observed'})
    manifest = {
        'title': meta['title'], 'table_id': TABLE, 'source': 'National Statistics Office of Mongolia',
        'source_url': SOURCE_PAGE, 'api_url': API.format(lang='en'),
        'retrieved_at_utc': RETRIEVAL_TIMES[hashlib.sha256((API.format(lang='en') + json.dumps(query, ensure_ascii=False)).encode()).hexdigest()].isoformat(timespec='seconds'),
        'frequency': 'monthly', 'currency': 'MNT', 'first_month': min(observed_months), 'latest_month': max(observed_months),
        'regions': len(region_codes), 'products': len(product_var['values']), 'grocery_products': sum(p['grocery'] for p in catalogue['products']),
        'row_count': len(rows), 'value_counts': dict(counts), 'raw_response_sha256': hashlib.sha256(raw).hexdigest(),
        'prices_csv_sha256': hashlib.sha256(csv_raw).hexdigest(),
        'missing_policy': 'Missing, nonfinite, and nonpositive source values are unavailable. No imputation, carry-forward, currency conversion, or synthetic prices.',
        'scope': 'Regional monthly average prices. Individual shop prices, promotions, delivery fees, and stock are not present.',
    }
    outputs = {
        'prices.csv': csv_raw, 'catalogue.json': encode_json(catalogue), 'snapshot.json': encode_json(manifest),
        'nso_metadata_en.json': meta_raw, 'nso_metadata_mn.json': mn_raw,
        'nso_query.json': encode_json(query), 'nso_response.json.gz': gzip.compress(raw, mtime=0),
    }
    # Validate everything before replacing the individually atomic data files.
    for filename, data in outputs.items(): atomic_write(DATA / filename, data)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    if '--fresh' in sys.argv:
        for path in CACHE.glob('*.json'):
            path.unlink()
    build_snapshot()
