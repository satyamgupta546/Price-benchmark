"""
Flipkart Minutes Scraper — Cookie-based login, API intercept + DOM extraction.

Same approach as Blinkit/Jiomart:
  1. Load cookies (logged-in session)
  2. Set location via geolocation
  3. Navigate categories
  4. Intercept API responses for product data (JSON)
  5. DOM fallback extraction
  6. Match with AM products (UnifiedMatchingEngine)
  7. Save URLs + JSON

Usage:
    python3 scripts/scrape_flipkart_minutes.py 834008
    python3 scripts/scrape_flipkart_minutes.py 834008 --match
"""
import asyncio
import json
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

sys.stdout.reconfigure(line_buffering=True)
sys.path.insert(0, str(Path(__file__).resolve().parent))

from playwright.async_api import async_playwright

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA = PROJECT_ROOT / "data"

PINCODE_COORDS = {
    "834008": {"lat": 23.3869, "lon": 85.3202, "label": "Gandhi Nagar, Kanke, Ranchi"},
    "834002": {"lat": 23.3441, "lon": 85.3096, "label": "Ranchi"},
    "700001": {"lat": 22.5726, "lon": 88.3639, "label": "Kolkata"},
    "712232": {"lat": 22.5850, "lon": 88.3200, "label": "Kolkata Howrah"},
    "492001": {"lat": 21.2514, "lon": 81.6296, "label": "Raipur (not available)"},
    "831001": {"lat": 22.8046, "lon": 86.2029, "label": "Jamshedpur"},
}

# Flipkart Minutes categories to scrape (all FMCG-relevant)
CATEGORIES = [
    {"name": "Grocery", "tab": "Grocery"},
    {"name": "Fresh", "tab": "Fresh"},
    {"name": "Beauty", "tab": "Beauty"},
    {"name": "Home", "tab": "Home"},
    {"name": "Summer", "tab": "Summer"},
    {"name": "Deal Zone", "tab": "Deal Zone"},
    {"name": "XtraSaver", "tab": "XtraSaver"},
    {"name": "Kids", "tab": "Kids"},
    {"name": "Healthcare", "tab": "Healthcare"},
    {"name": "Paan store", "tab": "Paan store"},
]

COOKIES_PATH = DATA / "flipkart_cookies.json"


async def init_browser(pw, pincode):
    """Init Chromium with cookies + geolocation."""
    coords = PINCODE_COORDS.get(pincode, PINCODE_COORDS["834008"])

    cookies = json.load(open(COOKIES_PATH)) if COOKIES_PATH.exists() else []
    if not cookies:
        print("  ERROR: No flipkart_cookies.json — login first!", flush=True)
        return None, None, None

    browser = await pw.chromium.launch(headless=True)
    context = await browser.new_context(
        user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                   "AppleWebKit/537.36 Chrome/125.0.0.0 Safari/537.36",
        viewport={"width": 1366, "height": 768},
        geolocation={"latitude": coords["lat"], "longitude": coords["lon"]},
        permissions=["geolocation"],
    )
    await context.add_cookies(cookies)
    page = await context.new_page()
    return browser, context, page


async def scrape_page(page, url, scroll_times=12):
    """Visit URL, intercept API responses, extract products from API + DOM."""
    captured_products = []

    async def on_response(response):
        """Intercept API JSON responses for product data."""
        try:
            resp_url = response.url
            ct = response.headers.get("content-type", "")
            if response.status == 200 and "json" in ct:
                # Flipkart API responses with product data
                if any(k in resp_url for k in ["hyperlocal", "minutes", "grocery", "widget", "feed"]):
                    body = await response.text()
                    if len(body) > 200 and "productId" in body or "title" in body:
                        data = json.loads(body)
                        _extract_from_json(data, captured_products, depth=0)
        except Exception:
            pass

    page.on("response", on_response)

    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=25000)
    except Exception:
        pass
    await asyncio.sleep(3)

    # Set location if prompted
    try:
        loc_btn = page.locator("text=Use my current location").first
        if await loc_btn.is_visible(timeout=2000):
            await loc_btn.click()
            await asyncio.sleep(4)
    except Exception:
        pass

    # Scroll to load all products
    prev_count = 0
    for _ in range(scroll_times):
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await asyncio.sleep(1)
        count = await page.evaluate("document.querySelectorAll('img[src*=rukminim]').length")
        if count == prev_count:
            break
        prev_count = count

    # DOM extraction fallback
    dom_products = await _extract_from_dom(page)

    page.remove_listener("response", on_response)

    # Merge: API products + DOM products (dedup by name)
    all_products = {}
    for p in captured_products:
        name = p.get("name", "")
        if name and len(name) >= 5:
            all_products[name] = p
    for p in dom_products:
        name = p.get("name", "")
        if name and name not in all_products:
            all_products[name] = p

    return list(all_products.values())


