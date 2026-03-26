#!/bin/bash
# One-time setup for Price Benchmark on a new machine
# Usage: ./setup.sh

set -e
cd "$(dirname "$0")"

echo "========================================="
echo "  Price Benchmark — Setup"
echo "========================================="
echo ""

# Check Node.js
if ! command -v node &>/dev/null; then
    echo "Node.js not found. Install it from https://nodejs.org (v18+)"
    exit 1
fi
echo "Node.js: $(node -v)"

# Check Python
PYTHON=""
if command -v python3 &>/dev/null; then
    PYTHON="python3"
elif command -v python &>/dev/null; then
    PYTHON="python"
else
    echo "Python not found. Install Python 3.11+ from https://python.org"
    exit 1
fi
echo "Python: $($PYTHON --version)"

# Frontend setup
echo ""
echo "[1/4] Installing frontend dependencies..."
cd frontend
npm install
cd ..

# Backend venv
echo ""
echo "[2/4] Creating Python virtual environment..."
cd backend
if [ ! -d "venv" ]; then
    $PYTHON -m venv venv
fi

# Backend dependencies
echo ""
echo "[3/4] Installing backend dependencies..."
./venv/bin/pip install -r requirements.txt --quiet

# Playwright browsers
echo ""
echo "[4/4] Installing Playwright browsers..."
./venv/bin/playwright install chromium firefox
cd ..

echo ""
echo "========================================="
echo "  Setup complete!"
echo "  Run ./start.sh to start the app"
echo "========================================="
