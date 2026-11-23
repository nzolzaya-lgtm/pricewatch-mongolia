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

# Bundled chart helpers keep this repair to one app.py file.
from html import escape
import math

import pandas as pd
import streamlit.components.v1 as components

PALETTE = ['#147D62','#3478C8','#B97923','#8A61BF','#C45872','#087F98','#626E87']
STYLE = '''<style>html,body{margin:0;background:transparent;font-family:system-ui,sans-serif;color:#526877}.scroll{overflow-x:auto;padding-bottom:6px}svg{width:960px;display:block}svg text{font:14px system-ui,sans-serif;fill:#617484}.legend{display:flex;flex-wrap:wrap;gap:8px 18px;font-size:14px;padding:5px 6px 7px}.legend i{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:6px}.point{outline:none}.point:hover,.point:focus{r:5;stroke:#172c3c;stroke-width:2}.bar:hover{opacity:.7}.empty{padding:24px;font-size:15px}</style>'''


def scale_max(value):
    if value <= 0 or not math.isfinite(value): return 1.0
    step_base = 10 ** math.floor(math.log10(value / 5))
    step = next(x * step_base for x in [1, 2, 2.5, 5, 10] if x * step_base >= value / 5)
    return math.ceil(value / step) * step


def line_chart_html(data, x, y, series=None, height=300, y_label='MNT', color='#147D62'):
    frame = data.copy()
    frame['_date'] = pd.to_datetime(frame[x])
    frame['_value'] = pd.to_numeric(frame[y], errors='coerce')
    frame['_series'] = frame[series].astype(str) if series else y
    finite = frame['_value'].map(lambda v: pd.notna(v) and math.isfinite(float(v)))
    if frame.empty or not finite.any(): return STYLE+'<div class="empty">No reported values in this chart window.</div>'
    dates = sorted(frame['_date'].dropna().unique())
    if not dates: return STYLE+'<div class="empty">No valid source months in this chart window.</div>'
    timestamps = [pd.Timestamp(d) for d in dates]
    month_numbers = [d.year*12+d.month for d in timestamps]
    low, high = min(month_numbers), max(month_numbers)
    top = scale_max(float(frame.loc[finite,'_value'].max()))
    width, left, right, upper, lower = 960, 90, 30, 25, height-55
    plot_width, plot_height = width-left-right, lower-upper
    xpos = lambda t: left + ((t.year*12+t.month-low)/max(high-low,1))*plot_width
    ypos = lambda v: lower-float(v)/top*plot_height
    svg = [f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-label="{escape(y_label,quote=True)} by month"><title>{escape(y_label)} by month</title>']
    for i in range(6):
        val = top*i/5; py=ypos(val)
        svg.append(f'<line x1="{left}" x2="{width-right}" y1="{py:.2f}" y2="{py:.2f}" stroke="#e4ebef"/><text x="{left-12}" y="{py+5:.2f}" text-anchor="end">{val:,.0f}</text>')
    ticks = sorted({round(i*(len(timestamps)-1)/min(5,max(len(timestamps)-1,1))) for i in range(min(6,len(timestamps)))})
    for i in ticks:
        t=timestamps[i]; px=xpos(t)
        svg.append(f'<text x="{px:.2f}" y="{lower+25}" text-anchor="middle">{t.strftime("%b %y")}</text>')
    svg.append(f'<text x="{left}" y="16">{escape(y_label)}</text>')
    legend=[]
    for group_no,(label, group) in enumerate(frame.groupby('_series',sort=False)):
        shade=PALETTE[group_no%len(PALETTE)] if series else color
        points=[]; segments=[]; markers=[]; previous=None
        for _,row in group.sort_values('_date').iterrows():
            date=row['_date']; value=row['_value']
            valid=pd.notna(date) and pd.notna(value) and math.isfinite(float(value))
            number=date.year*12+date.month if pd.notna(date) else None
            if not valid or (previous is not None and number!=previous+1):
                if points: segments.append(points); points=[]
            if valid:
                px,py=xpos(date),ypos(value);points.append((px,py));previous=number
                text=f'{label} · {date.strftime("%B %Y")} · ₮{float(value):,.2f}'
                markers.append(f'<circle class="point" cx="{px:.2f}" cy="{py:.2f}" r="3" fill="{shade}" tabindex="0" aria-label="{escape(text,quote=True)}"><title>{escape(text)}</title></circle>')
            else: previous=None
        if points: segments.append(points)
        for segment in segments:
            coords=' '.join(f'{a:.2f},{b:.2f}' for a,b in segment)
            svg.append(f'<polyline class="source-line" points="{coords}" fill="none" stroke="{shade}" stroke-width="2.5" stroke-linejoin="round"/>')
        svg.extend(markers)
        legend.append(f'<span><i style="background:{shade}"></i>{escape(str(label))}</span>')
    svg.append('</svg>')
    return STYLE+'<div class="legend">'+''.join(legend)+'</div><div class="scroll">'+''.join(svg)+'</div>'


def bar_chart_html(data, x, y, height=430, color='#147D62'):
    frame=data.copy()
    frame[x]=pd.to_numeric(frame[x],errors='coerce')
    frame=frame[frame[x].map(lambda v:pd.notna(v) and math.isfinite(float(v)) and v>=0)]
    if frame.empty:return STYLE+'<div class="empty">No complete baskets to compare.</div>'
    width,left,right=960,200,130
    height=max(height,len(frame)*30+55)
    row_h=(height-35)/len(frame)
    max_value=max(float(frame[x].max()),1)
    svg=[f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-label="Regional basket estimates in MNT"><title>Regional basket estimates in MNT</title>']
    for i,(_,row) in enumerate(frame.iterrows()):
        py=15+i*row_h; bw=float(row[x])/max_value*(width-left-right)
        label=str(row[y]); tooltip=f'{label} · ₮{float(row[x]):,.2f}'
        svg.append(f'<text x="{left-14}" y="{py+19:.2f}" text-anchor="end">{escape(label)}</text><rect class="bar" x="{left}" y="{py:.2f}" width="{bw:.2f}" height="24" rx="5" fill="{color}"><title>{escape(tooltip)}</title></rect><text x="{left+bw+10:.2f}" y="{py+18:.2f}">₮{float(row[x]):,.0f}</text>')
    svg.append('</svg>')
    return STYLE+'<div class="scroll">'+''.join(svg)+'</div>'


def render_line_chart(data, x, y, series=None, height=300, y_label='MNT', color='#147D62'):
    legend_rows=max(1,math.ceil((data[series].nunique() if series else 1)/3))
    components.html(line_chart_html(data,x,y,series,height,y_label,color),height=height+legend_rows*29+28,scrolling=False)


def render_bar_chart(data, x, y, height=430, color='#147D62'):
    components.html(bar_chart_html(data,x,y,height,color),height=max(height,len(data)*30+55)+25,scrolling=False)


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


def preserve_language_selections():
    keys = ['region', 'basket_products', 'explore_product', 'chart_regions'] + ['qty_'+code for code in FOODS]
    for key in keys:
        if key in ss:
            value = ss[key]
            ss[key] = list(value) if isinstance(value, list) else value


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
    st.selectbox('Product & region names', ['English', 'Монгол'], key='language', on_change=preserve_language_selections, help='Changes the product and place names. Source labels remain available in both languages.')
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
                quantities[code] = st.number_input('Quantity · '+p['name']+' · '+p['unit'], min_value=0.0, max_value=10000.0,
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
            render_line_chart(chart, x='date', y='Basket estimate · MNT', color='#147D62', height=285, y_label='MNT')
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
        render_line_chart(product_rows,x='Month',y='Average price · MNT',series='Region',height=320,y_label='MNT / '+product['unit'])
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
            render_bar_chart(bars,x='Basket estimate · MNT',y='Region',color='#147D62',height=430)
            st.caption('Chart shows up to 12 lowest complete baskets. These are average-price estimates; travel costs and store promotions are separate.')
        table = ranked.copy()
        table['Region'] = table.region_code.map(region_name)
        table['Prices available'] = table.available_items.astype(str)+' / '+table.requested_items.astype(str)
        table['Coverage'] = table.complete.map({True:'Complete',False:'Missing prices · not ranked'})
        table = table.rename(columns={'total':'Basket estimate · MNT','known_subtotal':'Known subtotal · MNT'})
        st.dataframe(table[['Region','Basket estimate · MNT','Known subtotal · MNT','Prices available','Coverage']],hide_index=True,use_container_width=True)
        download_file('Download regional comparison',table[['Region','Basket estimate · MNT','Known subtotal · MNT','Prices available','Coverage']].to_csv(index=False),f'PriceWatch_regions_{month}.csv')
        st.caption('Only complete baskets are ranked. A subtotal with missing items is not compared against a full basket.')

        # Regional comparisons use NSO averages, rather than individual shop prices.
        if not available.empty:
            affordable = available.nsmallest(3, 'total').copy()
            affordable['Region'] = affordable.region_code.map(region_name)
            highest_total = float(available['total'].max())
            st.markdown('<div class="note" style="margin:18px 0"><strong>Three lower-cost places for this basket</strong></div>', unsafe_allow_html=True)
            for _, place in affordable.iterrows():
                place_total = float(place['total'])
                savings = highest_total - place_total
                st.markdown(
                    f"<div style='font-size:1rem;line-height:1.5'>{escape(place['Region'])} · {money(place_total,2)} "
                    f"({money(savings,2)} lower than the highest complete regional estimate)</div>",
                    unsafe_allow_html=True,
                )
            if quote.complete:
                user_total = float(quote.total)
                affordable_total = float(affordable.iloc[0]['total'])
                difference = user_total - affordable_total
                if abs(difference) < 0.005:
                    comparison_text = 'Your regional estimate matches the lowest complete estimate.'
                else:
                    comparison_text = f'Your regional estimate is {money(difference,2)} higher than the lowest complete estimate.'
                note = (
                    "<div class='note' style='margin:12px 0'><strong>Your basket compared with the lowest estimate</strong><br>"
                    f"Your region: {money(user_total,2)} · Lowest complete estimate: {money(affordable_total,2)}<br>"
                    f"{comparison_text}</div>"
                )
                st.markdown(note, unsafe_allow_html=True)
            else:
                st.info('Your selected region has missing prices, so its subtotal cannot be compared with complete baskets.')
            st.caption('These places are aimags and Ulaanbaatar city. The estimates do not identify a supermarket or include travel costs.')
    else:
        st.info('Add products with quantities above zero to compare regional basket estimates.')

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
