# Gemini CLI Analysis Script for Robotics Control Project

## Modified Script for Your Project Structure

Based on your windsurf-project structure, here's the customized Gemini CLI analysis script:

### **Project-Specific Analysis Examples**

#### **Backend Architecture Analysis:**
```bash
# Analyze entire backend structure
gemini -p "@windsurf-project/backend/ Analyze the robotics control system architecture, focusing on the service layer and core infrastructure"

# Check Phase 2 implementation status
gemini -p "@windsurf-project/backend/services/ @windsurf-project/backend/core/ @windsurf-project/backend/routers/ What is the current implementation status of Phase 2 from CLAUDE.md? Which services are complete?"

# Verify dependency injection setup
gemini -p "@windsurf-project/backend/dependencies.py @windsurf-project/backend/main.py @windsurf-project/backend/services/ Is the dependency injection container fully implemented and working correctly?"
```

#### **Service Layer Verification:**
```bash
# Check all services implementation
gemini -p "@windsurf-project/backend/services/ List all implemented services and their current functionality. Are MecaService, OT2Service, and RobotOrchestrator complete?"

# Verify robot integration
gemini -p "@windsurf-project/backend/services/ @windsurf-project/backend/core/ How are the Mecademic and OT2 robots integrated? Show the connection and command handling flow"

# Check protocol execution
gemini -p "@windsurf-project/backend/services/protocol_service.py @windsurf-project/backend/protocols/ Is the protocol execution service fully implemented for multi-robot workflows?"
```

#### **Core Infrastructure Analysis:**
```bash
# Check circuit breaker implementation
gemini -p "@windsurf-project/backend/core/circuit_breaker.py @windsurf-project/backend/core/hardware_manager.py Is the circuit breaker pattern properly implemented for robot connections?"

# Verify state management
gemini -p "@windsurf-project/backend/core/state_manager.py @windsurf-project/backend/core/resource_lock.py Are atomic state management and resource locking working correctly?"

# Check async operations
gemini -p "@windsurf-project/backend/core/async_robot_wrapper.py @windsurf-project/backend/services/ Are async robot operations implemented to prevent blocking?"
```

#### **API and WebSocket Analysis:**
```bash
# Check router updates
gemini -p "@windsurf-project/backend/routers/ @windsurf-project/backend/services/ Have all API routers been updated to use the new service layer instead of RobotManager?"

# Verify WebSocket integration
gemini -p "@windsurf-project/backend/websocket/ @windsurf-project/backend/services/orchestrator.py Are WebSocket handlers properly integrated with the RobotOrchestrator?"

# Check API endpoints
gemini -p "@windsurf-project/backend/routers/ @windsurf-project/backend/main.py List all available API endpoints and their current functionality"
```

#### **Frontend Integration:**
```bash
# Analyze frontend-backend communication
gemini -p "@windsurf-project/frontend/src/utils/services/ @windsurf-project/backend/routers/ How does the frontend communicate with the new backend service architecture?"

# Check WebSocket client
gemini -p "@windsurf-project/frontend/src/utils/services/websocketService.js @windsurf-project/backend/websocket/ Is the frontend WebSocket client properly connected to the backend?"

# Verify API client
gemini -p "@windsurf-project/frontend/src/utils/services/api.js @windsurf-project/backend/ Is the frontend API client compatible with the current backend endpoints?"
```

#### **Configuration and Setup:**
```bash
# Check Docker configuration
gemini -p "@windsurf-project/docker-compose.yml @windsurf-project/backend/Dockerfile.dev @windsurf-project/frontend/Dockerfile.dev Is the Docker setup properly configured for development?"

# Verify environment setup
gemini -p "@windsurf-project/backend/core/settings.py @windsurf-project/backend/.env.example Are all required environment variables and configurations documented?"

# Check dependencies
gemini -p "@windsurf-project/backend/requirements.txt @windsurf-project/frontend/package.json Are all necessary dependencies included and compatible?"
```

#### **Phase Status Verification:**
```bash
# Check Phase 2 completion status
gemini -p "@windsurf-project/CLAUDE.md @windsurf-project/backend/ Based on the CLAUDE.md roadmap, what is the exact completion status of Phase 2? What needs to be done for Phase 3?"

# Verify legacy cleanup
gemini -p "@windsurf-project/backend/archive/ @windsurf-project/backend/ Has all legacy code been properly archived? Are there any remaining references to RobotManager?"

# Check implementation gaps
gemini -p "@windsurf-project/backend/ @windsurf-project/CLAUDE.md What implementation gaps exist between the current codebase and the Phase 2 requirements in CLAUDE.md?"
```

