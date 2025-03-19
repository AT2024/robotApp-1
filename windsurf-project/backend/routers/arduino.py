"""
Router for Arduino control endpoints.
"""
from fastapi import APIRouter, Depends, HTTPException
from typing import Dict, Any
from core.robot_manager import RobotManager
from utils.logger import get_logger

router = APIRouter()
logger = get_logger("arduino_router")

def get_robot_manager() -> RobotManager:
    return RobotManager()

@router.post("/command")
async def send_command(
    data: Dict[str, Any],
    robot_manager: RobotManager = Depends(get_robot_manager)
):
    """Send a command to the Arduino."""
    try:
        step_data = {
            "type": "arduino",
            "action": "command",
            "data": data
        }
        await robot_manager.execute_step(step_data)
        return {"status": "success", "message": "Command sent to Arduino"}
    except Exception as e:
        logger.error(f"Error sending command to Arduino: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/status")
async def get_status(
    robot_manager: RobotManager = Depends(get_robot_manager)
):
    """Get the current status of the Arduino."""
    try:
        status = robot_manager.get_status()
        return {"status": "success", "data": status.get("arduino")}
    except Exception as e:
        logger.error(f"Error getting Arduino status: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/stop")
async def stop_arduino(
    robot_manager: RobotManager = Depends(get_robot_manager)
):
    """Stop the Arduino operations."""
    try:
        await robot_manager._stop_arduino()
        return {"status": "success", "message": "Arduino stopped"}
    except Exception as e:
        logger.error(f"Error stopping Arduino: {e}")
        raise HTTPException(status_code=500, detail=str(e))