def _extract_from_json(data, results, depth=0):
    """Recursively extract product data from Flipkart API JSON."""
    if depth > 10:
        return
    if isinstance(data, dict):
        # Check if this dict is a product
        title = data.get("title") or data.get("name") or data.get("productName")
        price = data.get("price") or data.get("sellingPrice") or data.get("finalPrice")
        mrp = data.get("mrp") or data.get("maximumRetailPrice") or data.get("originalPrice")

        if title and price:
            # Extract unit/weight from title or separate field
            unit = data.get("unit") or data.get("quantity") or data.get("packSize") or ""
            brand = data.get("brand") or data.get("brandName") or ""
            pid = data.get("productId") or data.get("id") or ""
            img = data.get("image") or data.get("imageUrl") or ""
            link = (data.get("url") or data.get("link") or data.get("smartUrl")
                    or data.get("baseUrl") or data.get("pageUri") or "")
            if isinstance(link, dict):
                link = link.get("url") or link.get("href") or ""
            link = str(link or "").strip()
            if link.startswith("/"):
                link = "https://www.flipkart.com" + link
            if not link.startswith("http"):
                link = f"https://www.flipkart.com/p/itm?pid={pid}" if pid else ""

            # Parse price if nested
            if isinstance(price, dict):
                price = price.get("value") or price.get("amount") or price.get("finalPrice")
            if isinstance(mrp, dict):
                mrp = mrp.get("value") or mrp.get("amount")

            try:
                sp_val = float(price) if price else None
                mrp_val = float(mrp) if mrp else None
                if sp_val and sp_val > 0:
                    results.append({
                        "name": str(title).strip(),
                        "brand": str(brand).strip(),
                        "sp": sp_val,
                        "mrp": mrp_val if mrp_val and mrp_val != sp_val else None,
                        "unit": str(unit).strip(),
                        "product_id": str(pid),
                        "url": link[:300],
                        "image": str(img)[:200] if img else "",
                    })
            except (ValueError, TypeError):
                pass

        # Recurse into values
        for val in data.values():
            _extract_from_json(val, results, depth + 1)

    elif isinstance(data, list):
        for item in data:
            _extract_from_json(item, results, depth + 1)


