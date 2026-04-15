"""
Generate SAM output in EXACT same format as Anakin's cx_competitor_prices table.
Same 47 columns, same structure — drop-in replacement for Mirror dashboard.

Output: data/sam_output/sam_competitor_prices_<pincode>_<date>.csv + .json

Usage:
    python3 scripts/generate_sam_table.py 834002
    python3 scripts/generate_sam_table.py all
"""
import csv
import json
import os
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_ROOT = PROJECT_ROOT / "data"

CITIES = {"834002": "Ranchi", "712232": "Kolkata", "492001": "Raipur", "825301": "Hazaribagh"}

# Exact same 47 columns as Anakin's cx_competitor_prices
COLUMNS = [
    "Date", "City", "Pincode",
    "Item_Code", "Item_Name", "Brand", "Product_Type", "Unit", "Unit_Value", "Mrp", "Image_Link",
    # Blinkit (12 cols)
    "Blinkit_Product_Url", "Blinkit_Product_Id", "Blinkit_Item_Name", "Blinkit_Uom",
    "Blinkit_Mrp_Price", "Blinkit_Selling_Price", "Blinkit_Discount__",
    "Blinkit_Eta_Mins_", "Blinkit_In_Stock_Remark",
    "Blinkit_Status", "Blinkit_Partial", "Blinkit_Factor",
    # Jiomart (12 cols)
    "Jiomart_Product_Url", "Jiomart_Product_Id", "Jiomart_Item_Name", "Jiomart_Uom",
    "Jiomart_Mrp_Price", "Jiomart_Selling_Price", "Jiomart_Discount__",
    "Jiomart_Eta_Mins_", "Jiomart_In_Stock_Remark",
    "Jiomart_Status", "Jiomart_Partial", "Jiomart_Factor",
    # Dmart (12 cols)
    "Dmart_Product_Url", "Dmart_Product_Id", "Dmart_Item_Name", "Dmart_Uom",
    "Dmart_Mrp_Price", "Dmart_Selling_Price", "Dmart_Discount__",
    "Dmart_Eta_Mins_", "Dmart_In_Stock_Remark",
    "Dmart_Status", "Dmart_Partial", "Dmart_Factor",
]


def clean(v) -> str:
    if v is None:
        return "NA"
    s = str(v).strip()
    if s.lower() in ("", "none", "null"):
        return "NA"
    return s


def load_mapping(platform: str, pincode: str) -> dict:
    """Load SAM mapping file, return dict keyed by item_code."""
    path = DATA_ROOT / "mappings" / f"{platform}_{pincode}.json"
    if not path.exists():
        return {}
    d = json.load(open(path))
    return {m["item_code"]: m for m in d.get("mappings", [])}


def load_pdp_prices(platform: str, pincode: str) -> dict:
    """Load latest PDP scrape prices, return dict keyed by item_code."""
    prefix = "blinkit" if platform == "blinkit" else "jiomart"
    pattern = f"{prefix}_pdp_{pincode}_*.json"
    files = sorted(DATA_ROOT.glob(f"sam/{pattern}"))
    # Exclude partial files
    files = [f for f in files if "partial" not in f.name]
    if not files:
        return {}
    d = json.load(open(files[-1]))
    prices = {}
    for p in d.get("products", []):
        ic = p.get("item_code")
        if ic and p.get("status") == "ok":
            prices[ic] = {
                "selling_price": p.get("sam_selling_price") or p.get("hmlg_selling_price"),
                "mrp": p.get("sam_mrp") or p.get("hmlg_mrp"),
                "in_stock": "available" if p.get("sam_in_stock") or p.get("hmlg_in_stock") else "out_of_stock",
                "product_name": p.get("sam_product_name") or p.get("hmlg_product_name") or "",
            }
    return prices


def load_apna_master(pincode: str) -> list[dict]:
    """Load Anakin/Apna product list for this pincode (we use Anakin's reference as the SKU list)."""
    # Use latest Blinkit Anakin file as the master SKU list (has Item_Code, Name, Brand etc.)
    files = sorted((DATA_ROOT / "anakin").glob(f"blinkit_{pincode}_*.json"))
    if not files:
        return []
    d = json.load(open(files[-1]))
    return d.get("records", [])


