# Anakin — Complete Logic & Flow (All Platforms)

> This document captures EVERYTHING we decoded about how Anakin works — so if Anakin data disappears tomorrow, we have the full blueprint to rebuild independently.

---

## 1. Anakin ka Overall Flow

```
┌──────────────────────────────────────┐
│  Apna Mart gives SKU list to Anakin  │
│  (item_code, name, brand, MRP, unit) │
│  Source: smpcm_product (54k SKUs)    │
│  Anakin tracks: ~3,800 top sellers   │
└──────────────┬───────────────────────┘
               │
               ▼
┌──────────────────────────────────────┐
│  Anakin's matching engine            │
│  For each Apna SKU × each platform:  │
│    1. Search/manual map to product   │
│    2. Classify: Complete/Partial/NA  │
│    3. Compute Factor (pack size)     │
│    4. Store mapping (URL + ID)       │
└──────────────┬───────────────────────┘
               │
               ▼
┌──────────────────────────────────────┐
│  Anakin's daily scrape               │
│  Visit cached URLs → get live prices │
│  Push to GCS bucket as Parquet       │
└──────────────┬───────────────────────┘
               │
               ▼
┌──────────────────────────────────────┐
│  GCS → BigQuery → Mirror Dashboard  │
│  Apna team uses for pricing          │
└──────────────────────────────────────┘
```

## 2. Data Pipeline — Verified

| Step | What | How |
|---|---|---|
| **Anakin uploads** | Parquet files daily | `gs://cx_competitor_prices/anakin_raw_data/apnamart_anakin_delivery_*.parquet` |
| **BigQuery external table** | Federated read of parquet | `apna-mart-data.googlesheet.cx_competitor_prices_external` |
| **Scheduled query** | Daily 05:30 IST, owned by `ranjeet.kumar@apnamart.in` | `CREATE OR REPLACE TABLE cx_competitor_prices AS SELECT * FROM cx_competitor_prices_external` |
| **Materialized table** | Queryable by Mirror | `apna-mart-data.googlesheet.cx_competitor_prices` |
| **Mirror dashboard** | Apna analysts view data | `https://mirror.apnamart.in/model/17551-anakin-competitor-prices` |
| **Anakin update time** | ~11:00 AM IST daily | Confirmed by Satyam |

## 3. Blinkit — Anakin's Logic

### 3.1 What Anakin Captures

| Field | Example | Source |
|---|---|---|
| `Blinkit_Product_Url` | `https://blinkit.com/prn/x/prid/32390` | Anakin maps once |
| `Blinkit_Product_Id` | `32390` | From URL |
| `Blinkit_Item_Name` | `7UP Lime Soft Drink` | Scraped from Blinkit |
| `Blinkit_Uom` | `2.25 ltr` | Scraped from Blinkit |
| `Blinkit_Mrp_Price` | `100` | Scraped daily |
| `Blinkit_Selling_Price` | `96` | Scraped daily |
| `Blinkit_Discount__` | `4` | Computed: MRP - SP |
| `Blinkit_Eta_Mins_` | `8` | Delivery ETA |
| `Blinkit_In_Stock_Remark` | `available` / `out_of_stock` | Scraped daily |
| `Blinkit_Status` | `Complete Match` / `Partial Match` / `Semi Complete Match` / `NA` | Anakin classifies |
| `Blinkit_Partial` | `NFNV-Product-Weight-Diff` / `MRP Diff` | Partial reason |
| `Blinkit_Factor` | `0.5` (Apna 500g vs Blinkit 1kg) | Pack normalization |

### 3.2 Match Status Classification

```
if no_match_found:
    Status = "NA"
elif brand_substituted_with_private_label:
    Status = "Semi Complete Match"
    (e.g., "Sugar 1kg" → "Whole Farm Sugar 1kg")
elif brand_matches:
    if FRESH produce (FNV):
        Status = "Complete Match" (even with size diff)
        Factor = pack_ratio
    elif pack_size matches AND mrp matches:
        Status = "Complete Match", Factor = 1
    elif pack_size differs:
        Status = "Partial Match"
        _Partial = "NFNV-Product-Weight-Diff"
        Factor = apna_unit_value / blinkit_unit_value
    elif mrp differs:
        Status = "Partial Match"
        _Partial = "MRP Diff"
    elif container/packaging differs:
        _Partial = "NFNV-Container-Packing-Diff"
    elif color differs:
        _Partial = "Color Diff"
```

