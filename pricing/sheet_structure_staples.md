# Staples Pricing Sheet — Structure Analysis

Source: https://docs.google.com/spreadsheets/d/15krKSrw9BHjWngD2tDJ9uCJh4PWPZ0o_bqMkM3FLmdg/
Name: "NEW STPLS PRICING FILE 2026"

## 31 Sub-Sheets

### Core Pricing Sheets
| Sheet | Purpose |
|-------|---------|
| **MAIN SHEET** | Master pricing sheet — all SKUs, all calculations, final SP |
| **QUICK DATA** | Simplified view — key fields + city-level SPs |
| **KT** | Key Tracker — tracks SP changes (old SP → new SP) |
| **city level pricing** | City-specific price overrides |
| **City Level Pricing Extract** | Extracted from Price Master system |

### Input Data Sheets
| Sheet | Purpose |
|-------|---------|
| **Lastest Inward Cost** | Latest inward cost per SKU |
| **CHILD SKUs last inward Cost** | Child/variant SKU costs |
| **MAP - REDUNDANT** | MAP data (marked redundant) |
| **Price Master - Selling price** | Current SP from Price Master system |
| **Current Day MAP** | Today's MAP values |
| **Extract - Current Day MAP** | MAP extraction |
| **Connected sheet 1** | Connected/linked data |
| **WAREHOUSE mapping** | Warehouse-to-city mapping |

### Promo/Offer Sheets
| Sheet | Purpose |
|-------|---------|
| **APR PROMOS** | Off-invoice promos (vendor-funded) |
| **APR OFFERS** | On-invoice offers from Tez system |

### Benchmarking Sheets
| Sheet | Purpose |
|-------|---------|
| **BLINKIT 12 MAR** | SAM-scraped Blinkit prices (with match status) |
| **JIO 12 MAR** | SAM-scraped JioMart prices (with match status) |
| **GT BM WB** | Offline benchmark — West Bengal GT stores |
| **GT BM JH** | Offline benchmark — Jharkhand GT stores |

### Margin/Guardrail Sheets
| Sheet | Purpose |
|-------|---------|
| **GUARDRAIL MARGIN_4APR** | Per-SKU guardrail thresholds (lower/upper margin bounds) |

### Sales Data Sheets
| Sheet | Purpose |
|-------|---------|
| **SALE 30 DAYS** | Last 30-day sales |
| **90 DAY SALES_DEC_JAN_FEB** | 90-day sales (Dec-Jan-Feb) |
| **30 DAY SALES_FEB** | February 30-day sales |
| **wsh march** | Warehouse March data |

### Other
| Sheet | Purpose |
|-------|---------|
| Sheet141, Sheet140, Sheet147, Sheet149, Sheet158, Sheet162 | Work-in-progress / temp sheets |
| **Query result** | Query output sheet |

---

## MAIN SHEET — Column Structure (57 columns)

### Product Info (cols 1-12)
| # | Column | Source |
|---|--------|--------|
| 1 | KEY | State+ItemCode (e.g., "WB1615") |
| 2 | State | WB / JH / CG |
| 3 | Item code | AM item_code |
| 4 | Item name | AM display_name |
| 5 | KVI list | Super KVI / KVI / NON KVI |
| 6 | Segment | Product segment |
| 7 | category | Category |
| 8 | sub_category | Sub-category |
| 9 | leaf_category | Leaf category |
| 10 | brand | Brand |
| 11 | marketed by | Marketed by |
| 12 | AM Brand Tagging | Brand tagging |

### Sales Data (cols 13-15)
| # | Column | Source |
|---|--------|--------|
| 13 | LAST 90 DAY QTY SOLD | 90-day quantity |
| 14 | LAST 90 DAY SALES | 90-day sales value |
| 15 | DEMAND WEIGHT | Demand weightage |

### Cost & Margin (cols 16-20)
| # | Column | Source |
|---|--------|--------|
| 16 | MRP | Product MRP |
| 17 | LAST INWARD COST | Latest inward cost (model 1808) |
| 18 | MAP | Minimum Advertised Price |
| 19 | MAX of (INWARD AND MAP) | max(inward, MAP) = effective cost |
| 20 | GRN MARGIN | (MRP - cost) / MRP |

