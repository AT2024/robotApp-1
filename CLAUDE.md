# CLAUDE.md

Development guide for Claude Code when working with the Windsurf Robotics Control Application.

## Project Overview

Laboratory automation system controlling multiple robotic hardware:
- **Mecademic robotic arm** - Precise sample manipulation
- **Opentrons OT-2** - Liquid handling automation  
- **Arduino systems** - Additional automation control
- **Carousel system** - Sample storage and management

**Architecture**: `Frontend (React/Vite) ↔ API Layer ↔ Services Layer ↔ Core Infrastructure ↔ Hardware`

## Quick Start

```bash
# Development environment
cd windsurf-project && docker-compose up -d

# Access points
# Frontend: http://localhost:3000 (maps to container port 5173)
# Backend: http://localhost:8000

# View logs
docker-compose logs frontend
docker-compose logs backend
```

## Tool Usage & Decision Framework

### **Authority & Responsibilities**
- **Claude**: All decisions, architecture, strategy, planning, implementation
- **Gemini**: Code review only when context limits prevent Claude analysis
- **Process**: Claude defines analysis → Gemini reviews code → Claude decides

### **Tool Selection Rules**
```
Analysis Need → Tool Selection:
├── Specific file content → Read tool
├── Code pattern search → Grep tool  
├── File discovery → Glob tool
├── Open-ended research → Task tool (SuperClaude agent)
├── Large codebase review → Gemini code analysis (code review only)
├── UI testing → Playwright MCP
└── Web content → WebFetch MCP
```

### **SuperClaude Agent Usage**
- **Use When**: Open-ended searches, keyword hunting, file discovery, multi-round analysis
- **Avoid**: Specific file reads, known definitions, writing code, bash commands
- **Strategy**: Launch multiple agents concurrently for complex analysis

### **Gemini Integration (Code Review Only)**
- **Trigger**: Context too large for Claude analysis
- **Tasks**: Code structure analysis, implementation verification, pattern identification  
- **NOT for**: Architecture decisions, implementation strategy, debugging approach

## Development Standards

### **Mandatory Code Quality Tools**
```bash
# Install immediately
pip install black flake8 mypy pre-commit

# Pre-commit configuration (.pre-commit-config.yaml)
repos:
  - repo: https://github.com/psf/black
    hooks: [{ id: black }]
  - repo: https://github.com/pycqa/flake8  
    hooks: [{ id: flake8 }]
  - repo: https://github.com/pre-commit/mirrors-mypy
    hooks: [{ id: mypy }]
```

### **Code Style Rules**

**Explicitness Over Implicitness** (Critical for Robotics Safety)
```python
# ✅ Explicit (Required)
robot_position = await meca_service.get_current_position()
if robot_position.x > SAFE_ZONE_BOUNDARY:
    await meca_service.move_to_safe_position()
    
# ❌ Implicit (Dangerous)
pos = await svc.get_pos()
if pos.x > BOUNDARY: await svc.safe()
```

**Error Handling Standards**
```python
# ✅ Rich Context (Required)
try:
    await robot_operation()
except HardwareError as e:
    logger.error(f"Robot {robot_id} failed during {operation_name}: {e.to_dict()}")
    await emergency_stop_sequence()
    raise

# ❌ Minimal Context (Never)
try:
    await robot_operation()
except Exception as e:
    logger.error(f"Error: {e}")
```

**Configuration Access**
```python
# ✅ Environment Variables (Always)
from core.settings import get_settings
settings = get_settings()
meca_config = settings.get_robot_config("meca")

# ❌ Hard-coded Values (Never)
MECA_IP = "192.168.0.100"  # Don't do this
```

**Type Annotations** (Required for Service Interfaces)
```python
async def execute_pickup_sequence(
    self, start: int, count: int
) -> ServiceResult[Dict[str, Any]]:
    """Execute wafer pickup with full type safety."""
    pass
```

## Architecture Guidelines

### **Service Layer Pattern**
```python
class NewRobotService(RobotService):
    def __init__(self, robot_id: str, settings: RoboticsSettings, 
                 state_manager: AtomicStateManager, lock_manager: ResourceLockManager):
        super().__init__(robot_id=robot_id, robot_type="new_robot", 
                        settings=settings, state_manager=state_manager, 
                        lock_manager=lock_manager, service_name="NewRobotService")
        self.robot_config = settings.get_robot_config("new_robot")
    
    @circuit_breaker("new_robot_connect")
    async def connect(self) -> ServiceResult[bool]:
        # Implementation with circuit breaker protection
        pass
```

### **API Endpoint Template**
```python
@router.post("/operation-name")
async def operation_name(data: dict = Body(default={}), 
                        service: RobotService = ServiceDep()):
    try:
        param1 = data.get("param1", default_value)
        logger.info(f"Starting operation: param1={param1}")
        
        result = await service.execute_operation(param1)
        if not result.success:
            raise HTTPException(status_code=500, detail=result.error)
            
        return {"status": "success", "data": result.data, 
                "message": "Operation completed"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in operation: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
```

