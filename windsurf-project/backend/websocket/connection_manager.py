from fastapi import WebSocket
from typing import Dict, Optional
from utils.logger import get_logger
from datetime import datetime
from core.settings import RoboticsSettings

logger = get_logger("connection_manager")

class ConnectionManager:
    def __init__(self, settings: Optional[RoboticsSettings] = None):
        self.active_connections = []
        self.server_status = 'Disconnected'
        self.settings = settings or RoboticsSettings()
    async def handle_config_request(self, websocket: WebSocket, config_type: str):
        """Handle requests for configuration data using new settings system."""
        try:
            config_data = None
            if config_type == 'meca':
                # Get comprehensive Meca configuration from settings
                config_data = self.settings.get_robot_config("meca")
            elif config_type == 'ot2':
                # Get comprehensive OT2 configuration from settings
                config_data = self.settings.get_robot_config("ot2")
            elif config_type == 'arduino':
                # Get Arduino configuration from settings
                config_data = self.settings.get_robot_config("arduino")
            elif config_type == 'wiper':
                # Get Wiper configuration from settings
                config_data = self.settings.get_robot_config("wiper")
            elif config_type == 'system':
                # Get comprehensive system configuration
                config_data = {
                    "environment": self.settings.environment.value,
                    "debug": self.settings.debug,
                    "log_level": self.settings.log_level.value,
                    "host": self.settings.host,
                    "port": self.settings.port,
                    "database_url": self.settings.database_url,
                    "max_concurrent_operations": self.settings.max_concurrent_robot_commands,
                    "health_check_interval": self.settings.health_check_interval,
                    "robot_status_check_interval": self.settings.robot_status_check_interval,
                    "circuit_breaker": self.settings.get_circuit_breaker_config(),
                    "resource_locks": self.settings.get_resource_lock_config(),
                    "websocket": {
                        "ping_interval": self.settings.websocket_ping_interval,
                        "ping_timeout": self.settings.websocket_ping_timeout,
                        "max_connections": self.settings.websocket_max_connections,
                    },
                    "safety": {
                        "emergency_stop_timeout": self.settings.emergency_stop_timeout,
                        "operation_timeout": self.settings.operation_timeout,
                        "connection_timeout": self.settings.connection_timeout,
                    }
                }
            elif config_type == 'all' or config_type == 'robots':
                # Get all robot configurations
                config_data = {
                    "meca": self.settings.get_robot_config("meca"),
                    "ot2": self.settings.get_robot_config("ot2"),
                    "arduino": self.settings.get_robot_config("arduino"),
                    "wiper": self.settings.get_robot_config("wiper"),
                }
            
            if config_data:
                await websocket.send_json({
                    "type": "config_data",
                    "data": {
                        "config_type": config_type,
                        "content": config_data
                    }
                })
                logger.info(f"Sent {config_type} configuration to client")
            else:
                await websocket.send_json({
                    "type": "error",
                    "message": f"Configuration not found for {config_type}"
                })
        except Exception as e:
            logger.error(f"Error handling config request: {e}")
            await websocket.send_json({
                "type": "error",
                "message": f"Failed to load configuration: {str(e)}"
            })

    async def handle_message(self, websocket: WebSocket, message: dict):
        """Handle incoming WebSocket messages."""
        try:
            msg_type = message.get('type')
            if msg_type == 'get_config':
                await self.handle_config_request(
                    websocket, 
                    message.get('config_type')
                )
            elif msg_type == 'status_update':
                await self.broadcast_server_status()
            elif msg_type == 'get_all_config':
                # Handle request for all configuration data
                await self.handle_config_request(websocket, 'all')
        except Exception as e:
            logger.error(f"Error handling message: {e}")
            await websocket.send_json({
                "type": "error",
                "message": str(e)
            })

    async def connect(self, websocket: WebSocket, client_id: str):
        """Connect a new WebSocket client."""
        try:
            await websocket.accept()  # Accept the connection first
            self.active_connections.append(websocket)  # Register the connection
            logger.info(f"Client {client_id} connected. Total connections: {len(self.active_connections)}")
            await self.broadcast_server_status()  # Send initial status update
        except Exception as e:
            logger.error(f"Error connecting client {client_id}: {e}")
            if websocket in self.active_connections:
                self.active_connections.remove(websocket)

    async def disconnect(self, websocket: WebSocket):
        """Safely disconnect and clean up a client connection."""
        if websocket in self.active_connections:
            try:
                await websocket.close()
            except Exception as e:
                logger.error(f"Error closing connection: {e}")
            finally:
                self.active_connections.remove(websocket)
                logger.info(f"Client disconnected. Total connections: {len(self.active_connections)}")
                await self.broadcast_server_status()

    async def remove(self, websocket: WebSocket):
        """Remove a WebSocket connection."""
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
            logger.info(f"WebSocket connection removed. Total connections: {len(self.active_connections)}")

    async def broadcast(self, message: dict):
        """
        Broadcast a message to all connected clients.
        Handles failed deliveries and connection cleanup.
        """
        disconnected_clients = []
        
        # Add timestamp to the message
        message_with_timestamp = {
            **message,
            "timestamp": datetime.now().isoformat(),
        }
        
        logger.debug(f"Broadcasting message: {message_with_timestamp}")  # Add logging
        
        for websocket in self.active_connections:
            try:
                await websocket.send_json(message_with_timestamp)
            except Exception as e:
                logger.error(f"Failed to broadcast to client: {e}")
                disconnected_clients.append(websocket)

        # Clean up any failed connections
        for websocket in disconnected_clients:
            await self.disconnect(websocket)
    async def send_personal_message(self, message: dict, websocket: WebSocket):
        """
        Send a message to a specific client.
        Handles delivery failures and connection cleanup.
        """
        if websocket not in self.active_connections:
            logger.warning(f"Attempted to send message to unknown client")
            return

        try:
            await websocket.send_json({
                **message,
                "timestamp": datetime.now().isoformat()
            })
        except Exception as e:
            logger.error(f"Failed to send message to client: {e}")
            await self.disconnect(websocket)

    async def send_message(self, message: str):
        """
        Send a message to all connected clients.
        """
        for connection in self.active_connections:
            await connection.send_text(message)

    async def broadcast_server_status(self):
        """Broadcast the current server status to all connected clients."""
        message = {
            "type": "status_update",
            "data": {
                "type": "backend",
                "status": self.server_status.lower()
            }
        }
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception as e:
                logger.error(f"Failed to send status update: {e}")

    async def _send_welcome_message(self, websocket: WebSocket, client_id: str):
        """Send a welcome message to newly connected clients."""
        try:
            await websocket.send_json({
                "type": "connection_established",
                "client_id": client_id,
                "message": "Successfully connected to server",
                "timestamp": datetime.now().isoformat()
            })
        except Exception as e:
            logger.error(f"Failed to send welcome message to client {client_id}: {e}")


# Add to ConnectionManager class
def get_connection_manager(settings: Optional[RoboticsSettings] = None) -> ConnectionManager:
    return ConnectionManager(settings)