### Pricing (cols 21-24)
| # | Column | Source |
|---|--------|--------|
| 21 | CURRENT SP | Current selling price |
| 22 | CURRENT SP | (duplicate column) |
| 23 | FINAL SP | **OUTPUT: Final calculated SP** |
| 24 | RETENTION MARGIN | (MRP - off-invoice adjusted cost) / MRP |

### City-Level SPs (cols 26-31)
| # | Column |
|---|--------|
| 26 | ASANSOL SP |
| 27 | KOLKATA SP |
| 28 | BILASPUR SP |
| 29 | JAMSHEDPUR SP |
| 30 | HAZARIBAGH SP |
| 31 | RANCHI SP |

### Online Benchmarking (cols 32-34)
| # | Column | Source |
|---|--------|--------|
| 32 | BLINKIT 12 MAR | SAM Blinkit SP |
| 33 | JIO 12 MAR | SAM JioMart SP |
| 34 | MAX OF BOTH | max(Blinkit, Jio) = benchmark price |

### Offline Benchmarking (cols 36-50)
| # | Column | Source |
|---|--------|--------|
| 36 | CHANGES 12 MAR | Price changes |
| 37 | CHANGES | |
| 38 | RANCHI | Offline — Ranchi |
| 39 | RAIPUR | Offline — Raipur |
| 40 | BILASPUR | Offline — Bilaspur |
| 41 | KORBA | Offline — Korba |
| 42 | KOLKATA (SUMO) | Offline — Kolkata Sumo Save |
| 43 | KOLKATA (RELIANCE) | Offline — Kolkata Reliance |
| 44 | RELIANCE | Offline — Reliance |
| 45 | SMART POINT | Offline — Smart Point |
| 46 | GT | Offline — General Trade |
| 47 | DHANUKA STORE | Offline — Dhanuka |
| 48 | RELIANCE WB | Offline — Reliance WB |
| 49 | ASANSOL GT | Offline — Asansol GT |
| 50 | DURGAPUR GT | Offline — Durgapur GT |

### Output (cols 51-57)
| # | Column |
|---|--------|
| 51 | FINAL SKU LEVEL MARGIN |
| 52 | FINAL SKU LEVEL MARKUP |
| 53 | GUARDRAIL SKU PRICE |
| 54 | WSH MARCH SKU |
| 55 | REMARKS (RANCHI, RAIPUR, KOLKATA) |
| 56 | REMARKS (JMS, BILASP, ASANSOL) |
| 57 | REMARKS (HZB, KORBA) |

---

## QUICK DATA / WAREHOUSE mapping — Column Structure

| # | Column |
|---|--------|
| 1 | key (State+ItemCode) |
| 2 | STATE |
| 3 | ITEM CODE |
| 4 | DISPLAY NAME |
| 5 | KVI TAG |
| 6 | MRP |
| 7 | LAST INWARD COST |
| 8 | CURRENT SP |
| 9 | OFF INVOICE ADJUSTED COST |
| 10 | ADR SP (Cluster-level SP) |
| 11 | KOLKATA SP |
| 12 | BILASPUR/KORBA SP |
| 13 | JAMSHEDPUR SP |
| 14 | HAZARIBAGH SP |
| 15 | RANCHI SP |
| 16 | LAST 90 DAY SALE VALUE |
| 17 | LAST 90 DAY SALE QTY |

---

## APR PROMOS — Off-Invoice Promos

| # | Column |
|---|--------|
| 1 | KEY |
| 2 | STATE |
| 3 | Item Code |
| 4 | Item Name |
| 5 | Marketed By |
| 6 | MRP |
| 7 | % Offer |
| 8 | Rs. Offer |
| 9 | Promo Per Unit |
| 10 | FINAL OFFER VALUE |
| 11 | LATEST INWARD COST |
| 12 | OFF INVOICE ADJUSTED COST |

Example: Anik Ghee 1L → MRP 775, Rs.Offer 15, Final Offer Value 15, Cost 679.13, Adjusted Cost 664.13

---

## APR OFFERS — On-Invoice Offers (Tez System)

