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

    # ─── STAGE 2a: Brand filter (strict) ────────────
    if not ana_brand:
        return None, "no_anakin_brand", 0.0

    candidates = []
    for p in sam_products:
        p_brand = normalize_brand(p.get("brand") or "")
        if p_brand and p_brand == ana_brand:
            candidates.append(p)

    if not candidates:
        return None, "no_brand", 0.0

    if debug:
        print(f"    stage 2a → {len(candidates)} candidates by brand '{ana_brand}'")

    # ─── STAGE 2b: Product Type token overlap (loose) ──
    if ana_ptype:
        pt_tokens = set(ana_ptype.split())
        filtered = []
        for p in candidates:
            p_cat_tokens = tokens(p.get("category") or "")
            p_name_tokens = tokens(p.get("product_name") or "")
            if pt_tokens & (p_cat_tokens | p_name_tokens):
                filtered.append(p)
        if filtered:
            candidates = filtered
            if debug:
                print(f"    stage 2b → {len(candidates)} candidates by product_type overlap")

    # ─── STAGE 2c: Weight filter (±10% tolerance) ────
    weight_available = bool(ana_uv and ana_unit)
    if weight_available:
        ana_base_val, ana_base_unit = to_base_unit(ana_uv, ana_unit)
        weight_match = []
        for p in candidates:
            p_uv, p_unit = parse_unit(p.get("unit") or "")
            if p_uv and p_unit and units_compatible(ana_unit, p_unit):
                p_base_val, _ = to_base_unit(p_uv, p_unit)
                if p_base_val > 0 and ana_base_val > 0:
                    ratio = p_base_val / ana_base_val
                    if 0.9 <= ratio <= 1.1:
                        weight_match.append((p, abs(1 - ratio)))
        if weight_match:
            weight_match.sort(key=lambda x: x[1])
            candidates = [p for p, _ in weight_match]
            if debug:
                print(f"    stage 2c → {len(candidates)} candidates by weight filter")
        else:
            # No weight-compatible candidates — reject to avoid sachet→family pack mismatches
            return None, "no_weight", 0.0

    # ─── STAGE 2d: Name fuzzy match on filtered set ──
    # When weight is NA, require HIGHER name score (0.70) to compensate
    min_name_score = 0.55 if weight_available else 0.70
    ana_name_n = normalize(ana_name)
    best = None
    best_score = 0.0
    for p in candidates:
        p_name_n = normalize(p.get("product_name") or "")
        if not p_name_n:
            continue
        score = SequenceMatcher(None, ana_name_n, p_name_n).ratio()
        if score > best_score:
            best_score = score
            best = p

    if not best or best_score < min_name_score:
        return None, "no_name_score", best_score

    # ─── STAGE 2e: Price cross-check ──
    # Try MRP first, fall back to SP if MRP unavailable
    ana_mrp = parse_num(ana_sku.get("Mrp"))
    sam_mrp = parse_num(best.get("mrp"))
    ana_sp = parse_num(ana_sku.get("Blinkit_Selling_Price") or ana_sku.get("Jiomart_Selling_Price"))
    sam_sp = parse_num(best.get("price"))

    price_rejected = False
    if ana_mrp and sam_mrp and ana_mrp > 0 and sam_mrp > 0:
        mrp_diff = abs(ana_mrp - sam_mrp) / ana_mrp
        if mrp_diff > 0.15:
            price_rejected = True
    elif ana_sp and sam_sp and ana_sp > 0 and sam_sp > 0:
        # MRP unavailable — use SP as fallback (stricter: 25%)
        sp_diff = abs(ana_sp - sam_sp) / ana_sp
        if sp_diff > 0.25:
            price_rejected = True

    if price_rejected:
        if debug:
            print(f"    stage 2e → rejected: price mismatch")
        return None, "price_mismatch", best_score

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
        if "pdp" not in p.name:
            sam_path = p
            break

    if not ana_path:
        print(f"[cascade] No Anakin {platform} file for {pincode} — skipping", flush=True)
        sys.exit(0)
    if not sam_path:
        print(f"[cascade] No SAM {platform} BFS data for {pincode} — skipping", flush=True)
        sys.exit(0)

    print(f"[cascade] Platform: {platform}")
    print(f"[cascade] Anakin: {ana_path.name}")
    print(f"[cascade] SAM:   {sam_path.name}")

    ana = json.load(open(ana_path))
    sam = json.load(open(sam_path))

    # ── Stage 2 input = Anakin NA SKUs + Stage 1 PDP failures ──
    na_skus = [r for r in ana["records"]
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

    stage1_failed_skus = [r for r in ana["records"]
                          if r.get("Item_Code") in stage1_failed_codes]

    input_skus = na_skus + stage1_failed_skus
    print(f"[cascade] Anakin NA SKUs:          {len(na_skus)}")
    print(f"[cascade] Stage 1 PDP failures:    {len(stage1_failed_skus)}")
    print(f"[cascade] Total Stage 2 input:     {len(input_skus)}")
    print(f"[cascade] SAM products (search pool): {len(sam['products'])}")
    print()

    matched_skus = []
    unmatched_skus = []
    reasons = {}

    for ana_sku in input_skus:
        best, reason, score = find_match(ana_sku, sam["products"])
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
            "anakin_file": ana_path.name,
            "sam_file": sam_path.name,
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
