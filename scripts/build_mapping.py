"""
Build SAM's own independent mapping file — extracts all item_code → platform_product_id
mappings from Anakin data + Stage 2/3/4 discoveries and saves as a clean, standalone file.

Once this mapping exists, Anakin is no longer needed for daily price refresh.

Usage:
    python3 scripts/build_mapping.py 834002
    python3 scripts/build_mapping.py all
"""
import json
import glob
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_ROOT = PROJECT_ROOT / "data"

CITIES = {"834002": "Ranchi", "712232": "Kolkata", "492001": "Raipur", "825301": "Hazaribagh"}

PLATFORM_CONFIGS = {
    "blinkit": {
        "product_id_field": "Blinkit_Product_Id",
        "product_url_field": "Blinkit_Product_Url",
        "item_name_field": "Blinkit_Item_Name",
        "selling_price_field": "Blinkit_Selling_Price",
        "mrp_field": "Blinkit_Mrp_Price",
        "stock_field": "Blinkit_In_Stock_Remark",
        "status_field": "Blinkit_Status",
        "factor_field": "Blinkit_Factor",
    },
    "jiomart": {
        "product_id_field": "Jiomart_Product_Id",
        "product_url_field": "Jiomart_Product_Url",
        "item_name_field": "Jiomart_Item_Name",
        "selling_price_field": "Jiomart_Selling_Price",
        "mrp_field": "Jiomart_Mrp_Price",
        "stock_field": "Jiomart_In_Stock_Remark",
        "status_field": "Jiomart_Status",
        "factor_field": "Jiomart_Factor",
    },
}


def clean_str(v) -> str:
    if v is None:
        return ""
    s = str(v).strip()
    if s.lower() in ("", "na", "nan", "null", "none"):
        return ""
    return s


def build_for_pincode(pincode: str):
    """Build mapping for all platforms for a given pincode."""
    results = {}

    for platform, pf in PLATFORM_CONFIGS.items():
        # Skip Hazaribagh Jiomart (no data)
        if pincode == "825301" and platform == "jiomart":
            continue

        mappings = {}

        # ── Source 1: Anakin's existing mapping (highest confidence) ──
        ana_files = sorted((DATA_ROOT / "anakin").glob(f"{platform}_{pincode}_*.json"))
        if ana_files:
            ana = json.load(open(ana_files[-1]))
            for r in ana["records"]:
                ic = clean_str(r.get("Item_Code"))
                pid = clean_str(r.get(pf["product_id_field"]))
                url = clean_str(r.get(pf["product_url_field"]))

                if not ic or not pid:
                    continue

                mappings[ic] = {
                    "item_code": ic,
                    "apna_name": clean_str(r.get("Item_Name")),
                    "apna_brand": clean_str(r.get("Brand")),
                    "apna_product_type": clean_str(r.get("Product_Type")),
                    "apna_unit": clean_str(r.get("Unit")),
                    "apna_unit_value": clean_str(r.get("Unit_Value")),
                    "apna_mrp": clean_str(r.get("Mrp")),
                    "platform_product_id": pid,
                    "platform_product_url": url,
                    "platform_item_name": clean_str(r.get(pf["item_name_field"])),
                    "platform_status": clean_str(r.get(pf["status_field"])),
                    "platform_factor": clean_str(r.get(pf["factor_field"])),
                    "match_method": "anakin_seed",
                    "confidence": 1.0,
                    "source": f"anakin_{ana_files[-1].name}",
                }

        # ── Source 2: Stage 2 cascade discoveries ──
        for f in sorted((DATA_ROOT / "comparisons").glob(f"{platform}_cascade_{pincode}_*.json")):
            d = json.load(open(f))
            for m in d.get("new_mappings", []):
                ic = clean_str(m.get("item_code"))
                pid = clean_str(m.get("sam_product_id"))
                if ic and pid and ic not in mappings:
                    mappings[ic] = {
                        "item_code": ic,
                        "apna_name": clean_str(m.get("anakin_name")),
                        "apna_brand": clean_str(m.get("anakin_brand")),
                        "platform_product_id": pid,
                        "platform_product_url": clean_str(m.get("sam_product_url")),
                        "platform_item_name": clean_str(m.get("sam_product_name")),
                        "match_method": "cascade_brand",
                        "confidence": m.get("cascade_score", 0.5),
                        "source": f.name,
                    }

        # ── Source 3: Stage 3 type/MRP discoveries ──
        for f in sorted((DATA_ROOT / "comparisons").glob(f"{platform}_stage3_{pincode}_*.json")):
            d = json.load(open(f))
            for m in d.get("new_mappings", []):
                ic = clean_str(m.get("item_code"))
                pid = clean_str(m.get("sam_product_id"))
                if ic and pid and ic not in mappings:
                    mappings[ic] = {
                        "item_code": ic,
                        "apna_name": clean_str(m.get("anakin_name")),
                        "apna_brand": clean_str(m.get("anakin_brand")),
                        "platform_product_id": pid,
                        "platform_product_url": clean_str(m.get("sam_product_url")),
                        "platform_item_name": clean_str(m.get("sam_product_name")),
                        "match_method": "cascade_type_mrp",
                        "confidence": m.get("stage3_score", 0.4),
                        "source": f.name,
                    }

        # ── Source 4: Jiomart search API discoveries (Jiomart only!) ──
        if platform == "jiomart":
          for f in sorted((DATA_ROOT / "comparisons").glob(f"jiomart_search_match_{pincode}_*.json")):
            d = json.load(open(f))
            for m in d.get("new_mappings", []):
                ic = clean_str(m.get("item_code"))
                if ic and ic not in mappings:
                    mappings[ic] = {
                        "item_code": ic,
                        "apna_name": clean_str(m.get("anakin_name")),
                        "platform_item_name": clean_str(m.get("sam_product_name")),
                        "platform_product_id": "",
                        "platform_product_url": "",
                        "match_method": "search_api",
                        "confidence": m.get("match_score", 0.5),
                        "source": f.name,
                    }

        if mappings:
            results[platform] = mappings

    return results


