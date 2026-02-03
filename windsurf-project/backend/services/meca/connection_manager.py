"""
Connection manager for Mecademic robot.

Handles all connection-related operations including:
- Connect/disconnect with proper state management
- Safe connect with user confirmation flow
- Reconnection with exponential backoff
- Connection validation and health checks
"""

import asyncio
import time
from typing import Dict, Any, Optional, Tuple

from core.async_robot_wrapper import AsyncRobotWrapper
from core.state_manager import AtomicStateManager, RobotState
from core.circuit_breaker import circuit_breaker
from core.exceptions import HardwareError
from core.settings import RoboticsSettings
from utils.logger import get_logger


class MecaConnectionManager:
    """
    Manages connections to the Mecademic robot.

    Handles all connection lifecycle including connecting, disconnecting,
    safe connection with user confirmation, and automatic reconnection
    with exponential backoff.
    """

    def __init__(
        self,
        robot_id: str,
        settings: RoboticsSettings,
        async_wrapper: AsyncRobotWrapper,
        state_manager: AtomicStateManager,
        broadcaster_callback=None
    ):
        """
        Initialize connection manager.

        Args:
            robot_id: Robot identifier
            settings: Robotics settings
            async_wrapper: AsyncRobotWrapper for robot communication
            state_manager: AtomicStateManager for state tracking
            broadcaster_callback: Optional callback for broadcasting state changes
        """
        self.robot_id = robot_id
        self.settings = settings
        self.async_wrapper = async_wrapper
        self.state_manager = state_manager
        self.broadcaster_callback = broadcaster_callback
        self.logger = get_logger("meca_connection_manager")

        # Exponential backoff for reconnection attempts
        self._reconnect_attempt_count = 0
        self._next_reconnect_time = 0.0
        self._base_reconnect_delay = 1.0
        self._max_reconnect_delay = 30.0
        self._max_reconnect_attempts = 10

        # Flag to prevent auto-reconnection when user intentionally disconnected
        self._user_disconnected = False

    @property
    def user_disconnected(self) -> bool:
        """Check if user intentionally disconnected."""
        return self._user_disconnected

    @user_disconnected.setter
    def user_disconnected(self, value: bool) -> None:
        """Set user disconnected flag."""
        self._user_disconnected = value

    def enable_auto_reconnection(self) -> None:
        """Re-enable auto-reconnection after user disconnect."""
        self._user_disconnected = False
        self.logger.info(f"Auto-reconnection re-enabled for {self.robot_id}")

    def reset_reconnect_backoff(self) -> None:
        """Reset exponential backoff state."""
        self._reconnect_attempt_count = 0
        self._next_reconnect_time = 0.0

    def _schedule_next_reconnect_attempt(self, reason: str) -> None:
        """Schedule next reconnection attempt with exponential backoff."""
        self._reconnect_attempt_count = min(
            self._reconnect_attempt_count + 1,
            self._max_reconnect_attempts - 1
        )
        delay = min(
            self._base_reconnect_delay * (2 ** (self._reconnect_attempt_count - 1)),
            self._max_reconnect_delay
        )
        self._next_reconnect_time = time.time() + delay
        self.logger.debug(f"Next reconnect in {delay:.1f}s: {reason}")

    @circuit_breaker("meca_tcp_test", failure_threshold=3, recovery_timeout=10)
    async def test_robot_connection(self) -> bool:
        """
        Test if robot connection is working using real TCP connection.

        Returns:
            True if TCP connection succeeds

        Raises:
            HardwareError: If connection fails
        """
        meca_ip = self.settings.meca_ip
        meca_port = self.settings.meca_port
        connection_timeout = 5.0

        reader = None
        writer = None
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(meca_ip, meca_port),
                timeout=connection_timeout
            )

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
            raise HardwareError(
                f"Network error connecting to Meca robot at {meca_ip}:{meca_port}: {e}",
                robot_id=self.robot_id
            )

    @circuit_breaker("meca_check_connection", failure_threshold=3, recovery_timeout=10)
    async def check_robot_connection(self) -> bool:
        """
        Check robot connection, attempting reconnection if needed.

        Returns:
            True if robot is connected
        """
        try:
            # Skip auto-reconnection if user intentionally disconnected
            if self._user_disconnected:
                self.logger.warning(f"Auto-reconnection blocked - user disconnected {self.robot_id}. Call connect() to re-enable.")
                return False

            await self.test_robot_connection()

            if not hasattr(self.async_wrapper, 'robot_driver'):
                return True

            driver = self.async_wrapper.robot_driver
            robot_instance = driver.get_robot_instance() if hasattr(driver, 'get_robot_instance') else None

            if not robot_instance:
                if time.time() >= self._next_reconnect_time:
                    reconnected = await self.attempt_robot_reconnection()
                    if reconnected:
                        self.logger.info(f"Successfully reconnected to robot {self.robot_id}")
                        return True
                return False

            return True
        except Exception as e:
            self.logger.debug(f"Connection check failed: {e}")
            return False

    @circuit_breaker("meca_reconnection", failure_threshold=2, recovery_timeout=5)
    async def attempt_robot_reconnection(self) -> bool:
        """
        Attempt reconnection with exponential backoff.

        Returns:
            True if reconnection successful
        """
        if not hasattr(self.async_wrapper, 'robot_driver'):
            self._schedule_next_reconnect_attempt("No driver")
            return False

        driver = self.async_wrapper.robot_driver
        self.logger.info(f"Reconnection attempt {self._reconnect_attempt_count + 1} for {self.robot_id}")

        try:
            if await driver.connect():
                self.reset_reconnect_backoff()
                await self.state_manager.update_robot_state(
                    self.robot_id,
                    RobotState.IDLE,
                    reason="Reconnected"
                )
                self.logger.info(f"Reconnected to {self.robot_id}")
                return True

            self._schedule_next_reconnect_attempt("Connection failed")
            return False

        except Exception as e:
            self._schedule_next_reconnect_attempt(str(e)[:50])
            return False

    async def connect(self, capture_position_callback=None) -> Dict[str, Any]:
        """
        Connect to the Mecademic robot.

        Args:
            capture_position_callback: Optional callback to capture position after connect

        Returns:
            Connection result
        """
        # Reset user disconnect flag - user is explicitly connecting
        self._user_disconnected = False
        self.logger.info(f"User-initiated connect - auto-reconnection re-enabled for {self.robot_id}")

        await self.state_manager.update_robot_state(
            self.robot_id,
            RobotState.CONNECTING,
            reason="Connecting to robot"
        )

        if not hasattr(self.async_wrapper, 'robot_driver'):
            await self.state_manager.update_robot_state(
                self.robot_id,
                RobotState.ERROR,
                reason="Robot driver not available"
            )
            return {"success": False, "error": "Robot driver not available"}

        driver = self.async_wrapper.robot_driver
        try:
            connected = await driver.connect()
            if not connected:
                self.logger.error(f"Connection failed for {self.robot_id}")
                await self.state_manager.update_robot_state(
                    self.robot_id,
                    RobotState.ERROR,
                    reason="Failed to connect"
                )
                return {"success": False, "error": "Connection failed"}

            self.reset_reconnect_backoff()
            if capture_position_callback:
                await capture_position_callback()
            await self.state_manager.update_robot_state(
                self.robot_id,
                RobotState.IDLE,
                reason="Connected successfully"
            )
            self.logger.info(f"Robot {self.robot_id} connected and ready")
            return {"success": True}

        except Exception as e:
            await self.state_manager.update_robot_state(
                self.robot_id,
                RobotState.ERROR,
                reason=f"Connection error: {e}"
            )
            raise

    async def disconnect(self) -> Dict[str, Any]:
        """
        Disconnect from the Mecademic robot.

        Returns:
            Disconnection result
        """
        try:
            if hasattr(self.async_wrapper, 'robot_driver'):
                driver = self.async_wrapper.robot_driver
                disconnected = await driver.disconnect()

                await self.state_manager.update_robot_state(
                    self.robot_id,
                    RobotState.DISCONNECTED,
                    reason="Disconnected from robot"
                )

                self.logger.info(f"Disconnected from robot {self.robot_id}")
                return {"success": True, "disconnected": disconnected}
            else:
                await self.state_manager.update_robot_state(
                    self.robot_id,
                    RobotState.DISCONNECTED,
                    reason="Robot driver not available"
                )
                return {"success": True, "disconnected": True}

        except Exception as e:
            self.logger.error(f"Error during disconnection: {e}")
            await self.state_manager.update_robot_state(
                self.robot_id,
                RobotState.DISCONNECTED,
                reason=f"Disconnection error: {str(e)}"
            )
            return {"success": False, "error": str(e)}

    async def connect_safe(self) -> Dict[str, Any]:
        """
        Connect to robot WITHOUT automatic homing.
        Returns joint positions for UI confirmation before proceeding.

        Returns:
            Connection status with joint positions
        """
        self.logger.info(f"Safe connect initiated for robot {self.robot_id}")

        # Reset user disconnect flag
        self._user_disconnected = False
        self.logger.info(f"User-initiated connect - auto-reconnection re-enabled for {self.robot_id}")

        try:
            driver = self.async_wrapper.robot_driver

            # Pre-connection check: If already connected, return current state
            # This prevents Error 3001 "Another user is already controlling the robot"
            try:
                if await driver.is_connected():
                    self.logger.info(f"Robot {self.robot_id} already connected, returning current state")
                    status = await driver.get_status()
                    joints = await driver.get_joints()
                    return {
                        "connected": True,
                        "already_connected": True,
                        "joints": list(joints),
                        "message": "Robot already connected"
                    }
            except Exception as check_err:
                # Connection check failed - proceed with connect attempt
                self.logger.debug(f"Pre-connection check failed (proceeding with connect): {check_err}")

            # Step 1: Connect to robot (TCP connection only)
            connected = await driver.connect()
            if not connected:
                # Check if this was an Error 3001 situation - try force_reconnect
                self.logger.warning(
                    f"Initial connect failed for {self.robot_id}, attempting force_reconnect"
                )
                connected = await driver.force_reconnect()
                if not connected:
                    return {
                        "connected": False,
                        "error": True,
                        "message": f"Failed to connect to robot {self.robot_id}. "
                                  "If you triggered E-stop via app, the robot is in error state. "
                                  "Try using 'Reset & Reconnect' or power cycle the robot.",
                        "action_required": "reset_or_power_cycle"
                    }
            self.logger.info(f"TCP connection established for robot {self.robot_id}")

            # Update state to CONNECTING
            await self.state_manager.update_robot_state(
                self.robot_id,
                RobotState.CONNECTING,
                reason="TCP connection established, awaiting user confirmation"
            )

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

            # Step 4: Broadcast connection pending state
            if self.broadcaster_callback:
                await self.broadcaster_callback("connection_pending", {
                    "robot_id": self.robot_id,
                    "joints": list(joints),
                    "requires_confirmation": True,
                    "message": "Review robot position before homing"
                })

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

            try:
                await self.state_manager.update_robot_state(
                    self.robot_id,
                    RobotState.DISCONNECTED,
                    reason=f"Safe connect failed: {e}"
                )
            except Exception as state_err:
                self.logger.warning(f"Could not revert state: {state_err}")

            # Clean up TCP connection on failure
            try:
                driver = self.async_wrapper.robot_driver
                await driver.disconnect()
                self.logger.info(f"Cleaned up TCP connection after failed connect for {self.robot_id}")
            except Exception as cleanup_err:
                self.logger.warning(f"Cleanup disconnect failed: {cleanup_err}")

            raise HardwareError(f"Safe connect failed: {e}", robot_id=self.robot_id)

    async def confirm_activation(self, emergency_stop_callback=None) -> Dict[str, Any]:
        """
        User-confirmed activation and homing.
        Called by UI after user confirms robot position is safe.

        Args:
            emergency_stop_callback: Callback for emergency stop on failure

        Returns:
            Activation result
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

            # Step 4: Wait for homing to complete
            await driver.wait_homed(timeout=30.0)
            self.logger.info(f"Robot {self.robot_id} homing complete")

            # Step 5: Clear any pending motion commands after homing
            # IMPORTANT: After emergency stop + homing, the robot is at HOME position.
            # Any pending motion commands from before would be invalid/dangerous to resume.
            # Users must explicitly call quick_recovery to resume a paused sequence.
            status = await driver.get_status()
            if status.get('pause_motion_status'):
                self.logger.info(f"Robot {self.robot_id} has paused motion after homing - clearing motion queue")
                await driver.clear_motion()
                self.logger.info(f"Motion queue cleared. Use quick_recovery to resume sequence if needed.")

            # Step 6: Broadcast connection complete state
            if self.broadcaster_callback:
                await self.broadcaster_callback("connection_complete", {
                    "robot_id": self.robot_id,
                    "homed": True
                })

            # Step 7: Update internal state to IDLE
            await self.state_manager.update_robot_state(
                self.robot_id,
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
            if emergency_stop_callback:
                await emergency_stop_callback()
            raise HardwareError(f"Activation failed: {e}", robot_id=self.robot_id)

    async def disconnect_safe(self) -> Dict[str, Any]:
        """
        Gracefully disconnect from Mecademic robot.

        Per mecademicpy best practices, the proper disconnect sequence is:
        1. WaitIdle() - Wait for any motion to complete
        2. DeactivateRobot() - Deactivate before disconnect
        3. Disconnect() - Close TCP socket
        4. Post-disconnect delay - Give robot hardware time to release TCP connection

        Returns:
            Disconnection result
        """
        try:
            # Set flag to prevent auto-reconnection
            self._user_disconnected = True
            self.logger.info(f"User-initiated disconnect - auto-reconnection disabled for {self.robot_id}")

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

            # Step 1: Wait for any motion to complete
            try:
                await driver.wait_idle(timeout=10.0)
                self.logger.info(f"Robot {self.robot_id} is idle, proceeding with disconnect")
            except Exception as e:
                self.logger.warning(f"WaitIdle failed for {self.robot_id} (continuing): {e}")

            # Step 2: Deactivate robot before disconnect
            await driver.deactivate_robot()
            self.logger.info(f"Robot {self.robot_id} deactivated")

            await asyncio.sleep(0.5)

            # Step 3: Disconnect TCP socket
            await driver.disconnect()
            self.logger.info(f"Robot {self.robot_id} TCP disconnect called")

            # Step 4: Wait for socket to fully release
            await asyncio.sleep(1.0)

            # Step 5: Verify disconnection completed
            try:
                still_connected = await driver.is_connected()
                if still_connected:
                    self.logger.warning(f"Robot {self.robot_id} still reports connected, forcing cleanup")
                    try:
                        await driver.disconnect()
                        await asyncio.sleep(0.5)
                    except Exception:
                        pass
                else:
                    self.logger.info(f"Robot {self.robot_id} disconnect verified")
            except Exception as e:
                self.logger.debug(f"Post-disconnect connection check: {e}")

            # Update state to DISCONNECTED
            await self.state_manager.update_robot_state(
                self.robot_id,
                RobotState.DISCONNECTED,
                reason="User requested disconnect"
            )

            # Broadcast disconnected state
            if self.broadcaster_callback:
                await self.broadcaster_callback("disconnected", {
                    "robot_id": self.robot_id,
                    "disconnected": True
                })

            return {
                "disconnected": True,
                "was_connected": True
            }

        except Exception as e:
            self.logger.error(f"Robot {self.robot_id} disconnect failed: {e}")
            try:
                driver = self.async_wrapper.robot_driver
                await driver.disconnect()
            except Exception:
                pass
            raise HardwareError(f"Disconnect failed: {e}", robot_id=self.robot_id)

    async def attempt_recovery_reconnection(self, max_retries: int = 2) -> bool:
        """
        Attempt to reconnect to the robot for recovery mode.

        After emergency stop, the mecademicpy Robot instance may have dead socket
        threads. This method explicitly cleans up the old instance and waits longer
        for TCP cleanup before creating a fresh connection.

        Args:
            max_retries: Maximum number of reconnection attempts

        Returns:
            True if reconnection successful

        Raises:
            HardwareError: With actionable error message if reconnection fails
        """
        # Reset user disconnect flag - recovery should re-enable auto-reconnection
        self._user_disconnected = False
        self.logger.info(f"Recovery reconnection - auto-reconnection re-enabled for {self.robot_id}")

        driver = self.async_wrapper.robot_driver
        last_error = None

        for attempt in range(max_retries):
            try:
                self.logger.info(f"Recovery reconnection attempt {attempt + 1}/{max_retries} for {self.robot_id}")

                # Step 1: Force cleanup of old robot instance
                if hasattr(driver, 'disconnect'):
                    try:
                        await driver.disconnect()
                        self.logger.info(f"Disconnected stale session for {self.robot_id}")
                    except Exception as disc_err:
                        self.logger.debug(f"Disconnect during recovery (expected): {disc_err}")

                # Step 1b: Release robot instance reference
                if hasattr(driver, '_robot'):
                    driver._robot = None
                    driver._connected = False
                    self.logger.debug(f"Released old robot instance for {self.robot_id}")

                # Step 2: Wait for TCP cleanup
                self.logger.debug(f"Waiting 3s for TCP cleanup for {self.robot_id}")
                await asyncio.sleep(3.0)

                # Step 3: Attempt fresh connection
                if hasattr(driver, 'connect'):
                    self.logger.info(f"Attempting fresh connection for {self.robot_id}")
                    connected = await driver.connect()
                    if connected:
                        self.logger.info(f"Recovery reconnection successful for {self.robot_id}")
                        return True
                    else:
                        last_error = "Connection returned False"
                        self.logger.warning(f"Connection returned False for {self.robot_id}")
                else:
                    raise HardwareError(
                        f"Robot {self.robot_id} driver does not support connect(). "
                        "Please restart the backend service.",
                        robot_id=self.robot_id
                    )

            except Exception as e:
                last_error = e
                error_str = str(e)

                # Handle error 3001 - stale session
                if "3001" in error_str or "Another user" in error_str.lower():
                    self.logger.warning(f"Error 3001 detected - stale TCP session for {self.robot_id}")
                    await asyncio.sleep(3.0)
                    continue

                self.logger.warning(f"Recovery reconnection attempt {attempt + 1} failed: {e}")

        # All retries exhausted - provide actionable error message
        error_msg = str(last_error) if last_error else "Unknown error"
        self._raise_reconnection_error(error_msg)

    def _raise_reconnection_error(self, error_msg: str) -> None:
        """Raise appropriate HardwareError based on error message."""
        if "3001" in error_msg or "Another user" in error_msg.lower():
            raise HardwareError(
                f"Robot {self.robot_id} has a stale TCP session (Error 3001). "
                "Another connection may be blocking access. Please: "
                "1) Power cycle the robot (turn off, wait 10 seconds, turn on), or "
                "2) Restart the backend service to clear the stale session.",
                robot_id=self.robot_id
            )
        elif "timeout" in error_msg.lower():
            raise HardwareError(
                f"Robot {self.robot_id} connection timed out. Please: "
                "1) Check network connectivity to the robot, "
                "2) Verify the robot is powered on and responsive, "
                "3) Check if another application is connected to the robot.",
                robot_id=self.robot_id
            )
        elif "refused" in error_msg.lower():
            raise HardwareError(
                f"Robot {self.robot_id} refused connection. Please: "
                "1) Verify the robot is powered on, "
                "2) Check the robot's network configuration, "
                "3) Ensure no other client is connected.",
                robot_id=self.robot_id
            )
        else:
            raise HardwareError(
                f"Failed to reconnect to robot {self.robot_id}: {error_msg}. "
                "Please check the robot connection and try again. "
                "If the problem persists, power cycle the robot.",
                robot_id=self.robot_id
            )

    async def ensure_connection_for_recovery(self) -> Tuple[bool, Optional[str]]:
        """
        Check if robot is connected before recovery.

        Returns:
            Tuple of (is_connected, error_msg)
        """
        driver = self.async_wrapper.robot_driver

        robot_instance = driver.get_robot_instance() if hasattr(driver, 'get_robot_instance') else None
        if robot_instance is None:
            self.logger.warning(f"[RECOVERY] Robot instance None for {self.robot_id}")
            return (False, "Robot not connected")

        try:
            status = await driver.get_status()
            if not status.get("connected", False):
                self.logger.warning(f"[RECOVERY] Robot not connected for {self.robot_id}")
                return (False, "Robot not connected")
        except Exception as e:
            self.logger.warning(f"[RECOVERY] Connection check failed: {e}")
            return (False, str(e))

        return (True, None)
