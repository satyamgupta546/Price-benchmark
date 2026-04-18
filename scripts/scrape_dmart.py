"""
DMart Ready price scraper — pure API, no browser.

Usage:
    python3 scripts/scrape_dmart.py 492001
"""
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.scrapers.dmart_scraper import DMartScraper, DMART_STORE_IDS

PROJECT_ROOT = Path(__file__).resolve().parent.parent


async def main(pincode: str):
    if pincode not in DMART_STORE_IDS:
        print(f"[dmart] DMart not available for pincode {pincode}")
        return

    scraper = DMartScraper(pincode=pincode, max_products=10000)
    products = await scraper.scrape_all()

    if not products:
        print("[dmart] No products found")
        return

    # Save output
    out_dir = PROJECT_ROOT / "data" / "sam"
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    out_path = out_dir / f"dmart_{pincode}_{ts}.json"

    out_data = {
        "pincode": pincode,
        "platform": "dmart",
        "store_id": scraper.store_id,
        "scraped_at": datetime.now().isoformat(),
        "total_products": len(products),
        "in_stock": sum(1 for p in products if p.in_stock),
        "out_of_stock": sum(1 for p in products if not p.in_stock),
        "products": [
            {
                "product_name": p.product_name,
                "brand": p.brand,
                "price": p.price,
                "mrp": p.mrp,
                "unit": p.unit,
                "category": p.category,
                "sub_category": p.sub_category,
                "in_stock": p.in_stock,
                "product_id": p.product_id,
                "product_url": p.product_url,
                "image_url": p.image_url,
                "barcode": getattr(p, "barcode", ""),
            }
            for p in products
        ],
    }

    with open(out_path, "w") as f:
        json.dump(out_data, f, indent=2, default=str)

    print(f"[dmart] Saved {len(products)} products to {out_path.name}")


if __name__ == "__main__":
    pincode = sys.argv[1] if len(sys.argv) > 1 else "492001"
    asyncio.run(main(pincode))
