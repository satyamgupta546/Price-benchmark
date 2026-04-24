"""
Apnamart Pricing Data Loader
=============================
Loads input data from CSV exports + SAM output + Metabase API.
Merges everything into product dicts ready for engine.calculate_sp().

Input sources:
  1. AM Product Master     → data/am_product_master.json (Metabase API)
  2. Latest Inward Cost    → data/latest_mrp_{warehouse}.json (Metabase API)
  3. Off-Invoice Promos    → pricing/input/off_invoice.csv (export from Google Sheet)
  4. On-Invoice Promos     → pricing/input/on_invoice.csv (export from Google Sheet)
  5. KVI Tags              → pricing/input/kvi_tags.csv (export from Google Sheet)
  6. Exclusions            → pricing/input/exclusions.csv (export from Google Sheet)
  7. SAM Benchmark Data    → data/sam_output/ (our own scrape output)
  8. MAP Data              → pricing/input/map_data.csv (export from Google Sheet)
  9. Sales Data            → pricing/input/sales_data.csv (export from Google Sheet)
  10. Guardrails (Staples) → pricing/input/guardrails.csv (export from Google Sheet)
  11. City SP Overrides     → pricing/input/city_pricing.csv (export from Google Sheet)
"""

import csv
import json
import os
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
PRICING_DIR = Path(__file__).parent
INPUT_DIR = PRICING_DIR / 'input'

# ── State-to-warehouse mapping ───────────────────────────────────────────────
STATE_WAREHOUSE_MAP = {
    'JH': 'WRHS_1',   # Jharkhand
    'CG': 'WRHS_2',   # Chhattisgarh
    'WB': 'WRHS_10',  # West Bengal (Kolkata)
}

PINCODE_STATE_MAP = {
    '834002': 'JH',   # Ranchi
    '825301': 'JH',   # Hazaribagh
    '831001': 'JH',   # Jamshedpur
    '492001': 'CG',   # Raipur
    '495001': 'CG',   # Bilaspur
    '712232': 'WB',   # Kolkata
}

STATES = ['JH', 'CG', 'WB']


def safe_float(val, default=0.0):
    if val is None or val == '' or val == 'NA' or val == 'nan':
        return default
    try:
        if isinstance(val, str):
            val = val.replace(',', '').replace('%', '').replace('₹', '').strip()
        return float(val)
    except (ValueError, TypeError):
        return default


# ── CSV Reader ────────────────────────────────────────────────────────────────

