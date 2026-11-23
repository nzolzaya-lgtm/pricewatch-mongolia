"""PriceWatch's source validation, exact basket maths and comparable statistics."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Mapping
import hashlib
import json

import pandas as pd

DATA = Path(__file__).resolve().parent / 'data'


@dataclass(frozen=True)
class BasketQuote:
    region_code: str
    month: str
    lines: tuple[dict, ...]
    known_subtotal: Decimal
    total: Decimal | None
    missing: tuple[str, ...]

    @property
    def complete(self):
        return self.total is not None


def load_snapshot(directory: Path = DATA):
    snapshot = json.loads((directory / 'snapshot.json').read_text())
    catalogue = json.loads((directory / 'catalogue.json').read_text())
    raw = (directory / 'prices.csv').read_bytes()
    if hashlib.sha256(raw).hexdigest() != snapshot['prices_csv_sha256']:
        raise ValueError('The price file does not match its saved source snapshot. Refresh the complete data package.')
    df = pd.read_csv(directory / 'prices.csv', dtype={'region_code': str, 'product_code': str, 'month': str}, keep_default_na=True)
    validate_data(df, catalogue, snapshot)
    return df, catalogue, snapshot


def validate_data(df, catalogue, snapshot=None):
    required = {'region_code', 'product_code', 'month', 'price_mnt', 'value_status'}
    if not required.issubset(df.columns): raise ValueError('The price file is missing required columns.')
    if df.duplicated(['region_code', 'product_code', 'month']).any(): raise ValueError('Duplicate price observations are not allowed.')
    if not set(df.region_code).issubset({r['code'] for r in catalogue['regions']}): raise ValueError('Unknown region in the price file.')
    if not set(df.product_code).issubset({p['code'] for p in catalogue['products']}): raise ValueError('Unknown product in the price file.')
    if not df.month.str.fullmatch(r'\d{4}-(0[1-9]|1[0-2])').all(): raise ValueError('Invalid source month.')
    observed = df.value_status.eq('observed')
    if df.loc[observed, 'price_mnt'].isna().any() or not df.loc[observed, 'price_mnt'].gt(0).all(): raise ValueError('An observed price must be positive and present.')
    if df.loc[~observed, 'price_mnt'].notna().any(): raise ValueError('Unavailable observations must not contain usable prices.')
    if snapshot is not None and len(df) != snapshot['row_count']: raise ValueError('The saved row count does not match the price file.')


def clean_quantities(quantities: Mapping[str, object]) -> dict[str, Decimal]:
    result = {}
    for product, raw in quantities.items():
        try: value = Decimal(str(raw))
        except (InvalidOperation, TypeError, ValueError): raise ValueError('Enter a valid quantity for each product.') from None
        if not value.is_finite() or value < 0 or value > 10000: raise ValueError('Quantities must be from 0 to 10,000 source units.')
        if value > 0: result[str(product)] = value
    if not result: raise ValueError('Add at least one product with a quantity above zero.')
    return result


def quote_basket(df, region_code: str, month: str, quantities: Mapping[str, object]) -> BasketQuote:
    amounts = clean_quantities(quantities)
    if region_code not in set(df.region_code): raise ValueError('Choose a region present in this snapshot.')
    if month not in set(df.month): raise ValueError('Choose a month present in this snapshot.')
    unknown = set(amounts) - set(df.product_code)
    if unknown: raise ValueError('This basket contains an unknown product.')
    selection = df.loc[df.region_code.eq(region_code) & df.month.eq(month)].set_index('product_code')
    subtotal = Decimal('0')
    lines, missing = [], []
    for code, quantity in amounts.items():
        unit_price, line_total = None, None
        if code in selection.index:
            row = selection.loc[code]
            if row['value_status'] == 'observed' and pd.notna(row['price_mnt']) and row['price_mnt'] > 0:
                unit_price = Decimal(str(row['price_mnt']))
                line_total = unit_price * quantity
                subtotal += line_total
        if unit_price is None: missing.append(code)
        lines.append({'product_code': code, 'quantity': quantity, 'unit_price': unit_price, 'line_total': line_total})
    return BasketQuote(region_code, month, tuple(lines), subtotal, None if missing else subtotal, tuple(missing))


def compare_baskets(df, month, quantities, regions):
    amounts = clean_quantities(quantities)
    rows = []
    for region in regions:
        quote = quote_basket(df, region['code'], month, amounts)
        rows.append({'region_code': region['code'], 'region': region['name'],
                     'total': float(quote.total) if quote.complete else None,
                     'known_subtotal': float(quote.known_subtotal),
                     'available_items': len(quote.lines) - len(quote.missing),
                     'requested_items': len(quote.lines), 'complete': quote.complete})
    return pd.DataFrame(rows).sort_values(['complete', 'total', 'region'], ascending=[False, True, True], na_position='last').reset_index(drop=True)


def basket_history(df, region_code, quantities, months=None):
    amounts = clean_quantities(quantities)
    dates = sorted(months if months is not None else df.month.unique())
    subset = df.loc[df.region_code.eq(region_code) & df.product_code.isin(amounts)]
    pivot = subset.pivot(index='month', columns='product_code', values='price_mnt').reindex(index=dates, columns=list(amounts))
    weighted = pivot.mul(pd.Series({k: float(v) for k, v in amounts.items()}), axis='columns')
    result = weighted.sum(axis=1, min_count=len(amounts)).rename('total').reset_index()
    result['available_items'] = pivot.notna().sum(axis=1).to_numpy()
    return result


def shift_month(month, delta):
    return str(pd.Period(month, freq='M') + delta)


def observed_price(df, region_code, product_code, month):
    rows = df.loc[df.region_code.eq(region_code) & df.product_code.eq(product_code) & df.month.eq(month) & df.value_status.eq('observed')]
    if rows.empty: return None
    value = rows.iloc[0]['price_mnt']
    return None if pd.isna(value) else float(value)


def price_change(df, region_code, product_code, month, months_back=1):
    current = observed_price(df, region_code, product_code, month)
    previous = observed_price(df, region_code, product_code, shift_month(month, -months_back))
    if current is None or previous is None or previous <= 0: return None
    return (current / previous - 1) * 100


def export_observations(df, catalogue):
    products = {p['code']: p for p in catalogue['products']}
    regions = {r['code']: r for r in catalogue['regions']}
    out = df.copy()
    out['region'] = out.region_code.map(lambda c: regions[c]['name'])
    out['product'] = out.product_code.map(lambda c: products[c]['source_label'])
    out['source_unit'] = out.product_code.map(lambda c: products[c]['unit'])
    return out[['month', 'region', 'product', 'source_unit', 'price_mnt', 'value_status', 'region_code', 'product_code']]


def format_money(value, decimals=0):
    if value is None or pd.isna(value): return 'Not available'
    rounded = Decimal(str(value)).quantize(Decimal('0.01') if decimals else Decimal('1'), rounding=ROUND_HALF_UP)
    return f'₮{rounded:,.{decimals}f}'


def basket_text(quote, products, region_name, source_url):
    lines = ['PriceWatch Mongolia · Grocery basket', f'{region_name} · {quote.month}',
             'Based on regional monthly average prices from Mongolia’s NSO.', '']
    for item in quote.lines:
        product = products[item['product_code']]
        cost = format_money(item['line_total'], 2)
        lines.append(f"{product['name']} · {item['quantity']:g} {product['unit']} · {cost}")
    lines += ['', ('Estimated basket total: ' + format_money(quote.total, 2)) if quote.complete else
              ('Basket total unavailable: some prices are missing. Known subtotal: ' + format_money(quote.known_subtotal, 2)),
              '', 'This is an average-price estimate, not an individual shop quote or stock check.', 'Source: ' + source_url]
    return '\n'.join(lines)
