"""
Router for OT2 robot endpoints.
Updated to use the new service layer architecture.
"""

from fastapi import APIRouter, Body
from typing import Dict, Any, Optional
from dependencies import OT2ServiceDep, ProtocolServiceDep, CommandServiceDep
from services.ot2_service import OT2Service
from services.protocol_service import ProtocolExecutionService
from services.command_service import RobotCommandService, CommandType, CommandPriority
from common.helpers import RouterHelper, CommandHelper, ResponseHelper
from utils.logger import get_logger
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
    return await RouterHelper.execute_service_operation(
        ot2_service.get_robot_status, "get_ot2_robot_status", logger
    )


@router.post("/connect")
async def connect_ot2(ot2_service: OT2Service = OT2ServiceDep()):
    """Connect to OT2 robot"""
    await RouterHelper.execute_service_operation(
        ot2_service.connect, "connect_ot2", logger
    )
    return ResponseHelper.create_success_response(message="Connected to OT2 robot")


@router.post("/disconnect")
async def disconnect_ot2(ot2_service: OT2Service = OT2ServiceDep()):
    """Disconnect from OT2 robot"""
    await RouterHelper.execute_service_operation(
        ot2_service.disconnect, "disconnect_ot2", logger
    )
    return ResponseHelper.create_success_response(message="Disconnected from OT2 robot")


@router.post("/home")
async def home_ot2(command_service: RobotCommandService = CommandServiceDep()):
    """Send OT2 robot to home position"""
    return await CommandHelper.submit_robot_command(
        command_service=command_service,
        robot_id="ot2",
        command_type=CommandType.HOME,
        parameters={},
        priority=CommandPriority.HIGH,
        timeout=120.0,
        success_message="Home command submitted",
    )


@router.post("/emergency-stop")
async def emergency_stop_ot2(
    command_service: RobotCommandService = CommandServiceDep(),
):
    """Emergency stop the OT2 robot"""
    return await CommandHelper.submit_robot_command(
        command_service=command_service,
        robot_id="ot2",
        command_type=CommandType.EMERGENCY_STOP,
        parameters={},
        priority=CommandPriority.EMERGENCY,
        timeout=10.0,
        success_message="Emergency stop command submitted",
    )


@router.post("/pause/{execution_id}")
async def pause_protocol(
    execution_id: str, protocol_service: ProtocolExecutionService = ProtocolServiceDep()
):
    """Pause an OT2 protocol execution"""
    await RouterHelper.execute_service_operation(
        protocol_service.pause_protocol_execution, "pause_protocol", logger, execution_id
    )
    return ResponseHelper.create_success_response(
        message="Protocol execution paused", execution_id=execution_id
    )


@router.post("/resume/{execution_id}")
async def resume_protocol(
    execution_id: str, protocol_service: ProtocolExecutionService = ProtocolServiceDep()
):
    """Resume a paused OT2 protocol execution"""
    await RouterHelper.execute_service_operation(
        protocol_service.resume_protocol_execution, "resume_protocol", logger, execution_id
    )
    return ResponseHelper.create_success_response(
        message="Protocol execution resumed", execution_id=execution_id
    )


@router.post("/run-protocol")
async def run_ot2_protocol(
    request_data: ProtocolRequest = Body(default_factory=ProtocolRequest),
    protocol_service: ProtocolExecutionService = ProtocolServiceDep(),
):
    """Run the OT2 protocol using the new service layer.

    This endpoint creates and executes an OT2 protocol through the
    ProtocolExecutionService for better coordination and monitoring.
    """
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
    execution_id = await RouterHelper.execute_service_operation(
        protocol_service.create_ot2_protocol_execution,
        "create_ot2_protocol_execution",
        logger,
        protocol_name="OT2_Liquid_Handling",
        parameters=parameters if parameters else None,
    )

    # Start the protocol execution
    await RouterHelper.execute_service_operation(
        protocol_service.start_protocol_execution,
        "start_protocol_execution",
        logger,
        execution_id,
    )

    logger.info(f"OT2 protocol execution started: {execution_id}")
    return ResponseHelper.create_success_response(
        message="OT2 protocol execution started",
        execution_id=execution_id,
        parameters=parameters,
    )


@router.get("/status/{execution_id}")
async def get_protocol_status(
    execution_id: str, protocol_service: ProtocolExecutionService = ProtocolServiceDep()
):
    """Get the current status of a protocol execution.

    This endpoint allows clients to check the status of a running protocol
    by providing the execution ID.
    """
    return await RouterHelper.execute_service_operation(
        protocol_service.get_protocol_execution_status,
        "get_protocol_status",
        logger,
        execution_id,
    )


@router.post("/stop/{execution_id}")
async def stop_protocol(
    execution_id: str, protocol_service: ProtocolExecutionService = ProtocolServiceDep()
):
    """Stop an OT2 protocol execution.

    This endpoint allows clients to stop a running protocol execution
    by providing the execution ID.
    """
    await RouterHelper.execute_service_operation(
        lambda: protocol_service.cancel_protocol_execution(
            execution_id, reason="User requested stop"
        ),
        "stop_protocol",
        logger,
    )
    return ResponseHelper.create_success_response(
        message="Protocol execution stopped successfully",
        execution_id=execution_id,
    )


