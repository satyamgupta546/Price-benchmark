# Match Status Logic (BLINKIT STATUS / JIO STATUS / DMART STATUS)

## Source
- Latest MRP from: https://mirror.apnamart.in/model/1808-latest-inward-cost-price
- LOOSE/ASM tagging from: https://mirror.apnamart.in/model/1344-product-master
- Engine: `scripts/unified_matcher.py` (UnifiedMatchingEngine)

## Status Definitions

### COMPLETE MATCH
- EAN fast-track: barcode exact match → instant COMPLETE (bypasses all text/price logic)
- OR: All of these conditions met:
  - Exact brand match (normalized with alias dictionary)
  - Base weight matched (±10%, multipack-aware: "Pack of 2 x 500g" = 1000g)
  - Name fuzzy token_set_ratio >= 65
  - Exact MRP match (tolerance ±0.01)
  - No packaging mismatch (jar vs pouch)
  - No variant conflict (moong vs toor, dark vs milk)

### SEMI COMPLETE MATCH
- Only for LOOSE/ASM items in STPLS master category
- Same unit TYPE (weight/weight, volume/volume, count/count)
- Name score >= 40 with keyword overlap (at least 1 meaningful word common)
- MRP ratio 0.3-3.0x (sanity check only, exact match not required)
- No packaging or variant conflicts

### PARTIAL MATCH
- Product found but fails COMPLETE or SEMI COMPLETE criteria:
  - Unit value mismatch (outside ±10%)
  - MRP not exact
  - Name score between 40-64
  - Packaging mismatch (rigid vs soft)
  - Variant conflict (different dal types, different chocolate types)

### NA
- No match found on platform
- Product not available (OOS / redirected)
- Name score < 40 (too dissimilar)
- Price sanity fail (SP > 3x AM MRP)
- Combo/bundle product (skipped)

## Pre-Filter Heuristics (NEW in unified_matcher)

### Packaging Check
- Rigid: jar, tin, bottle, can, container, dabba, pet, glass, tub, bucket
- Soft: pouch, refill, sachet, packet, wrapper, pillow, standup, poly
- If one product is rigid and other is soft → automatic PARTIAL MATCH

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

## Warehouse Mapping (for MRP lookup)
- WRHS_1 = Jharkhand (Ranchi 834002, Hazaribagh 825301, Jamshedpur 831001)
- WRHS_2 = Chhattisgarh (Raipur 492001, Bilaspur 495001)
- WRHS_10 = Kolkata (712232)

## Master Category Filter
Only include: STPLS, FMCG, FMCGF, FMCGNF, GM
