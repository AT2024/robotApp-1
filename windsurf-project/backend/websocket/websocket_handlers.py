# websocket_handlers.py
from fastapi import WebSocket
from typing import Dict
from utils.logger import get_logger
from datetime import datetime
import time
# Import the drop sequence function and configuration
from routers.meca import drop_wafer_sequence, carousel_wafer_sequence
from config.meca_config import total_wafers

logger = get_logger("websocket_handler")

class WebsocketHandler:
    def __init__(self, robot_manager, connection_manager):
        # Store references to managers
        self.robot_manager = robot_manager
        self.connection_manager = connection_manager

        # Initialize connection tracking
        self.active_connections = []
        self.server_status = "Connected"
        self.last_status = {}

    async def send_status_update(self, websocket: WebSocket, device: str, status: str):
        """Send status update only if there's a change"""
        normalized_status = status.lower()

        # Check if status has changed
        if self.last_status.get(device) != normalized_status:
            logger.info(f"Status changed for {device}: {self.last_status.get(device, 'unknown')} -> {normalized_status}")

            # Update last known status
            self.last_status[device] = normalized_status

            # Send the update
            await websocket.send_json({
                "type": "status_update",
                "data": {
                    "type": device,
                    "status": normalized_status
                },
                "timestamp": datetime.now().isoformat()
            })

    async def connect(self, websocket: WebSocket):
        """
        Handle new WebSocket connections.
        This method is required by FastAPI's WebSocket implementation.
        """
        try:
            # Accept the connection
            await websocket.accept()

            # Add to active connections
            self.active_connections.append(websocket)

            # Log the connection
            logger.info(f"New WebSocket connection established. Total connections: {len(self.active_connections)}")

            # Send initial status
            await self.broadcast_server_status()

            # Send welcome message
            await websocket.send_json({
                "type": "connection_established",
                "message": "Successfully connected to server",
                "timestamp": datetime.now().isoformat()
            })

            # Send current robot status
            try:
                current_status = self.robot_manager.get_status()
                for device, status in current_status.items():
                    await websocket.send_json({
                        "type": "status_update",
                        "data": {
                            "type": device,
                            "status": status.lower()
                        },
                        "timestamp": datetime.now().isoformat()
                    })
            except Exception as e:
                logger.error(f"Error sending initial status: {e}")

        except Exception as e:
            logger.error(f"Error establishing WebSocket connection: {e}")
            if websocket in self.active_connections:
                self.active_connections.remove(websocket)
            raise

    async def disconnect(self, websocket: WebSocket):
        """
        Handle WebSocket disconnections.
        This method is required by FastAPI's WebSocket implementation.
        """
        try:
            if websocket in self.active_connections:
                self.active_connections.remove(websocket)
                await websocket.close()
                logger.info(f"WebSocket disconnected. Remaining connections: {len(self.active_connections)}")
                await self.broadcast_server_status()
        except Exception as e:
            logger.error(f"Error during WebSocket disconnection: {e}")

    async def broadcast(self, message: dict):
        """Broadcast a message to all connected clients."""
        disconnected_clients = []

        # Add timestamp to message
        message_with_timestamp = {
            **message,
            "timestamp": datetime.now().isoformat()
        }

        for websocket in self.active_connections:
            try:
                await websocket.send_json(message_with_timestamp)
            except Exception as e:
                logger.error(f"Error broadcasting message: {e}")
                disconnected_clients.append(websocket)

        # Clean up disconnected clients
        for websocket in disconnected_clients:
            await self.disconnect(websocket)

    async def handle_message(self, websocket: WebSocket, message: dict):
        """Handle incoming WebSocket messages."""
        try:
            msg_type = message.get("type")
            logger.info(f"Received message of type: {msg_type}")

            if msg_type == "get_status":
                # Get current status from robot manager
                current_status = self.robot_manager.get_status()
                logger.info(f"Status request received. Current status: {current_status}")

                # Send status updates for each device
                for device, status in current_status.items():
                    await self.send_status_update(websocket, device, status)
                return

            if msg_type == "command":
                command_type = message.get("command_type")
                command_data = message.get("data", {})
                command_id = message.get("commandId", str(int(time.time())))

                logger.info(f"Received command: {command_type} with data: {command_data}")

                # Prepare base response structure
                response = {
                    "type": "command_response",
                    "commandId": command_id,
                    "command_type": command_type,  # Include the command_type in the response
                    "timestamp": datetime.now().isoformat(),
                }

                # Route to appropriate command handler
                if command_type == "emergency_stop":
                    await self.robot_manager.emergency_stop(command_data.get("robots"))
                    response.update(
                        {
                            "status": "success",
                            "message": "Emergency stop executed successfully",
                        }
                    )
                elif command_type == "ot2_protocol":
                    # Pass the data directly to the robot manager's protocol runner
                    try:
                        result = await self.robot_manager.run_ot2_protocol_direct(
                            command_data
                        )
                        response.update(
                            {
                                "status": "success",
                                "message": "OT2 protocol started successfully",
                                "result": result,
                            }
                        )
                    except Exception as e:
                        logger.error(f"OT2 protocol error: {e}")
                        response.update(
                            {
                                "status": "error",
                                "message": f"Failed to start OT2 protocol: {str(e)}",
                            }
                        )
                elif command_type == "meca_pickup":
                    try:
                        # Import the pickup sequence function
                        from routers.meca import pickup_wafer_sequence

                        # Execute the pickup sequence
                        await pickup_wafer_sequence(self.robot_manager)
                        response.update(
                            {
                                "status": "success",
                                "message": "Meca pickup sequence completed successfully",
                            }
                        )
                    except Exception as e:
                        response.update(
                            {"status": "error", "message": f"Meca pickup failed: {str(e)}"}
                        )
                elif command_type == "meca_drop":
                    try:
                        # Import the drop sequence function and configuration
                        from routers.meca import drop_wafer_sequence, return_robot_to_home
                        from config.meca_config import total_wafers, EMPTY_SPEED

                        # Get parameters with defaults
                        start = command_data.get("start", 0)
                        count = command_data.get("count", 5)
                        end = min(start + count, total_wafers)
                        is_last_batch = command_data.get("is_last_batch", False)

                        # Execute the drop sequence
                        await drop_wafer_sequence(self.robot_manager, start, end)

                        # Return to home if this is the last batch
                        if is_last_batch:
                            await return_robot_to_home(
                                self.robot_manager.meca_robot, EMPTY_SPEED
                            )
                            logger.info("Completed drop sequence, robot returned to home")

                        response.update(
                            {
                                "status": "success",
                                "message": f"Meca drop sequence completed successfully for wafers {start+1} to {end}",
                            }
                        )
                    except Exception as e:
                        response.update(
                            {
                                "status": "error",
                                "message": f"Meca drop sequence failed: {str(e)}",
                            }
                        )
                # Support both command types for carousel operations
                elif command_type in ["meca_carousel", "carousel"]:
                    try:
                        # Import the carousel sequence function
                        from routers.meca import (
                            carousel_wafer_sequence,
                            return_robot_to_home,
                        )
                        from config.meca_config import (
                            total_wafers,
                            wafers_per_carousel,
                            EMPTY_SPEED,
                        )

                        # Get parameters with defaults
                        start = command_data.get("start", 0)
                        count = command_data.get("count", wafers_per_carousel)
                        end = min(start + count, total_wafers)
                        is_last_batch = command_data.get("is_last_batch", False)

                        # Execute the carousel sequence
                        await carousel_wafer_sequence(self.robot_manager, start, end)

                        # Return to home if this is the last batch
                        if is_last_batch:
                            await return_robot_to_home(
                                self.robot_manager.meca_robot, EMPTY_SPEED
                            )
                            logger.info(
                                "Completed carousel sequence, robot returned to home"
                            )

                        response.update(
                            {
                                "status": "success",
                                "message": f"Meca carousel sequence completed successfully for wafers {start+1} to {end}",
                            }
                        )
                    except Exception as e:
                        response.update(
                            {
                                "status": "error",
                                "message": f"Meca carousel sequence failed: {str(e)}",
                            }
                        )
                # Handle arduino commands
                elif command_type.startswith("arduino_"):
                    try:
                        # Add code for handling Arduino commands
                        operation = command_data.get("operation", "")
                        logger.info(f"Handling Arduino operation: {operation}")

                        # Implement the actual Arduino command logic here
                        # This is a placeholder that simulates success
                        response.update(
                            {
                                "status": "success",
                                "message": f"Arduino {operation} operation executed successfully",
                            }
                        )
                    except Exception as e:
                        response.update(
                            {
                                "status": "error",
                                "message": f"Arduino operation failed: {str(e)}",
                            }
                        )
                else:
                    response.update(
                        {
                            "status": "error",
                            "message": f"Unknown command type: {command_type}",
                        }
                    )

                await websocket.send_json(response)
                return

            # Handle other message types
            await self.connection_manager.handle_message(websocket, message)

        except Exception as e:
            logger.error(f"Error handling message: {e}")
            error_response = {
                "type": "error",
                "message": str(e),
                "timestamp": datetime.now().isoformat(),
            }
            try:
                await websocket.send_json(error_response)
            except Exception as send_error:
                logger.error(f"Error sending error response: {send_error}")

    async def broadcast_server_status(self):
        try:
            status = self.robot_manager.get_status()

            for device, state in status.items():
                normalized_state = state.lower() if state else "disconnected"

                # Only broadcast if status has changed
                if self.last_status.get(device) != normalized_state:
                    message = {
                        "type": "status_update",
                        "data": {
                            "type": device,
                            "status": normalized_state
                        },
                        "timestamp": datetime.now().isoformat()
                    }
                    logger.info(f"Broadcasting status change for {device}: {self.last_status.get(device, 'unknown')} -> {normalized_state}")
                    await self.broadcast(message)
                    self.last_status[device] = normalized_state
        except Exception as e:
            logger.error(f"Error broadcasting status: {e}")

    async def handle_config_request(self, websocket: WebSocket, config_type: str):
        """Handle configuration data requests."""
        try:
            # Route to connection manager's config handler
            await self.connection_manager.handle_config_request(websocket, config_type)
        except Exception as e:
            logger.error(f"Error handling config request: {e}")
            await websocket.send_json({
                "type": "error",
                "message": f"Failed to handle config request: {str(e)}"
            })


def get_websocket_handler(robot_manager, connection_manager) -> WebsocketHandler:
    """Factory function to create a WebSocket handler instance."""
    return WebsocketHandler(robot_manager, connection_manager)