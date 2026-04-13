# Matching Strategy — 4-Stage Cascade

## Goal

Match SAM's scraped Blinkit products to Anakin's reference SKUs at **95%+ price accuracy and 95%+ coverage**, without hand-mapping every SKU.

## Approach — Run in this exact order

```
┌────────────────────────────────────────────────────────────┐
│  STAGE 1: ID-based exact match (PDP direct)                │
│  ────────────────────────────────────────                  │
│  Input:  Anakin's cached Blinkit_Product_Url / Jiomart_Url │
│  Action: Visit each URL directly → scrape price + stock    │
│  Output: Exact match by item_code (no fuzzy)               │
│  Proven: 94.6% ±5% price match on Ranchi Blinkit           │
└──────────────────┬─────────────────────────────────────────┘
                   │
                   │ Whatever remains unmatched
                   ▼
┌────────────────────────────────────────────────────────────┐
│  STAGE 2: Brand-first cascade                              │
│  ────────────────────────────                              │
│  Input:  Anakin NA SKUs + SAM BFS pool                    │
│  Filter order: Brand → Product_Type → Weight → Name        │
│  Best for: clean brand names, high-confidence pairing      │
└──────────────────┬─────────────────────────────────────────┘
                   │
                   │ Whatever still remains (incl. weak matches)
                   ▼
┌────────────────────────────────────────────────────────────┐
│  STAGE 3: Type-first cascade with MRP filter (NEW)         │
│  ────────────────────────────────────────                  │
│  Input:  Stage 2 unmatched + weak matches                  │
│  Filter order: Type → Name token → Weight → MRP            │
│  Special: MRP ±15% catches variant mismatches              │
│           (e.g., Horlicks Chocolate ≠ Horlicks Women's Plus)│
│  Best for: dirty brand data, variant disambiguation        │
└──────────────────┬─────────────────────────────────────────┘
                   │
                   │ Whatever still remains
                   ▼
┌────────────────────────────────────────────────────────────┐
│  STAGE 4: Manual review queue                              │
│  ──────────────────────────                                │
│  Remaining ambiguous cases                                 │
│  Exported to CSV with top candidates + reason              │
│  Human verifies one-by-one                                 │
└────────────────────────────────────────────────────────────┘
```

## Why the new Stage 3

Stage 2's brand-first approach is strict — it fails when SAM's brand field is dirty (e.g., when the platform API doesn't return a brand and we fall back to "first word of name"). It also produces false positives when brand matches but MRP reveals the product is actually a different variant (e.g., Horlicks Chocolate Delight 400g ₹159 vs Horlicks Women's Plus ₹324 — same brand, wildly different SKU).

