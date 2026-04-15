"""
Structural and logic tests for verify_against_anakin.py
"""
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

from verify_against_anakin import (
    parse_price, price_accuracy_buckets, top_mismatches,
    collect_stage_results, load_anakin, get_usable_codes,
)

failures = []


def check(label, actual, expected=True):
    if actual == expected:
        print(f"  PASS: {label}")
    else:
        msg = f"  FAIL: {label} -> got {actual!r}, expected {expected!r}"
        print(msg)
        failures.append(msg)


# ── parse_price tests ─────────────────────────────────────────
print("=== parse_price ===")
check('parse_price(None)', parse_price(None), None)
check('parse_price("")', parse_price(""), None)
check('parse_price("NA")', parse_price("NA"), None)
check('parse_price("nan")', parse_price("nan"), None)
check('parse_price("#VALUE!")', parse_price("#VALUE!"), None)
check('parse_price(100)', parse_price(100), 100.0)
check('parse_price("99.5")', parse_price("99.5"), 99.5)

# ── price_accuracy_buckets tests ──────────────────────────────
print("\n=== price_accuracy_buckets ===")

# Empty input
b = price_accuracy_buckets([])
check("Empty input", b, {"compared": 0})

# All within 2%
matches = [{"price_diff_pct": 1.0}, {"price_diff_pct": 0.5}, {"price_diff_pct": 2.0}]
b = price_accuracy_buckets(matches)
check("3 matches within 2%", b["within_2pct"], 3)
check("accuracy_2pct = 100.0", b["accuracy_2pct"], 100.0)

# Mix
matches = [
    {"price_diff_pct": 1.0},   # within 2
    {"price_diff_pct": 4.0},   # within 5
    {"price_diff_pct": 8.0},   # within 10
    {"price_diff_pct": 15.0},  # within 20
    {"price_diff_pct": 25.0},  # beyond 20
]
b = price_accuracy_buckets(matches)
check("within_2pct = 1", b["within_2pct"], 1)
check("within_5pct = 2", b["within_5pct"], 2)
check("within_10pct = 3", b["within_10pct"], 3)
check("within_20pct = 4", b["within_20pct"], 4)
check("beyond_20pct = 1", b["beyond_20pct"], 1)

# ── top_mismatches tests ──────────────────────────────────────
print("\n=== top_mismatches ===")
matches = [
    {"price_diff_pct": 1.0, "item_code": "a"},
    {"price_diff_pct": 25.0, "item_code": "b"},
    {"price_diff_pct": 5.0, "item_code": "c"},
    {"price_diff_pct": 50.0, "item_code": "d"},
]
mm = top_mismatches(matches, n=2)
check("top_mismatches returns 2", len(mm), 2)
check("First is highest diff", mm[0]["item_code"], "d")
check("Second is second highest", mm[1]["item_code"], "b")
# Items with diff <= 2 should be excluded
check("1.0% excluded from mismatches", all(m["item_code"] != "a" for m in mm))

# ── Account for all stages ────────────────────────────────────
print("\n=== Stage accounting ===")
src = (SCRIPTS / "verify_against_anakin.py").read_text()

# Check all stages are present
check("Stage 1 PDP Direct", "Stage 1" in src)
check("Stage 2 Brand Cascade", "Stage 2" in src)
check("Stage 3 Type/MRP Cascade", "Stage 3" in src)
check("Stage 4 Search API", "Stage 4" in src)
check("Stage 5a Image Match", "Stage 5a" in src)
check("Stage 5b Barcode Match", "Stage 5b" in src)

# ── Deduplication across stages ───────────────────────────────
print("\n=== Deduplication ===")
# The script tracks cumulative all_matched and computes new_codes per stage
check("Tracks cumulative all_matched", "all_matched" in src)
check("Computes new_codes per stage", "new_codes" in src)
# Each stage uses its own _seen set for internal dedup
check("stage1_seen dedup", "stage1_seen" in src)
check("stage2_seen dedup", "stage2_seen" in src)
check("stage3_seen dedup", "stage3_seen" in src)

# ── Live test with actual data ────────────────────────────────
print("\n=== Live data test (834002 blinkit) ===")
anakin = load_anakin("834002", "blinkit")
if anakin:
    check("Anakin data loaded", len(anakin) > 0)
    print(f"  INFO: Loaded {len(anakin)} Anakin SKUs")

    usable = get_usable_codes(anakin, "blinkit")
    check("Usable codes > 0", len(usable) > 0)
    print(f"  INFO: {len(usable)} usable codes")

    stages, all_matched = collect_stage_results("834002", "blinkit", anakin)
    check("6 stages returned", len(stages), 6)

    # Check dedup: all_matched should have no duplicates by definition (it's a set)
    check("all_matched is a set", isinstance(all_matched, set))

    # Verify new_codes don't overlap across stages
    all_new = set()
    for s in stages:
        overlap = all_new & s["new_codes"]
        check(f"{s['name']} new_codes no overlap", len(overlap), 0)
        all_new |= s["new_codes"]

    # Coverage should be reasonable (>70%)
    matched_usable = all_matched & usable
    coverage = round(len(matched_usable) * 100 / len(usable), 1) if usable else 0
    check(f"Coverage {coverage}% > 70%", coverage > 70)
else:
    print("  SKIP: No Anakin data available for 834002")

print(f"\n{'='*40}")
if failures:
    print(f"FAILURES: {len(failures)}")
    for f in failures:
        print(f)
    sys.exit(1)
else:
    print("ALL TESTS PASSED")
