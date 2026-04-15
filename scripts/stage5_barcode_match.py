import os
"""
Stage 5: Barcode/EAN matching.

For each unmatched Anakin SKU (after Stage 1-4):
  1. Get Apna's barcode from smpcm_product (bar_code, bar_codes fields)
  2. Check if any SAM BFS pool product has the same barcode
  3. Exact barcode match = 100% guaranteed same product

Fallback — Search-by-barcode:
  If SAM pool has no barcode data (common since BFS scrape doesn't capture
  barcodes yet), use the Anakin barcode to search on the platform directly.
  E.g., search "8901030855054" on Blinkit — the platform often returns the
  exact product matching that EAN.

Only works for products with REAL EAN barcodes (13-digit, 890xxxx format).
Internal item_codes (5-6 digit) are skipped as they won't match platform IDs.

Usage:
    python3 scripts/stage5_barcode_match.py 834002 [blinkit|jiomart]
"""
import asyncio
import json
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

METABASE_API = "https://mirror.apnamart.in/api/dataset"
METABASE_KEY = os.environ.get("METABASE_API_KEY", "")

# Platform search URL templates
PLATFORM_SEARCH_URL = {
    "blinkit": "https://blinkit.com/s/?q={barcode}",
    "jiomart": "https://www.jiomart.com/search/{barcode}",
}

# Blinkit search API endpoint (intercepted from network)
BLINKIT_SEARCH_API = "https://blinkit.com/v6/search/products"

# Pincode prefix -> approximate (lat, lng) — subset from base_scraper.py
_PINCODE_COORDS = {
    "11": (28.6139, 77.2090), "12": (28.4595, 77.0266), "13": (30.7333, 76.7794),
    "14": (30.7333, 76.7794), "20": (26.8467, 80.9462), "22": (26.4499, 80.3319),
    "30": (26.9124, 75.7873), "38": (23.0225, 72.5714), "40": (19.0760, 72.8777),
    "41": (18.5204, 73.8567), "49": (21.2514, 81.6296), "50": (17.3850, 78.4867),
    "56": (12.9716, 77.5946), "60": (13.0827, 80.2707), "70": (22.5726, 88.3639),
    "71": (22.5726, 88.3639), "80": (25.6093, 85.1376), "82": (23.3441, 85.3096),
    "83": (23.3441, 85.3096), "84": (26.1542, 86.0614),
}


def _get_coords(pincode: str) -> tuple[float, float]:
    """Get approximate lat/lng for a pincode (by 2-digit prefix)."""
    prefix = pincode[:2] if len(pincode) >= 2 else ""
    return _PINCODE_COORDS.get(prefix, (28.6139, 77.2090))


def is_real_ean(bc: str) -> bool:
    """Check if barcode looks like a real EAN/UPC (8+ digits, not just item_code)."""
    if not bc:
        return False
    bc = bc.strip()
    return len(bc) >= 8 and bc.isdigit()


def query_metabase(mbql):
    req = urllib.request.Request(
        METABASE_API, method="POST",
        headers={"x-api-key": METABASE_KEY, "Content-Type": "application/json"},
        data=json.dumps(mbql).encode(),
    )
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())


def clean_str(v) -> str:
    if v is None:
        return ""
    s = str(v).strip()
    if s.lower() in ("", "na", "nan", "null", "none"):
        return ""
    return s


def latest_file(subdir: str, pattern: str) -> Path | None:
    cands = sorted((PROJECT_ROOT / "data" / subdir).glob(pattern))
    return cands[-1] if cands else None