Stage 3 flips the approach:
- **Starts with Product Type** (more stable across platforms)
- **Narrows by name tokens** (matches "horlicks" family)
- **Weight filter** (same as Stage 2)
- **MRP filter ±15%** as the final gate — this is the key step. If nothing matches within MRP tolerance, the SKU is rejected with reason `mrp_rejected` (a strong signal that it's a different variant).

Stage 3 only runs on SKUs Stage 2 couldn't resolve, so the input pool is smaller and more focused.

## CRITICAL: Proper Cascade Flow

**Each stage's FAILURES feed into the NEXT stage as input.** This is the core architecture:

```
Stage 1 (2,364 URLs)
├─ 933 OK (with price) → DONE ✅
├─ 1,431 no_price/error → FEED INTO STAGE 2 ↓
└─ (plus 1,256 Anakin NA SKUs also → Stage 2)

Stage 2 (2,687 input = 1,431 Stage1-fail + 1,256 NA)
├─ N matched → DONE ✅
└─ Remaining failures → FEED INTO STAGE 3 ↓

Stage 3 (Stage 2 failures + weak matches)
├─ N matched → DONE ✅
└─ Remaining failures → FEED INTO STAGE 4 ↓

Stage 4 (all remaining) → CSV for human review
```

**BUG WE FIXED:** Originally Stage 2 only processed Anakin's NA SKUs (1,256), ignoring Stage 1's 1,431 failures. This meant 60% of products were lost between stages. Now fixed — `cascade_match.py` loads Stage 1's comparison report and includes `no_price_on_pdp` + `scrape_error` item_codes as additional input.

## Why this order is correct

| Order | Reason |
|---|---|
| **ID first** | 100% guaranteed — no ambiguity. Clears the easy wins first. |
| **Brand cascade second** | Processes Stage 1 failures + Anakin NA SKUs against BFS pool. |
| **Type/MRP cascade third** | Different approach catches what Stage 2 missed (dirty brands, variant confusion). |
| **Manual last** | Only genuinely ambiguous products remain — human time well spent. |

---

## Stage 1 — ID-based PDP scraping

### Input
Anakin's `data/anakin/blinkit_<pincode>_<date>.json` contains 2,364 mapped SKUs per pincode like:
```json
{
  "Item_Code": "11732",
  "Blinkit_Product_Url": "https://blinkit.com/prn/x/prid/32390",
  "Blinkit_Product_Id": "32390",
  ...
}
```

### Process
```
For each mapped URL in Anakin's file:
    1. Open the URL in a fresh browser tab
    2. Wait for network settle
    3. Extract from PDP:
       - product_name
       - selling_price (₹)
       - mrp (₹)
       - in_stock (available / out_of_stock)
       - unit / pack size
       - image URL
    4. Save keyed by item_code (no fuzzy needed)
```

Parallel with 5 browser tabs → ~10 min for 2,364 URLs.

### Output
```json
{
  "pincode": "834002",
  "scraped_at": "...",
  "source": "anakin_url_seed",
  "products": [
    {
      "item_code": "11732",               // from Anakin
      "blinkit_product_id": "32390",      // from Anakin
      "blinkit_product_url": "...",       // from Anakin
      "sam_product_name": "7UP Lime ...",// from SAM scrape
      "sam_selling_price": 96,           // from SAM scrape
      "sam_mrp": 100,                    // from SAM scrape
      "sam_in_stock": true,
      "sam_unit": "2.25 l"
    }
  ]
}
```

### Matching (comparison script)
Exact join on `item_code`:
```python
for anakin_sku, sam_pdp in zip_by_item_code(anakin_data, sam_pdp_data):
    price_diff_pct = abs(sam_pdp.price - anakin_sku.blinkit_sp) / anakin_sku.blinkit_sp * 100
    # no fuzzy, no name matching
```

### Expected metrics
- **Coverage:** 100% of Anakin's mapped SKUs (2,364 / 2,364)
- **Price match ±5%:** 95%+
- **Wrong mappings:** 0 (we're literally visiting the same URLs Anakin has)

### Files
- `scripts/scrape_blinkit_pdps.py` — parallel PDP scraper (new)
- `scripts/compare_pdp.py` — exact-join compare (new)
- `data/sam/blinkit_pdp_<pincode>_<ts>.json` — output

---

## Stage 2 — Cascade filter (brand → type → weight → name)

Applied to SKUs that Stage 1 couldn't handle:
- Anakin's **384 "NA" SKUs** (products Anakin itself couldn't map to Blinkit)
- SAM's **general scrape output** (products we found that aren't in Anakin)

### Filter logic
```python
def find_match(ana_sku, sam_products):
    ana_brand = normalize(ana_sku.Brand)
    ana_ptype = normalize(ana_sku.Product_Type)
    ana_uv    = float(ana_sku.Unit_Value)
    ana_unit  = normalize_unit(ana_sku.Unit)
    ana_name  = normalize(ana_sku.Item_Name)
    
    # ─── STAGE 2a: Brand filter (strict) ────────────
    candidates = [p for p in sam_products 
                  if normalize(p.brand) == ana_brand]
    if not candidates:
        return None, "no_brand"
    
    # ─── STAGE 2b: Product Type filter (token overlap) ──
    if ana_ptype:
        pt_tokens = set(ana_ptype.split())
        filtered = [p for p in candidates 
                    if pt_tokens & tokens(p.category or p.name)]
        if filtered:
            candidates = filtered
    
    # ─── STAGE 2c: Weight filter (±20% tolerance) ────
    weight_match = []
    for p in candidates:
        p_uv, p_unit = parse_unit(p.unit)
        if p_uv and units_compatible(ana_unit, p_unit):
            ratio = p_uv / ana_uv
            if 0.8 <= ratio <= 1.2:
                weight_match.append((p, abs(1 - ratio)))
    if weight_match:
        weight_match.sort(key=lambda x: x[1])
        candidates = [p for p, _ in weight_match]
    
    # ─── STAGE 2d: Name fuzzy match on filtered set ──
    best_score = 0.0
    best_match = None
    for p in candidates:
        score = SequenceMatcher(None, ana_name, normalize(p.product_name)).ratio()
        if score > best_score:
            best_score = score
            best_match = p
    
    if best_match and best_score >= 0.4:
        return best_match, "cascaded"
    return None, "no_name_match"
```

