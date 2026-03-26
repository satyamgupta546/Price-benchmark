@echo off
REM One-time setup for Price Benchmark on Windows
REM Usage: setup.bat

echo =========================================
echo   Price Benchmark — Setup (Windows)
echo =========================================
echo.

REM Check Node.js
where node >nul 2>&1
if %errorlevel% neq 0 (
    echo Node.js not found. Install from https://nodejs.org
    exit /b 1
)
echo Node.js found

REM Check Python
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo Python not found. Install from https://python.org
    exit /b 1
)
echo Python found

REM Frontend setup
echo.
echo [1/4] Installing frontend dependencies...
cd frontend
call npm install
cd ..

REM Backend venv
echo.
echo [2/4] Creating Python virtual environment...
cd backend
if not exist "venv" (
    python -m venv venv
)

REM Backend dependencies
echo.
echo [3/4] Installing backend dependencies...
call venv\Scripts\pip install -r requirements.txt --quiet

REM Playwright browsers
echo.
echo [4/4] Installing Playwright browsers...
call venv\Scripts\playwright install chromium firefox
cd ..

echo.
echo =========================================
echo   Setup complete!
echo   Run start.bat to start the app
echo =========================================
pause
