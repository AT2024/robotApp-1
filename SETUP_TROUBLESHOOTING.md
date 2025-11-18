# Setup Troubleshooting Guide

## Common Issues and Solutions

### 1. Python Not Found Error

**Symptoms:**
- Command prompt says "python is not recognized"
- Error when trying to create virtual environment

**Solutions:**
1. **Check Python Installation:**
   ```cmd
   python --version
   ```
   If this fails, Python isn't in your PATH.

2. **Fix Python PATH:**
   - Go to Windows Settings → Apps → App execution aliases
   - Turn OFF the Python app installer aliases
   - Add Python to PATH manually:
     - Find where Python is installed (usually `C:\Users\[username]\AppData\Local\Programs\Python\Python3xx\`)
     - Add both the Python directory and the Scripts subdirectory to your PATH

3. **Alternative Python Commands:**
   Try these if `python` doesn't work:
   ```cmd
   py --version
   python3 --version
   ```

### 2. Docker Issues

**Symptoms:**
- "Docker is not running" errors
- Container startup failures

**Solutions:**
1. **Start Docker Desktop:**
   - Make sure Docker Desktop is installed and running
   - Look for the Docker whale icon in your system tray

2. **Enable WSL2 (if needed):**
   ```cmd
   wsl --install
   ```
   Restart your computer after installation.

3. **Enable Virtualization:**
   - Enter BIOS/UEFI settings on boot
   - Enable Intel VT-x or AMD-V virtualization
   - Save and restart

### 3. Git Issues

**Symptoms:**
- "git is not recognized" error

**Solution:**
- Download and install Git from https://git-scm.com
- Make sure to select "Add Git to PATH" during installation

### 4. Port Conflicts

**Symptoms:**
- "Port already in use" errors
- Cannot access http://localhost:3000 or http://localhost:8080

**Solutions:**
1. **Check what's using the ports:**
   ```cmd
   netstat -ano | findstr :3000
   netstat -ano | findstr :8080
   ```

2. **Kill processes using those ports:**
   ```cmd
   taskkill /PID [PID_NUMBER] /F
   ```

3. **Stop other Docker containers:**
   ```cmd
   docker-compose down
   docker stop $(docker ps -q)
   ```

### 5. Docker Build Failures - "404 Not Found" Errors

**Symptoms:**
- Error during `docker-compose up`: "404 Not Found [IP: 151.101.2.132 80]"
- Error message: "E: The repository 'http://deb.debian.org/debian buster Release' does not have a Release file."
- Build fails at "RUN apt-get update" step
- Error: "process did not complete successfully: exit code: 100"

**Root Cause:**
Your Dockerfile is using **Debian Buster** (`python:3.9-slim-buster`), which reached **End-of-Life in June 2022**. The APT package repositories no longer exist, causing 404 errors when trying to install packages.

**Solution - Update to Debian Bullseye:**

1. **Stop and remove all containers:**
   ```cmd
   cd windsurf-project
   docker-compose down
   docker rm -f $(docker ps -aq)
   ```

2. **Clear Docker build cache:**
   ```cmd
   docker system prune -a --volumes
   ```
   Type `y` when prompted. This removes all unused images and build cache.

3. **Verify your Dockerfile:**
   Open `windsurf-project\backend\Dockerfile.dev` and check line 2.

   **It should say:**
   ```dockerfile
   FROM python:3.9-slim-bullseye
   ```

   **If it says this (WRONG):**
   ```dockerfile
   FROM python:3.9-slim-buster
   ```

   **Change it to:**
   ```dockerfile
   FROM python:3.9-slim-bullseye
   ```

4. **Rebuild the containers:**
   ```cmd
   cd windsurf-project
   docker-compose build --no-cache
   docker-compose up -d
   ```

5. **Verify success:**
   ```cmd
   docker-compose ps
   ```
   Both containers should show "Up" status.

**Alternative Quick Fix (if Dockerfile is already correct):**
Sometimes Docker caches the old base image. Force a fresh pull:
```cmd
cd windsurf-project
docker-compose down
docker rmi python:3.9-slim-buster
docker pull python:3.9-slim-bullseye
docker-compose build --no-cache
docker-compose up -d
```

### 6. sync-usa.bat Script Errors

**Symptoms:**
- Running `sync-usa.bat` shows: "now? was unexpected at this time."
- Script fails during initialization (option 3)

**Root Cause:**
The `sync-usa.bat` batch script has a syntax error in the conditional logic.

**Solutions:**

1. **Skip sync-usa.bat and use setup-windsurf.bat instead:**
   ```cmd
   cd C:\Users\aprilp\source\repos\robotApp
   setup-windsurf.bat
   ```
   The setup script works independently and doesn't require the sync tool.

2. **If you need the latest code:**
   - Ask Amitai for the latest bundle file
   - Manually copy updated files from the shared network drive
   - OR: Use Git if the repository is accessible:
     ```cmd
     git pull origin main
     ```

3. **Manual bundle extraction (if you have a .bundle file):**
   ```cmd
   cd C:\Users\aprilp\source\repos\robotApp
   git pull "P:\Alpha Share\amitai to april\windsurf-2025-03-27-1636.bundle" main
   ```

## Quick Setup Steps

1. **Prerequisites Check:**
   - [ ] Python installed and in PATH
   - [ ] Git installed
   - [ ] Docker Desktop installed and running
   - [ ] WSL2 enabled (for Docker)
   - [ ] Virtualization enabled in BIOS

2. **Run the Setup:**
   ```cmd
   cd C:\Users\april\source\repos\robotApp
   setup-windsurf.bat
   ```

3. **Verify Installation:**
   - Frontend: http://localhost:3000
   - Backend: http://localhost:8080

## Manual Setup (if script fails)

If the automated script doesn't work, follow these manual steps:

### Backend Setup:
```cmd
cd windsurf-project/backend
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

### Frontend Setup:
```cmd
cd windsurf-project/frontend
npm install
```

### Start with Docker:
```cmd
cd windsurf-project
docker-compose up -d
```

## Environment Variables

Make sure these are set in your environment or `.env` file:
```
ROBOTICS_ENVIRONMENT=development
ROBOTICS_MECA_IP=192.168.1.100
ROBOTICS_MECA_PORT=10000
ROBOTICS_OT2_IP=169.254.49.202
ROBOTICS_OT2_PORT=31950
```

## Getting Help

If you're still having issues:
1. Check Docker Desktop logs
2. Run `docker-compose logs` to see container errors
3. Make sure all prerequisites are properly installed
4. Try restarting your computer
5. Contact Amitai with specific error messages