def save_mapping(pincode: str, city: str, platform_mappings: dict):
    """Save mapping file per pincode."""
    out_dir = DATA_ROOT / "mappings"
    out_dir.mkdir(parents=True, exist_ok=True)

    for platform, mappings in platform_mappings.items():
        out_path = out_dir / f"{platform}_{pincode}.json"

        # Count by method
        methods = {}
        for m in mappings.values():
            method = m.get("match_method", "unknown")
            methods[method] = methods.get(method, 0) + 1

        with open(out_path, "w") as f:
            json.dump({
                "platform": platform,
                "pincode": pincode,
                "city": city,
                "total_mappings": len(mappings),
                "by_method": methods,
                "built_at": datetime.now().isoformat(),
                "mappings": list(mappings.values()),
            }, f, indent=2, default=str)

        print(f"  ✅ {platform}_{pincode}.json — {len(mappings)} mappings ({methods})")


def main():
    pincode_arg = sys.argv[1] if len(sys.argv) > 1 else "834002"

    if pincode_arg == "all":
        pincodes = CITIES
    else:
        city = CITIES.get(pincode_arg, pincode_arg)
        pincodes = {pincode_arg: city}

    print("═══ Building SAM Independent Mappings ═══\n")

    grand_total = 0
    for pincode, city in pincodes.items():
        print(f"{city} ({pincode}):")
        platform_mappings = build_for_pincode(pincode)
        if platform_mappings:
            save_mapping(pincode, city, platform_mappings)
            for mappings in platform_mappings.values():
                grand_total += len(mappings)
        else:
            print("  ⚠️ No data found")
        print()

    print(f"Grand total: {grand_total} mappings saved to data/mappings/")
    print("Anakin dependency: REMOVED for daily refresh ✅")


if __name__ == "__main__":
    main()
