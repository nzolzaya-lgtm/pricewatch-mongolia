from __future__ import annotations

from datetime import datetime, timedelta, timezone
from html import escape
from pathlib import Path
import json

import pandas as pd
import streamlit as st

from downloads import download_file
from prices import (basket_history, basket_text, compare_baskets, export_observations,
                    format_money as money, load_snapshot, observed_price, price_change,
                    quote_basket, shift_month)

BASE = Path(__file__).resolve().parent
st.set_page_config(page_title='PriceWatch Mongolia', page_icon='₮', layout='wide', initial_sidebar_state='expanded')
st.markdown('<style>' + (BASE/'assets/style.css').read_text() + '</style>', unsafe_allow_html=True)


@st.cache_data(show_spinner='Opening the official price snapshot…')
def get_data():
    return load_snapshot()


try:
    prices, catalogue, snapshot = get_data()
except (OSError, ValueError, KeyError) as error:
    st.error('The official price snapshot could not be opened. Please restore or refresh the data files.')
    st.code(str(error))
    st.stop()

PRODUCTS = {p['code']: p for p in catalogue['products']}
REGIONS = {r['code']: r for r in catalogue['regions']}
REGION_CODES = list(REGIONS)
FOODS = [p['code'] for p in catalogue['products'] if p['grocery']]
MONTHS = sorted(prices.month.unique(), reverse=True)
RETRIEVED = datetime.fromisoformat(snapshot['retrieved_at_utc']).astimezone(timezone(timedelta(hours=8)))
ss = st.session_state


def month_label(month):
    return datetime.strptime(month, '%Y-%m').strftime('%B %Y')


def name(code):
    return PRODUCTS[code]['name_mn'] if LANGUAGE == 'Монгол' else PRODUCTS[code]['name']


def region_name(code):
    return REGIONS[code]['name_mn'] if LANGUAGE == 'Монгол' else REGIONS[code]['name']


def product_option(code):
    return f"{name(code)} · {PRODUCTS[code]['unit']}"


def head(title, subtitle='', pill=''):
    st.markdown(f'<div class="section-head"><div><h2>{escape(title)}</h2><p>{escape(subtitle)}</p></div>' +
                (f'<span class="pill">{escape(pill)}</span>' if pill else '') + '</div>', unsafe_allow_html=True)


def preset(which):
    choices = {
        'everyday': {'0':2.0, '2':1.0, '11':2.0, '14':6.0, '25':2.0},
        'student': {'0':1.0, '2':1.0, '14':4.0, '25':1.0, '23':.5},
        'family': {'0':3.0, '2':2.0, '5':2.0, '11':4.0, '14':12.0, '25':3.0, '22':1.0},
        'fresh': {'17':1.0, '19':1.0, '20':.5, '22':1.0, '23':1.0, '25':2.0},
    }
    ss.basket_products = list(choices[which])
    for code, quantity in choices[which].items(): ss['qty_'+code] = quantity


ss.setdefault('basket_products', ['0', '2', '11', '14', '25'])
ss.setdefault('region', '511')
ss.setdefault('month', MONTHS[0])
ss.setdefault('budget', 100000)
ss.setdefault('language', 'English')
LANGUAGE = ss.language
for c, q in {'0':2.0, '2':1.0, '11':2.0, '14':6.0, '25':2.0}.items(): ss.setdefault('qty_'+c, q)

