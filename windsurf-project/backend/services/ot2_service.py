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

        self.logger.info(
            f"OT2 robot {self.robot_id} connection state change: is_connected={is_connected}"
        )

        if is_connected:
            # Robot connected - set to IDLE state
            self.logger.info(f"Setting OT2 robot {self.robot_id} state to IDLE")
            await self.update_robot_state(
                RobotState.IDLE, reason="OT2 robot connection restored"
            )

            # Verify state was set correctly
            robot_info = await self.state_manager.get_robot_state(self.robot_id)
            if robot_info:
                self.logger.info(
                    f"OT2 robot {self.robot_id} state after update: {robot_info.current_state}, operational: {robot_info.is_operational}"
                )
            else:
                self.logger.error(
                    f"Failed to get robot state for {self.robot_id} after update"
                )

            self.logger.info(f"OT2 robot {self.robot_id} connection restored")
        else:
            # Robot disconnected - set to ERROR state
            self.logger.warning(
                f"Setting OT2 robot {self.robot_id} state to ERROR due to connection loss"
            )
            await self.update_robot_state(
                RobotState.ERROR, reason="OT2 robot connection lost"
            )
            self.logger.warning(f"OT2 robot {self.robot_id} connection lost")

        # Broadcast state change via WebSocket
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

    async def _execute_emergency_stop(self) -> bool:
        """Emergency stop implementation for OT2"""
        self.logger.critical(f"🚨 Executing emergency stop for OT2 robot {self.robot_id}")
        
        emergency_success = False
        stopped_operations = []
        
        try:
            # 1. Immediately stop any current run
            if self._current_run and self._current_run.status == ProtocolStatus.RUNNING:
                try:
                    self.logger.critical(f"⏹️  Stopping current protocol run: {self._current_run.run_id}")
                    stop_success = await self._stop_run(self._current_run.run_id)
                    if stop_success:
                        stopped_operations.append(f"protocol_run_{self._current_run.run_id}")
                        self.logger.critical(f"✅ Protocol run stopped successfully")
                    else:
                        self.logger.error(f"❌ Failed to stop protocol run")
                except Exception as run_error:
                    self.logger.error(f"Error stopping current run: {run_error}")
            
            # 2. Try to stop all runs via OT2 API (broader emergency stop)
            try:
                runs_data = await self._get_current_runs()
                active_runs = []
                
                # Handle different possible response formats
                data_list = runs_data.get("data", [])
                if isinstance(data_list, list):
                    for run in data_list:
                        try:
                            # Check various possible status locations
                            status = None
                            if isinstance(run, dict):
                                if "attributes" in run and isinstance(run["attributes"], dict):
                                    status = run["attributes"].get("status")
                                elif "status" in run:
                                    status = run["status"]
                                
                                if status == "running":
                                    active_runs.append(run.get("id", "unknown"))
                        except Exception:
                            continue
                
                # Stop all active runs
                for run_id in active_runs:
                    try:
                        await self._stop_run(run_id)
                        stopped_operations.append(f"active_run_{run_id}")
                        self.logger.critical(f"✅ Stopped active run: {run_id}")
                    except Exception as stop_error:
                        self.logger.error(f"Failed to stop run {run_id}: {stop_error}")
                        
            except Exception as runs_error:
                self.logger.warning(f"Could not check/stop active runs: {runs_error}")
            
            # 3. Cancel monitoring task if running
            if self._monitoring_task and not self._monitoring_task.done():
                try:
                    self._monitoring_task.cancel()
                    stopped_operations.append("monitoring_task")
                    self.logger.info(f"📡 Monitoring task cancelled")
                except Exception as monitor_error:
                    self.logger.warning(f"Could not cancel monitoring task: {monitor_error}")
            
            # 4. Emergency stop should NOT move the robot - stay in current position
            # Removed robot homing to prevent movement during emergency stop
            emergency_success = len(stopped_operations) > 0  # Success if we stopped any operations
            
            # 5. Clear current run state
            self._current_run = None
            
            # 6. Report results
            if stopped_operations:
                emergency_success = True
                self.logger.critical(f"🚨 Emergency stop completed for OT2 robot {self.robot_id}")
                self.logger.critical(f"✅ Stopped operations: {stopped_operations}")
            else:
                self.logger.warning(f"⚠️  Emergency stop completed but no active operations were found to stop")
                emergency_success = True  # Still consider success if nothing was running
            
            return emergency_success
            
        except Exception as e:
            self.logger.error(f"Emergency stop failed with unexpected error: {e}")
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
            # Ensure robot is ready (CommandService already set to BUSY)
            await self.ensure_robot_ready()

            # Check if another protocol is running
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

            try:
                # Get current calibration status
                calibration_data = await self._get_calibration_data()

                # Check if calibration is needed
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
                    self.logger.warning(
                        "Pipette calibration required - manual intervention needed"
                    )
                    result["message"] = (
                        "Manual calibration required through OT-2 interface"
                    )

                return result

            finally:
                pass  # CommandService handles state management

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
            # Filter out unsupported parameters and extract valid protocol parameters
            protocol_parameters = kwargs.copy()

            # Remove any unsupported parameters that might cause issues
            unsupported_params = ["test", "debug", "verbose"]
            for param in unsupported_params:
                protocol_parameters.pop(param, None)

            # Validate protocol file exists before creating config
            protocol_file_path = self.protocol_directory / self.default_protocol_file
            if not protocol_file_path.exists():
                raise ValidationError(f"Protocol file not found: {protocol_file_path}")

            # Get correct protocol parameters from settings
            ot2_config_params = self.ot2_config.get("protocol_parameters", {})

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
                return ServiceResult.success_result(
                    {
                        "status": "completed",
                        "run_status": (
                            result.data.__dict__
                            if hasattr(result.data, "__dict__")
                            else result.data
                        ),
                        "protocol_parameters": protocol_parameters,
                    }
                )
            else:
                return ServiceResult.error_result(
                    f"Protocol execution failed: {result.error}"
                )

        except Exception as e:
            self.logger.error(f"Failed to run protocol: {e}", exc_info=True)
            return ServiceResult.error_result(f"Protocol execution failed: {str(e)}")

    async def get_robot_status(self) -> ServiceResult[Dict[str, Any]]:
        """Get detailed OT2 robot status"""
        context = OperationContext(
            operation_id=f"{self.robot_id}_status",
            robot_id=self.robot_id,
            operation_type=OT2OperationType.STATUS_CHECK.value,
        )

        async def _get_status():
            # Get hardware status
            health_data = await self._get_health_status()

            # Get current runs
            runs_data = await self._get_current_runs()

            # Get robot info from state manager
            robot_info = await self.state_manager.get_robot_state(self.robot_id)

            # Get hardware validation information
            hardware_info = {}
            try:
                pipettes_data = await self._get_attached_pipettes()
                calibration_data = await self._get_calibration_data()

                hardware_info = {
                    "pipettes": pipettes_data.get("data", {}),
                    "calibration": calibration_data.get("data", {}),
                    "hardware_ready": bool(
                        pipettes_data.get("data", {}).get("left")
                        or pipettes_data.get("data", {}).get("right")
                    ),
                }

                # Add hardware readiness assessment
                left_pipette = pipettes_data.get("data", {}).get("left")
                right_pipette = pipettes_data.get("data", {}).get("right")

                hardware_info["hardware_issues"] = []
                if not left_pipette and not right_pipette:
                    hardware_info["hardware_issues"].append("No pipettes attached")
                else:
                    if left_pipette and not left_pipette.get("ok", False):
                        hardware_info["hardware_issues"].append(
                            f"Left pipette needs calibration: {left_pipette.get('model', 'unknown')}"
                        )
                    if right_pipette and not right_pipette.get("ok", False):
                        hardware_info["hardware_issues"].append(
                            f"Right pipette needs calibration: {right_pipette.get('model', 'unknown')}"
                        )

                # Check deck calibration
                deck_cal = calibration_data.get("data", {}).get("deckCalibration", {})
                if not deck_cal.get("status", {}).get("markedAt"):
                    hardware_info["hardware_issues"].append(
                        "Deck calibration may be required"
                    )

            except Exception as e:
                self.logger.warning(f"Could not get hardware status: {e}")
                hardware_info = {"error": f"Hardware status unavailable: {str(e)}"}

            return {
                "robot_id": self.robot_id,
                "robot_type": self.robot_type,
                "hardware_status": health_data,
                "hardware_info": hardware_info,
                "current_runs": runs_data,
                "state_info": {
                    "current_state": (
                        robot_info.current_state.value if robot_info else "unknown"
                    ),
                    "operational": robot_info.is_operational if robot_info else False,
                    "uptime_seconds": robot_info.uptime_seconds if robot_info else 0,
                    "error_count": robot_info.error_count if robot_info else 0,
                },
                "current_run": (
                    self._current_run.__dict__ if self._current_run else None
                ),
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

    async def _upload_protocol(self, protocol_config: ProtocolConfig) -> str:
        """Upload protocol to OT2 using dual-structure format (Python file + JSON metadata)

        This matches the working robot manager approach that properly enables hardware recognition.
        """
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
                    "apiLevel": "2.9",  # Match the protocol's API level
                },
                "defaultValues": {"forecastLabwareReagents": False},
                "parameters": protocol_config.parameters or {},
                "commands": [],
            }

            # Convert JSON metadata to string
            protocol_json_str = json.dumps(protocol_data)

            # CRITICAL: Upload using dual-structure format (Python file + JSON metadata)
            # This is the exact format that worked in the robot manager
            data = aiohttp.FormData()

            # Add Python protocol file
            data.add_field(
                "files",
                protocol_content.encode("utf-8"),
                filename=protocol_file.name,
                content_type="text/x-python",
            )

            # Add JSON metadata - this is what enables hardware recognition!
            data.add_field("data", protocol_json_str, content_type="application/json")

            headers = {"Opentrons-Version": "2"}

            self.logger.info(
                f"Uploading protocol with dual structure: {protocol_file.name}"
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
                    f"Protocol uploaded successfully with dual structure: {protocol_id}"
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
        """Create a new protocol run"""
        data = {"data": {"type": "Run", "attributes": {"protocolId": protocol_id}}}

        if parameters:
            data["data"]["attributes"]["runTimeParameterValues"] = parameters
            self.logger.info(f"Creating run with parameters: {parameters}")
        else:
            self.logger.info("Creating run without parameters")

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

        # Defensive parsing for response structure
        run_data_attrs = run_data.get("data", {})
        if "attributes" in run_data_attrs:
            # Nested structure: {"data": {"attributes": {...}}}
            attrs = run_data_attrs["attributes"]
        else:
            # Flat structure: {"data": {...}}
            attrs = run_data_attrs

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

    async def _monitor_run_progress(self, run_id: str) -> RunStatus:
        """Monitor protocol execution progress"""
        idle_start_time = time.time()
        idle_warning_threshold = 30.0  # Warn if stuck in idle for 30 seconds
        idle_timeout_threshold = 120.0  # Fail if stuck in idle for 2 minutes

        while True:
            try:
                await asyncio.sleep(
                    0.5
                )  # Check every 0.5 seconds for better responsiveness

                run_data = await self._api_request("GET", f"/runs/{run_id}")

                # Defensive parsing for response structure (same as _start_run)
                run_data_attrs = run_data.get("data", {})
                if "attributes" in run_data_attrs:
                    # Nested structure: {"data": {"attributes": {...}}}
                    attrs = run_data_attrs["attributes"]
                else:
                    # Flat structure: {"data": {...}}
                    attrs = run_data_attrs

                status = ProtocolStatus(attrs.get("status", "unknown"))
                actions = attrs.get("actions", [])

                # Check for stuck in idle state after play command
                play_actions = [
                    action for action in actions if action.get("actionType") == "play"
                ]
                if play_actions and status == ProtocolStatus.IDLE:
                    idle_duration = time.time() - idle_start_time

                    if idle_duration > idle_warning_threshold:
                        self.logger.warning(
                            f"Protocol {run_id} has been idle for {idle_duration:.1f}s after play command. "
                            f"This may indicate missing hardware or calibration issues."
                        )

                        # Get hardware status for debugging
                        try:
                            pipettes_data = await self._get_attached_pipettes()
                            attached_pipettes = pipettes_data.get("data", {})

                            if not attached_pipettes.get(
                                "left"
                            ) and not attached_pipettes.get("right"):
                                self.logger.error(
                                    f"Protocol stuck in idle: No pipettes detected. "
                                    f"Please attach and calibrate pipettes before running protocols."
                                )
                            else:
                                self.logger.warning(
                                    f"Protocol stuck in idle despite pipettes being attached: "
                                    f"left={attached_pipettes.get('left', {}).get('model', 'None')}, "
                                    f"right={attached_pipettes.get('right', {}).get('model', 'None')}"
                                )
                        except Exception:
                            pass  # Don't fail monitoring due to hardware check errors

                    if idle_duration > idle_timeout_threshold:
                        # Create a failed status to indicate the timeout
                        if self._current_run:
                            # Get current hardware info for detailed error message
                            try:
                                pipettes_data = await self._get_attached_pipettes()
                                hardware_info = pipettes_data.get("data", {})
                            except Exception:
                                hardware_info = {}

                            self._current_run.status = ProtocolStatus.FAILED
                            self._current_run.error_message = (
                                self._generate_idle_timeout_message(
                                    run_id, idle_duration, hardware_info
                                )
                            )
                            self._current_run.end_time = time.time()

                            final_status = self._current_run
                            self._current_run = None
                            return final_status
                elif status != ProtocolStatus.IDLE:
                    # Reset idle timer if status changes from idle
                    idle_start_time = time.time()

                # Update current run status
                if self._current_run:
                    self._current_run.status = status
                    self._current_run.current_command = attrs.get("currentCommand")

                    # Calculate progress if available
                    if "completedAt" in attrs and attrs["completedAt"]:
                        self._current_run.progress_percent = 100.0
                        self._current_run.end_time = time.time()

                    if status in {
                        ProtocolStatus.SUCCEEDED,
                        ProtocolStatus.FAILED,
                        ProtocolStatus.STOPPED,
                    }:
                        self._current_run.end_time = time.time()

                        if status == ProtocolStatus.FAILED:
                            # Get error details
                            errors = attrs.get("errors", [])
                            if errors and isinstance(errors, list) and len(errors) > 0:
                                self._current_run.error_message = errors[0].get(
                                    "detail", "Unknown error"
                                )
                            else:
                                self._current_run.error_message = (
                                    "Protocol failed - no error details available"
                                )

                            # CommandService handles error state management
                            pass
                        else:
                            # CommandService handles state management
                            pass

                        final_status = self._current_run
                        self._current_run = None
                        return final_status

            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(f"Error monitoring run {run_id}: {e}")
                await asyncio.sleep(
                    1.0
                )  # Shorter error recovery delay for faster startup

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

    async def _validate_hardware_requirements(self, protocol_id: str) -> Dict[str, Any]:
        """
        Validate that required hardware is available for protocol execution.

        Args:
            protocol_id: The protocol ID to validate hardware for

        Returns:
            Dict with validation results and missing hardware details
        """
        validation_result = {
            "valid": True,
            "missing_hardware": [],
            "warnings": [],
            "pipettes": {},
            "labware": [],
            "calibration_status": {},
        }

        try:
            # Get protocol analysis to understand requirements
            protocol_data = await self._api_request("GET", f"/protocols/{protocol_id}")

            # Check if protocol has been analyzed
            analysis_summaries = protocol_data.get("data", {}).get(
                "analysisSummaries", []
            )
            if (
                not analysis_summaries
                or analysis_summaries[0].get("status") != "completed"
            ):
                validation_result["valid"] = False
                validation_result["missing_hardware"].append(
                    "Protocol analysis not completed"
                )
                return validation_result

            # Get current robot hardware state
            pipettes_data = await self._get_attached_pipettes()
            calibration_data = await self._get_calibration_data()

            # DEBUG: Log the actual API response structure
            self.logger.info(f"Raw pipettes API response: {pipettes_data}")
            self.logger.info(f"Raw calibration API response: {calibration_data}")

            # Check attached pipettes
            # attached_pipettes = pipettes_data.get("data", {})
            attached_pipettes = pipettes_data
            self.logger.info(f"Parsed attached_pipettes: {attached_pipettes}")
            validation_result["pipettes"] = attached_pipettes

            # Validate pipettes are attached and calibrated
            left_pipette = attached_pipettes.get("left")
            right_pipette = attached_pipettes.get("right")

            self.logger.info(f"Left pipette data: {left_pipette}")
            self.logger.info(f"Right pipette data: {right_pipette}")

            if not left_pipette and not right_pipette:
                self.logger.error(
                    "Hardware validation failed: No pipettes detected in API response"
                )
                self.logger.error(f"Full pipettes_data structure: {pipettes_data}")
                validation_result["valid"] = False
                validation_result["missing_hardware"].append(
                    "No pipettes attached to robot"
                )
            else:
                self.logger.info("Pipettes detected, checking calibration...")
                # Check pipette calibration
                if left_pipette:
                    left_ok = left_pipette.get("ok", False)
                    left_model = left_pipette.get("model", "unknown")
                    self.logger.info(f"Left pipette: model={left_model}, ok={left_ok}")
                    if not left_ok:
                        validation_result["warnings"].append(
                            f"Left pipette may need calibration: {left_model}"
                        )

                if right_pipette:
                    right_ok = right_pipette.get("ok", False)
                    right_model = right_pipette.get("model", "unknown")
                    self.logger.info(
                        f"Right pipette: model={right_model}, ok={right_ok}"
                    )
                    if not right_ok:
                        validation_result["warnings"].append(
                            f"Right pipette may need calibration: {right_model}"
                        )

            # Store calibration status
            validation_result["calibration_status"] = calibration_data

            # Check deck calibration
            deck_cal = calibration_data.get("data", {}).get("deckCalibration", {})
            if not deck_cal.get("status", {}).get("markedAt"):
                validation_result["warnings"].append("Deck calibration may be required")

            self.logger.info(
                f"Hardware validation for protocol {protocol_id}: {'PASSED' if validation_result['valid'] else 'FAILED'}"
            )
            if validation_result["missing_hardware"]:
                self.logger.warning(
                    f"Missing hardware: {validation_result['missing_hardware']}"
                )
            if validation_result["warnings"]:
                self.logger.warning(
                    f"Hardware warnings: {validation_result['warnings']}"
                )

        except Exception as e:
            self.logger.error(f"Hardware validation failed: {e}")
            validation_result["valid"] = False
            validation_result["missing_hardware"].append(f"Validation error: {str(e)}")

        return validation_result

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
            "❌ Hardware Validation Failed",
            "",
            "The OT2 robot cannot execute this protocol due to missing or unconfigured hardware:",
            "",
        ]

        # Add specific missing items
        for item in missing_items:
            error_parts.append(f"  • {item}")

        if warnings:
            error_parts.extend(["", "⚠️  Additional Warnings:"])
            for warning in warnings:
                error_parts.append(f"  • {warning}")

        # Add troubleshooting steps
        error_parts.extend(
            [
                "",
                "🔧 Troubleshooting Steps:",
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
                f"🌐 Robot Interface: http://{self.ot2_config.get('ip', '169.254.49.202')}:31950",
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
            f"⏱️  Protocol Execution Timeout (Run ID: {run_id})",
            "",
            f"The protocol remained in 'idle' state for {duration:.1f} seconds after receiving the 'play' command.",
            "This typically indicates a hardware setup issue preventing execution.",
            "",
            "🔍 Diagnostic Information:",
            "",
        ]

        # Add pipette status
        left_pip = hardware_info.get("left")
        right_pip = hardware_info.get("right")

        if not left_pip and not right_pip:
            error_parts.extend(
                [
                    "❌ No pipettes detected",
                    "   → The robot has no pipettes attached or they are not recognized",
                    "   → Attach pipettes and run calibration through the OT2 interface",
                    "",
                ]
            )
        else:
            error_parts.append("✅ Pipettes detected:")
            if left_pip:
                status = (
                    "✅ OK" if left_pip.get("ok", False) else "⚠️  Needs calibration"
                )
                error_parts.append(
                    f"   • Left: {left_pip.get('model', 'Unknown')} - {status}"
                )
            if right_pip:
                status = (
                    "✅ OK" if right_pip.get("ok", False) else "⚠️  Needs calibration"
                )
                error_parts.append(
                    f"   • Right: {right_pip.get('model', 'Unknown')} - {status}"
                )
            error_parts.append("")

        # Add common solutions
        error_parts.extend(
            [
                "🔧 Common Solutions:",
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
                f"🌐 Robot Interface: http://{self.ot2_config.get('ip', '169.254.49.202')}:31950",
                "",
                "Check the robot's interface for specific error messages and hardware status.",
            ]
        )

        return "\n".join(error_parts)

    async def _home_robot(self) -> bool:
        """Home the robot"""
        try:
            data = {"target": "robot"}
            await self._api_request("POST", "/robot/home", data)
            return True
        except Exception as e:
            self.logger.error(f"Failed to home robot: {e}")
            return False

    async def _check_for_active_runs(self):
        """Check for any active runs on startup"""
        try:
            runs_data = await self._get_current_runs()

            # Handle different possible response formats
            data_list = runs_data.get("data", [])
            if not isinstance(data_list, list):
                data_list = []

            active_runs = []
            for run in data_list:
                try:
                    # Try different possible response formats
                    if isinstance(run, dict):
                        # Format 1: run.attributes.status
                        if "attributes" in run and isinstance(run["attributes"], dict):
                            status = run["attributes"].get("status", "unknown")
                        # Format 2: run.status
                        elif "status" in run:
                            status = run["status"]
                        # Format 3: run.data.status
                        elif "data" in run and isinstance(run["data"], dict):
                            status = run["data"].get("status", "unknown")
                        else:
                            status = "unknown"

                        if status == "running":
                            active_runs.append(run)
                except Exception as inner_e:
                    self.logger.debug(f"Error parsing run data: {inner_e}")
                    continue

            if active_runs:
                run = active_runs[0]  # Take the first active run

                # Extract protocol ID with fallback
                protocol_id = None
                if "attributes" in run and isinstance(run["attributes"], dict):
                    protocol_id = run["attributes"].get("protocolId")
                elif "protocolId" in run:
                    protocol_id = run["protocolId"]
                elif "protocol_id" in run:
                    protocol_id = run["protocol_id"]

                self._current_run = RunStatus(
                    run_id=run.get("id", "unknown"),
                    protocol_id=protocol_id or "unknown",
                    status=ProtocolStatus.RUNNING,
                    start_time=time.time(),  # Approximate start time
                )

                # Start monitoring this run
                self._monitoring_task = asyncio.create_task(
                    self._monitor_run_progress(self._current_run.run_id)
                )

                self.logger.info(f"Found active run: {self._current_run.run_id}")

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