async def search_barcode_on_blinkit(barcode: str, pincode: str, lat: float, lng: float) -> list[dict]:
    """Search a barcode on Blinkit using Playwright and return matching products.

    Opens a headless browser, sets location, searches the barcode,
    and returns any product results found.
    """
    from playwright.async_api import async_playwright

    products = []
    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(
                headless=True,
                args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
            )
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                           "AppleWebKit/537.36 (KHTML, like Gecko) "
                           "Chrome/125.0.0.0 Safari/537.36",
                viewport={"width": 1366, "height": 768},
                locale="en-IN",
                timezone_id="Asia/Kolkata",
            )
            await context.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                window.chrome = {runtime: {}};
            """)

            page = await context.new_page()

            # Collect API responses
            captured = []

            async def on_response(response):
                try:
                    ct = response.headers.get("content-type", "")
                    if "json" in ct and response.status == 200:
                        body = await response.text()
                        if len(body) > 50:
                            data = json.loads(body)
                            captured.append(data)
                except Exception:
                    pass

            page.on("response", on_response)

            # Load homepage, set location
            await page.goto("https://blinkit.com", wait_until="domcontentloaded", timeout=15000)
            await asyncio.sleep(1)

            location_data = json.dumps({
                "coords": {
                    "isDefault": False, "lat": lat, "lon": lng,
                    "locality": "Selected Location", "id": None,
                    "isTopCity": False, "cityName": "Selected",
                    "landmark": None, "addressId": None,
                }
            })
            await page.evaluate(f"() => localStorage.setItem('location', {json.dumps(location_data)})")
            await context.add_cookies([
                {"name": "__pincode", "value": pincode, "domain": ".blinkit.com", "path": "/"},
                {"name": "gr_1_lat", "value": str(lat), "domain": ".blinkit.com", "path": "/"},
                {"name": "gr_1_lon", "value": str(lng), "domain": ".blinkit.com", "path": "/"},
            ])

            # Search for barcode
            search_url = f"https://blinkit.com/s/?q={barcode}"
            await page.goto(search_url, wait_until="domcontentloaded", timeout=15000)
            await asyncio.sleep(2)

            # Scroll to trigger lazy loading
            for _ in range(3):
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await asyncio.sleep(0.5)

            # Parse captured API responses for products
            for data in captured:
                products.extend(_extract_products_from_json(data))

            await context.close()
            await browser.close()

    except Exception as e:
        print(f"[barcode] Playwright search error for {barcode}: {e}", file=sys.stderr)

    return products


def _extract_products_from_json(data, depth=0) -> list[dict]:
    """Recursively extract product-like dicts from JSON."""
    if depth > 8:
        return []
    products = []
    if isinstance(data, dict):
        has_name = any(k in data for k in ["name", "product_name", "title", "display_name"])
        has_price = any(k in data for k in ["price", "mrp", "selling_price", "offer_price"])
        if has_name and has_price:
            products.append(data)
        for val in data.values():
            products.extend(_extract_products_from_json(val, depth + 1))
    elif isinstance(data, list):
        for item in data:
            products.extend(_extract_products_from_json(item, depth + 1))
    return products


async def batch_barcode_search(barcodes_to_search: dict, pincode: str, lat: float, lng: float,
                               platform: str) -> list[dict]:
    """Search multiple barcodes on the platform and return matches.

    Uses a single browser session for efficiency (one browser, sequential searches).
    barcodes_to_search: {ean: {item_code, name}}

    Returns list of match dicts.
    """
    if platform != "blinkit":
        print(f"[barcode] Search-by-barcode not yet implemented for {platform}", flush=True)
        return []

    if not barcodes_to_search:
        return []

    from playwright.async_api import async_playwright

    matches = []
    total = len(barcodes_to_search)
    print(f"[barcode] Searching {total} barcodes on {platform}...", flush=True)

    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(
                headless=True,
                args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
            )
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                           "AppleWebKit/537.36 (KHTML, like Gecko) "
                           "Chrome/125.0.0.0 Safari/537.36",
                viewport={"width": 1366, "height": 768},
                locale="en-IN",
                timezone_id="Asia/Kolkata",
            )
            await context.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                window.chrome = {runtime: {}};
            """)

            page = await context.new_page()

            # Collect API responses (reset per search)
            captured = []
            processed_urls = set()

            async def on_response(response):
                try:
                    url = response.url
                    ct = response.headers.get("content-type", "")
                    if "json" in ct and response.status == 200 and url not in processed_urls:
                        body = await response.text()
                        if len(body) > 50 and any(kw in body.lower() for kw in
                                                    ["product", "price", "name"]):
                            data = json.loads(body)
                            captured.append({"url": url, "data": data})
                            processed_urls.add(url)
                except Exception:
                    pass

            page.on("response", on_response)

            # Load homepage, set location
            await page.goto("https://blinkit.com", wait_until="domcontentloaded", timeout=15000)
            await asyncio.sleep(1)

            location_data = json.dumps({
                "coords": {
                    "isDefault": False, "lat": lat, "lon": lng,
                    "locality": "Selected Location", "id": None,
                    "isTopCity": False, "cityName": "Selected",
                    "landmark": None, "addressId": None,
                }
            })
            await page.evaluate(f"() => localStorage.setItem('location', {json.dumps(location_data)})")
            await context.add_cookies([
                {"name": "__pincode", "value": pincode, "domain": ".blinkit.com", "path": "/"},
                {"name": "gr_1_lat", "value": str(lat), "domain": ".blinkit.com", "path": "/"},
                {"name": "gr_1_lon", "value": str(lng), "domain": ".blinkit.com", "path": "/"},
            ])

            # Reload to apply location
            await page.goto("https://blinkit.com", wait_until="domcontentloaded", timeout=15000)
            await asyncio.sleep(1)

            searched = 0
            consecutive_empty = 0
            max_consecutive_empty = 15  # stop if platform isn't returning results

            for ean, apna_info in barcodes_to_search.items():
                if consecutive_empty >= max_consecutive_empty:
                    print(f"[barcode] Stopping search: {max_consecutive_empty} consecutive "
                          f"empty searches (platform may not support barcode search)")
                    break

                # Clear captured for this search
                captured.clear()
                processed_urls.clear()

                try:
                    search_url = f"https://blinkit.com/s/?q={ean}"
                    await page.goto(search_url, wait_until="domcontentloaded", timeout=12000)
                    await asyncio.sleep(1.5)

                    # Scroll once to trigger lazy loading
                    await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    await asyncio.sleep(0.8)

                    # Extract products from API responses
                    search_products = []
                    for resp in captured:
                        search_products.extend(_extract_products_from_json(resp["data"]))

                    if search_products:
                        consecutive_empty = 0
                        # Take the first product as the match (barcode search is very specific)
                        p = search_products[0]
                        name = ""
                        for key in ["name", "product_name", "title", "display_name"]:
                            if p.get(key):
                                name = str(p[key]).strip()
                                break

                        price = 0.0
                        for key in ["price", "selling_price", "offer_price", "sp"]:
                            val = p.get(key)
                            if val:
                                try:
                                    # Handle nested price dict
                                    if isinstance(val, dict):
                                        for sk in ["offer_price", "selling_price", "sp", "price"]:
                                            sv = val.get(sk)
                                            if sv:
                                                price = float(str(sv).replace("₹", "").replace(",", ""))
                                                if price > 0:
                                                    break
                                    else:
                                        price = float(str(val).replace("₹", "").replace(",", ""))
                                    if price > 0:
                                        break
                                except (ValueError, TypeError):
                                    continue

                        mrp = None
                        for key in ["mrp", "marked_price", "original_price"]:
                            val = p.get(key)
                            if not val and isinstance(p.get("price"), dict):
                                val = p["price"].get(key)
                            if val:
                                try:
                                    mrp = float(str(val).replace("₹", "").replace(",", ""))
                                    if mrp > 0:
                                        break
                                except (ValueError, TypeError):
                                    continue

                        product_id = None
                        for key in ["id", "product_id", "prid", "pid"]:
                            if p.get(key) and not isinstance(p[key], (dict, list)):
                                product_id = str(p[key]).strip()
                                if product_id:
                                    break

                        brand = ""
                        for key in ["brand", "brand_name"]:
                            if p.get(key) and isinstance(p[key], str):
                                brand = p[key].strip()
                                break

                        image = None
                        for key in ["image_url", "image", "imageUrl", "thumbnail"]:
                            val = p.get(key)
                            if val and isinstance(val, str) and val.startswith("http"):
                                image = val
                                break

                        if name and price > 0:
                            matches.append({
                                "item_code": apna_info["item_code"],
                                "anakin_name": apna_info["name"],
                                "barcode": ean,
                                "sam_product_name": name,
                                "sam_brand": brand,
                                "sam_price": price,
                                "sam_mrp": mrp,
                                "sam_product_id": product_id,
                                "sam_image": image,
                                "match_method": "barcode_search",
                                "search_results_count": len(search_products),
                            })
                    else:
                        consecutive_empty += 1

                except Exception as e:
                    print(f"[barcode] Search error for EAN {ean}: {e}", file=sys.stderr)
                    consecutive_empty += 1

                searched += 1
                if searched % 10 == 0:
                    print(f"  [{searched}/{total}] {len(matches)} matches so far", flush=True)

            await context.close()
            await browser.close()

    except Exception as e:
        print(f"[barcode] Browser session error: {e}", file=sys.stderr)

    return matches


