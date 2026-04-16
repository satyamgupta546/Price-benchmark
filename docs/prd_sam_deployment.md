# PRD: SAM Price Benchmark — Deployment & Automation

## Goal
SAM ko fully automated deploy karna hai — daily 10:30 AM IST pe 4 cities ka Blinkit + Jiomart price scrape, BigQuery push, Mirror dashboard pe live data.

---

## Architecture

```
┌─────────────────┐     ┌──────────────┐     ┌─────────────┐     ┌──────────────┐
│  Server (VPS)   │────▶│  BigQuery    │────▶│  Forge/CH   │────▶│   Mirror     │
│  Cron 10:30 AM  │     │  sam_price_  │     │  (optional) │     │  Dashboard   │
│  Python+Playwright│    │  live/history│     │             │     │              │
└─────────────────┘     └──────────────┘     └─────────────┘     └──────────────┘
```

---

## Requirements

### 1. Server (Scraper Host)
| Requirement | Detail |
|-------------|--------|
| OS | Ubuntu 20.04+ / Debian |
| Python | 3.11+ |
| Playwright | Chromium + Firefox browsers |
| RAM | 4GB minimum (2 browsers parallel) |
| Disk | 10GB free |
| Network | Open outbound to blinkit.com, jiomart.com, mirror.apnamart.in |
| gcloud CLI | Authenticated with `satyam.gupta@apnamart.in` |
| bq CLI | For BigQuery push |
| Cron | System crontab |
| Uptime | 24/7 (or at least 10:00-12:00 AM daily) |

### 2. Setup Commands (on server)
```bash
# Clone repo
git clone https://github.com/satyamgupta546/Price-benchmark.git
cd Price-benchmark

# Python venv
python3 -m venv backend/venv
backend/venv/bin/pip install playwright openpyxl
backend/venv/bin/python -m playwright install chromium firefox

# gcloud auth
gcloud auth login satyam.gupta@apnamart.in
gcloud config set project apna-mart-data

# Environment
export METABASE_API_KEY="mb_rJuZYiQLgCMDOhoJkEVDq2+0AhAlLxgAk8TVfY7mlms="

# Cron
chmod +x scripts/sam_cron.sh
crontab -e
# Add: 30 10 * * * /path/to/Price-benchmark/scripts/sam_cron.sh >> /path/to/Price-benchmark/logs/sam_cron.log 2>&1

# Test run
backend/venv/bin/python scripts/sam_daily_run.py 834002
```

---

## Forge Integration

### Master Tool: `mcp__claude_ai_Forge__job`

| Action | Purpose |
|--------|---------|
| `create` | Create new scheduled job |
| `list` | List all jobs |
| `describe` | Get job details |
| `run` | Trigger manual run |
| `queue` | Queue for next tick |
| `history` | View past runs |
| `progress` | Check running job status |
| `pause` | Pause scheduled job |
| `resume` | Resume paused job |
| `delete` | Delete job |

### Sub Tools

#### Jobs (Scheduler)
| Feature | Detail |
|---------|--------|
| **Type: HTTP** | Calls external URL (our scraper API) on schedule |
| **Type: SQL** | Runs BigQuery SQL on schedule |
| **Type: Pipeline** | SQL output → Forge managed table |
| **Schedule** | `run_every_mins: 1440` (24 hours = daily) |
| **Depends On** | Chain jobs — scrape → transform → push |

#### Tables (Forge Managed)
| Feature | Detail |
|---------|--------|
| **Entity Table** | ReplacingMergeTree — upsert by key |
| **Log Table** | MergeTree — append only (history) |
| **Schema** | Typed columns, validation rules, FKs |
| **Track History** | Auto-tracks row changes |

#### Caching
| Feature | Detail |
|---------|--------|
| Cache TTL | Configurable per table/query |
| Invalidate | On data write or manual trigger |

---

## Data Schema

### BigQuery Tables (Source of Truth)

#### `sam_price_live` (overwrite daily)
```
date            DATE
time            TIMESTAMP
city            STRING
pincode         STRING
item_code       INTEGER
item_name       STRING
master_cat      STRING
brand           STRING
marketed_by     STRING
product_type    STRING
unit            STRING
unit_value      FLOAT
am_mrp          FLOAT
image_link      STRING
blinkit_url     STRING
blinkit_name    STRING
blinkit_unit    STRING
blinkit_mrp     FLOAT
blinkit_sp      FLOAT
blinkit_stock   STRING
blinkit_status  STRING
jio_url         STRING
jio_name        STRING
jio_unit        STRING
jio_mrp         FLOAT
jio_sp          FLOAT
jio_stock       STRING
jio_status      STRING
```

