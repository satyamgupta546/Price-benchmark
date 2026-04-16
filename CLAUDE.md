# SAM Price Benchmark — Project Rules (DO NOT ASK USER TO REPEAT THESE)

## What SAM Does
Apna Mart ke har product ke liye, Blinkit/Jiomart pe wahi product dhundh ke live price nikalna hai. Goal: Replace Anakin (₹3L/month vendor).

## Full Pipeline (run order — every time, no shortcuts)
1. `fetch_ean_map.py` — EAN barcodes from smpcm_product (table 578, db 5)
2. Fetch AM product master from smpcm_product (item_code, display_name, master_category, brand, marketed_by, product_type, unit, unit_value, mrp, main_image)
3. Fetch latest MRP from model 1808 (Latest inward Cost Price) — warehouse-specific
4. **Blinkit + Jiomart in PARALLEL** (NEVER sequential):
   - PDP scrape → compare → cascade → stage3 → image → barcode
   - Jiomart also runs search (Stage 4)
5. Compute match status (COMPLETE/SEMI COMPLETE/PARTIAL/NA)
6. Generate Excel in 27-column format
7. Save to `/Users/satyam/Desktop/price csv/SAM_{City}_{Pincode}_{Date}.xlsx`

## Excel Output Format — 27 Columns, SINGLE Sheet, Both Platforms
```
DATE | CITY | PINCODE | AM ITEM CODE | AM ITEM NAME | AM master cat | AM BRAND | AM MARKETED BY | AM PRODUCT TYPE | AM UNIT | AM UNIT VALUE | AM MRP | IMAGE LINK | BLINKIT URL | BLINKIT ITEM NAME | BLINKIT UNIT | BLINKIT MRP | BLINKIT SP | BLINKIT IN STOCK REMARK | BLINKIT STATUS | JIO URL | JIO ITEM NAME | JIO UNIT | JIO MRP | JIO SP | JIO IN STOCK REMARK | JIO STATUS
```

### Data Sources per Column
- **AM columns (1-13)**: smpcm_product (table 578, db 5)
- **AM MRP**: From model 1808 (latest inward cost price), warehouse-specific. Fallback to smpcm_product.mrp
- **BLINKIT/JIO columns (14-27)**: SAM scraped data (PDP + cascade + stage3 + search)
- **BLINKIT/JIO STATUS**: Computed match status (see logic below)

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
- Browser: Chromium (4 parallel tabs)
- Location: localStorage `location` JSON + cookies `__pincode`, `gr_1_lat`, `gr_1_lon` (NOT `gr_1_lng`)
- Smart wait: poll every 0.5s for API response, max 4s (not fixed sleep)
- PDP redirect detection: name = "blinkit.com" → search fallback → then mark not_available
- Retry pass: failed items get 2nd attempt with fresh browser
- OOS skip: don't visit products Anakin marks as out_of_stock
- MRP fallback: if MRP None, set MRP = SP

### Jiomart
- Browser: **Firefox** (Chromium gets 403 from Akamai CDN)
- Location: cookies `pincode`, `address_pincode`
- Price format: `buybox_mrp` pipe-delimited in `variants[0].attributes.buybox_mrp.text[0]`
  - `parts[4]` = MRP, `parts[5]` = SP
- PDP broken in headless Firefox → Search API (`/trex/search`) is reliable fallback
- DOM TRY 4 (body text regex) **DISABLED** — picks up carousel/bundle prices
- `projects/` names from Google Retail = garbage → skip, use search/DOM name instead
- Pagination: `?page=N` for category pages (up to page 19)
- Grocery-only filter in `_parse_trex_results`

## Cascade/Stage Matching Rules
- **Cascade (Stage 2)**: Brand strict → Product type → Weight ±10% (MANDATORY) → Name score ≥0.55 (or ≥0.70 if weight NA) → MRP ±15% / SP ±25% cross-check → EAN verification
- **Stage 3**: Brand 3-token check → Weight MANDATORY → MRP ±15% → Name score ≥0.50
- **Jiomart Search**: Brand from Anakin field (not first-word) → Score ≥0.55 → Also covers PDP failures + projects/ items
- **EAN**: fetch_ean_map.py loads from smpcm_product. If both sides have barcode, must match.
- **load_cascade_matches**: Higher score wins (stage3 doesn't overwrite better cascade match)

## Cities
- 834002: Ranchi
- 712232: Kolkata
- 492001: Raipur
- 825301: Hazaribagh (**no Jiomart** — skip Jiomart pipeline)

## File Locations
- AM product master: `data/am_product_master.json`
- Latest MRP: `data/latest_mrp_{warehouse}.json`
- EAN map: `data/ean_map.json`
- URL database: `data/mappings/url_database.json`
- Anakin data: `data/anakin/`
- SAM PDP data: `data/sam/`
- Cascade/stage3 output: `data/comparisons/`
- Excel output: `/Users/satyam/Desktop/price csv/`
- Config: `config/output_format.json`, `config/match_status_logic.md`

## BigQuery Tables
| Table | Dataset | Purpose |
|-------|---------|---------|
| `sam_price_history` | googlesheet | SAM daily scrape history (partitioned by date, clustered by pincode+item_code) |
| `cx_competitor_prices` | googlesheet | Anakin's current competitor prices |
| `cx_competitor_prices_external` | googlesheet | Anakin's external table (GCS parquet → BQ) |

### sam_price_history Schema (27 data cols + created_at)
```
date, city, pincode, item_code, item_name, master_cat, brand, marketed_by, product_type, unit, unit_value, am_mrp, image_link, blinkit_url, blinkit_name, blinkit_unit, blinkit_mrp, blinkit_sp, blinkit_stock, blinkit_status, jio_url, jio_name, jio_unit, jio_mrp, jio_sp, jio_stock, jio_status, created_at
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
