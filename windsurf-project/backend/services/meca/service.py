"""
Mecademic robot service - main orchestrator.

This is the primary interface for controlling the Mecademic robot.
It delegates to specialized modules for specific functionality:
- MecaConnectionManager: Connection lifecycle
- MecaRecoveryOperations: Recovery and safe homing
- MecaPositionCalculator: Position calculations
- MecaMovementExecutor: Movement command execution
- MecaWaferSequences: Wafer handling sequences
"""

import asyncio
import time
from typing import Dict, List, Any, Optional
from enum import Enum

from core.async_robot_wrapper import AsyncRobotWrapper, MovementCommand
from core.state_manager import AtomicStateManager, RobotState
from core.resource_lock import ResourceLockManager
from core.settings import RoboticsSettings
from core.circuit_breaker import circuit_breaker
from core.exceptions import HardwareError, ValidationError
from services.base import RobotService, ServiceResult, OperationContext
from services.wafer_config_manager import WaferConfigManager
from utils.logger import get_logger


class MecaOperationType(Enum):
    """Types of Mecademic operations"""
    PICKUP_WAFER = "pickup_wafer"
    DROP_WAFER = "drop_wafer"
    MOVE_TO_POSITION = "move_to_position"
    CAROUSEL_OPERATION = "carousel_operation"
    CALIBRATION = "calibration"
    GRIPPER_CONTROL = "gripper_control"

from .connection_manager import MecaConnectionManager
from .recovery_operations import MecaRecoveryOperations
from .position_calculator import MecaPositionCalculator, WaferPosition, CarouselPosition
from .movement_executor import MecaMovementExecutor
from .wafer_sequences import MecaWaferSequences


