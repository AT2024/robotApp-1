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
        lock_manager: ResourceLockManager
    ):
        super().__init__(
            robot_id=robot_id,
            robot_type="ot2",
            settings=settings,
            state_manager=state_manager,
            lock_manager=lock_manager,
            service_name="OT2Service"
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
        self.default_protocol_file = protocol_config.get("default_file", "ot2Protocole.py")
        self.protocol_execution_timeout = protocol_config.get("execution_timeout", 3600.0)
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
        
        if is_connected:
            # Robot connected - set to IDLE state
            await self.update_robot_state(
                RobotState.IDLE,
                reason="OT2 robot connection restored"
            )
            self.logger.info(f"OT2 robot {self.robot_id} connection restored")
        else:
            # Robot disconnected - set to ERROR state  
            await self.update_robot_state(
                RobotState.ERROR,
                reason="OT2 robot connection lost"
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
                "timestamp": time.time()
            }
            
            await broadcaster.broadcast_message(
                message_type=MessageType.ROBOT_STATUS,
                data=message,
                robot_id=self.robot_id
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
            connector=connector,
            timeout=timeout,
            headers={"opentrons-version": self.api_version}
        )
        
        # Try to connect and update state
        try:
            # Update to connecting state first
            await self.update_robot_state(
                RobotState.CONNECTING,
                reason="Attempting to connect to OT2"
            )
            
            # Test connection to OT2
            health_data = await self._get_health_status()
            if health_data:
                await self.update_robot_state(
                    RobotState.IDLE, 
                    reason="OT2 connected and ready"
                )
                self.logger.info(f"OT2 robot {self.robot_id} connected successfully")
            else:
                await self.update_robot_state(
                    RobotState.ERROR, 
                    reason="No health data received from OT2"
                )
        except Exception as e:
            self.logger.warning(f"OT2 robot {self.robot_id} connection failed: {e}")
            await self.update_robot_state(
                RobotState.ERROR, 
                reason=f"Connection failed: {e}"
            )
        
        # Start run monitoring if there's an active run
        await self._check_for_active_runs()
    
    async def _on_stop(self):
        """Clean up HTTP session and stop monitoring"""
        # Update robot state to disconnected
        try:
            await self.update_robot_state(
                RobotState.DISCONNECTED,
                reason="Service stopping"
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
        try:
            if self._current_run:
                # Stop current run
                await self._stop_run(self._current_run.run_id)
            
            # Home the robot
            await self._home_robot()
            
            return True
        except Exception as e:
            self.logger.error(f"Emergency stop failed: {e}")
            return False
    
    @circuit_breaker("ot2_connection", failure_threshold=3, recovery_timeout=30)
    async def execute_protocol(
        self,
        protocol_config: ProtocolConfig,
        monitor_progress: bool = True
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
            metadata={"protocol": protocol_config.protocol_name}
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
                
                # Step 2: Create and start run
                run_id = await self._create_run(protocol_id, protocol_config.parameters)
                
                # Step 3: Start execution
                run_status = await self._start_run(run_id)
                self._current_run = run_status
                
                # Step 4: Monitor execution if requested
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
        self,
        operation_id: str,
        params: LiquidHandlingParams
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
            metadata={"volume": params.volume, "source": params.source_well, "dest": params.dest_well}
        )
        
        async def _liquid_handling():
            # Create a simple protocol for liquid handling
            protocol_data = self._create_liquid_handling_protocol(params)
            
            # Save protocol temporarily
            protocol_file = self.protocol_directory / f"liquid_handling_{operation_id}.py"
            with open(protocol_file, 'w') as f:
                f.write(protocol_data)
            
            try:
                # Execute the liquid handling protocol
                protocol_config = ProtocolConfig(
                    protocol_name=f"liquid_handling_{operation_id}",
                    protocol_file=str(protocol_file),
                    parameters={},
                    labware_setup={}
                )
                
                result = await self.execute_protocol(protocol_config)
                
                if result.success:
                    return {
                        "operation_id": operation_id,
                        "volume_transferred": params.volume,
                        "source": f"{params.source_labware}:{params.source_well}",
                        "destination": f"{params.dest_labware}:{params.dest_well}",
                        "status": "completed"
                    }
                else:
                    raise HardwareError(f"Liquid handling failed: {result.error}", robot_id=self.robot_id)
                    
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
            timeout=300.0  # Calibration takes longer
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
                    "status": "completed"
                }
                
                if needs_calibration:
                    self.logger.warning("Pipette calibration required - manual intervention needed")
                    result["message"] = "Manual calibration required through OT-2 interface"
                
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
                await self.update_robot_state(RobotState.IDLE, reason="Connected to OT2")
                return ServiceResult.success_result(True)
            else:
                await self.update_robot_state(RobotState.ERROR, reason="Connection failed")
                return ServiceResult.success_result(False)
        except Exception as e:
            await self.update_robot_state(RobotState.ERROR, reason=f"Connection error: {e}")
            return ServiceResult.error_result(f"Connection failed: {e}")
    
    async def disconnect(self) -> ServiceResult[bool]:
        """Disconnect from OT2 robot"""
        try:
            await self.update_robot_state(RobotState.DISCONNECTED, reason="Disconnected from OT2")
            return ServiceResult.success_result(True)
        except Exception as e:
            return ServiceResult.error_result(f"Disconnect failed: {e}")
    
    async def emergency_stop(self) -> ServiceResult[bool]:
        """Emergency stop OT2 robot"""
        try:
            result = await self._execute_emergency_stop()
            if result:
                await self.update_robot_state(RobotState.ERROR, reason="Emergency stop activated")
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
    
    async def initialize_protocol(self, protocol_file: str, protocol_parameters: Dict[str, Any] = None) -> ServiceResult[Dict[str, Any]]:
        """Initialize protocol execution - wrapper method for ProtocolExecutionService compatibility"""
        try:
            # Validate protocol file exists
            if not Path(protocol_file).exists():
                return ServiceResult.error_result(f"Protocol file not found: {protocol_file}")
            
            # Ensure robot is ready
            await self.ensure_robot_ready()
            
            # Get health status to verify connection
            health_data = await self._get_health_status()
            if not health_data:
                return ServiceResult.error_result("OT2 robot not accessible")
            
            self.logger.info(f"OT2 protocol initialized: {protocol_file}")
            return ServiceResult.success_result({
                "status": "initialized",
                "protocol_file": protocol_file,
                "protocol_parameters": protocol_parameters or {},
                "robot_health": health_data
            })
        except Exception as e:
            self.logger.error(f"Failed to initialize protocol: {e}")
            return ServiceResult.error_result(f"Protocol initialization failed: {str(e)}")
    
    async def run_protocol(self, **kwargs) -> ServiceResult[Dict[str, Any]]:
        """Run protocol execution - wrapper method for ProtocolExecutionService compatibility"""
        try:
            # Filter out unsupported parameters and extract valid protocol parameters
            protocol_parameters = kwargs.copy()
            
            # Remove any unsupported parameters that might cause issues
            unsupported_params = ["test", "debug", "verbose"]
            for param in unsupported_params:
                protocol_parameters.pop(param, None)
            
            # Validate protocol file exists before creating config
            protocol_file_path = self.protocol_directory / "ot2Protocole.py"
            if not protocol_file_path.exists():
                raise ValidationError(f"Protocol file not found: {protocol_file_path}")
            
            # Create a default protocol config for the standard OT2 protocol
            protocol_config = ProtocolConfig(
                protocol_name=protocol_parameters.get("protocol_name", "OT2_Liquid_Handling"),
                protocol_file=str(protocol_file_path),
                parameters=protocol_parameters,
                labware_setup={}
            )
            
            # Execute the protocol using existing method
            result = await self.execute_protocol(protocol_config, monitor_progress=True)
            
            if result.success:
                return ServiceResult.success_result({
                    "status": "completed",
                    "run_status": result.data.__dict__ if hasattr(result.data, '__dict__') else result.data,
                    "protocol_parameters": protocol_parameters
                })
            else:
                return ServiceResult.error_result(f"Protocol execution failed: {result.error}")
                
        except Exception as e:
            self.logger.error(f"Failed to run protocol: {e}")
            return ServiceResult.error_result(f"Protocol execution failed: {str(e)}")

    async def get_robot_status(self) -> ServiceResult[Dict[str, Any]]:
        """Get detailed OT2 robot status"""
        context = OperationContext(
            operation_id=f"{self.robot_id}_status",
            robot_id=self.robot_id,
            operation_type=OT2OperationType.STATUS_CHECK.value
        )
        
        async def _get_status():
            # Get hardware status
            health_data = await self._get_health_status()
            
            # Get current runs
            runs_data = await self._get_current_runs()
            
            # Get robot info from state manager
            robot_info = await self.state_manager.get_robot_state(self.robot_id)
            
            return {
                "robot_id": self.robot_id,
                "robot_type": self.robot_type,
                "hardware_status": health_data,
                "current_runs": runs_data,
                "state_info": {
                    "current_state": robot_info.current_state.value if robot_info else "unknown",
                    "operational": robot_info.is_operational if robot_info else False,
                    "uptime_seconds": robot_info.uptime_seconds if robot_info else 0,
                    "error_count": robot_info.error_count if robot_info else 0
                },
                "current_run": self._current_run.__dict__ if self._current_run else None,
                "base_url": self.base_url
            }
        
        return await self.execute_operation(context, _get_status)
    
    async def stop_current_run(self) -> ServiceResult[bool]:
        """Stop the currently running protocol"""
        if not self._current_run or self._current_run.status != ProtocolStatus.RUNNING:
            return ServiceResult.error_result(
                "No protocol currently running",
                error_code="NO_ACTIVE_RUN"
            )
        
        context = OperationContext(
            operation_id=f"{self.robot_id}_stop_run",
            robot_id=self.robot_id,
            operation_type="stop_run"
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
        timeout: float = 30.0
    ) -> Dict[str, Any]:
        """Make HTTP request to OT2 API"""
        if not self._session:
            raise HardwareError("HTTP session not initialized", robot_id=self.robot_id)
        
        url = f"{self.base_url}{endpoint}"
        
        try:
            headers = {"opentrons-version": "4"}
            kwargs = {
                "timeout": aiohttp.ClientTimeout(total=timeout),
                "headers": headers
            }
            if data:
                kwargs["json"] = data
            
            async with self._session.request(method, url, **kwargs) as response:
                if response.status >= 400:
                    error_text = await response.text()
                    raise HardwareError(
                        f"OT2 API error: {response.status} - {error_text}",
                        robot_id=self.robot_id
                    )
                
                return await response.json()
                
        except aiohttp.ClientError as e:
            raise HardwareError(f"OT2 connection error: {e}", robot_id=self.robot_id)
    
    async def _upload_protocol(self, protocol_config: ProtocolConfig) -> str:
        """Upload protocol to OT2 using multipart/form-data format"""
        protocol_file = Path(protocol_config.protocol_file)
        
        # Protocol file should already be absolute path and validated
        if not protocol_file.exists():
            raise ValidationError(f"Protocol file not found: {protocol_file}")
        
        # Upload protocol using multipart/form-data format
        if not self._session:
            raise HardwareError("HTTP session not initialized", robot_id=self.robot_id)
        
        url = f"{self.base_url}/protocols"
        
        try:
            # Prepare multipart form data
            data = aiohttp.FormData()
            data.add_field('files', 
                          open(protocol_file, 'rb'), 
                          filename=protocol_file.name,
                          content_type='text/x-python')
            
            headers = {"opentrons-version": "4"}
            
            async with self._session.post(url, data=data, headers=headers, 
                                        timeout=aiohttp.ClientTimeout(total=30.0)) as response:
                if response.status >= 400:
                    error_text = await response.text()
                    raise HardwareError(
                        f"OT2 API error: {response.status} - {error_text}",
                        robot_id=self.robot_id
                    )
                
                response_data = await response.json()
                protocol_id = response_data["data"]["id"]
                
                self.logger.info(f"Protocol uploaded: {protocol_id}")
                return protocol_id
                
        except aiohttp.ClientError as e:
            raise HardwareError(f"OT2 connection error: {e}", robot_id=self.robot_id)
    
    async def _create_run(self, protocol_id: str, parameters: Dict[str, Any]) -> str:
        """Create a new protocol run"""
        data = {
            "data": {
                "type": "Run",
                "attributes": {
                    "protocolId": protocol_id
                }
            }
        }
        
        if parameters:
            data["data"]["attributes"]["runTimeParameterValues"] = parameters
        
        response = await self._api_request("POST", "/runs", data)
        run_id = response["data"]["id"]
        
        self.logger.info(f"Run created: {run_id}")
        return run_id
    
    async def _start_run(self, run_id: str) -> RunStatus:
        """Start protocol execution"""
        data = {
            "data": {
                "type": "RunAction",
                "attributes": {
                    "actionType": "play"
                }
            }
        }
        
        await self._api_request("POST", f"/runs/{run_id}/actions", data)
        
        # Get initial run status
        run_data = await self._api_request("GET", f"/runs/{run_id}")
        
        status = RunStatus(
            run_id=run_id,
            protocol_id=run_data["data"]["attributes"]["protocolId"],
            status=ProtocolStatus(run_data["data"]["attributes"]["status"]),
            start_time=time.time()
        )
        
        self.logger.info(f"Run started: {run_id}")
        return status
    
    async def _stop_run(self, run_id: str) -> bool:
        """Stop protocol execution"""
        try:
            data = {
                "data": {
                    "type": "RunAction",
                    "attributes": {
                        "actionType": "stop"
                    }
                }
            }
            
            await self._api_request("POST", f"/runs/{run_id}/actions", data)
            
            self.logger.info(f"Run stopped: {run_id}")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to stop run {run_id}: {e}")
            return False
    
    async def _monitor_run_progress(self, run_id: str) -> RunStatus:
        """Monitor protocol execution progress"""
        while True:
            try:
                await asyncio.sleep(0.5)  # Check every 0.5 seconds for better responsiveness
                
                run_data = await self._api_request("GET", f"/runs/{run_id}")
                attrs = run_data["data"]["attributes"]
                
                status = ProtocolStatus(attrs["status"])
                
                # Update current run status
                if self._current_run:
                    self._current_run.status = status
                    self._current_run.current_command = attrs.get("currentCommand")
                    
                    # Calculate progress if available
                    if "completedAt" in attrs and attrs["completedAt"]:
                        self._current_run.progress_percent = 100.0
                        self._current_run.end_time = time.time()
                    
                    if status in {ProtocolStatus.SUCCEEDED, ProtocolStatus.FAILED, ProtocolStatus.STOPPED}:
                        self._current_run.end_time = time.time()
                        
                        if status == ProtocolStatus.FAILED:
                            # Get error details
                            self._current_run.error_message = attrs.get("errors", [{}])[0].get("detail", "Unknown error")
                            
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
                await asyncio.sleep(1.0)  # Shorter error recovery delay for faster startup
    
    async def _get_health_status(self) -> Dict[str, Any]:
        """Get OT2 health status"""
        return await self._api_request("GET", "/health")
    
    async def _get_current_runs(self) -> Dict[str, Any]:
        """Get current runs"""
        return await self._api_request("GET", "/runs")
    
    async def _get_calibration_data(self) -> Dict[str, Any]:
        """Get calibration data"""
        return await self._api_request("GET", "/calibration/status")
    
    async def _home_robot(self) -> bool:
        """Home the robot"""
        try:
            data = {
                "target": "robot"
            }
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
                    start_time=time.time()  # Approximate start time
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
        protocol = f'''
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
'''
        return protocol