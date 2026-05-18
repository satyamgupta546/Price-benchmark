"""
Stage 2: Cascade filter matcher (brand → product_type → weight → name).

Runs on SKUs that Stage 1 couldn't handle:
  - Anakin's "NA" SKUs (where Anakin itself couldn't map to Blinkit)
  - SAM's general scrape output (products not in Anakin)

For each unmatched Anakin SKU, narrows candidates via strict filters,
then picks the best name match from the filtered set.

Usage:
    python3 scripts/cascade_match.py 834002
"""
import json
import sys
from difflib import SequenceMatcher
from datetime import datetime
from pathlib import Path

from utils import (
    clean_str, normalize, parse_num,
    UNIT_ALIASES, parse_unit, to_base_unit, units_compatible,
    normalize_brand, latest_file, PROJECT_ROOT,
)

# ── EAN map (loaded once at startup) ──
EAN_MAP: dict[str, str] = {}


def load_ean_map():
    """Load item_code→EAN mapping from data/ean_map.json."""
    global EAN_MAP
    ean_path = PROJECT_ROOT / "data" / "ean_map.json"
    if ean_path.exists():
        EAN_MAP = json.load(open(ean_path))
        print(f"[cascade] EAN map loaded: {len(EAN_MAP)} barcodes")


# ── Local tokens (different from utils.tokens — no length/stopword filtering) ──

def tokens(s: str) -> set[str]:
    return set(normalize(s).split())


# ── Core matcher ────────────────────────────────────────────────

