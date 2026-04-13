# SAM (Price Benchmark) — Our System Reference

> Companion to `ANAKIN.md`. This file documents our own Price Benchmark system — architecture, scraping algorithm, matching logic, output format, strengths, and gaps.
>
> **Goal:** Build our own competitor pricing system that matches Anakin at 99%+ accuracy → save ₹3 lakh/month.

---

## 1. High-Level Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  Frontend (React + Vite)                                    │
│  - Pincode input + platform selector + category selector    │
│  - Live SSE progress bar                                    │
│  - Excel download                                           │
│  - Delta Compare UI (upload reference Excel)                │
└──────────────────┬──────────────────────────────────────────┘
                   │ HTTP / SSE
┌──────────────────▼──────────────────────────────────────────┐
│  Backend (FastAPI + Uvicorn)                                │
│  ├─ /scrape           POST: trigger scrape, returns JSON    │
│  ├─ /scrape/stream    GET:  SSE progress per platform       │
│  ├─ /export           GET:  download last scrape as Excel   │
│  ├─ /compare/upload   POST: upload reference Excel          │
│  ├─ /compare/stream   POST: SSE compare progress            │
│  └─ /compare/download GET:  download delta Excel            │
└──────────────────┬──────────────────────────────────────────┘
                   │
┌──────────────────▼──────────────────────────────────────────┐
│  Scraper Layer (Playwright)                                 │
│  ├─ BaseScraper (shared logic, 521 lines)                   │
│  └─ 5 platform scrapers (each ~370–470 lines):              │
│     ├─ BlinkitScraper          (Chromium)                   │
│     ├─ ZeptoScraper            (Chromium)                   │
│     ├─ InstamartScraper        (Chromium + Swiggy WAF)      │
│     ├─ JioMartScraper          (Firefox — Akamai bypass)    │
│     └─ FlipkartMinutesScraper  (Chromium + pincode form)    │
└─────────────────────────────────────────────────────────────┘
```

---

## 2. Tech Stack

| Layer | Tech |
|---|---|
| **Backend** | FastAPI + Uvicorn (Python) |
| **Browser automation** | Playwright (Chromium + Firefox) |
| **Excel** | openpyxl (styled per-platform sheets) |
| **Frontend** | React 18 + Vite + Tailwind |
| **Real-time** | Server-Sent Events (SSE) |
| **Concurrency** | asyncio + asyncio.gather |
| **Match algorithm (current)** | difflib.SequenceMatcher (threshold 0.35) |

---

## 3. File Structure

```
backend/
├── app/
│   ├── main.py                    44 lines  — FastAPI app entry
│   ├── config.py                  16 lines  — env var loader
│   ├── models/
│   │   └── product.py             40 lines  — Pydantic schemas
│   ├── scrapers/
│   │   ├── base_scraper.py       521 lines  — shared scraping logic
│   │   ├── blinkit_scraper.py    386 lines  — Blinkit-specific
│   │   ├── zepto_scraper.py      460 lines  — Zepto-specific
│   │   ├── instamart_scraper.py  468 lines  — Instamart-specific
│   │   ├── jiomart_scraper.py    377 lines  — JioMart-specific
│   │   └── flipkart_minutes_scraper.py  371 lines
│   ├── services/
│   │   ├── compare_service.py    763 lines  — multi-platform compare
│   │   └── export_service.py     289 lines  — styled Excel writer
│   └── routes/
│       └── scrape.py             380 lines  — API endpoints + SSE
└── .env                                     — METABASE_API_KEY etc.

frontend/
└── src/
    ├── App.jsx
    ├── components/
    │   └── DeltaCompare.jsx
    ├── hooks/
    │   └── useCompare.js
    └── utils/
        └── constants.js                     — PLATFORMS array

data/
├── pincodes.json                            — pincode → coords (top cities)
└── anakin/                                  — saved Anakin snapshots
    ├── blinkit_834002_2026-04-11.json
    └── blinkit_834002_2026-04-11.csv

ANAKIN.md                                    — Anakin reverse engineering doc
SAM.md                                      — This file
```

---

## 4. Data Models

```python
class Product(BaseModel):
    product_name: str
    brand: str
    price: float           # selling price
    mrp: float | None
    unit: str | None       # e.g., "500g", "1 L"
    category: str | None
    sub_category: str | None
    platform: str          # "blinkit" | "zepto" | ...
    pincode: str
    in_stock: bool = True
    scraped_at: str        # ISO timestamp UTC
    image_url: str | None
