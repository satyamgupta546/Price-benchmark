"""
Jiomart New PDP Scraper — Scrape product details from new /product/ URLs.

Visits each PDP, intercepts catalog + price APIs, extracts:
  product_id, name, sp, mrp, unit, brand, article_id, in_stock, url

Saves ALL product details to data/jiomart_product_master.json so we don't
have to re-scrape static fields (name, brand, unit, article_id) again.
Next time only price API needed.

Usage:
    # Single product
    backend/venv/bin/python scripts/test_jiomart_pdp.py bikaji-bikaneri-bhujia-1-kg-mffmvk-7511132

    # From category page (discover + scrape all)
    backend/venv/bin/python scripts/test_jiomart_pdp.py --category biscuits-cookies --pincode 834002

    # All grocery categories
    backend/venv/bin/python scripts/test_jiomart_pdp.py --all --pincode 834002
"""
import asyncio
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

from playwright.async_api import async_playwright

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA = PROJECT_ROOT / "data"

PINCODE_LOCATION = {
    "834002": {"pincode": "834002", "city": "RANCHI", "state": "JHARKHAND", "lat": "23.3441", "lon": "85.3096"},
    "712232": {"pincode": "712232", "city": "KOLKATA", "state": "WEST BENGAL", "lat": "22.5726", "lon": "88.3639"},
    "492001": {"pincode": "492001", "city": "RAIPUR", "state": "CHHATTISGARH", "lat": "21.2514", "lon": "81.6296"},
    "825301": {"pincode": "825301", "city": "HAZARIBAGH", "state": "JHARKHAND", "lat": "23.9925", "lon": "85.3637"},
    "495001": {"pincode": "495001", "city": "BILASPUR", "state": "CHHATTISGARH", "lat": "22.0797", "lon": "82.1409"},
    "831001": {"pincode": "831001", "city": "JAMSHEDPUR", "state": "JHARKHAND", "lat": "22.8046", "lon": "86.2029"},
}

# Product master — permanent store (name, brand, unit, article_id don't change)
MASTER_PATH = DATA / "jiomart_product_master.json"


def load_master():
    if MASTER_PATH.exists():
        return json.load(open(MASTER_PATH))
    return {}


def save_master(master):
    MASTER_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(MASTER_PATH, "w") as f:
        json.dump(master, f, indent=2, ensure_ascii=False, default=str)


async def init_jiomart_context(pw, pincode="834002"):
    loc = PINCODE_LOCATION.get(pincode, PINCODE_LOCATION["834002"])
    browser = await pw.firefox.launch(headless=True)
    context = await browser.new_context(
        user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:128.0) Gecko/20100101 Firefox/128.0",
        viewport={"width": 1366, "height": 768},
        locale="en-IN", timezone_id="Asia/Kolkata",
    )
    cookie_data = json.dumps({
        "country": "INDIA", "country_iso_code": "IN",
        "city": loc["city"], "pincode": loc["pincode"], "state": loc["state"]
    })
    await context.add_cookies([
        {"name": "pincode", "value": loc["pincode"], "domain": ".jiomart.com", "path": "/"},
        {"name": "app_location_details", "value": quote(cookie_data), "domain": "www.jiomart.com", "path": "/"},
    ])
    await context.add_init_script(f'''
        try {{
            localStorage.setItem('pin', JSON.stringify({{
                country: "INDIA", country_iso_code: "IN",
                pincode: "{loc['pincode']}", city: "{loc['city']}", state: "{loc['state']}"
            }}));
            localStorage.setItem('jio_lat_long', JSON.stringify({{
                latitude: "{loc['lat']}", longitude: "{loc['lon']}"
            }}));
        }} catch(e) {{}}
    ''')
    return browser, context


