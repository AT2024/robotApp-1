@echo off
echo ============================================
echo Windsurf Robotics - First Run Setup
echo ============================================
echo.

REM Check if Docker is installed
docker --version >nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: Docker is not installed!
    echo.
    echo Please install Docker Desktop from:
    echo https://www.docker.com/products/docker-desktop/
    echo.
    echo After installation, restart your computer and run this script again.
    pause
    exit /b 1
)

echo [OK] Docker is installed
echo.

REM Setup backend .env
if not exist "backend\.env" (
    echo Setting up backend configuration...
    copy "backend\.env.example" "backend\.env" >nul
    echo [OK] Created backend\.env
) else (
    echo [SKIP] backend\.env already exists
)

REM Setup frontend .env
if not exist "frontend\.env.development" (
    echo Setting up frontend configuration...
    copy "frontend\.env.example" "frontend\.env.development" >nul
    echo [OK] Created frontend\.env.development
) else (
    echo [SKIP] frontend\.env.development already exists
)

echo.
echo ============================================
echo Setup Complete! Starting application...
echo ============================================
echo.
echo Access points:
echo   Frontend: http://localhost:3002
echo   Backend:  http://localhost:8080
echo   API Docs: http://localhost:8080/docs
echo.
echo Press Ctrl+C to stop the application
echo ============================================
echo.

REM Start the application
docker-compose up --build
