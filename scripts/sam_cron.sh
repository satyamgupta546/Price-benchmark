#!/bin/bash
# SAM Daily Cron — runs at 10:30 AM IST
# Add to crontab: crontab -e
# 30 10 * * * /Users/satyam/Desktop/code/Price\ benchmark/scripts/sam_cron.sh >> /Users/satyam/Desktop/code/Price\ benchmark/logs/sam_cron.log 2>&1

export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$PATH"
export METABASE_API_KEY="mb_rJuZYiQLgCMDOhoJkEVDq2+0AhAlLxgAk8TVfY7mlms="

cd "/Users/satyam/Desktop/code/Price benchmark"

# Create logs directory
mkdir -p logs

echo "========================================"
echo "SAM Daily Run — $(date '+%Y-%m-%d %H:%M:%S IST')"
echo "========================================"

# Switch gcloud account
gcloud config set account satyam.gupta@apnamart.in 2>/dev/null

# Run the master script
backend/venv/bin/python scripts/sam_daily_run.py all 2>&1

echo ""
echo "Completed at $(date '+%H:%M:%S IST')"
echo "========================================"
