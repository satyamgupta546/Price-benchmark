# Anakin — Reverse Engineering Reference

> **Goal:** Replace Anakin (₹3 lakh/month = ₹36 lakh/year) with our own Price Benchmark.
> Target: 99% match accuracy with Anakin's data.

This file documents everything we've discovered about how Anakin captures and matches competitor pricing data. Use this as the source-of-truth reference when building our own logic.

---

## 1. Data Source

| Item | Value |
|---|---|
| **Mirror URL** | `https://mirror.apnamart.in` |
| **Metabase API** | `https://mirror.apnamart.in/api/dataset` |
| **Authentication** | API key header: `x-api-key: <key>` |
| **API key location** | `backend/.env` → `METABASE_API_KEY` ✅ saved |
| **Database ID** | `5` |
| **Schema** | `googlesheet` (Anakin pushes data via Google Sheets sync) |
| **Main table** | `cx_competitor_prices` (table id = `4742`) |
| **External table** | `cx_competitor_prices_external` (table id = `4745`) — same schema, parallel feed |
| **Total rows** | ~29,33,242 |
| **History** | 253 distinct dates (~8 months of daily snapshots) |
| **SKUs per pincode** | ~3,600–4,100 |

### 🔑 ACTUAL DATA FLOW (Fully decoded — 2026-04-11)

**Anakin dumps Parquet files to GCS:** `gs://cx_competitor_prices/anakin_raw_data/apnamart_anakin_delivery_*.parquet`

```
┌────────────────────────────────────────────────────┐
│  Anakin's pipeline (still opaque internally)       │
│  - Anakin's mapping + scraping logic               │
│  - Anakin's classification (Status, Factor, etc.)  │
│  - Generates Parquet files                         │
└──────────────────┬─────────────────────────────────┘
                   │ Anakin uploads .parquet files
                   ▼
   ┌────────────────────────────────────────────────┐
   │  GCS Bucket                                    │
   │  gs://cx_competitor_prices/                    │
   │      anakin_raw_data/                          │
   │      apnamart_anakin_delivery_*.parquet        │
   └──────────────┬─────────────────────────────────┘
                  │
                  │ BigQuery EXTERNAL table (federated read)
                  ▼
   ┌────────────────────────────────────────────────┐
   │  BigQuery EXTERNAL table                       │
   │  apna-mart-data.googlesheet.                   │
   │  cx_competitor_prices_external                 │
   │  (Type: EXTERNAL, Format: PARQUET)             │
   └──────────────┬─────────────────────────────────┘
                  │
                  │ Daily 05:30 IST scheduled query (owner: ranjeet.kumar@apnamart.in):
                  │   CREATE OR REPLACE TABLE cx_competitor_prices AS
                  │   SELECT * FROM cx_competitor_prices_external;
                  ▼
   ┌────────────────────────────────────────────────┐
   │  BigQuery MATERIALIZED table                   │
   │  apna-mart-data.googlesheet.                   │
   │  cx_competitor_prices                          │
   │  (Type: TABLE, snapshot of external)           │
   └──────────────┬─────────────────────────────────┘
                  │
                  │ Apna analyst SQL joins to enrich:
                  │   c.item_code = sp.item_code
                  ▼
   ┌────────────────────────────────────────────────┐
   │  smpublic.smpcm_product                        │
   │  (Apna's own catalog — enrichment only)        │
   └──────────────┬─────────────────────────────────┘
                  │
                  ▼
       ┌──────────────────┐
       │ Mirror Dashboard │
       │   (final view)   │
       └──────────────────┘
```

### Where Anakin Actually Dumps Data — VERIFIED

| Item | Value |
|---|---|
| **GCS bucket** | `gs://cx_competitor_prices/` |
| **Path** | `anakin_raw_data/` |
| **File pattern** | `apnamart_anakin_delivery_*.parquet` |
| **Format** | **PARQUET** (not CSV) |
| **External table** | `apna-mart-data.googlesheet.cx_competitor_prices_external` (Type: EXTERNAL) |
| **Materialized table** | `apna-mart-data.googlesheet.cx_competitor_prices` (Type: TABLE — daily snapshot) |
| **Snapshot job** | `scheduled_query_69e21dbb-0000-263f-ab30-d43a2cd6283f` |
| **Snapshot owner** | `ranjeet.kumar@apnamart.in` |
| **Snapshot schedule** | Daily at 05:30 IST |
| **Snapshot SQL** | `CREATE OR REPLACE TABLE cx_competitor_prices AS SELECT * FROM cx_competitor_prices_external;` |

### How we discovered this

```bash
# 1. Check who creates the materialized table → found ranjeet.kumar's scheduled query
bq query --use_legacy_sql=false '
SELECT creation_time, user_email, job_id
FROM `apna-mart-data.region-asia-south1.INFORMATION_SCHEMA.JOBS_BY_PROJECT`
WHERE destination_table.table_id = "cx_competitor_prices"
ORDER BY creation_time DESC LIMIT 5'

# 2. Get the scheduled query SQL
bq query --use_legacy_sql=false '
SELECT query FROM `apna-mart-data.region-asia-south1.INFORMATION_SCHEMA.JOBS_BY_PROJECT`
WHERE job_id = "scheduled_query_69e21dbb-0000-263f-ab30-d43a2cd6283f"'
# → CREATE OR REPLACE TABLE ... AS SELECT * FROM cx_competitor_prices_external;

# 3. Inspect the external table to find its source URI
bq show --format=prettyjson apna-mart-data:googlesheet.cx_competitor_prices_external
# → externalDataConfiguration.sourceUris:
#   ['gs://cx_competitor_prices/anakin_raw_data/apnamart_anakin_delivery_*.parquet']
```

### Access status (as of 2026-04-11)