logo = '<svg width="25" height="25" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M4 9h16l-1 12H5L4 9ZM8 9V7a4 4 0 0 1 8 0v2M9 13v4M15 13v4"/></svg>'
with st.sidebar:
    st.markdown(f'<div class="brand"><div class="brand-mark">{logo}</div><div>PriceWatch<small>MONGOLIA</small></div></div><div class="side-kicker">YOUR EVERYDAY ESSENTIALS</div><div class="side-title">A basket that makes sense.</div><div class="side-sub">Choose a place and a month.<br>See what the reported prices say.</div>', unsafe_allow_html=True)
    st.selectbox('Product & region names', ['English', 'Монгол'], key='language', help='Changes the product and place names. Source labels remain available in both languages.')
    st.selectbox('Your region', REGION_CODES, format_func=region_name, key='region')
    st.selectbox('Price month', MONTHS, format_func=month_label, key='month')
    st.number_input('Your basket budget · ₮', min_value=0, max_value=10000000, step=10000, key='budget')
    st.multiselect('Choose your groceries', FOODS, format_func=product_option, key='basket_products', help='Each quantity uses the product’s stated unit. Imported and domestic variants are kept separate.')
    st.markdown(f'<div class="side-source"><strong>Official NSO price averages</strong>{snapshot["regions"]} places · {snapshot["grocery_products"]} groceries<br>Latest month: {month_label(snapshot["latest_month"])}<br>Regional averages, with a source for every observation.</div>', unsafe_allow_html=True)
    st.caption('A snapshot of published statistics. Shop prices, promotions and stock can differ.')

region, month = ss.region, ss.month
region_display = region_name(region)
st.markdown(f'<div class="masthead"><div class="source-chip">NSO · Official price data</div><div class="snapshot">Snapshot retrieved {RETRIEVED.strftime("%d %b %Y")} · Monthly data</div></div><div class="hero"><div><div class="hero-title">Everyday prices.<br><span>A clearer picture.</span></div><div class="hero-copy">Build your grocery basket, compare places, and follow price changes.<br>Real published figures, made a little easier to use.</div></div><div class="hero-note"><small>Latest reported month</small><b>{datetime.strptime(snapshot["latest_month"],"%Y-%m").strftime("%b %Y")}</b><div class="fine">21 aimags + Ulaanbaatar city</div></div></div><div class="context-line"><strong>{escape(region_display)}</strong><span>·</span><span>{month_label(month)}</span><span>·</span><span>Mongolian tögrög · MNT</span></div>', unsafe_allow_html=True)

basket_tab, explorer_tab, regions_tab, sources_tab = st.tabs(['My grocery basket', 'Price explorer', 'Compare regions', 'Data & sources'])

