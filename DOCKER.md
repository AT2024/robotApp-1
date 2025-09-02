# Docker Setup for RobotApp Native Mecademic Backend

## Quick Start

### **For Real Robot Testing:**
```bash
# Edit docker-compose.native.yml - set your robot IP
# MECA_ROBOT_IP=192.168.0.100  (change to your robot's IP)

# Start in development mode
docker-compose -f docker-compose.native.yml up --build

# Access API at http://localhost:8000
```

### **For Safe Testing (Fake Robot):**
```bash
# Start with fake robot server
docker-compose -f docker-compose.native.yml --profile fake up --build

# Access API at http://localhost:8000
# Fake robot available on ports 10010/10011
```

### **Production Deployment:**
```bash
# Start production server
docker-compose -f docker-compose.prod.yml up -d --build

# Access API at http://localhost:8000
```

## Using the Helper Script

```bash
# Make executable (Linux/macOS/WSL)
chmod +x docker-run.sh

# Development mode
./docker-run.sh dev

# Testing with fake robot
./docker-run.sh fake

# Production mode
./docker-run.sh prod

# Test API endpoints
./docker-run.sh test-api

# View logs
./docker-run.sh logs

# Stop everything
./docker-run.sh stop

# Clean up
./docker-run.sh clean
```

## Configuration

### Environment Variables

Edit the compose files or use environment overrides:

```yaml
environment:
  # Robot settings
  - MECA_ROBOT_IP=192.168.0.100     # Your robot IP
  - MECA_CONTROL_PORT=10000         # Robot control port
  - MECA_MONITOR_PORT=10001         # Robot monitor port
  
  # Network binding (optional)
  - ROBOT_NIC_INTERFACE=eth0        # Specific network interface
  - ROBOT_BIND_IP=192.168.1.100     # Bind to specific IP
  
  # API settings
  - API_PORT=8000                   # API server port
  - LOG_LEVEL=INFO                  # Logging level
  - DEBUG_MODE=false                # Debug mode
```

### Network Modes

**Bridge Network (default):**
- Good for development and testing
- Container isolation
- Port mapping required

**Host Network (production):**
- Required for NIC binding features
- Direct host network access
- Better performance
- Use in `docker-compose.prod.yml`

## API Endpoints

Once running, test these endpoints:

```bash
# Health check
curl http://localhost:8000/api/health

# Robot status
curl http://localhost:8000/api/status

# WebSocket monitoring
websocat ws://localhost:8000/ws/status

# Acquire robot lease
curl -X POST http://localhost:8000/api/lease/acquire \
  -H "Content-Type: application/json" \
  -d '{"client_id": "test", "duration": 120}'
```

## Troubleshooting

### Build Issues
```bash
# Clean rebuild
docker-compose -f docker-compose.native.yml build --no-cache

# Check logs
docker-compose -f docker-compose.native.yml logs robotapp-native
```

### Connection Issues
```bash
# Check if robot IP is reachable
docker-compose -f docker-compose.native.yml exec robotapp-native ping 192.168.0.100

# Test from inside container
docker-compose -f docker-compose.native.yml exec robotapp-native curl http://localhost:8000/api/health
```

### Port Conflicts
```bash
# Check what's using port 8000
netstat -tulpn | grep :8000

# Use different port
docker-compose -f docker-compose.native.yml up -p 8001:8000
```

## File Structure

```
├── Dockerfile                    # Multi-stage container definition
├── .dockerignore                 # Build optimization
├── docker-compose.native.yml     # Development/testing setup
├── docker-compose.prod.yml       # Production setup  
├── docker-run.sh                 # Helper script
└── backend/                      # Application code
    ├── app/main.py               # FastAPI application
    ├── drivers/                  # Robot drivers
    ├── services/                 # Service layer
    └── tests/fakes/              # Fake robot server
```

## Production Considerations

1. **Security:**
   - Set `ROBOT_API_KEY` for API authentication
   - Configure `ALLOWED_CLIENT_IPS` for network restrictions
   - Use HTTPS with SSL certificates

2. **Performance:**
   - Use host networking for NIC binding
   - Set appropriate resource limits
   - Monitor container health

3. **Monitoring:**
   - Check health endpoint regularly
   - Monitor container logs
   - Set up log aggregation

4. **Backup:**
   - Robot configurations
   - Application logs
   - Lease management state