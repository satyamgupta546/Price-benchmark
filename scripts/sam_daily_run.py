"""
SAM Daily Run — THE master script. Cron this at 10:30 AM IST.

What it does:
  1. Fetch AM product master (smpcm_product) + latest MRP (model 1808)
  2. Fetch EAN map
  3. Fetch Anakin data (all cities, both platforms)
  4. Scrape Blinkit + Jiomart in PARALLEL (all stages per city)
  5. Compute match status (COMPLETE/SEMI COMPLETE/PARTIAL/NA)
  6. Generate Excel per city → /Users/satyam/Desktop/price csv/
  7. Push to BigQuery (sam_price_live = replace, sam_price_history = append)

Usage:
    export METABASE_API_KEY=...
    python3 scripts/sam_daily_run.py              # all cities
    python3 scripts/sam_daily_run.py 834002       # single city
    python3 scripts/sam_daily_run.py --no-scrape  # skip scrape, just regenerate Excel + push
"""
import csv
import json
import os
import re
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

sys.stdout.reconfigure(line_buffering=True)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
VENV_PYTHON = str(PROJECT_ROOT / "backend" / "venv" / "bin" / "python")
SCRIPTS = PROJECT_ROOT / "scripts"
DATA = PROJECT_ROOT / "data"
OUTPUT_DIR = Path(os.environ.get("SAM_OUTPUT_DIR", str(PROJECT_ROOT / "output")))
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

VALID_MASTER_CATEGORIES = {"STPLS", "FMCG", "FMCGF", "FMCGNF", "GM"}
CITIES = {
    "834002": "Ranchi", "712232": "Kolkata", "492001": "Raipur",
    "825301": "Hazaribagh", "495001": "Bilaspur", "831001": "Jamshedpur",
}
WAREHOUSE_MAP = {
    "834002": "WRHS_1", "825301": "WRHS_1", "831001": "WRHS_1",  # Jharkhand
    "492001": "WRHS_2", "495001": "WRHS_2",                       # Chhattisgarh
    "712232": "WRHS_10",                                           # Kolkata
}
DATE = datetime.now().strftime("%Y-%m-%d")
NOW = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

URL_DATABASE_PATH = DATA / "mappings" / "url_database.json"

METABASE_API = "https://mirror.apnamart.in/api"
METABASE_KEY = os.environ.get("METABASE_API_KEY", "")

BQ_PROJECT = "apna-mart-data"
BQ_DATASET = "googlesheet"
BQ_LIVE_TABLE = f"{BQ_PROJECT}:{BQ_DATASET}.sam_price_live"
BQ_HISTORY_TABLE = f"{BQ_PROJECT}:{BQ_DATASET}.sam_price_history"


def run(script, args=[], use_venv=False):
    python = VENV_PYTHON if use_venv else sys.executable
    cmd = [python, str(SCRIPTS / script)] + args
    print(f"  ▶ {script} {' '.join(args)}", flush=True)
    r = subprocess.run(cmd, cwd=str(PROJECT_ROOT), capture_output=True, text=True)
    if r.returncode != 0:
        print(f"    ⚠️ {script} failed (exit {r.returncode}): {(r.stderr or '')[:200]}", flush=True)


def metabase_query(payload):
    import urllib.request
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        f"{METABASE_API}/dataset", data=data,
        headers={"x-api-key": METABASE_KEY, "Content-Type": "application/json"},
    )
    resp = urllib.request.urlopen(req, timeout=60)
    return json.loads(resp.read())


# ── URL Database (fallback when Anakin is removed) ──

_url_db_cache = None
_url_db_lock = threading.Lock()


def load_url_database() -> dict:
    """Load url_database.json. Returns dict keyed by '{platform}_{pincode}_{item_code}'."""
    global _url_db_cache
    if _url_db_cache is not None:
        return _url_db_cache
    with _url_db_lock:
        if _url_db_cache is not None:
            return _url_db_cache
        if URL_DATABASE_PATH.exists():
            try:
                _url_db_cache = json.load(open(URL_DATABASE_PATH))
                print(f"  📂 URL database: {len(_url_db_cache)} entries", flush=True)
            except Exception as e:
                print(f"  ⚠️ URL database load error: {e}", flush=True)
                _url_db_cache = {}
        else:
            _url_db_cache = {}
    return _url_db_cache