class MecaService(RobotService):
    """
    Mecademic robot service - coordinates all robot operations.

    This service provides the public API for controlling the Mecademic robot,
    delegating to specialized modules for implementation details.
    """

    def __init__(
        self,
        robot_id: str,
        settings: RoboticsSettings,
        state_manager: AtomicStateManager,
        lock_manager: ResourceLockManager,
        async_wrapper: AsyncRobotWrapper = None
    ):
        """
        Initialize Mecademic robot service.

        Args:
            robot_id: Robot identifier
            settings: Robotics settings
            state_manager: AtomicStateManager for state tracking
            lock_manager: ResourceLockManager for resource locking
            async_wrapper: Optional AsyncRobotWrapper instance (for testing)
        """
        super().__init__(
            robot_id=robot_id,
            robot_type="meca",
            settings=settings,
            state_manager=state_manager,
            lock_manager=lock_manager,
            service_name="MecaService"
        )

        self.robot_config = settings.get_robot_config("meca")
        self.movement_params = self.robot_config.get("movement_params", {})
        self.logger = get_logger("meca_service")

        # Initialize wafer config manager
        self.wafer_config_manager = WaferConfigManager(
            self.robot_config,
            self.movement_params
        )

        # Use provided async wrapper or create new one
        self.async_wrapper = async_wrapper or AsyncRobotWrapper(robot_id, "meca", settings)

        # Initialize specialized modules
        self.connection_manager = MecaConnectionManager(
            robot_id=robot_id,
            settings=settings,
            async_wrapper=self.async_wrapper,
            state_manager=state_manager,
            broadcaster_callback=self._broadcast_message
        )

        self.position_calculator = MecaPositionCalculator(
            robot_config=self.robot_config,
            movement_params=self.movement_params,
            wafer_config_manager=self.wafer_config_manager
        )

        self.movement_executor = MecaMovementExecutor(
            robot_id=robot_id,
            async_wrapper=self.async_wrapper,
            state_manager=state_manager,
            movement_params=self.movement_params
        )

        self.recovery_operations = MecaRecoveryOperations(
            robot_id=robot_id,
            settings=settings,
            robot_config=self.robot_config,
            async_wrapper=self.async_wrapper,
            state_manager=state_manager,
            connection_manager=self.connection_manager,
            broadcaster_callback=self._broadcast_message
        )

        self.wafer_sequences = MecaWaferSequences(
            robot_id=robot_id,
            robot_config=self.robot_config,
            async_wrapper=self.async_wrapper,
            state_manager=state_manager,
            position_calculator=self.position_calculator,
            movement_executor=self.movement_executor,
            broadcaster_callback=self._broadcast_message
        )

        # Speed settings for convenience (defaults match original meca_service.py values)
        self.FORCE = self.movement_params.get("force", 100)
        self.ACC = self.movement_params.get("acceleration", 50)
        self.WAFER_SPEED = self.movement_params.get("wafer_speed", 35)
        self.SPEED = self.movement_params.get("speed", 35)
        self.ALIGN_SPEED = self.movement_params.get("align_speed", 20)
        self.ENTRY_SPEED = self.movement_params.get("entry_speed", 15)
        self.EMPTY_SPEED = self.movement_params.get("empty_speed", 50)
        self.SPREAD_WAIT = self.movement_params.get("spread_wait", 25)

        # Log speed settings for diagnostics
        self.logger.info(
            f"[SPEED DIAGNOSTIC] {self.robot_id} speed settings loaded: "
            f"WAFER={self.WAFER_SPEED}, SPEED={self.SPEED}, ALIGN={self.ALIGN_SPEED}, "
            f"ENTRY={self.ENTRY_SPEED}, EMPTY={self.EMPTY_SPEED} "
            f"(Expected: WAFER=35, SPEED=35, ALIGN=20, ENTRY=15, EMPTY=50)"
        )
        if self.WAFER_SPEED < 30 or self.SPEED < 30 or self.ALIGN_SPEED < 15:
            self.logger.warning(
                f"[SPEED WARNING] Speed values below expected! Check if movement_params "
                f"is properly populated from settings. movement_params keys: {list(self.movement_params.keys())}"
            )

        # Position constants (exposed for compatibility)
        self.SAFE_POINT = self.position_calculator.SAFE_POINT
        self.CAROUSEL = self.position_calculator.CAROUSEL
        self.CAROUSEL_SAFEPOINT = self.position_calculator.CAROUSEL_SAFEPOINT
        self.T_PHOTOGATE = self.position_calculator.T_PHOTOGATE
        self.C_PHOTOGATE = self.position_calculator.C_PHOTOGATE

        # Expose carousel positions
        self.carousel_positions = self.position_calculator.carousel_positions
        self.safe_position = self.position_calculator.safe_position

        # Safe homing state (delegated to recovery operations)
        self._safe_homing_active = False
        self._safe_homing_stop_requested = False

        # Resume task reference
        self._resume_task: Optional[asyncio.Task] = None

        # Gripper state (accessed through movement executor)
        self._gripper_open = True

    # =========================================================================
    # Service Lifecycle Methods
    # =========================================================================

    async def _on_stop(self):
        """
        Gracefully disconnect from Mecademic robot on service shutdown.

        CRITICAL: This method ensures the TCP connection is properly closed
        before Docker shuts down. Without this, the Mecademic robot holds
        a stale TCP connection and rejects new connections until power cycled.
        """
        self.logger.info(f"MecaService stopping - disconnecting robot {self.robot_id}")

        try:
            # Use disconnect_safe for proper TCP cleanup
            # This follows mecademicpy best practices:
            # 1. WaitIdle() 2. DeactivateRobot() 3. Disconnect()
            await self.connection_manager.disconnect_safe()
            self.logger.info(f"MecaService: Robot {self.robot_id} disconnected cleanly")
        except Exception as e:
            self.logger.warning(f"MecaService: Disconnect failed (may already be disconnected): {e}")
            # Force state to DISCONNECTED even if disconnect fails
            try:
                await self.state_manager.update_robot_state(
                    self.robot_id,
                    RobotState.DISCONNECTED,
                    reason=f"Service stopping (disconnect error: {e})"
                )
            except Exception:
                pass

    # =========================================================================
    # Broadcasting Helper
    # =========================================================================

    async def _broadcast_message(self, message_type: str, data: Dict[str, Any]) -> bool:
        """
        Broadcast message to connected WebSocket clients.

        Args:
            message_type: Type of message
            data: Message data

        Returns:
            True if broadcast succeeded
        """
        try:
            # Import websocket handler singleton which has reference to actual connection manager
            from websocket.websocket_handlers import get_websocket_handler_singleton
            ws_handler = get_websocket_handler_singleton()
            if ws_handler and ws_handler.connection_manager:
                # Use operation_update format expected by frontend
                message = {
                    "type": "operation_update",
                    "data": {
                        "event": message_type,
                        **data
                    }
                }
                # INFO-level logging to verify broadcasts are reaching WebSocket
                self.logger.info(f"[BROADCAST] {message_type}: wafer_num={data.get('wafer_num', 'N/A')}, data={data}")
                await ws_handler.connection_manager.broadcast(message)
                return True
            else:
                self.logger.warning(
                    f"No WebSocket handler available for {message_type} broadcast "
                    f"(ws_handler={ws_handler is not None}, "
                    f"connection_manager={ws_handler.connection_manager is not None if ws_handler else 'N/A'})"
                )
        except Exception as e:
            self.logger.warning(f"Failed to broadcast {message_type}: {e}")
        return False

    # =========================================================================
    # Connection Methods (delegated to MecaConnectionManager)
    # =========================================================================

    @circuit_breaker("meca_connect", failure_threshold=3, recovery_timeout=30)
    async def connect(self) -> ServiceResult[Dict[str, Any]]:
        """Connect to the Mecademic robot."""
        context = OperationContext(
            operation_id=f"{self.robot_id}_connect",
            robot_id=self.robot_id,
            operation_type="connect",
            timeout=30.0
        )

        async def _connect():
            return await self.connection_manager.connect(
                capture_position_callback=self._capture_initial_position
            )

        return await self.execute_operation(context, _connect)

    async def _capture_initial_position(self) -> None:
        """Capture initial position after connect."""
        try:
            driver = self.async_wrapper.robot_driver
            joints = await driver.get_joints()
            self.logger.info(f"Initial position captured: {joints}")
        except Exception as e:
            self.logger.warning(f"Could not capture initial position: {e}")

    @circuit_breaker("meca_disconnect", failure_threshold=3, recovery_timeout=10)
    async def disconnect(self) -> ServiceResult[Dict[str, Any]]:
        """Disconnect from the Mecademic robot."""
        context = OperationContext(
            operation_id=f"{self.robot_id}_disconnect",
            robot_id=self.robot_id,
            operation_type="disconnect",
            timeout=15.0
        )

        async def _disconnect():
            return await self.connection_manager.disconnect()

        return await self.execute_operation(context, _disconnect)

    async def connect_safe(self) -> ServiceResult[Dict[str, Any]]:
        """
        Connect to robot WITHOUT automatic homing.
        Returns joint positions for UI confirmation before proceeding.
        """
        context = OperationContext(
            operation_id=f"{self.robot_id}_connect_safe",
            robot_id=self.robot_id,
            operation_type="connect_safe",
            timeout=30.0
        )

        async def _connect_safe():
            return await self.connection_manager.connect_safe()

        return await self.execute_operation(context, _connect_safe)

    async def confirm_activation(self) -> ServiceResult[Dict[str, Any]]:
        """
        User-confirmed activation and homing.
        Called by UI after user confirms robot position is safe.
        """
        context = OperationContext(
            operation_id=f"{self.robot_id}_confirm_activation",
            robot_id=self.robot_id,
            operation_type="activation",
            timeout=60.0
        )

        async def _confirm_activation():
            return await self.connection_manager.confirm_activation(
                emergency_stop_callback=self.emergency_stop
            )

        return await self.execute_operation(context, _confirm_activation)

    async def disconnect_safe(self) -> ServiceResult[Dict[str, Any]]:
        """Gracefully disconnect from Mecademic robot."""
        context = OperationContext(
            operation_id=f"{self.robot_id}_disconnect_safe",
            robot_id=self.robot_id,
            operation_type="disconnect_safe",
            timeout=30.0
        )

        async def _disconnect_safe():
            return await self.connection_manager.disconnect_safe()

        return await self.execute_operation(context, _disconnect_safe)

    # =========================================================================
    # Recovery Methods (delegated to MecaRecoveryOperations)
    # =========================================================================

    async def enable_recovery_mode(self) -> ServiceResult[Dict[str, Any]]:
        """Enable recovery mode for safe robot repositioning."""
        context = OperationContext(
            operation_id=f"{self.robot_id}_enable_recovery_mode",
            robot_id=self.robot_id,
            operation_type="recovery_mode",
            timeout=30.0
        )

        async def _enable_recovery():
            return await self.recovery_operations.enable_recovery_mode()

        return await self.execute_operation(context, _enable_recovery)

    async def disable_recovery_mode(self) -> ServiceResult[Dict[str, Any]]:
        """Disable recovery mode after robot has been repositioned."""
        context = OperationContext(
            operation_id=f"{self.robot_id}_disable_recovery_mode",
            robot_id=self.robot_id,
            operation_type="recovery_mode",
            timeout=30.0
        )

        async def _disable_recovery():
            return await self.recovery_operations.disable_recovery_mode()

        return await self.execute_operation(context, _disable_recovery)

    async def get_recovery_status(self) -> ServiceResult[Dict[str, Any]]:
        """Get current recovery status with available actions."""
        context = OperationContext(
            operation_id=f"{self.robot_id}_get_recovery_status",
            robot_id=self.robot_id,
            operation_type="status_check",
            timeout=15.0
        )

        async def _get_recovery_status():
            return await self.recovery_operations.get_recovery_status()

        return await self.execute_operation(context, _get_recovery_status)

    async def quick_recovery(self) -> ServiceResult[Dict[str, Any]]:
        """Quick recovery - clear robot error state and resume workflow."""
        context = OperationContext(
            operation_id=f"{self.robot_id}_quick_recovery_{int(time.time() * 1000)}",
            robot_id=self.robot_id,
            operation_type="quick_recovery",
            timeout=60.0
        )

        async def _quick_recovery():
            return await self.recovery_operations.quick_recovery()

        return await self.execute_operation(context, _quick_recovery)

    async def reset_errors_and_reconnect(self) -> ServiceResult[Dict[str, Any]]:
        """Full recovery sequence: reset errors, reconnect, and prepare for activation."""
        context = OperationContext(
            operation_id=f"{self.robot_id}_reset_and_reconnect",
            robot_id=self.robot_id,
            operation_type="recovery",
            timeout=60.0
        )

        async def _reset_and_reconnect():
            return await self.recovery_operations.reset_errors_and_reconnect()

        return await self.execute_operation(context, _reset_and_reconnect)

    async def move_to_safe_position_recovery(
        self,
        speed_percent: float = 10.0
    ) -> ServiceResult[Dict[str, Any]]:
        """Move robot to safe position while in recovery mode."""
        context = OperationContext(
            operation_id=f"{self.robot_id}_recovery_move_safe",
            robot_id=self.robot_id,
            operation_type="recovery_movement",
            timeout=120.0
        )

        async def _move_to_safe():
            return await self.recovery_operations.move_to_safe_position_recovery(speed_percent)

        return await self.execute_operation(context, _move_to_safe)

    async def start_safe_homing(
        self, speed_percent: int = 20
    ) -> ServiceResult[Dict[str, Any]]:
        """Start safe homing at reduced speed with automatic recovery mode handling."""
        context = OperationContext(
            operation_id=f"{self.robot_id}_safe_homing_{int(time.time() * 1000)}",
            robot_id=self.robot_id,
            operation_type="safe_homing",
            timeout=180.0
        )

        async def _start_safe_homing():
            return await self.recovery_operations.start_safe_homing(speed_percent)

        return await self.execute_operation(context, _start_safe_homing)

    async def stop_safe_homing(self) -> ServiceResult[Dict[str, Any]]:
        """Stop safe homing in progress - robot holds position."""
        context = OperationContext(
            operation_id=f"{self.robot_id}_stop_safe_homing_{int(time.time() * 1000)}",
            robot_id=self.robot_id,
            operation_type="stop_safe_homing",
            timeout=10.0
        )

        async def _stop_safe_homing():
            return await self.recovery_operations.stop_safe_homing()

        return await self.execute_operation(context, _stop_safe_homing)

    async def resume_safe_homing(self) -> ServiceResult[Dict[str, Any]]:
        """Resume safe homing from current position."""
        context = OperationContext(
            operation_id=f"{self.robot_id}_resume_safe_homing_{int(time.time() * 1000)}",
            robot_id=self.robot_id,
            operation_type="resume_safe_homing",
            timeout=180.0
        )

        async def _resume_safe_homing():
            return await self.recovery_operations.resume_safe_homing()

        return await self.execute_operation(context, _resume_safe_homing)

    def is_safe_homing_active(self) -> bool:
        """Check if safe homing is currently in progress."""
        return self.recovery_operations.safe_homing_active

    def is_safe_homing_stopped(self) -> bool:
        """Check if safe homing is stopped (paused mid-movement)."""
        return self.recovery_operations.safe_homing_stopped

    # =========================================================================
    # Wafer Sequence Methods (delegated to MecaWaferSequences)
    # =========================================================================

    async def execute_pickup_sequence(
        self, start: int, count: int, retry_wafers: Optional[List[int]] = None
    ) -> ServiceResult[Dict[str, Any]]:
        """Execute wafer pickup sequence from inert tray to spreader."""
        context = OperationContext(
            operation_id=f"{self.robot_id}_pickup_sequence_{start}_{count}",
            robot_id=self.robot_id,
            operation_type=MecaOperationType.PICKUP_WAFER.value,
            timeout=600.0,
            metadata={"start": start, "count": count}
        )

        async def _pickup_sequence():
            await self.ensure_robot_ready()
            return await self.wafer_sequences.execute_pickup_sequence(start, count, retry_wafers)

        return await self.execute_operation(context, _pickup_sequence)

    async def execute_drop_sequence(
        self, start: int, count: int, retry_wafers: Optional[List[int]] = None
    ) -> ServiceResult[Dict[str, Any]]:
        """Execute wafer drop sequence from spreader to baking tray."""
        context = OperationContext(
            operation_id=f"{self.robot_id}_drop_sequence_{start}_{count}",
            robot_id=self.robot_id,
            operation_type=MecaOperationType.DROP_WAFER.value,
            timeout=600.0,
            metadata={"start": start, "count": count}
        )

        async def _drop_sequence():
            await self.ensure_robot_ready()
            return await self.wafer_sequences.execute_drop_sequence(start, count, retry_wafers)

        return await self.execute_operation(context, _drop_sequence)

    async def execute_carousel_sequence(self, start: int, count: int) -> ServiceResult[Dict[str, Any]]:
        """Execute carousel sequence from baking tray to carousel."""
        context = OperationContext(
            operation_id=f"{self.robot_id}_carousel_sequence_{start}_{count}",
            robot_id=self.robot_id,
            operation_type=MecaOperationType.CAROUSEL_OPERATION.value,
            timeout=900.0,
            metadata={"start": start, "count": count}
        )

        async def _carousel_sequence():
            await self.ensure_robot_ready()
            return await self.wafer_sequences.execute_carousel_sequence(start, count)

        return await self.execute_operation(context, _carousel_sequence)

    async def execute_empty_carousel_sequence(self, start: int, count: int) -> ServiceResult[Dict[str, Any]]:
        """Execute empty carousel sequence from carousel back to baking tray."""
        context = OperationContext(
            operation_id=f"{self.robot_id}_empty_carousel_sequence_{start}_{count}",
            robot_id=self.robot_id,
            operation_type=MecaOperationType.CAROUSEL_OPERATION.value,
            timeout=900.0,
            metadata={"start": start, "count": count}
        )

        async def _empty_carousel_sequence():
            await self.ensure_robot_ready()
            return await self.wafer_sequences.execute_empty_carousel_sequence(start, count)

        return await self.execute_operation(context, _empty_carousel_sequence)

    async def resume_operations(self) -> ServiceResult[Dict[str, Any]]:
        """Resume interrupted operations based on step state."""
        return await self.wafer_sequences.resume_operations()

    # =========================================================================
    # Position Calculation Methods (delegated to MecaPositionCalculator)
    # =========================================================================

    def calculate_wafer_position(self, wafer_index: int, tray_type: str) -> List[float]:
        """Calculate exact wafer position based on wafer index and tray type."""
        return self.position_calculator.calculate_wafer_position(wafer_index, tray_type)

    def calculate_intermediate_positions(self, wafer_index: int, operation: str) -> Dict[str, List[float]]:
        """Calculate intermediate positions for safe movement during wafer operations."""
        return self.position_calculator.calculate_intermediate_positions(wafer_index, operation)

    async def get_wafer_position_preview(self, wafer_index: int) -> Dict[str, Any]:
        """Get position preview data for a single wafer."""
        return self.position_calculator.get_wafer_position_preview(wafer_index)

    # =========================================================================
    # Status and Utility Methods
    # =========================================================================

    async def get_robot_status(self) -> ServiceResult[Dict[str, Any]]:
        """Get detailed robot status."""
        context = OperationContext(
            operation_id=f"{self.robot_id}_status",
            robot_id=self.robot_id,
            operation_type="status_check"
        )

        async def _get_status():
            robot_status = await self.async_wrapper.get_status()
            robot_info = await self.state_manager.get_robot_state(self.robot_id)
            performance = await self.async_wrapper.get_performance_stats()

            return {
                "robot_id": self.robot_id,
                "robot_type": self.robot_type,
                "hardware_status": robot_status,
                "state_info": {
                    "current_state": robot_info.current_state.value if robot_info else "unknown",
                    "operational": robot_info.is_operational if robot_info else False,
                    "uptime_seconds": robot_info.uptime_seconds if robot_info else 0,
                    "error_count": robot_info.error_count if robot_info else 0
                },
                "gripper_open": self.movement_executor.gripper_open,
                "carousel_status": {
                    "total_positions": len(self.carousel_positions),
                    "occupied_positions": sum(1 for pos in self.carousel_positions if pos.occupied)
                },
                "performance": performance
            }

        return await self.execute_operation(context, _get_status)

    async def get_carousel_status(self) -> ServiceResult[List[Dict[str, Any]]]:
        """Get status of all carousel positions."""
        context = OperationContext(
            operation_id=f"{self.robot_id}_carousel_status",
            robot_id=self.robot_id,
            operation_type="carousel_status"
        )

        async def _get_carousel_status():
            return [
                {
                    "position_index": pos.position_index,
                    "occupied": pos.occupied,
                    "wafer_id": pos.wafer_id,
                    "coordinates": {
                        "x": pos.coordinates.x,
                        "y": pos.coordinates.y,
                        "z": pos.coordinates.z
                    }
                }
                for pos in self.carousel_positions
            ]

        return await self.execute_operation(context, _get_carousel_status)

    async def move_to_safe_position(self) -> ServiceResult[bool]:
        """Move robot to safe position."""
        context = OperationContext(
            operation_id=f"{self.robot_id}_safe_position",
            robot_id=self.robot_id,
            operation_type="move_to_safe"
        )

        async def _move_safe():
            await self.movement_executor.move_to_position(self.safe_position, "safe")
            return True

        return await self.execute_operation(context, _move_safe)

    async def calibrate_robot(self) -> ServiceResult[Dict[str, Any]]:
        """Perform robot calibration sequence."""
        context = OperationContext(
            operation_id=f"{self.robot_id}_calibration",
            robot_id=self.robot_id,
            operation_type=MecaOperationType.CALIBRATION.value,
            timeout=120.0
        )

        async def _calibrate():
            await self.ensure_robot_ready()

            try:
                await self.async_wrapper.execute_movement(
                    MovementCommand(command_type="home")
                )
                await self.async_wrapper.execute_movement(
                    MovementCommand(command_type="activate")
                )
                await self.movement_executor.open_gripper()
                await self.async_wrapper.delay(1000)
                await self.movement_executor.close_gripper()

                result = {
                    "calibration_status": "completed",
                    "robot_active": True,
                    "gripper_functional": True
                }

                self.logger.info(f"Robot calibration completed: {self.robot_id}")
                return result

            except Exception as e:
                self.logger.error(f"Robot calibration failed: {e}")
                raise

        return await self.execute_operation(context, _calibrate)

    async def carousel_wafer_operation(
        self,
        operation: str,
        wafer_id: str,
        carousel_position: int
    ) -> ServiceResult[Dict[str, Any]]:
        """Execute wafer operation with carousel resource locking."""
        if operation not in ["pickup", "drop"]:
            return ServiceResult.error_result(
                f"Invalid operation: {operation}. Must be 'pickup' or 'drop'",
                error_code="INVALID_OPERATION"
            )

        if not 0 <= carousel_position < len(self.carousel_positions):
            return ServiceResult.error_result(
                f"Invalid carousel position: {carousel_position}",
                error_code="INVALID_POSITION"
            )

        context = OperationContext(
            operation_id=f"{self.robot_id}_carousel_{operation}_{wafer_id}",
            robot_id=self.robot_id,
            operation_type=MecaOperationType.CAROUSEL_OPERATION.value,
            timeout=self.settings.operation_timeout * 2,
            metadata={
                "wafer_id": wafer_id,
                "operation": operation,
                "carousel_position": carousel_position
            }
        )

        async def _carousel_operation():
            async with self.lock_manager.acquire_resource(
                "carousel",
                holder_id=context.operation_id,
                timeout=self.settings.meca_timeout
            ):
                carousel_pos = self.carousel_positions[carousel_position]
                target_position = carousel_pos.coordinates

                if operation == "pickup":
                    if not carousel_pos.occupied:
                        raise ValidationError(f"No wafer at carousel position {carousel_position}")

                    result = await self.pickup_wafer_sequence(wafer_id, target_position)
                    carousel_pos.occupied = False
                    carousel_pos.wafer_id = None

                else:
                    if carousel_pos.occupied:
                        raise ValidationError(
                            f"Carousel position {carousel_position} already occupied"
                        )

                    result = await self.drop_wafer_sequence(wafer_id, target_position)
                    carousel_pos.occupied = True
                    carousel_pos.wafer_id = wafer_id

                if result.success:
                    return {
                        "operation": operation,
                        "wafer_id": wafer_id,
                        "carousel_position": carousel_position,
                        "coordinates": target_position,
                        "status": "completed"
                    }
                else:
                    raise HardwareError(f"Carousel {operation} failed: {result.error}", robot_id=self.robot_id)

        return await self.execute_operation(context, _carousel_operation)

    async def reload_sequence_config(self) -> ServiceResult[Dict[str, Any]]:
        """Reload sequence configuration from runtime.json for mid-run adjustments."""
        try:
            from core.settings import get_settings

            new_settings = get_settings()
            new_robot_config = new_settings.get_robot_config("meca")
            new_movement_params = new_robot_config.get("movement_params", {})

            self.wafer_config_manager.reload_config(new_robot_config, new_movement_params)
            self.robot_config = new_robot_config
            self.movement_params = new_movement_params

            errors = self.wafer_config_manager.validate_all_wafers()

            self.logger.info(f"Sequence config reloaded - version {self.wafer_config_manager.config_version}")

            return ServiceResult(
                success=len(errors) == 0,
                data={
                    "version": self.wafer_config_manager.config_version,
                    "validation_errors": errors,
                    "message": "Configuration reloaded successfully" if not errors else f"Config reloaded with {len(errors)} warnings"
                },
                error="; ".join(errors) if errors else None
            )
        except Exception as e:
            self.logger.error(f"Failed to reload sequence config: {e}")
            return ServiceResult(success=False, error=str(e))

    async def get_debug_connection_state(self) -> Dict[str, Any]:
        """Get comprehensive connection diagnostics for debugging."""
        robot_info = await self.state_manager.get_robot_state(self.robot_id)
        current_state = robot_info.current_state if robot_info else None

        debug_info = {
            "timestamp": time.time(),
            "robot_id": self.robot_id,
            "service_state": current_state.name if hasattr(current_state, 'name') else str(current_state),
            "service_ready": False,
            "driver_available": False,
            "robot_instance_available": False,
            "socket_connected": False,
            "activation_status": False,
            "homing_status": False,
            "error_status": False,
            "paused_status": False,
            "connection_details": {},
            "errors": [],
        }

        try:
            debug_info["service_ready"] = await self.ensure_robot_ready(allow_busy=True)
        except Exception as e:
            debug_info["errors"].append(f"Service readiness check failed: {str(e)}")

        if hasattr(self.async_wrapper, 'robot_driver'):
            debug_info["driver_available"] = True
            driver = self.async_wrapper.robot_driver

            try:
                robot_instance = driver.get_robot_instance() if hasattr(driver, 'get_robot_instance') else None
                debug_info["robot_instance_available"] = robot_instance is not None

                if robot_instance:
                    if hasattr(robot_instance, 'is_connected'):
                        debug_info["socket_connected"] = robot_instance.is_connected()
                    elif hasattr(driver, '_connected') and driver._connected:
                        debug_info["socket_connected"] = True
                    else:
                        try:
                            test_status = await driver.get_status()
                            debug_info["socket_connected"] = test_status.get('connected', False)
                        except Exception:
                            debug_info["socket_connected"] = False

                    try:
                        status = await driver.get_status()
                        debug_info["activation_status"] = status.get('activation_status', False)
                        debug_info["homing_status"] = status.get('homing_status', False)
                        debug_info["error_status"] = status.get('error_status', False)
                        debug_info["paused_status"] = status.get('pause_motion_status', False)
                    except Exception as e:
                        debug_info["errors"].append(f"Status retrieval failed: {str(e)}")

            except Exception as e:
                debug_info["errors"].append(f"Driver inspection failed: {str(e)}")

        return debug_info

    # =========================================================================
    # Emergency Stop Implementation
    # =========================================================================

    async def _execute_emergency_stop(self) -> bool:
        """Emergency stop implementation for Mecademic robot."""
        self.logger.critical(f"[EMERGENCY] Executing emergency stop for Meca robot {self.robot_id}")

        emergency_success = False

        try:
            try:
                await self.async_wrapper.execute_movement(
                    MovementCommand(command_type="emergency_stop")
                )
                emergency_success = True
                self.logger.critical(f"Emergency stop executed for {self.robot_id}")
            except Exception as wrapper_error:
                self.logger.error(f"AsyncRobotWrapper emergency stop failed: {wrapper_error}")

                try:
                    if hasattr(self.async_wrapper.robot_driver, '_emergency_stop_impl'):
                        await self.async_wrapper.robot_driver._emergency_stop_impl()
                        emergency_success = True
                except Exception as driver_error:
                    self.logger.error(f"Direct driver emergency stop failed: {driver_error}")

            connection_preserved = await self._validate_connection_after_emergency_stop()

            if emergency_success:
                self.logger.critical(
                    f"Emergency stop completed for {self.robot_id}, "
                    f"connection preserved: {connection_preserved}"
                )

                try:
                    from dependencies import get_orchestrator
                    orchestrator = await get_orchestrator()
                    await orchestrator.state_manager.pause_step(
                        self.robot_id,
                        reason="Emergency stop triggered"
                    )
                    self.logger.info(f"Workflow paused at current step for {self.robot_id}")
                except Exception as pause_error:
                    self.logger.warning(f"Failed to pause workflow: {pause_error}")
            else:
                self.logger.error(f"Emergency stop FAILED for {self.robot_id}")

            return emergency_success

        except Exception as e:
            self.logger.error(f"Emergency stop failed: {e}")
            return False

    async def _validate_connection_after_emergency_stop(self) -> bool:
        """Validate connection after emergency stop."""
        try:
            status = await self.async_wrapper.get_status()
            if status.get("connected", False):
                return True

            self.logger.warning(
                f"Connection appears lost after emergency stop for {self.robot_id} - "
                "manual reconnection may be required via recovery panel"
            )
            return False

        except Exception as e:
            self.logger.error(f"Connection validation failed: {e}")
            return False

    # =========================================================================
    # Low-level Movement Methods (for compatibility)
    # =========================================================================

    async def _execute_movement_command(self, command_type: str, parameters: List[Any] = None) -> None:
        """Execute movement command through the movement executor."""
        await self.movement_executor.execute_movement_command(command_type, parameters)

    async def _open_gripper(self) -> None:
        """Open the gripper."""
        await self.movement_executor.open_gripper()
        self._gripper_open = True

    async def _close_gripper(self) -> None:
        """Close the gripper."""
        await self.movement_executor.close_gripper()
        self._gripper_open = False

    async def _move_to_position(self, position: WaferPosition, move_type: str = "linear") -> Any:
        """Internal method to move robot to specified position."""
        return await self.movement_executor.move_to_position(position, move_type)

    def _validate_robot_parameters(self, command_type: str, parameters: List[Any]) -> bool:
        """Validate robot command parameters."""
        return self.movement_executor._validate_robot_parameters(command_type, parameters)

    def _build_movement_command(self, command_type: str, parameters: List[Any]) -> MovementCommand:
        """Build MovementCommand from command type and parameters."""
        return self.movement_executor._build_movement_command(command_type, parameters)
