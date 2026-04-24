"""
Stage 1: Direct PDP (Product Detail Page) scraping for Blinkit.

Reads Anakin's cached Blinkit_Product_Url list, visits each PDP in parallel,
and scrapes live price/stock. Saves output keyed by Apna item_code for
exact-join comparison.

Flow:
    1. Load data/anakin/blinkit_<pincode>_<date>.json
    2. Extract every (item_code, Blinkit_Product_Url, Blinkit_Product_Id) where URL != "NA"
    3. Init ONE Chromium browser with Ranchi location set (Blinkit-specific setup)
    4. Spawn N parallel tabs (default 5), each pulling URLs from a queue
    5. For each PDP: page.goto, wait for product card, extract name/price/mrp/stock
    6. Save to data/sam/blinkit_pdp_<pincode>_<ts>.json

Usage:
    cd backend && ./venv/bin/python ../scripts/scrape_blinkit_pdps.py 834002 [num_tabs]
"""
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

# Line-buffered stdout for real-time progress
sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from playwright.async_api import async_playwright  # noqa: E402
from app.scrapers.base_scraper import get_coords, USER_AGENTS  # noqa: E402
import random  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def latest_anakin_file(pincode: str) -> Path | None:
    cands = sorted((PROJECT_ROOT / "data" / "anakin").glob(f"blinkit_{pincode}_*.json"))
    return cands[-1] if cands else None