```

> **Note:** Currently `product_name` and `unit` are stored as a single string (no separation of unit_value + unit_suffix). This is a gap when comparing to Anakin which has `Unit_Value` (numeric) and `Unit` (g/ml/kg) as separate columns.

---

## 5. Scraping Algorithm — BaseScraper (Shared Logic)

### 5.1 Browser initialization
```python
async def init_browser():
    self.playwright = await async_playwright().start()
    self.browser = await self.playwright.chromium.launch(
        headless=True,
        args=["--disable-blink-features=AutomationControlled", "--no-sandbox"]
    )
    self.context = await self.browser.new_context(
        user_agent=random.choice(USER_AGENTS),
        viewport={"width": 1366, "height": 768},
        locale="en-IN",
        timezone_id="Asia/Kolkata",
    )
    # Hide automation
    await self.context.add_init_script("""
        Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
        window.chrome = {runtime: {}};
    """)
    self.page = await self.context.new_page()
    self.page.on("response", self._on_response)   # capture all JSON responses
```

### 5.2 Response interception (the core trick)
Every HTTP response with `content-type: json` is captured into `_captured_responses`. Later, `_extract_products_from_json` recursively walks each captured payload looking for objects that have BOTH a name field AND a price field.

```python
async def _on_response(self, response):
    if "json" in content_type and status == 200:
        body = await response.text()
        if any(kw in body.lower() for kw in ["product", "price", "mrp", "name", "selling", "inventory"]):
            data = json.loads(body)
            self._captured_responses.append({"url": url, "data": data})
```

### 5.3 Generic product extraction (recursive walker)
```python
def _extract_products_from_json(self, data, depth=0) -> list[dict]:
    if depth > 8:
        return []
    products = []
    if isinstance(data, dict):
        has_name = any(k in data for k in [
            "name", "product_name", "title", "display_name", "productName"
        ])
        has_price = any(k in data for k in [
            "price", "mrp", "selling_price", "offer_price", "sp", "sellingPrice", "finalPrice"
        ])
        if has_name and has_price:
            products.append(data)
        for val in data.values():
            products.extend(self._extract_products_from_json(val, depth + 1))
    elif isinstance(data, list):
        for item in data:
            products.extend(self._extract_products_from_json(item, depth + 1))
    return products
```

### 5.4 Generic field parser
```python
def _parse_generic_product(self, p: dict) -> Product | None:
    # Try multiple key candidates for each field
    name = first_match(p, ["name", "product_name", "title", "display_name", "productName"])
    
    # Top-level price keys
    price = float_from(p, ["price", "selling_price", "offer_price", "sp", ...])
    
    # Nested pricing dict (Blinkit style: p["price"] is a dict)
    pricing = p.get("pricing") or p.get("priceInfo") or {}
    if isinstance(p.get("price"), dict):
        pricing = p["price"]
    if isinstance(pricing, dict) and price == 0:
        # IMPORTANT: order matters — offer_price BEFORE price
        # because Blinkit's pricing dict has "price" = MRP value
        for key in ["offer_price", "selling_price", "sp", "finalPrice", ..., "price"]:
            ...
    
    mrp = float_from(p, ["mrp", "marked_price", "original_price", ...])
    brand = first_string(p, ["brand", "brand_name", "brandName", "manufacturer"])
    unit = first_string(p, ["unit", "weight", "quantity", "pack_size", ...])
    in_stock = bool_from(p, ["in_stock", "inStock", "available", ...])
    image = url_from(p, ["image_url", "image", "thumbnail", ...])
    
    return Product(...)
```

### 5.5 Three-phase scrape flow (per platform)

```
PHASE 1: Deep Category Crawl (BFS)
─────────────────────────────────────
1. Load homepage → set location → reload
2. Seed queue with category URLs from CATEGORY_MAP
3. For each URL:
    a. Visit + scroll aggressively (5–12 times) to trigger lazy load
    b. Wait for network idle (settle window)
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
    c. If <5 products found, also try HTML __NEXT_DATA__ extraction
    d. Stop after 10 consecutive empty searches

