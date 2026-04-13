"""Test parallel PDP scraping with 5 workers on 10 URLs — verify location fix."""
import asyncio
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(line_buffering=True)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from scrape_blinkit_pdps import init_blinkit_browser, scrape_one_pdp  # noqa


async def worker(name, page, queue, results):
    while True:
        try:
            item_code, url, pid, ana_name, ana_sp = queue.get_nowait()
        except asyncio.QueueEmpty:
            return
        r = await scrape_one_pdp(page, item_code, url, pid)
        results.append({"ana_name": ana_name, "ana_sp": ana_sp, **r})
        print(f"[{name}] {item_code} | {ana_name[:40]} | Ana ₹{ana_sp} → SAM ₹{r.get('sam_selling_price')} ({r.get('status')})", flush=True)


async def main():
    pincode = "834002"
    ana = json.load(open(Path(__file__).resolve().parent.parent / "data/anakin/blinkit_834002_2026-04-11.json"))
    test_urls = []
    for r in ana["records"]:
        if r.get("Blinkit_Product_Id") and r["Blinkit_Product_Id"] != "NA":
            if r.get("Blinkit_Selling_Price") and r["Blinkit_Selling_Price"] != "NA":
                test_urls.append((
                    r["Item_Code"], r["Blinkit_Product_Url"], r["Blinkit_Product_Id"],
                    r["Item_Name"], r["Blinkit_Selling_Price"]
                ))
                if len(test_urls) >= 10:
                    break

    print(f"[test] {len(test_urls)} urls × 5 workers", flush=True)

    num_tabs = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    pw, browser, context, pages = await init_blinkit_browser(pincode, num_tabs)
    try:
        queue = asyncio.Queue()
        for u in test_urls:
            queue.put_nowait(u)
        results = []
        workers = [worker(f"w{i}", pages[i], queue, results) for i in range(num_tabs)]
        await asyncio.gather(*workers)

        ok = sum(1 for r in results if r.get("status") == "ok")
        print(f"\n[test] OK: {ok}/{len(results)}", flush=True)
    finally:
        await browser.close()
        await pw.stop()


if __name__ == "__main__":
    asyncio.run(main())