def read_csv(filepath: str | Path) -> list[dict]:
    """Read CSV file, return list of dicts. Handles BOM and encoding."""
    filepath = Path(filepath)
    if not filepath.exists():
        print(f"  ⚠ File not found: {filepath}")
        return []
    with open(filepath, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        return list(reader)


def read_json(filepath: str | Path) -> list | dict:
    """Read JSON file."""
    filepath = Path(filepath)
    if not filepath.exists():
        print(f"  ⚠ File not found: {filepath}")
        return []
    with open(filepath, 'r', encoding='utf-8') as f:
        return json.load(f)


# ── Load AM Product Master ───────────────────────────────────────────────────

def load_product_master() -> dict:
    """
    Load AM product master → dict keyed by item_code.
    Source: data/am_product_master.json
    """
    filepath = BASE_DIR / 'data' / 'am_product_master.json'
    raw = read_json(filepath)
    if not raw:
        return {}

    products = {}
    # Handle both dict-keyed-by-item_code and list formats
    if isinstance(raw, dict) and 'data' not in raw and 'rows' not in raw:
        items = raw.values()  # dict keyed by item_code
    elif isinstance(raw, list):
        items = raw
    else:
        items = raw.get('data', raw.get('rows', []))
    for item in items:
        if isinstance(item, dict):
            code = str(item.get('item_code', '')).strip()
            if code:
                products[code] = {
                    'item_code': code,
                    'display_name': item.get('display_name', ''),
                    'master_category': item.get('master_category', ''),
                    'brand': item.get('brand', ''),
                    'marketed_by': item.get('marketed_by', ''),
                    'product_type': item.get('product_type', ''),
                    'unit': item.get('unit', ''),
                    'unit_value': safe_float(item.get('unit_value')),
                    'mrp': safe_float(item.get('mrp')),
                    'main_image': item.get('main_image', ''),
                    'bar_code': item.get('bar_code', ''),
                }
    print(f"  ✓ Product master: {len(products)} items")
    return products


# ── Load Latest Inward Cost ──────────────────────────────────────────────────

def load_inward_costs() -> dict:
    """
    Load latest inward costs per warehouse → dict keyed by item_code.
    Returns the latest cost across all warehouses, plus per-warehouse costs.
    Source: data/latest_mrp_*.json
    """
    costs = {}  # item_code → {wrhs_1: cost, wrhs_2: cost, ...}

    for warehouse in ['WRHS_1', 'WRHS_2', 'WRHS_10']:
        # Try both naming conventions: wrhs_1 and wrhs1
        wh_key = warehouse.lower()
        filepath = BASE_DIR / 'data' / f'latest_mrp_{wh_key}.json'
        if not filepath.exists():
            filepath = BASE_DIR / 'data' / f'latest_mrp_{wh_key.replace("_", "")}.json'
        raw = read_json(filepath)
        if not raw:
            continue
        # Handle both dict-keyed and list formats
        if isinstance(raw, dict) and 'data' not in raw:
            items = raw.values()
        elif isinstance(raw, list):
            items = raw
        else:
            items = raw.get('data', [])
        count = 0
        for item in items:
            if isinstance(item, dict):
                code = str(item.get('item_code', '')).strip()
                if code:
                    if code not in costs:
                        costs[code] = {}
                    cost_val = safe_float(item.get('cost') or item.get('mrp') or item.get('cost_price'))
                    mrp_val = safe_float(item.get('mrp'))
                    costs[code][warehouse.lower()] = {
                        'inward_cost': cost_val,
                        'mrp': mrp_val,
                    }
                    count += 1
        print(f"  ✓ Inward costs ({warehouse}): {count} items")

    return costs


# ── Load Promos (Off-Invoice) ────────────────────────────────────────────────

def load_off_invoice() -> dict:
    """
    Load off-invoice promos → dict keyed by KEY (State+ItemCode).
    Source: pricing/input/off_invoice.csv
    Expected columns: Key, State, Item Code, Item Name, MRP, April Offer %,
                      April Offer Rs., April Final Landing, Promo Type
    """
    rows = read_csv(INPUT_DIR / 'off_invoice.csv')
    promos = {}
    for row in rows:
        key = row.get('Key') or row.get('KEY') or ''
        if not key:
            continue
        # Handle FMCG columns (April Offer %) + STPLS columns (% Offer)
        pct = safe_float(row.get('April Offer %') or row.get('Apr 26 Offer %')
                         or row.get('% Offer'))
        val = safe_float(row.get('April Offer Rs.') or row.get('Apr 26 Offer Rs.')
                         or row.get('Rs.Offer') or row.get('Promo Per Unit'))
        # STPLS has FINAL OFFER VALUE directly
        final = safe_float(row.get('April Final Landing') or row.get('Apr 26 Final Landing')
                           or row.get('FINAL OFFER VALUE'))
        # If we have % but no Rs value, and MRP available, calc value
        mrp = safe_float(row.get('MRP by Vendor') or row.get('MRP') or row.get('System MRP'))
        if val == 0 and pct > 0 and mrp > 0:
            val = mrp * pct  # pct already in decimal from safe_float stripping %
        # Use FINAL OFFER VALUE as the value if it's the best we have
        if val == 0 and final > 0:
            val = final
        promos[key] = {
            'off_invoice_pct': pct,
            'off_invoice_value': val,
            'final_landing': final,
            'marketed_by': row.get('Marketed By', ''),
            'brand': row.get('Brand', ''),
        }
    print(f"  ✓ Off-invoice promos: {len(promos)} items")
    return promos


# ── Load Promos (On-Invoice) ─────────────────────────────────────────────────

def load_on_invoice() -> dict:
    """
    Load on-invoice promos → dict keyed by KEY (State+ItemCode).
    Source: pricing/input/on_invoice.csv
    """
    rows = read_csv(INPUT_DIR / 'on_invoice.csv')
    promos = {}
    for row in rows:
        key = row.get('Key') or row.get('KEY') or ''
        if not key:
            continue
        # Handle FMCG + STPLS column names
        pct = safe_float(row.get('April Offer %') or row.get('Apr 26 Offer %')
                         or row.get('offer_percentagereward'))
        val = safe_float(row.get('April Offer Rs.') or row.get('Apr 26 Offer Rs.')
                         or row.get('offer_amountreward') or row.get('OFFER VALUE'))
        promos[key] = {
            'on_invoice_pct': pct,
            'on_invoice_value': val,
            'final_landing': safe_float(row.get('April Final Landing') or row.get('Apr 26 Final Landing')),
        }
    print(f"  ✓ On-invoice promos: {len(promos)} items")
    return promos


# ── Load KVI Tags ────────────────────────────────────────────────────────────

def load_kvi_tags() -> dict:
    """
    Load KVI classification → dict keyed by KEY.
    Source: pricing/input/kvi_tags.csv
    Expected columns: KEY, STATE, item_code, display_name, master category, KVI / NKVI TAG
    """
    rows = read_csv(INPUT_DIR / 'kvi_tags.csv')
    tags = {}
    for row in rows:
        key = row.get('KEY') or row.get('Key') or ''
        if not key:
            continue
        tag = row.get('KVI / NKVI TAG') or row.get('KVI TAG') or 'NON KVI'
        tags[key] = tag.strip().upper()
    print(f"  ✓ KVI tags: {len(tags)} items")
    return tags


# ── Load Exclusions ──────────────────────────────────────────────────────────

def load_exclusions() -> dict:
    """
    Load exclusion list → dict keyed by item_code.
    Source: pricing/input/exclusions.csv
    Expected columns: ITEM_CODE, DISPLAY NAME, MASTER CAT, TYPE, Tag
    """
    rows = read_csv(INPUT_DIR / 'exclusions.csv')
    exclusions = {}
    for row in rows:
        code = str(row.get('ITEM_CODE') or row.get('item_code') or '').strip()
        if code:
            exclusions[code] = {
                'type': row.get('TYPE') or row.get('type', ''),
                'master_cat': row.get('MASTER CAT') or '',
            }
    print(f"  ✓ Exclusions: {len(exclusions)} items")
    return exclusions


# ── Load MAP Data ────────────────────────────────────────────────────────────

def load_map_data() -> dict:
    """
    Load MAP (Minimum Advertised Price) → dict keyed by KEY (State+ItemCode).
    Source: pricing/input/map_data.csv (fetched from Google Sheets)
    """
    rows = read_csv(INPUT_DIR / 'map_data.csv')
    maps = {}
    for row in rows:
        code = str(row.get('item_code') or row.get('ITEM CODE') or row.get('Item Code') or '').strip()
        state = (row.get('state') or row.get('State') or '').strip().upper()
        # Normalize state names
        if state in ('JHARKHAND',):
            state = 'JH'
        elif state in ('CHHATTISGARH',):
            state = 'CG'
        elif state in ('WEST BENGAL',):
            state = 'WB'
        val = safe_float(row.get('map_value') or row.get('MAP') or row.get('map') or row.get('map_price'))
        if code and val > 0:
            if state:
                maps[f"{state}{code}"] = val
            else:
                maps[code] = val
    print(f"  ✓ MAP data: {len(maps)} items")
    return maps


# ── Load SAM Benchmark Data ──────────────────────────────────────────────────

def load_sam_benchmarks() -> dict:
    """
    Load SAM scraped prices (Blinkit + JioMart) → dict keyed by KEY.
    Source: data/sam_output/ (latest CSV files)
    """
    sam_dir = BASE_DIR / 'data' / 'sam_output'
    if not sam_dir.exists():
        print(f"  ⚠ SAM output dir not found: {sam_dir}")
        return {}

    benchmarks = {}

    # Find latest SAM output files
    csv_files = sorted(sam_dir.glob('*.csv'), key=os.path.getmtime, reverse=True)
    if not csv_files:
        print(f"  ⚠ No SAM CSV files found in {sam_dir}")
        return {}

    for csv_file in csv_files[:10]:  # process latest files
        rows = read_csv(csv_file)
        for row in rows:
            item_code = str(row.get('item_code') or row.get('Item_Code') or
                           row.get('AM ITEM CODE') or '').strip()
            state = row.get('city') or row.get('City') or ''
            if not item_code:
                continue

            # Build key per state — map city/pincode to state code
            pincode = str(row.get('Pincode') or row.get('pincode') or '').strip()
            city_upper = state.upper().strip()
            if pincode in PINCODE_STATE_MAP:
                st = PINCODE_STATE_MAP[pincode]
            elif city_upper in ('RANCHI', 'HAZARIBAGH', 'JAMSHEDPUR') or city_upper == 'JH':
                st = 'JH'
            elif city_upper in ('RAIPUR', 'BILASPUR') or city_upper == 'CG':
                st = 'CG'
            elif city_upper in ('KOLKATA',) or city_upper == 'WB':
                st = 'WB'
            else:
                st = city_upper[:2] if len(city_upper) >= 2 else ''
            key = f"{st}{item_code}" if st else item_code

            blinkit_sp = safe_float(row.get('blinkit_sp') or row.get('Blinkit_Selling_Price') or
                                     row.get('BLINKIT SP'))
            jio_sp = safe_float(row.get('jio_sp') or row.get('Jiomart_Selling_Price') or
                                 row.get('JIO SP'))
            blinkit_stock = (row.get('blinkit_stock') or row.get('Blinkit_In_Stock_Remark') or
                             row.get('BLINKIT IN STOCK REMARK') or '')
            jio_stock = (row.get('jio_stock') or row.get('Jiomart_In_Stock_Remark') or
                          row.get('JIO IN STOCK REMARK') or '')

            # Only use price if in-stock
            if 'not' in blinkit_stock.lower() or 'unavail' in blinkit_stock.lower():
                blinkit_sp = 0
            if 'not' in jio_stock.lower() or 'unavail' in jio_stock.lower():
                jio_sp = 0

            benchmark_sp = max(blinkit_sp, jio_sp) if (blinkit_sp > 0 or jio_sp > 0) else 0

            # JioMart MRP
            jio_mrp = safe_float(row.get('Jiomart_Mrp_Price') or row.get('jio_mrp') or
                                  row.get('JIOMART MRP'))

            if key not in benchmarks or benchmark_sp > 0:
                benchmarks[key] = {
                    'blinkit_sp': blinkit_sp,
                    'jio_sp': jio_sp,
                    'jio_mrp': jio_mrp,
                    'benchmark_sp': benchmark_sp,
                    'blinkit_stock': blinkit_stock,
                    'jio_stock': jio_stock,
                }

    print(f"  ✓ SAM benchmarks: {len(benchmarks)} items")
    return benchmarks


# ── Load Sales Data ──────────────────────────────────────────────────────────

def load_sales_data() -> dict:
    """
    Load 30-day and 90-day sales → dict keyed by item_code (per state).
    Source: pricing/input/sales_data.csv
    """
    rows = read_csv(INPUT_DIR / 'sales_data.csv')
    sales = {}
    for row in rows:
        # Try KEY first, then build from item_code+state
        key = row.get('KEY') or row.get('key') or ''
        if not key:
            code = str(row.get('item_code') or row.get('ITEM CODE') or '').strip()
            state = (row.get('states') or row.get('state') or row.get('State') or '').strip().upper()
            if code and state:
                key = f"{state}{code}"
            elif code:
                # No state — store per item, all states get same data
                for st in STATES:
                    sales[f"{st}{code}"] = {
                        'qty_30d': safe_float(row.get('qty_sold_30d') or row.get('LAST 30 DAY QTY SOLD')),
                        'sale_30d': safe_float(row.get('sale_value_30d') or row.get('LAST 30 DAY SALE VALUE')),
                        'qty_90d': safe_float(row.get('qty_sold_90d') or row.get('Last_90day_qty_Sold')),
                        'sale_90d': safe_float(row.get('sale_value_90d') or row.get('Last_90day_Sale')),
                    }
                continue
        if not key:
            continue
        sales[key] = {
            'qty_30d': safe_float(row.get('qty_sold_30d') or row.get('LAST 30 DAY QTY SOLD') or row.get('30_day_qty')),
            'sale_30d': safe_float(row.get('sale_value_30d') or row.get('LAST 30 DAY SALE VALUE') or row.get('30_day_sale')),
            'qty_90d': safe_float(row.get('qty_sold_90d') or row.get('Last_90day_qty_Sold') or row.get('90_day_qty')),
            'sale_90d': safe_float(row.get('sale_value_90d') or row.get('Last_90day_Sale') or row.get('90_day_sale')),
        }
    print(f"  ✓ Sales data: {len(sales)} items")
    return sales


# ── Load Guardrails (Staples) ────────────────────────────────────────────────

def load_guardrails() -> dict:
    """
    Load Staples guardrail thresholds → dict keyed by KEY.
    Source: pricing/input/guardrails.csv
    """
    rows = read_csv(INPUT_DIR / 'guardrails.csv')
    guardrails = {}
    for row in rows:
        key = row.get('Key') or row.get('KEY') or row.get('key') or ''
        if not key:
            continue
        sku_type = (row.get('Markup/gkm') or row.get('markup_gkm') or 'GKM').strip().upper()
        if 'COST' in sku_type:
            sku_type = 'COST_BASED'
        else:
            sku_type = 'GKM'
        guardrails[key] = {
            'sku_type': sku_type,
            'guardrail_lower': safe_float(row.get('Guardrail LOWER') or row.get('guardrail_lower')),
            'guardrail_upper': safe_float(row.get('GUARDRAIL HIGHER') or row.get('guardrail_upper')),
            'cost_based_markup': safe_float(row.get('markup_pct')),
            # Extra fields for sheet matching
            'segment': (row.get('Markup/gkm') or row.get('markup_gkm') or '').strip(),
            'category': row.get('category', ''),
            'sub_category': row.get('sub_category', ''),
            'leaf_category': row.get('leaf_category', ''),
            'current_sp': safe_float(row.get('latest_selling') or row.get('latest_sp')),
            'product_type': row.get('PRODUCT TYPE', ''),
            'brand_tag': row.get('brand', ''),
        }
    print(f"  ✓ Guardrails: {len(guardrails)} items")
    return guardrails


# ── Load Inward Costs from Google Sheet CSV ──────────────────────────────────

def load_inward_costs_csv() -> dict:
    """
    Load inward costs from Google Sheet export CSV → dict keyed by KEY.
    Source: pricing/input/fmcgf_inward_cost.csv
    Has all 3 warehouses (WRHS_1, WRHS_2, WRHS_10).
    """
    filepath = INPUT_DIR / 'fmcgf_inward_cost.csv'
    rows = read_csv(filepath)
    costs = {}
    for row in rows:
        key = row.get('Key') or row.get('KEY') or ''
        if not key:
            continue
        cost_val = safe_float(row.get('cost (Rs)') or row.get('cost'))
        mrp_val = safe_float(row.get('mrp') or row.get('MRP'))
        warehouse = (row.get('warehouse_id') or '').strip()
        # Keep latest (last row wins for same key)
        if key not in costs or cost_val > 0:
            costs[key] = {
                'inward_cost': cost_val,
                'mrp': mrp_val,
                'warehouse': warehouse,
            }
    print(f"  ✓ Inward costs (CSV): {len(costs)} items")
    return costs


# ── Load Category data from off_invoice ──────────────────────────────────────

def load_categories() -> dict:
    """
    Extract category/sub_category/leaf_category from off_invoice and on_invoice CSVs.
    Returns dict keyed by KEY → {category, sub_category, leaf_category}.
    """
    cats = {}
    for filename in ['off_invoice.csv', 'on_invoice.csv']:
        rows = read_csv(INPUT_DIR / filename)
        for row in rows:
            key = row.get('Key') or row.get('KEY') or ''
            if not key:
                continue
            cat = row.get('Category') or row.get('category') or ''
            sub = row.get('Sub Category') or row.get('sub_category') or ''
            leaf = row.get('Leaf Category') or row.get('leaf_category') or ''
            if cat and key not in cats:
                cats[key] = {'category': cat, 'sub_category': sub, 'leaf_category': leaf}
    print(f"  ✓ Categories: {len(cats)} items")
    return cats


# ── Load City SP Overrides ───────────────────────────────────────────────────

def load_city_pricing() -> dict:
    """
    Load city-level SP overrides → dict keyed by KEY → {city: sp}.
    Source: pricing/input/city_pricing.csv
    """
    rows = read_csv(INPUT_DIR / 'city_pricing.csv')
    city_prices = {}  # KEY → {KOLKATA: sp, BILASPUR: sp, ...}
    for row in rows:
        key = row.get('KEY') or row.get('key') or ''
        if not key:
            continue
        city_data = {}
        for city_col, city_key in [
            ('ADR SP', 'ADR'), ('KOLKATA SP', 'KOLKATA'),
            ('BILASPUR/KORBA SP', 'BILASPUR'), ('JAMSHEDPUR SP', 'JAMSHEDPUR'),
            ('HAZARIBAGH SP', 'HAZARIBAGH'), ('RANCHI SP', 'RANCHI'),
            ('ASANSOL SP', 'ASANSOL'),
        ]:
            sp = safe_float(row.get(city_col))
            if sp > 0:
                city_data[city_key] = sp
        # Also store current_sp from this sheet
        current_sp = safe_float(row.get('CURRENT SP'))
        if current_sp > 0:
            city_data['CURRENT_SP'] = current_sp
        if city_data:
            city_prices[key] = city_data
    print(f"  ✓ City pricing: {len(city_prices)} items")
    return city_prices


# ══════════════════════════════════════════════════════════════════════════════
# MAIN: Merge all data sources into product dicts
# ══════════════════════════════════════════════════════════════════════════════

def load_all_data(master_category: str = None) -> list[dict]:
    """
    Load and merge all data sources into product dicts ready for engine.

    Args:
        master_category: Filter by category — "FMCGF", "FMCGNF", "STPLS", or None for all.

    Returns:
        List of product dicts with all fields needed for calculate_sp().
    """
    print(f"\n{'='*60}")
    print(f"Loading pricing data{f' for {master_category}' if master_category else ''}...")
    print(f"{'='*60}")

    # Load all sources
    products_master = load_product_master()
    inward_costs_json = load_inward_costs()    # from JSON (model 1808)
    inward_costs_csv = load_inward_costs_csv()  # from Google Sheet CSV (all warehouses)
    off_invoice = load_off_invoice()
    on_invoice = load_on_invoice()
    kvi_tags = load_kvi_tags()
    exclusions = load_exclusions()
    sam_benchmarks = load_sam_benchmarks()
    map_data = load_map_data()
    sales = load_sales_data()
    guardrails = load_guardrails()
    city_pricing = load_city_pricing()
    categories = load_categories()

    # Build product list (one entry per state × item)
    merged = []
    for code, product in products_master.items():
        mcat = product.get('master_category', '').upper().strip()

        # Map master_category to pricing category
        pricing_cat = mcat
        if mcat in ('FMCGF',):
            pricing_cat = 'FMCGF'
        elif mcat in ('FMCGNF',):
            pricing_cat = 'FMCGNF'
        elif mcat in ('STPLS',):
            pricing_cat = 'STPLS'
        elif mcat in ('FMCG',):
            pricing_cat = 'FMCGF'
        elif mcat in ('GM',):
            pricing_cat = 'FMCGNF'

        if master_category and pricing_cat != master_category.upper():
            continue

        # Create one entry per state
        for state in STATES:
            key = f"{state}{code}"
            warehouse = STATE_WAREHOUSE_MAP.get(state, 'WRHS_1')

            # Inward cost: prefer CSV (Google Sheet, has all warehouses), fallback to JSON
            ic_csv = inward_costs_csv.get(key, {})
            ic_json = inward_costs_json.get(code, {}).get(warehouse.lower(), {})
            inward = ic_csv.get('inward_cost', 0) or ic_json.get('inward_cost', 0)
            mrp_from_cost = ic_csv.get('mrp', 0) or ic_json.get('mrp', 0)

            # MRP: prefer cost table MRP, fallback to product master
            mrp = mrp_from_cost if mrp_from_cost > 0 else product.get('mrp', 0)

            # MAP: keyed by KEY (state+code) first, fallback to just code
            map_val = safe_float(map_data.get(key) or map_data.get(code))

            # Promos
            off_inv = off_invoice.get(key, {})
            on_inv = on_invoice.get(key, {})

            # KVI tag
            kvi = kvi_tags.get(key, 'NON KVI')

            # Exclusion
            excl = exclusions.get(code, {})
            is_excluded = bool(excl)

            # SAM benchmark
            bm = sam_benchmarks.get(key, {})

            # Sales
            sale = sales.get(key, {})

            # Guardrails (Staples)
            guard = guardrails.get(key, {})

            # Category data: guardrails > off_invoice > product_type
            cat_data = guard if guard.get('category') else categories.get(key, {})
            category = cat_data.get('category', '')
            sub_category = cat_data.get('sub_category', '')
            leaf_category = cat_data.get('leaf_category', '')

            # City pricing (all cities for this key)
            city_data = city_pricing.get(key, {})

            # Current SP (from city_pricing or guardrails)
            current_sp = safe_float(city_data.get('CURRENT_SP') or guard.get('current_sp'))

            merged.append({
                # Identity
                'key': key,
                'state': state,
                'item_code': code,
                'display_name': product.get('display_name', ''),
                'master_category': pricing_cat,
                'brand': product.get('brand', ''),
                'marketed_by': product.get('marketed_by', ''),
                'product_type': product.get('product_type', ''),
                'unit': product.get('unit', ''),
                'unit_value': product.get('unit_value', 0),
                'main_image': product.get('main_image', ''),
                'category': category,
                'sub_category': sub_category,
                'leaf_category': leaf_category,

                # Cost
                'mrp': mrp,
                'latest_inward_cost': inward,
                'map_price': map_val,

                # Promos
                'off_invoice_pct': safe_float(off_inv.get('off_invoice_pct')),
                'off_invoice_value': safe_float(off_inv.get('off_invoice_value')),
                'on_invoice_pct': safe_float(on_inv.get('on_invoice_pct')),
                'on_invoice_value': safe_float(on_inv.get('on_invoice_value')),

                # Classification
                'kvi_tag': kvi,
                'is_excluded': is_excluded,
                'exclusion_type': excl.get('type', ''),

                # Benchmark
                'benchmark_sp': safe_float(bm.get('benchmark_sp')),
                'blinkit_sp': safe_float(bm.get('blinkit_sp')),
                'jio_sp': safe_float(bm.get('jio_sp')),
                'jio_mrp': safe_float(bm.get('jio_mrp')),

                # Sales
                'qty_30d': safe_float(sale.get('qty_30d')),
                'sale_30d': safe_float(sale.get('sale_30d')),
                'qty_90d': safe_float(sale.get('qty_90d')),
                'sale_90d': safe_float(sale.get('sale_90d')),

                # Staples specific
                'sku_type': guard.get('sku_type', 'GKM'),
                'segment': guard.get('segment', ''),
                'guardrail_lower': safe_float(guard.get('guardrail_lower')),
                'guardrail_upper': safe_float(guard.get('guardrail_upper')),
                'cost_based_markup': safe_float(guard.get('cost_based_markup')),
                'current_sp': current_sp,

                # City SPs (all cities)
                'city_sps': {
                    'ADR': safe_float(city_data.get('ADR')),
                    'ASANSOL': safe_float(city_data.get('ASANSOL')),
                    'KOLKATA': safe_float(city_data.get('KOLKATA')),
                    'BILASPUR': safe_float(city_data.get('BILASPUR')),
                    'JAMSHEDPUR': safe_float(city_data.get('JAMSHEDPUR')),
                    'HAZARIBAGH': safe_float(city_data.get('HAZARIBAGH')),
                    'RANCHI': safe_float(city_data.get('RANCHI')),
                },
                'city_sp_override': safe_float(city_data.get('ADR')),  # cluster-level SP
            })

    print(f"\n  ✓ Total merged products: {len(merged)}")
    return merged


# ── Create sample input files for testing ────────────────────────────────────

def create_sample_inputs():
    """Create sample CSV input files so team knows the expected format."""
    INPUT_DIR.mkdir(parents=True, exist_ok=True)

    samples = {
        'off_invoice.csv': [
            'Key,State,Marketed By,Brand,Item Code,Item Name,System MRP,MRP by Vendor,'
            'GKM (TOT Margin),GRN Margin,April invoice Landing,April Offer %,April Offer Rs.,'
            'April Final Landing,Promo Type,Category,Sub Category,Leaf Category',
            'JH17442,JH,Rasna Pvt. Ltd.,Rasna,17442,Rasna Fruit Fun 32 Glass Mango 20g,,47,'
            '20.00%,30.64%,37.6,10.64%,5,32.6,OFF Invoice,,,',
        ],
        'on_invoice.csv': [
            'Key,State,Marketed By,Brand,Item Code,Item Name,System MRP,MRP by Vendor,'
            'GKM (TOT Margin),Apr 26 invoice Landing,Apr 26 Offer %,Apr 26 Offer Rs.,'
            'Apr 26 Final Landing,GRN Margin,Promo Type,Category,Sub Category,Leaf Category,Offer Link',
            'JH73474,JH,Hul,Hul,73474,Horlicks Health & Nutrition Drink Chocolate 1 Kg Jar,,480,'
            '7.04%,446.21,6.25%,30,416.21,,ON Invoice,,,,',
        ],
        'kvi_tags.csv': [
            'KEY,STATE,STATE KEY,item_code,display_name,master category,KVI / NKVI TAG',
            'JH2405,JH,1,2405,Aashirvaad Shudh Chakki Atta 5 Kg,STPLS,Super KVI',
            'CG2405,CG,3,2405,Aashirvaad Shudh Chakki Atta 5 Kg,STPLS,Super KVI',
            'WB2405,WB,2,2405,Aashirvaad Shudh Chakki Atta 5 Kg,STPLS,Super KVI',
        ],
        'exclusions.csv': [
            'ITEM_CODE,DISPLAY NAME,MASTER CAT,TYPE,Tag',
            '97077,Savlon Moisture Shield Hand Wash 650ml x 2 BOGO,fmcgnf,BOGO,yes',
            '15867,Stan Fresh Super Lemon Floor Cleaner 1L BOGO,fmcgnf,BOGO,yes',
        ],
        'map_data.csv': [
            'item_code,display_name,MAP',
            '8091,Patanjali Gonyle Floor Cleaner 1L,61.5',
            '2405,Aashirvaad Shudh Chakki Atta 5 Kg,216.612',
        ],
        'sales_data.csv': [
            'KEY,state,item_code,LAST 30 DAY QTY SOLD,LAST 30 DAY SALE VALUE,'
            'Last_90day_qty_Sold,Last_90day_Sale',
            'WB1615,WB,1615,800,372000,2649,1232141',
            'WB2405,WB,2405,3500,822500,11848,2841132',
        ],
        'guardrails.csv': [
            'Key,Region,item_code,display_name,Markup/gkm,KVI,latest_MRP,CP,latest_selling,'
            'gm%,Guardrail LOWER,GUARDRAIL HIGHER,SATELLITE LOW,SATELLITE HIGH',
            'CG97393,CG,97393,Basil Seeds 50g,cost based,NON KVI,39,11,29,62%,60%,65%,,',
            'CG645,CG,645,Almond Badaam 100g,cost based,NON KVI,169,86,125,31%,30%,35%,,',
        ],
        'city_pricing.csv': [
            'KEY,STATE,ITEM CODE,DISPLAY NAME,ADR SP,KOLKATA SP,BILASPUR/KORBA SP,'
            'JAMSHEDPUR SP,HAZARIBAGH SP,RANCHI SP',
            'WB1615,WB,1615,Aashirvaad Shudh Chakki Atta 10 Kg,465,465,,,,',
            'WB104239,WB,104239,Almond Badaam Popular 500g,409,409,,,,',
        ],
    }

    for filename, lines in samples.items():
        filepath = INPUT_DIR / filename
        if not filepath.exists():
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write('\n'.join(lines) + '\n')
            print(f"  Created sample: {filepath.name}")
        else:
            print(f"  Exists: {filepath.name}")


if __name__ == '__main__':
    print("Creating sample input files...")
    create_sample_inputs()
    print("\nLoading all data...")
    products = load_all_data()
    print(f"\nReady: {len(products)} products loaded")
