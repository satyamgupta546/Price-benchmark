# Matching Strategy — 6-Stage Pipeline

## What We're Doing

Apna Mart ke har product ke liye, competitor platforms (Blinkit, Jiomart) pe wahi product dhundh ke uska live price nikaalna hai. Phir verify karna hai ki hamara data Anakin ke data se match karta hai ya nahi. Jab 90%+ match ho → Anakin hatao (₹3 lakh/month bachao).

## 6 Stages — Run in this exact order

```
┌────────────────────────────────────────────────────────────┐
│  STAGE 1: PDP Direct (ID-based)                            │
│  ────────────────────────────────                          │
│  Input:  Anakin's cached Product URLs                      │
│  Action: Visit each URL → scrape live price via API        │
│  Works:  Blinkit (Chromium, API interception)              │
│  Result: Blinkit Ranchi 97.4% coverage                     │
│  Script: scrape_blinkit_pdps.py, scrape_jiomart_pdps.py    │
└──────────────────┬─────────────────────────────────────────┘
                   │ Failures (no_price, errors)
                   ▼
┌────────────────────────────────────────────────────────────┐
│  STAGE 2: Brand-first Cascade                              │
│  ────────────────────────────                              │
│  Input:  Stage 1 failures + Anakin NA SKUs                 │
│  Filter: Brand → Product Type → Weight → Name              │
│  Pool:   SAM BFS scrape (800-3000 products)                │
│  Script: cascade_match.py <pincode> <platform>             │
└──────────────────┬─────────────────────────────────────────┘
                   │ Failures
                   ▼
┌────────────────────────────────────────────────────────────┐
│  STAGE 3: Type/MRP Cascade                                 │
│  ──────────────────────                                    │
│  Input:  Stage 2 failures + weak matches                   │
│  Filter: Product Type → Name token → Weight → MRP (±15%)   │
│  Key:    MRP filter catches variant mismatches              │
│          (Horlicks Chocolate ≠ Horlicks Women's Plus)       │
│  Script: stage3_match.py <pincode> <platform>              │
└──────────────────┬─────────────────────────────────────────┘
                   │ Failures
                   ▼
┌────────────────────────────────────────────────────────────┐
│  STAGE 4: Search API Match (Jiomart-specific)              │
│  ─────────────────────────────────────                     │
│  Input:  Stage 1-3 failures (Jiomart only)                 │
│  Action: Search by product name on Jiomart → /trex/search  │
│          API returns prices reliably (PDP doesn't render    │
│          in headless Firefox)                               │
│  Result: 95% hit rate on unmatched Jiomart products         │
│  Script: jiomart_search_match.py <pincode>                 │
│  NOTE:   Blinkit doesn't need this (PDP works fine)        │
└──────────────────┬─────────────────────────────────────────┘
                   │ Failures
                   ▼
┌────────────────────────────────────────────────────────────┐
│  STAGE 5: Image Match + Barcode Match                      │
│  ────────────────────────────────────                      │
│  Input:  Stage 1-4 failures                                │
│  Image:  Compare product photos via pHash (Pillow +        │
│          imagehash). Requires accessible image URLs.        │
│  Barcode: Match by EAN/UPC barcode (exact = 100% match).   │
│  Current status:                                           │
│    - Image: blocked (Apna GCS bucket private, no auth)     │
│    - Barcode: 0 matches (Blinkit API doesn't expose EAN)   │
│  Script: stage4_image_match.py, stage5_barcode_match.py    │
└──────────────────┬─────────────────────────────────────────┘
                   │ Remaining
                   ▼
┌────────────────────────────────────────────────────────────┐
│  STAGE 6: Manual Review Queue                              │
│  ──────────────────────────                                │
│  Input:  Everything Stage 1-5 couldn't match               │
│  Output: CSV with top candidates + reason + human_decision │
│  Script: export_review_queue.py <pincode>                  │
└────────────────────────────────────────────────────────────┘
```

## Cascade Flow — Each Stage's Failures Feed Into the Next

```
Stage 1 (PDP Direct)
├─ OK with price → DONE ✅
├─ no_price / error → FEED INTO STAGE 2
└─ Anakin NA SKUs (no URL) → also STAGE 2

Stage 2 (Brand Cascade)
├─ matched → DONE ✅
└─ failures → STAGE 3

Stage 3 (Type/MRP Cascade)
├─ matched → DONE ✅
└─ failures → STAGE 4

Stage 4 (Search API — Jiomart only)
├─ matched → DONE ✅
└─ failures → STAGE 5

Stage 5 (Image + Barcode)
├─ matched → DONE ✅
└─ failures → STAGE 6

Stage 6 (Manual Review)
└─ Human decides
```

## Filter Logic Per Stage

### Stage 1 — PDP Direct
```
Visit Anakin's cached Product URL → intercept API response → extract price
No fuzzy matching. Join by item_code.
```

### Stage 2 — Brand Cascade
```
1. Brand filter (strict exact match)
2. Product Type filter (token overlap)
3. Weight filter (±20% tolerance)
4. Name fuzzy match (SequenceMatcher ≥ 0.4)
```

### Stage 3 — Type/MRP Cascade
```
1. Product Type filter (token overlap) — strict: reject if 0 matches
2. Name token overlap — strict: reject if 0 common tokens
3. Weight filter (±25% tolerance)
4. MRP filter (±15%) — KEY: catches variant mismatches
5. Name fuzzy match (SequenceMatcher ≥ 0.35)
```

### Stage 4 — Search API (Jiomart)
```
1. Take Anakin's Jiomart_Item_Name (or Item_Name fallback)
2. Search on Jiomart via /search/<query> URL
3. /trex/search API returns product results with prices
4. Pick best name match from results (SequenceMatcher ≥ 0.4)
Why needed: Jiomart PDP doesn't render prices in headless Firefox.
```