def find_match(ana_sku: dict, sam_products: list[dict], debug: bool = False) -> tuple[dict | None, str, float]:
    """
    Apply cascading filter to find best SAM match for one Anakin SKU.
    Returns (matched_product, reason, score). reason is one of:
      "no_brand", "no_weight", "no_name_score", "cascaded"
    """
    ana_brand = normalize_brand(clean_str(ana_sku.get("Brand")))
    ana_ptype = normalize(clean_str(ana_sku.get("Product_Type")))
    ana_uv_raw = ana_sku.get("Unit_Value")
    ana_unit_raw = clean_str(ana_sku.get("Unit"))
    ana_name = clean_str(ana_sku.get("Blinkit_Item_Name")) or clean_str(ana_sku.get("Item_Name"))

    ana_uv = parse_num(ana_uv_raw)
    ana_unit = UNIT_ALIASES.get(normalize(ana_unit_raw), normalize(ana_unit_raw))

    # ─── PATH A: Brand → Weight → Name → MRP (strict, high confidence) ────
    brand_candidates = []
    if ana_brand:
        for p in sam_products:
            p_brand = normalize_brand(p.get("brand") or "")
            if p_brand and p_brand == ana_brand:
                brand_candidates.append(p)

    if brand_candidates:
        if debug:
            print(f"    path A: {len(brand_candidates)} candidates by brand '{ana_brand}'")

        # Product Type filter (loose)
        if ana_ptype:
            pt_tokens = set(ana_ptype.split())
            filtered = [p for p in brand_candidates
                        if pt_tokens & (tokens(p.get("category") or "") | tokens(p.get("product_name") or ""))]
            if filtered:
                brand_candidates = filtered

        # Weight filter
        weight_available = bool(ana_uv and ana_unit)
        if weight_available:
            ana_base_val, ana_base_unit = to_base_unit(ana_uv, ana_unit)
            weight_match = []
            for p in brand_candidates:
                p_uv, p_unit = parse_unit(p.get("unit") or "")
                if p_uv and p_unit and units_compatible(ana_unit, p_unit):
                    p_base_val, _ = to_base_unit(p_uv, p_unit)
                    if p_base_val > 0 and ana_base_val > 0:
                        ratio = p_base_val / ana_base_val
                        if 0.9 <= ratio <= 1.1:
                            weight_match.append((p, abs(1 - ratio)))
            if weight_match:
                weight_match.sort(key=lambda x: x[1])
                brand_candidates = [p for p, _ in weight_match]

        # Name match
        ana_name_n = normalize(ana_name)
        min_score = 0.45 if weight_available else 0.65
        best = None
        best_score = 0.0
        for p in brand_candidates:
            p_name_n = normalize(p.get("product_name") or "")
            if not p_name_n:
                continue
            score = SequenceMatcher(None, ana_name_n, p_name_n).ratio()
            if score > best_score:
                best_score = score
                best = p

        if best and best_score >= min_score:
            # Price check
            ana_mrp = parse_num(ana_sku.get("Mrp"))
            sam_mrp = parse_num(best.get("mrp"))
            if ana_mrp and sam_mrp and ana_mrp > 0 and sam_mrp > 0:
                if abs(ana_mrp - sam_mrp) / ana_mrp > 0.25:
                    best = None  # fall through to Path B
            if best:
                # EAN check
                ic = ana_sku.get("Item_Code", "")
                apna_ean = EAN_MAP.get(str(ic), "")
                sam_ean = str(best.get("barcode") or best.get("ean") or "").strip()
                if apna_ean and sam_ean and len(sam_ean) >= 8 and apna_ean != sam_ean:
                    best = None
                if best:
                    return best, "cascaded", best_score

    # ─── PATH B: Weight + MRP → Name (brand bypass, catches cross-brand matches) ────
    ana_name_n = normalize(ana_name) if ana_name else ""
    ana_mrp = parse_num(ana_sku.get("Mrp"))
    weight_available = bool(ana_uv and ana_unit)

    if not weight_available or not ana_name_n:
        return None, "no_weight_or_name", 0.0

    ana_base_val, ana_base_unit = to_base_unit(ana_uv, ana_unit)
    if ana_base_val <= 0:
        return None, "no_weight", 0.0

    # Filter by weight first (fast — narrows 12k → ~200)
    weight_candidates = []
    for p in sam_products:
        p_uv, p_unit = parse_unit(p.get("unit") or "")
        if not p_uv or not p_unit or not units_compatible(ana_unit, p_unit):
            continue
        p_base_val, _ = to_base_unit(p_uv, p_unit)
        if p_base_val > 0:
            ratio = p_base_val / ana_base_val
            if 0.85 <= ratio <= 1.15:
                weight_candidates.append(p)

    if not weight_candidates:
        return None, "no_weight", 0.0

    # MRP filter (±25%) — MANDATORY for Path B (no brand safety net)
    if not ana_mrp or ana_mrp <= 0:
        return None, "no_mrp_for_pathb", 0.0
    mrp_filtered = []
    for p in weight_candidates:
        p_mrp = parse_num(p.get("mrp"))
        if p_mrp and p_mrp > 0:
            if abs(p_mrp - ana_mrp) / ana_mrp <= 0.25:
                mrp_filtered.append(p)
    if not mrp_filtered:
        return None, "no_mrp_match_pathb", 0.0
    weight_candidates = mrp_filtered

    # Name match on weight+MRP filtered set (strict — no brand safety net)
    best = None
    best_score = 0.0
    for p in weight_candidates:
        p_name_n = normalize(p.get("product_name") or "")
        if not p_name_n:
            continue
        score = SequenceMatcher(None, ana_name_n, p_name_n).ratio()
        if score > best_score:
            best_score = score
            best = p

    if not best or best_score < 0.70:
        return None, "no_name_score_pathb", best_score

    # EAN check
    ic = ana_sku.get("Item_Code", "")
    apna_ean = EAN_MAP.get(str(ic), "")
    sam_ean = str(best.get("barcode") or best.get("ean") or "").strip()
    if apna_ean and sam_ean and len(sam_ean) >= 8 and apna_ean != sam_ean:
        return None, "ean_mismatch", best_score

    # ─── STAGE 2f: EAN cross-verification ──
    # If both Apna and SAM product have barcodes, they MUST match
    ic = ana_sku.get("Item_Code", "")
    apna_ean = EAN_MAP.get(str(ic), "")
    sam_ean = str(best.get("barcode") or best.get("ean") or "").strip()
    if apna_ean and sam_ean and len(sam_ean) >= 8:
        if apna_ean != sam_ean:
            if debug:
                print(f"    stage 2f → rejected: EAN mismatch ({apna_ean} != {sam_ean})")
            return None, "ean_mismatch", best_score

    return best, "cascaded", best_score


# ── Main ────────────────────────────────────────────────────────