| Resource | satyam.gupta@apnamart.in access | Notes |
|---|---|---|
| BigQuery `cx_competitor_prices` (materialized) | ✅ Read | Use this for all data analysis |
| BigQuery `cx_competitor_prices_external` (federated) | ❌ Read fails | Needs GCS Storage Object Viewer to glob parquet files |
| GCS bucket `gs://cx_competitor_prices/` | ❌ 403 (bucket exists) | Need `Storage Object Viewer` role |
| BigQuery JOBS_BY_PROJECT | ✅ Read | Used to discover scheduled queries |
| Apna `smpublic.smpcm_product` | ✅ Read via Mirror | 54,884 active SKUs |

**To get GCS access** (optional but useful for inspecting raw parquets):
Ask Apna DevOps / `ranjeet.kumar@apnamart.in` for `Storage Object Viewer` role on `gs://cx_competitor_prices/anakin_raw_data/` for `satyam.gupta@apnamart.in`.

We don't strictly **need** GCS access — `bq query` against the materialized table gives us everything Anakin produces. GCS would just let us see the raw parquet files (file naming, upload timing, file size, etc.) and inspect Anakin's actual delivery cadence.

### What this changes vs my earlier conclusion

I was right that **the dataset name `googlesheet` is misleading** — it's not actually sourced from a Google Sheet anymore. It's a **GCS-backed BigQuery table** with a legacy dataset name.

What we still don't know:
- Exact bucket name (likely `samaan-backend`)
- File format Anakin uses (CSV? Parquet? JSON?)
- Whether files contain pre-mapped data or raw scrapes
- Anakin's actual scraping infrastructure
- How frequently Anakin updates (daily? hourly?)

What we DO know:
- The drop point is in Apna's GCS infrastructure (not Anakin's)
- Anakin has WRITE access to a specific path in Apna's bucket
- Apna's data team has set up the BQ load job from this path
- We can potentially get GCS read access from Apna's DevOps team to inspect Anakin's raw uploads

**Key facts:**

1. **The dataset name is `googlesheet`** — meaning these tables are BigQuery federated views over Google Sheets. The `cx_competitor_prices` table is sourced from a Google Sheet that Anakin pushes to. We see only the final output.

2. **Proof: Apna's analyst SQL** (from card 21286 "Anakin Coverage Base Data"):
   ```sql
   from `apna-mart-data.googlesheet.cx_competitor_prices` as c
   LEFT join smpublic.smpcm_product sp 
     on cast(c.item_code as int) = cast(sp.item_code as int)
   ```
   This is a **LEFT JOIN** on item_code — i.e., Anakin provides item_codes, Apna's analyst joins to enrich with Apna's own master data.

3. **Why values match:** Anakin uses the **same item_codes** that exist in Apna's `smpcm_product` (because someone at Apna gave them the SKU list). When Anakin populates Item_Name, Brand, etc., they likely get them from the same source — but we cannot verify HOW (could be: API, SFTP, manual upload, or scraping Apna's customer-facing site).

4. **Image_Link evidence:** All `Image_Link` URLs in `cx_competitor_prices` start with `https://storage.cloud.google.com/samaan-backend/product/product_<id>/<timestamp>-<item_code>_1.webp`. The `samaan-backend` GCS bucket is Apna's own, and filenames embed the `item_code`. So at minimum Anakin has access to Apna's image URLs (could be public URLs, or shared bucket access).

### Apna's `smpcm_product` table — used for ENRICHMENT, not as Anakin's source

`smpublic.smpcm_product` (table id `578`) is **Apna's own product master** with 116 columns. It is NOT Anakin's source — it's what Apna's analysts JOIN against to enrich Anakin's output.

