"""
Blinkit Search-based matching: For unmatched products (PDP/cascade/stage3 misses),
search by name on Blinkit, intercept API JSON responses, and match via
brand overlap + name similarity + weight validation.

Uses Chromium (not Firefox) with localStorage location + cookies for pincode.

Usage:
    cd backend && ./venv/bin/python ../scripts/blinkit_search_match.py 834002
"""
import asyncio
import json
import re
import sys
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from urllib.parse import quote

sys.stdout.reconfigure(line_buffering=True)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

import random  # noqa: E402
from playwright.async_api import async_playwright  # noqa: E402
from app.scrapers.base_scraper import USER_AGENTS  # noqa: E402

from utils import clean_str, normalize, latest_file, PROJECT_ROOT  # noqa: E402


# ── Blinkit location data per pincode ──────────────────────────────

BLINKIT_LOCATIONS = {
    "834002": {"lat": 23.3441, "lon": 85.3096, "city": "Ranchi"},
    "712232": {"lat": 22.5726, "lon": 88.3639, "city": "Kolkata"},
    "492001": {"lat": 21.2514, "lon": 81.6296, "city": "Raipur"},
    "825301": {"lat": 23.9921, "lon": 85.3637, "city": "Hazaribagh"},
    "495001": {"lat": 22.0797, "lon": 82.1391, "city": "Bilaspur"},
    "831001": {"lat": 22.8046, "lon": 86.2029, "city": "Jamshedpur"},
}


# ── Weight parsing ─────────────────────────────────────────────────

def parse_wt(name):
    """Parse weight value and unit from product name."""
    if not name:
        return None, None
    m = re.search(
        r"(\d+\.?\d*)\s*(g|gm|gms|kg|kgs|ml|mls|l|ltr|ltrs|pc|pcs|piece|pieces|unit|units|n|nos)\b",
        name.lower(),
    )
    if m:
        v = float(m.group(1))
        u = m.group(2)
        if u in ("gm", "gms"):
            u = "g"
        elif u in ("kgs",):
            u = "kg"
        elif u in ("mls",):
            u = "ml"
        elif u in ("ltrs",):
            u = "ltr"
        elif u in ("pcs", "piece", "pieces", "units", "n", "nos"):
            u = "pc"
        return v, u
    return None, None


def _to_grams_or_ml(val, unit):
    """Normalize weight to base unit (g or ml) for comparison."""
    if val is None or unit is None:
        return None
    u = unit.lower()
    if u == "kg":
        return val * 1000
    if u in ("l", "ltr"):
        return val * 1000
    return val


def weight_ratio_ok(am_val, am_unit, sam_val, sam_unit):
    """Check if AM weight vs SAM weight ratio is within 0.7-1.5.
    Returns True if valid, False if ratio is outside bounds.
    Returns None if either side has no weight (cannot validate)."""
    if am_val is None or sam_val is None:
        return None  # can't validate — no weight data
    if am_unit is None or sam_unit is None:
        return None

    am_base = _to_grams_or_ml(am_val, am_unit)
    sam_base = _to_grams_or_ml(sam_val, sam_unit)
    if am_base is None or sam_base is None:
        return None

    # Units must be in same family (g/kg vs ml/l)
    am_family = "weight" if am_unit.lower() in ("g", "gm", "gms", "kg", "kgs") else (
        "volume" if am_unit.lower() in ("ml", "mls", "l", "ltr", "ltrs") else "count"
    )
    sam_family = "weight" if sam_unit.lower() in ("g", "gm", "gms", "kg", "kgs") else (
        "volume" if sam_unit.lower() in ("ml", "mls", "l", "ltr", "ltrs") else "count"
    )
    if am_family != sam_family:
        return False

    if sam_base == 0:
        return False
    ratio = am_base / sam_base
    return 0.7 <= ratio <= 1.5


# ── Product extraction from intercepted API responses ──────────────

