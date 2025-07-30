# websocket_handlers.py
# Updated to use the new service layer architecture
from fastapi import WebSocket
from typing import Dict, Optional
from utils.logger import get_logger
from datetime import datetime
import time
import asyncio
from services.orchestrator import RobotOrchestrator
from services.command_service import RobotCommandService, CommandType, CommandPriority
from services.protocol_service import ProtocolExecutionService
from core.state_manager import AtomicStateManager, RobotState

logger = get_logger("websocket_handler")

class WebsocketHandler:
    def __init__(
        self, 
        orchestrator: RobotOrchestrator,
        command_service: RobotCommandService,
        protocol_service: ProtocolExecutionService,
        state_manager: AtomicStateManager,
        connection_manager
    ):
        # Store references to services
        self.orchestrator = orchestrator
        self.command_service = command_service
        self.protocol_service = protocol_service
        self.state_manager = state_manager
        self.connection_manager = connection_manager

        # Initialize connection tracking
        self.active_connections = []
        self.server_status = "Connected"
        self.last_status = {}
        
        # Background tasks
        self._status_monitor_task: Optional[asyncio.Task] = None

    async def connect(self, websocket: WebSocket):
        """Handle new WebSocket connection"""
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"WebSocket connected. Total connections: {len(self.active_connections)}")

    async def disconnect(self, websocket: WebSocket):
        """Handle WebSocket disconnection"""
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        logger.info(f"WebSocket disconnected. Total connections: {len(self.active_connections)}")

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

            # Send current robot status - only the 4 required statuses
            try:
                # Get system status from orchestrator
                system_status = await self.orchestrator.get_system_status()
                
                # Send backend status based on system state
                backend_status = "connected" if system_status.system_state.value == "ready" else "disconnected"
                await websocket.send_json({
                    "type": "status_update",
                    "data": {
                        "type": "backend",
                        "status": backend_status
                    },
                    "timestamp": datetime.now().isoformat()
                })
                
                # Send robot status updates - check if robots exist and their states
                robot_statuses = {
                    "meca": "disconnected",
                    "arduino": "disconnected", 
                    "ot2": "disconnected"
                }
                
                # Update robot statuses based on actual robot states
                for robot_id, robot_info in system_status.robot_details.items():
                    robot_state = robot_info.get("state", "disconnected")
                    if "meca" in robot_id.lower():
                        robot_statuses["meca"] = "connected" if robot_state in ["idle", "busy"] else "disconnected"
                    elif "ot2" in robot_id.lower():
                        robot_statuses["ot2"] = "connected" if robot_state in ["idle", "busy"] else "disconnected"
                    elif "arduino" in robot_id.lower():
                        robot_statuses["arduino"] = "connected" if robot_state in ["idle", "busy"] else "disconnected"
                
                # Send individual robot status updates
                for robot_type, status in robot_statuses.items():
                    await websocket.send_json({
                        "type": "status_update",
                        "data": {
                            "type": robot_type,
                            "status": status
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
                # Get current status from orchestrator
                try:
                    system_status = await self.orchestrator.get_system_status()
                    logger.info(f"Status request received. System state: {system_status.system_state.value}")

                    # Send individual status updates for each component
                    # Backend status based on system state
                    backend_status = "connected" if system_status.system_state.value == "ready" else "disconnected"
                    await websocket.send_json({
                        "type": "status_update",
                        "data": {
                            "type": "backend",
                            "status": backend_status
                        },
                        "timestamp": datetime.now().isoformat()
                    })
                    
                    # Send robot status updates - check if robots exist and their states
                    robot_statuses = {
                        "meca": "disconnected",
                        "arduino": "disconnected", 
                        "ot2": "disconnected"
                    }
                    
                    # Update robot statuses based on actual robot states
                    for robot_id, robot_info in system_status.robot_details.items():
                        robot_type = robot_info.get("state", "disconnected")
                        if "meca" in robot_id.lower():
                            robot_statuses["meca"] = "connected" if robot_type in ["idle", "busy"] else "disconnected"
                        elif "ot2" in robot_id.lower():
                            robot_statuses["ot2"] = "connected" if robot_type in ["idle", "busy"] else "disconnected"
                        elif "arduino" in robot_id.lower():
                            robot_statuses["arduino"] = "connected" if robot_type in ["idle", "busy"] else "disconnected"
                    
                    # Send individual robot status updates
                    for robot_type, status in robot_statuses.items():
                        await websocket.send_json({
                            "type": "status_update",
                            "data": {
                                "type": robot_type,
                                "status": status
                            },
                            "timestamp": datetime.now().isoformat()
                        })
                except Exception as e:
                    logger.error(f"Error getting system status: {e}")
                    await websocket.send_json({
                        "type": "error",
                        "message": f"Failed to get status: {str(e)}",
                        "timestamp": datetime.now().isoformat()
                    })
                return

            if msg_type == "command":
                command_type = message.get("command_type")
                command_data = message.get("data", {})
                command_id = message.get("commandId", str(int(time.time())))

                logger.info(f"*** WEBSOCKET: Received command: {command_type} with data: {command_data}, commandId: {command_id}")

                # Prepare base response structure
                response = {
                    "type": "command_response",
                    "commandId": command_id,
                    "command_type": command_type,  # Include the command_type in the response
                    "timestamp": datetime.now().isoformat(),
                }

                # Route to appropriate command handler
                if command_type == "emergency_stop":
                    try:
                        robots = command_data.get("robots", [])
                        if not robots:  # Emergency stop all if no specific robots
                            result = await self.orchestrator.emergency_stop_all(
                                reason="Emergency stop requested via WebSocket"
                            )
                        else:
                            # Emergency stop specific robots
                            results = {}
                            for robot_id in robots:
                                cmd_result = await self.command_service.submit_command(
                                    robot_id=robot_id,
                                    command_type=CommandType.EMERGENCY_STOP,
                                    parameters={},
                                    priority=CommandPriority.EMERGENCY,
                                    timeout=10.0
                                )
                                results[robot_id] = cmd_result.success
                            result = type('obj', (object,), {'success': True, 'data': results})()
                        
                        if result.success:
                            response.update({
                                "status": "success",
                                "message": "Emergency stop executed successfully",
                                "results": result.data if hasattr(result, 'data') else None
                            })
                        else:
                            response.update({
                                "status": "error",
                                "message": f"Emergency stop failed: {result.error}"
                            })
                    except Exception as e:
                        logger.error(f"Emergency stop error: {e}")
                        response.update({
                            "status": "error",
                            "message": f"Emergency stop failed: {str(e)}"
                        })
                elif command_type == "ot2_protocol":
                    # Submit OT2 protocol execution command through command service
                    try:
                        result = await self.command_service.submit_command(
                            robot_id="ot2",
                            command_type=CommandType.PROTOCOL_EXECUTION,
                            parameters=command_data,
                            priority=CommandPriority.NORMAL,
                            timeout=600.0
                        )
                        
                        if result.success:
                            response.update({
                                "status": "success",
                                "message": "OT2 protocol command submitted successfully",
                                "command_id": result.data
                            })
                        else:
                            response.update({
                                "status": "error",
                                "message": f"OT2 protocol failed: {result.error}"
                            })
                    except Exception as e:
                        logger.error(f"OT2 protocol error: {e}")
                        response.update({
                            "status": "error",
                            "message": f"Failed to start OT2 protocol: {str(e)}"
                        })
                elif command_type == "meca_pickup":
                    try:
                        # Submit pickup sequence command through command service
                        start = command_data.get("start", 0)
                        count = command_data.get("count", 5)
                        is_last_batch = command_data.get("is_last_batch", False)
                        
                        logger.info(f"*** WEBSOCKET: Submitting meca_pickup command with start={start}, count={count}")
                        
                        result = await self.command_service.submit_command(
                            robot_id="meca",
                            command_type=CommandType.PICKUP_SEQUENCE,
                            parameters={
                                "start": start,
                                "count": count,
                                "operation_type": "pickup_wafer_sequence",
                                "is_last_batch": is_last_batch
                            },
                            priority=CommandPriority.NORMAL,
                            timeout=600.0
                        )
                        
                        logger.info(f"*** WEBSOCKET: Command submission result: {result.success}, data: {result.data}, error: {result.error}")
                        
                        if result.success:
                            response.update({
                                "status": "success",
                                "message": "Meca pickup command submitted successfully",
                                "command_id": result.data
                            })
                        else:
                            response.update({
                                "status": "error",
                                "message": f"Meca pickup failed: {result.error}"
                            })
                    except Exception as e:
                        response.update({
                            "status": "error", 
                            "message": f"Meca pickup failed: {str(e)}"
                        })
                elif command_type == "meca_drop":
                    try:
                        # Submit drop sequence command through command service
                        start = command_data.get("start", 0)
                        count = command_data.get("count", 5)
                        is_last_batch = command_data.get("is_last_batch", False)
                        
                        result = await self.command_service.submit_command(
                            robot_id="meca",
                            command_type=CommandType.DROP_SEQUENCE,
                            parameters={
                                "start": start,
                                "count": count,
                                "operation_type": "drop_wafer_sequence",
                                "is_last_batch": is_last_batch
                            },
                            priority=CommandPriority.NORMAL,
                            timeout=600.0
                        )
                        
                        if result.success:
                            response.update({
                                "status": "success",
                                "message": "Meca drop command submitted successfully",
                                "command_id": result.data
                            })
                        else:
                            response.update({
                                "status": "error",
                                "message": f"Meca drop failed: {result.error}"
                            })
                    except Exception as e:
                        response.update({
                            "status": "error",
                            "message": f"Meca drop sequence failed: {str(e)}"
                        })
                # Support both command types for carousel operations
                elif command_type in ["meca_carousel", "carousel"]:
                    try:
                        # Submit carousel sequence command through command service
                        start = command_data.get("start", 0)
                        count = command_data.get("count", 11)  # Default carousel count
                        is_last_batch = command_data.get("is_last_batch", False)
                        
                        result = await self.command_service.submit_command(
                            robot_id="meca",
                            command_type=CommandType.CAROUSEL_SEQUENCE,
                            parameters={
                                "start": start,
                                "count": count,
                                "operation_type": "carousel_wafer_sequence",
                                "is_last_batch": is_last_batch
                            },
                            priority=CommandPriority.NORMAL,
                            timeout=900.0  # 15 minutes timeout
                        )
                        
                        if result.success:
                            response.update({
                                "status": "success",
                                "message": "Meca carousel command submitted successfully",
                                "command_id": result.data
                            })
                        else:
                            response.update({
                                "status": "error",
                                "message": f"Meca carousel failed: {result.error}"
                            })
                    except Exception as e:
                        response.update({
                            "status": "error",
                            "message": f"Meca carousel sequence failed: {str(e)}"
                        })
                # Handle arduino commands
                elif command_type.startswith("arduino_"):
                    try:
                        operation = command_data.get("operation", "")
                        arduino_command = command_data.get("command", operation)
                        priority = command_data.get("priority", "normal")
                        
                        # Map priority
                        priority_map = {
                            "low": CommandPriority.LOW,
                            "normal": CommandPriority.NORMAL,
                            "high": CommandPriority.HIGH,
                            "critical": CommandPriority.CRITICAL,
                            "emergency": CommandPriority.EMERGENCY
                        }
                        cmd_priority = priority_map.get(priority.lower(), CommandPriority.NORMAL)
                        
                        logger.info(f"Handling Arduino operation: {operation}")
                        
                        result = await self.command_service.submit_command(
                            robot_id="arduino",
                            command_type=arduino_command,
                            parameters=command_data.get("parameters", {}),
                            priority=cmd_priority,
                            timeout=60.0
                        )
                        
                        if result.success:
                            response.update({
                                "status": "success",
                                "message": f"Arduino {operation} command submitted successfully",
                                "command_id": result.data
                            })
                        else:
                            response.update({
                                "status": "error",
                                "message": f"Arduino operation failed: {result.error}"
                            })
                    except Exception as e:
                        response.update({
                            "status": "error",
                            "message": f"Arduino operation failed: {str(e)}"
                        })
                elif command_type == "pause_system":
                    # System-wide pause functionality
                    try:
                        pause_reason = command_data.get("reason", "User requested pause")
                        current_step = command_data.get("current_step", 0)
                        pause_all = command_data.get("pause_all_operations", True)
                        
                        logger.info(f"System pause requested: {pause_reason}")
                        
                        # Pause through orchestrator
                        pause_result = await self.orchestrator.pause_all_operations(
                            reason=pause_reason,
                            metadata={"current_step": current_step, "pause_all": pause_all}
                        )
                        
                        if pause_result.success:
                            response.update({
                                "status": "success",
                                "message": "System paused successfully",
                                "paused_operations": pause_result.data.get("paused_operations", [])
                            })
                            
                            # Broadcast pause status to all clients
                            await self.broadcast({
                                "type": "system_status_update",
                                "data": {
                                    "system_paused": True,
                                    "pause_reason": pause_reason,
                                    "current_step": current_step
                                }
                            })
                        else:
                            response.update({
                                "status": "error",
                                "message": f"Failed to pause system: {pause_result.error}"
                            })
                    except Exception as e:
                        logger.error(f"System pause error: {e}")
                        response.update({
                            "status": "error",
                            "message": f"System pause failed: {str(e)}"
                        })
                elif command_type == "resume_system":
                    # System-wide resume functionality
                    try:
                        current_step = command_data.get("current_step", 0)
                        resume_all = command_data.get("resume_all_operations", True)
                        
                        logger.info("System resume requested")
                        
                        # Resume through orchestrator
                        resume_result = await self.orchestrator.resume_all_operations(
                            metadata={"current_step": current_step, "resume_all": resume_all}
                        )
                        
                        if resume_result.success:
                            response.update({
                                "status": "success",
                                "message": "System resumed successfully",
                                "resumed_operations": resume_result.data.get("resumed_operations", [])
                            })
                            
                            # Broadcast resume status to all clients
                            await self.broadcast({
                                "type": "system_status_update",
                                "data": {
                                    "system_paused": False,
                                    "pause_reason": "",
                                    "current_step": current_step
                                }
                            })
                        else:
                            response.update({
                                "status": "error",
                                "message": f"Failed to resume system: {resume_result.error}"
                            })
                    except Exception as e:
                        logger.error(f"System resume error: {e}")
                        response.update({
                            "status": "error",
                            "message": f"System resume failed: {str(e)}"
                        })
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
            system_status = await self.orchestrator.get_system_status()

            # Broadcast backend status based on system state
            backend_status = "connected" if system_status.system_state.value == "ready" else "disconnected"
            if self.last_status.get("backend") != backend_status:
                message = {
                    "type": "status_update",
                    "data": {
                        "type": "backend",
                        "status": backend_status
                    },
                    "timestamp": datetime.now().isoformat()
                }
                logger.info(f"Broadcasting backend status change: {self.last_status.get('backend', 'unknown')} -> {backend_status}")
                await self.broadcast(message)
                self.last_status["backend"] = backend_status

            # Broadcast robot status updates - only the 4 required statuses
            robot_statuses = {
                "meca": "disconnected",
                "arduino": "disconnected", 
                "ot2": "disconnected"
            }
            
            # Update robot statuses based on actual robot states
            for robot_id, robot_info in system_status.robot_details.items():
                robot_state = robot_info.get("state", "disconnected")
                if "meca" in robot_id.lower():
                    robot_statuses["meca"] = "connected" if robot_state in ["idle", "busy"] else "disconnected"
                elif "ot2" in robot_id.lower():
                    robot_statuses["ot2"] = "connected" if robot_state in ["idle", "busy"] else "disconnected"
                elif "arduino" in robot_id.lower():
                    robot_statuses["arduino"] = "connected" if robot_state in ["idle", "busy"] else "disconnected"
            
            # Send individual robot status updates only if changed
            for robot_type, status in robot_statuses.items():
                if self.last_status.get(robot_type) != status:
                    message = {
                        "type": "status_update",
                        "data": {
                            "type": robot_type,
                            "status": status
                        },
                        "timestamp": datetime.now().isoformat()
                    }
                    logger.info(f"Broadcasting status change for {robot_type}: {self.last_status.get(robot_type, 'unknown')} -> {status}")
                    await self.broadcast(message)
                    self.last_status[robot_type] = status
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


def get_websocket_handler(
    orchestrator: RobotOrchestrator,
    command_service: RobotCommandService,
    protocol_service: ProtocolExecutionService,
    state_manager: AtomicStateManager,
    connection_manager
) -> WebsocketHandler:
    """Factory function to create a WebSocket handler instance."""
    return WebsocketHandler(
        orchestrator,
        command_service,
        protocol_service,
        state_manager,
        connection_manager
    )