@echo off
echo Starting Windsurf Project in Development Mode

echo Building Docker images...
docker-compose build

echo Running Docker containers in development mode...
docker-compose up -d

echo.
echo ======================================================
echo Development environment is now running:
echo Frontend: http://localhost:3002
echo Backend: http://localhost:8080
echo ======================================================
echo.
echo To stop the containers, run: docker-compose down

pause