async def scrape_one_pdp(page, slug, pincode="834002"):
    """Scrape one Jiomart PDP. Returns product dict."""
    url = f"https://www.jiomart.com/product/{slug}"
    product_id = slug.split("-")[-1] if "-" in slug else slug

    result = {
        "product_id": product_id,
        "slug": slug,
        "url": url,
        "pincode": pincode,
        "scraped_at": datetime.now().isoformat(),
    }

    catalog_data = {}
    price_data = {}

    async def on_resp(r):
        nonlocal catalog_data, price_data
        try:
            ct = r.headers.get("content-type", "")
            if r.status != 200 or "json" not in ct:
                return
            body = await r.text()
            if len(body) < 100:
                return
            data = json.loads(body)
            if "/catalog/v1.0/products/" in r.url and "sizes/price" not in r.url and "promotion" not in r.url:
                catalog_data = data
            elif "sizes/price" in r.url and not price_data:
                price_data = data
        except Exception:
            pass

    page.on("response", on_resp)
    try:
        await page.goto(url, wait_until="networkidle", timeout=20000)
        await asyncio.sleep(2)
    except Exception as e:
        result["status"] = "error"
        result["error"] = str(e)[:150]
        page.remove_listener("response", on_resp)
        return result
    page.remove_listener("response", on_resp)

    # === Price API ===
    if price_data:
        price = price_data.get("price", {})
        result["sp"] = price.get("effective") or price.get("selling")
        result["mrp"] = price.get("marked")
        result["article_id"] = price_data.get("article_id", "")
        result["discount"] = price_data.get("discount", "")
        result["in_stock"] = (price_data.get("quantity") or 0) > 0

    # === Catalog API ===
    if catalog_data:
        result["name"] = catalog_data.get("name", "")
        result["brand"] = catalog_data.get("brand", {}).get("name", "") if isinstance(catalog_data.get("brand"), dict) else str(catalog_data.get("brand", ""))
        # Extract weight/unit from attributes
        for attr_group in catalog_data.get("grouped_attributes", []):
            for detail in attr_group.get("details", []):
                key = (detail.get("key") or "").lower()
                val = detail.get("value", "")
                if key == "net quantity":
                    result["net_quantity"] = val
                elif key == "fssai number":
                    result["fssai"] = val

    # === DOM fallback ===
    dom = await page.evaluate(r'''() => {
        const r = {};
        const h1 = document.querySelector('h1, [class*=productTitle]');
        r.name = h1 ? h1.textContent.trim() : '';
        const sp = document.querySelector('[class*=currentPrice]');
        const mrp = document.querySelector('[class*=originalPrice]');
        r.sp = sp ? parseFloat(sp.textContent.replace(/[₹,\s]/g, '')) : null;
        r.mrp = mrp ? parseFloat(mrp.textContent.replace(/[₹,\s]/g, '')) : null;
        // Product info table
        const info = {};
        document.querySelectorAll('table tr').forEach(tr => {
            const cells = tr.querySelectorAll('td');
            if (cells.length >= 2) {
                info[cells[0].textContent.trim().toLowerCase()] = cells[1].textContent.trim();
            }
        });
        r.info = info;
        // Stock
        r.out_of_stock = (document.body?.innerText || '').toLowerCase().includes('out of stock');
        // Unit from size selector
        const sz = document.querySelector('[class*=sizeSelector] [class*=active]');
        r.unit = sz ? sz.textContent.trim().split('₹')[0].trim() : '';
        return r;
    }''')

    if not result.get("name"):
        result["name"] = dom.get("name", "")
    if not result.get("sp"):
        result["sp"] = dom.get("sp")
    if not result.get("mrp"):
        result["mrp"] = dom.get("mrp")

    info = dom.get("info", {})
    if not result.get("brand"):
        result["brand"] = info.get("brand", "")
    if not result.get("article_id"):
        result["article_id"] = info.get("article id", "")
    if not result.get("net_quantity"):
        result["net_quantity"] = info.get("net quantity", "")
    if not result.get("fssai"):
        result["fssai"] = info.get("fssai number", "")

    # Unit
    if not result.get("unit"):
        result["unit"] = dom.get("unit", "")
    if not result.get("unit") and result.get("name"):
        m = re.search(r"(\d+\.?\d*)\s*(g|gm|gms|kg|kgs|ml|mls|l|ltr|ltrs|pc|pcs)\b", result["name"].lower())
        if m:
            result["unit"] = f"{m.group(1)} {m.group(2)}"

    if "in_stock" not in result:
        result["in_stock"] = not dom.get("out_of_stock", False)
    if result.get("sp") and not result.get("mrp"):
        result["mrp"] = result["sp"]

    result["status"] = "ok" if result.get("sp") else "no_price"
    return result


