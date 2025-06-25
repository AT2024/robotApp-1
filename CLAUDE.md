# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Description

The Windsurf Robotics Control Application is a laboratory automation system that coordinates multiple robotic hardware components:
- **Mecademic robotic arm** for precise sample manipulation
- **Opentrons OT-2 liquid handling robot** for automated pipetting
- **Arduino-controlled systems** for additional automation
- **Carousel system** for sample storage and management

The system automates complex laboratory processes including liquid handling, sample spreading operations, and sample management in a client-server architecture.

## Architecture Overview

**Client-Server Architecture:**
```
Frontend (React/Vite) ↔ Backend (FastAPI/Python) ↔ Hardware (Robots)
```

- **Backend**: FastAPI with WebSocket support, SQLAlchemy ORM, robot-specific drivers
- **Frontend**: React 18 with Vite, Material-UI, real-time WebSocket communication
- **Database**: SQLAlchemy with comprehensive schema for robots, samples, and process logs
- **Infrastructure**: Docker containerization for development and production

## Common Development Commands

### Docker Operations
```bash
# Development environment (hot-reloading)
./windsurf-project/run.bat
# or manually:
cd windsurf-project && docker-compose up -d

# Production environment  
./windsurf-project/run-prod.bat
# or manually:
cd windsurf-project && docker-compose -f docker-compose.prod.yml up -d

# Stop containers
cd windsurf-project && docker-compose down

# Rebuild containers
cd windsurf-project && docker-compose build

# View logs
docker-compose logs frontend
docker-compose logs backend
```

### Access Points
- **Development Frontend**: http://localhost:3000 (maps to container port 5173)
- **Development Backend**: http://localhost:8000
- **Production**: http://localhost (Nginx reverse proxy)

### Backend Development
```bash
# Backend is located in windsurf-project/backend/
# Main entry point: main.py
# Key modules: core/robot_manager.py, routers/, websocket/

# Dependencies are in requirements.txt
# Key libraries: fastapi, uvicorn, sqlalchemy, mecademicpy, opentrons
```

### Frontend Development  
```bash
# Frontend is located in windsurf-project/frontend/
# Built with Vite, uses port 5173 internally
# Key files: src/App.jsx, src/pages/, src/components/

# Package scripts (run inside container or locally):
npm run dev     # Development server
npm run build   # Production build
npm run preview # Preview production build
```

## Key Directories

### Backend Structure (`windsurf-project/backend/`)
- **`config/`** - Robot configurations (meca_config.py, ot2_config.py)
- **`core/robot_manager.py`** - Central robot coordination and management
- **`database/`** - SQLAlchemy models, repositories, database configuration
- **`object/`** - Business objects (Robot_object.py, Carousel_object.py, wafer_object.py)
- **`protocols/`** - OT-2 liquid handling protocols
- **`routers/`** - FastAPI endpoint definitions (meca.py, ot2.py, arduino.py)  
- **`websocket/`** - Real-time communication handlers
- **`test/`** - Test suite for backend functionality
- **`logs/`** - Application logs (organized by date and component)

### Frontend Structure (`windsurf-project/frontend/`)
- **`src/components/`** - Reusable UI components (config/, status/, steps/)
- **`src/pages/`** - Main application pages and views
- **`src/utils/services/`** - API clients and WebSocket services
- **`src/utils/logger.js`** - Frontend logging utilities

## Robot Configuration

### Mecademic Robot (`backend/config/meca_config.py`)
- IP: 192.168.0.100, Port: 10000
- Precise positioning coordinates for wafer handling
- Motion parameters and safety points

### OT-2 Robot (`backend/config/ot2_config.py`)  
- IP: 169.254.77.72, Port: 31950
- Liquid handling parameters and volumes
- Generator positions for radioactive material handling

## Database Schema

Key entities managed by SQLAlchemy:
- **ROBOT** - Robot instances and configurations
- **WAFER** - Individual sample tracking  
- **BAKING_TRAY** - Sample container management
- **CAROUSEL** - Automated sample storage
- **THORIUM_VIAL** - Radioactive material tracking
- **PROCESSLOG** - Audit trail of operations

## API Structure

### REST Endpoints
- **`/api/meca/`** - Mecademic robot operations (pickup, drop, positioning)
- **`/api/ot2/`** - OT-2 operations (protocols, liquid handling)
- **`/api/arduino/`** - Arduino system control
- **`/api/logs/`** - Log file access and management

### WebSocket Communication
- **`/ws`** - Real-time status updates, command feedback, error notifications

## Safety and Error Handling

- **Emergency stop** functionality across all robotic systems
- **Connection monitoring** with automatic reconnection
- **Status validation** before executing operations  
- **Comprehensive logging** in `backend/logs/` directory
- **Error recovery** procedures for hardware failures

## Development Notes

- **Port Configuration**: Frontend runs on port 5173 inside container, mapped to 3000 externally
- **Docker Issues**: If builds fail, check Alpine vs Debian package manager conflicts
- **WebSocket Integration**: Real-time communication is essential for robot status monitoring
- **Hardware Dependencies**: Robot configurations must match physical hardware setup
- **Logging**: Extensive logging system tracks all operations by date and component