# Scraping Techniques Reference Guide

Complete reference for all platform scrapers — techniques, APIs, gotchas. Use this when building scrapers for new platforms.

---

## General: BaseScraper (base_scraper.py)

### Browser Init
- Default: **Chromium** (headless)
- Anti-detection: `navigator.webdriver = undefined`, `window.chrome = {runtime: {}}`
- Random User-Agent (3 Chrome UAs), viewport 1366x768, locale `en-IN`, timezone `Asia/Kolkata`
- Optional proxy support via `config/proxies.json`

### Pincode → Coordinates
- `get_coords(pincode)` maps first 2 digits to (lat, lng) — 85 entries covering all Indian zones
- Default fallback: Delhi (28.6139, 77.2090)

### Response Interception Pattern
```python
page.on("response", self._on_response)
```
- Filters: `content-type: json`, status 200, body > 100 chars
- Keywords: `"product"`, `"price"`, `"mrp"`, `"name"`, `"selling"`, `"inventory"`
- Stored in `self._captured_responses`

### Generic Product JSON Parsing
- Recursive DFS (max depth 8) over any JSON tree
- Product = dict with BOTH name key + price key
- **Name keys**: `name`, `product_name`, `title`, `display_name`, `productName`
- **Price keys**: `price`, `mrp`, `selling_price`, `offer_price`, `sp`, `sellingPrice`, `finalPrice`
- **SP keys**: `price`, `selling_price`, `offer_price`, `sp`, `sellingPrice`, `finalPrice`, `salePrice`
- **MRP keys**: `mrp`, `marked_price`, `original_price`, `maxPrice`, `max_price`
- **Brand keys**: `brand`, `brand_name`, `brandName`, `manufacturer` (fallback: first word of name)
- **Unit keys**: `unit`, `weight`, `quantity`, `pack_size`, `packSize`, `unitOfMeasure`
- **Barcode keys**: `barcode`, `ean`, `upc`, `gtin`, `ean13`, `bar_code`, `ean_code`, `product_barcode`
- **ID keys**: `id`, `product_id`, `productId`, `prid`, `pid`, `sku`, `slug`
- Price > 50,000 → divide by 100 (paise → rupees heuristic)

### HTML Fallback
- `<script id="__NEXT_DATA__">` (Next.js SSR payload)
- All `<script>` tags with JSON-like content containing product/price keywords

### Scrolling
- Default 5 scrolls, 0.7s delay
- Early exit after 2 consecutive idle scrolls (no new responses + no height change)

### BFS Category Crawl
- Visit category URLs, scroll, collect
- Early exit after N consecutive empty categories (default 5)

### Search
- Iterate filtered search terms, visit search URL, scroll, collect
- Early exit after 10 consecutive empty searches
- HTML fallback if total < 5 products

### Deduplication
- `_seen_ids` set by product ID
- `_processed_urls` set by API response URL

---

## Blinkit

### Browser: Chromium

### Location Setting (CRITICAL — order matters)
1. Load homepage first (establish `blinkit.com` origin for localStorage)
2. **localStorage key `location`**: `{"coords": {"lat": X, "lon": Y, "locality": "...", "cityName": "..."}}`
3. **Cookies** on `.blinkit.com`:
   - `__pincode` = pincode
   - `gr_1_lat` = latitude
   - `gr_1_lon` = longitude (**NOT `gr_1_lng`!**)
4. Reload page

Without localStorage, Blinkit defaults to Gurugram regardless of cookies.

### Product Extraction
| Method | Details |
|--------|---------|
| API interception | JSON responses with product keywords. Product found by `product_id`/`prid` match |
| DOM extraction | Leaf `<div>` with `img[src*="grofers.com"]` or `img[src*="blinkit"]` + `₹` prices |

### PDP Price Extraction (4-level cascade)
1. **API response** → `_find_product_in_json(data, product_id)` → `offer_price`/`selling_price`/`sp` + nested `price` dict
2. **DOM** → `meta[property="product:price:amount"]` + `₹` elements within 800px of h1
3. **JSON-LD** → `<script type="application/ld+json">` → `@type: Product` → `offers.price`
4. **Raw HTML regex** → `"price":123` and `₹X` patterns, frequency-based selection

