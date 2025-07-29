"""
Router for Arduino control endpoints.
Updated to use the new service layer architecture.
"""
from fastapi import APIRouter, Depends, HTTPException
from typing import Dict, Any
from dependencies import OrchestratorDep, CommandServiceDep
from services.orchestrator import RobotOrchestrator
from services.command_service import RobotCommandService, CommandType, CommandPriority
from utils.logger import get_logger

router = APIRouter()
logger = get_logger("arduino_router")

@router.post("/command")
async def send_command(
    data: Dict[str, Any],
    command_service: RobotCommandService = CommandServiceDep()
):
    """Send a command to the Arduino through the command service."""
    try:
        # Submit Arduino command through the command service
        result = await command_service.submit_command(
            robot_id="arduino_001",
            command_type="custom_command",  # Custom command type for Arduino
            parameters={
                "action": data.get("action", "unknown"),
                "data": data
            },
            priority=CommandPriority.NORMAL,
            timeout=30.0
        )
        
        if not result.success:
            raise HTTPException(status_code=500, detail=result.error)
        
        return {
            "status": "success", 
            "command_id": result.data,
            "message": "Command sent to Arduino"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error sending command to Arduino: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/status")
async def get_status():
    """Get the current status of the Arduino."""
    try:
        # Arduino is handled as a command interface rather than a full robot service
        # Return a basic status response indicating Arduino is available via commands
        return {
            "status": "success", 
            "data": {
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
        }
    except Exception as e:
        logger.error(f"Error getting Arduino status: {e}")
        # Return a fallback status response
        return {
            "status": "success", 
            "data": {
                "robot_id": "arduino_001",
                "robot_type": "arduino",
                "connection_status": "unknown",
                "message": "Arduino command interface available",
                "error": str(e)
            }
        }

@router.post("/stop")
async def stop_arduino(
    command_service: RobotCommandService = CommandServiceDep()
):
    """Stop the Arduino operations."""
    try:
        # Submit emergency stop command for Arduino
        result = await command_service.submit_command(
            robot_id="arduino_001",
            command_type=CommandType.EMERGENCY_STOP,
            parameters={},
            priority=CommandPriority.EMERGENCY,
            timeout=10.0
        )
        
        if not result.success:
            raise HTTPException(status_code=500, detail=result.error)
        
        return {
            "status": "success", 
            "command_id": result.data,
            "message": "Arduino stop command submitted"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error stopping Arduino: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/commands")
async def list_active_commands(
    command_service: RobotCommandService = CommandServiceDep()
):
    """List active commands for Arduino."""
    try:
        result = await command_service.list_active_commands(robot_id="arduino_001")
        if not result.success:
            raise HTTPException(status_code=500, detail=result.error)
        return {"status": "success", "commands": result.data}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error listing Arduino commands: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/commands/{command_id}/status")
async def get_command_status(
    command_id: str,
    command_service: RobotCommandService = CommandServiceDep()
):
    """Get status of a specific Arduino command."""
    try:
        result = await command_service.get_command_status(command_id)
        if not result.success:
            raise HTTPException(status_code=404, detail=result.error)
        return {"status": "success", "command_status": result.data}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting Arduino command status: {e}")
        raise HTTPException(status_code=500, detail=str(e))
