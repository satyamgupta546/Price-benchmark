"""
Jiomart Search-based matching: For failed PDP products, search by name
on Jiomart and match via the /trex/search API (which reliably returns prices,
unlike the PDP page which doesn't render in headless Firefox).

Usage:
    cd backend && ./venv/bin/python ../scripts/jiomart_search_match.py 834002
"""
import asyncio
import json
import re
import sys
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path

sys.stdout.reconfigure(line_buffering=True)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.scrapers.jiomart_scraper import JioMartScraper  # noqa

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def normalize(s: str) -> str:
    if not s:
        return ""
    s = s.lower()
    s = re.sub(r"[^\w\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


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


async def search_one_product(scraper, search_term: str, target_name: str) -> dict | None:
    """Search Jiomart for a product, return best match with price."""
    scraper.products.clear()
    scraper._captured_responses.clear()
    scraper._processed_urls.clear()
    scraper._seen_ids.clear()

    try:
        from urllib.parse import quote
        url = f"https://www.jiomart.com/search/{quote(search_term)}"
        await scraper.page.goto(url, wait_until="domcontentloaded", timeout=20000)
        await asyncio.sleep(2)

        # Process /trex/search API responses
        scraper._process_responses()

        # Also try DOM extraction
        await scraper._extract_products_from_dom()

        if not scraper.products:
            return None

        # Find best name match
        target_norm = normalize(target_name)
        best_score = 0.0
        best_product = None
        for p in scraper.products:
            score = SequenceMatcher(None, target_norm, normalize(p.product_name)).ratio()
            if score > best_score:
                best_score = score
                best_product = p

        if best_product and best_score >= 0.4:
            return {
                "product_name": best_product.product_name,
                "brand": best_product.brand,
                "price": best_product.price,
                "mrp": best_product.mrp,
                "product_id": best_product.product_id,
                "match_score": round(best_score, 3),
            }
    except Exception as e:
        print(f"  search error: {e}", flush=True)
    return None


async def main(pincode: str):
    ana_path = latest_file("anakin", f"jiomart_{pincode}_*.json")
    if not ana_path:
        print(f"[jm-search] ERROR: no Anakin Jiomart file for {pincode}", file=sys.stderr)
        sys.exit(1)

    ana = json.load(open(ana_path))

    # Find unmatched: usable non-loose Jiomart products not yet matched by any stage
    usable = {r.get("Item_Code") for r in ana["records"]
              if r.get("Jiomart_Selling_Price") not in (None, "", "NA", "nan")
              and "loose" not in (r.get("Item_Name") or "").lower()}

    matched = set()
    for pat in ["jiomart_pdp_*_compare.json", "jiomart_cascade_*.json", "jiomart_stage3_*.json"]:
        for f in sorted((PROJECT_ROOT / "data" / "comparisons").glob(pat)):
            d = json.load(open(f))
            for m in d.get("matches", []):
                if m.get("match_status") == "ok":
                    matched.add(m.get("item_code"))
            for m in d.get("new_mappings", []):
                matched.add(m.get("item_code"))

    unmatched_codes = usable - matched
    unmatched_skus = [r for r in ana["records"] if r.get("Item_Code") in unmatched_codes]

    print(f"[jm-search] Anakin: {ana_path.name}")
    print(f"[jm-search] Usable non-loose: {len(usable)}")
    print(f"[jm-search] Already matched: {len(matched & usable)}")
    print(f"[jm-search] Unmatched (search input): {len(unmatched_skus)}")
    print()

    # Init Jiomart scraper (Firefox)
    scraper = JioMartScraper(pincode=pincode, max_products=100)
    await scraper.init_browser()
    await scraper.context.add_cookies([
        {"name": "pincode", "value": pincode, "domain": ".jiomart.com", "path": "/"},
        {"name": "address_pincode", "value": pincode, "domain": ".jiomart.com", "path": "/"},
    ])
    await scraper.page.goto("https://www.jiomart.com", wait_until="domcontentloaded", timeout=30000)
    await asyncio.sleep(2)

    new_matches = []
    no_result = 0
    errors = 0

    try:
        for i, sku in enumerate(unmatched_skus):
            # Search by Jiomart_Item_Name (closest to what Jiomart shows)
            jm_name = clean_str(sku.get("Jiomart_Item_Name"))
            ana_name = clean_str(sku.get("Item_Name"))
            search_term = jm_name or ana_name
            if not search_term:
                no_result += 1
                continue

            result = await search_one_product(scraper, search_term, search_term)

            if result:
                ana_sp = None
                try:
                    ana_sp = float(str(sku.get("Jiomart_Selling_Price", "")).replace(",", ""))
                except (ValueError, TypeError):
                    pass

                price_diff = None
                if ana_sp and result["price"]:
                    price_diff = abs(result["price"] - ana_sp) / ana_sp * 100

                new_matches.append({
                    "item_code": sku.get("Item_Code"),
                    "anakin_name": ana_name,
                    "anakin_jiomart_name": jm_name,
                    "anakin_sp": ana_sp,
                    "sam_product_name": result["product_name"],
                    "sam_brand": result["brand"],
                    "sam_price": result["price"],
                    "sam_mrp": result["mrp"],
                    "match_score": result["match_score"],
                    "price_diff_pct": round(price_diff, 1) if price_diff is not None else None,
                    "match_method": "jiomart_search_api",
                })
            else:
                no_result += 1

            if (i + 1) % 20 == 0:
                print(f"  [{i+1}/{len(unmatched_skus)}] {len(new_matches)} matched, {no_result} no-result", flush=True)

    finally:
        await scraper.close()

    print()
    print("=" * 60)
    print(f"JIOMART SEARCH MATCH (pincode {pincode})")
    print("=" * 60)
    print(f"Input:          {len(unmatched_skus)}")
    print(f"New matches:    {len(new_matches)}")
    print(f"No result:      {no_result}")
    print()

    if new_matches:
        # Price accuracy
        priced = [m for m in new_matches if m.get("price_diff_pct") is not None]
        in5 = sum(1 for m in priced if m["price_diff_pct"] <= 5)
        in10 = sum(1 for m in priced if m["price_diff_pct"] <= 10)
        if priced:
            print(f"Price accuracy (vs Anakin SP):")
            print(f"  ±5%:  {in5}/{len(priced)} = {in5*100/len(priced):.1f}%")
            print(f"  ±10%: {in10}/{len(priced)} = {in10*100/len(priced):.1f}%")
            print()

        print("Sample matches (top 5 by score):")
        for m in sorted(new_matches, key=lambda x: -x["match_score"])[:5]:
            diff = f" | diff={m['price_diff_pct']}%" if m.get("price_diff_pct") is not None else ""
            print(f"  [{m['match_score']:.2f}] {m['anakin_jiomart_name'][:40]}")
            print(f"       → {m['sam_product_name'][:40]} | ₹{m['sam_price']}{diff}")

    # Save
    out_dir = PROJECT_ROOT / "data" / "comparisons"
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    out_path = out_dir / f"jiomart_search_match_{pincode}_{ts}.json"
    with open(out_path, "w") as f:
        json.dump({
            "pincode": pincode,
            "compared_at": datetime.now().isoformat(),
            "metrics": {
                "input": len(unmatched_skus),
                "new_matches": len(new_matches),
                "no_result": no_result,
            },
            "new_mappings": new_matches,
        }, f, indent=2, default=str)
    print(f"\nReport: {out_path}")


if __name__ == "__main__":
    pincode = sys.argv[1] if len(sys.argv) > 1 else "834002"
    asyncio.run(main(pincode))
