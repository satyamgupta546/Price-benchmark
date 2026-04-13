"""
Stage 3: Type-first cascade matcher with MRP filter.

Order: Product Type → Name token → Weight → MRP → best name match

Runs on SKUs that Stage 2 couldn't resolve. Looser on brand, stricter on MRP
— catches cases where SAM's brand field is dirty or Stage 2's strict brand
filter rejected valid matches. MRP as final filter catches variant mismatches
(e.g., Horlicks Chocolate Delight vs Horlicks Women's Plus — 104% MRP diff).

Usage:
    python3 scripts/stage3_match.py 834002
"""
import json
import re
import sys
from difflib import SequenceMatcher
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# ── Tunables ─────────────────────────────────────────────────────
MRP_TOLERANCE_PCT = 15.0        # Stage 3d: MRP filter tolerance
WEIGHT_TOLERANCE_RATIO = (0.8, 1.25)  # Stage 3c: weight filter
NAME_SCORE_MIN = 0.35           # Minimum name similarity to accept


# ── Normalization ────────────────────────────────────────────────

def normalize(s: str) -> str:
    if not s:
        return ""
    s = s.lower()
    s = re.sub(r"[^\w\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


STOPWORDS = {"the", "and", "of", "a", "an", "with", "for", "in", "on", "to",
             "pack", "pc", "pcs", "n", "by", "free", "new"}


def tokens(s: str) -> set[str]:
    """Significant tokens (≥3 chars, not stopwords, not pure numbers)."""
    return {
        t for t in normalize(s).split()
        if len(t) >= 3 and t not in STOPWORDS and not t.isdigit()
    }


# ── Unit parsing (same as stage 2) ───────────────────────────────

UNIT_ALIASES = {
    "g": "g", "gm": "g", "gms": "g", "gram": "g", "grams": "g",
    "kg": "kg", "kgs": "kg", "kilo": "kg", "kilogram": "kg",
    "ml": "ml", "mls": "ml",
    "l": "l", "ltr": "l", "ltrs": "l", "liter": "l", "litre": "l", "liters": "l", "litres": "l",
    "pc": "pc", "pcs": "pc", "piece": "pc", "pieces": "pc", "n": "pc",
    "unit": "pc", "units": "pc", "pack": "pc",
}


def parse_unit(text: str) -> tuple[float | None, str | None]:
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

    m = re.search(r"(\d+\.?\d*)\s*[x×]\s*(\d+\.?\d*)\s*(g|gm|kg|ml|l|ltr|pc|pcs|piece|n|unit|units|pack)", s)
    if m:
        try:
            return float(m.group(1)) * float(m.group(2)), UNIT_ALIASES.get(m.group(3), m.group(3))
        except ValueError:
            pass

    m = re.search(r"(\d+\.?\d*)\s*(g|gm|kg|ml|l|ltr|pc|pcs|piece|n|unit|units|pack)\b", s)
    if m:
        try:
            return float(m.group(1)), UNIT_ALIASES.get(m.group(2), m.group(2))
        except ValueError:
            pass
    return None, None


def to_base_unit(value: float, unit: str) -> tuple[float, str]:
    if unit == "kg":
        return value * 1000, "g"
    if unit == "l":
        return value * 1000, "ml"
    return value, unit


def units_compatible(u1: str, u2: str) -> bool:
    if not u1 or not u2:
        return False
    base1 = "g" if u1 in ("g", "kg") else ("ml" if u1 in ("ml", "l") else u1)
    base2 = "g" if u2 in ("g", "kg") else ("ml" if u2 in ("ml", "l") else u2)
    return base1 == base2


def parse_num(v):
    if v is None or str(v).strip().lower() in ("", "na", "nan", "null", "none"):
        return None
    try:
        s = str(v).replace("₹", "").replace("Rs.", "").replace("Rs", "").replace(",", "").strip()
        s = s.rstrip("/-").strip()
        return float(s)
    except (ValueError, TypeError):
        return None


def clean_str(v) -> str:
    """Return empty string for sentinel missing values (NA, nan, null, empty)."""
    if v is None:
        return ""
    s = str(v).strip()
    if s.lower() in ("", "na", "nan", "null", "none"):
        return ""
    return s


# ── Core matcher (type-first, MRP filter) ───────────────────────

def find_match(ana_sku: dict, sam_products: list[dict], debug: bool = False) -> tuple[dict | None, str, float]:
    """
    Cascade: type → name_token → weight → MRP → name_score.
    Returns (matched_product, reason, score).
    """
    ana_ptype = normalize(clean_str(ana_sku.get("Product_Type")))
    ana_name = clean_str(ana_sku.get("Blinkit_Item_Name")) or clean_str(ana_sku.get("Item_Name"))
    ana_name_tokens = tokens(ana_name)
    ana_brand_tokens = tokens(clean_str(ana_sku.get("Brand")))
    ana_uv_raw = ana_sku.get("Unit_Value")
    ana_unit_raw = clean_str(ana_sku.get("Unit"))
    ana_mrp = parse_num(ana_sku.get("Mrp"))

    ana_uv = parse_num(ana_uv_raw)
    ana_unit = UNIT_ALIASES.get(normalize(ana_unit_raw), normalize(ana_unit_raw))

    # ─── STAGE 3a: Product Type filter (token overlap on category/name) ──
    # If ptype present, STRICT: if no candidate shares a type token, reject.
    # If ptype missing, pass through.
    candidates = sam_products
    if ana_ptype:
        ptype_tokens = set(ana_ptype.split())
        ptype_tokens = {t for t in ptype_tokens if len(t) >= 3 and t not in STOPWORDS}
        if ptype_tokens:
            filtered = []
            for p in candidates:
                p_pool = tokens(p.get("category") or "") | tokens(p.get("product_name") or "")
                if ptype_tokens & p_pool:
                    filtered.append(p)
            if not filtered:
                return None, "no_type_match", 0.0
            candidates = filtered
    if debug:
        print(f"    3a type → {len(candidates)} candidates")

    # ─── STAGE 3b: Name token overlap (specific product identity) ─────
    # STRICT: require at least 1 significant name/brand token overlap.
    combined_tokens = ana_name_tokens | ana_brand_tokens
    if combined_tokens:
        filtered = []
        for p in candidates:
            p_tokens = tokens(p.get("product_name") or "") | tokens(p.get("brand") or "")
            if combined_tokens & p_tokens:
                filtered.append(p)
        if not filtered:
            return None, "no_name_token", 0.0
        candidates = filtered
    if debug:
        print(f"    3b name-token → {len(candidates)} candidates")

    # ─── STAGE 3c: Weight filter (±20% tolerance) ─────────────────────
    if ana_uv and ana_unit:
        ana_base_val, _ = to_base_unit(ana_uv, ana_unit)
        filtered = []
        for p in candidates:
            p_uv, p_unit = parse_unit(p.get("unit") or "")
            if p_uv and p_unit and units_compatible(ana_unit, p_unit):
                p_base_val, _ = to_base_unit(p_uv, p_unit)
                if p_base_val > 0 and ana_base_val > 0:
                    ratio = p_base_val / ana_base_val
                    if WEIGHT_TOLERANCE_RATIO[0] <= ratio <= WEIGHT_TOLERANCE_RATIO[1]:
                        filtered.append((p, abs(1 - ratio)))
        if filtered:
            filtered.sort(key=lambda x: x[1])
            candidates = [p for p, _ in filtered]
    if debug:
        print(f"    3c weight → {len(candidates)} candidates")

    # ─── STAGE 3d: MRP filter (±15% tolerance) ────────────────────────
    # This is the KEY step — catches variant mismatches where name+weight match
    # but it's actually a different SKU (e.g., Horlicks Chocolate vs Women's Plus).
    if ana_mrp:
        filtered = []
        for p in candidates:
            p_mrp = parse_num(p.get("mrp")) or parse_num(p.get("price"))
            if p_mrp and p_mrp > 0:
                diff_pct = abs(p_mrp - ana_mrp) / ana_mrp * 100
                if diff_pct <= MRP_TOLERANCE_PCT:
                    filtered.append((p, diff_pct))
        if filtered:
            filtered.sort(key=lambda x: x[1])
            candidates = [p for p, _ in filtered]
        elif candidates:
            # MRP filter rejected everything — this is a rejection signal
            return None, "mrp_rejected", 0.0
    if debug:
        print(f"    3d mrp → {len(candidates)} candidates")

    # ─── Final: best name similarity ───────────────────────────────
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

    if best and best_score >= NAME_SCORE_MIN:
        return best, "stage3_type_mrp", best_score
    return None, "no_name_score", best_score


# ── Main ────────────────────────────────────────────────────────

def latest_file(subdir: str, pattern: str) -> Path | None:
    cands = sorted((PROJECT_ROOT / "data" / subdir).glob(pattern))
    return cands[-1] if cands else None


def main(pincode: str, platform: str = "blinkit"):
    PLATFORM_FIELDS = {
        "blinkit": {"product_id": "Blinkit_Product_Id"},
        "jiomart": {"product_id": "Jiomart_Product_Id"},
    }
    pf = PLATFORM_FIELDS.get(platform, PLATFORM_FIELDS["blinkit"])

    ana_path = latest_file("anakin", f"{platform}_{pincode}_*.json")
    stage2_path = latest_file("comparisons", f"{platform}_cascade_{pincode}_*.json")

    sam_path = None
    for p in sorted((PROJECT_ROOT / "data" / "sam").glob(f"{platform}_{pincode}_*.json"), reverse=True):
        if "pdp" not in p.name:
            sam_path = p
            break

    if not ana_path:
        print(f"[stage3] ERROR: no Anakin {platform} file for {pincode}", file=sys.stderr)
        sys.exit(1)
    if not sam_path:
        print(f"[stage3] ERROR: no SAM {platform} BFS scrape for {pincode}", file=sys.stderr)
        sys.exit(1)

    print(f"[stage3] Platform: {platform}")
    print(f"[stage3] Anakin:   {ana_path.name}")
    print(f"[stage3] SAM:     {sam_path.name}")
    print(f"[stage3] Stage 2:  {stage2_path.name if stage2_path else 'NONE'}")

    ana = json.load(open(ana_path))
    sam = json.load(open(sam_path))

    if stage2_path:
        stage2 = json.load(open(stage2_path))
        stage2_unmatched_codes = {r["item_code"] for r in stage2.get("unmatched", [])}
        stage2_weak_codes = {r["item_code"] for r in stage2.get("new_mappings", [])
                             if r.get("cascade_score", 0) < 0.6}
        retry_codes = stage2_unmatched_codes | stage2_weak_codes
        input_skus = [r for r in ana["records"]
                      if (r.get(pf["product_id"]) in (None, "", "NA"))
                      and (r.get("Item_Code") in retry_codes)]
    else:
        input_skus = [r for r in ana["records"]
                      if r.get(pf["product_id"]) in (None, "", "NA")]

    print(f"[stage3] Input SKUs (leftover from Stage 2): {len(input_skus)}")
    print(f"[stage3] SAM pool: {len(sam['products'])}")
    print()

    matched = []
    unmatched = []
    reasons = {}

    for sku in input_skus:
        best, reason, score = find_match(sku, sam["products"])
        reasons[reason] = reasons.get(reason, 0) + 1

        record = {
            "item_code": sku.get("Item_Code"),
            "anakin_name": sku.get("Item_Name"),
            "anakin_brand": sku.get("Brand"),
            "anakin_product_type": sku.get("Product_Type"),
            "anakin_weight": f"{sku.get('Unit_Value')} {sku.get('Unit')}".strip(),
            "anakin_mrp": sku.get("Mrp"),
            "stage3_reason": reason,
            "stage3_score": round(score, 3),
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
            matched.append(record)
        else:
            unmatched.append(record)

    print("=" * 60)
    print(f"STAGE 3 RESULT — type/MRP cascade (pincode {pincode})")
    print("=" * 60)
    print(f"Input SKUs:            {len(input_skus)}")
    print(f"New matches found:     {len(matched)} ({len(matched)/max(len(input_skus),1)*100:.1f}%)")
    print()
    print("Reason breakdown:")
    for r, c in sorted(reasons.items(), key=lambda x: -x[1]):
        print(f"  {r:25s} {c}")
    print()

    if matched:
        print("Sample Stage 3 matches (top 5 by score):")
        for m in sorted(matched, key=lambda x: -x["stage3_score"])[:5]:
            print(f"  [{m['stage3_score']:.2f}] {m['anakin_name']}")
            print(f"          → {m['sam_product_name']}")
            print(f"          Anakin MRP ₹{m['anakin_mrp']} | SAM ₹{m['sam_price']}")

    out_dir = PROJECT_ROOT / "data" / "comparisons"
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    out_path = out_dir / f"{platform}_stage3_{pincode}_{ts}.json"
    with open(out_path, "w") as f:
        json.dump({
            "pincode": pincode,
            "compared_at": datetime.now().isoformat(),
            "anakin_file": ana_path.name,
            "sam_file": sam_path.name,
            "stage2_file": stage2_path.name if stage2_path else None,
            "metrics": {
                "input_skus": len(input_skus),
                "new_matches": len(matched),
                "unmatched": len(unmatched),
                "reasons": reasons,
            },
            "new_mappings": matched,
            "unmatched": unmatched,
        }, f, indent=2, default=str)
    print(f"\nFull report: {out_path}")


if __name__ == "__main__":
    pincode = sys.argv[1] if len(sys.argv) > 1 else "834002"
    platform = sys.argv[2] if len(sys.argv) > 2 else "blinkit"
    main(pincode, platform)
