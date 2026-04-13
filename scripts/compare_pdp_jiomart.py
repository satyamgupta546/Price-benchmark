"""
Stage 1 matching for Jiomart: Exact-join comparison between SAM's Jiomart PDP
scrape and Anakin's Jiomart reference data, using Apna item_code as key.

Usage:
    python3 scripts/compare_pdp_jiomart.py 834002
"""
import json
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def latest_anakin_jiomart(pincode: str) -> Path | None:
    cands = sorted((PROJECT_ROOT / "data" / "anakin").glob(f"jiomart_{pincode}_*.json"))
    return cands[-1] if cands else None


def latest_pdp_sam(pincode: str) -> Path | None:
    cands = [p for p in sorted((PROJECT_ROOT / "data" / "sam").glob(f"jiomart_pdp_{pincode}_*.json"))
             if "latest_partial" not in p.name and "latest" not in p.name.replace(".json", "").split("_")[-1]]
    # Prefer non-partial final files
    if cands:
        return cands[-1]
    # Fallback to partial
    partial = PROJECT_ROOT / "data" / "sam" / f"jiomart_pdp_{pincode}_latest_partial.json"
    if partial.exists():
        return partial
    return None


def parse_num(v):
    if v is None or str(v).strip().lower() in ("", "na", "nan", "null", "none"):
        return None
    try:
        s = str(v).replace("₹", "").replace("Rs.", "").replace("Rs", "").replace(",", "").strip()
        s = s.rstrip("/-").strip()
        return float(s)
    except (ValueError, TypeError):
        return None