| Apna's master table | `smpublic.smpcm_product` (table id `578`) |
|---|---|
| **Total SKUs** | 56,690 |
| **Active SKUs** | 54,884 |
| **Columns** | 116 (vs Anakin exposes only 5) |
| **Image bucket** | `samaan-backend` (Apna's own GCS) |

**Same item_code 11732 in both tables matches exactly:**

| Field | Anakin's `cx_competitor_prices` | Apna's `smpcm_product` | Match |
|---|---|---|---|
| Name | `7up 2.25 Ltr` | `7up 2.25 Ltr` | ✅ EXACT |
| Brand | `7 Up` | `7 Up` | ✅ EXACT |
| MRP | `90` | `90.0` | ✅ EXACT |
| Unit | `ltr` | `ltr` | ✅ EXACT |
| Unit_Value | `2.25` | `2.25` | ✅ EXACT |

But this match doesn't prove Anakin queries `smpcm_product` directly — it just proves Anakin's data is **derived from the same source** that Apna uses (i.e., the data ultimately originates in Apna's catalog).

### Implication for replacing Anakin

**Anakin's actual workflow is opaque to us, but it doesn't matter** — for replacement, we just need:
1. **Apna's SKU list** → directly from `smpublic.smpcm_product` (or Apna's API)
2. **Competitor scraping** → our 5 platform scrapers
3. **Mapping logic** → build our own (Apna SKU → competitor URL)
4. **Daily refresh** → cron job
5. **Output format** → Google Sheet / BigQuery / Excel

The "₹3 lakh/month for data" really pays for:
- (a) Anakin's hidden pipeline that connects Apna ↔ competitors
- (b) Daily price refresh automation

We can replace both ourselves.

### Other related tables found in `googlesheet` schema

| Table | ID | Status | Notes |
|---|---|---|---|
| `cx_competitor_prices` | 4742 | ✅ **Active** | Main Anakin feed (29 lakh rows) |
| `cx_competitor_prices_external` | 4745 | ⚠️ **Empty** | Reserved for secondary vendor |
| `pricing_blinkit` | 5841 | ❌ **Abandoned** | 1 NULL row only |
| `blinkit_price` | 1548 | 📦 **Historical** | 3,270 rows from 2024-11-20, has `am_item_codes` (Apna mapping) — looks like an old internal Apna scrape |
| `price_competitive_dashboard_base_query` | 6730 | — | 32 cols, joined view by Apna analyst |

The presence of `blinkit_price` (with `am_item_codes`) from Nov 2024 suggests **Apna had its own internal Blinkit scraping at some point** — and then switched/added Anakin. We could potentially revive that.

### Apna Product Master — Key Fields (`smpublic.smpcm_product`)

| Field | Type | Field ID | Notes |
|---|---|---|---|
| `id` | int | — | Primary key (different from item_code) |
| `item_code` | int | 7191 | **Apna SKU code** (same as in `cx_competitor_prices`) |
| `display_name` | text | 7118 | Product name |
| `brand` | text | 7113 | |
| `mrp` | float | 7158 | |
| `selling_price` | float | 7185 | **Apna's own selling price** (Anakin hides this!) |
| `wholesale_price` | float | — | |
| `unit` | text | 7176 | g / ml / kg / ltr / unit |
| `unit_value` | float | 7193 | numeric quantity |
| `pack_size` | text | — | "1 x 500g", "Pack of 6" etc. |
| `master_category` | text | 8935 | FMCGF / FMCGNF / GM |
| `product_type` | text | — | leaf category |
| `marketed_by` | text | 7133 | manufacturer/marketer |
| `bar_code` | text | — | EAN/UPC |
| `main_image` | text | 7149 | primary product image URL |
| `image_list` | json | — | full image list |
| `active` | bool | 7161 | currently sold |
| `is_food` | bool | — | |
| `food_type` | text | — | veg/non-veg/jain |
| `nutrition` | json | — | nutritional info |
| `ingredients` | text | — | |
| `gst_slab_id` | int | — | |
| `hsn_code` | text | — | |
| `gross_weight`, `length`, `breadth`, `height` | float | — | for logistics |

**Total: 116 columns.** Anakin only uses 5 of these.

### Apna's Other Useful Tables (Mirror Metabase)

| Table / Card | ID | Purpose |
|---|---|---|
| `smpublic.smpcm_product` | 578 | **Master product catalog** (54,884 active SKUs) |
| `vertexai.products` | 4868 | VertexAI search index for products |
| `Latest Samaan city level pricing - staples` | card 18769 | City-level pricing snapshots |
| `Latest Store-Stock pricing + Store Samaan ID` | card 3698 | Store stock + Samaan internal ID |
| `Tez Samaan Store IDs` | card 7986 | Store ID master |
| `product_id-item_code-name_master_category_product_type` | dataset 22960 | Joined master view |
| `Product Master` | dataset 1272 | Another product master view |



**Card URL** (Metabase UI): `https://mirror.apnamart.in/model/17551-anakin-competitor-prices`
- Note: Card 17551 returns 403 with our API key, but the underlying table 4742 is queryable.

---

## 2. Schema — All 47 Columns

### 2.1 Apna Mart's reference fields (from Anakin's catalog)

| Column | Field ID | Type | Example | Notes |
|---|---|---|---|---|
| `Date` | 138779 | text | `2026-04-11` | Snapshot date |
| `City` | 138755 | text | `Ranchi` | |
| `Pincode` | 138793 | text | `834002` | |
| `Item_Code` | 138778 | text | `11732` | **Apna Mart's internal SKU code** |
| `Item_Name` | 138790 | text | `7up 2.25 Ltr` | Apna's product name |
| `Brand` | 138754 | text | `7 Up` | |
| `Product_Type` | 138788 | text | `Clear Soft Drink` | Apna's category label |
| `Unit` | 138749 | text | `ltr`, `g`, `ml`, `kg`, `unit` | Unit of measure |
| `Unit_Value` | 138785 | text | `2.25`, `500`, `1` | Quantity in that unit |
| `Mrp` | 138772 | text | `90`, `nan`, `NA` | Apna's reference MRP (sometimes blank for fresh produce) |
| `Image_Link` | — | text | `https://storage.cloud.google.com/...` | |

### 2.2 Per-platform mapping fields (12 cols × 3 platforms = 36 cols)

For each of **Blinkit / Jiomart / Dmart**, there are 12 mirror columns:

| Suffix | Blinkit Field ID | Jiomart Field ID | Dmart Field ID | Description |
|---|---|---|---|---|
| `_Product_Url` | 138776 | 138771 | — | Direct PDP URL |
| `_Product_Id` | 138758 | 138752 | 138791 | Platform's internal product ID |
| `_Item_Name` | 138764 | 138756 | — | Name as it appears on the platform |
| `_Uom` | 138769 | 138784 | — | Unit string from platform (e.g., `2.25 ltr`) |
| `_Mrp_Price` | 138757 | 138766 | — | MRP shown on platform (often blank/NA) |
| `_Selling_Price` | 138774 | 138789 | 138792 | **Live selling price** |
| `_Discount__` | 138783 | 138747 | — | Discount % |
| `_Eta_Mins_` | 138780 | 138767 | — | Delivery ETA (mins) |
| `_In_Stock_Remark` | 138750 | 138748 | 138775 | `available`, `out_of_stock`, `NA` |
| `_Status` | 138753 | 138777 | 138751 | **Match status** (see §5) |
| `_Partial` | 138761 | 138762 | — | **Partial match reason** (see §6) |
| `_Factor` | 138770 | 138768 | — | **Pack-size normalization factor** (see §7) |

> **Note:** Dmart columns exist but most rows are NULL. Dmart is only available in select pincodes. For pincode `834002` (Ranchi), all 3,620 Dmart fields are NULL.

---

## 3. Platforms Tracked by Anakin

| Platform | Tracked? | Pincode 834002 Coverage |
|---|---|---|
| **Blinkit** | ✅ Yes | 2,364 / 3,620 (65%) |
| **Jiomart** | ✅ Yes | 2,512 / 3,620 (70%) |
| **Dmart** | ⚠️ Yes (column exists) | 0 / 3,620 (Ranchi nahi hai) |
| **Zepto** | ❌ NO | — |
| **Instamart** | ❌ NO | — |
| **Flipkart Minutes** | ❌ NO | — |
| **BigBasket** | ❌ NO | — |

**Implication:** Hamare paas already 5 quick-commerce platforms hain — Anakin se 2 zyada (Zepto, Instamart, Flipkart Min). Replacing Anakin = match Blinkit + Jiomart + Dmart at 99%, automatically gives us **wider coverage** than Anakin.

---

## 4. Cost Justification

| Metric | Value |
|---|---|
| **Anakin monthly fee** | ₹3,00,000 |
| **Annual** | ₹36,00,000 |
| **What we get** | 3 platforms × daily snapshots × ~3,600 SKUs × ~50 pincodes |
| **Estimated rows/day** | ~5.4 lakh rows |
| **Apna Mart team usage** | Pricing decisions for store ops |

---

## 5. Match Status — 4 Categories

The `Blinkit_Status` / `Jiomart_Status` field classifies each Apna SKU's match quality:

| Status | Count (Blinkit, pincode 834002) | Meaning |
|---|---|---|
| **Complete Match** | 1,699 (47%) | Brand + Pack Size + MRP all match perfectly |
| **Partial Match** | 1,470 (41%) | Match found, but ONE attribute differs (see §6 for reasons) |
| **Semi Complete Match** | 65 (2%) | Generic / private label substitute (e.g., "Sugar 1kg" → "Whole Farm Sugar 1kg") |
| **NA** | 384 (10%) | No match found in catalog |
| `partial Match` (typo) | 2 | Data quality issue — should be "Partial Match" |

**Jiomart distribution (834002):**
- Complete Match: 1,560 (43%)
- Partial Match: 924 (26%)
- Semi Complete: 27
- NA: 1,109 (31%)

---

## 6. Partial Match Reasons (`_Partial` field)

When Status = "Partial Match", the `_Partial` column tells us **why** it's only partial:

### Blinkit (pincode 834002):

| Reason | Count | Meaning |
|---|---|---|
| `NFNV-Product-Weight-Diff` | 1,078 | Same product, **different pack size** — uses `_Factor` to normalize |
| `MRP Diff` | 358 | Same product, **different MRP** between Apna catalog and platform |
| `NFNV-Container-Packing-Diff` | 15 | Same content, different bottle/pouch/box format |
| `FNV-UOM-Diff` | 7 | Fresh fruit/veg with different unit of measure (e.g., piece vs grams) |
| `NFNV-Combo-Weights` | 4 | Combo pack with weight per item differs |
| `NFNV-Graphics-Packing-Diff` | 3 | Same product, different label graphics |
| `Color Diff` | 2 | Color variant difference |
| `MRP-Diff` (with hyphen) | 2 | Same as `MRP Diff` (inconsistent labels) |
| `nan` | 1 | Data quality issue |

### Jiomart (pincode 834002):

| Reason | Count |
|---|---|
| `NFNV-Product-Weight-Diff` | 448 |
| `MRP Diff` | 435 |
| `NFNV-White-label` | 12 |
| `MRP DIFF` (uppercase) | 11 |
| `NFNV-Container-Packing-Diff` | 6 |

### Label legend:
- **NFNV** = Non-Fruit Non-Vegetable (i.e., packaged goods)
- **FNV** = Fruit & Vegetable (fresh produce)
- **UOM** = Unit of Measure

---

## 7. Factor Column — Pack Size Normalization 🔑

This is the **most important insight** for our matching algorithm.

When Anakin's product and the platform's product are **different pack sizes**, Anakin stores a `_Factor` to normalize the price for fair comparison.

### Formula:
```
Factor = anakin_unit_value / platform_unit_value
Normalized_platform_price = platform_price × Factor
```

### Real Examples (from pincode 834002):

| Anakin Product | Platform Product | Factor | Math Check |
|---|---|---|---|
| JK Jeera **50g** ₹44 | Blinkit **100g** ₹52 SP | **0.5** | 50/100 = 0.5 ✓ |
| Wheel Powder **500g** ₹39 | Blinkit **1kg** ₹76 | **0.5** | 500/1000 = 0.5 ✓ |
| Patanjali Hand Wash **750ml** ₹110 | Blinkit **200ml** | **3.75** | 750/200 = 3.75 ✓ |
| Oreo **108.55g** ₹26 | Blinkit **125.25g** ₹39 | **0.867** | 108.55/125.25 ≈ 0.867 ✓ |
| Drools Puppy **150g** ₹40 | Blinkit **6 × 150g** | **0.167** | 1/6 ≈ 0.167 ✓ |
| Ching's Paneer Chilli **20g** ₹10 | Blinkit **5 × 20g** ₹50 | **0.2** | 1/5 = 0.2 ✓ |
| Gillette Guard **8 pcs** ₹98 | Blinkit **6 pcs** | **1.333** | 8/6 ≈ 1.333 ✓ |

### Fair price comparison:
```
# To compare on apples-to-apples basis:
apna_price_per_unit = apna_mrp / apna_unit_value
platform_price_per_unit = platform_selling_price / platform_unit_value

# Or use Anakin's Factor:
normalized_price = platform_price × factor
delta = normalized_price - apna_mrp
```

---

## 8. Anakin's Matching Algorithm (Reverse Engineered)

Based on observed status/factor/partial values, Anakin's flow appears to be:

```
For each Apna SKU (Item_Code):
    1. Search competitor platform by:
       - Brand (mandatory)
       - Product_Type (helpful filter)
       - Item_Name fuzzy matching
    
    2. Find best candidate product on platform
       - If no candidate found → Status = "NA"
    
    3. Compare brands:
       - If brand mismatch + private label fallback exists → Status = "Semi Complete Match"
       - If brand mismatch entirely → Status = "NA"
    
    4. Compare pack size (Unit + Unit_Value):
       - Exact match → Factor = 1, no partial flag
       - Different size, same product family →
            Status = "Partial Match"
            _Partial = "NFNV-Product-Weight-Diff"
            _Factor = anakin_unit_value / platform_unit_value
       - Different UOM (kg vs unit, g vs piece) →
            _Partial = "FNV-UOM-Diff" or "NFNV-Combo-Weights"
    
    5. Compare MRP:
       - Match → no flag
       - Differ → _Partial += "MRP Diff" (or just "MRP Diff" if pack size matched)
    
    6. Compare container/packaging:
       - Different bottle/pouch/box → "NFNV-Container-Packing-Diff"
       - Different graphics only → "NFNV-Graphics-Packing-Diff"
    
    7. Compare color/variant:
       - Different color → "Color Diff"
    
    8. If all checks pass → Status = "Complete Match"

    9. Once matched, store the platform's:
       - Product_Url (PDP link)
       - Product_Id
       - Item_Name (as displayed on platform)
       - Uom (unit string from platform)
       - Selling_Price, Mrp_Price, Discount
       - In_Stock_Remark, Eta_Mins
```

### Daily refresh:
- Anakin re-runs this for every pincode every day
- Mapping (URL/Product_Id) is **cached and reused** — only prices/stock get refreshed
- New SKUs get manually mapped (likely human-in-the-loop QC)

---

## 9. Anakin's Weaknesses (Areas We Can Improve)

| Weakness | Evidence | Our Improvement |
|---|---|---|
| **Inconsistent labels** | `MRP-Diff`, `MRP Diff`, `MRP DIFF`, `partial Match` (typo) | Use enum constants, validation |
| **Limited platforms** | Only 3 (B/J/D) | We have 5+ already |
| **Stale mappings** | Some Product_Ids return NA prices (out of catalog) | Verify mapping freshness daily |
| **No image-based matching** | Pure text similarity | Optionally use product image hashing |
| **Factor computed but rarely used** | Many "Partial" rows have no useful price | Always compute fair price/unit |
| **`nan` values** | Data quality leak | Strict null handling |
| **Coverage gaps** | 10–30% NA per platform | Better discovery via search + category browse |
| **Manual mapping bottleneck** | Likely human-in-loop | Automate via brand+name+pack triple-key |

---

## 10. Data Type Quirks

⚠️ **Everything is `type/Text` in the table** — even numeric fields like `Mrp`, `Unit_Value`, `Selling_Price`, `Factor`. This is because the data is sourced from Google Sheets where Anakin uploads CSVs.

When parsing:
```python
def parse_num(v):
    if v is None or str(v).strip().lower() in ('', 'na', 'nan', 'null'):
        return None
    try:
        return float(str(v).replace(',', '').replace('₹', '').strip())
    except (ValueError, TypeError):
        return None
```

**`NA` literal vs NULL:**
- Most "missing" values are the literal string `"NA"`
- Some columns have actual `NULL` (e.g., Dmart fields when not applicable)
- Always check for both: `field IS NULL OR field = 'NA'`

---

## 11. Useful Metabase API Queries

### 11.1 Get total row count
```python
import json, urllib.request

API = "https://mirror.apnamart.in/api/dataset"
KEY = "<api_key>"  # from backend/.env

def query(mbql):
    req = urllib.request.Request(API, method="POST",
        headers={"x-api-key": KEY, "Content-Type": "application/json"},
        data=json.dumps(mbql).encode())
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())

# Total rows
r = query({"database":5, "type":"query", "query":{
    "source-table": 4742,
    "aggregation":[["count"]]}})
```

### 11.2 Filter by pincode + latest date
```python
r = query({"database":5, "type":"query", "query":{
    "source-table": 4742,
    "filter": ["and",
        ["=", ["field", 138793, None], "834002"],
        ["=", ["field", 138779, None], "2026-04-11"]],
    "limit": 100
}})
```

### 11.3 Get all Blinkit-mapped SKUs for a pincode
```python
r = query({"database":5, "type":"query", "query":{
    "source-table": 4742,
    "filter": ["and",
        ["=", ["field", 138793, None], "834002"],
        ["=", ["field", 138779, None], "2026-04-11"],
        ["!=", ["field", 138758, None], "NA"]],
    "fields": [
        ["field", 138778, None],  # Item_Code
        ["field", 138790, None],  # Item_Name
        ["field", 138754, None],  # Brand
        ["field", 138749, None],  # Unit
        ["field", 138785, None],  # Unit_Value
        ["field", 138772, None],  # Mrp
        ["field", 138776, None],  # Blinkit_Product_Url
        ["field", 138758, None],  # Blinkit_Product_Id
        ["field", 138764, None],  # Blinkit_Item_Name
        ["field", 138769, None],  # Blinkit_Uom
        ["field", 138757, None],  # Blinkit_Mrp_Price
        ["field", 138774, None],  # Blinkit_Selling_Price
        ["field", 138750, None],  # Blinkit_In_Stock_Remark
        ["field", 138753, None],  # Blinkit_Status
        ["field", 138761, None],  # Blinkit_Partial
        ["field", 138770, None],  # Blinkit_Factor
    ],
    "limit": 5000
}})
```

### 11.4 Get latest date for a pincode
```python
r = query({"database":5, "type":"query", "query":{
    "source-table": 4742,
    "filter": ["=", ["field", 138793, None], "834002"],
    "aggregation":[["max", ["field", 138779, None]]]
}})
latest_date = r['data']['rows'][0][0]
```

---

## 12. Plan to Replace Anakin

### Phase 1 — Validate Anakin's data with our scrapes (CURRENT)
- [ ] Pull Anakin's Blinkit data for one pincode → save locally
- [ ] Run our Price Benchmark Blinkit scrape for same pincode
- [ ] Compare: how many of Anakin's 2,364 mapped Blinkit SKUs do we find?
- [ ] Compare prices: where do they differ? Why?

### Phase 2 — Build matching algorithm
- [ ] Implement Status classification (Complete / Partial / Semi / NA)
- [ ] Implement Factor calculation
- [ ] Implement _Partial reason tagging
- [ ] Use brand + pack size + name fuzzy match for discovery

### Phase 3 — Improve coverage
- [ ] For Anakin's 384 NA Blinkit SKUs, can we find them?
- [ ] For Anakin's 1,109 NA Jiomart SKUs, can we find them?
- [ ] Achieve coverage ≥ Anakin's

### Phase 4 — Daily automation
- [ ] Cron-style daily snapshot per pincode
- [ ] Store results to Postgres / Google Sheet
- [ ] Notify pricing team of major deltas

### Phase 5 — Cancel Anakin
- [ ] Verify 99%+ accuracy for 4 weeks consecutive
- [ ] Migrate Apna pricing team to our dashboard
- [ ] Cancel Anakin contract → save ₹3 L/month

---

## 13. Reference: Sample Rows

### 13.1 Complete Match example
```
Item_Code: 3439
Item_Name: Himalaya Baby Powder 400g
Brand: Himalaya
Unit: g, Unit_Value: 400, Mrp: 302
Blinkit_Product_Id: 5039
Blinkit_Item_Name: (Himalaya Baby Powder) — exact match
Status: Complete Match
Partial: nan, Factor: 1
```

### 13.2 Partial Match (Weight Diff) example
```
Item_Code: 23183
Item_Name: Catch Ginger Garlic Paste 20g
Unit_Value: 20, Mrp: 5
Blinkit_Product_Id: 415627
Blinkit_Item_Name: Catch Ginger Garlic Paste (Blinkit shows 200g)
Status: Partial Match
Partial: NFNV-Product-Weight-Diff
Factor: 0.1   ← 20/200 = 0.1
```

### 13.3 Semi Complete Match (private label) example
```
Item_Code: ?
Item_Name: Sugar 1 Kg
Brand: (generic)
Blinkit_Item_Name: Whole Farm Grocery Sugar (Packet)
Status: Semi Complete Match
Partial: nan, Factor: 1
```

### 13.4 NA example
```
Item_Code: 97864
Item_Name: Shubhkart Darshana Chandan Tika 40g
Brand: Shubhkart
Blinkit_Product_Id: NA
Status: Complete Match (yes — Anakin sometimes marks NA-ID as Complete?? need investigation)
```

---

## 14. Open Questions / TODO Investigation

1. **Why does some `Status="Complete Match"` have `Product_Id="NA"`?** (e.g., Item_Code 97864) — possibly stale Status field from previous days
2. **What does `Semi Complete Match` exactly trigger on?** Is it always private-label substitution?
3. **Do mappings get re-validated daily** or are they cached forever once mapped?
4. **What's the difference between `cx_competitor_prices` and `cx_competitor_prices_external`?** Same schema, parallel feed — maybe internal vs vendor sources?
5. **Are there other tables with category mapping, manual override, etc.?**

---

## 15. File Locations in Our Codebase

| File | Purpose |
|---|---|
| `ANAKIN.md` | This file — reference doc |
| `backend/app/services/anakin_service.py` | **TODO** — Pull data from Mirror Metabase API |
| `backend/app/services/compare_service.py` | Existing compare logic — to be enhanced |
| `backend/.env` | API key storage — `METABASE_API_KEY=...` |
| `backend/app/scrapers/blinkit_scraper.py` | Our Blinkit scraper |

---

## 16. Read-Only Investigation Findings (2026-04-11)

This section documents findings from a deep, read-only investigation of Anakin's data — no modifications, no writes, pure decoding of HOW Anakin generates this data. Used direct BigQuery access via `bq query` (more powerful than Mirror's restricted query builder).

