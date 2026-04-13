# Test Findings #001 — During 7-agent parallel run

_Generated 2026-04-12, during multi-agent test phase_

## Summary

While 7 agents were running in background (Blinkit Kolkata/Raipur/Hazaribagh, Jiomart Ranchi, Dev, PM, Stage3-fix), I ran local integrity tests on Stage 3 output and found several quality issues worth documenting.

## Stage 3 after clean_str fix — works but has false positives in low-score bucket

**Before fix:** 4 matches, all garbage (Banana false positives for JK Methi etc.)
**After fix:** 282 matches

Score distribution:
| Bucket | Count | Quality |
|---|---|---|
| 0.9+ | 8 | ✅ Excellent (Puramate, Ganesh Atta, Wagh Bakri, Saloni, Brooke Bond all legit) |
| 0.7-0.9 | 25 | ✅ Likely correct |
| 0.5-0.7 | 74 | ⚠️ Mixed (some legit, some brand-mismatch with MRP coincidence) |
| 0.4-0.5 | 175 | 🔴 Mostly false positives |

## Concrete false-positive examples in 0.4-0.5 bucket

1. **"Go Cheese Spread Plain 200g" (₹115) → "Amul Jalapeno Cheese Sauce" (₹99)**  
   Wrong brand (Go vs Amul), wrong product (spread vs sauce). MRP diff 14% passed ±15% filter.

2. **"Mcvities Tasties Cashew Almond Biscuits 560g" (₹171) → "Sapphire Original Danish Biscuits Gift Pack" (₹129)**  
   Wrong brand, wrong variant.

3. **"Limca Soft Drink 2L" (₹99) → "Wai Wai Chicken Noodles" (₹86)**  
   COMPLETELY unrelated (beverage vs noodles). MRP coincidence passed filter.

4. **"Pringles Desi Masala Tadka Crisps 40g" (₹53) → "Maggi Masala Cuppa Noodles" (₹50)**  
   Wrong brand, wrong product type.

5. **"Swiss Roll Chocolate Vanilla 100g" (₹55) → "Oreo Soft Chocolate Layered Cake" (₹47)**  
   Different product.

## Concrete false-positive examples in 0.5-0.7 bucket

1. **"Lotus Herbals Teatree Face Wash 150g" → "Plum Green Tea Face Wash 50ml"** (score 0.54)  
   Wrong brand. Anakin MRP=0 (unknown), SAM price=150. Bad data on Anakin side made MRP filter useless.

2. **"Bisk Farm Sugar Free Cream Cracker 250g/300g" → "Britannia Nutrichoice Cracker"** (score 0.54, 0.52)  
   Wrong brand. Biscuit category overlap.

3. **"Nivea Oil Control Face Wash 100ml" → "Garnier Bright Complete Face Wash 100g"** (score 0.64)  
   Wrong brand. Both are face wash 100g. MRP coincidentally close (₹249 → ₹176 — 29% diff... should have been rejected but the report shows it matched, need to investigate).

## Concrete CORRECT matches in 0.5-0.7 bucket (don't discard blindly)

1. **"MamyPoko Pants All Night Absorb S" → "MamyPoko Pants All Night Absorb Pant Style"** (score 0.70)  
   Real match. Same product, different size suffix.

2. **"MTR Original Uttappam Ready Mix 500g" (₹142) → "MTR Uttappam Breakfast Mix" (₹142)**  
   Perfect price match, same brand. Legit.

3. **"Comfort Morning Fresh Fabric Conditioner 430ml" (₹120) → "Comfort After Wash Fabric Conditioner (Morning Fresh)" (₹120)**  
   Perfect price match, same brand. Legit.

## Root cause analysis

The MRP filter (±15%) is too lenient as the final gate when brand isn't checked strictly. Two products with:
- Same product type (Face Wash, Biscuits, etc.)
- Similar weight
- Coincidentally similar MRP
...will pass all filters even if brands are completely different.

## Recommended fixes

### Option A: Add soft brand check as scoring boost
```python
# After cascade, before final name-score:
p_brand_tokens = tokens(p.get("brand") or "")
if ana_brand_tokens and p_brand_tokens and ana_brand_tokens & p_brand_tokens:
    score += 0.2  # Strong boost for brand agreement
elif ana_brand_tokens and not (ana_brand_tokens & p_brand_tokens):
    score -= 0.2  # Penalty for brand mismatch
```

### Option B: Tighten MRP tolerance
Change MRP_TOLERANCE_PCT from 15% to 5-8%. This alone would eliminate most false positives (but may also reject some legit matches where prices changed during the day).

### Option C: Tighter NAME_SCORE_MIN
Raise from 0.4 to 0.55. This would cut the 0.4-0.5 bucket entirely (175 matches — mostly garbage based on samples).

### Option D (best): Combine B + C + A
- MRP tolerance: 8%
- NAME_SCORE_MIN: 0.55
- Brand agreement boost: +0.15 if brand tokens overlap
- Brand mismatch penalty: -0.15 if no overlap AND ana_brand was non-empty

## Impact estimate

With Option D applied, Stage 3 output would likely go from 282 matches → ~40-60 high-quality matches. Quality over quantity.

## Price diff analysis

For the current 282 matches:
- Median price diff: 10.0%
- Mean price diff: 13.2%
- Within 5%: 31.8%
- Within 10%: 52.1%
- Within 15%: 69.6%

Compare to Stage 1 (PDP direct) which had 94.6% within 5%. Stage 3 quality is much lower — expected because there's no URL-level ground truth.

## Note for Dev and PM agents

- Dev agent: please consider implementing Option D in `stage3_match.py`
- PM agent: use this as a starting point for your 99% feasibility analysis. Stage 3 contributes to coverage but not to Stage 1's gold-standard accuracy.
