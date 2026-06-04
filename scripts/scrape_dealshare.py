"""
DealShare Scraper — Pure API, no browser needed.

Fetches product data from DealShare internal API for given pincode.
Saves products to JSON + matches with AM products.

Usage:
    python3 scripts/scrape_dealshare.py 700001           # Kolkata
    python3 scripts/scrape_dealshare.py 700001 --match    # with AM matching
"""
import json
import random
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path
from urllib.request import Request, urlopen, ProxyHandler, build_opener
from urllib.error import HTTPError, URLError

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA = PROJECT_ROOT / "data"

API_URL = "https://services.dealshare.in/feedservice/api/v1/get-page"

# Free proxy list — rotate to avoid IP block
PROXIES = []  # Add proxies here: ["http://ip:port", ...]
_proxy_index = 0

# Category IDs (discovered from API)
CATEGORIES = {
    "719": "Grocery & Packaged Food",
    "720": "Personal Care",
    "721": "Cleaning & Home Care",
    "722": "Home & Kitchen",
    "723": "Electronics",
    "724": "Fashion",
    "725": "Stationery & Toys",
    "726": "Dairy, Frozen & Bakery",
    "727": "Fruits & Vegetables",
}

# All categories with products (discovered via API scan)
ALL_CATEGORIES = {
    # L1 parent categories (contain sub-category products)
    "719": "Grocery & Packaged Food",
    # Sub-categories not covered by 719
    "829": "Rice & Rice Products",
    "845": "Salt",
    "886": "Insecticides",
    "894": "Detergent Powders",
    "898": "Liquid Detergents",
    "904": "Tissues & Disposables",
    "925": "Cookies",
    "934": "Salted Biscuits",
    "855": "Cleaners",
    "856": "Floor Cleaners",
    "877": "Other Pooja Needs",
    "883": "Toilet Freshners",
    "895": "Fabric Softeners",
}
FMCG_CATEGORIES = list(ALL_CATEGORIES.keys())

USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Gecko/20100101 Firefox/128.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Gecko/20100101 Firefox/127.0",
]


def _get_proxy():
    """Get next proxy from rotation list."""
    global _proxy_index
    if not PROXIES:
        return None
    proxy = PROXIES[_proxy_index % len(PROXIES)]
    _proxy_index += 1
    return proxy


def api_request(pincode, payload, retries=2):
    """Make POST request to DealShare API with proxy rotation + retry."""
    for attempt in range(retries + 1):
        device_id = str(uuid.uuid4())  # Fresh device ID each request
        headers = {
            "appVersion": "1.1.9",
            "businessModel": "B2C",
            "channel": "APP",
            "deviceId": device_id,
            "deviceType": "desktop",
            "palId": "670",
            "pincode": str(pincode),
            "platform": "web",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": random.choice(USER_AGENTS),
        }

        data = json.dumps(payload).encode()
        req = Request(API_URL, data=data, headers=headers, method="POST")

        try:
            proxy = _get_proxy()
            if proxy:
                opener = build_opener(ProxyHandler({"https": proxy, "http": proxy}))
                with opener.open(req, timeout=15) as resp:
                    return json.loads(resp.read())
            else:
                with urlopen(req, timeout=15) as resp:
                    return json.loads(resp.read())
        except HTTPError as e:
            if e.code == 403 and attempt < retries:
                wait = random.uniform(3, 8) * (attempt + 1)
                print(f"    403 blocked, retry in {wait:.0f}s...", flush=True)
                time.sleep(wait)
                continue
            print(f"    API error: {e.code}", flush=True)
            return None
        except URLError as e:
            if attempt < retries:
                time.sleep(2)
                continue
            print(f"    URL error: {e.reason}", flush=True)
            return None
        except Exception as e:
            if attempt < retries:
                time.sleep(2)
                continue
            print(f"    Request error: {e}", flush=True)
            return None
    return None


def discover_slots(pincode):
    """Discover slot IDs for each category."""
    print(f"  Discovering category slots...", flush=True)
    slots = {}

    for cat_id in FMCG_CATEGORIES:
        payload = {
            "pageQueryType": "PAGE",
            "pageInfo": {"url": f"/category/l1/{cat_id}", "foldNumber": 1, "version": "NEW"},
            "slotInfo": {"componentEntityCursor": 1},
            "lang": "en", "slotPosition": 0,
        }
        resp = api_request(pincode, payload)
        if resp:
            for section in resp.get("listSection", []):
                sid = section.get("slotId")
                if sid:
                    slots[cat_id] = sid
                    break
        time.sleep(0.2)

    print(f"  Found {len(slots)} category slots", flush=True)
    return slots