### Homepage Redirect Detection
If `page.url` is just `blinkit.com/` after goto → product not available → status `not_available`

### Category URLs
- Pattern: `/cn/<slug>/cid/<category_id>/<subcategory_id>`
- CID-based filtering when `selected_categories` set
- 20 categories, multiple subcategory paths each

### Pagination: Infinite scroll (no `?page=` parameter)

### Gotchas
- `visibility` API call reveals which city scraper is targeting
- Sidebar links share CIDs across unrelated categories
- Images on `grofers.com` (old domain) or `blinkit.com`

---

## Jiomart

### Browser: Firefox (Chromium gets 403 from Akamai CDN)

### Location Setting
- **Cookies** on `.jiomart.com`: `pincode`, `address_pincode`
- **UI fallback**: Click "Select Location Manually" → fill pincode → select suggestion

### Product Extraction
| Method | Details |
|--------|---------|
| `/trex/search` API | Google Retail Catalog format — primary source |
| DOM extraction | `[class*="plp_product"]`, `[class*="ProductCard"]` — grocery pages only |

### `/trex/search` Google Retail Format
```
response.results[].product.variants[0].attributes.buybox_mrp.text[0]
```
Pipe-delimited: `"store|qty|seller||mrp|price||discount|disc_pct||rank|"`
- `parts[4]` = MRP, `parts[5]` = Selling Price
- Title: `variants[0].title` or `product.title`
- Brand: `variants[0].brands[0]`
- Category: `product.categories[]` → `"Category > Groceries > ... > Basmati Rice"` → last segment
- Filter: only keep items with "Groceries" in categories

### PDP Price Extraction (2-level)
1. **API** → `_find_product_in_json(data, code/id)` → `buybox_mrp` pipe format (top-level + nested `variants[0].attributes`)
2. **DOM** → JSON-LD first, then meta tags, then h1 name. **Body text regex DISABLED** (picks up carousel/bundle prices)

### Category Discovery
- Visit `/c/groceries/2` → extract `a[href*="/c/groceries"]` links
- Match to `CATEGORY_MAP` via `_CATEGORY_KEYWORDS` (fuzzy slug matching)
- Fallback to hardcoded paths if < 3 links found

### Pagination: **Explicit `?page=N`** (page 2 through 19 per category)

### Gotchas
- Category URLs change periodically — auto-discovery mitigates
- Firefox needs longer settle time (2.5s)
- PDP pages don't render prices in headless Firefox — Search API is the reliable fallback
- BFS pool can contain non-grocery items (jewelry, furniture) — category filter needed

---

## Zepto

### Browser: Chromium

### Location Setting (Triple-method)
1. **Cookies** on `.zepto.com`: `pincode`, `user_pincode`, `latitude`, `longitude`, `lat`, `lng`
2. **localStorage**: `latitude`, `longitude`, `store_id`, `user_position` (JSON), `serviceability` (JSON), `marketplace` (JSON)
3. **UI fallback**: Detect location prompt → click → fill pincode → select suggestion

### Product Extraction
| Method | Details |
|--------|---------|
| BFF gateway | `bff-gateway.zepto.com` — may use `octet-stream` content-type |
| RSC streaming | Line-delimited JSON (React Server Components) — parse each line |
| DOM extraction | `div`/`a` with `₹` + `img[src*="cdn.zeptonow.com"]` |

### Phase Order: **Search FIRST**, then BFS crawl (search is most reliable for Zepto)

### Category URLs: `/cn/<slug>` pattern, 16 slugs

### Pagination: Infinite scroll

### Gotchas
- RSC streaming = responses are line-delimited JSON, not standard JSON
- BFF gateway may have non-JSON content-type
- Server-rendered products → DOM extraction is critical

---

## Swiggy Instamart

### Browser: Chromium (Firefox gets 403 on Swiggy WAF)

### Location Setting
1. **Cookies** on `.swiggy.com` (BEFORE first navigation): `lat`, `lng`, `userLocation` (JSON)
2. Navigate to `swiggy.com` first (WAF challenge), wait 3s
3. **localStorage**: `lat`, `lng`, `userLocation`, `address` (JSON)
4. Then navigate to `/instamart`