PHASE 3: DOM Fallback (Blinkit-specific)
─────────────────────────────────────
JavaScript walks all <div> elements looking for product cards:
- Has <img> with platform image domain
- Contains ₹ price
- 2–15 children, 20–400 chars text length
- Is "leaf" (no nested cards)
Extract: name (first text line), prices (₹ regex), image URL
```

### 5.6 Deduplication
```python
self._seen_ids: set = set()
# pid = product_id OR slug OR name (lowercased)
# Each product hashed by ID, duplicates skipped
```

---

## 6. Per-Platform Overrides

### 6.1 Blinkit (`blinkit_scraper.py`)
- **Location**: `localStorage["location"] = {coords: {lat, lon, locality, cityName, ...}}`
- **Cookies**: `__pincode`, `gr_1_lat`, `gr_1_lon` (NOT `gr_1_lng`!)
- **Crawl**: BFS over `/cn/...` paths with CID-based filtering
- **DOM fallback**: searches `img[src*="grofers.com"]` for product cards
- **Categories**: 21 (Paan Corner, Dairy, Fruits, Snacks, etc.)

### 6.2 Zepto (`zepto_scraper.py`)
- **Location**: cookies + localStorage + UI fallback (clicks pincode picker)
- **Browser**: Chromium
- **Special**: parses RSC streaming JSON from Next.js

### 6.3 Instamart (`instamart_scraper.py`)
- **Location**: Swiggy `userLocation` cookie + Swiggy address API
- **Special**: WAF bypass — must visit `swiggy.com` first to set cookies
- **Parser**: `_parse_swiggy_widgets()` recursive walker for Swiggy widget JSON

### 6.4 JioMart (`jiomart_scraper.py`)
- **Browser**: **Firefox** (Chromium → 403 from Akamai CDN)
- **API**: `/trex/search` returns Google Retail catalog format
- **Parse**: `product.variants[0].attributes.buybox_mrp.text[0]` →
  pipe-delimited: `"store|qty|seller||mrp|price||..."`
- **Categories**: discovered from `/c/groceries/2` (URLs change frequently)

### 6.5 Flipkart Minutes (`flipkart_minutes_scraper.py`)
- **Pincode form**: must use `press_sequentially()` (NOT `fill()` — React onChange ignores fill)
- **DOM extraction**: server-rendered, no JSON API → parse `img[src*="rukminim"]` cards
- **Filter**: aggressive cleanup of junk product names (DOM has many noise rows)

---

## 7. Compare Service (Current)

`compare_service.py` (763 lines) handles **Delta Compare** workflow:

### 7.1 Inputs
- Reference Excel (Apna catalog with `Item_Name`, `Brand`, `Jiomart_Item_Name`, `Mrp`, `Sp`)
- Pincode
- List of platforms

### 7.2 Flow
```
1. parse_reference_excel()
   - Reads "anaken" sheet
   - Extracts: name, brand, jio_name, jio_mrp, jio_sp

2. Init all platform browsers IN PARALLEL via asyncio.gather
   - Each platform's _init_*() function replicates its scrape_all() setup

3. For each platform IN PARALLEL:
   For each ref product SEQUENTIALLY:
       a. Clear scraper state (products, responses, seen_ids)
       b. Build search URL with reference name
       c. Visit + capture + extract candidates
       d. Score each candidate by SequenceMatcher(ref_name, candidate_name)
       e. JioMart: try jio_name first, fallback to name
       f. Best score >= 0.35 → use as match

4. Generate styled Excel:
   - Per-platform price columns
   - Per-platform match% columns
   - Best price + Best platform + Delta from Ref
   - Color: green if cheaper than ref, red if costlier, gray if no match
   - Summary sheet with stats
```

### 7.3 Match scoring (current)
```python
def _name_similarity(a: str, b: str) -> float:
    a_clean = re.sub(r'[^\w\s]', '', a.lower()).strip()
    b_clean = re.sub(r'[^\w\s]', '', b.lower()).strip()
    return SequenceMatcher(None, a_clean, b_clean).ratio()