| # | Column |
|---|--------|
| 1 | KEY |
| 2 | STATE |
| 3 | item_code |
| 4 | item_name |
| 5 | master_category |
| 6 | category, sub_category |
| 7 | tez_store_id, store_name, city, state |
| 8 | business_type |
| 9 | offer_creation_date |
| 10 | offer_id, group_id |
| 11 | campaign_name, title, offer_code |
| 12 | type (SKU) |
| 13 | channel |
| 14 | offer_start, offer_end |
| 15 | offer_amountreward / offer_percentagereward |
| 16 | MRP |

Example: Organic Tattva Jowar Flour → 17% off, valid 4 Apr - 30 Apr 2026

---

## GUARDRAIL MARGIN — Per-SKU Thresholds

| # | Column |
|---|--------|
| 1 | Region |
| 2 | Key |
| 3 | item_code |
| 4 | display_name |
| 5 | Markup/gkm (cost based / GKM) |
| 6 | KVI (Super KVI / KVI / NON KVI) |
| 7 | category, sub_category, leaf_category |
| 8 | PRODUCT TYPE |
| 9 | brand |
| 10 | Unit wt |
| 11 | Total_Inventory |
| 12 | Last_90day_qty_Sold, Last_90day_Sale |
| 13 | Last90daysale_stores_cnt |
| 14 | latest_MRP |
| 15 | CP (cost price) |
| 16 | latest_selling |
| 17 | gm% (gross margin %) |
| 18 | Guardrail LOWER |
| 19 | GUARDRAIL HIGHER |
| 20 | SATELLITE LOW |
| 21 | SATELLITE HIGH |

Example: Almond 250g → cost based, NON KVI, CP 216, SP 285, GM 24%, Guardrail 20%-25%, Satellite 25%-30%

---

## BLINKIT / JIO Benchmark Sheets

### BLINKIT 12 MAR columns:
KEY, City, Pincode, Item_Code, Item_Name, Brand, Product_Type, Unit, Unit_Value, Mrp, Image_Link, Blinkit_Product_Url, Blinkit_Product_Id, Blinkit_Item_Name, Blinkit_Uom, Blinkit_Mrp_Price, Blinkit_Selling_Price, Blinkit_Discount_%, Blinkit_Eta_Mins, Blinkit_In_Stock_Remark, Blinkit_Status, Blinkit_Partial, Blinkit_Factor

### JIO 12 MAR columns:
KEY, City, Pincode, Item_Code, Item_Name, Brand, Product_Type, Jiomart_Item_Name, Jiomart_Uom, Jiomart_Mrp_Price, Jiomart_Selling_Price, Jiomart_Discount_%, Jiomart_Eta_Mins, Jiomart_In_Stock_Remark, Jiomart_Status, Jiomart_Partial, Jiomart_Factor

---

## City Level Pricing Extract

From Price Master system — city-specific SP overrides:
id, created_at, updated_at, product, level_code (CITY_Bilaspur / CITY_Jamshedpur / CITY_Hazaribagh), mrp, selling_price, cost_price, display_name, item_code, master_category

---

## How Pricing Works (Staples Flow)

```
INPUTS:
  ├── AM product data (item_code, name, KVI tag, category, brand)
  ├── Latest inward cost (model 1808)
  ├── MAP (Current Day MAP sheet)
  ├── Promos (APR PROMOS = off-invoice, APR OFFERS = on-invoice)
  ├── Guardrail thresholds (per SKU lower/upper margin bounds)
  ├── SAM benchmark data (Blinkit + JioMart SPs)
  ├── Offline benchmark data (Reliance, GT, Sumo Save, Smart Point)
  ├── 90-day sales data (for demand weighting)
  └── City-level pricing overrides

PROCESS:
  1. Calculate effective cost = max(latest inward, MAP)
  2. Calculate margin = (MRP - effective cost) / MRP
  3. Apply promo if available (higher of on/off invoice)
  4. Apply KVI/Non-KVI rules (see pricing_policy.md)
  5. Check against benchmark prices (MAX of Blinkit + Jio)
  6. Check against guardrail thresholds
  7. Apply city-level overrides where needed
  8. Verify: no negative margin, no below-cost SP

OUTPUT:
  ├── FINAL SP (cluster-level)
  ├── City-level SPs (Kolkata, Bilaspur, Jamshedpur, Hazaribagh, Ranchi, Asansol)
  ├── Final SKU level margin & markup
  └── Remarks per city group
```
