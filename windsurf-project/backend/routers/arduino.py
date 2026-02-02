"""
Router for Arduino control endpoints.
Updated to use the new service layer architecture.
"""
from fastapi import APIRouter
from typing import Dict, Any
from dependencies import CommandServiceDep
from services.command_service import RobotCommandService, CommandType, CommandPriority
from common.helpers import RouterHelper, CommandHelper, ResponseHelper
from utils.logger import get_logger

router = APIRouter()
logger = get_logger("arduino_router")

@router.post("/command")
async def send_command(
    data: Dict[str, Any],
    command_service: RobotCommandService = CommandServiceDep()
):
    """Send a command to the Arduino through the command service."""
    return await CommandHelper.submit_robot_command(
        command_service=command_service,
        robot_id="arduino_001",
        command_type="custom_command",  # Custom command type for Arduino
        parameters={
            "action": data.get("action", "unknown"),
            "data": data
        },
        priority=CommandPriority.NORMAL,
        timeout=30.0,
        success_message="Command sent to Arduino",
    )

@router.get("/status")
async def get_status():
    """Get the current status of the Arduino."""
    # Arduino is handled as a command interface rather than a full robot service
    # Return a basic status response indicating Arduino is available via commands
    return ResponseHelper.create_success_response(
        data={
            "robot_id": "arduino_001",
            "robot_type": "arduino",
            "connection_status": "available_via_commands",
            "message": "Arduino operations available through command service",
            "available_operations": [
                "send_command",
                "emergency_stop",
                "list_active_commands",
                "get_command_status"
            ],
            "endpoints": {
                "send_command": "/api/arduino/command",
                "emergency_stop": "/api/arduino/stop",
                "list_commands": "/api/arduino/commands",
                "command_status": "/api/arduino/commands/{command_id}/status"
            }
        }
    )

@router.post("/stop")
async def stop_arduino(
    command_service: RobotCommandService = CommandServiceDep()
):
    """Stop the Arduino operations."""
    return await CommandHelper.submit_robot_command(
        command_service=command_service,
        robot_id="arduino_001",
        command_type=CommandType.EMERGENCY_STOP,
        parameters={},
        priority=CommandPriority.EMERGENCY,
        timeout=10.0,
        success_message="Arduino stop command submitted",
    )

@router.get("/commands")
async def list_active_commands(
    command_service: RobotCommandService = CommandServiceDep()
):
    """List active commands for Arduino."""
    commands = await RouterHelper.execute_service_operation(
        command_service.list_active_commands,
        "list_arduino_commands",
        logger,
        robot_id="arduino_001",
    )
    return ResponseHelper.create_success_response(commands=commands)

@router.get("/commands/{command_id}/status")
async def get_command_status(
    command_id: str,
    command_service: RobotCommandService = CommandServiceDep()
):
    """Get status of a specific Arduino command."""
    command_status = await RouterHelper.execute_service_operation(
        command_service.get_command_status,
        "get_arduino_command_status",
        logger,
        command_id,
    )
    return ResponseHelper.create_success_response(command_status=command_status)
