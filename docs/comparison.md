# Comparison — SAM vs Anakin

## What it does

Compares SAM's scraped product data against Anakin's reference data (pulled from `apna-mart-data.googlesheet.cx_competitor_prices`) for the same pincode + platform, and generates accuracy metrics:

- **Coverage** — % of Anakin's mapped SKUs that SAM found
- **Price match** — for matched SKUs, % within ±5% / ±10% of Anakin's selling price
- **Score distribution** — how confident were the matches (fuzzy similarity buckets)

This is the framework used to validate SAM's accuracy on the path to replacing Anakin. Target: **90%+ coverage and 90%+ price match within ±5%**.

## How it works

```
1. Load Anakin reference (data/anakin/blinkit_<pincode>_<date>.json)
2. Filter to Anakin's mapped SKUs (Blinkit_Product_Id != "NA")
3. Load latest SAM scrape (data/sam/blinkit_<pincode>_<timestamp>.json)
4. Build SAM index — list of {brand, name, unit, full_text, normalized}
5. For each Anakin mapped SKU:
   a. Build search query: brand + Blinkit_Item_Name (Anakin's curated name closest to Blinkit's actual)
   b. Score every SAM product via SequenceMatcher on normalized text
   c. Boost score by +0.1 if brand exactly matches
   d. Pick best candidate; accept if score >= 0.5
6. Compute price diff: |sam_price - anakin_blinkit_sp| / anakin_blinkit_sp * 100
7. Aggregate metrics + dump full report
```

## Files involved

| File | Role |
|---|---|
| `scripts/run_blinkit_scrape.py` | Standalone scraper runner — saves SAM output |
| `scripts/compare_sam_vs_anakin.py` | Main comparison script |
| `data/anakin/blinkit_<pincode>_<date>.json` | Anakin reference (pulled via Mirror Metabase API) |
| `data/sam/blinkit_<pincode>_<timestamp>.json` | SAM scrape output |
| `data/comparisons/blinkit_<pincode>_<timestamp>_compare.json` | Full comparison report |

## Inputs

### Anakin reference JSON
```json
{
  "pincode": "834002",
  "date": "2026-04-11",
  "total_rows": 3620,
  "blinkit_mapped": 2364,
  "records": [
    {
      "Item_Code": "100",
      "Item_Name": "Chings ManChow Instant Soup 12g",
      "Brand": "Chings",
      "Unit": "g",
      "Unit_Value": "12",
      "Mrp": "10",
      "Blinkit_Product_Url": "https://blinkit.com/prn/x/prid/581162",
      "Blinkit_Product_Id": "581162",
      "Blinkit_Item_Name": "Ching's Secret Manchow Instant Soup",
      "Blinkit_Selling_Price": "...",
      "Blinkit_Status": "Partial Match",
      "Blinkit_Factor": "0.083"
    }
  ]
}
```

### SAM scrape JSON
```json
{
  "pincode": "834002",
  "scraped_at": "2026-04-11T...",
  "duration_seconds": 750.5,
  "total_products": 4500,
  "products": [
    {
      "product_name": "Ching's Secret Manchow Instant Soup",
      "brand": "Ching's",
      "price": 50.0,
      "mrp": 60.0,
      "unit": "10 x 12 g",
      "category": null,
      "platform": "blinkit",
      "in_stock": true,
      "image_url": "..."
    }
  ]
}
```

## Outputs

### Console summary
```
============================================================
COMPARISON: SAM vs Anakin (Blinkit, pincode 834002)
============================================================
Anakin Blinkit-mapped SKUs: 2364
SAM scraped products:      4500

COVERAGE:           1840/2364 = 77.8%
  Score 0.9+:       820
  Score 0.7-0.9:    640
  Score 0.5-0.7:    380

PRICE MATCH (vs Anakin's Blinkit_Selling_Price):
  Within ±5%:       1100/1300 = 84.6%
  Within ±10%:      1240/1300 = 95.4%
```

### Full JSON report
```json
{
  "pincode": "834002",
  "compared_at": "...",
  "metrics": { ... },
  "matches": [
    { "item_code": "100", "matched": true, "match_score": 0.85,
      "anakin_name": "...", "sam_name": "...",
      "anakin_blinkit_sp": "50", "sam_price": 52.0,
      "price_diff_pct": 4.0 }
  ],
  "not_found": [
    { "item_code": "...", "matched": false, "match_score": 0.32,
      "best_candidate": "..." }
  ]
}
```

## Match scoring

**Current (Day 1):** Pure fuzzy text matching
```python
score = SequenceMatcher(normalize(anakin_full), normalize(sam_full)).ratio()
if anakin_brand.lower() in sam_normalized:
    score += 0.1
matched_if score >= 0.5
```

**Planned upgrades (Day 2-3):**
1. **Pack-size constraint** — reject matches where pack sizes differ significantly (apply Anakin's Factor logic)
2. **Brand exact-match required** — don't match across different brands
3. **Image-based re-ranking** — use Apna's product images (samaan-backend) + Blinkit images for top-3 candidates
4. **Use Anakin's cached Product_URLs as ground truth** — visit those URLs directly to get exact Blinkit product (skip fuzzy entirely for known mappings)

## Known limitations

1. **Anakin's selling prices are often NA** — only ~62% of Anakin's mapped SKUs have live prices, so price-match denominator is smaller than coverage denominator
2. **Threshold 0.5 is loose** — produces some false-positive matches; will tighten as we add multi-factor scoring
3. **No Hindi/English synonym handling** — "aalu" vs "potato" scores 0
4. **No multi-pack normalization in matching** — `5 x 100g` and `500g` both normalize to "500" but matcher doesn't know they're the same
5. **No image matching yet** — relies purely on name text similarity

## Usage

```bash
# Step 1: Pull Anakin reference (one-time, or whenever Anakin updates)
python3 scripts/fetch_anakin_blinkit.py 834002

# Step 2: Run SAM scrape
cd backend && ./venv/bin/python ../scripts/run_blinkit_scrape.py 834002

# Step 3: Compare
python3 scripts/compare_sam_vs_anakin.py 834002
```

## Next improvements

- [ ] Add `--platform jiomart` support (currently Blinkit-only)
- [ ] Multi-pincode mode: loop over all 4 Anakin cities
- [ ] HTML report output (for sharing on Slack)
- [ ] Image-based re-ranking module
- [ ] Time-series tracking — keep daily comparison history
- [ ] Push results to BigQuery as `apna-mart-data.googlesheet.cx_competitor_prices_sam_compare`
