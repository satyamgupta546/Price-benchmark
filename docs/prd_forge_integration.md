# PRD: SAM × Forge Integration

## Overview
SAM ka data BigQuery mein hai. Forge se ClickHouse mein sync karenge for fast dashboards + API access. Daily automated pipeline.

---

## Master Tool: `mcp__claude_ai_Forge__job`

### Actions Available
| Action | Purpose | When to Use |
|--------|---------|-------------|
| `create` | New scheduled job | Setup time |
| `describe` | Job details + config | Debugging |
| `list` | All jobs in project | Overview |
| `run` | Manual immediate trigger | Testing / re-run |
| `queue` | Queue for next scheduler tick | Soft trigger |
| `history` | Past run results | Debugging failures |
| `progress` | Check running job | Monitor live |
| `pause` | Stop schedule temporarily | Maintenance |
| `resume` | Restart paused job | After maintenance |
| `delete` | Remove job permanently | Cleanup |

### Job Types
| Type | What it Does | Our Use |
|------|-------------|---------|
| `incremental` | BQ→CH with high-water mark (HWM), only new rows | `sam_price_history` sync |
| `full` | BQ→CH full snapshot (replace) | `sam_price_live` sync |
| `view` | Creates a CH view | Derived metrics |
| `http` | Calls external URL on schedule | Trigger scraper (future) |
| `pipeline` | SQL → Forge entity table | Transform + store |

### Schedule Config
```json
{
  "schedule": {
    "run_every_mins": 1440   // 24 hours = daily
  }
}
```
Other options: `60` (hourly), `720` (12h), `10080` (weekly)

---

## Sub Tools

### 1. Tables (`mcp__claude_ai_Forge__table`)

#### Table Types
| Type | Engine | Behavior | Our Use |
|------|--------|----------|---------|
| `entity` | ReplacingMergeTree | Upsert by key (latest wins) | `sam_price_live` |
| `log` | MergeTree | Append only, never delete | `sam_price_history` |
| `snapshot` | ReplacingMergeTree | Full replace per partition | Alternative for live |
| `history` | MergeTree | All versions tracked | Audit trail |

#### Operations
| Operation | Method | Purpose |
|-----------|--------|---------|
| `save` | PUT | Create/update table definition |
| `publish` | POST | Create CH table from definition (draft → active) |
| `insert-rows` | POST | Batch insert rows |
| `upsert-rows` | PATCH | Partial update by key |
| `read-rows` | GET | Read with filters |
| `truncate` | POST | Clear all data (2-step confirm) |
| `delete` | DELETE | Drop table entirely (2-step confirm) |

### 2. Saved Queries (`mcp__claude_ai_Forge__view`)

#### Features
| Feature | Detail |
|---------|--------|
| Engine | `clickhouse` or `bigquery` |
| Variables | Typed params: `string`, `number`, `date`, `boolean`, `string[]` |
| Caching | 5 min default, `?fresh=true` bypasses |
| Versioning | Auto-archives on update |
| Tags | Categorize queries (e.g., `sam`, `pricing`, `daily`) |

#### Operations
| Operation | Purpose |
|-----------|---------|
| `save` | Create/update SQL query |
| `run` | Execute with variable substitution |
| `preview` | Render SQL without executing |
| `enrich` | Update metadata (tags, description) |
| `delete` | Remove query |

### 3. Database (Raw SQL)
| Endpoint | Purpose |
|----------|---------|
| `POST /api/query/clickhouse` | Raw CH read-only query |
| `POST /api/query/bigquery` | Raw BQ read-only query |
Rate limit: 100 queries/min

---

## Data Schema

### Table 1: `sam_price_live` (Entity — upsert by pincode+item_code)

```
Forge Table Definition:
  slug: sam-price-live
  table_type: entity
  upsert_key: (pincode, item_code)
  order_by: (pincode, item_code)
```

| Column | CH Type | Description |
|--------|---------|-------------|
| date | Date | Scrape date |
| time | DateTime64(6, 'UTC') | Scrape timestamp |
| city | String | City name |
| pincode | String | Pincode |
| item_code | UInt32 | Apna Mart item code |
| item_name | String | AM product name |
| master_cat | String | STPLS/FMCG/FMCGNF/GM |
| brand | String | Brand |
| marketed_by | String | Manufacturer |
| product_type | String | Product type |
| unit | String | Unit (g/kg/ml/pc) |
| unit_value | Float64 | Unit numeric value |
| am_mrp | Float64 | AM latest inward MRP |
| image_link | String | Product image URL |
| blinkit_url | String | Blinkit product URL |
| blinkit_name | String | SAM scraped Blinkit name |
| blinkit_unit | String | Blinkit unit |
| blinkit_mrp | Float64 | Blinkit MRP |
| blinkit_sp | Float64 | Blinkit selling price |
| blinkit_stock | String | available/out_of_stock |
| blinkit_status | String | COMPLETE/SEMI/PARTIAL/NA |
| jio_url | String | Jiomart product URL |
| jio_name | String | SAM scraped Jiomart name |
| jio_unit | String | Jiomart unit |
| jio_mrp | Float64 | Jiomart MRP |
| jio_sp | Float64 | Jiomart selling price |
| jio_stock | String | available/out_of_stock |
| jio_status | String | COMPLETE/SEMI/PARTIAL/NA |

### Table 2: `sam_price_history` (Log — append only)

```
Forge Table Definition:
  slug: sam-price-history
  table_type: log
  order_by: (date, pincode, item_code)
  partition_by: toYYYYMM(date)
```

Same 28 columns as live. Partitioned by month for fast date-range queries.

---

## Jobs

