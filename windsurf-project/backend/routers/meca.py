from fastapi import APIRouter, HTTPException, Body
from utils.logger import get_logger
from dependencies import MecaServiceDep, OrchestratorDep, CommandServiceDep
from services.meca import MecaService
from services.orchestrator import RobotOrchestrator
from services.command_service import RobotCommandService, CommandType, CommandPriority
from common.helpers import RouterHelper, CommandHelper, ResponseHelper


router = APIRouter()
logger = get_logger("meca_router")


# -----------------------------------------------------------------------------
# Connection Endpoints
# -----------------------------------------------------------------------------


@router.get("/status")
async def get_meca_status(meca_service: MecaService = MecaServiceDep()):
    """Get current status of the Meca robot."""
    return await RouterHelper.execute_service_operation(
        meca_service.get_robot_status, "get_meca_status", logger
    )


@router.post("/connect")
async def connect_meca(meca_service: MecaService = MecaServiceDep()):
    """Connect to Meca robot."""
    result = await RouterHelper.execute_service_operation(
        meca_service.connect, "connect_meca", logger
    )
    return ResponseHelper.create_success_response(
        data=result, message="Connected to Meca robot"
    )


@router.post("/connect-safe")
async def connect_safe_meca(meca_service: MecaService = MecaServiceDep()):
    """
    Connect to Meca robot WITHOUT automatic homing.
    Returns current joint positions for user safety confirmation.
    Step 1 of two-step safe connection flow.
    """
    result = await RouterHelper.execute_service_operation(
        meca_service.connect_safe, "connect_safe_meca", logger
    )
    return ResponseHelper.create_success_response(
        data=result, message="Connected to Meca robot - awaiting confirmation"
    )


@router.post("/confirm-activation")
async def confirm_activation_meca(meca_service: MecaService = MecaServiceDep()):
    """
    Confirm robot position is safe and proceed with activation/homing.
    Step 2 of two-step safe connection flow.
    """
    result = await RouterHelper.execute_service_operation(
        meca_service.confirm_activation, "confirm_activation_meca", logger
    )
    return ResponseHelper.create_success_response(
        data=result, message="Robot activated and homed successfully"
    )


@router.post("/disconnect-safe")
async def disconnect_safe_meca(meca_service: MecaService = MecaServiceDep()):
    """Gracefully disconnect from Meca robot with deactivation."""
    result = await RouterHelper.execute_service_operation(
        meca_service.disconnect_safe, "disconnect_safe_meca", logger
    )
    return ResponseHelper.create_success_response(
        data=result, message="Robot disconnected safely"
    )


@router.post("/disconnect")
async def disconnect_meca(meca_service: MecaService = MecaServiceDep()):
    """Disconnect from Meca robot."""
    result = await RouterHelper.execute_service_operation(
        meca_service.disconnect, "disconnect_meca", logger
    )
    return ResponseHelper.create_success_response(
        data=result, message="Disconnected from Meca robot"
    )


# -----------------------------------------------------------------------------
# Command Endpoints
# -----------------------------------------------------------------------------


@router.post("/home")
async def home_meca(command_service: RobotCommandService = CommandServiceDep()):
    """Send Meca robot to home position."""
    return await CommandHelper.submit_robot_command(
        command_service=command_service,
        robot_id="meca",
        command_type=CommandType.HOME,
        parameters={},
        priority=CommandPriority.HIGH,
        timeout=120.0,
        success_message="Home command submitted",
    )


@router.post("/emergency-stop")
async def emergency_stop_meca(
    command_service: RobotCommandService = CommandServiceDep(),
):
    """Emergency stop the Meca robot."""
    return await CommandHelper.submit_robot_command(
        command_service=command_service,
        robot_id="meca",
        command_type=CommandType.EMERGENCY_STOP,
        parameters={},
        priority=CommandPriority.EMERGENCY,
        timeout=10.0,
        success_message="Emergency stop command submitted",
    )