### Product Extraction
| Method | Details |
|--------|---------|
| Swiggy widget API | `/api` endpoints → recursive DFS → `displayName` + price keys |
| DOM extraction | Generic card detection with image + ₹ pattern |

**Paise conversion**: Swiggy prices sometimes in paise (> 50,000 → ÷ 100)

### Phase Order: **Search FIRST**, then BFS crawl

### Category URLs: `/instamart/category/<name>` and `/instamart/collection/<name>`

### Gotchas
- Web version may NOT serve product prices (mobile app only)
- WAF challenge requires initial homepage visit + 3s wait
- `/instamart` sometimes redirects back to `/` — retry needed

---

## Flipkart Minutes (Kilos)

### Browser: Chromium

### Location Setting (2-step)
1. Click "Select delivery location" → fill pincode in area search → select suggestion
2. Navigate to grocery search → pincode verification form appears
3. **CRITICAL**: Use `press_sequentially(pincode, delay=100)` NOT `fill()` — React onChange doesn't fire with fill()
4. Press Enter, wait 3s

### Product Extraction
| Method | Details |
|--------|---------|
| DOM (primary) | Server-rendered. `img[src*="rukminim"]` + `₹` prices |
| API interception | Secondary — most data is in HTML |

### DOM Price Gotcha
Flipkart splits prices across inline spans: `<span>₹918</span><span>46</span>` reads as "₹91846" from innerText. Fix: iterate individual `*` descendants, check each element's textContent for `₹`, only accept elements with length <= 25 or childElementCount === 0.

### Search URL: `https://www.flipkart.com/search?q={term}&marketplace=GROCERY` (marketplace=GROCERY is critical)

### Category URLs: `/grocery-supermart-store`, `/grocery/<category>/pr?sid=eat`

### Pagination: Infinite scroll

### Gotchas
- Login popup on first visit — dismiss first
- `fill()` vs `press_sequentially()` — critical for React inputs
- Product card CSS classes change frequently — image+price heuristic is essential
- Images from `rukminim*.flipkart.com`

---

## Auto-Heal System (auto_heal.py)

5 extraction strategies tried in order:

| # | Strategy | Confidence | Method |
|---|----------|-----------|--------|
| 1 | API interception | 0.95 | `window.__sam_captured` |
| 2 | JSON-LD | 0.90 | `<script type="application/ld+json">` → `@type: Product` |
| 3 | Meta tags | 0.85 | `meta[property="product:price:amount"]` |
| 4 | DOM prices | 0.75 | `₹` elements within 800px of h1 |
| 5 | HTML regex | 0.50 | `"price":X` and `₹X` patterns |

**Sanity**: Price 1-50,000. Historical > 200% change → halve confidence.
**Stock**: Check for "out of stock", "currently unavailable", "notify me", "sold out"

---

## Cross-Platform Comparison

| Feature | Blinkit | JioMart | Zepto | Instamart | Flipkart |
|---------|---------|---------|-------|-----------|----------|
| Browser | Chromium | **Firefox** | Chromium | Chromium | Chromium |
| Location | localStorage + cookies | Cookies + UI | Cookies + localStorage + UI | Cookies + localStorage + WAF | UI form (press_sequentially) |
| Primary extraction | API interception | /trex/search (Google Retail) | BFF gateway + RSC streaming | Swiggy widget API | DOM (server-rendered) |
| Price format | Standard JSON | Pipe-delimited buybox_mrp | Standard JSON | Standard + paise | ₹ in DOM spans |
| Phase order | BFS → Search | BFS → Search | Search → BFS | Search → BFS | Search → BFS |
| Pagination | Infinite scroll | **?page=N** | Infinite scroll | Infinite scroll | Infinite scroll |
| Anti-bot | None | Akamai (blocks Chromium) | None | Swiggy WAF | Login popup |
| Key cookie | `__pincode`, `gr_1_lon` | `pincode`, `address_pincode` | `pincode`, `latitude`, `longitude` | `lat`, `lng`, `userLocation` | None (UI-based) |

---

_Last updated: 2026-04-15_
