"""
Fetch EAN/barcode data from Apna's product master (smpcm_product).
Saves item_code → EAN mapping to data/ean_map.json.

Run daily before pipeline — EAN is used for cross-verification in cascade/stage3.

Usage:
    export METABASE_API_KEY=...
    python3 scripts/fetch_ean_map.py
"""
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

API = "https://mirror.apnamart.in/api"
KEY = os.environ.get("METABASE_API_KEY", "")
PROJECT_ROOT = Path(__file__).resolve().parent.parent

if not KEY:
    print("ERROR: METABASE_API_KEY not set", file=sys.stderr)
    sys.exit(1)


def query(payload: dict) -> dict:
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        f"{API}/dataset", data=data,
        headers={"x-api-key": KEY, "Content-Type": "application/json"},
    )
    try:
        resp = urllib.request.urlopen(req, timeout=60)
        return json.loads(resp.read())
    except (urllib.error.URLError, urllib.error.HTTPError) as e:
        print(f"ERROR: API call failed: {e}", file=sys.stderr)
        return {}


def main():
    print("[ean] Fetching EAN barcodes from smpcm_product...", flush=True)

    all_rows = []
    page = 1
    while True:
        r = query({
            "database": 5,
            "type": "query",
            "query": {
                "source-table": 578,  # smpcm_product
                "fields": [["field", 7191], ["field", 7127]],  # item_code, bar_code
                "limit": 2000,
                "offset": (page - 1) * 2000,
            },
        })
        rows = r.get("data", {}).get("rows", [])
        if not rows:
            break
        all_rows.extend(rows)
        if len(rows) < 2000:
            break
        page += 1
        if page > 50:
            break

    # Filter real EANs: 8+ digits, not same as item_code
    ean_map = {}
    for ic, bc in all_rows:
        ic_str = str(ic).strip()
        bc_str = str(bc).strip()
        if bc_str and bc_str != ic_str and len(bc_str) >= 8 and bc_str.isdigit():
            ean_map[ic_str] = bc_str

    out_dir = PROJECT_ROOT / "data"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "ean_map.json"
    with open(out_path, "w") as f:
        json.dump(ean_map, f, indent=2)

    print(f"[ean] Total products: {len(all_rows)}")
    print(f"[ean] With real EAN (8+ digits): {len(ean_map)}")
    print(f"[ean] Saved to {out_path}")


if __name__ == "__main__":
    main()
