"""
Stage 5: Barcode/EAN matching.

For each unmatched Anakin SKU (after Stage 1-4):
  1. Get Apna's barcode from smpcm_product (bar_code, bar_codes fields)
  2. Check if any SAM BFS pool product has the same barcode
  3. Exact barcode match = 100% guaranteed same product

Only works for products with REAL EAN barcodes (13-digit, 890xxxx format).
Internal item_codes (5-6 digit) are skipped as they won't match Blinkit's IDs.

Usage:
    python3 scripts/stage5_barcode_match.py 834002 [blinkit|jiomart]
"""
import json
import re
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

METABASE_API = "https://mirror.apnamart.in/api/dataset"
METABASE_KEY = "mb_vk+r3s1MVlQHdlRfpI1+1onHFQYvMQMQ5QPfdPROGvM="


def is_real_ean(bc: str) -> bool:
    """Check if barcode looks like a real EAN/UPC (8+ digits, not just item_code)."""
    if not bc:
        return False
    bc = bc.strip()
    return len(bc) >= 8 and bc.isdigit()


def query_metabase(mbql):
    req = urllib.request.Request(
        METABASE_API, method="POST",
        headers={"x-api-key": METABASE_KEY, "Content-Type": "application/json"},
        data=json.dumps(mbql).encode(),
    )
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())


def clean_str(v) -> str:
    if v is None:
        return ""
    s = str(v).strip()
    if s.lower() in ("", "na", "nan", "null", "none"):
        return ""
    return s


def latest_file(subdir: str, pattern: str) -> Path | None:
    cands = sorted((PROJECT_ROOT / "data" / subdir).glob(pattern))
    return cands[-1] if cands else None


