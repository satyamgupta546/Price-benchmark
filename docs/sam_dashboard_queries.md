# SAM Dashboard — Mirror Queries (Updated with DMart + 6 Cities)

Create these as "New Question" → "Native query" on https://mirror.apnamart.in
Database: **Apna Data Warehouse**

Then add all to a new Dashboard named **"SAM Price Benchmark"**

---

## Card 1: Daily Coverage Overview (Table)
```sql
SELECT 
  date, city, pincode,
  COUNT(*) as total_products,
  COUNTIF(blinkit_sp IS NOT NULL) as blinkit_priced,
  COUNTIF(jio_sp IS NOT NULL) as jio_priced,
  COUNTIF(blinkit_status = 'COMPLETE MATCH') as blinkit_complete,
  COUNTIF(blinkit_status = 'PARTIAL MATCH') as blinkit_partial,
  COUNTIF(jio_status = 'COMPLETE MATCH') as jio_complete,
  COUNTIF(jio_status = 'PARTIAL MATCH') as jio_partial,
  ROUND(COUNTIF(blinkit_sp IS NOT NULL) * 100.0 / COUNT(*), 1) as blinkit_coverage_pct,
  ROUND(COUNTIF(jio_sp IS NOT NULL) * 100.0 / COUNT(*), 1) as jio_coverage_pct
FROM `apna-mart-data.googlesheet.sam_price_history`
WHERE date = (SELECT MAX(date) FROM `apna-mart-data.googlesheet.sam_price_history`)
GROUP BY 1, 2, 3
ORDER BY city
```

## Card 2: Blinkit Match Status (Pie Chart)
```sql
SELECT blinkit_status as status, COUNT(*) as count
FROM `apna-mart-data.googlesheet.sam_price_history`
WHERE date = (SELECT MAX(date) FROM `apna-mart-data.googlesheet.sam_price_history`)
  AND blinkit_status IS NOT NULL
GROUP BY 1 ORDER BY 2 DESC
```

## Card 3: Jiomart Match Status (Pie Chart)
```sql
SELECT jio_status as status, COUNT(*) as count
FROM `apna-mart-data.googlesheet.sam_price_history`
WHERE date = (SELECT MAX(date) FROM `apna-mart-data.googlesheet.sam_price_history`)
  AND jio_status IS NOT NULL
GROUP BY 1 ORDER BY 2 DESC
```

## Card 4: Coverage Trend Daily (Line Chart)
```sql
SELECT 
  date,
  ROUND(COUNTIF(blinkit_sp IS NOT NULL) * 100.0 / COUNT(*), 1) as blinkit_pct,
  ROUND(COUNTIF(jio_sp IS NOT NULL) * 100.0 / COUNT(*), 1) as jio_pct,
  ROUND(COUNTIF(blinkit_status = 'COMPLETE MATCH') * 100.0 / COUNT(*), 1) as blinkit_complete_pct,
  ROUND(COUNTIF(jio_status = 'COMPLETE MATCH') * 100.0 / COUNT(*), 1) as jio_complete_pct
FROM `apna-mart-data.googlesheet.sam_price_history`
GROUP BY 1 ORDER BY 1
```

## Card 5: Top Price Differences (Table)
```sql
SELECT 
  item_code, item_name, brand, am_mrp, blinkit_sp, blinkit_mrp, blinkit_name,
  ROUND(ABS(blinkit_sp - am_mrp) / NULLIF(am_mrp, 0) * 100, 1) as diff_pct
FROM `apna-mart-data.googlesheet.sam_price_history`
WHERE date = (SELECT MAX(date) FROM `apna-mart-data.googlesheet.sam_price_history`)
  AND blinkit_sp IS NOT NULL AND am_mrp IS NOT NULL AND am_mrp > 0
ORDER BY diff_pct DESC
LIMIT 50
```

## Card 6: Brand-wise Coverage (Table)
```sql
SELECT 
  brand,
  COUNT(*) as total,
  COUNTIF(blinkit_sp IS NOT NULL) as blinkit,
  COUNTIF(jio_sp IS NOT NULL) as jiomart,
  ROUND(COUNTIF(blinkit_sp IS NOT NULL) * 100.0 / COUNT(*), 0) as blinkit_pct,
  ROUND(COUNTIF(jio_sp IS NOT NULL) * 100.0 / COUNT(*), 0) as jio_pct
FROM `apna-mart-data.googlesheet.sam_price_history`
WHERE date = (SELECT MAX(date) FROM `apna-mart-data.googlesheet.sam_price_history`)
GROUP BY 1
HAVING COUNT(*) >= 5
ORDER BY total DESC
LIMIT 50
```

## Card 7: City-wise Daily Summary (Table)
```sql
SELECT 
  date, city,
  COUNT(*) as products,
  COUNTIF(blinkit_status = 'COMPLETE MATCH') as blinkit_complete,
  COUNTIF(blinkit_status = 'PARTIAL MATCH') as blinkit_partial,
  COUNTIF(blinkit_status = 'NA') as blinkit_na,
  COUNTIF(jio_status = 'COMPLETE MATCH') as jio_complete,
  COUNTIF(jio_status = 'PARTIAL MATCH') as jio_partial,
  COUNTIF(jio_status = 'NA') as jio_na
FROM `apna-mart-data.googlesheet.sam_price_history`
GROUP BY 1, 2
ORDER BY 1 DESC, 2
```

## Card 8: Full Data (with date filter)
```sql
SELECT *
FROM `apna-mart-data.googlesheet.sam_price_history`
WHERE date = {{date}}
ORDER BY item_code
```
*(Add a Date filter parameter named `date`)*