with basket_tab:
    st.markdown('<div class="fine-print" style="margin:18px 0 8px">A starting basket, if you need one</div>', unsafe_allow_html=True)
    for col, label, key in zip(st.columns(4), ['Everyday essentials','Student basics','Family staples','Fruit & vegetables'], ['everyday','student','family','fresh']):
        col.button(label, on_click=preset, args=(key,), key='preset_'+key, use_container_width=True)
    head('What’s in your basket?', 'Set the quantities you need. Every unit price is for your selected place and month.', f'{len(ss.basket_products)} products')
    quantities = {}
    main, aside = st.columns([1.55, 1], gap='large')
    with main:
        if not ss.basket_products:
            st.info('Choose groceries from the sidebar, or start with one of the baskets above.')
        for code in ss.basket_products:
            p = PRODUCTS[code]
            ss.setdefault('qty_'+code, 1.0)
            row = st.columns([2.0, 1.0, 1.0], vertical_alignment='center')
            row[0].markdown(f'<div class="product-info"><div class="product-name">{escape(name(code))}</div><div class="product-sub">Price per {escape(p["unit"])}</div></div>', unsafe_allow_html=True)
            with row[1]:
                quantities[code] = st.number_input('Quantity · '+product_option(code), min_value=0.0, max_value=10000.0,
                    step=1.0 if p['unit'] in ('piece','bulb') else .5, key='qty_'+code,
                    label_visibility='collapsed', format='%g', help='Quantity in '+p['unit']+'. '+p['source_label'])
            unit_price = observed_price(prices, region, code, month)
            row[2].markdown(f'<div class="unit-price">{money(unit_price,2) if unit_price is not None else "Not reported"}</div><div class="product-sub" style="text-align:right">per {escape(p["unit"])}</div>', unsafe_allow_html=True)
            st.markdown('<div class="row-divider"></div>', unsafe_allow_html=True)
        quote = None
        try:
            quote = quote_basket(prices, region, month, quantities)
        except ValueError as error:
            if quantities: st.info(str(error))
        if quote:
            if quote.complete:
                st.markdown(f'<div class="total-line"><span>Estimated basket total</span><strong>{money(quote.total,2)}</strong></div>', unsafe_allow_html=True)
            else:
                missing_names = ', '.join(name(c) for c in quote.missing)
                st.markdown(f'<div class="note warning"><strong>Full basket total unavailable.</strong><br>Prices are missing for {escape(missing_names)} in this place and month. The known subtotal is {money(quote.known_subtotal,2)}.</div>', unsafe_allow_html=True)
            st.markdown('<div class="fine-print">Quantities multiply the exact source values. The total estimates your basket using regional monthly averages.</div>', unsafe_allow_html=True)
            detail = pd.DataFrame([{'Product':name(line['product_code']), 'Quantity':float(line['quantity']), 'Unit':PRODUCTS[line['product_code']]['unit'],
                                    'Unit price · MNT':float(line['unit_price']) if line['unit_price'] is not None else None,
                                    'Line total · MNT':float(line['line_total']) if line['line_total'] is not None else None} for line in quote.lines])
            with st.expander('See the calculation'):
                st.dataframe(detail, hide_index=True, use_container_width=True)
            text = basket_text(quote, PRODUCTS, REGIONS[region]['name'], snapshot['source_url'])
            download_file('Save basket summary', text, f'PriceWatch_basket_{region}_{month}.txt', 'text/plain')
            with st.expander('View or copy basket summary'):
                st.code(text, language=None, wrap_lines=True)
    with aside:
        with st.container(border=True):
            st.markdown('<div class="chart-title">Your basket at a glance</div><div class="chart-sub">Same groceries. Same quantities. Reported average prices.</div>', unsafe_allow_html=True)
            if quote and quote.complete:
                total = float(quote.total)
                st.metric('Estimated basket · '+month_label(month), money(total))
                delta = ss.budget-total
                st.markdown(f'<div class="stat-pair"><span>Your budget</span><strong>{money(ss.budget)}</strong></div><div class="stat-pair"><span>{"Budget left" if delta>=0 else "Above your budget"}</span><strong>{money(abs(delta))}</strong></div>', unsafe_allow_html=True)
                if ss.budget > 0:
                    st.progress(min(total/ss.budget,1.0), text=f'{total/ss.budget:.0%} of your budget')
            elif quote:
                st.metric('Known subtotal · incomplete basket', money(quote.known_subtotal))
                st.caption('Budget checks need a price for every selected item.')
            else:
                st.info('Add a product with a quantity above zero to see your total.')
            if quote:
                st.markdown(f'<div class="stat-pair"><span>Products with a price</span><strong>{len(quote.lines)-len(quote.missing)} / {len(quote.lines)}</strong></div>', unsafe_allow_html=True)
                comparison = compare_baskets(prices, month, quantities, catalogue['regions'])
                complete = comparison[comparison.complete]
                if not complete.empty:
                    best = complete.iloc[0]
                    st.markdown(f'<div class="note"><strong>Lowest complete basket in this snapshot</strong><br>{escape(region_name(best.region_code))} · {money(best.total)}<br><span class="fine-print">Among {len(complete)} places with every basket item reported. Travel costs are separate.</span></div>', unsafe_allow_html=True)
            st.markdown('<div class="fine-print">This calculator estimates a grocery basket. It does not measure official inflation or check an individual supermarket.</div>', unsafe_allow_html=True)
    if quote:
        head('Your basket over time', 'The same quantities are used in every month. A missing item makes that month’s full total unavailable.')
        period = st.radio('Basket history', ['Last 12 months','Last 36 months','All history'], horizontal=True, label_visibility='collapsed', key='basket_period')
        count = 12 if period=='Last 12 months' else 36 if period=='Last 36 months' else len(MONTHS)
        wanted = sorted(m for m in MONTHS if m<=month)[-count:]
        history = basket_history(prices, region, quantities, wanted)
        if history.total.notna().any():
            chart = history.assign(date=pd.to_datetime(history.month)).rename(columns={'total':'Basket estimate · MNT'})
            st.line_chart(chart, x='date', y='Basket estimate · MNT', color='#147D62', height=285, x_label='Month', y_label='MNT')
        else: st.info('No complete basket is available in this history window.')
        st.caption(f'{int(history.total.notna().sum())} of {len(history)} months have every basket item reported. Values are nominal prices, without inflation adjustment.')
        with st.expander('View basket history data'):
            st.dataframe(history.rename(columns={'month':'Month','total':'Basket estimate · MNT','available_items':'Priced products'}), hide_index=True, use_container_width=True)