def main(pincode: str):
    ana_path = latest_anakin_jiomart(pincode)
    pdp_path = latest_pdp_sam(pincode)

    if not ana_path:
        print(f"[compare_jm] ERROR: no Anakin Jiomart file for {pincode}", file=sys.stderr)
        sys.exit(1)
    if not pdp_path:
        print(f"[compare_jm] ERROR: no SAM Jiomart PDP file for {pincode}", file=sys.stderr)
        sys.exit(1)

    print(f"[compare_jm] Anakin:   {ana_path.name}")
    print(f"[compare_jm] SAM PDP: {pdp_path.name}")

    ana = json.load(open(ana_path))
    pdp = json.load(open(pdp_path))

    ana_by_code = {}
    for rec in ana["records"]:
        ic = (rec.get("Item_Code") or "").strip()
        if ic:
            ana_by_code[ic] = rec

    sam_products = pdp["products"]
    total_sam = len(sam_products)
    total_anakin_mapped = sum(1 for r in ana["records"]
                              if r.get("Jiomart_Product_Id") not in (None, "", "NA"))

    matches = []
    ok_count = no_price_count = error_count = 0

    for p in sam_products:
        ic = p.get("item_code")
        if not ic or ic not in ana_by_code:
            continue
        ana_rec = ana_by_code[ic]
        sam_status = p.get("status")

        if sam_status == "error":
            error_count += 1
            matches.append({**p, "match_status": "scrape_error"})
            continue
        if sam_status == "no_price":
            no_price_count += 1
            matches.append({**p, "match_status": "no_price_on_pdp"})
            continue

        ok_count += 1
        ana_sp = parse_num(ana_rec.get("Jiomart_Selling_Price"))
        ana_mrp_j = parse_num(ana_rec.get("Jiomart_Mrp_Price"))
        sam_sp = parse_num(p.get("sam_selling_price"))
        sam_mrp = parse_num(p.get("sam_mrp"))

        price_diff_pct = None
        if ana_sp and sam_sp:
            price_diff_pct = abs(sam_sp - ana_sp) / ana_sp * 100

        matches.append({
            "item_code": ic,
            "anakin_name": ana_rec.get("Item_Name"),
            "anakin_brand": ana_rec.get("Brand"),
            "anakin_jiomart_name": ana_rec.get("Jiomart_Item_Name"),
            "anakin_jiomart_sp": ana_sp,
            "anakin_jiomart_mrp": ana_mrp_j,
            "anakin_in_stock": ana_rec.get("Jiomart_In_Stock_Remark"),
            "anakin_status": ana_rec.get("Jiomart_Status"),
            "jiomart_product_id": p.get("jiomart_product_id"),
            "jiomart_product_url": p.get("jiomart_product_url"),
            "sam_product_name": p.get("sam_product_name"),
            "sam_selling_price": sam_sp,
            "sam_mrp": sam_mrp,
            "sam_in_stock": p.get("sam_in_stock"),
            "price_diff_pct": round(price_diff_pct, 2) if price_diff_pct is not None else None,
            "match_status": "ok",
        })

    price_compared = [m for m in matches if m.get("price_diff_pct") is not None]
    in_2 = [m for m in price_compared if m["price_diff_pct"] <= 2]
    in_5 = [m for m in price_compared if m["price_diff_pct"] <= 5]
    in_10 = [m for m in price_compared if m["price_diff_pct"] <= 10]

    cov_pct = ok_count / total_anakin_mapped * 100 if total_anakin_mapped else 0

    print()
    print("=" * 60)
    print(f"STAGE 1 RESULT — Jiomart PDP exact-match (pincode {pincode})")
    print("=" * 60)
    print(f"Anakin mapped SKUs:       {total_anakin_mapped}")
    print(f"SAM PDPs scraped:        {total_sam}")
    print(f"  OK with price:          {ok_count}")
    print(f"  No price on PDP:        {no_price_count}")
    print(f"  Scrape errors:          {error_count}")
    print()
    print(f"COVERAGE (ID-exact):      {ok_count}/{total_anakin_mapped} = {cov_pct:.1f}%")
    print()
    print(f"PRICE MATCH (vs Anakin's Jiomart_Selling_Price):")
    print(f"  Price-compared pool:    {len(price_compared)} SKUs")
    if price_compared:
        p2 = len(in_2) / len(price_compared) * 100
        p5 = len(in_5) / len(price_compared) * 100
        p10 = len(in_10) / len(price_compared) * 100
        print(f"  Within ±2%:             {len(in_2)}/{len(price_compared)} = {p2:.1f}%")
        print(f"  Within ±5%:             {len(in_5)}/{len(price_compared)} = {p5:.1f}%")
        print(f"  Within ±10%:            {len(in_10)}/{len(price_compared)} = {p10:.1f}%")
    print()

    out_dir = PROJECT_ROOT / "data" / "comparisons"
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    out_path = out_dir / f"jiomart_pdp_{pincode}_{ts}_compare.json"
    with open(out_path, "w") as f:
        json.dump({
            "pincode": pincode,
            "platform": "jiomart",
            "compared_at": datetime.now().isoformat(),
            "anakin_file": ana_path.name,
            "sam_pdp_file": pdp_path.name,
            "metrics": {
                "anakin_mapped_skus": total_anakin_mapped,
                "sam_pdp_scraped": total_sam,
                "ok": ok_count,
                "no_price": no_price_count,
                "errors": error_count,
                "coverage_pct": round(cov_pct, 1),
                "price_compared": len(price_compared),
                "price_match_2pct": len(in_2),
                "price_match_5pct": len(in_5),
                "price_match_10pct": len(in_10),
                "price_match_pct_2": round(len(in_2) / len(price_compared) * 100, 1) if price_compared else 0,
                "price_match_pct_5": round(len(in_5) / len(price_compared) * 100, 1) if price_compared else 0,
                "price_match_pct_10": round(len(in_10) / len(price_compared) * 100, 1) if price_compared else 0,
            },
            "matches": matches,
        }, f, indent=2, default=str)
    print(f"Full report: {out_path}")


if __name__ == "__main__":
    pincode = sys.argv[1] if len(sys.argv) > 1 else "834002"
    main(pincode)