def generate_for_pincode(pincode: str, date_str: str):
    """Generate one SAM output file for a pincode."""
    city = CITIES.get(pincode, pincode)
    master = load_apna_master(pincode)
    if not master:
        print(f"  ⚠️ No master data for {pincode}")
        return

    # Load mappings
    blinkit_map = load_mapping("blinkit", pincode)
    jiomart_map = load_mapping("jiomart", pincode)

    # Load latest prices
    blinkit_prices = load_pdp_prices("blinkit", pincode)
    jiomart_prices = load_pdp_prices("jiomart", pincode)

    rows = []
    for rec in master:
        ic = clean(rec.get("Item_Code"))
        if ic == "NA":
            continue

        # Base Apna fields
        row = {
            "Date": date_str,
            "City": city,
            "Pincode": pincode,
            "Item_Code": ic,
            "Item_Name": clean(rec.get("Item_Name")),
            "Brand": clean(rec.get("Brand")),
            "Product_Type": clean(rec.get("Product_Type")),
            "Unit": clean(rec.get("Unit")),
            "Unit_Value": clean(rec.get("Unit_Value")),
            "Mrp": clean(rec.get("Mrp")),
            "Image_Link": clean(rec.get("Image_Link")),
        }

        # Blinkit fields
        b_map = blinkit_map.get(ic, {})
        b_price = blinkit_prices.get(ic, {})
        sp = b_price.get("selling_price")
        mrp = b_price.get("mrp")
        discount = ""
        if sp and mrp and mrp > 0:
            discount = str(round((1 - sp / mrp) * 100, 1))

        row.update({
            "Blinkit_Product_Url": clean(b_map.get("platform_product_url")),
            "Blinkit_Product_Id": clean(b_map.get("platform_product_id")),
            "Blinkit_Item_Name": clean(b_map.get("platform_item_name") or b_price.get("product_name")),
            "Blinkit_Uom": "NA",
            "Blinkit_Mrp_Price": clean(mrp),
            "Blinkit_Selling_Price": clean(sp),
            "Blinkit_Discount__": clean(discount) if discount else "NA",
            "Blinkit_Eta_Mins_": "NA",
            "Blinkit_In_Stock_Remark": clean(b_price.get("in_stock")),
            "Blinkit_Status": clean(b_map.get("platform_status") or ("Complete Match" if b_price else "NA")),
            "Blinkit_Partial": clean(b_map.get("match_method")),
            "Blinkit_Factor": clean(b_map.get("platform_factor", "1")),
        })

        # Jiomart fields
        j_map = jiomart_map.get(ic, {})
        j_price = jiomart_prices.get(ic, {})
        j_sp = j_price.get("selling_price")
        j_mrp = j_price.get("mrp")
        j_discount = ""
        if j_sp and j_mrp and j_mrp > 0:
            j_discount = str(round((1 - j_sp / j_mrp) * 100, 1))

        row.update({
            "Jiomart_Product_Url": clean(j_map.get("platform_product_url")),
            "Jiomart_Product_Id": clean(j_map.get("platform_product_id")),
            "Jiomart_Item_Name": clean(j_map.get("platform_item_name") or j_price.get("product_name")),
            "Jiomart_Uom": "NA",
            "Jiomart_Mrp_Price": clean(j_mrp),
            "Jiomart_Selling_Price": clean(j_sp),
            "Jiomart_Discount__": clean(j_discount) if j_discount else "NA",
            "Jiomart_Eta_Mins_": "NA",
            "Jiomart_In_Stock_Remark": clean(j_price.get("in_stock")),
            "Jiomart_Status": clean(j_map.get("platform_status") or ("Complete Match" if j_price else "NA")),
            "Jiomart_Partial": clean(j_map.get("match_method")),
            "Jiomart_Factor": clean(j_map.get("platform_factor", "1")),
        })

        # Dmart fields (all NA for now — Dmart not active in these cities)
        row.update({
            "Dmart_Product_Url": "NA", "Dmart_Product_Id": "NA",
            "Dmart_Item_Name": "NA", "Dmart_Uom": "NA",
            "Dmart_Mrp_Price": "NA", "Dmart_Selling_Price": "NA",
            "Dmart_Discount__": "NA", "Dmart_Eta_Mins_": "NA",
            "Dmart_In_Stock_Remark": "NA",
            "Dmart_Status": "NA", "Dmart_Partial": "NA", "Dmart_Factor": "NA",
        })

        rows.append(row)

    # Save
    out_dir = DATA_ROOT / "sam_output"
    out_dir.mkdir(parents=True, exist_ok=True)

    # CSV (same as Anakin's format)
    csv_path = out_dir / f"sam_competitor_prices_{pincode}_{date_str}.csv"
    with open(csv_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(rows)

    # JSON
    json_path = out_dir / f"sam_competitor_prices_{pincode}_{date_str}.json"
    with open(json_path, "w") as f:
        json.dump(rows, f, indent=2, default=str)

    # Stats
    b_priced = sum(1 for r in rows if r["Blinkit_Selling_Price"] != "NA")
    j_priced = sum(1 for r in rows if r["Jiomart_Selling_Price"] != "NA")
    print(f"  ✅ {city} ({pincode}): {len(rows)} rows | Blinkit: {b_priced} priced | Jiomart: {j_priced} priced")
    print(f"     CSV: {csv_path.name}")


def main():
    pincode_arg = sys.argv[1] if len(sys.argv) > 1 else "834002"
    date_str = datetime.now().strftime("%Y-%m-%d")

    print(f"═══ Generating SAM Output (Anakin-format, {date_str}) ═══\n")

    if pincode_arg == "all":
        for pincode in CITIES:
            generate_for_pincode(pincode, date_str)
    else:
        generate_for_pincode(pincode_arg, date_str)

    print(f"\nOutput: data/sam_output/")
    print("Format: EXACTLY same as Anakin's cx_competitor_prices (47 columns)")
    print("Can push to BigQuery as drop-in replacement ✅")


if __name__ == "__main__":
    main()