### 16.1 Scope — Anakin tracks much less than expected

Anakin tracks **only 4 cities, 1 pincode each:**

| City | Pincode | SKUs | Blinkit | Jiomart | Dmart |
|---|---|---|---|---|---|
| Kolkata | (1 pincode) | 4,125 | 2,364 | 2,831 | **0** |
| Raipur | (1 pincode) | 4,215 | 2,364 | 2,623 | **0** |
| Ranchi | 834002 | 4,103 | 2,364 | 2,512 | **0** |
| **Hazaribagh** | (1 pincode) | 3,750 | 2,364 | **0** | **0** |
| **Total** | 4 pincodes | 4,267 distinct | 2,364 distinct | 2,831 distinct | **0** |

**Critical observations:**
1. **Dmart is COMPLETELY EMPTY** across all 4 cities — column exists but Anakin has never delivered Dmart data
2. **Hazaribagh only gets Blinkit** (no Jiomart, no Dmart)
3. **Blinkit count is exactly 2,364 in EVERY city** — meaning Anakin uses ONE Blinkit mapping list and applies it universally (not per-city mapping)
4. Date range: 2025-08-02 to 2026-04-11 (~8 months / 253 days)
5. Total rows: 29,33,242

**₹3 lakh/month gives Apna:** Blinkit + Jiomart in 3 cities + Blinkit only in Hazaribagh. That's it.