# Threshold: 0.35
# Single-factor: name only (no brand, pack size, MRP weighting)
```

---

## 8. Output Format

### 8.1 Regular scrape Excel (per platform sheet)
| Column | Description |
|---|---|
| Sr No | row number |
| Pincode | scraped pincode |
| Product Name | from scraper |
| Brand | extracted or first word |
| MRP | if found |
| Selling Price | live price |
| Discount % | computed |
| Unit | size string (e.g., "500g") |
| Category | best guess |
| In Stock | bool |
| Image URL | first image |
| Scraped At | ISO timestamp |

### 8.2 Delta Compare Excel
- **Summary sheet**: Total / Pincode / Platforms / Match rates / Price analysis
- **Price Delta sheet**:
  - Sr No, Item Name, Brand, Ref MRP, Ref SP
  - For each platform: Price column (color-coded) + Match% column
  - Best Price, Best Platform, Delta from Ref

---

## 9. Algorithm Strengths

| Strength | Why it matters |
|---|---|
| **5 platforms vs Anakin's 3** | We track Zepto, Instamart, Flipkart Min that Anakin doesn't |
| **Real-time live scraping** | Anakin gives daily snapshots; we can refresh on demand |
| **Multi-platform parallel** | All 5 browsers run concurrently via asyncio |
| **API interception + DOM fallback** | Catches products even if API misses |
| **Generic JSON walker** | Same code works across all 5 platform APIs |
| **No human-in-loop** | Fully automated; Anakin appears to use manual mapping |
| **SSE progress** | User sees per-platform live progress |
| **Category filtering** | User can scope to specific categories per platform |
| **CID-based BFS** | Prevents drifting into unrelated categories |

---

## 10. Algorithm Weaknesses (vs Anakin)

| Weakness | Anakin's approach | Fix |
|---|---|---|
| **Single-factor matching (name only)** | Brand + pack size + MRP weighted | Add multi-factor scoring |
| **Threshold 0.35 is too loose** | Anakin classifies into 4 buckets | Implement Status enum |
| **No pack size normalization** | Anakin computes `_Factor` (e.g., 0.5 for 500g vs 1kg) | Add Factor calculation |
| **No "Partial Match" reasons** | Anakin tags `MRP-Diff`, `Weight-Diff`, etc. | Add reason tagging |
| **No private-label substitution** | Anakin's "Semi Complete Match" finds Whole Farm equivalents | Add substitute matching |
| **`unit` is a single string** | Anakin separates `Unit_Value` (numeric) + `Unit` (g/ml) | Refactor Product model |
| **Fuzzy match on whole catalog** | Anakin uses cached Product_Url/Id mapping | Use Anakin's mapping as seed |
| **One-shot scrape** | Anakin runs daily snapshots | Add scheduler |
| **No diff tracking over time** | Anakin keeps 253 days of history | Add price history table |

---

## 11. Side-by-Side: Anakin vs SAM

| Feature | Anakin | SAM (current) |
|---|---|---|
| **Platforms** | Blinkit, Jiomart, Dmart | Blinkit, Jiomart, Zepto, Instamart, Flipkart Min |
| **Approach** | Manual mapping + script | Automated scraping (BFS + search) |
| **Match Status** | 4 buckets (Complete/Partial/Semi/NA) | Single ratio threshold (0.35) |
| **Pack Size Normalization** | `Factor` column (e.g., 0.5) | None |
| **Match Reasons** | `_Partial` field (Weight-Diff, MRP-Diff, etc.) | None |
| **Live Price Coverage** | 1,464 / 2,364 = 61% (834002 Blinkit) | TBD (need to run scrape) |
| **Stock Tracking** | Yes (`In_Stock_Remark`) | Yes (`in_stock` bool) |
| **History Storage** | 253 days in Metabase | None (in-memory only) |
| **Frequency** | Daily snapshot | On-demand |
| **Output** | Google Sheets / Metabase dashboard | Excel download |
| **Delivery to team** | Anakin pushes to Mirror | Manual download from web UI |
| **Cost** | ₹3 lakh / month | ₹0 (our infra) |
| **Coverage gaps** | 10–30% NA per platform | TBD |

---

## 12. Next Steps to Reach 99% Match with Anakin

### 🔑 Critical Discovery (2026-04-11) — corrected after user feedback

**Anakin's actual data flow is OPAQUE** — we only see the final output. The chain is:

```
Anakin's hidden pipeline
       ↓ (pushes daily output)
Google Sheet (Anakin owned)
       ↓ (federated sync)
BigQuery: apna-mart-data.googlesheet.cx_competitor_prices
       ↓ (Apna analysts JOIN with smpcm_product to enrich)
