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


# -----------------------------------------------------------------------------
# Legacy functions (to be removed after migration)
# -----------------------------------------------------------------------------


# Legacy function - will be removed after service migration
async def wait_for_protocol_analysis(
    robot_manager, protocol_id: str, headers: Dict
) -> bool:
    """Wait for protocol analysis to complete and return whether it was successful.

    Args:
        robot_manager: The robot manager instance
        protocol_id: The ID of the protocol to check
        headers: The HTTP headers to use for requests

    Returns:
        bool: True if analysis completed successfully, False otherwise
    """
    max_attempts = 15  # Try for up to 30 seconds (15 * 2)
    for attempt in range(max_attempts):
        analysis_url = f"http://{robot_manager.ot2_ip}:{robot_manager.ot2_port}/protocols/{protocol_id}"

        try:
            analysis_response = await asyncio.to_thread(
                lambda: requests.get(analysis_url, headers=headers, timeout=10)
            )

            if analysis_response.status_code == 200:
                data = analysis_response.json().get("data", {})
                analysis_summaries = data.get("analysisSummaries", [])

                if analysis_summaries:
                    status = analysis_summaries[0].get("status", "")
                    logger.info(f"Protocol analysis status: {status}")

                    # Check for various status possibilities
                    if status in ["succeeded", "success"]:
                        logger.info("Protocol analysis succeeded")
                        return True
                    elif status in ["failed", "error"]:
                        logger.error("Protocol analysis failed")
                        return False
                    elif status == "completed":
                        # The OT2 API uses "completed" as the final state
                        # Now check if there's a valid analysis result in the response
                        if (
                            "errors" in analysis_summaries[0]
                            and analysis_summaries[0]["errors"]
                        ):
                            logger.error(
                                f"Protocol analysis completed with errors: {analysis_summaries[0]['errors']}"
                            )
                            return False

                        # Additional check: if the protocol is valid, it will have analyzedAt field
                        if "analyzedAt" in data:
                            logger.info("Protocol analysis completed successfully")
                            return True

                        # If we've seen "completed" status multiple times, assume it's done
                        if attempt >= 2:  # Seen "completed" at least 3 times
                            logger.info(
                                "Protocol analysis appears complete after multiple checks"
                            )
                            return True
            else:
                logger.warning(
                    f"Failed to check analysis status: {analysis_response.status_code}"
                )
                logger.warning(f"Response: {analysis_response.text}")

        except Exception as e:
            logger.error(f"Error checking analysis status: {e}")

        await asyncio.sleep(
            0.5
        )  # Optimized: check every 0.5 seconds for faster response

    # If we've been polling for a while and keep seeing "completed", assume it's ready
    logger.info(
        "Timed out waiting for analysis status change - proceeding with run creation"
    )
    return True  # Proceed anyway after max attempts


async def monitor_run(robot_manager, run_id: str, headers: Dict) -> None:
    """Monitor the run progress in a background task.

    Args:
        robot_manager: The robot manager instance
        run_id: The ID of the run to monitor
        headers: The HTTP headers to use for requests
    """
    try:
        max_attempts = 60  # Check status for 5 minutes (5s interval)
        for attempt in range(max_attempts):
            await asyncio.sleep(5)  # Optimized: check every 5 seconds instead of 10
            status_url = (
                f"http://{robot_manager.ot2_ip}:{robot_manager.ot2_port}/runs/{run_id}"
            )

            try:
                status_response = await asyncio.to_thread(
                    lambda: requests.get(status_url, headers=headers, timeout=10)
                )

                if status_response.status_code == 200:
                    status_data = status_response.json().get("data", {})
                    current_status = status_data.get("status", "unknown")
                    logger.info(
                        f"Run status check ({attempt + 1}/{max_attempts}): {current_status}"
                    )

                    if current_status in ["succeeded", "stopped", "failed"]:
                        logger.info(f"Run completed with status: {current_status}")
                        # Notify the websocket server about the completion
                        if (
                            hasattr(robot_manager, "websocket_server")
                            and robot_manager.websocket_server
                        ):
                            await robot_manager.websocket_server.broadcast(
                                {
                                    "type": "status_update",
                                    "data": {
                                        "type": "ot2",
                                        "status": (
                                            "complete"
                                            if current_status == "succeeded"
                                            else "error"
                                        ),
                                        "runId": run_id,
                                        "runStatus": current_status,
                                    },
                                }
                            )
                        break
                else:
                    logger.warning(
                        f"Failed to get run status: {status_response.status_code}"
                    )

            except Exception as e:
                logger.error(f"Error checking run status: {e}")

    except Exception as e:
        logger.error(f"Error monitoring run: {e}")


async def check_run_status(robot_manager, run_id: str) -> str:
    """Check the status of a run.

    Args:
        robot_manager: The robot manager instance
        run_id: The ID of the run to check

    Returns:
        str: The status of the run
    """
    headers = {"Accept": "application/json", "Opentrons-Version": "2"}
    status_url = f"http://{robot_manager.ot2_ip}:{robot_manager.ot2_port}/runs/{run_id}"

    try:
        status_response = await asyncio.to_thread(
            lambda: requests.get(status_url, headers=headers, timeout=10)
        )

        if status_response.status_code == 200:
            status_data = status_response.json().get("data", {})
            return status_data.get("status", "unknown")
        else:
            logger.warning(f"Failed to get run status: {status_response.status_code}")
            return "unknown"
    except Exception as e:
        logger.error(f"Error checking run status: {e}")
        return "error"


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


@router.get("/executions")
async def list_protocol_executions(
    protocol_service: ProtocolExecutionService = ProtocolServiceDep(),
):
    """List all protocol executions.

    This endpoint retrieves a list of all protocol executions in the system.
    """
    try:
        result = await protocol_service.list_active_protocols()

        if not result.success:
            raise HTTPException(status_code=500, detail=result.error)

        return {"executions": result.data, "status": "success"}

    except HTTPException:
        raise
    except Exception as e:
        error_msg = f"Failed to list executions: {str(e)}"
        logger.error(error_msg)
        raise HTTPException(status_code=500, detail=error_msg)
