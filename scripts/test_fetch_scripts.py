"""
Structural tests for fetch_anakin_blinkit.py, fetch_anakin_jiomart.py, fetch_ean_map.py
These verify code structure without hitting APIs.
"""
import ast
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
failures = []


def check(label, actual, expected=True):
    if actual == expected:
        print(f"  PASS: {label}")
    else:
        msg = f"  FAIL: {label} -> got {actual!r}, expected {expected!r}"
        print(msg)
        failures.append(msg)


def get_source(name):
    return (SCRIPTS / name).read_text()


def has_pattern(src, pattern):
    return pattern in src


# ────────────────────────────────────────────────────────────────
print("=== fetch_anakin_blinkit.py ===")
src_bl = get_source("fetch_anakin_blinkit.py")
tree_bl = ast.parse(src_bl)

# 1. API key validation at startup (in __main__ block)
check("API key validation at startup", 'if not KEY:' in src_bl)

# 2. try/except around urlopen with timeout=30
check("try/except around urlopen", 'try:' in src_bl and 'urlopen' in src_bl)
check("timeout=30 in urlopen", 'timeout=30' in src_bl)
check("catches URLError", 'URLError' in src_bl)
check("catches HTTPError", 'HTTPError' in src_bl)

# 3. Empty results guard (rows[0][0] check)
check("Empty results guard rows[0][0]", 'rows[0][0]' in src_bl)
check("Exits on no data", 'sys.exit(1)' in src_bl)

# ────────────────────────────────────────────────────────────────
print("\n=== fetch_anakin_jiomart.py ===")
src_jm = get_source("fetch_anakin_jiomart.py")

check("API key validation at startup", 'if not KEY:' in src_jm)
check("try/except around urlopen", 'try:' in src_jm and 'urlopen' in src_jm)
check("timeout=30 in urlopen", 'timeout=30' in src_jm)
check("catches URLError", 'URLError' in src_jm)
check("catches HTTPError", 'HTTPError' in src_jm)
check("Empty results guard rows[0][0]", 'rows[0][0]' in src_jm)
check("Exits on no data", 'sys.exit(1)' in src_jm)

# ────────────────────────────────────────────────────────────────
print("\n=== fetch_ean_map.py ===")
src_ean = get_source("fetch_ean_map.py")

# 1. Fetches from smpcm_product table (578)
check("source-table 578 (smpcm_product)", '"source-table": 578' in src_ean)

# 2. Filters real EANs (8+ digits, not same as item_code)
check("EAN filter: 8+ digits", 'len(bc_str) >= 8' in src_ean)
check("EAN filter: not same as item_code", 'bc_str != ic_str' in src_ean)
check("EAN filter: digits only", 'bc_str.isdigit()' in src_ean)

# 3. Output format (data/ean_map.json)
check("Output to ean_map.json", 'ean_map.json' in src_ean)

# 4. API key validation at startup
check("API key validation at startup", 'if not KEY:' in src_ean)

# 5. try/except around urlopen
check("try/except around urlopen", 'try:' in src_ean and 'urlopen' in src_ean)

# 6. timeout set
check("timeout set", 'timeout=60' in src_ean)

# ────────────────────────────────────────────────────────────────
print(f"\n{'='*40}")
if failures:
    print(f"FAILURES: {len(failures)}")
    for f in failures:
        print(f)
    sys.exit(1)
else:
    print("ALL STRUCTURAL TESTS PASSED")