def save_urls_to_database(pincode):
    """Save new URLs from PDP results to url_database.json. Only adds, never removes."""
    url_db = {}
    if URL_DATABASE_PATH.exists():
        try:
            url_db = json.load(open(URL_DATABASE_PATH))
        except Exception:
            url_db = {}

    added = 0
    for platform in ["blinkit", "jiomart"]:
        # Find latest PDP file for this pincode (any date)
        files = sorted([f for f in DATA.glob(f"sam/{platform}_pdp_{pincode}_*.json")
                        if "partial" not in f.name])
        if not files:
            continue
        try:
            data = json.load(open(files[-1]))
        except Exception:
            continue

        for p in data.get("products", []):
            ic = p.get("item_code")
            if not ic:
                continue
            url_key = f"{platform}_{pincode}_{ic}"
            product_url = p.get(f"{platform}_product_url")
            product_id = p.get(f"{platform}_product_id")
            if not product_url:
                continue

            # Only add if key is new or URL has changed
            existing = url_db.get(url_key)
            if existing and existing.get("product_url") == product_url:
                continue

            url_db[url_key] = {
                "item_code": ic,
                "platform": platform,
                "pincode": pincode,
                "product_id": product_id,
                "product_url": product_url,
                "platform_item_name": p.get("sam_product_name") or "",
                "apna_name": "",
                "brand": "",
                "updated_at": NOW,
            }
            added += 1

    if added > 0:
        URL_DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(URL_DATABASE_PATH, "w") as f:
            json.dump(url_db, f, indent=2)
        # Invalidate cache so next load picks up new data
        global _url_db_cache
        _url_db_cache = None
        print(f"  💾 URL database: +{added} URLs for {pincode} (total {len(url_db)})", flush=True)


# ── Data Validation ──

def validate_data(rows, pincodes):
    """Validate data before BQ push. Returns (ok: bool, messages: list[str])."""
    errors = []

    # Total rows > 0
    if len(rows) == 0:
        errors.append("FAIL: 0 total rows")
        return False, errors

    # Each pincode has at least 100 rows (pincode is index 3 in row)
    pincode_counts = {}
    for row in rows:
        pin = str(row[3])
        pincode_counts[pin] = pincode_counts.get(pin, 0) + 1
    for pin in pincodes:
        count = pincode_counts.get(pin, 0)
        if count < 100:
            errors.append(f"FAIL: pincode {pin} has only {count} rows (need >= 100)")

    # No row has item_code = None (item_code is index 4)
    none_ic = sum(1 for row in rows if row[4] is None)
    if none_ic > 0:
        errors.append(f"FAIL: {none_ic} rows have item_code = None")

    # blinkit_sp (index 18) and jio_sp (index 25) in range 0-50000 when not None
    for idx, label in [(18, "blinkit_sp"), (25, "jio_sp")]:
        bad = 0
        for row in rows:
            val = row[idx]
            if val is not None:
                try:
                    v = float(val)
                    if v < 0 or v > 50000:
                        bad += 1
                except (ValueError, TypeError):
                    bad += 1
        if bad > 0:
            errors.append(f"FAIL: {bad} rows have {label} outside 0-50000 range")

    # At least 10% of rows have blinkit_sp (not all blank)
    blinkit_filled = sum(1 for row in rows if row[18] is not None)
    pct = blinkit_filled / len(rows) * 100 if rows else 0
    if pct < 10:
        errors.append(f"FAIL: only {pct:.1f}% of rows have blinkit_sp ({blinkit_filled}/{len(rows)})")

    ok = len(errors) == 0
    return ok, errors


# ── Old File Cleanup ──

def cleanup_old_files():
    """Delete files older than 7 days from data/sam/, data/comparisons/, data/anakin/.
    Keeps data/mappings/ and data/ean_map.json. Only deletes if >20 files in directory."""
    from datetime import timedelta

    cutoff = datetime.now() - timedelta(days=7)
    dirs_to_clean = [DATA / "sam", DATA / "comparisons", DATA / "anakin"]
    total_deleted = 0

    for dir_path in dirs_to_clean:
        if not dir_path.exists():
            continue
        files = [f for f in dir_path.iterdir() if f.is_file()]
        if len(files) <= 20:
            continue
        deleted = 0
        for f in files:
            try:
                mtime = datetime.fromtimestamp(f.stat().st_mtime)
                if mtime < cutoff:
                    f.unlink()
                    deleted += 1
            except Exception:
                pass
        if deleted > 0:
            print(f"  🧹 {dir_path.name}/: deleted {deleted} old files", flush=True)
        total_deleted += deleted

    if total_deleted > 0:
        print(f"  🧹 Total cleanup: {total_deleted} files removed", flush=True)
    else:
        print(f"  🧹 Cleanup: nothing to remove", flush=True)


