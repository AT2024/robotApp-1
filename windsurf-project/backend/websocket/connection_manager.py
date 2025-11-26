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
        """Handle requests for configuration data - reads directly from runtime.json for accuracy."""
        try:
            from utils.config_manager import get_config_manager

            config_data = None

            # For robot configs, read directly from runtime.json to ensure fresh data
            if config_type in ['meca', 'ot2', 'arduino', 'wiper']:
                config_manager = get_config_manager()
                all_config = await config_manager.load_runtime_config()
                config_data = all_config.get(config_type, {})
            elif config_type == 'all' or config_type == 'robots':
                # Get all robot configurations directly from runtime.json
                config_manager = get_config_manager()
                config_data = await config_manager.load_runtime_config()
            elif config_type == 'system':
                # System config from settings (not in runtime.json)
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

            if config_data is not None:
                await websocket.send_json({
                    "type": "config_data",
                    "data": {
                        "config_type": config_type,
                        "content": config_data
                    }
                })
                logger.info(f"Sent {config_type} configuration to client (from runtime.json)")
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

    async def handle_config_save(self, websocket: WebSocket, config_type: str, data: dict):
        """Handle save_config messages from WebSocket clients."""
        try:
            from utils.config_manager import get_config_manager
            from core.settings import reload_settings

            logger.info(f"Received config save request for {config_type}")

            # Save to runtime.json using config_manager
            config_manager = get_config_manager()
            success = await config_manager.save_runtime_config(config_type, data)

            if not success:
                await websocket.send_json({
                    "type": "save_config_response",
                    "success": False,
                    "message": f"Failed to save configuration for {config_type}"
                })
                return

            # Reload settings from JSON file
            new_settings = reload_settings()
            self.settings = new_settings  # Update connection manager settings

            # Get the updated config data
            updated_config = new_settings.get_robot_config(config_type)

            # Send success response
            await websocket.send_json({
                "type": "save_config_response",
                "success": True,
                "message": f"Configuration for {config_type} saved successfully"
            })

            # Broadcast update to all clients WITH the updated data
            await self.broadcast({
                "type": "config_updated",
                "config_type": config_type,
                "data": {
                    "config_type": config_type,
                    "content": updated_config
                }
            })

            logger.info(f"Configuration for {config_type} saved and broadcasted successfully")

        except Exception as e:
            logger.error(f"Error saving config: {e}", exc_info=True)
            await websocket.send_json({
                "type": "save_config_response",
                "success": False,
                "message": f"Error saving configuration: {str(e)}"
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
            elif msg_type == 'save_config':
                await self.handle_config_save(
                    websocket,
                    message.get('config_type'),
                    message.get('data')
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