def extract_products_from_json(data, depth=0):
    """Recursively extract product dicts from API response."""
    if depth > 8:
        return []
    products = []
    price_keys = ("price", "mrp", "offer_price", "selling_price")
    if isinstance(data, dict):
        has_price = any(k in data for k in price_keys)
        has_name = any(k in data for k in ("name", "product_name", "title"))
        if has_price and has_name:
            products.append(data)
        for v in data.values():
            products.extend(extract_products_from_json(v, depth + 1))
    elif isinstance(data, list):
        for item in data:
            products.extend(extract_products_from_json(item, depth + 1))
    return products


def _extract_product_fields(p: dict) -> dict | None:
    """Extract normalized fields from a raw product dict."""
    # Name
    name = None
    for k in ("name", "product_name", "display_name", "productName", "title"):
        v = p.get(k)
        if v and isinstance(v, str) and len(v.strip()) > 2:
            name = v.strip()
            break
    if not name:
        return None

    # Product ID — try multiple field names
    pid = None
    for k in ("product_id", "productId", "prid", "id"):
        v = p.get(k)
        if v is not None:
            pid = str(v)
            break

    # Brand
    brand = ""
    for k in ("brand", "brand_name", "brandName"):
        v = p.get(k)
        if v and isinstance(v, str):
            brand = v.strip()
            break

    # Price / MRP
    sp = None
    for k in ("offer_price", "selling_price", "sellingPrice", "finalPrice", "sp"):
        v = p.get(k)
        if v and not isinstance(v, (dict, list)):
            try:
                sp = float(str(v).replace(",", "").replace("₹", "").strip())
                if sp > 50000:
                    sp /= 100
                if sp > 0:
                    break
            except (ValueError, TypeError):
                pass
    # Try nested price dict
    if sp is None and isinstance(p.get("price"), dict):
        inner = p["price"]
        for k in ("offer_price", "selling_price", "sp"):
            v = inner.get(k)
            if v:
                try:
                    sp = float(str(v).replace(",", "").replace("₹", "").strip())
                    if sp > 50000:
                        sp /= 100
                    if sp > 0:
                        break
                except (ValueError, TypeError):
                    pass
    # Scalar price fallback
    if sp is None:
        v = p.get("price")
        if v and not isinstance(v, (dict, list)):
            try:
                sp = float(str(v).replace(",", "").replace("₹", "").strip())
                if sp > 50000:
                    sp /= 100
            except (ValueError, TypeError):
                pass

    mrp = None
    for k in ("mrp", "marked_price", "max_price", "original_price"):
        v = p.get(k)
        if v and not isinstance(v, (dict, list)):
            try:
                mrp = float(str(v).replace(",", "").replace("₹", "").strip())
                if mrp > 50000:
                    mrp /= 100
                if mrp > 0:
                    break
            except (ValueError, TypeError):
                pass
    if mrp is None and isinstance(p.get("price"), dict):
        v = p["price"].get("mrp")
        if v:
            try:
                mrp = float(str(v).replace(",", "").replace("₹", "").strip())
                if mrp > 50000:
                    mrp /= 100
            except (ValueError, TypeError):
                pass

    # MRP fallback: if SP exists but MRP missing, MRP = SP
    if sp and not mrp:
        mrp = sp

    # Unit / weight
    unit = None
    for k in ("unit", "weight", "quantity", "pack_size", "packSize"):
        v = p.get(k)
        if v and isinstance(v, (str, int, float)):
            unit = str(v).strip()
            break

    # Product URL
    slug = p.get("slug") or p.get("url_key") or ""
    product_url = None
    if pid:
        product_url = f"https://blinkit.com/prn/{slug or 'x'}/prid/{pid}"

    return {
        "product_id": pid,
        "name": name,
        "brand": brand,
        "sp": sp,
        "mrp": mrp,
        "unit": unit,
        "product_url": product_url,
    }


# ── Browser setup ──────────────────────────────────────────────────

