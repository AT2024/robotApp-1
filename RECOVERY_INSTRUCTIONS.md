# Recovery Instructions for April's Computer

## Problem Summary

You're experiencing a **Docker build failure** because your version of the code uses an outdated Debian version (Buster) that is no longer supported. This causes 404 errors when trying to download packages during the Docker build process.

**Error messages you're seeing:**
```
404  Not Found [IP: 151.101.2.132 80]
E: The repository 'http://deb.debian.org/debian buster Release' does not have a Release file.
```

## Complete Recovery Steps

Follow these steps in order to fix the issue:

### Step 1: Clean Up Current Setup

Open PowerShell or Command Prompt and run these commands:

```cmd
cd C:\Users\aprilp\source\repos\robotApp\windsurf-project
docker-compose down
```

This stops all running containers.

### Step 2: Remove All Docker Containers and Images

**WARNING:** This will remove all Docker images and containers on your system. If you have other Docker projects, they will need to be rebuilt.

```cmd
docker system prune -a --volumes
```

When prompted "Are you sure you want to continue? [y/N]", type `y` and press Enter.

This process may take a few minutes. Wait for it to complete.

### Step 3: Verify Your Dockerfile

1. Open File Explorer and navigate to:
   ```
   C:\Users\aprilp\source\repos\robotApp\windsurf-project\backend\
   ```

2. Right-click on `Dockerfile.dev` and open it with Notepad

3. Look at line 2 (the second line of the file)

4. **Check what it says:**

   ✅ **CORRECT (Bullseye):**
   ```dockerfile
   FROM python:3.9-slim-bullseye
   ```

   ❌ **WRONG (Buster - needs to be fixed):**
   ```dockerfile
   FROM python:3.9-slim-buster
   ```

5. **If it says `buster`**, change it to `bullseye`:
   - Select the word `buster` on line 2
   - Type `bullseye` to replace it
   - Save the file (File → Save or Ctrl+S)

6. Close Notepad

### Step 4: Rebuild the Docker Containers

Go back to PowerShell/Command Prompt:

```cmd
cd C:\Users\aprilp\source\repos\robotApp\windsurf-project
docker-compose build --no-cache
```

**This will take 5-10 minutes.** You'll see it downloading packages and building the containers. Wait for it to finish.

### Step 5: Start the Application

Once the build is complete, start the containers:

```cmd
docker-compose up -d
```

### Step 6: Verify Everything is Working

Check that both containers are running:

```cmd
docker-compose ps
```

You should see something like:
```
NAME                     STATUS
robotics-backend         Up 30 seconds
robotics-frontend        Up 30 seconds
```

### Step 7: Access the Application

Open your web browser and navigate to:

- **Frontend**: http://localhost:3000
- **Backend API**: http://localhost:8080

If you can see the application interface, you're all set!

## If You Still Have Issues

### Issue: Dockerfile already says "bullseye" but build still fails

**Solution:** Docker might be caching the old image. Run:

```cmd
cd C:\Users\aprilp\source\repos\robotApp\windsurf-project
docker rmi python:3.9-slim-buster
docker pull python:3.9-slim-bullseye
docker-compose build --no-cache
docker-compose up -d
```

### Issue: Port already in use

**Symptoms:** Error says port 3000 or 8080 is already in use.

**Solution:**
```cmd
netstat -ano | findstr :3000
netstat -ano | findstr :8080
```

Find the PID (Process ID) number and kill it:
```cmd
taskkill /PID [number] /F
```

Then try starting Docker again:
```cmd
docker-compose up -d
```

### Issue: Docker Desktop not responding

**Solution:**
1. Close Docker Desktop completely (right-click the whale icon in system tray → Quit)
2. Restart Docker Desktop
3. Wait for it to fully start (the whale icon should be steady, not animated)
4. Try the setup again

## Getting Updated Code (Skip sync-usa.bat)

The `sync-usa.bat` script has a bug. Instead, to get the latest code:

### Option 1: Manual File Copy (Simplest)

1. Ask Amitai to copy the latest `windsurf-project` folder to the shared network drive
2. Copy the entire folder to your computer
3. Run the recovery steps above

### Option 2: Use Git Bundle (If Available)

If Amitai provides a `.bundle` file on the shared drive:

```cmd
cd C:\Users\aprilp\source\repos\robotApp
git pull "P:\Alpha Share\amitai to april\[bundle-filename].bundle" main
```

Replace `[bundle-filename]` with the actual bundle file name.

### Option 3: Use setup-windsurf.bat (After Fixing Dockerfile)

Once your Dockerfile is updated to `bullseye`, you can use:

```cmd
cd C:\Users\aprilp\source\repos\robotApp
setup-windsurf.bat
```

This script should work without needing sync-usa.bat.

## Quick Reference Commands

```cmd
# Stop containers
docker-compose down

# View logs
docker-compose logs backend
docker-compose logs frontend

# Rebuild from scratch
docker-compose down
docker system prune -a --volumes
docker-compose build --no-cache
docker-compose up -d

# Check container status
docker-compose ps

# Restart containers
docker-compose restart
```

## Need Help?

If you're still stuck after following these steps:

1. Take a screenshot of the exact error message
2. Copy the full error text from PowerShell
3. Note which step you're on
4. Contact Amitai with this information

Good luck! The issue is fixable, just follow the steps carefully.
