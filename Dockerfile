FROM mcr.microsoft.com/playwright/python:v1.52.0-noble

WORKDIR /app

# Copy requirements first (better caching)
COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt \
    && pip install --no-cache-dir gspread google-auth google-cloud-bigquery openpyxl

# Install Playwright browsers
RUN playwright install chromium firefox

# Copy code
COPY scripts/ ./scripts/
COPY config/ ./config/
COPY backend/app/ ./backend/app/
COPY CLAUDE.md ./

# Create data directories
RUN mkdir -p data/anakin data/sam data/comparisons data/mappings output

# Copy mapping data (product IDs, URLs — needed for cities without Anakin)
COPY data/mappings/ ./data/mappings/

# Environment
ENV PYTHONUNBUFFERED=1
ENV SAM_OUTPUT_DIR=/app/output

# Entry point — sam_daily_run.py
CMD ["python", "scripts/sam_daily_run.py"]