async def init_blinkit_search_browser(pincode: str):
    """Start Chromium with Blinkit location set.
    Returns (playwright, browser, context, page)."""
    loc = BLINKIT_LOCATIONS.get(pincode)
    if not loc:
        raise ValueError(f"Unknown pincode {pincode} — add to BLINKIT_LOCATIONS")

    print(f"[bk-search] Init Chromium for pincode {pincode} ({loc['city']})", flush=True)

    pw = await async_playwright().start()
    browser = await pw.chromium.launch(
        headless=True,
        args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
    )
    context = await browser.new_context(
        user_agent=random.choice(USER_AGENTS),
        viewport={"width": 1366, "height": 768},
        locale="en-IN",
        timezone_id="Asia/Kolkata",
    )

    # Cookies for location
    await context.add_cookies([
        {"name": "__pincode", "value": pincode, "domain": ".blinkit.com", "path": "/"},
        {"name": "gr_1_lat", "value": str(loc["lat"]), "domain": ".blinkit.com", "path": "/"},
        {"name": "gr_1_lon", "value": str(loc["lon"]), "domain": ".blinkit.com", "path": "/"},
    ])

    # localStorage init script — runs on every page navigation
    location_data = json.dumps({
        "coords": {
            "isDefault": False,
            "lat": loc["lat"],
            "lon": loc["lon"],
            "locality": "Selected Location",
            "id": None,
            "isTopCity": False,
            "cityName": loc["city"],
            "landmark": None,
            "addressId": None,
        }
    })
    await context.add_init_script(f"""
        Object.defineProperty(navigator, 'webdriver', {{get: () => undefined}});
        window.chrome = {{runtime: {{}}}};
        try {{
            localStorage.setItem('location', {json.dumps(location_data)});
        }} catch(e) {{}}
    """)

    # Warm-up: load blinkit homepage to bind origin
    page = await context.new_page()
    try:
        await page.goto("https://blinkit.com", wait_until="domcontentloaded", timeout=20000)
        await asyncio.sleep(1.5)
    except Exception:
        pass

    return pw, browser, context, page


# ── Search + match for one product ─────────────────────────────────