def main(pincode: str, platform: str = "blinkit"):
    load_ean_map()
    # Platform-aware field names
    PLATFORM_FIELDS = {
        "blinkit": {"product_id": "Blinkit_Product_Id", "selling_price": "Blinkit_Selling_Price",
                     "item_name": "Blinkit_Item_Name", "status": "Blinkit_Status"},
        "jiomart": {"product_id": "Jiomart_Product_Id", "selling_price": "Jiomart_Selling_Price",
                     "item_name": "Jiomart_Item_Name", "status": "Jiomart_Status"},
    }
    pf = PLATFORM_FIELDS.get(platform, PLATFORM_FIELDS["blinkit"])

    ana_path = latest_file("anakin", f"{platform}_{pincode}_*.json")
    sam_path = None
    for p in sorted((PROJECT_ROOT / "data" / "sam").glob(f"{platform}_{pincode}_*.json"), reverse=True):
        if "pdp" not in p.name and "category" not in p.name:
            sam_path = p
            break

    # Category products — PRIMARY search pool (from category discovery)
    cat_path = None
    for p in sorted((PROJECT_ROOT / "data" / "sam").glob(f"{platform}_category_{pincode}_*.json"), reverse=True):
        cat_path = p
        break

    # AM product master — fallback input when Anakin not available
    am_path = PROJECT_ROOT / "data" / "am_product_master.json"

    has_anakin = ana_path is not None
    has_sam = sam_path is not None
    has_category = cat_path is not None
    has_am = am_path.exists()

    jm_master_path = PROJECT_ROOT / "data" / "jiomart_product_master.json"
    has_jm_master = platform == "jiomart" and jm_master_path.exists()

    if not has_sam and not has_category and not has_jm_master:
        print(f"[cascade] No SAM/category/master data for {platform} {pincode} — skipping", flush=True)
        sys.exit(0)

    print(f"[cascade] Platform: {platform}")
    if has_anakin:
        print(f"[cascade] Anakin: {ana_path.name}")
    else:
        print(f"[cascade] Anakin: not available — using AM master")
    if has_sam:
        print(f"[cascade] SAM BFS: {sam_path.name}")
    if has_category:
        print(f"[cascade] Category: {cat_path.name}")

    # ── Build search pool: BFS + category products ──
    sam_products = []
    seen_pids = set()

    if has_sam:
        sam = json.load(open(sam_path))
        for p in sam.get("products", []):
            pid = str(p.get("product_id", ""))
            if pid and pid not in seen_pids:
                seen_pids.add(pid)
                sam_products.append(p)

    if has_category:
        cat = json.load(open(cat_path))
        cat_added = 0
        for p in cat.get("products", []):
            pid = str(p.get("product_id") or p.get("pid", ""))
            if pid and pid not in seen_pids:
                seen_pids.add(pid)
                # Normalize category product to match expected format
                sam_products.append({
                    "product_id": pid,
                    "product_url": p.get("product_url", f"https://blinkit.com/prn/x/prid/{pid}"),
                    "product_name": p.get("name", ""),
                    "brand": (p.get("name") or "").split()[0] if p.get("name") else "",
                    "price": p.get("price") or p.get("sp"),
                    "mrp": p.get("mrp"),
                    "unit": p.get("unit", ""),
                    "category": p.get("category", ""),
                    "in_stock": bool(p.get("inventory") or p.get("stock")),
                })
                cat_added += 1
        print(f"[cascade] Category products added to pool: {cat_added}")

    # Jiomart product master — permanent store with all products
    if has_jm_master:
        jm_master = json.load(open(jm_master_path))
        jm_added = 0
        for pid, p in jm_master.items():
            if pid not in seen_pids and p.get("last_sp"):
                seen_pids.add(pid)
                sam_products.append({
                    "product_id": pid,
                    "product_url": p.get("url", ""),
                    "product_name": p.get("name", ""),
                    "brand": p.get("brand", ""),
                    "price": p.get("last_sp"),
                    "mrp": p.get("last_mrp"),
                    "unit": p.get("unit", ""),
                    "in_stock": p.get("in_stock", True),
                })
                jm_added += 1
        print(f"[cascade] Jiomart master added to pool: {jm_added}")

    print(f"[cascade] Total search pool: {len(sam_products)} products")

    # ── Stage 2 input = Anakin NA SKUs + PDP failures + AM unmatched ──
    ana_records = []
    if has_anakin:
        ana = json.load(open(ana_path))
        ana_records = ana.get("records", [])

    na_skus = [r for r in ana_records
               if r.get(pf["product_id"]) in (None, "", "NA")]

    stage1_failed_codes: set[str] = set()
    pdp_compare_path = latest_file("comparisons", f"{platform}_pdp_{pincode}_*_compare.json")
    if pdp_compare_path:
        pdp_cmp = json.load(open(pdp_compare_path))
        for m in pdp_cmp.get("matches", []):
            ms = m.get("match_status")
            if ms in ("no_price_on_pdp", "scrape_error"):
                ic = m.get("item_code")
                if ic:
                    stage1_failed_codes.add(ic)
        print(f"[cascade] Stage 1 PDP failures loaded: {len(stage1_failed_codes)} from {pdp_compare_path.name}")

    stage1_failed_skus = [r for r in ana_records
                          if r.get("Item_Code") in stage1_failed_codes]

    # Also add AM products that have no PDP match yet (for category-based matching)
    am_unmatched_skus = []
    if has_am:
        am_map = json.load(open(am_path))
        pdp_ok_codes = set()
        pdp_files = sorted((PROJECT_ROOT / "data" / "sam").glob(f"{platform}_pdp_{pincode}_*.json"))
        if pdp_files:
            pdp_data = json.load(open(pdp_files[-1]))
            pdp_ok_codes = {p["item_code"] for p in pdp_data.get("products", [])
                           if p.get("status") == "ok" and p.get("item_code")}
        anakin_matched_codes = {r.get("Item_Code") for r in ana_records
                               if r.get(pf["product_id"]) not in (None, "", "NA")}
        already_in_input = {r.get("Item_Code") for r in na_skus + stage1_failed_skus}

        for ic, am in am_map.items():
            if ic in pdp_ok_codes or ic in anakin_matched_codes or ic in already_in_input:
                continue
            if am.get("master_category") not in ("STPLS", "FMCG", "FMCGF", "FMCGNF", "GM"):
                continue
            am_unmatched_skus.append({
                "Item_Code": ic,
                "Item_Name": am.get("display_name", ""),
                "Brand": am.get("brand", ""),
                "Product_Type": am.get("product_type", ""),
                "Unit_Value": am.get("unit_value"),
                "Unit": am.get("unit", ""),
                "Mrp": am.get("mrp"),
            })
        print(f"[cascade] AM unmatched (no PDP/Anakin): {len(am_unmatched_skus)}")

    input_skus = na_skus + stage1_failed_skus + am_unmatched_skus
    print(f"[cascade] Anakin NA SKUs:          {len(na_skus)}")
    print(f"[cascade] Stage 1 PDP failures:    {len(stage1_failed_skus)}")
    print(f"[cascade] AM unmatched:            {len(am_unmatched_skus)}")
    print(f"[cascade] Total Stage 2 input:     {len(input_skus)}")
    print(f"[cascade] SAM products (search pool): {len(sam_products)}")
    print()

    matched_skus = []
    unmatched_skus = []
    reasons = {}

    for ana_sku in input_skus:
        best, reason, score = find_match(ana_sku, sam_products)
        reasons[reason] = reasons.get(reason, 0) + 1

        record = {
            "item_code": ana_sku.get("Item_Code"),
            "anakin_name": ana_sku.get("Item_Name"),
            "anakin_brand": ana_sku.get("Brand"),
            "anakin_product_type": ana_sku.get("Product_Type"),
            "anakin_weight": f"{ana_sku.get('Unit_Value')} {ana_sku.get('Unit')}".strip(),
            "anakin_mrp": ana_sku.get("Mrp"),
            "cascade_reason": reason,
            "cascade_score": round(score, 3),
        }

        if best:
            record.update({
                "sam_product_id": best.get("product_id"),
                "sam_product_url": best.get("product_url"),
                "sam_product_name": best.get("product_name"),
                "sam_brand": best.get("brand"),
                "sam_unit": best.get("unit"),
                "sam_price": best.get("price"),
                "sam_mrp": best.get("mrp"),
            })
            matched_skus.append(record)
        else:
            unmatched_skus.append(record)

    print("=" * 60)
    print(f"STAGE 2 RESULT — cascade filter (pincode {pincode})")
    print("=" * 60)
    print(f"Total SKUs processed:       {len(input_skus)} (NA: {len(na_skus)}, Stage1 fail: {len(stage1_failed_skus)})")
    print(f"New mappings found:         {len(matched_skus)} "
          f"({len(matched_skus)/max(len(na_skus),1)*100:.1f}%)")
    print()
    print("Failure reasons:")
    for r, c in sorted(reasons.items(), key=lambda x: -x[1]):
        print(f"  {r:25s} {c}")
    print()

    if matched_skus:
        print("Sample new discoveries (top 5 by score):")
        for m in sorted(matched_skus, key=lambda x: -x["cascade_score"])[:5]:
            print(f"  [{m['cascade_score']:.2f}] {m['anakin_name']}  →  {m['sam_product_name']}")
            print(f"          sam price: {m['sam_price']}, unit: {m['sam_unit']}")

    # Save
    out_dir = PROJECT_ROOT / "data" / "comparisons"
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    out_path = out_dir / f"{platform}_cascade_{pincode}_{ts}.json"
    with open(out_path, "w") as f:
        json.dump({
            "pincode": pincode,
            "compared_at": datetime.now().isoformat(),
            "anakin_file": ana_path.name if has_anakin else "none",
            "sam_file": sam_path.name if has_sam else "none",
            "category_file": cat_path.name if has_category else "none",
            "metrics": {
                "na_skus": len(na_skus),
                "new_mappings": len(matched_skus),
                "unmatched": len(unmatched_skus),
                "reasons": reasons,
            },
            "new_mappings": matched_skus,
            "unmatched": unmatched_skus,
        }, f, indent=2, default=str)
    print(f"\nFull report: {out_path}")


if __name__ == "__main__":
    pincode = sys.argv[1] if len(sys.argv) > 1 else "834002"
    platform = sys.argv[2] if len(sys.argv) > 2 else "blinkit"
    main(pincode, platform)