### Job 1: `sam-sync-live` (BQ → CH live table)
```yaml
Type: full
Schedule: every 1440 min (daily, after scraper pushes to BQ)
Source: BigQuery — apna-mart-data.googlesheet.sam_price_live
Destination: ClickHouse — sam-price-live (entity table)
Strategy: full snapshot (replace entire table)
```

**SQL:**
```sql
SELECT
  date, time, city, pincode, item_code, item_name, master_cat, brand,
  marketed_by, product_type, unit, unit_value, am_mrp, image_link,
  blinkit_url, blinkit_name, blinkit_unit, blinkit_mrp, blinkit_sp,
  blinkit_stock, blinkit_status,
  jio_url, jio_name, jio_unit, jio_mrp, jio_sp, jio_stock, jio_status
FROM `apna-mart-data.googlesheet.sam_price_live`
```

### Job 2: `sam-sync-history` (BQ → CH history table)
```yaml
Type: incremental
Schedule: every 1440 min (daily)
Partition Column: date
Source: BigQuery — apna-mart-data.googlesheet.sam_price_history
Destination: ClickHouse — sam-price-history (log table)
Strategy: append (HWM = date, only fetch new dates)
```

**SQL:**
```sql
SELECT
  date, time, city, pincode, item_code, item_name, master_cat, brand,
  marketed_by, product_type, unit, unit_value, am_mrp, image_link,
  blinkit_url, blinkit_name, blinkit_unit, blinkit_mrp, blinkit_sp,
  blinkit_stock, blinkit_status,
  jio_url, jio_name, jio_unit, jio_mrp, jio_sp, jio_stock, jio_status
FROM `apna-mart-data.googlesheet.sam_price_history`
WHERE date >= '${start_date}' AND date <= '${end_date}'
```

### Job 3: `sam-coverage-daily` (Derived view — daily coverage stats)
```yaml
Type: view
Schedule: every 1440 min
Source: ClickHouse — sam-price-live
```

**SQL:**
```sql
SELECT
  date, city, pincode,
  count() as total_products,
  countIf(blinkit_sp > 0) as blinkit_priced,
  countIf(jio_sp > 0) as jio_priced,
  countIf(blinkit_status = 'COMPLETE MATCH') as blinkit_complete,
  countIf(blinkit_status = 'PARTIAL MATCH') as blinkit_partial,
  countIf(jio_status = 'COMPLETE MATCH') as jio_complete,
  countIf(jio_status = 'PARTIAL MATCH') as jio_partial,
  round(countIf(blinkit_sp > 0) * 100.0 / count(), 1) as blinkit_coverage_pct,
  round(countIf(jio_sp > 0) * 100.0 / count(), 1) as jio_coverage_pct
FROM kinetic.homepage__sam_price_live FINAL
GROUP BY date, city, pincode
ORDER BY city
```

---

## Caching & Invalidation

| What | Cache TTL | Invalidation |
|------|-----------|-------------|
| Table definitions | 24h | Auto on PUT/publish |
| Saved queries | 24h | Auto on PUT |
| Query results | 5 min | `?fresh=true` param |
| Read rows | 24h | Auto on insert/upsert |
| Job contract list | 24h | Auto on create/update |

### Manual Invalidation
- Query run: `POST /queries/:slug/run?fresh=true`
- Table re-read: Automatically invalidated on write operations

---

## Run History & Monitoring

### Per Job
| API | What |
|-----|------|
| `history` action | List past runs (status, duration, rows, errors) |
| `progress` action | Current running job status |
| Last run: from `history` | `runs[0].completed_at` |
| Next run: from `describe` | `job.next_run_at` (calculated from schedule + last run) |

### Scheduler Health
| API | What |
|-----|------|
| `GET /api/scheduler/health` | Active status, config, currently running job |
| `GET /api/scheduler/runs` | All runs across all jobs |
| `GET /api/scheduler/runs/:id/logs` | Structured logs for a specific run |

### Run States
```
QUEUED → RUNNING → COMPLETED
                 → FAILED (retry with backoff: 5m, 10m, 20m)
```
Max retries: 3 (configurable)

---

## Domains Summary

| Domain | Prefix | Purpose | Our Use |
|--------|--------|---------|---------|
| **Scheduler** | `/api/scheduler` | Jobs, contracts, runs | BQ→CH sync jobs |
| **Forge Tables** | `/api/projects/:project/tables` | Managed CH tables | sam_price_live/history |
| **Saved Queries** | `/api/projects/:project/queries` | SQL templates | Dashboard queries |
| **Database** | `/api/query` | Raw SQL execution | Ad-hoc queries |

---

## Implementation Steps

### Phase 1: Create Tables
1. Create `sam-price-live` entity table in Forge
2. Create `sam-price-history` log table in Forge
3. Publish both (draft → active)

### Phase 2: Create Jobs
1. Create `sam-sync-live` job (full, daily)
2. Create `sam-sync-history` job (incremental, daily)
3. Test both with manual `run` action

### Phase 3: Create Saved Queries
1. Live dashboard query (with date/city filters)
2. History trend query (date range)
3. Coverage summary query
4. Brand-wise coverage query

### Phase 4: Verify
1. Run jobs manually, check CH data
2. Query results match BQ source
3. Schedule active, verify next day auto-run
4. History table growing daily

---

## What's Needed from User

| Item | Status |
|------|--------|
| Forge project access (which project to use?) | ❓ Need to confirm |
| Server for scraper (Invictus/VPS?) | ❓ Need to confirm |
| Model 1344 access (ASM/LOOSE tagging) | ❓ Currently 403 |
| Slack webhook for alerts | ❓ Optional |
| More cities/platforms (Zepto, Instamart, Flipkart) | ❓ Future scope |