#### **Testing and Quality:**
```bash
# Check test coverage
gemini -p "@windsurf-project/backend/test/ @windsurf-project/backend/services/ What is the current test coverage for the service layer? Which services need more tests?"

# Verify error handling
gemini -p "@windsurf-project/backend/core/exceptions.py @windsurf-project/backend/services/ Is comprehensive error handling implemented across all services?"

# Check logging implementation
gemini -p "@windsurf-project/backend/logs/ @windsurf-project/backend/utils/logger.py Is proper logging implemented throughout the system?"
```

### **Project-Specific Commands for Common Tasks**

#### **Quick Status Check:**
```bash
gemini -p "@windsurf-project/CLAUDE.md @windsurf-project/backend/ What is the current implementation status compared to the CLAUDE.md roadmap?"
```

#### **Architecture Overview:**
```bash
gemini --all_files -p "Provide a comprehensive overview of the robotics control system architecture and current implementation status"
```

#### **Phase 3 Readiness:**
```bash
gemini -p "@windsurf-project/backend/ @windsurf-project/CLAUDE.md Is the system ready for Phase 3 performance optimization? What prerequisites are missing?"
```

### **Robot-Specific Analysis Commands**

#### **Mecademic Robot Analysis:**
```bash
# Check Mecademic integration
gemini -p "@windsurf-project/backend/services/meca_service.py @windsurf-project/backend/core/mecademic_driver.py @windsurf-project/backend/routers/meca.py Is the Mecademic robot fully integrated with proper error handling and circuit breakers?"

# Verify wafer handling operations
gemini -p "@windsurf-project/backend/services/meca_service.py @windsurf-project/backend/object/wafer_object.py Are wafer pickup and drop operations properly implemented with safety checks?"
```

#### **OT2 Robot Analysis:**
```bash
# Check OT2 integration
gemini -p "@windsurf-project/backend/services/ot2_service.py @windsurf-project/backend/routers/ot2.py @windsurf-project/backend/protocols/ Is the OT2 robot properly integrated with protocol execution capabilities?"

# Verify liquid handling protocols
gemini -p "@windsurf-project/backend/protocols/ @windsurf-project/backend/services/protocol_service.py Are liquid handling protocols properly implemented and executable?"
```

#### **Carousel System Analysis:**
```bash
# Check carousel operations
gemini -p "@windsurf-project/backend/object/Carousel_object.py @windsurf-project/backend/services/ @windsurf-project/backend/routers/arduino.py Is the carousel system properly integrated with resource locking and safety measures?"
```

### **Performance and Optimization Analysis**

#### **Async Operations Check:**
```bash
# Check for blocking operations
gemini -p "@windsurf-project/backend/services/ @windsurf-project/backend/core/async_robot_wrapper.py Are there any remaining blocking robot operations that need to be converted to async?"

# Verify connection pooling
gemini -p "@windsurf-project/backend/core/ @windsurf-project/backend/services/ Is connection pooling implemented for robot communications?"
```

#### **Database Performance:**
```bash
# Check database operations
gemini -p "@windsurf-project/backend/database/ @windsurf-project/backend/object/ Are database operations optimized with proper indexing and async support?"
```

### **Security and Safety Analysis:**
```bash
# Check emergency stop implementation
gemini -p "@windsurf-project/backend/services/orchestrator.py @windsurf-project/backend/routers/ Is emergency stop functionality properly implemented across all robots?"

# Verify input validation
gemini -p "@windsurf-project/backend/routers/ @windsurf-project/backend/services/ Is proper input validation implemented for all API endpoints and robot commands?"

# Check safety measures
gemini -p "@windsurf-project/backend/ @windsurf-project/frontend/ Are proper safety measures implemented for laboratory automation (collision detection, safety zones, etc.)?"
```

### **Integration Testing Commands:**
```bash
# Check end-to-end workflows
gemini -p "@windsurf-project/backend/services/protocol_service.py @windsurf-project/backend/test/ Are end-to-end workflows tested for multi-robot operations?"

# Verify WebSocket real-time updates
gemini -p "@windsurf-project/frontend/src/utils/services/websocketService.js @windsurf-project/backend/websocket/ Are real-time status updates working correctly between frontend and backend?"
```

## Usage Instructions

1. **Run from project root**: All paths are relative to your project root directory
2. **Use specific analysis**: Choose the most relevant command for your current needs
3. **Combine multiple areas**: Use multiple @ paths to analyze interactions between components
4. **Save results**: Redirect output to files for documentation: `gemini -p "..." > analysis-results.md`

## Best Practices

- **Start broad, then narrow**: Begin with architecture overview, then dive into specific components
- **Focus on integration points**: Pay special attention to service boundaries and API contracts
- **Verify against CLAUDE.md**: Always compare current state with the roadmap requirements
- **Check error handling**: Ensure robust error handling throughout the system
- **Validate safety measures**: Critical for laboratory automation systems

This customized script will help you efficiently analyze your robotics control project using Gemini's large context window to understand implementation status and identify next steps for Phase 3 optimization.