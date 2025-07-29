@echo off
echo ================================
echo Robot App Docker Fix Test Script
echo ================================
echo.

REM Set PROJECT_DIR to your project path if not already set
IF "%PROJECT_DIR%"=="" (
	SET "PROJECT_DIR=C:\Users\amitaik\robotApp-1\windsurf-project"
)

cd /d "%PROJECT_DIR%"

echo Step 1: Stopping existing containers...
docker-compose down --volumes
echo.

echo Step 2: Removing old images to force rebuild...
docker image prune -f
echo.

echo Step 3: Building containers with no cache...
docker-compose build --no-cache
echo.

echo Step 4: Starting services...
docker-compose up -d
echo.

echo Step 5: Checking container status...
docker-compose ps
echo.

echo Step 6: Checking logs for any errors...
echo "=== Backend Logs ==="
docker-compose logs backend --tail=20
echo.
echo "=== Frontend Logs ==="
docker-compose logs frontend --tail=20
echo.

echo ================================
echo If no errors above, your app should be running at:
echo Frontend: http://localhost:3000
echo Backend:  http://localhost:8000
echo ================================
echo.
echo To view live logs, run: docker-compose logs -f
echo To stop services, run: docker-compose down
echo.
pause
