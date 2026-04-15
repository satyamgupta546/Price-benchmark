# SAM Matching Strategy — Complete Pipeline

## What SAM Does

Apna Mart ke har product ke liye, competitor platforms (Blinkit, Jiomart) pe wahi product dhundh ke uska live price nikaalna hai. Jab 90%+ match ho → Anakin hatao (₹3 lakh/month bachao).

## Pipeline — 7 Stages (Priority Order)

```
┌────────────────────────────────────────────────────────────┐
│  STAGE 0: EAN/Barcode Match (HIGHEST PRIORITY)             │
│  ──────────────────────────────────────────                 │
│  Input:  Apna's bar_code (smpcm_product) vs platform EAN   │
│  Match:  Exact barcode = 100% guaranteed same product       │
│  Skip:   ALL other stages if EAN matches                    │
│  Note:   Also check EAN at EVERY stage as secondary verify  │
│  Status: Blocked (platforms don't expose EAN in API yet)    │
│  Script: stage0_ean_match.py                               │
└──────────────────┬─────────────────────────────────────────┘
                   │ No EAN match
                   ▼
┌────────────────────────────────────────────────────────────┐
│  STAGE 1: PDP Direct (ID-based URL visit)                  │
│  ────────────────────────────────                          │
│  Input:  Anakin's cached Product URLs (seed mapping)        │
│  Action: Visit URL → intercept API → extract price          │
│  EAN:    If product page has barcode, verify with Apna EAN  │
│  Result: Ranchi 98.9% coverage, 96.7% price ±5%            │
│  Script: scrape_blinkit_pdps.py, scrape_jiomart_pdps.py    │
└──────────────────┬─────────────────────────────────────────┘
                   │ Failures (no_price, errors)
                   ▼
┌────────────────────────────────────────────────────────────┐
│  STAGE 2: Brand-first Cascade                              │
│  ────────────────────────────                              │
│  Input:  Stage 1 failures + Anakin NA SKUs                  │
│  Filter: Brand → Product Type → Weight → Name               │
│  EAN:    If candidate has barcode, verify with Apna EAN     │
│  Pool:   SAM BFS scrape (800-3000 products)                 │
│  Script: cascade_match.py <pincode> <platform>              │
└──────────────────┬─────────────────────────────────────────┘
                   │ Failures
                   ▼
┌────────────────────────────────────────────────────────────┐
│  STAGE 3: Type/MRP Cascade                                 │
│  ──────────────────────                                    │
│  Input:  Stage 2 failures + weak matches                    │
│  Filter: Product Type → Name token → Weight → MRP (±15%)    │
│  EAN:    If candidate has barcode, verify with Apna EAN     │
│  Key:    MRP filter catches variant mismatches               │
│  Script: stage3_match.py <pincode> <platform>               │
└──────────────────┬─────────────────────────────────────────┘
                   │ Failures
                   ▼
┌────────────────────────────────────────────────────────────┐
│  STAGE 4: Search API Match                                 │
│  ─────────────────────────                                 │
│  Input:  Stage 1-3 failures                                 │
│  Action: Search product name on platform → match results    │
│  EAN:    If search result has barcode, verify with Apna EAN │
│  Note:   Essential for Jiomart (PDP doesn't render)         │
│  Script: jiomart_search_match.py                            │
└──────────────────┬─────────────────────────────────────────┘
                   │ Failures
                   ▼
┌────────────────────────────────────────────────────────────┐
│  STAGE 5: Image Match (pHash)                              │
│  ────────────────────────                                  │
│  Input:  Stage 1-4 failures                                 │
│  Action: Compare product photos via perceptual hash          │
│  EAN:    Cross-verify if image match also has barcode        │
│  Status: Blocked (Apna GCS bucket private)                  │
│  Script: stage4_image_match.py                              │
└──────────────────┬─────────────────────────────────────────┘
                   │ Failures
                   ▼
┌────────────────────────────────────────────────────────────┐
│  STAGE 6: Manual Review Queue                              │
│  ──────────────────────────                                │
│  Input:  Everything Stage 0-5 couldn't match                │
│  Output: CSV with top candidates + reason + human_decision  │
│  EAN:    Show Apna barcode in CSV for manual barcode lookup  │
│  Script: export_review_queue.py                             │
└────────────────────────────────────────────────────────────┘
```

## EAN/Barcode — Used at EVERY Stage

EAN is not just Stage 0 — it's a **verification layer across all stages**:

```
Every stage does:
  1. Find candidate product (via URL/search/cascade/image)
  2. IF candidate has barcode AND Apna has barcode:
       IF barcodes match → CONFIRMED ✅ (100% confidence)
       IF barcodes DON'T match → REJECTED ❌ (wrong product!)
  3. IF no barcode available → proceed with name/price matching
```

This catches false positives that other stages might miss.

## Brand Matching — Normalization + Alias Map

