"""
Day 3 orchestrator: Run Stage 1 PDP scrape for all 4 Anakin cities + both
platforms (Blinkit + Jiomart) in sequence, and generate a combined report.

Usage:
    cd backend && ./venv/bin/python ../scripts/run_all_cities.py [--platforms blinkit,jiomart]
                                                                 [--cities 834002,712232,...]

Notes:
    - Uses existing scrape_blinkit_pdps.main() and scrape_jiomart_pdps.main()
    - Runs platforms+cities sequentially (not parallel) to avoid browser/RAM overload
    - After each run, generates comparison and appends to combined report
    - Total expected time: ~32 min × 4 cities × 2 platforms = ~4 hrs
"""
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

sys.stdout.reconfigure(line_buffering=True)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Default: all 4 Anakin cities
DEFAULT_PINCODES = ["834002", "712232", "492001", "825301"]
CITY_NAMES = {
    "834002": "Ranchi",
    "712232": "Kolkata",
    "492001": "Raipur",
    "825301": "Hazaribagh",
}


async def run_blinkit_for_pincode(pincode: str, num_tabs: int = 2):
    from scrape_blinkit_pdps import main as scrape_main
    print(f"\n{'='*60}\n[orch] BLINKIT: {CITY_NAMES.get(pincode, pincode)} ({pincode})\n{'='*60}", flush=True)
    await scrape_main(pincode, num_tabs)


async def run_jiomart_for_pincode(pincode: str, num_tabs: int = 2):
    from scrape_jiomart_pdps import main as scrape_main
    print(f"\n{'='*60}\n[orch] JIOMART: {CITY_NAMES.get(pincode, pincode)} ({pincode})\n{'='*60}", flush=True)
    await scrape_main(pincode, num_tabs)


def run_compare(platform: str, pincode: str):
    """Run the appropriate compare script and return metrics dict."""
    import subprocess
    script = "compare_pdp.py" if platform == "blinkit" else "compare_pdp_jiomart.py"
    result = subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "scripts" / script), pincode],
        capture_output=True, text=True,
    )
    print(result.stdout, flush=True)
    if result.stderr:
        print(result.stderr, flush=True)

    # Find the latest comparison report
    pattern = f"{platform}_pdp_{pincode}_*_compare.json" if platform == "jiomart" \
        else f"blinkit_pdp_{pincode}_*_compare.json"
    cmp_files = sorted((PROJECT_ROOT / "data" / "comparisons").glob(pattern))
    if not cmp_files:
        return None
    cmp_data = json.load(open(cmp_files[-1]))
    return cmp_data.get("metrics", {})


async def main():
    # Parse args
    pincodes = DEFAULT_PINCODES[:]
    platforms = ["blinkit", "jiomart"]
    for i, arg in enumerate(sys.argv[1:]):
        if arg == "--cities" and i + 1 < len(sys.argv) - 1:
            pincodes = sys.argv[i + 2].split(",")
        if arg == "--platforms" and i + 1 < len(sys.argv) - 1:
            platforms = sys.argv[i + 2].split(",")

    print(f"[orch] Cities: {pincodes}", flush=True)
    print(f"[orch] Platforms: {platforms}", flush=True)
    print(f"[orch] Total runs: {len(pincodes) * len(platforms)}", flush=True)

    start = datetime.now()
    combined_metrics = []

    for platform in platforms:
        for pincode in pincodes:
            city = CITY_NAMES.get(pincode, pincode)
            try:
                if platform == "blinkit":
                    await run_blinkit_for_pincode(pincode)
                elif platform == "jiomart":
                    await run_jiomart_for_pincode(pincode)

                # Compare
                metrics = run_compare(platform, pincode)
                combined_metrics.append({
                    "city": city,
                    "pincode": pincode,
                    "platform": platform,
                    "metrics": metrics or {},
                    "completed_at": datetime.now().isoformat(),
                })

                # Save combined report after each run
                out_path = PROJECT_ROOT / "data" / "comparisons" / f"day3_combined_{start.strftime('%Y-%m-%d_%H%M%S')}.json"
                with open(out_path, "w") as f:
                    json.dump({
                        "started_at": start.isoformat(),
                        "last_updated": datetime.now().isoformat(),
                        "runs": combined_metrics,
                    }, f, indent=2, default=str)
                print(f"\n[orch] Combined report so far: {out_path}", flush=True)
            except Exception as e:
                print(f"[orch] ERROR for {platform} {pincode}: {e}", flush=True)
                combined_metrics.append({
                    "city": city,
                    "pincode": pincode,
                    "platform": platform,
                    "error": str(e),
                })

    duration = (datetime.now() - start).total_seconds() / 60
    print(f"\n\n{'#'*60}", flush=True)
    print(f"# DAY 3 COMPLETE in {duration:.1f} minutes", flush=True)
    print(f"{'#'*60}", flush=True)
    print(f"\nSummary:")
    for r in combined_metrics:
        m = r.get("metrics", {})
        print(f"  {r['platform']:8s} {r['city']:12s} "
              f"cov={m.get('coverage_pct','?')}% "
              f"±5%={m.get('price_match_pct_5','?')}% "
              f"±10%={m.get('price_match_pct_10','?')}%")


if __name__ == "__main__":
    asyncio.run(main())
