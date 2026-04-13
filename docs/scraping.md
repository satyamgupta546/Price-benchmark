# Scraping — Per-Platform Notes

## What it does

SAM runs Playwright-based scrapers for 5 quick-commerce platforms to collect product data (name, brand, price, MRP, unit, stock, image) for a given pincode. Output is a list of `Product` Pydantic models that downstream services (export, compare) consume.

## Architecture

```
BaseScraper (abstract)              ← shared logic in app/scrapers/base_scraper.py
├── BlinkitScraper                  ← Chromium + localStorage location
├── ZeptoScraper                    ← Chromium + cookies + UI fallback
├── InstamartScraper                ← Chromium + Swiggy WAF bypass
├── JioMartScraper                  ← Firefox (Akamai blocks Chromium)
└── FlipkartMinutesScraper          ← Chromium + pincode form
```

All inherit from `BaseScraper` which provides:
- Browser init (`init_browser`)
- Response interception via `page.on("response", ...)`
- Generic JSON walker that finds product-shaped objects
- Multi-key field parser (handles different platform schemas)
- Network-settle waiter
- Aggressive scroll loop for lazy loading
- BFS category crawl with early-exit on consecutive empty pages
- Search-based gap-fill phase

## 3-phase scrape flow (per platform)

```
PHASE 1: Deep Category Crawl (BFS)
─────────────────────────────────────
1. Load homepage → set location → reload
2. Seed queue with category URLs from CATEGORY_MAP (per platform)
3. For each URL in queue:
    a. Visit + scroll aggressively (5–12 times) for lazy load
    b. Wait for network idle
    c. Process all captured JSON responses → extract products
    d. Discover new sub-category links on the page
    e. Enqueue new links (with CID filtering when category-restricted)
4. Stop on: queue empty, max products hit, 15 consecutive empty pages,
   or 300-page safety cap

PHASE 2: Search-Based Gap Fill
─────────────────────────────────────
For each search term in SEARCH_TERMS_BY_CATEGORY:
    a. Visit search URL
    b. Same scroll + capture + extract
    c. Stop after 10 consecutive empty searches

PHASE 3: DOM Fallback (Blinkit only)
─────────────────────────────────────
JavaScript walks all <div> elements looking for product cards:
- Has <img> with platform image domain
- Contains ₹ price
- 2–15 children, 20–400 chars text length
Extract: name (first text line), prices (₹ regex), image URL
```

## Per-platform quirks

### Blinkit
- **Location**: `localStorage["location"] = {coords: {lat, lon, locality, cityName, ...}}`
- **Cookies**: `__pincode`, `gr_1_lat`, **`gr_1_lon`** (NOT `gr_1_lng`! — common gotcha)
- **Crawl**: BFS over `/cn/...` paths with CID-based filtering to avoid drifting between categories
- **DOM fallback**: searches `img[src*="grofers.com"]` for product cards (catches products missed by API interception)
- **CATEGORY_MAP**: 21 top-level categories (Paan Corner, Dairy, Fruits, Snacks, etc.)

### Zepto
- **Location**: cookies + localStorage + UI fallback (clicks pincode picker if needed)
- **Browser**: Chromium
- **Special**: parses RSC (React Server Components) streaming JSON from Next.js

### Instamart
- **Location**: Swiggy `userLocation` cookie + Swiggy address API
- **WAF bypass**: must visit `swiggy.com` first to set base cookies before navigating to `/instamart`
- **Parser**: `_parse_swiggy_widgets()` recursive walker for Swiggy widget JSON format

### JioMart
- **Browser**: **Firefox** (Chromium → 403 from Akamai CDN)
- **API**: `/trex/search` returns Google Retail catalog format (not standard product JSON)
- **Parse**: `product.variants[0].attributes.buybox_mrp.text[0]` → pipe-delimited:
  `"store|qty|seller||mrp|price||..."`
- **Categories**: discovered from `/c/groceries/2` (URLs change frequently — discover at runtime)

### Flipkart Minutes
- **Pincode form**: must use `press_sequentially()` (NOT `fill()` — React onChange ignores fill)
- **DOM extraction**: server-rendered, no JSON API → parse `img[src*="rukminim"]` cards
- **Filter**: aggressive cleanup of junk product names (DOM has many noise rows)

## Files involved

| File | Lines | Role |
|---|---|---|
| `backend/app/scrapers/base_scraper.py` | 521 | Shared logic + generic parser |
| `backend/app/scrapers/blinkit_scraper.py` | 386 | Blinkit-specific |
| `backend/app/scrapers/zepto_scraper.py` | 460 | Zepto-specific |
| `backend/app/scrapers/instamart_scraper.py` | 468 | Instamart-specific |
| `backend/app/scrapers/jiomart_scraper.py` | 377 | JioMart-specific |
| `backend/app/scrapers/flipkart_minutes_scraper.py` | 371 | Flipkart Minutes |
| `scripts/run_blinkit_scrape.py` | — | Standalone runner for one platform |

## Inputs

```python
BlinkitScraper(
    pincode="834002",            # mandatory — sets browser location
    max_products=10000,          # cap to prevent runaway
    selected_categories=None,    # None = all; or list of category names from CATEGORY_MAP
    progress_callback=None,      # optional async callback for live SSE updates
)
```

## Outputs

List of `Product` Pydantic models:

```python
Product(
    product_name: str,
    brand: str,
    price: float,           # selling price
    mrp: float | None,
    unit: str | None,       # e.g., "500g", "1 L"
    category: str | None,
    sub_category: str | None,
    platform: str,          # "blinkit" | "zepto" | ...
    pincode: str,
    in_stock: bool = True,
    scraped_at: str,        # ISO timestamp UTC
    image_url: str | None,
)
```

## Performance

| Platform | Typical scrape time (one pincode, all categories) | Typical product count |
|---|---|---|
| Blinkit | 12-20 min | 3,000-5,000 |
| Zepto | 10-15 min | 2,500-4,000 |
| Instamart | 15-20 min | 3,000-4,500 |
| JioMart | 8-12 min | 2,000-3,500 |
| Flipkart Minutes | 10-15 min | 1,500-3,000 |

Run-in-parallel via `asyncio.gather()` — 5 platforms simultaneously = ~20 min wall-clock instead of 70 min sequential.

## Known limitations

1. **Output buffering**: scrapers use plain `print()` without `flush=True` — when run via subprocess with stdout redirected, progress logs appear only at the end. Workaround: use `python -u` or `sys.stdout.reconfigure(line_buffering=True)` in the runner.
2. **Pincode coords are approximate** — coords are derived from a 2-digit pincode prefix in `PINCODE_COORDS` dict. May land in wrong neighborhood for big cities.
3. **`unit` is a single string** — not parsed into `unit_value` (numeric) + `unit` (g/ml). Downstream comparison has to re-parse.
4. **No deduplication across pincodes** — running multiple pincodes produces overlapping products.
5. **Browser leak**: if scrape errors out before `close()`, browser processes can be orphaned. Always wrap in try/finally.

## Next improvements

- [ ] `flush=True` on all scraper print statements (or migrate to `logging`)
- [ ] Parse `unit` into numeric `unit_value` + `unit_text`
- [ ] Add concurrent multi-pincode mode (one browser per pincode)
- [ ] Cache discovered category URLs (avoid re-discovering)
- [ ] Add health checks (browser still alive? location set correctly?)
- [ ] Retry on transient failures