Mirror dashboard (what we see)
```

**What we know:**
- The dataset name `googlesheet` confirms it's a Google Sheet sync
- Apna analyst's SQL (card 21286) explicitly LEFT JOINs `cx_competitor_prices` with `smpcm_product` on `item_code`
- Anakin's source for Apna SKU data is unknown — could be API, SFTP, manual upload, or scraping

**What we can use:**
- Apna's `smpublic.smpcm_product` table — 54,884 active SKUs, full catalog with brand/MRP/unit/etc.
- This is OUR source-of-truth, not Anakin's

**Strategy:**
1. Pull Apna's full SKU master directly from `smpcm_product` (we have read access via Mirror API)
2. Build our own mapping (Apna SKU → competitor product URL)
3. Daily scrape mapped URLs for live prices
4. Output to BigQuery / Google Sheet / Excel
5. After 4 weeks of 99% accuracy → replace Anakin

We don't need to know Anakin's pipeline. We're building a parallel system from scratch using Apna's own catalog as input.

### Phase 1 — Validate (current)
- [x] Pull Anakin's Blinkit data for pincode 834002 (3,620 SKUs, 2,364 Blinkit-mapped)
- [x] Discover Apna product master at `smpcm_product` (table 578)
- [ ] Pull Apna's full SKU master via Metabase MBQL → save locally
- [ ] Run our Blinkit scraper for 834002
- [ ] Compare: which of Anakin's 2,364 Blinkit SKUs do we find?
- [ ] Compare: do prices match?

### Phase 2 — Match algorithm upgrade
- [ ] Implement multi-factor scoring: `0.5×name + 0.2×brand + 0.2×qty + 0.1×token_overlap`
- [ ] Implement pack size normalization (Factor = ref_qty / scraped_qty)
- [ ] Implement Status enum: Complete / Partial / Semi / NA
- [ ] Implement Partial reason tagging: `Weight-Diff`, `MRP-Diff`, `Container-Diff`
- [ ] Refactor Product model: split `unit` into `unit_value` (float) + `unit` (str)

### Phase 3 — Use Anakin mapping as seed
- [ ] New service: `anakin_service.py` — pull Anakin's Product_Url/Id mapping via Metabase API
- [ ] New mode in compare: "Anakin Seeded" — visit Product_Url directly, scrape PDP
- [ ] Cache Anakin mapping locally

### Phase 4 — Historical storage
- [ ] Add Postgres table for daily snapshots
- [ ] Or push to Google Sheets like manufacture project does
- [ ] Add diff tracking over time

### Phase 5 — Coverage improvement
- [ ] For Anakin's 384 NA Blinkit SKUs → can we discover them?
- [ ] For Anakin's 1,109 NA Jiomart SKUs → can we discover them?

### Phase 6 — Replace Anakin
- [ ] 4 weeks of 99%+ accuracy
- [ ] Pricing team migrates to our dashboard
- [ ] Cancel ₹3 L/month contract

---

## 13. Useful Commands

### Run backend
```bash
cd backend
./venv/bin/uvicorn app.main:app --reload --port 8000
```

### Run frontend
```bash
cd frontend
npm run dev
```

### Test scrape
```bash
curl -X POST http://localhost:8000/scrape \
  -H "Content-Type: application/json" \
  -d '{"pincodes":["834002"], "platforms":["blinkit"], "max_products_per_platform": 5000}'
```

### Build frontend
```bash
cd frontend && npm run build
```

---

## 14. Key Insights from Anakin Comparison (so far)

### Insight 1 — Anakin's data is incomplete
Out of 2,364 Blinkit-mapped SKUs in Anakin for pincode 834002:
- Only **1,464 (61%) have actual live prices**
- **899 (38%) marked out of stock** with NA prices
- 1 row literally has `in_stock_remark = "NA"`

→ **We can do better** by scraping live and not relying on stale snapshots.

### Insight 2 — Anakin name format hides unit info
| Anakin `Item_Name` | Anakin `Blinkit_Item_Name` | Anakin `Blinkit_Uom` |
|---|---|---|
| `Chings ManChow Instant Soup 12g` | `Ching's Secret Manchow Instant Soup` | `10 x 12 g` |
| `Parle Milk Shakti Cookies 350g` | `Parle Milk Shakti Biscuit` | `350 g` |
| `Cadbury 5Star Chocolate 18g` | `Cadbury 5 Star Chocolate Filled Bar` | `35.2 g` |

→ Anakin's `Item_Name` includes unit ("12g") while Blinkit's strips it to a separate Uom field.
→ Our scraper currently produces a single `unit` string — need to normalize.

### Insight 3 — `Factor` column is the key to fair comparison
Anakin computes `Factor = anakin_unit / platform_unit` to normalize prices when pack sizes differ. Examples:
- Anakin Cadbury 5 Star **18g** vs Blinkit **35.2g** → Factor 0.545
- Anakin Wheel Powder **500g** vs Blinkit **1kg** → Factor 0.5
- Anakin Patanjali Hand Wash **750ml** vs Blinkit **200ml** → Factor 3.75

→ We must implement this for accurate price comparison.

### Insight 4 — Anakin has data quality issues
- `MRP-Diff`, `MRP Diff`, `MRP DIFF` (3 spellings)
- `partial Match` typo
- `nan` values in Partial column
- Some `Status="Complete Match"` rows have `Product_Id="NA"`

→ Our system can be cleaner from day 1.

---

_Last updated: 2026-04-11 — initial documentation. Will be updated as Phase 1 validation proceeds._