### 16.2 SKU coverage — only 6.9% of Apna's catalog

| Metric | Value |
|---|---|
| Apna active SKUs (`smpcm_product`) | 54,891 |
| Anakin tracked SKUs | 3,801 distinct |
| **Coverage** | **6.9%** |

Anakin tracks the **top sellers / KVI subset** — not the full catalog. Of Anakin's 3,801 SKUs:
- 100% exist in Apna's master
- 100% are active in Apna
- 0 orphans

### 16.3 Category-wise coverage

| master_category | Anakin SKUs | Apna active | Coverage | Note |
|---|---|---|---|---|
| **FMCGF** (Food & Beverages) | 1,380 | 13,955 | 9.9% | Main focus |
| **FMCGNF** (Non-Food FMCG) | 1,183 | 14,582 | 8.1% | Personal care, cleaning |
| **STPLS** (Staples) | 721 | 8,091 | 8.9% | Atta, dal, oil, rice |
| **GM** (General Merch) | 257 | 15,899 | **1.6%** | Anakin barely tracks (utensils, electronics) |
| **FRESH** (Produce) | 164 | 547 | 30.0% | Limited universe |
| **BDF** (Bread/Dairy/Frozen) | 96 | 1,781 | 5.4% | |

**Insight:** Anakin focuses on **FMCG categories where competitor pricing matters** — quick commerce mostly competes on packaged FMCG, not on utensils. GM is intentionally ignored.