async def init_blinkit_browser(pincode: str, num_tabs: int):
    """Start Chromium, set Blinkit location on EVERY new page via init_script + cookies.
    Returns (playwright, browser, context, pages)."""
    lat, lng = get_coords(pincode)
    print(f"[pdp] Init browser for pincode {pincode} ({lat}, {lng}) with {num_tabs} tabs", flush=True)

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

    # Set cookies at the context level — applies to ALL pages in this context
    await context.add_cookies([
        {"name": "__pincode", "value": pincode, "domain": ".blinkit.com", "path": "/"},
        {"name": "gr_1_lat", "value": str(lat), "domain": ".blinkit.com", "path": "/"},
        {"name": "gr_1_lon", "value": str(lng), "domain": ".blinkit.com", "path": "/"},
    ])

    # Init scripts run on EVERY new document (every page.goto).
    # This sets localStorage before Blinkit's own JS reads it.
    location_data = json.dumps({
        "coords": {
            "isDefault": False,
            "lat": lat,
            "lon": lng,
            "locality": "Selected Location",
            "id": None,
            "isTopCity": False,
            "cityName": "Selected",
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

    # Warm-up: load blinkit homepage once so Chromium binds the origin.
    warm = await context.new_page()
    try:
        await warm.goto("https://blinkit.com", wait_until="domcontentloaded", timeout=20000)
        await asyncio.sleep(1)
    except Exception:
        pass
    await warm.close()

    # Create worker tabs — each will also run the init_script on goto
    pages = []
    for _ in range(num_tabs):
        pages.append(await context.new_page())

    return pw, browser, context, pages


def _find_product_in_json(data, target_pid: str, depth: int = 0):
    """Recursively walk a JSON tree looking for a product object matching target_pid.
    A product object must have BOTH:
      - a matching product_id/id field
      - at least one price-like field (mrp, price, offer_price, etc.)
      - at least one name-like field (name, product_name, display_name, title)
    This prevents matching page-level metadata (tracking.le_meta) which has 'id' but no prices.
    Returns the matching dict or None."""
    if depth > 12:
        return None
    if isinstance(data, dict):
        # Check multiple ID field names
        this_id = str(data.get("product_id") or data.get("productId") or data.get("prid") or "")
        # Only fall back to generic "id" if the dict also has product-like fields
        if not this_id:
            raw_id = data.get("id")
            if raw_id is not None and any(k in data for k in ("product_name", "display_name", "brand", "unit")):
                this_id = str(raw_id)

        if this_id == str(target_pid):
            has_price = any(k in data for k in ("mrp", "price", "offer_price", "selling_price", "sellingPrice"))
            has_name = any(k in data for k in ("name", "product_name", "display_name", "title"))
            if has_price and has_name:
                return data
            # Even without name, if it has price + product_id (not just 'id'), accept it
            if has_price and "product_id" in data:
                return data

        for v in data.values():
            found = _find_product_in_json(v, target_pid, depth + 1)
            if found:
                return found
    elif isinstance(data, list):
        for item in data:
            found = _find_product_in_json(item, target_pid, depth + 1)
            if found:
                return found
    return None


def _find_name_in_payload(data, target_pid: str, depth: int = 0) -> str | None:
    """Search entire JSON payload for a product name associated with target_pid.
    Blinkit sometimes puts name at a parent/sibling level, not in the price dict."""
    if depth > 12:
        return None
    if isinstance(data, dict):
        # Check if this dict has the target product_id AND a name
        pid = str(data.get("product_id") or data.get("productId") or data.get("prid") or data.get("id") or "")
        if pid == str(target_pid):
            for k in ("name", "product_name", "display_name", "productName", "title"):
                v = data.get(k)
                if v and isinstance(v, str) and len(v.strip()) > 2:
                    return v.strip()
        # Also check if this dict has a name AND contains the target_pid somewhere
        # in its immediate children (handles parent-dict-with-name + child-with-pid pattern)
        if not pid or pid != str(target_pid):
            name_here = None
            for k in ("name", "product_name", "display_name", "productName", "title"):
                v = data.get(k)
                if v and isinstance(v, str) and len(v.strip()) > 2:
                    name_here = v.strip()
                    break
            if name_here:
                # Check if target_pid appears anywhere in this dict's JSON representation
                # (lightweight: only check immediate children that are dicts/lists with product_id)
                for child_v in data.values():
                    if isinstance(child_v, dict):
                        child_pid = str(child_v.get("product_id") or child_v.get("productId") or child_v.get("prid") or "")
                        if child_pid == str(target_pid):
                            return name_here
                    elif isinstance(child_v, list):
                        for item in child_v:
                            if isinstance(item, dict):
                                child_pid = str(item.get("product_id") or item.get("productId") or item.get("prid") or "")
                                if child_pid == str(target_pid):
                                    return name_here
        for v in data.values():
            found = _find_name_in_payload(v, target_pid, depth + 1)
            if found:
                return found
    elif isinstance(data, list):
        for item in data:
            found = _find_name_in_payload(item, target_pid, depth + 1)
            if found:
                return found
    return None


def _extract_price_from_product_dict(p: dict) -> tuple[float | None, float | None]:
    """Pull selling_price and mrp out of a Blinkit product dict, handling nested pricing objects."""
    sp = None
    mrp = None

    # MRP first — Blinkit usually has a clean top-level 'mrp'
    for k in ("mrp", "marked_price", "max_price", "original_price"):
        v = p.get(k)
        if v:
            try:
                mrp = float(str(v).replace(",", "").replace("₹", "").strip())
                if mrp > 50000:
                    mrp /= 100  # paise → rupees
                if mrp > 0:
                    break
            except (ValueError, TypeError):
                pass

    # SP: try top-level first, then nested
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

    # Sometimes 'price' itself is a dict like {mrp: .., offer_price: ..}
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
        if mrp is None:
            mv = inner.get("mrp")
            if mv:
                try:
                    mrp = float(str(mv).replace(",", "").replace("₹", "").strip())
                    if mrp > 50000:
                        mrp /= 100
                except (ValueError, TypeError):
                    pass

    # Top-level 'price' as scalar number
    if sp is None:
        v = p.get("price")
        if v and not isinstance(v, (dict, list)):
            try:
                sp = float(str(v).replace(",", "").replace("₹", "").strip())
                if sp > 50000:
                    sp /= 100
            except (ValueError, TypeError):
                pass

    # If MRP not found but SP exists, MRP = SP (no discount)
    if sp and not mrp:
        mrp = sp
    return sp, mrp


async def scrape_one_pdp(page, item_code: str, url: str, blinkit_pid: str,
                         anakin_name: str = "", max_retries: int = 3) -> dict:
    """Visit a single Blinkit PDP, intercept product JSON API responses, extract price/stock/name.
    Retries on transient network errors with exponential backoff."""
    out = {
        "item_code": item_code,
        "blinkit_product_id": blinkit_pid,
        "blinkit_product_url": url,
        "scraped_at": datetime.now(tz=None).isoformat(),
        "_anakin_name": anakin_name,
    }
    captured: list = []

    async def on_response(response):
        try:
            ct = response.headers.get("content-type", "")
            if "json" not in ct or response.status != 200:
                return
            body = await response.text()
            if len(body) < 50:
                return
            low = body.lower()
            if not any(kw in low for kw in ("mrp", "price", "product")):
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
        last_error = None
        for attempt in range(max_retries):
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=18000)
                last_error = None
                break
            except Exception as e:
                err_str = str(e)
                last_error = err_str
                # Transient network errors — worth retrying
                transient = any(k in err_str for k in (
                    "ERR_INTERNET_DISCONNECTED",
                    "ERR_NETWORK_CHANGED",
                    "ERR_NAME_NOT_RESOLVED",
                    "ERR_CONNECTION_RESET",
                    "ERR_TIMED_OUT",
                    "ERR_CONNECTION_REFUSED",
                    "ERR_ABORTED",
                    "Timeout",
                ))
                if transient and attempt < max_retries - 1:
                    backoff = 5 * (2 ** attempt)  # 5s, 10s, 20s
                    await asyncio.sleep(backoff)
                    continue
                break
        if last_error is not None:
            out["status"] = "error"
            out["error"] = f"goto (after {attempt+1} attempts): {last_error[:150]}"
            return out

        # Smart wait: poll for product in captured responses, max 4s
        # Fast products resolve in 0.5s, slow ones get up to 4s
        product_dict = None
        for _wait in range(8):  # 8 × 0.5s = 4s max
            await asyncio.sleep(0.5)
            for payload in captured:
                found = _find_product_in_json(payload, blinkit_pid)
                if found:
                    product_dict = found
                    break
            if product_dict:
                break

        # ── Early detect: homepage redirect = product not available at this location ──
        final_url = page.url
        if final_url and ("blinkit.com/" == final_url.rstrip("/").split("//")[-1]
                          or final_url.rstrip("/").endswith("blinkit.com")):
            out.update({
                "sam_product_name": None,
                "sam_selling_price": None,
                "sam_mrp": None,
                "sam_in_stock": False,
                "sam_unit": None,
                "status": "not_available",
            })
            return out

        # ── Try 1: product_dict already found in smart-wait loop above ──
        # If not found yet, one final check on all captured responses
        if not product_dict:
            for payload in captured:
                found = _find_product_in_json(payload, blinkit_pid)
                if found:
                    product_dict = found
                break

        sp = mrp = None
        name = None
        unit = None
        in_stock = True

        if product_dict:
            sp, mrp = _extract_price_from_product_dict(product_dict)
            for k in ("name", "product_name", "display_name", "productName", "title"):
                v = product_dict.get(k)
                if v and isinstance(v, str) and len(v.strip()) > 2:
                    name = v.strip()
                    break
            # If name not in product dict, search entire captured payload for name near this product_id
            if not name:
                for payload in captured:
                    name = _find_name_in_payload(payload, blinkit_pid)
                    if name:
                        break
            for k in ("unit", "weight", "quantity", "pack_size", "packSize"):
                v = product_dict.get(k)
                if v and isinstance(v, (str, int, float)):
                    unit = str(v).strip()
                    break
            for k in ("inventory", "in_stock", "inStock", "available"):
                v = product_dict.get(k)
                if v is not None:
                    if isinstance(v, bool):
                        in_stock = v
                    elif isinstance(v, (int, float)):
                        in_stock = v > 0

        # ── Try 2: DOM fallback using meta tags + h1-anchored price ──
        if sp is None or not name:
            # Brief extra wait for SPA rendering (h1 may not be in initial HTML)
            await asyncio.sleep(0.8)
            dom_data = await page.evaluate("""() => {
                // Product name from h1, og:title, or document.title
                let name = '';
                const h1 = document.querySelector('h1');
                if (h1) name = (h1.innerText || '').trim();
                if (!name) {
                    const og = document.querySelector('meta[property="og:title"]');
                    if (og) name = (og.getAttribute('content') || '').trim();
                }
                if (!name) {
                    // Blinkit sets document.title to "Product Name | Blinkit ..."
                    const dt = (document.title || '').split('|')[0].split('-')[0].trim();
                    if (dt && dt.length > 2 && dt.toLowerCase() !== 'blinkit') name = dt;
                }

                // Price from og meta tags (cleanest)
                const metaPriceEl = document.querySelector('meta[property="product:price:amount"], meta[property="og:price:amount"]');
                let sp_meta = null;
                if (metaPriceEl) {
                    const v = parseFloat((metaPriceEl.getAttribute('content') || '').replace(',', ''));
                    if (v > 0) sp_meta = v;
                }

                // Try to find product price near the h1 (within 800px below)
                let sp_near_h1 = null, mrp_near_h1 = null;
                if (h1) {
                    const h1Rect = h1.getBoundingClientRect();
                    const spans = document.querySelectorAll('span, div, p, strong');
                    const candidates = [];
                    for (const el of spans) {
                        const t = (el.textContent || '').trim();
                        if (!t.includes('\\u20B9')) continue;
                        if (t.length > 30) continue;  // must be a short price label
                        const m = t.match(/\\u20B9\\s*([\\d,]+\\.?\\d*)/);
                        if (!m) continue;
                        const price = parseFloat(m[1].replace(/,/g, ''));
                        if (price <= 0 || price > 20000) continue;
                        const r = el.getBoundingClientRect();
                        // Must be near the h1 (above or below within 800px, same viewport column area)
                        if (Math.abs(r.top - h1Rect.top) > 800) continue;
                        candidates.push({ price, top: r.top });
                    }
                    // Pick the highest-price number near the top (title area usually has the main price)
                    candidates.sort((a, b) => Math.abs(a.top - h1Rect.top) - Math.abs(b.top - h1Rect.top));
                    // Among the closest 5, separate into distinct SP/MRP by frequency
                    const near = candidates.slice(0, 8).map(c => c.price);
                    const uniq = [...new Set(near)].sort((a, b) => b - a);
                    if (uniq.length >= 2) {
                        mrp_near_h1 = uniq[0];
                        sp_near_h1 = uniq[1];
                    } else if (uniq.length === 1) {
                        sp_near_h1 = uniq[0];
                    }
                }

                // Stock / availability
                const bodyLower = (document.body.innerText || '').toLowerCase();
                let in_stock = true;
                if (bodyLower.includes('currently unavailable') ||
                    bodyLower.includes('notify me when available') ||
                    bodyLower.includes('out of stock') ||
                    bodyLower.includes('sold out')) {
                    in_stock = false;
                }

                // Unit
                let unit = '';
                const unitEl = document.querySelector('[class*="Weight"], [class*="weight"], [class*="pack-size"]');
                if (unitEl) unit = (unitEl.innerText || '').trim();

                return { name, sp_meta, sp_near_h1, mrp_near_h1, in_stock, unit };
            }""")

            if not name:
                name = dom_data.get("name") or None
            if sp is None:
                sp = dom_data.get("sp_meta") or dom_data.get("sp_near_h1")
            if mrp is None:
                mrp = dom_data.get("mrp_near_h1")
            if unit is None:
                unit = dom_data.get("unit") or None
            # Only use DOM stock status when API didn't already find the product
            # (API stock info is more reliable than DOM text search)
            if not product_dict:
                in_stock = dom_data.get("in_stock", in_stock)

        # ── Try 3: Auto-heal fallback (JSON-LD, meta tags, raw regex) ──
        if sp is None:
            try:
                # JSON-LD structured data
                ld_result = await page.evaluate("""() => {
                    const scripts = document.querySelectorAll('script[type="application/ld+json"]');
                    for (const s of scripts) {
                        try {
                            const data = JSON.parse(s.textContent);
                            const items = Array.isArray(data) ? data : [data];
                            const stack = [...items];
                            while (stack.length) {
                                const cur = stack.pop();
                                if (!cur || typeof cur !== 'object') continue;
                                if (cur['@type'] === 'Product' || cur['@type'] === 'ProductGroup') {
                                    const pname = cur.name || '';
                                    const offers = cur.offers || {};
                                    const offerList = Array.isArray(offers) ? offers : [offers];
                                    for (const off of offerList) {
                                        const sp = parseFloat(off.price || off.lowPrice);
                                        const mrp = parseFloat(off.highPrice);
                                        if (sp > 0) return {sp, mrp: mrp > 0 ? mrp : null, name: pname};
                                    }
                                }
                                if (cur['@graph']) stack.push(...cur['@graph']);
                                for (const v of Object.values(cur)) {
                                    if (v && typeof v === 'object') stack.push(v);
                                }
                            }
                        } catch(e) {}
                    }
                    return null;
                }""")
                if ld_result and ld_result.get("sp") and 1 <= ld_result["sp"] <= 50000:
                    sp = ld_result["sp"]
                    mrp = mrp or ld_result.get("mrp")
                    name = name or ld_result.get("name")
            except Exception:
                pass

        # ── Try 4: Raw HTML regex (last resort) ──
        if sp is None:
            try:
                html = await page.content()
                import re as _re
                prices = []
                for m_p in _re.finditer(r'"(?:price|selling_price|offer_price|sp|sellingPrice)"[:\s]*"?(\d+\.?\d*)"?', html, _re.IGNORECASE):
                    try:
                        p = float(m_p.group(1))
                        if 1 < p < 50000:
                            prices.append(p)
                    except ValueError:
                        pass
                for m_p in _re.finditer(r'₹\s*([\d,]+\.?\d*)', html):
                    try:
                        p = float(m_p.group(1).replace(',', ''))
                        if 1 < p < 50000:
                            prices.append(p)
                    except ValueError:
                        pass
                if prices:
                    from collections import Counter as _Counter
                    freq = _Counter(prices)
                    most_common = freq.most_common(3)
                    if len(most_common) >= 2:
                        sp = min(most_common[0][0], most_common[1][0])
                        mrp = mrp or max(most_common[0][0], most_common[1][0])
                    elif most_common:
                        sp = most_common[0][0]
            except Exception:
                pass

        # Final MRP fallback: if SP exists but MRP is missing, set MRP = SP (no discount)
        if sp and not mrp:
            mrp = sp

        # Detect SPA redirect: Blinkit SPA doesn't change URL on redirect,
        # but sets page title/name to "blinkit.com" instead of product name.
        # When this happens, try SEARCH as fallback before giving up.
        if not sp and name and name.lower().strip() in ("blinkit.com", "blinkit"):
            # Search fallback: use Anakin item name to search on Blinkit
            search_name = out.get("_anakin_name", "")
            if search_name:
                try:
                    from urllib.parse import quote
                    search_url = f"https://blinkit.com/s/?q={quote(search_name)}"
                    search_captured = []

                    async def on_search_response(response):
                        try:
                            ct = response.headers.get("content-type", "")
                            if "json" in ct and response.status == 200:
                                body = await response.text()
                                if len(body) > 50 and any(kw in body.lower() for kw in ("product", "price", "mrp")):
                                    search_captured.append(json.loads(body))
                        except Exception:
                            pass

                    page.on("response", on_search_response)
                    await page.goto(search_url, wait_until="domcontentloaded", timeout=15000)
                    await asyncio.sleep(2.0)
                    page.remove_listener("response", on_search_response)

                    # Find best match by product_id in search results
                    for payload in search_captured:
                        found = _find_product_in_json(payload, blinkit_pid)
                        if found:
                            sp, mrp = _extract_price_from_product_dict(found)
                            if sp:
                                for k in ("name", "product_name", "display_name", "productName", "title"):
                                    v = found.get(k)
                                    if v and isinstance(v, str) and len(v.strip()) > 2:
                                        name = v.strip()
                                        break
                                if not name:
                                    name = _find_name_in_payload(payload, blinkit_pid)
                                if not mrp:
                                    mrp = sp
                                out.update({
                                    "sam_product_name": name,
                                    "sam_selling_price": sp,
                                    "sam_mrp": mrp,
                                    "sam_in_stock": True,
                                    "sam_unit": None,
                                    "status": "ok",
                                })
                                return out
                except Exception:
                    pass

            out.update({
                "sam_product_name": None,
                "sam_selling_price": None,
                "sam_mrp": None,
                "sam_in_stock": False,
                "sam_unit": None,
                "status": "not_available",
            })
            return out

        out.update({
            "sam_product_name": name,
            "sam_selling_price": sp,
            "sam_mrp": mrp,
            "sam_in_stock": bool(in_stock),
            "sam_unit": unit,
            "status": "ok" if sp else "no_price",
        })
    except Exception as e:
        out["status"] = "error"
        out["error"] = str(e)[:200]
    finally:
        try:
            page.remove_listener("response", on_response)
        except Exception:
            pass
    return out


def save_snapshot(pincode: str, results: list, anakin_file: str, duration: float, partial: bool) -> Path:
    """Save current results to JSON. Used for incremental snapshots + final save."""
    out_dir = PROJECT_ROOT / "data" / "sam"
    out_dir.mkdir(parents=True, exist_ok=True)
    suffix = "_partial" if partial else ""
    out_path = out_dir / f"blinkit_pdp_{pincode}_latest{suffix}.json"
    ok = sum(1 for r in results if r.get("status") == "ok")
    no_price = sum(1 for r in results if r.get("status") == "no_price")
    errs = sum(1 for r in results if r.get("status") == "error")
    with open(out_path, "w") as f:
        json.dump({
            "pincode": pincode,
            "source": "anakin_url_seed",
            "anakin_file": anakin_file,
            "scraped_at": datetime.now().isoformat(),
            "duration_seconds": round(duration, 1),
            "partial": partial,
            "total_scraped": len(results),
            "ok": ok,
            "no_price": no_price,
            "errors": errs,
            "products": results,
        }, f, indent=2, default=str)
    return out_path


async def worker(worker_id: int, page, queue: asyncio.Queue, results: list,
                 progress_counter: list, total: int, pincode: str, anakin_file: str, start_time):
    while True:
        try:
            item_code, url, blinkit_pid, anakin_name = queue.get_nowait()
        except asyncio.QueueEmpty:
            break
        result = await scrape_one_pdp(page, item_code, url, blinkit_pid, anakin_name=anakin_name)
        results.append(result)
        progress_counter[0] += 1
        if progress_counter[0] % 20 == 0:
            ok = sum(1 for r in results if r.get("status") == "ok")
            print(f"[pdp] [worker {worker_id}] {progress_counter[0]}/{total} — {ok} with price", flush=True)
        # Incremental snapshot every 200
        if progress_counter[0] % 200 == 0:
            duration = (datetime.now() - start_time).total_seconds()
            snap_path = save_snapshot(pincode, results, anakin_file, duration, partial=True)
            print(f"[pdp] snapshot saved to {snap_path.name} ({len(results)} so far)", flush=True)


async def main(pincode: str, num_tabs: int = 5):
    urls_to_scrape = []
    skipped_oos = 0
    source_name = ""

    # Source 1: Anakin file for this pincode
    ana_path = latest_anakin_file(pincode)
    if ana_path:
        ana = json.load(open(ana_path))
        for rec in ana["records"]:
            pid = (rec.get("Blinkit_Product_Id") or "").strip()
            url = (rec.get("Blinkit_Product_Url") or "").strip()
            ic = (rec.get("Item_Code") or "").strip()
            if pid and pid != "NA" and url and url.startswith("http"):
                stock = (rec.get("Blinkit_In_Stock_Remark") or "").lower()
                if stock == "out_of_stock":
                    skipped_oos += 1
                    continue
                aname = (rec.get("Blinkit_Item_Name") or rec.get("Item_Name") or "").strip()
                urls_to_scrape.append((ic, url, pid, aname))
        source_name = ana_path.name

    # Source 2: product_mapping.json — fallback for cities without Anakin data
    # Product IDs are same across cities, only location/availability changes
    if not urls_to_scrape:
        mapping_path = PROJECT_ROOT / "data" / "mappings" / "product_mapping.json"
        if mapping_path.exists():
            mapping = json.load(open(mapping_path))
            seen_ics = set()
            for key, entry in mapping.items():
                if entry.get("platform") != "blinkit":
                    continue
                pid = entry.get("product_id")
                url = entry.get("product_url")
                ic = entry.get("item_code")
                if not pid or not ic or ic in seen_ics:
                    continue
                seen_ics.add(ic)
                if not url or not url.startswith("http"):
                    url = f"https://blinkit.com/prn/x/prid/{pid}"
                aname = entry.get("platform_name") or entry.get("am_name") or ""
                urls_to_scrape.append((ic, url, pid, aname))
            source_name = f"product_mapping.json ({len(seen_ics)} unique items)"
        else:
            print(f"[pdp] ERROR: no Anakin file and no product_mapping.json for {pincode}", file=sys.stderr)
            sys.exit(1)

    print(f"[pdp] Loaded {len(urls_to_scrape)} URLs from {source_name} (skipped {skipped_oos} OOS)", flush=True)
    print(f"[pdp] Scraping with {num_tabs} parallel tabs", flush=True)

    start = datetime.now()
    pw = browser = None
    try:
        pw, browser, context, pages = await init_blinkit_browser(pincode, num_tabs)

        # Load queue
        queue: asyncio.Queue = asyncio.Queue()
        for item in urls_to_scrape:
            queue.put_nowait(item)

        results: list = []
        progress: list = [0]

        workers = [
            worker(i, pages[i], queue, results, progress, len(urls_to_scrape),
                   pincode, source_name, start)
            for i in range(num_tabs)
        ]
        await asyncio.gather(*workers)
    finally:
        try:
            if browser:
                await browser.close()
            if pw:
                await pw.stop()
        except Exception:
            pass

    duration = (datetime.now() - start).total_seconds()
    ok = sum(1 for r in results if r.get("status") == "ok")
    err = sum(1 for r in results if r.get("status") == "error")
    no_price = sum(1 for r in results if r.get("status") == "no_price")
    not_avail = sum(1 for r in results if r.get("status") == "not_available")
    print(f"\n[pdp] Pass 1 done in {duration:.0f}s — {ok} OK, {no_price} no-price, {not_avail} not-available, {err} errors", flush=True)

    # ── RETRY PASS: re-scrape failed items with longer wait (single tab, 4s wait) ──
    retry_items = [(r["item_code"], r["blinkit_product_url"], r["blinkit_product_id"],
                     r.get("_anakin_name", ""))
                    for r in results
                    if r.get("status") in ("no_price", "not_available")
                    and r.get("blinkit_product_url", "").startswith("http")]
    if retry_items:
        print(f"\n[pdp] RETRY PASS: {len(retry_items)} failed items with 4s wait...", flush=True)
        try:
            pw2, browser2, context2, pages2 = await init_blinkit_browser(pincode, 1)
            retry_page = pages2[0]
            recovered = 0
            # Build lookup for quick replacement
            result_idx = {r["item_code"]: i for i, r in enumerate(results)}

            for i, (ic, url, pid, aname) in enumerate(retry_items):
                # Override wait time: 4s instead of 2s
                retry_result = await scrape_one_pdp(retry_page, ic, url, pid,
                                                     anakin_name=aname, max_retries=2)
                if retry_result.get("status") == "ok":
                    idx = result_idx.get(ic)
                    if idx is not None:
                        results[idx] = retry_result
                    recovered += 1
                if (i + 1) % 20 == 0:
                    print(f"[pdp] retry {i+1}/{len(retry_items)} — recovered {recovered}", flush=True)

            await browser2.close()
            await pw2.stop()

            ok = sum(1 for r in results if r.get("status") == "ok")
            print(f"[pdp] Retry recovered {recovered} items. Total OK now: {ok}", flush=True)
        except Exception as e:
            print(f"[pdp] Retry pass failed: {e}", flush=True)

    # Save
    out_dir = PROJECT_ROOT / "data" / "sam"
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    out_path = out_dir / f"blinkit_pdp_{pincode}_{ts}.json"
    with open(out_path, "w") as f:
        json.dump({
            "pincode": pincode,
            "source": "anakin_url_seed",
            "anakin_file": source_name,
            "scraped_at": datetime.now().isoformat(),
            "duration_seconds": round(duration, 1),
            "total_urls": len(urls_to_scrape),
            "ok": ok,
            "no_price": no_price,
            "errors": err,
            "products": results,
        }, f, indent=2, default=str)
    print(f"[pdp] Saved to {out_path}", flush=True)


if __name__ == "__main__":
    pincode = sys.argv[1] if len(sys.argv) > 1 else "834002"
    num_tabs = int(sys.argv[2]) if len(sys.argv) > 2 else 5
    asyncio.run(main(pincode, num_tabs))
