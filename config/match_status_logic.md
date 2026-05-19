# Match Status Logic (BLINKIT STATUS / JIO STATUS / DMART STATUS)

## Source
- **AM MRP**: `smpricing_latestproductpricingtracker` (BQ: smpublic) — latest warehouse-specific MRP+SP
- **Fallback MRP**: model 1808 (latest inward cost price)
- **LOOSE/ASM tagging**: model 1344 (product-master) or name/product_type detection
- **Engine**: `scripts/unified_matcher.py` (UnifiedMatchingEngine)

## MRP Query (BQ)
```sql
SELECT p.item_code, lpt.mrp, lpt.selling_price, lpt.updated_at
FROM `smpublic.smpricing_latestproductpricingtracker` lpt
JOIN `smpublic.smpcm_product` p ON lpt.product = p.id
WHERE lpt.level_code = 'WRHS_1'  -- warehouse specific
AND p.item_code IN (...)          -- only target items
```

## Status Definitions

### COMPLETE MATCH
- EAN fast-track: barcode exact match → instant COMPLETE (bypasses all text/price logic)
- OR: All conditions met:
  - Exact brand match (normalized with alias dictionary)
  - **Weight EXACT same** (no tolerance, e.g., 500g = 500g)
  - Name fuzzy token_set_ratio >= 65
  - **MRP exact match** (tolerance ±0.01)
  - No packaging mismatch (jar vs pouch)
  - No variant conflict (moong vs toor, dark vs milk)

### SEMI COMPLETE MATCH
- Weight **±10% tolerance** (e.g., 500g matched to 480g or 520g)
- Name token_set_ratio >= 65
- MRP can differ
- No packaging or variant conflicts

### PARTIAL MATCH
- Product found but fails COMPLETE or SEMI COMPLETE criteria
- Name score between 40-64
- OR packaging mismatch (rigid vs soft)
- OR variant conflict (different dal types, chocolate types)

### NA
- No match found on platform
- Product not available (OOS / redirected)
- Name score < 40
- Price sanity fail (SP > 3x AM MRP)
- Combo/bundle product (skipped)

## Jiomart Scraping Flow

### Scripts
- `jiomart_fetch_prices.py` — Main daily script (mapping-based)
- `unified_matcher.py` — Matching engine (brand, weight, name, MRP, packaging, variant)
- `jiomart_direct_search.py` — Legacy direct search (deprecated by fetch_prices)

### Daily Flow
```
1. Load am_jiomart_mapping.json (AM item_code → Jiomart URL)
2. Mapped items → Open saved URL → fetch latest SP/MRP (fast, no search)
3. Unmapped items → Search on Jiomart (keyword search, scroll, paginate)
   - Brand search first → name search fallback
   - 4 parallel tabs, random delays (anti-block)
4. Match using UnifiedMatchingEngine (brand + weight + name + MRP)
5. Save mapping permanently (URL, product_id, match status)
6. Output: JSON + Excel
7. Next day: only URL fetch for mapped items (no re-search)
```

### Search Term Rules
- Remove `| 500g | Pack of 1` suffixes
- Remove `- 500g` weight suffixes
- NO brand repeat (if brand in name, don't prepend)
- Hyphens → spaces (Jiomart handles spaces better)
- Loose items: strip "Loose" prefix, keep product + weight
- Max 5 words

### Data Files
- `data/am_jiomart_mapping.json` — Permanent AM↔Jiomart mapping
- `data/am_pricing_wrhs_1.json` — Latest AM MRP from latestproductpricingtracker
- `data/jiomart_product_master.json` — Jiomart product details (permanent store)

## Pre-Filter Heuristics

### Packaging Check
- Rigid: jar, tin, bottle, can, container, dabba, pet, glass, tub, bucket
- Soft: pouch, refill, sachet, packet, wrapper, pillow, standup, poly
- Mismatch → automatic PARTIAL MATCH

### Critical Variant Check
Groups (cross-matching within a group = conflict → PARTIAL):
- Dal: moong, toor, masoor, chana, urad, arhar, rajma, kabuli
- Chocolate: dark, milk, white
- Seasoning: salted, unsalted, roasted, raw
- Tea: green, black, herbal, masala
- Oil: mustard, sunflower, groundnut, soybean, olive, coconut, sesame
- Milk: toned, skimmed, standardized, fullcream
- Rice: basmati, kolam, sona, ponni, gobindo
- Flour: multigrain, wholewheat, maida, besan, sooji, ragi
- Spice: red, yellow, kashmiri, bydagi
- Salt: iodized, rock, pink, sendha

## Warehouse Mapping
- WRHS_1 = Jharkhand (Ranchi 834002, Hazaribagh 825301, Jamshedpur 831001)
- WRHS_2 = Chhattisgarh (Raipur 492001, Bilaspur 495001)
- WRHS_10 = Kolkata (712232)

## Master Category Filter
Only include: STPLS, FMCG, FMCGF, FMCGNF, GM