### Stage 5 — Image + Barcode
```
Image:
1. Download Apna's product image (samaan-backend GCS)
2. Download SAM BFS pool product images (Blinkit CDN)
3. Compute pHash (perceptual hash) for both
4. Match if hamming distance ≤ 12
Status: blocked — GCS bucket requires auth

Barcode:
1. Get Apna's EAN from smpcm_product.bar_code
2. Check if SAM BFS pool has matching barcode
3. Exact match = guaranteed same product
Status: 0 matches — Blinkit/Jiomart APIs don't expose EAN
```

### Stage 6 — Manual Review
```
Export CSV with columns:
  item_code, reason, anakin_name, top_candidates, human_decision
Reviewer fills: correct / wrong / manual:<id> / not_available
```

## Loose Items — Excluded

Products with "loose" in name are excluded from all matching:
- "Sugar 1kg Loose", "Toor Dal Loose", etc.
- Generic, unbranded, price varies daily
- Only 15-22 items per pincode (< 2%)

## Results — Ranchi 834002 (Non-Loose, Blinkit April 12)

| Stage | Blinkit Matched | Jiomart Matched |
|---|---|---|
| Stage 1 (PDP) | 747 | 412 |
| Stage 2 (Brand) | +268 | +46 |
| Stage 3 (Type/MRP) | +0 | +0 |
| Stage 4 (Search API) | N/A (not needed) | +~740 (running, 95% hit rate) |
| Stage 5 (Image/Barcode) | +0 (blocked) | +0 (blocked) |
| **TOTAL** | **1,375 / 1,411 = 97.4%** | **~1,198 / 1,240 = ~96.6%** |
| **Unmatched** | 36 (genuinely OOS) | ~42 |

## Platform-Specific Notes

### Blinkit
- **Browser:** Chromium (headless)
- **Location:** localStorage `location` JSON + cookies `gr_1_lon` (NOT `gr_1_lng`)
- **PDP works:** API response interception catches product data from `snippets[].data.rfc_actions_v2.default[].cart_item`
- **PDP bug fixed:** `_find_product_in_json` now requires `product_id` (not just `id`) + price fields to avoid matching page metadata
- **BFS pool:** ~855 products from 103 categories + search terms

### Jiomart
- **Browser:** Firefox (Chromium → 403 from Akamai CDN)
- **Location:** cookies `pincode` + `address_pincode`
- **PDP BROKEN:** Headless Firefox doesn't render product prices (React SPA hydration issue, `productPrice = 0`)
- **Search API works:** `/trex/search` reliably returns prices in Google Retail catalog format
- **JSON-LD:** Only has BreadcrumbList (no Product type with price)
- **BFS pool:** ~3,000 products from category pages

## Scripts Summary

| Script | Stage | Platform | What it does |
|---|---|---|---|
| `scrape_blinkit_pdps.py` | 1 | Blinkit | Visit Anakin URLs, API interception |
| `scrape_jiomart_pdps.py` | 1 | Jiomart | Visit Anakin URLs (limited — PDP broken) |
| `cascade_match.py` | 2 | Both | Brand → Type → Weight → Name |
| `stage3_match.py` | 3 | Both | Type → Name → Weight → MRP |
| `jiomart_search_match.py` | 4 | Jiomart | Search API for failed PDP products |
| `stage4_image_match.py` | 5 | Both | pHash image comparison (blocked by GCS auth) |
| `stage5_barcode_match.py` | 5 | Both | EAN barcode matching (no platform barcode data) |
| `export_review_queue.py` | 6 | Both | CSV export for human review |
| `compare_pdp.py` | — | Blinkit | Stage 1 comparison report |
| `compare_pdp_jiomart.py` | — | Jiomart | Stage 1 comparison report |
| `export_pdp_csv.py` | — | Both | CSV + Excel export |
| `run_blinkit_scrape.py` | — | Blinkit | BFS pool builder |
| `fetch_anakin_blinkit.py` | — | Blinkit | Pull Anakin reference data |
| `fetch_anakin_jiomart.py` | — | Jiomart | Pull Anakin reference data |
| `run_all_cities.py` | — | Both | Multi-city orchestrator |
| `scheduled_morning_run.sh` | — | Both | Daily 10:30 AM run script |

## Config

Platform settings in `config/platforms.json` — browser type, URL patterns, Anakin field names, location method per platform.

## Key Bugs Fixed

1. **PDP extractor matched page metadata** — `tracking.le_meta.id` instead of actual product `cart_item.product_id`. Fixed: require `product_id` + price fields.
2. **Cascade didn't receive Stage 1 failures** — Stage 2 only processed Anakin NA SKUs. Fixed: loads Stage 1 comparison and includes `no_price_on_pdp` codes.
3. **"NA" string sentinel** — Anakin uses literal `"NA"` for missing values. Python `or` treats it as truthy. Fixed: `clean_str()` helper everywhere.
4. **Jiomart PDP doesn't render** — headless Firefox shows `productPrice = 0`. Fixed: use Search API instead of PDP.

## Path to Replace Anakin

1. ✅ **Pipeline built** — 6 stages, both platforms
2. ✅ **Blinkit 97.4%** — target exceeded
3. 🟡 **Jiomart ~96.6%** (projected, search match running)
4. ⏳ **Same-day Anakin data** — waiting for Anakin tech issue fix
5. ⏳ **Other 3 cities** — Kolkata, Raipur, Hazaribagh (scripts ready, need to run)
6. 🎯 **Goal:** 4 weeks of 90%+ → cancel Anakin → save ₹3L/month

---

_Last updated: 2026-04-13_
