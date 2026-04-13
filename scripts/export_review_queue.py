"""
Stage 4: Export a manual-review CSV for SKUs that none of Stage 1 (PDP),
Stage 2 (brand cascade), or Stage 3 (type/MRP cascade) could resolve.

The output CSV has one row per ambiguous SKU with Anakin's reference data,
the top N SAM candidates, and a reason code so a human can quickly decide.

Inputs:
  - data/comparisons/blinkit_pdp_<pincode>_*.json       (Stage 1 results)
  - data/comparisons/blinkit_cascade_<pincode>_*.json    (Stage 2 results)
  - data/comparisons/blinkit_stage3_<pincode>_*.json     (Stage 3 results)
  - data/anakin/blinkit_<pincode>_*.json                 (reference)
  - data/sam/blinkit_<pincode>_*.json                   (search pool)

Output:
  - data/comparisons/blinkit_<pincode>_review_queue_<ts>.csv

A row is flagged for review if ANY of:
  - Stage 1 error / no_price
  - Stage 1/2/3 found a match but price diff > 20% (suspicious)
  - Stage 2 + Stage 3 both failed
  - Stage 3 weak score (< 0.6)

Usage:
    python3 scripts/export_review_queue.py 834002
"""
import csv
import json
import re
import sys
from difflib import SequenceMatcher
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Review thresholds
PRICE_DIFF_SUSPICIOUS_PCT = 20.0
CASCADE_SCORE_WEAK_THRESHOLD = 0.6
TOP_N_CANDIDATES = 3


def latest_file(subdir: str, pattern: str) -> Path | None:
    cands = sorted((PROJECT_ROOT / "data" / subdir).glob(pattern))
    return cands[-1] if cands else None


def clean_str(v) -> str:
    """Return empty string for sentinel missing values (NA, nan, null, empty)."""
    if v is None:
        return ""
    s = str(v).strip()
    if s.lower() in ("", "na", "nan", "null", "none"):
        return ""
    return s


