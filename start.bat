@echo off
REM Start both backend and frontend servers on Windows
REM Usage: start.bat

echo =========================================
echo   Price Benchmark — Starting...
echo =========================================
echo.

REM Start Backend
echo Starting Backend (port 8000)...
cd backend
start "PriceBenchmark-Backend" cmd /k "venv\Scripts\python -m uvicorn app.main:app --host 0.0.0.0 --port 8000"
cd ..

REM Wait a moment for backend to start
timeout /t 3 /noq >nul

REM Start Frontend
echo Starting Frontend (port 6789)...
cd frontend
start "PriceBenchmark-Frontend" cmd /k "npm run dev"
cd ..

echo.
echo =========================================
echo   Price Benchmark is running!
echo   Frontend: http://localhost:6789
echo   Backend:  http://localhost:8000
echo =========================================
echo.
echo Close the two new terminal windows to stop.
pause
