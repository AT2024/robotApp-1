"""
Mecademic Robot Driver Implementation.
Native TCP implementation with NIC-binding transport for precise network control.
"""

import asyncio
import time
from typing import Dict, Any, Optional

from core.exceptions import ConnectionError, HardwareError, ConfigurationError
from core.hardware_manager import BaseRobotDriver
from utils.logger import get_logger
from .native_mecademic import NativeMecademicDriver, MecademicConfig, RobotState as NativeRobotState


class MecademicDriver(BaseRobotDriver):
    """
    Mecademic robot driver implementing BaseRobotDriver interface.
    
    Uses native TCP implementation with NIC-binding transport for 
    precise network control and improved performance.
    """
    
    def __init__(self, robot_id: str, config: Dict[str, Any]):
        super().__init__(robot_id, config)
        self.logger = get_logger(f"meca_driver_{robot_id}")
        
        # Extract configuration
        self.ip_address = config.get("ip", "192.168.0.100")
        self.port = config.get("port", 10000)
        self.timeout = config.get("timeout", 30.0)
        self.retry_attempts = config.get("retry_attempts", 3)
        self.retry_delay = config.get("retry_delay", 1.0)
        
        # Movement parameters
        self.force = config.get("force", 50.0)
        self.acceleration = config.get("acceleration", 25.0)
        self.speed = config.get("speed", 25.0)
        
        # Network binding configuration
        self.bind_interface = config.get("bind_interface", None)
        self.bind_ip = config.get("bind_ip", None)
        
        # Create native driver configuration
        native_config = MecademicConfig(
            robot_ip=self.ip_address,
            control_port=self.port,
            monitor_port=config.get("monitor_port", 10001),
            bind_interface=self.bind_interface,
            bind_ip=self.bind_ip,
            connect_timeout=self.timeout,
            command_timeout=config.get("command_timeout", 30.0),
            default_speed=self.speed,
            default_acceleration=self.acceleration,
        )
        
        # Native Mecademic driver instance
        self._native_driver = NativeMecademicDriver(native_config)
        
        # Connection state
        self._last_status = {}
        self._last_status_time = 0.0
        self._status_cache_duration = 1.0  # Cache for 1 second
        
        self.logger.info(
            f"Initialized Native Mecademic driver for {robot_id} at {self.ip_address}:{self.port}"
            f"{f' via {self.bind_interface or self.bind_ip}' if (self.bind_interface or self.bind_ip) else ''}"
        )
    
    def set_settings(self, settings):
        """Set settings reference for debug logging"""
        self._settings = settings
    
    def debug_log(self, method: str, step: str, message: str, context: Dict[str, Any] = None):
        """
        Debug logging utility for driver operations.
        Only logs when enable_debug_logging is True in settings.
        """
        if not hasattr(self, '_settings') or not self._settings or not self._settings.enable_debug_logging:
            return
            
        context_str = ""
        if context:
            context_str = f" ({context})"
            
        timestamp = time.time()
        debug_msg = f"ROBOT_DEBUG [{self.robot_id}] {method}:{step} - {message}{context_str} [{timestamp:.3f}]"
        self.logger.debug(debug_msg)
    
    def clear_status_cache(self):
        """Clear cached status to force fresh fetch"""
        self.debug_log("clear_status_cache", "clearing", "Clearing status cache to force fresh fetch")
        self._last_status = {}
        self._last_status_time = 0.0
    
    async def __aenter__(self):
        """Async context manager entry"""
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        await self.shutdown()
    
    async def shutdown(self):
        """Shutdown the driver and cleanup resources"""
        try:
            if self._connected:
                await self.disconnect()
        finally:
            # Disconnect native driver
            if self._native_driver:
                await self._native_driver.disconnect()
            self.logger.info(f"Mecademic driver for {self.robot_id} shutdown complete")
    
    async def _connect_impl(self) -> bool:
        """Implementation-specific connection logic using native driver"""
        try:
            self.debug_log("_connect_impl", "entry", "Starting Native MecademicDriver connection process")
            self.logger.info(f"🔄 Starting Native MecademicDriver connection process for {self.robot_id}")
            
            # Connect using native driver
            self.debug_log("_connect_impl", "native_connect", "Connecting via native TCP driver")
            self.logger.info(f"📡 Connecting via native TCP driver to {self.ip_address}:{self.port} for {self.robot_id}")
            
            connect_success = await self._native_driver.connect()
            
            if connect_success:
                self.debug_log("_connect_impl", "native_success", "Native driver connection succeeded")
                self.logger.info(f"🎉 Native driver connection succeeded for {self.robot_id}")
                
                # Clear status cache to ensure fresh status on next get_status() call
                self.debug_log("_connect_impl", "cache_clear", "Clearing status cache after successful connection")
                self.clear_status_cache()
                
                self.logger.info(f"🏆 Native MecademicDriver fully initialized and connected for {self.robot_id}")
                return True
            else:
                self.logger.error(f"❌ Native driver connection failed for {self.robot_id}")
                return False
                
        except Exception as e:
            self.logger.error(f"💥 Critical connection failure for {self.robot_id}: {type(e).__name__}: {e}")
            return False
    
    async def _disconnect_impl(self) -> bool:
        """Implementation-specific disconnection logic"""
        try:
            self.debug_log("_disconnect_impl", "entry", "Starting disconnection process")
            self.logger.info(f"🔄 Disconnecting from robot {self.robot_id}")
            
            if self._native_driver:
                await self._native_driver.disconnect()
                self.debug_log("_disconnect_impl", "success", "Native driver disconnected successfully")
                self.logger.info(f"✅ Successfully disconnected from robot {self.robot_id}")
            
            return True
        except Exception as e:
            self.logger.error(f"Error during disconnection for {self.robot_id}: {e}")
            return False
    
    async def _ping_impl(self) -> float:
        """Implementation-specific ping logic"""
        start_time = time.time()
        
        try:
            if not self._native_driver or not self._native_driver.is_connected:
                raise ConnectionError("Robot not connected")
            
            # Use native driver status check as ping
            status = self._native_driver.status
            ping_time = time.time() - start_time
            
            self.debug_log("_ping_impl", "success", f"Ping successful", {"ping_time": ping_time})
            return ping_time
            
        except Exception as e:
            self.logger.error(f"Ping failed for {self.robot_id}: {e}")
            raise ConnectionError(f"Ping failed: {e}", robot_id=self.robot_id)
    
    async def _get_status_impl(self) -> Dict[str, Any]:
        """Implementation-specific status logic"""
        current_time = time.time()
        
        self.debug_log("_get_status_impl", "entry", "Getting robot status")
        
        # Check cache first
        if (self._last_status and 
            current_time - self._last_status_time < self._status_cache_duration):
            self.debug_log("_get_status_impl", "cache_hit", "Returning cached status")
            return self._last_status
        
        try:
            if not self._native_driver or not self._native_driver.is_connected:
                return {
                    "connected": False,
                    "error": "Robot not connected",
                    "timestamp": current_time
                }
            
            # Get status from native driver
            native_status = self._native_driver.status
            
            # Convert native status to windsurf format
            status = {
                "connected": self._native_driver.is_connected,
                "state": native_status.state.value,
                "position": native_status.position.to_dict(),
                "is_activated": native_status.is_activated,
                "is_homed": native_status.is_homed,
                "is_in_error": native_status.is_in_error,
                "is_moving": native_status.is_moving,
                "is_paused": native_status.is_paused,
                # Add service-expected field names for compatibility
                "activation_status": native_status.is_activated,
                "homing_status": native_status.is_homed,
                "error_status": native_status.is_in_error,
                "paused": native_status.is_paused,
                "error_code": native_status.error_code,
                "error_message": native_status.error_message,
                "timestamp": current_time,
                "connection_info": self._native_driver.connection_info
            }
            
            # Cache the status
            self._last_status = status
            self._last_status_time = current_time
            
            self.debug_log("_get_status_impl", "success", "Status retrieved successfully")
            return status
            
        except Exception as e:
            self.logger.error(f"Failed to get status for {self.robot_id}: {e}")
            error_status = {
                "connected": False,
                "error": str(e),
                "timestamp": current_time
            }
            # Cache error status briefly
            self._last_status = error_status
            self._last_status_time = current_time
            return error_status
    
    async def _emergency_stop_impl(self) -> bool:
        """Implementation-specific emergency stop logic"""
        try:
            if not self._native_driver or not self._native_driver.is_connected:
                return False
            
            self.debug_log("_emergency_stop_impl", "entry", "Executing emergency stop")
            self.logger.warning(f"🚨 Emergency stop activated for {self.robot_id}")
            
            # Clear motion and pause
            success = True
            
            try:
                await self._native_driver.clear_motion()
                self.debug_log("_emergency_stop_impl", "clear_motion", "Motion cleared")
            except Exception as e:
                self.logger.error(f"Failed to clear motion during emergency stop: {e}")
                success = False
            
            try:
                await self._native_driver.pause_motion()
                self.debug_log("_emergency_stop_impl", "pause_motion", "Motion paused")
            except Exception as e:
                self.logger.error(f"Failed to pause motion during emergency stop: {e}")
                success = False
            
            if success:
                self.logger.info(f"✅ Emergency stop completed for {self.robot_id}")
            else:
                self.logger.error(f"❌ Emergency stop partially failed for {self.robot_id}")
            
            return success
            
        except Exception as e:
            self.logger.error(f"Emergency stop failed for {self.robot_id}: {e}")
            return False
    
    # Additional methods that may be used by the service layer
    
    async def activate_robot(self) -> bool:
        """Activate the robot for operation"""
        try:
            if not self._native_driver or not self._native_driver.is_connected:
                raise ConnectionError("Robot not connected")
            
            result = await self._native_driver.activate()
            self.clear_status_cache()  # Clear cache after state change
            return result
        except Exception as e:
            self.logger.error(f"Failed to activate robot {self.robot_id}: {e}")
            return False
    
    async def deactivate_robot(self) -> bool:
        """Deactivate the robot"""
        try:
            if not self._native_driver or not self._native_driver.is_connected:
                raise ConnectionError("Robot not connected")
            
            result = await self._native_driver.deactivate()
            self.clear_status_cache()  # Clear cache after state change
            return result
        except Exception as e:
            self.logger.error(f"Failed to deactivate robot {self.robot_id}: {e}")
            return False
    
    async def home_robot(self) -> bool:
        """Home the robot to reference position"""
        try:
            if not self._native_driver or not self._native_driver.is_connected:
                raise ConnectionError("Robot not connected")
            
            result = await self._native_driver.home()
            self.clear_status_cache()  # Clear cache after state change
            return result
        except Exception as e:
            self.logger.error(f"Failed to home robot {self.robot_id}: {e}")
            return False
    
    async def move_pose(self, x: float, y: float, z: float, 
                       alpha: float = 0.0, beta: float = 0.0, gamma: float = 0.0) -> bool:
        """Move robot to specified pose"""
        try:
            if not self._native_driver or not self._native_driver.is_connected:
                raise ConnectionError("Robot not connected")
            
            result = await self._native_driver.move_pose(x, y, z, alpha, beta, gamma)
            self.clear_status_cache()  # Clear cache after movement command
            return result
        except Exception as e:
            self.logger.error(f"Failed to move robot {self.robot_id} to pose: {e}")
            return False
    
    async def set_velocity(self, velocity: float) -> bool:
        """Set joint velocity percentage"""
        try:
            if not self._native_driver or not self._native_driver.is_connected:
                raise ConnectionError("Robot not connected")
            
            return await self._native_driver.set_joint_vel(velocity)
        except Exception as e:
            self.logger.error(f"Failed to set velocity for robot {self.robot_id}: {e}")
            return False
    
    async def set_acceleration(self, acceleration: float) -> bool:
        """Set joint acceleration percentage"""
        try:
            if not self._native_driver or not self._native_driver.is_connected:
                raise ConnectionError("Robot not connected")
            
            return await self._native_driver.set_joint_acc(acceleration)
        except Exception as e:
            self.logger.error(f"Failed to set acceleration for robot {self.robot_id}: {e}")
            return False
    
    async def clear_motion(self) -> bool:
        """Clear motion queue"""
        try:
            if not self._native_driver or not self._native_driver.is_connected:
                raise ConnectionError("Robot not connected")
            
            result = await self._native_driver.clear_motion()
            self.clear_status_cache()  # Clear cache after state change
            return result
        except Exception as e:
            self.logger.error(f"Failed to clear motion for robot {self.robot_id}: {e}")
            return False
    
    async def pause_motion(self) -> bool:
        """Pause robot motion"""
        try:
            if not self._native_driver or not self._native_driver.is_connected:
                raise ConnectionError("Robot not connected")
            
            result = await self._native_driver.pause_motion()
            self.clear_status_cache()  # Clear cache after state change
            return result
        except Exception as e:
            self.logger.error(f"Failed to pause motion for robot {self.robot_id}: {e}")
            return False
    
    async def resume_motion(self) -> bool:
        """Resume robot motion"""
        try:
            if not self._native_driver or not self._native_driver.is_connected:
                raise ConnectionError("Robot not connected")
            
            result = await self._native_driver.resume_motion()
            self.clear_status_cache()  # Clear cache after state change
            return result
        except Exception as e:
            self.logger.error(f"Failed to resume motion for robot {self.robot_id}: {e}")
            return False
    
    async def reset_error(self) -> bool:
        """Reset robot error state"""
        try:
            if not self._native_driver or not self._native_driver.is_connected:
                raise ConnectionError("Robot not connected")
            
            result = await self._native_driver.reset_error()
            self.clear_status_cache()  # Clear cache after state change
            return result
        except Exception as e:
            self.logger.error(f"Failed to reset error for robot {self.robot_id}: {e}")
            return False
    
    def get_robot_instance(self):
        """
        Get robot instance for service layer compatibility.
        
        Returns the native driver instance when connected, providing
        compatibility with the service layer's robot instance checks.
        
        Returns:
            NativeMecademicDriver instance if connected, None otherwise
        """
        if self._native_driver:
            return self._native_driver.get_robot_instance()
        return None
    
    async def wait_idle(self, timeout: float = 30.0) -> bool:
        """Wait for robot to finish motion."""
        if self._native_driver:
            return await self._native_driver.wait_idle(timeout)
        return False
    
    @property
    def native_driver(self) -> NativeMecademicDriver:
        """Access to underlying native driver for advanced operations"""
        return self._native_driver


class MecademicDriverFactory:
    """
    Factory class for creating Mecademic drivers.
    Provides a standardized interface for driver instantiation.
    """
    
    @staticmethod
    def create_driver(robot_id: str, settings) -> MecademicDriver:
        """
        Create a Mecademic driver instance with configuration from settings.
        
        Args:
            robot_id: Unique identifier for the robot
            settings: RoboticsSettings instance with configuration
            
        Returns:
            Configured MecademicDriver instance
        """
        config = settings.get_robot_config("meca")
        return MecademicDriver(robot_id, config)