with explorer_tab:
    head('Follow a price, month by month.', 'Choose an exact commodity. Imported, domestic, and package variants stay separate.')
    e1,e2 = st.columns([1,2])
    category = e1.selectbox('Category', ['All categories'] + sorted({p['category'] for p in catalogue['products']}), key='explore_category')
    options = [p['code'] for p in catalogue['products'] if category=='All categories' or p['category']==category]
    pc = e2.selectbox('Product',options,index=options.index('0') if '0' in options else 0,format_func=product_option,key='explore_product')
    product = PRODUCTS[pc]
    st.caption('Exact NSO label: '+product['source_label']+' · '+product['name_mn'])
    current = observed_price(prices,region,pc,month)
    mom,yoy = price_change(prices,region,pc,month),price_change(prices,region,pc,month,12)
    cols = st.columns(3)
    cols[0].metric('Average price / '+product['unit'],money(current,2))
    cols[1].metric('Change from previous month', f'{mom:+.1f}%' if mom is not None else 'Not available')
    cols[2].metric('Change from same month last year',f'{yoy:+.1f}%' if yoy is not None else 'Not available')
    chosen_regions = st.multiselect('Compare places in the price chart', REGION_CODES, default=list(dict.fromkeys([region,'345','261'])),format_func=region_name,key='chart_regions')
    range_label = st.radio('Price history',['Last 12 months','Last 36 months','All history'],index=1,horizontal=True,key='price_period')
    n = 12 if range_label=='Last 12 months' else 36 if range_label=='Last 36 months' else len(MONTHS)
    chart_months = sorted(m for m in MONTHS if m<=month)[-n:]
    product_rows = prices[prices.product_code.eq(pc) & prices.region_code.isin(chosen_regions) & prices.month.isin(chart_months)].copy()
    if not product_rows.empty and product_rows.price_mnt.notna().any():
        product_rows['Month'] = pd.to_datetime(product_rows.month)
        product_rows['Region'] = product_rows.region_code.map(region_name)
        product_rows['Average price · MNT'] = product_rows.price_mnt
        st.line_chart(product_rows,x='Month',y='Average price · MNT',color='Region',height=320,y_label='MNT / '+product['unit'])
    else: st.info('Choose a place with reported prices to show this chart.')
    st.caption('Changes compare exact calendar months. If either price is missing, the percentage stays unavailable.')
    with st.expander('View the selected price observations'):
        export = export_observations(product_rows[['region_code','product_code','month','price_mnt','value_status']],catalogue)
        st.dataframe(export,hide_index=True,use_container_width=True)
        download_file('Download selected price data',export.to_csv(index=False),f'PriceWatch_{pc}_{month}.csv')