### 16.4 SKU overlap across cities

| Tracked in N cities | SKU count | % |
|---|---|---|
| All 4 | 3,236 | 85% |
| 3 | 344 | 9% |
| 2 | 104 | 3% |
| 1 | 117 | 3% |

Core 3,236 SKUs are tracked everywhere. The 117 city-specific SKUs are likely local/regional brands (sweets, pickles, fresh produce variants).

### 16.5 Match Status logic — DECODED

Anakin classifies each Apna→Blinkit mapping into 4 status buckets:

```
if no_blinkit_candidate_found:
    Status = "NA"
elif brand_substituted_with_private_label:
    Status = "Semi Complete Match"
    # e.g., "Sugar 1kg" → "Whole Farm Sugar 1kg" (Blinkit's house brand)
elif brand_matches and product_matches:
    if FRESH produce (FNV):
        Status = "Complete Match"
        Factor = pack_ratio  # even with size diff, fresh = same product
    elif pack_size matches AND mrp matches:
        Status = "Complete Match"
        Factor = 1
    elif pack_size differs:
        Status = "Partial Match"
        _Partial = "NFNV-Product-Weight-Diff"
        Factor = apna_uv / blinkit_uv (with multipack handling)
    elif mrp differs:
        Status = "Partial Match"
        _Partial = "MRP Diff"
        Factor = 1
    elif container/packaging differs:
        _Partial = "NFNV-Container-Packing-Diff"
    elif color differs:
        _Partial = "Color Diff"
```

