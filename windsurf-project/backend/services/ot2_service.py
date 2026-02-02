"""
OT2 robot service - Specialized service for Opentrons OT2 liquid handling operations.
Handles protocol execution, liquid dispensing, and tip management.
"""

import asyncio
import json
import time
from typing import Dict, Any, List, Optional
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

import aiohttp
from core.state_manager import AtomicStateManager, RobotState
from core.resource_lock import ResourceLockManager
from core.circuit_breaker import circuit_breaker
from core.settings import RoboticsSettings
from core.exceptions import HardwareError, ValidationError, ProtocolExecutionError
from .base import RobotService, ServiceResult, OperationContext
from utils.logger import get_logger


class OT2OperationType(Enum):
    """Types of OT2 operations"""

    PROTOCOL_EXECUTION = "protocol_execution"
    LIQUID_HANDLING = "liquid_handling"
    TIP_MANAGEMENT = "tip_management"
    CALIBRATION = "calibration"
    STATUS_CHECK = "status_check"


class ProtocolStatus(Enum):
    """OT2 protocol execution statuses"""

    IDLE = "idle"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    STOPPED = "stopped"
    PAUSED = "paused"
    FINISHING = "finishing"


@dataclass
class LiquidHandlingParams:
    """Parameters for liquid handling operations"""

    source_labware: str
    dest_labware: str
    volume: float
    source_well: str
    dest_well: str
    pipette_name: str = "right"
    speed_multiplier: float = 1.0
    tip_reuse: bool = False


@dataclass
class ProtocolConfig:
    """Configuration for protocol execution"""

    protocol_name: str
    protocol_file: str
    parameters: Dict[str, Any]
    labware_setup: Dict[str, str]
    calibration_required: bool = True


@dataclass
class RunStatus:
    """Status of a protocol run"""

    run_id: str
    protocol_id: str
    status: ProtocolStatus
    current_command: Optional[str] = None
    progress_percent: float = 0.0
    error_message: Optional[str] = None
    start_time: Optional[float] = None
    end_time: Optional[float] = None