def main(pincode: str, platform: str = "blinkit"):
    PLATFORM_FIELDS = {
        "blinkit": {"product_id": "Blinkit_Product_Id", "selling_price": "Blinkit_Selling_Price"},
        "jiomart": {"product_id": "Jiomart_Product_Id", "selling_price": "Jiomart_Selling_Price"},
    }
    pf = PLATFORM_FIELDS.get(platform, PLATFORM_FIELDS["blinkit"])

    ana_path = latest_file("anakin", f"{platform}_{pincode}_*.json")
    sam_path = None
    for p in sorted((PROJECT_ROOT / "data" / "sam").glob(f"{platform}_{pincode}_*.json"), reverse=True):
        if "pdp" not in p.name:
            sam_path = p
            break

    if not ana_path or not sam_path:
        print(f"[barcode] ERROR: missing files", file=sys.stderr)
        sys.exit(1)

    print(f"[barcode] Platform: {platform}")
    print(f"[barcode] Anakin: {ana_path.name}")
    print(f"[barcode] SAM pool: {sam_path.name}")

    ana = json.load(open(ana_path))
    sam = json.load(open(sam_path))

    # Find unmatched non-loose usable SKUs (same logic as Stage 4)
    usable_codes = {r.get("Item_Code") for r in ana["records"]
                    if r.get(pf["selling_price"]) not in (None, "", "NA", "nan")
                    and "loose" not in (r.get("Item_Name") or "").lower()}

    matched_codes: set[str] = set()
    for pattern_str in [f"{platform}_pdp_{pincode}_*_compare.json",
                        f"{platform}_cascade_{pincode}_*.json",
                        f"{platform}_stage3_{pincode}_*.json",
                        f"{platform}_image_match_{pincode}_*.json"]:
        for f in sorted((PROJECT_ROOT / "data" / "comparisons").glob(pattern_str)):
            d = json.load(open(f))
            for m in d.get("matches", []):
                if m.get("match_status") == "ok":
                    matched_codes.add(m.get("item_code"))
            for m in d.get("new_mappings", []):
                matched_codes.add(m.get("item_code"))

    unmatched_codes = usable_codes - matched_codes
    print(f"[barcode] Unmatched after Stage 1-4: {len(unmatched_codes)}")

    # Step 1: Fetch barcodes from Apna's smpcm_product for unmatched item_codes
    print("[barcode] Fetching barcodes from smpcm_product...", flush=True)
    # Query in batches (Metabase MBQL doesn't support IN lists well, use filter)
    # Fetch ALL barcodes and filter locally
    all_records = []
    page = 1
    while True:
        r = query_metabase({
            "database": 5, "type": "query",
            "query": {
                "source-table": 578,
                "filter": ["and",
                           ["=", ["field", 7161, None], True],
                           ["not-null", ["field", 7127, None]],
                           ["!=", ["field", 7127, None], ""]],
                "fields": [
                    ["field", 7191, None],  # item_code
                    ["field", 7118, None],  # display_name
                    ["field", 7127, None],  # bar_code
                    ["field", 12890, None], # bar_codes (JSON array)
                ],
                "page": {"page": page, "items": 2000},
                "limit": 2000,
            }
        })
        rows = r["data"]["rows"]
        if not rows:
            break
        all_records.extend(rows)
        if len(rows) < 2000:
            break
        page += 1
        if page > 30:
            break

    print(f"[barcode] Fetched {len(all_records)} products with barcodes")

    # Build barcode → item_code lookup (only real EANs for unmatched)
    apna_barcode_map: dict[str, dict] = {}  # ean → {item_code, name}
    for row in all_records:
        ic = str(row[0])
        if ic not in unmatched_codes:
            continue
        name = row[1]
        bc = str(row[2]) if row[2] else ""
        bcs_raw = row[3]  # JSON array like ["12345", "8901234567890"]

        # Collect all EANs
        eans = set()
        if is_real_ean(bc):
            eans.add(bc)
        if bcs_raw:
            if isinstance(bcs_raw, list):
                for b in bcs_raw:
                    if is_real_ean(str(b)):
                        eans.add(str(b))
            elif isinstance(bcs_raw, str):
                try:
                    arr = json.loads(bcs_raw)
                    for b in arr:
                        if is_real_ean(str(b)):
                            eans.add(str(b))
                except (json.JSONDecodeError, TypeError):
                    pass

        for ean in eans:
            apna_barcode_map[ean] = {"item_code": ic, "name": name}

    print(f"[barcode] Unmatched with real EAN: {len(set(d['item_code'] for d in apna_barcode_map.values()))}")
    print(f"[barcode] Total unique EANs: {len(apna_barcode_map)}")

    # Step 2: Check SAM BFS pool for barcode data
    # SAM products from BFS don't usually have barcodes — need to check
    # Blinkit API sometimes returns barcode in product JSON
    sam_barcodes: dict[str, dict] = {}  # ean → product
    for p in sam["products"]:
        # Check if product has barcode-like field
        for key in ("barcode", "bar_code", "ean", "upc", "gtin"):
            v = p.get(key)
            if v and is_real_ean(str(v)):
                sam_barcodes[str(v)] = p

    print(f"[barcode] SAM pool products with barcodes: {len(sam_barcodes)}")

    # Step 3: Match by barcode
    new_matches = []
    if sam_barcodes and apna_barcode_map:
        for ean, apna_info in apna_barcode_map.items():
            if ean in sam_barcodes:
                sam_p = sam_barcodes[ean]
                new_matches.append({
                    "item_code": apna_info["item_code"],
                    "anakin_name": apna_info["name"],
                    "barcode": ean,
                    "sam_product_name": sam_p.get("product_name"),
                    "sam_brand": sam_p.get("brand"),
                    "sam_price": sam_p.get("price"),
                    "sam_mrp": sam_p.get("mrp"),
                    "sam_product_id": sam_p.get("product_id"),
                    "match_method": "barcode_ean",
                })

    print()
    print("=" * 60)
    print(f"STAGE 5 RESULT — Barcode matching ({platform}, {pincode})")
    print("=" * 60)
    print(f"Unmatched input:         {len(unmatched_codes)}")
    print(f"With real EAN barcode:   {len(set(d['item_code'] for d in apna_barcode_map.values()))}")
    print(f"SAM pool with barcodes:  {len(sam_barcodes)}")
    print(f"New barcode matches:     {len(new_matches)}")
    print()

    if new_matches:
        print("Barcode matches:")
        for m in new_matches[:10]:
            print(f"  EAN {m['barcode']}: {m['anakin_name'][:40]} → {m['sam_product_name'][:40]}")

    # Save
    out_dir = PROJECT_ROOT / "data" / "comparisons"
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    out_path = out_dir / f"{platform}_barcode_match_{pincode}_{ts}.json"
    with open(out_path, "w") as f:
        json.dump({
            "pincode": pincode,
            "platform": platform,
            "compared_at": datetime.now().isoformat(),
            "metrics": {
                "unmatched_input": len(unmatched_codes),
                "with_real_ean": len(set(d["item_code"] for d in apna_barcode_map.values())),
                "sam_with_barcodes": len(sam_barcodes),
                "new_matches": len(new_matches),
            },
            "new_mappings": new_matches,
        }, f, indent=2, default=str)
    print(f"\nReport: {out_path}")


if __name__ == "__main__":
    pincode = sys.argv[1] if len(sys.argv) > 1 else "834002"
    platform = sys.argv[2] if len(sys.argv) > 2 else "blinkit"
    main(pincode, platform)
