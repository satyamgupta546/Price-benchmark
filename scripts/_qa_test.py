"""Temporary QA analysis script for cascade_match.py review."""
import json
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
data_path = PROJECT_ROOT / "data" / "comparisons" / "blinkit_cascade_834002_2026-04-15_125310.json"

with open(data_path) as f:
    data = json.load(f)

matches = data["new_mappings"]
unmatched = data["unmatched"]

print(f"Total matches: {len(matches)}")
print(f"Total unmatched: {len(unmatched)}")
print()

# 1. How many matches have cascade_score < 0.5?
low_score = [m for m in matches if m["cascade_score"] < 0.5]
print(f"Matches with cascade_score < 0.5: {len(low_score)} / {len(matches)} ({len(low_score)/len(matches)*100:.1f}%)")
print()

# 2. How many have "NA" unit?
na_unit_matches = [m for m in matches if " NA" in (m.get("anakin_weight") or "")]
print(f"Matches with anakin_weight containing 'NA' unit: {len(na_unit_matches)} / {len(matches)}")

# 3. How many have sam_unit null?
null_sam_unit = [m for m in matches if m.get("sam_unit") is None]
print(f"Matches with sam_unit=null: {len(null_sam_unit)} / {len(matches)}")
print()

# 4. Rejection reasons breakdown (unmatched)
reasons = {}
for u in unmatched:
    r = u["cascade_reason"]
    reasons[r] = reasons.get(r, 0) + 1
print("Unmatched reason breakdown:")
for r, c in sorted(reasons.items(), key=lambda x: -x[1]):
    print(f"  {r:25s} {c}")
print()

# 5. Check 10 random-ish matches for brand consistency and product mismatch
import random
random.seed(42)
sample = random.sample(matches, min(15, len(matches)))
print("=== SAMPLE MATCH QUALITY CHECK ===")
mismatches = 0
for m in sample:
    ana_brand = (m.get("anakin_brand") or "").lower().strip()
    sam_brand = (m.get("sam_brand") or "").lower().strip()
    brand_ok = ana_brand == sam_brand or ana_brand in sam_brand or sam_brand in ana_brand

    ana_name = m.get("anakin_name", "")
    sam_name = m.get("sam_product_name", "")
    score = m["cascade_score"]

    # Check if products are clearly different
    flag = ""
    if not brand_ok:
        flag += " [BRAND MISMATCH]"
        mismatches += 1

    # Check weight
    ana_wt = m.get("anakin_weight", "")
    sam_unit = m.get("sam_unit") or "N/A"

    print(f"  Score={score:.3f} | Brand OK={brand_ok}")
    print(f"    Anakin: {ana_name} ({ana_wt})")
    print(f"    SAM:    {sam_name} ({sam_unit}){flag}")
    print()

# 6. Simulate mandatory weight filter on existing 904 matches
# The weight filter ONLY runs when ana_uv and ana_unit are both truthy
# "NNN NA" means Unit_Value=NNN, Unit="NA" -> clean_str("NA")="" -> falsy -> BYPASS
# Let's count how many would SURVIVE if we required weight check for ALL

UNIT_ALIASES = {
    "g": "g", "gm": "g", "gms": "g", "gram": "g", "grams": "g",
    "kg": "kg", "kgs": "kg", "kilo": "kg", "kilogram": "kg", "kilograms": "kg",
    "ml": "ml", "mls": "ml", "millilitre": "ml", "milliliter": "ml",
    "l": "l", "ltr": "l", "ltrs": "l", "liter": "l", "litre": "l", "liters": "l", "litres": "l",
    "pc": "pc", "pcs": "pc", "piece": "pc", "pieces": "pc", "n": "pc",
    "unit": "pc", "units": "pc", "pack": "pc",
}

def parse_unit(text):
    if not text:
        return None, None
    s = str(text).strip().lower()
    s = re.sub(r"(\d+)/(\d+)", lambda m: str(round(int(m.group(1)) / int(m.group(2)), 4)), s)
    m = re.search(r"(\d+\.?\d*)\s*[x\u00d7]\s*(\d+\.?\d*)\s*(g|gm|kg|ml|l|ltr|pc|pcs|piece|pieces|n|unit|units|pack)", s)
    if m:
        try:
            return float(m.group(1)) * float(m.group(2)), UNIT_ALIASES.get(m.group(3), m.group(3))
        except ValueError:
            pass
    m = re.search(r"(\d+\.?\d*)\s*(g|gm|kg|ml|l|ltr|pc|pcs|piece|pieces|n|unit|units|pack)\b", s)
    if m:
        try:
            return float(m.group(1)), UNIT_ALIASES.get(m.group(2), m.group(2))
        except ValueError:
            pass
    return None, None

