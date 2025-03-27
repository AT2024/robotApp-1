@echo off
echo Starting Windsurf Project in Production Mode

echo Building Docker images...
docker-compose -f docker-compose.prod.yml build

echo Running Docker containers in production mode...
docker-compose -f docker-compose.prod.yml up -d

echo.
echo ======================================================
echo Production environment is now running:
echo Application: http://localhost
echo ======================================================
echo.
echo To stop the containers, run: docker-compose -f docker-compose.prod.yml down

pause