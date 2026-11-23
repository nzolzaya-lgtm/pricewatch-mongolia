from decimal import Decimal
from pathlib import Path
import gzip
import hashlib
import json
import random
import unittest

import pandas as pd

from prices import (basket_history, clean_quantities, compare_baskets, load_snapshot,
                    observed_price, price_change, quote_basket, shift_month, validate_data)

ROOT = Path(__file__).resolve().parents[1]


def example():
    rows = [
        ('A','rice','2025-10',100),('A','milk','2025-10',200),
        ('A','rice','2026-08',200),('A','milk','2026-08',300),
        ('A','rice','2026-09',None),('A','milk','2026-09',350),
        ('A','rice','2026-10',250),('A','milk','2026-10',400),
        ('B','rice','2026-10',10),('B','milk','2026-10',None),
        ('C','rice','2026-10',200),('C','milk','2026-10',350),
    ]
    return pd.DataFrame([{'region_code':r,'product_code':p,'month':m,'price_mnt':v,
                          'value_status':'observed' if v is not None else 'missing'} for r,p,m,v in rows])


class BasketTests(unittest.TestCase):
    def setUp(self): self.df=example()

    def test_exact_quantity_multiplication(self):
        q=quote_basket(self.df,'A','2026-10',{'rice':'2.5','milk':2})
        self.assertEqual(q.total,Decimal('1425'))

    def test_zero_quantity_is_not_a_missing_item(self):
        q=quote_basket(self.df,'B','2026-10',{'rice':3,'milk':0})
        self.assertEqual(q.total,Decimal('30'))

    def test_missing_price_does_not_create_a_cheaper_full_basket(self):
        q=quote_basket(self.df,'B','2026-10',{'rice':2,'milk':2})
        self.assertIsNone(q.total)
        self.assertEqual(q.known_subtotal,Decimal('20'))
        self.assertEqual(q.missing,('milk',))

    def test_comparison_ranks_only_complete_baskets(self):
        regions=[{'code':x,'name':x} for x in ['A','B','C']]
        ranking=compare_baskets(self.df,'2026-10',{'rice':2,'milk':2},regions)
        self.assertEqual(ranking.iloc[0].region_code,'C')
        self.assertEqual(ranking.iloc[-1].region_code,'B')
        self.assertTrue(pd.isna(ranking.iloc[-1].total))

    def test_history_keeps_missing_full_total(self):
        h=basket_history(self.df,'A',{'rice':2,'milk':2}).set_index('month')
        self.assertTrue(pd.isna(h.loc['2026-09','total']))
        self.assertEqual(h.loc['2026-10','total'],1300)

    def test_previous_calendar_month_is_not_previous_available_observation(self):
        self.assertIsNone(price_change(self.df,'A','rice','2026-10'))

    def test_year_on_year_matches_same_month(self):
        self.assertEqual(price_change(self.df,'A','rice','2026-10',12),150)

    def test_missing_current_price_has_no_change(self):
        self.assertIsNone(price_change(self.df,'A','rice','2026-09'))

    def test_negative_nonfinite_and_excessive_quantities_are_rejected(self):
        for value in [-1,'nan','inf',10001,'x']:
            with self.subTest(value=value),self.assertRaises(ValueError):clean_quantities({'rice':value})

    def test_empty_and_zero_only_baskets_are_rejected(self):
        for values in [{},{'rice':0}]:
            with self.assertRaises(ValueError):clean_quantities(values)

    def test_unknown_region_product_or_month_is_rejected(self):
        for r,m,q in [('Z','2026-10',{'rice':1}),('A','2030-01',{'rice':1}),('A','2026-10',{'other':1})]:
            with self.assertRaises(ValueError):quote_basket(self.df,r,m,q)

    def test_month_shift_crosses_year_boundary(self):
        self.assertEqual(shift_month('2026-01',-1),'2025-12')


class RealSnapshotTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.df,cls.cat,cls.meta=load_snapshot()

    def test_snapshot_dimensions_and_reported_values(self):
        self.assertEqual(len(self.cat['regions']),22)
        self.assertEqual(len(self.cat['products']),43)
        self.assertEqual(sum(p['grocery'] for p in self.cat['products']),27)
        self.assertEqual(self.df.value_status.eq('observed').sum(),self.meta['value_counts']['observed'])

    def test_aggregated_regions_are_excluded(self):
        self.assertTrue(all(len(code)==3 for code in self.df.region_code.unique()))
        self.assertIn('511',self.df.region_code.unique())
        self.assertNotIn('5',self.df.region_code.unique())

    def test_raw_source_checksum_and_independent_value_sample(self):
        raw=gzip.decompress((ROOT/'data/nso_response.json.gz').read_bytes())
        self.assertEqual(hashlib.sha256(raw).hexdigest(),self.meta['raw_response_sha256'])
        source=json.loads(raw)
        meta=json.loads((ROOT/'data/nso_metadata_en.json').read_text())
        variables={v['text']:v for v in meta['variables']}
        month_map=dict(zip(variables['Month']['values'],variables['Month']['valueTexts']))
        dims=[c['code'] for c in source['columns'] if c['type']!='c']
        lookup=self.df.set_index(['region_code','product_code','month'])
        for entry in random.Random(2026).sample(source['data'],75):
            keys=dict(zip(dims,entry['key']))
            identity=(keys[variables['Region']['code']],keys[variables['Goods and services']['code']],month_map[keys[variables['Month']['code']]])
            value=entry['values'][0]
            row=lookup.loc[identity]
            if row.value_status=='observed':self.assertEqual(Decimal(str(row.price_mnt)),Decimal(str(value)))
            else:self.assertTrue(pd.isna(row.price_mnt))

    def test_source_units_are_not_swapped(self):
        products={p['code']:p for p in self.cat['products']}
        self.assertEqual(products['0']['unit'],'kg')
        self.assertEqual(products['14']['unit'],'piece')
        self.assertEqual(products['11']['unit'],'litre')
        self.assertEqual(products['24']['unit'],'bulb')

    def test_real_basket_total_matches_separate_sum(self):
        month=self.meta['latest_month']; amounts={'0':2,'2':1,'11':2,'14':6,'25':2}
        quote=quote_basket(self.df,'511',month,amounts)
        selection=self.df[self.df.region_code.eq('511') & self.df.month.eq(month)].set_index('product_code')
        expected=sum(Decimal(str(selection.loc[k,'price_mnt']))*v for k,v in amounts.items())
        self.assertEqual(quote.total,expected)

    def test_duplicates_cannot_silently_inflate_totals(self):
        doubled=pd.concat([self.df,self.df.iloc[:1]],ignore_index=True)
        with self.assertRaises(ValueError):validate_data(doubled,self.cat)


if __name__=='__main__':unittest.main()
