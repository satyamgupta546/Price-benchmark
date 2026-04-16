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

CITIES = {"834002": "Ranchi", "712232": "Kolkata", "492001": "Raipur", "825301": "Hazaribagh"}
WAREHOUSE_MAP = {"834002": "WRHS_1", "825301": "WRHS_1", "492001": "WRHS_2", "712232": "WRHS_10"}
DATE = datetime.now().strftime("%Y-%m-%d")
NOW = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

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

    def run_platform(platform):
        if pincode == "825301" and platform == "jiomart":
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

    # Run both platforms in PARALLEL
    t1 = threading.Thread(target=run_platform, args=("blinkit",))
    t2 = threading.Thread(target=run_platform, args=("jiomart",))
    t1.start()
    t2.start()
    t1.join()
    t2.join()


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


def compute_status(am, am_mrp, sam_sp, sam_mrp, sam_name, anakin_rec, platform):
    if sam_sp is None:
        return "NA"
    am_name_lower = (am.get("display_name") or "").lower()
    if "loose" in am_name_lower and am.get("master_category") == "STPLS":
        return "SEMI COMPLETE MATCH"

    sam_wt, sam_wu = parse_wt(sam_name)
    am_unit = (am.get("unit") or "").lower().strip()
    am_uv = am.get("unit_value")

    unit_match = True
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

    mrp5 = mrp10 = False
    if am_mrp and sam_mrp:
        try:
            pct = abs(float(am_mrp) - float(sam_mrp)) / max(float(am_mrp), 0.01) * 100
            mrp5 = pct <= 5
            mrp10 = pct <= 10
        except Exception:
            pass
    elif not am_mrp:
        mrp5 = mrp10 = True

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

    if (unit_match and mrp5) or sp_match or (unit_match and mrp10):
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

    b_pdp = load_pdp("blinkit", pincode)
    j_pdp = load_pdp("jiomart", pincode)
    b_cascade = load_cascade("blinkit", pincode)
    j_cascade = load_cascade("jiomart", pincode)

    rows = []
    for ic in sorted(am_map.keys(), key=lambda x: int(x) if x.isdigit() else 0):
        am = am_map.get(ic, {})
        mrp_rec = mrp_map.get(ic, {})
        am_mrp = mrp_rec.get("mrp") if mrp_rec else am.get("mrp")
        b_ana = blinkit_anakin.get(ic, {})
        j_ana = jiomart_anakin.get(ic, {})

        def get_sam(pdp_m, cas_m, ana_r, url_k):
            sp = mrp = name = stock = unit = None
            url = ana_r.get(url_k)
            if url and str(url).strip().lower() in ("na", "nan", "null", "none", ""):
                url = None
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
            return url, name, unit, mrp, sp, stock

        b_url, b_name, b_unit, b_mrp, b_sp, b_stock = get_sam(b_pdp, b_cascade, b_ana, "Blinkit_Product_Url")
        b_status = compute_status(am, am_mrp, b_sp, b_mrp, b_name, b_ana, "blinkit")

        j_url, j_name, j_unit, j_mrp, j_sp, j_stock = get_sam(j_pdp, j_cascade, j_ana, "Jiomart_Product_Url")
        j_status = compute_status(am, am_mrp, j_sp, j_mrp, j_name, j_ana, "jiomart")

        rows.append([
            DATE, NOW, city, pincode, int(ic) if ic.isdigit() else ic,
            am.get("display_name"), am.get("master_category"), am.get("brand"), am.get("marketed_by"),
            am.get("product_type"), am.get("unit"), am.get("unit_value"), am_mrp, am.get("main_image"),
            b_url, b_name, b_unit, b_mrp, b_sp, b_stock, b_status,
            j_url, j_name, j_unit, j_mrp, j_sp, j_stock, j_status,
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
    ]
    for i, h in enumerate(headers, 1):
        c = ws.cell(row=1, column=i, value=h)
        c.font = Font(bold=True, size=10)
        if 1 <= i <= 14: c.fill = am_fill
        elif 15 <= i <= 21: c.fill = blinkit_fill
        elif 22 <= i <= 28: c.fill = jio_fill

    for r_idx, row_data in enumerate(rows, 2):
        for c_idx, val in enumerate(row_data, 1):
            ws.cell(row=r_idx, column=c_idx, value=val)

    widths = [10, 18, 10, 8, 10, 40, 8, 15, 20, 20, 5, 8, 8, 30, 35, 40, 10, 8, 8, 12, 20, 35, 40, 10, 8, 8, 12, 20]
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = "E2"

    out_dir = Path("/Users/satyam/Desktop/price csv")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"SAM_{city}_{pincode}_{DATE}.xlsx"
    wb.save(out_path)
    print(f"  📊 {out_path.name}", flush=True)


def push_to_bigquery(csv_path):
    """Push CSV to both BQ tables."""
    print("\n📤 Pushing to BigQuery...", flush=True)

    # Live table (replace)
    r1 = subprocess.run(
        ["bq", "load", "--source_format=CSV", "--replace", BQ_LIVE_TABLE, str(csv_path)],
        capture_output=True, text=True,
    )
    if r1.returncode == 0:
        print(f"  ✅ sam_price_live (replaced)", flush=True)
    else:
        print(f"  ❌ sam_price_live: {r1.stderr[:200]}", flush=True)

    # History table (append)
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

    # Step 2: Scrape all cities
    if not skip_scrape:
        if len(pincodes) > 1:
            # Parallel cities
            from concurrent.futures import ThreadPoolExecutor, as_completed
            print(f"\n🚀 Running {len(pincodes)} cities in PARALLEL...", flush=True)
            with ThreadPoolExecutor(max_workers=len(pincodes)) as executor:
                futures = {executor.submit(scrape_city, pin, city): (pin, city) for pin, city in pincodes.items()}
                for future in as_completed(futures):
                    pin, city = futures[future]
                    try:
                        future.result()
                        print(f"  ✅ {city} complete", flush=True)
                    except Exception as e:
                        print(f"  ❌ {city} failed: {e}", flush=True)
        else:
            for pin, city in pincodes.items():
                scrape_city(pin, city)

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

    push_to_bigquery(csv_path)

    print(f"\n{'═' * 60}")
    print(f"  DONE! {len(pincodes)} cities, {len(all_rows)} rows")
    print(f"  Excel: /Users/satyam/Desktop/price csv/")
    print(f"  BigQuery: sam_price_live + sam_price_history")
    print(f"{'═' * 60}")


if __name__ == "__main__":
    main()
