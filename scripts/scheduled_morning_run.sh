#!/bin/bash
# Scheduled morning run — runs at 10:30 AM IST daily
# Pulls fresh Anakin data + runs full 4-stage pipeline for Ranchi Blinkit
#
# Set via crontab: 30 10 * * * /Users/satyam/Desktop/code/Price\ benchmark/scripts/scheduled_morning_run.sh

set -e
cd "/Users/satyam/Desktop/code/Price benchmark"
VENV="backend/venv/bin/python"
LOG="data/logs/morning_run_$(date +%Y-%m-%d_%H%M%S).log"
mkdir -p data/logs

echo "=== MORNING RUN START: $(date) ===" | tee -a "$LOG"

# 1. Pull fresh Anakin data (today's date)
echo "[1/5] Fetching fresh Anakin Blinkit data for Ranchi..." | tee -a "$LOG"
python3 scripts/fetch_anakin_blinkit.py 834002 2>&1 | tee -a "$LOG"

# 2. Run BFS scrape to build bigger pool (for Stage 2/3)
echo "[2/5] BFS scrape (pool building, max 5000)..." | tee -a "$LOG"
$VENV scripts/run_blinkit_scrape.py 834002 5000 2>&1 | tee -a "$LOG"

# 3. Run PDP scrape (Stage 1)
echo "[3/5] PDP scrape (Stage 1, 2 workers)..." | tee -a "$LOG"
$VENV scripts/scrape_blinkit_pdps.py 834002 2 2>&1 | tee -a "$LOG"

# Clean partial files
rm -f data/sam/blinkit_pdp_834002_latest_partial.json

# 4. Run all comparisons
echo "[4/5] Running Stage 1-3 comparisons..." | tee -a "$LOG"
python3 scripts/compare_pdp.py 834002 2>&1 | tee -a "$LOG"
python3 scripts/cascade_match.py 834002 2>&1 | tee -a "$LOG"
python3 scripts/stage3_match.py 834002 2>&1 | tee -a "$LOG"
python3 scripts/export_review_queue.py 834002 2>&1 | tee -a "$LOG"

# 5. Generate combined report
echo "[5/5] Generating combined report..." | tee -a "$LOG"
python3 -c "
import json, glob
ana = json.load(open(sorted(glob.glob('data/anakin/blinkit_834002_*.json'))[-1]))
anakin_usable = {r.get('Item_Code') for r in ana['records'] if r.get('Blinkit_Selling_Price') not in (None,'','NA','nan')}

s1 = json.load(open(sorted(glob.glob('data/comparisons/blinkit_pdp_834002_*_compare.json'))[-1]))
s1_ok = {m.get('item_code') for m in s1.get('matches',[]) if m.get('match_status')=='ok'}

s2 = json.load(open(sorted(glob.glob('data/comparisons/blinkit_cascade_834002_*.json'))[-1]))
s2_ok = {m.get('item_code') for m in s2.get('new_mappings',[])}

s3 = json.load(open(sorted(glob.glob('data/comparisons/blinkit_stage3_834002_*.json'))[-1]))
s3_ok = {m.get('item_code') for m in s3.get('new_mappings',[])}

all_matched = (s1_ok | s2_ok | s3_ok) & anakin_usable
pct = len(all_matched)*100/len(anakin_usable)

print(f'Anakin usable: {len(anakin_usable)}')
print(f'Stage 1: {len(s1_ok & anakin_usable)}')
print(f'Stage 2: {len((s2_ok - s1_ok) & anakin_usable)}')
print(f'Stage 3: {len((s3_ok - s1_ok - s2_ok) & anakin_usable)}')
print(f'TOTAL: {len(all_matched)} / {len(anakin_usable)} = {pct:.1f}%')
print(f'Stage 1 price ±5%: {s1[\"metrics\"][\"price_match_pct_5\"]}%')
" 2>&1 | tee -a "$LOG"

# Export CSV/Excel
$VENV scripts/export_pdp_csv.py 834002 2>&1 | tee -a "$LOG"

echo "=== MORNING RUN DONE: $(date) ===" | tee -a "$LOG"
echo "Log: $LOG"
