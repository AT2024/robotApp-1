@echo off
REM Update run.bat to include environment variables

echo Choose environment:
echo 1. Development
echo 2. Production
echo 3. Debug
set /p choice="Enter choice: "

if %choice%==1 (
    echo Starting Development Environment...
    set VITE_API_BASE_URL=http://localhost:8000
    set NODE_OPTIONS=--openssl-legacy-provider
    start cmd /k "cd frontend && npm run dev"
    start cmd /k "cd backend && uvicorn main:app --reload --host 127.0.0.1 --port 8000"
    echo Access the frontend at http://localhost:5173
    echo Access the backend at http://localhost:8000
) else if %choice%==2 (
    echo Starting Production Environment...
    set VITE_API_BASE_URL=http://localhost:3000
    REM Start the backend
    start cmd /k "cd backend && uvicorn main:app --host 127.0.0.1 --port 3000"
    
    REM Build and serve the frontend
    cd frontend
    npm run build
    serve -s dist
) else if %choice%==3 (
    echo Starting Debug Environment...
    set VITE_API_BASE_URL=http://localhost:8000
    python -m pdb "%~dp0backend\main.py"
)