with regions_tab:
    head('Compare your basket across Mongolia.', 'Every place uses your basket quantities and the same selected month.', month_label(month))
    if quote:
        ranked = compare_baskets(prices,month,quantities,catalogue['regions'])
        available = ranked[ranked.complete].copy()
        if available.empty:
            st.warning('No place has all your basket prices for this month. Try another month or a different basket.')
        else:
            c1,c2,c3 = st.columns(3)
            low, high = available.iloc[0],available.iloc[-1]
            c1.metric('Lowest complete basket',money(low.total),region_name(low.region_code),delta_color='off')
            c2.metric('Highest complete basket',money(high.total),region_name(high.region_code),delta_color='off')
            c3.metric('Difference · highest minus lowest',money(high.total-low.total))
            bars = available.head(12).copy()
            bars['Region'] = bars.region_code.map(region_name)
            bars['Basket estimate · MNT'] = bars.total
            st.bar_chart(bars,x='Basket estimate · MNT',y='Region',horizontal=True,color='#147D62',height=430)
            st.caption('Chart shows up to 12 lowest complete baskets. These are average-price estimates; travel costs and store promotions are separate.')
        table = ranked.copy()
        table['Region'] = table.region_code.map(region_name)
        table['Prices available'] = table.available_items.astype(str)+' / '+table.requested_items.astype(str)
        table['Coverage'] = table.complete.map({True:'Complete',False:'Missing prices · not ranked'})
        table = table.rename(columns={'total':'Basket estimate · MNT','known_subtotal':'Known subtotal · MNT'})
        st.dataframe(table[['Region','Basket estimate · MNT','Known subtotal · MNT','Prices available','Coverage']],hide_index=True,use_container_width=True)
        download_file('Download regional comparison',table[['Region','Basket estimate · MNT','Known subtotal · MNT','Prices available','Coverage']].to_csv(index=False),f'PriceWatch_regions_{month}.csv')
        st.caption('Only complete baskets are ranked. A subtotal with missing items is not compared against a full basket.')\n\n        # --- Affordable market suggestions ---\n        if not available.empty:\n            # Show the 3 most affordable places\n            affordable = available.nsmallest(3, 'total').copy()\n            affordable['Region'] = affordable.region_code.map(region_name)\n            st.markdown('<div class="note" style="margin:18px 0"><strong>More affordable markets:</strong></div>', unsafe_allow_html=True)\n            for _, row in affordable.iterrows():\n                st.markdown(f"<div style='font-size:.875rem; line-height:1.5'>{escape(row['Region'])} · {money(row['total'],2)} (saved <strong>{money(high.total - row['total'],2)}</strong> vs highest)</div>", unsafe_allow_html=True)\n\n            # Show savings opportunity vs user's basket\n            if quote and quote.complete:\n                user_total = float(quote.total)\n                st.markdown(f"<div class="note" style="margin:12px 0"><strong>Your basket vs most affordable:</strong> Your basket {money(user_total,2)} vs most affordable {money(affordable.iloc[0]['total'],2)} — {'you're above' if user_total > affordable.iloc[0]['total'] else 'you're below'} the most affordable place by {money(abs(user_total - affordable.iloc[0]['total']),2)}</div>", unsafe_allow_html=True)\n        else:\n            st.info('Add products to your basket to see affordable market suggestions.')
                user_total_f = float(user_total)
                affordable_total = affordable.iloc[0]["total"]
                above_below = "you're above" if user_total_f > affordable_total else "you're below"
                diff = abs(user_total_f - affordable_total)
                note = "<div class='note' style='margin:12px 0'><strong>Your basket vs most affordable:</strong> Your basket {money(user_total_f,2)} vs most affordable {money(affordable_total,2)} — {above_below} the most affordable place by {money(diff,2)}</div>"
                st.markdown(note, unsafe_allow_html=True)

        # --- Price spread analysis ---
        if not available.empty and quote and quote.complete:
            st.markdown('<div class="note" style="margin:18px 0"><strong>Price spread analysis:</strong> product price ranges across regions</div>', unsafe_allow_html=True)
            # Calculate price spread for each product
            spread_rows = []
            for prod_code in catalogue['products'][:10]:  # Top 10 products by availability
                prod_data = ranked[ranked.product_code == prod_code]
                if len(prod_data) > 1:
                    prices = prod_data.price_mnt.dropna()
                    if len(prices) > 0:
                        highest_price = prices.max()
                        lowest_price = prices.min()
                        if highest_price > 0:
                            spread_pct = ((highest_price - lowest_price) / lowest_price) * 100
                            spread_rows.append({
                                'product': prod_data.iloc[0]['product_name'] if 'product_name' in prod_data.columns else f'Product {prod_code}',
                                'lowest': money(lowest_price, 0),
                                'highest': money(highest_price, 0),
                                'spread': f'{spread_pct:.0f}%',
                            })
            if spread_rows:
                spread_df = pd.DataFrame(spread_rows)
                st.dataframe(
                    spread_df,
                    column_config={
                        'product': 'Product',
                        'lowest': 'Lowest',
                        'highest': 'Highest',
                        'spread': 'Spread',
                    },
                    hide_index=True,
                    use_container_width=True,
                )
                st.caption('Shows price range across regions for the 10 most available products. Wider spreads indicate greater price disparity.')
            else:
                st.info('Not enough price data available for spread analysis this month.')
        else:
            st.info('Add products to your basket and select a month to see price spread analysis.')