async def discover_category_products(page, category_url):
    """Visit a category page, scroll to load all products, extract slugs from DOM + dataLayer."""
    await page.goto(f"https://www.jiomart.com{category_url}", wait_until="networkidle", timeout=25000)
    await asyncio.sleep(2)

    # Scroll to load all products
    prev = 0
    for _ in range(20):
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await asyncio.sleep(1.5)
        count = await page.evaluate("document.querySelectorAll('[class*=productCard]').length")
        if count == prev:
            break
        prev = count

    # Extract from dataLayer (product_id, name, brand, SP, slug)
    dl_products = await page.evaluate('''() => {
        const products = [];
        const seen = new Set();
        if (window.dataLayer) {
            for (const entry of window.dataLayer) {
                const items = entry?.ecommerce?.items || [];
                for (const item of items) {
                    const slug = item.product_url || '';
                    if (slug && !seen.has(slug)) {
                        seen.add(slug);
                        products.push({
                            slug,
                            product_id: item.item_id || '',
                            name: item.item_name || '',
                            brand: item.item_brand || '',
                            sp: item.price || null,
                        });
                    }
                }
            }
        }
        return products;
    }''')

    # Extract SP + MRP from DOM for ALL products (dataLayer only has SP)
    dom_products = await page.evaluate(r'''() => {
        const products = [];
        document.querySelectorAll('.productCard__productDescription').forEach(card => {
            const nameEl = card.querySelector('.productCard__productTitle, h3');
            const spEl = card.querySelector('[class*=currentPrice]');
            const mrpEl = card.querySelector('[class*=originalPrice]');
            const name = nameEl ? nameEl.textContent.trim() : '';
            const sp = spEl ? parseFloat(spEl.textContent.replace(/[₹,\s]/g, '')) : null;
            const mrp = mrpEl ? parseFloat(mrpEl.textContent.replace(/[₹,\s]/g, '')) : null;
            if (name && sp) products.push({name, sp, mrp: mrp || sp});
        });
        return products;
    }''')

    # Merge: dataLayer has product_id/slug, DOM has MRP. Match by name+SP.
    for dl_p in dl_products:
        for dom_p in dom_products:
            if dl_p["name"] == dom_p["name"] and dl_p.get("sp") == dom_p.get("sp"):
                dl_p["mrp"] = dom_p.get("mrp")
                break
        if "mrp" not in dl_p:
            dl_p["mrp"] = dl_p.get("sp")  # no discount = MRP == SP

    return dl_products, dom_products


async def get_grocery_categories(page):
    """Visit /categories and extract all grocery sub-category URLs."""
    await page.goto("https://www.jiomart.com/categories", wait_until="networkidle", timeout=25000)
    await asyncio.sleep(3)
    await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    await asyncio.sleep(2)
    await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    await asyncio.sleep(2)

    cats = await page.evaluate('''() => {
        const cats = [];
        const seen = new Set();
        document.querySelectorAll('a[href]').forEach(a => {
            const href = a.getAttribute('href') || '';
            const text = (a.innerText || '').trim();
            if (href.includes('/products?') && href.includes('groceries') && text && !seen.has(text)) {
                seen.add(text);
                cats.push({name: text, url: href});
            }
        });
        return cats;
    }''')
    return cats


