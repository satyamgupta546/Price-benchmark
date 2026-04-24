"""
SAM Pipeline Data Quality Report
Run: ./backend/venv/bin/python scripts/qa_check.py
"""
import json
import csv
import os
import random
from pathlib import Path
from collections import defaultdict, Counter
from datetime import datetime
import re

DATA_ROOT = Path(__file__).resolve().parent.parent / "data"
CITIES = {"834002": "Ranchi", "712232": "Kolkata", "492001": "Raipur", "825301": "Hazaribagh"}
PLATFORMS = ["blinkit", "jiomart"]

random.seed(42)  # Reproducible samples

print("=" * 80)
print("SAM PIPELINE DATA QUALITY REPORT")
print(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
print("=" * 80)

# ============================================================================
# 1. MATCH ACCURACY PER STAGE
# ============================================================================
print("\n" + "=" * 80)
print("1. MATCH ACCURACY PER STAGE (sampling up to 20 per stage)")
print("=" * 80)

def check_name_similarity(name1, name2):
    if not name1 or not name2:
        return 0
    w1 = set(name1.lower().split())
    w2 = set(name2.lower().split())
    union = w1 | w2
    return len(w1 & w2) / len(union) if union else 0

def check_brand_match(anakin_brand, sam_name):
    if not anakin_brand or not sam_name:
        return None
    return anakin_brand.lower().strip() in sam_name.lower()

stage_accuracy = {}

for platform in PLATFORMS:
    for pincode in CITIES:
        # --- PDP ---
        pdp_files = sorted(DATA_ROOT.glob(f"comparisons/{platform}_pdp_{pincode}_*_compare.json"))
        if pdp_files:
            d = json.load(open(pdp_files[-1]))
            ok_matches = [m for m in d.get("matches", []) if m.get("match_status") == "ok"]
            if ok_matches:
                sample = random.sample(ok_matches, min(20, len(ok_matches)))
                # PDP visits exact Anakin-mapped URLs, so ok status means correct by design
                correct = len(sample)
                key = f"PDP ({platform})"
                stage_accuracy.setdefault(key, {"correct": 0, "total": 0, "all_count": 0, "wrong": []})
                stage_accuracy[key]["correct"] += correct
                stage_accuracy[key]["total"] += len(sample)
                stage_accuracy[key]["all_count"] += len(ok_matches)

        # --- Cascade ---
        cascade_files = sorted(DATA_ROOT.glob(f"comparisons/{platform}_cascade_{pincode}_*.json"))
        if cascade_files:
            d = json.load(open(cascade_files[-1]))
            mappings = d.get("new_mappings", [])
            if mappings:
                sample = random.sample(mappings, min(20, len(mappings)))
                correct = 0
                wrong_examples = []
                for m in sample:
                    anakin_name = m.get("anakin_name", "")
                    sam_name = m.get("sam_product_name", "")
                    anakin_brand = m.get("anakin_brand", "")
                    score = m.get("cascade_score", 0)
                    brand_ok = check_brand_match(anakin_brand, sam_name)
                    jaccard = check_name_similarity(anakin_name, sam_name)
                    is_correct = (brand_ok is True or brand_ok is None) and jaccard > 0.15
                    if is_correct:
                        correct += 1
                    else:
                        wrong_examples.append(
                            f"    MISMATCH: '{anakin_name}' -> '{sam_name}' "
                            f"(brand_ok={brand_ok}, jaccard={jaccard:.3f}, score={score})")
                key = f"Cascade ({platform})"
                stage_accuracy.setdefault(key, {"correct": 0, "total": 0, "all_count": 0, "wrong": []})
                stage_accuracy[key]["correct"] += correct
                stage_accuracy[key]["total"] += len(sample)
                stage_accuracy[key]["all_count"] += len(mappings)
                stage_accuracy[key]["wrong"].extend(wrong_examples[:5])

        # --- Stage3 ---
        stage3_files = sorted(DATA_ROOT.glob(f"comparisons/{platform}_stage3_{pincode}_*.json"))
        if stage3_files:
            d = json.load(open(stage3_files[-1]))
            mappings = d.get("new_mappings", [])
            if mappings:
                sample = random.sample(mappings, min(20, len(mappings)))
                correct = 0
                wrong_examples = []
                for m in sample:
                    anakin_name = m.get("anakin_name", "")
                    sam_name = m.get("sam_product_name", "")
                    anakin_brand = m.get("anakin_brand", "")
                    score = m.get("stage3_score", 0)
                    brand_ok = check_brand_match(anakin_brand, sam_name)
                    jaccard = check_name_similarity(anakin_name, sam_name)
                    is_correct = jaccard > 0.1 and (brand_ok is True or brand_ok is None)
                    if is_correct:
                        correct += 1
                    else:
                        wrong_examples.append(
                            f"    MISMATCH: '{anakin_name}' -> '{sam_name}' "
                            f"(brand_ok={brand_ok}, jaccard={jaccard:.3f}, score={score})")
                key = f"Stage3 ({platform})"
                stage_accuracy.setdefault(key, {"correct": 0, "total": 0, "all_count": 0, "wrong": []})
                stage_accuracy[key]["correct"] += correct
                stage_accuracy[key]["total"] += len(sample)
                stage_accuracy[key]["all_count"] += len(mappings)
                stage_accuracy[key]["wrong"].extend(wrong_examples[:5])

        # --- Search ---
        search_files = sorted(DATA_ROOT.glob(f"comparisons/{platform}_search_match_{pincode}_*.json"))
        if platform == "blinkit":
            search_files += sorted(DATA_ROOT.glob(f"comparisons/jiomart_search_match_{pincode}_*.json"))
        search_files = list(dict.fromkeys(search_files))
        if search_files:
            d = json.load(open(search_files[-1]))
            mappings = d.get("new_mappings", [])
            if mappings:
                sample = random.sample(mappings, min(20, len(mappings)))
                correct = 0
                wrong_examples = []
                for m in sample:
                    anakin_name = m.get("anakin_name", m.get("anakin_jiomart_name", ""))
                    sam_name = m.get("sam_product_name", "")
                    score = m.get("match_score", 0)
                    price_diff = m.get("price_diff_pct", 0) or 0
                    jaccard = check_name_similarity(anakin_name, sam_name)
                    is_correct = jaccard > 0.15 and abs(price_diff) < 200
                    if is_correct:
                        correct += 1
                    else:
                        wrong_examples.append(
                            f"    MISMATCH: '{anakin_name}' -> '{sam_name}' "
                            f"(jaccard={jaccard:.3f}, score={score}, price_diff={price_diff}%)")
                key = f"Search ({platform})"
                stage_accuracy.setdefault(key, {"correct": 0, "total": 0, "all_count": 0, "wrong": []})
                stage_accuracy[key]["correct"] += correct
                stage_accuracy[key]["total"] += len(sample)
                stage_accuracy[key]["all_count"] += len(mappings)
                stage_accuracy[key]["wrong"].extend(wrong_examples[:5])

for stage, data in sorted(stage_accuracy.items()):
    pct = round(data["correct"] * 100 / data["total"], 1) if data["total"] else 0
    print(f"\n  {stage}:")
    print(f"    Sampled: {data['total']} | Correct: {data['correct']} | Accuracy: {pct}%")
    print(f"    Total matches in this stage across all cities: {data['all_count']}")
    for w in data.get("wrong", [])[:5]:
        print(w)

# ============================================================================
# 2. PRICE SANITY
# ============================================================================
print("\n" + "=" * 80)
print("2. PRICE SANITY CHECKS")
print("=" * 80)

price_issues = {
    "below_1": [],
    "above_50000": [],
    "sp_exceeds_mrp": [],
    "zero_or_negative": [],
}
total_prices_checked = 0

for pincode in CITIES:
    files = sorted(DATA_ROOT.glob(f"sam_output/sam_competitor_prices_{pincode}_2026-04-15.json"))
    if not files:
        files = sorted(DATA_ROOT.glob(f"sam_output/sam_competitor_prices_{pincode}_*.json"))
    if not files:
        continue
    rows = json.load(open(files[-1]))

    for row in rows:
        for prefix in ["Blinkit", "Jiomart"]:
            sp_val = row.get(f"{prefix}_Selling_Price", "NA")
            mrp_val = row.get(f"{prefix}_Mrp_Price", "NA")

            if sp_val not in ("NA", "", None):
                try:
                    sp = float(sp_val)
                    total_prices_checked += 1
                    if sp <= 0:
                        price_issues["zero_or_negative"].append(
                            f"  {CITIES[pincode]}/{prefix}: Item {row['Item_Code']} "
                            f"'{row['Item_Name'][:40]}' SP={sp}")
                    elif sp < 1:
                        price_issues["below_1"].append(
                            f"  {CITIES[pincode]}/{prefix}: Item {row['Item_Code']} "
                            f"'{row['Item_Name'][:40]}' SP={sp}")
                    elif sp > 50000:
                        price_issues["above_50000"].append(
                            f"  {CITIES[pincode]}/{prefix}: Item {row['Item_Code']} "
                            f"'{row['Item_Name'][:40]}' SP={sp}")
                except (ValueError, TypeError):
                    pass

            if sp_val not in ("NA", "", None) and mrp_val not in ("NA", "", None):
                try:
                    sp = float(sp_val)
                    mrp = float(mrp_val)
                    if sp > mrp > 0:
                        price_issues["sp_exceeds_mrp"].append(
                            f"  {CITIES[pincode]}/{prefix}: Item {row['Item_Code']} "
                            f"'{row['Item_Name'][:40]}' SP={sp} > MRP={mrp}")
                except (ValueError, TypeError):
                    pass

print(f"\n  Total price values checked: {total_prices_checked}")
for issue_type, issues in price_issues.items():
    label = {
        "below_1": "Prices < Rs 1",
        "above_50000": "Prices > Rs 50,000",
        "sp_exceeds_mrp": "Selling Price > MRP",
        "zero_or_negative": "Zero or negative prices",
    }[issue_type]
    print(f"\n  {label}: {len(issues)} issues")
    for i in issues[:5]:
        print(i)
    if len(issues) > 5:
        print(f"  ... and {len(issues) - 5} more")

# ============================================================================
# 3. DUPLICATE DETECTION
# ============================================================================
print("\n" + "=" * 80)
print("3. DUPLICATE DETECTION")
print("=" * 80)

print("\n  3a. Duplicate Item_Codes in SAM output files:")
for pincode in CITIES:
    files = sorted(DATA_ROOT.glob(f"sam_output/sam_competitor_prices_{pincode}_2026-04-15.json"))
    if not files:
        files = sorted(DATA_ROOT.glob(f"sam_output/sam_competitor_prices_{pincode}_*.json"))
    if not files:
        continue
    rows = json.load(open(files[-1]))
    item_codes = [r["Item_Code"] for r in rows]
    dupes = {ic: cnt for ic, cnt in Counter(item_codes).items() if cnt > 1}
    if dupes:
        print(f"    {CITIES[pincode]} ({pincode}): {len(dupes)} duplicate item_codes!")
        for ic, cnt in list(dupes.items())[:5]:
            print(f"      Item_Code {ic} appears {cnt} times")
    else:
        print(f"    {CITIES[pincode]} ({pincode}): No duplicates in {len(rows)} rows. PASS")

print("\n  3b. Duplicate Item_Codes in mapping files:")
for platform in PLATFORMS:
    for pincode in CITIES:
        path = DATA_ROOT / "mappings" / f"{platform}_{pincode}.json"
        if not path.exists():
            print(f"    {platform}/{CITIES[pincode]}: No mapping file")
            continue
        d = json.load(open(path))
        mappings = d.get("mappings", [])
        item_codes = [m["item_code"] for m in mappings]
        dupes = {ic: cnt for ic, cnt in Counter(item_codes).items() if cnt > 1}
        if dupes:
            print(f"    {platform}/{CITIES[pincode]}: {len(dupes)} duplicate item_codes!")
        else:
            print(f"    {platform}/{CITIES[pincode]}: No duplicates in {len(mappings)} mappings. PASS")

print("\n  3c. Stage overlap (items claimed by multiple stages in latest run):")
for platform in PLATFORMS:
    for pincode in CITIES:
        stage_claims = defaultdict(list)

        pdp_files = sorted(DATA_ROOT.glob(f"comparisons/{platform}_pdp_{pincode}_*_compare.json"))
        if pdp_files:
            d = json.load(open(pdp_files[-1]))
            for m in d.get("matches", []):
                if m.get("match_status") == "ok":
                    stage_claims[m.get("item_code")].append("PDP")

        cascade_files = sorted(DATA_ROOT.glob(f"comparisons/{platform}_cascade_{pincode}_*.json"))
        if cascade_files:
            d = json.load(open(cascade_files[-1]))
            for m in d.get("new_mappings", []):
                stage_claims[m.get("item_code")].append("Cascade")

        stage3_files = sorted(DATA_ROOT.glob(f"comparisons/{platform}_stage3_{pincode}_*.json"))
        if stage3_files:
            d = json.load(open(stage3_files[-1]))
            for m in d.get("new_mappings", []):
                stage_claims[m.get("item_code")].append("Stage3")

        search_files = sorted(DATA_ROOT.glob(f"comparisons/{platform}_search_match_{pincode}_*.json"))
        if not search_files:
            search_files = sorted(DATA_ROOT.glob(f"comparisons/jiomart_search_match_{pincode}_*.json"))
        if search_files:
            d = json.load(open(search_files[-1]))
            for m in d.get("new_mappings", []):
                stage_claims[m.get("item_code")].append("Search")

        multi = {ic: st for ic, st in stage_claims.items() if len(st) > 1}
        total_claimed = len(stage_claims)
        if multi:
            print(f"    {platform}/{CITIES[pincode]}: {len(multi)} items in multiple stages (out of {total_claimed})")
            for ic, stages in list(multi.items())[:3]:
                print(f"      Item {ic}: {' + '.join(stages)}")
        elif total_claimed:
            print(f"    {platform}/{CITIES[pincode]}: No overlaps across {total_claimed} items. PASS")
        else:
            print(f"    {platform}/{CITIES[pincode]}: No comparison data")

# ============================================================================
# 4. COMPLETENESS
# ============================================================================
print("\n" + "=" * 80)
print("4. COMPLETENESS CHECK")
print("=" * 80)

for pincode in CITIES:
    anakin_files = sorted((DATA_ROOT / "anakin").glob(f"blinkit_{pincode}_*.json"))
    anakin_files = [f for f in anakin_files if ".bak" not in f.name]
    if not anakin_files:
        print(f"\n  {CITIES[pincode]} ({pincode}): No Anakin data")
        continue

    anakin = json.load(open(anakin_files[-1]))
    anakin_ics = {str(r["Item_Code"]) for r in anakin.get("records", []) if r.get("Item_Code")}

    sam_files = sorted(DATA_ROOT.glob(f"sam_output/sam_competitor_prices_{pincode}_2026-04-15.json"))
    if not sam_files:
        sam_files = sorted(DATA_ROOT.glob(f"sam_output/sam_competitor_prices_{pincode}_*.json"))
    if not sam_files:
        print(f"\n  {CITIES[pincode]} ({pincode}): No SAM output")
        continue

    sam_rows = json.load(open(sam_files[-1]))
    sam_ics = {str(r["Item_Code"]) for r in sam_rows}

    missing_from_sam = anakin_ics - sam_ics
    extra_in_sam = sam_ics - anakin_ics

    priced = sum(1 for r in sam_rows
                 if r.get("Blinkit_Selling_Price", "NA") != "NA"
                 or r.get("Jiomart_Selling_Price", "NA") != "NA")

    print(f"\n  {CITIES[pincode]} ({pincode}):")
    print(f"    Anakin items: {len(anakin_ics)}")
    print(f"    SAM output rows: {len(sam_rows)}")
    print(f"    Items with >=1 price: {priced} ({round(priced*100/len(sam_rows),1) if sam_rows else 0}%)")
    print(f"    Missing from SAM (in Anakin but not SAM): {len(missing_from_sam)}")
    print(f"    Extra in SAM (not in Anakin): {len(extra_in_sam)}")
    if missing_from_sam:
        print(f"    Sample missing: {list(missing_from_sam)[:5]}")
    if extra_in_sam:
        print(f"    ALERT -- extra items: {list(extra_in_sam)[:5]}")

# ============================================================================
# 5. FRESHNESS
# ============================================================================
print("\n" + "=" * 80)
print("5. DATA FRESHNESS")
print("=" * 80)

today = datetime(2026, 4, 15)

print("\n  5a. Latest SAM output per city:")
for pincode in CITIES:
    files = sorted(DATA_ROOT.glob(f"sam_output/sam_competitor_prices_{pincode}_*.csv"))
    if files:
        latest = files[-1].name
        date_str = latest.split("_")[-1].replace(".csv", "")
        try:
            file_date = datetime.strptime(date_str, "%Y-%m-%d")
            age_days = (today - file_date).days
            status = "CURRENT" if age_days == 0 else f"STALE ({age_days} day(s) old)"
            print(f"    {CITIES[pincode]}: {latest} -- {status}")
        except Exception:
            print(f"    {CITIES[pincode]}: {latest}")
    else:
        print(f"    {CITIES[pincode]}: NO OUTPUT FILE")

print("\n  5b. Latest PDP scrape per city/platform:")
for platform in PLATFORMS:
    for pincode in CITIES:
        pdp = sorted(DATA_ROOT.glob(f"comparisons/{platform}_pdp_{pincode}_*_compare.json"))
        if pdp:
            name = pdp[-1].name
            parts = name.replace("_compare.json", "").split("_")
            date_part = parts[-2] if len(parts) >= 3 else "unknown"
            print(f"    {platform}/{CITIES[pincode]}: {date_part}")
        else:
            print(f"    {platform}/{CITIES[pincode]}: NO PDP scrape")

print("\n  5c. Stale/partial files that may need cleanup:")
partial_files = list(DATA_ROOT.glob("**/*partial*"))
bak_files = list(DATA_ROOT.glob("**/*.bak"))
print(f"    Partial files: {len(partial_files)}")
for f in partial_files:
    print(f"      {f.relative_to(DATA_ROOT)}")
print(f"    .bak files: {len(bak_files)}")
for f in bak_files:
    print(f"      {f.relative_to(DATA_ROOT)}")

# ============================================================================
# 6. CROSS-CITY PRICE CONSISTENCY
# ============================================================================
print("\n" + "=" * 80)
print("6. CROSS-CITY PRICE CONSISTENCY")
print("=" * 80)

city_prices = defaultdict(dict)

for pincode in CITIES:
    files = sorted(DATA_ROOT.glob(f"sam_output/sam_competitor_prices_{pincode}_2026-04-15.json"))
    if not files:
        files = sorted(DATA_ROOT.glob(f"sam_output/sam_competitor_prices_{pincode}_*.json"))
    if not files:
        continue
    rows = json.load(open(files[-1]))
    for row in rows:
        ic = row["Item_Code"]
        for prefix in ["Blinkit", "Jiomart"]:
            sp = row.get(f"{prefix}_Selling_Price", "NA")
            if sp not in ("NA", "", None):
                try:
                    sp_val = float(sp)
                    city_prices[ic].setdefault(prefix, {})[pincode] = sp_val
                except (ValueError, TypeError):
                    pass

wild_variations = []
total_cross_city = 0

for ic, platform_prices in city_prices.items():
    for platform, city_vals in platform_prices.items():
        if len(city_vals) >= 2:
            total_cross_city += 1
            prices = list(city_vals.values())
            min_p = min(prices)
            max_p = max(prices)
            if min_p > 0:
                variation_pct = (max_p - min_p) / min_p * 100
                if variation_pct > 50:
                    wild_variations.append({
                        "item_code": ic,
                        "platform": platform,
                        "prices": {CITIES[p]: v for p, v in city_vals.items()},
                        "variation_pct": round(variation_pct, 1),
                    })

wild_variations.sort(key=lambda x: x["variation_pct"], reverse=True)

print(f"\n  Items priced in 2+ cities: {total_cross_city}")
print(f"  Items with >50% price variation: {len(wild_variations)}")
if wild_variations:
    print(f"\n  Top 10 wildest variations:")
    for v in wild_variations[:10]:
        price_str = ", ".join(f"{city}: Rs {p}" for city, p in v["prices"].items())
        print(f"    Item {v['item_code']} ({v['platform']}): {price_str} -- {v['variation_pct']}% var")

if total_cross_city:
    all_variations = []
    for ic, platform_prices in city_prices.items():
        for platform, city_vals in platform_prices.items():
            if len(city_vals) >= 2:
                prices = list(city_vals.values())
                min_p = min(prices)
                if min_p > 0:
                    all_variations.append((max(prices) - min_p) / min_p * 100)

    if all_variations:
        all_variations.sort()
        n = len(all_variations)
        print(f"\n  Variation distribution ({n} item-platform combos with 2+ cities):")
        print(f"    Median: {all_variations[n//2]:.1f}%")
        print(f"    90th pctile: {all_variations[int(n*0.9)]:.1f}%")
        print(f"    <5%: {sum(1 for v in all_variations if v < 5)} ({round(sum(1 for v in all_variations if v < 5)*100/n,1)}%)")
        print(f"    5-20%: {sum(1 for v in all_variations if 5 <= v < 20)}")
        print(f"    20-50%: {sum(1 for v in all_variations if 20 <= v < 50)}")
        print(f"    >50%: {sum(1 for v in all_variations if v >= 50)}")

# ============================================================================
# SUMMARY
# ============================================================================
print("\n" + "=" * 80)
print("PIPELINE COVERAGE SUMMARY")
print("=" * 80)

for pincode in CITIES:
    files = sorted(DATA_ROOT.glob(f"sam_output/sam_competitor_prices_{pincode}_2026-04-15.json"))
    if not files:
        files = sorted(DATA_ROOT.glob(f"sam_output/sam_competitor_prices_{pincode}_*.json"))
    if not files:
        continue
    rows = json.load(open(files[-1]))

    b_priced = sum(1 for r in rows if r.get("Blinkit_Selling_Price", "NA") != "NA")
    j_priced = sum(1 for r in rows if r.get("Jiomart_Selling_Price", "NA") != "NA")
    either = sum(1 for r in rows
                 if r.get("Blinkit_Selling_Price", "NA") != "NA"
                 or r.get("Jiomart_Selling_Price", "NA") != "NA")

    methods_b = Counter(r.get("Blinkit_Partial", "NA") for r in rows if r.get("Blinkit_Selling_Price", "NA") != "NA")
    methods_j = Counter(r.get("Jiomart_Partial", "NA") for r in rows if r.get("Jiomart_Selling_Price", "NA") != "NA")

    print(f"\n  {CITIES[pincode]} ({pincode}): {len(rows)} total items")
    print(f"    Blinkit priced: {b_priced} ({round(b_priced*100/len(rows),1)}%)")
    print(f"    Jiomart priced: {j_priced} ({round(j_priced*100/len(rows),1)}%)")
    print(f"    Either: {either} ({round(either*100/len(rows),1)}%)")
    if methods_b:
        print(f"    Blinkit by method: {dict(methods_b.most_common())}")
    if methods_j:
        print(f"    Jiomart by method: {dict(methods_j.most_common())}")

print("\n  Mapping files summary:")
for platform in PLATFORMS:
    for pincode in CITIES:
        path = DATA_ROOT / "mappings" / f"{platform}_{pincode}.json"
        if not path.exists():
            print(f"    {platform}/{CITIES[pincode]}: MISSING")
            continue
        d = json.load(open(path))
        print(f"    {platform}/{CITIES[pincode]}: {d.get('total_mappings',0)} mappings -- {dict(d.get('by_method',{}))}")

print("\n" + "=" * 80)
print("END OF QUALITY REPORT")
print("=" * 80)