async def search_one_product(
    page,
    search_term: str,
    target_name: str,
    am_brand: str,
    am_weight_val: float | None,
    am_weight_unit: str | None,
) -> dict | None:
    """Search Blinkit for a product, intercept API responses, return best match."""
    captured = []

    async def on_response(response):
        try:
            ct = response.headers.get("content-type", "")
            if "json" not in ct or response.status != 200:
                return
            body = await response.text()
            if len(body) < 50:
                return
            low = body.lower()
            if not any(kw in low for kw in ("mrp", "price", "product", "name")):
                return
            try:
                data = json.loads(body)
                captured.append(data)
            except json.JSONDecodeError:
                pass
        except Exception:
            pass

    page.on("response", on_response)
    try:
        search_url = f"https://blinkit.com/s/?q={quote(search_term)}"
        await page.goto(search_url, wait_until="domcontentloaded", timeout=20000)

        # Smart wait: poll for API responses, max 4s
        for _ in range(8):
            await asyncio.sleep(0.5)
            if captured:
                break
        # Give an extra moment for all responses to settle
        await asyncio.sleep(1.0)

        # Extract all products from captured responses
        all_products = []
        for payload in captured:
            raw = extract_products_from_json(payload)
            for r in raw:
                pf = _extract_product_fields(r)
                if pf and pf["name"]:
                    all_products.append(pf)

        if not all_products:
            return None

        # Deduplicate by product_id
        seen_ids = set()
        unique_products = []
        for p in all_products:
            pid = p.get("product_id")
            if pid and pid in seen_ids:
                continue
            if pid:
                seen_ids.add(pid)
            unique_products.append(p)

        # Find best match: brand overlap + name similarity + weight validation
        target_norm = normalize(target_name)
        target_brand_norm = normalize(am_brand) if am_brand else ""
        target_brand_words = set(target_brand_norm.split()) if target_brand_norm else set()
        # Fallback: first 2 significant words from target_name
        if not target_brand_words and target_name:
            target_brand_words = {normalize(w) for w in target_name.split()[:2] if len(w) >= 3}

        best_score = 0.0
        best_product = None

        for p in unique_products:
            p_name = p["name"]
            p_norm = normalize(p_name)
            p_brand_norm = normalize(p.get("brand") or "")
            p_brand_words = set(p_brand_norm.split()) if p_brand_norm else set()

            # Brand overlap check
            if target_brand_words and p_brand_words:
                has_brand_overlap = bool(target_brand_words & p_brand_words)
                has_name_overlap = any(bw in p_norm for bw in target_brand_words if len(bw) >= 3)
                if not has_brand_overlap and not has_name_overlap:
                    continue

            # Weight validation (MANDATORY — reject if ratio outside 0.7-1.5)
            sam_wt_val, sam_wt_unit = parse_wt(p_name)
            # Also try the unit field from API
            if sam_wt_val is None and p.get("unit"):
                sam_wt_val, sam_wt_unit = parse_wt(p["unit"])

            wt_ok = weight_ratio_ok(am_weight_val, am_weight_unit, sam_wt_val, sam_wt_unit)
            if wt_ok is False:
                # Weight mismatch — reject
                continue
            # wt_ok is None means we couldn't validate (no weight on one side)
            # wt_ok is True means weight is valid

            score = SequenceMatcher(None, target_norm, p_norm).ratio()

            # If weight couldn't be validated, require higher name threshold
            if wt_ok is None:
                if score < 0.70:
                    continue
            else:
                if score < 0.55:
                    continue

            if score > best_score:
                best_score = score
                best_product = p

        if best_product and best_score >= 0.55:
            return {
                "product_id": best_product.get("product_id"),
                "product_name": best_product["name"],
                "brand": best_product.get("brand", ""),
                "sp": best_product.get("sp"),
                "mrp": best_product.get("mrp"),
                "unit": best_product.get("unit"),
                "product_url": best_product.get("product_url"),
                "match_score": round(best_score, 3),
            }

    except Exception as e:
        print(f"  search error: {e}", flush=True)
    finally:
        try:
            page.remove_listener("response", on_response)
        except Exception:
            pass

    return None


# ── Load AM product master for weight data ─────────────────────────

def load_am_master() -> dict:
    """Load AM product master (item_code → product dict)."""
    path = PROJECT_ROOT / "data" / "am_product_master.json"
    if not path.exists():
        print(f"[bk-search] WARNING: AM product master not found at {path}", flush=True)
        return {}
    data = json.load(open(path))
    # Keys are already item_code strings
    return data


# ── Main ───────────────────────────────────────────────────────────

