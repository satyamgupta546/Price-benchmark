"""Quick sanity test: scrape 5 known PDPs and print what we extracted."""
import asyncio
import sys
from pathlib import Path
import json

sys.stdout.reconfigure(line_buffering=True)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from scrape_blinkit_pdps import init_blinkit_browser, scrape_one_pdp  # noqa


async def main():
    pincode = "834002"
    # Pick 5 known (item_code, url, prid) from Anakin data
    ana = json.load(open(Path(__file__).resolve().parent.parent / "data/anakin/blinkit_834002_2026-04-11.json"))
    test_urls = []
    for r in ana["records"]:
        if r.get("Blinkit_Product_Id") and r["Blinkit_Product_Id"] != "NA":
            if r.get("Blinkit_Selling_Price") and r["Blinkit_Selling_Price"] != "NA":
                test_urls.append((r["Item_Code"], r["Blinkit_Product_Url"], r["Blinkit_Product_Id"],
                                  r["Item_Name"], r["Blinkit_Selling_Price"]))
                if len(test_urls) >= 5:
                    break

    print(f"[test] testing {len(test_urls)} URLs...", flush=True)
    pw, browser, context, pages = await init_blinkit_browser(pincode, 1)
    try:
        page = pages[0]
        for ic, url, pid, name, ana_sp in test_urls:
            print(f"\n[test] {ic} | {name[:50]} | Anakin SP: {ana_sp}", flush=True)
            print(f"[test] url: {url}", flush=True)
            result = await scrape_one_pdp(page, ic, url, pid)
            print(f"[test]   sam name:  {result.get('sam_product_name')}", flush=True)
            print(f"[test]   sam SP:    {result.get('sam_selling_price')}", flush=True)
            print(f"[test]   sam MRP:   {result.get('sam_mrp')}", flush=True)
            print(f"[test]   sam stock: {result.get('sam_in_stock')}", flush=True)
            print(f"[test]   status:     {result.get('status')}", flush=True)
    finally:
        await browser.close()
        await pw.stop()


if __name__ == "__main__":
    asyncio.run(main())
