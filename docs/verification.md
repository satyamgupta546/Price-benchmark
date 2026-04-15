# Verification System — SAM vs Anakin

## Overview

Every time SAM scrapes data, it is verified against Anakin's reference catalog across all 6 matching stages. Anakin is the current source of truth for product mapping and pricing.

## How It Works

```
SAM Scrape (fetch)
    ↓
Stage 1: PDP Direct (exact URL visit)
Stage 2: Brand Cascade (brand → type → weight → name)
Stage 3: Type/MRP Cascade (type → name → weight → MRP)
Stage 4: Search API (Jiomart only)
Stage 5a: Image Match (pHash)
Stage 5b: Barcode Match (EAN)
    ↓
verify_against_anakin.py
    ↓
Verification Report (console + JSON)
```

## Running Verification

```bash
# Standalone (after stages have already run)
python scripts/verify_against_anakin.py 834002 blinkit
python scripts/verify_against_anakin.py 834002 all

# Auto-runs at end of full pipeline
python scripts/run_full_pipeline.py 834002 blinkit
```

## Report Output

### Console Report
```
VERIFICATION REPORT — BLINKIT / Pincode 834002

  Anakin total SKUs:      3611
  Anakin usable (mapped): 1440
  SAM matched (usable):   976
  Coverage:               67.8%

  Stage                      Matched   New   Compared   ≤5%    ≤10%
  Stage 1 — PDP Direct          819   +670       680   97.4%  99.3%
  Stage 2 — Brand Cascade       904   +306       306   31.7%  35.6%
  ...

  PRICE ACCURACY (986 prices compared):
    Within  2%:  739 (74.9%)
    Within  5%:  759 (77.0%)
    Within 10%:  784 (79.5%)

  TOP MISMATCHES (>2% price diff):
  Code      Diff%    Anakin₹    SAM₹   Name
  ...
```

### JSON Report
Saved to: `data/comparisons/verification_{platform}_{pincode}_{timestamp}.json`

Contains:
- `coverage_pct` — % of Anakin usable SKUs matched by SAM
- `overall_price_accuracy` — accuracy buckets (2%, 5%, 10%, 20%)
- `stages[]` — per-stage match counts and accuracy
- `top_mismatches[]` — largest price deviations for investigation

## Stage Types & Confidence

| Stage | Type | Confidence | Description |
|-------|------|------------|-------------|
| 1 — PDP Direct | `id_match` | High | Exact item_code join via URL visit |
| 2 — Brand Cascade | `fuzzy_match` | Medium | Brand → type → weight ±10% → name (score ≥ 0.55) + MRP ±15% check |
| 3 — Type/MRP | `fuzzy_match` | Medium | Type → name → weight → MRP ±15% (score ≥ 0.35) |
| 4 — Search API | `api_search` | Medium | Platform search by name (Jiomart only) |
| 5a — Image | `perceptual_hash` | Medium-High | pHash, Hamming distance ≤ 12 |
| 5b — Barcode | `exact_match` | Very High | EAN/UPC exact match (≥8 digits) |

## Configuration

All thresholds and stage definitions are in `config/verification.json`:
- `verification.price_tolerance_buckets` — accuracy bucket boundaries
- `verification.mismatch_threshold_pct` — minimum diff to flag as mismatch
- `stages[].min_score` — minimum fuzzy match score per stage
- `verification.usable_filters` — rules for filtering Anakin "usable" SKUs

## Key Concepts

### Usable SKUs
Anakin SKUs that have a valid selling price and are not "loose" items. These are the denominator for coverage %.

### Coverage vs Accuracy
- **Coverage** = how many Anakin usable SKUs did SAM find a match for
- **Accuracy** = of matched SKUs where both sides have a price, how close are they

### Stage Cascade
Each stage only processes SKUs that previous stages couldn't match. The "New" column in the report shows incremental matches per stage.

### Price Diff Calculation
```
price_diff_pct = |SAM_price - Anakin_price| / Anakin_price * 100
```

For stages 2-3 where Anakin SP is often "NA", the diff uses Anakin MRP as fallback reference.

Large diffs (>20%) usually indicate:
- Wrong product matched (variant mismatch — e.g., single vs multipack)
- Stale Anakin data (price changed since Anakin's last fetch)
- SAM extraction bug (wrong price field scraped)

## Recent Fixes (2026-04-15)

### Stage 1 — PDP Direct
- **Skip OOS products**: Products Anakin marks `out_of_stock` are no longer scraped (saves ~767 requests)
- **Homepage redirect detection**: Blinkit redirects unavailable products to homepage — now detected early and marked `not_available` instead of `no_price`
- **New status**: `not_available_at_location` distinguishes "product not in local catalog" from "scraper failed"

### Stage 2 — Brand Cascade
- **Min score increased**: 0.4 → 0.55 (rejects false positives like Spaghetti→Macaroni at 0.489)
- **Weight tolerance tightened**: ±20% → ±10% (425g no longer matches 500g)
- **MRP cross-check added**: Rejects matches where MRP differs >15%
- **Shared utils**: Duplicate functions replaced with imports from `utils.py`

### Stage 3 — Type/MRP Cascade
- **Price diff in output**: Now includes `anakin_sp` and `price_diff_pct` in match records
- **Shared utils**: Duplicate functions replaced with imports from `utils.py`

### Stage 5a — Image Match
- **GCS URL fix**: Anakin image URLs use `storage.cloud.google.com` (requires auth) — now converted to `storage.googleapis.com` (public)
- **Retry logic**: Image downloads retry once with 2x timeout
- **Fallback**: When Anakin image missing, uses SAM product image if product_id mapped

### Stage 5b — Barcode Match
- **Barcode search fallback**: When SAM pool has no barcodes, searches Anakin EAN directly on platform
- **Blinkit search**: Searches `blinkit.com/s/?q={barcode}` and matches first result

### Base Scraper
- **Proxy integration**: Optional proxy support via `config/proxies.json` (opt-in, `"enabled": true`)
- **Barcode capture**: `_parse_generic_product()` now extracts barcode/EAN/UPC/GTIN fields

### JioMart Scraper
- **Category auto-discovery**: Discovers live category URLs from `/c/groceries/2` page with keyword matching fallback
