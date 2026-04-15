# SAM — Price Benchmark Tool

In-house competitor price tracking system for Apna Mart. Replaces Anakin (₹3L/month).

## Quick Start

```bash
# 1. Setup
cd backend && python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt && playwright install

# 2. Set env
cp .env.example .env  # add METABASE_API_KEY

# 3. Run pipeline (single city)
./venv/bin/python ../scripts/run_full_pipeline.py 834002 blinkit

# 4. Start web UI
./venv/bin/uvicorn app.main:app --reload --port 8000
# Open http://localhost:8000 → SAM Dashboard tab
```

## What It Does

Scrapes Blinkit + Jiomart prices for Apna Mart's products and compares against Anakin's reference data.

**Result: 98.9% coverage, 96.7% price accuracy (same-day, Ranchi Blinkit)**

## 7-Stage Pipeline

| Stage | Method | Confidence |
|---|---|---|
| 0 | EAN/Barcode match | 100% |
| 1 | PDP Direct (URL visit) | 100% |
| 2 | Brand → Type → Weight → Name | 70-90% |
| 3 | Type → Name → Weight → MRP | 60-85% |
| 4 | Search API (Jiomart) | 80-95% |
| 5 | Image match (pHash) | 85-95% |
| 6 | Manual review (CSV) | Human |

## Structure

```
backend/         FastAPI + Playwright scrapers
frontend/        React dashboard (Vite + Tailwind)
scripts/         Pipeline scripts (20+)
config/          Platform settings
data/            Anakin reference + SAM output + comparisons + mappings
docs/            Feature documentation
```

## Docs

- `docs/matching.md` — Pipeline logic (7 stages)
- `docs/anakin_full_logic.md` — How Anakin works (decoded)
- `SAM.md` — System overview
- `ANAKIN.md` — Anakin reverse engineering
