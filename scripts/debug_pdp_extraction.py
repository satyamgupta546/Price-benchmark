"""Debug: Visit 5 failed PDP URLs and log everything — captured API responses,
DOM state, what product_id match finds, why price extraction fails."""
import asyncio
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(line_buffering=True)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from scrape_blinkit_pdps import init_blinkit_browser  # noqa


async def debug_one_pdp(page, item_code, url, prid):
    """Visit a PDP and dump ALL captured data for debugging."""
    captured = []

    async def on_response(response):
        try:
            ct = response.headers.get("content-type", "")
            if "json" not in ct or response.status != 200:
                return
            body = await response.text()
            if len(body) < 50:
                return
            data = json.loads(body)
            captured.append({"url": response.url[:120], "size": len(body), "data": data})
        except Exception:
            pass

    page.on("response", on_response)
    try:
        print(f"\n{'='*70}", flush=True)
        print(f"DEBUG: item_code={item_code}, prid={prid}", flush=True)
        print(f"URL: {url}", flush=True)

        await page.goto(url, wait_until="domcontentloaded", timeout=20000)
        await asyncio.sleep(1.5)

        # 1. What API responses did we capture?
        print(f"\n  [API] Captured {len(captured)} JSON responses:", flush=True)
        for i, c in enumerate(captured):
            print(f"    [{i}] {c['url'][:80]}... ({c['size']} bytes)", flush=True)

        # 2. Search for our product_id in captured responses
        print(f"\n  [MATCH] Searching for prid={prid} in captured JSON:", flush=True)
        found_product = None
        for i, c in enumerate(captured):
            result = _find_recursive(c["data"], prid, depth=0, path=f"resp[{i}]")
            if result:
                found_product = result
                break
        if found_product:
            print(f"    FOUND! Keys: {list(found_product.keys())[:15]}", flush=True)
            # Show price-related fields
            for k in ["id", "product_id", "productId", "prid",
                       "price", "mrp", "offer_price", "selling_price",
                       "name", "product_name", "title"]:
                if k in found_product:
                    val = found_product[k]
                    if isinstance(val, dict):
                        print(f"    {k}: (dict) keys={list(val.keys())[:10]}", flush=True)
                        for dk, dv in list(val.items())[:5]:
                            print(f"      {dk}: {str(dv)[:80]}", flush=True)
                    else:
                        print(f"    {k}: {str(val)[:100]}", flush=True)
        else:
            print(f"    NOT FOUND in any response.", flush=True)
            # Show what IDs ARE in the responses
            all_ids = set()
            for c in captured:
                _collect_ids(c["data"], all_ids, depth=0)
            if all_ids:
                print(f"    IDs found in responses: {sorted(list(all_ids))[:20]}", flush=True)
            else:
                print(f"    No recognizable IDs in any response.", flush=True)

        # 3. DOM state — what's the page showing?
        dom_info = await page.evaluate("""() => {
            const h1 = document.querySelector('h1');
            const title = document.title;
            const body = document.body?.innerText || '';
            const priceEls = [];
            for (const el of document.querySelectorAll('*')) {
                const t = (el.textContent || '').trim();
                if (t.includes('₹') && t.length < 25 && el.childElementCount <= 1) {
                    priceEls.push(t);
                }
            }
            return {
                h1: h1 ? h1.innerText.trim().substring(0, 100) : null,
                title: title.substring(0, 100),
                bodyLen: body.length,
                bodyFirst200: body.substring(0, 200),
                priceElements: priceEls.slice(0, 10),
                url: window.location.href,
            };
        }""")
        print(f"\n  [DOM] Page state:", flush=True)
        print(f"    URL:   {dom_info.get('url')}", flush=True)
        print(f"    Title: {dom_info.get('title')}", flush=True)
        print(f"    h1:    {dom_info.get('h1')}", flush=True)
        print(f"    Body:  {dom_info.get('bodyLen')} chars", flush=True)
        print(f"    First 200: {dom_info.get('bodyFirst200','')[:150]}...", flush=True)
        print(f"    ₹ elements: {dom_info.get('priceElements')}", flush=True)

    except Exception as e:
        print(f"  [ERROR] {e}", flush=True)
    finally:
        try:
            page.remove_listener("response", on_response)
        except Exception:
            pass


def _find_recursive(data, target_id, depth=0, path=""):
    """Find a dict with matching product id."""
    if depth > 10:
        return None
    if isinstance(data, dict):
        for k in ("id", "product_id", "productId", "prid"):
            if str(data.get(k, "")) == str(target_id):
                return data
        for k, v in data.items():
            r = _find_recursive(v, target_id, depth + 1, f"{path}.{k}")
            if r:
                return r
    elif isinstance(data, list):
        for i, item in enumerate(data):
            r = _find_recursive(item, target_id, depth + 1, f"{path}[{i}]")
            if r:
                return r
    return None


def _collect_ids(data, ids: set, depth=0):
    if depth > 6:
        return
    if isinstance(data, dict):
        for k in ("id", "product_id", "productId", "prid"):
            v = data.get(k)
            if v and not isinstance(v, (dict, list)):
                ids.add(str(v))
        for v in data.values():
            _collect_ids(v, ids, depth + 1)
    elif isinstance(data, list):
        for item in data:
            _collect_ids(item, ids, depth + 1)


async def main():
    pincode = "834002"
    # 5 known failed URLs (available in Anakin but no_price in SAM)
    test_urls = [
        ("18562", "https://blinkit.com/prn/x/prid/18562", "18562", "Active Wheel Detergent"),
        ("10630", "https://blinkit.com/prn/x/prid/10630", "10630", "Sunsilk Shampoo"),
        ("392509", "https://blinkit.com/prn/x/prid/392509", "392509", "Haldirams Soan Papadi"),
        ("591806", "https://blinkit.com/prn/x/prid/591806", "591806", "Jalan Ragi Atta"),
        ("601164", "https://blinkit.com/prn/x/prid/601164", "601164", "Kellogg's Muesli"),
    ]

    pw, browser, context, pages = await init_blinkit_browser(pincode, 1)
    try:
        page = pages[0]
        for ic, url, prid, name in test_urls:
            await debug_one_pdp(page, ic, url, prid)
    finally:
        await browser.close()
        await pw.stop()


if __name__ == "__main__":
    asyncio.run(main())