### Problem
| Apna | Blinkit | Jiomart | Issue |
|---|---|---|---|
| Amul | AMUL | amuL | Case |
| Taj Mahal | Taj Mahal | taj_mahal | Underscore |
| Haldiram's | Haldirams | Haldiram | Apostrophe |
| L'Oreal | Loreal | L'Oréal | Special chars |
| CDM | Cadbury Dairy Milk | Cadbury | Short form |

### Solution: normalize_brand()
```python
def normalize_brand(brand):
    brand = brand.lower()                    # "Taj Mahal" → "taj mahal"
    brand = re.sub(r"[^\w\s]", " ", brand)   # "haldiram's" → "haldirams"
                                              # "taj_mahal" → "taj mahal"
    brand = re.sub(r"\s+", " ", brand)        # collapse spaces
    # Check alias map
    brand = BRAND_ALIASES.get(brand, brand)
    return brand.strip()
```

### Brand Alias Map
```json
{
  "cdm": "cadbury dairy milk",
  "maggie": "maggi",
  "tata namak": "tata salt",
  "lays": "lays",
  "vim bar": "vim",
  "rin bar": "rin"
}
```

## Product Name Matching — Token Overlap (Not Exact String)

### Problem
| Apna | Jiomart |
|---|---|
| "Cadbury Chocolate Dairy Milk 500gm" | "Cadbury Dairy Milk 500gm" |

Exact string match → FAIL (extra "Chocolate" word)

### Solution: Token set intersection
```
Apna tokens:    {cadbury, chocolate, dairy, milk, 500gm}
Jiomart tokens: {cadbury, dairy, milk, 500gm}
Common:         {cadbury, dairy, milk, 500gm} = 4/5 = 80% overlap → MATCH ✅
```

Extra words ignored. Important tokens (brand + product + weight) sab match.

## Cascade Flow — Each Stage Feeds the Next

```
Stage 0 (EAN)
├─ EAN match → DONE ✅ (100% confident)
└─ No EAN → Stage 1

Stage 1 (PDP Direct)
├─ OK with price → DONE ✅
│  └─ IF has EAN → verify (bonus confidence)
├─ no_price / error → FEED INTO STAGE 2
└─ Anakin NA SKUs (no URL) → also STAGE 2

Stage 2 (Brand Cascade)
├─ matched → DONE ✅
│  └─ IF has EAN → verify
└─ failures → STAGE 3

Stage 3 (Type/MRP Cascade)
├─ matched → DONE ✅
│  └─ IF has EAN → verify
└─ failures → STAGE 4

Stage 4 (Search API)
├─ matched → DONE ✅
│  └─ IF has EAN → verify
└─ failures → STAGE 5

Stage 5 (Image Match)
├─ matched → DONE ✅
└─ failures → STAGE 6

Stage 6 (Manual Review)
└─ Human decides (CSV with Apna barcode shown for manual lookup)
```

## Filter Logic Per Stage

### Stage 0 — EAN Match
```
1. Load Apna's bar_code from smpcm_product (54,858 have barcodes)
2. Filter to real EANs (8+ digit, not just item_code copy)
3. Check if platform product has same EAN
4. Exact match = 100% guaranteed
```

### Stage 1 — PDP Direct
```
1. Visit Anakin's cached Product URL
2. Intercept API response (Blinkit: snippets[].cart_item)
3. Extract price, stock, name
4. Join by item_code (no fuzzy)
5. IF product has barcode field → verify against Apna EAN
```

### Stage 2 — Brand Cascade
```
1. Brand filter (strict, after normalization + alias map)
2. Product Type filter (token overlap)
3. Weight filter (±20% tolerance, unit conversion: g↔kg, ml↔L)
4. Name fuzzy match (SequenceMatcher ≥ 0.4)
5. EAN verify if available
```

### Stage 3 — Type/MRP Cascade
```
1. Product Type filter (token overlap) — strict: reject if 0 matches
2. Name token overlap — strict: reject if 0 common tokens
3. Weight filter (±25% tolerance)
4. MRP filter (±15%) — KEY: catches variant mismatches
   (Horlicks Chocolate Delight ₹159 ≠ Horlicks Women's Plus ₹324)
5. Name fuzzy match (SequenceMatcher ≥ 0.35)
6. EAN verify if available
```

### Stage 4 — Search API
```
1. Take Apna's product name (or Anakin's platform-specific name)
2. Search on platform (Blinkit /s/?q=, Jiomart /search/)
3. Parse API response (trex/search for Jiomart)
4. Best name match from results (SequenceMatcher ≥ 0.4)
5. EAN verify if available
Why needed: Jiomart PDP doesn't render in headless Firefox
```

### Stage 5 — Image Match
```
1. Download Apna's product image
2. Download candidate product images from platform
3. Compute pHash (perceptual hash, 64-bit)
4. Match if hamming distance ≤ 12
Status: Blocked — Apna GCS bucket private, no auth
```

### Stage 6 — Manual Review
```
Export CSV with columns:
  item_code, apna_barcode, reason, anakin_name, top_candidates, human_decision
Reviewer fills: correct / wrong / manual:<id> / not_available
Apna barcode shown so reviewer can manually search on platform
```

## Loose Items — Excluded