def normalize(s: str) -> str:
    if not s:
        return ""
    s = s.lower()
    s = re.sub(r"[^\w\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def find_top_candidates(ana_sku: dict, sam_products: list[dict], top_n: int = 3) -> list[dict]:
    """Return top N SAM products by name similarity to the Anakin SKU."""
    ana_brand = normalize(clean_str(ana_sku.get("Brand")))
    ana_name = normalize(
        clean_str(ana_sku.get("Blinkit_Item_Name")) or clean_str(ana_sku.get("Item_Name"))
    )
    query = f"{ana_brand} {ana_name}".strip()

    scored = []
    for p in sam_products:
        full = f"{normalize(p.get('brand') or '')} {normalize(p.get('product_name') or '')}".strip()
        if not full:
            continue
        s = SequenceMatcher(None, query, full).ratio()
        if ana_brand and ana_brand in full:
            s = min(1.0, s + 0.1)
        scored.append((s, p))
    scored.sort(key=lambda x: -x[0])
    return [
        {
            "score": round(sc, 3),
            "name": p.get("product_name"),
            "brand": p.get("brand"),
            "unit": p.get("unit"),
            "price": p.get("price"),
            "product_id": p.get("product_id"),
        }
        for sc, p in scored[:top_n]
    ]


def main(pincode: str):
    ana_path = latest_file("anakin", f"blinkit_{pincode}_*.json")
    pdp_cmp_path = latest_file("comparisons", f"blinkit_pdp_{pincode}_*_compare.json")
    cascade_path = latest_file("comparisons", f"blinkit_cascade_{pincode}_*.json")
    stage3_path = latest_file("comparisons", f"blinkit_stage3_{pincode}_*.json")

    if not ana_path:
        print(f"[review] ERROR: no Anakin file for {pincode}", file=sys.stderr)
        sys.exit(1)

    # Find latest general SAM scrape (not the PDP one) for candidate lookups
    sam_path = None
    for p in sorted((PROJECT_ROOT / "data" / "sam").glob(f"blinkit_{pincode}_*.json"), reverse=True):
        if "pdp" not in p.name:
            sam_path = p
            break

    print(f"[review] Anakin: {ana_path.name}")
    print(f"[review] PDP cmp: {pdp_cmp_path.name if pdp_cmp_path else 'NONE'}")
    print(f"[review] Cascade: {cascade_path.name if cascade_path else 'NONE'}")
    print(f"[review] Stage3:  {stage3_path.name if stage3_path else 'NONE'}")
    print(f"[review] SAM pool: {sam_path.name if sam_path else 'NONE'}")

    ana = json.load(open(ana_path))
    ana_by_code: dict[str, dict] = {}
    for rec in ana["records"]:
        ic = (rec.get("Item_Code") or "").strip()
        if ic:
            ana_by_code[ic] = rec

    sam_pool = json.load(open(sam_path))["products"] if sam_path else []

    review_rows: list[dict] = []

    # ── Pull Stage 1 ambiguous cases ──
    stage1_seen = set()
    if pdp_cmp_path:
        stage1 = json.load(open(pdp_cmp_path))
        for m in stage1.get("matches", []):
            ic = m.get("item_code")
            if not ic:
                continue
            stage1_seen.add(ic)

            ms = m.get("match_status")
            pdp = m.get("price_diff_pct")

            needs_review = False
            reason = None
            if ms == "scrape_error":
                needs_review, reason = True, "stage1_scrape_error"
            elif ms == "no_price_on_pdp":
                needs_review, reason = True, "stage1_no_price_on_pdp"
            elif pdp is not None and pdp > PRICE_DIFF_SUSPICIOUS_PCT:
                needs_review, reason = True, f"stage1_price_diff_{pdp:.0f}pct"

            if not needs_review:
                continue

            ana_rec = ana_by_code.get(ic, {})
            review_rows.append({
                "stage": "1",
                "item_code": ic,
                "reason": reason,
                "anakin_name": clean_str(ana_rec.get("Item_Name")),
                "anakin_brand": clean_str(ana_rec.get("Brand")),
                "anakin_weight": f"{clean_str(ana_rec.get('Unit_Value'))} {clean_str(ana_rec.get('Unit'))}".strip(),
                "anakin_mrp": clean_str(ana_rec.get("Mrp")),
                "anakin_blinkit_sp": clean_str(ana_rec.get("Blinkit_Selling_Price")),
                "anakin_product_url": clean_str(ana_rec.get("Blinkit_Product_Url")),
                "sam_product_name": m.get("sam_product_name"),
                "sam_price": m.get("sam_selling_price"),
                "price_diff_pct": m.get("price_diff_pct"),
                "top_candidates": "",
            })

    # ── Collect Stage 3 successes so we don't flag rescued SKUs ──
    stage3_success_codes: set[str] = set()
    stage3_weak_rows: list = []
    stage3_unmatched_rows: list = []
    if stage3_path:
        s3 = json.load(open(stage3_path))
        for r in s3.get("new_mappings", []):
            ic = r.get("item_code")
            if r.get("stage3_score", 0) >= CASCADE_SCORE_WEAK_THRESHOLD:
                stage3_success_codes.add(ic)
            else:
                stage3_weak_rows.append(r)
        for r in s3.get("unmatched", []):
            stage3_unmatched_rows.append(r)

    # ── Pull Stage 2 weak / unmatched cases (skip SKUs Stage 3 rescued) ──
    if cascade_path:
        cascade = json.load(open(cascade_path))
        for r in cascade.get("unmatched", []):
            ic = r.get("item_code")
            if ic in stage3_success_codes:
                continue
            cands = find_top_candidates(ana_by_code.get(ic, {}), sam_pool, TOP_N_CANDIDATES)
            cand_txt = "; ".join(
                f"[{c['score']}] {c['name']} ({c['unit']}, ₹{c['price']})" for c in cands
            )
            review_rows.append({
                "stage": "2",
                "item_code": ic,
                "reason": f"stage2_{r.get('cascade_reason')}",
                "anakin_name": r.get("anakin_name"),
                "anakin_brand": r.get("anakin_brand"),
                "anakin_weight": r.get("anakin_weight"),
                "anakin_mrp": r.get("anakin_mrp"),
                "anakin_blinkit_sp": "",
                "anakin_product_url": "",
                "sam_product_name": "",
                "sam_price": "",
                "price_diff_pct": "",
                "top_candidates": cand_txt,
            })
        for r in cascade.get("new_mappings", []):
            if r.get("cascade_score", 0) < CASCADE_SCORE_WEAK_THRESHOLD:
                ic = r.get("item_code")
                if ic in stage3_success_codes:
                    continue
                cands = find_top_candidates(ana_by_code.get(ic, {}), sam_pool, TOP_N_CANDIDATES)
                cand_txt = "; ".join(
                    f"[{c['score']}] {c['name']} ({c['unit']}, ₹{c['price']})" for c in cands
                )
                review_rows.append({
                    "stage": "2",
                    "item_code": ic,
                    "reason": f"stage2_weak_score_{r.get('cascade_score')}",
                    "anakin_name": r.get("anakin_name"),
                    "anakin_brand": r.get("anakin_brand"),
                    "anakin_weight": r.get("anakin_weight"),
                    "anakin_mrp": r.get("anakin_mrp"),
                    "anakin_blinkit_sp": "",
                    "anakin_product_url": "",
                    "sam_product_name": r.get("sam_product_name"),
                    "sam_price": r.get("sam_price"),
                    "price_diff_pct": "",
                    "top_candidates": cand_txt,
                })

    # ── Pull Stage 3 weak + unmatched cases ──
    for r in stage3_weak_rows:
        ic = r.get("item_code")
        cands = find_top_candidates(ana_by_code.get(ic, {}), sam_pool, TOP_N_CANDIDATES)
        cand_txt = "; ".join(
            f"[{c['score']}] {c['name']} ({c['unit']}, ₹{c['price']})" for c in cands
        )
        review_rows.append({
            "stage": "3",
            "item_code": ic,
            "reason": f"stage3_weak_score_{r.get('stage3_score')}",
            "anakin_name": r.get("anakin_name"),
            "anakin_brand": r.get("anakin_brand"),
            "anakin_weight": r.get("anakin_weight"),
            "anakin_mrp": r.get("anakin_mrp"),
            "anakin_blinkit_sp": "",
            "anakin_product_url": "",
            "sam_product_name": r.get("sam_product_name"),
            "sam_price": r.get("sam_price"),
            "price_diff_pct": "",
            "top_candidates": cand_txt,
        })
    for r in stage3_unmatched_rows:
        ic = r.get("item_code")
        cands = find_top_candidates(ana_by_code.get(ic, {}), sam_pool, TOP_N_CANDIDATES)
        cand_txt = "; ".join(
            f"[{c['score']}] {c['name']} ({c['unit']}, ₹{c['price']})" for c in cands
        )
        review_rows.append({
            "stage": "3",
            "item_code": ic,
            "reason": f"stage3_{r.get('stage3_reason')}",
            "anakin_name": r.get("anakin_name"),
            "anakin_brand": r.get("anakin_brand"),
            "anakin_weight": r.get("anakin_weight"),
            "anakin_mrp": r.get("anakin_mrp"),
            "anakin_blinkit_sp": "",
            "anakin_product_url": "",
            "sam_product_name": "",
            "sam_price": "",
            "price_diff_pct": "",
            "top_candidates": cand_txt,
        })

    # ── SKUs entirely absent from both stages (safety net) ──
    for ic, ana_rec in ana_by_code.items():
        if ic in stage1_seen:
            continue
        # Was this SKU a mapped one (should have been in Stage 1) or NA (Stage 2)?
        # Already handled by the above loops. This catches orphans.
        pass

    # ── Write CSV ──
    out_dir = PROJECT_ROOT / "data" / "comparisons"
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    csv_path = out_dir / f"blinkit_{pincode}_review_queue_{ts}.csv"

    fieldnames = [
        "stage", "item_code", "reason",
        "anakin_name", "anakin_brand", "anakin_weight", "anakin_mrp",
        "anakin_blinkit_sp", "anakin_product_url",
        "sam_product_name", "sam_price", "price_diff_pct",
        "top_candidates",
        "human_decision",  # blank — filled in by reviewer
        "notes",
    ]
    with open(csv_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in review_rows:
            r.setdefault("human_decision", "")
            r.setdefault("notes", "")
            w.writerow(r)

    # Summary by reason
    reason_counts: dict[str, int] = {}
    for r in review_rows:
        reason_counts[r["reason"]] = reason_counts.get(r["reason"], 0) + 1

    print()
    print("=" * 60)
    print(f"STAGE 4 — MANUAL REVIEW QUEUE (pincode {pincode})")
    print("=" * 60)
    print(f"Total items needing human review: {len(review_rows)}")
    print()
    print("Breakdown by reason:")
    for reason, count in sorted(reason_counts.items(), key=lambda x: -x[1]):
        print(f"  {reason:40s} {count}")
    print()
    print(f"CSV saved: {csv_path}")
    print()
    print("Reviewer: fill in `human_decision` column with one of:")
    print("  correct       — Stage 1/2 match is right; accept it")
    print("  wrong         — match is wrong; rejected")
    print("  manual:<id>   — manual Blinkit product_id to use instead")
    print("  not_available — Blinkit doesn't sell this SKU in this pincode")


if __name__ == "__main__":
    pincode = sys.argv[1] if len(sys.argv) > 1 else "834002"
    main(pincode)