async def main(pincode: str):
    # Load Anakin blinkit data
    ana_path = latest_file("anakin", f"blinkit_{pincode}_*.json")
    if not ana_path:
        print(f"[bk-search] ERROR: no Anakin Blinkit file for {pincode}", file=sys.stderr)
        sys.exit(1)
    ana = json.load(open(ana_path))

    # Load AM product master for weight validation
    am_master = load_am_master()
    print(f"[bk-search] AM product master: {len(am_master)} items", flush=True)

    # Load product_mapping.json
    mapping_path = PROJECT_ROOT / "data" / "mappings" / "product_mapping.json"
    product_mapping = {}
    if mapping_path.exists():
        product_mapping = json.load(open(mapping_path))
    print(f"[bk-search] Product mapping: {len(product_mapping)} entries", flush=True)

    # Find usable items (have selling price, not loose)
    usable = {
        r.get("Item_Code")
        for r in ana["records"]
        if r.get("Blinkit_Selling_Price") not in (None, "", "NA", "nan")
        and "loose" not in (r.get("Item_Name") or "").lower()
    }

    # Find already-matched items from PDP compare + cascade + stage3
    matched = set()
    comp_dir = PROJECT_ROOT / "data" / "comparisons"
    for pat in [
        "blinkit_pdp_*_compare.json",
        "blinkit_cascade_*.json",
        "blinkit_stage3_*.json",
        "blinkit_barcode_match_*.json",
        "blinkit_image_match_*.json",
    ]:
        for f in sorted(comp_dir.glob(pat)):
            try:
                d = json.load(open(f))
                for m in d.get("matches", []):
                    if m.get("match_status") == "ok":
                        matched.add(m.get("item_code"))
                for m in d.get("new_mappings", []):
                    matched.add(m.get("item_code"))
            except (json.JSONDecodeError, KeyError):
                pass

    unmatched_codes = usable - matched
    unmatched_skus = [r for r in ana["records"] if r.get("Item_Code") in unmatched_codes]

    print(f"[bk-search] Anakin: {ana_path.name}")
    print(f"[bk-search] Usable non-loose: {len(usable)}")
    print(f"[bk-search] Already matched: {len(matched & usable)}")
    print(f"[bk-search] Unmatched (search input): {len(unmatched_skus)}")
    print()

    if not unmatched_skus:
        print("[bk-search] Nothing to search — all items matched!", flush=True)
        return

    # Init browser
    pw, browser, context, page = await init_blinkit_search_browser(pincode)

    new_matches = []
    no_result = 0
    weight_rejected = 0
    errors = 0

    try:
        for i, sku in enumerate(unmatched_skus):
            bk_name = clean_str(sku.get("Blinkit_Item_Name"))
            ana_name = clean_str(sku.get("Item_Name"))
            ana_brand = clean_str(sku.get("Brand"))
            item_code = sku.get("Item_Code", "")
            search_term = bk_name or ana_name
            if not search_term:
                no_result += 1
                continue

            # Get AM weight for validation
            am_item = am_master.get(str(item_code), {})
            am_unit_value = am_item.get("unit_value")
            am_unit = am_item.get("unit")
            # Fallback: parse from Anakin fields
            if am_unit_value is None:
                try:
                    am_unit_value = float(str(sku.get("Unit_Value", "")).replace(",", ""))
                except (ValueError, TypeError):
                    am_unit_value = None
            if not am_unit:
                am_unit = clean_str(sku.get("Unit"))
            # Also try parsing weight from product name as last resort
            if am_unit_value is None:
                am_unit_value, am_unit = parse_wt(ana_name)

            result = await search_one_product(
                page,
                search_term,
                search_term,
                am_brand=ana_brand,
                am_weight_val=am_unit_value,
                am_weight_unit=am_unit,
            )

            if result:
                ana_sp = None
                try:
                    ana_sp = float(str(sku.get("Blinkit_Selling_Price", "")).replace(",", ""))
                except (ValueError, TypeError):
                    pass

                price_diff = None
                if ana_sp and result["sp"]:
                    price_diff = abs(result["sp"] - ana_sp) / ana_sp * 100

                # Parse SAM weight for output
                sam_wt_val, sam_wt_unit = parse_wt(result["product_name"])
                if sam_wt_val is None and result.get("unit"):
                    sam_wt_val, sam_wt_unit = parse_wt(result["unit"])

                new_matches.append({
                    "item_code": item_code,
                    "anakin_name": ana_name,
                    "anakin_blinkit_name": bk_name,
                    "anakin_brand": ana_brand,
                    "anakin_sp": ana_sp,
                    "am_weight": f"{am_unit_value} {am_unit}" if am_unit_value else None,
                    "sam_product_id": result["product_id"],
                    "sam_product_name": result["product_name"],
                    "sam_brand": result["brand"],
                    "sam_price": result["sp"],
                    "sam_mrp": result["mrp"],
                    "sam_unit": result["unit"],
                    "sam_weight": f"{sam_wt_val} {sam_wt_unit}" if sam_wt_val else None,
                    "sam_product_url": result["product_url"],
                    "match_score": result["match_score"],
                    "price_diff_pct": round(price_diff, 1) if price_diff is not None else None,
                    "match_method": "blinkit_search",
                })
            else:
                no_result += 1

            if (i + 1) % 20 == 0:
                print(
                    f"  [{i+1}/{len(unmatched_skus)}] "
                    f"{len(new_matches)} matched, {no_result} no-result",
                    flush=True,
                )

    finally:
        try:
            await browser.close()
            await pw.stop()
        except Exception:
            pass

    # ── Summary ────────────────────────────────────────────────────
    print()
    print("=" * 60)
    print(f"BLINKIT SEARCH MATCH (pincode {pincode})")
    print("=" * 60)
    print(f"Input:          {len(unmatched_skus)}")
    print(f"New matches:    {len(new_matches)}")
    print(f"No result:      {no_result}")
    print()

    if new_matches:
        # Price accuracy vs Anakin SP
        priced = [m for m in new_matches if m.get("price_diff_pct") is not None]
        in5 = sum(1 for m in priced if m["price_diff_pct"] <= 5)
        in10 = sum(1 for m in priced if m["price_diff_pct"] <= 10)
        if priced:
            print("Price accuracy (vs Anakin SP):")
            print(f"  ±5%:  {in5}/{len(priced)} = {in5*100/len(priced):.1f}%")
            print(f"  ±10%: {in10}/{len(priced)} = {in10*100/len(priced):.1f}%")
            print()

        print("Sample matches (top 5 by score):")
        for m in sorted(new_matches, key=lambda x: -x["match_score"])[:5]:
            diff = f" | diff={m['price_diff_pct']}%" if m.get("price_diff_pct") is not None else ""
            print(f"  [{m['match_score']:.2f}] {m['anakin_blinkit_name'][:40]}")
            print(f"       -> {m['sam_product_name'][:40]} | Rs.{m['sam_price']}{diff}")

    # ── Update product_mapping.json ────────────────────────────────
    mapping_updates = 0
    for m in new_matches:
        key = f"blinkit_{pincode}_{m['item_code']}"
        if key not in product_mapping:
            product_mapping[key] = {
                "item_code": m["item_code"],
                "platform": "blinkit",
                "pincode": pincode,
                "product_id": m["sam_product_id"],
                "product_url": m["sam_product_url"],
                "platform_name": m["sam_product_name"],
                "weight_value": None,
                "weight_unit": None,
                "last_sp": m["sam_price"],
                "last_mrp": m["sam_mrp"],
                "in_stock": "available",
                "source": "blinkit_search",
                "source_file": f"blinkit_search_match_{pincode}_{datetime.now().strftime('%Y-%m-%d')}.json",
            }
            # Parse weight for mapping
            wv, wu = parse_wt(m["sam_product_name"])
            if wv is None and m.get("sam_unit"):
                wv, wu = parse_wt(m["sam_unit"])
            product_mapping[key]["weight_value"] = wv
            product_mapping[key]["weight_unit"] = wu
            mapping_updates += 1

    if mapping_updates > 0:
        mapping_path.parent.mkdir(parents=True, exist_ok=True)
        with open(mapping_path, "w") as f:
            json.dump(product_mapping, f, indent=2, default=str)
        print(f"\n[bk-search] Updated product_mapping.json: +{mapping_updates} new entries (total {len(product_mapping)})")

    # ── Save results ───────────────────────────────────────────────
    out_dir = PROJECT_ROOT / "data" / "comparisons"
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    out_path = out_dir / f"blinkit_search_match_{pincode}_{ts}.json"
    with open(out_path, "w") as f:
        json.dump({
            "pincode": pincode,
            "compared_at": datetime.now().isoformat(),
            "metrics": {
                "input": len(unmatched_skus),
                "new_matches": len(new_matches),
                "no_result": no_result,
                "mapping_updates": mapping_updates,
            },
            "new_mappings": new_matches,
        }, f, indent=2, default=str)
    print(f"\nReport: {out_path}")


if __name__ == "__main__":
    pincode = sys.argv[1] if len(sys.argv) > 1 else "834002"
    asyncio.run(main(pincode))