async def _extract_from_dom(page):
    """Extract products from Flipkart Minutes DOM."""
    products = await page.evaluate(r'''() => {
        const results = [];
        const seen = new Set();

        // Flipkart Minutes product cards
        const allDivs = document.querySelectorAll('div');
        const cards = [];
        for (const div of allDivs) {
            const hasImg = div.querySelector('img[src*="rukminim"]');
            const text = div.innerText || '';
            if (!hasImg || !text.includes('₹') || text.length < 20 || text.length > 600) continue;
            if (div.children.length < 2 || div.children.length > 25) continue;
            let isLeaf = true;
            for (const child of div.children) {
                if (child.querySelector('img[src*="rukminim"]') && (child.innerText || '').includes('₹')) {
                    isLeaf = false; break;
                }
            }
            if (isLeaf) cards.push(div);
        }

        // Flipkart Minutes card structure:
        // Line 1: ↓11% (discount)
        // Line 2: 4.5 (rating)
        // Line 3: 12 x 70 g (UNIT — before name!)
        // Line 4: Maggi 2-Minute... (PRODUCT NAME — longest line with letters)
        // Line 5+: ₹prices, XtraSaver

        const skipRe = [
            /^↓?\d+%$/,
            /^₹/,
            /^\d+\.?\d*$/,
            /^\d+\.\d+$/,
            /^Add$/i,
            /^add to/i,
            /% off$/i,
            /^XtraSaver/i,
            /^Featured/i,
            /^Recommended/i,
            /^★/,
            /^sponsored/i,
            /^free delivery/i,
            /^\+$/,
            /^min$/i,
            /^\d+\s*min$/i,
        ];

        // Unit patterns
        const unitRe = /^\d+\.?\d*\s*(x\s*\d|g\b|kg\b|ml\b|l\b|L\b|gm\b|ltr\b|pc|pcs|pack|Bottle|Can|Pouch|Sachet)/i;

        for (const card of cards) {
            const lines = (card.innerText || '').split('\n').map(l => l.trim()).filter(l => l);
            let name = '';
            let unit = '';
            let brand = '';

            // Strategy: pick LONGEST line with 3+ letters as product name
            // Unit = line matching unit pattern
            let bestNameLine = '';
            let bestNameLen = 0;

            for (const line of lines) {
                if (skipRe.some(r => r.test(line))) continue;
                if (line.startsWith('₹')) continue;

                // Unit line
                if (unitRe.test(line)) {
                    if (!unit) unit = line;
                    continue;
                }

                // Candidate for product name — longest line wins
                if (line.length >= 5 && line.length < 250 && /[a-zA-Z]{3,}/.test(line)) {
                    if (line.length > bestNameLen) {
                        bestNameLen = line.length;
                        bestNameLine = line;
                    }
                }
            }

            name = bestNameLine;
            if (!name || name.length < 5) continue;

            // Extract brand from first word of name
            const words = name.split(/\s+/);
            if (words.length > 1) brand = words[0];

            // Clean name
            name = name.replace(/^\d+\.\s+/, '');

            // Extract prices from leaf DOM elements
            const priceSet = new Set();
            for (const el of card.querySelectorAll('*')) {
                const t = el.textContent?.trim() || '';
                if (t.includes('₹') && t.length <= 25) {
                    for (const m of t.matchAll(/₹([\d,]+\.?\d*)/g)) {
                        const p = parseFloat(m[1].replace(/,/g, ''));
                        if (p > 0 && p <= 50000) priceSet.add(p);
                    }
                }
            }
            const prices = [...priceSet];
            const sp = prices.length > 0 ? Math.min(...prices) : null;
            const mrp = prices.length > 1 ? Math.max(...prices) : null;

            // Product link: nearest wrapping/descendant anchor pointing to a PDP
            let url = '';
            const a = card.closest('a[href]') || card.querySelector('a[href*="/p/"]') || card.querySelector('a[href]');
            if (a) {
                let href = a.getAttribute('href') || '';
                if (href.startsWith('/')) href = location.origin + href;
                if (href.startsWith('http')) url = href.slice(0, 300);
            }

            if (sp && !seen.has(name)) {
                seen.add(name);
                results.push({name, sp, mrp: mrp !== sp ? mrp : null, unit, brand, url});
            }
        }
        return results;
    }''')
    return products


