# Data Storage Strategy

## What it does

Defines where SAM stores scraped data, Anakin reference data, comparison reports, and (eventually) the production output that replaces Anakin's pipeline.

## Current (Day 1-3) — Local JSON files

```
data/
├── anakin/                                    ← Anakin reference (read-only ground truth)
│   ├── blinkit_834002_2026-04-11.json        (Anakin Blinkit data for Ranchi, latest)
│   └── blinkit_834002_2026-04-11.csv         (same, CSV view)
├── sam/                                      ← Our scrape output
│   └── blinkit_<pincode>_<timestamp>.json
└── comparisons/                               ← Comparison reports
    └── blinkit_<pincode>_<timestamp>_compare.json
```

**Why JSON files for now:**
- Zero infra setup
- Easy to inspect / version-control
- Sufficient for 4 pincodes × 5 platforms (~20 files per day)
- Easy to load into Python or pandas for analysis

**Limits:**
- Doesn't scale beyond a few thousand SKUs per file (becomes slow to load)
- No time-series queries (have to load each day's file separately)
- Not concurrent-safe (two processes writing the same file = corruption)
- No deduplication / change detection across snapshots

## Long-term — Choose ONE of these (decide after Day 3)

### Option A — BigQuery (recommended) ⭐

Push SAM output as a parallel table next to Anakin's:

```
apna-mart-data.googlesheet.cx_competitor_prices         ← Anakin's table (existing)
apna-mart-data.googlesheet.cx_competitor_prices_sam    ← SAM's table (new, same schema)
apna-mart-data.googlesheet.cx_competitor_prices_diff    ← daily diff view
```

**Pros:**
- Apna analysts can query side-by-side with zero migration
- Same schema as Anakin → existing dashboards work with minimal change
- Time-series queries are trivial
- Scales to billions of rows
- Free for our scale (within free tier)

**Cons:**
- Need write access to BQ (have read currently)
- Need a load pipeline (parquet upload → BQ external → materialize) — same pattern as Anakin

**Path to set up:**
1. Get write access from `ranjeet.kumar@apnamart.in` for `apna-mart-data.googlesheet` dataset
2. Or get a service-account key with BQ Data Editor role
3. Write a daily upload script that materializes our local JSON → parquet → GCS → BQ load
4. Or use BQ direct streaming inserts (simpler, slightly more expensive)

### Option B — Postgres (local/Cloud SQL)

Run a Postgres instance and store everything in normalized tables:

```sql
CREATE TABLE products (
    id BIGSERIAL PRIMARY KEY,
    pincode TEXT,
    platform TEXT,
    item_code BIGINT,                  -- Apna SKU code
    platform_product_id TEXT,
    name TEXT, brand TEXT,
    unit TEXT, unit_value NUMERIC,
    mrp NUMERIC, selling_price NUMERIC,
    in_stock BOOLEAN,
    scraped_at TIMESTAMPTZ,
    image_url TEXT
);
CREATE INDEX ON products (pincode, platform, scraped_at);
CREATE INDEX ON products (item_code);
```

**Pros:**
- SQL queries familiar
- Strong consistency
- Good for transactional reads (single SKU lookup)

**Cons:**
- Need to manage a server
- Not directly visible to Apna analysts (they use BQ via Mirror)
- Migration overhead later if we move to BQ

### Option C — Google Sheet (drop-in Anakin replacement)

Push to a Google Sheet at the same path Anakin uses, formatted identically:

```
gs://cx_competitor_prices/sam_raw_data/sam_delivery_<timestamp>.parquet
```

Then have a parallel scheduled query that materializes it into `cx_competitor_prices_sam`.

**Pros:**
- Same consumption pattern as Anakin
- Apna team needs no training

**Cons:**
- Same fragility as Anakin's pipeline (Excel errors, etc.)
- Slower than direct BQ writes

## Schema (target — same as Anakin's)

For long-term BQ table, mirror Anakin's schema so dashboards work without changes:

```
Date, City, Pincode, Item_Code, Item_Name, Brand, Product_Type, Unit, Unit_Value, Mrp, Image_Link,
Blinkit_Product_Url, Blinkit_Product_Id, Blinkit_Item_Name, Blinkit_Uom,
Blinkit_Mrp_Price, Blinkit_Selling_Price, Blinkit_Discount__,
Blinkit_Eta_Mins_, Blinkit_In_Stock_Remark, Blinkit_Status, Blinkit_Partial, Blinkit_Factor,
Jiomart_*, Dmart_* (same 12 columns × 3 platforms)
```

**Plus extras Anakin doesn't have:**
- `Zepto_*` (12 cols)
- `Instamart_*` (12 cols)
- `Flipkart_Min_*` (12 cols)
- `match_method` (fuzzy / image / manual / anakin_seed)
- `match_confidence` (0-1 score)
- `last_remapped_at`

## Open questions

1. **Cardinality** — how many SKUs × how many cities × how many platforms × daily snapshots?
   - Conservative: 4,000 × 4 × 6 × 365 = ~35M rows/year (BQ trivial, Postgres fine)
   - Aggressive (full Apna catalog): 55,000 × 50 × 6 × 365 = ~6B rows/year (BQ only)

2. **Retention** — how long do we keep history?
   - Anakin keeps 253 days = ~8 months
   - We can match that initially

3. **Snapshot strategy** — full reload daily, or incremental?
   - Anakin does full reload (`CREATE OR REPLACE TABLE`) — simple but wasteful
   - Better: incremental upsert + snapshot every N days

## Next decisions

- [ ] After Day 3: pick BQ vs Postgres vs Sheet
- [ ] After Day 3: get write access to chosen target
- [ ] Build daily upload pipeline
- [ ] Set up monitoring (file count, row count, freshness alerts)
