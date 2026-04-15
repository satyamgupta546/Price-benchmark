"""
Structural tests for jiomart_scraper.py (no browser launch).
"""
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND))

failures = []


def check(label, actual, expected=True):
    if actual == expected:
        print(f"  PASS: {label}")
    else:
        msg = f"  FAIL: {label} -> got {actual!r}, expected {expected!r}"
        print(msg)
        failures.append(msg)


src = (BACKEND / "app" / "scrapers" / "jiomart_scraper.py").read_text()

# ── 1. Pagination ────────────────────────────────────────────
print("=== Pagination ===")
check("page= in category crawl", "?page=" in src)
check("range(2, 20) pagination loop", "range(2, 20)" in src)
check("Breaks on empty page", 'break  # no more pages' in src)

# ── 2. Grocery-only filter in _parse_trex_results ────────────
print("\n=== Grocery filter ===")
check("categories filter in _parse_trex_results", '"Groceries"' in src)
check("groceries check (lowercase)", '"groceries"' in src)
check("Skip non-grocery items (continue)", 'continue' in src)

# ── 3. Category auto-discovery ───────────────────────────────
print("\n=== Category auto-discovery ===")
check("_discover_categories method", "async def _discover_categories" in src)
check("Visits /c/groceries/2", "/c/groceries/2" in src)
check("Falls back to hardcoded on failure", "using hardcoded fallback" in src)
check("_CATEGORY_KEYWORDS for matching", "_CATEGORY_KEYWORDS" in src)

# ── 4. Firefox browser (not Chromium) ────────────────────────
print("\n=== Firefox browser ===")
check("Uses Firefox", "firefox.launch" in src)

# ── 5. DOM extraction as supplement ──────────────────────────
print("\n=== DOM extraction ===")
check("_extract_products_from_dom exists", "_extract_products_from_dom" in src)
check("Only on grocery pages", '"/groceries" not in url' in src)

# ── 6. Subcategory discovery ────────────────────────────────
print("\n=== Subcategory discovery ===")
check("Discovers subcategory links", 'a[href*="/c/groceries"]' in src)
check("Adds to queue", "queue.append" in src)

# ── 7. Parse trex results ────────────────────────────────────
print("\n=== _parse_trex_results ===")
check("Parses buybox_mrp", "buybox_mrp" in src)
check("Splits pipe-separated format", 'buybox[0].split("|")' in src)
check("Extracts mrp at index 4", "parts[4]" in src)
check("Extracts price at index 5", "parts[5]" in src)
check("Skips price <= 0", "price <= 0" in src)

# ── 8. Dedup ────────────────────────────────────────────────
print("\n=== Deduplication ===")
check("Uses _seen_ids for dedup", "_seen_ids" in src)

print(f"\n{'='*40}")
if failures:
    print(f"FAILURES: {len(failures)}")
    for f in failures:
        print(f)
    sys.exit(1)
else:
    print("ALL TESTS PASSED")