async def scrape_all_categories(page, pincode):
    """Scrape all categories by clicking category tabs."""
    all_products = {}

    # First load homepage
    url = "https://www.flipkart.com/hyperlocal-grocery-new-ab-at-store?marketplace=HYPERLOCAL"
    initial = await scrape_page(page, url, scroll_times=15)
    for p in initial:
        name = p.get("name", "")
        if name:
            all_products[name] = p
    print(f"  Homepage: {len(initial)} products", flush=True)

    # Click each category tab
    for cat in CATEGORIES:
        try:
            tab = page.locator(f'text="{cat["tab"]}"').first
            if await tab.is_visible(timeout=2000):
                await tab.click()
                await asyncio.sleep(3)

                # Scroll
                for _ in range(10):
                    await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    await asyncio.sleep(1)
                    count = await page.evaluate("document.querySelectorAll('img[src*=rukminim]').length")

                # Extract
                dom = await _extract_from_dom(page)
                new = 0
                for p in dom:
                    name = p.get("name", "")
                    if name and name not in all_products:
                        all_products[name] = p
                        new += 1
                print(f"  {cat['name']}: +{new} new (total {len(all_products)})", flush=True)
        except Exception as e:
            print(f"  {cat['name']}: ERROR {str(e)[:50]}", flush=True)

    # Also try search for common terms to find more products
    search_terms = ["atta", "rice", "oil", "dal", "sugar", "salt", "soap", "shampoo",
                    "biscuit", "chips", "tea", "coffee", "milk", "ghee", "masala",
                    "detergent", "noodles", "juice", "water", "diaper", "toothpaste"]

    for term in search_terms:
        try:
            search_url = f"https://www.flipkart.com/search?q={term}&marketplace=HYPERLOCAL"
            products = await scrape_page(page, search_url, scroll_times=5)
            new = 0
            for p in products:
                name = p.get("name", "")
                if name and name not in all_products:
                    all_products[name] = p
                    new += 1
            if new > 0:
                print(f"  Search '{term}': +{new} new", flush=True)
        except Exception:
            pass
        await asyncio.sleep(0.5)

    return list(all_products.values())