@router.get("/commands/{command_id}/status")
async def get_command_status(
    command_id: str, command_service: RobotCommandService = CommandServiceDep()
):
    """Get status of a specific command."""
    return await RouterHelper.execute_service_operation(
        command_service.get_command_status, "get_command_status", logger, command_id
    )


@router.get("/commands")
async def list_active_commands(
    command_service: RobotCommandService = CommandServiceDep(),
):
    """List active commands for Meca robot."""
    return await RouterHelper.execute_service_operation(
        command_service.list_active_commands, "list_active_commands", logger, robot_id="meca"
    )


# -----------------------------------------------------------------------------
# Wafer Status Endpoints
# -----------------------------------------------------------------------------


@router.get("/wafer/current")
async def get_current_wafer():
    """Get the currently processing wafer information."""
    try:
        from database.db_config import SessionLocal
        from database.repositories import WaferRepository

        db = SessionLocal()
        try:
            # Get currently processing wafer (status='picked')
            current_wafer = WaferRepository.get_current_processing(db)

            if current_wafer:
                # Calculate cycle info
                wafer_pos = current_wafer.wafer_pos
                cycle_number = ((wafer_pos - 1) // 5) + 1
                wafer_in_cycle = ((wafer_pos - 1) % 5) + 1
                cycle_start = ((cycle_number - 1) * 5) + 1

                return ResponseHelper.create_success_response(data={
                    "wafer_id": current_wafer.id,
                    "wafer_pos": wafer_pos,
                    "status": current_wafer.status,
                    "cycle_number": cycle_number,
                    "wafer_in_cycle": wafer_in_cycle,
                    "cycle_start": cycle_start,
                    "cycle_end": cycle_start + 4,
                    "updated_at": current_wafer.updated_at.isoformat() if current_wafer.updated_at else None
                })
            else:
                # No wafer currently processing
                return ResponseHelper.create_success_response(data={
                    "wafer_id": None,
                    "wafer_pos": None,
                    "status": "idle",
                    "message": "No wafer currently being processed"
                })
        finally:
            db.close()
    except Exception as e:
        logger.error(f"Error getting current wafer: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/wafer/status/{wafer_num}")
async def get_wafer_status(wafer_num: int):
    """Get status of a specific wafer by position number (1-55)."""
    if wafer_num < 1 or wafer_num > 55:
        raise HTTPException(status_code=400, detail="Wafer number must be between 1 and 55")

    try:
        from database.db_config import SessionLocal
        from database.repositories import WaferRepository

        db = SessionLocal()
        try:
            wafer = WaferRepository.get_by_position(db, wafer_num)

            if wafer:
                cycle_number = ((wafer_num - 1) // 5) + 1
                wafer_in_cycle = ((wafer_num - 1) % 5) + 1

                return ResponseHelper.create_success_response(data={
                    "wafer_id": wafer.id,
                    "wafer_pos": wafer.wafer_pos,
                    "status": wafer.status,
                    "cycle_number": cycle_number,
                    "wafer_in_cycle": wafer_in_cycle,
                    "created_at": wafer.created_at.isoformat() if wafer.created_at else None,
                    "updated_at": wafer.updated_at.isoformat() if wafer.updated_at else None
                })
            else:
                # Wafer not yet in database
                cycle_number = ((wafer_num - 1) // 5) + 1
                wafer_in_cycle = ((wafer_num - 1) % 5) + 1

                return ResponseHelper.create_success_response(data={
                    "wafer_id": None,
                    "wafer_pos": wafer_num,
                    "status": "not_started",
                    "cycle_number": cycle_number,
                    "wafer_in_cycle": wafer_in_cycle,
                    "message": "Wafer has not been processed yet"
                })
        finally:
            db.close()
    except Exception as e:
        logger.error(f"Error getting wafer status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/wafer/batch-status")
async def get_batch_status():
    """Get status of all wafers for batch progress tracking."""
    try:
        from database.db_config import SessionLocal
        from database.repositories import WaferRepository

        db = SessionLocal()
        try:
            all_wafers = WaferRepository.get_all(db, limit=55)

            # Build status summary
            status_counts = {"created": 0, "picked": 0, "dropped": 0, "completed": 0, "failed": 0, "not_started": 0}
            wafer_statuses = []

            # Create a map of existing wafers
            existing_wafers = {w.wafer_pos: w for w in all_wafers}

            for pos in range(1, 56):
                if pos in existing_wafers:
                    wafer = existing_wafers[pos]
                    status_counts[wafer.status] = status_counts.get(wafer.status, 0) + 1
                    wafer_statuses.append({
                        "wafer_pos": pos,
                        "status": wafer.status,
                        "cycle": ((pos - 1) // 5) + 1
                    })
                else:
                    status_counts["not_started"] += 1
                    wafer_statuses.append({
                        "wafer_pos": pos,
                        "status": "not_started",
                        "cycle": ((pos - 1) // 5) + 1
                    })

            return ResponseHelper.create_success_response(data={
                "total_wafers": 55,
                "status_counts": status_counts,
                "wafers": wafer_statuses,
                "progress_percent": round((status_counts.get("completed", 0) / 55) * 100, 1)
            })
        finally:
            db.close()
    except Exception as e:
        logger.error(f"Error getting batch status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# -----------------------------------------------------------------------------
# Sequence Operation Endpoints
# -----------------------------------------------------------------------------


async def _execute_sequence(
    meca_service: MecaService,
    sequence_method,
    sequence_name: str,
    start: int,
    count: int,
) -> dict:
    """Execute a wafer sequence operation with standard error handling."""
    result = await sequence_method(start, count)
    if not result.success:
        logger.error(f"{sequence_name} failed: {result.error}")
        raise HTTPException(status_code=500, detail=result.error)
    return ResponseHelper.create_success_response(
        data=result.data,
        message=f"{sequence_name} completed for wafers {start + 1} to {start + count}",
    )


@router.post("/pickup")
async def create_pickup(
    data: dict = Body(default={}),
    meca_service: MecaService = MecaServiceDep(),
):
    """Execute pickup sequence for wafers."""
    start = data.get("start", 0)
    count = data.get("count", 5)
    return await _execute_sequence(
        meca_service, meca_service.execute_pickup_sequence, "Pickup sequence", start, count
    )


@router.post("/drop")
async def create_drop(
    data: dict = Body(default={}),
    meca_service: MecaService = MecaServiceDep(),
):
    """Execute drop sequence for wafers."""
    start = data.get("start", 0)
    count = data.get("count", 5)
    return await _execute_sequence(
        meca_service, meca_service.execute_drop_sequence, "Drop sequence", start, count
    )


@router.post("/carousel")
async def create_carousel_sequence(
    data: dict = Body(default={}),
    meca_service: MecaService = MecaServiceDep(),
):
    """Execute carousel fill sequence for wafers."""
    start = data.get("start", 0)
    count = data.get("count", 11)
    return await _execute_sequence(
        meca_service, meca_service.execute_carousel_sequence, "Carousel sequence", start, count
    )


@router.post("/empty-carousel")
async def create_empty_carousel_sequence(
    data: dict = Body(default={}),
    meca_service: MecaService = MecaServiceDep(),
):
    """Execute carousel empty sequence for wafers."""
    start = data.get("start", 0)
    count = data.get("count", 11)
    return await _execute_sequence(
        meca_service, meca_service.execute_empty_carousel_sequence, "Empty carousel sequence", start, count
    )


@router.post("/test-wafer/{wafer_number}")
async def test_single_wafer(
    wafer_number: int,
    meca_service: MecaService = MecaServiceDep(),
):
    """Test position calculation for a single wafer (1-55)."""
    if wafer_number < 1 or wafer_number > 55:
        raise HTTPException(status_code=400, detail="Wafer number must be between 1 and 55")

    wafer_index = wafer_number - 1
    result = await RouterHelper.execute_service_operation(
        meca_service.get_wafer_position_preview,
        "test_single_wafer",
        logger,
        wafer_index,
    )
    return ResponseHelper.create_success_response(
        data=result, message=f"Position calculation test completed for wafer {wafer_number}"
    )


# -----------------------------------------------------------------------------
# Batch Processing Endpoint
# -----------------------------------------------------------------------------


def _build_batch_operations(
    total_wafers: int, wafers_per_cycle: int, wafers_per_carousel: int
) -> list:
    """Build robot operations list for batch processing workflow."""
    operations = []

    # Phase 1: Pickup and drop operations
    for start in range(0, total_wafers, wafers_per_cycle):
        count = min(wafers_per_cycle, total_wafers - start)
        operations.append({
            "robot_id": "meca",
            "operation_type": "pickup_wafer_sequence",
            "parameters": {"start": start, "count": count},
            "timeout": 600.0,
        })
        operations.append({
            "robot_id": "meca",
            "operation_type": "drop_wafer_sequence",
            "parameters": {"start": start, "count": count},
            "timeout": 600.0,
        })

    # Phase 2: Carousel operations
    for start in range(0, total_wafers, wafers_per_carousel):
        count = min(wafers_per_carousel, total_wafers - start)
        operations.append({
            "robot_id": "meca",
            "operation_type": "carousel_wafer_sequence",
            "parameters": {"start": start, "count": count},
            "timeout": 900.0,
        })
        operations.append({
            "robot_id": "meca",
            "operation_type": "empty_carousel_sequence",
            "parameters": {"start": start, "count": count},
            "timeout": 900.0,
        })

    # Final home operation
    operations.append({
        "robot_id": "meca",
        "operation_type": "home_robot",
        "parameters": {},
        "timeout": 120.0,
    })

    return operations


@router.post("/process-batch")
async def process_wafer_batch(
    data: dict = Body(default={}),
    orchestrator: RobotOrchestrator = OrchestratorDep(),
):
    """Execute multi-robot workflow for batch wafer processing."""
    total_wafers = data.get("total_wafers", 25)
    wafers_per_cycle = data.get("wafers_per_cycle", 5)
    wafers_per_carousel = data.get("wafers_per_carousel", 11)

    robot_operations = _build_batch_operations(total_wafers, wafers_per_cycle, wafers_per_carousel)
    workflow_id = f"batch_process_{total_wafers}_wafers"

    result = await orchestrator.execute_multi_robot_workflow(
        workflow_id=workflow_id,
        robot_operations=robot_operations,
        coordination_strategy="sequential",
    )

    if not result.success:
        raise HTTPException(status_code=500, detail=result.error)

    return ResponseHelper.create_success_response(
        message=f"Batch processing workflow started for {total_wafers} wafers",
        workflow_id=workflow_id,
        total_operations=len(robot_operations),
    )


# -----------------------------------------------------------------------------
# Debug/Diagnostic Endpoints
# -----------------------------------------------------------------------------


@router.get("/debug-connection-state")
async def debug_connection_state(service: MecaService = MecaServiceDep()):
    """Get comprehensive connection diagnostics for the Meca robot."""
    result = await RouterHelper.execute_service_operation(
        service.get_debug_connection_state, "debug_connection_state", logger
    )
    return ResponseHelper.create_success_response(data=result)


@router.get("/test-tcp-connection")
async def test_tcp_connection():
    """Test direct TCP connection to Meca robot, bypassing service layer."""
    import socket
    import time
    from core.settings import get_settings

    settings = get_settings()
    robot_config = settings.get_robot_config("meca")
    host = robot_config["ip"]
    port = robot_config["port"]
    timeout = robot_config.get("timeout", 30.0)

    result = _test_tcp_connectivity(host, port, timeout)
    return ResponseHelper.create_success_response(
        data=result, message=result.get("diagnosis", "TCP test completed")
    )


def _test_tcp_connectivity(host: str, port: int, timeout: float) -> dict:
    """Test TCP connectivity to robot and return diagnostic results."""
    import socket
    import time

    result = {
        "timestamp": time.time(),
        "target": f"{host}:{port}",
        "tcp_connection": "unknown",
        "socket_details": {},
        "recommendations": [],
    }

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(timeout)
            start_time = time.time()
            connect_result = sock.connect_ex((host, port))
            connect_time = time.time() - start_time

            result["socket_details"] = {
                "connect_result_code": connect_result,
                "connect_time_seconds": round(connect_time, 3),
            }

            if connect_result == 0:
                result["tcp_connection"] = "success"
                result["diagnosis"] = "TCP connection successful - robot should be accessible"
                try:
                    result["socket_details"]["local_address"] = f"{sock.getsockname()[0]}:{sock.getsockname()[1]}"
                    result["socket_details"]["peer_address"] = f"{sock.getpeername()[0]}:{sock.getpeername()[1]}"
                except Exception:
                    pass
            elif connect_result == 10061:  # Windows WSAECONNREFUSED
                result["tcp_connection"] = "connection_refused"
                result["diagnosis"] = "Robot hardware reachable but software not listening"
                result["recommendations"] = [
                    "Check if Mecademic robot software is running",
                    "Verify robot is not in error/fault state",
                ]
            elif connect_result == 10060:  # Windows WSAETIMEDOUT
                result["tcp_connection"] = "timeout"
                result["diagnosis"] = "Connection timeout - check network/firewall settings"
                result["recommendations"] = [
                    "Check network firewall settings",
                    "Verify robot network configuration",
                ]
            else:
                result["tcp_connection"] = f"failed_code_{connect_result}"
                result["diagnosis"] = f"Connection failed with code: {connect_result}"

    except socket.timeout:
        result["tcp_connection"] = "timeout_exception"
        result["diagnosis"] = f"Socket timeout after {timeout}s"
        result["recommendations"] = ["Increase connection timeout", "Verify robot is powered on"]
    except Exception as e:
        result["tcp_connection"] = f"error"
        result["diagnosis"] = f"Connection error: {str(e)}"

    return result


# -----------------------------------------------------------------------------
# Sequence Configuration Endpoints
# -----------------------------------------------------------------------------


@router.get("/sequence-config")
async def get_sequence_config(meca_service: MecaService = MecaServiceDep()):
    """Get sequence configuration for batch workflow initialization."""
    from core.settings import get_settings

    settings = get_settings()
    meca_config = settings.get_robot_config("meca")
    sequence_config = meca_config.get("sequence_config", {})
    total_wafers = sequence_config.get("total_wafers", 55)

    return ResponseHelper.create_success_response(data={
        "total_wafers": total_wafers,
        "wafers_per_batch": 5,
        "total_batches": (total_wafers + 4) // 5,
        "sequence_config": sequence_config,
    })


@router.post("/validate-sequence-config")
async def validate_sequence_config(meca_service: MecaService = MecaServiceDep()):
    """Validate sequence configuration for all 55 wafers."""
    errors = meca_service.wafer_config_manager.validate_all_wafers()
    return {
        "status": "valid" if not errors else "invalid",
        "errors": errors,
        "config_version": meca_service.wafer_config_manager.config_version,
        "total_wafers_validated": 55,
    }


@router.post("/preview-wafer-positions")
async def preview_wafer_positions(
    data: dict = Body(default={}),
    meca_service: MecaService = MecaServiceDep(),
):
    """Preview calculated positions for specified wafers."""
    wafer_indices = data.get("wafer_indices", [0, 27, 54])

    invalid_indices = [i for i in wafer_indices if i < 0 or i > 54]
    if invalid_indices:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid wafer indices (must be 0-54): {invalid_indices}",
        )

    preview = meca_service.wafer_config_manager.preview_wafer_positions(
        wafer_indices=wafer_indices,
        first_wafer=meca_service.FIRST_WAFER,
        first_baking=meca_service.FIRST_BAKING_TRAY,
    )

    return ResponseHelper.create_success_response(
        data={"preview": preview, "config_version": meca_service.wafer_config_manager.config_version}
    )


@router.post("/reload-sequence-config")
async def reload_sequence_config(meca_service: MecaService = MecaServiceDep()):
    """Reload sequence configuration from runtime.json."""
    result = await RouterHelper.execute_service_operation(
        meca_service.reload_sequence_config, "reload_sequence_config", logger
    )
    return ResponseHelper.create_success_response(
        data=result, message="Sequence configuration reloaded successfully"
    )


# -----------------------------------------------------------------------------
# Recovery Endpoints - For post-emergency-stop recovery
# -----------------------------------------------------------------------------


@router.post("/recovery/enable")
async def enable_recovery_mode(meca_service: MecaService = MecaServiceDep()):
    """
    Enable recovery mode for safe robot repositioning.

    WARNING: This DISABLES joint limits. Use only after emergency stop when
    the robot needs to be manually repositioned to a safe location.

    Recovery mode enables slow movement without homing, which is critical
    for repositioning a robot that may be in an unsafe position.
    """
    logger.warning("Recovery mode enable requested - joint limits will be disabled")
    result = await RouterHelper.execute_service_operation(
        meca_service.enable_recovery_mode, "enable_recovery_mode", logger
    )
    return ResponseHelper.create_success_response(
        data=result,
        message="Recovery mode enabled - joint limits DISABLED. Move robot carefully."
    )


@router.post("/recovery/disable")
async def disable_recovery_mode(meca_service: MecaService = MecaServiceDep()):
    """
    Disable recovery mode after robot has been repositioned.

    Call this after the robot has been moved to a safe position to
    re-enable normal joint limits and safety features.
    """
    logger.info("Recovery mode disable requested")
    result = await RouterHelper.execute_service_operation(
        meca_service.disable_recovery_mode, "disable_recovery_mode", logger
    )
    return ResponseHelper.create_success_response(
        data=result,
        message="Recovery mode disabled - joint limits restored"
    )


@router.get("/recovery/status")
async def get_recovery_status(meca_service: MecaService = MecaServiceDep()):
    """
    Get current recovery status and available actions.

    Returns comprehensive status including:
    - Current robot state
    - Safety status (errors, e-stop, recovery mode)
    - Available recovery actions
    - Recommended recovery workflow
    """
    result = await RouterHelper.execute_service_operation(
        meca_service.get_recovery_status, "get_recovery_status", logger
    )
    return ResponseHelper.create_success_response(data=result)


@router.post("/recovery/reset-and-reconnect")
async def reset_and_reconnect(meca_service: MecaService = MecaServiceDep()):
    """
    Full recovery sequence: reset errors and reconnect.

    This performs the complete recovery workflow:
    1. Reset any error states
    2. Attempt to reconnect if needed
    3. Prepare robot for activation (but don't activate)

    After this succeeds, call /confirm-activation to activate and home the robot.
    """
    logger.info("Full recovery sequence (reset and reconnect) requested")
    result = await RouterHelper.execute_service_operation(
        meca_service.reset_errors_and_reconnect, "reset_and_reconnect", logger
    )
    return ResponseHelper.create_success_response(
        data=result,
        message=result.get("message", "Recovery sequence completed")
    )


@router.post("/recovery/move-to-safe")
async def move_to_safe_position(
    data: dict = Body(default={}),
    meca_service: MecaService = MecaServiceDep()
):
    """
    Move robot to safe position while in recovery mode.

    The robot MUST be in recovery mode before calling this endpoint.
    Movement is performed at very slow speed for safety.

    Request body (optional):
        speed_percent: Movement speed as percentage (default: 10, max: 20)

    WARNING: Only use this after enabling recovery mode with /recovery/enable
    """
    speed_percent = data.get("speed_percent", 10.0)

    # Validate and clamp speed
    if speed_percent > 20.0:
        logger.warning(f"Requested speed {speed_percent}% exceeds max. Clamping to 20%")
        speed_percent = 20.0
    if speed_percent < 1.0:
        speed_percent = 1.0

    logger.warning(f"Recovery movement requested at {speed_percent}% speed")

    result = await RouterHelper.execute_service_operation(
        lambda: meca_service.move_to_safe_position_recovery(speed_percent),
        "move_to_safe_position_recovery",
        logger
    )
    return ResponseHelper.create_success_response(
        data=result,
        message=result.get("message", "Recovery movement completed")
    )


@router.post("/recovery/quick-recovery")
async def quick_recovery(meca_service: MecaService = MecaServiceDep()):
    """
    Quick recovery - resume workflow from where it stopped.

    Resumes a paused workflow after an emergency stop without losing progress.
    Clears robot error state and continues from the checkpoint.

    This is the recommended recovery option when the robot position is safe
    and you want to continue the workflow.
    """
    logger.info("Quick recovery requested for Meca")
    result = await RouterHelper.execute_service_operation(
        meca_service.quick_recovery, "quick_recovery", logger
    )
    return ResponseHelper.create_success_response(
        data=result,
        message=result.get("message", "Quick recovery completed")
    )


@router.post("/recovery/start-safe-homing")
async def start_safe_homing(
    data: dict = Body(default={}),
    meca_service: MecaService = MecaServiceDep()
):
    """
    Start safe homing at 20% speed with stop/resume capability.

    Moves the robot to a safe home position at reduced speed.
    The movement can be stopped and resumed at any time using the
    stop-safe-homing and resume-safe-homing endpoints.

    Request body (optional):
        speed_percent: Movement speed (default: 20, max: 20)
    """
    speed_percent = min(data.get("speed_percent", 20), 20)
    logger.info(f"Starting safe homing at {speed_percent}% speed")

    result = await RouterHelper.execute_service_operation(
        lambda: meca_service.start_safe_homing(speed_percent),
        "start_safe_homing",
        logger
    )
    return ResponseHelper.create_success_response(
        data=result,
        message=result.get("message", "Safe homing started")
    )


@router.post("/recovery/stop-safe-homing")
async def stop_safe_homing(meca_service: MecaService = MecaServiceDep()):
    """
    Stop safe homing mid-movement - robot holds position.

    Pauses the safe homing movement. The robot will hold its current
    position until resume-safe-homing is called.
    """
    logger.warning("Stop safe homing requested")
    result = await RouterHelper.execute_service_operation(
        meca_service.stop_safe_homing, "stop_safe_homing", logger
    )
    return ResponseHelper.create_success_response(
        data=result,
        message=result.get("message", "Safe homing stopped")
    )


@router.post("/recovery/resume-safe-homing")
async def resume_safe_homing(meca_service: MecaService = MecaServiceDep()):
    """
    Resume safe homing from current position.

    Continues the safe homing movement from where it was stopped.
    """
    logger.info("Resume safe homing requested")
    result = await RouterHelper.execute_service_operation(
        meca_service.resume_safe_homing, "resume_safe_homing", logger
    )
    return ResponseHelper.create_success_response(
        data=result,
        message=result.get("message", "Safe homing resumed")
    )


@router.get("/recovery/safe-homing-status")
async def get_safe_homing_status(meca_service: MecaService = MecaServiceDep()):
    """
    Get current safe homing status.

    Returns whether safe homing is active and whether it's stopped (paused).
    """
    return ResponseHelper.create_success_response(
        data={
            "active": meca_service.is_safe_homing_active(),
            "stopped": meca_service.is_safe_homing_stopped()
        }
    )


@router.post("/recovery/reset-emergency")
async def reset_emergency_stop(orchestrator: RobotOrchestrator = OrchestratorDep()):
    """
    Reset emergency stop state for Meca robot.

    This is a REST API fallback for when WebSocket is unavailable.
    Clears the e-stop flag so the robot can receive new commands.
    """
    logger.info("Reset emergency stop requested for Meca via REST API")
    result = await RouterHelper.execute_service_operation(
        lambda: orchestrator.reset_robot_emergency_stop("meca"),
        "reset_meca_emergency_stop",
        logger
    )
    return ResponseHelper.create_success_response(
        data={"reset": result},
        message="Emergency stop state cleared for Meca"
    )
