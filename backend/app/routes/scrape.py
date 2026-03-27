import asyncio
import json
import time
from pathlib import Path

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse

from app.config import settings
from app.models.product import PlatformResult, Product, ScrapeRequest, ScrapeResponse
from app.scrapers.blinkit_scraper import BlinkitScraper
from app.scrapers.flipkart_minutes_scraper import FlipkartMinutesScraper
from app.scrapers.jiomart_scraper import JioMartScraper
from app.scrapers.zepto_scraper import ZeptoScraper
from app.scrapers.instamart_scraper import InstamartScraper
from app.services.export_service import generate_excel

router = APIRouter()

# In-memory store for last scrape results
_scrape_cache: dict[str, list[Product]] = {}
_results_cache: dict[str, list[dict]] = {}  # platform results without products

# Limit concurrent browser instances to prevent CPU/memory overload
MAX_CONCURRENT_SCRAPERS = 10
_scrape_semaphore = asyncio.Semaphore(MAX_CONCURRENT_SCRAPERS)

SCRAPER_MAP = {
    "blinkit": BlinkitScraper,
    "jiomart": JioMartScraper,
    "flipkart_minutes": FlipkartMinutesScraper,
    "zepto": ZeptoScraper,
    "instamart": InstamartScraper,
}


async def _scrape_platform(platform: str, pincode: str, max_products: int,
                           selected_categories: list[str] | None = None,
                           progress_callback=None) -> PlatformResult:
    scraper_cls = SCRAPER_MAP.get(platform)
    if not scraper_cls:
        return PlatformResult(
            platform=platform,
            pincode=pincode,
            status="failed",
            total_products=0,
            scrape_duration_seconds=0,
            products=[],
            error_message=f"Unknown platform: {platform}",
        )

    # Limit concurrent browsers to prevent CPU/memory overload
    async with _scrape_semaphore:
        start = time.time()
        try:
            scraper = scraper_cls(pincode=pincode, max_products=max_products,
                                  progress_callback=progress_callback,
                                  selected_categories=selected_categories)
            products = await scraper.scrape_all()
            duration = time.time() - start
            return PlatformResult(
                platform=platform,
                pincode=pincode,
                status="success" if products else "partial",
                total_products=len(products),
                scrape_duration_seconds=round(duration, 2),
                products=products,
            )
        except Exception as e:
            duration = time.time() - start
            return PlatformResult(
                platform=platform,
                pincode=pincode,
                status="failed",
                total_products=0,
                scrape_duration_seconds=round(duration, 2),
                products=[],
                error_message=str(e),
            )


@router.post("/scrape", response_model=ScrapeResponse)
async def scrape_products(request: ScrapeRequest):
    start = time.time()

    max_per = min(request.max_products_per_platform, settings.MAX_PRODUCTS_PER_PLATFORM)

    # Scrape all selected platforms x pincodes concurrently
    tasks = [
        _scrape_platform(platform, pincode, max_per,
                         selected_categories=request.categories.get(platform))
        for pincode in request.pincodes
        for platform in request.platforms
    ]
    results = await asyncio.gather(*tasks)

    total_duration = round(time.time() - start, 2)
    total_products = sum(r.total_products for r in results)

    # Cache results per pincode
    all_products = []
    for r in results:
        all_products.extend(r.products)
    cache_key = ",".join(sorted(request.pincodes))
    _scrape_cache[cache_key] = all_products

    return ScrapeResponse(
        pincodes=request.pincodes,
        results=list(results),
        total_products=total_products,
        total_duration_seconds=total_duration,
    )