# ── Step 1: Fetch AM product master + MRP ──

def fetch_am_master(item_codes: list[str]) -> dict:
    """Fetch product data from smpcm_product for given item_codes."""
    print("📥 Fetching AM product master...", flush=True)
    am_map = {}
    batch_size = 100
    for i in range(0, len(item_codes), batch_size):
        batch = [int(ic) for ic in item_codes[i:i+batch_size] if ic.isdigit()]
        if not batch:
            continue
        try:
            r = metabase_query({
                "database": 5, "type": "query",
                "query": {
                    "source-table": 578,
                    "fields": [["field", 7191], ["field", 7118], ["field", 8935], ["field", 7113],
                               ["field", 7133], ["field", 7131], ["field", 7176], ["field", 7193],
                               ["field", 7158], ["field", 7149]],
                    "filter": ["=", ["field", 7191]] + batch,
                    "limit": 200,
                }
            })
            cols = ["item_code", "display_name", "master_category", "brand", "marketed_by",
                    "product_type", "unit", "unit_value", "mrp", "main_image"]
            for row in r.get("data", {}).get("rows", []):
                rec = dict(zip(cols, row))
                ic = str(rec.get("item_code", "")).strip()
                if ic:
                    am_map[ic] = rec
        except Exception as e:
            print(f"    AM batch error: {e}", flush=True)

    print(f"  ✅ AM master: {len(am_map)} products", flush=True)
    with open(DATA / "am_product_master.json", "w") as f:
        json.dump(am_map, f, default=str)
    return am_map


def fetch_latest_mrp(warehouse_id: str) -> dict:
    """Fetch latest inward MRP from model 1808 for a warehouse."""
    print(f"📥 Fetching latest MRP ({warehouse_id})...", flush=True)
    mrp_rows = []
    page = 1
    while True:
        try:
            r = metabase_query({
                "database": 3, "type": "query",
                "query": {
                    "source-table": "card__1808",
                    "filter": ["=", ["field", "warehouse_id", {"base-type": "type/Text"}], warehouse_id],
                    "limit": 2000, "offset": (page - 1) * 2000,
                }
            })
            rows = r.get("data", {}).get("rows", [])
            if not rows:
                break
            mrp_rows.extend(rows)
            if len(rows) < 2000:
                break
            page += 1
            if page > 15:
                break
        except Exception as e:
            print(f"    MRP fetch error: {e}", flush=True)
            break

    mrp_cols = ["warehouse_id", "grn_date", "pricing_approv_date", "product_id",
                "item_code", "cost", "mrp", "display_name", "master_category"]
    mrp_map = {}
    for row in mrp_rows:
        rec = dict(zip(mrp_cols, row))
        ic = str(rec.get("item_code", "")).strip()
        if ic:
            mrp_map[ic] = rec

    print(f"  ✅ MRP: {len(mrp_map)} items for {warehouse_id}", flush=True)
    safe_name = warehouse_id.lower().replace(" ", "_")
    with open(DATA / f"latest_mrp_{safe_name}.json", "w") as f:
        json.dump(mrp_map, f, default=str)
    return mrp_map


# ── Step 2: Scrape one city ──