def to_base_unit(value, unit):
    if unit == "kg":
        return value * 1000, "g"
    if unit == "l":
        return value * 1000, "ml"
    return value, unit

def units_compatible(u1, u2):
    if not u1 or not u2:
        return False
    base1 = "g" if u1 in ("g", "kg") else ("ml" if u1 in ("ml", "l") else u1)
    base2 = "g" if u2 in ("g", "kg") else ("ml" if u2 in ("ml", "l") else u2)
    return base1 == base2

# For each match, check if weight is parseable and compatible
weight_ok = 0
weight_fail_no_ana = 0
weight_fail_no_sam = 0
weight_fail_incompatible = 0
weight_fail_ratio = 0

for m in matches:
    ana_wt = m.get("anakin_weight", "")
    sam_unit_str = m.get("sam_unit") or ""

    # Try parsing anakin weight from the combined "Unit_Value Unit" string
    ana_uv, ana_u = parse_unit(ana_wt)
    sam_uv, sam_u = parse_unit(sam_unit_str)

    if not ana_uv or not ana_u:
        weight_fail_no_ana += 1
        continue
    if not sam_uv or not sam_u:
        weight_fail_no_sam += 1
        continue
    if not units_compatible(ana_u, sam_u):
        weight_fail_incompatible += 1
        continue

    ana_base, _ = to_base_unit(ana_uv, ana_u)
    sam_base, _ = to_base_unit(sam_uv, sam_u)
    if ana_base > 0 and sam_base > 0:
        ratio = sam_base / ana_base
        if 0.8 <= ratio <= 1.25:
            weight_ok += 1
        else:
            weight_fail_ratio += 1
    else:
        weight_fail_ratio += 1

print()
print("=== RE-SIMULATION: Mandatory weight filter on all 904 matches ===")
print(f"Would SURVIVE weight filter:         {weight_ok}")
print(f"Rejected - no parseable Anakin unit:  {weight_fail_no_ana}")
print(f"Rejected - no parseable SAM unit:     {weight_fail_no_sam}")
print(f"Rejected - incompatible units:        {weight_fail_incompatible}")
print(f"Rejected - ratio out of range:        {weight_fail_ratio}")
print(f"Total rejections:                     {weight_fail_no_ana + weight_fail_no_sam + weight_fail_incompatible + weight_fail_ratio}")
print(f"Survival rate:                        {weight_ok}/{len(matches)} = {weight_ok/len(matches)*100:.1f}%")

# 7. Check for clearly wrong product matches (different product types)
print()
print("=== EGREGIOUS MISMATCHES (product type clearly wrong) ===")
bad = []
for m in matches:
    ana = m.get("anakin_name", "").lower()
    sam = m.get("sam_product_name", "").lower()
    score = m["cascade_score"]

    # Flag if one is food and other is non-food
    food_words = {"rice", "oil", "flour", "atta", "dal", "sugar", "salt", "noodles", "pasta", "biscuit", "cookie", "chips"}
    nonfood_words = {"detergent", "soap", "shampoo", "cream", "lotion", "cleaner", "brush", "broom"}

    ana_food = any(w in ana for w in food_words)
    ana_nonfood = any(w in ana for w in nonfood_words)
    sam_food = any(w in sam for w in food_words)
    sam_nonfood = any(w in sam for w in nonfood_words)

    if (ana_food and sam_nonfood) or (ana_nonfood and sam_food):
        bad.append(m)

    # Also flag sachet->large pack type mismatches where price differs >5x
    ana_mrp = float(m.get("anakin_mrp") or 0) if m.get("anakin_mrp") else 0
    sam_price = float(m.get("sam_price") or 0) if m.get("sam_price") else 0
    if ana_mrp > 0 and sam_price > 0:
        price_ratio = max(ana_mrp, sam_price) / min(ana_mrp, sam_price)
        if price_ratio > 10 and score < 0.6:
            if m not in bad:
                bad.append(m)

print(f"Found {len(bad)} egregious mismatches")
for m in bad[:10]:
    print(f"  Score={m['cascade_score']:.3f}")
    print(f"    Anakin: {m['anakin_name']} (MRP={m['anakin_mrp']})")
    print(f"    SAM:    {m['sam_product_name']} (Price={m['sam_price']}, Unit={m.get('sam_unit')})")
    print()