@router.post("/scrape/stream")
async def scrape_products_stream(request: ScrapeRequest):
    max_per = min(request.max_products_per_platform, settings.MAX_PRODUCTS_PER_PLATFORM)
    queue: asyncio.Queue = asyncio.Queue()

    async def progress_callback(platform: str, pincode: str, product_count: int):
        await queue.put({
            "event": "progress",
            "data": {"platform": platform, "pincode": pincode, "product_count": product_count},
        })

    async def run_scraper(platform: str, pincode: str):
        result = await _scrape_platform(platform, pincode, max_per,
                                        selected_categories=request.categories.get(platform),
                                        progress_callback=progress_callback)
        # Don't send products in SSE — too large for browser to parse
        await queue.put({
            "event": "platform_complete",
            "data": {
                "platform": result.platform,
                "pincode": result.pincode,
                "status": result.status,
                "total_products": result.total_products,
                "scrape_duration_seconds": result.scrape_duration_seconds,
                "error_message": result.error_message,
            },
        })
        return result

    async def event_generator():
        start = time.time()

        # Send started event
        platforms_pincodes = [
            {"platform": p, "pincode": pc}
            for pc in request.pincodes
            for p in request.platforms
        ]
        yield f"event: started\ndata: {json.dumps({'tasks': platforms_pincodes})}\n\n"

        # Launch all scrapers concurrently
        tasks = [
            asyncio.create_task(run_scraper(platform, pincode))
            for pincode in request.pincodes
            for platform in request.platforms
        ]

        completed = 0
        total_tasks = len(tasks)

        while completed < total_tasks:
            try:
                msg = await asyncio.wait_for(queue.get(), timeout=60.0)
                yield f"event: {msg['event']}\ndata: {json.dumps(msg['data'])}\n\n"
                if msg["event"] == "platform_complete":
                    completed += 1
            except asyncio.TimeoutError:
                yield f"event: heartbeat\ndata: {json.dumps({'alive': True})}\n\n"

        # Gather results and cache
        results = await asyncio.gather(*tasks)
        total_duration = round(time.time() - start, 2)
        total_products = sum(r.total_products for r in results)

        all_products = []
        results_summary = []
        for r in results:
            all_products.extend(r.products)
            results_summary.append({
                "platform": r.platform,
                "pincode": r.pincode,
                "status": r.status,
                "total_products": r.total_products,
                "scrape_duration_seconds": r.scrape_duration_seconds,
                "error_message": r.error_message,
            })
        cache_key = ",".join(sorted(request.pincodes))
        _scrape_cache[cache_key] = all_products
        _results_cache[cache_key] = results_summary

        yield f"event: done\ndata: {json.dumps({'total_products': total_products, 'total_duration_seconds': total_duration, 'pincodes': request.pincodes, 'cache_key': cache_key})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.get("/pincodes")
async def get_pincodes():
    pincodes_path = Path(__file__).parent.parent.parent.parent / "data" / "pincodes.json"
    try:
        with open(pincodes_path) as f:
            return json.load(f)
    except FileNotFoundError:
        return {"error": "Pincodes data not found"}


@router.get("/results")
async def get_results(pincodes: str = Query(..., description="Comma-separated pincodes")):
    """Get cached scrape results (summary + products)."""
    pincodes_list = [p.strip() for p in pincodes.split(",")]
    cache_key = ",".join(sorted(pincodes_list))

    products = _scrape_cache.get(cache_key, [])
    results_summary = _results_cache.get(cache_key, [])

    if not products and not results_summary:
        return {"error": "No cached data found"}

    return {
        "pincodes": pincodes_list,
        "results": [
            {
                **r,
                "products": [p.model_dump() for p in products if p.platform == r["platform"] and p.pincode == r["pincode"]],
            }
            for r in results_summary
        ],
        "total_products": len(products),
    }


@router.get("/export/excel")
async def export_excel(
    pincode: str = Query(..., description="Comma-separated pincodes to export data for"),
    platforms: str = Query("", description="Comma-separated platform names to filter"),
):
    pincodes_requested = [p.strip() for p in pincode.split(",")]
    cache_key = ",".join(sorted(pincodes_requested))
    products = _scrape_cache.get(cache_key, [])

    if not products:
        for pc in pincodes_requested:
            products.extend(_scrape_cache.get(pc, []))

    if platforms:
        platform_list = [p.strip() for p in platforms.split(",")]
        products = [p for p in products if p.platform in platform_list]

    if not products:
        return {"error": "No data found. Run a scrape first."}

    pincodes_str = ",".join(pincodes_requested) if len(pincodes_requested) <= 3 else f"{len(pincodes_requested)}_pincodes"
    excel_bytes, filename = generate_excel(products, pincodes_str)

    return StreamingResponse(
        iter([excel_bytes]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/categories/{platform}")
async def get_categories(platform: str):
    scraper_cls = SCRAPER_MAP.get(platform)
    if not scraper_cls:
        return {"error": f"Unknown platform: {platform}"}

    return {"platform": platform, "categories": list(scraper_cls.CATEGORY_MAP.keys())}
