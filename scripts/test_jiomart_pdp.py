"""Test: scrape 5 JioMart PDPs and print extracted price vs Anakin."""
import asyncio
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(line_buffering=True)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from scrape_jiomart_pdps import init_jiomart_browser, scrape_one_jiomart_pdp  # noqa


async def main():
    pincode = "834002"
    ana = json.load(open(Path(__file__).resolve().parent.parent / "data/anakin/jiomart_834002_2026-04-11.json"))
    test = []
    for r in ana["records"]:
        if r.get("Jiomart_Product_Id") and r["Jiomart_Product_Id"] not in ("", "NA"):
            if r.get("Jiomart_Selling_Price") and r["Jiomart_Selling_Price"] not in ("", "NA"):
                test.append((
                    r["Item_Code"], r["Jiomart_Product_Url"], str(r["Jiomart_Product_Id"]).strip(),
                    r["Item_Name"], r["Jiomart_Selling_Price"]
                ))
                if len(test) >= 5:
                    break
    print(f"[test-jm] {len(test)} URLs", flush=True)
    pw, browser, context, pages = await init_jiomart_browser(pincode, 1)
    try:
        page = pages[0]
        for ic, url, pid, name, ana_sp in test:
            print(f"\n[test-jm] {ic} | {name[:50]} | Ana ₹{ana_sp}", flush=True)
            print(f"[test-jm] url: {url}", flush=True)
            r = await scrape_one_jiomart_pdp(page, ic, url, pid)
            print(f"[test-jm]   sam name:  {r.get('sam_product_name')}", flush=True)
            print(f"[test-jm]   sam SP:    {r.get('sam_selling_price')}", flush=True)
            print(f"[test-jm]   sam MRP:   {r.get('sam_mrp')}", flush=True)
            print(f"[test-jm]   status:     {r.get('status')}", flush=True)
    finally:
        await browser.close()
        await pw.stop()


if __name__ == "__main__":
    asyncio.run(main())