## Environment Configuration

### **Required Environment Variables**
```bash
# All settings use ROBOTICS_ prefix
ROBOTICS_ENVIRONMENT=development
ROBOTICS_MECA_IP=192.168.0.100
ROBOTICS_MECA_PORT=10000
ROBOTICS_OT2_IP=169.254.49.202
ROBOTICS_OT2_PORT=31950
ROBOTICS_DATABASE_URL=sqlite+aiosqlite:///./robotics.db
```

### **Configuration Access Pattern**
```python
# ✅ Always use settings system
from core.settings import get_settings
settings = get_settings()
robot_config = settings.get_robot_config("meca")

# ❌ Never hard-code
IP_ADDRESS = "192.168.0.100"  # Don't do this
```

## Safety & Performance Standards

### **Robotics Safety Requirements**
1. **State Validation**: Always verify robot state before operations
2. **Emergency Stop**: All services must support emergency stop
3. **Resource Locking**: Use `ResourceLockManager` for shared resources
4. **Circuit Breakers**: Protect all external robot connections
5. **Graceful Degradation**: If one robot fails, others continue safely

### **Performance Thresholds**
- API Response: <100ms (status), <2s (operations)
- Robot Response: <2s for movement commands
- Database Queries: <100ms (real-time), optimize slower queries
- Memory: <2GB per service, <80% system resources
- Error Recovery: <5s for automatic recovery

### **Testing Requirements**
- Unit Test Coverage: 90%+ (service layer)
- Integration Coverage: 70%+ (overall)
- Hardware Simulation: Mock hardware for CI/CD
- Performance Testing: Regular benchmarking
- Safety Testing: Emergency stop scenarios

## Development Procedures

### **Adding New Robot Support**
1. Create service class inheriting from `RobotService`
2. Implement `connect()`, `disconnect()`, `get_robot_status()`
3. Update `core/settings.py` with robot settings
4. Create FastAPI router in `routers/` directory
5. Add service to `dependencies.py`
6. Create comprehensive test suite
7. Update this CLAUDE.md documentation

### **Common Development Tasks**
```bash
# Code formatting
black .
flake8 .
mypy .

# Docker operations
docker-compose build  # Rebuild containers
docker-compose down   # Stop all services
docker-compose logs <service>  # View service logs

# Database operations
# Use service layer - never direct database access
```

## Decision Trees

### **Service Creation**
```
Need functionality?
├── Existing robot type? → Extend existing service
├── New robot type? → Create new service  
├── Cross-robot coordination? → Use RobotOrchestrator
└── Utility function? → Add to appropriate service
```

### **Error Handling**
```
Error occurred?
├── Hardware connection? → Circuit breaker + retry
├── Invalid input? → Validation error + user message
├── Safety violation? → Emergency stop + full logging
├── Resource conflict? → Resource lock + retry
└── Unknown error? → Fail fast + context logging
```

### **Performance Optimization**
```
Performance issue?
├── Database slow? → Add indexes, optimize queries
├── API slow? → Add caching, async processing  
├── Robot slow? → Check network, hardware status
├── Memory high? → Profile and optimize algorithms
└── CPU high? → Async processing, load balancing
```

## Key Directories

```
windsurf-project/
├── backend/
│   ├── core/          # Infrastructure (settings, state, locks)
│   ├── services/      # Robot service layer
│   ├── routers/       # FastAPI endpoints
│   ├── database/      # Models and repositories
│   ├── websocket/     # Real-time communication
│   └── dependencies.py # Dependency injection
└── frontend/
    ├── src/components/ # UI components
    ├── src/pages/     # Application pages
    └── src/utils/     # API clients
```

## Essential Troubleshooting

### **OT2 Connection Issues**
- Check `robot_id` parameter in OT2Service constructor
- Verify `opentrons-version: 4` header in requests
- Ensure `pydantic<2.0.0` compatibility

### **Mecademic Connection Issues**  
- Verify IP: 192.168.0.100, Port: 10000
- Check TCP connection and motion parameters
- Review safety system activation

### **Docker Build Issues**
- Use `--no-cache` flag for troubleshooting
- Check package manager compatibility (Alpine vs Debian)
- Increase Docker memory allocation if needed

### **Performance Issues**
- Check robot response times (<2s required)
- Monitor API response times (<100ms for status)
- Profile database queries (optimize if >100ms)
- Monitor memory usage (<2GB per service)

---

## Development Notes

- **Port Config**: Frontend runs on 5173 internally, mapped to 3000 externally
- **Architecture**: Always use service layer, never direct robot access
- **State Management**: All state changes through AtomicStateManager
- **Resource Safety**: Use ResourceLockManager for shared resources
- **Performance**: Use AsyncRobotWrapper for non-blocking operations
- **Configuration**: Use settings.get_robot_config() for all robot config
- **Testing**: Mock hardware for unit tests, real hardware for integration
- **Documentation**: Keep this CLAUDE.md updated with any architectural changes