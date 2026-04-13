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
import re
import sys
from difflib import SequenceMatcher
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


# ── Text normalization ──────────────────────────────────────────

def normalize(s: str) -> str:
    if not s:
        return ""
    s = s.lower()
    s = re.sub(r"[^\w\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def tokens(s: str) -> set[str]:
    return set(normalize(s).split())


def clean_str(v) -> str:
    """Return empty string for sentinel missing values (NA, nan, null, empty)."""
    if v is None:
        return ""
    s = str(v).strip()
    if s.lower() in ("", "na", "nan", "null", "none"):
        return ""
    return s


def parse_num(v):
    """Parse number, handling NA/nan/null sentinels and ₹ / comma formatting."""
    if v is None:
        return None
    s = str(v).strip()
    if s.lower() in ("", "na", "nan", "null", "none"):
        return None
    # Strip common currency prefixes and separators
    s = s.replace("₹", "").replace("Rs.", "").replace("Rs", "").replace(",", "").strip()
    s = s.rstrip("/-").strip()
    try:
        return float(s)
    except (ValueError, TypeError):
        return None


# ── Unit parsing ────────────────────────────────────────────────

UNIT_ALIASES = {
    "g": "g", "gm": "g", "gms": "g", "gram": "g", "grams": "g",
    "kg": "kg", "kgs": "kg", "kilo": "kg", "kilogram": "kg", "kilograms": "kg",
    "ml": "ml", "mls": "ml", "millilitre": "ml", "milliliter": "ml",
    "l": "l", "ltr": "l", "ltrs": "l", "liter": "l", "litre": "l", "liters": "l", "litres": "l",
    "pc": "pc", "pcs": "pc", "piece": "pc", "pieces": "pc", "n": "pc",
    "unit": "pc", "units": "pc", "pack": "pc",
}


def parse_unit(text: str) -> tuple[float | None, str | None]:
    """Parse a unit string like '500 g', '1.5 kg', '2 x 100ml' into (value, normalized_unit)."""
    if not text:
        return None, None
    s = str(text).strip().lower()

    # Handle half / fraction notation: "1/2 kg" → "0.5 kg"
    m_frac = re.match(r"^\s*(\d+)\s*/\s*(\d+)\s+(.+)$", s)
    if m_frac:
        try:
            num = float(m_frac.group(1))
            den = float(m_frac.group(2))
            if den != 0:
                s = f"{num/den} {m_frac.group(3)}"
        except ValueError:
            pass

    # Handle multipack "N x M unit" → return total (N * M)
    m = re.search(r"(\d+\.?\d*)\s*[x×]\s*(\d+\.?\d*)\s*(g|gm|kg|ml|l|ltr|pc|pcs|piece|n|unit|units|pack)", s)
    if m:
        try:
            count = float(m.group(1))
            each = float(m.group(2))
            unit = UNIT_ALIASES.get(m.group(3), m.group(3))
            return count * each, unit
        except ValueError:
            pass

    # Single pack "500 g"
    m = re.search(r"(\d+\.?\d*)\s*(g|gm|kg|ml|l|ltr|pc|pcs|piece|n|unit|units|pack)\b", s)
    if m:
        try:
            val = float(m.group(1))
            unit = UNIT_ALIASES.get(m.group(2), m.group(2))
            return val, unit
        except ValueError:
            pass

    return None, None


def to_base_unit(value: float, unit: str) -> tuple[float, str]:
    """Convert to a canonical base: g / ml / pc."""
    if unit == "kg":
        return value * 1000, "g"
    if unit == "l":
        return value * 1000, "ml"
    return value, unit


def units_compatible(u1: str, u2: str) -> bool:
    """True if the two units are comparable (same base family)."""
    if not u1 or not u2:
        return False
    base1 = "g" if u1 in ("g", "kg") else ("ml" if u1 in ("ml", "l") else u1)
    base2 = "g" if u2 in ("g", "kg") else ("ml" if u2 in ("ml", "l") else u2)
    return base1 == base2


# ── Brand normalization ─────────────────────────────────────────

BRAND_STOPWORDS = {"private", "limited", "ltd", "pvt", "company", "co", "the", "and"}


def normalize_brand(b: str) -> str:
    if not b:
        return ""
    s = normalize(b)
    toks = [t for t in s.split() if t not in BRAND_STOPWORDS]
    return " ".join(toks)


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

    # ─── STAGE 2c: Weight filter (±20% tolerance) ────
    if ana_uv and ana_unit:
        ana_base_val, ana_base_unit = to_base_unit(ana_uv, ana_unit)
        weight_match = []
        for p in candidates:
            p_uv, p_unit = parse_unit(p.get("unit") or "")
            if p_uv and p_unit and units_compatible(ana_unit, p_unit):
                p_base_val, _ = to_base_unit(p_uv, p_unit)
                if p_base_val > 0 and ana_base_val > 0:
                    ratio = p_base_val / ana_base_val
                    if 0.8 <= ratio <= 1.25:
                        weight_match.append((p, abs(1 - ratio)))
        if weight_match:
            weight_match.sort(key=lambda x: x[1])
            candidates = [p for p, _ in weight_match]
            if debug:
                print(f"    stage 2c → {len(candidates)} candidates by weight filter")

    # ─── STAGE 2d: Name fuzzy match on filtered set ──
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

    if best and best_score >= 0.4:
        return best, "cascaded", best_score
    return None, "no_name_score", best_score


# ── Main ────────────────────────────────────────────────────────

def latest_file(subdir: str, pattern: str) -> Path | None:
    cands = sorted((PROJECT_ROOT / "data" / subdir).glob(pattern))
    return cands[-1] if cands else None


def main(pincode: str, platform: str = "blinkit"):
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
        print(f"[cascade] ERROR: no Anakin {platform} file for {pincode}", file=sys.stderr)
        sys.exit(1)
    if not sam_path:
        print(f"[cascade] ERROR: no SAM {platform} BFS scrape for {pincode}", file=sys.stderr)
        sys.exit(1)

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