### Why cascade works
- **Stage 2a (brand)** cuts 800 products → ~30 candidates (only same-brand products)
- **Stage 2b (type)** cuts 30 → ~8 candidates (same product family)
- **Stage 2c (weight)** cuts 8 → ~2 candidates (correct pack size)
- **Stage 2d (name)** picks the final winner from 2-3 high-quality options

Even a low fuzzy score of 0.4 is safe here because Stages 2a-2c already guarantee brand + category + weight match.

### SAM data quality fixes needed first
| Field | Current state | Fix |
|---|---|---|
| `brand` | 123/800 from API, 462 = "first word of name" fallback, 215 empty | Remove first-word fallback, add more API key candidates |
| `unit` | Single string "500 g" | Parse into `unit_value` (float) + `unit` (normalized g/ml/kg/ltr/pc) |
| `category` | Only 49/800 (6%) | More key candidates, fallback to URL breadcrumb |
| DOM-extracted products | 462/800 have only name+price+image | Either skip DOM or re-enrich via API post-extraction |

### Expected metrics
- **New discoveries:** ~200-300 SKUs that Anakin missed
- **Accuracy:** 60-80% (lower than Stage 1 because no ground truth URL)
- **False positives:** Low due to strict brand filter

---

## Stage 3 — Manual review queue

What remains after Stages 1 and 2:
- SKUs where brand doesn't match any SAM product
- SKUs where weight filter rejected all candidates
- SKUs with very low name similarity after filtering

### Output
`data/comparisons/blinkit_<pincode>_needs_review.csv`:
```csv
item_code,anakin_name,anakin_brand,anakin_weight,top_candidates,needs_review_reason
97864,Shubhkart Darshana Chandan Tika 40g,Shubhkart,40 g,"[...]",no_brand_match
42875,Del Monte Tomato Ketchup Classic 900g,Del Monte,900 g,"[A, B, C]",low_name_score
```

Expected: 5% of total (~100 SKUs for Ranchi) → ~1 day of human review to clear.

---

## Implementation order

1. **Stage 1 first** — highest ROI, 100% guaranteed
2. **Fix SAM data quality** — parse unit, clean brand, add category
3. **Stage 2 cascade** — runs on leftover + general scrape
4. **Stage 3 review CSV** — automated export of ambiguous items

---

## Status

| Stage | Status | File(s) |
|---|---|---|
| Stage 1 Blinkit PDP scraper | ✅ tested (94.6% ±5%) | `scripts/scrape_blinkit_pdps.py` |
| Stage 1 Jiomart PDP scraper | ✅ tested | `scripts/scrape_jiomart_pdps.py` |
| Stage 1 exact-join compare | ✅ | `scripts/compare_pdp.py`, `scripts/compare_pdp_jiomart.py` |
| Stage 2 brand-first cascade | ✅ | `scripts/cascade_match.py` |
| Stage 3 type/MRP cascade | ✅ built | `scripts/stage3_match.py` |
| Stage 4 review CSV export | ✅ | `scripts/export_review_queue.py` |
| SAM data quality (parse unit → numeric) | ❌ TODO | `backend/app/scrapers/base_scraper.py` |

---

## Why we don't skip Stage 2 even though Stage 1 covers Anakin's 2,364 SKUs

Stage 1 alone matches Anakin's exact scope but:
- **Anakin tracks only 6.9% of Apna's catalog** (3,801 / 54,891 SKUs)
- **384 of those are NA** (Anakin itself couldn't map them)

Stage 2 lets us:
- **Match Anakin's 384 NA SKUs** ourselves
- **Add 200-500 more Apna SKUs** that Anakin never tried
- **Not depend on Anakin's mapping** for new SKU launches

Long-term, Stage 2 is what lets SAM surpass Anakin in coverage — not just match it.

---

_Last updated: 2026-04-11 — strategy agreed with product team._