### 3.3 Factor Formula

```
Factor = Apna_Unit_Value / Platform_Unit_Value

Examples:
  Apna 500g vs Blinkit 1kg → Factor = 0.5
  Apna 750ml vs Blinkit 200ml → Factor = 3.75
  Apna 5×100g vs Blinkit 4×100g → Factor = 1.25 (pack count ratio)

For multipack: "N x M unit" patterns handled specially
Manual overrides for ~5% edge cases
```

### 3.4 Blinkit-specific Details

- **URL pattern**: `https://blinkit.com/prn/{slug}/prid/{product_id}`
- **Same mapping across all 4 cities** (2,364 mapped, exact same IDs per city)
- **API**: `/v1/layout/product/{prid}` — returns page layout with product data in `snippets[].data.rfc_actions_v2.default[].cart_item`
- **Location**: localStorage `location` JSON + cookies `gr_1_lon` (NOT `gr_1_lng`)
- **Stock rotation**: Products go OOS temporarily (10-20 min) during delivery restocking

## 4. Jiomart — Anakin's Logic

### 4.1 What Anakin Captures

Same 12 fields as Blinkit, prefixed with `Jiomart_*`:

| Field | Example |
|---|---|
| `Jiomart_Product_Url` | `https://www.jiomart.com/p/groceries/7up-2-l/490005200` |
| `Jiomart_Product_Id` | `490005200` |
| `Jiomart_Item_Name` | `7 Up 2.25 L` |
| `Jiomart_Uom` | `2.25 L` |
| `Jiomart_Selling_Price` | `85` |
| `Jiomart_Status` | `Complete Match` |

### 4.2 Jiomart-specific Details

- **URL pattern**: `https://www.jiomart.com/p/groceries/{slug}/{product_id}`
- **Browser**: Must use Firefox (Chromium → 403 from Akamai CDN)
- **PDP page**: React SPA, doesn't render prices in headless Firefox (`productPrice = 0`)
- **Search API**: `/trex/search` returns Google Retail catalog format — reliable for prices
- **Price format**: `buybox_mrp.text[0]` = pipe-delimited: `"store|qty|seller||mrp|price||discount|..."`
- **Coverage varies by city**: Kolkata 2,831, Raipur 2,623, Ranchi 2,512, Hazaribagh 0

## 5. Dmart — Anakin's Logic

### 5.1 Current State

**Dmart column exists but is COMPLETELY EMPTY across all 4 cities and all dates.**

| Field | Value (all cities) |
|---|---|
| `Dmart_Product_Url` | `NA` / `NULL` |
| `Dmart_Product_Id` | `NA` / `NULL` |
| All other `Dmart_*` | `NA` / `NULL` |

### 5.2 Why Empty

- Dmart Ready (online delivery) not available in Ranchi, Kolkata, Raipur, Hazaribagh
- Dmart operates in Mumbai, Bangalore, Pune, Hyderabad etc.
- Anakin created the columns for future expansion but never populated

### 5.3 If We Need Dmart Later

- Base URL: `https://www.dmart.in`
- API: `/api/v1/products/...` — returns JSON with product details
- Store ID required: `DMART_STORE_ID` (e.g., `10151`)
- Works with Chromium
- Category URLs: different structure from Blinkit/Jiomart
- Our manufacture project (`/Users/satyam/Desktop/code/manufacture/dmart/`) has a working Dmart scraper

## 6. Anakin's Scope — What They Track

### 6.1 Coverage

| Metric | Value |
|---|---|
| Apna total active SKUs | 54,891 |
| Anakin tracks | 3,801 (6.9%) |
| Cities | 4 (Ranchi, Kolkata, Raipur, Hazaribagh) |
| Platforms | 3 columns (Blinkit, Jiomart, Dmart) — but Dmart always empty |
| Effective platforms | 2 (Blinkit + Jiomart) |
| History | ~253 days (Aug 2025 - Apr 2026) |
| Update frequency | Daily ~11 AM IST |

### 6.2 Category Focus

| master_category | Anakin SKUs | Coverage of Apna |
|---|---|---|
| FMCGF (Food) | 1,380 | 9.9% |
| FMCGNF (Non-Food) | 1,183 | 8.1% |
| STPLS (Staples) | 721 | 8.9% |
| GM (General Merch) | 257 | 1.6% |
| FRESH (Produce) | 164 | 30.0% |
| BDF (Bread/Dairy) | 96 | 5.4% |

