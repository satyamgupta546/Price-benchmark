# FMCGF & FMCGNF Pricing Sheets — Structure Analysis

## FMCGF
- Source: https://docs.google.com/spreadsheets/d/1F3sbhuSM-CZzDrQBnTACer4nWjtEoJz8fGMCPsSsc5g/
- Name: "FMCGF_PRICING_FILE_April_2026"
- Sub-sheets: 35

## FMCGNF
- Source: https://docs.google.com/spreadsheets/d/10Aw35StophBwiTd49VHK2TJN8t2oei8YczFmIfboUv0/
- Name: "FMCGNF_PRICING_FILE_April_26"
- Sub-sheets: 53

Both share the SAME Main sheet column structure and Rules.

---

## Sub-Sheets (Common to Both)

### Core Pricing
| Sheet | Purpose |
|-------|---------|
| **Main** | Master pricing sheet — all SKUs, all calculations, final SP BAU |
| **Quick_data / Quick data** | Simplified: KEY, STATE, ITEM CODE, DISPLAY NAME, KVI TAG, CATEGORY, SUB CATEGORY, LEAF CATEGORY, MRP, OFF INVOICE ADJ COST, SP BAU |
| **Rules / RULE** | Pricing rules reference (11 rules) |
| **Price_Changes** | Tracks SP changes |

### Input Data
| Sheet | Purpose |
|-------|---------|
| **latest_Inward / MRP & cost** | Latest inward cost per SKU |
| **Map / MAP** | MAP data |
| **MAP COST / map cost** | MAP cost data |
| **MAP IMPORT / MAP - AUTOMATED** | Automated MAP imports |
| **latest_Assortment / ASSORTMENT** | Current product assortment |
| **30_day / 30_Day** | Last 30-day sales |
| **90_day / 90_Day** | Last 90-day sales |

### Promo Sheets
| Sheet | Purpose |
|-------|---------|
| **Off_Invoice** | Off-invoice promos from vendors |
| **On_Invoice** | On-invoice promos from vendors |
| **off invoice check** | Validation sheet |

### Classification
| Sheet | Purpose |
|-------|---------|
| **KVI_Tag / KVI** | KVI / Non-KVI classification per SKU |
| **Exclusion** | Excluded SKUs (BOGO, baby food, etc.) |

### Benchmarking
| Sheet | Purpose |
|-------|---------|
| **Anakin_dashboard** | Blinkit + JioMart scraped data (SAM data!) |
| **Jio_data / JIO** | JioMart-specific price data |

### FMCGNF-Only Sheets
| Sheet | Purpose |
|-------|---------|
| **kvi_working_*_apr** | Daily KVI pricing work (multiple dates) |
| **sinu updated price** | Manual price updates |
| **siddaraju input** | Category lead inputs |
| **SUMMER BIG BET SKU'S** | Summer campaign SKUs |
| **AROMAPLUS** | Brand-specific pricing |
| **PROMO ISSUE / PROMOS NEEDS TO BE CORRECTED** | Promo validation/fix sheets |

### FMCGF-Only Sheets
| Sheet | Purpose |
|-------|---------|
| **CNC_11th_April** | Cost & carry check |
| **KVI_15th_April** | KVI working for that date |
| **beverages pricing** | Beverage-specific pricing |
| **APR WSH** | April wholesale data |

---

## Main Sheet — Column Structure (59 columns)

### Product Info (cols 1-10)
| # | Column | Source |
|---|--------|--------|
| 1 | KEY | State+ItemCode (e.g., "WB8091") |
| 2 | STATE | WB / JH / CG |
| 3 | ITEM_CODE | AM item_code |
| 4 | DISPLAY_NAME | AM display_name |
| 5 | KVI TAG | KVI / NON KVI |
| 6 | CATEGORY | Product category |
| 7 | SUB_CATEGORY | Sub-category |
| 8 | LEAF_CATEGORY | Leaf category |
| 9 | BRAND | Brand |
| 10 | MARKETED_BY | Marketed by |

### Sales Data (cols 11-15)
| # | Column |
|---|--------|
| 11 | LAST 30 DAY QTY SOLD |
| 12 | LAST 30 DAY SALE VALUE |
| 13 | Last_90day_qty_Sold |
| 14 | Last_90day_Sale |
| 15 | DEMAND WT. (demand weight %) |

### Promos & Invoice (cols 16-23)
| # | Column | Notes |
|---|--------|-------|
| 16 | EXCLUSION | "yes" if excluded SKU |
| 17 | OFF INVOICE PROMO % | Vendor off-invoice % |
| 18 | OFF INVOICE PROMO VALUE | Rs. off-invoice amount |
| 19 | ON INVOICE PROMO % | On-invoice % |
| 20 | ON INVOICE PROMO VALUE | Rs. on-invoice amount |
| 21 | FINAL INVOICE VALUE | **Higher of on/off invoice** |
| 22 | ON INVOICE % OF MRP | On-invoice as % of MRP |
| 23 | ON INVOICE % / MARGIN % | On-invoice % relative to margin |

