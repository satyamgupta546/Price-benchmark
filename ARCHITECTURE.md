# Price Benchmark — Architecture & Logic Documentation

> Quick Commerce Assortment Tracker — Scrapes product data from Blinkit, Zepto, Swiggy Instamart, JioMart & Flipkart Minutes and provides a unified comparison dashboard.

---

## Table of Contents

- [System Overview](#system-overview)
- [High-Level Architecture](#high-level-architecture)
- [Request Flow](#request-flow)
- [Scraping Engine](#scraping-engine)
- [Frontend Architecture](#frontend-architecture)
- [Data Models](#data-models)
- [CSV Export Logic](#csv-export-logic)
- [File Structure](#file-structure)
- [Configuration](#configuration)
- [Platform-Specific Logic](#platform-specific-logic)

---

## System Overview

```mermaid
graph TB
    subgraph Client["Browser (React SPA)"]
        UI[Dashboard UI]
        CSV[CSV Export]
    end

    subgraph Server["FastAPI Server :6789"]
        API["/api/* Routes"]
        Static["Static File Server<br/>(React dist/)"]
    end

    subgraph Scrapers["Scraping Engine (Playwright)"]
        BS[BaseScraper]
        BL[BlinkitScraper]
        ZP[ZeptoScraper]
        IM[InstamartScraper]
        JM[JioMartScraper]
        FK[FlipkartMinutesScraper]
    end

    subgraph Targets["Quick Commerce Platforms"]
        T1[blinkit.com]
        T2[zepto.com]
        T3[swiggy.com/instamart]
        T4[jiomart.com]
        T5[flipkart.com]
    end

    UI -->|POST /api/scrape| API
    UI -->|GET /api/pincodes| API
    API --> BS
    BS --> BL --> T1
    BS --> ZP --> T2
    BS --> IM --> T3
    BS --> JM --> T4
    BS --> FK --> T5
    API -->|JSON Response| UI
    UI --> CSV
    Client -->|GET /| Static
```

---

## High-Level Architecture

```mermaid
flowchart LR
    subgraph Frontend["Frontend (React + Vite + Tailwind)"]
        direction TB
        App["App.jsx<br/>Theme, State, Layout"]
        Header["Header.jsx<br/>Logo, Dark/Light Toggle"]
        PinInput["PincodeInput.jsx<br/>State → City → Pincode<br/>Multi-select Dropdowns"]
        PlatSel["PlatformSelector.jsx<br/>5 Platform Checkboxes"]
        ProdTable["ProductTable.jsx<br/>Tabs, Filters, Sort, Paginate"]
        CompView["ComparisonView.jsx<br/>Side-by-side Price Compare"]
        Export["ExportButton.jsx<br/>Comparison CSV Download"]
        Hook["useScrapeData.js<br/>API Communication"]
    end

    subgraph Backend["Backend (FastAPI + Playwright)"]
        direction TB
        Main["main.py<br/>FastAPI App + Static Mount"]
        Routes["scrape.py<br/>POST /scrape, GET /pincodes<br/>GET /export/csv"]
        Config["config.py<br/>Environment Settings"]
        Models["product.py<br/>Pydantic Models"]
        Service["export_service.py<br/>CSV Generation"]
        Base["base_scraper.py<br/>Abstract Scraper Engine"]
        Scrapers2["5 Platform Scrapers"]
    end

    subgraph Data["Data Layer"]
        Pincodes["pincodes.json<br/>29 States, 300+ Cities"]
        Cache["In-Memory Cache<br/>Last Scrape Results"]
    end

    App --> Header
    App --> PinInput
    App --> PlatSel
    App --> ProdTable
    App --> CompView
    App --> Export
    App --> Hook
    Hook -->|HTTP| Routes
    Routes --> Scrapers2
    Scrapers2 --> Base
    Routes --> Service
    Routes --> Pincodes
    Routes --> Cache
```

---

## Request Flow

### Scrape Flow (Main Feature)

```mermaid
sequenceDiagram
    participant U as User (Browser)
    participant F as Frontend (React)
    participant A as FastAPI Server
    participant S as Scraper Engine
    participant P as Platform Sites

    U->>F: Select Pincodes + Platforms
    U->>F: Click "Fetch Data"
    F->>A: POST /api/scrape<br/>{pincodes: [...], platforms: [...]}

    Note over A: Create scrape tasks for<br/>each (platform × pincode) combo

    par Concurrent Scraping
        A->>S: BlinkitScraper(pincode)
        S->>P: Launch Chromium → blinkit.com
        S->>P: Set location cookies
        S->>P: Crawl 65 categories + scroll
        S->>P: Search 120+ terms (early exit after 5 empty)
        P-->>S: Intercept JSON API responses
        S-->>A: Return Product[]

        A->>S: ZeptoScraper(pincode)
        S->>P: Launch Chromium → zepto.com
        S->>P: Set cookies + localStorage + UI
        S->>P: 3-tier category discovery + scroll
        S->>P: Intercept BFF gateway + RSC streaming
        P-->>S: Parse JSON + line-delimited JSON
        S-->>A: Return Product[]

        A->>S: InstamartScraper(pincode)
        S->>P: Launch Firefox → swiggy.com/instamart
        S->>P: Set Swiggy location + UI picker
        S->>P: Browse categories + search
        P-->>S: Intercept JSON API responses
        S-->>A: Return Product[]

        Note over A,S: Same for JioMart, Flipkart
    end

    A->>A: Aggregate results + cache
    A-->>F: ScrapeResponse JSON
    F->>F: Render tables, cards, charts
    F-->>U: Display dashboard
```

### Scraping Engine Detail

```mermaid
flowchart TD
    Start([Scraper.scrape_all]) --> Init[Launch Headless Browser<br/>Chromium or Firefox]
    Init --> Cookie[Set Platform Cookies<br/>pincode, lat, lng]
    Cookie --> LS[Set localStorage<br/>location, serviceability]
    LS --> Home[Navigate to Homepage]
    Home --> UILoc{UI Location<br/>Picker needed?}
    UILoc -->|Yes| TypePin[Type pincode in UI<br/>→ select suggestion]
    UILoc -->|No| Discover
    TypePin --> Discover{Discover Categories}

    Discover -->|DOM links| CatList[Category URL List]
    Discover -->|API responses| CatList
    Discover -->|Neither found| Fallback[Use Hardcoded<br/>Category Paths]
    Fallback --> CatList

    CatList --> CrawlLoop["_visit_categories_with_early_exit()"]
    CrawlLoop --> Navigate[page.goto category URL]
    Navigate --> Wait[Wait 1.5s for load]
    Wait --> Scroll[Scroll page 5-8 times<br/>triggers lazy loading]

    Scroll --> Intercept{Network Response<br/>Interceptor}
    Intercept -->|JSON with product data| Parse[Extract products<br/>from nested JSON]
    Intercept -->|No JSON caught| HTMLFallback[Extract from<br/>__NEXT_DATA__ / script tags]

    Parse --> Dedup{Seen before?<br/>check product ID}
    HTMLFallback --> Dedup
    Dedup -->|New| Add[Add to products list]
    Dedup -->|Duplicate| Skip[Skip]

    Add --> EarlyExit{5 consecutive<br/>empty categories?}
    Skip --> EarlyExit
    EarlyExit -->|Yes| SearchPhase
    EarlyExit -->|No| MaxCheck{Hit max_products?}
    MaxCheck -->|No| CrawlLoop
    MaxCheck -->|Yes| SearchPhase

    CrawlLoop -->|All done| SearchPhase["_search_and_capture()<br/>120+ search terms"]
    SearchPhase --> SearchLoop[For each search term]
    SearchLoop --> SearchNav[Navigate to search URL]
    SearchNav --> SearchScroll[Scroll 3 times]
    SearchScroll --> Intercept
    SearchLoop -->|5 consecutive empty| Return([Return products])
    SearchLoop -->|All done| Return
```

### Network Response Interception

```mermaid
flowchart TD
    Browser[Browser] -->|Every HTTP Response| Handler["_on_response()"]
    Handler --> CheckType{Content-Type<br/>or BFF gateway?}
    CheckType -->|Standard JSON| CheckStatus{Status 200?}
    CheckType -->|BFF gateway<br/>zepto.com| TryParse[Try JSON + RSC<br/>line-delimited]
    CheckType -->|Neither| Ignore[Ignore]
    CheckStatus -->|No| Ignore
    CheckStatus -->|Yes| CheckKeywords{Body contains<br/>'product', 'price',<br/>'mrp', 'name'?}
    CheckKeywords -->|No| Ignore
    CheckKeywords -->|Yes| Store[Store in<br/>_captured_responses]
    TryParse --> Store

    Store --> Process["_process_responses()"]
    Process --> Extract["_extract_products_from_json()<br/>Recursive depth-8 traversal"]
    Extract --> ParseProduct["_parse_generic_product()<br/>Flexible key matching:<br/>20+ field name variants"]
    ParseProduct --> ProductObj[Product Object]
```

### Early Exit Strategy

```mermaid
flowchart LR
    CatLoop["Category/Search Loop"] --> Check{New products<br/>found?}
    Check -->|Yes| Reset["consecutive_empty = 0"]
    Check -->|No| Increment["consecutive_empty++"]
    Increment --> Threshold{">= 5 empty<br/>in a row?"}
    Threshold -->|Yes| Exit["Early exit<br/>(location not set<br/>or site blocking)"]
    Threshold -->|No| Continue["Continue loop"]
    Reset --> Continue
```

---

## Frontend Architecture

### Component Hierarchy

```mermaid
graph TD
    App["App.jsx<br/>─────────────<br/>• dark/light theme state<br/>• selectedPincodes[]<br/>• selectedPlatforms[]<br/>• view: table | compare<br/>• useScrapeData() hook"]

    App --> Header["Header.jsx<br/>─────────────<br/>• Gradient header bar<br/>• Dark/Light toggle button<br/>• Props: dark, onToggleTheme"]

    App --> PincodeInput["PincodeInput.jsx<br/>─────────────<br/>• State → City → Pincode<br/>  cascading dropdowns<br/>• Searchable dropdowns<br/>  (type to filter)<br/>• Multi-select with checkboxes<br/>• Manual pincode entry<br/>• Selected shown as tags<br/>• Uses usePincodes() hook"]

    App --> PlatformSelector["PlatformSelector.jsx<br/>─────────────<br/>• 5 platform checkboxes<br/>• Brand color indicators<br/>• Select All / Deselect All"]

    App --> ErrorBanner["ErrorBanner.jsx<br/>─────────────<br/>• Error (red) or Warning (amber)<br/>• Dismissible with ✕ button"]

    App --> LoadingSpinner["LoadingSpinner.jsx<br/>─────────────<br/>• Dual spinning rings<br/>• Platform name badges<br/>• Shows during scrape"]

    App --> SummaryCards["Summary Cards (inline)<br/>─────────────<br/>• Per-platform product count<br/>• Scrape duration<br/>• Total aggregation<br/>• 3-state: success / 0 amber / failed red<br/>• Shows error messages on failure"]

    App --> ViewToggle["View Toggle (inline)<br/>─────────────<br/>• Product Table view<br/>• Price Comparison view"]

    App --> ProductTable["ProductTable.jsx<br/>─────────────<br/>• Platform tabs with counts<br/>• Search, brand, pincode filters<br/>• Sortable columns<br/>• Pagination (25/page)<br/>• Color-coded platform badges"]

    App --> ComparisonView["ComparisonView.jsx<br/>─────────────<br/>• Groups products by name<br/>• Only shows items on 2+ platforms<br/>• Highlights cheapest in green<br/>• 'Lowest' label on best price"]

    App --> ExportButton["ExportButton.jsx<br/>─────────────<br/>• Downloads comparison CSV<br/>• Platform prices as columns<br/>• cheapest_platform column<br/>• price_diff column"]
```

### Theme System

```mermaid
flowchart LR
    Toggle["Toggle Button<br/>(Header.jsx)"] -->|onClick| SetDark["setDark(!dark)"]
    SetDark --> Effect["useEffect"]
    Effect -->|dark=true| AddClass["document.documentElement<br/>.classList.add('dark')"]
    Effect -->|dark=false| RemoveClass["document.documentElement<br/>.classList.remove('dark')"]
    Effect --> Save["localStorage.setItem<br/>('theme', dark?'dark':'light')"]

    Init["App Mount"] --> ReadLS["localStorage.getItem('theme')"]
    ReadLS -->|'dark' or null| DarkDefault["dark = true"]
    ReadLS -->|'light'| LightDefault["dark = false"]

    AddClass --> Tailwind["Tailwind CSS<br/>dark: variants activate"]
    RemoveClass --> Tailwind
```

---

## Data Models

### Pydantic Models (Backend)

```mermaid
classDiagram
    class Product {
        +str product_name
        +str brand
        +float price
        +float|None mrp
        +str|None unit
        +str|None category
        +str|None sub_category
        +str platform
        +str pincode
        +bool in_stock
        +str scraped_at
        +str|None image_url
    }

    class PlatformResult {
        +str platform
        +str pincode
        +str status
        +int total_products
        +float scrape_duration_seconds
        +list~Product~ products
        +str|None error_message
    }

    class ScrapeRequest {
        +list~str~ pincodes
        +list~str~ platforms
        +list~str~ categories
        +int max_products_per_platform
    }

    class ScrapeResponse {
        +list~str~ pincodes
        +list~PlatformResult~ results
        +int total_products
        +float total_duration_seconds
    }

    ScrapeResponse *-- PlatformResult
    PlatformResult *-- Product
    ScrapeRequest ..> ScrapeResponse : triggers
```

---

## CSV Export Logic

```mermaid
flowchart TD
    Products["All Products Array<br/>(from all platforms)"] --> Normalize["Normalize product names<br/>lowercase + trim whitespace"]
    Normalize --> Group["Group by normalized name<br/>Map: name → {prices: {platform: info}}"]
    Group --> Sort["Sort alphabetically<br/>by product_name"]

    Sort --> Headers["Build CSV Headers"]
    Headers --> H1["sr_no, product_name, brand,<br/>unit, category, pincode"]
    Headers --> H2["For each active platform:<br/>{Platform}_price,<br/>{Platform}_mrp,<br/>{Platform}_stock"]
    Headers --> H3["cheapest_platform,<br/>cheapest_price,<br/>price_diff"]

    Sort --> Rows["For each product row"]
    Rows --> FillPrices["Fill platform columns<br/>from prices map"]
    FillPrices --> FindCheapest["Find min price<br/>across platforms"]
    FindCheapest --> CalcDiff["price_diff =<br/>max_price - min_price"]

    H1 --> CSVFile["Combined CSV File"]
    H2 --> CSVFile
    H3 --> CSVFile
    Rows --> CSVFile
    CalcDiff --> CSVFile
```

### CSV Output Example

```
sr_no | product_name    | brand | unit | Blinkit_price | Blinkit_stock | Zepto_price | Zepto_stock | cheapest_platform | cheapest_price | price_diff
1     | Amul Butter     | Amul  | 500g | 275.00        | Yes           | 279.00      | Yes         | Blinkit           | 275.00         | 4.00
2     | Lays Classic    | Lays  | 52g  | 20.00         | Yes           | 19.00       | Yes         | Zepto             | 19.00          | 1.00
3     | Tata Salt       | Tata  | 1kg  | 28.00         | Yes           |             |             | Tata              | 28.00          | 0.00
```

---

## File Structure

```
Price benchmark/
├── config.yaml                        # Central project configuration
├── ARCHITECTURE.md                    # This file
├── .gitignore
│
├── data/
│   └── pincodes.json                  # 29 states, 300+ cities, pincodes
│
├── backend/
│   ├── .env                           # Environment variables
│   ├── .env.example                   # Example env template
│   ├── requirements.txt               # Python dependencies
│   │
│   └── app/
│       ├── __init__.py
│       ├── main.py                    # FastAPI app + static file serving
│       ├── config.py                  # Settings from .env
│       │
│       ├── models/
│       │   ├── __init__.py
│       │   └── product.py             # Pydantic: Product, ScrapeRequest/Response
│       │
│       ├── routes/
│       │   ├── __init__.py
│       │   └── scrape.py              # API endpoints: /scrape, /pincodes, /export
│       │
│       ├── scrapers/
│       │   ├── __init__.py
│       │   ├── base_scraper.py        # Abstract base: browser, intercept, parse
│       │   ├── blinkit_scraper.py     # Blinkit: cookies + 65 categories + search
│       │   ├── zepto_scraper.py       # Zepto: cookies + localStorage + UI + search
│       │   ├── instamart_scraper.py   # Instamart: Swiggy location + categories + search
│       │   ├── jiomart_scraper.py     # JioMart: pincode cookie + categories + search
│       │   └── flipkart_minutes_scraper.py  # Flipkart: grocery search + categories
│       │
│       └── services/
│           ├── __init__.py
│           └── export_service.py      # Comparison-format CSV generation
│
└── frontend/
    ├── package.json                   # npm dependencies
    ├── vite.config.js                 # Vite: port 6789, API proxy
    ├── tailwind.config.js             # Tailwind: darkMode 'class', brand colors
    ├── postcss.config.js
    ├── index.html                     # Entry HTML
    │
    ├── src/
    │   ├── main.jsx                   # React DOM render
    │   ├── App.jsx                    # Root: theme, state, layout
    │   ├── index.css                  # Tailwind imports
    │   │
    │   ├── components/
    │   │   ├── Header.jsx             # Logo + dark/light toggle
    │   │   ├── PincodeInput.jsx       # State → City → Pincode multi-select
    │   │   ├── PlatformSelector.jsx   # Platform checkboxes
    │   │   ├── ProductTable.jsx       # Filterable, sortable, paginated table
    │   │   ├── ComparisonView.jsx     # Cross-platform price comparison
    │   │   ├── ExportButton.jsx       # CSV download trigger
    │   │   ├── LoadingSpinner.jsx     # Scrape progress indicator
    │   │   └── ErrorBanner.jsx        # Error/warning display
    │   │
    │   ├── hooks/
    │   │   └── useScrapeData.js       # POST /api/scrape + GET /api/pincodes
    │   │
    │   └── utils/
    │       ├── constants.js           # PLATFORMS array, API_BASE
    │       └── csvExport.js           # Client-side comparison CSV builder
    │
    └── dist/                          # Vite build output (served by FastAPI)
```

---

## Configuration

All settings are centralized in `config.yaml` (project root) and `backend/.env`.

See `config.yaml` for the complete reference of all configurable options.

---

## Platform-Specific Logic

### Blinkit

```mermaid
flowchart TD
    Start([BlinkitScraper]) --> Cookies["Set Cookies:<br/>__pincode, gr_1_lat, gr_1_lng"]
    Cookies --> Home["goto blinkit.com"]
    Home --> Discover["Discover category links<br/>from homepage (a[href*='/cn/'])"]
    Discover --> Merge["Merge with 65 hardcoded<br/>category paths"]
    Merge --> Loop["For each category"]
    Loop --> Visit["Visit category URL"]
    Visit --> Scroll["Scroll 8 times<br/>(lazy load trigger)"]
    Scroll --> Capture["Capture API JSON responses"]
    Capture --> Parse["Parse products"]
    Parse --> Loop
    Loop -->|Done| Search["Search 120+ terms<br/>/s/?q={term}"]
    Search --> Return([Return products])
```

### Zepto

```mermaid
flowchart TD
    Start([ZeptoScraper<br/>Chromium]) --> Cookies["Set Cookies on .zepto.com:<br/>pincode, lat, lng"]
    Cookies --> LS["Set localStorage:<br/>user_position, serviceability,<br/>marketplace, store_id"]
    LS --> Home["goto zepto.com"]
    Home --> Reload["Reload with location set<br/>(wait 4s for RSC hydration)"]
    Reload --> UILoc["Try UI location picker<br/>(only if location prompt visible)"]

    UILoc --> Discover["3-Tier Category Discovery"]
    Discover --> T1["Tier 1: DOM links<br/>(a[href*='/cn/'])"]
    T1 -->|>= 3 found| CatLoop
    T1 -->|< 3| T2["Tier 2: Parse API responses<br/>for category URLs"]
    T2 -->|>= 3 found| CatLoop
    T2 -->|< 3| T3["Tier 3: 16 fallback slugs"]
    T3 --> CatLoop

    CatLoop["Browse categories<br/>(early exit after 5 empty)"]
    CatLoop --> Search["Search 120+ terms<br/>/search?query={term}"]
    Search --> Fallback["Fallback: __NEXT_DATA__"]
    Fallback --> Return([Return products])

    subgraph Interception["Custom Response Handler"]
        BFF["bff-gateway.zepto.com<br/>responses intercepted"]
        RSC["RSC streaming parsed<br/>line-delimited JSON"]
    end
```

### Swiggy Instamart

```mermaid
flowchart TD
    Start(["InstamartScraper<br/>🦊 Firefox (bypasses TLS fingerprint)"]) --> Swiggy["goto swiggy.com"]
    Swiggy --> Cookies["Set Cookies on .swiggy.com:<br/>lat, lng, userLocation"]
    Cookies --> LS["Set localStorage:<br/>lat, lng, address, userLocation"]
    LS --> UILoc["Try UI location picker<br/>(only if location prompt visible)"]
    UILoc --> IM["goto swiggy.com/instamart"]
    IM --> Process["Process homepage responses"]
    Process --> Discover["Discover categories:<br/>a[href*='/instamart/']<br/>→ /category/ or /collection/"]
    Discover -->|< 3 found| FallbackCats["19 fallback paths:<br/>/instamart/category/*<br/>/instamart/collection/*"]
    Discover -->|>= 3| CatLoop
    FallbackCats --> CatLoop
    CatLoop["Browse categories<br/>(early exit after 5 empty)"]
    CatLoop --> Search["Search /instamart/search?query={term}"]
    Search --> Fallback["Fallback: HTML extraction"]
    Fallback --> Return([Return products])
```

### JioMart

```mermaid
flowchart TD
    Start([JioMartScraper]) --> Cookies["Set Cookies:<br/>pincode, address_pincode"]
    Cookies --> Home["goto jiomart.com"]
    Home --> UIPincode["Try UI: click pincode button<br/>→ type pincode → Apply"]
    UIPincode --> Discover["Discover grocery category links"]
    Discover --> CatLoop["Browse 25 categories + scroll"]
    CatLoop --> Search["Search /search/{term}"]
    Search --> Return([Return products])
```

### Flipkart Minutes

```mermaid
flowchart TD
    Start([FlipkartMinutesScraper]) --> Home["goto flipkart.com"]
    Home --> Dismiss["Dismiss login popup"]
    Dismiss --> UIPincode["Try setting pincode via UI"]
    UIPincode --> Search["Search ?q={term}&marketplace=GROCERY"]
    Search --> Grocery["Browse /grocery/* category pages"]
    Grocery --> Return([Return products])
```

---

## Pincode → Coordinates Mapping

The scraper uses a **pincode prefix → lat/lng lookup table** to set correct location for each platform. This ensures that a Mumbai pincode shows Mumbai products, not Delhi.

```
Pincode prefix → City → (lat, lng)
────────────────────────────────────
11xxxx → Delhi     → (28.6139, 77.2090)
40xxxx → Mumbai    → (19.0760, 72.8777)
56xxxx → Bangalore → (12.9716, 77.5946)
50xxxx → Hyderabad → (17.3850, 78.4867)
60xxxx → Chennai   → (13.0827, 80.2707)
70xxxx → Kolkata   → (22.5726, 88.3639)
38xxxx → Ahmedabad → (23.0225, 72.5714)
41xxxx → Pune      → (18.5204, 73.8567)
... (80+ prefixes mapped)
```

---

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/scrape` | Scrape products for given pincodes × platforms |
| `GET` | `/api/pincodes` | Get state → city → pincode mapping |
| `GET` | `/api/export/csv` | Download comparison CSV |
| `GET` | `/api/categories/{platform}` | Get category list for a platform |
| `GET` | `/api/health` | Health check |
| `GET` | `/*` | Serve React frontend (SPA) |