### 6.3 Blinkit Mapping Per City (Latest Data)

| City | Pincode | Total SKUs | Blinkit Mapped | Jiomart Mapped | Dmart |
|---|---|---|---|---|---|
| Ranchi | 834002 | 3,620 | 2,364 | 2,512 | 0 |
| Kolkata | 712232 | 3,724 | 2,364 | 2,831 | 0 |
| Raipur | 492001 | 3,721 | 2,364 | 2,623 | 0 |
| Hazaribagh | 825301 | 3,236 | 2,364 | 0 | 0 |

**Note**: Blinkit mapped count = exactly 2,364 in EVERY city = same mapping list applied universally.

### 6.4 Data Quality Issues We Found

1. `#VALUE!` Excel errors in `Blinkit_Factor`
2. Inconsistent labels: `MRP Diff` / `MRP-Diff` / `MRP DIFF`
3. `partial Match` (lowercase typo)
4. `nan` literal string in `_Partial`
5. Some `Status="Complete Match"` with `Product_Id="NA"` (stale)
6. Wrong mappings: Horlicks Chocolate → Horlicks Women's Plus (104% MRP diff)
7. Anakin's effective delivery rate: only 61% (900/2,364 have no price)

## 7. Apna Mart Product Master — Our Source of Truth

### 7.1 Table: `smpublic.smpcm_product`

| Field | Type | Field ID | Usage |
|---|---|---|---|
| `item_code` | int | 7191 | Primary key — same as Anakin's `Item_Code` |
| `display_name` | text | 7118 | Product name |
| `brand` | text | 7113 | Brand name |
| `mrp` | float | 7158 | Reference MRP |
| `selling_price` | float | 7185 | Apna's own selling price |
| `unit` | text | 7176 | g / ml / kg / ltr / unit |
| `unit_value` | float | 7193 | Numeric quantity |
| `bar_code` | text | 7127 | EAN/UPC (54,858 have it — but ~75% are just item_code copies) |
| `bar_codes` | json | 12890 | Array of barcodes (may include real EAN) |
| `master_category` | text | 8935 | FMCGF / FMCGNF / STPLS / GM / FRESH / BDF |
| `product_type` | text | — | Leaf category |
| `marketed_by` | text | 7133 | Manufacturer |
| `main_image` | text | 7149 | Product image (GCS path — private bucket) |
| `active` | bool | 7161 | Currently sold |

### 7.2 Access

- **Mirror Metabase API**: MBQL queries via `x-api-key` header
- **BigQuery direct**: `bq query` with gcloud auth (`satyam.gupta@apnamart.in`)
- **GCS**: No storage access (bucket `samaan-backend` is private)

## 8. How SAM Replaces Anakin — Complete

### 8.1 Mapping Build (one-time, replaces Anakin's manual mapping)

```
For each Apna SKU (from smpcm_product):
    Stage 0: EAN match (if barcode available on both sides)
    Stage 1: Search on platform by brand + name
    Stage 2: Brand cascade (brand → type → weight → name)
    Stage 3: Type/MRP cascade (type → name → weight → MRP ±15%)
    Stage 4: Image match (pHash — if images accessible)
    Stage 5: Manual review (CSV for human)
    
    Save: {item_code → platform_product_id → URL → confidence}
    File: data/mappings/{platform}_{pincode}.json
```

### 8.2 Daily Refresh (replaces Anakin's daily scrape)

```
Load mapping file (data/mappings/blinkit_834002.json)
For each mapping:
    Visit platform_product_url → scrape price + stock
    Save to daily snapshot
Schedule: 10:30 AM IST (before Anakin's 11 AM)
```

### 8.3 Mapping saved at: `data/mappings/`

```
data/mappings/
├── blinkit_834002.json    (Ranchi Blinkit — 2,363 mappings)
├── blinkit_712232.json    (Kolkata Blinkit)
├── blinkit_492001.json    (Raipur Blinkit)
├── blinkit_825301.json    (Hazaribagh Blinkit)
├── jiomart_834002.json    (Ranchi Jiomart — 2,512 mappings)
├── jiomart_712232.json    (Kolkata Jiomart)
└── jiomart_492001.json    (Raipur Jiomart)
```

**These files = SAM's own mapping. Anakin delete ho jaaye toh bhi kaam chalega.**

---

_Last updated: 2026-04-14. Source: BigQuery direct access + Mirror API + Anakin data reverse engineering._
