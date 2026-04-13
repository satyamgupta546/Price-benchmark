# SAM / Price Benchmark — Documentation Index

This folder contains feature-level documentation for the SAM Price Benchmark system. Each `.md` file describes one feature in detail. Top-level docs (`ANAKIN.md`, `SAM.md`) live in the project root and cover the bigger picture.

## Top-level docs (project root)

| File | Purpose |
|---|---|
| [`../ANAKIN.md`](../ANAKIN.md) | Reverse engineering of Anakin's data, schema, algorithm, and weaknesses |
| [`../SAM.md`](../SAM.md) | Our system overview, scraper architecture, strengths/gaps |
| [`../ARCHITECTURE.md`](../ARCHITECTURE.md) | Original FastAPI/React architecture doc |

## Feature docs (this folder)

| File | Topic | Status |
|---|---|---|
| [`comparison.md`](comparison.md) | SAM vs Anakin comparison framework + metrics | ✅ Day 1 |
| [`data_storage.md`](data_storage.md) | Where and how we store scrape/anakin/comparison data | ✅ Day 1 |
| [`scraping.md`](scraping.md) | Per-platform scraper notes (BFS, search, DOM fallback) | ✅ Day 1 |
| [`matching.md`](matching.md) | 3-stage matching strategy (ID → Cascade → Manual) | ✅ Day 2 |
| `deployment.md` | Daily cron + cloud deployment | ❌ |
| `api.md` | FastAPI endpoint reference | ❌ |

## Scripts status

| Script | Purpose | Status |
|---|---|---|
| `fetch_anakin_blinkit.py` | Pull Anakin Blinkit data from Mirror | ✅ tested |
| `fetch_anakin_jiomart.py` | Pull Anakin Jiomart data from Mirror | ✅ tested |
| `run_blinkit_scrape.py` | SAM BFS Blinkit scraper runner | ✅ tested |
| `scrape_blinkit_pdps.py` | **Stage 1** Blinkit PDP scraper (retry + API intercept) | ✅ tested — 94.6% ±5% match |
| `scrape_jiomart_pdps.py` | **Stage 1** Jiomart PDP scraper (Firefox + JSON-LD) | ✅ tested on 5 URLs (4/5 ok) |
| `compare_pdp.py` | Stage 1 Blinkit exact-join comparator | ✅ tested |
| `compare_pdp_jiomart.py` | Stage 1 Jiomart exact-join comparator | ✅ built |
| `cascade_match.py` | **Stage 2** brand→type→weight→name cascade | ✅ tested |
| `export_review_queue.py` | **Stage 3** manual review CSV export | ✅ tested |
| `export_pdp_csv.py` | CSV + styled Excel export | ✅ tested |
| `run_all_cities.py` | **Day 3** multi-city + multi-platform orchestrator | ✅ built |
| `format_slack_report.py` | Slack-friendly report formatter | ✅ built |

## Data files status

| Type | Ranchi 834002 | Kolkata 712232 | Raipur 492001 | Hazaribagh 825301 |
|---|---|---|---|---|
| Anakin Blinkit | ✅ 3,620 rows | ✅ 3,724 rows | ✅ 3,721 rows | ✅ 3,236 rows |
| Anakin Jiomart | ✅ 3,620 rows | ✅ (fetched) | ✅ (fetched) | ✅ (fetched) |
| SAM Blinkit PDP | ✅ 2,363 scraped | ❌ | ❌ | ❌ |
| SAM Jiomart PDP | 🟡 running | ❌ | ❌ | ❌ |

## Convention

When you ship a new feature:
1. Add a row to this index
2. Create `docs/<feature>.md` with:
   - **What it does** (one paragraph)
   - **How it works** (algorithm + flow)
   - **Files involved** (paths)
   - **Inputs / Outputs** (formats)
   - **Known limitations**
   - **Next improvements**
