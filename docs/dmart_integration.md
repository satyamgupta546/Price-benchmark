# DMart Ready Integration

## Overview
DMart Ready (dmart.in) has an **open JSON API** — no auth, no cookies, no Playwright needed. Simplest and fastest scraper.

## API Details

### Base URL
```
https://digital.dmart.in/api/v3/plp/{slug}?page={n}&size=100&storeId={id}&channel=web&buryOOS=true
```

### Key Endpoints
| Endpoint | Purpose |
|----------|---------|
| `/api/v3/plp/{slug}` | Category listing (PLP) — primary endpoint |
| `/api/v2/pdp/{productId}?type=productid&storeId={id}` | Product detail page |
| `/api/v1/categories/top?storeId={id}` | Category hierarchy |

### Search: BROKEN — DO NOT USE
Search API returns wrong results (searching "toor dal" returns umbrellas). Use category browsing exclusively.

## Product Data from API
```json
{
  "productId": 96573,
  "name": "Tata Sampann Unpolished Toor Dal",
  "manufacturer": "Tata Sampann",        // = BRAND
  "sKUs": [{
    "skuUniqueID": 99529,
    "articleNumber": "110000783",          // = barcode/article
    "name": "Tata Sampann Unpolished Toor Dal: 1 kg",
    "priceMRP": 244.00,
    "priceSALE": 170.00,
    "savePrice": 74.00,
    "savingPercentage": 30,
    "invStatus": 2,                       // 2=In Stock, 0=OOS
    "variantTextValue": "1 kg",           // = unit/pack size
    "defaultVariant": true
  }]
}
```

## Store ID (CRITICAL — prices vary by store)
| Pincode | City | storeId | Status |
|---------|------|---------|--------|
| 492001 | Raipur | 10677 | Needs verification |
| — | Mumbai | 10151 | Confirmed working |

### How to discover storeId for new cities:
1. Open dmart.in in browser
2. Set pincode via location picker
3. Open DevTools → Network → filter by "storeId"
4. Copy the storeId from any API call

## Availability
DMart Ready is NOT available in:
- Ranchi (834002) ❌
- Kolkata (712232) ❌
- Hazaribagh (825301) ❌

Available in:
- Raipur (492001) ✅ (only current city)

## Scraper: `backend/app/scrapers/dmart_scraper.py`
- Pure API (no Playwright, no browser)
- 31 grocery categories
- Pagination: page=1,2,... up to totalRecords
- Deduplication by skuUniqueID
- Returns Product objects compatible with SAM pipeline

## Anakin's DMart Status
Anakin has 12 DMart columns in cx_competitor_prices but ALL are "NA" — they never implemented DMart scraping. SAM will be the first to provide DMart data.

## How Anakin Scrapes (for reference)
Anakin's approach (from docs/anakin_full_logic.md):
- Anakin does NOT scrape DMart — all DMart fields are empty
- They planned to use the same crawl+match approach but never built it
- SAM's API-based approach is superior (direct JSON, no browser, faster)

## Excel Columns for DMart
```
DMART URL | DMART ITEM NAME | DMART UNIT | DMART MRP | DMART SP | DMART IN STOCK REMARK | DMART STATUS
```
Added after JIO columns in the 35-column format (was 28, now 35 with DMart).

## Match Status Logic (same as Blinkit/Jiomart)
```
COMPLETE MATCH: unit ±10% + MRP ±5% OR SP matches ±5% OR unit ±10% + MRP ±10%
SEMI COMPLETE: LOOSE in STPLS + same unit type
PARTIAL MATCH: found but criteria not met
NA: not found / DMart not available in this city
```
