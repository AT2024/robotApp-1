"""
Wiper 6-55 API router.
Provides HTTP endpoints for Wiper 6-55 cleaning operations.
"""

from fastapi import APIRouter, HTTPException, Depends
from typing import Dict, Any, Optional
from pydantic import BaseModel, Field

from services.wiper_service import WiperService
from services.command_service import RobotCommandService, CommandType, CommandPriority
from dependencies import get_wiper_service, get_command_service
from utils.logger import get_logger

router = APIRouter()
logger = get_logger("wiper_router")


# Request/Response Models
class CleaningRequest(BaseModel):
    """Request model for cleaning operations"""
    cycles: Optional[int] = Field(default=None, ge=1, le=10, description="Number of cleaning cycles")
    speed: Optional[str] = Field(default=None, regex="^(slow|normal|fast)$", description="Cleaning speed")
    include_drying: bool = Field(default=True, description="Include drying phase")
    dry_time: Optional[float] = Field(default=None, ge=10.0, le=300.0, description="Drying time in seconds")


class DryingRequest(BaseModel):
    """Request model for drying operations"""
    dry_time: Optional[float] = Field(default=None, ge=10.0, le=300.0, description="Drying time in seconds")


class CommandRequest(BaseModel):
    """Request model for general commands"""
    command_type: str = Field(..., description="Type of command to execute")
    parameters: Dict[str, Any] = Field(default_factory=dict, description="Command parameters")
    priority: str = Field(default="normal", regex="^(low|normal|high|critical|emergency)$")
    timeout: Optional[float] = Field(default=None, ge=1.0, le=3600.0)


# Helper function to get WiperService dependency
WiperServiceDep = Depends(get_wiper_service)
CommandServiceDep = Depends(get_command_service)


@router.get("/status")
async def get_wiper_status(wiper_service: WiperService = WiperServiceDep):
    """Get current Wiper 6-55 status"""
    try:
        result = await wiper_service.get_detailed_status()
        if result.success:
            return {
                "status": "success",
                "data": result.data,
                "timestamp": result.timestamp
            }
        else:
            raise HTTPException(status_code=500, detail=result.error)
    
    except Exception as e:
        logger.error(f"Error getting Wiper status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/clean")
async def start_cleaning_cycle(
    request: CleaningRequest,
    wiper_service: WiperService = WiperServiceDep
):
    """Start a cleaning cycle with optional drying"""
    try:
        result = await wiper_service.start_cleaning_cycle(
            cycles=request.cycles,
            speed=request.speed,
            include_drying=request.include_drying,
            dry_time=request.dry_time
        )
        
        if result.success:
            return {
                "status": "success",
                "message": "Cleaning cycle started successfully",
                "data": result.data,
                "operation_id": result.operation_id,
                "execution_time": result.execution_time
            }
        else:
            raise HTTPException(status_code=500, detail=result.error)
    
    except Exception as e:
        logger.error(f"Error starting cleaning cycle: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/dry")
async def start_drying_cycle(
    request: DryingRequest,
    wiper_service: WiperService = WiperServiceDep
):
    """Start a standalone drying cycle"""
    try:
        result = await wiper_service.start_drying_cycle(dry_time=request.dry_time)
        
        if result.success:
            return {
                "status": "success",
                "message": "Drying cycle started successfully",
                "data": result.data,
                "operation_id": result.operation_id,
                "execution_time": result.execution_time
            }
        else:
            raise HTTPException(status_code=500, detail=result.error)
    
    except Exception as e:
        logger.error(f"Error starting drying cycle: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/stop")
async def stop_current_operation(wiper_service: WiperService = WiperServiceDep):
    """Stop any current cleaning or drying operation"""
    try:
        result = await wiper_service.stop_current_operation()
        
        if result.success:
            return {
                "status": "success",
                "message": "Operation stopped successfully",
                "data": result.data
            }
        else:
            raise HTTPException(status_code=500, detail=result.error)
    
    except Exception as e:
        logger.error(f"Error stopping operation: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/emergency-stop")
async def emergency_stop_wiper(command_service: RobotCommandService = CommandServiceDep):
    """Emergency stop the Wiper 6-55"""
    try:
        result = await command_service.submit_command(
            robot_id="wiper_001",
            command_type=CommandType.EMERGENCY_STOP,
            parameters={},
            priority=CommandPriority.EMERGENCY,
            timeout=10.0
        )
        
        if result.success:
            return {
                "status": "success",
                "message": "Emergency stop executed",
                "command_id": result.data
            }
        else:
            raise HTTPException(status_code=500, detail=result.error)
    
    except Exception as e:
        logger.error(f"Emergency stop failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/disconnect")
async def disconnect_wiper(wiper_service: WiperService = WiperServiceDep):
    """Disconnect from Wiper 6-55"""
    try:
        # Note: disconnect method should be implemented in WiperService
        if hasattr(wiper_service, 'disconnect'):
            result = await wiper_service.disconnect()
            if result.success:
                return {
                    "status": "success",
                    "message": "Disconnected from Wiper 6-55"
                }
            else:
                raise HTTPException(status_code=500, detail=result.error)
        else:
            raise HTTPException(
                status_code=501, 
                detail="Disconnect method not implemented in WiperService"
            )
    
    except Exception as e:
        logger.error(f"Disconnect failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/command")
async def execute_wiper_command(
    request: CommandRequest,
    command_service: RobotCommandService = CommandServiceDep
):
    """Execute a general Wiper command through the command service"""
    try:
        # Map priority string to CommandPriority enum
        priority_map = {
            "low": CommandPriority.LOW,
            "normal": CommandPriority.NORMAL,
            "high": CommandPriority.HIGH,
            "critical": CommandPriority.CRITICAL,
            "emergency": CommandPriority.EMERGENCY
        }
        
        priority = priority_map.get(request.priority.lower(), CommandPriority.NORMAL)
        timeout = request.timeout or 300.0  # 5 minute default
        
        result = await command_service.submit_command(
            robot_id="wiper_001",
            command_type=request.command_type,
            parameters=request.parameters,
            priority=priority,
            timeout=timeout
        )
        
        if result.success:
            return {
                "status": "success",
                "message": f"Wiper command '{request.command_type}' submitted successfully",
                "command_id": result.data
            }
        else:
            raise HTTPException(status_code=500, detail=result.error)
    
    except Exception as e:
        logger.error(f"Command execution failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/commands")
async def get_wiper_commands(command_service: RobotCommandService = CommandServiceDep):
    """Get list of recent Wiper commands and their status"""
    try:
        # Get command history for wiper
        commands = await command_service.get_robot_command_history("wiper_001", limit=20)
        
        return {
            "status": "success",
            "commands": commands
        }
    
    except Exception as e:
        logger.error(f"Error getting command history: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/statistics")
async def get_operational_statistics(wiper_service: WiperService = WiperServiceDep):
    """Get operational statistics for the Wiper 6-55"""
    try:
        stats = wiper_service.get_operational_statistics()
        
        return {
            "status": "success",
            "statistics": stats
        }
    
    except Exception as e:
        logger.error(f"Error getting statistics: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/health")
async def wiper_health_check(wiper_service: WiperService = WiperServiceDep):
    """Health check for Wiper 6-55 service"""
    try:
        health = await wiper_service.health_check()
        
        status_code = 200 if health.get("healthy", False) else 503
        
        return {
            "status": "healthy" if health.get("healthy", False) else "unhealthy",
            "details": health
        }
    
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return {
            "status": "error",
            "error": str(e)
        }