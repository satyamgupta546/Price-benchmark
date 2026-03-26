#!/bin/bash
# Start both backend and frontend servers

cd "$(dirname "$0")"

# Kill any existing servers on these ports
lsof -ti:8000 | xargs kill -9 2>/dev/null
lsof -ti:6789 | xargs kill -9 2>/dev/null

echo "Starting Backend (port 8000)..."
cd backend
./venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 &
BACKEND_PID=$!
cd ..

echo "Starting Frontend (port 6789)..."
cd frontend
npm run dev &
FRONTEND_PID=$!
cd ..

echo ""
echo "========================================="
echo "  Price Benchmark is running!"
echo "  Frontend: http://localhost:6789"
echo "  Backend:  http://localhost:8000"
echo "========================================="
echo ""
echo "Press Ctrl+C to stop both servers"

# Trap Ctrl+C to kill both
trap "kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; exit" INT TERM
wait
