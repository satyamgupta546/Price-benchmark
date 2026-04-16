#!/bin/bash
# SAM Daily Cron — runs at 10:30 AM IST
# Add to crontab: crontab -e
# 30 10 * * * /path/to/scripts/sam_cron.sh >> /path/to/logs/sam_cron.log 2>&1

# Resolve project root from script location
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$PATH"

# Load secrets from .env
if [ -f "$PROJECT_DIR/.env" ]; then
    set -a
    source "$PROJECT_DIR/.env"
    set +a
else
    echo "ERROR: .env file not found at $PROJECT_DIR/.env"
    exit 1
fi

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
