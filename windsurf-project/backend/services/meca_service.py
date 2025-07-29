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
        
        # Movement parameters from config
        self.movement_params = self.robot_config.get("movement_params", {})
        
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
    
    async def _check_robot_connection(self) -> bool:
        """Check if Meca robot is connected and accessible, attempt reconnection if needed"""
        try:
            # First check basic TCP connectivity
            await self._test_robot_connection()
            
            # Check if we have a full robot connection (not just TCP)
            if hasattr(self.async_wrapper, 'robot_driver'):
                driver = self.async_wrapper.robot_driver
                robot_instance = driver.get_robot_instance() if hasattr(driver, 'get_robot_instance') else None
                
                if not robot_instance:
                    # TCP is working but no robot instance - check if we should attempt reconnection
                    current_time = time.time()
                    if current_time >= self._next_reconnect_time:
                        self.logger.info(f"TCP connection OK but no robot instance for {self.robot_id} - attempting reconnection (attempt {self._reconnect_attempt_count + 1})")
                        reconnected = await self._attempt_robot_reconnection()
                        if reconnected:
                            self.logger.info(f"🎉 Successfully reconnected to robot {self.robot_id}")
                            return True
                        else:
                            self.logger.debug(f"Robot reconnection attempt failed for {self.robot_id}")
                            return True  # TCP is working, just no full connection yet
                    else:
                        # Still in backoff period
                        remaining = self._next_reconnect_time - current_time
                        self.logger.debug(f"Robot {self.robot_id} reconnection in backoff - {remaining:.1f}s remaining")
                        return True  # TCP is working, just waiting for next retry
                        
            return True
        except Exception as e:
            self.logger.debug(f"Meca connection check failed: {e}")
            return False
    
    async def _attempt_robot_reconnection(self) -> bool:
        """Attempt to reconnect to the robot hardware (full mecademicpy connection) with exponential backoff"""
        try:
            if hasattr(self.async_wrapper, 'robot_driver'):
                driver = self.async_wrapper.robot_driver
                self.logger.info(f"🔄 Attempting full robot reconnection for {self.robot_id} (attempt {self._reconnect_attempt_count + 1}/{self._max_reconnect_attempts})")
                
                # Attempt the full robot connection
                connected = await driver.connect()
                
                if connected:
                    self.logger.info(f"✅ Robot reconnection successful for {self.robot_id}")
                    # Reset backoff state on successful connection
                    self._reset_reconnect_backoff()
                    
                    # Update robot state to reflect successful connection
                    await self.update_robot_state(
                        RobotState.IDLE,
                        reason="Robot hardware reconnected successfully"
                    )
                    return True
                else:
                    self.logger.debug(f"⚠️ Robot reconnection failed for {self.robot_id}")
                    self._schedule_next_reconnect_attempt("Connection returned False")
                    return False
            else:
                self.logger.warning(f"No robot_driver available for reconnection for {self.robot_id}")
                self._schedule_next_reconnect_attempt("No robot driver available")
                return False
                
        except Exception as e:
            # Check if it's the "Another user connected" error
            if "Another user is already connected" in str(e):
                self.logger.debug(f"⏳ Robot {self.robot_id} still has another user connected - will retry later")
                self._schedule_next_reconnect_attempt("Another user connected")
            else:
                self.logger.warning(f"⚠️ Robot reconnection error for {self.robot_id}: {e}")
                self._schedule_next_reconnect_attempt(f"Exception: {str(e)}")
            return False
    
    def _reset_reconnect_backoff(self):
        """Reset exponential backoff state after successful connection"""
        self._reconnect_attempt_count = 0
        self._next_reconnect_time = 0.0
        self.logger.debug(f"Reset reconnection backoff for {self.robot_id}")
    
    def _schedule_next_reconnect_attempt(self, reason: str):
        """Schedule the next reconnection attempt with exponential backoff"""
        self._reconnect_attempt_count += 1
        
        if self._reconnect_attempt_count >= self._max_reconnect_attempts:
            self.logger.warning(f"Maximum reconnection attempts ({self._max_reconnect_attempts}) reached for {self.robot_id}")
            # Reset to allow future attempts, but with maximum delay
            self._reconnect_attempt_count = self._max_reconnect_attempts - 1
        
        # Calculate exponential backoff delay: base_delay * 2^(attempt-1), capped at max_delay
        delay = min(
            self._base_reconnect_delay * (2 ** (self._reconnect_attempt_count - 1)),
            self._max_reconnect_delay
        )
        
        self._next_reconnect_time = time.time() + delay
        
        self.logger.info(
            f"Scheduled next reconnection attempt for {self.robot_id} in {delay:.1f}s "
            f"(attempt {self._reconnect_attempt_count}/{self._max_reconnect_attempts}, reason: {reason})"
        )
    
    async def _handle_connection_state_change(self, is_connected: bool):
        """Handle Meca robot connection state changes"""
        from core.state_manager import RobotState
        
        if is_connected:
            # Robot connected - set to IDLE state
            await self.update_robot_state(
                RobotState.IDLE,
                reason="Meca robot connection restored"
            )
            self.logger.info(f"Meca robot {self.robot_id} connection restored")
        else:
            # Robot disconnected - set to ERROR state
            await self.update_robot_state(
                RobotState.ERROR,
                reason="Meca robot connection lost"
            )
            self.logger.warning(f"Meca robot {self.robot_id} connection lost")
        
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
            
            self.logger.debug(f"Broadcasted Meca state change: connected={is_connected}")
            
        except Exception as e:
            self.logger.error(f"Failed to broadcast Meca state change: {e}")
    
    async def _on_start(self):
        """Initialize Meca robot connection on service start"""
        # First register the robot with state manager
        await super()._on_start()
        
        try:
            # Update to connecting state first
            await self.update_robot_state(
                RobotState.CONNECTING,
                reason="Attempting to connect to Meca robot"
            )
            
            # Test robot connection using status check
            try:
                await self._test_robot_connection()
                self.logger.info("TCP connection test successful, attempting full robot connection...")
                
                # Attempt full robot connection (mecademicpy Robot.Connect)
                robot_connection_established = False
                try:
                    if hasattr(self.async_wrapper, 'robot_driver'):
                        driver = self.async_wrapper.robot_driver
                        self.logger.info(f"🔄 Attempting mecademicpy Robot.Connect() during startup for {self.robot_id}")
                        
                        # Attempt connection
                        connected = await driver.connect()
                        
                        if connected:
                            self.logger.info(f"🎉 Full robot connection established during startup for {self.robot_id}")
                            # Reset backoff state on successful connection
                            self._reset_reconnect_backoff()
                            robot_connection_established = True
                        else:
                            self.logger.error(f"❌ Robot connection failed during startup for {self.robot_id}")
                            self.logger.error(f"💡 Check network connectivity and robot status at {driver.ip_address}:{driver.port}")
                    else:
                        self.logger.error(f"❌ No robot_driver available for connection for {self.robot_id}")
                        self.logger.error(f"💡 Check robot driver initialization in async_wrapper")
                        
                except Exception as robot_conn_error:
                    self.logger.error(f"❌ mecademicpy Robot.Connect() failed during startup for {self.robot_id}: {robot_conn_error}")
                    self.logger.error(f"💡 See detailed connection logs above for troubleshooting information")
                
                # CRITICAL: Only proceed if robot connection is established
                if not robot_connection_established:
                    self.logger.error(f"🚫 Robot {self.robot_id} connection failed - service cannot start without hardware connection")
                    # Set to error state instead of continuing
                    await self.update_robot_state(
                        RobotState.ERROR,
                        reason=f"Robot connection failed during startup"
                    )
                    # Don't raise exception here, just log the failure and let health monitoring handle reconnection
                    self.logger.error(f"💡 Health monitoring will attempt reconnection for {self.robot_id}")
                else:
                    self.logger.info(f"✅ Robot {self.robot_id} successfully connected and ready for operations")
                
                # Capture current position
                await self.capture_current_position()
                
                # Update robot state to idle if connection successful
                await self.update_robot_state(
                    RobotState.IDLE,
                    reason="Meca robot service started and connected"
                )
                
                self.logger.info("Meca robot service started successfully")
                
            except Exception as conn_error:
                self.logger.error(f"❌ Meca robot connection failed: {type(conn_error).__name__}: {conn_error}")
                self.logger.error(f"💡 Connection troubleshooting for {self.robot_id}:")
                robot_config = self.robot_config
                self.logger.error(f"   - Robot IP: {robot_config.get('ip', 'N/A')}")
                self.logger.error(f"   - Robot Port: {robot_config.get('port', 'N/A')}")
                self.logger.error(f"   - Timeout: {robot_config.get('timeout', 'N/A')}s")
                self.logger.error(f"   - Check robot power and network accessibility")
                # Set to error state from connecting state
                await self.update_robot_state(
                    RobotState.ERROR,
                    reason=f"Connection failed: {str(conn_error)}"
                )
            
        except Exception as e:
            self.logger.error(f"💥 Failed to start Meca robot service: {type(e).__name__}: {e}")
            self.logger.error(f"💡 Service startup troubleshooting:")
            self.logger.error(f"   1. Check system dependencies and imports")
            self.logger.error(f"   2. Verify configuration settings")
            self.logger.error(f"   3. Check state manager and lock manager initialization")
            # If we can't even get to connecting state, there's a critical issue
            try:
                await self.update_robot_state(
                    RobotState.ERROR,
                    reason=f"Critical startup failure: {str(e)}"
                )
            except Exception as state_error:
                self.logger.error(f"Could not update robot state: {state_error}")
    
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
    
    async def ensure_robot_ready(self, allow_busy: bool = True) -> bool:
        """
        Override base method to add hardware state verification for Mecademic robot.
        
        Ensures both software state (IDLE/BUSY) and hardware state (activated/homed)
        are ready before allowing operations to proceed.
        
        Args:
            allow_busy: Whether to allow BUSY state (for operations already in progress)
            
        Returns:
            True if robot is ready for operations
            
        Raises:
            ValidationError: If robot is not in valid state
            HardwareError: If hardware activation/homing fails
        """
        # First check software state using base class method
        await super().ensure_robot_ready(allow_busy)
        
        # Now check hardware state for Mecademic-specific requirements
        try:
            self.logger.debug(f"Checking Mecademic hardware state for {self.robot_id}")
            
            # Get robot status from driver
            if not hasattr(self.async_wrapper, 'robot_driver'):
                self.logger.warning(f"No robot driver available for {self.robot_id} - skipping hardware state check")
                return True
                
            driver = self.async_wrapper.robot_driver
            robot_instance = driver.get_robot_instance() if hasattr(driver, 'get_robot_instance') else None
            
            if not robot_instance:
                self.logger.warning(f"No robot instance available for {self.robot_id} - skipping hardware state check")
                return True
            
            # Get current robot status
            status = await driver.get_status()
            activation_status = status.get('activation_status', False)
            homing_status = status.get('homing_status', False)
            error_status = status.get('error_status', False)
            pause_status = status.get('paused', False)
            
            self.logger.debug(f"Robot {self.robot_id} hardware state - Activated: {activation_status}, Homed: {homing_status}, Error: {error_status}, Paused: {pause_status}")
            
            # Step 1: Reset any error condition first
            if error_status:
                self.logger.info(f"🔧 Robot {self.robot_id} has error - resetting...")
                try:
                    reset_success = await driver.reset_error()
                    if reset_success:
                        self.logger.info(f"✅ Error reset successful for {self.robot_id}")
                        # Re-check status after reset
                        await asyncio.sleep(2.0)
                        status = await driver.get_status()
                        activation_status = status.get('activation_status', False)
                        homing_status = status.get('homing_status', False)
                        error_status = status.get('error_status', False)
                        pause_status = status.get('paused', False)
                    else:
                        raise HardwareError(f"Failed to reset error for robot {self.robot_id}", robot_id=self.robot_id)
                except Exception as e:
                    error_msg = f"Error reset failed for robot {self.robot_id}: {str(e)}"
                    self.logger.error(error_msg)
                    raise HardwareError(error_msg, robot_id=self.robot_id)
            
            # Check if robot needs activation
            if not activation_status:
                self.logger.info(f"🔧 Robot {self.robot_id} not activated - activating now...")
                try:
                    await driver.activate_robot()
                    self.logger.info(f"✅ Robot {self.robot_id} activation command sent")
                    
                    # Wait and verify activation completed
                    await asyncio.sleep(2.0)  # Give time for activation to complete
                    verification_status = await driver.get_status()
                    if not verification_status.get('activation_status', False):
                        raise HardwareError(f"Robot {self.robot_id} activation failed to complete", robot_id=self.robot_id)
                    
                    self.logger.info(f"✅ Robot {self.robot_id} activation verified")
                    activation_status = True  # Update local status
                    
                except Exception as e:
                    error_msg = f"Failed to activate robot {self.robot_id}: {str(e)}"
                    self.logger.error(error_msg)
                    raise HardwareError(error_msg, robot_id=self.robot_id)
            
            # Step 3: Resume motion if paused and not homed (prevents homing deadlock)
            if pause_status and not homing_status:
                self.logger.info(f"🔧 Robot {self.robot_id} is paused and not homed - resuming before homing...")
                try:
                    resume_success = await driver.resume_motion()
                    if resume_success:
                        self.logger.info(f"✅ Motion resumed for robot {self.robot_id} before homing")
                        # Update pause status
                        await asyncio.sleep(1.0)
                        status = await driver.get_status()
                        pause_status = status.get('paused', False)
                    else:
                        self.logger.warning(f"⚠️ Failed to resume motion before homing for {self.robot_id}")
                except Exception as e:
                    self.logger.error(f"Failed to resume motion before homing for {self.robot_id}: {str(e)}")
            
            # Step 4: Home robot if needed, then wait for completion
            if not homing_status:
                self.logger.info(f"🏠 Robot {self.robot_id} not homed - homing now...")
                try:
                    await driver.home_robot()
                    self.logger.info(f"✅ Robot {self.robot_id} homing command sent")
                    
                    # Wait for homing to complete using wait_idle
                    self.logger.info(f"⏳ Waiting for robot {self.robot_id} to complete homing...")
                    wait_success = await driver.wait_idle(timeout=30.0)
                    if not wait_success:
                        self.logger.warning(f"⚠️ Wait idle timeout for robot {self.robot_id} - checking status")
                    
                    # Verify homing completed
                    verification_status = await driver.get_status()
                    if not verification_status.get('homing_status', False):
                        raise HardwareError(f"Robot {self.robot_id} homing failed to complete", robot_id=self.robot_id)
                    
                    self.logger.info(f"✅ Robot {self.robot_id} homing verified")
                    homing_status = True  # Update local status
                    
                except Exception as e:
                    error_msg = f"Failed to home robot {self.robot_id}: {str(e)}"
                    self.logger.error(error_msg)
                    raise HardwareError(error_msg, robot_id=self.robot_id)
            
            # Clear motion queue and resume motion after successful homing/activation
            if homing_status and activation_status:
                try:
                    self.logger.info(f"🔧 Clearing and resuming motion for {self.robot_id}")
                    
                    # Clear any leftover motion queue (this also pauses the robot)
                    clear_success = await driver.clear_motion()
                    if not clear_success:
                        self.logger.warning(f"⚠️ Failed to clear motion for {self.robot_id}")
                    
                    # Resume motion so robot is ready for new commands
                    resume_success = await driver.resume_motion()
                    if not resume_success:
                        self.logger.warning(f"⚠️ Failed to resume motion for {self.robot_id}")
                    
                    if clear_success and resume_success:
                        self.logger.info(f"✅ Motion cleared and resumed for {self.robot_id}")
                    
                except Exception as e:
                    # Log error but don't fail - robot is still technically ready
                    self.logger.error(f"⚠️ Failed to clear/resume motion for {self.robot_id}: {str(e)}", exc_info=True)
            
            # Final verification of robot readiness
            final_status = await driver.get_status()
            final_activation = final_status.get('activation_status', False)
            final_homing = final_status.get('homing_status', False)
            error_status = final_status.get('error_status', False)
            
            if error_status:
                self.logger.warning(f"🔧 Robot {self.robot_id} is in error state - attempting error recovery...")
                try:
                    # Attempt to reset the error state
                    reset_success = await driver.reset_error()
                    if reset_success:
                        self.logger.info(f"✅ Error state cleared for robot {self.robot_id}")
                        # Re-check status after error reset
                        await asyncio.sleep(1.0)
                        reset_status = await driver.get_status()
                        error_after_reset = reset_status.get('error_status', True)
                        if not error_after_reset:
                            self.logger.info(f"✅ Robot {self.robot_id} error recovery successful")
                            # Update local status variables
                            activation_status = reset_status.get('activation_status', False)
                            homing_status = reset_status.get('homing_status', False)
                            error_status = False
                        else:
                            error_msg = f"Robot {self.robot_id} still in error state after reset attempt"
                            self.logger.error(error_msg)
                            raise HardwareError(error_msg, robot_id=self.robot_id)
                    else:
                        error_msg = f"Failed to reset error state for robot {self.robot_id}"
                        self.logger.error(error_msg)
                        raise HardwareError(error_msg, robot_id=self.robot_id)
                except Exception as e:
                    error_msg = f"Error during error recovery for robot {self.robot_id}: {str(e)}"
                    self.logger.error(error_msg)
                    raise HardwareError(error_msg, robot_id=self.robot_id)
            
            if not final_activation or not final_homing:
                error_msg = f"Robot {self.robot_id} final state check failed - Activated: {final_activation}, Homed: {final_homing}"
                self.logger.error(error_msg)
                raise HardwareError(error_msg, robot_id=self.robot_id)
            
            self.logger.info(f"✅ Robot {self.robot_id} hardware state verified - Activated: {final_activation}, Homed: {final_homing}, Ready for operations")
            
            return True
            
        except HardwareError:
            # Re-raise hardware errors as-is
            raise
        except Exception as e:
            error_msg = f"Unexpected error checking hardware state for {self.robot_id}: {str(e)}"
            self.logger.error(error_msg)
            raise HardwareError(error_msg, robot_id=self.robot_id)
    
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
        
        Args:
            wafer_index: Wafer index (0-54 for wafers 1-55)
            operation: Operation type ('pickup', 'drop', 'carousel', 'empty_carousel')
            
        Returns:
            Dictionary of position names to coordinate lists
        """
        positions = {}
        
        if operation == "pickup":
            # High point above pickup position
            pickup_pos = self.calculate_wafer_position(wafer_index, "inert")
            high_point = copy.deepcopy(pickup_pos)
            high_point[1] += 0.2
            high_point[2] += 11.9286
            positions["pickup_high"] = high_point
            
            # Intermediate movement positions
            intermediate_pos1 = copy.deepcopy(self.FIRST_WAFER)
            intermediate_pos1[1] += self.GAP_WAFERS * wafer_index - 0.2
            intermediate_pos1[2] += 2.8
            positions["intermediate_1"] = intermediate_pos1
            
            intermediate_pos2 = copy.deepcopy(intermediate_pos1)
            intermediate_pos2[1] -= 0.8
            intermediate_pos2[2] += 2.7
            positions["intermediate_2"] = intermediate_pos2
            
            intermediate_pos3 = copy.deepcopy(intermediate_pos2)
            intermediate_pos3[1] -= 11.5595
            intermediate_pos3[2] += 31.4
            positions["intermediate_3"] = intermediate_pos3
            
            # Spreader positions
            spread_index = 4 - (wafer_index % 5)
            above_spreader = copy.deepcopy(self.GEN_DROP[spread_index])
            above_spreader[2] += 40.4987
            positions["above_spreader"] = above_spreader
            
            spreader = copy.deepcopy(self.GEN_DROP[spread_index])
            positions["spreader"] = spreader
            
            above_spreader_exit = copy.deepcopy(self.GEN_DROP[spread_index])
            above_spreader_exit[2] += 56.4987
            positions["above_spreader_exit"] = above_spreader_exit
            
        elif operation == "drop":
            # Drop sequence positions from spreader to baking tray
            spread_index = 4 - (wafer_index % 5)
            above_spreader = copy.deepcopy(self.GEN_DROP[spread_index])
            above_spreader[2] += 36.6
            positions["above_spreader"] = above_spreader
            
            spreader = copy.deepcopy(self.GEN_DROP[spread_index])
            positions["spreader"] = spreader
            
            above_spreader_pickup = copy.deepcopy(self.GEN_DROP[spread_index])
            above_spreader_pickup[2] += 25.4987
            positions["above_spreader_pickup"] = above_spreader_pickup
            
            # Baking tray alignment positions
            baking_align1 = copy.deepcopy(self.FIRST_BAKING_TRAY)
            baking_align1[0] += self.GAP_WAFERS * wafer_index - 9.7
            baking_align1[1] += 0.3
            baking_align1[2] += 32.058
            positions["baking_align1"] = baking_align1
            
            baking_align2 = copy.deepcopy(self.FIRST_BAKING_TRAY)
            baking_align2[0] += self.GAP_WAFERS * wafer_index - 7.7
            baking_align2[1] += 0.3
            baking_align2[2] += 22
            positions["baking_align2"] = baking_align2
            
            baking_align3 = copy.deepcopy(self.FIRST_BAKING_TRAY)
            baking_align3[0] += self.GAP_WAFERS * wafer_index - 2.1
            baking_align3[1] += 0.3
            baking_align3[2] += 6
            positions["baking_align3"] = baking_align3
            
            baking_align4 = copy.deepcopy(self.FIRST_BAKING_TRAY)
            baking_align4[0] += self.GAP_WAFERS * wafer_index - 0.7
            baking_align4[1] += 0.3
            baking_align4[2] += 2.8
            positions["baking_align4"] = baking_align4
            
            baking_up = copy.deepcopy(self.FIRST_BAKING_TRAY)
            baking_up[0] += self.GAP_WAFERS * wafer_index
            baking_up[2] += 29.458
            positions["baking_up"] = baking_up
            
        elif operation == "carousel":
            # Carousel movement positions
            above_baking = copy.deepcopy(self.FIRST_BAKING_TRAY)
            above_baking[0] += self.GAP_WAFERS * wafer_index
            above_baking[2] += 27.558
            positions["above_baking"] = above_baking
            
            # Movement sequence positions
            move1 = copy.deepcopy(self.FIRST_BAKING_TRAY)
            move1[0] += self.GAP_WAFERS * wafer_index - 0.7
            move1[2] += 2.8
            positions["move1"] = move1
            
            move2 = copy.deepcopy(self.FIRST_BAKING_TRAY)
            move2[0] += self.GAP_WAFERS * wafer_index - 2.1
            move2[2] += 6
            positions["move2"] = move2
            
            move3 = copy.deepcopy(self.FIRST_BAKING_TRAY)
            move3[0] += self.GAP_WAFERS * wafer_index - 7.7
            move3[2] += 22
            positions["move3"] = move3
            
            move4 = copy.deepcopy(self.FIRST_BAKING_TRAY)
            move4[0] += self.GAP_WAFERS * wafer_index - 9.7
            move4[2] += 32.058
            positions["move4"] = move4
            
            # Carousel approach positions
            y_away1 = copy.deepcopy(self.CAROUSEL)
            y_away1[1] = -216.95
            y_away1[2] = 119.9
            positions["y_away1"] = y_away1
            
            y_away2 = copy.deepcopy(self.CAROUSEL)
            y_away2[1] = -245.95
            y_away2[2] = 115.9
            positions["y_away2"] = y_away2
            
            above_carousel1 = copy.deepcopy(self.CAROUSEL)
            above_carousel1[2] = 115.9
            positions["above_carousel1"] = above_carousel1
            
            above_carousel2 = copy.deepcopy(self.CAROUSEL)
            above_carousel2[2] = 109.9
            positions["above_carousel2"] = above_carousel2
            
            above_carousel3 = copy.deepcopy(self.CAROUSEL)
            above_carousel3[2] = 103.9
            positions["above_carousel3"] = above_carousel3
            
        elif operation == "empty_carousel":
            # Empty carousel positions (reverse of carousel)
            y_away1 = copy.deepcopy(self.CAROUSEL)
            y_away1[1] = -216.95
            y_away1[2] = 119.9
            positions["y_away1"] = y_away1
            
            y_away2 = copy.deepcopy(self.CAROUSEL)
            y_away2[1] = -245.95
            y_away2[2] = 119.9
            positions["y_away2"] = y_away2
            
            above_carousel = copy.deepcopy(self.CAROUSEL)
            above_carousel[2] = 115.9
            positions["above_carousel"] = above_carousel
            
            # Reverse movement positions for baking tray
            move4_rev = copy.deepcopy(self.FIRST_BAKING_TRAY)
            move4_rev[0] += self.GAP_WAFERS * wafer_index - 9.7
            move4_rev[1] += 0.3
            move4_rev[2] += 32.058
            positions["move4_rev"] = move4_rev
            
            move3_rev = copy.deepcopy(self.FIRST_BAKING_TRAY)
            move3_rev[0] += self.GAP_WAFERS * wafer_index - 7.7
            move3_rev[1] += 0.3
            move3_rev[2] += 22
            positions["move3_rev"] = move3_rev
            
            move2_rev = copy.deepcopy(self.FIRST_BAKING_TRAY)
            move2_rev[0] += self.GAP_WAFERS * wafer_index - 2.1
            move2_rev[1] += 0.3
            move2_rev[2] += 6
            positions["move2_rev"] = move2_rev
            
            move1_rev = copy.deepcopy(self.FIRST_BAKING_TRAY)
            move1_rev[0] += self.GAP_WAFERS * wafer_index - 0.7
            move1_rev[1] += 0.3
            move1_rev[2] += 2.8
            positions["move1_rev"] = move1_rev
            
            above_baking_rev = copy.deepcopy(self.FIRST_BAKING_TRAY)
            above_baking_rev[0] += self.GAP_WAFERS * wafer_index
            above_baking_rev[2] += 22.058
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
        """
        Connect to the Mecademic robot.
        
        Returns:
            ServiceResult with connection status
        """
        context = OperationContext(
            operation_id=f"{self.robot_id}_connect_{int(time.time() * 1000)}",
            robot_id=self.robot_id,
            operation_type="connect",
            timeout=self.settings.meca_timeout
        )
        
        async def _connect():
            await self.update_robot_state(
                RobotState.CONNECTING,
                reason="Attempting to connect to robot"
            )
            
            try:
                # Get the underlying Mecademic driver
                if hasattr(self.async_wrapper, 'robot_driver'):
                    driver = self.async_wrapper.robot_driver
                    
                    # Attempt connection
                    connected = await driver.connect()
                    
                    if connected:
                        # Reset backoff state on successful connection
                        self._reset_reconnect_backoff()
                        
                        # Capture initial position
                        await self.capture_current_position()
                        
                        # Update state to idle
                        await self.update_robot_state(
                            RobotState.IDLE,
                            reason="Successfully connected to robot"
                        )
                        
                        self.logger.info(f"Successfully connected to robot {self.robot_id}")
                        return True
                    else:
                        await self.update_robot_state(
                            RobotState.ERROR,
                            reason="Failed to connect to robot"
                        )
                        return False
                else:
                    await self.update_robot_state(
                        RobotState.ERROR,
                        reason="Robot driver not available"
                    )
                    return False
                    
            except Exception as e:
                await self.update_robot_state(
                    RobotState.ERROR,
                    reason=f"Connection error: {str(e)}"
                )
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
    
    async def _execute_emergency_stop(self) -> bool:
        """Emergency stop implementation for Mecademic robot"""
        try:
            # Emergency stop through hardware
            if hasattr(self.async_wrapper.robot_driver, 'EmergencyStop'):
                await self.async_wrapper.execute_movement(
                    MovementCommand(command_type="emergency_stop")
                )
            
            # Open gripper for safety
            await self._open_gripper()
            
            return True
        except Exception as e:
            self.logger.error(f"Emergency stop failed: {e}")
            return False
    
    @circuit_breaker("meca_connection", failure_threshold=3, recovery_timeout=30)
    async def pickup_wafer_sequence(
        self,
        wafer_id: str,
        pickup_position: WaferPosition,
        safe_height_offset: float = 50.0
    ) -> ServiceResult[Dict[str, Any]]:
        """
        Execute complete wafer pickup sequence with safety checks.
        
        Args:
            wafer_id: Unique wafer identifier
            pickup_position: Position where wafer is located
            safe_height_offset: Height offset for safe approach
        """
        context = OperationContext(
            operation_id=f"{self.robot_id}_pickup_{wafer_id}",
            robot_id=self.robot_id,
            operation_type=MecaOperationType.PICKUP_WAFER.value,
            timeout=self.settings.operation_timeout,
            metadata={"wafer_id": wafer_id, "position": pickup_position}
        )
        
        async def _pickup_sequence():
            # Ensure robot is ready (CommandService already set to BUSY)
            await self.ensure_robot_ready()
            
            try:
                # Step 1: Move to safe position
                await self._move_to_position(self.safe_position, "safe_position")
                
                # Step 2: Open gripper
                await self._open_gripper()
                
                # Step 3: Move to safe approach position (above pickup)
                approach_position = WaferPosition(
                    x=pickup_position.x,
                    y=pickup_position.y,
                    z=pickup_position.z + safe_height_offset,
                    alpha=pickup_position.alpha,
                    beta=pickup_position.beta,
                    gamma=pickup_position.gamma
                )
                await self._move_to_position(approach_position, "approach")
                
                # Step 4: Move down to pickup position
                await self._move_to_position(pickup_position, "pickup")
                
                # Step 5: Close gripper
                await self._close_gripper()
                
                # Step 6: Move back to safe height
                await self._move_to_position(approach_position, "lift")
                
                # Step 7: Return to safe position
                await self._move_to_position(self.safe_position, "safe_return")
                
                result = {
                    "wafer_id": wafer_id,
                    "pickup_position": pickup_position,
                    "status": "completed"
                }
                
                self.logger.info(f"Wafer pickup completed: {wafer_id}")
                return result
                
            except Exception as e:
                self.logger.error(f"Pickup sequence failed for wafer {wafer_id}: {e}")
                raise
        
        return await self.execute_operation(context, _pickup_sequence)
    
    async def drop_wafer_sequence(
        self,
        wafer_id: str,
        drop_position: WaferPosition,
        safe_height_offset: float = 50.0
    ) -> ServiceResult[Dict[str, Any]]:
        """
        Execute complete wafer drop sequence with safety checks.
        
        Args:
            wafer_id: Unique wafer identifier
            drop_position: Position where wafer should be placed
            safe_height_offset: Height offset for safe approach
        """
        context = OperationContext(
            operation_id=f"{self.robot_id}_drop_{wafer_id}",
            robot_id=self.robot_id,
            operation_type=MecaOperationType.DROP_WAFER.value,
            timeout=self.settings.operation_timeout,
            metadata={"wafer_id": wafer_id, "position": drop_position}
        )
        
        async def _drop_sequence():
            # Ensure robot is ready (CommandService already set to BUSY)
            await self.ensure_robot_ready()
            
            try:
                # Step 1: Move to safe approach position
                approach_position = WaferPosition(
                    x=drop_position.x,
                    y=drop_position.y,
                    z=drop_position.z + safe_height_offset,
                    alpha=drop_position.alpha,
                    beta=drop_position.beta,
                    gamma=drop_position.gamma
                )
                await self._move_to_position(approach_position, "approach")
                
                # Step 2: Move down to drop position
                await self._move_to_position(drop_position, "drop")
                
                # Step 3: Open gripper
                await self._open_gripper()
                
                # Step 4: Move back to safe height
                await self._move_to_position(approach_position, "lift")
                
                # Step 5: Return to safe position
                await self._move_to_position(self.safe_position, "safe_return")
                
                result = {
                    "wafer_id": wafer_id,
                    "drop_position": drop_position,
                    "status": "completed"
                }
                
                self.logger.info(f"Wafer drop completed: {wafer_id}")
                return result
                
            except Exception as e:
                self.logger.error(f"Drop sequence failed for wafer {wafer_id}: {e}")
                raise
        
        return await self.execute_operation(context, _drop_sequence)
    
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
    
    # Wafer sequence methods - exact implementations from Meca_FullCode.py
    
    async def execute_pickup_sequence(self, start: int, count: int) -> ServiceResult[Dict[str, Any]]:
        """
        Execute wafer pickup sequence from inert tray to spreader.
        Exact implementation of createPickUpPt() from Meca_FullCode.py
        
        Args:
            start: Starting wafer index (0-based)
            count: Number of wafers to process
        """
        context = OperationContext(
            operation_id=f"{self.robot_id}_pickup_sequence_{start}_{count}",
            robot_id=self.robot_id,
            operation_type=MecaOperationType.PICKUP_WAFER.value,
            timeout=600.0,  # 10 minutes for pickup sequence
            metadata={"start": start, "count": count}
        )
        
        async def _pickup_sequence():
            await self.ensure_robot_ready()
            
            self.logger.info(f"Starting pickup sequence for wafers {start+1} to {start+count}")
            
            # Initial statements for first wafer
            if start == 0:
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
            
            for i in range(start, start + count):
                wafer_num = i + 1
                self.logger.info(f"Processing wafer {wafer_num}")
                
                # Get positions for this wafer
                positions = self.calculate_intermediate_positions(i, "pickup")
                pickup_position = self.calculate_wafer_position(i, "inert")
                
                # Move to high position above wafer
                await self._execute_movement_command("MovePose", positions["pickup_high"])
                
                # Move to pickup position
                await self._execute_movement_command("MovePose", pickup_position)
                await self._execute_movement_command("Delay", [1])
                
                # Close gripper to pick wafer
                await self._execute_movement_command("GripperClose", [])
                await self._execute_movement_command("Delay", [1])
                
                # Move up with wafer through intermediate positions
                await self._execute_movement_command("SetJointVel", [self.WAFER_SPEED])
                await self._execute_movement_command("MovePose", positions["intermediate_1"])
                await self._execute_movement_command("SetBlending", [100])
                await self._execute_movement_command("MovePose", positions["intermediate_2"])
                await self._execute_movement_command("MoveLin", positions["intermediate_3"])
                await self._execute_movement_command("SetBlending", [0])
                
                # Move to safe point
                await self._execute_movement_command("MovePose", self.SAFE_POINT)
                
                # Move to spreader
                await self._execute_movement_command("SetJointVel", [self.ALIGN_SPEED])
                await self._execute_movement_command("MovePose", positions["above_spreader"])
                await self._execute_movement_command("MovePose", positions["spreader"])
                await self._execute_movement_command("Delay", [1])
                
                # Release wafer
                await self._execute_movement_command("GripperOpen", [])
                await self._execute_movement_command("Delay", [1])
                
                # Move up and return to safe point
                await self._execute_movement_command("MovePose", positions["above_spreader_exit"])
                await self._execute_movement_command("SetJointVel", [self.EMPTY_SPEED])
                await self._execute_movement_command("MovePose", self.SAFE_POINT)
                
                # Add spreading wait time when needed
                if (4 - (i % 5)) == 0:
                    await self._execute_movement_command("Delay", [self.SPREAD_WAIT])
            
            result = {
                "status": "completed",
                "wafers_processed": count,
                "start_wafer": start + 1,
                "end_wafer": start + count
            }
            
            self.logger.info(f"Pickup sequence completed for wafers {start+1} to {start+count}")
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
        """
        Helper method to execute movement commands through the async wrapper.
        
        Args:
            command_type: Type of movement command (e.g., "MovePose", "SetJointVel")
            parameters: List of parameters for the command
        """
        if parameters is None:
            parameters = []
        
        # Validate parameters before sending to robot
        try:
            self._validate_robot_parameters(command_type, parameters)
            self.logger.debug(f"Parameters validated for command {command_type}: {parameters}")
        except ValidationError as e:
            self.logger.error(f"Parameter validation failed for {command_type}: {e}")
            raise
        
        # Convert list parameters to proper format for MovementCommand
        if command_type == "MovePose" and len(parameters) == 6:
            # MovePose with 6 coordinates
            command = MovementCommand(
                command_type="MovePose",
                target_position={
                    "x": parameters[0],
                    "y": parameters[1], 
                    "z": parameters[2],
                    "alpha": parameters[3],
                    "beta": parameters[4],
                    "gamma": parameters[5]
                }
            )
        elif command_type == "MoveLin" and len(parameters) == 6:
            # Linear movement with 6 coordinates
            command = MovementCommand(
                command_type="MoveLin",
                target_position={
                    "x": parameters[0],
                    "y": parameters[1],
                    "z": parameters[2], 
                    "alpha": parameters[3],
                    "beta": parameters[4],
                    "gamma": parameters[5]
                }
            )
        elif command_type == "GripperOpen":
            command = MovementCommand(
                command_type="GripperOpen",
                tool_action="grip_open"
            )
        elif command_type == "GripperClose":
            command = MovementCommand(
                command_type="GripperClose", 
                tool_action="grip_close"
            )
        elif command_type == "MoveGripper" and len(parameters) == 1:
            command = MovementCommand(
                command_type="MoveGripper",
                tool_action="grip_move",
                parameters={"width": parameters[0]}
            )
        elif command_type == "Delay" and len(parameters) == 1:
            command = MovementCommand(
                command_type="Delay",
                parameters={"duration": parameters[0]}
            )
        elif command_type.startswith("Set"):
            # Configuration commands
            command = MovementCommand(
                command_type="config",
                parameters={"config_type": command_type, "values": parameters}
            )
        else:
            # Generic command
            command = MovementCommand(
                command_type=command_type.lower(),
                parameters={"values": parameters} if parameters else {}
            )
        
        result = await self.async_wrapper.execute_movement(command)
        if not result.success:
            raise HardwareError(f"Movement command {command_type} failed: {result.error}", robot_id=self.robot_id)
    
    async def execute_drop_sequence(self, start: int, count: int) -> ServiceResult[Dict[str, Any]]:
        """
        Execute wafer drop sequence from spreader to baking tray.
        Exact implementation of createDropPt() from Meca_FullCode.py
        
        Args:
            start: Starting wafer index (0-based)
            count: Number of wafers to process
        """
        context = OperationContext(
            operation_id=f"{self.robot_id}_drop_sequence_{start}_{count}",
            robot_id=self.robot_id,
            operation_type=MecaOperationType.DROP_WAFER.value,
            timeout=600.0,  # 10 minutes for drop sequence
            metadata={"start": start, "count": count}
        )
        
        async def _drop_sequence():
            await self.ensure_robot_ready()
            
            self.logger.info(f"Starting drop sequence for wafers {start+1} to {start+count}")
            
            for i in range(start, start + count):
                wafer_num = i + 1
                self.logger.info(f"Processing wafer {wafer_num} drop from spreader to baking tray")
                
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
            
            result = {
                "status": "completed",
                "wafers_processed": count,
                "start_wafer": start + 1,
                "end_wafer": start + count
            }
            
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
            
            # Configuration specific to carousel movement
            if start == 0:
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