"""Dump Blinkit layout API snippets to find where product name/price lives."""
import asyncio
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(line_buffering=True)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from scrape_blinkit_pdps import init_blinkit_browser  # noqa


def find_price_objects(data, path="", depth=0, results=None):
    """Find all dicts that have BOTH a name-like field AND a price-like field."""
    if results is None:
        results = []
    if depth > 12:
        return results
    if isinstance(data, dict):
        has_name = any(k in data for k in ("name", "product_name", "title", "display_name"))
        has_price = any(k in data for k in ("mrp", "price", "offer_price", "selling_price"))
        if has_name and has_price:
            results.append({"path": path, "data": data})
        for k, v in data.items():
            find_price_objects(v, f"{path}.{k}", depth + 1, results)
    elif isinstance(data, list):
        for i, item in enumerate(data):
            find_price_objects(item, f"{path}[{i}]", depth + 1, results)
    return results


async def main():
    pincode = "834002"
    pw, browser, context, pages = await init_blinkit_browser(pincode, 1)
    page = pages[0]
    layout_data = None

    async def on_response(response):
        nonlocal layout_data
        try:
            if "/v1/layout/product/" in response.url and response.status == 200:
                body = await response.text()
                layout_data = json.loads(body)
        except Exception:
            pass

    page.on("response", on_response)
    try:
        await page.goto("https://blinkit.com/prn/x/prid/18562", wait_until="domcontentloaded", timeout=20000)
        await asyncio.sleep(2)

        if not layout_data:
            print("No layout response!", flush=True)
            return

        print("Searching for product-shaped objects (has name + price)...\n", flush=True)
        results = find_price_objects(layout_data)
        print(f"Found {len(results)} objects with name+price fields:\n", flush=True)

        for r in results[:5]:
            d = r["data"]
            print(f"PATH: {r['path'][:100]}", flush=True)
            print(f"  Keys: {list(d.keys())[:15]}", flush=True)
            for k in ("name", "product_name", "title", "display_name",
                       "mrp", "price", "offer_price", "selling_price",
                       "id", "product_id", "unit", "weight", "brand"):
                if k in d:
                    v = d[k]
                    if isinstance(v, dict):
                        print(f"  {k}: (dict) {dict(list(v.items())[:5])}", flush=True)
                    elif isinstance(v, list):
                        print(f"  {k}: (list, {len(v)} items) first={v[0] if v else '?'}", flush=True)
                    else:
                        print(f"  {k}: {str(v)[:100]}", flush=True)
            print(flush=True)

    finally:
        page.remove_listener("response", on_response)
        await browser.close()
        await pw.stop()


if __name__ == "__main__":
    asyncio.run(main())