class OT2Service(RobotService):
    """
    Service for OT2 liquid handling robot operations.

    Provides high-level operations for protocol execution, liquid handling,
    and system management with proper error handling and monitoring.
    """

    def __init__(
        self,
        robot_id: str,
        settings: RoboticsSettings,
        state_manager: AtomicStateManager,
        lock_manager: ResourceLockManager,
    ):
        super().__init__(
            robot_id=robot_id,
            robot_type="ot2",
            settings=settings,
            state_manager=state_manager,
            lock_manager=lock_manager,
            service_name="OT2Service",
        )

        self.logger = get_logger("ot2_service")

        self.ot2_config = settings.get_robot_config("ot2")
        self.base_url = f"http://{self.ot2_config['ip']}:{self.ot2_config['port']}"

        # HTTP session for API calls
        self._session: Optional[aiohttp.ClientSession] = None

        # Current run tracking
        self._current_run: Optional[RunStatus] = None
        self._monitoring_task: Optional[asyncio.Task] = None

        # Protocol storage from settings
        protocol_config = self.ot2_config.get("protocol_config", {})
        protocol_dir = protocol_config.get("directory", "protocols/")

        # Ensure protocol directory is resolved as absolute path
        if not Path(protocol_dir).is_absolute():
            self.protocol_directory = Path("/app") / protocol_dir
        else:
            self.protocol_directory = Path(protocol_dir)

        self.protocol_directory.mkdir(exist_ok=True)
        self.default_protocol_file = protocol_config.get(
            "default_file", "ot2Protocole.py"
        )
        self.protocol_execution_timeout = protocol_config.get(
            "execution_timeout", 3600.0
        )
        self.monitoring_interval = protocol_config.get("monitoring_interval", 2.0)

        # Protocol execution lock - prevents double-start race condition
        # Per plan: Use async with lock to serialize protocol execution
        self._protocol_lock = asyncio.Lock()

        # Track emergency stop state - robot needs homing after emergency stop
        self._was_emergency_stopped = False

        # Position tracking for reverse path homing (Phase 4)
        self._position_history: List[Dict[str, Any]] = []
        self._max_position_history = 50

    async def _check_robot_connection(self) -> bool:
        """Check if OT2 robot is connected and accessible"""
        try:
            # Use existing HTTP health check
            health_data = await self._get_health_status()
            return health_data is not None
        except Exception as e:
            self.logger.debug(f"OT2 connection check failed: {e}")
            return False

    async def _handle_connection_state_change(self, is_connected: bool):
        """Handle OT2 robot connection state changes"""
        from core.state_manager import RobotState

        if is_connected:
            await self.update_robot_state(RobotState.IDLE, reason="OT2 robot connection restored")
            self.logger.info(f"OT2 robot {self.robot_id} connection restored")
        else:
            await self.update_robot_state(RobotState.ERROR, reason="OT2 robot connection lost")
            self.logger.warning(f"OT2 robot {self.robot_id} connection lost")

        await self._broadcast_robot_state_change(is_connected)

    async def _broadcast_robot_state_change(self, is_connected: bool):
        """Broadcast robot state change to WebSocket clients"""
        try:
            # Import here to avoid circular imports
            from websocket.selective_broadcaster import get_broadcaster, MessageType

            broadcaster = await get_broadcaster()

            message = {
                "type": "robot_status",
                "robot_id": self.robot_id,
                "robot_type": self.robot_type,
                "connected": is_connected,
                "robot_state": "idle" if is_connected else "error",
                "operational": is_connected,
                "timestamp": time.time(),
            }

            await broadcaster.broadcast_message(
                message_type=MessageType.ROBOT_STATUS,
                data=message,
                robot_id=self.robot_id,
            )

            self.logger.debug(f"Broadcasted OT2 state change: connected={is_connected}")

        except Exception as e:
            self.logger.error(f"Failed to broadcast OT2 state change: {e}")

    async def _on_start(self):
        """Initialize HTTP session and start monitoring"""
        # First register the robot with state manager
        await super()._on_start()

        # HTTP configuration from settings
        http_config = self.ot2_config.get("http_config", {})
        connector_limit = http_config.get("connector_limit", 10)
        total_timeout = http_config.get("total_timeout", 30.0)
        connect_timeout = http_config.get("connect_timeout", 10.0)
        self.api_version = http_config.get("api_version", "4")

        connector = aiohttp.TCPConnector(limit=connector_limit)
        timeout = aiohttp.ClientTimeout(total=total_timeout, connect=connect_timeout)
        self._session = aiohttp.ClientSession(
            connector=connector, timeout=timeout, headers={"Opentrons-Version": "2"}
        )

        # Try to connect and update state
        try:
            # Update to connecting state first
            await self.update_robot_state(
                RobotState.CONNECTING, reason="Attempting to connect to OT2"
            )

            # Test connection to OT2
            health_data = await self._get_health_status()
            if health_data:
                await self.update_robot_state(
                    RobotState.IDLE, reason="OT2 connected and ready"
                )
                self.logger.info(f"OT2 robot {self.robot_id} connected successfully")
            else:
                await self.update_robot_state(
                    RobotState.ERROR, reason="No health data received from OT2"
                )
        except Exception as e:
            self.logger.warning(f"OT2 robot {self.robot_id} connection failed: {e}")
            await self.update_robot_state(
                RobotState.ERROR, reason=f"Connection failed: {e}"
            )

        # Start run monitoring if there's an active run
        await self._check_for_active_runs()

    async def _on_stop(self):
        """Clean up HTTP session and stop monitoring"""
        # Update robot state to disconnected
        try:
            await self.update_robot_state(
                RobotState.DISCONNECTED, reason="Service stopping"
            )
        except Exception as e:
            self.logger.error(f"Failed to update robot state on stop: {e}")

        if self._monitoring_task:
            self._monitoring_task.cancel()
            try:
                await self._monitoring_task
            except asyncio.CancelledError:
                pass

        if self._session:
            await self._session.close()

    def _extract_run_status(self, run: Dict[str, Any]) -> Optional[str]:
        """Extract status from a run dict handling various API response formats."""
        if not isinstance(run, dict):
            return None
        if "attributes" in run and isinstance(run["attributes"], dict):
            return run["attributes"].get("status")
        return run.get("status")

    async def _execute_emergency_stop(self) -> bool:
        """
        Emergency stop implementation for OT2.

        This method is resilient to state desync - it will stop ALL running or paused
        runs discovered via API query, not just the tracked _current_run.

        Steps:
        1. Stop tracked run if exists and is active (running OR paused)
        2. CRITICAL: Query /runs API and stop ALL running/paused runs (handles desync)
        3. Cancel monitoring task
        4. Clear internal state

        Note: Does NOT home robot - emergency stop should only STOP motion, not initiate
        new motion. User should manually home after emergency condition is cleared.
        """
        self.logger.critical(f"Executing emergency stop for OT2 robot {self.robot_id}")
        stopped_operations = []
        failed_operations = []

        try:
            # Step 1: Stop tracked run if active (running OR paused)
            if self._current_run and self._current_run.status in [ProtocolStatus.RUNNING, ProtocolStatus.PAUSED]:
                tracked_run_id = self._current_run.run_id
                self.logger.critical(f"Stopping tracked run: {tracked_run_id} (status: {self._current_run.status})")
                if await self._stop_run(tracked_run_id):
                    stopped_operations.append(f"tracked_run_{tracked_run_id}")
                else:
                    failed_operations.append(f"tracked_run_{tracked_run_id}")

            # Step 2: CRITICAL - Query /runs API and stop ALL running/paused runs
            # This handles state desync where _current_run may be None but runs are active
            try:
                runs_data = await self._get_current_runs()
                data_list = runs_data.get("data", [])
                if isinstance(data_list, list):
                    for run in data_list:
                        status = self._extract_run_status(run)
                        # Stop both running AND paused runs
                        if status in ["running", "paused"]:
                            run_id = run.get("id")
                            if run_id:
                                # Skip if we already stopped this run in step 1
                                if self._current_run and run_id == self._current_run.run_id:
                                    continue

                                self.logger.critical(f"Found active run via API query: {run_id} (status: {status})")
                                if await self._stop_run(run_id):
                                    stopped_operations.append(f"api_discovered_run_{run_id}")
                                else:
                                    failed_operations.append(f"api_discovered_run_{run_id}")
            except Exception as e:
                self.logger.error(f"Could not query/stop active runs from API: {e}")
                failed_operations.append(f"api_query_error: {e}")

            # Step 3: Cancel monitoring task
            if self._monitoring_task and not self._monitoring_task.done():
                self._monitoring_task.cancel()
                try:
                    await self._monitoring_task
                except asyncio.CancelledError:
                    pass
                stopped_operations.append("monitoring_task")

            # Step 4: Clear internal state
            # NOTE: Homing removed from emergency stop - homing initiates motion which
            # contradicts the purpose of emergency stop (STOP all motion, not start new motion).
            # User should manually home after emergency condition is cleared.
            self._current_run = None
            self._was_emergency_stopped = True  # Track that we need homing before next run

            # Step 5: Set robot state to EMERGENCY_STOP so RecoveryPanel is shown
            # This is critical - without this state change, the frontend won't display
            # the recovery options (Safe Home, reverse path homing, etc.)
            await self.update_robot_state(
                RobotState.EMERGENCY_STOP,
                reason="Emergency stop activated - manual recovery required"
            )

            # Log summary
            if failed_operations:
                self.logger.critical(
                    f"Emergency stop completed with failures. "
                    f"Stopped: {stopped_operations}, Failed: {failed_operations}"
                )
            else:
                self.logger.critical(f"Emergency stop completed successfully. Stopped: {stopped_operations}")

            return True

        except Exception as e:
            self.logger.error(f"Emergency stop failed with exception: {e}", exc_info=True)
            return False

    @circuit_breaker("ot2_connection", failure_threshold=3, recovery_timeout=30)
    async def execute_protocol(
        self, protocol_config: ProtocolConfig, monitor_progress: bool = True
    ) -> ServiceResult[RunStatus]:
        """
        Execute a protocol on the OT2 robot.

        Args:
            protocol_config: Protocol configuration and parameters
            monitor_progress: Whether to monitor execution progress
        """
        context = OperationContext(
            operation_id=f"{self.robot_id}_protocol_{protocol_config.protocol_name}",
            robot_id=self.robot_id,
            operation_type=OT2OperationType.PROTOCOL_EXECUTION.value,
            timeout=self.settings.protocol_execution_timeout,
            metadata={"protocol": protocol_config.protocol_name},
        )

        async def _execute_protocol():
            # Acquire protocol lock to prevent double-start race condition
            # Per plan: Lock FIRST, then check state INSIDE the lock
            async with self._protocol_lock:
                # Ensure robot is ready (CommandService already set to BUSY)
                await self.ensure_robot_ready()

                # Check if another protocol is running (now thread-safe inside lock)
                if self._current_run and self._current_run.status == ProtocolStatus.RUNNING:
                    raise ValidationError(
                        f"Protocol already running: {self._current_run.protocol_id}"
                    )

                try:
                    # Step 1: Upload protocol if needed
                    protocol_id = await self._upload_protocol(protocol_config)

                    # Step 2: CRITICAL FIX - Wait for protocol analysis to complete
                    self.logger.info("Waiting for protocol analysis to complete...")
                    analysis_success = await self._wait_for_analysis_completion(protocol_id)

                    if not analysis_success:
                        raise ProtocolExecutionError(
                            "Protocol analysis failed - cannot create run with empty protocol"
                        )

                    # Step 2.5: Validate hardware requirements
                    self.logger.info("Validating hardware requirements...")
                    hardware_validation = await self._validate_hardware_requirements(
                        protocol_id
                    )

                    if not hardware_validation["valid"]:
                        detailed_error = self._generate_hardware_error_message(
                            hardware_validation
                        )
                        raise HardwareError(detailed_error, robot_id=self.robot_id)

                    # Log warnings but continue execution
                    if hardware_validation["warnings"]:
                        for warning in hardware_validation["warnings"]:
                            self.logger.warning(f"Hardware warning: {warning}")

                    self.logger.info(
                        "Hardware validation passed - proceeding with protocol execution"
                    )

                    # Step 2.75: Pre-run homing (skip if already homed AND not after emergency stop)
                    # Opentrons default is HOME_AND_STAY_ENGAGED after runs, so motors
                    # stay engaged when robot is at known position. Skip homing if engaged
                    # UNLESS we had an emergency stop (robot may be in unknown position).
                    motors_engaged = await self._are_motors_engaged()
                    if motors_engaged and not self._was_emergency_stopped:
                        self.logger.info("Motors engaged - skipping pre-run homing (robot already at known position)")
                    else:
                        reason = "after emergency stop" if self._was_emergency_stopped else "motors not engaged"
                        self.logger.info(f"Performing pre-run homing ({reason})...")
                        home_success = await self._home_robot()
                        if home_success:
                            self._was_emergency_stopped = False  # Clear flag after successful home
                            self.logger.info("Pre-run homing successful, waiting for stabilization...")
                            # Wait 20 seconds for homing to complete (successful runs show ~18s homing time)
                            await asyncio.sleep(20)
                            self.logger.info("Hardware stabilized, ready for protocol execution")
                        else:
                            self.logger.warning("Pre-run homing failed, but continuing with protocol execution")

                    # Step 3: Create and start run (only after analysis completes)
                    run_id = await self._create_run(protocol_id, protocol_config.parameters)

                    # Step 4: Start execution
                    run_status = await self._start_run(run_id)
                    self._current_run = run_status

                    # Step 5: Monitor execution if requested
                    if monitor_progress:
                        self._monitoring_task = asyncio.create_task(
                            self._monitor_run_progress(run_id)
                        )

                        # Wait for completion
                        final_status = await self._monitoring_task
                        return final_status
                    else:
                        return run_status

                except Exception as e:
                    self.logger.error(f"Protocol execution failed: {e}")
                    raise

        return await self.execute_operation(context, _execute_protocol)

    async def liquid_handling_operation(
        self, operation_id: str, params: LiquidHandlingParams
    ) -> ServiceResult[Dict[str, Any]]:
        """
        Execute a liquid handling operation.

        Args:
            operation_id: Unique operation identifier
            params: Liquid handling parameters
        """
        context = OperationContext(
            operation_id=f"{self.robot_id}_liquid_{operation_id}",
            robot_id=self.robot_id,
            operation_type=OT2OperationType.LIQUID_HANDLING.value,
            metadata={
                "volume": params.volume,
                "source": params.source_well,
                "dest": params.dest_well,
            },
        )

        async def _liquid_handling():
            # Create a simple protocol for liquid handling
            protocol_data = self._create_liquid_handling_protocol(params)

            # Save protocol temporarily
            protocol_file = (
                self.protocol_directory / f"liquid_handling_{operation_id}.py"
            )
            with open(protocol_file, "w") as f:
                f.write(protocol_data)

            try:
                # Execute the liquid handling protocol
                protocol_config = ProtocolConfig(
                    protocol_name=f"liquid_handling_{operation_id}",
                    protocol_file=str(protocol_file),
                    parameters={},
                    labware_setup={},
                )

                result = await self.execute_protocol(protocol_config)

                if result.success:
                    return {
                        "operation_id": operation_id,
                        "volume_transferred": params.volume,
                        "source": f"{params.source_labware}:{params.source_well}",
                        "destination": f"{params.dest_labware}:{params.dest_well}",
                        "status": "completed",
                    }
                else:
                    raise HardwareError(
                        f"Liquid handling failed: {result.error}",
                        robot_id=self.robot_id,
                    )

            finally:
                # Clean up temporary protocol file
                if protocol_file.exists():
                    protocol_file.unlink()

        return await self.execute_operation(context, _liquid_handling)

    async def calibrate_pipettes(self) -> ServiceResult[Dict[str, Any]]:
        """Calibrate OT2 pipettes"""
        context = OperationContext(
            operation_id=f"{self.robot_id}_calibration",
            robot_id=self.robot_id,
            operation_type=OT2OperationType.CALIBRATION.value,
            timeout=300.0,  # Calibration takes longer
        )

        async def _calibrate():
            await self.ensure_robot_ready()

            calibration_data = await self._get_calibration_data()

            needs_calibration = any(
                not cal.get("status", {}).get("markedAt")
                for cal in calibration_data.get("data", {}).values()
            )

            result = {
                "calibration_required": needs_calibration,
                "calibration_data": calibration_data,
                "status": "completed",
            }

            if needs_calibration:
                self.logger.warning("Pipette calibration required - manual intervention needed")
                result["message"] = "Manual calibration required through OT-2 interface"

            return result

        return await self.execute_operation(context, _calibrate)

    async def calibrate_robot(self) -> ServiceResult[Dict[str, Any]]:
        """Calibrate robot (alias for calibrate_pipettes to match CommandService expectations)"""
        return await self.calibrate_pipettes()

    async def connect(self) -> ServiceResult[bool]:
        """Connect to OT2 robot"""
        try:
            # Test connection
            health_data = await self._get_health_status()
            if health_data:
                await self.update_robot_state(
                    RobotState.IDLE, reason="Connected to OT2"
                )
                return ServiceResult.success_result(True)
            else:
                await self.update_robot_state(
                    RobotState.ERROR, reason="Connection failed"
                )
                return ServiceResult.success_result(False)
        except Exception as e:
            await self.update_robot_state(
                RobotState.ERROR, reason=f"Connection error: {e}"
            )
            return ServiceResult.error_result(f"Connection failed: {e}")

    async def disconnect(self) -> ServiceResult[bool]:
        """Disconnect from OT2 robot"""
        try:
            await self.update_robot_state(
                RobotState.DISCONNECTED, reason="Disconnected from OT2"
            )
            return ServiceResult.success_result(True)
        except Exception as e:
            return ServiceResult.error_result(f"Disconnect failed: {e}")

    async def emergency_stop(self) -> ServiceResult[bool]:
        """Emergency stop OT2 robot"""
        try:
            result = await self._execute_emergency_stop()
            if result:
                await self.update_robot_state(
                    RobotState.ERROR, reason="Emergency stop activated"
                )
            return ServiceResult.success_result(result)
        except Exception as e:
            return ServiceResult.error_result(f"Emergency stop failed: {e}")

    async def home_robot(self) -> ServiceResult[bool]:
        """Home the OT2 robot"""
        try:
            result = await self._home_robot()
            return ServiceResult.success_result(result)
        except Exception as e:
            return ServiceResult.error_result(f"Homing failed: {e}")

    async def stop_robot(self) -> ServiceResult[bool]:
        """Stop current operation"""
        return await self.stop_current_run()

    async def reset_robot(self) -> ServiceResult[bool]:
        """Reset robot to idle state"""
        try:
            # CommandService handles state management
            return ServiceResult.success_result(True)
        except Exception as e:
            return ServiceResult.error_result(f"Reset failed: {e}")

    async def clear_and_reconnect(self) -> ServiceResult[Dict[str, Any]]:
        """
        Recovery operation: Clear all runs, home the robot, and reset state.

        This is used after an emergency stop or error state to recover the OT2.
        The OT2 uses HTTP-based stateless connections, so recovery is simpler
        than for the Mecademic - we just need to:
        1. Stop any running protocols
        2. Clear/delete any stuck runs
        3. Home the robot
        4. Reset internal state

        Returns:
            ServiceResult containing recovery status and steps performed
        """
        context = OperationContext(
            operation_id=f"{self.robot_id}_clear_and_reconnect",
            robot_id=self.robot_id,
            operation_type="recovery",
            timeout=120.0
        )

        async def _clear_and_reconnect():
            self.logger.info(f"[CONNECTING] Starting OT2 recovery sequence for {self.robot_id}")
            recovery_steps = []

            # Step 1: Check current connection/health
            self.logger.info(f"Step 1: Checking OT2 health for {self.robot_id}")
            try:
                health_data = await self._get_health_status()
                recovery_steps.append({
                    "step": "health_check",
                    "success": health_data is not None,
                    "robot_name": health_data.get("name") if health_data else None
                })
            except Exception as e:
                self.logger.warning(f"Health check failed: {e}")
                recovery_steps.append({
                    "step": "health_check",
                    "success": False,
                    "error": str(e)
                })
                # If health check fails, robot is not accessible
                return {
                    "robot_id": self.robot_id,
                    "recovery_success": False,
                    "steps": recovery_steps,
                    "message": "OT2 not accessible. Check network connection and power."
                }

            # Step 2: Stop any active runs
            self.logger.info(f"Step 2: Stopping any active runs for {self.robot_id}")
            try:
                active_run_id = await self.get_active_run_id()
                if active_run_id:
                    stop_success = await self._stop_run(active_run_id)
                    recovery_steps.append({
                        "step": "stop_active_run",
                        "run_id": active_run_id,
                        "success": stop_success
                    })
                    await asyncio.sleep(2.0)  # Allow time for stop to complete
                else:
                    recovery_steps.append({
                        "step": "stop_active_run",
                        "success": True,
                        "message": "No active run to stop"
                    })
            except Exception as e:
                self.logger.warning(f"Stop active run failed: {e}")
                recovery_steps.append({
                    "step": "stop_active_run",
                    "success": False,
                    "error": str(e)
                })

            # Step 3: Clear runs (delete completed/failed runs)
            self.logger.info(f"Step 3: Clearing runs for {self.robot_id}")
            try:
                runs_data = await self._get_current_runs()
                runs_list = runs_data.get("data", [])
                cleared_count = 0

                for run in runs_list:
                    run_id = run.get("id")
                    status = self._extract_run_status(run)
                    # Only delete non-running runs
                    if status not in ["running", "paused"] and run_id:
                        try:
                            await self._api_request("DELETE", f"/runs/{run_id}")
                            cleared_count += 1
                        except Exception as e:
                            self.logger.debug(f"Could not delete run {run_id}: {e}")

                recovery_steps.append({
                    "step": "clear_runs",
                    "success": True,
                    "runs_cleared": cleared_count
                })
            except Exception as e:
                self.logger.warning(f"Clear runs failed: {e}")
                recovery_steps.append({
                    "step": "clear_runs",
                    "success": False,
                    "error": str(e)
                })

            # Step 4: Home the robot
            self.logger.info(f"Step 4: Homing robot {self.robot_id}")
            try:
                home_success = await self._home_robot()
                recovery_steps.append({
                    "step": "home_robot",
                    "success": home_success
                })
            except Exception as e:
                self.logger.warning(f"Homing failed: {e}")
                recovery_steps.append({
                    "step": "home_robot",
                    "success": False,
                    "error": str(e)
                })

            # Step 5: Reset internal state
            self.logger.info(f"Step 5: Resetting internal state for {self.robot_id}")
            try:
                self._current_run = None
                if self._monitoring_task:
                    self._monitoring_task.cancel()
                    self._monitoring_task = None

                # Update robot state to IDLE
                await self.update_robot_state(
                    RobotState.IDLE,
                    reason="Recovery complete - robot ready"
                )

                recovery_steps.append({
                    "step": "reset_state",
                    "success": True
                })
                recovery_success = True

            except Exception as e:
                self.logger.warning(f"State reset failed: {e}")
                recovery_steps.append({
                    "step": "reset_state",
                    "success": False,
                    "error": str(e)
                })
                recovery_success = False

            self.logger.info(f"OT2 recovery sequence completed: success={recovery_success}")

            return {
                "robot_id": self.robot_id,
                "recovery_success": recovery_success,
                "steps": recovery_steps,
                "message": "OT2 recovery complete. Robot is ready." if recovery_success else "OT2 recovery incomplete. Check robot status."
            }

        return await self.execute_operation(context, _clear_and_reconnect)

    async def move_to_position(self, **kwargs) -> ServiceResult[bool]:
        """Move robot to position (not applicable for OT2)"""
        return ServiceResult.error_result("Move to position not supported for OT2")

    async def initialize_protocol(
        self, protocol_file: str, protocol_parameters: Dict[str, Any] = None
    ) -> ServiceResult[Dict[str, Any]]:
        """Initialize protocol execution - wrapper method for ProtocolExecutionService compatibility"""
        try:
            # Validate protocol file exists
            if not Path(protocol_file).exists():
                return ServiceResult.error_result(
                    f"Protocol file not found: {protocol_file}"
                )

            # Ensure robot is ready
            await self.ensure_robot_ready()

            # Get health status to verify connection
            health_data = await self._get_health_status()
            if not health_data:
                return ServiceResult.error_result("OT2 robot not accessible")

            self.logger.info(f"OT2 protocol initialized: {protocol_file}")
            return ServiceResult.success_result(
                {
                    "status": "initialized",
                    "protocol_file": protocol_file,
                    "protocol_parameters": protocol_parameters or {},
                    "robot_health": health_data,
                }
            )
        except Exception as e:
            self.logger.error(f"Failed to initialize protocol: {e}")
            return ServiceResult.error_result(
                f"Protocol initialization failed: {str(e)}"
            )

    async def run_protocol(self, **kwargs) -> ServiceResult[Dict[str, Any]]:
        """
        Run protocol execution - Fixed to correctly upload protocol, wait for analysis, and then execute.
        This is a wrapper method for ProtocolExecutionService compatibility.
        """
        try:
            # CRITICAL: Set robot state to BUSY at start of protocol execution
            # This enables pause_system to find OT2 as an active robot
            await self.update_robot_state(RobotState.BUSY, reason="Protocol executing")
            self.logger.info("OT2 state set to BUSY - protocol starting")

            # Filter out unsupported parameters and extract valid protocol parameters
            protocol_parameters = kwargs.copy()

            # Remove unsupported parameters
            for param in ["test", "debug", "verbose"]:
                protocol_parameters.pop(param, None)

            # Validate protocol file exists
            protocol_file_path = self.protocol_directory / self.default_protocol_file
            if not protocol_file_path.exists():
                raise ValidationError(f"Protocol file not found: {protocol_file_path}")

            # Merge runtime.json defaults with API overrides
            ot2_config_params = self.ot2_config.get("protocol_parameters", {}).copy()
            api_overrides = {k: v for k, v in protocol_parameters.items() if k in ot2_config_params}
            ot2_config_params.update(api_overrides)

            self.logger.debug(f"Protocol parameters: {ot2_config_params}")

            # Create a default protocol config for the standard OT2 protocol
            protocol_config = ProtocolConfig(
                protocol_name=protocol_parameters.get(
                    "protocol_name", "OT2_Liquid_Handling"
                ),
                protocol_file=str(protocol_file_path),
                parameters=ot2_config_params,
                labware_setup={},
            )

            # Execute the protocol using the corrected execute_protocol method
            result = await self.execute_protocol(protocol_config, monitor_progress=True)

            if result.success:
                # Check if emergency stop occurred during execution
                # If so, do NOT override the EMERGENCY_STOP state with IDLE
                # The RecoveryPanel needs to be shown for manual recovery
                if self._was_emergency_stopped:
                    self.logger.info(
                        "OT2 protocol completed but emergency stop was triggered - "
                        "maintaining EMERGENCY_STOP state for RecoveryPanel"
                    )
                else:
                    # Set robot state back to IDLE after successful protocol completion
                    await self.update_robot_state(RobotState.IDLE, reason="Protocol completed successfully")
                    self.logger.info("OT2 state set to IDLE - protocol completed successfully")
                return ServiceResult.success_result(
                    {
                        "status": "completed" if not self._was_emergency_stopped else "emergency_stopped",
                        "run_status": (
                            result.data.__dict__
                            if hasattr(result.data, "__dict__")
                            else result.data
                        ),
                        "protocol_parameters": protocol_parameters,
                    }
                )
            else:
                # Check if this failure was due to emergency stop
                if self._was_emergency_stopped:
                    self.logger.info(
                        "OT2 protocol failed due to emergency stop - "
                        "maintaining EMERGENCY_STOP state for RecoveryPanel"
                    )
                else:
                    # Set robot state back to IDLE on protocol failure (non-emergency)
                    await self.update_robot_state(RobotState.IDLE, reason=f"Protocol failed: {result.error}")
                    self.logger.info("OT2 state set to IDLE - protocol failed")
                return ServiceResult.error_result(
                    f"Protocol execution failed: {result.error}"
                )

        except Exception as e:
            self.logger.error(f"Failed to run protocol: {e}", exc_info=True)
            # Ensure robot state is reset appropriately
            # Do NOT override EMERGENCY_STOP state - RecoveryPanel needs to be shown
            try:
                if self._was_emergency_stopped:
                    self.logger.info(
                        "OT2 protocol exception after emergency stop - "
                        "maintaining EMERGENCY_STOP state for RecoveryPanel"
                    )
                else:
                    await self.update_robot_state(RobotState.IDLE, reason=f"Protocol exception: {str(e)}")
                    self.logger.info("OT2 state set to IDLE - protocol exception")
            except Exception as state_error:
                self.logger.error(f"Failed to reset OT2 state after exception: {state_error}")
            return ServiceResult.error_result(f"Protocol execution failed: {str(e)}")

    async def get_robot_status(self) -> ServiceResult[Dict[str, Any]]:
        """Get detailed OT2 robot status"""
        context = OperationContext(
            operation_id=f"{self.robot_id}_status",
            robot_id=self.robot_id,
            operation_type=OT2OperationType.STATUS_CHECK.value,
        )

        async def _get_status():
            health_data = await self._get_health_status()
            runs_data = await self._get_current_runs()
            robot_info = await self.state_manager.get_robot_state(self.robot_id)
            hardware_info = await self._build_hardware_info()

            return {
                "robot_id": self.robot_id,
                "robot_type": self.robot_type,
                "hardware_status": health_data,
                "hardware_info": hardware_info,
                "current_runs": runs_data,
                "state_info": {
                    "current_state": robot_info.current_state.value if robot_info else "unknown",
                    "operational": robot_info.is_operational if robot_info else False,
                    "uptime_seconds": robot_info.uptime_seconds if robot_info else 0,
                    "error_count": robot_info.error_count if robot_info else 0,
                },
                "current_run": self._current_run.__dict__ if self._current_run else None,
                "base_url": self.base_url,
            }

        return await self.execute_operation(context, _get_status)

    async def stop_current_run(self) -> ServiceResult[bool]:
        """Stop the currently running protocol"""
        if not self._current_run or self._current_run.status != ProtocolStatus.RUNNING:
            return ServiceResult.error_result(
                "No protocol currently running", error_code="NO_ACTIVE_RUN"
            )

        context = OperationContext(
            operation_id=f"{self.robot_id}_stop_run",
            robot_id=self.robot_id,
            operation_type="stop_run",
        )

        async def _stop_run():
            success = await self._stop_run(self._current_run.run_id)
            # CommandService handles state management
            return success

        return await self.execute_operation(context, _stop_run)

    # HTTP API helper methods

    def _parse_run_response(self, run_data: Dict[str, Any]) -> Dict[str, Any]:
        """Parse run response handling both nested and flat structures."""
        run_data_attrs = run_data.get("data", {})
        if "attributes" in run_data_attrs:
            return run_data_attrs["attributes"]
        return run_data_attrs

    async def _api_request(
        self,
        method: str,
        endpoint: str,
        data: Optional[Dict[str, Any]] = None,
        timeout: float = 30.0,
    ) -> Dict[str, Any]:
        """Make HTTP request to OT2 API"""
        if not self._session:
            raise HardwareError("HTTP session not initialized", robot_id=self.robot_id)

        url = f"{self.base_url}{endpoint}"

        try:
            headers = {"Opentrons-Version": "2"}
            kwargs = {
                "timeout": aiohttp.ClientTimeout(total=timeout),
                "headers": headers,
            }
            if data:
                kwargs["json"] = data

            self.logger.debug(f"OT2 API Request: {method} {url}")
            if data:
                self.logger.debug(f"Request data: {data}")

            async with self._session.request(method, url, **kwargs) as response:
                if response.status >= 400:
                    error_text = await response.text()
                    self.logger.error(
                        f"OT2 API error response: {response.status} - {error_text}"
                    )
                    raise HardwareError(
                        f"OT2 API error: {response.status} - {error_text}",
                        robot_id=self.robot_id,
                    )

                response_data = await response.json()
                
                # Use concise logging for routine status checks to reduce log noise
                if endpoint in ["/health", "/runs"]:
                    if endpoint == "/health":
                        self.logger.debug(f"OT2 health check: {response.status} OK")
                    elif endpoint == "/runs":
                        # Log run count instead of full data
                        run_count = len(response_data.get('data', [])) if isinstance(response_data, dict) else 0
                        self.logger.debug(f"OT2 runs check: {response.status} OK ({run_count} runs)")
                else:
                    # Full response logging for important operations (protocols, commands, etc.)
                    self.logger.debug(
                        f"OT2 API Response: {response.status} - {response_data}"
                    )
                return response_data

        except aiohttp.ClientError as e:
            self.logger.error(f"OT2 connection error for {method} {url}: {e}")
            raise HardwareError(f"OT2 connection error: {e}", robot_id=self.robot_id)

    async def _clear_protocol_cache(self):
        """Clear protocol cache by deleting all existing protocols.

        This prevents OT2 v7.0.0+ protocol cache from reusing stale analysis.
        """
        try:
            self.logger.info("Clearing protocol cache...")
            protocols_response = await self._api_request("GET", "/protocols")
            protocols = protocols_response.get("data", [])

            for protocol in protocols:
                protocol_id = protocol.get("id")
                if protocol_id:
                    try:
                        await self._api_request("DELETE", f"/protocols/{protocol_id}")
                        self.logger.debug(f"Deleted cached protocol: {protocol_id}")
                    except Exception as e:
                        self.logger.warning(f"Failed to delete protocol {protocol_id}: {e}")

            self.logger.info(f"Cleared {len(protocols)} cached protocol(s)")
        except Exception as e:
            self.logger.warning(f"Failed to clear protocol cache: {e}")
            # Don't fail if cache clearing fails - it's a best-effort optimization

    def _get_runtime_value(self, key: str, default: Any, parse_json: bool = False) -> Any:
        """Get a runtime config value, optionally parsing JSON."""
        value = self.ot2_config.get(key, default)
        if parse_json and isinstance(value, str):
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                self.logger.warning(f"Failed to parse JSON for {key}, using default")
                return default if not isinstance(default, str) else json.loads(default)
        return value

    def _inject_runtime_values(self, protocol_content: str) -> str:
        """Inject runtime.json values into protocol constants."""
        import re

        # Scalar replacements: (pattern, config_key, default, format_string)
        scalar_replacements = [
            (r'NUM_OF_GENERATORS = \d+', 'num_generators', 5, 'NUM_OF_GENERATORS = {}'),
            (r'THORIUM_VOL = [\d.]+', 'radioactive_vol', 6.6, 'THORIUM_VOL = {}'),
            (r'SDS_VOL = [\d.]+', 'sds_vol', 1.0, 'SDS_VOL = {}'),
            (r'CUR = \d+', 'cur', 2, 'CUR = {}'),
            (r'tip_location = "[^"]*"', 'tip_location', "1", 'tip_location = "{}"'),
        ]

        # Array replacements: (pattern, config_key, default_json)
        array_replacements = [
            (r'sds_lct = \[[^\]]+\]', 'sds_location', '[287, 226, 40]'),
            (r'thorium_lct = \[[^\]]+\]', 'radioactive_location', '[354, 225, 40]'),
            (r'home_lct = \[[^\]]+\]', 'home_location', '[350, 350, 147]'),
            (r'temp_lct = \[[^\]]+\]', 'temp_location', '[8, 350, 147]'),
            (r'hight_home_lct = \[[^\]]+\]', 'height_home_location', '[302, 302, 147]'),
            (r'hight_temp_lct = \[[^\]]+\]', 'height_temp_location', '[8, 228, 147]'),
        ]

        # Apply scalar replacements
        for pattern, key, default, fmt in scalar_replacements:
            value = self._get_runtime_value(key, default)
            protocol_content = re.sub(pattern, fmt.format(value), protocol_content)

        # Apply array replacements
        for pattern, key, default_json in array_replacements:
            value = self._get_runtime_value(key, default_json, parse_json=True)
            var_name = pattern.split(' = ')[0]
            protocol_content = re.sub(pattern, f'{var_name} = {value}', protocol_content)

        # Handle nested array (generators_locations) separately
        generators = self._get_runtime_value(
            'generators_locations',
            '[[4, 93, 133], [4, 138, 133], [4, 183, 133], [4, 228, 133], [4, 273, 133]]',
            parse_json=True
        )
        protocol_content = re.sub(
            r'generators_locations = \[.*\]$',
            f'generators_locations = {generators}',
            protocol_content,
            flags=re.MULTILINE
        )

        self.logger.info(
            f"Injected runtime values: num_generators={self._get_runtime_value('num_generators', 5)}, "
            f"radioactive_vol={self._get_runtime_value('radioactive_vol', 6.6)}"
        )

        return protocol_content

    async def _upload_protocol(self, protocol_config: ProtocolConfig) -> str:
        """Upload protocol to OT2 using dual-structure format (Python file + JSON metadata)

        This matches the working robot manager approach that properly enables hardware recognition.
        """
        # Clear protocol cache first to prevent v7.0.0+ stale analysis issues
        await self._clear_protocol_cache()

        protocol_file = Path(protocol_config.protocol_file)

        # Protocol file should already be absolute path and validated
        if not protocol_file.exists():
            raise ValidationError(f"Protocol file not found: {protocol_file}")

        # Upload protocol using multipart/form-data format
        if not self._session:
            raise HardwareError("HTTP session not initialized", robot_id=self.robot_id)

        url = f"{self.base_url}/protocols"

        try:
            # Read the protocol file content
            with open(protocol_file, "r") as file_handle:
                protocol_content = file_handle.read()

            # Inject runtime.json values into protocol constants
            # This embeds user-configurable values (from runtime.json) directly into the protocol code
            # Required because OT2 runTimeParameterValues only supports scalar types, not arrays
            protocol_content = self._inject_runtime_values(protocol_content)

            # Add timestamp to protocol content
            import time

            timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
            protocol_content = f"# Generated at: {timestamp}\n{protocol_content}"

            # CRITICAL: Create JSON metadata structure exactly like working robot manager
            # This is what enables proper hardware recognition during protocol analysis
            protocol_data = {
                "labwareDefinitions": {},
                "pipetteDefinitions": {},
                "designerApplication": {
                    "name": "opentrons/protocol-designer",
                    "version": "5.1.0",
                },
                "metadata": {
                    "protocolName": protocol_config.protocol_name,
                    "author": "System",
                    "description": "Generated protocol for hardware recognition",
                    # Note: apiLevel removed to avoid conflict with Python protocol file's apiLevel
                    # OT2 API rule: "You may only put apiLevel in the metadata dict or the requirements dict, not both"
                    # The Python protocol file (ot2Protocole.py) already contains apiLevel in its metadata
                },
                "defaultValues": {"forecastLabwareReagents": False},
                "parameters": protocol_config.parameters or {},
                "commands": [],
            }

            # Convert JSON metadata to string
            protocol_json_str = json.dumps(protocol_data)

            # CRITICAL: Upload using correct Opentrons API format
            # Field name must be "files" per actual Opentrons robot-server API (v7.x)
            # Note: Old docs say "protocolFile" but modern OT-2 firmware expects "files"
            data = aiohttp.FormData()

            # Add Python protocol file - using "files" per actual robot-server source code
            data.add_field(
                "files",
                protocol_content.encode("utf-8"),
                filename=protocol_file.name,
                content_type="text/x-python",
            )

            headers = {"Opentrons-Version": "2"}

            self.logger.info(
                f"Uploading protocol: {protocol_file.name}"
            )
            self.logger.info(
                f"Protocol parameters: {json.dumps(protocol_config.parameters or {}, indent=2)}"
            )

            async with self._session.post(
                url,
                data=data,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=60.0),
            ) as response:
                if response.status >= 400:
                    error_text = await response.text()
                    self.logger.error(
                        f"Protocol upload failed: {response.status} - {error_text}"
                    )
                    raise HardwareError(
                        f"OT2 API error: {response.status} - {error_text}",
                        robot_id=self.robot_id,
                    )

                response_data = await response.json()
                protocol_id = response_data["data"]["id"]

                self.logger.info(
                    f"Protocol uploaded successfully: {protocol_id}"
                )
                return protocol_id

        except aiohttp.ClientError as e:
            self.logger.error(f"Protocol upload connection error: {e}")
            raise HardwareError(f"OT2 connection error: {e}", robot_id=self.robot_id)

    async def _wait_for_analysis_completion(self, protocol_id: str) -> bool:
        """Wait for protocol analysis to complete - ported from working legacy code

        Args:
            protocol_id: The ID of the protocol to check

        Returns:
            bool: True if analysis completed successfully, False otherwise
        """
        max_attempts = 15  # Try for up to 30 seconds (15 * 2)
        for attempt in range(max_attempts):
            try:
                response = await self._api_request("GET", f"/protocols/{protocol_id}")
                data = response.get("data", {})
                analysis_summaries = data.get("analysisSummaries", [])

                if analysis_summaries:
                    status = analysis_summaries[0].get("status", "")
                    self.logger.info(f"Protocol analysis status: {status}")

                    # Check for various status possibilities
                    if status in ["succeeded", "success"]:
                        self.logger.info("Protocol analysis succeeded")
                        return True
                    elif status in ["failed", "error"]:
                        self.logger.error("Protocol analysis failed")
                        # Fetch and log detailed analysis errors
                        if "errors" in analysis_summaries[0]:
                            self.logger.error(
                                f"Analysis errors: {json.dumps(analysis_summaries[0]['errors'], indent=2)}"
                            )
                        return False
                    elif status == "completed":
                        # The OT2 API uses "completed" as the final state
                        # Now check if there's a valid analysis result in the response
                        if (
                            "errors" in analysis_summaries[0]
                            and analysis_summaries[0]["errors"]
                        ):
                            self.logger.error(
                                f"Protocol analysis completed with errors: {analysis_summaries[0]['errors']}"
                            )
                            return False

                        # Additional check: if the protocol is valid, it will have analyzedAt field
                        if "analyzedAt" in data:
                            self.logger.info("Protocol analysis completed successfully")
                            return True

                        # If we've seen "completed" status multiple times, assume it's done
                        if attempt >= 2:  # Seen "completed" at least 3 times
                            self.logger.info(
                                "Protocol analysis appears complete after multiple checks"
                            )
                            return True
                else:
                    self.logger.warning(
                        f"No analysis summaries found for protocol {protocol_id}"
                    )

            except Exception as e:
                self.logger.error(f"Error checking analysis status: {e}")

            await asyncio.sleep(2)  # Wait 2 seconds before checking again

        # If we've been polling for a while and keep seeing "completed", assume it's ready
        self.logger.info(
            "Timed out waiting for analysis status change - proceeding with run creation"
        )
        return True  # Proceed anyway after max attempts

    async def _create_run(self, protocol_id: str, parameters: Dict[str, Any]) -> str:
        """Create a new protocol run

        Uses correct OT2 API format per OpenAPI spec at /openapi.json:
        {"data": {"protocolId": "..."}}

        Note: Runtime parameters are NOT passed here because:
        1. OT2 runTimeParameterValues only supports scalar types (int, float, bool, str)
        2. Our config includes arrays (sds_lct, generators_locations) which are not supported
        3. All values are embedded directly in the protocol file via _inject_runtime_values()

        Previous format with "type": "Run" and "attributes" wrapper was incorrect
        and caused runs to be created without protocol link (0 commands executed).
        """
        data = {"data": {"protocolId": protocol_id}}

        # Note: Don't pass parameters to runTimeParameterValues - they are embedded in protocol file
        # OT2 API only supports scalar types for runtime parameters, not arrays
        self.logger.info(f"Creating run for protocol {protocol_id} (parameters embedded in protocol file)")

        try:
            response = await self._api_request("POST", "/runs", data)
            run_id = response["data"]["id"]

            self.logger.info(
                f"Run created successfully: {run_id} for protocol: {protocol_id}"
            )
            return run_id
        except Exception as e:
            self.logger.error(f"Failed to create run for protocol {protocol_id}: {e}")
            raise

    async def _start_run(self, run_id: str) -> RunStatus:
        """Start protocol execution"""
        data = {"data": {"actionType": "play"}}

        await self._api_request("POST", f"/runs/{run_id}/actions", data)

        # Get initial run status
        run_data = await self._api_request("GET", f"/runs/{run_id}")
        attrs = self._parse_run_response(run_data)

        status = RunStatus(
            run_id=run_id,
            protocol_id=attrs.get("protocolId", "unknown"),
            status=ProtocolStatus(attrs.get("status", "unknown")),
            start_time=time.time(),
        )

        self.logger.info(f"Run started: {run_id}")
        return status

    async def _stop_run(self, run_id: str) -> bool:
        """Stop protocol execution"""
        try:
            data = {"data": {"actionType": "stop"}}

            await self._api_request("POST", f"/runs/{run_id}/actions", data)

            self.logger.info(f"Run stopped: {run_id}")
            return True

        except Exception as e:
            self.logger.error(f"Failed to stop run {run_id}: {e}")
            return False

    async def _pause_run(self, run_id: str) -> bool:
        """Pause protocol execution via OT2 API"""
        try:
            data = {"data": {"actionType": "pause"}}

            await self._api_request("POST", f"/runs/{run_id}/actions", data)

            self.logger.info(f"Run paused: {run_id}")
            return True

        except Exception as e:
            self.logger.error(f"Failed to pause run {run_id}: {e}")
            return False

    async def _resume_run(self, run_id: str) -> bool:
        """Resume paused protocol execution via OT2 API"""
        try:
            data = {"data": {"actionType": "play"}}

            await self._api_request("POST", f"/runs/{run_id}/actions", data)

            self.logger.info(f"Run resumed: {run_id}")
            return True

        except Exception as e:
            self.logger.error(f"Failed to resume run {run_id}: {e}")
            return False

    async def get_active_run_id(self) -> Optional[str]:
        """
        Get the ID of any active (running or paused) run.

        Uses resilient discovery:
        1. First check self._current_run if it's valid and active
        2. Fallback: Query /runs API for any running/paused runs

        This handles state desync situations where _current_run may be None
        but a run is still active on the OT2.

        Returns:
            run_id if an active run is found, None otherwise
        """
        # Step 1: Check tracked run first
        if self._current_run:
            if self._current_run.status in [ProtocolStatus.RUNNING, ProtocolStatus.PAUSED]:
                self.logger.debug(f"Found active run from tracking: {self._current_run.run_id}")
                return self._current_run.run_id

        # Step 2: Fallback - query OT2 API for any running/paused runs
        try:
            runs_data = await self._get_current_runs()
            data_list = runs_data.get("data", [])

            if isinstance(data_list, list):
                for run in data_list:
                    status = self._extract_run_status(run)
                    if status in ["running", "paused"]:
                        run_id = run.get("id")
                        if run_id:
                            self.logger.info(f"Found active run via API query: {run_id} (status: {status})")
                            return run_id
        except Exception as e:
            self.logger.warning(f"Could not query runs API: {e}")

        self.logger.debug("No active run found")
        return None

    async def pause_current_run(self) -> ServiceResult[bool]:
        """
        Pause the currently running protocol.

        Uses resilient run discovery to find active runs even if
        internal state has become desynced.

        Returns:
            ServiceResult with success=True if paused, error otherwise
        """
        try:
            # Use resilient run discovery
            run_id = await self.get_active_run_id()

            if not run_id:
                return ServiceResult.error_result(
                    "No active run to pause", error_code="NO_ACTIVE_RUN"
                )

            # Check if already paused
            if self._current_run and self._current_run.status == ProtocolStatus.PAUSED:
                return ServiceResult.error_result(
                    "Run is already paused", error_code="ALREADY_PAUSED"
                )

            # Call OT2 API to pause
            success = await self._pause_run(run_id)

            if success:
                # Update internal state
                if self._current_run:
                    self._current_run.status = ProtocolStatus.PAUSED

                self.logger.info(f"Successfully paused run: {run_id}")
                return ServiceResult.success_result(True)
            else:
                return ServiceResult.error_result(
                    f"Failed to pause run {run_id}", error_code="PAUSE_FAILED"
                )

        except Exception as e:
            self.logger.error(f"Error pausing run: {e}")
            return ServiceResult.error_result(f"Pause failed: {e}")

    async def resume_current_run(self) -> ServiceResult[bool]:
        """
        Resume a paused protocol.

        Uses resilient run discovery to find paused runs even if
        internal state has become desynced.

        Returns:
            ServiceResult with success=True if resumed, error otherwise
        """
        try:
            # Use resilient run discovery
            run_id = await self.get_active_run_id()

            if not run_id:
                return ServiceResult.error_result(
                    "No paused run to resume", error_code="NO_PAUSED_RUN"
                )

            # Call OT2 API to resume
            success = await self._resume_run(run_id)

            if success:
                # Update internal state
                if self._current_run:
                    self._current_run.status = ProtocolStatus.RUNNING

                self.logger.info(f"Successfully resumed run: {run_id}")
                return ServiceResult.success_result(True)
            else:
                return ServiceResult.error_result(
                    f"Failed to resume run {run_id}", error_code="RESUME_FAILED"
                )

        except Exception as e:
            self.logger.error(f"Error resuming run: {e}")
            return ServiceResult.error_result(f"Resume failed: {e}")

    # -------------------------------------------------------------------------
    # Phase 2 & 4: Quick Recovery and Position Tracking Methods
    # -------------------------------------------------------------------------

    async def quick_recovery(self) -> ServiceResult[Dict[str, Any]]:
        """
        Resume from paused state using existing pause/resume API.

        This is a convenience wrapper around resume_current_run() that provides
        consistent interface with MecaService's quick_recovery.

        Returns:
            ServiceResult with recovery status
        """
        self.logger.info(f"Quick recovery requested for {self.robot_id}")

        # Check current step state
        step_state = await self.state_manager.get_step_state(self.robot_id)

        # Resume using existing method
        result = await self.resume_current_run()

        if result.success:
            # Resume step tracking if paused
            if step_state and step_state.paused:
                await self.state_manager.resume_step(self.robot_id)

            return ServiceResult.success_result({
                "robot_id": self.robot_id,
                "recovery_type": "quick",
                "resumed_step": {
                    "index": step_state.step_index if step_state else None,
                    "name": step_state.step_name if step_state else None,
                    "operation_type": step_state.operation_type if step_state else None
                } if step_state else None,
                "message": "OT2 protocol resumed successfully"
            })
        else:
            return ServiceResult.error_result(
                f"Quick recovery failed: {result.error}",
                error_code="QUICK_RECOVERY_FAILED"
            )

    async def _record_position(self, context: str = "") -> None:
        """
        Record current pipette position to history for reverse path homing.

        Args:
            context: Optional context string describing the movement
        """
        try:
            pos = await self._get_pipette_position()
            if pos:
                self._position_history.append({
                    "x": pos.get("x", 0),
                    "y": pos.get("y", 0),
                    "z": pos.get("z", 0),
                    "timestamp": time.time(),
                    "context": context
                })

                # Limit history size
                if len(self._position_history) > self._max_position_history:
                    self._position_history.pop(0)

                self.logger.debug(
                    f"Recorded position: ({pos.get('x')}, {pos.get('y')}, {pos.get('z')}) - {context}"
                )
        except Exception as e:
            self.logger.warning(f"Could not record position: {e}")

    async def _get_pipette_position(self) -> Optional[Dict[str, float]]:
        """
        Get current pipette position from OT2 API.

        Returns:
            Dict with x, y, z coordinates or None if unavailable
        """
        try:
            async with self._get_session() as session:
                url = f"{self.base_url}/robot/positions"
                headers = {"Opentrons-Version": "2"}

                async with session.get(url, headers=headers, timeout=10) as response:
                    if response.status == 200:
                        data = await response.json()
                        # Extract position from response
                        positions = data.get("positions", {})
                        # Return first pipette position found
                        for mount in ["left", "right"]:
                            if mount in positions:
                                return positions[mount]
                        return None
        except Exception as e:
            self.logger.debug(f"Could not get pipette position: {e}")
            return None

    async def _move_pipette(
        self, x: float, y: float, z: float, speed: float = 50.0
    ) -> bool:
        """
        Move pipette to specified coordinates.

        Args:
            x, y, z: Target coordinates
            speed: Movement speed (percentage)

        Returns:
            True if successful, False otherwise
        """
        try:
            async with self._get_session() as session:
                url = f"{self.base_url}/robot/move"
                headers = {"Opentrons-Version": "2", "Content-Type": "application/json"}
                payload = {
                    "target": "pipette",
                    "point": [x, y, z],
                    "speed": speed
                }

                async with session.post(
                    url, headers=headers, json=payload, timeout=30
                ) as response:
                    return response.status == 200

        except Exception as e:
            self.logger.error(f"Error moving pipette: {e}")
            return False

    async def safe_home_reverse_path(self) -> ServiceResult[Dict[str, Any]]:
        """
        Home by retracing path in reverse (shield-safe).

        This method reverses through the recorded position history, ensuring
        the pipette doesn't collide with any obstacles (like the shield).
        Z-up movements are prioritized for safety.

        Returns:
            ServiceResult with homing status
        """
        self.logger.info(f"Starting reverse path homing for {self.robot_id}")

        if not self._position_history:
            self.logger.info("No position history - using normal homing")
            result = await self._home_robot()
            if result:
                # Clear emergency stop flag and update state to IDLE
                self._was_emergency_stopped = False
                await self.update_robot_state(
                    RobotState.IDLE,
                    reason="Recovery completed - normal homing successful"
                )
                self.logger.info("Emergency stop cleared - OT2 state set to IDLE after normal homing")
            return ServiceResult.success_result({
                "robot_id": self.robot_id,
                "method": "normal_home",
                "positions_retraced": 0,
                "homed": result,
                "message": "No position history - homed normally"
            })

        positions_retraced = 0
        try:
            # Reverse through positions
            for pos in reversed(self._position_history):
                # Get current position
                current = await self._get_pipette_position()

                if current:
                    # Z-up first for safety (if needed)
                    if current.get("z", 0) < pos["z"]:
                        self.logger.debug(f"Z-up to {pos['z']}")
                        await self._move_pipette(
                            current.get("x", 0),
                            current.get("y", 0),
                            pos["z"],
                            speed=30.0  # Slow for safety
                        )
                        await asyncio.sleep(0.5)

                # Move to recorded position
                self.logger.debug(f"Moving to ({pos['x']}, {pos['y']}, {pos['z']})")
                success = await self._move_pipette(
                    pos["x"], pos["y"], pos["z"], speed=30.0
                )

                if success:
                    positions_retraced += 1
                else:
                    self.logger.warning(
                        f"Failed to move to position: ({pos['x']}, {pos['y']}, {pos['z']})"
                    )
                    break

                await asyncio.sleep(0.3)  # Brief pause between moves

            # Clear history after successful retrace
            self._position_history.clear()

            # Home robot
            home_result = await self._home_robot()

            if home_result:
                # Clear emergency stop flag and update state to IDLE
                # This allows the RecoveryPanel to auto-close
                self._was_emergency_stopped = False
                await self.update_robot_state(
                    RobotState.IDLE,
                    reason="Recovery completed - reverse path homing successful"
                )
                self.logger.info("Emergency stop cleared - OT2 state set to IDLE after reverse path homing")

            return ServiceResult.success_result({
                "robot_id": self.robot_id,
                "method": "reverse_path",
                "positions_retraced": positions_retraced,
                "homed": home_result,
                "message": f"Retraced {positions_retraced} positions and homed"
            })

        except Exception as e:
            self.logger.error(f"Error during reverse path homing: {e}")
            return ServiceResult.error_result(
                f"Reverse path homing failed: {e}",
                error_code="REVERSE_HOME_FAILED"
            )

    async def _home_robot(self) -> bool:
        """
        Home the OT2 robot using API.

        Returns:
            True if homing successful
        """
        try:
            async with self._get_session() as session:
                url = f"{self.base_url}/robot/home"
                headers = {"Opentrons-Version": "2", "Content-Type": "application/json"}

                async with session.post(url, headers=headers, timeout=60) as response:
                    if response.status == 200:
                        self.logger.info("OT2 homing completed")
                        return True
                    else:
                        self.logger.error(f"Homing failed with status {response.status}")
                        return False

        except Exception as e:
            self.logger.error(f"Error homing robot: {e}")
            return False

    def get_position_history_count(self) -> int:
        """Get the number of positions recorded in history."""
        return len(self._position_history)

    def clear_position_history(self) -> None:
        """Clear the position history."""
        self._position_history.clear()
        self.logger.info("Position history cleared")

    async def _handle_idle_timeout(
        self, run_id: str, idle_duration: float
    ) -> Optional[RunStatus]:
        """Handle protocol stuck in idle state, returning failed status if timeout exceeded."""
        if not self._current_run:
            return None

        try:
            pipettes_data = await self._get_attached_pipettes()
            hardware_info = pipettes_data.get("data", {})
        except Exception:
            hardware_info = {}

        self._current_run.status = ProtocolStatus.FAILED
        self._current_run.error_message = self._generate_idle_timeout_message(
            run_id, idle_duration, hardware_info
        )
        self._current_run.end_time = time.time()

        final_status = self._current_run
        self._current_run = None
        return final_status

    def _has_play_action(self, actions: List[Dict[str, Any]]) -> bool:
        """Check if play action exists in actions list."""
        return any(action.get("actionType") == "play" for action in actions)

    async def _monitor_run_progress(self, run_id: str) -> RunStatus:
        """Monitor protocol execution progress"""
        idle_start_time = time.time()
        idle_warning_logged = False
        IDLE_WARNING_THRESHOLD = 30.0
        IDLE_TIMEOUT_THRESHOLD = 120.0

        while True:
            try:
                await asyncio.sleep(0.5)

                run_data = await self._api_request("GET", f"/runs/{run_id}")
                attrs = self._parse_run_response(run_data)
                status = ProtocolStatus(attrs.get("status", "unknown"))
                actions = attrs.get("actions", [])

                # Check for stuck in idle state after play command
                if self._has_play_action(actions) and status == ProtocolStatus.IDLE:
                    idle_duration = time.time() - idle_start_time

                    if idle_duration > IDLE_WARNING_THRESHOLD and not idle_warning_logged:
                        self.logger.warning(
                            f"Protocol {run_id} idle for {idle_duration:.1f}s - possible hardware issue"
                        )
                        idle_warning_logged = True

                    if idle_duration > IDLE_TIMEOUT_THRESHOLD:
                        return await self._handle_idle_timeout(run_id, idle_duration)
                elif status != ProtocolStatus.IDLE:
                    idle_start_time = time.time()
                    idle_warning_logged = False

                # Update current run status
                if self._current_run:
                    self._current_run.status = status
                    self._current_run.current_command = attrs.get("currentCommand")

                    if attrs.get("completedAt"):
                        self._current_run.progress_percent = 100.0
                        self._current_run.end_time = time.time()

                    # Check for terminal states
                    terminal_states = {ProtocolStatus.SUCCEEDED, ProtocolStatus.FAILED, ProtocolStatus.STOPPED}
                    if status in terminal_states:
                        self._current_run.end_time = time.time()

                        if status == ProtocolStatus.FAILED:
                            errors = attrs.get("errors", [])
                            self._current_run.error_message = (
                                errors[0].get("detail", "Unknown error")
                                if errors else "Protocol failed - no error details available"
                            )

                        final_status = self._current_run
                        self._current_run = None
                        return final_status

            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(f"Error monitoring run {run_id}: {e}")
                await asyncio.sleep(1.0)

    async def _get_health_status(self) -> Dict[str, Any]:
        """Get OT2 health status"""
        return await self._api_request("GET", "/health")

    async def _get_current_runs(self) -> Dict[str, Any]:
        """Get current runs"""
        return await self._api_request("GET", "/runs")

    async def _get_calibration_data(self) -> Dict[str, Any]:
        """Get calibration data"""
        return await self._api_request("GET", "/calibration/status")

    async def _get_attached_pipettes(self) -> Dict[str, Any]:
        """Get currently attached pipettes"""
        return await self._api_request("GET", "/pipettes")

    async def _get_deck_configuration(self) -> Dict[str, Any]:
        """Get current deck configuration"""
        return await self._api_request("GET", "/deck_configuration")

    async def _build_hardware_info(self) -> Dict[str, Any]:
        """Build hardware info dict with pipettes, calibration, and issues."""
        try:
            pipettes_data = await self._get_attached_pipettes()
            calibration_data = await self._get_calibration_data()

            pipettes = pipettes_data.get("data", {})
            left_pipette = pipettes.get("left")
            right_pipette = pipettes.get("right")

            issues = []
            if not left_pipette and not right_pipette:
                issues.append("No pipettes attached")
            else:
                if left_pipette and not left_pipette.get("ok", False):
                    issues.append(f"Left pipette needs calibration: {left_pipette.get('model', 'unknown')}")
                if right_pipette and not right_pipette.get("ok", False):
                    issues.append(f"Right pipette needs calibration: {right_pipette.get('model', 'unknown')}")

            deck_cal = calibration_data.get("data", {}).get("deckCalibration", {})
            if not deck_cal.get("status", {}).get("markedAt"):
                issues.append("Deck calibration may be required")

            return {
                "pipettes": pipettes,
                "calibration": calibration_data.get("data", {}),
                "hardware_ready": bool(left_pipette or right_pipette),
                "hardware_issues": issues,
            }
        except Exception as e:
            self.logger.warning(f"Could not get hardware status: {e}")
            return {"error": f"Hardware status unavailable: {str(e)}"}

    def _check_pipette_calibration(
        self, pipette: Optional[Dict], mount: str, warnings: List[str]
    ) -> None:
        """Check if a pipette needs calibration and add warning if so."""
        if pipette and not pipette.get("ok", False):
            model = pipette.get("model", "unknown")
            warnings.append(f"{mount} pipette may need calibration: {model}")

    async def _validate_hardware_requirements(self, protocol_id: str) -> Dict[str, Any]:
        """Validate that required hardware is available for protocol execution."""
        result = {
            "valid": True,
            "missing_hardware": [],
            "warnings": [],
            "pipettes": {},
            "labware": [],
            "calibration_status": {},
        }

        try:
            # Check protocol analysis status
            protocol_data = await self._api_request("GET", f"/protocols/{protocol_id}")
            analysis_summaries = protocol_data.get("data", {}).get("analysisSummaries", [])

            if not analysis_summaries or analysis_summaries[0].get("status") != "completed":
                result["valid"] = False
                result["missing_hardware"].append("Protocol analysis not completed")
                return result

            # Get hardware state
            pipettes_data = await self._get_attached_pipettes()
            calibration_data = await self._get_calibration_data()

            result["pipettes"] = pipettes_data
            result["calibration_status"] = calibration_data

            left_pipette = pipettes_data.get("left")
            right_pipette = pipettes_data.get("right")

            # Validate pipettes
            if not left_pipette and not right_pipette:
                self.logger.error("Hardware validation failed: No pipettes detected")
                result["valid"] = False
                result["missing_hardware"].append("No pipettes attached to robot")
            else:
                self._check_pipette_calibration(left_pipette, "Left", result["warnings"])
                self._check_pipette_calibration(right_pipette, "Right", result["warnings"])

            # Check deck calibration
            deck_cal = calibration_data.get("data", {}).get("deckCalibration", {})
            if not deck_cal.get("status", {}).get("markedAt"):
                result["warnings"].append("Deck calibration may be required")

            # Log summary
            status = "PASSED" if result["valid"] else "FAILED"
            self.logger.info(f"Hardware validation for protocol {protocol_id}: {status}")

            if result["missing_hardware"]:
                self.logger.warning(f"Missing hardware: {result['missing_hardware']}")
            if result["warnings"]:
                self.logger.warning(f"Hardware warnings: {result['warnings']}")

        except Exception as e:
            self.logger.error(f"Hardware validation failed: {e}")
            result["valid"] = False
            result["missing_hardware"].append(f"Validation error: {str(e)}")

        return result

    def _generate_hardware_error_message(
        self, validation_result: Dict[str, Any]
    ) -> str:
        """
        Generate user-friendly error message with actionable suggestions.

        Args:
            validation_result: Result from _validate_hardware_requirements

        Returns:
            Formatted error message with troubleshooting steps
        """
        missing_items = validation_result.get("missing_hardware", [])
        warnings = validation_result.get("warnings", [])

        error_parts = [
            "[ERROR] Hardware Validation Failed",
            "",
            "The OT2 robot cannot execute this protocol due to missing or unconfigured hardware:",
            "",
        ]

        # Add specific missing items
        for item in missing_items:
            error_parts.append(f"  • {item}")

        if warnings:
            error_parts.extend(["", "[WARNING]  Additional Warnings:"])
            for warning in warnings:
                error_parts.append(f"  • {warning}")

        # Add troubleshooting steps
        error_parts.extend(
            [
                "",
                "[EXEC] Troubleshooting Steps:",
                "",
                "1. Check Physical Hardware:",
                "   • Ensure pipettes are physically attached to the robot",
                "   • Verify tip racks are loaded in the correct deck positions",
                "   • Check that all labware is properly seated",
                "",
                "2. Calibrate Hardware:",
                "   • Access the OT2 touchscreen or web interface",
                "   • Run 'Calibrate Pipettes' if pipettes are attached but not calibrated",
                "   • Run 'Calibrate Deck' if deck calibration is needed",
                "",
                "3. Verify Protocol Requirements:",
                "   • Check the protocol to see what pipettes and labware it expects",
                "   • Ensure the correct pipette models are attached",
                "   • Load the required labware in the specified positions",
                "",
                "4. Test Manually:",
                "   • Try running the protocol directly from the OT2 interface",
                "   • This will show specific error messages about missing hardware",
                "",
                f"[NETWORK] Robot Interface: http://{self.ot2_config['ip']}:{self.ot2_config['port']}",
                "",
                "After resolving hardware issues, try running the protocol again.",
            ]
        )

        return "\n".join(error_parts)

    def _generate_idle_timeout_message(
        self, run_id: str, duration: float, hardware_info: Dict[str, Any]
    ) -> str:
        """
        Generate detailed error message for protocols stuck in idle state.

        Args:
            run_id: The run ID that timed out
            duration: How long it was stuck in idle
            hardware_info: Current hardware status information

        Returns:
            Detailed error message with diagnostic information
        """
        error_parts = [
            f"[TIMEOUT]  Protocol Execution Timeout (Run ID: {run_id})",
            "",
            f"The protocol remained in 'idle' state for {duration:.1f} seconds after receiving the 'play' command.",
            "This typically indicates a hardware setup issue preventing execution.",
            "",
            "[DEBUG] Diagnostic Information:",
            "",
        ]

        # Add pipette status
        left_pip = hardware_info.get("left")
        right_pip = hardware_info.get("right")

        if not left_pip and not right_pip:
            error_parts.extend(
                [
                    "[ERROR] No pipettes detected",
                    "   → The robot has no pipettes attached or they are not recognized",
                    "   → Attach pipettes and run calibration through the OT2 interface",
                    "",
                ]
            )
        else:
            error_parts.append("[OK] Pipettes detected:")
            if left_pip:
                status = (
                    "[OK] OK" if left_pip.get("ok", False) else "[WARNING]  Needs calibration"
                )
                error_parts.append(
                    f"   • Left: {left_pip.get('model', 'Unknown')} - {status}"
                )
            if right_pip:
                status = (
                    "[OK] OK" if right_pip.get("ok", False) else "[WARNING]  Needs calibration"
                )
                error_parts.append(
                    f"   • Right: {right_pip.get('model', 'Unknown')} - {status}"
                )
            error_parts.append("")

        # Add common solutions
        error_parts.extend(
            [
                "[EXEC] Common Solutions:",
                "",
                "1. Hardware Issues:",
                "   • Check that pipettes are properly seated and recognized",
                "   • Ensure tip racks are loaded and in the correct positions",
                "   • Verify all required labware is present and properly placed",
                "",
                "2. Calibration Issues:",
                "   • Run pipette calibration if pipettes need calibration",
                "   • Run deck calibration if prompted",
                "   • Check tip pickup and drop locations",
                "",
                "3. Protocol Issues:",
                "   • The protocol may have errors preventing execution",
                "   • Try running a simple test protocol to verify hardware",
                "   • Check the OT2 logs for specific error messages",
                "",
                f"[NETWORK] Robot Interface: http://{self.ot2_config['ip']}:{self.ot2_config['port']}",
                "",
                "Check the robot's interface for specific error messages and hardware status.",
            ]
        )

        return "\n".join(error_parts)

    async def _are_motors_engaged(self) -> bool:
        """Check if robot motors are engaged (indicating robot is homed).

        Opentrons default post_run_hardware_state is HOME_AND_STAY_ENGAGED,
        meaning after a successful run, the robot homes AND keeps motors engaged.
        If motors are engaged, robot is at a known position (likely home).
        If motors are disengaged, robot MUST be homed.
        """
        try:
            response = await self._api_request("GET", "/motors/engaged")
            # Check if all gantry axes are engaged
            # OT2 API returns: x, y, z_l (left Z), z_r (right Z), p_l/p_r (pipettes)
            required_axes = ['x', 'y', 'z_l', 'z_r']  # Gantry axes only
            for axis in required_axes:
                if not response.get(axis, {}).get('enabled', False):
                    self.logger.debug(f"Motor axis '{axis}' is not engaged")
                    return False
            self.logger.debug("All gantry motor axes are engaged")
            return True
        except Exception as e:
            self.logger.warning(f"Failed to check motor status: {e}")
            return False  # Assume not homed if check fails

    async def _home_robot(self) -> bool:
        """Home the robot"""
        try:
            data = {"target": "robot"}
            await self._api_request("POST", "/robot/home", data)
            return True
        except Exception as e:
            self.logger.error(f"Failed to home robot: {e}")
            return False

    def _extract_protocol_id(self, run: Dict[str, Any]) -> str:
        """Extract protocol ID from run dict handling various API formats."""
        if "attributes" in run and isinstance(run["attributes"], dict):
            return run["attributes"].get("protocolId", "unknown")
        return run.get("protocolId") or run.get("protocol_id") or "unknown"

    async def _check_for_active_runs(self):
        """Check for any active runs on startup"""
        try:
            runs_data = await self._get_current_runs()
            data_list = runs_data.get("data", [])

            if not isinstance(data_list, list):
                return

            # Find first running run
            for run in data_list:
                if self._extract_run_status(run) == "running":
                    self._current_run = RunStatus(
                        run_id=run.get("id", "unknown"),
                        protocol_id=self._extract_protocol_id(run),
                        status=ProtocolStatus.RUNNING,
                        start_time=time.time(),
                    )
                    self._monitoring_task = asyncio.create_task(
                        self._monitor_run_progress(self._current_run.run_id)
                    )
                    self.logger.info(f"Found active run: {self._current_run.run_id}")
                    break

        except Exception as e:
            self.logger.error(f"Failed to check for active runs: {e}")

    def _create_liquid_handling_protocol(self, params: LiquidHandlingParams) -> str:
        """Create a simple liquid handling protocol"""
        protocol = f"""
from opentrons import protocol_api

metadata = {{
    'protocolName': 'Liquid Handling Operation',
    'author': 'Windsurf Robotics System',
    'description': 'Automated liquid handling',
    'apiLevel': '2.13'
}}

def run(protocol: protocol_api.ProtocolContext):
    # Load labware
    source_labware = protocol.load_labware('{params.source_labware}', 1)
    dest_labware = protocol.load_labware('{params.dest_labware}', 2)
    
    # Load pipette
    pipette = protocol.load_instrument('{params.pipette_name}', 'right')
    
    # Load tips
    tip_rack = protocol.load_labware('opentrons_96_tiprack_300ul', 3)
    
    # Perform liquid transfer
    pipette.pick_up_tip(tip_rack['A1'])
    pipette.aspirate({params.volume}, source_labware['{params.source_well}'])
    pipette.dispense({params.volume}, dest_labware['{params.dest_well}'])
    pipette.drop_tip()
"""
        return protocol