@router.get("/protocols")
async def list_active_protocols(
    protocol_service: ProtocolExecutionService = ProtocolServiceDep(),
):
    """List all active protocol executions.

    This endpoint retrieves a list of all protocol executions that are
    currently active in the system.
    """
    protocols = await RouterHelper.execute_service_operation(
        protocol_service.list_active_protocols,
        "list_active_protocols",
        logger,
    )
    return ResponseHelper.create_success_response(protocols=protocols)


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
    result = await RouterHelper.execute_service_operation(
        lambda: ot2_service.run_protocol(**parameters),
        "run_protocol_direct",
        logger,
    )

    logger.info("Direct OT2 protocol execution completed successfully")
    return ResponseHelper.create_success_response(
        message="OT2 protocol executed successfully",
        result=result,
        parameters=parameters,
    )


@router.post("/pause-run")
async def pause_current_run(ot2_service: OT2Service = OT2ServiceDep()):
    """Pause the currently running OT2 protocol.

    This endpoint uses resilient run discovery to find and pause any active run,
    even if internal state has become desynced. No execution_id required.

    Returns:
        Success response if paused, error otherwise
    """
    logger.info("Pause run request received")
    await RouterHelper.execute_service_operation(
        ot2_service.pause_current_run, "pause_current_run", logger
    )
    return ResponseHelper.create_success_response(
        message="OT2 protocol paused successfully"
    )


@router.post("/resume-run")
async def resume_current_run(ot2_service: OT2Service = OT2ServiceDep()):
    """Resume a paused OT2 protocol.

    This endpoint uses resilient run discovery to find and resume any paused run,
    even if internal state has become desynced. No execution_id required.

    Returns:
        Success response if resumed, error otherwise
    """
    logger.info("Resume run request received")
    await RouterHelper.execute_service_operation(
        ot2_service.resume_current_run, "resume_current_run", logger
    )
    return ResponseHelper.create_success_response(
        message="OT2 protocol resumed successfully"
    )


@router.get("/active-run")
async def get_active_run(ot2_service: OT2Service = OT2ServiceDep()):
    """Get information about the currently active (running or paused) OT2 run.

    Uses resilient run discovery to find active runs even if internal state
    has become desynced.

    Returns:
        Active run ID if found, null otherwise
    """
    run_id = await RouterHelper.execute_service_operation(
        ot2_service.get_active_run_id, "get_active_run", logger
    )
    return ResponseHelper.create_success_response(
        active_run_id=run_id,
        has_active_run=run_id is not None,
    )


# -----------------------------------------------------------------------------
# Recovery Endpoints - For post-emergency-stop recovery
# -----------------------------------------------------------------------------


@router.post("/recovery/clear-and-reconnect")
async def clear_and_reconnect(ot2_service: OT2Service = OT2ServiceDep()):
    """
    Recovery operation: Clear all runs, home robot, and reset state.

    Use this endpoint after an emergency stop or when the OT2 is in an
    error state. This will:
    1. Stop any running/paused protocols
    2. Clear completed/failed runs
    3. Home the robot
    4. Reset internal state to IDLE

    After this succeeds, the OT2 should be ready for new protocol execution.
    """
    logger.info("OT2 recovery (clear and reconnect) requested")
    result = await RouterHelper.execute_service_operation(
        ot2_service.clear_and_reconnect, "clear_and_reconnect", logger
    )
    return ResponseHelper.create_success_response(
        data=result,
        message=result.get("message", "OT2 recovery completed") if isinstance(result, dict) else "OT2 recovery completed"
    )


@router.post("/recovery/quick-recovery")
async def quick_recovery(ot2_service: OT2Service = OT2ServiceDep()):
    """
    Quick recovery - resume OT2 protocol from where it stopped.

    Resumes a paused protocol after an emergency stop without losing progress.
    This wraps the existing resume_current_run functionality with consistent
    interface for the recovery panel.

    This is the recommended recovery option when you want to continue
    the protocol from where it paused.
    """
    logger.info("Quick recovery requested for OT2")
    result = await RouterHelper.execute_service_operation(
        ot2_service.quick_recovery, "quick_recovery", logger
    )
    return ResponseHelper.create_success_response(
        data=result,
        message=result.get("message", "OT2 quick recovery completed") if isinstance(result, dict) else "OT2 quick recovery completed"
    )


@router.post("/recovery/safe-home-reverse")
async def safe_home_reverse_path(ot2_service: OT2Service = OT2ServiceDep()):
    """
    Safe home by retracing path in reverse (shield-safe).

    Moves the pipette back through recorded positions in reverse order,
    then homes the robot. This is useful for avoiding obstacles like
    shields that may block direct homing paths.

    Z-up movements are prioritized for collision safety.
    """
    logger.info("Safe home reverse path requested for OT2")
    result = await RouterHelper.execute_service_operation(
        ot2_service.safe_home_reverse_path, "safe_home_reverse_path", logger
    )
    return ResponseHelper.create_success_response(
        data=result,
        message=result.get("message", "Safe homing completed") if isinstance(result, dict) else "Safe homing completed"
    )


@router.get("/recovery/position-history")
async def get_position_history(ot2_service: OT2Service = OT2ServiceDep()):
    """
    Get the number of positions recorded in the history.

    Used to determine if reverse path homing is available.
    """
    position_count = ot2_service.get_position_history_count()
    return ResponseHelper.create_success_response(
        position_count=position_count,
        can_reverse_home=position_count > 0
    )


@router.post("/recovery/clear-position-history")
async def clear_position_history(ot2_service: OT2Service = OT2ServiceDep()):
    """
    Clear the position history.

    Use this after manual repositioning or when starting a new workflow.
    """
    ot2_service.clear_position_history()
    return ResponseHelper.create_success_response(message="Position history cleared")
