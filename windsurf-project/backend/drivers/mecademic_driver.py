"""
Mecademic Robot Driver Implementation.
Provides async wrapper for mecademicpy.Robot with proper error handling and connection management.
"""

import asyncio
import time
import logging
from typing import Dict, Any, Optional
from concurrent.futures import ThreadPoolExecutor

try:
    from mecademicpy.robot import Robot as MecademicRobot
    mecademicpy_available = True
except ImportError:
    MecademicRobot = None
    mecademicpy_available = False

from core.exceptions import ConnectionError, HardwareError, ConfigurationError
from core.hardware_manager import BaseRobotDriver
from utils.logger import get_logger


class MecademicDriver(BaseRobotDriver):
    """
    Mecademic robot driver implementing BaseRobotDriver interface.
    
    Provides async wrapper around mecademicpy.Robot with proper connection
    management, error handling, and thread-safe operations.
    """
    
    def __init__(self, robot_id: str, config: Dict[str, Any]):
        super().__init__(robot_id, config)
        self.logger = get_logger(f"meca_driver_{robot_id}")
        
        if not mecademicpy_available:
            raise ConfigurationError(
                "mecademicpy library not available. Install with: pip install mecademicpy",
                robot_id=robot_id
            )
        
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
        
        # Mecademic robot instance
        self._robot: Optional[mecademicpy.Robot] = None
        self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix=f"meca_{robot_id}")
        
        # Connection state
        self._last_status = {}
        self._last_status_time = 0.0
        self._status_cache_duration = 1.0  # Cache for 1 second
        
        self.logger.info(f"Initialized Mecademic driver for {robot_id} at {self.ip_address}:{self.port}")
    
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
            # Shutdown executor
            self._executor.shutdown(wait=True)
            self.logger.info(f"Mecademic driver for {self.robot_id} shutdown complete")
    
    async def _connect_impl(self) -> bool:
        """Implementation-specific connection logic"""
        try:
            self.logger.info(f"🔄 Starting MecademicDriver connection process for {self.robot_id}")
            
            # Create robot instance
            self.logger.info(f"📦 Creating mecademicpy Robot() instance for {self.robot_id}")
            try:
                self._robot = MecademicRobot()
                self.logger.info(f"✅ mecademicpy Robot() instance created successfully for {self.robot_id}")
            except Exception as robot_create_error:
                self.logger.error(f"❌ Failed to create mecademicpy Robot instance for {self.robot_id}: {robot_create_error}")
                self.logger.error(f"💡 Troubleshooting: Check mecademicpy library installation")
                return False
            
            # Connect in thread pool to avoid blocking
            self.logger.info(f"🔧 Executing connection in thread pool (timeout={self.timeout}s) for {self.robot_id}")
            loop = asyncio.get_event_loop()
            
            try:
                connect_success = await asyncio.wait_for(
                    loop.run_in_executor(
                        self._executor,
                        self._connect_sync
                    ),
                    timeout=self.timeout + 5.0  # Add 5s buffer for thread pool overhead
                )
            except asyncio.TimeoutError:
                self.logger.error(f"⏱️ Connection timeout ({self.timeout}s + 5s buffer) for {self.robot_id}")
                self.logger.error(f"💡 Troubleshooting: Robot may be unresponsive or network latency is high")
                self._robot = None
                return False
            
            if connect_success:
                self.logger.info(f"🎉 mecademicpy Robot.Connect() succeeded for {self.robot_id}")
                
                # Activate robot before setting parameters
                self.logger.info(f"⏳ Waiting 1s for connection stabilization before activation for {self.robot_id}")
                await asyncio.sleep(1.0)  # Give connection more time to stabilize
                
                try:
                    await self._activate_robot_after_connect()
                    self.logger.info(f"✅ Robot activation completed for {self.robot_id}")
                except Exception as activation_error:
                    self.logger.warning(f"⚠️ Robot activation failed for {self.robot_id}: {activation_error}")
                    self.logger.warning(f"💡 Connection successful but robot may need manual activation")
                
                # Set initial parameters
                try:
                    await self._set_initial_parameters()
                    self.logger.info(f"✅ Initial parameters set for {self.robot_id}")
                except Exception as params_error:
                    self.logger.warning(f"⚠️ Failed to set initial parameters for {self.robot_id}: {params_error}")
                    self.logger.warning(f"💡 Connection successful but parameters may need manual configuration")
                
                self.logger.info(f"🏆 MecademicDriver fully initialized and connected for {self.robot_id}")
                return True
            else:
                self.logger.error(f"❌ mecademicpy Robot.Connect() failed for {self.robot_id}")
                self.logger.error(f"💡 Check detailed logs above for specific failure reason")
                self._robot = None
                return False
                
        except Exception as e:
            self.logger.error(f"💥 Critical connection failure for {self.robot_id}: {type(e).__name__}: {e}")
            import traceback
            self.logger.error(f"Full connection traceback for {self.robot_id}:\n{traceback.format_exc()}")
            self._robot = None
            return False
    
    def _connect_sync(self) -> bool:
        """Synchronous connection implementation"""
        try:
            self.logger.info(f"🔄 Starting mecademicpy Robot.Connect() to {self.ip_address}:{self.port} for {self.robot_id}")
            
            # Verify robot instance exists
            if not self._robot:
                self.logger.error(f"❌ No mecademicpy Robot instance available for {self.robot_id}")
                return False
            
            # Log mecademicpy library info
            try:
                import mecademicpy
                version = getattr(mecademicpy, '__version__', 'unknown')
                self.logger.info(f"📦 Using mecademicpy version: {version} for {self.robot_id}")
            except Exception:
                self.logger.warning(f"⚠️ Could not determine mecademicpy version for {self.robot_id}")
            
            # Log connection parameters for debugging
            self.logger.info(f"🔧 Connection parameters for {self.robot_id}:")
            self.logger.info(f"   - IP Address: {self.ip_address}")
            self.logger.info(f"   - Port: {self.port} (mecademicpy uses fixed port 10000)")
            self.logger.info(f"   - Timeout: {self.timeout}s")
            self.logger.info(f"   - Force: {self.force}")
            self.logger.info(f"   - Speed: {self.speed}")
            self.logger.info(f"   - Acceleration: {self.acceleration}")
            
            # Disable auto-disconnect on exception to prevent premature disconnection
            if hasattr(self._robot, 'SetDisconnectOnException'):
                self._robot.SetDisconnectOnException(False)
                self.logger.info(f"🔧 Disabled auto-disconnect on exception for {self.robot_id}")
            else:
                self.logger.warning(f"⚠️ Robot {self.robot_id} does not support SetDisconnectOnException")
            
            # Connect to robot with detailed logging  
            # Note: mecademicpy Connect() only takes address parameter, not port (port is fixed at 10000)
            self.logger.info(f"🚀 Calling mecademicpy Robot.Connect() with parameters for {self.robot_id}:")
            self.logger.info(f"   - address='{self.ip_address}'")
            self.logger.info(f"   - enable_synchronous_mode=False")
            self.logger.info(f"   - disconnect_on_exception=False")
            self.logger.info(f"   - timeout={self.timeout}")
            
            start_time = time.time()
            
            # Attempt connection with specific exception handling - try both async and sync modes
            connection_succeeded = False
            last_error = None
            connection_modes = [
                {"enable_synchronous_mode": False, "mode_name": "async"},
                {"enable_synchronous_mode": True, "mode_name": "sync"}
            ]
            
            for mode_config in connection_modes:
                try:
                    mode_name = mode_config["mode_name"]
                    enable_sync = mode_config["enable_synchronous_mode"]
                    
                    self.logger.info(f"🔄 Attempting connection in {mode_name} mode for {self.robot_id}")
                    
                    self._robot.Connect(
                        address=self.ip_address,
                        enable_synchronous_mode=enable_sync,
                        disconnect_on_exception=False,  # We handle disconnections manually
                        timeout=self.timeout
                    )
                    
                    self.logger.info(f"✅ Connection successful in {mode_name} mode for {self.robot_id}")
                    connection_succeeded = True
                    break
                    
                except Exception as mode_e:
                    last_error = mode_e
                    self.logger.warning(f"⚠️ Connection failed in {mode_name} mode for {self.robot_id}: {type(mode_e).__name__}: {mode_e}")
            
            # If both connection modes failed, handle the error
            if not connection_succeeded:
                if last_error:
                    if isinstance(last_error, ConnectionRefusedError):
                        self.logger.error(f"🚫 Connection refused by robot {self.robot_id}: {last_error}")
                        self.logger.error(f"💡 Troubleshooting: Check if robot is powered on and network is accessible")
                    elif isinstance(last_error, (TimeoutError, asyncio.TimeoutError)):
                        self.logger.error(f"⏱️ Connection timeout for robot {self.robot_id}: {last_error}")
                        self.logger.error(f"💡 Troubleshooting: Check network latency or increase timeout (current: {self.timeout}s)")
                    elif isinstance(last_error, OSError):
                        self.logger.error(f"🌐 Network error connecting to robot {self.robot_id}: {last_error}")
                        self.logger.error(f"💡 Troubleshooting: Check network connectivity to {self.ip_address}")
                    elif isinstance(last_error, ImportError):
                        self.logger.error(f"📦 mecademicpy library error for robot {self.robot_id}: {last_error}")
                        self.logger.error(f"💡 Troubleshooting: Check mecademicpy installation")
                    else:
                        self.logger.error(f"❌ Unexpected error during Robot.Connect() for {self.robot_id}: {type(last_error).__name__}: {last_error}")
                        import traceback
                        self.logger.error(f"Full connection traceback for {self.robot_id}:\n{traceback.format_exc()}")
                else:
                    self.logger.error(f"❌ Connection failed in both async and sync modes for {self.robot_id} with no specific error")
                return False
            
            connect_duration = time.time() - start_time
            self.logger.info(f"⏱️ mecademicpy Robot.Connect() completed in {connect_duration:.2f}s for {self.robot_id}")
            
            # Wait for connection to be established
            self.logger.info(f"⏳ Waiting 0.5s for connection stabilization for {self.robot_id}")
            time.sleep(0.5)
            
            # Check if connected
            if hasattr(self._robot, 'IsConnected'):
                try:
                    is_connected = self._robot.IsConnected()
                    self.logger.info(f"🔍 mecademicpy Robot.IsConnected() returned: {is_connected} for {self.robot_id}")
                    
                    if is_connected:
                        self.logger.info(f"✅ Successfully connected to Mecademic robot {self.robot_id}")
                        
                        # Additional connection validation
                        try:
                            # Try to get robot status to validate connection
                            if hasattr(self._robot, 'GetStatusRobot'):
                                status = self._robot.GetStatusRobot()
                                self.logger.info(f"✅ Robot status check successful for {self.robot_id}: {status}")
                            else:
                                self.logger.warning(f"⚠️ GetStatusRobot not available for validation on {self.robot_id}")
                        except Exception as status_e:
                            self.logger.warning(f"⚠️ Could not validate connection with status check for {self.robot_id}: {status_e}")
                            
                        return True
                    else:
                        self.logger.error(f"❌ mecademicpy connection failed - IsConnected() returned False for {self.robot_id}")
                        self.logger.error(f"💡 Troubleshooting: Robot may be in error state or require activation")
                        return False
                except Exception as check_e:
                    self.logger.error(f"❌ Error checking connection status for {self.robot_id}: {check_e}")
                    return False
            else:
                self.logger.warning(f"⚠️ mecademicpy Robot instance lacks IsConnected() method for {self.robot_id}")
                # Assume connection succeeded if no exception was thrown
                self.logger.info(f"✅ Assuming successful connection to Mecademic robot {self.robot_id} (no IsConnected method)")
                return True
                
        except Exception as e:
            self.logger.error(f"💥 Critical error in _connect_sync for {self.robot_id}: {type(e).__name__}: {e}")
            import traceback
            self.logger.error(f"Full critical error traceback for {self.robot_id}:\n{traceback.format_exc()}")
            return False
    
    async def _activate_robot_after_connect(self):
        """Activate robot immediately after connection"""
        try:
            if self._robot:
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(
                    self._executor,
                    self._activate_robot_sync_internal
                )
        except Exception as e:
            self.logger.warning(f"Failed to activate robot after connect for {self.robot_id}: {e}")
            # Don't raise exception - allow connection to proceed
    
    def _activate_robot_sync_internal(self):
        """Internal activation and homing for connection process (per mecademicpy best practices)"""
        try:
            self.logger.info(f"🔧 Starting robot activation sequence for {self.robot_id}")
            
            # Check robot status before activation
            try:
                if hasattr(self._robot, 'GetStatusRobot'):
                    status = self._robot.GetStatusRobot()
                    self.logger.info(f"📊 Robot status before activation for {self.robot_id}: {status}")
                    
                    # Check if robot is in error state
                    if hasattr(status, 'error_status') and status.error_status:
                        self.logger.warning(f"⚠️ Robot {self.robot_id} is in error state before activation")
                        # Try to reset errors if possible
                        if hasattr(self._robot, 'ResetError'):
                            self._robot.ResetError()
                            self.logger.info(f"✅ Error reset attempted for {self.robot_id}")
            except Exception as status_e:
                self.logger.warning(f"⚠️ Could not check robot status before activation for {self.robot_id}: {status_e}")
            
            # Step 1: Activate Robot
            if hasattr(self._robot, 'ActivateRobot'):
                self.logger.info(f"🔋 Activating robot {self.robot_id}...")
                try:
                    self._robot.ActivateRobot()
                    self.logger.info(f"✅ Robot {self.robot_id} activation command sent")
                    
                    # Wait for activation to complete
                    self.logger.info(f"⏳ Waiting 2s for activation to complete for {self.robot_id}")
                    time.sleep(2.0)
                    
                    # Verify activation if possible
                    if hasattr(self._robot, 'GetStatusRobot'):
                        try:
                            status = self._robot.GetStatusRobot()
                            if hasattr(status, 'activation_status'):
                                self.logger.info(f"📊 Robot {self.robot_id} activation status: {status.activation_status}")
                        except Exception:
                            pass
                except Exception as activate_e:
                    self.logger.error(f"❌ Robot activation failed for {self.robot_id}: {activate_e}")
                    raise
            else:
                self.logger.warning(f"⚠️ Robot {self.robot_id} does not support ActivateRobot method")
            
            # Step 2: Home Robot (required before movements per mecademicpy docs)
            if hasattr(self._robot, 'Home'):
                self.logger.info(f"🏠 Homing robot {self.robot_id}...")
                try:
                    self._robot.Home()
                    self.logger.info(f"✅ Robot {self.robot_id} homing command sent")
                    
                    # Wait for homing or use WaitHomed if available
                    if hasattr(self._robot, 'WaitHomed'):
                        self.logger.info(f"⏳ Waiting for robot {self.robot_id} to complete homing...")
                        try:
                            self._robot.WaitHomed(timeout=30.0)  # 30 second timeout for homing
                            self.logger.info(f"✅ Robot {self.robot_id} homing completed")
                        except Exception as wait_e:
                            self.logger.warning(f"⚠️ WaitHomed timeout/error for {self.robot_id}: {wait_e}")
                            self.logger.info(f"⏳ Fallback: waiting 5s for homing to complete")
                            time.sleep(5.0)
                    else:
                        # Fallback: wait a reasonable time for homing
                        self.logger.info(f"⏳ Waiting 5s for robot {self.robot_id} homing (no WaitHomed method)")
                        time.sleep(5.0)
                        
                    # Verify homing if possible
                    if hasattr(self._robot, 'GetStatusRobot'):
                        try:
                            status = self._robot.GetStatusRobot()
                            if hasattr(status, 'homing_status'):
                                self.logger.info(f"📊 Robot {self.robot_id} homing status: {status.homing_status}")
                        except Exception:
                            pass
                except Exception as home_e:
                    self.logger.error(f"❌ Robot homing failed for {self.robot_id}: {home_e}")
                    raise
            else:
                self.logger.warning(f"⚠️ Robot {self.robot_id} does not support Home method")
            
            self.logger.info(f"🎉 Robot activation sequence completed for {self.robot_id}")
                
        except Exception as e:
            self.logger.error(f"❌ Error in robot activation sequence for {self.robot_id}: {e}")
            raise
    
    async def _set_initial_parameters(self):
        """Set initial robot parameters after connection"""
        try:
            if self._robot:
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(
                    self._executor,
                    self._set_parameters_sync
                )
        except Exception as e:
            self.logger.warning(f"Failed to set initial parameters for {self.robot_id}: {e}")
    
    def _set_parameters_sync(self):
        """Set robot parameters synchronously"""
        try:
            # Set movement parameters
            if hasattr(self._robot, 'SetJointVel'):
                self._robot.SetJointVel(self.speed)
            
            if hasattr(self._robot, 'SetJointAcc'):
                self._robot.SetJointAcc(self.acceleration)
            
            if hasattr(self._robot, 'SetCartVel'):
                self._robot.SetCartVel(self.speed)
            
            if hasattr(self._robot, 'SetCartAcc'):
                self._robot.SetCartAcc(self.acceleration)
            
            # Set force if available
            if hasattr(self._robot, 'SetForce') and self.force > 0:
                self._robot.SetForce(self.force)
            
            self.logger.info(f"Set initial parameters for {self.robot_id}")
            
        except Exception as e:
            self.logger.error(f"Error setting parameters for {self.robot_id}: {e}")
    
    async def _disconnect_impl(self) -> bool:
        """Implementation-specific disconnection logic"""
        try:
            if self._robot:
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(
                    self._executor,
                    self._disconnect_sync
                )
            return True
        except Exception as e:
            self.logger.error(f"Error during disconnection for {self.robot_id}: {e}")
            return False
        finally:
            self._robot = None
    
    def _disconnect_sync(self):
        """Synchronous disconnection implementation"""
        try:
            if self._robot and hasattr(self._robot, 'Disconnect'):
                self._robot.Disconnect()
                self.logger.info(f"Disconnected from Mecademic robot {self.robot_id}")
        except Exception as e:
            self.logger.error(f"Error disconnecting from {self.robot_id}: {e}")
    
    async def _ping_impl(self) -> float:
        """Implementation-specific ping logic"""
        start_time = time.time()
        
        try:
            if not self._robot:
                raise ConnectionError(f"Robot {self.robot_id} not connected")
            
            # Use status check as ping
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                self._executor,
                self._ping_sync
            )
            
            return time.time() - start_time
            
        except Exception as e:
            self.logger.warning(f"Ping failed for {self.robot_id}: {e}")
            raise
    
    def _ping_sync(self):
        """Synchronous ping implementation"""
        try:
            if hasattr(self._robot, 'GetStatusRobot'):
                # This will raise exception if robot is not responsive
                status = self._robot.GetStatusRobot()
                return status
            else:
                # Fallback: check if still connected
                if hasattr(self._robot, 'IsConnected'):
                    if not self._robot.IsConnected():
                        raise ConnectionError(f"Robot {self.robot_id} lost connection")
                return True
        except Exception as e:
            raise ConnectionError(f"Ping failed for {self.robot_id}: {e}")
    
    async def _get_status_impl(self) -> Dict[str, Any]:
        """Implementation-specific status logic"""
        current_time = time.time()
        
        # Use cached status if available and fresh
        if (self._last_status and 
            current_time - self._last_status_time < self._status_cache_duration):
            return self._last_status.copy()
        
        try:
            if not self._robot:
                return {"connected": False, "error": "Robot not initialized"}
            
            loop = asyncio.get_event_loop()
            status = await loop.run_in_executor(
                self._executor,
                self._get_status_sync
            )
            
            # Cache the result
            self._last_status = status
            self._last_status_time = current_time
            
            return status
            
        except Exception as e:
            self.logger.error(f"Status check failed for {self.robot_id}: {e}")
            return {
                "connected": False,
                "error": str(e),
                "timestamp": current_time
            }
    
    def _get_status_sync(self) -> Dict[str, Any]:
        """Synchronous status check implementation"""
        try:
            status = {
                "connected": True,
                "timestamp": time.time(),
                "robot_id": self.robot_id
            }
            
            # Get robot status if available
            if hasattr(self._robot, 'GetStatusRobot'):
                robot_status = self._robot.GetStatusRobot()
                self.logger.info(f"🔍 RAW robot_status object for {self.robot_id}: {robot_status}")
                self.logger.info(f"🔍 robot_status type: {type(robot_status)}")
                self.logger.info(f"🔍 robot_status attributes: {dir(robot_status) if robot_status else 'None'}")
                
                if robot_status:
                    # Use correct mecademicpy attribute names
                    activation_status = getattr(robot_status, 'activation_state', False)
                    homing_status = getattr(robot_status, 'homing_state', False)
                    error_status = getattr(robot_status, 'error_status', False)
                    
                    self.logger.info(f"🔍 Fixed attribute access for {self.robot_id}:")
                    self.logger.info(f"  - activation_state: {activation_status}")
                    self.logger.info(f"  - homing_state: {homing_status}")
                    self.logger.info(f"  - error_status: {error_status}")
                    
                    status.update({
                        "activation_status": activation_status,  # Keep API consistent
                        "homing_status": homing_status,        # Keep API consistent  
                        "error_status": error_status,
                        "paused": getattr(robot_status, 'pause_motion_status', False),
                        "end_of_cycle": getattr(robot_status, 'end_of_block_status', False),
                        "motion_complete": getattr(robot_status, 'end_of_block_status', False)
                    })
            
            # Get position data if available
            if hasattr(self._robot, 'GetRobotRtData'):
                try:
                    rt_data = self._robot.GetRobotRtData()
                    if rt_data:
                        status['position'] = {
                            'x': getattr(rt_data, 'x', 0.0),
                            'y': getattr(rt_data, 'y', 0.0),
                            'z': getattr(rt_data, 'z', 0.0),
                            'alpha': getattr(rt_data, 'alpha', 0.0),
                            'beta': getattr(rt_data, 'beta', 0.0),
                            'gamma': getattr(rt_data, 'gamma', 0.0)
                        }
                except Exception as e:
                    self.logger.warning(f"Failed to get position data for {self.robot_id}: {e}")
            
            # Check connection status
            if hasattr(self._robot, 'IsConnected'):
                status['connected'] = self._robot.IsConnected()
            
            return status
            
        except Exception as e:
            self.logger.error(f"Error getting status for {self.robot_id}: {e}")
            return {
                "connected": False,
                "error": str(e),
                "timestamp": time.time()
            }
    
    async def _emergency_stop_impl(self) -> bool:
        """Implementation-specific emergency stop logic"""
        try:
            if not self._robot:
                return False
            
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                self._executor,
                self._emergency_stop_sync
            )
            
            return True
            
        except Exception as e:
            self.logger.error(f"Emergency stop failed for {self.robot_id}: {e}")
            return False
    
    def _emergency_stop_sync(self):
        """Synchronous emergency stop implementation"""
        try:
            if hasattr(self._robot, 'EmergencyStop'):
                self._robot.EmergencyStop()
                self.logger.critical(f"Emergency stop executed for {self.robot_id}")
            elif hasattr(self._robot, 'PauseMotion'):
                self._robot.PauseMotion()
                self.logger.critical(f"Motion paused for {self.robot_id} (emergency stop)")
            else:
                self.logger.warning(f"No emergency stop method available for {self.robot_id}")
        except Exception as e:
            self.logger.error(f"Error during emergency stop for {self.robot_id}: {e}")
            raise
    
    async def home_robot(self) -> bool:
        """Home the robot to its reference position"""
        try:
            if not self._robot:
                raise ConnectionError(f"Robot {self.robot_id} not connected")
            
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                self._executor,
                self._home_robot_sync
            )
            
            return True
            
        except Exception as e:
            self.logger.error(f"Homing failed for {self.robot_id}: {e}")
            raise HardwareError(f"Homing failed: {e}", robot_id=self.robot_id)
    
    def _home_robot_sync(self):
        """Synchronous robot homing implementation"""
        try:
            if hasattr(self._robot, 'Home'):
                self._robot.Home()
                self.logger.info(f"Homing initiated for {self.robot_id}")
                
                # Wait for homing to complete if method available
                if hasattr(self._robot, 'WaitHomed'):
                    self._robot.WaitHomed(timeout=60.0)
                    self.logger.info(f"Homing completed for {self.robot_id}")
                else:
                    # Fallback: wait a bit and check status
                    time.sleep(2.0)
            else:
                self.logger.warning(f"Homing not available for {self.robot_id}")
        except Exception as e:
            self.logger.error(f"Homing error for {self.robot_id}: {e}")
            raise
    
    async def activate_robot(self) -> bool:
        """Activate the robot for operation with connection validation and retry"""
        self.logger.info(f"🚀 NEW ACTIVATION LOGIC CALLED for {self.robot_id}")
        max_retries = 2
        
        for attempt in range(max_retries):
            try:
                if not self._robot:
                    raise ConnectionError(f"Robot {self.robot_id} not connected")
                
                # Check connection status before activation attempt
                await self._validate_connection_before_activation(attempt + 1)
                
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(
                    self._executor,
                    self._activate_robot_sync
                )
                
                self.logger.info(f"✅ Robot {self.robot_id} activation successful on attempt {attempt + 1}")
                return True
                
            except Exception as e:
                error_str = str(e)
                self.logger.warning(f"⚠️ Activation attempt {attempt + 1} failed for {self.robot_id}: {error_str}")
                
                # Check if this is a socket/connection error that we can retry
                if attempt < max_retries - 1 and any(err in error_str.lower() for err in 
                    ['socket was closed', 'connection', 'disconnect', 'communication']):
                    
                    self.logger.info(f"🔄 Connection issue detected, attempting reconnection for {self.robot_id}")
                    
                    # Try to reconnect
                    try:
                        await self._reconnect_for_activation()
                        self.logger.info(f"🎯 Reconnection successful, retrying activation for {self.robot_id}")
                        continue  # Retry activation
                    except Exception as reconnect_error:
                        self.logger.error(f"❌ Reconnection failed for {self.robot_id}: {reconnect_error}")
                
                # If this is the last attempt or not a connection error, raise the exception
                if attempt == max_retries - 1:
                    self.logger.error(f"❌ All activation attempts failed for {self.robot_id}: {e}")
                    raise HardwareError(f"Activation failed after {max_retries} attempts: {e}", robot_id=self.robot_id)
    
    async def _validate_connection_before_activation(self, attempt_num: int):
        """Validate connection status before attempting activation"""
        self.logger.info(f"🔍 Validating connection before activation attempt {attempt_num} for {self.robot_id}")
        
        if not self._robot:
            raise ConnectionError(f"No robot instance available for {self.robot_id}")
        
        # Check if robot reports as connected
        if hasattr(self._robot, 'IsConnected'):
            loop = asyncio.get_event_loop()
            is_connected = await loop.run_in_executor(
                self._executor,
                lambda: self._robot.IsConnected()
            )
            
            self.logger.info(f"📊 Robot {self.robot_id} IsConnected() reports: {is_connected}")
            
            if not is_connected:
                raise ConnectionError(f"Robot {self.robot_id} reports as not connected")
        else:
            self.logger.warning(f"⚠️ Robot {self.robot_id} lacks IsConnected() method")
        
        # Clear robot occupation state before activation
        await self._clear_robot_occupation_state(attempt_num)
    
    async def _clear_robot_occupation_state(self, attempt_num: int):
        """Clear robot occupation state to allow activation"""
        self.logger.info(f"🧹 Clearing robot occupation state for attempt {attempt_num} on {self.robot_id}")
        
        if not self._robot:
            self.logger.warning(f"⚠️ No robot instance to clear state for {self.robot_id}")
            return
        
        loop = asyncio.get_event_loop()
        
        try:
            # First check current robot status to see if clearing is needed
            if hasattr(self._robot, 'GetStatusRobot'):
                try:
                    current_status = self._robot.GetStatusRobot()
                    activated = getattr(current_status, 'activation_state', False)
                    homed = getattr(current_status, 'homing_state', False)
                    error = getattr(current_status, 'error_status', False)
                    
                    self.logger.info(f"🔍 Current robot state before clearing: activated={activated}, homed={homed}, error={error}")
                    
                    # If robot is already activated and homed with no errors, don't clear
                    if activated and homed and not error:
                        self.logger.info(f"✅ Robot {self.robot_id} already in good state, skipping occupation clearing")
                        return
                    
                    # If robot just has error but is activated/homed, only reset error, don't deactivate
                    if activated and homed and error:
                        self.logger.info(f"🔧 Robot {self.robot_id} activated/homed but has error, only resetting error")
                        if hasattr(self._robot, 'ResetError'):
                            await loop.run_in_executor(self._executor, self._robot.ResetError)
                            self.logger.info(f"✅ Error reset for {self.robot_id}")
                        return
                        
                except Exception as status_e:
                    self.logger.warning(f"⚠️ Could not check robot status, proceeding with clearing: {status_e}")
            
            # Step 1: Deactivate robot if it's activated/occupied (only if needed)
            if hasattr(self._robot, 'DeactivateRobot'):
                self.logger.info(f"🔧 Calling DeactivateRobot() to clear occupation for {self.robot_id}")
                await loop.run_in_executor(
                    self._executor,
                    self._robot.DeactivateRobot
                )
                self.logger.info(f"✅ DeactivateRobot() completed for {self.robot_id}")
                
                # Wait for deactivation to complete
                await asyncio.sleep(1.0)
            else:
                self.logger.warning(f"⚠️ DeactivateRobot() not available for {self.robot_id}")
            
            # Step 2: Clear any pending motions
            if hasattr(self._robot, 'ClearMotion'):
                self.logger.info(f"🔧 Calling ClearMotion() for {self.robot_id}")
                await loop.run_in_executor(
                    self._executor,
                    self._robot.ClearMotion
                )
                self.logger.info(f"✅ ClearMotion() completed for {self.robot_id}")
            else:
                self.logger.warning(f"⚠️ ClearMotion() not available for {self.robot_id}")
            
            # Step 3: Reset any error states
            if hasattr(self._robot, 'ResetError'):
                self.logger.info(f"🔧 Calling ResetError() for {self.robot_id}")
                await loop.run_in_executor(
                    self._executor,
                    self._robot.ResetError
                )
                self.logger.info(f"✅ ResetError() completed for {self.robot_id}")
            else:
                self.logger.warning(f"⚠️ ResetError() not available for {self.robot_id}")
            
            # Wait a moment for all clearing operations to take effect
            await asyncio.sleep(0.5)
            self.logger.info(f"🎯 Robot occupation state cleared for {self.robot_id}")
            
        except Exception as e:
            self.logger.warning(f"⚠️ Error during occupation state clearing for {self.robot_id}: {e}")
            # Don't raise the exception - we'll still try activation
    
    async def _reconnect_for_activation(self):
        """Attempt to reconnect the robot for activation"""
        self.logger.info(f"🔄 Starting reconnection process for {self.robot_id}")
        
        # First disconnect if still connected
        try:
            if self._robot and hasattr(self._robot, 'Disconnect'):
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(
                    self._executor,
                    self._robot.Disconnect
                )
                self.logger.info(f"🔌 Disconnected stale connection for {self.robot_id}")
        except Exception as disconnect_error:
            self.logger.warning(f"⚠️ Error during disconnect for {self.robot_id}: {disconnect_error}")
        
        # Wait a moment for cleanup
        await asyncio.sleep(1.0)
        
        # Attempt fresh connection
        self._robot = None
        self._connected = False
        
        connection_success = await self._connect_impl()
        if not connection_success:
            raise ConnectionError(f"Failed to re-establish connection for {self.robot_id}")
        
        self.logger.info(f"✅ Fresh connection established for {self.robot_id}")

    def _activate_robot_sync(self):
        """Synchronous robot activation implementation"""
        try:
            if hasattr(self._robot, 'ActivateRobot'):
                self.logger.info(f"🔧 Calling ActivateRobot() for {self.robot_id}")
                self._robot.ActivateRobot()
                self.logger.info(f"✅ ActivateRobot() completed for {self.robot_id}")
                
                # Wait for activation to complete
                time.sleep(1.0)
            else:
                self.logger.warning(f"⚠️ ActivateRobot() not available for {self.robot_id}")
        except Exception as e:
            self.logger.error(f"❌ Activation error for {self.robot_id}: {type(e).__name__}: {e}")
            raise
    
    async def clear_motion(self) -> bool:
        """Clear robot motion queue"""
        try:
            if not self._robot:
                self.logger.warning(f"⚠️ No robot connection to clear motion for {self.robot_id}")
                return False
                
            self.logger.info(f"🔧 Clearing motion queue for {self.robot_id}")
            loop = asyncio.get_event_loop()
            
            if hasattr(self._robot, 'ClearMotion'):
                await loop.run_in_executor(
                    self._executor,
                    self._robot.ClearMotion
                )
                self.logger.info(f"✅ ClearMotion() completed for {self.robot_id}")
                return True
            else:
                self.logger.warning(f"⚠️ ClearMotion() not available for {self.robot_id}")
                return False
                
        except Exception as e:
            self.logger.error(f"❌ Clear motion error for {self.robot_id}: {type(e).__name__}: {e}")
            return False

    async def resume_motion(self) -> bool:
        """Resume robot motion after pause"""
        try:
            if not self._robot:
                self.logger.warning(f"⚠️ No robot connection to resume motion for {self.robot_id}")
                return False
                
            self.logger.info(f"🔧 Resuming motion for {self.robot_id}")
            loop = asyncio.get_event_loop()
            
            if hasattr(self._robot, 'ResumeMotion'):
                await loop.run_in_executor(
                    self._executor,
                    self._robot.ResumeMotion
                )
                self.logger.info(f"✅ ResumeMotion() completed for {self.robot_id}")
                return True
            else:
                self.logger.warning(f"⚠️ ResumeMotion() not available for {self.robot_id}")
                return False
                
        except Exception as e:
            self.logger.error(f"❌ Resume motion error for {self.robot_id}: {type(e).__name__}: {e}")
            return False

    async def wait_idle(self, timeout: float = 30.0) -> bool:
        """Wait for robot to become idle (motion complete)"""
        try:
            if not self._robot:
                self.logger.warning(f"⚠️ No robot connection to wait for idle for {self.robot_id}")
                return False
                
            self.logger.info(f"⏳ Waiting for robot {self.robot_id} to become idle (timeout: {timeout}s)")
            loop = asyncio.get_event_loop()
            
            if hasattr(self._robot, 'WaitIdle'):
                # WaitIdle expects timeout in milliseconds
                timeout_ms = int(timeout * 1000)
                await loop.run_in_executor(
                    self._executor,
                    self._robot.WaitIdle,
                    timeout_ms
                )
                self.logger.info(f"✅ Robot {self.robot_id} is now idle")
                return True
            else:
                self.logger.warning(f"⚠️ WaitIdle() not available for {self.robot_id}")
                # Fallback: wait and check status
                await asyncio.sleep(timeout)
                return False
                
        except Exception as e:
            self.logger.error(f"❌ Wait idle error for {self.robot_id}: {type(e).__name__}: {e}")
            return False

    async def reset_error(self) -> bool:
        """Reset robot error state with connection recovery"""
        max_attempts = 3
        
        for attempt in range(max_attempts):
            try:
                if not self._robot:
                    self.logger.warning(f"⚠️ No robot connection to reset error for {self.robot_id}")
                    return False
                    
                self.logger.info(f"🔧 Resetting error state for {self.robot_id} (attempt {attempt + 1})")
                loop = asyncio.get_event_loop()
                
                # Reset errors
                if hasattr(self._robot, 'ResetError'):
                    await loop.run_in_executor(
                        self._executor,
                        self._robot.ResetError
                    )
                    self.logger.info(f"✅ ResetError() completed for {self.robot_id}")
                    
                    # Wait for reset to take effect
                    await asyncio.sleep(2.0)
                    
                    # Resume motion if paused
                    if hasattr(self._robot, 'ResumeMotion'):
                        await loop.run_in_executor(
                            self._executor,
                            self._robot.ResumeMotion
                        )
                        self.logger.info(f"✅ ResumeMotion() completed for {self.robot_id}")
                    
                    return True
                else:
                    self.logger.warning(f"⚠️ ResetError() not available for {self.robot_id}")
                    return False
                    
            except Exception as e:
                error_str = str(e)
                self.logger.warning(f"⚠️ Error reset attempt {attempt + 1} failed for {self.robot_id}: {error_str}")
                
                # Check if this is a connection error that we can recover from
                if "socket was closed" in error_str.lower() or "connection" in error_str.lower():
                    if attempt < max_attempts - 1:
                        self.logger.info(f"🔄 Connection lost during error reset, attempting to reconnect for {self.robot_id}")
                        try:
                            # Try to reconnect
                            await self._force_reconnection()
                            await asyncio.sleep(1.0)
                            continue
                        except Exception as reconnect_e:
                            self.logger.warning(f"⚠️ Reconnection failed: {reconnect_e}")
                
                # If last attempt or non-recoverable error, fail
                if attempt == max_attempts - 1:
                    self.logger.error(f"❌ All error reset attempts failed for {self.robot_id}")
                    return False
                    
        return False
    
    def get_robot_instance(self) -> Optional[Any]:
        """Get the underlying mecademicpy.Robot instance"""
        return self._robot
    
    def get_connection_info(self) -> Dict[str, Any]:
        """Get connection information"""
        return {
            "robot_id": self.robot_id,
            "ip_address": self.ip_address,
            "port": self.port,
            "timeout": self.timeout,
            "connected": self._connected,
            "config": self.config
        }


class MecademicDriverFactory:
    """Factory for creating Mecademic drivers"""
    
    @staticmethod
    def create_driver(robot_id: str, settings: Any) -> MecademicDriver:
        """
        Create a Mecademic driver from settings.
        
        Args:
            robot_id: Robot identifier
            settings: RoboticsSettings instance
            
        Returns:
            Configured MecademicDriver instance
        """
        config = {
            "ip": settings.meca_ip,
            "port": settings.meca_port,
            "timeout": settings.meca_timeout,
            "retry_attempts": settings.meca_retry_attempts,
            "retry_delay": settings.meca_retry_delay,
            "force": settings.meca_force,
            "acceleration": settings.meca_acceleration,
            "speed": settings.meca_speed
        }
        
        return MecademicDriver(robot_id, config)