def fetch_category_products(pincode, cat_id, slot_id):
    """Fetch all products from a category using pagination."""
    products = []
    cursor = 1

    while True:
        # Step 1: PAGE query to get dealDetailsList
        payload = {
            "pageQueryType": "PAGE",
            "pageInfo": {"url": f"/category/l1/{cat_id}", "foldNumber": 1, "version": "NEW"},
            "slotInfo": {"componentEntityCursor": cursor},
            "lang": "en", "slotPosition": 0,
        }

        resp = api_request(pincode, payload)
        if not resp:
            break

        # Extract from listSection → contentData → dealDetailsList
        page_products = []
        has_next = False

        for section in resp.get("listSection", []):
            content = section.get("contentData", {}) or {}
            deals = content.get("dealDetailsList", [])
            has_next = content.get("hasNext", False)
            next_cursor = content.get("componentEntityCursor")

            for deal in deals:
                if deal.get("title") and deal.get("price") is not None:
                    page_products.append({
                        "product_id": str(deal.get("productId", "")),
                        "offer_id": str(deal.get("offerId", "")),
                        "title": deal.get("title", ""),
                        "brand": deal.get("brand", ""),
                        "price": deal.get("price"),       # SP
                        "mrp": deal.get("mrp"),            # MRP
                        "grammage": deal.get("grammage", ""),
                        "off_percent": deal.get("offPercentage"),
                        "discount_text": deal.get("discountText", ""),
                        "category_l1": deal.get("categoryNameL1", ""),
                        "category_l2": deal.get("categoryNameL2", ""),
                        "category_l3": deal.get("categoryNameL3", ""),
                        "image": deal.get("image", ""),
                        "food_type": deal.get("foodType"),
                        "max_qty": deal.get("maxQuantityAllowed"),
                        "per_unit_price": deal.get("perUnitPriceText", ""),
                    })

        if not page_products:
            break

        products.extend(page_products)

        if not has_next:
            break

        cursor = next_cursor if next_cursor else cursor + 5
        time.sleep(0.3)

    return products


def scrape_all(pincode):
    """Scrape all FMCG categories for a pincode."""
    print(f"\n{'=' * 60}")
    print(f"  DEALSHARE SCRAPER — pincode {pincode}")
    print(f"{'=' * 60}\n")

    # Discover slot IDs
    slots = discover_slots(pincode)

    all_products = []
    seen_ids = set()

    for cat_id in FMCG_CATEGORIES:
        cat_name = CATEGORIES.get(cat_id, cat_id)
        slot_id = slots.get(cat_id)
        print(f"  [{cat_id}] {cat_name}...", flush=True, end=" ")

        products = fetch_category_products(pincode, cat_id, slot_id)

        # Dedup by product_id
        new = 0
        for p in products:
            pid = p["product_id"]
            if pid and pid not in seen_ids:
                seen_ids.add(pid)
                all_products.append(p)
                new += 1

        print(f"{new} products", flush=True)
        time.sleep(random.uniform(1, 2))  # Delay between categories

    print(f"\n  Total: {len(all_products)} unique products")

    # Save to JSON
    ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    out_path = DATA / f"dealshare_{pincode}_{ts}.json"
    with open(out_path, "w") as f:
        json.dump({
            "pincode": pincode,
            "scraped_at": datetime.now().isoformat(),
            "total": len(all_products),
            "products": all_products,
        }, f, indent=2, ensure_ascii=False, default=str)
    print(f"  Saved: {out_path.name}")

    return all_products


def match_with_am(products, pincode):
    """Match DealShare products with AM products using UnifiedMatchingEngine."""
    sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
    from unified_matcher import UnifiedMatchingEngine
    from utils import parse_num

    # Load AM master
    am_path = DATA / "am_product_master.json"
    if not am_path.exists():
        print("  AM master not found — skipping match")
        return

    am_map = json.load(open(am_path))
    ean_map = json.load(open(DATA / "ean_map.json")) if (DATA / "ean_map.json").exists() else {}

    # Convert DealShare products to engine pool format
    pool = []
    for p in products:
        pool.append({
            "product_id": p["product_id"],
            "product_name": p["title"],
            "brand": p["brand"],
            "price": p["price"],   # SP
            "mrp": p["mrp"],
            "unit": p["grammage"],
            "in_stock": True,
            "product_url": f"https://www.dealshare.in/product/{p['product_id']}",
        })

    engine = UnifiedMatchingEngine(ean_map)
    engine.set_pool(pool)

    # Load MRP
    pricing_path = DATA / "am_pricing_wrhs_1.json"
    mrp_map = json.load(open(pricing_path)) if pricing_path.exists() else {}

    # Match all AM products
    from collections import Counter
    status_counts = Counter()
    matched = []
    valid_cats = {"STPLS", "FMCG", "FMCGF", "FMCGNF", "GM"}

    for ic, am in am_map.items():
        if am.get("master_category") not in valid_cats:
            continue
        mrp_rec = mrp_map.get(ic)
        am_mrp = parse_num(mrp_rec.get("mrp")) if mrp_rec else parse_num(am.get("mrp"))
        result = engine.match(am, am_mrp)
        status_counts[result.status] += 1

        if result.product:
            matched.append({
                "item_code": ic,
                "am_name": am.get("display_name"),
                "ds_name": result.product.get("product_name"),
                "ds_sp": result.product.get("price"),
                "ds_mrp": result.product.get("mrp"),
                "match_status": result.status,
                "match_score": round(result.score, 3),
            })

    print(f"\n  Match results:")
    for s, c in status_counts.most_common():
        print(f"    {s:25s} {c}")
    print(f"  Matched: {len(matched)}")

    # Save match results
    ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    match_path = DATA / f"dealshare_match_{pincode}_{ts}.json"
    with open(match_path, "w") as f:
        json.dump({
            "pincode": pincode, "matched_at": datetime.now().isoformat(),
            "total_matched": len(matched),
            "status_counts": dict(status_counts),
            "matches": matched,
        }, f, indent=2, default=str)
    print(f"  Match saved: {match_path.name}")


if __name__ == "__main__":
    pincode = sys.argv[1] if len(sys.argv) > 1 else "700001"
    do_match = "--match" in sys.argv

    products = scrape_all(pincode)

    if do_match and products:
        match_with_am(products, pincode)
