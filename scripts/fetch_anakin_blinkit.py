import os
"""
Fetch Anakin's Blinkit data from BigQuery (apna-mart-data.googlesheet.cx_competitor_prices)
for a given pincode + latest date, and save to data/anakin/blinkit_<pincode>_<date>.json + .csv.

Auth: requires `gcloud auth application-default login` with apnamart.in account.

Usage:
    python3 scripts/fetch_anakin_blinkit.py 834002
"""
import csv
import json
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

# Mirror Metabase endpoint (we use this because BQ python client isn't installed,
# and it's fine for read-only data pulls of < 10k rows per call).
API = "https://mirror.apnamart.in/api/dataset"
KEY = os.environ.get("METABASE_API_KEY", "")
TABLE_ID = 4742  # cx_competitor_prices in Mirror

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = PROJECT_ROOT / "data" / "anakin"

# Field IDs (from Mirror's table metadata) — order matters; rows are returned positionally
FIELDS = [
    ("Item_Code",                138778),
    ("Item_Name",                138790),
    ("Brand",                    138754),
    ("Product_Type",             138788),
    ("Unit",                     138749),
    ("Unit_Value",               138785),
    ("Mrp",                      138772),
    ("Image_Link",               138781),
    ("Blinkit_Product_Url",      138776),
    ("Blinkit_Product_Id",       138758),
    ("Blinkit_Item_Name",        138764),
    ("Blinkit_Uom",              138769),
    ("Blinkit_Mrp_Price",        138757),
    ("Blinkit_Selling_Price",    138774),
    ("Blinkit_In_Stock_Remark",  138750),
    ("Blinkit_Status",           138753),
    ("Blinkit_Partial",          138761),
    ("Blinkit_Factor",           138770),
]
PINCODE_FIELD_ID = 138793
DATE_FIELD_ID = 138779


def query(mbql):
    req = urllib.request.Request(
        API,
        method="POST",
        headers={"x-api-key": KEY, "Content-Type": "application/json"},
        data=json.dumps(mbql).encode(),
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())
    except urllib.error.URLError as e:
        print(f"ERROR: API request failed: {e}", file=sys.stderr)
        sys.exit(1)
    except urllib.error.HTTPError as e:
        print(f"ERROR: HTTP {e.code}: {e.reason}", file=sys.stderr)
        sys.exit(1)


def fetch_for_pincode(pincode: str) -> tuple[str, list[dict]]:
    # 1. Find latest date for this pincode
    print(f"Finding latest date for pincode {pincode}...")
    r = query({
        "database": 5, "type": "query",
        "query": {
            "source-table": TABLE_ID,
            "filter": ["=", ["field", PINCODE_FIELD_ID, None], pincode],
            "aggregation": [["max", ["field", DATE_FIELD_ID, None]]],
        }
    })
    rows = r["data"]["rows"]
    if not rows or not rows[0][0]:
        print(f"ERROR: No data found for pincode {pincode}", file=sys.stderr)
        sys.exit(1)
    latest_date = rows[0][0]
    print(f"  Latest date: {latest_date}")

    # 2. Paginate through all rows for that pincode + date
    all_records = []
    page_size = 2000
    page = 1
    while True:
        print(f"Fetching page {page}...")
        r = query({
            "database": 5, "type": "query",
            "query": {
                "source-table": TABLE_ID,
                "filter": ["and",
                           ["=", ["field", PINCODE_FIELD_ID, None], pincode],
                           ["=", ["field", DATE_FIELD_ID, None], latest_date]],
                "fields": [["field", fid, None] for _, fid in FIELDS],
                "order-by": [["asc", ["field", 138778, None]]],
                "page": {"page": page, "items": page_size},
                "limit": page_size,
            }
        })
        rows = r["data"]["rows"]
        if not rows:
            break
        for row in rows:
            all_records.append({name: row[i] for i, (name, _) in enumerate(FIELDS)})
        if len(rows) < page_size:
            break
        page += 1
        if page > 10:  # safety
            break

    return latest_date, all_records


def main(pincode: str):
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    latest_date, records = fetch_for_pincode(pincode)

    # Stats
    mapped = sum(1 for r in records if r.get("Blinkit_Product_Id") not in (None, "", "NA"))
    status_dist = {}
    for r in records:
        s = r.get("Blinkit_Status") or "NULL"
        status_dist[s] = status_dist.get(s, 0) + 1

    print(f"\nTotal rows: {len(records)}")
    print(f"Blinkit mapped (non-NA Product_Id): {mapped}")
    print("Status distribution:")
    for s, c in sorted(status_dist.items(), key=lambda x: -x[1]):
        print(f"  {s}: {c}")

    # Save JSON
    json_path = OUT_DIR / f"blinkit_{pincode}_{latest_date}.json"
    with open(json_path, "w") as f:
        json.dump({
            "pincode": pincode,
            "date": latest_date,
            "fetched_at": datetime.now().isoformat(),
            "total_rows": len(records),
            "blinkit_mapped": mapped,
            "status_distribution": status_dist,
            "records": records,
        }, f, indent=2, default=str)
    print(f"\nSaved JSON: {json_path}")

    # Save CSV
    csv_path = OUT_DIR / f"blinkit_{pincode}_{latest_date}.csv"
    with open(csv_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=[name for name, _ in FIELDS])
        w.writeheader()
        for rec in records:
            w.writerow(rec)
    print(f"Saved CSV:  {csv_path}")


if __name__ == "__main__":
    if not KEY:
        print("ERROR: METABASE_API_KEY not set", file=sys.stderr)
        sys.exit(1)
    pincode = sys.argv[1] if len(sys.argv) > 1 else "834002"
    main(pincode)
