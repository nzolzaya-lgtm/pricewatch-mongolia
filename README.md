# PriceWatch Mongolia

A real-data grocery basket and price comparison app built with **Python and Streamlit**. It uses the National Statistics Office of Mongolia's monthly regional price observations, rather than invented store prices.

## Run on your Mac

Unzip the project and open Terminal in the `PriceWatch_Mongolia` folder. Use Python 3.10 or newer; 3.12 is recommended.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m streamlit run app.py --server.port 8513
```

Open **http://localhost:8513**. This port is separate from UniFinder and DayOut.

## What the app does

- Choose a region and a source month.
- Build a grocery basket from 27 food products, with explicit quantities and units.
- Calculate an estimated total using the reported regional monthly averages.
- Check the estimated basket against your own budget.
- Compare the identical basket across 21 aimags and Ulaanbaatar city.
- Explore all 43 goods and services in the source table.
- Display exact-month and year-on-year changes and historical charts.
- Switch product and region names between English and Mongolian.
- Export basket summaries, selected observations, regional comparisons and data dictionaries.

The source snapshot includes **179,405 reported positive prices** and **1,281 unavailable cells** across **180,686 region/product/month combinations**, from **December 2010 through October 2026**. Retrieved **23 November 2026**. These counts describe the bundled snapshot and will change if the source is refreshed.

## Real data and provenance

Source: **National Statistics Office of Mongolia (NSO), 1212.mn**.

Table: **DT_NSO_0600_019V1.px — Average price of main selected commodities, by type of goods and services, aimags and the Capital and by month**.

- Official source table: https://data.1212.mn/pxweb/en/NSO/NSO__Economy,%20environment__Consumer%20Price%20Index/DT_NSO_0600_019V1.px/
- API documentation: https://www.1212.mn/en/data-base/open-data
- English metadata and query endpoint: https://data.1212.mn/api/v1/en/NSO/Economy%2C%20environment/Consumer%20Price%20Index/DT_NSO_0600_019V1.px

The downloader selects the 22 three-digit administrative entries. Broad region aggregates and the extra Ulaanbaatar heading are excluded from comparisons.

`data/prices.csv` stores the complete selected grid with region code, product code, source month, price in MNT and a value status. Blank prices remain blank. The product and region dictionaries are in `data/catalogue.json`.

For reproducibility, the project includes the original response (`nso_response.json.gz`), English and Mongolian metadata, the exact request query and SHA-256 checksums in `snapshot.json`. App loading verifies the clean file checksum, identities, positive observed prices and duplicate-free keys. Tests independently match a sample of saved values against the raw NSO response.

## What the figures mean

These are **monthly regional averages**, not quotes from individual supermarkets. The source does not provide specific-store prices, promotions, delivery fees, stock or guarantees about what you will pay today. The app does not identify the cheapest Nomin, Emart or other shop.

Every quantity uses its source product unit: kilograms, litres, pieces or bulbs for groceries. Imported/domestic and packaged variants stay separate. The source labels remain visible in the product dictionary. Display rounding does not alter the calculation inputs.

Missing, nonfinite and nonpositive source values are unavailable for spending calculations. There is no imputation, carry-forward, synthetic replacement or currency conversion. A basket with a missing price has an explicitly labelled known subtotal and no full total. Only complete baskets enter the regional ranking. Quantities of zero do not add an item to a basket. Travel costs are not included in regional comparisons.

Monthly changes compare the exact previous calendar month, and annual changes compare the same month one year earlier. Missing comparison prices produce no percentage. Basket history holds the user's quantities fixed and is not an official CPI or a forecast. Prices are nominal, without inflation adjustment.

The app reads a saved source snapshot; it does not automatically fetch live updates.

## Refresh the official snapshot

```bash
.venv/bin/python scripts/fetch_snapshot.py --fresh
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python scripts/build_web.py
```

The downloader uses a temporary `.fetch_cache` to resume a single retrieval after a temporary request failure. To fetch newly published data on a later day, first remove only this disposable cache or run the script with `--fresh`. Existing validated data stays in place until a complete new response has passed the downloader's checks. All data files should be kept together when distributing a refreshed snapshot.

## Checks

```bash
.venv/bin/python -m unittest discover -s tests -v
```

The included 18 checks cover exact basket arithmetic, missing prices, ranking coverage, month matching, invalid quantities, source checksums, duplicate rejection, source units and independent real-data samples. Streamlit's AppTest was also used for basket presets, a region change, empty selections, and Mongolian names.

## Browser version and deployment

The web build uses **Stlite `@stlite/browser` 0.85.1** with **Streamlit 1.45.1**, which runs the same Streamlit Python code in the browser through Python/WebAssembly. The native requirements pin the same Streamlit version. It needs an internet connection for the first runtime download; startup can take a moment. The Python project runs separately with normal Streamlit.

```bash
.venv/bin/python scripts/build_web.py
```

The command creates `dist/index.html`, runtime files, direct data downloads and `dist/PriceWatch_Mongolia_Streamlit.zip`. Large browser exports use direct static-file links; smaller generated exports use local Blob downloads, with copyable basket text as an alternative.

For **Streamlit Community Cloud**, upload the source folder to GitHub, keep `app.py`, `prices.py`, `downloads.py`, `requirements.txt`, `assets/`, `.streamlit/` and `data/` at the repository root, and select `app.py` as the entry point. Do not upload `.venv`, secrets, or `.fetch_cache`.

No accounts, purchases, payments or persistent personal-data storage are implemented by the app. Basket inputs remain in the current Streamlit session.

Retain NSO source attribution and the source metadata when sharing this dataset or analysis. Stlite is an open-source Streamlit browser runtime: https://github.com/whitphx/stlite.

