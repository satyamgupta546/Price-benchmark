# SAM Pipeline — Complete Flow & Logic

## STEP 0: Setup & Config

```
sam_daily_run.py → main()
├── gcloud account switch (satyam.gupta@apnamart.in)
├── Load config/cities.json → CITIES, WAREHOUSE_MAP, CITY_PLATFORMS
├── Valid master categories: STPLS, FMCG, FMCGF, FMCGNF, GM
```

---

## STEP 1: Data Fetch (Sequential)

### 1a. EAN Map

```
fetch_ean_map.py → data/ean_map.json
  smpcm_product (table 578, db 5) → bar_code field (7127)
  Output: {item_code: "8901030855054", ...}
```

### 1b. Item Codes Collection (3 sources)

```
Source 1: url_database.json (PRIMARY — 17,446+ URLs)
Source 2: kvi_master.json (high-priority items)
Source 3: Anakin files (OPTIONAL supplement — shutting down)
```

### 1c. AM Product Master

```
fetch_am_master() → Metabase API → smpcm_product (table 578, db 5)
  Fields: item_code, display_name, master_category, brand, marketed_by,
          product_type, unit, unit_value, mrp, main_image, sub_variant, variant, pack_size
  Batch: 100 item_codes per query
  Output: data/am_product_master.json
```

### 1d. Latest MRP (per warehouse)

```
fetch_latest_mrp() → Metabase API → model 1808 (db 3)
  Filter: warehouse_id (WRHS_1/WRHS_2/WRHS_10)
  Pagination: 2000 rows/page, max 15 pages
  Output: data/latest_mrp_{warehouse}.json

  Warehouse map:
    834002 Ranchi, 825301 Hazaribagh → WRHS_1
    492001 Raipur, 495001 Bilaspur  → WRHS_2
    712232 Kolkata                   → WRHS_10
```

---

## STEP 2: City Processing (Sequential per city, Parallel per platform)

Each city calls `process_city()` which does:

```
process_city(pin, city)
├── scrape_city()          ← Blinkit + Jiomart + DMart in PARALLEL (threading)
├── generate_city_data()   ← merge all data + compute status
├── validate_data()        ← sanity checks
├── push_to_bigquery()     ← dedup DELETE + APPEND
└── backup_to_gcs()        ← gs://sam-price-data/{date}/{pin}.csv
```

### scrape_city() — 3 platforms in parallel threads

---

### BLINKIT Pipeline

```
1. scrape_blinkit_pdps.py [pincode] [8 tabs]
   ├── Load URLs from: url_database.json + Anakin (fallback)
   ├── Launch Chromium (headless, 8 parallel tabs)
   ├── Set location: localStorage 'location' JSON + cookies (__pincode, gr_1_lat, gr_1_lon)
   ├── Visit each PDP URL → extract: name, SP, MRP, stock, unit
   ├── Redirect detection: homepage redirect / prid mismatch / slug mismatch → "not_available"
   ├── Smart wait: poll 0.5s for API response, max 4s
   └── Output: data/sam/blinkit_pdp_{pincode}_{date}.json

2. compare_pdp.py [pincode]   ← Stage 1: Exact Join
   ├── item_code se direct join (Anakin ↔ SAM PDP)
   ├── No fuzzy matching, just price comparison
   └── Output: comparison report

3. unified_matcher.py [pincode] blinkit  ← Stage 2+3: Unified Match (replaces cascade+stage3)
4. stage4_image_match.py [pincode] blinkit  ← Stage 4: Image
5. stage5_barcode_match.py [pincode] blinkit  ← Stage 5: Barcode
```

### JIOMART Pipeline

```
1. test_jiomart_pdp.py --all --pincode [pincode]
   ├── Firefox browser (Akamai blocks Chromium)
   ├── Category scrape: /categories → 94 grocery sub-cats → visit each
   ├── Product data: dataLayer + DOM parsing
   ├── Save to jiomart_product_master.json (permanent store)
   └── Output: data/sam/jiomart_category_{pincode}_latest.json

2. unified_matcher.py [pincode] jiomart  ← Stage 2+3: Unified Match
3. stage4_image_match.py [pincode] jiomart
4. stage5_barcode_match.py [pincode] jiomart
```

### DMART Pipeline

```
1. scrape_dmart.py [pincode]
   ├── Pure API (no browser needed)
   └── Output: data/sam/dmart_{pincode}_{date}.json
   (No cascade/stage matching — uses rapidfuzz name match in generate_city_data)
```

---

## STAGE 1: PDP Compare (compare_pdp.py)

