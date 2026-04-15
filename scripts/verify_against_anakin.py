"""
Verify SAM scrape results against Anakin reference data across all stages.

Loads latest Anakin data + all stage outputs for a pincode/platform,
then produces a consolidated verification report:
  - Per-stage match count & coverage %
  - Price accuracy buckets (within 2%, 5%, 10%, 20%)
  - Top mismatches (where SAM price differs most from Anakin)
  - Unmatched SKUs summary

Usage:
    python scripts/verify_against_anakin.py 834002 blinkit
    python scripts/verify_against_anakin.py 834002 all
"""
import json
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA = PROJECT_ROOT / "data"
ANAKIN_DIR = DATA / "anakin"
CMP_DIR = DATA / "comparisons"


def latest_file(directory: Path, pattern: str) -> Path | None:
    files = sorted(directory.glob(pattern))
    return files[-1] if files else None


def parse_price(val) -> float | None:
    if val is None:
        return None
    s = str(val).strip()
    if s in ("", "NA", "nan", "None", "#VALUE!"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def load_anakin(pincode: str, platform: str) -> dict:
    """Load latest Anakin data. Returns {item_code: record}."""
    f = latest_file(ANAKIN_DIR, f"{platform}_{pincode}_*.json")
    if not f:
        print(f"[verify] ERROR: no Anakin {platform} file for {pincode}", file=sys.stderr)
        return {}
    data = json.load(open(f))
    print(f"[verify] Anakin file: {f.name}")

    sp_key = "Blinkit_Selling_Price" if platform == "blinkit" else "Jiomart_Selling_Price"
    records = {}
    for r in data.get("records", []):
        code = r.get("Item_Code")
        if not code:
            continue
        records[str(code)] = r
    return records


def get_usable_codes(anakin: dict, platform: str) -> set:
    """Anakin SKUs with valid selling price and not loose."""
    sp_key = "Blinkit_Selling_Price" if platform == "blinkit" else "Jiomart_Selling_Price"
    usable = set()
    for code, r in anakin.items():
        sp = r.get(sp_key)
        if str(sp).strip() in ("", "NA", "nan", "None", "#VALUE!"):
            continue
        name = (r.get("Item_Name") or "").lower()
        if "loose" in name:
            continue
        usable.add(code)
    return usable


def collect_stage_results(pincode: str, platform: str, anakin: dict):
    """Collect matched item_codes and price pairs per stage."""

    sp_key = "Blinkit_Selling_Price" if platform == "blinkit" else "Jiomart_Selling_Price"
    mrp_key = "Blinkit_Mrp_Price" if platform == "blinkit" else "Jiomart_Mrp_Price"

    stages = []
    all_matched = set()  # cumulative

    # ── Stage 1: PDP Direct ─────────────────────────────────
    stage1_matches = []
    stage1_seen = set()
    f = latest_file(CMP_DIR, f"{platform}_pdp_{pincode}_*_compare.json")
    if f:
        d = json.load(open(f))
        for m in d.get("matches", []):
            if m.get("match_status") == "ok":
                code = str(m.get("item_code"))
                if code in stage1_seen:
                    continue
                stage1_seen.add(code)
                anakin_sp = parse_price(m.get("anakin_blinkit_sp") if platform == "blinkit"
                                        else m.get("anakin_jiomart_sp"))
                sam_sp = parse_price(m.get("sam_selling_price"))
                stage1_matches.append({
                    "item_code": code,
                    "anakin_name": m.get("anakin_name"),
                    "sam_name": m.get("sam_product_name"),
                    "anakin_sp": anakin_sp,
                    "sam_sp": sam_sp,
                    "price_diff_pct": m.get("price_diff_pct"),
                })

    new_codes = {m["item_code"] for m in stage1_matches} - all_matched
    all_matched |= new_codes
    stages.append({
        "name": "Stage 1 — PDP Direct",
        "matches": stage1_matches,
        "new_codes": new_codes,
    })

    # ── Stage 2: Brand Cascade ──────────────────────────────
    stage2_matches = []
    stage2_seen = set()
    f = latest_file(CMP_DIR, f"{platform}_cascade_{pincode}_*.json")
    if f:
        d = json.load(open(f))
        for m in d.get("new_mappings", []):
            code = str(m.get("item_code"))
            if code in stage2_seen:
                continue
            stage2_seen.add(code)
            anakin_sp = parse_price(anakin.get(code, {}).get(sp_key))
            sam_sp = parse_price(m.get("sam_price"))
            anakin_mrp = parse_price(m.get("anakin_mrp"))
            sam_mrp = parse_price(m.get("sam_mrp"))
            diff = None
            # Use SP if available, else fall back to MRP comparison
            ref_price = anakin_sp or anakin_mrp
            cmp_price = sam_sp
            if ref_price and cmp_price and ref_price > 0:
                diff = round(abs(cmp_price - ref_price) * 100 / ref_price, 2)
            stage2_matches.append({
                "item_code": code,
                "anakin_name": m.get("anakin_name"),
                "sam_name": m.get("sam_product_name"),
                "anakin_sp": anakin_sp,
                "sam_sp": sam_sp,
                "anakin_mrp": anakin_mrp,
                "sam_mrp": sam_mrp,
                "cascade_score": m.get("cascade_score"),
                "price_diff_pct": diff,
            })

    new_codes = {m["item_code"] for m in stage2_matches} - all_matched
    all_matched |= new_codes
    stages.append({
        "name": "Stage 2 — Brand Cascade",
        "matches": stage2_matches,
        "new_codes": new_codes,
    })

    # ── Stage 3: Type/MRP Cascade ───────────────────────────
    stage3_matches = []
    stage3_seen = set()
    f = latest_file(CMP_DIR, f"{platform}_stage3_{pincode}_*.json")
    if f:
        d = json.load(open(f))
        for m in d.get("new_mappings", []):
            code = str(m.get("item_code"))
            if code in stage3_seen:
                continue
            stage3_seen.add(code)
            anakin_sp = parse_price(anakin.get(code, {}).get(sp_key))
            anakin_mrp = parse_price(m.get("anakin_mrp") or anakin.get(code, {}).get("Mrp"))
            sam_sp = parse_price(m.get("sam_price"))
            diff = None
            # Use SP if available, else fall back to MRP comparison
            ref_price = anakin_sp or anakin_mrp
            if ref_price and sam_sp and ref_price > 0:
                diff = round(abs(sam_sp - ref_price) * 100 / ref_price, 2)
            stage3_matches.append({
                "item_code": code,
                "anakin_name": m.get("anakin_name"),
                "sam_name": m.get("sam_product_name"),
                "anakin_sp": anakin_sp,
                "sam_sp": sam_sp,
                "stage3_score": m.get("stage3_score"),
                "price_diff_pct": diff,
            })

    new_codes = {m["item_code"] for m in stage3_matches} - all_matched
    all_matched |= new_codes
    stages.append({
        "name": "Stage 3 — Type/MRP Cascade",
        "matches": stage3_matches,
        "new_codes": new_codes,
    })

    # ── Stage 4: Search API (Jiomart only) ──────────────────
    stage4_matches = []
    stage4_seen = set()
    if platform == "jiomart":
        f = latest_file(CMP_DIR, f"jiomart_search_match_{pincode}_*.json")
        if f:
            d = json.load(open(f))
            for m in d.get("new_mappings", []):
                code = str(m.get("item_code"))
                if code in stage4_seen:
                    continue
                stage4_seen.add(code)
                anakin_sp = parse_price(anakin.get(code, {}).get(sp_key))
                sam_sp = parse_price(m.get("sam_price"))
                diff = None
                if anakin_sp and sam_sp and anakin_sp > 0:
                    diff = round(abs(sam_sp - anakin_sp) * 100 / anakin_sp, 2)
                stage4_matches.append({
                    "item_code": code,
                    "anakin_name": m.get("anakin_name"),
                    "sam_name": m.get("sam_product_name"),
                    "anakin_sp": anakin_sp,
                    "sam_sp": sam_sp,
                    "price_diff_pct": diff,
                })

    new_codes = {m["item_code"] for m in stage4_matches} - all_matched
    all_matched |= new_codes
    stages.append({
        "name": "Stage 4 — Search API",
        "matches": stage4_matches,
        "new_codes": new_codes,
    })

    # ── Stage 5a: Image Match ───────────────────────────────
    stage5i_matches = []
    stage5i_seen = set()
    f = latest_file(CMP_DIR, f"{platform}_image_match_{pincode}_*.json")
    if f:
        d = json.load(open(f))
        for m in d.get("new_mappings", []):
            code = str(m.get("item_code"))
            if code in stage5i_seen:
                continue
            stage5i_seen.add(code)
            anakin_sp = parse_price(anakin.get(code, {}).get(sp_key))
            sam_sp = parse_price(m.get("sam_price"))
            diff = None
            if anakin_sp and sam_sp and anakin_sp > 0:
                diff = round(abs(sam_sp - anakin_sp) * 100 / anakin_sp, 2)
            stage5i_matches.append({
                "item_code": code,
                "anakin_name": m.get("anakin_name"),
                "sam_name": m.get("sam_product_name"),
                "anakin_sp": anakin_sp,
                "sam_sp": sam_sp,
                "price_diff_pct": diff,
            })

    new_codes = {m["item_code"] for m in stage5i_matches} - all_matched
    all_matched |= new_codes
    stages.append({
        "name": "Stage 5a — Image Match",
        "matches": stage5i_matches,
        "new_codes": new_codes,
    })

    # ── Stage 5b: Barcode Match ─────────────────────────────
    stage5b_matches = []
    stage5b_seen = set()
    f = latest_file(CMP_DIR, f"{platform}_barcode_match_{pincode}_*.json")
    if f:
        d = json.load(open(f))
        for m in d.get("new_mappings", []):
            code = str(m.get("item_code"))
            if code in stage5b_seen:
                continue
            stage5b_seen.add(code)
            anakin_sp = parse_price(anakin.get(code, {}).get(sp_key))
            sam_sp = parse_price(m.get("sam_price"))
            diff = None
            if anakin_sp and sam_sp and anakin_sp > 0:
                diff = round(abs(sam_sp - anakin_sp) * 100 / anakin_sp, 2)
            stage5b_matches.append({
                "item_code": code,
                "anakin_name": m.get("anakin_name"),
                "sam_name": m.get("sam_product_name"),
                "anakin_sp": anakin_sp,
                "sam_sp": sam_sp,
                "price_diff_pct": diff,
            })

    new_codes = {m["item_code"] for m in stage5b_matches} - all_matched
    all_matched |= new_codes
    stages.append({
        "name": "Stage 5b — Barcode Match",
        "matches": stage5b_matches,
        "new_codes": new_codes,
    })

    return stages, all_matched


def price_accuracy_buckets(matches: list) -> dict:
    """Compute price accuracy buckets from a list of matches with price_diff_pct."""
    with_price = [m for m in matches if m.get("price_diff_pct") is not None]
    total = len(with_price)
    if total == 0:
        return {"compared": 0}

    within_2 = sum(1 for m in with_price if abs(m["price_diff_pct"]) <= 2)
    within_5 = sum(1 for m in with_price if abs(m["price_diff_pct"]) <= 5)
    within_10 = sum(1 for m in with_price if abs(m["price_diff_pct"]) <= 10)
    within_20 = sum(1 for m in with_price if abs(m["price_diff_pct"]) <= 20)
    beyond_20 = total - within_20

    return {
        "compared": total,
        "within_2pct": within_2,
        "within_5pct": within_5,
        "within_10pct": within_10,
        "within_20pct": within_20,
        "beyond_20pct": beyond_20,
        "accuracy_2pct": round(within_2 * 100 / total, 1),
        "accuracy_5pct": round(within_5 * 100 / total, 1),
        "accuracy_10pct": round(within_10 * 100 / total, 1),
    }


def top_mismatches(matches: list, n: int = 15) -> list:
    """Return top N mismatches by price_diff_pct descending, deduplicated by item_code."""
    with_price = [m for m in matches if m.get("price_diff_pct") is not None
                  and abs(m["price_diff_pct"]) > 2]
    with_price.sort(key=lambda x: -abs(x["price_diff_pct"]))
    # Deduplicate by item_code — keep the first (highest diff) entry
    seen = set()
    deduped = []
    for m in with_price:
        code = m.get("item_code")
        if code in seen:
            continue
        seen.add(code)
        deduped.append(m)
    return deduped[:n]


def print_report(pincode: str, platform: str, stages: list,
                 all_matched: set, usable: set, anakin_total: int):
    """Print the verification report to stdout."""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")

    print(f"\n{'═' * 70}")
    print(f"  VERIFICATION REPORT — {platform.upper()} / Pincode {pincode}")
    print(f"  Generated: {ts}")
    print(f"{'═' * 70}")

    # ── Summary ──────────────────────────────────────────────
    matched_usable = all_matched & usable
    print(f"\n  Anakin total SKUs:     {anakin_total}")
    print(f"  Anakin usable (mapped): {len(usable)}")
    print(f"  SAM matched (all):     {len(all_matched)}")
    print(f"  SAM matched (usable):  {len(matched_usable)}")
    coverage = round(len(matched_usable) * 100 / len(usable), 1) if usable else 0
    print(f"  Coverage:              {coverage}%")
    print(f"  Unmatched usable:      {len(usable) - len(matched_usable)}")

    # ── Per-stage breakdown ──────────────────────────────────
    print(f"\n{'─' * 70}")
    print(f"  {'Stage':<30s} {'Matched':>8s} {'New':>6s} {'Compared':>10s} {'≤5%':>6s} {'≤10%':>6s}")
    print(f"{'─' * 70}")

    all_price_matches = []
    cumulative = 0
    for stage in stages:
        matches = stage["matches"]
        new = len(stage["new_codes"] & usable)
        cumulative += new
        buckets = price_accuracy_buckets(matches)
        compared = buckets.get("compared", 0)
        acc5 = f"{buckets['accuracy_5pct']}%" if compared > 0 else "—"
        acc10 = f"{buckets['accuracy_10pct']}%" if compared > 0 else "—"

        print(f"  {stage['name']:<30s} {len(matches):>8d} {f'+{new}':>6s} {compared:>10d} {acc5:>6s} {acc10:>6s}")
        all_price_matches.extend(matches)

    print(f"{'─' * 70}")
    print(f"  {'TOTAL':<30s} {len(all_price_matches):>8d} {f'={cumulative}':>6s}")

    # ── Overall price accuracy (deduplicated by item_code) ──
    seen_codes = set()
    deduped_matches = []
    for m in all_price_matches:
        code = m.get("item_code")
        if code not in seen_codes:
            seen_codes.add(code)
            deduped_matches.append(m)
    overall = price_accuracy_buckets(deduped_matches)
    if overall["compared"] > 0:
        print(f"\n  PRICE ACCURACY (across all stages, {overall['compared']} prices compared):")
        print(f"    Within  2%: {overall['within_2pct']:>5d} ({overall['accuracy_2pct']}%)")
        print(f"    Within  5%: {overall['within_5pct']:>5d} ({overall['accuracy_5pct']}%)")
        print(f"    Within 10%: {overall['within_10pct']:>5d} ({overall['accuracy_10pct']}%)")
        print(f"    Within 20%: {overall['within_20pct']:>5d}")
        print(f"    Beyond 20%: {overall['beyond_20pct']:>5d}")

    # ── Top mismatches ───────────────────────────────────────
    mismatches = top_mismatches(deduped_matches)
    if mismatches:
        print(f"\n  TOP MISMATCHES (>2% price diff):")
        print(f"  {'Code':<10s} {'Diff%':>7s} {'Anakin₹':>9s} {'SAM₹':>9s}  Anakin Name")
        print(f"  {'─' * 65}")
        for m in mismatches:
            code = m["item_code"][:9]
            diff = f"{m['price_diff_pct']:+.1f}%"
            asp = f"₹{m['anakin_sp']:.0f}" if m.get("anakin_sp") else "—"
            ssp = f"₹{m['sam_sp']:.0f}" if m.get("sam_sp") else "—"
            name = (m.get("anakin_name") or "")[:40]
            print(f"  {code:<10s} {diff:>7s} {asp:>9s} {ssp:>9s}  {name}")

    print(f"\n{'═' * 70}\n")
    return overall


def save_report(pincode: str, platform: str, stages: list,
                all_matched: set, usable: set, anakin_total: int, overall: dict):
    """Save verification JSON report."""
    matched_usable = all_matched & usable
    coverage = round(len(matched_usable) * 100 / len(usable), 1) if usable else 0

    stage_summary = []
    for stage in stages:
        new = len(stage["new_codes"] & usable)
        buckets = price_accuracy_buckets(stage["matches"])
        stage_summary.append({
            "name": stage["name"],
            "total_matches": len(stage["matches"]),
            "new_usable": new,
            "price_accuracy": buckets,
        })

    report = {
        "pincode": pincode,
        "platform": platform,
        "verified_at": datetime.now().isoformat(),
        "anakin_total": anakin_total,
        "anakin_usable": len(usable),
        "sam_matched_usable": len(matched_usable),
        "coverage_pct": coverage,
        "unmatched_usable": len(usable) - len(matched_usable),
        "overall_price_accuracy": overall,
        "stages": stage_summary,
        "top_mismatches": top_mismatches(
            [m for s in stages for m in s["matches"]]
        ),
    }

    out_dir = CMP_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    out_path = out_dir / f"verification_{platform}_{pincode}_{ts}.json"
    with open(out_path, "w") as f:
        json.dump(report, f, indent=2, default=str)
    print(f"  Report saved: {out_path.name}")
    return out_path


def verify_platform(pincode: str, platform: str) -> dict:
    """Run verification for one platform. Returns summary dict."""
    anakin = load_anakin(pincode, platform)
    if not anakin:
        return {}

    usable = get_usable_codes(anakin, platform)
    stages, all_matched = collect_stage_results(pincode, platform, anakin)
    overall = print_report(pincode, platform, stages, all_matched, usable, len(anakin))
    save_report(pincode, platform, stages, all_matched, usable, len(anakin), overall)

    matched_usable = all_matched & usable
    return {
        "usable": len(usable),
        "matched": len(matched_usable),
        "coverage_pct": round(len(matched_usable) * 100 / len(usable), 1) if usable else 0,
        "price_accuracy": overall,
    }


def main():
    pincode = sys.argv[1] if len(sys.argv) > 1 else "834002"
    platform = sys.argv[2] if len(sys.argv) > 2 else "all"

    if platform == "all":
        for p in ["blinkit", "jiomart"]:
            verify_platform(pincode, p)
    else:
        verify_platform(pincode, platform)


if __name__ == "__main__":
    main()
