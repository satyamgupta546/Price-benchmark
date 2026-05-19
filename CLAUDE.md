# SAM Price Benchmark — Project Rules (DO NOT ASK USER TO REPEAT THESE)

## What SAM Does
Apna Mart ke har product ke liye, Blinkit/Jiomart pe wahi product dhundh ke live price nikalna hai. Goal: Replace Anakin (₹3L/month vendor).

## Full Pipeline (run order — every time, no shortcuts)
1. `fetch_ean_map.py` — EAN barcodes from smpcm_product (table 578, db 5)
2. Fetch AM product master from smpcm_product (item_code, display_name, master_category, brand, marketed_by, product_type, unit, unit_value, mrp, main_image)
3. Fetch latest MRP from model 1808 (Latest inward Cost Price) — warehouse-specific
4. **Blinkit + Jiomart + DMart in PARALLEL** (NEVER sequential):
   - **Blinkit**: PDP scrape (url_database → PDP visit) → category discovery (homepage API → all sub-cats) → compare → unified_matcher → image → barcode
   - **Jiomart**: PAUSED (UI rewrite in progress from Jiomart side — PDP+Search broken)
   - **DMart**: Pure API scrape → name fuzzy match (rapidfuzz)
5. All stages use **category products as search pool** (not just BFS)
6. All stages use **AM master as input** (not just Anakin — Anakin is optional)
7. Compute match status (COMPLETE/SEMI COMPLETE/PARTIAL/NA)
8. Generate Excel in 35-column format
9. Push to BigQuery (dedup DELETE then APPEND to live + APPEND to history)
10. Save Excel to output dir

## Hosting
- **Cloud Run Job** (`sam-daily`) — Docker container, 2 CPU / 4GB, 4hr timeout
- **Cloud Scheduler** (`sam-daily-cron`) — Daily 8 AM IST
- **Cloud NAT** — 25 rotating IPs on `sam-network` (isolated from default/kinetic)
- **No laptop dependency** — fully cloud-hosted

## URL Sources (priority order)
1. `url_database.json` — PRIMARY (17,446+ saved URLs from Anakin + scrapes)
2. `product_mapping.json` — supplement
3. Category discovery — new products from Blinkit category APIs (dynamic per city)
4. Anakin — OPTIONAL (shutting down end of May 2026)

## Category Discovery (Blinkit)
- Homepage API returns full category tree (city-specific IDs)
- Each sub-category visited → `listing_widgets` API intercepted → products extracted
- Products saved to `blinkit_category_{pincode}_latest.json`
- Fed into unified_matcher + stage4 + stage5 as search pool
- URL database auto-updated with new product_ids

## Excel Output Format — 35 Columns, SINGLE Sheet, All Platforms
```
DATE | TIME | CITY | PINCODE | AM ITEM CODE | AM ITEM NAME | AM master cat | AM BRAND | AM MARKETED BY | AM PRODUCT TYPE | AM UNIT | AM UNIT VALUE | AM MRP | IMAGE LINK | BLINKIT URL | BLINKIT ITEM NAME | BLINKIT UNIT | BLINKIT MRP | BLINKIT SP | BLINKIT IN STOCK REMARK | BLINKIT STATUS | JIO URL | JIO ITEM NAME | JIO UNIT | JIO MRP | JIO SP | JIO IN STOCK REMARK | JIO STATUS | DMART URL | DMART ITEM NAME | DMART UNIT | DMART MRP | DMART SP | DMART IN STOCK REMARK | DMART STATUS
```

### Data Sources per Column
- **AM columns (1-14)**: smpcm_product (table 578, db 5)
- **AM MRP**: From model 1808 (latest inward cost price), warehouse-specific. Fallback to smpcm_product.mrp
- **BLINKIT columns (15-21)**: SAM scraped (PDP + unified_matcher)
- **JIO columns (22-28)**: SAM scraped (jiomart_fetch_prices.py — mapping-based URL fetch + search fallback)
- **DMART columns (29-35)**: SAM API scrape (pure JSON API, no browser)
- **STATUS columns**: Computed match status (see logic below)

### Match Status Logic
```
COMPLETE MATCH — ANY of these:
  (1) Same unit value (±10%) + Same MRP (±5%)
  (2) SAM SP matches Anakin SP (±5%) — price verified correct
  (3) Same unit value (±10%) + MRP within 10%

SEMI COMPLETE MATCH:
  - Only for LOOSE/ASM items in STPLS master category
  - Same unit type (kg/kg, ml/ml)
  - MRP can differ

PARTIAL MATCH:
  - Product found but doesn't meet COMPLETE or SEMI COMPLETE criteria
  - Usually variant mismatch (different pack size at same URL)

NA:
  - No price found on platform
```

### Unit Comparison
- Do NOT use `sam_unit` from Blinkit (always "1" — useless)
- PARSE weight from SAM product name: "Amul Butter 500 g" → 500g
- Compare AM unit_value + unit vs parsed weight
- Normalize: kg→g, l→ml before comparison