```
- Exact join on item_code (Anakin ↔ SAM PDP)
- No fuzzy matching, no name comparison
- Same item_code → compare prices directly
- Output: comparison report with price diffs
```

---

## STAGE 2+3: Unified Matcher (unified_matcher.py — replaces cascade_match.py + stage3_match.py)

Single-pass deterministic matcher. All AM products matched in one run.

### Algorithm Flow

```
STEP 1: EAN Fast-Track
  If Apna barcode matches any SAM product barcode
  → instant COMPLETE MATCH (bypass all text/price logic)

STEP 2: Build Candidates
  Path A: Brand STRICT match (normalized with alias dictionary)
    e.g., "chings" → "ching's secret", "maggie" → "maggi"
    → narrows ~12k products to ~50-200
  Path B (no brand hit): Name/brand token overlap
    brand_ok OR ≥2 common name tokens (≥3 if brand known but mismatched)

STEP 3: Weight Filter (±10%) — MANDATORY for non-loose items
  Advanced multipack parser:
    "500 g" → 500g | "2 x 500g" → 1000g | "Pack of 4 x 100ml" → 400ml
  Precomputed in set_pool() for speed
  Loose items: unit TYPE match only (weight↔weight, volume↔volume)

STEP 4: Score Each Candidate
  a. Packaging Check: rigid (jar/tin/bottle) vs soft (pouch/refill)
     → mismatch = flag "packaging_mismatch"
  b. Variant Check: critical tokens (moong/toor/masoor, dark/milk/white, salted/unsalted)
     → conflict within same group = flag "variant_mismatch"
  c. EAN Cross-Check: if both have barcodes, must match → else skip
  d. Name Score: token_set_ratio (rapidfuzz, order-independent, 0-100)

STEP 5: Status Determination
  Loose/ASM in STPLS:
    score ≥ 40 + MRP ratio 0.3-3.0 + keyword overlap → SEMI COMPLETE MATCH
  Non-loose:
    Any heuristic flag (packaging/variant) → max PARTIAL MATCH
    score < 40 → NA
    score 40-64 → PARTIAL MATCH
    score ≥ 65 + MRP exact (±0.01) → COMPLETE MATCH
    score ≥ 65 + MRP mismatch → PARTIAL MATCH
```

### Thresholds

| Parameter | Value |
|-----------|-------|
| NAME_SCORE_COMPLETE | 65.0 (token_set_ratio) |
| NAME_SCORE_PARTIAL | 40.0 |
| WEIGHT_TOLERANCE | ±10% (0.9-1.1 ratio) |
| MRP_EXACT_TOL | ±0.01 |
| MRP_LOOSE_RATIO | 0.3-3.0x |
| PRICE_SANITY_MULT | 3.0x (SP > 3× AM MRP → reject) |

Output: `data/comparisons/{platform}_unified_{pincode}_{ts}.json`

---

## STAGE 4: Image Match (stage4_image_match.py)

For unmatched SKUs after Stage 1-3.

```
1. Download AM product image (from main_image / Anakin Image_Link)
   ├── Fix GCS URLs: storage.cloud.google.com → storage.googleapis.com
   ├── Retry with 2x timeout on failure
   └── Skip loose items (name contains "loose")

2. Compute pHash (perceptual hash, 8x8 = 64 bits)

3. Compare against every SAM pool product's image
   ├── Download SAM image → compute pHash
   ├── Hamming distance = diff between hashes
   └── Threshold: ≤ 12 bits difference = match

4. Best visual match (lowest hamming distance) → new mapping
```

Output: merged into cascade/stage3 results

---

## STAGE 5: Barcode Match (stage5_barcode_match.py)

For unmatched SKUs after Stage 1-4.

```
Method 1: EAN Pool Lookup
  ├── Get Apna barcode from ean_map.json
  ├── Check if any SAM pool product has same barcode
  └── Exact barcode match = 100% guaranteed same product

Method 2: Search-by-barcode (Blinkit only)
  ├── Open Playwright browser → set location
  ├── Search barcode string on Blinkit (e.g., "8901030855054")
  ├── Intercept API response → extract products
  └── Match if product found

Filter: Only real EAN barcodes (8+ digits, not internal item_codes)
```

Output: merged into cascade results

---

## STEP 3: Data Merge + Status (generate_city_data)

### Data Loading Priority

```
For each AM product (item_code):
  1. PDP data (status == "ok") ← highest priority
  2. Cascade/Stage3 matches   ← fallback
  3. If PDP says "not_available" → skip cascade too → force NA
```

### Sanity Filters in get_sam()

