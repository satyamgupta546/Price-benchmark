"""
Compare SAM's Blinkit scrape output against Anakin's reference data.

Inputs:
  - data/anakin/blinkit_<pincode>_<date>.json   (Anakin ground truth)
  - data/sam/blinkit_<pincode>_<timestamp>.json (latest SAM scrape)

Outputs:
  - data/comparisons/blinkit_<pincode>_<timestamp>_compare.json (full diff)
  - Console: summary metrics (coverage %, price match %, mapping accuracy %)

Match criteria:
  An Anakin SKU is considered "matched" by SAM if SAM has a product where
  fuzzy(brand+name) score >= 0.6 AND (no pack_size or pack_size matches).

Usage:
    python3 scripts/compare_sam_vs_anakin.py 834002
"""
import json
import re
import sys
from difflib import SequenceMatcher
from pathlib import Path
from datetime import datetime


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def normalize_text(s: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace."""
    if not s:
        return ""
    s = s.lower()
    s = re.sub(r"[^\w\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def name_similarity(a: str, b: str) -> float:
    a_n = normalize_text(a)
    b_n = normalize_text(b)
    if not a_n or not b_n:
        return 0.0
    return SequenceMatcher(None, a_n, b_n).ratio()


def parse_pack(text: str):
    """Extract numeric pack value + unit from text. Returns (value, unit) or (None, None)."""
    if not text:
        return None, None
    text = str(text).lower()
    # Look for patterns like "500g", "1.5 kg", "200 ml", "1 ltr", "12 pcs"
    m = re.search(r"(\d+\.?\d*)\s*(g|gm|kg|ml|l|ltr|liter|litre|pc|pcs|pack|n|unit|units)\b", text)
    if not m:
        return None, None
    val = float(m.group(1))
    unit = m.group(2)
    # Normalize unit
    if unit in ("g", "gm"):
        unit = "g"
    elif unit in ("kg",):
        val *= 1000
        unit = "g"
    elif unit in ("ml",):
        unit = "ml"
    elif unit in ("l", "ltr", "liter", "litre"):
        val *= 1000
        unit = "ml"
    elif unit in ("pc", "pcs", "pack", "n", "unit", "units"):
        unit = "pc"
    return val, unit


def latest_anakin_file(pincode: str) -> Path | None:
    candidates = sorted((PROJECT_ROOT / "data" / "anakin").glob(f"blinkit_{pincode}_*.json"))
    return candidates[-1] if candidates else None


def latest_sam_file(pincode: str) -> Path | None:
    candidates = sorted((PROJECT_ROOT / "data" / "sam").glob(f"blinkit_{pincode}_*.json"))
    return candidates[-1] if candidates else None


def main(pincode: str):
    ana_path = latest_anakin_file(pincode)
    sam_path = latest_sam_file(pincode)

    if not ana_path:
        print(f"[compare] ERROR: no Anakin file found for pincode {pincode}")
        sys.exit(1)
    if not sam_path:
        print(f"[compare] ERROR: no SAM file found for pincode {pincode}")
        sys.exit(1)

    print(f"[compare] Anakin file: {ana_path.name}")
    print(f"[compare] SAM file:   {sam_path.name}")

    anakin = json.load(open(ana_path))
    sam = json.load(open(sam_path))

    anakin_records = anakin["records"]
    sam_products = sam["products"]

    print(f"[compare] Anakin total SKUs:        {len(anakin_records)}")
    print(f"[compare] Anakin Blinkit-mapped:    {sum(1 for r in anakin_records if r.get('Blinkit_Product_Id') not in (None, '', 'NA'))}")
    print(f"[compare] SAM scraped products:    {len(sam_products)}")
    print()

    # Filter Anakin to only mapped SKUs (these are the ones we should match)
    anakin_mapped = [
        r for r in anakin_records
        if r.get("Blinkit_Product_Id") not in (None, "", "NA")
    ]

    # ── Build TWO indexes:
    #    1. By exact product_id (Blinkit prid) — primary, exact join
    #    2. By name tokens — fallback fuzzy matching for products without product_id
    sam_index = []
    sam_by_pid: dict[str, int] = {}
    sam_by_brand_token: dict[str, list[int]] = {}
    sam_with_id_count = 0
    for idx, p in enumerate(sam_products):
        brand = (p.get("brand") or "").strip()
        name = (p.get("product_name") or "").strip()
        unit = p.get("unit") or ""
        pid = (p.get("product_id") or "").strip()
        purl = (p.get("product_url") or "").strip()
        full_text = f"{brand} {name} {unit}".strip()
        norm = normalize_text(full_text)
        first_tokens = norm.split()[:3]
        entry = {
            "brand": brand,
            "name": name,
            "unit": unit,
            "product_id": pid,
            "product_url": purl,
            "full_text": full_text,
            "norm": norm,
            "tokens_set": set(norm.split()),
            "price": p.get("price"),
            "mrp": p.get("mrp"),
        }
        sam_index.append(entry)
        if pid:
            sam_with_id_count += 1
            sam_by_pid[pid] = idx
        for tok in first_tokens:
            if len(tok) >= 3:
                sam_by_brand_token.setdefault(tok, []).append(idx)

    print(f"[compare] SAM with product_id: {sam_with_id_count}/{len(sam_products)}")
    print()

    # For each Anakin mapped SKU, find best SAM match
    matches = []
    not_found = []
    matched_by_id = 0
    matched_by_fuzzy = 0

    for ar in anakin_mapped:
        ana_brand = (ar.get("Brand") or "").strip()
        ana_name = (ar.get("Item_Name") or "").strip()
        ana_blinkit_name = (ar.get("Blinkit_Item_Name") or "").strip()
        ana_unit = (ar.get("Unit") or "").strip()
        ana_uv = (ar.get("Unit_Value") or "").strip()
        ana_mrp = ar.get("Mrp")
        ana_blinkit_sp = ar.get("Blinkit_Selling_Price")
        ana_blinkit_id = (ar.get("Blinkit_Product_Id") or "").strip()

        record = {
            "item_code": ar.get("Item_Code"),
            "anakin_name": ana_name,
            "anakin_brand": ana_brand,
            "anakin_unit": f"{ana_uv} {ana_unit}".strip(),
            "anakin_mrp": ana_mrp,
            "anakin_blinkit_name": ana_blinkit_name,
            "anakin_blinkit_sp": ana_blinkit_sp,
            "anakin_blinkit_id": ana_blinkit_id,
            "anakin_status": ar.get("Blinkit_Status"),
        }

        # ── PASS 1: Exact match by product_id (Blinkit prid)
        best_match = None
        best_score = 0.0
        match_method = None
        if ana_blinkit_id and ana_blinkit_id in sam_by_pid:
            best_match = sam_index[sam_by_pid[ana_blinkit_id]]
            best_score = 1.0
            match_method = "id_exact"
            matched_by_id += 1
        else:
            # ── PASS 2: Fuzzy fallback (only for SKUs not matched by ID)
            search_text = ana_blinkit_name if ana_blinkit_name else ana_name
            full_query = f"{ana_brand} {search_text}".strip()
            norm_query = normalize_text(full_query)
            query_tokens = set(norm_query.split())

            candidate_idxs: set[int] = set()
            for tok in query_tokens:
                if len(tok) >= 3 and tok in sam_by_brand_token:
                    candidate_idxs.update(sam_by_brand_token[tok])
            candidates = [sam_index[i] for i in candidate_idxs] if candidate_idxs else sam_index

            for h in candidates:
                if len(query_tokens & h["tokens_set"]) == 0:
                    continue
                score = name_similarity(full_query, h["full_text"])
                if ana_brand and ana_brand.lower() in h["norm"]:
                    score = min(1.0, score + 0.1)
                if score > best_score:
                    best_score = score
                    best_match = h
            if best_match and best_score >= 0.5:
                match_method = "fuzzy"
                matched_by_fuzzy += 1

        if best_match and best_score >= 0.5:
            # Compute price diff
            price_diff_pct = None
            try:
                ana_sp = float(str(ana_blinkit_sp).replace(",", ""))
                h_price = float(best_match["price"]) if best_match["price"] else None
                if h_price and ana_sp:
                    price_diff_pct = abs(h_price - ana_sp) / ana_sp * 100
            except (ValueError, TypeError):
                pass

            record.update({
                "matched": True,
                "match_method": match_method,
                "match_score": round(best_score, 3),
                "sam_product_id": best_match.get("product_id"),
                "sam_name": best_match["name"],
                "sam_brand": best_match["brand"],
                "sam_unit": best_match["unit"],
                "sam_price": best_match["price"],
                "sam_mrp": best_match["mrp"],
                "price_diff_pct": round(price_diff_pct, 1) if price_diff_pct is not None else None,
            })
            matches.append(record)
        else:
            record.update({
                "matched": False,
                "match_score": round(best_score, 3) if best_match else 0.0,
                "best_candidate": best_match["name"] if best_match else None,
            })
            not_found.append(record)

    # Compute metrics
    total_anakin_mapped = len(anakin_mapped)
    total_matched = len(matches)
    coverage_pct = total_matched / total_anakin_mapped * 100 if total_anakin_mapped else 0

    # Price-match accuracy: of matched ones with both prices, how many within ±5%?
    price_compared = [m for m in matches if m.get("price_diff_pct") is not None]
    price_match_5pct = [m for m in price_compared if m["price_diff_pct"] <= 5]
    price_match_10pct = [m for m in price_compared if m["price_diff_pct"] <= 10]
    price_match_pct_5 = len(price_match_5pct) / len(price_compared) * 100 if price_compared else 0
    price_match_pct_10 = len(price_match_10pct) / len(price_compared) * 100 if price_compared else 0

    # Match score distribution buckets
    score_buckets = {"0.9+": 0, "0.7-0.9": 0, "0.5-0.7": 0}
    for m in matches:
        s = m["match_score"]
        if s >= 0.9:
            score_buckets["0.9+"] += 1
        elif s >= 0.7:
            score_buckets["0.7-0.9"] += 1
        else:
            score_buckets["0.5-0.7"] += 1

    print("=" * 60)
    print(f"COMPARISON: SAM vs Anakin (Blinkit, pincode {pincode})")
    print("=" * 60)
    print(f"Anakin Blinkit-mapped SKUs: {total_anakin_mapped}")
    print(f"SAM scraped products:      {len(sam_products)} ({sam_with_id_count} with product_id)")
    print()
    print(f"COVERAGE:           {total_matched}/{total_anakin_mapped} = {coverage_pct:.1f}%")
    print(f"  by exact ID:      {matched_by_id}")
    print(f"  by fuzzy:         {matched_by_fuzzy}")
    print(f"  Score 0.9+:       {score_buckets['0.9+']}")
    print(f"  Score 0.7-0.9:    {score_buckets['0.7-0.9']}")
    print(f"  Score 0.5-0.7:    {score_buckets['0.5-0.7']}")
    print()
    print(f"PRICE MATCH (vs Anakin's Blinkit_Selling_Price):")
    print(f"  Within ±5%:       {len(price_match_5pct)}/{len(price_compared)} = {price_match_pct_5:.1f}%")
    print(f"  Within ±10%:      {len(price_match_10pct)}/{len(price_compared)} = {price_match_pct_10:.1f}%")
    print(f"  Note: only {len(price_compared)} matched SKUs had Anakin SP available; rest were NA")
    print()
    # Drill into ID-matched only (the gold-standard subset)
    id_matches = [m for m in matches if m.get("match_method") == "id_exact"]
    id_with_price = [m for m in id_matches if m.get("price_diff_pct") is not None]
    id_5pct = sum(1 for m in id_with_price if m["price_diff_pct"] <= 5)
    id_10pct = sum(1 for m in id_with_price if m["price_diff_pct"] <= 10)
    if id_with_price:
        print(f"PRICE MATCH (ID-MATCHED ONLY — gold standard):")
        print(f"  Within ±5%:       {id_5pct}/{len(id_with_price)} = {id_5pct/len(id_with_price)*100:.1f}%")
        print(f"  Within ±10%:      {id_10pct}/{len(id_with_price)} = {id_10pct/len(id_with_price)*100:.1f}%")
        print()

    # Save full report
    out_dir = PROJECT_ROOT / "data" / "comparisons"
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    out_path = out_dir / f"blinkit_{pincode}_{ts}_compare.json"

    report = {
        "pincode": pincode,
        "compared_at": datetime.now().isoformat(),
        "anakin_file": ana_path.name,
        "sam_file": sam_path.name,
        "metrics": {
            "anakin_mapped_skus": total_anakin_mapped,
            "sam_scraped_count": len(sam_products),
            "sam_with_product_id": sam_with_id_count,
            "coverage_count": total_matched,
            "coverage_pct": round(coverage_pct, 1),
            "matched_by_id": matched_by_id,
            "matched_by_fuzzy": matched_by_fuzzy,
            "score_buckets": score_buckets,
            "price_compared": len(price_compared),
            "price_match_5pct": len(price_match_5pct),
            "price_match_10pct": len(price_match_10pct),
            "price_match_pct_5": round(price_match_pct_5, 1),
            "price_match_pct_10": round(price_match_pct_10, 1),
            "id_match_with_price": len(id_with_price) if id_with_price else 0,
            "id_match_price_5pct": id_5pct if id_with_price else 0,
            "id_match_price_10pct": id_10pct if id_with_price else 0,
        },
        "matches": matches,
        "not_found": not_found,
    }
    with open(out_path, "w") as f:
        json.dump(report, f, indent=2, default=str)

    print(f"Full report saved to: {out_path}")

    # Sample output
    print()
    print("=" * 60)
    print("SAMPLE MATCHES (top 5 by score):")
    print("=" * 60)
    for m in sorted(matches, key=lambda x: -x["match_score"])[:5]:
        print(f"  [{m['match_score']:.2f}] {m['anakin_name']}")
        print(f"         → {m['sam_name']}")
        print(f"         Anakin SP: {m['anakin_blinkit_sp']} | SAM: {m['sam_price']}"
              + (f" | diff: {m['price_diff_pct']}%" if m.get('price_diff_pct') is not None else ""))

    print()
    print("=" * 60)
    print("SAMPLE NOT-FOUND (5 random):")
    print("=" * 60)
    for nf in not_found[:5]:
        print(f"  {nf['anakin_name']} (brand: {nf['anakin_brand']}, unit: {nf['anakin_unit']})")
        print(f"     Best candidate: {nf.get('best_candidate', '-')} (score {nf['match_score']:.2f})")


if __name__ == "__main__":
    pincode = sys.argv[1] if len(sys.argv) > 1 else "834002"
    main(pincode)