### MRP Fallback
- If SAM MRP is None but SP exists → set MRP = SP (no discount)
- AM MRP source: model 1808 (warehouse-specific latest inward) → fallback smpcm_product.mrp

## AM Data Sources
### smpcm_product (table 578, database 5)
Fields: item_code (7191), display_name (7118), master_category (8935), brand (7113), marketed_by (7133), product_type (7131), unit (7176), unit_value (7193), mrp (7158), main_image (7149), bar_code (7127)

### Master Category Filter
Only include: **STPLS, FMCG, FMCGF, FMCGNF, GM**

### Model 1808 — Latest Inward Cost Price (database 3)
Columns: warehouse_id, grn_date, pricing_approv_date, product_id, item_code, cost, mrp, display_name, master_category

### Warehouse Mapping
| Pincode | Warehouse | City |
|---------|-----------|------|
| 834002 | WRHS_1 | Ranchi (Jharkhand) |
| 825301 | WRHS_1 | Hazaribagh (Jharkhand) |
| 492001 | WRHS_2 | Raipur (Chhattisgarh) |
| 712232 | WRHS_10 | Kolkata |

### LOOSE/ASM Tagging
- Model 1344 (product-master) has sub_variant column — needs access (currently 403)
- Fallback: check "loose" in item name
- Reference: https://mirror.apnamart.in/model/1344-product-master

### URL Database
- `data/mappings/url_database.json` — 17,446 URLs permanently saved from Anakin
- New URLs from BFS crawl get added automatically
- When Anakin is removed, these URLs continue to work

## Platform-Specific Rules
### Blinkit
- Browser: Chromium (8 parallel tabs on cloud)
- Location: localStorage `location` JSON + cookies `__pincode`, `gr_1_lat`, `gr_1_lon` (NOT `gr_1_lng`)
- Smart wait: poll every 0.5s for API response, max 4s (not fixed sleep)
- PDP redirect detection: (1) homepage redirect, (2) /prid/ mismatch, (3) URL slug vs name mismatch
- Category discovery: homepage → category tree → visit each sub-cat → `listing_widgets` API
- URL source: url_database.json (primary) → product_mapping.json → Anakin (optional)
- Retry pass: failed items get 2nd attempt with fresh browser
- MRP fallback: if MRP None, set MRP = SP

### Jiomart — NEW UI (May 2026)
- Browser: **Firefox** (Chromium gets 403 from Akamai CDN)
- Location: localStorage `pin` JSON + `jio_lat_long` + cookie `app_location_details`
- Old URLs `/p/groceries/...` — DEAD. New URLs: `/product/{slug-with-id}`
- Old `buybox_mrp`, `__NEXT_DATA__`, `/trex/search` — ALL GONE
- **New PDP APIs**:
  - `/api/service/application/catalog/v1.0/products/{slug}` → name, images, brand
  - `/api/service/application/catalog/v1.0/products/sizes/price` → SP (`price.effective`), MRP (`price.marked`), article_id, stock (`quantity`)
- **Category discovery**: `/categories` page → 94 grocery sub-categories → `/products?department=groceries&l1_category=...&l2_category=...`
- **Product data from category pages**: `dataLayer` (product_id, name, brand, SP, slug) + DOM (`PriceContainer__currentPrice`, `PriceContainer__originalPrice`, `productCard__productTitle`)
- **Product master**: `data/jiomart_product_master.json` — permanent store. Save product_id, slug, name, brand, unit, article_id, fssai, URL once. Only fetch prices daily.
- **Scraper script**: `scripts/test_jiomart_pdp.py` — single PDP, category, or `--all` grocery
- **No EAN available** from Jiomart — use name+brand+weight+MRP matching (unified_matcher)
- **Jiomart MRP source**: `smpricing_latestproductpricingtracker` (BQ: smpublic) — NOT model 1808
- **Jiomart mapping**: `data/am_jiomart_mapping.json` — permanent AM↔Jiomart URL mapping
- **Jiomart pricing**: `data/am_pricing_wrhs_1.json` — latest AM MRP from pricing tracker
- **Daily Jiomart flow**: mapped items = URL fetch (fast), unmapped = search + match + save mapping
- **Scripts**: `jiomart_fetch_prices.py` (main daily), `unified_matcher.py` (matching engine)
- DOM TRY 4 (body text regex) **DISABLED** — picks up carousel/bundle prices
- `projects/` names from Google Retail = garbage → skip, use search/DOM name instead
- Pagination: `?page=N` for category pages (up to page 19)
- Grocery-only filter in `_parse_trex_results`