async def main():
    pincode = sys.argv[1] if len(sys.argv) > 1 else "834008"
    do_match = "--match" in sys.argv

    print(f"\n{'=' * 60}")
    print(f"  FLIPKART MINUTES SCRAPER — {pincode}")
    print(f"{'=' * 60}\n")

    coords = PINCODE_COORDS.get(pincode, {})
    print(f"  Location: {coords.get('label', pincode)}")
    print(f"  Cookies: {COOKIES_PATH.exists()}")

    pw = await async_playwright().start()
    browser, context, page = await init_browser(pw, pincode)
    if not page:
        return

    # Scrape all categories + search
    products = await scrape_all_categories(page, pincode)

    print(f"\n  Total unique products: {len(products)}")

    # Parse unit from name if missing
    unit_re = re.compile(r'(\d+\.?\d*)\s*(g|gm|kg|ml|l|L|ltr|pc|pcs|pack)\b', re.IGNORECASE)
    for p in products:
        if not p.get("unit"):
            m = unit_re.search(p.get("name", ""))
            if m:
                p["unit"] = f"{m.group(1)} {m.group(2)}"

    # Remove fruits/vegetables (no unit, not FMCG)
    skip_fresh = {"kiwi", "capsicum", "brinjal", "zucchini", "tomato", "onion", "potato",
                  "banana", "apple", "papaya", "guava", "watermelon", "cucumber",
                  "carrot", "beans", "peas", "spinach", "cabbage", "cauliflower",
                  "mushroom", "coriander", "ginger raw", "chilli green", "lemon raw"}
    before = len(products)
    products = [p for p in products if not any(
        kw in p.get("name", "").lower() for kw in skip_fresh)]
    if before != len(products):
        print(f"  Removed {before - len(products)} fresh/veg items", flush=True)

    # Save JSON
    ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    out_path = DATA / f"flipkart_minutes_{pincode}_{ts}.json"
    with open(out_path, "w") as f:
        json.dump({
            "pincode": pincode,
            "scraped_at": datetime.now().isoformat(),
            "total": len(products),
            "products": products,
        }, f, indent=2, ensure_ascii=False, default=str)
    print(f"  Saved: {out_path.name}")

    await browser.close()
    await pw.stop()

    # Match with AM products using ALL logic (same as Blinkit/Jiomart)
    if do_match and products:
        import csv
        from unified_matcher import UnifiedMatchingEngine
        from utils import parse_num, normalize

        am_map = json.load(open(DATA / "am_product_master.json")) if (DATA / "am_product_master.json").exists() else {}
        ean_map = json.load(open(DATA / "ean_map.json")) if (DATA / "ean_map.json").exists() else {}

        # MRP source: latestproductpricingtracker (same as Jiomart)
        pricing_path = DATA / "am_pricing_wrhs_1.json"
        mrp_map = json.load(open(pricing_path)) if pricing_path.exists() else {}
        print(f"  MRP source: am_pricing ({len(mrp_map)} items)", flush=True)

        # Load HD assortment — match only HD products (same as Jiomart)
        hd_csv = DATA / "hd_assortment.csv"
        hd_items = {}
        if hd_csv.exists():
            with open(hd_csv, newline="", encoding="utf-8-sig") as f:
                for row in csv.DictReader(f):
                    # Filter by state based on pincode
                    state = row.get("State", "").strip()
                    ic = str(row.get("Item Code", "")).strip()
                    if ic:
                        am = am_map.get(ic, {})
                        hd_items[ic] = {
                            "item_code": ic,
                            "display_name": row.get("Item Name", "") or am.get("display_name", ""),
                            "brand": row.get("Brand", "") or am.get("brand", ""),
                            "master_category": row.get("Master Catgory", "").strip() or am.get("master_category", ""),
                            "product_type": row.get("Product Type", "") or am.get("product_type", ""),
                            "unit": am.get("unit", ""),
                            "unit_value": am.get("unit_value"),
                            "mrp": am.get("mrp"),
                        }
            print(f"  HD items: {len(hd_items)}", flush=True)

        # Use HD items if available, else all AM
        target = hd_items if hd_items else {
            ic: am for ic, am in am_map.items()
            if am.get("master_category") in {"STPLS", "FMCG", "FMCGF", "FMCGNF", "GM"}
        }

        # Build pool with better brand extraction
        pool = []
        for p in products:
            name = p["name"]
            brand = p.get("brand", "")

            # Better brand: if first word is generic, try extracting known brand
            generic_words = {"red", "green", "yellow", "black", "white", "indian",
                             "premium", "fresh", "organic", "natural", "pure",
                             "jeera", "toor", "urad", "moong", "chana", "sugar",
                             "salt", "rice", "atta", "dal", "oil"}
            if brand.lower() in generic_words or not brand:
                # Try matching with known AM brands
                name_lower = normalize(name)
                for ic, am in target.items():
                    am_brand = (am.get("brand") or "").strip()
                    if am_brand and am_brand.lower() in name_lower:
                        brand = am_brand
                        break

            pool.append({
                "product_id": p.get("product_id", ""),
                "product_name": name,
                "brand": brand,
                "price": p["sp"],
                "mrp": p.get("mrp"),
                "unit": p.get("unit", ""),
                "url": p.get("url", ""),
                "in_stock": True,
            })

        engine = UnifiedMatchingEngine(ean_map)
        engine.set_pool(pool)

        from collections import Counter
        status_counts = Counter()
        matched = []

        for ic, am in target.items():
            mrp_rec = mrp_map.get(ic)
            am_mrp = parse_num(mrp_rec.get("mrp")) if mrp_rec else parse_num(am.get("mrp"))
            result = engine.match(am, am_mrp)
            status_counts[result.status] += 1
            if result.product:
                matched.append({
                    "item_code": ic,
                    "am_name": am.get("display_name"),
                    "am_brand": am.get("brand"),
                    "fk_name": result.product.get("product_name"),
                    "fk_sp": result.product.get("price"),
                    "fk_mrp": result.product.get("mrp"),
                    "fk_unit": result.product.get("unit"),
                    "fk_url": result.product.get("url", ""),
                    "match_status": result.status,
                    "match_score": round(result.score, 3),
                    "match_reason": result.reason,
                    "match_flags": ", ".join(result.flags) if result.flags else "",
                })

        total = sum(status_counts.values())
        print(f"\n  Match results ({total} items):")
        for s, c in status_counts.most_common():
            print(f"    {s:25s} {c:5d}  ({c/total*100:.1f}%)")
        print(f"  Total matched: {len(matched)} ({len(matched)/total*100:.1f}%)")

        match_path = DATA / f"flipkart_minutes_match_{pincode}_{ts}.json"
        with open(match_path, "w") as f:
            json.dump({
                "pincode": pincode,
                "total_matched": len(matched),
                "total_items": total,
                "status_counts": dict(status_counts),
                "matches": matched,
            }, f, indent=2, default=str)
        print(f"  Match saved: {match_path.name}")


if __name__ == "__main__":
    asyncio.run(main())
