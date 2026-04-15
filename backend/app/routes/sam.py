"""SAM Dashboard API — serves coverage data + CSV downloads for the frontend."""
import csv
import io
import json
import glob
from pathlib import Path
from fastapi import APIRouter
from fastapi.responses import StreamingResponse

router = APIRouter(prefix="/api/sam")

DATA_ROOT = Path(__file__).resolve().parent.parent.parent.parent / "data"

CITIES = {
    "834002": "Ranchi",
    "712232": "Kolkata",
    "492001": "Raipur",
    "825301": "Hazaribagh",
}

PLATFORM_SP_FIELDS = {
    "blinkit": "Blinkit_Selling_Price",
    "jiomart": "Jiomart_Selling_Price",
}


def _count_matched(pincode: str, platform: str) -> dict:
    """Count matched products across all stages for a pincode+platform."""
    ana_files = sorted((DATA_ROOT / "anakin").glob(f"{platform}_{pincode}_*.json"))
    if not ana_files:
        return {"usable": 0, "matched": 0, "stages": {}, "coverage_pct": 0}

    ana = json.load(open(ana_files[-1]))
    pf_sp = PLATFORM_SP_FIELDS.get(platform, "Blinkit_Selling_Price")

    usable = {r.get("Item_Code") for r in ana["records"]
              if r.get(pf_sp) not in (None, "", "NA", "nan")
              and "loose" not in (r.get("Item_Name") or "").lower()}

    matched = set()
    stages = {}
    cmp_dir = DATA_ROOT / "comparisons"

    # Stage 1 — PDP
    for f in sorted(cmp_dir.glob(f"{platform}_pdp_{pincode}_*_compare.json")):
        d = json.load(open(f))
        for m in d.get("matches", []):
            if m.get("match_status") == "ok":
                matched.add(m.get("item_code"))
    stages["Stage 1 (PDP)"] = len(matched & usable)
    prev = len(matched & usable)

    # Stage 2 — Cascade
    for f in sorted(cmp_dir.glob(f"{platform}_cascade_{pincode}_*.json")):
        d = json.load(open(f))
        for m in d.get("new_mappings", []):
            matched.add(m.get("item_code"))
    stages["Stage 2 (Brand)"] = len(matched & usable) - prev
    prev = len(matched & usable)

    # Stage 3 — Type/MRP
    for f in sorted(cmp_dir.glob(f"{platform}_stage3_{pincode}_*.json")):
        d = json.load(open(f))
        for m in d.get("new_mappings", []):
            matched.add(m.get("item_code"))
    stages["Stage 3 (Type/MRP)"] = len(matched & usable) - prev
    prev = len(matched & usable)

    # Stage 4 — Search API (Jiomart)
    for f in sorted(cmp_dir.glob(f"jiomart_search_match_{pincode}_*.json")):
        d = json.load(open(f))
        for m in d.get("new_mappings", []):
            matched.add(m.get("item_code"))
    stages["Stage 4 (Search)"] = len(matched & usable) - prev
    prev = len(matched & usable)

    # Stage 5 — Image + Barcode
    for f in sorted(cmp_dir.glob(f"{platform}_image_match_{pincode}_*.json")):
        d = json.load(open(f))
        for m in d.get("new_mappings", []):
            matched.add(m.get("item_code"))
    for f in sorted(cmp_dir.glob(f"{platform}_barcode_match_{pincode}_*.json")):
        d = json.load(open(f))
        for m in d.get("new_mappings", []):
            matched.add(m.get("item_code"))
    stages["Stage 5 (Image/Barcode)"] = len(matched & usable) - prev

    total_matched = len(matched & usable)
    return {
        "usable": len(usable),
        "matched": total_matched,
        "unmatched": len(usable) - total_matched,
        "coverage_pct": round(total_matched * 100 / len(usable), 1) if usable else 0,
        "stages": stages,
    }


@router.get("/dashboard")
def get_dashboard():
    """Return coverage data for all cities × platforms."""
    results = []
    grand_usable = 0
    grand_matched = 0

    for pincode, city in CITIES.items():
        for platform in ["blinkit", "jiomart"]:
            # Skip Hazaribagh Jiomart (no data)
            if pincode == "825301" and platform == "jiomart":
                continue

            data = _count_matched(pincode, platform)
            grand_usable += data["usable"]
            grand_matched += data["matched"]

            results.append({
                "city": city,
                "pincode": pincode,
                "platform": platform,
                **data,
            })

    return {
        "cities": list(CITIES.values()),
        "results": results,
        "grand_total": {
            "usable": grand_usable,
            "matched": grand_matched,
            "coverage_pct": round(grand_matched * 100 / grand_usable, 1) if grand_usable else 0,
        },
    }


def _find_sam_output(pincode: str) -> Path | None:
    """Find latest SAM output CSV for a pincode."""
    files = sorted((DATA_ROOT / "sam_output").glob(f"sam_competitor_prices_{pincode}_*.csv"))
    return files[-1] if files else None


@router.get("/download/{pincode}")
def download_csv(pincode: str):
    """Download SAM output CSV for a specific pincode."""
    if not pincode.isdigit() or len(pincode) != 6:
        return {"error": "Invalid pincode"}

    csv_path = _find_sam_output(pincode)
    if not csv_path:
        return {"error": f"No SAM output for pincode {pincode}. Run generate_sam_table.py first."}

    city = CITIES.get(pincode, pincode)

    def stream():
        with open(csv_path, "r") as f:
            yield f.read()

    return StreamingResponse(
        stream(),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=SAM_{city}_{pincode}.csv"},
    )


@router.get("/download/all")
def download_all_csv():
    """Download combined SAM output CSV for all cities."""
    all_rows = []
    header = None

    for pincode in CITIES:
        csv_path = _find_sam_output(pincode)
        if not csv_path:
            continue
        with open(csv_path, "r") as f:
            reader = csv.reader(f)
            rows = list(reader)
            if not rows:
                continue
            if header is None:
                header = rows[0]
                all_rows.append(rows[0])
            all_rows.extend(rows[1:])

    if not all_rows:
        return {"error": "No SAM output files found. Run generate_sam_table.py first."}

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerows(all_rows)

    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=SAM_All_Cities.csv"},
    )
