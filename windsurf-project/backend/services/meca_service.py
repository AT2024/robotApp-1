"""
Mecademic robot service - Specialized service for Mecademic robot operations.
Handles precise positioning, wafer manipulation, and carousel interactions.
"""

import asyncio
import copy
import math
import time
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum

from core.state_manager import AtomicStateManager, RobotState
from core.resource_lock import ResourceLockManager
from core.async_robot_wrapper import AsyncRobotWrapper, MovementCommand
from core.circuit_breaker import circuit_breaker
from core.settings import RoboticsSettings
from core.exceptions import HardwareError, ValidationError, ResourceLockTimeout
from .base import RobotService, ServiceResult, OperationContext
from .wafer_config_manager import WaferConfigManager, ConfigurationError
from utils.logger import get_logger


class MecaOperationType(Enum):
    """Types of Mecademic operations"""
    PICKUP_WAFER = "pickup_wafer"
    DROP_WAFER = "drop_wafer"
    MOVE_TO_POSITION = "move_to_position"
    CAROUSEL_OPERATION = "carousel_operation"
    CALIBRATION = "calibration"
    GRIPPER_CONTROL = "gripper_control"


@dataclass
class WaferPosition:
    """Represents a wafer position with coordinates"""
    x: float
    y: float
    z: float
    alpha: float = 0.0
    beta: float = 0.0
    gamma: float = 0.0
    slot_id: Optional[str] = None


@dataclass
class CarouselPosition:
    """Represents a carousel position"""
    position_index: int
    coordinates: WaferPosition
    occupied: bool = False
    wafer_id: Optional[str] = None