def main(pincode: str, platform: str = "blinkit"):
    PLATFORM_FIELDS = {
        "blinkit": {"product_id": "Blinkit_Product_Id", "selling_price": "Blinkit_Selling_Price"},
        "jiomart": {"product_id": "Jiomart_Product_Id", "selling_price": "Jiomart_Selling_Price"},
    }
    pf = PLATFORM_FIELDS.get(platform, PLATFORM_FIELDS["blinkit"])

    ana_path = latest_file("anakin", f"{platform}_{pincode}_*.json")
    sam_path = None
    for p in sorted((PROJECT_ROOT / "data" / "sam").glob(f"{platform}_{pincode}_*.json"), reverse=True):
        if "pdp" not in p.name:
            sam_path = p
            break

    if not ana_path or not sam_path:
        print(f"[barcode] ERROR: missing files", file=sys.stderr)
        sys.exit(1)

    print(f"[barcode] Platform: {platform}")
    print(f"[barcode] Anakin: {ana_path.name}")
    print(f"[barcode] SAM pool: {sam_path.name}")

    ana = json.load(open(ana_path))
    sam = json.load(open(sam_path))

    # Find unmatched non-loose usable SKUs (same logic as Stage 4)
    usable_codes = {r.get("Item_Code") for r in ana["records"]
                    if r.get(pf["selling_price"]) not in (None, "", "NA", "nan")
                    and "loose" not in (r.get("Item_Name") or "").lower()}

    matched_codes: set[str] = set()
    for pattern_str in [f"{platform}_pdp_{pincode}_*_compare.json",
                        f"{platform}_cascade_{pincode}_*.json",
                        f"{platform}_stage3_{pincode}_*.json",
                        f"{platform}_image_match_{pincode}_*.json"]:
        for f in sorted((PROJECT_ROOT / "data" / "comparisons").glob(pattern_str)):
            d = json.load(open(f))
            for m in d.get("matches", []):
                if m.get("match_status") == "ok":
                    matched_codes.add(m.get("item_code"))
            for m in d.get("new_mappings", []):
                matched_codes.add(m.get("item_code"))

    unmatched_codes = usable_codes - matched_codes
    print(f"[barcode] Unmatched after Stage 1-4: {len(unmatched_codes)}")

    # Step 1: Fetch barcodes from Apna's smpcm_product for unmatched item_codes
    print("[barcode] Fetching barcodes from smpcm_product...", flush=True)
    all_records = []
    page = 1
    while True:
        try:
            r = query_metabase({
                "database": 5, "type": "query",
                "query": {
                    "source-table": 578,
                    "filter": ["and",
                               ["=", ["field", 7161, None], True],
                               ["not-null", ["field", 7127, None]],
                               ["!=", ["field", 7127, None], ""]],
                    "fields": [
                        ["field", 7191, None],  # item_code
                        ["field", 7118, None],  # display_name
                        ["field", 7127, None],  # bar_code
                        ["field", 12890, None], # bar_codes (JSON array)
                    ],
                    "page": {"page": page, "items": 2000},
                    "limit": 2000,
                }
            })
            rows = r["data"]["rows"]
            if not rows:
                break
            all_records.extend(rows)
            if len(rows) < 2000:
                break
            page += 1
            if page > 30:
                break
        except Exception as e:
            print(f"[barcode] Metabase query error (page {page}): {e}", file=sys.stderr)
            break

    print(f"[barcode] Fetched {len(all_records)} products with barcodes from Metabase")

    # Build barcode -> item_code lookup (only real EANs for unmatched)
    apna_barcode_map: dict[str, dict] = {}  # ean -> {item_code, name}
    for row in all_records:
        ic = str(row[0])
        if ic not in unmatched_codes:
            continue
        name = row[1]
        bc = str(row[2]) if row[2] else ""
        bcs_raw = row[3]  # JSON array like ["12345", "8901234567890"]

        # Collect all EANs
        eans = set()
        if is_real_ean(bc):
            eans.add(bc)
        if bcs_raw:
            if isinstance(bcs_raw, list):
                for b in bcs_raw:
                    if is_real_ean(str(b)):
                        eans.add(str(b))
            elif isinstance(bcs_raw, str):
                try:
                    arr = json.loads(bcs_raw)
                    for b in arr:
                        if is_real_ean(str(b)):
                            eans.add(str(b))
                except (json.JSONDecodeError, TypeError):
                    pass

        for ean in eans:
            apna_barcode_map[ean] = {"item_code": ic, "name": name}

    unique_items_with_ean = len(set(d["item_code"] for d in apna_barcode_map.values()))
    print(f"[barcode] Unmatched with real EAN: {unique_items_with_ean}")
    print(f"[barcode] Total unique EANs: {len(apna_barcode_map)}")

    # Step 2: Check SAM BFS pool for barcode data
    sam_barcodes: dict[str, dict] = {}  # ean -> product
    for p in sam["products"]:
        for key in ("barcode", "bar_code", "ean", "upc", "gtin"):
            v = p.get(key)
            if v and is_real_ean(str(v)):
                sam_barcodes[str(v)] = p

    print(f"[barcode] SAM pool products with barcodes: {len(sam_barcodes)}")

    # Step 3: Match by barcode (direct lookup in SAM pool)
    new_matches = []
    matched_by_pool = 0
    if sam_barcodes and apna_barcode_map:
        for ean, apna_info in apna_barcode_map.items():
            if ean in sam_barcodes:
                sam_p = sam_barcodes[ean]
                new_matches.append({
                    "item_code": apna_info["item_code"],
                    "anakin_name": apna_info["name"],
                    "barcode": ean,
                    "sam_product_name": sam_p.get("product_name"),
                    "sam_brand": sam_p.get("brand"),
                    "sam_price": sam_p.get("price"),
                    "sam_mrp": sam_p.get("mrp"),
                    "sam_product_id": sam_p.get("product_id"),
                    "match_method": "barcode_ean",
                })
        matched_by_pool = len(new_matches)
        print(f"[barcode] Matched via SAM pool barcodes: {matched_by_pool}")

    # Step 4: Fallback -- search by barcode on platform
    # Only do this if SAM pool had few/no barcode matches and we have barcodes to search
    already_matched_items = {m["item_code"] for m in new_matches}
    remaining_barcodes = {
        ean: info for ean, info in apna_barcode_map.items()
        if info["item_code"] not in already_matched_items
    }
    # De-duplicate: only search one barcode per item_code
    seen_items = set()
    deduped_barcodes: dict[str, dict] = {}
    for ean, info in remaining_barcodes.items():
        if info["item_code"] not in seen_items:
            seen_items.add(info["item_code"])
            deduped_barcodes[ean] = info

    if deduped_barcodes and platform in PLATFORM_SEARCH_URL:
        print(f"\n[barcode] Fallback: searching {len(deduped_barcodes)} barcodes on {platform}...")

        # Get pincode coords for location setting
        lat, lng = _get_coords(pincode)

        search_matches = asyncio.run(
            batch_barcode_search(deduped_barcodes, pincode, lat, lng, platform)
        )
        new_matches.extend(search_matches)
        print(f"[barcode] Search-by-barcode found: {len(search_matches)} matches")
    elif deduped_barcodes:
        print(f"\n[barcode] Skipping search fallback: platform '{platform}' not supported yet")
    else:
        print(f"\n[barcode] No remaining barcodes to search")

    print()
    print("=" * 60)
    print(f"STAGE 5 RESULT -- Barcode matching ({platform}, {pincode})")
    print("=" * 60)
    print(f"Unmatched input:             {len(unmatched_codes)}")
    print(f"With real EAN barcode:       {unique_items_with_ean}")
    print(f"SAM pool with barcodes:      {len(sam_barcodes)}")
    print(f"Matched via pool lookup:     {matched_by_pool}")
    print(f"Matched via barcode search:  {len(new_matches) - matched_by_pool}")
    print(f"Total new barcode matches:   {len(new_matches)}")
    print()

    if new_matches:
        print("Barcode matches (first 10):")
        for m in new_matches[:10]:
            method = m.get("match_method", "?")
            print(f"  [{method}] EAN {m['barcode']}: {(m.get('anakin_name') or '')[:40]}")
            print(f"           -> {(m.get('sam_product_name') or '')[:40]} (₹{m.get('sam_price', '?')})")

    # Save
    out_dir = PROJECT_ROOT / "data" / "comparisons"
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    out_path = out_dir / f"{platform}_barcode_match_{pincode}_{ts}.json"
    with open(out_path, "w") as f:
        json.dump({
            "pincode": pincode,
            "platform": platform,
            "compared_at": datetime.now().isoformat(),
            "metrics": {
                "unmatched_input": len(unmatched_codes),
                "with_real_ean": unique_items_with_ean,
                "sam_with_barcodes": len(sam_barcodes),
                "matched_by_pool": matched_by_pool,
                "matched_by_search": len(new_matches) - matched_by_pool,
                "new_matches": len(new_matches),
            },
            "new_mappings": new_matches,
        }, f, indent=2, default=str)
    print(f"\nReport: {out_path}")


if __name__ == "__main__":
    pincode = sys.argv[1] if len(sys.argv) > 1 else "834002"
    platform = sys.argv[2] if len(sys.argv) > 2 else "blinkit"
    main(pincode, platform)
