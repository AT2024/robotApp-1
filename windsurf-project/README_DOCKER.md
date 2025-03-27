# Windsurf Project - Docker Setup Guide

This document provides instructions on how to set up and run the Windsurf project using Docker.

## Prerequisites

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) must be installed on your machine.

## Project Structure

The project is set up with the following Docker configuration:

- Separate development and production environments
- Development environment with hot-reloading for both frontend and backend
- Production environment with optimized builds and Nginx as a reverse proxy
- Health checks to ensure services start in the correct order

## Development Mode

1. Navigate to the `windsurf-project` directory.
2. Run the `run.bat` file. This will:
   - Build the Docker images
   - Start the containers in development mode
   - Set up volume mounts for hot-reloading
3. Access the frontend at `http://localhost:3000`.
4. Access the backend at `http://localhost:8000`.
5. Any changes you make to the frontend or backend code will automatically reload.
6. To stop the containers, run `docker-compose down` in the `windsurf-project` directory.

## Production Mode

1. Navigate to the `windsurf-project` directory.
2. Run the `run-prod.bat` file, or use the following command to build and start the containers in production mode:

   ```bash
   docker-compose -f docker-compose.prod.yml up -d
   ```
   
3. Access the application at `http://localhost`.
4. The production setup uses Nginx as a reverse proxy to:
   - Serve optimized frontend static files
   - Route API requests to the backend
   - Handle WebSocket connections
5. To stop the containers, run the following command:

   ```bash
   docker-compose -f docker-compose.prod.yml down
   ```

## Configuration

The application can be configured using environment variables. The following environment variables are available:

- `ENVIRONMENT`: Set to `development` or `production`.
- `VITE_API_BASE_URL`: The base URL for the backend API.
  - In development: `http://localhost:8000`
  - In production: `/api` (handled by Nginx)

## Dockerfiles

The project uses separate Dockerfiles for development and production:

- Development:
  - `backend/Dockerfile.dev`: Includes hot-reloading and development tools
  - `frontend/Dockerfile.dev`: Runs the Vite development server
  
- Production:
  - `backend/Dockerfile.prod`: Optimized for production
  - `frontend/Dockerfile.prod`: Builds static files and prepares them for Nginx

## Troubleshooting

- **Services not starting in the correct order**: The production setup includes health checks and depends_on conditions to ensure services start in the correct order.
- **Changes not reflecting in development mode**: Make sure the volume mounts are set up correctly in `docker-compose.yml`.
- **Frontend not connecting to backend**: Check the `VITE_API_BASE_URL` environment variable in the respective Docker Compose file.