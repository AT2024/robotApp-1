"""
Mecademic Robot Driver Implementation.
Provides async wrapper for mecademicpy.Robot with proper error handling and connection management.
"""

import asyncio
import time
from typing import Dict, Any, Optional
from concurrent.futures import ThreadPoolExecutor
import mecademicpy

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
        
        # Extract configuration - all required from config (no fallbacks)
        self.ip_address = config["ip"]
        self.port = config["port"]
        self.timeout = config["timeout"]
        self.retry_attempts = config["retry_attempts"]
        self.retry_delay = config["retry_delay"]

        # Movement parameters
        self.force = config["force"]
        self.acceleration = config["acceleration"]
        self.speed = config["speed"]
        
        # Mecademic robot instance
        self._robot: Optional[mecademicpy.Robot] = None
        self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix=f"meca_{robot_id}")
        
        # Connection state
        self._last_status = {}
        self._last_status_time = 0.0
        self._status_cache_duration = 1.0  # Cache for 1 second

        # Recovery mode tracking (mecademicpy doesn't expose this on status)
        self._recovery_mode_active = False

        # Software E-stop tracking (PauseMotion+ClearMotion doesn't set hardware error_status)
        self._software_estop_active = False
        self._estop_lock = asyncio.Lock()  # Thread safety for E-stop flag

        self.logger.info(f"Initialized Mecademic driver for {robot_id} at {self.ip_address}:{self.port}")
    
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
            # Shutdown executor
            self._executor.shutdown(wait=True)
            self.logger.info(f"Mecademic driver for {self.robot_id} shutdown complete")
    
    async def _connect_impl(self) -> bool:
        """Implementation-specific connection logic"""
        try:
            self.debug_log("_connect_impl", "entry", "Starting MecademicDriver connection process")
            self.logger.debug(f"[CONNECTING] Starting MecademicDriver connection process for {self.robot_id}")
            
            # Create robot instance
            self.debug_log("_connect_impl", "create_instance", "Creating mecademicpy Robot() instance")
            self.logger.debug(f"[INIT] Creating mecademicpy Robot() instance for {self.robot_id}")
            try:
                self._robot = MecademicRobot()
                self.debug_log("_connect_impl", "instance_success", "mecademicpy instance created successfully")
                self.logger.debug(f"[OK] mecademicpy Robot() instance created successfully for {self.robot_id}")
            except Exception as robot_create_error:
                self.debug_log("_connect_impl", "instance_failure", f"Robot instance creation failed", 
                              {"error": str(robot_create_error)})
                self.logger.error(f"[ERROR] Failed to create mecademicpy Robot instance for {self.robot_id}: {robot_create_error}")
                self.logger.error(f"[TIP] Troubleshooting: Check mecademicpy library installation")
                return False
            
            # Connect in thread pool to avoid blocking
            self.debug_log("_connect_impl", "thread_pool", "Submitting connection to thread pool executor")
            self.logger.debug(f"[EXEC] Executing connection in thread pool (timeout={self.timeout}s) for {self.robot_id}")
            loop = asyncio.get_event_loop()
            
            try:
                self.debug_log("_connect_impl", "connection_attempt", 
                              f"Starting TCP connection attempt", 
                              {"ip": self.ip_address, "port": self.port, "timeout": self.timeout})
                connect_success = await asyncio.wait_for(
                    loop.run_in_executor(
                        self._executor,
                        self._connect_sync
                    ),
                    timeout=self.timeout + 5.0  # Add 5s buffer for thread pool overhead
                )
                self.debug_log("_connect_impl", "connection_complete", 
                              f"TCP connection attempt completed", {"success": connect_success})
            except asyncio.TimeoutError:
                self.logger.error(f"[TIMEOUT] Connection timeout ({self.timeout}s + 5s buffer) for {self.robot_id}")
                self.logger.error(f"[TIP] Troubleshooting: Robot may be unresponsive or network latency is high")
                self._robot = None
                return False
            
            if connect_success:
                self.debug_log("_connect_impl", "tcp_success", "mecademicpy Robot.Connect() succeeded")
                self.logger.debug(f"[SUCCESS] mecademicpy Robot.Connect() succeeded for {self.robot_id}")
                
                # Activate robot before setting parameters
                self.debug_log("_connect_impl", "stabilization", "Waiting for connection stabilization")
                self.logger.debug(f"[WAITING] Waiting 1s for connection stabilization before activation for {self.robot_id}")
                await asyncio.sleep(1.0)  # Give connection more time to stabilize
                
                try:
                    self.debug_log("_connect_impl", "activation_start", "Starting robot activation sequence")
                    await self._activate_robot_after_connect()
                    self.debug_log("_connect_impl", "activation_success", "Robot activation completed successfully")
                    self.logger.debug(f"[OK] Robot activation completed for {self.robot_id}")
                except Exception as activation_error:
                    self.debug_log("_connect_impl", "activation_failure", 
                                  f"Robot activation failed", {"error": str(activation_error)})
                    self.logger.warning(f"[WARNING] Robot activation failed for {self.robot_id}: {activation_error}")
                    self.logger.warning(f"[TIP] Connection successful but robot may need manual activation")
                
                # Set initial parameters
                try:
                    await self._set_initial_parameters()
                    self.logger.debug(f"[OK] Initial parameters set for {self.robot_id}")
                except Exception as params_error:
                    self.logger.warning(f"[WARNING] Failed to set initial parameters for {self.robot_id}: {params_error}")
                    self.logger.warning(f"[TIP] Connection successful but parameters may need manual configuration")
                
                # Clear status cache to ensure fresh status on next get_status() call
                self.debug_log("_connect_impl", "cache_clear", "Clearing status cache after successful connection")
                self.clear_status_cache()

                # Reset recovery mode flag on fresh connection
                self._recovery_mode_active = False

                self.logger.info(f"[COMPLETE] MecademicDriver fully initialized and connected for {self.robot_id}")
                return True
            else:
                self.logger.error(f"[ERROR] mecademicpy Robot.Connect() failed for {self.robot_id}")
                self.logger.error(f"[TIP] Check detailed logs above for specific failure reason")
                self._robot = None
                return False
                
        except Exception as e:
            self.logger.error(f"[CRITICAL] Critical connection failure for {self.robot_id}: {type(e).__name__}: {e}")
            import traceback
            self.logger.error(f"Full connection traceback for {self.robot_id}:\n{traceback.format_exc()}")
            self._robot = None
            return False
    
    def _connect_sync(self) -> bool:
        """Synchronous connection implementation"""
        try:
            self.logger.debug(f"[CONNECTING] Starting mecademicpy Robot.Connect() to {self.ip_address}:{self.port} for {self.robot_id}")
            
            # Verify robot instance exists
            if not self._robot:
                self.logger.error(f"[ERROR] No mecademicpy Robot instance available for {self.robot_id}")
                return False
            
            # Log mecademicpy library info
            try:
                import mecademicpy
                version = getattr(mecademicpy, '__version__', 'unknown')
                self.logger.debug(f"[INIT] Using mecademicpy version: {version} for {self.robot_id}")
            except Exception:
                self.logger.warning(f"[WARNING] Could not determine mecademicpy version for {self.robot_id}")
            
            # Log connection parameters for debugging
            self.logger.debug(f"[EXEC] Connection parameters for {self.robot_id}: IP={self.ip_address}, port={self.port}, timeout={self.timeout}s")
            self.logger.debug(f"   - Force: {self.force}, Speed: {self.speed}, Acceleration: {self.acceleration}")
            
            # Disable auto-disconnect on exception to prevent premature disconnection
            if hasattr(self._robot, 'SetDisconnectOnException'):
                self._robot.SetDisconnectOnException(False)
                self.logger.debug(f"[EXEC] Disabled auto-disconnect on exception for {self.robot_id}")
            else:
                self.logger.warning(f"[WARNING] Robot {self.robot_id} does not support SetDisconnectOnException")
            
            # Connect to robot with detailed logging
            # Note: mecademicpy Connect() only takes address parameter, not port (port is fixed at 10000)
            self.logger.debug(f"[STARTING] Calling Robot.Connect(address='{self.ip_address}', timeout={self.timeout}) for {self.robot_id}")
            
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

                    self.logger.debug(f"[CONNECTING] Attempting connection in {mode_name} mode for {self.robot_id}")
                    
                    self._robot.Connect(
                        address=self.ip_address,
                        enable_synchronous_mode=enable_sync,
                        disconnect_on_exception=False,  # We handle disconnections manually
                        timeout=self.timeout
                    )
                    
                    self.logger.debug(f"[OK] Connection successful in {mode_name} mode for {self.robot_id}")
                    connection_succeeded = True
                    break
                    
                except Exception as mode_e:
                    last_error = mode_e
                    error_msg = str(mode_e)

                    # Check for Error 3001 - "Another user is already controlling the robot"
                    if "3001" in error_msg or "Another user" in error_msg.lower():
                        self.logger.warning(
                            f"[WARNING] Error 3001 - Robot {self.robot_id} occupied by another session. "
                            "Use force_reconnect() to release the lock and reconnect."
                        )
                        # Don't retry other modes - this error requires force_reconnect
                        break

                    self.logger.warning(f"[WARNING] Connection failed in {mode_name} mode for {self.robot_id}: {type(mode_e).__name__}: {mode_e}")

            # If both connection modes failed, handle the error
            if not connection_succeeded:
                if last_error:
                    if isinstance(last_error, ConnectionRefusedError):
                        self.logger.error(f"[REFUSED] Connection refused by robot {self.robot_id}: {last_error}")
                        self.logger.error(f"[TIP] Troubleshooting: Check if robot is powered on and network is accessible")
                    elif isinstance(last_error, (TimeoutError, asyncio.TimeoutError)):
                        self.logger.error(f"[TIMEOUT] Connection timeout for robot {self.robot_id}: {last_error}")
                        self.logger.error(f"[TIP] Troubleshooting: Check network latency or increase timeout (current: {self.timeout}s)")
                    elif isinstance(last_error, OSError):
                        self.logger.error(f"[NETWORK] Network error connecting to robot {self.robot_id}: {last_error}")
                        self.logger.error(f"[TIP] Troubleshooting: Check network connectivity to {self.ip_address}")
                    elif isinstance(last_error, ImportError):
                        self.logger.error(f"[INIT] mecademicpy library error for robot {self.robot_id}: {last_error}")
                        self.logger.error(f"[TIP] Troubleshooting: Check mecademicpy installation")
                    else:
                        self.logger.error(f"[ERROR] Unexpected error during Robot.Connect() for {self.robot_id}: {type(last_error).__name__}: {last_error}")
                        import traceback
                        self.logger.error(f"Full connection traceback for {self.robot_id}:\n{traceback.format_exc()}")
                else:
                    self.logger.error(f"[ERROR] Connection failed in both async and sync modes for {self.robot_id} with no specific error")
                return False
            
            connect_duration = time.time() - start_time
            self.logger.debug(f"[TIMING] Robot.Connect() completed in {connect_duration:.2f}s for {self.robot_id}")

            # Wait for connection to be established
            self.logger.debug(f"[WAITING] Waiting 0.5s for connection stabilization for {self.robot_id}")
            time.sleep(0.5)
            
            # Check if connected
            if hasattr(self._robot, 'IsConnected'):
                try:
                    is_connected = self._robot.IsConnected()
                    self.logger.debug(f"[CHECK] Robot.IsConnected() returned: {is_connected} for {self.robot_id}")
                    
                    if is_connected:
                        self.logger.debug(f"[OK] Successfully connected to Mecademic robot {self.robot_id}")

                        # Additional connection validation
                        try:
                            # Try to get robot status to validate connection
                            if hasattr(self._robot, 'GetStatusRobot'):
                                status = self._robot.GetStatusRobot()
                                self.logger.debug(f"[OK] Robot status check successful for {self.robot_id}: {status}")
                            else:
                                self.logger.warning(f"[WARNING] GetStatusRobot not available for validation on {self.robot_id}")
                        except Exception as status_e:
                            self.logger.warning(f"[WARNING] Could not validate connection with status check for {self.robot_id}: {status_e}")
                            
                        return True
                    else:
                        self.logger.error(f"[ERROR] mecademicpy connection failed - IsConnected() returned False for {self.robot_id}")
                        self.logger.error(f"[TIP] Troubleshooting: Robot may be in error state or require activation")
                        return False
                except Exception as check_e:
                    self.logger.error(f"[ERROR] Error checking connection status for {self.robot_id}: {check_e}")
                    return False
            else:
                self.logger.warning(f"[WARNING] mecademicpy Robot instance lacks IsConnected() method for {self.robot_id}")
                # Assume connection succeeded if no exception was thrown
                self.logger.debug(f"[OK] Assuming successful connection to Mecademic robot {self.robot_id} (no IsConnected method)")
                return True
                
        except Exception as e:
            self.logger.error(f"[CRITICAL] Critical error in _connect_sync for {self.robot_id}: {type(e).__name__}: {e}")
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
            self.logger.debug(f"[EXEC] Starting robot activation sequence for {self.robot_id}")
            
            # Check robot status before activation
            try:
                if hasattr(self._robot, 'GetStatusRobot'):
                    status = self._robot.GetStatusRobot()
                    self.logger.debug(f"[STATUS] Robot status before activation for {self.robot_id}: {status}")
                    
                    # Check if robot is in error state
                    if hasattr(status, 'error_status') and status.error_status:
                        self.logger.warning(f"[WARNING] Robot {self.robot_id} is in error state before activation")
                        # Try to reset errors if possible
                        if hasattr(self._robot, 'ResetError'):
                            self._robot.ResetError()
                            self.logger.debug(f"[OK] Error reset attempted for {self.robot_id}")
            except Exception as status_e:
                self.logger.warning(f"[WARNING] Could not check robot status before activation for {self.robot_id}: {status_e}")
            
            # Step 1: Activate Robot
            if hasattr(self._robot, 'ActivateRobot'):
                self.logger.debug(f"[ACTIVATING] Activating robot {self.robot_id}...")
                try:
                    self._robot.ActivateRobot()
                    self.logger.debug(f"[OK] Robot {self.robot_id} activation command sent")

                    # Wait for activation to complete
                    self.logger.debug(f"[WAITING] Waiting 2s for activation to complete for {self.robot_id}")
                    time.sleep(2.0)
                    
                    # Verify activation if possible
                    if hasattr(self._robot, 'GetStatusRobot'):
                        try:
                            status = self._robot.GetStatusRobot()
                            if hasattr(status, 'activation_status'):
                                self.logger.debug(f"[STATUS] Robot {self.robot_id} activation status: {status.activation_status}")
                        except Exception:
                            pass
                except Exception as activate_e:
                    self.logger.error(f"[ERROR] Robot activation failed for {self.robot_id}: {activate_e}")
                    raise
            else:
                self.logger.warning(f"[WARNING] Robot {self.robot_id} does not support ActivateRobot method")
            
            # Step 2: Home Robot (required before movements per mecademicpy docs)
            if hasattr(self._robot, 'Home'):
                self.logger.debug(f"[HOMING] Homing robot {self.robot_id}...")
                try:
                    self._robot.Home()
                    self.logger.debug(f"[OK] Robot {self.robot_id} homing command sent")

                    # Wait for homing or use WaitHomed if available
                    if hasattr(self._robot, 'WaitHomed'):
                        self.logger.debug(f"[WAITING] Waiting for robot {self.robot_id} to complete homing...")
                        try:
                            self._robot.WaitHomed(timeout=30.0)  # 30 second timeout for homing
                            self.logger.debug(f"[OK] Robot {self.robot_id} homing completed")
                        except Exception as wait_e:
                            self.logger.warning(f"[WARNING] WaitHomed timeout/error for {self.robot_id}: {wait_e}")
                            self.logger.debug(f"[WAITING] Fallback: waiting 5s for homing to complete")
                            time.sleep(5.0)
                    else:
                        # Fallback: wait a reasonable time for homing
                        self.logger.debug(f"[WAITING] Waiting 5s for robot {self.robot_id} homing (no WaitHomed method)")
                        time.sleep(5.0)
                        
                    # Verify homing if possible
                    if hasattr(self._robot, 'GetStatusRobot'):
                        try:
                            status = self._robot.GetStatusRobot()
                            if hasattr(status, 'homing_status'):
                                self.logger.debug(f"[STATUS] Robot {self.robot_id} homing status: {status.homing_status}")
                        except Exception:
                            pass
                except Exception as home_e:
                    self.logger.error(f"[ERROR] Robot homing failed for {self.robot_id}: {home_e}")
                    raise
            else:
                self.logger.warning(f"[WARNING] Robot {self.robot_id} does not support Home method")

            # Step 3: Resume Motion if Paused (critical per mecademicpy docs)
            # After connection/activation/homing, robot may be in paused state
            # Commands will fail with "Socket was closed" if motion is paused
            try:
                if hasattr(self._robot, 'GetStatusRobot'):
                    status = self._robot.GetStatusRobot()
                    paused = getattr(status, 'pause_motion_status', False)

                    if paused:
                        self.logger.debug(f"[EXEC] Robot {self.robot_id} is paused (pause_motion_status: True) - calling ResumeMotion()...")
                        if hasattr(self._robot, 'ResumeMotion'):
                            self._robot.ResumeMotion()
                            self.logger.debug(f"[OK] ResumeMotion() completed for {self.robot_id}")

                            # Wait briefly and verify motion resumed
                            time.sleep(1.0)
                            verify_status = self._robot.GetStatusRobot()
                            verify_paused = getattr(verify_status, 'pause_motion_status', True)

                            if verify_paused:
                                self.logger.warning(f"[WARNING] Motion still paused after ResumeMotion() for {self.robot_id}")
                            else:
                                self.logger.debug(f"[OK] Motion resume verified (pause_motion_status: False) for {self.robot_id}")
                        else:
                            self.logger.warning(f"[WARNING] ResumeMotion() not available for {self.robot_id}")
                    else:
                        self.logger.debug(f"[OK] Robot {self.robot_id} not paused (pause_motion_status: False)")
            except Exception as resume_e:
                self.logger.warning(f"[WARNING] Error checking/resuming motion for {self.robot_id}: {resume_e}")
                # Don't raise - allow activation to proceed

            self.logger.debug(f"[SUCCESS] Robot activation sequence completed for {self.robot_id}")

        except Exception as e:
            self.logger.error(f"[ERROR] Error in robot activation sequence for {self.robot_id}: {e}")
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
            
            self.logger.debug(f"Set initial parameters for {self.robot_id}")
            
        except Exception as e:
            self.logger.error(f"Error setting parameters for {self.robot_id}: {e}")
    
    async def _disconnect_impl(self) -> bool:
        """Implementation-specific disconnection logic.

        Ensures TCP socket is fully released by:
        1. Calling mecademicpy Disconnect()
        2. Verifying IsConnected() returns False
        3. Cleaning up robot reference
        """
        try:
            if self._robot:
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(
                    self._executor,
                    self._disconnect_sync
                )

                # Verify disconnect completed
                if self._robot and hasattr(self._robot, 'IsConnected'):
                    try:
                        still_connected = self._robot.IsConnected()
                        if still_connected:
                            self.logger.warning(f"Robot {self.robot_id} still connected after Disconnect(), TCP may not be fully released")
                        else:
                            self.logger.debug(f"Robot {self.robot_id} IsConnected() confirmed False - TCP released")
                    except Exception as e:
                        # IsConnected may fail after disconnect, which is fine
                        self.logger.debug(f"IsConnected check after disconnect: {e}")

            return True
        except Exception as e:
            self.logger.error(f"Error during disconnection for {self.robot_id}: {e}")
            return False
        finally:
            self._robot = None
            # Clear software E-stop flag on disconnect
            self._software_estop_active = False

    def _disconnect_sync(self):
        """Synchronous disconnection implementation.

        Calls mecademicpy Disconnect() which:
        - Shuts down queue threads
        - Closes _command_socket and _monitor_socket
        - Sets on_disconnected event
        """
        try:
            if self._robot and hasattr(self._robot, 'Disconnect'):
                self._robot.Disconnect()
                self.logger.debug(f"Disconnect() called for Mecademic robot {self.robot_id}")
        except Exception as e:
            self.logger.error(f"Error disconnecting from {self.robot_id}: {e}")

    async def force_reconnect(self) -> bool:
        """Force a complete reconnection by destroying old instance and releasing robot lock.

        Use this when normal reconnect fails due to stale socket state.
        After emergency stop, the mecademicpy Robot instance may have dead
        socket threads (_check_internal_states throws DisconnectError).
        Creating a new Robot() + Connect() can fail if the old session blocks.

        Error 3001 "Another user is already controlling the robot" occurs when:
        - Disconnect() is called but doesn't release the occupation lock
        - The robot still thinks the old session is active

        This method:
        1. Calls DeactivateRobot() BEFORE Disconnect() to release occupation lock
        2. Forces cleanup of the old Robot instance
        3. Waits for TCP cleanup (5 seconds for Error 3001)
        4. Creates a fresh connection with full activation

        Note: For quick recovery after E-stop, prefer checking if connection is alive
        and just calling ActivateRobot() instead of force_reconnect(). This method
        destroys the existing connection and resets all robot parameters.

        Returns:
            True if reconnection successful, False otherwise
        """
        try:
            self.logger.debug(f"Force reconnect initiated for {self.robot_id}")

            # Step 0: Try to reset error state first (needed after software E-stop)
            if self._robot:
                try:
                    if hasattr(self._robot, 'ResetError'):
                        self.logger.debug(f"Resetting error state for {self.robot_id}")
                        self._robot.ResetError()
                        await asyncio.sleep(0.5)  # Brief pause for robot to process
                except Exception as reset_err:
                    self.logger.debug(f"ResetError during force_reconnect: {reset_err}")

            # Step 1: Force cleanup of old instance - MUST deactivate first to release lock
            if self._robot:
                try:
                    # Deactivate BEFORE disconnect to release occupation lock (fixes Error 3001)
                    if hasattr(self._robot, 'DeactivateRobot'):
                        self.logger.debug(f"Deactivating robot to release occupation lock for {self.robot_id}")
                        try:
                            self._robot.DeactivateRobot()
                        except Exception as deact_err:
                            self.logger.debug(f"DeactivateRobot during force_reconnect: {deact_err}")

                    if hasattr(self._robot, 'Disconnect'):
                        self._robot.Disconnect()
                except Exception as disc_err:
                    # Ignore errors during cleanup - the socket may already be dead
                    self.logger.debug(f"Disconnect during force_reconnect (expected): {disc_err}")

            # Explicitly release the old instance
            self._robot = None
            self._connected = False
            # Clear software E-stop flag on force reconnect
            self._software_estop_active = False

            # Step 2: Wait for TCP cleanup - increased to 5 seconds for Error 3001
            # This allows TIME_WAIT sockets to clear and the robot to release the session
            self.logger.debug(f"Waiting 5s for TCP cleanup and session release for {self.robot_id}")
            await asyncio.sleep(5.0)

            # Step 3: Full reconnect with activation/homing/params
            self.logger.debug(f"Attempting fresh connection for {self.robot_id}")
            return await self._connect_impl()

        except Exception as e:
            self.logger.error(f"Force reconnect failed for {self.robot_id}: {type(e).__name__}: {e}")
            return False
    
    async def is_connected(self) -> bool:
        """
        Check if robot is connected using mecademicpy's IsConnected().

        This overrides the base class method to use the actual robot state
        instead of just the internal flag, which can become stale.

        Returns:
            True if connected, False otherwise
        """
        if not self._robot:
            return False

        try:
            loop = asyncio.get_event_loop()
            is_conn = await loop.run_in_executor(
                self._executor,
                lambda: self._robot.IsConnected() if hasattr(self._robot, 'IsConnected') else False
            )
            # Sync internal flag with actual state
            self._connected = is_conn
            return is_conn
        except Exception as e:
            self.logger.debug(f"IsConnected check failed for {self.robot_id}: {e}")
            return False

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
        
        self.debug_log("_get_status_impl", "entry", "Getting robot status")
        
        # Use cached status if available and fresh
        if (self._last_status and 
            current_time - self._last_status_time < self._status_cache_duration):
            self.debug_log("_get_status_impl", "cache_hit", 
                          f"Using cached status", {"age": current_time - self._last_status_time})
            return self._last_status.copy()
        
        self.debug_log("_get_status_impl", "cache_miss", "Status cache expired or empty - fetching fresh status")
        
        try:
            if not self._robot:
                self.debug_log("_get_status_impl", "no_robot", "No robot instance available")
                return {"connected": False, "error": "Robot not initialized"}
            
            self.debug_log("_get_status_impl", "fetching", "Executing status fetch in thread pool")
            loop = asyncio.get_event_loop()
            status = await loop.run_in_executor(
                self._executor,
                self._get_status_sync
            )
            
            self.debug_log("_get_status_impl", "status_received", 
                          f"Fresh status retrieved", {"status": status})
            
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

            if hasattr(self._robot, 'GetStatusRobot'):
                robot_status = self._robot.GetStatusRobot()

                if robot_status:
                    status.update({
                        "activation_status": getattr(robot_status, 'activation_state', False),
                        "homing_status": getattr(robot_status, 'homing_state', False),
                        "error_status": getattr(robot_status, 'error_status', False),
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
        """
        Synchronous emergency stop implementation using proper Mecademic API methods.
        
        Uses ClearMotion() as primary method (closest to hardware e-stop behavior):
        - Stops robot movement immediately
        - Clears all planned movements from queue
        - Follows Mecademic recommended emergency stop sequence
        """
        try:
            emergency_executed = False
            
            # STEP 1: Immediate stop current movement
            if hasattr(self._robot, 'PauseMotion'):
                self.logger.critical(f"[EMERGENCY] Executing PauseMotion() for immediate stop on {self.robot_id}")
                self._robot.PauseMotion()
                emergency_executed = True
                self.logger.critical(f"[OK] PauseMotion() immediate stop executed for {self.robot_id}")
                # Set software E-stop flag (hardware error_status won't be set for software E-stop)
                self._software_estop_active = True

            # STEP 2: Clear remaining movement queue
            if hasattr(self._robot, 'ClearMotion'):
                self.logger.critical(f"[EMERGENCY] Executing ClearMotion() to clear queue on {self.robot_id}")
                self._robot.ClearMotion()
                emergency_executed = True
                self.logger.critical(f"[OK] ClearMotion() queue cleared for {self.robot_id}")
                
                # Also engage brakes if available for additional safety
                if hasattr(self._robot, 'BrakesOn'):
                    try:
                        self._robot.BrakesOn()
                        self.logger.critical(f"[OK] Emergency brakes engaged for {self.robot_id}")
                    except Exception as brake_error:
                        self.logger.warning(f"[WARNING] Could not engage brakes during emergency stop: {brake_error}")
                        
            # STEP 3: Fallback if neither method available
            if not emergency_executed and hasattr(self._robot, 'StopMotion'):
                self.logger.critical(f"[EMERGENCY] Executing StopMotion() fallback for emergency stop on {self.robot_id}")
                self._robot.StopMotion()
                emergency_executed = True
                self.logger.critical(f"[OK] StopMotion() fallback executed for {self.robot_id}")
                
            else:
                self.logger.error(f"[ERROR] No emergency stop methods available for {self.robot_id}")
                self.logger.error(f"[TIP] Available methods: {[attr for attr in dir(self._robot) if 'Motion' in attr or 'Stop' in attr or 'Brake' in attr]}")
                
            if emergency_executed:
                self.logger.critical(f"[STOPPED] Emergency stop completed for {self.robot_id} - robot halted in place")
                # Note: Connection preserved, no movement to safe position, gripper state unchanged
            else:
                self.logger.error(f"[ERROR] Emergency stop FAILED for {self.robot_id} - no suitable methods available")
                
        except Exception as e:
            self.logger.error(f"[ERROR] Critical error during emergency stop for {self.robot_id}: {type(e).__name__}: {e}")
            # Log detailed error info for debugging
            import traceback
            self.logger.error(f"Emergency stop error traceback:\n{traceback.format_exc()}")
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
                self.logger.debug(f"Homing initiated for {self.robot_id}")

                # Wait for homing to complete if method available
                if hasattr(self._robot, 'WaitHomed'):
                    self._robot.WaitHomed(timeout=60.0)
                    self.logger.debug(f"Homing completed for {self.robot_id}")
                else:
                    # Fallback: wait a bit and check status
                    time.sleep(2.0)
            else:
                self.logger.warning(f"Homing not available for {self.robot_id}")
        except Exception as e:
            self.logger.error(f"Homing error for {self.robot_id}: {e}")
            raise

    async def wait_homed(self, timeout: float = 40.0) -> bool:
        """
        Wait for robot homing to complete.

        Args:
            timeout: Maximum time to wait in seconds (default 40s per mecademicpy)

        Returns:
            True if homing completed successfully
        """
        try:
            if not self._robot:
                raise ConnectionError(f"Robot {self.robot_id} not connected")

            self.logger.debug(f"Waiting for robot {self.robot_id} to complete homing (timeout: {timeout}s)")

            loop = asyncio.get_event_loop()

            if hasattr(self._robot, 'WaitHomed'):
                await loop.run_in_executor(
                    self._executor,
                    self._robot.WaitHomed,
                    timeout
                )
                self.logger.debug(f"Robot {self.robot_id} homing completed")
                return True
            else:
                # Fallback: wait and check status periodically
                self.logger.warning(f"WaitHomed not available for {self.robot_id}, using fallback")
                await asyncio.sleep(min(timeout, 10.0))
                return True

        except Exception as e:
            self.logger.error(f"Wait homed failed for {self.robot_id}: {e}")
            raise HardwareError(f"Wait homed failed: {e}", robot_id=self.robot_id)

    async def activate_robot(self) -> bool:
        """Activate the robot for operation with connection validation and retry"""
        self.logger.debug(f"[STARTING] NEW ACTIVATION LOGIC CALLED for {self.robot_id}")
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
                
                self.logger.debug(f"[OK] Robot {self.robot_id} activation successful on attempt {attempt + 1}")
                return True
                
            except Exception as e:
                error_str = str(e)
                self.logger.warning(f"[WARNING] Activation attempt {attempt + 1} failed for {self.robot_id}: {error_str}")
                
                # Check if this is a socket/connection error that we can retry
                if attempt < max_retries - 1 and any(err in error_str.lower() for err in 
                    ['socket was closed', 'connection', 'disconnect', 'communication']):
                    
                    self.logger.debug(f"[CONNECTING] Connection issue detected, attempting reconnection for {self.robot_id}")
                    
                    # Try to reconnect
                    try:
                        await self._reconnect_for_activation()
                        self.logger.debug(f"[READY] Reconnection successful, retrying activation for {self.robot_id}")
                        continue  # Retry activation
                    except Exception as reconnect_error:
                        self.logger.error(f"[ERROR] Reconnection failed for {self.robot_id}: {reconnect_error}")
                
                # If this is the last attempt or not a connection error, raise the exception
                if attempt == max_retries - 1:
                    self.logger.error(f"[ERROR] All activation attempts failed for {self.robot_id}: {e}")
                    raise HardwareError(f"Activation failed after {max_retries} attempts: {e}", robot_id=self.robot_id)
    
    async def _validate_connection_before_activation(self, attempt_num: int):
        """Validate connection status before attempting activation"""
        self.logger.debug(f"[DEBUG] Validating connection before activation attempt {attempt_num} for {self.robot_id}")
        
        if not self._robot:
            raise ConnectionError(f"No robot instance available for {self.robot_id}")
        
        # Check if robot reports as connected
        if hasattr(self._robot, 'IsConnected'):
            loop = asyncio.get_event_loop()
            is_connected = await loop.run_in_executor(
                self._executor,
                lambda: self._robot.IsConnected()
            )
            
            self.logger.debug(f"[STATUS] Robot {self.robot_id} IsConnected() reports: {is_connected}")
            
            if not is_connected:
                raise ConnectionError(f"Robot {self.robot_id} reports as not connected")
        else:
            self.logger.warning(f"[WARNING] Robot {self.robot_id} lacks IsConnected() method")
        
        # Clear robot occupation state before activation
        await self._clear_robot_occupation_state(attempt_num)
    
    async def _clear_robot_occupation_state(self, attempt_num: int):
        """Clear robot occupation state to allow activation"""
        self.logger.debug(f"[CLEARING] Clearing robot occupation state for attempt {attempt_num} on {self.robot_id}")
        
        if not self._robot:
            self.logger.warning(f"[WARNING] No robot instance to clear state for {self.robot_id}")
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
                    
                    self.logger.debug(f"[DEBUG] Current robot state before clearing: activated={activated}, homed={homed}, error={error}")

                    # If robot is already activated and homed with no errors, don't clear
                    if activated and homed and not error:
                        self.logger.debug(f"[OK] Robot {self.robot_id} already in good state, skipping occupation clearing")
                        return

                    # If robot just has error but is activated/homed, only reset error, don't deactivate
                    if activated and homed and error:
                        self.logger.debug(f"[EXEC] Robot {self.robot_id} activated/homed but has error, only resetting error")
                        if hasattr(self._robot, 'ResetError'):
                            await loop.run_in_executor(self._executor, self._robot.ResetError)
                            self.logger.debug(f"[OK] Error reset for {self.robot_id}")
                        return
                        
                except Exception as status_e:
                    self.logger.warning(f"[WARNING] Could not check robot status, proceeding with clearing: {status_e}")
            
            # Step 1: Deactivate robot if it's activated/occupied (only if needed)
            if hasattr(self._robot, 'DeactivateRobot'):
                self.logger.debug(f"[EXEC] Calling DeactivateRobot() to clear occupation for {self.robot_id}")
                await loop.run_in_executor(
                    self._executor,
                    self._robot.DeactivateRobot
                )
                self.logger.debug(f"[OK] DeactivateRobot() completed for {self.robot_id}")
                
                # Wait for deactivation to complete
                await asyncio.sleep(1.0)
            else:
                self.logger.warning(f"[WARNING] DeactivateRobot() not available for {self.robot_id}")
            
            # Step 2: Clear any pending motions
            if hasattr(self._robot, 'ClearMotion'):
                self.logger.debug(f"[EXEC] Calling ClearMotion() for {self.robot_id}")
                await loop.run_in_executor(
                    self._executor,
                    self._robot.ClearMotion
                )
                self.logger.debug(f"[OK] ClearMotion() completed for {self.robot_id}")
            else:
                self.logger.warning(f"[WARNING] ClearMotion() not available for {self.robot_id}")
            
            # Step 3: Reset any error states
            if hasattr(self._robot, 'ResetError'):
                self.logger.debug(f"[EXEC] Calling ResetError() for {self.robot_id}")
                await loop.run_in_executor(
                    self._executor,
                    self._robot.ResetError
                )
                self.logger.debug(f"[OK] ResetError() completed for {self.robot_id}")
            else:
                self.logger.warning(f"[WARNING] ResetError() not available for {self.robot_id}")
            
            # Wait a moment for all clearing operations to take effect
            await asyncio.sleep(0.5)
            self.logger.debug(f"[READY] Robot occupation state cleared for {self.robot_id}")
            
        except Exception as e:
            self.logger.warning(f"[WARNING] Error during occupation state clearing for {self.robot_id}: {e}")
            # Don't raise the exception - we'll still try activation
    
    async def _reconnect_for_activation(self):
        """Attempt to reconnect the robot for activation"""
        self.logger.debug(f"[CONNECTING] Starting reconnection process for {self.robot_id}")
        
        # First disconnect if still connected
        try:
            if self._robot and hasattr(self._robot, 'Disconnect'):
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(
                    self._executor,
                    self._robot.Disconnect
                )
                self.logger.debug(f"[SOCKET] Disconnected stale connection for {self.robot_id}")
        except Exception as disconnect_error:
            self.logger.warning(f"[WARNING] Error during disconnect for {self.robot_id}: {disconnect_error}")
        
        # Wait a moment for cleanup
        await asyncio.sleep(1.0)
        
        # Attempt fresh connection
        self._robot = None
        self._connected = False
        
        connection_success = await self._connect_impl()
        if not connection_success:
            raise ConnectionError(f"Failed to re-establish connection for {self.robot_id}")
        
        self.logger.debug(f"[OK] Fresh connection established for {self.robot_id}")

    def _activate_robot_sync(self):
        """Synchronous robot activation implementation"""
        try:
            if hasattr(self._robot, 'ActivateRobot'):
                self.logger.debug(f"[EXEC] Calling ActivateRobot() for {self.robot_id}")
                self._robot.ActivateRobot()
                self.logger.debug(f"[OK] ActivateRobot() completed for {self.robot_id}")
                
                # Wait for activation to complete
                time.sleep(1.0)
            else:
                self.logger.warning(f"[WARNING] ActivateRobot() not available for {self.robot_id}")
        except Exception as e:
            self.logger.error(f"[ERROR] Activation error for {self.robot_id}: {type(e).__name__}: {e}")
            raise
    
    async def clear_motion(self) -> bool:
        """Clear robot motion queue"""
        try:
            self.debug_log("clear_motion", "entry", "Starting clear motion sequence")
            
            if not self._robot:
                self.debug_log("clear_motion", "no_robot", "No robot connection available")
                self.logger.warning(f"[WARNING] No robot connection to clear motion for {self.robot_id}")
                return False
                
            self.debug_log("clear_motion", "clearing", "Calling ClearMotion() on robot instance")
            self.logger.debug(f"[EXEC] Clearing motion queue for {self.robot_id}")
            loop = asyncio.get_event_loop()
            
            if hasattr(self._robot, 'ClearMotion'):
                self.debug_log("clear_motion", "executing", "Executing ClearMotion() in thread pool")
                await loop.run_in_executor(
                    self._executor,
                    self._robot.ClearMotion
                )
                self.debug_log("clear_motion", "success", "ClearMotion() completed successfully")
                self.logger.debug(f"[OK] ClearMotion() completed for {self.robot_id}")
                return True
            else:
                self.debug_log("clear_motion", "unavailable", "ClearMotion() method not available")
                self.logger.warning(f"[WARNING] ClearMotion() not available for {self.robot_id}")
                return False
                
        except Exception as e:
            self.logger.error(f"[ERROR] Clear motion error for {self.robot_id}: {type(e).__name__}: {e}")
            return False

    async def resume_motion(self) -> bool:
        """Resume robot motion after pause"""
        try:
            self.debug_log("resume_motion", "entry", "Starting resume motion sequence")
            
            if not self._robot:
                self.debug_log("resume_motion", "no_robot", "No robot connection available")
                self.logger.warning(f"[WARNING] No robot connection to resume motion for {self.robot_id}")
                return False
                
            self.debug_log("resume_motion", "resuming", "Calling ResumeMotion() on robot instance")
            self.logger.debug(f"[EXEC] Resuming motion for {self.robot_id}")
            loop = asyncio.get_event_loop()
            
            if hasattr(self._robot, 'ResumeMotion'):
                self.debug_log("resume_motion", "executing", "Executing ResumeMotion() in thread pool")
                await loop.run_in_executor(
                    self._executor,
                    self._robot.ResumeMotion
                )
                self.debug_log("resume_motion", "success", "ResumeMotion() completed successfully")
                self.logger.debug(f"[OK] ResumeMotion() completed for {self.robot_id}")
                return True
            else:
                self.debug_log("resume_motion", "unavailable", "ResumeMotion() method not available")
                self.logger.warning(f"[WARNING] ResumeMotion() not available for {self.robot_id}")
                return False
                
        except Exception as e:
            self.logger.error(f"[ERROR] Resume motion error for {self.robot_id}: {type(e).__name__}: {e}")
            return False

    async def wait_idle(self, timeout: float = 30.0) -> bool:
        """Wait for robot to become idle (motion complete)"""
        try:
            if not self._robot:
                self.logger.warning(f"[WARNING] No robot connection to wait for idle for {self.robot_id}")
                return False
                
            self.logger.debug(f"[WAITING] Waiting for robot {self.robot_id} to become idle (timeout: {timeout}s)")
            loop = asyncio.get_event_loop()
            
            if hasattr(self._robot, 'WaitIdle'):
                # WaitIdle expects timeout in milliseconds
                timeout_ms = int(timeout * 1000)
                await loop.run_in_executor(
                    self._executor,
                    self._robot.WaitIdle,
                    timeout_ms
                )
                self.logger.debug(f"[OK] Robot {self.robot_id} is now idle")
                return True
            else:
                self.logger.warning(f"[WARNING] WaitIdle() not available for {self.robot_id}")
                # Fallback: wait and check status
                await asyncio.sleep(timeout)
                return False
                
        except Exception as e:
            self.logger.error(f"[ERROR] Wait idle error for {self.robot_id}: {type(e).__name__}: {e}")
            return False

    async def reset_error(self) -> bool:
        """
        Reset robot error state following Mecademic best practices.

        From Mecademic robot_initializer.py:
            robot.ResetError()
            robot.WaitErrorReset(timeout=5)

        Returns:
            True if error reset successful, False otherwise
        """
        max_attempts = 3

        for attempt in range(max_attempts):
            try:
                if not self._robot:
                    self.logger.warning(f"[WARNING] No robot connection for error reset on {self.robot_id}")
                    return False

                # Check if reset/resume is needed (handles both hardware errors and software E-stop)
                async with self._estop_lock:
                    software_estop = self._software_estop_active

                status = await self.get_status()
                error_status = status.get('error_status', False)
                pause_status = status.get('paused', False)

                needs_error_reset = error_status
                needs_motion_resume = pause_status or software_estop

                if not needs_error_reset and not needs_motion_resume:
                    self.logger.debug(f"Robot {self.robot_id} not in error/paused state - no reset needed")
                    return True

                self.logger.debug(f"[EXEC] Resetting robot {self.robot_id}: error={needs_error_reset}, paused={needs_motion_resume}, software_estop={software_estop} (attempt {attempt + 1})")
                loop = asyncio.get_event_loop()

                # Call ResetError() (Mecademic pattern)
                if hasattr(self._robot, 'ResetError'):
                    await loop.run_in_executor(self._executor, self._robot.ResetError)
                    self.logger.debug(f"[OK] ResetError() called for {self.robot_id}")

                    # Wait for error reset confirmation (Mecademic pattern)
                    if hasattr(self._robot, 'WaitErrorReset'):
                        try:
                            await loop.run_in_executor(
                                self._executor,
                                lambda: self._robot.WaitErrorReset(timeout=5.0)
                            )
                            self.logger.debug(f"[OK] Error reset confirmed via WaitErrorReset() for {self.robot_id}")
                        except Exception as wait_err:
                            self.logger.warning(f"[WARNING] WaitErrorReset timeout for {self.robot_id}: {wait_err}")
                            # Check status again to verify error actually cleared
                            await asyncio.sleep(1.0)
                            verify_status = await self.get_status()
                            if verify_status.get('error_status'):
                                self.logger.warning(f"[WARNING] Robot {self.robot_id} still in error after reset attempt")
                                if attempt < max_attempts - 1:
                                    continue  # Retry
                                return False
                    else:
                        # Fallback: wait a bit for reset to take effect
                        self.logger.debug(f"WaitErrorReset not available, using fallback wait for {self.robot_id}")
                        await asyncio.sleep(2.0)

                    # Clear status cache after error reset
                    if hasattr(self, 'clear_status_cache'):
                        self.clear_status_cache()

                    # NOTE: ResumeMotion is NOT called here intentionally.
                    # ResumeMotion should only be called from resume_motion() after speed is set,
                    # to prevent race conditions where motion resumes before proper speed configuration.

                    # Clear software E-stop flag after successful recovery
                    async with self._estop_lock:
                        self._software_estop_active = False
                    self.logger.debug(f"[OK] Software E-stop cleared for {self.robot_id}")

                    return True
                else:
                    self.logger.warning(f"[WARNING] ResetError() not available for {self.robot_id}")
                    return False

            except Exception as e:
                error_str = str(e)
                self.logger.warning(f"[WARNING] Error reset attempt {attempt + 1} failed for {self.robot_id}: {error_str}")

                # Check if this is a connection error that we can recover from
                if "socket was closed" in error_str.lower() or "connection" in error_str.lower():
                    if attempt < max_attempts - 1:
                        self.logger.debug(f"[CONNECTING] Connection lost during error reset, attempting to reconnect for {self.robot_id}")
                        try:
                            # Try to reconnect
                            await self.force_reconnect()
                            await asyncio.sleep(1.0)
                            continue
                        except Exception as reconnect_e:
                            self.logger.warning(f"[WARNING] Reconnection failed: {reconnect_e}")

                # If last attempt or non-recoverable error, fail
                if attempt == max_attempts - 1:
                    self.logger.error(f"[ERROR] All error reset attempts failed for {self.robot_id}")
                    return False

        return False

    async def set_recovery_mode(self, activated: bool) -> bool:
        """
        Enable or disable recovery mode for the robot.

        Recovery mode enables slow movement without homing and without joint limits,
        which is useful for repositioning the robot after an emergency stop when
        it may be in an unsafe position.

        WARNING: Joint limits are disabled in recovery mode. Use with caution.

        Args:
            activated: True to enable recovery mode, False to disable

        Returns:
            True if successful, False otherwise

        Raises:
            ConnectionError: If the socket connection is dead (caller should reconnect)
        """
        try:
            if not self._robot:
                self.logger.warning(f"[WARNING] No robot connection for recovery mode for {self.robot_id}")
                return False

            mode_str = "enabled" if activated else "disabled"
            self.logger.debug(f"[EXEC] Setting recovery mode {mode_str} for {self.robot_id}")

            loop = asyncio.get_event_loop()

            if hasattr(self._robot, 'SetRecoveryMode'):
                await loop.run_in_executor(
                    self._executor,
                    self._robot.SetRecoveryMode,
                    activated
                )
                # Update local flag since mecademicpy doesn't expose this on status
                self._recovery_mode_active = activated
                self.logger.debug(f"[OK] Recovery mode {mode_str} for {self.robot_id}")
                return True
            else:
                self.logger.warning(f"[WARNING] SetRecoveryMode() not available for {self.robot_id}")
                return False

        except Exception as e:
            error_str = str(e).lower()
            error_type = type(e).__name__

            # Check for socket/disconnect errors - these indicate dead connection
            # mecademicpy raises DisconnectError when socket threads are dead
            is_socket_error = (
                'disconnect' in error_type.lower() or
                'socket' in error_str or
                'connection' in error_str or
                'closed' in error_str or
                'disconnected' in error_str
            )

            if is_socket_error:
                self.logger.warning(
                    f"[SOCKET] Socket error during set_recovery_mode for {self.robot_id}: "
                    f"{error_type}: {e} - connection may need force reconnect"
                )
                # Raise ConnectionError so caller knows to reconnect
                raise ConnectionError(f"Socket connection dead for {self.robot_id}: {e}")
            else:
                self.logger.error(f"[ERROR] Set recovery mode error for {self.robot_id}: {error_type}: {e}")
                return False

    async def prepare_for_recovery_mode(self) -> bool:
        """Prepare robot for recovery mode after emergency stop.

        Calls ClearMotion() before SetRecoveryMode() as required
        by mecademicpy library after EStop.
        """
        try:
            if not self._robot:
                return False

            self.logger.debug(f"Preparing robot {self.robot_id} for recovery mode")

            loop = asyncio.get_event_loop()
            if hasattr(self._robot, 'ClearMotion'):
                await loop.run_in_executor(
                    self._executor,
                    self._robot.ClearMotion
                )
                self.logger.debug(f"ClearMotion() completed for {self.robot_id}")

            await asyncio.sleep(0.5)
            return True

        except Exception as e:
            self.logger.error(f"Failed to prepare for recovery mode: {e}")
            return False

    async def get_safety_status(self) -> Dict[str, Any]:
        """
        Get comprehensive safety status including error state, recovery mode, and safety stops.

        Returns:
            Dictionary containing:
            - error_status: True if robot is in error state
            - recovery_mode: True if recovery mode is enabled
            - e_stop_active: True if emergency stop is active (hardware OR software OR motion paused)
            - p_stop_active: True if protective stop is active
            - is_activated: True if robot is activated
            - is_homed: True if robot is homed
            - is_connected: True if connected to robot
            - software_estop_active: True if software E-stop flag is set
            - motion_paused: True if robot's pause_motion_status is True (SOURCE OF TRUTH)
        """
        safety_info = {
            "error_status": False,
            "recovery_mode": False,
            "e_stop_active": False,
            "p_stop_active": False,
            "is_activated": False,
            "is_homed": False,
            "is_connected": self._connected,
            "robot_id": self.robot_id,
            "software_estop_active": False,
            "motion_paused": False,
        }

        try:
            if not self._robot:
                self.logger.warning(f"[WARNING] No robot connection for safety status for {self.robot_id}")
                # CRITICAL: Still check software E-stop flag even when disconnected!
                safety_info["software_estop_active"] = self._software_estop_active
                if self._software_estop_active:
                    safety_info["e_stop_active"] = True
                    self.logger.warning(f"E-stop active (software flag) for disconnected robot {self.robot_id}")
                return safety_info

            loop = asyncio.get_event_loop()

            # Get status flags using GetStatusRobot
            if hasattr(self._robot, 'GetStatusRobot'):
                try:
                    status = await loop.run_in_executor(
                        self._executor,
                        self._robot.GetStatusRobot
                    )
                    if status:

                        if hasattr(status, 'error_status'):
                            safety_info["error_status"] = status.error_status
                        if hasattr(status, 'estopState'):
                            # estopState is an enum - 0 means not active
                            safety_info["e_stop_active"] = status.estopState != 0
                        if hasattr(status, 'pstop2State'):
                            # pstop2State is an enum - 0 means not active
                            safety_info["p_stop_active"] = status.pstop2State != 0
                        if hasattr(status, 'activation_state'):
                            safety_info["is_activated"] = status.activation_state
                        if hasattr(status, 'homing_state'):
                            safety_info["is_homed"] = status.homing_state

                        # Check pause_motion_status - this is the SOURCE OF TRUTH for software E-stop
                        if hasattr(status, 'pause_motion_status'):
                            motion_paused = status.pause_motion_status
                            safety_info["motion_paused"] = motion_paused
                            if motion_paused:
                                self.logger.debug(f"Robot {self.robot_id} motion is paused (pause_motion_status=True)")

                        # Use local tracking since mecademicpy doesn't expose recovery_mode on status
                        safety_info["recovery_mode"] = self._recovery_mode_active

                        # Include software E-stop flag and combine all E-stop sources
                        safety_info["software_estop_active"] = self._software_estop_active

                        hardware_estop = safety_info.get("e_stop_active", False)
                        motion_paused = safety_info.get("motion_paused", False)
                        safety_info["e_stop_active"] = hardware_estop or self._software_estop_active or motion_paused
                except Exception as e:
                    self.logger.warning(f"GetStatusRobot parsing failed: {type(e).__name__}: {e}")

            # Fallback: use our regular get_status method
            try:
                regular_status = await self.get_status()
                if regular_status:
                    if "error_status" in regular_status:
                        safety_info["error_status"] = regular_status["error_status"]
                    if "activation_status" in regular_status:
                        safety_info["is_activated"] = regular_status["activation_status"]
                    if "homing_status" in regular_status:
                        safety_info["is_homed"] = regular_status["homing_status"]
                    if "connected" in regular_status:
                        safety_info["is_connected"] = regular_status["connected"]
                    # Also check paused status as another E-stop source
                    if regular_status.get("paused", False):
                        safety_info["motion_paused"] = True
                        safety_info["e_stop_active"] = True
                        self.logger.debug(f"Motion paused detected via get_status for {self.robot_id}")
            except Exception as e:
                self.logger.debug(f"Regular status fallback failed: {e}")

            # Always include software E-stop flag (even if GetStatusRobot failed)
            safety_info["software_estop_active"] = self._software_estop_active
            if self._software_estop_active:
                safety_info["e_stop_active"] = True

            self.logger.debug(f"Safety status for {self.robot_id}: {safety_info}")
            return safety_info

        except Exception as e:
            self.logger.error(f"[ERROR] Get safety status error for {self.robot_id}: {type(e).__name__}: {e}")
            return safety_info

    async def get_joints(self) -> tuple:
        """
        Get current joint positions.

        Returns:
            tuple: Six joint angles in degrees (j1, j2, j3, j4, j5, j6)
        """
        try:
            if not self._robot:
                raise ConnectionError(f"Robot {self.robot_id} not connected")

            loop = asyncio.get_event_loop()
            joints = await loop.run_in_executor(
                self._executor,
                self._robot.GetJoints
            )
            return joints
        except Exception as e:
            self.logger.error(f"Failed to get joints for {self.robot_id}: {e}")
            raise HardwareError(f"Failed to get joints: {e}", robot_id=self.robot_id)

    async def deactivate_robot(self) -> bool:
        """
        Deactivate the robot for recovery operations.

        This is used to put the robot in a state where it can be safely
        manipulated in recovery mode.

        Returns:
            True if successful, False otherwise
        """
        try:
            if not self._robot:
                self.logger.warning(f"[WARNING] No robot connection to deactivate for {self.robot_id}")
                return False

            self.logger.debug(f"[EXEC] Deactivating robot {self.robot_id}")

            loop = asyncio.get_event_loop()

            if hasattr(self._robot, 'DeactivateRobot'):
                await loop.run_in_executor(
                    self._executor,
                    self._robot.DeactivateRobot
                )
                self.logger.debug(f"[OK] Robot {self.robot_id} deactivated")
                return True
            else:
                self.logger.warning(f"[WARNING] DeactivateRobot() not available for {self.robot_id}")
                return False

        except Exception as e:
            self.logger.error(f"[ERROR] Deactivate robot error for {self.robot_id}: {type(e).__name__}: {e}")
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