```
Filter 1: Price sanity
  if sam_sp > 3 x am_mrp → reject (combo/bulk product)

Filter 2: Variant check
  weight ratio (sam/am) outside 0.7 - 1.5 → reject (wrong variant)
```

### DMart Matching (inline, no stages)

```
For each AM product:
  ├── Clean AM name (strip unit suffix)
  ├── Clean DMart name (strip SKU suffix, remove "dmart premia/swaad" prefix)
  ├── Brand check: AM brand ∩ DMart brand (skip if different, unless score ≥80)
  ├── rapidfuzz.token_sort_ratio(am_clean, dmart_clean)
  └── Best match with score ≥ 50 → use it
```

---

## Match Status Logic (compute_status)

### Helper Functions

#### parse_wt() — Weight Parsing

```
Parses weight from product name:
  "Amul Butter 500 g" → (500.0, "g")
  "Tata Salt 1 kg"    → (1.0, "kg")

Regex: (\d+\.?\d*)\s*(g|gm|gms|kg|kgs|ml|mls|l|ltr|ltrs|pc|pcs|piece|pieces|unit|units|n|nos)
Normalize: gm/gms→g, kgs→kg, mls→ml, ltrs→ltr, pcs/piece/units/n/nos→pc
```

#### unit_type_group() — Unit Type Grouping

| Group    | Units                          |
|----------|--------------------------------|
| weight   | g, gm, gms, kg, kgs           |
| volume   | ml, mls, l, ltr, ltrs          |
| count    | pc, pcs, piece, unit, n, nos   |

### LOOSE/ASM Detection

```python
is_loose_asm = (
    ("loose" in am_name_lower
     or "asm" in am_name_lower.split()
     or am_pt in ("LOOSE", "ASM"))
    and am.get("master_category") == "STPLS"
)
```

3 conditions me se koi ek + master_category = STPLS:
- Name me "loose" ho
- Name ke words me "asm" ho
- product_type LOOSE ya ASM ho

### Status Decision Tree

```
                    ┌─────────────────┐
                    │  sam_sp is None? │
                    └────────┬────────┘
                        YES │        NO
                        ┌───┘        └──────────────┐
                       "NA"                          │
                                        ┌────────────▼───────────┐
                                        │ Is LOOSE/ASM + STPLS?  │
                                        └────────────┬───────────┘
                                            YES │         NO
                                    ┌───────────┘         └──────────────┐
                                    │                                     │
                        ┌───────────▼──────────┐            ┌────────────▼──────────┐
                        │ Unit TYPE matches?    │            │ Unit value ±10%?      │
                        │ (weight↔weight, etc.) │            │ (after kg→g convert)  │
                        └───────────┬──────────┘            └────────────┬──────────┘
                        YES │       NO                     True │  False │  None
                            │    PARTIAL                        │  PARTIAL  │
                ┌───────────▼──────────┐                       │           │
                │ MRP ratio 0.3-3.0x?  │                ┌──────▼───────────▼──────┐
                └───────────┬──────────┘                │ MRP exact (±0.01)?     │
                YES │       NO                          └───────────┬────────────┘
                    │    PARTIAL                         YES │        NO
        ┌───────────▼──────────┐                            │     PARTIAL
        │ ≥1 keyword common?   │                    "COMPLETE MATCH"
        └───────────┬──────────┘
        YES │       NO
            │    PARTIAL
    "SEMI COMPLETE MATCH"
```

### Status Definitions

| Status | Condition |
|--------|-----------|
| **NA** | `sam_sp is None` — no price found on platform |
| **SEMI COMPLETE MATCH** | LOOSE/ASM + STPLS + unit type same + MRP ratio 0.3-3x + ≥1 keyword common |
| **COMPLETE MATCH** | MRP exact (±0.01) + unit value ±10% (or unparseable) |
| **PARTIAL MATCH** | Everything else (default fallback) |

### SEMI COMPLETE MATCH — Detailed Checks

```
1. Unit type match — kg↔g both "weight" group = OK. AM=kg, SAM=ml → PARTIAL
2. MRP ratio — SAM_MRP / AM_MRP between 0.3 and 3.0. Outside → PARTIAL (wrong product)
3. Keyword match — At least 1 meaningful word common (dal↔dal, rice↔rice)
   Skip generic words: loose, 1kg, 1, kg, g, ml, l, pack, of, the, -, |
   No common keyword → PARTIAL
All 3 pass → SEMI COMPLETE MATCH
```

### COMPLETE MATCH — Detailed Checks

