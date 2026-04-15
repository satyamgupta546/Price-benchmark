"""
Stage 1: Direct PDP scraping for JioMart (Firefox-based).

Reads Anakin's cached Jiomart_Product_Url list, visits each PDP in parallel,
scrapes price/stock. Saves output keyed by Apna item_code.

Uses Firefox because JioMart's Akamai CDN blocks Chromium with 403.

Usage:
    cd backend && ./venv/bin/python ../scripts/scrape_jiomart_pdps.py 834002 [num_tabs]
"""
import asyncio
import json
import random
import sys
from datetime import datetime
from pathlib import Path

sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from playwright.async_api import async_playwright  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parent.parent

FIREFOX_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) Gecko/20100101 Firefox/128.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:128.0) Gecko/20100101 Firefox/128.0",
    "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0",
]


def latest_anakin_file(pincode: str) -> Path | None:
    cands = sorted((PROJECT_ROOT / "data" / "anakin").glob(f"jiomart_{pincode}_*.json"))
    return cands[-1] if cands else None


async def init_jiomart_browser(pincode: str, num_tabs: int):
    print(f"[jm-pdp] Init Firefox for pincode {pincode} with {num_tabs} tabs", flush=True)
    pw = await async_playwright().start()
    browser = await pw.firefox.launch(headless=True)
    context = await browser.new_context(
        user_agent=random.choice(FIREFOX_USER_AGENTS),
        viewport={"width": 1366, "height": 768},
        locale="en-IN",
        timezone_id="Asia/Kolkata",
    )
    await context.add_cookies([
        {"name": "pincode", "value": pincode, "domain": ".jiomart.com", "path": "/"},
        {"name": "address_pincode", "value": pincode, "domain": ".jiomart.com", "path": "/"},
    ])

    # Warm-up
    warm = await context.new_page()
    try:
        await warm.goto("https://www.jiomart.com", wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(2)
    except Exception:
        pass
    await warm.close()

    pages = [await context.new_page() for _ in range(num_tabs)]
    return pw, browser, context, pages


def _find_product_in_json(data, target_pid: str, depth: int = 0):
    """Walk JSON tree looking for a product object matching target_pid."""
    if depth > 10:
        return None
    price_keys = ("mrp", "price", "offer_price", "buybox_mrp",
                  "sellingPrice", "final_price", "base_price")
    if isinstance(data, dict):
        this_id = str(
            data.get("code") or data.get("id") or data.get("product_id") or
            data.get("productId") or data.get("sku") or ""
        )
        if this_id == str(target_pid):
            # Check for price keys at this level
            if any(k in data for k in price_keys):
                return data
            # Also check nested subtree (e.g. variants[0].attributes.buybox_mrp)
            for v in data.values():
                if isinstance(v, (dict, list)):
                    subtree_str = json.dumps(v)
                    if any(pk in subtree_str for pk in ("buybox_mrp", "price", "mrp", "selling_price")):
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


def _extract_price_from_jiomart_dict(p: dict) -> tuple[float | None, float | None]:
    """Extract SP and MRP from a JioMart product dict."""
    sp = None
    mrp = None

    # buybox_mrp pipe format: "store|qty|seller||mrp|price||discount|..."
    # Check at top level first, then dig into variants[0].attributes
    bb = p.get("buybox_mrp")
    if bb is None:
        # Google Retail catalog nesting: variants[0].attributes.buybox_mrp
        variants = p.get("variants")
        if isinstance(variants, list) and variants:
            attrs = variants[0] if isinstance(variants[0], dict) else {}
            attrs = attrs.get("attributes", attrs)
            bb = attrs.get("buybox_mrp")
    if isinstance(bb, dict):
        texts = bb.get("text", [])
        if texts:
            parts = str(texts[0]).split("|")
            if len(parts) >= 6:
                try:
                    if parts[4]:
                        mrp = float(parts[4])
                    if parts[5]:
                        sp = float(parts[5])
                except ValueError:
                    pass

    # Standard keys
    if sp is None:
        for k in ("final_price", "selling_price", "sellingPrice", "offer_price", "sp",
                  "current_price", "final_selling_price", "price"):
            v = p.get(k)
            if v and not isinstance(v, (dict, list)):
                try:
                    sp = float(str(v).replace(",", "").replace("₹", "").strip())
                    if sp > 0:
                        break
                except (ValueError, TypeError):
                    pass

    if mrp is None:
        for k in ("mrp", "marked_price", "max_price", "original_price", "strike_price"):
            v = p.get(k)
            if v and not isinstance(v, (dict, list)):
                try:
                    mrp = float(str(v).replace(",", "").replace("₹", "").strip())
                    if mrp > 0:
                        break
                except (ValueError, TypeError):
                    pass

    # If MRP not found but SP exists, MRP = SP (no discount)
    if sp and not mrp:
        mrp = sp
    return sp, mrp


async def scrape_one_jiomart_pdp(page, item_code: str, url: str, jm_pid: str, max_retries: int = 3) -> dict:
    out = {
        "item_code": item_code,
        "jiomart_product_id": jm_pid,
        "jiomart_product_url": url,
        "scraped_at": datetime.now(tz=None).isoformat(),
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
            if not any(kw in low for kw in ("mrp", "price", "product", "buybox")):
                return
            try:
                captured.append(json.loads(body))
            except json.JSONDecodeError:
                pass
        except Exception:
            pass

    page.on("response", on_response)
    try:
        last_error = None
        for attempt in range(max_retries):
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=25000)
                last_error = None
                break
            except Exception as e:
                last_error = str(e)
                transient = any(k in last_error for k in (
                    "ERR_INTERNET_DISCONNECTED", "ERR_NETWORK_CHANGED",
                    "ERR_NAME_NOT_RESOLVED", "ERR_CONNECTION_RESET",
                    "ERR_TIMED_OUT", "ERR_CONNECTION_REFUSED",
                    "NS_ERROR_NET", "Timeout",
                ))
                if transient and attempt < max_retries - 1:
                    await asyncio.sleep(5 * (2 ** attempt))
                    continue
                break
        if last_error is not None:
            out["status"] = "error"
            out["error"] = f"goto: {last_error[:150]}"
            return out

        await asyncio.sleep(2.5)  # Firefox + Akamai needs longer settle

        # Try: Find product in captured JSON by matching product_id
        product_dict = None
        jm_pid_clean = jm_pid.strip()
        for payload in captured:
            found = _find_product_in_json(payload, jm_pid_clean)
            if found:
                product_dict = found
                break

        sp = mrp = None
        name = None
        unit = None
        in_stock = True

        if product_dict:
            sp, mrp = _extract_price_from_jiomart_dict(product_dict)
            # Google Retail format: "name" = catalog path (projects/...),
            # actual title in variants[0].title or product.title
            # Check variant-level title first (most specific), then product-level
            variants = product_dict.get("variants")
            if isinstance(variants, list) and variants and isinstance(variants[0], dict):
                vt = variants[0].get("title")
                if vt and isinstance(vt, str) and not vt.startswith("projects/"):
                    name = vt.strip()
            if not name:
                for k in ("title", "product_name", "display_name", "name"):
                    v = product_dict.get(k)
                    if v and isinstance(v, str):
                        candidate = v.strip()
                        # Skip Google Retail catalog paths
                        if candidate.startswith("projects/"):
                            continue
                        name = candidate
                        break

        # DOM fallback — also triggered when name is a Google Retail catalog path
        _name_bad = not name or (isinstance(name, str) and name.startswith("projects/"))
        if sp is None or _name_bad:
            dom_data = await page.evaluate("""() => {
                let name = '';
                let sp_val = null, mrp_val = null;

                // ─── TRY 1: JSON-LD structured data (most reliable) ───
                const ldScripts = document.querySelectorAll('script[type="application/ld+json"]');
                for (const s of ldScripts) {
                    try {
                        const data = JSON.parse(s.textContent || '{}');
                        const items = Array.isArray(data) ? data : [data];
                        for (const item of items) {
                            // Walk nested graph
                            const stack = [item];
                            while (stack.length) {
                                const cur = stack.pop();
                                if (!cur || typeof cur !== 'object') continue;
                                if (cur['@type'] === 'Product' || cur['@type'] === 'ProductGroup') {
                                    if (!name && cur.name) name = String(cur.name).trim();
                                    const offers = cur.offers || {};
                                    const offerList = Array.isArray(offers) ? offers : [offers];
                                    for (const off of offerList) {
                                        const p = parseFloat(off.price || off.lowPrice);
                                        if (p > 0 && !sp_val) sp_val = p;
                                        const hp = parseFloat(off.highPrice);
                                        if (hp > 0 && !mrp_val) mrp_val = hp;
                                    }
                                }
                                if (cur['@graph']) stack.push(...cur['@graph']);
                                for (const v of Object.values(cur)) {
                                    if (v && typeof v === 'object') stack.push(v);
                                }
                            }
                        }
                    } catch (e) {}
                }

                // ─── TRY 2: og/product meta tags ───
                if (!name) {
                    const og = document.querySelector('meta[property="og:title"]');
                    if (og) name = (og.getAttribute('content') || '').trim();
                }
                if (!sp_val) {
                    const metaP = document.querySelector('meta[property="product:price:amount"], meta[property="og:price:amount"]');
                    if (metaP) {
                        const v = parseFloat((metaP.getAttribute('content') || '').replace(',', ''));
                        if (v > 0) sp_val = v;
                    }
                }

                // ─── TRY 3: Name — find h1 with meaningful product text ───
                if (!name) {
                    const h1s = document.querySelectorAll('h1');
                    for (const h of h1s) {
                        const t = (h.innerText || '').trim();
                        // Skip generic headings like "Questions & Answers", "Related Products"
                        if (t.length < 5) continue;
                        if (/questions|answer|reviews|related|similar|about/i.test(t)) continue;
                        if (t.length < 150) {
                            name = t;
                            break;
                        }
                    }
                }

                // ─── TRY 4: DISABLED — body text ₹ regex picks up carousel/bundle prices ───
                // no_price is better than wrong price

                // Stock
                const bodyLower = (document.body.innerText || '').toLowerCase();
                let in_stock = true;
                if (bodyLower.includes('out of stock') ||
                    bodyLower.includes('notify me') ||
                    bodyLower.includes('sold out') ||
                    bodyLower.includes('currently unavailable')) {
                    in_stock = false;
                }

                return { name, sp_val, mrp_val, in_stock };
            }""")

            if not name or (isinstance(name, str) and name.startswith("projects/")):
                name = dom_data.get("name") or None
            if sp is None:
                sp = dom_data.get("sp_val")
            if mrp is None:
                mrp = dom_data.get("mrp_val")
            in_stock = dom_data.get("in_stock", in_stock)

        # ── Raw HTML regex DISABLED — picks up prices from carousels/script tags ──
        # no_price is better than wrong price

        # Final MRP fallback: if SP found but MRP still missing, assume MRP = SP
        if sp and not mrp:
            mrp = sp

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
    out_dir = PROJECT_ROOT / "data" / "sam"
    out_dir.mkdir(parents=True, exist_ok=True)
    suffix = "_partial" if partial else ""
    out_path = out_dir / f"jiomart_pdp_{pincode}_latest{suffix}.json"
    ok = sum(1 for r in results if r.get("status") == "ok")
    no_price = sum(1 for r in results if r.get("status") == "no_price")
    errs = sum(1 for r in results if r.get("status") == "error")
    with open(out_path, "w") as f:
        json.dump({
            "pincode": pincode,
            "source": "anakin_url_seed",
            "platform": "jiomart",
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
            item_code, url, jm_pid = queue.get_nowait()
        except asyncio.QueueEmpty:
            break
        result = await scrape_one_jiomart_pdp(page, item_code, url, jm_pid)
        results.append(result)
        progress_counter[0] += 1
        if progress_counter[0] % 20 == 0:
            ok = sum(1 for r in results if r.get("status") == "ok")
            print(f"[jm-pdp] [w{worker_id}] {progress_counter[0]}/{total} — {ok} with price", flush=True)
        if progress_counter[0] % 200 == 0:
            duration = (datetime.now() - start_time).total_seconds()
            save_snapshot(pincode, results, anakin_file, duration, partial=True)


async def main(pincode: str, num_tabs: int = 2):
    ana_path = latest_anakin_file(pincode)
    if not ana_path:
        print(f"[jm-pdp] ERROR: no Anakin Jiomart file for {pincode}", file=sys.stderr)
        sys.exit(1)

    ana = json.load(open(ana_path))
    urls_to_scrape = []
    for rec in ana["records"]:
        pid = (rec.get("Jiomart_Product_Id") or "").strip()
        url = (rec.get("Jiomart_Product_Url") or "").strip()
        ic = (rec.get("Item_Code") or "").strip()
        if pid and pid != "NA" and url and url.startswith("http"):
            urls_to_scrape.append((ic, url, pid))

    print(f"[jm-pdp] Loaded {len(urls_to_scrape)} mapped URLs from {ana_path.name}", flush=True)
    print(f"[jm-pdp] Scraping with {num_tabs} parallel tabs (Firefox)", flush=True)

    start = datetime.now()
    pw = browser = None
    try:
        pw, browser, context, pages = await init_jiomart_browser(pincode, num_tabs)

        queue: asyncio.Queue = asyncio.Queue()
        for item in urls_to_scrape:
            queue.put_nowait(item)

        results: list = []
        progress: list = [0]

        workers = [
            worker(i, pages[i], queue, results, progress, len(urls_to_scrape),
                   pincode, ana_path.name, start)
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
    print(f"\n[jm-pdp] DONE in {duration:.0f}s — {ok} OK, {no_price} no-price, {err} errors (of {len(results)})",
          flush=True)

    out_dir = PROJECT_ROOT / "data" / "sam"
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    out_path = out_dir / f"jiomart_pdp_{pincode}_{ts}.json"
    with open(out_path, "w") as f:
        json.dump({
            "pincode": pincode,
            "platform": "jiomart",
            "source": "anakin_url_seed",
            "anakin_file": ana_path.name,
            "scraped_at": datetime.now().isoformat(),
            "duration_seconds": round(duration, 1),
            "total_urls": len(urls_to_scrape),
            "ok": ok,
            "no_price": no_price,
            "errors": err,
            "products": results,
        }, f, indent=2, default=str)
    print(f"[jm-pdp] Saved to {out_path}", flush=True)


if __name__ == "__main__":
    pincode = sys.argv[1] if len(sys.argv) > 1 else "834002"
    num_tabs = int(sys.argv[2]) if len(sys.argv) > 2 else 2
    asyncio.run(main(pincode, num_tabs))