with sources_tab:
    head('Real data. A clear source.', 'The app includes a reproducible snapshot of Mongolia’s official regional price table.')
    st.markdown(f'<div class="source-card"><strong>National Statistics Office of Mongolia</strong><br>{escape(snapshot["title"])}<br>Table: {snapshot["table_id"]}<br>Coverage: {month_label(snapshot["first_month"])} to {month_label(snapshot["latest_month"])}<br>Retrieved: {RETRIEVED.strftime("%d %B %Y, %H:%M")} · Ulaanbaatar time<br><a href="{escape(snapshot["source_url"],quote=True)}" target="_blank" rel="noopener">Open the official source table</a></div>',unsafe_allow_html=True)
    stats = st.columns(4)
    stats[0].metric('Places',snapshot['regions'])
    stats[1].metric('Goods & services',snapshot['products'])
    stats[2].metric('Reported prices',f'{snapshot["value_counts"]["observed"]:,}')
    stats[3].metric('Unavailable source cells',f'{snapshot["row_count"]-snapshot["value_counts"]["observed"]:,}')
    st.markdown('**What these figures mean**')
    st.write('Prices are monthly regional averages in Mongolian tögrög, using each product’s stated unit. The basket uses 27 grocery products from the wider 43-item table. Broader region aggregates and the extra Ulaanbaatar heading are excluded, leaving 21 aimags and Ulaanbaatar city.')
    st.write('Missing or nonpositive source values stay unavailable. The app does not fill gaps, copy prices from another place or month, convert currencies, or create synthetic prices. A basket needs a reported price for every item before its full total can be ranked or checked against a budget.')
    st.write('The snapshot does not include individual supermarket prices, stock, delivery charges or special offers. A basket comparison is not an official CPI calculation. No forecast or future price is presented as an observed value.')
    st.markdown('**Data files and reproducibility**')
    st.write('The source response, English and Mongolian metadata, exact API query, clean price grid and source checksums are bundled with the Python project. Run scripts/fetch_snapshot.py --fresh to retrieve a fresh official snapshot, then rebuild the browser version. The published app uses its saved snapshot and does not refresh automatically.')
    c1,c2 = st.columns(2)
    with c1: download_file('Download price grid · CSV',(BASE/'data/prices.csv').read_bytes(),'PriceWatch_NSO_price_grid.csv')
    package = BASE/'dist/PriceWatch_Mongolia_Streamlit.zip'
    if package.exists():
        with c2: download_file('Download Streamlit project',package.read_bytes(),package.name,'application/zip')
    product_table = pd.DataFrame([{'Code':p['code'],'Product':p['name'],'Mongolian source label':p['name_mn'],'English source label':p['source_label'],'Unit':p['unit'],'Grocery basket':p['grocery']} for p in catalogue['products']])
    with st.expander('Product names and source units'):
        st.dataframe(product_table,hide_index=True,use_container_width=True)
        download_file('Download product dictionary',product_table.to_csv(index=False),'PriceWatch_product_dictionary.csv')
    with st.expander('Snapshot verification details'):
        st.json(snapshot)

st.markdown('<div class="footer"><span>PriceWatch Mongolia · Make sense of everyday prices.</span><span>Source: NSO Mongolia · Regional monthly averages</span></div>',unsafe_allow_html=True)