### Cost & Margin (cols 24-30)
| # | Column | Notes |
|---|--------|-------|
| 24 | MRP | Product MRP |
| 25 | MRP BUCKET | "<=40", "40-100", "100-200", ">=200" |
| 26 | LATEST INWARD COST | From model 1808 |
| 27 | MAP | Minimum Advertised Price |
| 28 | OFF INVOICE ADJUSTED COST | MAP − off-invoice (or inward if no MAP) |
| 29 | GRN_MARGIN | (MRP − inward cost) / MRP |
| 30 | MAP MARGIN | (MRP − MAP) / MRP |

### Benchmarking (cols 31-33)
| # | Column | Notes |
|---|--------|-------|
| 31 | JIOMART MRP | JioMart MRP from SAM/Anakin |
| 32 | JIOMART SP | JioMart SP from SAM/Anakin |
| 33 | JIOMART MRP = MRP | Whether JioMart MRP matches AM MRP |

### Margin Calculation (cols 34-35)
| # | Column |
|---|--------|
| 34 | MARGIN | Effective margin used for discount formula |
| 35 | MARGIN BUCKET | "<=10%", "10%-15%", "15%-20%", etc. |

### Previous Period (cols 36-39)
| # | Column |
|---|--------|
| 36 | OLD MRP |
| 37 | OLD SP BAU |
| 38 | OLD DISCOUNT % |
| 39 | ASSORTMENT CHECK |

### SP Calculation (cols 40-43) — THE CORE OUTPUT
| # | Column | Notes |
|---|--------|-------|
| 40 | MRP | (repeated for formula) |
| 41 | OFF INV ADJ COST | (repeated for formula) |
| 42 | Automated MAP / MAP INCLUDING GST | MAP with GST |
| 43 | **SP BAU** | **FINAL OUTPUT: Selling Price (Business As Usual)** |

### Remarks & Validation (cols 44-59)
| # | Column | Notes |
|---|--------|-------|
| 44 | CHANGES | TRUE/FALSE if SP changed |
| 45 | remark 5 | |
| 46 | Remark 4 | |
| 47 | Remark 3 | |
| 48 | REMARK 2 | |
| 49 | REMARK 1 | Primary remark (e.g., "NON KVI, promo passed") |
| 50 | DISCOUNT % | |
| 51 | BAU DISCOUNT | Final discount % applied |
| 52 | DISCOUNT BUCKET | "b0%-3%", "b3%-7%", etc. |
| 53 | RM % | Retention Margin % |
| 54 | RM BUCKET | "10-15%", etc. |
| 55 | SP X QTY | Revenue estimate |
| 56 | CP X QTY | Cost estimate |
| 57 | SP = MRP | TRUE/FALSE guard |
| 58 | MRP >= BAU | TRUE/FALSE guard (MRP must be >= SP) |
| 59 | BAU >= COST | TRUE/FALSE guard (SP must be >= cost) |

---

## Off_Invoice Sheet — Column Structure

| # | Column | Notes |
|---|--------|-------|
| 1 | Key | State+ItemCode |
| 2 | State | |
| 3 | Marketed By | Vendor name |
| 4 | Brand | |
| 5 | Item Code | |
| 6 | Item Name | |
| 7 | System MRP | MRP in AM system |
| 8 | MRP by Vendor | MRP provided by vendor |
| 9 | GKM (TOT Margin) | Total margin % |
| 10 | GRN Margin | |
| 11 | April invoice Landing | Cost after invoice |
| 12 | April Offer % | Off-invoice % |
| 13 | April Offer Rs. | Off-invoice Rs. |
| 14 | April Final Landing | Final cost after off-invoice |
| 15 | Promo Type | "OFF Invoice" |
| 16 | Category | |
| 17 | Sub Category | |
| 18 | Leaf Category | |

Example: Rasna Fruit Fun → MRP 47, Off-invoice Rs.5, Final Landing 32.6

---

## On_Invoice Sheet — Column Structure

Same columns as Off_Invoice, with:
- Promo Type = "ON Invoice"
- Offer Link (Google Drive folder with proof)
- On Pack Selling Price (if applicable)

Example: Horlicks 1Kg → MRP 480, GKM 7.04%, On-invoice Rs.30, Final Landing 416.21

---

## Exclusion Sheet

| # | Column |
|---|--------|
| 1 | ITEM_CODE |
| 2 | DISPLAY NAME |
| 3 | MASTER CAT | fmcgf / fmcgnf |
| 4 | TYPE | BOGO / baby_food / chocolate_lt80 / etc. |
| 5 | Tag | "yes" |

---

## KVI_Tag / KVI Sheet

