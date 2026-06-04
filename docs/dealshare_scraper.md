# DealShare Scraper

## Overview
Pure API scraper — no browser needed. Fetches product data directly from DealShare internal API.

## API
```
POST https://services.dealshare.in/feedservice/api/v1/get-page
Headers: pincode=700001, channel=APP, appVersion=1.1.9
Body: {pageQueryType, pageInfo, slotInfo, lang}
Response: JSON with products (title, brand, price, mrp, grammage)
```

## Location
Pincode header controls city. No cookies/localStorage needed.
- 700001 = Kolkata
- 712232 = Howrah

## Product Fields
title, brand, price (SP), mrp, grammage, categoryL1/L2/L3, image, foodType, offPercentage

## Pagination
Cursor-based, increment by 5. Loop until hasNext=false.

## Speed
~0.5-1 sec per API call, 10 products per call.
Full grocery category (~200+ products): ~20 sec.

## Usage
```bash
python3 scripts/scrape_dealshare.py 700001          # scrape only
python3 scripts/scrape_dealshare.py 700001 --match   # scrape + AM match
```

## Output
- `data/dealshare_{pincode}_{ts}.json` — all products
- `data/dealshare_match_{pincode}_{ts}.json` — AM match results

## Categories Scraped
- 719: Grocery & Packaged Food
- 720: Personal Care
- 721: Cleaning & Home Care
- 726: Dairy, Frozen & Bakery
- 727: Fruits & Vegetables
