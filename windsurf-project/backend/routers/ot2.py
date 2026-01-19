"""
Router for OT2 robot endpoints.
Updated to use the new service layer architecture.
"""

from fastapi import APIRouter, Depends, Request, HTTPException, Body
from fastapi.responses import JSONResponse
from typing import Dict, Any, Optional
from dependencies import OT2ServiceDep, ProtocolServiceDep, CommandServiceDep
from services.ot2_service import OT2Service
from services.protocol_service import ProtocolExecutionService
from services.command_service import RobotCommandService, CommandType, CommandPriority
from utils.logger import get_logger
import os
import json
import asyncio
import requests
import time
from pydantic import BaseModel

router = APIRouter()
logger = get_logger("ot2_router")


# Pydantic models for request validation
class ProtocolRequest(BaseModel):
    trayInfo: Optional[Dict[str, Any]] = None
    vialNumber: Optional[int] = None
    trayNumber: Optional[int] = None
    parameters: Optional[Dict[str, Any]] = None


class RunRequest(BaseModel):
    protocol_name: Optional[str] = "OT2_Liquid_Handling"
    parameters: Optional[Dict[str, Any]] = None


# -----------------------------------------------------------------------------
# New service layer endpoints
# -----------------------------------------------------------------------------


@router.get("/robot-status")
async def get_ot2_robot_status(ot2_service: OT2Service = OT2ServiceDep()):
    """Get current status of the OT2 robot"""
    try:
        result = await ot2_service.get_robot_status()
        if not result.success:
            raise HTTPException(status_code=500, detail=result.error)
        return result.data
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting OT2 status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/connect")
async def connect_ot2(ot2_service: OT2Service = OT2ServiceDep()):
    """Connect to OT2 robot"""
    try:
        result = await ot2_service.connect()
        if not result.success:
            raise HTTPException(status_code=500, detail=result.error)
        return {"status": "success", "message": "Connected to OT2 robot"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error connecting to OT2: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/disconnect")
async def disconnect_ot2(ot2_service: OT2Service = OT2ServiceDep()):
    """Disconnect from OT2 robot"""
    try:
        result = await ot2_service.disconnect()
        if not result.success:
            raise HTTPException(status_code=500, detail=result.error)
        return {"status": "success", "message": "Disconnected from OT2 robot"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error disconnecting from OT2: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/home")
async def home_ot2(command_service: RobotCommandService = CommandServiceDep()):
    """Send OT2 robot to home position"""
    try:
        result = await command_service.submit_command(
            robot_id="ot2",
            command_type=CommandType.HOME,
            parameters={},
            priority=CommandPriority.HIGH,
            timeout=120.0,
        )

        if not result.success:
            raise HTTPException(status_code=500, detail=result.error)

        return {
            "status": "success",
            "command_id": result.data,
            "message": "Home command submitted",
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error homing OT2 robot: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/emergency-stop")
async def emergency_stop_ot2(
    command_service: RobotCommandService = CommandServiceDep(),
):
    """Emergency stop the OT2 robot"""
    try:
        result = await command_service.submit_command(
            robot_id="ot2",
            command_type=CommandType.EMERGENCY_STOP,
            parameters={},
            priority=CommandPriority.EMERGENCY,
            timeout=10.0,
        )

        if not result.success:
            raise HTTPException(status_code=500, detail=result.error)

        return {
            "status": "success",
            "command_id": result.data,
            "message": "Emergency stop command submitted",
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error emergency stopping OT2 robot: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/pause/{execution_id}")
async def pause_protocol(
    execution_id: str, protocol_service: ProtocolExecutionService = ProtocolServiceDep()
):
    """Pause an OT2 protocol execution"""
    try:
        result = await protocol_service.pause_protocol_execution(execution_id)

        if not result.success:
            raise HTTPException(status_code=500, detail=result.error)

        return {
            "status": "success",
            "execution_id": execution_id,
            "message": "Protocol execution paused",
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error pausing protocol: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/resume/{execution_id}")
async def resume_protocol(
    execution_id: str, protocol_service: ProtocolExecutionService = ProtocolServiceDep()
):
    """Resume a paused OT2 protocol execution"""
    try:
        result = await protocol_service.resume_protocol_execution(execution_id)

        if not result.success:
            raise HTTPException(status_code=500, detail=result.error)

        return {
            "status": "success",
            "execution_id": execution_id,
            "message": "Protocol execution resumed",
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error resuming protocol: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/run-protocol")
async def run_ot2_protocol(
    request_data: ProtocolRequest = Body(default_factory=ProtocolRequest),
    protocol_service: ProtocolExecutionService = ProtocolServiceDep(),
):
    """Run the OT2 protocol using the new service layer.

    This endpoint creates and executes an OT2 protocol through the
    ProtocolExecutionService for better coordination and monitoring.
    """
    try:
        logger.info("Starting OT2 protocol execution through service layer")

        # Prepare protocol parameters
        parameters = {}
        if request_data.trayInfo:
            parameters.update(request_data.trayInfo)
        if request_data.vialNumber:
            parameters["vialNumber"] = request_data.vialNumber
        if request_data.trayNumber:
            parameters["trayNumber"] = request_data.trayNumber
        if request_data.parameters:
            parameters.update(request_data.parameters)

        # Create OT2 protocol execution
        result = await protocol_service.create_ot2_protocol_execution(
            protocol_name="OT2_Liquid_Handling",
            parameters=parameters if parameters else None,
        )

        if not result.success:
            raise HTTPException(status_code=500, detail=result.error)

        execution_id = result.data

        # Start the protocol execution
        start_result = await protocol_service.start_protocol_execution(execution_id)

        if not start_result.success:
            raise HTTPException(status_code=500, detail=start_result.error)

        logger.info(f"OT2 protocol execution started: {execution_id}")
        return {
            "message": "OT2 protocol execution started",
            "status": "success",
            "execution_id": execution_id,
            "parameters": parameters,
        }

    except HTTPException:
        raise
    except Exception as e:
        error_msg = f"Failed to execute protocol: {str(e)}"
        logger.error(error_msg)
        raise HTTPException(status_code=500, detail=error_msg)


@router.get("/status/{execution_id}")
async def get_protocol_status(
    execution_id: str, protocol_service: ProtocolExecutionService = ProtocolServiceDep()
):
    """Get the current status of a protocol execution.

    This endpoint allows clients to check the status of a running protocol
    by providing the execution ID.
    """
    try:
        result = await protocol_service.get_protocol_execution_status(execution_id)

        if not result.success:
            raise HTTPException(status_code=404, detail=result.error)

        return result.data

    except HTTPException:
        raise
    except Exception as e:
        error_msg = f"Failed to get protocol status: {str(e)}"
        logger.error(error_msg)
        raise HTTPException(status_code=500, detail=error_msg)


@router.post("/stop/{execution_id}")
async def stop_protocol(
    execution_id: str, protocol_service: ProtocolExecutionService = ProtocolServiceDep()
):
    """Stop an OT2 protocol execution.

    This endpoint allows clients to stop a running protocol execution
    by providing the execution ID.
    """
    try:
        result = await protocol_service.cancel_protocol_execution(
            execution_id, reason="User requested stop"
        )

        if not result.success:
            raise HTTPException(status_code=500, detail=result.error)

        return {
            "message": "Protocol execution stopped successfully",
            "status": "success",
            "execution_id": execution_id,
        }

    except HTTPException:
        raise
    except Exception as e:
        error_msg = f"Failed to stop protocol: {str(e)}"
        logger.error(error_msg)
        raise HTTPException(status_code=500, detail=error_msg)


@router.get("/protocols")
async def list_active_protocols(
    protocol_service: ProtocolExecutionService = ProtocolServiceDep(),
):
    """List all active protocol executions.

    This endpoint retrieves a list of all protocol executions that are
    currently active in the system.
    """
    try:
        result = await protocol_service.list_active_protocols()

        if not result.success:
            raise HTTPException(status_code=500, detail=result.error)

        return {"protocols": result.data, "status": "success"}

    except HTTPException:
        raise
    except Exception as e:
        error_msg = f"Failed to list protocols: {str(e)}"
        logger.error(error_msg)
        raise HTTPException(status_code=500, detail=error_msg)


@router.get("/debug/connectivity")
async def debug_ot2_connectivity(
    ot2_service: OT2Service = OT2ServiceDep(),
):
    """Debug endpoint to test OT2 robot connectivity and API communication."""
    try:
        logger.info("Testing OT2 connectivity...")
        
        # Test basic connectivity
        health_result = await ot2_service._get_health_status()
        
        # Get detailed status
        status_result = await ot2_service.get_robot_status()
        
        return {
            "status": "success",
            "connectivity": "connected",
            "health": health_result,
            "robot_status": status_result.data if status_result.success else status_result.error,
            "base_url": ot2_service.base_url,
        }
        
    except Exception as e:
        error_msg = f"OT2 connectivity test failed: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return {
            "status": "error",
            "connectivity": "failed",
            "error": error_msg,
            "base_url": getattr(ot2_service, 'base_url', 'unknown'),
        }


@router.post("/run-protocol-direct")
async def run_protocol_direct(
    request_data: ProtocolRequest = Body(default_factory=ProtocolRequest),
    ot2_service: OT2Service = OT2ServiceDep(),
):
    """Run OT2 protocol directly through OT2Service (bypasses ProtocolExecutionService).

    This endpoint provides a direct path to OT2Service.run_protocol() for simpler
    protocol execution without the complexity of the ProtocolExecutionService.
    """
    try:
        logger.info("Starting direct OT2 protocol execution")

        # Prepare protocol parameters
        parameters = {}
        if request_data.trayInfo:
            parameters.update(request_data.trayInfo)
        if request_data.vialNumber:
            parameters["vialNumber"] = request_data.vialNumber
        if request_data.trayNumber:
            parameters["trayNumber"] = request_data.trayNumber
        if request_data.parameters:
            parameters.update(request_data.parameters)

        logger.info(f"Protocol parameters: {parameters}")

        # Call OT2Service.run_protocol directly
        result = await ot2_service.run_protocol(**parameters)

        if not result.success:
            raise HTTPException(status_code=500, detail=result.error)

        logger.info("Direct OT2 protocol execution completed successfully")
        return {
            "message": "OT2 protocol executed successfully",
            "status": "success",
            "result": result.data,
            "parameters": parameters,
        }

    except HTTPException:
        raise
    except Exception as e:
        error_msg = f"Failed to execute protocol directly: {str(e)}"
        logger.error(error_msg, exc_info=True)
        raise HTTPException(status_code=500, detail=error_msg)


@router.post("/pause-run")
async def pause_current_run(ot2_service: OT2Service = OT2ServiceDep()):
    """Pause the currently running OT2 protocol.

    This endpoint uses resilient run discovery to find and pause any active run,
    even if internal state has become desynced. No execution_id required.

    Returns:
        Success response if paused, error otherwise
    """
    try:
        logger.info("Pause run request received")
        result = await ot2_service.pause_current_run()

        if not result.success:
            raise HTTPException(status_code=400, detail=result.error)

        return {
            "status": "success",
            "message": "OT2 protocol paused successfully",
        }

    except HTTPException:
        raise
    except Exception as e:
        error_msg = f"Failed to pause protocol: {str(e)}"
        logger.error(error_msg, exc_info=True)
        raise HTTPException(status_code=500, detail=error_msg)


@router.post("/resume-run")
async def resume_current_run(ot2_service: OT2Service = OT2ServiceDep()):
    """Resume a paused OT2 protocol.

    This endpoint uses resilient run discovery to find and resume any paused run,
    even if internal state has become desynced. No execution_id required.

    Returns:
        Success response if resumed, error otherwise
    """
    try:
        logger.info("Resume run request received")
        result = await ot2_service.resume_current_run()

        if not result.success:
            raise HTTPException(status_code=400, detail=result.error)

        return {
            "status": "success",
            "message": "OT2 protocol resumed successfully",
        }

    except HTTPException:
        raise
    except Exception as e:
        error_msg = f"Failed to resume protocol: {str(e)}"
        logger.error(error_msg, exc_info=True)
        raise HTTPException(status_code=500, detail=error_msg)


@router.get("/active-run")
async def get_active_run(ot2_service: OT2Service = OT2ServiceDep()):
    """Get information about the currently active (running or paused) OT2 run.

    Uses resilient run discovery to find active runs even if internal state
    has become desynced.

    Returns:
        Active run ID if found, null otherwise
    """
    try:
        run_id = await ot2_service.get_active_run_id()

        return {
            "status": "success",
            "active_run_id": run_id,
            "has_active_run": run_id is not None,
        }

    except Exception as e:
        error_msg = f"Failed to get active run: {str(e)}"
        logger.error(error_msg, exc_info=True)
        raise HTTPException(status_code=500, detail=error_msg)
