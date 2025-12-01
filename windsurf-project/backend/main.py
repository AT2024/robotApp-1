from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import traceback
import asyncio
from datetime import datetime
from utils.logger import get_logger
from dependencies import (
    startup_dependencies, 
    shutdown_dependencies, 
    check_dependencies_health,
    get_container
)
from websocket.connection_manager import ConnectionManager
from websocket.websocket_handlers import get_websocket_handler
from routers import meca, ot2, arduino, config

logger = get_logger("main")
app = FastAPI()

# CORS setup remains the same
origins = [
    "http://localhost:3000",
    "http://localhost:3002",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:3002",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize service layer architecture
async def initialize_application():
    try:
        # Initialize dependency container
        container = await get_container()
        
        # Initialize connection manager
        connection_manager = ConnectionManager()
        
        # Create websocket handler with service dependencies
        websocket_handler = get_websocket_handler(
            orchestrator=container.get_orchestrator(),
            command_service=container.get_command_service(),
            protocol_service=container.get_protocol_service(),
            state_manager=container.get_state_manager(),
            connection_manager=connection_manager
        )
        
        # Store services in app state for FastAPI dependencies
        app.state.container = container
        app.state.websocket_handler = websocket_handler
        app.state.connection_manager = connection_manager
        
        logger.info("Application services initialized successfully")
        return True
    except Exception as e:
        logger.error(f"Failed to initialize application services: {e}")
        logger.debug(f"Initialization error traceback: {traceback.format_exc()}")
        return False

# Register API routers
app.include_router(meca.router, prefix="/api/meca", tags=["Mecademic Robot"])
app.include_router(ot2.router, prefix="/api/ot2", tags=["OT2 Robot"])
app.include_router(arduino.router, prefix="/api/arduino", tags=["Arduino System"])
app.include_router(config.router, prefix="/api", tags=["Configuration"])

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """
    Main WebSocket endpoint handling all real-time communication.
    Manages connection lifecycle and message routing.
    """
    client_id = f"client-{id(websocket)}"
    handler = app.state.websocket_handler
    broadcaster = None  # Track broadcaster subscription for cleanup

    try:
        # Initial connection setup
        await handler.connect(websocket)
        logger.info(f"Client {client_id} connected successfully")

        # Subscribe client to SelectiveWebSocketBroadcaster for operation updates
        try:
            from websocket.selective_broadcaster import get_broadcaster, SubscriptionLevel
            broadcaster = await get_broadcaster()
            await broadcaster.subscribe_client(
                client_id=client_id,
                websocket=websocket,
                level=SubscriptionLevel.ALL
            )
            logger.info(f"Client {client_id} subscribed to selective broadcaster")
        except Exception as e:
            logger.warning(f"Failed to subscribe client {client_id} to selective broadcaster: {e}")

        # Send initial system status
        try:
            # Get system status from orchestrator
            orchestrator = app.state.container.get_orchestrator()
            system_status = await orchestrator.get_system_status()
            
            await websocket.send_json({
                "type": "status_update",
                "data": {
                    "system_state": system_status.system_state.value,
                    "operational_robots": system_status.operational_robots,
                    "total_robots": system_status.total_robots,
                    "active_operations": system_status.active_operations,
                    "robots": system_status.robot_details
                },
                "timestamp": datetime.now().isoformat()
            })
        except Exception as e:
            logger.error(f"Error sending initial status to {client_id}: {e}")

        # Main message handling loop
        while True:
            try:
                # Wait for and process incoming messages
                message = await websocket.receive_json()
                logger.debug(f"Received message from {client_id}: {message}")

                # Route message to appropriate handler
                await handler.handle_message(websocket, message)

            except WebSocketDisconnect:
                logger.info(f"Client {client_id} disconnected normally")
                break
            except Exception as e:
                logger.error(f"Error processing message from {client_id}: {str(e)}")
                # Send error notification to client
                try:
                    await websocket.send_json({
                        "type": "error",
                        "message": str(e),
                        "timestamp": datetime.now().isoformat()
                    })
                except:
                    logger.error(f"Could not send error message to {client_id}")
                # Continue listening for messages instead of breaking
                continue

    except Exception as e:
        logger.error(f"WebSocket error for {client_id}: {str(e)}")
        logger.debug(f"WebSocket error traceback: {traceback.format_exc()}")
    finally:
        # Ensure proper cleanup on any exit path
        try:
            # Unsubscribe from selective broadcaster first
            if broadcaster:
                try:
                    await broadcaster.unsubscribe_client(client_id)
                    logger.info(f"Client {client_id} unsubscribed from selective broadcaster")
                except Exception as e:
                    logger.warning(f"Error unsubscribing client {client_id} from broadcaster: {e}")

            await handler.disconnect(websocket)
            logger.info(f"Client {client_id} connection cleaned up successfully")
        except Exception as cleanup_error:
            logger.error(f"Error during connection cleanup for {client_id}: {cleanup_error}")

@app.on_event("startup")
async def startup_event():
    """
    Application startup handler that ensures all components are properly initialized
    and the system is ready to handle requests.
    """
    try:
        logger.info("Starting application initialization...")
        
        # Initialize dependencies (this will start all services)
        await startup_dependencies()
        
        # Initialize application components
        if not await initialize_application():
            raise Exception("Failed to initialize application components")
        
        # Health check to ensure everything is working
        health_info = await check_dependencies_health()
        if not health_info.get("healthy", False):
            logger.warning(f"Some components are not healthy: {health_info}")
        
        logger.info("Application startup completed successfully")
    except Exception as e:
        logger.error(f"Critical error during startup: {e}")
        logger.debug(f"Startup error traceback: {traceback.format_exc()}")
        raise

@app.on_event("shutdown")
async def shutdown_event():
    """
    Application shutdown handler that ensures clean shutdown of all components
    and releases all resources.
    """
    try:
        logger.info("Starting application shutdown...")
        
        # Close all WebSocket connections
        if hasattr(app.state, 'websocket_handler'):
            for websocket in app.state.websocket_handler.active_connections:
                try:
                    await websocket.close()
                except Exception as e:
                    logger.error(f"Error closing websocket during shutdown: {e}")
        
        # Shutdown all dependencies and services
        await shutdown_dependencies()
        
        logger.info("Application shutdown completed successfully")
    except Exception as e:
        logger.error(f"Error during shutdown: {e}")
        logger.debug(f"Shutdown error traceback: {traceback.format_exc()}")
        raise

@app.get("/health")
async def health_check():
    """
    Health check endpoint that also returns the status of critical system components.
    """
    try:
        # Get comprehensive health information
        health_info = await check_dependencies_health()
        
        # Add WebSocket connection info if available
        websocket_connections = 0
        if hasattr(app.state, 'websocket_handler'):
            websocket_connections = len(app.state.websocket_handler.active_connections)
        
        return {
            "status": "healthy" if health_info.get("healthy", False) else "unhealthy",
            "timestamp": datetime.now().isoformat(),
            "dependencies": health_info,
            "websocket_connections": websocket_connections
        }
    except Exception as e:
        logger.error(f"Error in health check: {e}")
        return {
            "status": "error",
            "timestamp": datetime.now().isoformat(),
            "error": str(e)
        }

@app.get("/api/system/status")
async def get_system_status():
    """
    Get detailed system status including all robots and services.
    """
    try:
        if not hasattr(app.state, 'container'):
            raise Exception("Service container not initialized")
        
        orchestrator = app.state.container.get_orchestrator()
        system_status = await orchestrator.get_system_status()
        
        return {
            "system_state": system_status.system_state.value,
            "operational_robots": system_status.operational_robots,
            "error_robots": system_status.error_robots,
            "total_robots": system_status.total_robots,
            "active_operations": system_status.active_operations,
            "last_updated": system_status.last_updated,
            "robot_details": system_status.robot_details
        }
    except Exception as e:
        logger.error(f"Error getting system status: {e}")
        raise JSONResponse(
            status_code=500,
            content={"error": f"Failed to get system status: {str(e)}"}
        )

if __name__ == "__main__":
    import uvicorn
    from core.settings import get_settings
    settings = get_settings()
    logger.info("Starting Robotics Control System Server...")
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=settings.port,
        log_level="info",
        access_log=True
    )