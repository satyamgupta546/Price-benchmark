"""Dump the Blinkit /v1/layout/product/{prid} API response structure."""
import asyncio
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(line_buffering=True)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from scrape_blinkit_pdps import init_blinkit_browser  # noqa


async def main():
    pincode = "834002"
    pw, browser, context, pages = await init_blinkit_browser(pincode, 1)
    page = pages[0]
    captured = {}

    async def on_response(response):
        try:
            url = response.url
            if "/v1/layout/product/" in url and response.status == 200:
                body = await response.text()
                captured["layout"] = json.loads(body)
                captured["url"] = url
        except Exception:
            pass

    page.on("response", on_response)
    try:
        # Use one of the failed URLs
        url = "https://blinkit.com/prn/x/prid/18562"
        print(f"Visiting: {url}", flush=True)
        await page.goto(url, wait_until="domcontentloaded", timeout=20000)
        await asyncio.sleep(2)

        if "layout" not in captured:
            print("No /v1/layout/product/ response captured!", flush=True)
            return

        data = captured["layout"]
        print(f"\nAPI URL: {captured['url'][:100]}", flush=True)
        print(f"Top-level keys: {list(data.keys())}", flush=True)
        print(f"Total size: {len(json.dumps(data))} chars", flush=True)

        # Walk top levels
        def show_structure(d, prefix="", depth=0):
            if depth > 3:
                return
            if isinstance(d, dict):
                for k, v in list(d.items())[:15]:
                    if isinstance(v, dict):
                        print(f"{prefix}{k}: (dict, {len(v)} keys: {list(v.keys())[:8]})", flush=True)
                        if any(pk in v for pk in ("mrp", "price", "offer_price", "selling_price", "name", "product_name")):
                            print(f"{prefix}  *** HAS PRICE/NAME FIELDS ***", flush=True)
                            for pk in ("name", "product_name", "mrp", "price", "offer_price", "selling_price", "id"):
                                if pk in v:
                                    pv = v[pk]
                                    if isinstance(pv, dict):
                                        print(f"{prefix}    {pk}: (dict) {list(pv.keys())[:8]}", flush=True)
                                    else:
                                        print(f"{prefix}    {pk}: {str(pv)[:80]}", flush=True)
                        show_structure(v, prefix + "  ", depth + 1)
                    elif isinstance(v, list):
                        print(f"{prefix}{k}: (list, {len(v)} items)", flush=True)
                        if v and isinstance(v[0], dict):
                            # Check first item for product-like shape
                            f0 = v[0]
                            if any(pk in f0 for pk in ("mrp", "price", "offer_price", "name", "product_name")):
                                print(f"{prefix}  *** FIRST ITEM HAS PRICE/NAME ***", flush=True)
                                for pk in ("name", "product_name", "mrp", "price", "offer_price", "id", "unit"):
                                    if pk in f0:
                                        pv = f0[pk]
                                        if isinstance(pv, dict):
                                            print(f"{prefix}    {pk}: (dict) {list(pv.keys())[:8]}", flush=True)
                                        else:
                                            print(f"{prefix}    {pk}: {str(pv)[:80]}", flush=True)
                            show_structure(v[0], prefix + "  [0].", depth + 1)
                    else:
                        print(f"{prefix}{k}: {str(v)[:80]}", flush=True)

        show_structure(data)

    finally:
        page.remove_listener("response", on_response)
        await browser.close()
        await pw.stop()


if __name__ == "__main__":
    asyncio.run(main())