**Confirmed Complete Match factor distribution (Ranchi, latest date):**
- 1,640 (96%) have factor = 1
- 7 have NULL factor
- 22 have non-1 factors (mostly fresh produce with size differences)
- **2 rows have `#VALUE!` errors** — proof Anakin uses **Excel/Sheets** in their pipeline (Excel formula error leaked through)

### 16.6 Partial Match reasons (Blinkit, Ranchi)

| Reason | Count | Meaning |
|---|---|---|
| `NFNV-Product-Weight-Diff` | 1,078 | Pack size differs (uses Factor) |
| `MRP Diff` | 358 | MRP value differs |
| `NFNV-Container-Packing-Diff` | 15 | Different bottle/pouch/box |
| `FNV-UOM-Diff` | 7 | Fresh produce UOM mismatch (kg vs piece) |
| `NFNV-Combo-Weights` | 4 | Combo pack with item count diff |
| `NFNV-Graphics-Packing-Diff` | 3 | Same product, different label graphics |
| `Color Diff` | 2 | Color variant |
| `MRP-Diff` | 2 | Inconsistent label (should be `MRP Diff`) |
| `nan` | 1 | Data quality issue |

### 16.7 MRP-Diff threshold

**No fixed threshold** — Anakin tags `MRP Diff` if MRPs are not strictly equal. Even ₹3 / 3% diff triggers it. Examples:

| Apna MRP | Blinkit MRP | Diff | Note |
|---|---|---|---|
| 70 | 75 | 7% | Tagged |
| 190 | 195 | 3% | Tagged |
| 138 | 165 | 20% | Tagged |
| 159 | 324 | **104%** | Tagged — but this is a WRONG mapping (different Horlicks variant) |

### 16.8 Factor formula — NOT pure division

**Most factors** = `apna_unit_value / blinkit_unit_value` (95% of cases)

**But edge cases handled differently:**

| Apna | Blinkit | Anakin Factor | Pure formula | Verdict |
|---|---|---|---|---|
| Colgate 81g | 150g | 0.54 | 81/150 ✅ | Pure |
| Joy Shampoo 650ml | 340ml | 1.911 | 650/340 ✅ | Pure |
| Cadbury Dairy Milk 40g | 46g | 0.870 | 40/46 ✅ | Pure |
| Bhelpuri 270g | **2 × 270g** | **0.5** | pack count = 1/2 | Multipack handled |
| Joy Soap **5 × 100g** | 4 × 100g | 1.25 | 5/4 = 1.25 | Multipack handled |
| Top Ramen 40g | 240g | 0.208 | 40/192 (not 240) | **Manual override** |
| Cadbury Chocobakes 18g | 126.5g | 0.083 | 1/12 (12-pack assumption) | **Manual override** |
| Kurkure 28g | 58g | 0.538 | 28/52 (not 58) | **Manual override** |

**Decoded:** Anakin's factor calculation is mostly pure division but uses:
1. **Unit conversion** (g↔kg, ml↔L)
2. **Multipack pattern recognition** (`N x M unit`, `Pack of N`, `Buy 1 Get 1`)
3. **Internal product weight database** that overrides displayed Uom (e.g., they know real net weight)
4. **Manual overrides** for ~5% of edge cases (likely human review)

### 16.9 Mapping stability over time

For pincode 834002 across all dates:

| Distinct Blinkit IDs per Item_Code | Item count | % |
|---|---|---|
| 1 (never remapped) | 913 | 28% |
| **2 (remapped once)** | **2,352** | **72%** |
| 3 (remapped twice) | 115 | 4% |
| 4+ | 28 | 1% |

