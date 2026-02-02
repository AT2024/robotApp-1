---
name: fix-docker-ports
description: Diagnose and auto-fix Docker/WSL port conflicts when localhost fails but 127.0.0.1 works. Use when app not loading, connection refused, or port conflicts on Windows with Docker Desktop.
allowed-tools: Bash(netstat:*), Bash(curl:*), Bash(powershell:*), Bash(wmic:*), Bash(docker:*)
argument-hint: [port-number]
---

# Docker/WSL Port Conflict Auto-Fix

Automatically diagnoses and fixes the IPv6/IPv4 localhost conflict caused by wslrelay.exe on Windows with Docker Desktop.

## Problem This Solves

- `localhost:PORT` times out or connection refused
- `127.0.0.1:PORT` works fine
- Caused by wslrelay.exe binding to `[::1]:PORT` (IPv6 localhost)

## Auto-Fix Workflow

### Step 1: Get the port to check
If no argument provided, default to common ports: 3002, 8080, 3000, 5173

### Step 2: Test connectivity
```bash
# Test if localhost fails but 127.0.0.1 works
curl -s -o nul -w "%{http_code}" --connect-timeout 3 http://127.0.0.1:$PORT/
curl -s -o nul -w "%{http_code}" --connect-timeout 3 http://localhost:$PORT/
```

### Step 3: Check for wslrelay conflict
```bash
netstat -ano | findstr ":$PORT" | findstr "LISTENING"
```

Look for TWO listeners:
- Docker: `0.0.0.0:PORT` or `[::]:PORT`
- wslrelay: `[::1]:PORT` (THIS IS THE PROBLEM)

### Step 4: Identify the wslrelay PID
```bash
# Get PID from the [::1]:PORT line
wmic process where processid=PID get name,commandline
# If it shows wslrelay.exe, that's the culprit
```

### Step 5: Kill wslrelay
```bash
powershell -Command "Stop-Process -Id PID -Force"
```

### Step 6: Verify fix
```bash
curl -s -o nul -w "%{http_code}" --connect-timeout 3 http://localhost:$PORT/
# Should now return 200
```

## Usage Examples

```
/fix-docker-ports 3002
/fix-docker-ports 8080
```

Or just say: "localhost:3002 isn't working but 127.0.0.1:3002 works"

## Common Ports for This Project

| Service | Port |
|---------|------|
| Frontend | 3002 (external) -> 5173 (internal) |
| Backend | 8080 (external) -> 8000 (internal) |

## Why This Happens

Docker Desktop uses WSL2. Sometimes `wslrelay.exe` binds to IPv6 localhost `[::1]` but doesn't properly forward traffic. When your browser resolves `localhost`, Windows may prefer IPv6, hitting the broken relay instead of Docker's working IPv4 binding.

## Prevention

If this happens frequently:
1. Restart Docker Desktop
2. Or add to hosts file: `127.0.0.1 localhost` (and comment out `::1 localhost`)