| # | Column |
|---|--------|
| 1 | KEY |
| 2 | STATE |
| 3 | STATE KEY |
| 4 | item_code |
| 5 | display_name |
| 6 | master category |
| 7 | KVI / NKVI TAG | "KVI" / "NON KVI" / "Super KVI" |

Note: KVI list is shared across FMCGF, FMCGNF, and Staples.

---

## Rules Sheet (11 Rules — Same for FMCGF & FMCGNF)

```
Rule 1:  MRP <= 40 → SP = MRP − Final Invoice Value. No promo → SP = MRP
Rule 2:  NON KVI, MRP > 40 →
         A: Promo → SP = MRP − Final Invoice Value
         B: No promo → Discount formula (margin-based table)
Rule 3:  KVI, MRP > 40 →
         A: Promo + BM → SP = MIN(MRP−promo, benchmark). Cost floor applies.
         B: Only promo → SP = MRP − promo
         C: Only BM → SP = IF(BM > cost, BM, cost)
         D: Neither → Discount formula
Rule 4:  SP = MRP → Apply 1.5% discount if MRP >= 200, 1% if 100-200
Rule 5:  SP = MRP because Blinkit at MRP → Apply discount formula (KVI only, MRP > 40)
Rule 6:  Guardrails — No negative discount, no negative RM, MRP >= SP, SP >= cost
Rule 7:  MRP > 10, margin > 54% → 50% discount straight (KVI & Non-KVI)
Rule 8:  Exclusions (FMCGF only) — Baby food = 0% discount. Others = 0% unless promo
Rule 9:  On-invoice > 80% of margin → check RM. If RM < 6-7% → remove/consult
Rule 10: Calculate overall retention margin
Rule 11: Both on + off invoice → pick the GREATER one
```

### Margin-Based Discount Table (used in Rules 2B, 3D, 4, 5)
| Margin % | Discount % |
|----------|------------|
| <= 10%   | 0%         |
| <= 15%   | 2%         |
| <= 20%   | 3%         |
| <= 25%   | 5%         |
| <= 30%   | 7%         |
| <= 40%   | 10%        |
| <= 50%   | 20%        |
| <= 54%   | 20%        |
| > 54%    | 50%        |

---

## Anakin_dashboard / SAM Data — Column Structure

This is the SAM/Anakin scraped data that feeds benchmarking:

| # | Column |
|---|--------|
| 1 | Date |
| 2 | Key (or City) |
| 3 | City / Pincode |
| 4 | Item_Code |
| 5 | Item_Name |
| 6 | Brand |
| 7 | Product_Type |
| 8 | Unit |
| 9 | Unit_Value |
| 10 | Mrp |
| 11 | Image_Link |
| 12-23 | Blinkit columns (URL, ID, Name, UOM, MRP, SP, Discount%, ETA, Stock, Status, Partial, Factor) |
| 24-35 | JioMart columns (URL, ID, Name, UOM, MRP, SP, Discount%, ETA, Stock, Status, Partial, Factor) |

---

## How FMCG Pricing Works (Flow)

```
INPUTS:
  ├── AM product data (item_code, name, KVI tag, category, brand)
  ├── Latest inward cost (model 1808)
  ├── MAP (Minimum Advertised Price)
  ├── Off-invoice promos (vendor-funded, Rs. or %)
  ├── On-invoice promos (vendor-funded, Rs. or %)
  ├── KVI tag (KVI / NON KVI)
  ├── Exclusion list (BOGO, baby food, etc.)
  ├── SAM benchmark data (Blinkit SP + JioMart SP)
  ├── 30-day and 90-day sales data
  └── Previous period SP (old SP BAU)

PROCESS (apply rules in order):
  1. Compute OFF INVOICE ADJUSTED COST = MAP − off-invoice (or inward if no MAP)
  2. Compute MARGIN = (MRP − adjusted cost) / MRP
  3. Determine FINAL INVOICE VALUE = max(on-invoice, off-invoice)
  4. Check EXCLUSIONS → if excluded, 0% discount (only pass promos)
  5. Check MRP <= 40 → Rule 1
  6. Check NON KVI + MRP > 40 → Rule 2
  7. Check KVI + MRP > 40 → Rule 3
  8. Check SP = MRP cases → Rule 4 (minimum discount) + Rule 5 (benchmark)
  9. Check high margin override → Rule 7 (margin > 54%)
  10. Guardrails → Rule 6 (no negative, SP <= MRP, SP >= cost)
  11. On-invoice validation → Rule 9 (if >80% of margin, escalate)
  12. Compute RM % → Rule 10
  
OUTPUT:
  ├── SP BAU (final selling price)
  ├── BAU DISCOUNT % 
  ├── RM % (retention margin)
  ├── REMARK (which rule applied)
  └── Validation flags (SP=MRP?, MRP>=BAU?, BAU>=COST?)
```
