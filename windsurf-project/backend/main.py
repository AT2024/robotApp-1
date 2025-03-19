from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import traceback
import asyncio
from datetime import datetime
from utils.logger import get_logger
from core.robot_manager import RobotManager
from websocket.connection_manager import ConnectionManager
from websocket.websocket_handlers import get_websocket_handler
from routers import meca, ot2

logger = get_logger("main")
app = FastAPI()

# CORS setup remains the same
origins = [
    "http://localhost:3000",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://127.0.0.1:3000",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize managers and handlers with better error handling
async def initialize_application():
    try:
        connection_manager = ConnectionManager()
        robot_manager = RobotManager(connection_manager)
        websocket_handler = get_websocket_handler(robot_manager, connection_manager)
        
        # Store managers in app state
        app.state.robot_manager = robot_manager
        app.state.websocket_handler = websocket_handler
        app.state.connection_manager = connection_manager
        
        logger.info("Application managers initialized successfully")
        return True
    except Exception as e:
        logger.error(f"Failed to initialize application managers: {e}")
        return False

# Register API routers
app.include_router(meca.router, prefix="/api/meca")
app.include_router(ot2.router, prefix="/api/ot2")

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """
    Main WebSocket endpoint handling all real-time communication.
    Manages connection lifecycle and message routing.
    """
    client_id = f"client-{id(websocket)}"
    handler = app.state.websocket_handler

    try:
        # Initial connection setup
        await handler.connect(websocket)
        logger.info(f"Client {client_id} connected successfully")

        # Send initial system status
        try:
            current_status = app.state.robot_manager.get_status()
            await websocket.send_json({
                "type": "status_update",
                "data": current_status,
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
        
        # Initialize application components
        if not await initialize_application():
            raise Exception("Failed to initialize application components")

        # Initialize robots and start monitoring
        await app.state.robot_manager.initialize_robots()
        asyncio.create_task(app.state.robot_manager.monitor_robots())
        
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
        
        # Stop robot monitoring and cleanup
        await app.state.robot_manager.shutdown()
        
        # Close all WebSocket connections
        for websocket in app.state.websocket_handler.active_connections:
            try:
                await websocket.close()
            except Exception as e:
                logger.error(f"Error closing websocket during shutdown: {e}")
        
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
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "robot_status": app.state.robot_manager.get_status(),
        "connections": len(app.state.websocket_handler.active_connections)
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)