```
1. Unit value ±10% check (after normalization):
   - kg→g (x1000), l→ml (x1000)
   - ratio: 0.9 ≤ sam_weight / am_weight ≤ 1.1
   - Three states: True (match), False (mismatch), None (can't parse)
   - False → immediate PARTIAL (can never be COMPLETE)

2. MRP exact match:
   - abs(AM_MRP - SAM_MRP) < 0.01 (practically equal)

3. Both conditions:
   - mrp_match=True AND unit_match is not False → COMPLETE MATCH
   - Otherwise → PARTIAL MATCH
```

---

## STEP 4: Output

### Excel (35 columns, single sheet)

```
generate_excel() → SAM_{city}_{pincode}_{date}.xlsx

Headers:
  DATE | TIME | CITY | PINCODE |
  AM ITEM CODE | AM ITEM NAME | AM master cat | AM BRAND | AM MARKETED BY |
  AM PRODUCT TYPE | AM UNIT | AM UNIT VALUE | AM MRP | IMAGE LINK |
  BLINKIT URL | BLINKIT ITEM NAME | BLINKIT UNIT | BLINKIT MRP | BLINKIT SP |
  BLINKIT IN STOCK REMARK | BLINKIT STATUS |
  JIO URL | JIO ITEM NAME | JIO UNIT | JIO MRP | JIO SP |
  JIO IN STOCK REMARK | JIO STATUS |
  DMART URL | DMART ITEM NAME | DMART UNIT | DMART MRP | DMART SP |
  DMART IN STOCK REMARK | DMART STATUS

Color coding: AM=blue, Blinkit=green, Jio=yellow, DMart=purple
Freeze pane at E2
```

### BigQuery Push

```
push_to_bigquery()
  1. DELETE from sam_price_live WHERE date=today AND pincode IN (...)  ← dedup
  2. APPEND to sam_price_live
  3. APPEND to sam_price_history  ← permanent record

backup_to_gcs()
  gs://sam-price-data/{date}/{pincode}.csv
```

### Validation (before push)

```
validate_data():
  ├── Total rows > 0
  ├── Each pincode ≥ 100 rows
  ├── No item_code = None
  ├── blinkit_sp / jio_sp in range 0-50000
  └── At least 10% rows have blinkit_sp
```

---

## STEP 5: Post-run

```
1. URL database update — new URLs from PDP saved to url_database.json (only adds, never removes)
2. KVI coverage report — per state, Super KVI tracking
3. Cleanup — delete files older than 7 days (if >20 files in dir)
4. Summary alert — send_daily_summary() with cities, row counts, errors
```

---

## Load Priority (Higher stage doesn't overwrite better match)

```
PDP (Stage 1) > Cascade (Stage 2) > Stage 3 > Stage 4 (Image) > Stage 5 (Barcode)

In load_cascade(): if ic not in cm → only first match is kept
  cascade_match output loaded first → stage3 can't overwrite better cascade match
```

---

## Search Pool (for Stage 2-5)

```
All stages use the SAME search pool, built from:
  1. BFS scrape data (data/sam/{platform}_{pincode}_*.json)
  2. Category discovery (data/sam/{platform}_category_{pincode}_*.json)
  3. Jiomart product master (data/jiomart_product_master.json) — for jiomart only

Deduplication: seen_pids set prevents same product appearing twice
```

---

## Cities & Platforms

| City | Pincode | Warehouse | Blinkit | Jiomart | DMart |
|------|---------|-----------|---------|---------|-------|
| Ranchi | 834002 | WRHS_1 | Yes | Yes | No |
| Hazaribagh | 825301 | WRHS_1 | Yes | No | No |
| Raipur | 492001 | WRHS_2 | Yes | Yes | No (closed) |
| Kolkata | 712232 | WRHS_10 | Yes | Yes | No |
| Bilaspur | 495001 | WRHS_2 | Yes | Yes | No |
| Jamshedpur | 831001 | WRHS_1 | Yes | Yes | No |

---

## Script Run Order (per platform per city)

```
Blinkit:  scrape_blinkit_pdps → compare_pdp → unified_matcher → stage4_image_match → stage5_barcode_match
Jiomart:  test_jiomart_pdp --all → unified_matcher → stage4_image_match → stage5_barcode_match
DMart:    scrape_dmart (API only, matching done inline in generate_city_data)
```

---

## Error Handling

```
run() function:
  ├── Retries: 2 attempts by default (configurable)
  ├── Timeout: 7200s (2 hours) default
  ├── Wait between retries: 10s × (attempt + 1)
  ├── RUN_ERRORS list collects all failures
  └── Critical scripts trigger alert on failure

process_city():
  ├── If scrape crashes → retry entire city once
  └── If retry also fails → skip city, log error

End of run:
  ├── Summary alert with all errors
  └── Print error count
```