async def main():
    args = sys.argv[1:]
    pincode = "834002"
    mode = "single"
    slug = ""
    category = ""

    for i, a in enumerate(args):
        if a == "--pincode" and i + 1 < len(args):
            pincode = args[i + 1]
        elif a == "--all":
            mode = "all"
        elif a == "--category" and i + 1 < len(args):
            mode = "category"
            category = args[i + 1]
        elif not a.startswith("--"):
            slug = a
            if "jiomart.com/product/" in slug:
                slug = slug.split("/product/")[-1].split("?")[0]

    pw = await async_playwright().start()
    browser, context = await init_jiomart_context(pw, pincode)
    page = await context.new_page()
    master = load_master()
    initial_count = len(master)

    if mode == "single" and slug:
        # Single PDP test
        result = await scrape_one_pdp(page, slug, pincode)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        # Save to master
        pid = result.get("product_id", slug)
        master[pid] = {
            "product_id": pid,
            "slug": result.get("slug"),
            "name": result.get("name"),
            "brand": result.get("brand"),
            "unit": result.get("unit"),
            "net_quantity": result.get("net_quantity"),
            "article_id": result.get("article_id"),
            "fssai": result.get("fssai"),
            "url": result.get("url"),
            "last_sp": result.get("sp"),
            "last_mrp": result.get("mrp"),
            "in_stock": result.get("in_stock"),
            "last_scraped": result.get("scraped_at"),
        }

    elif mode in ("all", "category"):
        today = datetime.now()
        is_discovery_day = today.day == 1  # 1st of every month
        force_discovery = "--force-discovery" in args

        # Check if master already has products
        has_master = len(master) > 100

        if has_master and not is_discovery_day and not force_discovery:
            # ── DAILY MODE: Sirf prices update from master (no category scrape) ──
            print(f"[jm] Daily mode — master has {len(master)} products, skipping category discovery", flush=True)
            print(f"[jm] (Full discovery runs on 1st of every month, or use --force-discovery)", flush=True)
            # Prices already in master from last discovery — cascade/stage3 will use them
            now = datetime.now().isoformat()
            for pid in master:
                master[pid]["last_scraped"] = now
        else:
            # ── DISCOVERY MODE: Full category scrape (1st of month or first run) ──
            if is_discovery_day:
                print(f"[jm] Monthly discovery — 1st of month", flush=True)
            elif force_discovery:
                print(f"[jm] Forced discovery", flush=True)
            else:
                print(f"[jm] First run — no master file, doing full discovery", flush=True)

            if mode == "all":
                print("[jm] Fetching all grocery categories...", flush=True)
                cats = await get_grocery_categories(page)
                skip_l1 = {"kitchenware-l1", "tableware-l1", "school-office-stationery", "disposables",
                            "gifts-hampers", "fashion-jewellery-l1", "crafts-of-india", "books",
                            "kitchen-dining-l1"}
                cats = [c for c in cats if not any(s in c["url"] for s in skip_l1)]
                print(f"[jm] {len(cats)} FMCG grocery categories", flush=True)
            else:
                cats = [{"name": category, "url": f"/products?department=groceries&l2_category={category}"}]

            all_slugs = {}
            for ci, cat in enumerate(cats, 1):
                print(f"[jm] [{ci}/{len(cats)}] {cat['name']}...", flush=True, end=" ")
                try:
                    dl_prods, dom_prods = await discover_category_products(page, cat["url"])
                    for p in dl_prods:
                        if p["slug"] and p["slug"] not in all_slugs:
                            all_slugs[p["slug"]] = p
                    print(f"{len(dl_prods)} products (dataLayer)", flush=True)
                except Exception as e:
                    print(f"ERROR: {str(e)[:80]}", flush=True)

            print(f"\n[jm] Total unique products discovered: {len(all_slugs)}", flush=True)

            now = datetime.now().isoformat()
            new_count = 0
            updated = 0
            for slug_key, p in all_slugs.items():
                pid = str(p.get("product_id", slug_key.split("-")[-1]))
                url = f"https://www.jiomart.com/product/{slug_key}"

                if pid in master:
                    master[pid]["last_sp"] = p.get("sp")
                    master[pid]["last_mrp"] = p.get("mrp") or p.get("sp")
                    master[pid]["last_scraped"] = now
                    updated += 1
                else:
                    unit = ""
                    name = p.get("name", "")
                    m = re.search(r"(\d+\.?\d*)\s*(g|gm|gms|kg|kgs|ml|mls|l|ltr|ltrs|pc|pcs)\b", name.lower())
                    if m:
                        unit = f"{m.group(1)} {m.group(2)}"

                    master[pid] = {
                        "product_id": pid,
                        "slug": slug_key,
                        "name": name,
                        "brand": p.get("brand", ""),
                        "unit": unit,
                        "url": url,
                        "last_sp": p.get("sp"),
                        "last_mrp": p.get("mrp") or p.get("sp"),
                        "in_stock": True,
                        "last_scraped": now,
                    }
                    new_count += 1

            print(f"[jm] New: {new_count}, Updated: {updated}", flush=True)

    save_master(master)
    print(f"[jm] Master saved: {len(master)} products (+{len(master) - initial_count} new) → {MASTER_PATH.name}", flush=True)

    await browser.close()
    await pw.stop()


if __name__ == "__main__":
    asyncio.run(main())