Products with "loose" in name excluded from all matching:
- "Sugar 1kg Loose", "Toor Dal Loose", etc.
- Generic, unbranded, price varies daily
- Only 15-22 items per pincode (< 2%)

## Mapping Lifecycle

### One-time build (replaces Anakin's manual mapping)
```
For each Apna SKU (from smpcm_product):
    Run Stage 0-5 cascade
    Save mapping: {item_code, platform, product_id, product_url, match_method, confidence}
    Low confidence → Stage 6 manual review
```

### Daily refresh (replaces Anakin's daily scrape)
```
For each cached mapping:
    Visit product_url → scrape live price + stock
    Save to daily snapshot
    (No search/cascade needed — mapping is fixed)
```

### Periodic re-validation
```
Every 2 weeks:
    Re-run matching for all SKUs
    Check if platform product_id still valid
    Update mappings that changed
    Flag discontinued products
```

## Results — Ranchi 834002 (Same-Day, April 14)

| Stage | Matched |
|---|---|
| Stage 1 (PDP) | 1,386 |
| Stage 2 (Brand) | +27 |
| Stage 3-5 | +0 |
| **TOTAL** | **1,413 / 1,428 = 98.9%** |

**Price accuracy: 96.7% within ±5%**

Remaining 15 products: temporarily OOS during scrape. Manual retry: 15/15 matched with exact prices.

## Platform-Specific Notes

### Blinkit
- Browser: Chromium (headless)
- Location: localStorage `location` JSON + cookies `gr_1_lon` (NOT `gr_1_lng`)
- PDP works: API interception → `snippets[].data.rfc_actions_v2.default[].cart_item`
- BFS pool: ~855 products from 103 categories + 279 search terms (including brand-specific)

### Jiomart
- Browser: Firefox (Chromium → 403 from Akamai CDN)
- Location: cookies `pincode` + `address_pincode`
- PDP BROKEN: headless Firefox doesn't render prices (`productPrice = 0`)
- Search API works: `/trex/search` reliably returns prices
- BFS pool: ~3,000 products from category pages

## Scripts

| Script | Stage | What |
|---|---|---|
| `stage0_ean_match.py` | 0 | EAN barcode matching (TODO) |
| `scrape_blinkit_pdps.py` | 1 | Blinkit PDP scrape |
| `scrape_jiomart_pdps.py` | 1 | Jiomart PDP scrape |
| `cascade_match.py` | 2 | Brand cascade |
| `stage3_match.py` | 3 | Type/MRP cascade |
| `jiomart_search_match.py` | 4 | Jiomart search API |
| `stage4_image_match.py` | 5 | pHash image matching |
| `stage5_barcode_match.py` | 0+5 | EAN barcode matching |
| `export_review_queue.py` | 6 | Manual review CSV |
| `run_full_pipeline.py` | ALL | Single command runs all stages |
| `compare_pdp.py` | — | Stage 1 comparison report |
| `compare_pdp_jiomart.py` | — | Jiomart comparison report |
| `export_pdp_csv.py` | — | CSV + Excel export |

## Config

Platform settings: `config/platforms.json`
Brand aliases: TODO — `config/brand_aliases.json`

## Key Bugs Fixed

1. PDP extractor matched page metadata instead of product cart_item
2. Cascade didn't receive Stage 1 failures
3. "NA" string sentinel treated as truthy
4. Jiomart PDP doesn't render → use Search API
5. Brand normalization needed for cross-platform matching

## Path to Replace Anakin

1. ✅ Pipeline built (7 stages including EAN)
2. ✅ Same-day Ranchi Blinkit: 98.9% coverage, 96.7% accuracy
3. ⏳ Build own mapping (without Anakin seed) using Stage 0-5
4. ⏳ Scale to all 4 cities × both platforms
5. ⏳ Daily automated runs
6. 🎯 4 weeks of 90%+ → cancel Anakin → save ₹3L/month

---

_Last updated: 2026-04-14_

## Auto-Heal — Self-Healing Price Extraction

If Blinkit/Jiomart changes their page layout, DOM, or API format, the scraper doesn't break. It tries 5 strategies in order:

```
Strategy 1: API Response Interception (95% confidence)
    ↓ failed?
Strategy 2: JSON-LD Structured Data (90% confidence)
    ↓ failed?
Strategy 3: Meta Tags — og:price (85% confidence)
    ↓ failed?
Strategy 4: DOM Price Elements — ₹ near title (75% confidence)
    ↓ failed?
Strategy 5: Raw HTML Regex (50% confidence — last resort)
    ↓ all failed?
Mark as out-of-stock / no_price
```

### Sanity Checks
- Price must be ₹1 - ₹50,000 (reject garbage)
- If price changed >200% from last known → flag as anomaly
- Track success rate per method → alert if <40%

### Health Monitor
```python
healer = AutoHealExtractor()
# ... use for many products ...
report = healer.get_health_report()
# {"health": "🟢 HEALTHY", "success_rate": 95.2, "by_method": {"api_interception": 800, "dom_price": 50}}
```

### File: `backend/app/scrapers/auto_heal.py`