class MecaService(RobotService):
    """
    Service for Mecademic robot operations.
    
    Provides high-level operations for wafer handling, precise positioning,
    and carousel interactions with proper resource locking and error handling.
    """
    
    def __init__(
        self,
        robot_id: str,
        settings: RoboticsSettings,
        state_manager: AtomicStateManager,
        lock_manager: ResourceLockManager,
        async_wrapper: AsyncRobotWrapper
    ):
        super().__init__(
            robot_id=robot_id,
            robot_type="meca",
            settings=settings,
            state_manager=state_manager,
            lock_manager=lock_manager,
            service_name="MecaService"
        )
        
        self.logger = get_logger("meca_service")
        
        self.async_wrapper = async_wrapper
        self.robot_config = settings.get_robot_config("meca")
        
        # Set settings reference on driver for debug logging
        if hasattr(self.async_wrapper, 'robot_driver') and hasattr(self.async_wrapper.robot_driver, 'set_settings'):
            self.async_wrapper.robot_driver.set_settings(settings)
        
        # Movement parameters from config
        self.movement_params = self.robot_config.get("movement_params", {})

        # Initialize WaferConfigManager for sequence configuration
        try:
            self.wafer_config_manager = WaferConfigManager(
                robot_config=self.robot_config,
                movement_params=self.movement_params
            )
            self.logger.info(f"WaferConfigManager initialized - version {self.wafer_config_manager.config_version}")
        except ConfigurationError as e:
            self.logger.error(f"Failed to initialize WaferConfigManager: {e}")
            raise

        # Position constants from settings (externalized from Meca_FullCode.py)
        positions = self.robot_config.get("positions", {})
        self.FIRST_WAFER = positions.get("first_wafer", [173.562, -175.178, 27.9714, 109.5547, 0.2877, -90.059])
        self.GAP_WAFERS = self.movement_params.get("gap_wafers", 2.7)  # Distance between wafers in each tray
        
        # Spreading Machine locations (from location closest to inert tray to furthest)
        gen_drop_positions = positions.get("gen_drop", [])
        self.GEN_DROP = gen_drop_positions if gen_drop_positions else [
            [130.2207, 159.230, 123.400, 179.7538, -0.4298, -89.9617],   # 5
            [85.5707, 159.4300, 123.400, 179.7538, -0.4298, -89.6617],   # 4
            [41.0207, 159.4300, 123.400, 179.7538, -0.4298, -89.6617],   # 3
            [-3.5793, 159.3300, 123.400, 179.7538, -0.4298, -89.6617],   # 2
            [-47.9793, 159.2300, 123.400, 179.7538, -0.4298, -89.6617]   # 1
        ]
        
        # From baking tray to carousel
        self.FIRST_BAKING_TRAY = positions.get("first_baking", [-141.6702, -170.5871, 27.9420, -178.2908, -69.0556, 1.7626])
        
        # Carousel location
        self.CAROUSEL = positions.get("carousel", [133.8, -247.95, 101.9, 90, 0, -90])
        
        # Safe points and special locations
        self.SAFE_POINT = positions.get("safe_point", [135, -17.6177, 160, 123.2804, 40.9554, -101.3308])
        self.CAROUSEL_SAFEPOINT = positions.get("carousel_safe", [25.567, -202.630, 179.700, 90.546, 0.866, -90.882])
        self.T_PHOTOGATE = positions.get("t_photogate", [53.8, -217.2, 94.9, 90, 0, -90])
        self.C_PHOTOGATE = positions.get("c_photogate", [84.1, -217.2, 94.9, 90, 0, -90])
        
        # Movement parameters from settings (externalized from Meca_FullCode.py)
        self.ACC = self.movement_params.get("acceleration", 50.0)  # Acceleration - percentage of max
        self.EMPTY_SPEED = self.movement_params.get("empty_speed", 50.0)  # Speed when the robot is empty
        self.SPREAD_WAIT = self.movement_params.get("spread_wait", 2.0)  # Waiting time for spreading
        self.WAFER_SPEED = self.movement_params.get("wafer_speed", 35.0)  # Speed when carrying a wafer
        self.SPEED = self.movement_params.get("speed", 35.0)  # General Speed
        self.ALIGN_SPEED = self.movement_params.get("align_speed", 20.0)  # Speed when aligning to something
        self.ENTRY_SPEED = self.movement_params.get("entry_speed", 15.0)  # Carousel entry speed
        self.FORCE = self.movement_params.get("force", 100.0)  # Gripper Force
        self.CLOSE_WIDTH = self.movement_params.get("close_width", 1.0)  # Width to close the grippers to
        
        # Predefined positions (converted from lists to WaferPosition objects)
        self.safe_position = WaferPosition(x=self.SAFE_POINT[0], y=self.SAFE_POINT[1], z=self.SAFE_POINT[2],
                                         alpha=self.SAFE_POINT[3], beta=self.SAFE_POINT[4], gamma=self.SAFE_POINT[5])
        self.carousel_safe_position = WaferPosition(x=self.CAROUSEL_SAFEPOINT[0], y=self.CAROUSEL_SAFEPOINT[1], z=self.CAROUSEL_SAFEPOINT[2],
                                                  alpha=self.CAROUSEL_SAFEPOINT[3], beta=self.CAROUSEL_SAFEPOINT[4], gamma=self.CAROUSEL_SAFEPOINT[5])
        
        # Carousel configuration
        self.carousel_positions: List[CarouselPosition] = []
        self._initialize_carousel_positions()
        
        # Gripper state
        self._gripper_open = True
        
        # Position tracking for auto-reset enhancement
        self._last_known_position: Optional[WaferPosition] = None
        self._position_captured = False
        self._auto_reset_enabled = False  # Disabled by default now
        
        # Exponential backoff for reconnection attempts
        self._reconnect_attempt_count = 0
        self._next_reconnect_time = 0.0
        self._base_reconnect_delay = 1.0  # Start with 1 second
        self._max_reconnect_delay = 30.0  # Maximum 30 seconds
        self._max_reconnect_attempts = 10  # Maximum attempts before giving up
    
    @circuit_breaker("meca_check_connection", failure_threshold=3, recovery_timeout=10)
    async def _check_robot_connection(self) -> bool:
        """Check robot connection, attempting reconnection if needed."""
        try:
            await self._test_robot_connection()

            if not hasattr(self.async_wrapper, 'robot_driver'):
                return True

            driver = self.async_wrapper.robot_driver
            robot_instance = driver.get_robot_instance() if hasattr(driver, 'get_robot_instance') else None

            if not robot_instance:
                # No robot instance - attempt reconnection if not in backoff
                if time.time() >= self._next_reconnect_time:
                    reconnected = await self._attempt_robot_reconnection()
                    if reconnected:
                        self.logger.info(f"Successfully reconnected to robot {self.robot_id}")
                        return True
                # Return False - TCP works but no mecademicpy connection
                return False

            return True
        except Exception as e:
            self.logger.debug(f"Connection check failed: {e}")
            return False

    @circuit_breaker("meca_reconnection", failure_threshold=2, recovery_timeout=5)
    async def _attempt_robot_reconnection(self) -> bool:
        """Attempt reconnection with exponential backoff."""
        if not hasattr(self.async_wrapper, 'robot_driver'):
            self._schedule_next_reconnect_attempt("No driver")
            return False

        driver = self.async_wrapper.robot_driver
        self.logger.info(f"Reconnection attempt {self._reconnect_attempt_count + 1} for {self.robot_id}")

        try:
            if await driver.connect():
                self._reset_reconnect_backoff()
                await self.update_robot_state(RobotState.IDLE, reason="Reconnected")
                self.logger.info(f"Reconnected to {self.robot_id}")
                return True

            self._schedule_next_reconnect_attempt("Connection failed")
            return False

        except Exception as e:
            self._schedule_next_reconnect_attempt(str(e)[:50])
            return False

    def _reset_reconnect_backoff(self) -> None:
        """Reset exponential backoff state."""
        self._reconnect_attempt_count = 0
        self._next_reconnect_time = 0.0

    def _schedule_next_reconnect_attempt(self, reason: str) -> None:
        """Schedule next reconnection attempt with exponential backoff."""
        self._reconnect_attempt_count = min(self._reconnect_attempt_count + 1, self._max_reconnect_attempts - 1)
        delay = min(self._base_reconnect_delay * (2 ** (self._reconnect_attempt_count - 1)), self._max_reconnect_delay)
        self._next_reconnect_time = time.time() + delay
        self.logger.debug(f"Next reconnect in {delay:.1f}s: {reason}")

    async def _handle_connection_state_change(self, is_connected: bool) -> None:
        """Handle robot connection state changes."""
        state = RobotState.IDLE if is_connected else RobotState.ERROR
        reason = "Connection restored" if is_connected else "Connection lost"
        await self.update_robot_state(state, reason=reason)
        self.logger.info(f"Robot {self.robot_id}: {reason}")
        await self._broadcast_robot_state_change(is_connected)
    
    async def _broadcast_message(self, message_type_str: str, data: Dict[str, Any]) -> bool:
        """Broadcast message to WebSocket clients. Returns True on success."""
        try:
            from websocket.selective_broadcaster import get_broadcaster, MessageType
            broadcaster = await get_broadcaster()
            msg_type = MessageType.ROBOT_STATUS if message_type_str == "robot_status" else MessageType.OPERATION_UPDATE
            data["robot_id"] = self.robot_id
            data["timestamp"] = time.time()
            return await broadcaster.broadcast_message(message_type=msg_type, data=data, robot_id=self.robot_id) or True
        except Exception as e:
            self.logger.warning(f"Broadcast failed: {e}")
            return False

    async def _broadcast_robot_state_change(self, is_connected: bool) -> None:
        """Broadcast robot state change to WebSocket clients."""
        await self._broadcast_message("robot_status", {
            "type": "robot_status",
            "robot_type": self.robot_type,
            "connected": is_connected,
            "robot_state": "idle" if is_connected else "error",
            "operational": is_connected
        })

    async def _broadcast_batch_completion(self, operation_type: str, start: int, count: int, result: Dict[str, Any]) -> bool:
        """Broadcast batch completion event to WebSocket clients."""
        success = await self._broadcast_message("operation", {
            "event": "batch_completion",
            "operation_type": operation_type,
            "batch_start": start,
            "batch_count": count,
            "wafers_processed": result.get("wafers_processed", 0),
            "wafers_failed": result.get("wafers_failed", []),
            "success_rate": result.get("success_rate", "0%"),
            "status": result.get("status", "completed")
        })
        self.logger.debug(f"Batch completion broadcast: {operation_type} wafers {start+1}-{start+count}")
        return success

    async def _broadcast_wafer_progress(self, operation_type: str, wafer_num: int, wafer_index: int, batch_start: int, batch_count: int) -> None:
        """Broadcast wafer progress event to WebSocket clients."""
        await self._broadcast_message("operation", {
            "event": "wafer_progress",
            "operation_type": operation_type,
            "wafer_num": wafer_num,
            "wafer_index": wafer_index,
            "batch_start": batch_start,
            "batch_count": batch_count
        })

    async def _on_start(self) -> None:
        """Initialize Meca robot connection on service start."""
        await super()._on_start()

        await self.update_robot_state(RobotState.CONNECTING, reason="Attempting to connect to Meca robot")

        # Test TCP connection first
        tcp_ok = await self._test_tcp_connection_safe()
        if not tcp_ok:
            await self._handle_startup_failure("TCP connection failed")
            return

        self.logger.info(f"TCP connection test successful for {self.robot_id}")

        # Attempt full robot connection
        connected = await self._attempt_startup_connection()
        if not connected:
            await self._handle_startup_failure("Robot connection failed during startup")
            return

        self._reset_reconnect_backoff()
        self.logger.info(f"Robot {self.robot_id} successfully connected")

        await self.capture_current_position()
        await self.update_robot_state(RobotState.IDLE, reason="Meca robot service started and connected")
        self.logger.info(f"Meca robot service started successfully for {self.robot_id}")

    async def _test_tcp_connection_safe(self) -> bool:
        """Test TCP connection, returning False on failure instead of raising."""
        try:
            await self._test_robot_connection()
            return True
        except Exception as e:
            self.logger.error(f"TCP connection test failed for {self.robot_id}: {e}")
            return False

    async def _attempt_startup_connection(self) -> bool:
        """Attempt to establish full robot connection during startup."""
        if not hasattr(self.async_wrapper, 'robot_driver'):
            self.logger.error(f"No robot_driver available for {self.robot_id}")
            return False

        driver = self.async_wrapper.robot_driver
        try:
            connected = await driver.connect()
            if not connected:
                self.logger.error(f"Robot connection returned False for {self.robot_id}")
            return connected
        except Exception as e:
            self.logger.error(f"Robot connection failed for {self.robot_id}: {e}")
            return False

    async def _handle_startup_failure(self, reason: str) -> None:
        """Handle startup failure by setting error state."""
        self.logger.error(f"Startup failure for {self.robot_id}: {reason}")
        try:
            await self.update_robot_state(RobotState.ERROR, reason=reason)
        except Exception as e:
            self.logger.error(f"Could not update robot state: {e}")
    
    async def _on_stop(self):
        """Clean up Meca robot connection on service stop"""
        try:
            # Update robot state to disconnected
            await self.update_robot_state(
                RobotState.DISCONNECTED,
                reason="Service stopping"
            )
            
            # Shutdown the async wrapper
            if self.async_wrapper:
                await self.async_wrapper.shutdown()
                
            self.logger.info("Meca robot service stopped")
            
        except Exception as e:
            self.logger.error(f"Error stopping Meca robot service: {e}")
    
    @circuit_breaker("meca_tcp_test", failure_threshold=3, recovery_timeout=10)
    async def _test_robot_connection(self):
        """Test if robot connection is working using real TCP connection"""
        try:
            # Get robot configuration from settings
            meca_ip = self.settings.meca_ip
            meca_port = self.settings.meca_port
            connection_timeout = 5.0  # Short timeout for connection test
            
            # Attempt TCP connection to robot
            reader = None
            writer = None
            try:
                reader, writer = await asyncio.wait_for(
                    asyncio.open_connection(meca_ip, meca_port),
                    timeout=connection_timeout
                )
                
                # Connection successful, close it immediately
                if writer:
                    writer.close()
                    await writer.wait_closed()
                    
                self.logger.info(f"Meca robot TCP connection test successful to {meca_ip}:{meca_port}")
                return True
                
            except asyncio.TimeoutError:
                raise HardwareError(
                    f"Connection timeout to Meca robot at {meca_ip}:{meca_port}",
                    robot_id=self.robot_id
                )
            except ConnectionRefusedError:
                raise HardwareError(
                    f"Connection refused by Meca robot at {meca_ip}:{meca_port}",
                    robot_id=self.robot_id
                )
            except OSError as e:
                # Network unreachable, host unreachable, etc.
                raise HardwareError(
                    f"Network error connecting to Meca robot at {meca_ip}:{meca_port}: {e}",
                    robot_id=self.robot_id
                )
            
        except HardwareError:
            # Re-raise hardware errors as-is
            raise
        except Exception as e:
            raise HardwareError(
                f"Unexpected error testing Meca robot connection: {str(e)}",
                robot_id=self.robot_id
            )
    
    def _initialize_carousel_positions(self):
        """Initialize carousel position mappings"""
        # This would typically be loaded from configuration
        base_x, base_y, base_z = 100, 100, 50
        
        for i in range(24):  # 24 positions in carousel
            angle = (i * 15) * 3.14159 / 180  # 15 degrees per position
            radius = 80
            
            x = base_x + radius * math.cos(angle)
            y = base_y + radius * math.sin(angle)
            
            position = CarouselPosition(
                position_index=i,
                coordinates=WaferPosition(x=x, y=y, z=base_z)
            )
            self.carousel_positions.append(position)
    
    @circuit_breaker("meca_robot_ready", failure_threshold=4, recovery_timeout=20)
    async def ensure_robot_ready(self, allow_busy: bool = True) -> bool:
        """
        Ensure robot is ready for operations by verifying hardware state.

        Checks software state and hardware state (activated/homed), performing
        necessary recovery steps (error reset, activation, homing) as needed.

        Args:
            allow_busy: Whether to allow BUSY state

        Returns:
            True if robot is ready

        Raises:
            ValidationError: If robot is not in valid state
            HardwareError: If hardware activation/homing fails
        """
        await super().ensure_robot_ready(allow_busy)

        if not hasattr(self.async_wrapper, 'robot_driver'):
            self.logger.warning(f"No robot driver for {self.robot_id} - skipping hardware check")
            return True

        driver = self.async_wrapper.robot_driver

        # Ensure robot instance is available
        await self._ensure_robot_instance(driver)

        # Get and process robot status
        status = await driver.get_status()
        self.logger.debug(f"Robot {self.robot_id} state: {status}")

        # Step 1: Reset errors if present
        if status.get('error_status', False):
            status = await self._reset_robot_error(driver)

        # Step 2: Activate if needed
        if not status.get('activation_status', False):
            await self._activate_robot_with_retry(driver)

        # Step 3: Resume if paused before homing
        if status.get('paused', False) and not status.get('homing_status', False):
            await self._resume_motion_safe(driver)
            status = await driver.get_status()

        # Step 4: Home if needed
        if not status.get('homing_status', False):
            await self._home_robot_with_retry(driver)

        # Step 5: Clear motion queue and resume after homing
        await self._prepare_motion_after_homing(driver)

        # Final verification
        final_status = await driver.get_status()

        # Handle any lingering error state
        if final_status.get('error_status', False):
            await self._reset_robot_error(driver)
            final_status = await driver.get_status()

        # Ensure not paused
        if final_status.get('paused', False):
            await self._resume_paused_robot(driver)
            final_status = await driver.get_status()

        # Verify final state
        if not final_status.get('activation_status') or not final_status.get('homing_status'):
            raise HardwareError(
                f"Robot {self.robot_id} not ready: activated={final_status.get('activation_status')}, "
                f"homed={final_status.get('homing_status')}",
                robot_id=self.robot_id
            )

        self.logger.info(f"Robot {self.robot_id} ready for operations")
        return True

    async def _ensure_robot_instance(self, driver) -> None:
        """Ensure robot instance is available, connecting if needed."""
        robot_instance = driver.get_robot_instance() if hasattr(driver, 'get_robot_instance') else None
        if robot_instance:
            return

        self.logger.info(f"No robot instance for {self.robot_id} - connecting")
        if not await driver.connect():
            raise HardwareError(f"Failed to connect robot {self.robot_id}", robot_id=self.robot_id)

        robot_instance = driver.get_robot_instance() if hasattr(driver, 'get_robot_instance') else None
        if not robot_instance:
            raise HardwareError(f"Robot instance unavailable after connect for {self.robot_id}", robot_id=self.robot_id)

        if hasattr(driver, 'clear_status_cache'):
            driver.clear_status_cache()

    async def _reset_robot_error(self, driver) -> Dict[str, Any]:
        """Reset robot error state and return fresh status."""
        self.logger.info(f"Resetting error for {self.robot_id}")
        if not await driver.reset_error():
            raise HardwareError(f"Failed to reset error for {self.robot_id}", robot_id=self.robot_id)
        await asyncio.sleep(2.0)
        return await driver.get_status()

    async def _activate_robot_with_retry(self, driver, max_retries: int = 3) -> None:
        """Activate robot with exponential backoff retry."""
        self.logger.info(f"Activating {self.robot_id}")

        for attempt in range(max_retries):
            if attempt > 0:
                delay = 1.0 * (2 ** (attempt - 1))
                self.logger.info(f"Activation retry {attempt} for {self.robot_id} after {delay}s")
                await asyncio.sleep(delay)

            try:
                await driver.activate_robot()
                await asyncio.sleep(2.0)

                status = await driver.get_status()
                if status.get('activation_status', False):
                    self.logger.info(f"Activation verified for {self.robot_id}")
                    return

                if attempt == max_retries - 1:
                    raise HardwareError(f"Activation failed for {self.robot_id} after {max_retries} attempts", robot_id=self.robot_id)

            except HardwareError:
                raise
            except Exception as e:
                if attempt == max_retries - 1 or not self._is_transient_error(e):
                    raise HardwareError(f"Activation failed for {self.robot_id}: {e}", robot_id=self.robot_id)

    async def _home_robot_with_retry(self, driver, max_retries: int = 3) -> None:
        """Home robot with exponential backoff retry."""
        self.logger.info(f"Homing {self.robot_id}")

        for attempt in range(max_retries):
            if attempt > 0:
                delay = 2.0 * (2 ** (attempt - 1))
                self.logger.info(f"Homing retry {attempt} for {self.robot_id} after {delay}s")
                await asyncio.sleep(delay)

            try:
                await driver.home_robot()
                await driver.wait_idle(timeout=30.0)

                status = await driver.get_status()
                if status.get('homing_status', False):
                    self.logger.info(f"Homing verified for {self.robot_id}")
                    return

                if attempt == max_retries - 1:
                    raise HardwareError(f"Homing failed for {self.robot_id} after {max_retries} attempts", robot_id=self.robot_id)

            except HardwareError:
                raise
            except Exception as e:
                if attempt == max_retries - 1 or not self._is_transient_error(e):
                    raise HardwareError(f"Homing failed for {self.robot_id}: {e}", robot_id=self.robot_id)

    async def _prepare_motion_after_homing(self, driver) -> None:
        """Clear motion queue and resume motion after homing."""
        if hasattr(driver, 'clear_status_cache'):
            driver.clear_status_cache()

        try:
            await driver.clear_motion()
            await driver.resume_motion()
            self.logger.debug(f"Motion prepared for {self.robot_id}")
        except Exception as e:
            self.logger.warning(f"Motion preparation warning for {self.robot_id}: {e}")

    async def _resume_motion_safe(self, driver) -> None:
        """Safely resume motion, handling failures gracefully."""
        try:
            await driver.resume_motion()
            await asyncio.sleep(1.0)
        except Exception as e:
            self.logger.warning(f"Resume motion warning for {self.robot_id}: {e}")

    async def _resume_paused_robot(self, driver) -> None:
        """Resume paused robot, handling socket closure with reconnection."""
        self.logger.info(f"Resuming paused {self.robot_id}")

        try:
            robot_instance = driver.get_robot_instance() if hasattr(driver, 'get_robot_instance') else None
            if robot_instance and hasattr(robot_instance, 'ResumeMotion'):
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, robot_instance.ResumeMotion)
                await asyncio.sleep(1.0)

                status = await driver.get_status()
                if status.get('paused', False):
                    raise HardwareError(f"Robot {self.robot_id} still paused after resume", robot_id=self.robot_id)
                return

        except Exception as e:
            if "Socket was closed" in str(e) or "DisconnectError" in type(e).__name__:
                await self._reconnect_after_socket_closure(driver)
            else:
                raise HardwareError(f"Failed to resume {self.robot_id}: {e}", robot_id=self.robot_id)

    async def _reconnect_after_socket_closure(self, driver) -> None:
        """Reconnect robot after socket closure (e.g., collision aftermath)."""
        self.logger.info(f"Reconnecting {self.robot_id} after socket closure")

        await driver.disconnect()
        await asyncio.sleep(3.0)

        if not await driver.connect():
            raise HardwareError(f"Reconnection failed for {self.robot_id}", robot_id=self.robot_id)

        await asyncio.sleep(2.0)

        status = await driver.get_status()
        if status.get('paused', False):
            robot_instance = driver.get_robot_instance()
            if robot_instance and hasattr(robot_instance, 'ResumeMotion'):
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, robot_instance.ResumeMotion)

    def _is_transient_error(self, error: Exception) -> bool:
        """Check if error is transient and retryable."""
        error_str = str(error).lower()
        return any(x in error_str for x in ["socket was closed", "connection", "timeout"])
    
    def calculate_wafer_position(self, wafer_index: int, tray_type: str) -> List[float]:
        """
        Calculate exact wafer position based on wafer index and tray type.
        
        Args:
            wafer_index: Wafer index (0-54 for wafers 1-55)
            tray_type: Type of tray ('inert', 'baking', 'carousel')
            
        Returns:
            List of 6 coordinates [x, y, z, alpha, beta, gamma]
        """
        if tray_type == "inert":
            base_position = copy.deepcopy(self.FIRST_WAFER)
            base_position[1] += self.GAP_WAFERS * wafer_index
            return base_position
        elif tray_type == "baking":
            base_position = copy.deepcopy(self.FIRST_BAKING_TRAY)
            base_position[0] += self.GAP_WAFERS * wafer_index
            return base_position
        elif tray_type == "carousel":
            return copy.deepcopy(self.CAROUSEL)
        else:
            raise ValidationError(f"Unknown tray type: {tray_type}")
    
    def calculate_intermediate_positions(self, wafer_index: int, operation: str) -> Dict[str, List[float]]:
        """
        Calculate intermediate positions for safe movement during wafer operations.
        All offset values are loaded from runtime.json via WaferConfigManager.

        Args:
            wafer_index: Wafer index (0-54 for wafers 1-55)
            operation: Operation type ('pickup', 'drop', 'carousel', 'empty_carousel')

        Returns:
            Dictionary of position names to coordinate lists
        """
        positions = {}

        # Get wafer-specific config (for effective_gap)
        wafer_config = self.wafer_config_manager.get_wafer_config(wafer_index)
        effective_gap = wafer_config.effective_gap

        # Helper to get offset from config
        def get_offset(offset_name: str) -> float:
            return self.wafer_config_manager.get_offset(operation, offset_name, wafer_index)

        if operation == "pickup":
            # High point above pickup position
            pickup_pos = self.calculate_wafer_position(wafer_index, "inert")
            high_point = copy.deepcopy(pickup_pos)
            high_point[1] += get_offset("pickup_high_y")
            high_point[2] += get_offset("pickup_high_z")
            positions["pickup_high"] = high_point

            # Intermediate movement positions
            intermediate_pos1 = copy.deepcopy(self.FIRST_WAFER)
            intermediate_pos1[1] += effective_gap * wafer_index + get_offset("intermediate_1_y")
            intermediate_pos1[2] += get_offset("intermediate_1_z")
            positions["intermediate_1"] = intermediate_pos1

            intermediate_pos2 = copy.deepcopy(intermediate_pos1)
            intermediate_pos2[1] += get_offset("intermediate_2_y")
            intermediate_pos2[2] += get_offset("intermediate_2_z")
            positions["intermediate_2"] = intermediate_pos2

            intermediate_pos3 = copy.deepcopy(intermediate_pos2)
            intermediate_pos3[1] += get_offset("intermediate_3_y")
            intermediate_pos3[2] += get_offset("intermediate_3_z")
            positions["intermediate_3"] = intermediate_pos3

            # Spreader positions
            spread_index = 4 - (wafer_index % 5)
            above_spreader = copy.deepcopy(self.GEN_DROP[spread_index])
            above_spreader[2] += get_offset("above_spreader_z")
            positions["above_spreader"] = above_spreader

            spreader = copy.deepcopy(self.GEN_DROP[spread_index])
            positions["spreader"] = spreader

            above_spreader_exit = copy.deepcopy(self.GEN_DROP[spread_index])
            above_spreader_exit[2] += get_offset("above_spreader_exit_z")
            positions["above_spreader_exit"] = above_spreader_exit

        elif operation == "drop":
            # Drop sequence positions from spreader to baking tray
            spread_index = 4 - (wafer_index % 5)
            above_spreader = copy.deepcopy(self.GEN_DROP[spread_index])
            above_spreader[2] += get_offset("above_spreader_z")
            positions["above_spreader"] = above_spreader

            spreader = copy.deepcopy(self.GEN_DROP[spread_index])
            positions["spreader"] = spreader

            above_spreader_pickup = copy.deepcopy(self.GEN_DROP[spread_index])
            above_spreader_pickup[2] += get_offset("above_spreader_pickup_z")
            positions["above_spreader_pickup"] = above_spreader_pickup

            # Baking tray alignment positions
            baking_align1 = copy.deepcopy(self.FIRST_BAKING_TRAY)
            baking_align1[0] += effective_gap * wafer_index + get_offset("baking_align1_x")
            baking_align1[1] += get_offset("baking_align1_y")
            baking_align1[2] += get_offset("baking_align1_z")
            positions["baking_align1"] = baking_align1

            baking_align2 = copy.deepcopy(self.FIRST_BAKING_TRAY)
            baking_align2[0] += effective_gap * wafer_index + get_offset("baking_align2_x")
            baking_align2[1] += get_offset("baking_align2_y")
            baking_align2[2] += get_offset("baking_align2_z")
            positions["baking_align2"] = baking_align2

            baking_align3 = copy.deepcopy(self.FIRST_BAKING_TRAY)
            baking_align3[0] += effective_gap * wafer_index + get_offset("baking_align3_x")
            baking_align3[1] += get_offset("baking_align3_y")
            baking_align3[2] += get_offset("baking_align3_z")
            positions["baking_align3"] = baking_align3

            baking_align4 = copy.deepcopy(self.FIRST_BAKING_TRAY)
            baking_align4[0] += effective_gap * wafer_index + get_offset("baking_align4_x")
            baking_align4[1] += get_offset("baking_align4_y")
            baking_align4[2] += get_offset("baking_align4_z")
            positions["baking_align4"] = baking_align4

            baking_up = copy.deepcopy(self.FIRST_BAKING_TRAY)
            baking_up[0] += effective_gap * wafer_index
            baking_up[2] += get_offset("baking_up_z")
            positions["baking_up"] = baking_up

        elif operation == "carousel":
            # Carousel movement positions
            above_baking = copy.deepcopy(self.FIRST_BAKING_TRAY)
            above_baking[0] += effective_gap * wafer_index
            above_baking[2] += get_offset("above_baking_z")
            positions["above_baking"] = above_baking

            # Movement sequence positions
            move1 = copy.deepcopy(self.FIRST_BAKING_TRAY)
            move1[0] += effective_gap * wafer_index + get_offset("move1_x")
            move1[2] += get_offset("move1_z")
            positions["move1"] = move1

            move2 = copy.deepcopy(self.FIRST_BAKING_TRAY)
            move2[0] += effective_gap * wafer_index + get_offset("move2_x")
            move2[2] += get_offset("move2_z")
            positions["move2"] = move2

            move3 = copy.deepcopy(self.FIRST_BAKING_TRAY)
            move3[0] += effective_gap * wafer_index + get_offset("move3_x")
            move3[2] += get_offset("move3_z")
            positions["move3"] = move3

            move4 = copy.deepcopy(self.FIRST_BAKING_TRAY)
            move4[0] += effective_gap * wafer_index + get_offset("move4_x")
            move4[2] += get_offset("move4_z")
            positions["move4"] = move4

            # Carousel approach positions
            y_away1 = copy.deepcopy(self.CAROUSEL)
            y_away1[1] = get_offset("y_away1_y")
            y_away1[2] = get_offset("y_away1_z")
            positions["y_away1"] = y_away1

            y_away2 = copy.deepcopy(self.CAROUSEL)
            y_away2[1] = get_offset("y_away2_y")
            y_away2[2] = get_offset("y_away2_z")
            positions["y_away2"] = y_away2

            above_carousel1 = copy.deepcopy(self.CAROUSEL)
            above_carousel1[2] = get_offset("above_carousel1_z")
            positions["above_carousel1"] = above_carousel1

            above_carousel2 = copy.deepcopy(self.CAROUSEL)
            above_carousel2[2] = get_offset("above_carousel2_z")
            positions["above_carousel2"] = above_carousel2

            above_carousel3 = copy.deepcopy(self.CAROUSEL)
            above_carousel3[2] = get_offset("above_carousel3_z")
            positions["above_carousel3"] = above_carousel3

        elif operation == "empty_carousel":
            # Empty carousel positions (reverse of carousel)
            y_away1 = copy.deepcopy(self.CAROUSEL)
            y_away1[1] = get_offset("y_away1_y")
            y_away1[2] = get_offset("y_away1_z")
            positions["y_away1"] = y_away1

            y_away2 = copy.deepcopy(self.CAROUSEL)
            y_away2[1] = get_offset("y_away2_y")
            y_away2[2] = get_offset("y_away2_z")
            positions["y_away2"] = y_away2

            above_carousel = copy.deepcopy(self.CAROUSEL)
            above_carousel[2] = get_offset("above_carousel_z")
            positions["above_carousel"] = above_carousel

            # Reverse movement positions for baking tray
            # Note: empty_carousel uses carousel offsets for move positions
            move4_rev = copy.deepcopy(self.FIRST_BAKING_TRAY)
            move4_rev[0] += effective_gap * wafer_index + self.wafer_config_manager.get_offset("carousel", "move4_x", wafer_index)
            move4_rev[1] += get_offset("move_rev_y")
            move4_rev[2] += self.wafer_config_manager.get_offset("carousel", "move4_z", wafer_index)
            positions["move4_rev"] = move4_rev

            move3_rev = copy.deepcopy(self.FIRST_BAKING_TRAY)
            move3_rev[0] += effective_gap * wafer_index + self.wafer_config_manager.get_offset("carousel", "move3_x", wafer_index)
            move3_rev[1] += get_offset("move_rev_y")
            move3_rev[2] += self.wafer_config_manager.get_offset("carousel", "move3_z", wafer_index)
            positions["move3_rev"] = move3_rev

            move2_rev = copy.deepcopy(self.FIRST_BAKING_TRAY)
            move2_rev[0] += effective_gap * wafer_index + self.wafer_config_manager.get_offset("carousel", "move2_x", wafer_index)
            move2_rev[1] += get_offset("move_rev_y")
            move2_rev[2] += self.wafer_config_manager.get_offset("carousel", "move2_z", wafer_index)
            positions["move2_rev"] = move2_rev

            move1_rev = copy.deepcopy(self.FIRST_BAKING_TRAY)
            move1_rev[0] += effective_gap * wafer_index + self.wafer_config_manager.get_offset("carousel", "move1_x", wafer_index)
            move1_rev[1] += get_offset("move_rev_y")
            move1_rev[2] += self.wafer_config_manager.get_offset("carousel", "move1_z", wafer_index)
            positions["move1_rev"] = move1_rev

            above_baking_rev = copy.deepcopy(self.FIRST_BAKING_TRAY)
            above_baking_rev[0] += effective_gap * wafer_index
            above_baking_rev[2] += get_offset("above_baking_rev_z")
            positions["above_baking_rev"] = above_baking_rev

        return positions
    
    async def capture_current_position(self) -> ServiceResult[WaferPosition]:
        """
        Capture and store the robot's current position.
        Called on connection to store last known position.
        """
        try:
            # Get current position from robot
            if hasattr(self.async_wrapper.robot_driver, 'GetRobotRtData'):
                # Mecademic specific position query
                command = MovementCommand(
                    command_type="get_position",
                    parameters={}
                )
                result = await self.async_wrapper.execute_movement(command)
                
                if result and 'position' in result:
                    position_data = result['position']
                    self._last_known_position = WaferPosition(
                        x=float(position_data.get('x', 0)),
                        y=float(position_data.get('y', 0)), 
                        z=float(position_data.get('z', 0))
                    )
                    self._position_captured = True
                    
                    self.logger.info(
                        f"Captured current position: {self._last_known_position}"
                    )
                    
                    return ServiceResult.success_result(self._last_known_position)
                else:
                    # Fallback to safe position if unable to get current position
                    self._last_known_position = self.safe_position
                    self._position_captured = True
                    
                    self.logger.warning(
                        "Unable to get current position, using safe position as fallback"
                    )
                    
                    return ServiceResult.success_result(self._last_known_position)
            else:
                # Robot driver doesn't support position query
                self._last_known_position = self.safe_position
                self._position_captured = True
                
                return ServiceResult.success_result(self._last_known_position)
                
        except Exception as e:
            self.logger.error(f"Failed to capture current position: {e}")
            # Use safe position as fallback
            self._last_known_position = self.safe_position
            self._position_captured = True
            
            return ServiceResult.error_result(
                error=f"Position capture failed: {str(e)}",
                error_code="POSITION_CAPTURE_FAILED"
            )
    
    async def controlled_homing_sequence(self, force_homing: bool = False) -> ServiceResult[Dict[str, Any]]:
        """
        Perform controlled homing sequence instead of automatic reset.
        
        Args:
            force_homing: If True, perform full homing. If False, only home if needed.
        """
        context = OperationContext(
            operation_id=f"{self.robot_id}_controlled_homing_{int(time.time() * 1000)}",
            robot_id=self.robot_id,
            operation_type="controlled_homing",
            timeout=120.0  # 2 minutes for homing
        )
        
        async def _homing_sequence():
            await self.ensure_robot_ready()
            
            try:
                homing_results = {}
                
                # Check if homing is needed
                if not force_homing and self._position_captured:
                    # Check if robot is already in a known good state
                    if hasattr(self.async_wrapper.robot_driver, 'GetStatusRobot'):
                        status_command = MovementCommand(
                            command_type="get_status",
                            parameters={}
                        )
                        status_result = await self.async_wrapper.execute_movement(status_command)
                        
                        if (status_result and 
                            status_result.get('homed', False) and 
                            not status_result.get('error', False)):
                            
                            self.logger.info("Robot already homed and in good state, skipping homing")
                            homing_results['homing_skipped'] = True
                            homing_results['reason'] = 'already_homed'
                            
                            return homing_results
                
                # Perform controlled homing sequence
                self.logger.info("Starting controlled homing sequence...")
                
                # Step 1: Move to safe position first if we have a known position
                if self._last_known_position and not force_homing:
                    safe_move_command = MovementCommand(
                        command_type="move_to",
                        target_position=(
                            self.safe_position.x,
                            self.safe_position.y, 
                            self.safe_position.z
                        ),
                        parameters={
                            "move_type": "linear",
                            "speed": 25,  # Slow speed for safety
                            "wait_for_completion": True
                        }
                    )
                    await self.async_wrapper.execute_movement(safe_move_command)
                    homing_results['safe_move_completed'] = True
                
                # Step 2: Perform actual homing
                if hasattr(self.async_wrapper.robot_driver, 'Home'):
                    home_command = MovementCommand(
                        command_type="home",
                        parameters={"timeout": 30.0}
                    )
                    await self.async_wrapper.execute_movement(home_command)
                    homing_results['homing_completed'] = True
                    
                    # Wait for homing to complete
                    if hasattr(self.async_wrapper.robot_driver, 'WaitHomed'):
                        wait_command = MovementCommand(
                            command_type="wait_homed",
                            parameters={"timeout": 30.0}
                        )
                        await self.async_wrapper.execute_movement(wait_command)
                        homing_results['homing_verified'] = True
                
                # Step 3: Initialize gripper if needed
                await self._initialize_gripper()
                homing_results['gripper_initialized'] = True
                
                # Update state
                # CommandService handles state management
                
                self.logger.info("Controlled homing sequence completed successfully")
                return homing_results
                
            except Exception as e:
                # CommandService handles error state management
                raise
        
        return await self.execute_operation(context, _homing_sequence)
    
    async def _initialize_gripper(self) -> None:
        """Initialize gripper to known state"""
        try:
            # Open gripper and reset state
            await self._open_gripper()
            self.logger.info("Gripper initialized to open state")
        except Exception as e:
            self.logger.warning(f"Gripper initialization failed: {e}")
    
    def get_last_known_position(self) -> Optional[WaferPosition]:
        """Get the last known position of the robot"""
        return self._last_known_position
    
    def is_position_captured(self) -> bool:
        """Check if position has been captured"""
        return self._position_captured
    
    def enable_auto_reset(self, enabled: bool = True) -> None:
        """Enable or disable auto-reset functionality"""
        self._auto_reset_enabled = enabled
        self.logger.info(f"Auto-reset {'enabled' if enabled else 'disabled'}")
    
    def is_auto_reset_enabled(self) -> bool:
        """Check if auto-reset is enabled"""
        return self._auto_reset_enabled
    
    async def connect(self) -> ServiceResult[bool]:
        """Connect to the Mecademic robot."""
        context = OperationContext(
            operation_id=f"{self.robot_id}_connect_{int(time.time() * 1000)}",
            robot_id=self.robot_id,
            operation_type="connect",
            timeout=self.settings.meca_timeout
        )

        async def _connect():
            await self.update_robot_state(RobotState.CONNECTING, reason="Connecting to robot")

            if not hasattr(self.async_wrapper, 'robot_driver'):
                await self.update_robot_state(RobotState.ERROR, reason="Robot driver not available")
                return False

            driver = self.async_wrapper.robot_driver
            try:
                connected = await driver.connect()
                if not connected:
                    self.logger.error(f"Connection failed for {self.robot_id}")
                    await self.update_robot_state(RobotState.ERROR, reason="Failed to connect")
                    return False

                self._reset_reconnect_backoff()
                await self.capture_current_position()
                await self.update_robot_state(RobotState.IDLE, reason="Connected successfully")
                self.logger.info(f"Robot {self.robot_id} connected and ready")
                return True

            except Exception as e:
                await self.update_robot_state(RobotState.ERROR, reason=f"Connection error: {e}")
                raise

        return await self.execute_operation(context, _connect)
    
    async def disconnect(self) -> ServiceResult[bool]:
        """
        Disconnect from the Mecademic robot.
        
        Returns:
            ServiceResult with disconnection status
        """
        context = OperationContext(
            operation_id=f"{self.robot_id}_disconnect_{int(time.time() * 1000)}",
            robot_id=self.robot_id,
            operation_type="disconnect",
            timeout=10.0
        )
        
        async def _disconnect():
            try:
                # Get the underlying Mecademic driver
                if hasattr(self.async_wrapper, 'robot_driver'):
                    driver = self.async_wrapper.robot_driver
                    
                    # Attempt disconnection
                    disconnected = await driver.disconnect()
                    
                    # Update state to disconnected
                    await self.update_robot_state(
                        RobotState.DISCONNECTED,
                        reason="Disconnected from robot"
                    )
                    
                    self.logger.info(f"Disconnected from robot {self.robot_id}")
                    return disconnected
                else:
                    await self.update_robot_state(
                        RobotState.DISCONNECTED,
                        reason="Robot driver not available"
                    )
                    return True
                    
            except Exception as e:
                self.logger.error(f"Error during disconnection: {e}")
                await self.update_robot_state(
                    RobotState.DISCONNECTED,
                    reason=f"Disconnection error: {str(e)}"
                )
                return False
        
        return await self.execute_operation(context, _disconnect)

    async def connect_safe(self) -> dict:
        """
        Connect to robot WITHOUT automatic homing.
        Returns joint positions for UI confirmation before proceeding.

        This is Phase 2 of the safety plan - prevents auto-homing
        when robot might be in an unsafe position (e.g., after E-Stop).

        Returns:
            dict with keys:
                - connected: bool
                - awaiting_confirmation: bool (if successful)
                - joints: list[float] (current joint angles in degrees)
                - error: bool (if robot has error status)
                - error_code: int (if error exists)
        """
        self.logger.info(f"Safe connect initiated for robot {self.robot_id}")

        try:
            # Get the underlying Mecademic driver
            driver = self.async_wrapper.robot_driver

            # Step 1: Connect to robot (TCP connection only)
            await driver.connect()
            self.logger.info(f"TCP connection established for robot {self.robot_id}")

            # Step 2: Get current state BEFORE activation
            status = await driver.get_status()
            joints = await driver.get_joints()

            # Step 3: Check for error status
            if status.get('error_status'):
                error_code = status.get('error_code', 'unknown')
                self.logger.warning(
                    f"Robot {self.robot_id} connected but in error state: {error_code}"
                )
                return {
                    "connected": True,
                    "error": True,
                    "error_code": error_code,
                    "message": "Robot in error state - clear error before homing"
                }

            # Step 4: Broadcast connection pending state via WebSocket
            await self._broadcast_robot_state_change_pending(joints)

            self.logger.info(
                f"Robot {self.robot_id} connected safely. "
                f"Current joints: {joints}. Awaiting user confirmation."
            )

            return {
                "connected": True,
                "awaiting_confirmation": True,
                "joints": list(joints)
            }

        except Exception as e:
            self.logger.error(f"Robot {self.robot_id} safe connect failed: {e}")
            raise HardwareError(
                f"Safe connect failed: {e}",
                robot_id=self.robot_id
            )

    async def confirm_activation(self) -> dict:
        """
        User-confirmed activation and homing.
        Called by UI after user confirms robot position is safe.

        Proceeds with the activation → home → wait homed sequence.

        Returns:
            dict with keys:
                - connected: bool
                - homed: bool
        """
        self.logger.info(f"Activation confirmed by user for robot {self.robot_id}")

        try:
            driver = self.async_wrapper.robot_driver

            # Step 1: Check and reset any errors first
            status = await driver.get_status()
            if status.get('error_status'):
                error_code = status.get('error_code', 'unknown')
                self.logger.info(
                    f"Resetting error {error_code} before activation for robot {self.robot_id}"
                )
                await driver.reset_error()

            # Step 2: Activate robot
            self.logger.info(f"Activating robot {self.robot_id}")
            await driver.activate_robot()

            # Step 3: Home robot
            self.logger.info(f"Homing robot {self.robot_id}")
            await driver.home_robot()

            # Step 4: Wait for homing to complete (30s timeout)
            await driver.wait_homed(timeout=30.0)
            self.logger.info(f"Robot {self.robot_id} homing complete")

            # Step 5: Check if robot is paused after homing and resume if needed
            status = await driver.get_status()
            if status.get('pause_motion_status'):
                self.logger.info(f"Robot {self.robot_id} paused after homing - resuming motion")
                await driver.resume_motion()

            # Step 6: Broadcast connection complete state
            await self._broadcast_robot_state_change_complete()

            # Step 7: Update internal state to IDLE
            await self.update_robot_state(
                RobotState.IDLE,
                reason="Robot activated and homed successfully"
            )

            self.logger.info(f"Robot {self.robot_id} activation and homing complete")

            return {
                "connected": True,
                "homed": True
            }

        except Exception as e:
            self.logger.error(f"Robot {self.robot_id} activation failed: {e}")
            # Execute emergency stop on failure
            await self._execute_emergency_stop()
            raise HardwareError(
                f"Activation failed: {e}",
                robot_id=self.robot_id
            )

    async def _broadcast_robot_state_change_pending(self, joints: list):
        """Broadcast connection pending state to UI via WebSocket."""
        try:
            from websocket.selective_broadcaster import get_broadcaster, MessageType

            broadcaster = await get_broadcaster()
            await broadcaster.broadcast_message(
                {
                    "type": "connection_pending",
                    "robot_id": self.robot_id,
                    "joints": list(joints),
                    "requires_confirmation": True,
                    "message": "Review robot position before homing"
                },
                message_type=MessageType.ROBOT_STATUS
            )
        except Exception as e:
            self.logger.warning(f"Failed to broadcast pending state: {e}")

    async def _broadcast_robot_state_change_complete(self):
        """Broadcast connection complete state to UI via WebSocket."""
        try:
            from websocket.selective_broadcaster import get_broadcaster, MessageType

            broadcaster = await get_broadcaster()
            await broadcaster.broadcast_message(
                {
                    "type": "connection_complete",
                    "robot_id": self.robot_id,
                    "homed": True
                },
                message_type=MessageType.ROBOT_STATUS
            )
        except Exception as e:
            self.logger.warning(f"Failed to broadcast complete state: {e}")

    async def disconnect_safe(self) -> dict:
        """
        Gracefully disconnect from Mecademic robot.

        Per plan: Deactivates robot before disconnecting to ensure clean shutdown.
        This follows mecademicpy best practices for proper disconnection sequence.

        Returns:
            dict: Result containing disconnected status and whether robot was connected
        """
        try:
            driver = self.async_wrapper.robot_driver

            # Check if connected first
            is_connected = await driver.is_connected()
            if not is_connected:
                self.logger.info(f"Robot {self.robot_id} already disconnected")
                return {
                    "disconnected": True,
                    "was_connected": False
                }

            self.logger.info(f"Disconnecting robot {self.robot_id} safely...")

            # Deactivate robot before disconnect (per mecademicpy best practices)
            await driver.deactivate_robot()
            self.logger.info(f"Robot {self.robot_id} deactivated")

            # Disconnect from robot
            await driver.disconnect()
            self.logger.info(f"Robot {self.robot_id} disconnected")

            # Update state to DISCONNECTED
            await self.state_manager.update_state(
                self.robot_id,
                {"status": "DISCONNECTED"}
            )

            # Broadcast disconnected state via WebSocket
            await self._broadcast_robot_disconnected()

            return {
                "disconnected": True,
                "was_connected": True
            }

        except Exception as e:
            self.logger.error(f"Robot {self.robot_id} disconnect failed: {e}")
            # Force disconnect on error to avoid stuck connection
            try:
                driver = self.async_wrapper.robot_driver
                await driver.disconnect()
            except Exception:
                pass  # Ignore secondary errors during forced disconnect
            raise HardwareError(
                f"Disconnect failed: {e}",
                robot_id=self.robot_id
            )

    async def _broadcast_robot_disconnected(self):
        """Broadcast disconnected state to UI via WebSocket."""
        try:
            from websocket.selective_broadcaster import get_broadcaster, MessageType

            broadcaster = await get_broadcaster()
            await broadcaster.broadcast_message(
                {
                    "type": "disconnected",
                    "robot_id": self.robot_id,
                    "disconnected": True
                },
                message_type=MessageType.ROBOT_STATUS
            )
        except Exception as e:
            self.logger.warning(f"Failed to broadcast disconnected state: {e}")

    async def _execute_emergency_stop(self) -> bool:
        """Emergency stop implementation for Mecademic robot"""
        self.logger.critical(f"🚨 Executing emergency stop for Meca robot {self.robot_id}")
        
        emergency_success = False
        
        try:
            # Primary method: Emergency stop through AsyncRobotWrapper (now has handler)
            try:
                await self.async_wrapper.execute_movement(
                    MovementCommand(command_type="emergency_stop")
                )
                emergency_success = True
                self.logger.critical(f"Emergency stop executed for {self.robot_id}")
            except Exception as wrapper_error:
                self.logger.error(f"AsyncRobotWrapper emergency stop failed: {wrapper_error}")

                # Fallback: Direct driver emergency stop
                try:
                    if hasattr(self.async_wrapper.robot_driver, '_emergency_stop_impl'):
                        await self.async_wrapper.robot_driver._emergency_stop_impl()
                        emergency_success = True
                except Exception as driver_error:
                    self.logger.error(f"Direct driver emergency stop failed: {driver_error}")

            # Validate connection after emergency stop
            connection_preserved = await self._validate_connection_after_emergency_stop()

            if emergency_success:
                self.logger.critical(f"Emergency stop completed for {self.robot_id}, connection preserved: {connection_preserved}")
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

            # Attempt reconnection
            return await self._attempt_emergency_reconnection()

        except Exception as e:
            self.logger.error(f"Connection validation failed: {e}")
            return False

    async def _attempt_emergency_reconnection(self) -> bool:
        """Attempt to reconnect robot after emergency stop."""
        if not hasattr(self.async_wrapper.robot_driver, 'connect'):
            return False

        try:
            if await self.async_wrapper.robot_driver.connect():
                await self.update_robot_state(RobotState.IDLE, reason="Reconnected after emergency stop")
                self.logger.info(f"Emergency reconnection successful for {self.robot_id}")
                return True

            await self.update_robot_state(RobotState.ERROR, reason="Connection lost after emergency stop")
            return False

        except Exception as e:
            self.logger.error(f"Emergency reconnection failed: {e}")
            return False
    
    
    async def carousel_wafer_operation(
        self,
        operation: str,  # "pickup" or "drop"
        wafer_id: str,
        carousel_position: int
    ) -> ServiceResult[Dict[str, Any]]:
        """
        Execute wafer operation with carousel resource locking.
        
        Args:
            operation: "pickup" or "drop"
            wafer_id: Unique wafer identifier
            carousel_position: Carousel position index (0-23)
        """
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
            timeout=self.settings.operation_timeout * 2,  # Carousel ops take longer
            metadata={
                "wafer_id": wafer_id,
                "operation": operation,
                "carousel_position": carousel_position
            }
        )
        
        async def _carousel_operation():
            # Acquire carousel lock to prevent conflicts
            async with self.lock_manager.acquire_resource(
                "carousel",
                holder_id=context.operation_id,
                timeout=self.settings.meca_timeout
            ):
                carousel_pos = self.carousel_positions[carousel_position]
                target_position = carousel_pos.coordinates
                
                if operation == "pickup":
                    if not carousel_pos.occupied:
                        raise ValidationError(
                            f"No wafer at carousel position {carousel_position}"
                        )
                    
                    result = await self.pickup_wafer_sequence(
                        wafer_id, target_position
                    )
                    
                    # Update carousel state
                    carousel_pos.occupied = False
                    carousel_pos.wafer_id = None
                    
                else:  # drop
                    if carousel_pos.occupied:
                        raise ValidationError(
                            f"Carousel position {carousel_position} already occupied by wafer {carousel_pos.wafer_id}"
                        )
                    
                    result = await self.drop_wafer_sequence(
                        wafer_id, target_position
                    )
                    
                    # Update carousel state
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
    
    async def move_to_safe_position(self) -> ServiceResult[bool]:
        """Move robot to safe position"""
        context = OperationContext(
            operation_id=f"{self.robot_id}_safe_position",
            robot_id=self.robot_id,
            operation_type="move_to_safe"
        )
        
        async def _move_safe():
            await self._move_to_position(self.safe_position, "safe")
            return True
        
        return await self.execute_operation(context, _move_safe)
    
    async def calibrate_robot(self) -> ServiceResult[Dict[str, Any]]:
        """Perform robot calibration sequence"""
        context = OperationContext(
            operation_id=f"{self.robot_id}_calibration",
            robot_id=self.robot_id,
            operation_type=MecaOperationType.CALIBRATION.value,
            timeout=120.0  # Calibration takes longer
        )
        
        async def _calibrate():
            # Ensure robot is ready (CommandService already set to BUSY)
            await self.ensure_robot_ready()
            
            try:
                # Home the robot
                await self.async_wrapper.execute_movement(
                    MovementCommand(command_type="home")
                )
                
                # Activate robot
                await self.async_wrapper.execute_movement(
                    MovementCommand(command_type="activate")
                )
                
                # Test gripper
                await self._open_gripper()
                await self.async_wrapper.delay(1000)
                await self._close_gripper()
                
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
    
    async def _move_to_position(self, position: WaferPosition, move_type: str = "linear"):
        """Internal method to move robot to specified position"""
        command = MovementCommand(
            command_type="MoveLin" if move_type == "linear" else "MovePose",
            target_position={
                "x": position.x,
                "y": position.y,
                "z": position.z,
                "alpha": position.alpha,
                "beta": position.beta,
                "gamma": position.gamma
            },
            speed=self.movement_params.get("speed", 25.0),
            acceleration=self.movement_params.get("acceleration", 25.0)
        )
        
        result = await self.async_wrapper.execute_movement(command)
        if not result.success:
            raise HardwareError(f"Movement failed: {result.error}", robot_id=self.robot_id)
        
        return result
    
    async def _open_gripper(self):
        """Open the gripper"""
        if self._gripper_open:
            return  # Already open
        
        command = MovementCommand(
            command_type="gripper_open",
            tool_action="grip_open"
        )
        
        result = await self.async_wrapper.execute_movement(command)
        if result.success:
            self._gripper_open = True
        else:
            raise HardwareError(f"Failed to open gripper: {result.error}", robot_id=self.robot_id)
    
    async def _close_gripper(self):
        """Close the gripper"""
        if not self._gripper_open:
            return  # Already closed
        
        command = MovementCommand(
            command_type="gripper_close",
            tool_action="grip_close"
        )
        
        result = await self.async_wrapper.execute_movement(command)
        if result.success:
            self._gripper_open = False
        else:
            raise HardwareError(f"Failed to close gripper: {result.error}", robot_id=self.robot_id)
    
    async def get_robot_status(self) -> ServiceResult[Dict[str, Any]]:
        """Get detailed robot status"""
        context = OperationContext(
            operation_id=f"{self.robot_id}_status",
            robot_id=self.robot_id,
            operation_type="status_check"
        )
        
        async def _get_status():
            # Get status from async wrapper
            robot_status = await self.async_wrapper.get_status()
            
            # Get state manager info
            robot_info = await self.state_manager.get_robot_state(self.robot_id)
            
            # Get performance stats
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
                "gripper_open": self._gripper_open,
                "carousel_status": {
                    "total_positions": len(self.carousel_positions),
                    "occupied_positions": sum(1 for pos in self.carousel_positions if pos.occupied)
                },
                "performance": performance
            }
        
        return await self.execute_operation(context, _get_status)
    
    async def get_carousel_status(self) -> ServiceResult[List[Dict[str, Any]]]:
        """Get status of all carousel positions"""
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

    async def reload_sequence_config(self) -> ServiceResult[Dict[str, Any]]:
        """Reload sequence configuration from runtime.json for mid-run adjustments"""
        try:
            from core.settings import get_settings

            # Get fresh settings
            new_settings = get_settings()
            new_robot_config = new_settings.get_robot_config("meca")
            new_movement_params = new_robot_config.get("movement_params", {})

            # Reload the config manager
            self.wafer_config_manager.reload_config(new_robot_config, new_movement_params)

            # Also update local references
            self.robot_config = new_robot_config
            self.movement_params = new_movement_params

            # Validate new config for all wafers
            errors = self.wafer_config_manager.validate_all_wafers()

            self.logger.info(f"Sequence config reloaded - version {self.wafer_config_manager.config_version}")

            return ServiceResult(
                success=len(errors) == 0,
                data={
                    "version": self.wafer_config_manager.config_version,
                    "validation_errors": errors,
                    "message": "Configuration reloaded successfully" if not errors else f"Configuration reloaded with {len(errors)} validation warnings"
                },
                error="; ".join(errors) if errors else None
            )
        except ConfigurationError as e:
            self.logger.error(f"Failed to reload sequence config: {e}")
            return ServiceResult(success=False, error=str(e))
        except Exception as e:
            self.logger.error(f"Unexpected error reloading sequence config: {e}")
            return ServiceResult(success=False, error=f"Unexpected error: {str(e)}")

    # Wafer sequence methods - exact implementations from Meca_FullCode.py
    
    async def execute_pickup_sequence(
        self, start: int, count: int, retry_wafers: Optional[List[int]] = None
    ) -> ServiceResult[Dict[str, Any]]:
        """
        Execute wafer pickup sequence from inert tray to spreader.
        Exact implementation of createPickUpPt() from Meca_FullCode.py

        Args:
            start: Starting wafer index (0-based)
            count: Number of wafers to process
            retry_wafers: Optional list of specific wafer indices to retry (for error recovery)
        """
        context = OperationContext(
            operation_id=f"{self.robot_id}_pickup_sequence_{start}_{count}",
            robot_id=self.robot_id,
            operation_type=MecaOperationType.PICKUP_WAFER.value,
            timeout=600.0,  # 10 minutes for pickup sequence
            metadata={"start": start, "count": count}
        )
        
        async def _pickup_sequence():
            # Ensure robot is ready and connected
            await self.ensure_robot_ready()

            self.logger.info(f"Starting pickup sequence for wafers {start+1} to {start+count}")

            # Initial statements for first wafer
            # Initial statements - apply at start of every sequence to ensure consistent parameters
            # if start == 0:  <-- REMOVED: Always apply parameters to prevent loss in subsequent batches
            await self._execute_movement_command("SetGripperForce", [self.FORCE])
            await self._execute_movement_command("SetJointAcc", [self.ACC])
            await self._execute_movement_command("SetTorqueLimits", [40, 40, 40, 40, 40, 40])
            await self._execute_movement_command("SetTorqueLimitsCfg", [2, 1])
            await self._execute_movement_command("SetBlending", [0])
            
            # Set initial velocity and configuration
            await self._execute_movement_command("SetJointVel", [self.ALIGN_SPEED])
            await self._execute_movement_command("SetConf", [1, 1, 1])
            await self._execute_movement_command("GripperOpen", [])
            await self._execute_movement_command("Delay", [1])
            
            processed_wafers = []
            failed_wafers = []

            # Determine starting point (handle resume from pause)
            step_state = await self.state_manager.get_step_state(self.robot_id)
            resume_from = step_state.progress_data.get("current_wafer_index", 0) if step_state else 0

            # Determine wafers to process
            wafer_indices = retry_wafers if retry_wafers else list(range(max(start, resume_from), start + count))

            for i in wafer_indices:
                wafer_num = i + 1

                # Handle pause
                if await self.state_manager.is_step_paused(self.robot_id):
                    await self.state_manager.update_step_progress(self.robot_id, {"current_wafer_index": i, "total_wafers": count})
                    while await self.state_manager.is_step_paused(self.robot_id):
                        await asyncio.sleep(1.0)

                # Check emergency stop
                robot_info = await self.state_manager.get_robot_state(self.robot_id)
                if robot_info and robot_info.current_state == RobotState.EMERGENCY_STOP:
                    self.logger.critical(f"Emergency stop - aborting at wafer {wafer_num}")
                    break

                try:
                    await self._broadcast_wafer_progress("pickup", wafer_num, i, start, count)
                    await self.state_manager.update_step_progress(
                        self.robot_id,
                        {"current_wafer_index": i, "current_wafer_num": wafer_num, "total_wafers": count}
                    )

                    positions = self.calculate_intermediate_positions(i, "pickup")
                    pickup_position = self.calculate_wafer_position(i, "inert")

                    # Move to pickup position and grab wafer
                    await self._execute_movement_command("MovePose", positions["pickup_high"])
                    await self._execute_movement_command("MovePose", pickup_position)
                    await self._execute_movement_command("Delay", [1])
                    await self._execute_movement_command("GripperClose", [])
                    await self._execute_movement_command("Delay", [1])

                    # Move through intermediate positions to safe point
                    await self._execute_movement_command("SetJointVel", [self.WAFER_SPEED])
                    await self._execute_movement_command("MovePose", positions["intermediate_1"])
                    await self._execute_movement_command("SetBlending", [100])
                    await self._execute_movement_command("MovePose", positions["intermediate_2"])
                    await self._execute_movement_command("MoveLin", positions["intermediate_3"])
                    await self._execute_movement_command("SetBlending", [0])
                    await self._execute_movement_command("MovePose", self.SAFE_POINT)

                    # Move to spreader and release wafer
                    await self._execute_movement_command("SetJointVel", [self.ALIGN_SPEED])
                    await self._execute_movement_command("MovePose", positions["above_spreader"])
                    await self._execute_movement_command("MovePose", positions["spreader"])
                    await self._execute_movement_command("Delay", [1])
                    await self._execute_movement_command("GripperOpen", [])
                    await self._execute_movement_command("Delay", [1])

                    # Return to safe point
                    await self._execute_movement_command("MovePose", positions["above_spreader_exit"])
                    await self._execute_movement_command("SetJointVel", [self.EMPTY_SPEED])
                    await self._execute_movement_command("MovePose", self.SAFE_POINT)

                    # Check for collision/error
                    await self._check_robot_status_after_motion(wafer_num)

                    await self.async_wrapper.wait_idle(timeout=60.0)
                    self.logger.debug(f"Wafer {wafer_num} completed")

                    if (4 - (i % 5)) == 0:
                        await self._execute_movement_command("Delay", [self.SPREAD_WAIT])

                except Exception as e:
                    self.logger.error(f"Failed wafer {wafer_num}: {e}")
                    failed_wafers.append({"wafer_num": wafer_num, "error": str(e)})
                    raise

            if failed_wafers:
                self.logger.warning(f"Pickup completed with {len(failed_wafers)} failures")

            # Calculate success rate based on actual wafers processed
            total_attempted = len(retry_wafers) if retry_wafers else count
            success_rate = (len(processed_wafers) / total_attempted * 100) if total_attempted > 0 else 0

            result = {
                "status": "completed" if not failed_wafers else "partial_success",
                "wafers_processed": len(processed_wafers),
                "wafers_succeeded": processed_wafers,
                "wafers_failed": [fw["wafer_num"] for fw in failed_wafers],  # Return just indices for frontend
                "start_wafer": start + 1,
                "end_wafer": start + count,
                "success_rate": f"{success_rate:.1f}%",
                "retry_mode": retry_wafers is not None
            }

            if failed_wafers:
                self.logger.info(f"Pickup sequence completed with partial success: {len(processed_wafers)}/{total_attempted} wafers processed successfully")
            else:
                self.logger.info(f"Pickup sequence completed successfully for all {total_attempted} wafers")

            # Complete step tracking
            await self.state_manager.complete_step(self.robot_id)

            # Broadcast batch completion to frontend
            await self._broadcast_batch_completion(
                operation_type="pickup",
                start=start,
                count=count,
                result=result
            )

            return result

        return await self.execute_operation(context, _pickup_sequence)

    def _validate_robot_parameters(self, command_type: str, parameters: List[Any]) -> bool:
        """
        Validate robot command parameters to prevent sending values that could cause errors.
        
        Args:
            command_type: Type of command (SetJointVel, MovePose, etc.)
            parameters: Parameters to validate
            
        Returns:
            True if parameters are valid
            
        Raises:
            ValidationError: If parameters are invalid
        """
        if not parameters:
            return True
            
        # Speed and acceleration validation (should be percentages: 1-100)
        if command_type in ["SetJointVel", "SetJointAcc", "SetCartVel", "SetCartAcc"]:
            if len(parameters) >= 1:
                value = parameters[0]
                if not (1 <= value <= 100):
                    raise ValidationError(
                        f"{command_type} parameter {value} is out of range (1-100)",
                        field="speed_acceleration"
                    )
        
        # Force validation (should be reasonable: 1-200)
        elif command_type == "SetGripperForce":
            if len(parameters) >= 1:
                value = parameters[0]
                if not (1 <= value <= 200):
                    raise ValidationError(
                        f"SetGripperForce parameter {value} is out of range (1-200)",
                        field="gripper_force"
                    )
        
        # Torque limits validation (should be reasonable: 1-100 for each joint)
        elif command_type == "SetTorqueLimits":
            if len(parameters) >= 6:
                for i, value in enumerate(parameters[:6]):
                    if not (1 <= value <= 100):
                        raise ValidationError(
                            f"SetTorqueLimits joint {i+1} parameter {value} is out of range (1-100)",
                            field="torque_limits"
                        )
        
        # Configuration validation (should be valid configurations: -1, 0, or 1)
        elif command_type == "SetConf":
            if len(parameters) >= 3:
                for i, value in enumerate(parameters[:3]):
                    if value not in [-1, 0, 1]:
                        raise ValidationError(
                            f"SetConf parameter {i+1} value {value} is invalid (must be -1, 0, or 1)",
                            field="robot_configuration"
                        )
        
        # Position validation (basic workspace check for Mecademic Meca500)
        elif command_type in ["MovePose", "MoveLin"]:
            if len(parameters) >= 6:
                x, y, z = parameters[0], parameters[1], parameters[2]
                alpha, beta, gamma = parameters[3], parameters[4], parameters[5]
                
                # Basic workspace validation for Meca500 (approximate)
                # X: -500 to +500 mm, Y: -500 to +500 mm, Z: -100 to +400 mm
                if not (-500 <= x <= 500):
                    raise ValidationError(
                        f"{command_type} X coordinate {x} is out of workspace (-500 to +500 mm)",
                        field="position_x"
                    )
                if not (-500 <= y <= 500):
                    raise ValidationError(
                        f"{command_type} Y coordinate {y} is out of workspace (-500 to +500 mm)",
                        field="position_y"
                    )
                if not (-100 <= z <= 400):
                    raise ValidationError(
                        f"{command_type} Z coordinate {z} is out of workspace (-100 to +400 mm)",
                        field="position_z"
                    )
                
                # Orientation validation (degrees: -180 to +180, but allow some tolerance)
                for angle, name in [(alpha, "Alpha"), (beta, "Beta"), (gamma, "Gamma")]:
                    if not (-180.1 <= angle <= 180.1):
                        self.logger.warning(f"{command_type} {name} angle {angle} is at limit (-180 to +180 degrees)")
                    if not (-360 <= angle <= 360):
                        raise ValidationError(
                            f"{command_type} {name} angle {angle} is severely out of range (-360 to +360 degrees)",
                            field=f"orientation_{name.lower()}"
                        )
        
        # Delay validation (should be reasonable: 0.1 to 10 seconds)
        elif command_type == "Delay":
            if len(parameters) >= 1:
                value = parameters[0]
                if not (0.1 <= value <= 10.0):
                    raise ValidationError(
                        f"Delay parameter {value} is out of range (0.1 to 10.0 seconds)",
                        field="delay_duration"
                    )
        
        return True
    
    async def _execute_movement_command(self, command_type: str, parameters: List[Any] = None) -> None:
        """Execute movement command through the async wrapper."""
        if parameters is None:
            parameters = []

        # Safety check: abort if emergency stop is active
        robot_info = await self.state_manager.get_robot_state(self.robot_id)
        if robot_info and robot_info.current_state == RobotState.EMERGENCY_STOP:
            raise RuntimeError(f"Emergency stop activated during {command_type}")

        # Validate parameters
        self._validate_robot_parameters(command_type, parameters)

        # Build command
        command = self._build_movement_command(command_type, parameters)

        # Execute
        self.logger.debug(f"Executing {command_type}")
        result = await self.async_wrapper.execute_movement(command)
        if not result.success:
            raise HardwareError(f"Command {command_type} failed: {result.error}", robot_id=self.robot_id)

    def _build_movement_command(self, command_type: str, parameters: List[Any]) -> MovementCommand:
        """Build MovementCommand from command type and parameters."""
        # Position commands with 6 coordinates
        if command_type in ("MovePose", "MoveLin") and len(parameters) == 6:
            return MovementCommand(
                command_type=command_type,
                target_position={
                    "x": parameters[0], "y": parameters[1], "z": parameters[2],
                    "alpha": parameters[3], "beta": parameters[4], "gamma": parameters[5]
                }
            )

        # Gripper commands
        if command_type == "GripperOpen":
            return MovementCommand(command_type="GripperOpen", tool_action="grip_open")
        if command_type == "GripperClose":
            return MovementCommand(command_type="GripperClose", tool_action="grip_close")
        if command_type == "MoveGripper" and len(parameters) == 1:
            return MovementCommand(command_type="MoveGripper", tool_action="grip_move", parameters={"width": parameters[0]})

        # Delay command
        if command_type == "Delay" and len(parameters) == 1:
            return MovementCommand(command_type="Delay", parameters={"duration": parameters[0]})

        # Configuration commands (Set*)
        if command_type.startswith("Set"):
            return MovementCommand(command_type="config", parameters={"config_type": command_type, "values": parameters})

        # Generic fallback
        return MovementCommand(command_type=command_type.lower(), parameters={"values": parameters} if parameters else {})

    async def _check_robot_status_after_motion(self, wafer_num: int) -> None:
        """Check robot status after motion sequence to detect collisions/errors."""
        driver = self.async_wrapper.robot_driver
        if not hasattr(driver, 'get_robot_instance'):
            return

        robot_instance = driver.get_robot_instance()
        if not robot_instance or not hasattr(robot_instance, 'GetStatusRobot'):
            return

        try:
            status = robot_instance.GetStatusRobot()
            if getattr(status, 'error_status', False):
                raise HardwareError(f"Robot error after wafer {wafer_num}", robot_id=self.robot_id)
            if getattr(status, 'pause_motion_status', False):
                raise HardwareError(f"Robot paused after wafer {wafer_num}", robot_id=self.robot_id)
        except HardwareError:
            raise
        except Exception as e:
            self.logger.debug(f"Status check warning: {e}")

    async def execute_drop_sequence(
        self, start: int, count: int, retry_wafers: Optional[List[int]] = None
    ) -> ServiceResult[Dict[str, Any]]:
        """
        Execute wafer drop sequence from spreader to baking tray.
        Exact implementation of createDropPt() from Meca_FullCode.py

        Args:
            start: Starting wafer index (0-based)
            count: Number of wafers to process
            retry_wafers: Optional list of specific wafer indices to retry (for error recovery)
        """
        context = OperationContext(
            operation_id=f"{self.robot_id}_drop_sequence_{start}_{count}",
            robot_id=self.robot_id,
            operation_type=MecaOperationType.DROP_WAFER.value,
            timeout=600.0,  # 10 minutes for drop sequence
            metadata={"start": start, "count": count}
        )
        
        async def _drop_sequence():
            # Start step tracking
            await self.state_manager.start_step(
                robot_id=self.robot_id,
                step_index=7,  # This will be updated from WebSocket handler
                step_name="Move to Baking Tray",
                operation_type="drop_sequence",
                progress_data={"start": start, "count": count, "current_wafer_index": start}
            )
            
            await self.ensure_robot_ready()
            
            self.logger.info(f"Starting drop sequence for wafers {start+1} to {start+count}")
            
            processed_wafers = []
            failed_wafers = []

            # Determine starting point (handle resume from pause)
            step_state = await self.state_manager.get_step_state(self.robot_id)
            resume_from = step_state.progress_data.get("current_wafer_index", 0) if step_state else 0

            # Determine wafers to process
            wafer_indices = retry_wafers if retry_wafers else list(range(max(start, resume_from), start + count))

            for i in wafer_indices:
                wafer_num = i + 1

                # Handle pause
                if await self.state_manager.is_step_paused(self.robot_id):
                    await self.state_manager.update_step_progress(self.robot_id, {"current_wafer_index": i, "total_wafers": count})
                    while await self.state_manager.is_step_paused(self.robot_id):
                        await asyncio.sleep(1.0)

                try:
                    await self._broadcast_wafer_progress("drop", wafer_num, i, start, count)
                    await self.state_manager.update_step_progress(
                        self.robot_id,
                        {"current_wafer_index": i, "current_wafer_num": wafer_num, "total_wafers": count}
                    )
                    
                    # Get positions for this wafer
                    positions = self.calculate_intermediate_positions(i, "drop")
                
                    # Move to spreader area
                    await self._execute_movement_command("SetJointVel", [self.ALIGN_SPEED])
                    await self._execute_movement_command("MovePose", positions["above_spreader"])
                    await self._execute_movement_command("Delay", [1])
                    await self._execute_movement_command("MovePose", positions["spreader"])
                    await self._execute_movement_command("Delay", [1])
                    
                    # Pick up wafer from spreader
                    await self._execute_movement_command("GripperClose", [])
                    await self._execute_movement_command("Delay", [1])
                
                    # Move up from spreader
                    await self._execute_movement_command("MovePose", positions["above_spreader_pickup"])
                    await self._execute_movement_command("SetJointVel", [self.SPEED])
                    
                    # Move to safe point
                    await self._execute_movement_command("MovePose", self.SAFE_POINT)
                    
                    # Move through baking tray alignment sequence
                    await self._execute_movement_command("MovePose", positions["baking_align1"])
                    await self._execute_movement_command("SetJointVel", [self.ALIGN_SPEED])
                    await self._execute_movement_command("SetBlending", [100])
                    await self._execute_movement_command("MovePose", positions["baking_align2"])
                    await self._execute_movement_command("MovePose", positions["baking_align3"])
                    await self._execute_movement_command("MovePose", positions["baking_align4"])
                    await self._execute_movement_command("Delay", [1])
                    
                    # Release wafer in baking tray
                    await self._execute_movement_command("GripperOpen", [])
                    await self._execute_movement_command("Delay", [0.5])
                    
                    # Move up from baking tray
                    await self._execute_movement_command("MovePose", positions["baking_up"])
                    await self._execute_movement_command("SetJointVel", [self.SPEED])
                    await self._execute_movement_command("SetBlending", [0])
                    
                    # Return to safe point
                    await self._execute_movement_command("MovePose", self.SAFE_POINT)

                    # CRITICAL: Wait for robot to finish all queued movements before proceeding
                    # Without this, code proceeds to next wafer while robot is still moving
                    await self.async_wrapper.wait_idle(timeout=60.0)

                    processed_wafers.append(wafer_num)
                    self.logger.debug(f"Completed drop for wafer {wafer_num}")

                except Exception as e:
                    self.logger.error(f"Failed wafer {wafer_num}: {e}")
                    failed_wafers.append({"wafer_num": wafer_num, "error": str(e)})

                    # Attempt recovery - move to safe position
                    try:
                        await self._execute_movement_command("SetJointVel", [self.SPEED])
                        await self._execute_movement_command("MovePose", self.SAFE_POINT)
                        await self._execute_movement_command("GripperOpen", [])
                    except Exception as recovery_error:
                        raise HardwareError(f"Drop failed and recovery failed: {e}", robot_id=self.robot_id)

                    continue

            if failed_wafers:
                self.logger.warning(f"Drop sequence completed with {len(failed_wafers)} failures")

            # Calculate success rate based on actual wafers processed
            total_attempted = len(retry_wafers) if retry_wafers else count
            success_rate = (len(processed_wafers) / total_attempted * 100) if total_attempted > 0 else 0

            result = {
                "status": "completed" if not failed_wafers else "partial_success",
                "wafers_processed": len(processed_wafers),
                "wafers_succeeded": processed_wafers,
                "wafers_failed": [fw["wafer_num"] for fw in failed_wafers],  # Return just indices for frontend
                "start_wafer": start + 1,
                "end_wafer": start + count,
                "success_rate": f"{success_rate:.1f}%",
                "retry_mode": retry_wafers is not None
            }

            # Complete step tracking
            await self.state_manager.complete_step(self.robot_id)

            # Broadcast batch completion to frontend
            broadcast_success = await self._broadcast_batch_completion(
                operation_type="drop",
                start=start,
                count=count,
                result=result
            )

            # Add broadcast status to result so HTTP response includes it
            result["broadcast_sent"] = broadcast_success

            self.logger.info(f"Drop sequence completed for wafers {start+1} to {start+count}")
            return result

        return await self.execute_operation(context, _drop_sequence)

    async def execute_carousel_sequence(self, start: int, count: int) -> ServiceResult[Dict[str, Any]]:
        """
        Execute carousel sequence from baking tray to carousel.
        Exact implementation of carouselPt() from Meca_FullCode.py
        
        Args:
            start: Starting wafer index (0-based)
            count: Number of wafers to process (typically 11 for carousel)
        """
        context = OperationContext(
            operation_id=f"{self.robot_id}_carousel_sequence_{start}_{count}",
            robot_id=self.robot_id,
            operation_type=MecaOperationType.CAROUSEL_OPERATION.value,
            timeout=900.0,  # 15 minutes for carousel sequence
            metadata={"start": start, "count": count}
        )
        
        async def _carousel_sequence():
            await self.ensure_robot_ready()
            
            self.logger.info(f"Starting carousel sequence for wafers {start+1} to {start+count}")
            
            # Configuration specific to carousel movement - apply every batch
            await self._execute_movement_command("SetConf", [1, 1, -1])
            await self._execute_movement_command("Delay", [3])
            
            for i in range(start, start + count):
                wafer_num = i + 1
                self.logger.info(f"Processing wafer {wafer_num} from baking tray to carousel")
                
                # Add delay for each new carousel batch  
                if wafer_num % 11 == 1 and wafer_num >= 1:
                    await self._execute_movement_command("Delay", [5])
                
                # Open gripper and prepare for pickup
                await self._execute_movement_command("GripperOpen", [])
                await self._execute_movement_command("Delay", [1])
                
                # Get positions for this wafer
                positions = self.calculate_intermediate_positions(i, "carousel")
                baking_position = self.calculate_wafer_position(i, "baking")
                
                # Move to above baking tray position
                await self._execute_movement_command("SetJointVel", [self.SPEED])
                await self._execute_movement_command("MovePose", positions["above_baking"])
                await self._execute_movement_command("SetJointVel", [self.ALIGN_SPEED])
                await self._execute_movement_command("SetBlending", [0])
                
                # Pick up wafer from baking tray
                await self._execute_movement_command("MovePose", baking_position)
                await self._execute_movement_command("Delay", [0.5])
                await self._execute_movement_command("GripperClose", [])
                await self._execute_movement_command("Delay", [0.5])
                
                # Start movement path to carousel
                await self._execute_movement_command("SetBlending", [100])
                await self._execute_movement_command("MovePose", positions["move1"])
                await self._execute_movement_command("SetJointVel", [self.SPEED])
                await self._execute_movement_command("MovePose", positions["move2"])
                await self._execute_movement_command("MovePose", positions["move3"])
                await self._execute_movement_command("MovePose", positions["move4"])
                await self._execute_movement_command("Delay", [0.5])
                await self._execute_movement_command("SetBlending", [80])
                
                # Move through photogate
                await self._execute_movement_command("MovePose", self.T_PHOTOGATE)  # Before Photogate
                await self._execute_movement_command("MovePose", self.C_PHOTOGATE)  # After Photogate
                
                # Y Away approach
                await self._execute_movement_command("MovePose", positions["y_away1"])  # Y Away 1
                await self._execute_movement_command("SetBlending", [0])
                await self._execute_movement_command("Delay", [1])
                await self._execute_movement_command("SetJointVel", [self.ENTRY_SPEED])
                await self._execute_movement_command("MovePose", positions["y_away2"])  # Y Away 2
                
                # Approach carousel positions
                await self._execute_movement_command("MovePose", positions["above_carousel1"])  # Above Carousel 1
                await self._execute_movement_command("MovePose", positions["above_carousel2"])  # Above Carousel 2
                await self._execute_movement_command("MovePose", positions["above_carousel3"])  # Above Carousel 3
                
                # Carousel position - release wafer
                await self._execute_movement_command("MovePose", self.CAROUSEL)  # Carousel
                await self._execute_movement_command("Delay", [0.5])
                await self._execute_movement_command("MoveGripper", [2.9])
                await self._execute_movement_command("Delay", [0.5])
                
                # Exit carousel
                await self._execute_movement_command("SetJointVel", [self.EMPTY_SPEED])
                await self._execute_movement_command("MovePose", positions["above_carousel3"])  # Above Carousel 4
                await self._execute_movement_command("MovePose", positions["above_carousel2"])  # Above Carousel 5
                await self._execute_movement_command("MovePose", positions["above_carousel1"])  # Above Carousel
                await self._execute_movement_command("MovePose", positions["y_away2"])  # Y Away 1
                await self._execute_movement_command("MovePose", positions["y_away1"])  # Y Away 2
                
                # Return to safe point
                await self._execute_movement_command("MovePose", self.CAROUSEL_SAFEPOINT)
                await self._execute_movement_command("SetBlending", [100])
            
            result = {
                "status": "completed", 
                "wafers_processed": count,
                "start_wafer": start + 1,
                "end_wafer": start + count
            }
            
            self.logger.info(f"Carousel sequence completed for wafers {start+1} to {start+count}")
            return result
        
        return await self.execute_operation(context, _carousel_sequence)
    
    async def execute_empty_carousel_sequence(self, start: int, count: int) -> ServiceResult[Dict[str, Any]]:
        """
        Execute empty carousel sequence from carousel back to baking tray.
        Exact implementation of emptyCarousel() from Meca_FullCode.py
        
        Args:
            start: Starting wafer index (0-based)
            count: Number of wafers to process (typically 11 for carousel)
        """
        context = OperationContext(
            operation_id=f"{self.robot_id}_empty_carousel_sequence_{start}_{count}",
            robot_id=self.robot_id,
            operation_type=MecaOperationType.CAROUSEL_OPERATION.value,
            timeout=900.0,  # 15 minutes for empty carousel sequence
            metadata={"start": start, "count": count}
        )
        
        async def _empty_carousel_sequence():
            await self.ensure_robot_ready()
            
            self.logger.info(f"Starting empty carousel sequence for wafers {start+1} to {start+count}")
            
            for i in range(start, start + count):
                wafer_num = i + 1
                self.logger.info(f"Processing wafer {wafer_num} from carousel to baking tray")
                
                # Add delay for each new carousel batch
                if wafer_num % 11 == 1:
                    await self._execute_movement_command("Delay", [7.5])
                else:
                    await self._execute_movement_command("Delay", [1])
                
                # Open gripper and prepare to pick up wafer from carousel
                await self._execute_movement_command("GripperOpen", [])
                await self._execute_movement_command("Delay", [1])
                
                # Get positions for this wafer
                positions = self.calculate_intermediate_positions(i, "empty_carousel")
                
                # Move to Y-away positions
                await self._execute_movement_command("MovePose", positions["y_away1"])  # Y Away 2
                await self._execute_movement_command("MovePose", positions["y_away2"])  # Y Away 1
                await self._execute_movement_command("MovePose", positions["above_carousel"])  # Above Carousel
                
                # Prepare to pick up from carousel
                await self._execute_movement_command("SetBlending", [0])
                await self._execute_movement_command("SetJointVel", [self.ENTRY_SPEED])
                await self._execute_movement_command("MoveGripper", [3.7])
                await self._execute_movement_command("Delay", [0.5])
                
                # Staged approach to carousel (reverse order)
                above_carousel5 = copy.deepcopy(self.CAROUSEL)
                above_carousel5[2] = 109.9
                await self._execute_movement_command("MovePose", above_carousel5)  # Above Carousel 5
                
                above_carousel4 = copy.deepcopy(self.CAROUSEL)
                above_carousel4[2] = 103.9
                await self._execute_movement_command("MovePose", above_carousel4)  # Above Carousel 4
                
                # Grab wafer from carousel
                await self._execute_movement_command("MovePose", self.CAROUSEL)  # Carousel
                await self._execute_movement_command("Delay", [0.5])
                await self._execute_movement_command("GripperClose", [])
                await self._execute_movement_command("SetJointVel", [self.ALIGN_SPEED])
                await self._execute_movement_command("Delay", [0.5])
                
                # Staged exit from carousel
                above_carousel3 = copy.deepcopy(self.CAROUSEL)
                above_carousel3[2] = 103.9
                await self._execute_movement_command("MovePose", above_carousel3)  # Above Carousel 4
                
                above_carousel2 = copy.deepcopy(self.CAROUSEL)
                above_carousel2[2] = 109.9
                await self._execute_movement_command("MovePose", above_carousel2)  # Above Carousel 2
                
                above_carousel1 = copy.deepcopy(self.CAROUSEL)
                above_carousel1[2] = 115.9
                await self._execute_movement_command("MovePose", above_carousel1)  # Above Carousel 1
                
                # Move through Y-away positions
                move8_rev = copy.deepcopy(self.CAROUSEL)
                move8_rev[1] = -245.95
                move8_rev[2] = 115.9
                await self._execute_movement_command("MovePose", move8_rev)  # Y Away 1
                await self._execute_movement_command("Delay", [0.5])
                await self._execute_movement_command("SetBlending", [80])
                await self._execute_movement_command("SetJointVel", [self.SPEED])
                
                # Y-away position with precise coordinates
                move7_rev = copy.deepcopy(self.CAROUSEL)
                move7_rev[1] = -216.95
                move7_rev[2] = 120.0  # Exact height from reference
                await self._execute_movement_command("MovePose", move7_rev)  # Y Away 2
                
                # Through photogate in reverse order
                await self._execute_movement_command("MovePose", self.C_PHOTOGATE)  # Before Photogate
                await self._execute_movement_command("MovePose", self.T_PHOTOGATE)  # After Photogate
                await self._execute_movement_command("Delay", [0.5])
                
                # Move through baking tray alignment positions (reverse order)
                await self._execute_movement_command("MovePose", positions["move4_rev"])
                await self._execute_movement_command("SetJointVel", [self.ALIGN_SPEED])
                await self._execute_movement_command("Delay", [0.5])
                await self._execute_movement_command("SetBlending", [100])
                await self._execute_movement_command("MovePose", positions["move3_rev"])
                await self._execute_movement_command("MovePose", positions["move2_rev"])
                await self._execute_movement_command("MovePose", positions["move1_rev"])
                await self._execute_movement_command("Delay", [1])
                
                # Release wafer
                await self._execute_movement_command("GripperOpen", [])
                await self._execute_movement_command("Delay", [0.5])
                
                # Final position - move up from baking tray
                await self._execute_movement_command("MovePose", positions["above_baking_rev"])
                await self._execute_movement_command("SetJointVel", [self.EMPTY_SPEED])
                await self._execute_movement_command("Delay", [0.2])
                await self._execute_movement_command("SetBlending", [100])
                
                # Return to safe point
                await self._execute_movement_command("MovePose", self.CAROUSEL_SAFEPOINT)
            
            result = {
                "status": "completed",
                "wafers_processed": count,
                "start_wafer": start + 1,
                "end_wafer": start + count
            }
            
            self.logger.info(f"Empty carousel sequence completed for wafers {start+1} to {start+count}")
            return result
        
        return await self.execute_operation(context, _empty_carousel_sequence)

    async def get_wafer_position_preview(self, wafer_index: int) -> Dict[str, Any]:
        """
        Get position preview data for a single wafer.
        Used by test endpoint to verify position calculations.

        Args:
            wafer_index: Wafer index (0-based, 0-54)

        Returns:
            Dictionary with calculated positions for the wafer
        """
        wafer_number = wafer_index + 1
        baking_position = self.calculate_wafer_position(wafer_index, "baking")
        carousel_position = self.calculate_wafer_position(wafer_index, "carousel")
        carousel_positions = self.calculate_intermediate_positions(wafer_index, "carousel")

        return {
            "wafer_number": wafer_number,
            "wafer_index": wafer_index,
            "positions": {
                "baking_tray": {
                    "coordinates": baking_position,
                    "x": baking_position[0],
                    "y": baking_position[1],
                    "z": baking_position[2],
                },
                "carousel": {"coordinates": carousel_position},
                "intermediate_positions": {
                    "above_baking": carousel_positions.get("above_baking"),
                    "move_sequence": [
                        carousel_positions.get("move1"),
                        carousel_positions.get("move2"),
                        carousel_positions.get("move3"),
                        carousel_positions.get("move4"),
                    ],
                },
            },
            "verification": {
                "calculated_x": baking_position[0],
                "expected_x_wafer_55": 4.1298,
                "matches_expected": abs(baking_position[0] - 4.1298) < 0.001 if wafer_number == 55 else "N/A",
            },
        }

    async def get_debug_connection_state(self) -> Dict[str, Any]:
        """
        Get comprehensive connection diagnostics for debugging.

        Returns:
            Dictionary with detailed connection state information
        """
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

        # Check service readiness
        try:
            debug_info["service_ready"] = await self.ensure_robot_ready(allow_busy=True)
        except Exception as e:
            debug_info["errors"].append(f"Service readiness check failed: {str(e)}")

        # Check driver and robot instance
        if hasattr(self.async_wrapper, 'robot_driver'):
            debug_info["driver_available"] = True
            driver = self.async_wrapper.robot_driver

            try:
                robot_instance = driver.get_robot_instance() if hasattr(driver, 'get_robot_instance') else None
                debug_info["robot_instance_available"] = robot_instance is not None

                if robot_instance:
                    # Check socket connection status
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

                    # Get detailed robot status
                    try:
                        status = await driver.get_status()
                        debug_info["activation_status"] = status.get('activation_status', False)
                        debug_info["homing_status"] = status.get('homing_status', False)
                        debug_info["error_status"] = status.get('error_status', False)
                        debug_info["paused_status"] = status.get('paused', False)
                        debug_info["connection_details"] = status
                    except Exception as e:
                        debug_info["errors"].append(f"Status retrieval failed: {str(e)}")

            except Exception as e:
                debug_info["errors"].append(f"Driver instance check failed: {str(e)}")

        # Build summary
        overall_health = (
            debug_info["service_ready"]
            and debug_info["driver_available"]
            and debug_info["robot_instance_available"]
            and debug_info["socket_connected"]
            and debug_info["activation_status"]
            and debug_info["homing_status"]
            and not debug_info["error_status"]
        )

        return {
            "debug_info": debug_info,
            "summary": {
                "overall_health": overall_health,
                "connection_ready": debug_info["socket_connected"] and debug_info["robot_instance_available"],
                "robot_operational": debug_info["activation_status"] and debug_info["homing_status"] and not debug_info["error_status"],
            },
        }