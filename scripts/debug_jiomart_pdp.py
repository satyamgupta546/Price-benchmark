"""Debug: check 5 failed Jiomart PDPs to find why price extraction fails."""
import asyncio
import json
import sys
import glob
from pathlib import Path

sys.stdout.reconfigure(line_buffering=True)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from scrape_jiomart_pdps import init_jiomart_browser  # noqa


async def main():
    ana = json.load(open(sorted(glob.glob(str(Path(__file__).resolve().parent.parent / "data/anakin/jiomart_834002_*.json")))[-1]))
    cmp_files = sorted(glob.glob(str(Path(__file__).resolve().parent.parent / "data/comparisons/jiomart_pdp_834002_*_compare.json")))
    cmp = json.load(open(cmp_files[-1]))

    no_price_codes = {m.get("item_code") for m in cmp.get("matches", []) if m.get("match_status") == "no_price_on_pdp"}

    test = []
    for r in ana["records"]:
        ic = r.get("Item_Code")
        if ic in no_price_codes and r.get("Jiomart_In_Stock_Remark") == "available":
            url = r.get("Jiomart_Product_Url", "")
            pid = str(r.get("Jiomart_Product_Id", "")).strip()
            if url.startswith("http") and pid and pid != "NA":
                test.append((ic, url, pid, r.get("Item_Name"), r.get("Jiomart_Selling_Price")))
                if len(test) >= 5:
                    break

    print(f"Testing {len(test)} failed Jiomart URLs...", flush=True)
    pw, browser, context, pages = await init_jiomart_browser("834002", 1)
    try:
        page = pages[0]
        for ic, url, pid, name, ana_sp in test:
            print(f"\n{'='*60}", flush=True)
            print(f"{ic} | {name[:45]} | Ana SP={ana_sp}", flush=True)
            print(f"URL: {url}", flush=True)

            captured = []

            async def on_resp(response):
                try:
                    ct = response.headers.get("content-type", "")
                    if "json" in ct and response.status == 200:
                        body = await response.text()
                        if len(body) > 50:
                            captured.append({"url": response.url[:100], "size": len(body),
                                             "data": json.loads(body)})
                except Exception:
                    pass

            page.on("response", on_resp)
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=25000)
                await asyncio.sleep(2)

                print(f"  Captured {len(captured)} JSON responses:", flush=True)
                for c in captured[:8]:
                    print(f"    {c['url']} ({c['size']} bytes)", flush=True)

                # Check JSON-LD
                ld_data = await page.evaluate("""() => {
                    const scripts = document.querySelectorAll('script[type="application/ld+json"]');
                    const results = [];
                    for (const s of scripts) {
                        try {
                            results.push(JSON.parse(s.textContent));
                        } catch(e) {}
                    }
                    return results;
                }""")
                print(f"  JSON-LD: {len(ld_data)} scripts found", flush=True)
                for ld in ld_data:
                    if isinstance(ld, dict):
                        t = ld.get("@type", "?")
                        n = ld.get("name", "?")[:50]
                        offers = ld.get("offers", {})
                        price = offers.get("price") or offers.get("lowPrice")
                        print(f"    @type={t} name={n} price={price}", flush=True)

                # Check OG tags
                og = await page.evaluate("""() => {
                    const t = document.querySelector('meta[property="og:title"]');
                    const p = document.querySelector('meta[property="product:price:amount"]');
                    return {title: t ? t.getAttribute('content') : null,
                            price: p ? p.getAttribute('content') : null};
                }""")
                print(f"  OG: title={og.get('title','')[:50]} price={og.get('price')}", flush=True)

                # Check all prices on page
                prices = await page.evaluate("""() => {
                    const text = document.body ? document.body.innerText : '';
                    const matches = [...text.matchAll(/\\u20B9\\s*([\\d,]+\\.?\\d*)/g)]
                        .map(m => parseFloat(m[1].replace(/,/g, '')))
                        .filter(p => p > 0 && p < 100000);
                    return [...new Set(matches)].sort((a, b) => a - b).slice(0, 15);
                }""")
                print(f"  All prices on page: {prices}", flush=True)

                # Check page title + h1
                info = await page.evaluate("""() => {
                    const h1s = [...document.querySelectorAll('h1')]
                        .map(h => h.innerText.trim()).filter(t => t.length > 3);
                    return {title: document.title.substring(0, 80),
                            h1s: h1s.slice(0, 3),
                            bodyLen: (document.body ? document.body.innerText : '').length};
                }""")
                print(f"  Title: {info.get('title')}", flush=True)
                print(f"  H1s: {info.get('h1s')}", flush=True)
                print(f"  Body: {info.get('bodyLen')} chars", flush=True)

            finally:
                page.remove_listener("response", on_resp)

    finally:
        await browser.close()
        await pw.stop()


if __name__ == "__main__":
    asyncio.run(main())
