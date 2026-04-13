"""
Standalone runner — runs SAM's Blinkit scraper for a single pincode and dumps
the result to data/sam/blinkit_<pincode>_<timestamp>.json.

Usage:
    cd backend && ./venv/bin/python ../scripts/run_blinkit_scrape.py 834002
"""
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

# Force line-buffered stdout/stderr so progress logs show up in real time
# (BlinkitScraper uses plain print() without flush=True)
sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

# Make `app.*` importable when run from project root or scripts/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.scrapers.blinkit_scraper import BlinkitScraper  # noqa: E402


def save_products(pincode: str, products: list, duration: float, partial: bool = False) -> Path:
    """Save scraped products to JSON. Used both on normal completion and on interrupt."""
    out_dir = Path(__file__).resolve().parent.parent / "data" / "sam"
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    suffix = "_partial" if partial else ""
    out_path = out_dir / f"blinkit_{pincode}_{ts}{suffix}.json"

    serializable = [
        {
            "product_name": p.product_name,
            "brand": p.brand,
            "product_id": p.product_id,
            "product_url": p.product_url,
            "price": p.price,
            "mrp": p.mrp,
            "unit": p.unit,
            "category": p.category,
            "platform": p.platform,
            "pincode": p.pincode,
            "in_stock": p.in_stock,
            "scraped_at": p.scraped_at,
            "image_url": p.image_url,
        }
        for p in products
    ]

    with open(out_path, "w") as f:
        json.dump(
            {
                "pincode": pincode,
                "scraped_at": datetime.now().isoformat(),
                "duration_seconds": round(duration, 1),
                "total_products": len(products),
                "partial": partial,
                "products": serializable,
            },
            f,
            indent=2,
            default=str,
        )
    return out_path


async def main(pincode: str, max_products: int = 10000):
    print(f"[runner] Starting Blinkit scrape for pincode {pincode}, max={max_products}", flush=True)
    start = datetime.now()

    scraper = BlinkitScraper(pincode=pincode, max_products=max_products)
    products: list = []
    interrupted = False
    try:
        products = await scraper.scrape_all()
    except (KeyboardInterrupt, asyncio.CancelledError):
        interrupted = True
        # Recover products from scraper state
        products = list(scraper.products)
        print(f"[runner] Interrupted — recovered {len(products)} products from scraper state", flush=True)
    finally:
        try:
            await scraper.close()
        except Exception:
            pass

    duration = (datetime.now() - start).total_seconds()
    print(f"[runner] Scrape done in {duration:.1f}s — {len(products)} products{' (PARTIAL)' if interrupted else ''}", flush=True)

    out_path = save_products(pincode, products, duration, partial=interrupted)
    print(f"[runner] Saved to {out_path}", flush=True)
    print(f"[runner] DONE", flush=True)


if __name__ == "__main__":
    pincode = sys.argv[1] if len(sys.argv) > 1 else "834002"
    max_products = int(sys.argv[2]) if len(sys.argv) > 2 else 10000
    asyncio.run(main(pincode, max_products))
