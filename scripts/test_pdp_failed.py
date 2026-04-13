"""Test: re-scrape 10 previously-failed PDP URLs to verify fix."""
import asyncio
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(line_buffering=True)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from scrape_blinkit_pdps import init_blinkit_browser, scrape_one_pdp  # noqa


async def main():
    pincode = "834002"
    # 10 URLs that FAILED (no_price) in the original run but Anakin says available
    test_urls = [
        ("100323", "https://blinkit.com/prn/x/prid/18562", "18562", "Active Wheel Detergent", "76"),
        ("10031", "https://blinkit.com/prn/x/prid/10630", "10630", "Sunsilk Shampoo", "276"),
        ("10048", "https://blinkit.com/prn/x/prid/392509", "392509", "Haldirams Soan Papadi", "135"),
        ("100492", "https://blinkit.com/prn/x/prid/591806", "591806", "Jalan Ragi Atta", "53"),
        ("100665", "https://blinkit.com/prn/x/prid/601164", "601164", "Kellogg's Muesli", "179"),
        ("100252", "https://blinkit.com/prn/x/prid/591214", "591214", "Kenko Eggs", "121"),
        ("100436", "https://blinkit.com/prn/x/prid/369742", "369742", "Broccoli", "33"),
        ("100432", "https://blinkit.com/prn/x/prid/203822", "203822", "Raw Turmeric", "30"),
        ("100255", "https://blinkit.com/prn/x/prid/497133", "497133", "On-Day Eggs 6", "48"),
        ("100256", "https://blinkit.com/prn/x/prid/497132", "497132", "On-Day Eggs 30", "231"),
    ]
    ok = 0
    pw, browser, context, pages = await init_blinkit_browser(pincode, 1)
    try:
        page = pages[0]
        for ic, url, pid, name, ana_sp in test_urls:
            r = await scrape_one_pdp(page, ic, url, pid)
            status = "✅" if r.get("status") == "ok" else "❌"
            sam_sp = r.get("sam_selling_price")
            print(f"  {status} {name[:35]:35s} Ana ₹{ana_sp:>5s} → SAM ₹{sam_sp} ({r.get('status')})", flush=True)
            if r.get("status") == "ok":
                ok += 1
        print(f"\nResult: {ok}/{len(test_urls)} OK", flush=True)
    finally:
        await browser.close()
        await pw.stop()


if __name__ == "__main__":
    asyncio.run(main())
