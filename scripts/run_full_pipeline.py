"""
Full 6-stage pipeline: runs all stages in sequence for a given pincode + platform.
Each stage's failures automatically feed into the next stage.

Stage 1: PDP Direct (ID-based URL visit)
Stage 2: Brand Cascade (brand → type → weight → name)
Stage 3: Type/MRP Cascade (type → name → weight → MRP)
Stage 4: Search API Match (Jiomart-specific — PDP doesn't render)
Stage 5: Image Match + Barcode Match
Stage 6: Manual Review Queue (CSV export)

Usage:
    cd backend && ./venv/bin/python ../scripts/run_full_pipeline.py 834002 blinkit
    cd backend && ./venv/bin/python ../scripts/run_full_pipeline.py 834002 jiomart
    cd backend && ./venv/bin/python ../scripts/run_full_pipeline.py 834002 all
"""
import asyncio
import json
import glob
import subprocess
import sys
from datetime import datetime
from pathlib import Path

sys.stdout.reconfigure(line_buffering=True)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = PROJECT_ROOT / "scripts"
VENV_PYTHON = str(PROJECT_ROOT / "backend" / "venv" / "bin" / "python")


def run_script(name: str, args: list[str] = [], use_venv: bool = False):
    """Run a script and return exit code."""
    python = VENV_PYTHON if use_venv else sys.executable
    script = str(SCRIPTS / name)
    cmd = [python, script] + args
    print(f"\n{'─'*60}", flush=True)
    print(f"▶ Running: {name} {' '.join(args)}", flush=True)
    print(f"{'─'*60}", flush=True)
    result = subprocess.run(cmd, cwd=str(PROJECT_ROOT))
    return result.returncode


def count_matched(pincode: str, platform: str) -> dict:
    """Count total matched from all stage outputs."""
    cmp_dir = PROJECT_ROOT / "data" / "comparisons"

    # Load Anakin usable
    ana_files = sorted((PROJECT_ROOT / "data" / "anakin").glob(f"{platform}_{pincode}_*.json"))
    if not ana_files:
        return {"usable": 0, "matched": 0}
    ana = json.load(open(ana_files[-1]))

    pf_sp = "Blinkit_Selling_Price" if platform == "blinkit" else "Jiomart_Selling_Price"
    usable = {r.get("Item_Code") for r in ana["records"]
              if r.get(pf_sp) not in (None, "", "NA", "nan")
              and "loose" not in (r.get("Item_Name") or "").lower()}

    matched = set()
    stage_counts = {}

    # Stage 1 — PDP
    for f in sorted(cmp_dir.glob(f"{platform}_pdp_{pincode}_*_compare.json")):
        d = json.load(open(f))
        for m in d.get("matches", []):
            if m.get("match_status") == "ok":
                matched.add(m.get("item_code"))
    stage_counts["stage1_pdp"] = len(matched & usable)

    prev = len(matched & usable)

    # Stage 2 — Cascade
    for f in sorted(cmp_dir.glob(f"{platform}_cascade_{pincode}_*.json")):
        d = json.load(open(f))
        for m in d.get("new_mappings", []):
            matched.add(m.get("item_code"))
    stage_counts["stage2_brand"] = len(matched & usable) - prev
    prev = len(matched & usable)

    # Stage 3 — Type/MRP
    for f in sorted(cmp_dir.glob(f"{platform}_stage3_{pincode}_*.json")):
        d = json.load(open(f))
        for m in d.get("new_mappings", []):
            matched.add(m.get("item_code"))
    stage_counts["stage3_type_mrp"] = len(matched & usable) - prev
    prev = len(matched & usable)

    # Stage 4 — Search API (Jiomart)
    for f in sorted(cmp_dir.glob(f"jiomart_search_match_{pincode}_*.json")):
        d = json.load(open(f))
        for m in d.get("new_mappings", []):
            matched.add(m.get("item_code"))
    stage_counts["stage4_search"] = len(matched & usable) - prev
    prev = len(matched & usable)

    # Stage 5 — Image
    for f in sorted(cmp_dir.glob(f"{platform}_image_match_{pincode}_*.json")):
        d = json.load(open(f))
        for m in d.get("new_mappings", []):
            matched.add(m.get("item_code"))
    stage_counts["stage5_image"] = len(matched & usable) - prev
    prev = len(matched & usable)

    # Stage 5 — Barcode
    for f in sorted(cmp_dir.glob(f"{platform}_barcode_match_{pincode}_*.json")):
        d = json.load(open(f))
        for m in d.get("new_mappings", []):
            matched.add(m.get("item_code"))
    stage_counts["stage5_barcode"] = len(matched & usable) - prev

    total_matched = len(matched & usable)
    return {
        "usable": len(usable),
        "matched": total_matched,
        "coverage_pct": round(total_matched * 100 / len(usable), 1) if usable else 0,
        "unmatched": len(usable) - total_matched,
        "stages": stage_counts,
    }


