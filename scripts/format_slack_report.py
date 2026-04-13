"""
Format the latest comparison JSON into a Slack-ready summary.

Usage:
    python3 scripts/format_slack_report.py 834002
"""
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def latest_compare(pincode: str) -> Path | None:
    files = sorted((PROJECT_ROOT / "data" / "comparisons").glob(f"blinkit_{pincode}_*_compare.json"))
    return files[-1] if files else None


def main(pincode: str):
    f = latest_compare(pincode)
    if not f:
        print(f"No comparison file found for pincode {pincode}", file=sys.stderr)
        sys.exit(1)

    data = json.load(open(f))
    m = data["metrics"]

    cov_emoji = "✅" if m["coverage_pct"] >= 90 else ("🟡" if m["coverage_pct"] >= 70 else "🔴")
    px_emoji = "✅" if m["price_match_pct_5"] >= 90 else ("🟡" if m["price_match_pct_5"] >= 70 else "🔴")

    out = f"""**Day 1 baseline — SAM vs Anakin (Blinkit, pincode {pincode})**

{cov_emoji} **Coverage**: {m['coverage_count']}/{m['anakin_mapped_skus']} = **{m['coverage_pct']}%**
   • Score 0.9+: {m['score_buckets']['0.9+']}
   • Score 0.7-0.9: {m['score_buckets']['0.7-0.9']}
   • Score 0.5-0.7: {m['score_buckets']['0.5-0.7']}

{px_emoji} **Price match** (vs Anakin's `Blinkit_Selling_Price`, where available):
   • Within ±5%: {m['price_match_5pct']}/{m['price_compared']} = **{m['price_match_pct_5']}%**
   • Within ±10%: {m['price_match_10pct']}/{m['price_compared']} = {m['price_match_pct_10']}%

**SAM scraped**: {m['sam_scraped_count']} products total
**Anakin baseline**: {m['anakin_mapped_skus']} mapped Blinkit SKUs
**Files**:
   • Anakin: `{data['anakin_file']}`
   • SAM:   `{data['sam_file']}`

_Day 2: extend to all 4 cities + Jiomart. Day 3: tune to 90%+._
"""
    print(out)


if __name__ == "__main__":
    pincode = sys.argv[1] if len(sys.argv) > 1 else "834002"
    main(pincode)