## Unified Matching Engine (unified_matcher.py — replaces cascade_match.py + stage3_match.py)
- **EAN Fast-Track**: If barcode matches → instant COMPLETE MATCH (bypass all text/price logic)
- **Brand**: Normalized with alias dictionary (e.g., "chings" → "ching's secret", "maggie" → "maggi")
- **Weight**: Advanced multipack-aware parser ("Pack of 2 x 500g" → 1000g), ±10% tolerance, MANDATORY
- **Packaging Check**: Detects rigid (jar/tin/bottle) vs soft (pouch/refill) — mismatch → PARTIAL
- **Variant Check**: Critical tokens (moong/toor/masoor, dark/milk/white, salted/unsalted) — conflict → PARTIAL
- **Name Score**: token_set_ratio ≥65 for COMPLETE, ≥40 for PARTIAL (uses rapidfuzz, order-independent)
- **MRP**: Exact match (±0.01) required for COMPLETE. Loose/ASM allows 0.3-3.0x ratio for SEMI COMPLETE
- **Jiomart Search**: Brand from Anakin field (not first-word) → Score ≥0.55 → Also covers PDP failures + projects/ items
- **EAN**: fetch_ean_map.py loads from smpcm_product. If both sides have barcode, must match.
- **load_cascade_matches**: Unified output loaded first; higher score wins (no overwrite)

## Cities
- 834002: Ranchi (WRHS_1 — Jharkhand)
- 712232: Kolkata (WRHS_10)
- 492001: Raipur (WRHS_2 — Chhattisgarh)
- 825301: Hazaribagh (WRHS_1 — **no Jiomart**)
- 495001: Bilaspur (WRHS_2 — Chhattisgarh) **NEW**
- 831001: Jamshedpur (WRHS_1 — Jharkhand) **NEW**

## Platforms per City
| City | Blinkit | Jiomart | DMart |
|------|---------|---------|-------|
| Ranchi | ✅ | ✅ | ❌ |
| Kolkata | ✅ | ✅ | ❌ |
| Raipur | ✅ | ✅ | ❌ (closed) |
| Hazaribagh | ✅ | ❌ | ❌ |
| Bilaspur | ✅ | ✅ | ❌ |
| Jamshedpur | ✅ | ✅ | ❌ |

## File Locations
- AM product master: `data/am_product_master.json`
- Latest MRP: `data/latest_mrp_{warehouse}.json`
- EAN map: `data/ean_map.json`
- URL database: `data/mappings/url_database.json` — PRIMARY source for Blinkit URLs (17,446+)
- Jiomart product master: `data/jiomart_product_master.json` — permanent store (name, brand, unit, article_id, slug, URL). Only prices change daily.
- Blinkit category products: `data/sam/blinkit_category_{pincode}_latest.json`
- Anakin data: `data/anakin/` — OPTIONAL, shutting down
- SAM PDP data: `data/sam/`
- Unified matcher output: `data/comparisons/` (files: `{platform}_unified_{pincode}_{ts}.json`)
- Jiomart mapping: `data/am_jiomart_mapping.json` — permanent AM item_code ↔ Jiomart product_id/URL
- Jiomart pricing: `data/am_pricing_wrhs_1.json` — latest MRP from latestproductpricingtracker
- Excel output: Cloud Run → `/app/output/`, Laptop → `/Users/satyam/Desktop/price csv/`
- Config: `config/cities.json`, `config/output_format.json`, `config/match_status_logic.md`
- Deploy: `deploy.sh` — 8 CPU / 32Gi RAM hardcoded, DO NOT CHANGE

## BigQuery Tables
| Table | Dataset | Purpose |
|-------|---------|---------|
| `sam_price_history` | googlesheet | SAM daily scrape history (partitioned by date, clustered by pincode+item_code) |
| `cx_competitor_prices` | googlesheet | Anakin's current competitor prices |
| `cx_competitor_prices_external` | googlesheet | Anakin's external table (GCS parquet → BQ) |

### sam_price_history/live Schema (35 data cols)
```
date, time, city, pincode, item_code, item_name, master_cat, brand, marketed_by, product_type, unit, unit_value, am_mrp, image_link, blinkit_url, blinkit_name, blinkit_unit, blinkit_mrp, blinkit_sp, blinkit_stock, blinkit_status, jio_url, jio_name, jio_unit, jio_mrp, jio_sp, jio_stock, jio_status, dmart_url, dmart_name, dmart_unit, dmart_mrp, dmart_sp, dmart_stock, dmart_status
```
- Partition: `date` (DAY)
- Cluster: `pincode`, `item_code`
- Push via: `bq load --source_format=CSV`
- After every scrape, push data to this table automatically

### BigQuery Access
- Project: `apna-mart-data`
- Auth account: `satyam.gupta@apnamart.in` (switch with `gcloud config set account`)
- bq CLI: `/opt/homebrew/bin/bq` v2.1.31

## Scrape Timing
- Daily at **10:30 AM IST** (before Anakin's 11 AM push)
- Blinkit/Jiomart prices are real-time (no fixed batch update)
- Cron: `scheduled_morning_run.sh`

## Don't Do
- Don't show inflated/fake coverage %
- Don't run cities sequentially (always PARALLEL)
- Don't trust DOM ₹ regex on Jiomart (carousel prices)
- Don't skip any stage
- Don't use `fill()` on Flipkart (use `press_sequentially()`)
- Don't commit data/ files to git (large JSON)
- Don't make changes without testing
- Don't use `sam_unit` from Blinkit for comparison (always "1")
- Don't ask user to repeat any of these rules — read this file