def run_platform_pipeline(pincode: str, platform: str):
    """Run full 6-stage pipeline for one platform."""
    print(f"\n{'═'*60}", flush=True)
    print(f"  FULL PIPELINE: {platform.upper()} — Pincode {pincode}", flush=True)
    print(f"{'═'*60}", flush=True)

    # Stage 1 — PDP Direct
    if platform == "blinkit":
        run_script("scrape_blinkit_pdps.py", [pincode, "2"], use_venv=True)
        # Clean partial
        partial = PROJECT_ROOT / "data" / "sam" / f"blinkit_pdp_{pincode}_latest_partial.json"
        if partial.exists():
            partial.unlink()
        run_script("compare_pdp.py", [pincode])
    elif platform == "jiomart":
        run_script("scrape_jiomart_pdps.py", [pincode, "2"], use_venv=True)
        partial = PROJECT_ROOT / "data" / "sam" / f"jiomart_pdp_{pincode}_latest_partial.json"
        if partial.exists():
            partial.unlink()
        run_script("compare_pdp_jiomart.py", [pincode])

    # Stage 2 — Brand Cascade
    run_script("cascade_match.py", [pincode, platform])

    # Stage 3 — Type/MRP Cascade
    run_script("stage3_match.py", [pincode, platform])

    # Stage 4 — Search API (Jiomart only)
    if platform == "jiomart":
        run_script("jiomart_search_match.py", [pincode], use_venv=True)

    # Stage 5 — Image + Barcode
    run_script("stage4_image_match.py", [pincode, platform])
    run_script("stage5_barcode_match.py", [pincode, platform])

    # Stage 6 — Manual Review Queue
    run_script("export_review_queue.py", [pincode])

    # Verification against Anakin
    run_script("verify_against_anakin.py", [pincode, platform])

    # Final report
    result = count_matched(pincode, platform)
    print(f"\n{'═'*60}", flush=True)
    print(f"  FINAL RESULT: {platform.upper()} — Pincode {pincode}", flush=True)
    print(f"{'═'*60}", flush=True)
    print(f"  Anakin usable (non-loose): {result['usable']}", flush=True)
    for stage, count in result["stages"].items():
        if count > 0:
            print(f"  {stage:25s}: +{count}", flush=True)
    print(f"  {'─'*40}", flush=True)
    print(f"  TOTAL MATCHED:           {result['matched']} / {result['usable']} = {result['coverage_pct']}%", flush=True)
    print(f"  UNMATCHED:               {result['unmatched']}", flush=True)

    return result


def main():
    pincode = sys.argv[1] if len(sys.argv) > 1 else "834002"
    platform = sys.argv[2] if len(sys.argv) > 2 else "all"

    start = datetime.now()
    results = {}

    if platform == "all":
        for p in ["blinkit", "jiomart"]:
            results[p] = run_platform_pipeline(pincode, p)
    else:
        results[platform] = run_platform_pipeline(pincode, platform)

    duration = (datetime.now() - start).total_seconds() / 60

    # Grand total
    if len(results) > 1:
        total_usable = sum(r["usable"] for r in results.values())
        total_matched = sum(r["matched"] for r in results.values())
        print(f"\n{'#'*60}", flush=True)
        print(f"  GRAND TOTAL — Pincode {pincode}", flush=True)
        print(f"{'#'*60}", flush=True)
        for p, r in results.items():
            print(f"  {p:10s}: {r['matched']} / {r['usable']} = {r['coverage_pct']}%", flush=True)
        print(f"  {'─'*40}", flush=True)
        print(f"  COMBINED:   {total_matched} / {total_usable} = {total_matched*100/total_usable:.1f}%", flush=True)
        print(f"  Duration:   {duration:.1f} min", flush=True)

    # Save summary
    out_dir = PROJECT_ROOT / "data" / "comparisons"
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    out_path = out_dir / f"pipeline_summary_{pincode}_{ts}.json"
    with open(out_path, "w") as f:
        json.dump({
            "pincode": pincode,
            "completed_at": datetime.now().isoformat(),
            "duration_minutes": round(duration, 1),
            "results": results,
        }, f, indent=2, default=str)
    print(f"\n  Summary: {out_path}", flush=True)


if __name__ == "__main__":
    main()
