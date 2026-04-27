"""Quick test: Visit one Blinkit PDP and capture all API URLs + responses."""
import asyncio
import json
import sys
sys.path.insert(0, "scripts")
from scrape_blinkit_pdps import init_blinkit_browser


async def main():
    pincode = "834002"
    pw, browser, context, pages = await init_blinkit_browser(pincode, 1)
    page = pages[0]

    captured = []

    async def on_response(response):
        try:
            ct = response.headers.get("content-type", "")
            if "json" not in ct or response.status != 200:
                return
            url = response.url
            body = await response.text()
            if len(body) > 50:
                low = body.lower()
                if any(kw in low for kw in ("mrp", "price", "product", "selling")):
                    data = json.loads(body)
                    captured.append({"url": url, "size": len(body), "data": data})
                    print(f"  CAPTURED: {url[:120]} ({len(body)} bytes)")
        except Exception:
            pass

    page.on("response", on_response)

    # Visit one product
    test_url = "https://blinkit.com/prn/x/prid/581162"
    print(f"Visiting: {test_url}")
    await page.goto(test_url, wait_until="domcontentloaded", timeout=20000)
    await asyncio.sleep(4)

    print(f"\n=== Captured {len(captured)} API responses ===")
    for i, c in enumerate(captured):
        print(f"\n--- Response {i+1}: {c['url'][:150]} ---")
        # Print first level keys
        if isinstance(c['data'], dict):
            print(f"  Keys: {list(c['data'].keys())[:10]}")
        print(f"  Size: {c['size']} bytes")

    # Save for analysis
    with open("data/blinkit_api_capture.json", "w") as f:
        json.dump(captured, f, indent=2, default=str)
    print(f"\nSaved to data/blinkit_api_capture.json")

    await browser.close()
    await pw.stop()


asyncio.run(main())
