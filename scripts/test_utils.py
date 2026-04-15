"""
Unit tests for scripts/utils.py
Run: python scripts/test_utils.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from utils import clean_str, parse_num, parse_unit, BRAND_ALIASES, normalize_brand

failures = []

def check(label, actual, expected):
    if actual == expected:
        print(f"  PASS: {label}")
    else:
        msg = f"  FAIL: {label} -> got {actual!r}, expected {expected!r}"
        print(msg)
        failures.append(msg)


print("=== clean_str ===")
check('clean_str("N/A")', clean_str("N/A"), "")
check('clean_str("NA")', clean_str("NA"), "")
check('clean_str("  null ")', clean_str("  null "), "")
check('clean_str("nan")', clean_str("nan"), "")
check('clean_str("None")', clean_str("None"), "")
check('clean_str(None)', clean_str(None), "")
check('clean_str("")', clean_str(""), "")
check('clean_str("n/a")', clean_str("n/a"), "")
check('clean_str("hello")', clean_str("hello"), "hello")

print("\n=== parse_num ===")
check('parse_num("NA")', parse_num("NA"), None)
check('parse_num("inf")', parse_num("inf"), None)
check('parse_num("-5")', parse_num("-5"), None)
check('parse_num("₹ 1,234.50")', parse_num("₹ 1,234.50"), 1234.5)
check('parse_num(None)', parse_num(None), None)
check('parse_num("nan")', parse_num("nan"), None)
check('parse_num("null")', parse_num("null"), None)
check('parse_num("")', parse_num(""), None)
check('parse_num("0")', parse_num("0"), 0.0)
check('parse_num("99")', parse_num("99"), 99.0)
check('parse_num("Rs. 500/-")', parse_num("Rs. 500/-"), 500.0)

print("\n=== parse_unit ===")
check('parse_unit("2 x 100ml")', parse_unit("2 x 100ml"), (200.0, "ml"))
check('parse_unit("1/2 kg")', parse_unit("1/2 kg"), (0.5, "kg"))
check('parse_unit("500gm")', parse_unit("500gm"), (500.0, "g"))
check('parse_unit("10 N")', parse_unit("10 N"), (10.0, "pc"))
check('parse_unit("250 g")', parse_unit("250 g"), (250.0, "g"))
check('parse_unit("1 ltr")', parse_unit("1 ltr"), (1.0, "l"))

print("\n=== BRAND_ALIASES ===")
check('BRAND_ALIASES has entries', len(BRAND_ALIASES) > 0, True)
print(f"  Aliases: {BRAND_ALIASES}")

print("\n=== normalize_brand ===")
check('normalize_brand("CDM")', normalize_brand("CDM"), "cadbury dairy milk")
check('normalize_brand("Maggie")', normalize_brand("Maggie"), "maggi")
check('normalize_brand("Tata Namak")', normalize_brand("Tata Namak"), "tata salt")
check('normalize_brand("")', normalize_brand(""), "")
check('normalize_brand("Some Brand")', normalize_brand("Some Brand"), "some brand")

print(f"\n{'='*40}")
if failures:
    print(f"FAILURES: {len(failures)}")
    for f in failures:
        print(f)
    sys.exit(1)
else:
    print("ALL TESTS PASSED")