#### `sam_price_history` (append daily, partitioned by date)
Same schema as live. Partitioned by `date`, clustered by `pincode, item_code`.

### Forge Tables (ClickHouse — if needed for dashboards)

#### `sam_live` (entity type, upsert by item_code+pincode)
- Same columns as BQ
- Key: `item_code + pincode`
- Engine: ReplacingMergeTree

#### `sam_history` (log type, append only)
- Same columns as BQ
- Engine: MergeTree
- Order by: `date, pincode, item_code`

---

## Jobs Plan

### Option A: Server Cron + Forge SQL Sync
```
Server Cron (10:30 AM)
  → sam_daily_run.py (scrape + push to BQ)
  
Forge Job: sam-bq-to-ch (SQL, every 1440 min)
  → SELECT * FROM BQ sam_price_live → CH sam_live
  → SELECT * FROM BQ sam_price_history WHERE date = today → CH sam_history (append)
```

### Option B: Forge HTTP Job (if server has API endpoint)
```
Forge Job: sam-scrape (HTTP, every 1440 min)
  → POST https://server-ip:8000/api/scrape/run
  → Server runs scraper → pushes to BQ
  
Forge Job: sam-bq-to-ch (SQL, depends_on: sam-scrape)
  → Syncs BQ → CH after scrape completes
```

---

## Mirror Dashboard

### Live Dashboard
```sql
SELECT date, time, city, pincode, item_code, item_name, master_cat, brand, 
       marketed_by, product_type, unit, unit_value, am_mrp, image_link,
       blinkit_url, blinkit_name, blinkit_unit, blinkit_mrp, blinkit_sp, 
       blinkit_stock, blinkit_status,
       jio_url, jio_name, jio_unit, jio_mrp, jio_sp, jio_stock, jio_status
FROM `apna-mart-data.googlesheet.sam_price_live`
ORDER BY item_code
```

### History Dashboard
```sql
SELECT date, time, city, pincode, item_code, item_name, master_cat, brand,
       marketed_by, product_type, unit, unit_value, am_mrp, image_link,
       blinkit_url, blinkit_name, blinkit_unit, blinkit_mrp, blinkit_sp,
       blinkit_stock, blinkit_status,
       jio_url, jio_name, jio_unit, jio_mrp, jio_sp, jio_stock, jio_status
FROM `apna-mart-data.googlesheet.sam_price_history`
ORDER BY date DESC, item_code
```

---

## Domain Summary

| Domain | What | Status |
|--------|------|--------|
| **Scraper** | Python + Playwright, 4 cities × 2 platforms | ✅ Built |
| **Pipeline** | 7-stage matching (PDP→Cascade→Stage3→Search→Image→Barcode) | ✅ Built |
| **Match Logic** | COMPLETE/SEMI/PARTIAL/NA based on unit+MRP+SP | ✅ Built |
| **Excel Output** | 28-col format, per city, auto-generated | ✅ Built |
| **BigQuery** | sam_price_live + sam_price_history | ✅ Created |
| **Mirror Dashboard** | SQL queries ready | ⏳ Manual setup needed |
| **Forge Tables** | sam_live + sam_history (ClickHouse) | ⏳ Not created yet |
| **Forge Jobs** | BQ→CH sync + optional HTTP trigger | ⏳ Not created yet |
| **Server Deploy** | Cron on VPS/Invictus | ⏳ Server needed |
| **Monitoring** | Logs, alerts on failure | ⏳ Not built |

---

## Next Steps (Priority Order)

1. **Mirror Dashboard** — Create manually using SQL queries (5 min)
2. **Server Deploy** — Host on Invictus/VPS, set cron (30 min)
3. **Forge Tables** — Create sam_live + sam_history entity tables
4. **Forge Jobs** — BQ→CH sync job (daily after scrape)
5. **Monitoring** — Slack alert on scrape failure
6. **Scale** — Add more cities, more platforms (Zepto, Instamart, Flipkart)

---

## Open Questions

1. **Server**: Invictus available hai? Ya naya VPS lena hai?
2. **Forge**: Kya Forge tables chahiye (ClickHouse) ya BigQuery + Mirror sufficient hai?
3. **Alerts**: Scrape fail hone pe Slack notification chahiye?
4. **Scale**: Kab Zepto/Instamart/Flipkart add karna hai?
5. **Anakin sunset**: Kab Anakin hatana hai? SAM ke URL database pe depend karna shuru karein?
