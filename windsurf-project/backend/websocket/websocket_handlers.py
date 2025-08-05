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

        # Debug logging for initialization
        logger.info(f"*** WEBSOCKET HANDLER INIT: Orchestrator type: {type(orchestrator)}")
        logger.info(f"*** WEBSOCKET HANDLER INIT: Orchestrator protocol service: {getattr(orchestrator, '_protocol_service', 'NOT_FOUND')}")
        logger.info(f"*** WEBSOCKET HANDLER INIT: Protocol service parameter: {protocol_service}")
        logger.info(f"*** WEBSOCKET HANDLER INIT: Command service: {command_service}")

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
                    # IMMEDIATE ACKNOWLEDGMENT - send response without waiting for execution
                    logger.critical(f"🚨 EMERGENCY STOP command received - sending immediate acknowledgment")
                    
                    immediate_response = {
                        "type": "command_response",
                        "commandId": command_id,
                        "command_type": command_type,
                        "status": "acknowledged",
                        "message": "Emergency stop command received - validating robot states",
                        "timestamp": datetime.now().isoformat(),
                    }
                    await websocket.send_json(immediate_response)
                    
                    # Execute emergency stop asynchronously without blocking response
                    async def execute_emergency_stop():
                        try:
                            robots = command_data.get("robots", {})
                            logger.critical(f"🚨 Executing emergency stop for robots: {robots}")
                            
                            # Validate actual robot connection states from backend
                            system_status = await self.orchestrator.get_system_status()
                            connected_robots = []
                            disconnected_robots = []
                            robot_statuses = {}
                            
                            for robot_id, frontend_connected in robots.items():
                                # Check actual backend robot state
                                backend_robot_info = system_status.robot_details.get(robot_id)
                                if backend_robot_info:
                                    backend_state = backend_robot_info.get("state", "disconnected")
                                    backend_operational = backend_robot_info.get("operational", False)
                                    robot_statuses[robot_id] = {
                                        "frontend_connected": frontend_connected,
                                        "backend_state": backend_state,
                                        "backend_operational": backend_operational,
                                        "can_stop": backend_operational and backend_state in ["idle", "busy"]
                                    }
                                    
                                    if robot_statuses[robot_id]["can_stop"]:
                                        connected_robots.append(robot_id)
                                    else:
                                        disconnected_robots.append(robot_id)
                                else:
                                    robot_statuses[robot_id] = {
                                        "frontend_connected": frontend_connected,
                                        "backend_state": "not_found",
                                        "backend_operational": False,
                                        "can_stop": False
                                    }
                                    disconnected_robots.append(robot_id)
                            
                            logger.critical(f"🔍 Robot connection validation: Connected={connected_robots}, Disconnected={disconnected_robots}")
                            
                            # Send validation status to user
                            validation_response = {
                                "type": "command_response",
                                "commandId": command_id,
                                "command_type": command_type,
                                "status": "validating",
                                "message": f"Found {len(connected_robots)} operational robots, {len(disconnected_robots)} unavailable",
                                "data": {
                                    "operational_robots": connected_robots,
                                    "unavailable_robots": disconnected_robots,
                                    "robot_details": robot_statuses
                                },
                                "timestamp": datetime.now().isoformat(),
                            }
                            await websocket.send_json(validation_response)
                            
                            # Execute emergency stop on operational robots only
                            emergency_stop_results = {}
                            tasks = []
                            
                            if not connected_robots:
                                # NO ROBOTS AVAILABLE - Send critical error
                                logger.error(f"❌ CRITICAL: No operational robots found for emergency stop!")
                                error_response = {
                                    "type": "command_response",
                                    "commandId": command_id,
                                    "command_type": command_type,
                                    "status": "error",
                                    "message": "EMERGENCY STOP FAILED: No operational robots found! Check robot connections.",
                                    "data": {
                                        "error_type": "no_operational_robots",
                                        "robot_statuses": robot_statuses,
                                        "troubleshooting": "Check robot power, network, and service status"
                                    },
                                    "timestamp": datetime.now().isoformat(),
                                }
                                await websocket.send_json(error_response)
                                return
                            
                            # Execute emergency stop directly on robot services (bypass command queue)
                            logger.critical(f"🚨 Executing IMMEDIATE emergency stop on {len(connected_robots)} operational robots")
                            
                            # Create direct service call tasks
                            tasks = []
                            for robot_id in connected_robots:
                                async def emergency_stop_robot(robot_id):
                                    try:
                                        robot_service = await self.orchestrator.get_robot_service(robot_id)
                                        if robot_service:
                                            logger.critical(f"🚨 Calling direct emergency_stop() for {robot_id}")
                                            emergency_result = await robot_service.emergency_stop()
                                            return robot_id, emergency_result
                                        else:
                                            logger.error(f"❌ No service found for robot {robot_id}")
                                            return robot_id, None
                                    except Exception as e:
                                        logger.error(f"❌ Emergency stop exception for {robot_id}: {e}")
                                        return robot_id, e
                                
                                tasks.append(emergency_stop_robot(robot_id))
                            
                            # Execute emergency stops in parallel (bypassing queue)
                            results = await asyncio.gather(*tasks, return_exceptions=True)
                            
                            # Process results
                            successful_stops = []
                            failed_stops = []
                            
                            for result in results:
                                if isinstance(result, Exception):
                                    failed_stops.append({"robot_id": "unknown", "error": str(result)})
                                    logger.error(f"❌ Emergency stop task failed: {result}")
                                elif isinstance(result, tuple) and len(result) == 2:
                                    robot_id, emergency_result = result
                                    if isinstance(emergency_result, Exception):
                                        failed_stops.append({"robot_id": robot_id, "error": str(emergency_result)})
                                        logger.error(f"❌ Emergency stop failed for {robot_id}: {emergency_result}")
                                    elif emergency_result and hasattr(emergency_result, 'success') and emergency_result.success:
                                        successful_stops.append(robot_id)
                                        logger.critical(f"✅ IMMEDIATE emergency stop executed for {robot_id}")
                                    elif emergency_result is None:
                                        failed_stops.append({"robot_id": robot_id, "error": "Service not found"})
                                        logger.error(f"❌ Emergency stop failed for {robot_id}: Service not found")
                                    else:
                                        error_msg = getattr(emergency_result, 'error', 'Unknown error')
                                        failed_stops.append({"robot_id": robot_id, "error": error_msg})
                                        logger.error(f"❌ Emergency stop failed for {robot_id}: {error_msg}")
                                else:
                                    failed_stops.append({"robot_id": "unknown", "error": f"Unexpected result format: {result}"})
                                    logger.error(f"❌ Emergency stop unexpected result: {result}")
                            
                            # Send comprehensive final status
                            if successful_stops:
                                status = "partial_success" if failed_stops else "success"
                                message = f"Emergency stop: {len(successful_stops)} robots stopped, {len(failed_stops)} failed, {len(disconnected_robots)} unavailable"
                            else:
                                status = "error"
                                message = f"Emergency stop FAILED: All {len(connected_robots)} operational robots failed to stop"
                            
                            final_response = {
                                "type": "command_response",
                                "commandId": command_id,
                                "command_type": command_type,
                                "status": status,
                                "message": message,
                                "data": {
                                    "successful_stops": successful_stops,
                                    "failed_stops": failed_stops,
                                    "unavailable_robots": disconnected_robots,
                                    "total_requested": len(robots),
                                    "total_operational": len(connected_robots),
                                    "total_stopped": len(successful_stops)
                                },
                                "timestamp": datetime.now().isoformat(),
                            }
                            
                            await websocket.send_json(final_response)
                            logger.critical(f"🚨 Emergency stop completed: {len(successful_stops)}/{len(connected_robots)} operational robots stopped")
                            
                        except Exception as e:
                            logger.error(f"❌ Emergency stop execution failed with exception: {e}", exc_info=True)
                            error_response = {
                                "type": "command_response",
                                "commandId": command_id,
                                "command_type": command_type,
                                "status": "error",
                                "message": f"Emergency stop system error: {str(e)}",
                                "data": {
                                    "error_type": "system_error",
                                    "troubleshooting": "Check backend logs and robot service status"
                                },
                                "timestamp": datetime.now().isoformat(),
                            }
                            try:
                                await websocket.send_json(error_response)
                            except Exception:
                                pass  # Websocket might be closed
                    
                    # Start emergency stop execution without waiting
                    asyncio.create_task(execute_emergency_stop())
                    
                    # Return immediately - don't send another response
                    return
                
                elif command_type == "emergency_reset":
                    # Reset emergency stop state
                    try:
                        logger.info("🔄 Resetting emergency stop state via WebSocket")
                        result = await self.orchestrator.reset_emergency_stop()
                        
                        if result.success:
                            logger.info("✅ Emergency stop reset successful")
                            response.update({
                                "status": "success",
                                "message": "Emergency stop reset successfully",
                                "data": {"reset": True}
                            })
                        else:
                            logger.error(f"❌ Emergency stop reset failed: {result.error}")
                            response.update({
                                "status": "error",
                                "message": f"Emergency stop reset failed: {result.error}"
                            })
                    except Exception as e:
                        logger.error(f"Emergency stop reset error: {e}")
                        response.update({
                            "status": "error",
                            "message": f"Emergency stop reset failed: {str(e)}"
                        })
                
                elif command_type == "ot2_protocol":
                    # Execute OT2 protocol directly through OT2Service (bypassing complex ProtocolExecutionService)
                    try:
                        logger.info(f"Starting DIRECT OT2 protocol execution with data: {command_data}")
                        
                        # Get the OT2 service directly from orchestrator
                        ot2_service = await self.orchestrator.get_robot_service("ot2")
                        logger.info(f"Retrieved OT2 service: {ot2_service is not None}")
                        
                        if not ot2_service:
                            logger.error("OT2 service not available")
                            response.update({
                                "status": "error",
                                "message": "OT2 service not available - service initialization may have failed"
                            })
                            await websocket.send_json(response)
                            return
                        
                        # Execute protocol directly through OT2Service.run_protocol()
                        protocol_result = await ot2_service.run_protocol(**command_data)
                        
                        if protocol_result.success:
                            response.update({
                                "status": "success",
                                "message": "OT2 protocol executed successfully via direct service",
                                "result": protocol_result.data
                            })
                            logger.info(f"OT2 protocol completed successfully: {protocol_result.data}")
                        else:
                            response.update({
                                "status": "error",
                                "message": f"OT2 protocol failed: {protocol_result.error}"
                            })
                            logger.error(f"OT2 protocol execution failed: {protocol_result.error}")
                            
                    except Exception as e:
                        logger.error(f"Direct OT2 protocol execution error: {e}", exc_info=True)
                        response.update({
                            "status": "error",
                            "message": f"Failed to execute OT2 protocol directly: {str(e)}"
                        })
                elif command_type == "meca_pickup":
                    try:
                        # Submit pickup sequence command through command service
                        start = command_data.get("start", 0)
                        count = command_data.get("count", 5)
                        is_last_batch = command_data.get("is_last_batch", False)
                        current_step = command_data.get("current_step", 0)
                        step_name = command_data.get("step_name", "Create Pick Up")
                        
                        logger.info(f"*** WEBSOCKET: Submitting meca_pickup command for step {current_step} with start={start}, count={count}")
                        
                        # Start step tracking before submitting command
                        await self.state_manager.start_step(
                            robot_id="meca",
                            step_index=current_step,
                            step_name=step_name,
                            operation_type="pickup_sequence",
                            progress_data={"start": start, "count": count, "current_wafer_index": start}
                        )
                        
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
                        current_step = command_data.get("current_step", 7)
                        step_name = command_data.get("step_name", "Move to Baking Tray")
                        
                        logger.info(f"*** WEBSOCKET: Submitting meca_drop command for step {current_step} with start={start}, count={count}")
                        
                        # Start step tracking before submitting command
                        await self.state_manager.start_step(
                            robot_id="meca",
                            step_index=current_step,
                            step_name=step_name,
                            operation_type="drop_sequence",
                            progress_data={"start": start, "count": count, "current_wafer_index": start}
                        )
                        
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
                    # Step-aware pause functionality
                    try:
                        pause_reason = command_data.get("reason", "User requested pause")
                        current_step = command_data.get("current_step", 0)
                        step_name = command_data.get("step_name", f"Step {current_step}")
                        
                        logger.info(f"Step-aware pause requested for step {current_step} ({step_name}): {pause_reason}")
                        
                        # Get step states to find which robot is currently active
                        step_states = await self.state_manager.get_all_step_states()
                        active_robot = None
                        
                        # Find robot currently running the specified step
                        for robot_id, step_state in step_states.items():
                            if step_state and step_state.step_index == current_step and not step_state.paused:
                                active_robot = robot_id
                                break
                        
                        if active_robot:
                            # Pause the specific robot's current step
                            paused_step = await self.state_manager.pause_step(active_robot, pause_reason)
                            
                            if paused_step:
                                response.update({
                                    "status": "success",
                                    "message": f"Step {current_step} paused successfully for robot {active_robot}",
                                    "paused_step": {
                                        "step_index": paused_step.step_index,
                                        "step_name": paused_step.step_name,
                                        "robot_id": paused_step.robot_id,
                                        "progress": paused_step.progress_data
                                    }
                                })
                                
                                # Broadcast step-specific pause status to all clients
                                await self.broadcast({
                                    "type": "step_status_update",
                                    "data": {
                                        "step_index": current_step,
                                        "step_name": step_name,
                                        "robot_id": active_robot,
                                        "paused": True,
                                        "pause_reason": pause_reason,
                                        "progress": paused_step.progress_data
                                    }
                                })
                            else:
                                response.update({
                                    "status": "error",
                                    "message": f"Failed to pause step {current_step} for robot {active_robot}"
                                })
                        else:
                            response.update({
                                "status": "error",
                                "message": f"No active robot found for step {current_step}"
                            })
                            
                    except Exception as e:
                        logger.error(f"Step pause error: {e}")
                        response.update({
                            "status": "error",
                            "message": f"Step pause failed: {str(e)}"
                        })
                elif command_type == "resume_system":
                    # Step-aware resume functionality
                    try:
                        current_step = command_data.get("current_step", 0)
                        step_name = command_data.get("step_name", f"Step {current_step}")
                        
                        logger.info(f"Step-aware resume requested for step {current_step} ({step_name})")
                        
                        # Get step states to find which robot is paused for this step
                        step_states = await self.state_manager.get_all_step_states()
                        paused_robot = None
                        
                        # Find robot with paused step matching the current step
                        for robot_id, step_state in step_states.items():
                            if step_state and step_state.step_index == current_step and step_state.paused:
                                paused_robot = robot_id
                                break
                        
                        if paused_robot:
                            # Resume the specific robot's step
                            resumed_step = await self.state_manager.resume_step(paused_robot)
                            
                            if resumed_step:
                                response.update({
                                    "status": "success",
                                    "message": f"Step {current_step} resumed successfully for robot {paused_robot}",
                                    "resumed_step": {
                                        "step_index": resumed_step.step_index,
                                        "step_name": resumed_step.step_name,
                                        "robot_id": resumed_step.robot_id,
                                        "progress": resumed_step.progress_data
                                    }
                                })
                                
                                # Broadcast step-specific resume status to all clients
                                await self.broadcast({
                                    "type": "step_status_update",
                                    "data": {
                                        "step_index": current_step,
                                        "step_name": step_name,
                                        "robot_id": paused_robot,
                                        "paused": False,
                                        "pause_reason": "",
                                        "progress": resumed_step.progress_data
                                    }
                                })
                            else:
                                response.update({
                                    "status": "error",
                                    "message": f"Failed to resume step {current_step} for robot {paused_robot}"
                                })
                        else:
                            response.update({
                                "status": "error",
                                "message": f"No paused robot found for step {current_step}"
                            })
                            
                    except Exception as e:
                        logger.error(f"Step resume error: {e}")
                        response.update({
                            "status": "error",
                            "message": f"Step resume failed: {str(e)}"
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