def scrape_city(pincode, city):
    """Run full pipeline for one city — both platforms."""
    print(f"\n{'─' * 60}", flush=True)
    print(f"  {city} ({pincode})", flush=True)
    print(f"{'─' * 60}", flush=True)

    # Fetch Anakin
    run("fetch_anakin_blinkit.py", [pincode])
    run("fetch_anakin_jiomart.py", [pincode])

    # Platform availability per city
    SKIP_PLATFORM = {
        "825301": {"jiomart"},     # Hazaribagh — no Jiomart
    }

    def run_platform(platform):
        if platform in SKIP_PLATFORM.get(pincode, set()):
            print(f"  ⏭️  {platform} not available in {city}", flush=True)
            return
        if platform == "dmart":
            # DMart: Pure API scraper — no Playwright, no PDP stages
            # Pincodes where DMart Ready is available (update when new cities added)
            DMART_PINCODES = {"492001"}  # Raipur only
            if pincode not in DMART_PINCODES:
                print(f"  ⏭️  DMart not available for {city} ({pincode})", flush=True)
                return
            print(f"\n⚙️  {city} — dmart pipeline (API)", flush=True)
            run("scrape_dmart.py", [pincode])
            print(f"  ✅ {city} dmart complete", flush=True)
            return

        print(f"\n⚙️  {city} — {platform} pipeline", flush=True)
        if platform == "blinkit":
            run("scrape_blinkit_pdps.py", [pincode, "4"], use_venv=True)
            partial = DATA / "sam" / f"blinkit_pdp_{pincode}_latest_partial.json"
            if partial.exists():
                partial.unlink()
            run("compare_pdp.py", [pincode])
        elif platform == "jiomart":
            run("scrape_jiomart_pdps.py", [pincode, "2"], use_venv=True)
            partial = DATA / "sam" / f"jiomart_pdp_{pincode}_latest_partial.json"
            if partial.exists():
                partial.unlink()
            run("compare_pdp_jiomart.py", [pincode])

        run("cascade_match.py", [pincode, platform])
        run("stage3_match.py", [pincode, platform])

        if platform == "jiomart":
            run("jiomart_search_match.py", [pincode], use_venv=True)

        run("stage4_image_match.py", [pincode, platform])
        run("stage5_barcode_match.py", [pincode, platform])
        print(f"  ✅ {city} {platform} complete", flush=True)

    # Run ALL platforms in PARALLEL (Blinkit + Jiomart + DMart)
    threads = [
        threading.Thread(target=run_platform, args=("blinkit",)),
        threading.Thread(target=run_platform, args=("jiomart",)),
        threading.Thread(target=run_platform, args=("dmart",)),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # Save new URLs to database after scrape
    save_urls_to_database(pincode)


# ── Step 3: Compute status + generate output ──

def parse_wt(name):
    if not name:
        return None, None
    m = re.search(r"(\d+\.?\d*)\s*(g|gm|gms|kg|kgs|ml|mls|l|ltr|ltrs|pc|pcs|piece|pieces|unit|units|n|nos)\b", name.lower())
    if m:
        v = float(m.group(1))
        u = m.group(2)
        if u in ("gm", "gms"): u = "g"
        elif u in ("kgs",): u = "kg"
        elif u in ("mls",): u = "ml"
        elif u in ("ltrs",): u = "ltr"
        elif u in ("pcs", "piece", "pieces", "units", "n", "nos"): u = "pc"
        return v, u
    return None, None


def unit_type_group(u):
    """Return unit category: 'weight', 'volume', 'count', or None."""
    if not u: return None
    u = str(u).lower().strip()
    if u in ("g", "gm", "gms", "kg", "kgs"): return "weight"
    if u in ("ml", "mls", "l", "ltr", "ltrs"): return "volume"
    if u in ("pc", "pcs", "piece", "pieces", "unit", "units", "n", "nos"): return "count"
    return None


def compute_status(am, am_mrp, sam_sp, sam_mrp, sam_name, anakin_rec, platform):
    if sam_sp is None:
        return "NA"

    am_name_lower = (am.get("display_name") or "").lower()
    am_unit = (am.get("unit") or "").lower().strip()
    am_uv = am.get("unit_value")
    am_pt = (am.get("product_type") or "").upper()

    sam_wt, sam_wu = parse_wt(sam_name)

    # ── SEMI COMPLETE: Loose / ASM items in STPLS ──
    # Criteria: product is loose/ASM + unit TYPE matches (kg↔g = weight, ml↔l = volume)
    is_loose_asm = (
        ("loose" in am_name_lower or "asm" in am_name_lower or am_pt in ("LOOSE", "ASM"))
        and am.get("master_category") == "STPLS"
    )
    if is_loose_asm:
        am_ug = unit_type_group(am_unit)
        sam_ug = unit_type_group(sam_wu)
        # Unit type must match — if either side unknown, give benefit of doubt
        if am_ug and sam_ug and am_ug != sam_ug:
            return "PARTIAL MATCH"  # e.g. AM=weight, SAM=volume → wrong product
        return "SEMI COMPLETE MATCH"

    # ── Unit value match (±10%) ──
    # None = unknown (one or both sides can't be parsed → don't assume match or mismatch)
    # True = confirmed match, False = confirmed mismatch
    unit_match = None
    if am_uv and sam_wt and am_unit and sam_wu:
        try:
            av = float(am_uv)
            sv = sam_wt
            if am_unit in ("kg", "kgs") and sam_wu == "g": av *= 1000
            elif am_unit in ("g", "gm") and sam_wu == "kg": sv *= 1000
            elif am_unit in ("l", "ltr") and sam_wu == "ml": av *= 1000
            elif am_unit == "ml" and sam_wu in ("l", "ltr"): sv *= 1000
            if av > 0 and sv > 0:
                unit_match = 0.9 <= sv / av <= 1.1
        except Exception:
            pass

    # Confirmed unit mismatch → can never be COMPLETE (don't let sp_match override this)
    if unit_match is False:
        return "PARTIAL MATCH"

    # ── MRP match ──
    mrp5 = mrp10 = False
    if am_mrp and sam_mrp:
        try:
            pct = abs(float(am_mrp) - float(sam_mrp)) / max(float(am_mrp), 0.01) * 100
            mrp5 = pct <= 5
            mrp10 = pct <= 10
        except Exception:
            pass
    elif not am_mrp:
        mrp5 = mrp10 = True  # No AM MRP to compare against — don't penalize

    # ── SP match vs Anakin (only for Blinkit/Jiomart, not DMart) ──
    sp_key = "Blinkit_Selling_Price" if platform == "blinkit" else "Jiomart_Selling_Price"
    ana_sp = anakin_rec.get(sp_key)
    sp_match = False
    if ana_sp and str(ana_sp).strip().lower() not in ("na", "nan", "null", "none", "") and sam_sp:
        try:
            asp = float(str(ana_sp).replace(",", ""))
            if asp > 0:
                sp_match = abs(sam_sp - asp) / asp * 100 <= 5
        except Exception:
            pass

    # ── COMPLETE MATCH (unit_match is True or None at this point) ──
    # (1) Unit confirmed match + MRP ±5%
    # (2) Unit confirmed match + MRP ±10%
    # (3) SP matches Anakin ±5% (only when unit is not a confirmed mismatch — already guarded above)
    if (unit_match and mrp5) or (unit_match and mrp10) or sp_match:
        return "COMPLETE MATCH"
    return "PARTIAL MATCH"


def load_pdp(platform, pincode):
    files = sorted([f for f in DATA.glob(f"sam/{platform}_pdp_{pincode}_{DATE}*.json") if "partial" not in f.name])
    if not files:
        return {}
    d = json.load(open(files[-1]))
    return {p["item_code"]: p for p in d["products"]
            if p.get("item_code") and p.get("status") == "ok"
            and not (p.get("sam_product_name") or "").startswith("projects/")}


def load_cascade(platform, pincode):
    cm = {}
    patterns = [f"{platform}_cascade_{pincode}_{DATE}*.json", f"{platform}_stage3_{pincode}_{DATE}*.json"]
    if platform == "jiomart":
        patterns.append(f"jiomart_search_match_{pincode}_{DATE}*.json")
    for pat in patterns:
        files = sorted(DATA.glob(f"comparisons/{pat}"))
        if files:
            for m in json.load(open(files[-1])).get("new_mappings", []):
                ic = m.get("item_code")
                if ic and m.get("sam_price") and ic not in cm:
                    cm[ic] = m
    return cm


def generate_city_data(pincode, city, am_map, mrp_map):
    """Generate rows for one city. Returns list of CSV rows."""
    blinkit_anakin = {}
    jiomart_anakin = {}
    for f in sorted(DATA.glob(f"anakin/blinkit_{pincode}_*.json")):
        blinkit_anakin = {r["Item_Code"]: r for r in json.load(open(f))["records"] if r.get("Item_Code")}
    for f in sorted(DATA.glob(f"anakin/jiomart_{pincode}_*.json")):
        jiomart_anakin = {r["Item_Code"]: r for r in json.load(open(f))["records"] if r.get("Item_Code")}

    # Load URL database as fallback for missing Anakin URLs
    url_db = load_url_database()

    b_pdp = load_pdp("blinkit", pincode)
    j_pdp = load_pdp("jiomart", pincode)
    b_cascade = load_cascade("blinkit", pincode)
    j_cascade = load_cascade("jiomart", pincode)

    # Load DMart data (API-based, no PDP/cascade stages)
    dmart_map = {}
    dmart_files = sorted([f for f in DATA.glob(f"sam/dmart_{pincode}_{DATE}*.json")])
    if dmart_files:
        d = json.load(open(dmart_files[-1]))
        for p in d.get("products", []):
            # Match by brand + name fuzzy (DMart doesn't use Anakin item_codes)
            dmart_map[p.get("product_name", "")] = p

    rows = []
    for ic in sorted(am_map.keys(), key=lambda x: int(x) if x.isdigit() else 0):
        am = am_map.get(ic, {})
        if am.get("master_category") not in VALID_MASTER_CATEGORIES:
            continue
        mrp_rec = mrp_map.get(ic, {})
        am_mrp = mrp_rec.get("mrp") if mrp_rec else am.get("mrp")
        b_ana = blinkit_anakin.get(ic, {})
        j_ana = jiomart_anakin.get(ic, {})

        def get_sam(pdp_m, cas_m, ana_r, url_k, platform):
            sp = mrp = name = stock = unit = None
            url = ana_r.get(url_k)
            if url and str(url).strip().lower() in ("na", "nan", "null", "none", ""):
                url = None
            # Fallback to URL database if Anakin URL is missing
            if not url:
                db_key = f"{platform}_{pincode}_{ic}"
                db_entry = url_db.get(db_key)
                if db_entry:
                    url = db_entry.get("product_url")
            if ic in pdp_m:
                p = pdp_m[ic]
                name = p.get("sam_product_name")
                sp = p.get("sam_selling_price")
                mrp = p.get("sam_mrp")
                stock = "available" if p.get("sam_in_stock") else "out_of_stock"
                unit = p.get("sam_unit")
            elif ic in cas_m:
                m = cas_m[ic]
                name = m.get("sam_product_name")
                sp = m.get("sam_price")
                mrp = m.get("sam_mrp")
                stock = "available"
                unit = m.get("sam_unit")
            if mrp is None and sp is not None:
                mrp = sp
            return url, name, unit, mrp, sp, stock

        b_url, b_name, b_unit, b_mrp, b_sp, b_stock = get_sam(b_pdp, b_cascade, b_ana, "Blinkit_Product_Url", "blinkit")
        b_status = compute_status(am, am_mrp, b_sp, b_mrp, b_name, b_ana, "blinkit")

        j_url, j_name, j_unit, j_mrp, j_sp, j_stock = get_sam(j_pdp, j_cascade, j_ana, "Jiomart_Product_Url", "jiomart")
        j_status = compute_status(am, am_mrp, j_sp, j_mrp, j_name, j_ana, "jiomart")

        # DMart: match by product name similarity (no Anakin mapping exists)
        d_url = d_name = d_unit = d_mrp = d_sp = d_stock = d_status = None
        am_display = (am.get("display_name") or "").lower()
        if dmart_map and am_display:
            best_match = None
            best_score = 0
            from difflib import SequenceMatcher
            for dname, dp in dmart_map.items():
                score = SequenceMatcher(None, am_display, dname.lower()).ratio()
                if score > best_score:
                    best_score = score
                    best_match = dp
            if best_match and best_score >= 0.55:
                d_url = best_match.get("product_url")
                d_name = best_match.get("product_name")
                d_unit = best_match.get("unit")
                d_mrp = best_match.get("mrp")
                d_sp = best_match.get("price")
                d_stock = "available" if best_match.get("in_stock") else "out_of_stock"
                if d_mrp is None and d_sp is not None:
                    d_mrp = d_sp
                d_status = compute_status(am, am_mrp, d_sp, d_mrp, d_name, {}, "dmart")

        rows.append([
            DATE, NOW, city, pincode, int(ic) if ic.isdigit() else ic,
            am.get("display_name"), am.get("master_category"), am.get("brand"), am.get("marketed_by"),
            am.get("product_type"), am.get("unit"), am.get("unit_value"), am_mrp, am.get("main_image"),
            b_url, b_name, b_unit, b_mrp, b_sp, b_stock, b_status,
            j_url, j_name, j_unit, j_mrp, j_sp, j_stock, j_status,
            d_url, d_name, d_unit, d_mrp, d_sp, d_stock, d_status,
        ])
    return rows


def generate_excel(rows, city, pincode):
    """Generate Excel file for one city."""
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill
        from openpyxl.utils import get_column_letter
    except ImportError:
        print("  ⚠️ openpyxl not installed — skipping Excel", flush=True)
        return

    am_fill = PatternFill(start_color="FFDCE6F1", end_color="FFDCE6F1", fill_type="solid")
    blinkit_fill = PatternFill(start_color="FFE2EFDA", end_color="FFE2EFDA", fill_type="solid")
    jio_fill = PatternFill(start_color="FFFFF2CC", end_color="FFFFF2CC", fill_type="solid")

    wb = Workbook()
    ws = wb.active
    ws.title = f"SAM_{city}_{DATE}"

    headers = [
        "DATE", "TIME", "CITY", "PINCODE",
        "AM ITEM CODE", "AM ITEM NAME", "AM master cat", "AM BRAND", "AM MARKETED BY",
        "AM PRODUCT TYPE", "AM UNIT", "AM UNIT VALUE", "AM MRP", "IMAGE LINK",
        "BLINKIT URL", "BLINKIT ITEM NAME", "BLINKIT UNIT", "BLINKIT MRP", "BLINKIT SP",
        "BLINKIT IN STOCK REMARK", "BLINKIT STATUS",
        "JIO URL", "JIO ITEM NAME", "JIO UNIT", "JIO MRP", "JIO SP",
        "JIO IN STOCK REMARK", "JIO STATUS",
        "DMART URL", "DMART ITEM NAME", "DMART UNIT", "DMART MRP", "DMART SP",
        "DMART IN STOCK REMARK", "DMART STATUS",
    ]
    dmart_fill = PatternFill(start_color="FFE6CCFF", end_color="FFE6CCFF", fill_type="solid")
    for i, h in enumerate(headers, 1):
        c = ws.cell(row=1, column=i, value=h)
        c.font = Font(bold=True, size=10)
        if 1 <= i <= 14: c.fill = am_fill
        elif 15 <= i <= 21: c.fill = blinkit_fill
        elif 22 <= i <= 28: c.fill = jio_fill
        elif 29 <= i <= 35: c.fill = dmart_fill

    for r_idx, row_data in enumerate(rows, 2):
        for c_idx, val in enumerate(row_data, 1):
            ws.cell(row=r_idx, column=c_idx, value=val)

    widths = [10, 18, 10, 8, 10, 40, 8, 15, 20, 20, 5, 8, 8, 30, 35, 40, 10, 8, 8, 12, 20, 35, 40, 10, 8, 8, 12, 20, 35, 40, 10, 8, 8, 12, 20]
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = "E2"

    out_path = OUTPUT_DIR / f"SAM_{city}_{pincode}_{DATE}.xlsx"
    wb.save(out_path)
    print(f"  📊 {out_path.name}", flush=True)


def push_to_bigquery(csv_path, pincodes):
    """Push CSV to both BQ tables using DELETE+INSERT to avoid wiping other cities."""
    print("\n📤 Pushing to BigQuery...", flush=True)
    bq_live_sql = f"{BQ_PROJECT}.{BQ_DATASET}.sam_price_live"
    bq_hist_sql = f"{BQ_PROJECT}.{BQ_DATASET}.sam_price_history"

    # Live table: delete rows for pincodes being pushed, then append
    for pin in pincodes:
        del_r = subprocess.run(
            ["bq", "query", "--use_legacy_sql=false",
             f"DELETE FROM `{bq_live_sql}` WHERE pincode = '{pin}'"],
            capture_output=True, text=True,
        )
        if del_r.returncode == 0:
            print(f"  🗑️  sam_price_live: deleted pincode {pin}", flush=True)
        else:
            print(f"  ⚠️  sam_price_live delete {pin}: {del_r.stderr[:200]}", flush=True)

    r1 = subprocess.run(
        ["bq", "load", "--source_format=CSV", BQ_LIVE_TABLE, str(csv_path)],
        capture_output=True, text=True,
    )
    if r1.returncode == 0:
        print(f"  ✅ sam_price_live (loaded)", flush=True)
    else:
        print(f"  ❌ sam_price_live: {r1.stderr[:200]}", flush=True)

    # History table: delete existing rows for same date+pincodes to prevent duplicates on re-run
    pin_list = ", ".join(f"'{p}'" for p in pincodes)
    del_hist = subprocess.run(
        ["bq", "query", "--use_legacy_sql=false",
         f"DELETE FROM `{bq_hist_sql}` WHERE date = '{DATE}' AND pincode IN ({pin_list})"],
        capture_output=True, text=True,
    )
    if del_hist.returncode == 0:
        print(f"  🗑️  sam_price_history: deduped {DATE} for {pin_list}", flush=True)
    else:
        print(f"  ⚠️  sam_price_history dedup: {del_hist.stderr[:200]}", flush=True)

    r2 = subprocess.run(
        ["bq", "load", "--source_format=CSV", BQ_HISTORY_TABLE, str(csv_path)],
        capture_output=True, text=True,
    )
    if r2.returncode == 0:
        print(f"  ✅ sam_price_history (appended)", flush=True)
    else:
        print(f"  ❌ sam_price_history: {r2.stderr[:200]}", flush=True)


# ── Main ──

def main():
    pincode_arg = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("--") else "all"
    skip_scrape = "--no-scrape" in sys.argv

    pincodes = CITIES if pincode_arg == "all" else {pincode_arg: CITIES.get(pincode_arg, pincode_arg)}

    print(f"{'═' * 60}")
    print(f"  SAM DAILY RUN — {DATE} {NOW}")
    print(f"  Cities: {', '.join(pincodes.values())}")
    print(f"  Scrape: {'skip' if skip_scrape else 'yes'}")
    print(f"{'═' * 60}")

    # Step 0: Switch gcloud account
    subprocess.run(["gcloud", "config", "set", "account", "satyam.gupta@apnamart.in"],
                    capture_output=True)

    # Step 1: Fetch EAN map
    print("\n📥 Fetching EAN map...", flush=True)
    run("fetch_ean_map.py")

    # Step 2: Scrape all cities (2 at a time to avoid RAM saturation)
    if not skip_scrape:
        from concurrent.futures import ThreadPoolExecutor, as_completed
        MAX_PARALLEL_CITIES = 2  # Each city runs 2 browsers × multiple tabs ≈ 8GB RAM
        pin_list = list(pincodes.items())
        for batch_start in range(0, len(pin_list), MAX_PARALLEL_CITIES):
            batch = pin_list[batch_start:batch_start + MAX_PARALLEL_CITIES]
            batch_names = ", ".join(city for _, city in batch)
            print(f"\n🚀 Batch {batch_start // MAX_PARALLEL_CITIES + 1}: {batch_names} ...", flush=True)
            with ThreadPoolExecutor(max_workers=len(batch)) as executor:
                futures = {executor.submit(scrape_city, pin, city): (pin, city) for pin, city in batch}
                for future in as_completed(futures):
                    pin, city = futures[future]
                    try:
                        future.result()
                        print(f"  ✅ {city} complete", flush=True)
                    except Exception as e:
                        print(f"  ❌ {city} failed: {e}", flush=True)

    # Step 3: Collect all item_codes from Anakin files
    all_item_codes = set()
    for pin in pincodes:
        for platform in ["blinkit", "jiomart"]:
            files = sorted(DATA.glob(f"anakin/{platform}_{pin}_*.json"))
            if files:
                d = json.load(open(files[-1]))
                for r in d.get("records", []):
                    ic = str(r.get("Item_Code", "")).strip()
                    if ic:
                        all_item_codes.add(ic)

    # Step 4: Fetch AM master + MRP
    am_map = fetch_am_master(list(all_item_codes))

    # Fetch MRP per warehouse (deduplicate warehouses)
    mrp_maps = {}
    for pin in pincodes:
        wh = WAREHOUSE_MAP.get(pin, "WRHS_1")
        if wh not in mrp_maps:
            mrp_maps[wh] = fetch_latest_mrp(wh)

    # Step 5: Generate data + Excel + CSV for BQ
    all_rows = []
    for pin, city in pincodes.items():
        wh = WAREHOUSE_MAP.get(pin, "WRHS_1")
        mrp_map = mrp_maps.get(wh, {})
        city_rows = generate_city_data(pin, city, am_map, mrp_map)
        all_rows.extend(city_rows)
        generate_excel(city_rows, city, pin)
        print(f"  ✅ {city}: {len(city_rows)} rows", flush=True)

    # Step 6: Write CSV + push to BQ
    csv_path = DATA / "bq_upload_temp.csv"
    with open(csv_path, "w", newline="") as f:
        w = csv.writer(f)
        for row in all_rows:
            w.writerow(row)
    print(f"\n📄 CSV: {len(all_rows)} total rows", flush=True)

    # Step 7: Validate data before BQ push
    valid, messages = validate_data(all_rows, list(pincodes.keys()))
    if not valid:
        print("\n⚠️  Data validation warnings:", flush=True)
        for msg in messages:
            print(f"    {msg}", flush=True)
        print("  (pushing anyway — these are warnings, not blockers)", flush=True)
    else:
        print("\n✅ Data validation passed", flush=True)

    push_to_bigquery(csv_path, list(pincodes.keys()))

    # Step 8: Cleanup old files
    cleanup_old_files()

    print(f"\n{'═' * 60}")
    print(f"  DONE! {len(pincodes)} cities, {len(all_rows)} rows")
    print(f"  Excel: {OUTPUT_DIR}")
    print(f"  BigQuery: sam_price_live + sam_price_history")
    print(f"{'═' * 60}")


if __name__ == "__main__":
    main()