→ **Most items get remapped at least once during 8 months.** Suggests Anakin runs **periodic re-validation** — perhaps a bulk re-mapping event or continuous QC corrections.

### 16.10 Update cadence

- **Anakin pushes new data daily at ~11:00 AM IST** (confirmed by Satyam — internal knowledge)
- BigQuery scheduled query (`scheduled_query_69e21dbb-...`) materializes the external table at **05:30 IST** — but this snapshot is from PREVIOUS day's parquet upload (since Anakin pushes at 11 AM, the 05:30 snapshot picks up yesterday's file)
- Apna pricing team consumes data after 11 AM each day
- Sample: Item_Code 11732 (7up 2.25L) in Ranchi — same selling price (₹96) for 10+ consecutive days → most daily refreshes are no-ops, values change only when actual market price changes

**Implication for SAM schedule:** We should target **before 11 AM IST daily** for our own scrape, so Apna team can compare side-by-side with Anakin's data on the same day.

### 16.11 Top brands tracked (Ranchi)

| Rank | Brand | SKUs |
|---|---|---|
| 1 | **ASM** | 108 (likely Apna's private label) |
| 2 | Patanjali | 88 |
| 3 | Amul | 70 |
| 4 | Haldiram's | 62 |
| 5 | Colgate | 46 |
| 6 | Everest | 44 |
| 7 | Himalaya | 40 |
| 8 | JK | 32 |
| 9 | Ching's | 31 |
| 10 | Nivea | 30 |

These are the top FMCG brands in India — Anakin's selection makes commercial sense.

### 16.12 Data quality issues found

1. **`#VALUE!` errors** in `Blinkit_Factor` — confirms Excel-based pipeline
2. **Inconsistent labels** — `MRP Diff`, `MRP-Diff`, `MRP DIFF` (3 different spellings)
3. **`partial Match`** (lowercase typo) — 2 occurrences
4. **`nan` literal string** in `_Partial` — 1 occurrence
5. **Wrong mappings:**
   - "Horlicks Chocolate Delight 400g" → "Horlicks Women's Plus Chocolate Drink Mix" (different SKUs, MRP diff 104%)
   - "Bella Vita Gift Set 4-pack" → "Bella Vita Organic Luxury Perfume Gift Set" (possibly different products)
6. **NULL factors** in 7 Complete Match rows (should always have a value)
7. **Some "Complete Match" rows have `Product_Id = NA`** — stale data leak

### 16.13 What we now KNOW about Anakin's algorithm

```
INPUT:
  - Apna's SKU master (item_code, item_name, brand, unit, unit_value, mrp)
  - Specific filter: top 6.9% of Apna's catalog (3,801 SKUs)
  - Specific cities: 4 (Kolkata, Raipur, Ranchi, Hazaribagh)

PIPELINE:
  1. Get pre-curated SKU mapping table (Apna_item_code → Blinkit_product_id)
     - This is built once + updated periodically (most SKUs remapped once in 8 months)
     - Same Blinkit IDs reused across all cities (not per-city mapping)
  
  2. For each (Apna SKU × City) combo:
     a. Visit cached Blinkit_Product_Url → scrape live MRP, SP, stock, ETA
     b. Compare with Apna's reference data (brand, pack, MRP)
     c. Apply Status classification rules (Complete/Partial/Semi/NA)
     d. Compute Factor for pack-size normalization (with multipack overrides)
     e. Tag _Partial reason if not Complete
  
  3. Daily output:
     - Generate parquet file: apnamart_anakin_delivery_<timestamp>.parquet
     - Upload to gs://cx_competitor_prices/anakin_raw_data/
     - Apna's BQ scheduled query (05:30 IST) materializes into cx_competitor_prices

QUALITY:
  - Mostly automated but with manual overrides + Excel intermediate steps
  - Some bad mappings persist (MRP diff 100%+)
  - Many "stale" entries where Blinkit price/stock returns NA
```

### 16.14 Open questions still unanswered

1. **Where does Anakin get the SKU list?** Is it API/SFTP from Apna, or scraped from apna's customer-facing site?
2. **How is the initial mapping built?** Pure fuzzy match? Manual? Image-based?
3. **What's the source of "internal product weight database"** that overrides displayed Uom?
4. **Why is `cx_competitor_prices_external` populated daily but the materialization is just `SELECT *`?** (Cost optimization for downstream queries?)
5. **Does Anakin track any data we don't see?** (e.g., review scores, new product detection)
6. **What's the SLA?** What time of day does Anakin upload?
7. **Why is Hazaribagh missing Jiomart?** (Probably Jiomart doesn't deliver there, but worth confirming)

### 16.15 Useful BigQuery commands for further investigation

```bash
# Direct BQ query (more powerful than Mirror)
bq query --use_legacy_sql=false 'SELECT ... FROM `apna-mart-data.googlesheet.cx_competitor_prices` LIMIT 10'

# Check job history (find scheduled queries, their owners)
bq query --use_legacy_sql=false '
SELECT creation_time, user_email, job_id, query
FROM `apna-mart-data.region-asia-south1.INFORMATION_SCHEMA.JOBS_BY_PROJECT`
WHERE destination_table.table_id = "cx_competitor_prices"
ORDER BY creation_time DESC LIMIT 5'

# Inspect external table source
bq show --format=prettyjson apna-mart-data:googlesheet.cx_competitor_prices_external

# Apna product master (read-only via BQ)
bq query --use_legacy_sql=false '
SELECT id, item_code, display_name, brand, mrp, selling_price, unit, unit_value, master_category
FROM smpublic.smpcm_product
WHERE item_code = 11732 LIMIT 5'
```

---

_Last updated: 2026-04-11 — comprehensive read-only investigation of Anakin's data structure, scope, algorithm, and quality. NO data modified — purely decoded._

