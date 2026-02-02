"""
Recovery operations for Mecademic robot.

Handles all recovery-related operations including:
- Enable/disable recovery mode
- Quick recovery after emergency stop
- Safe homing at reduced speed
- Move to safe position in recovery mode
"""

import asyncio
import time
from typing import Dict, Any, Optional

from core.async_robot_wrapper import AsyncRobotWrapper
from core.state_manager import AtomicStateManager, RobotState
from core.exceptions import HardwareError, ValidationError
from core.settings import RoboticsSettings
from utils.logger import get_logger


class MecaRecoveryOperations:
    """
    Recovery operations for Mecademic robot.

    Provides methods for recovering from emergency stops, enabling
    recovery mode for manual repositioning, and safe homing.
    """

    def __init__(
        self,
        robot_id: str,
        settings: RoboticsSettings,
        robot_config: Dict[str, Any],
        async_wrapper: AsyncRobotWrapper,
        state_manager: AtomicStateManager,
        connection_manager: Any,
        broadcaster_callback=None
    ):
        """
        Initialize recovery operations.

        Args:
            robot_id: Robot identifier
            settings: Robotics settings
            robot_config: Robot configuration
            async_wrapper: AsyncRobotWrapper for robot communication
            state_manager: AtomicStateManager for state tracking
            connection_manager: MecaConnectionManager for reconnection
            broadcaster_callback: Optional callback for broadcasting messages
        """
        self.robot_id = robot_id
        self.settings = settings
        self.robot_config = robot_config
        self.async_wrapper = async_wrapper
        self.state_manager = state_manager
        self.connection_manager = connection_manager
        self.broadcaster_callback = broadcaster_callback
        self.logger = get_logger("meca_recovery_operations")

        # Safe homing state
        self._safe_homing_active = False
        self._safe_homing_stop_requested = False

    @property
    def safe_homing_active(self) -> bool:
        """Check if safe homing is currently in progress."""
        return self._safe_homing_active

    @property
    def safe_homing_stopped(self) -> bool:
        """Check if safe homing is stopped (paused mid-movement)."""
        return self._safe_homing_stop_requested

    async def enable_recovery_mode(self) -> Dict[str, Any]:
        """
        Enable recovery mode for safe robot repositioning after emergency stop.

        Recovery mode allows slow movement without homing and without joint limits,
        which is critical for repositioning a robot that may be in an unsafe position.

        WARNING: Joint limits are disabled in recovery mode. The robot can move to
        positions that may cause damage. Use with extreme caution.

        Returns:
            Dictionary containing recovery mode status
        """
        self.logger.warning(f"[WARNING] ENABLING RECOVERY MODE for {self.robot_id} - Joint limits will be DISABLED")

        driver = self.async_wrapper.robot_driver

        if not hasattr(driver, 'set_recovery_mode'):
            raise HardwareError(
                "Recovery mode not supported by driver",
                robot_id=self.robot_id
            )

        # Step 0: CHECK CONNECTION FIRST
        self.logger.info(f"[RECOVERY] Checking connection for recovery mode")
        is_connected, conn_error = await self.connection_manager.ensure_connection_for_recovery()

        if not is_connected:
            self.logger.warning(f"[RECOVERY] Robot disconnected, forcing reconnection: {conn_error}")
            reconnected = False
            for attempt in range(2):
                self.logger.info(f"[RECOVERY] Force reconnect attempt {attempt + 1}")
                if hasattr(driver, 'force_reconnect'):
                    reconnected = await driver.force_reconnect()
                if reconnected:
                    self.logger.info(f"[RECOVERY] Reconnected successfully")
                    break
                await asyncio.sleep(3.0)

            if not reconnected:
                raise HardwareError(
                    f"Could not reconnect to robot {self.robot_id}. Try power cycling the robot.",
                    robot_id=self.robot_id
                )

        # Check if robot instance exists
        robot_instance = None
        if hasattr(driver, 'get_robot_instance'):
            robot_instance = driver.get_robot_instance()

        # Strategy 1: Try direct SetRecoveryMode if robot instance exists
        if robot_instance is not None:
            try:
                self.logger.info(f"Attempting direct recovery mode for {self.robot_id}")
                if hasattr(driver, 'prepare_for_recovery_mode'):
                    await driver.prepare_for_recovery_mode()
                success = await driver.set_recovery_mode(True)
                if success:
                    await self.state_manager.update_robot_state(
                        self.robot_id,
                        RobotState.MAINTENANCE,
                        reason="Recovery mode enabled - manual repositioning available"
                    )
                    return {
                        "recovery_mode": True,
                        "robot_id": self.robot_id,
                        "state": "maintenance",
                        "warning": "Joint limits are DISABLED. Move robot carefully with reduced speed.",
                        "max_speed_percent": 20
                    }
                self.logger.warning(f"Direct recovery mode returned False for {self.robot_id}")
            except ConnectionError as conn_err:
                self.logger.warning(f"Socket dead during direct recovery mode: {conn_err}")
            except Exception as direct_err:
                self.logger.warning(f"Direct recovery mode failed: {direct_err}")

        # Strategy 1.5: Try to reset error state before force reconnection
        self.logger.info(f"Attempting to reset error state for {self.robot_id}")
        try:
            if hasattr(driver, 'reset_error'):
                await driver.reset_error()
                self.logger.info(f"Error state reset for {self.robot_id}")
                await asyncio.sleep(1.0)
        except Exception as reset_err:
            self.logger.warning(f"Reset error failed (will try force reconnect): {reset_err}")

        # Strategy 2: Force full reconnection with Error 3001 handling
        self.logger.info(f"Attempting force reconnection for {self.robot_id}")
        reconnected = False
        max_reconnect_attempts = 2

        for attempt in range(max_reconnect_attempts):
            if hasattr(driver, 'force_reconnect'):
                reconnected = await driver.force_reconnect()
            else:
                try:
                    await self.connection_manager.attempt_recovery_reconnection()
                    reconnected = True
                except Exception:
                    reconnected = False

            if reconnected:
                break

            if attempt < max_reconnect_attempts - 1:
                self.logger.warning(f"Reconnection attempt {attempt + 1} failed, waiting 5s...")
                await asyncio.sleep(5.0)

        if not reconnected:
            raise HardwareError(
                f"Cannot connect to robot {self.robot_id}. "
                "After software E-stop, try: "
                "1) Wait 10 seconds for robot to settle, "
                "2) Click 'Reset & Reconnect' button if available, "
                "3) If still failing, power cycle the robot.",
                robot_id=self.robot_id
            )

        # Verify connection was successful
        if hasattr(driver, 'get_robot_instance'):
            robot_instance = driver.get_robot_instance()
            if robot_instance is None:
                raise HardwareError(
                    f"Failed to reconnect to robot {self.robot_id}. "
                    "Please check the robot connection and try again.",
                    robot_id=self.robot_id
                )

        # Now try recovery mode on fresh connection
        if hasattr(driver, 'prepare_for_recovery_mode'):
            await driver.prepare_for_recovery_mode()
        success = await driver.set_recovery_mode(True)

        if success:
            await self.state_manager.update_robot_state(
                self.robot_id,
                RobotState.MAINTENANCE,
                reason="Recovery mode enabled - manual repositioning available"
            )
            return {
                "recovery_mode": True,
                "robot_id": self.robot_id,
                "state": "maintenance",
                "warning": "Joint limits are DISABLED. Move robot carefully with reduced speed.",
                "max_speed_percent": 20
            }
        else:
            raise HardwareError(
                f"Failed to enable recovery mode for {self.robot_id}. "
                "The robot may still be in error state. "
                "Try: 1) Reset errors first, 2) Power cycle if needed.",
                robot_id=self.robot_id
            )

    async def disable_recovery_mode(self) -> Dict[str, Any]:
        """
        Disable recovery mode after robot has been repositioned.

        Call this after the robot has been moved to a safe position to
        re-enable normal joint limits and safety features.

        Returns:
            Dictionary containing recovery mode status
        """
        self.logger.info(f"Disabling recovery mode for {self.robot_id}")

        driver = self.async_wrapper.robot_driver

        if not hasattr(driver, 'set_recovery_mode'):
            raise HardwareError(
                "Recovery mode not supported by driver",
                robot_id=self.robot_id
            )

        success = await driver.set_recovery_mode(False)

        if success:
            await self.state_manager.update_robot_state(
                self.robot_id,
                RobotState.IDLE,
                reason="Recovery mode disabled - normal operation available"
            )
            return {
                "recovery_mode": False,
                "robot_id": self.robot_id,
                "state": "idle",
                "message": "Recovery mode disabled. Joint limits restored."
            }
        else:
            is_connected = driver._connected if hasattr(driver, '_connected') else False
            self.logger.error(f"Failed to disable recovery mode for {self.robot_id}")
            return {
                "recovery_mode": True,
                "robot_id": self.robot_id,
                "success": False,
                "state": "unknown",
                "connected": is_connected,
                "error": "Failed to disable recovery mode. Try Reset & Reconnect."
            }

    async def get_recovery_status(self) -> Dict[str, Any]:
        """
        Get current recovery status with available actions.

        Returns comprehensive status including whether recovery actions are
        available and what the recommended recovery workflow is.

        Returns:
            Dictionary containing recovery status and available actions
        """
        driver = self.async_wrapper.robot_driver

        # Get safety status from driver
        safety_status = {}
        if hasattr(driver, 'get_safety_status'):
            safety_status = await driver.get_safety_status()

        # Get current robot state
        current_state = await self.state_manager.get_robot_state(self.robot_id)

        # Determine available actions based on state
        available_actions = []
        recommended_workflow = []

        is_error = safety_status.get("error_status", False)
        is_e_stop = safety_status.get("e_stop_active", False)
        is_recovery_mode = safety_status.get("recovery_mode", False)
        is_connected = safety_status.get("is_connected", False)

        if is_error or is_e_stop or (current_state and current_state.current_state == RobotState.ERROR):
            if is_recovery_mode:
                available_actions = [
                    "move_to_safe_position",
                    "disable_recovery_mode",
                    "reset_and_reconnect"
                ]
                recommended_workflow = [
                    "1. Move robot to safe position using /recovery/move-to-safe",
                    "2. Disable recovery mode using /recovery/disable",
                    "3. Reset and reconnect using /recovery/reset-and-reconnect",
                    "4. Activate robot using /confirm-activation"
                ]
            else:
                available_actions = [
                    "enable_recovery_mode",
                    "reset_and_reconnect"
                ]
                recommended_workflow = [
                    "Option A (Quick Recovery):",
                    "  1. Call /recovery/reset-and-reconnect",
                    "  2. Call /confirm-activation",
                    "",
                    "Option B (Manual Recovery - if robot in unsafe position):",
                    "  1. Call /recovery/enable to enable recovery mode",
                    "  2. Call /recovery/move-to-safe to reposition robot",
                    "  3. Call /recovery/disable to disable recovery mode",
                    "  4. Call /recovery/reset-and-reconnect",
                    "  5. Call /confirm-activation"
                ]
        elif is_connected:
            available_actions = ["none_needed"]
            recommended_workflow = ["Robot is operational. No recovery needed."]
        else:
            available_actions = ["connect"]
            recommended_workflow = ["Robot not connected. Use /connect-safe to connect."]

        return {
            "robot_id": self.robot_id,
            "current_state": current_state.current_state.value if current_state else "unknown",
            "safety_status": safety_status,
            "recovery_mode_active": is_recovery_mode,
            "error_state": is_error,
            "e_stop_active": is_e_stop,
            "connected": is_connected,
            "available_actions": available_actions,
            "recommended_workflow": recommended_workflow
        }

    async def quick_recovery(self) -> Dict[str, Any]:
        """
        Quick recovery - clear robot error state and resume workflow.

        Simplified recovery sequence:
        1. Clear error state (ResetError)
        2. Resume motion (ResumeMotion)
        3. Restore speed settings from config
        4. Update state to BUSY/IDLE
        5. Signal orchestrator to resume workflow

        Returns:
            Dictionary with recovery status
        """
        driver = self.async_wrapper.robot_driver

        # Step 0: Check connection and activate if needed (NO force_reconnect!)
        self.logger.info(f"Quick recovery Step 0: Checking connection for {self.robot_id}")
        try:
            if not driver._connected or not driver._robot:
                self.logger.warning(f"Connection lost, need full reconnect for {self.robot_id}")
                reconnect_result = await driver.force_reconnect()
                if not reconnect_result:
                    return {"error": "Failed to reconnect"}
            else:
                self.logger.info(f"Connection alive, ensuring robot is activated for {self.robot_id}")
                if hasattr(driver._robot, 'ActivateRobot'):
                    loop = asyncio.get_event_loop()
                    await loop.run_in_executor(driver._executor, driver._robot.ActivateRobot)
                    await asyncio.sleep(0.5)
                    self.logger.info(f"Robot activated for {self.robot_id}")
        except Exception as e:
            self.logger.warning(f"Connection check failed: {e}, trying full reconnect")
            reconnect_result = await driver.force_reconnect()
            if not reconnect_result:
                return {"error": f"Failed to reconnect: {e}"}

        # Step 1: Clear robot error state
        self.logger.info(f"Quick recovery Step 1: Clearing error state for {self.robot_id}")
        if hasattr(driver, 'reset_error'):
            try:
                await driver.reset_error()
                self.logger.info(f"Error state cleared for {self.robot_id}")
            except Exception as e:
                self.logger.warning(f"Could not clear error state: {e}")

        # Step 2: Resume motion if robot is paused
        self.logger.info(f"Quick recovery Step 2: Resuming motion for {self.robot_id}")
        try:
            await self._resume_motion_safe(driver)
        except Exception as e:
            self.logger.warning(f"Resume motion warning: {e}")

        # Step 2.5: Restore speed settings from config
        self.logger.info(f"Quick recovery Step 2.5: Restoring speed settings for {self.robot_id}")
        try:
            await self._restore_speed_settings(driver)
        except Exception as e:
            self.logger.warning(f"Could not restore speed settings: {e}")

        # Step 3: Get step state and update robot state
        step_state = await self.state_manager.get_step_state(self.robot_id)

        # Handle state transitions
        current_state_info = await self.state_manager.get_robot_state(self.robot_id)
        current_state = current_state_info.current_state if current_state_info else None

        # If in MAINTENANCE, go through IDLE first
        if current_state == RobotState.MAINTENANCE:
            self.logger.info(f"Transitioning {self.robot_id} from MAINTENANCE to IDLE first")
            await self.state_manager.update_robot_state(
                self.robot_id,
                RobotState.IDLE,
                reason="Exiting maintenance mode for recovery"
            )

        if step_state and step_state.paused:
            self.logger.info(
                f"Quick recovery for {self.robot_id}: resuming step {step_state.step_index} "
                f"({step_state.step_name})"
            )
            # NOTE: Do NOT call resume_step() here! The paused flag must remain True
            # until execute_pickup_sequence() reads it to determine is_resume.
            # execute_pickup_sequence() calls resume_step() at line 170 after checking
            # was_paused. Calling it here would clear the flag too early, causing
            # is_resume=False and the sequence to restart from the beginning instead
            # of resuming from the exact command where it was paused.

            await self.state_manager.update_robot_state(
                self.robot_id,
                RobotState.BUSY,
                reason="Quick recovery - resuming workflow"
            )

            # Step 4: Signal orchestrator to resume
            self.logger.info(f"Quick recovery Step 4: Signaling orchestrator to resume")
            try:
                from dependencies import get_orchestrator
                orchestrator = await get_orchestrator()
                await orchestrator.resume_all_operations()
                self.logger.info(f"Orchestrator resumed for {self.robot_id}")

                if self.broadcaster_callback:
                    await self.broadcaster_callback("workflow_resumed", {
                        "robot_id": self.robot_id,
                        "step_index": step_state.step_index,
                        "resumed_from": "quick_recovery"
                    })
            except Exception as resume_error:
                self.logger.warning(f"Failed to resume orchestrator: {resume_error}")

            return {
                "robot_id": self.robot_id,
                "recovery_type": "quick",
                "resumed_step": {
                    "index": step_state.step_index,
                    "name": step_state.step_name
                },
                "message": f"Resuming from step {step_state.step_index}: {step_state.step_name}"
            }

        # No paused workflow - recover robot
        # Check current state to avoid invalid transition from DISCONNECTED
        self.logger.info(f"Quick recovery for {self.robot_id}: no paused workflow, clearing errors only")
        current_state_info = await self.state_manager.get_robot_state(self.robot_id)
        if current_state_info and current_state_info.current_state == RobotState.DISCONNECTED:
            self.logger.warning(f"Cannot transition to IDLE from DISCONNECTED - robot not connected")
            return {
                "robot_id": self.robot_id,
                "recovery_type": "quick",
                "resumed_step": None,
                "error": "Robot disconnected - connect first",
                "message": "Robot not connected - use connect_safe first"
            }

        await self.state_manager.update_robot_state(
            self.robot_id,
            RobotState.IDLE,
            reason="Quick recovery - robot ready"
        )

        return {
            "robot_id": self.robot_id,
            "recovery_type": "quick",
            "resumed_step": None,
            "message": "Robot recovered - ready for new commands"
        }

    async def _resume_motion_safe(self, driver) -> None:
        """
        Resume motion with proper error handling.

        Args:
            driver: Robot driver instance
        """
        if hasattr(driver._robot, 'ResumeMotion'):
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(driver._executor, driver._robot.ResumeMotion)
            self.logger.info(f"Motion resumed for {self.robot_id}")

    async def _restore_speed_settings(self, driver) -> None:
        """
        Restore speed settings from config after recovery.

        This ensures the robot uses the correct speed values from settings,
        not fallback defaults. Critical for maintaining consistent operation
        speed after E-stop recovery.

        Args:
            driver: Robot driver instance
        """
        movement_params = self.robot_config.get("movement_params", {})

        # Get normal operational speed (not align_speed which is for slow/safe movements)
        # align_speed (20%) is only for recovery mode movements, not normal operation
        normal_speed = movement_params.get("speed", 35.0)
        force = movement_params.get("force", 100)
        acceleration = movement_params.get("acceleration", 50)

        self.logger.info(
            f"[SPEED RESTORE] Restoring speed settings: speed={normal_speed}%, "
            f"force={force}, acceleration={acceleration}"
        )

        if hasattr(driver, '_robot') and driver._robot:
            loop = asyncio.get_event_loop()

            # Restore gripper force
            if hasattr(driver._robot, 'SetGripperForce'):
                await loop.run_in_executor(driver._executor, driver._robot.SetGripperForce, force)
                self.logger.debug(f"Gripper force restored to {force}")

            # Restore acceleration
            if hasattr(driver._robot, 'SetJointAcc'):
                await loop.run_in_executor(driver._executor, driver._robot.SetJointAcc, acceleration)
                self.logger.debug(f"Joint acceleration restored to {acceleration}")

            # Restore normal operational speed (NOT align_speed)
            if hasattr(driver._robot, 'SetJointVel'):
                await loop.run_in_executor(driver._executor, driver._robot.SetJointVel, normal_speed)
                self.logger.info(f"Joint velocity restored to {normal_speed}%")

    async def reset_errors_and_reconnect(self) -> Dict[str, Any]:
        """
        Full recovery sequence: reset errors, reconnect, and prepare for activation.

        This performs the complete recovery workflow in one step:
        1. Reset any error states
        2. Attempt to reconnect if needed
        3. Prepare robot for activation

        Returns:
            Dictionary containing recovery status
        """
        self.logger.info(f"[RECOVERY] Starting recovery sequence for {self.robot_id}")
        recovery_steps = []

        driver = self.async_wrapper.robot_driver

        # Step 0: CHECK CONNECTION FIRST
        self.logger.info(f"[RECOVERY] Step 0: Checking connection for {self.robot_id}")
        is_connected, conn_error = await self.connection_manager.ensure_connection_for_recovery()

        if not is_connected:
            self.logger.warning(f"[RECOVERY] Robot disconnected, forcing reconnection: {conn_error}")
            recovery_steps.append({"step": "connection_check", "connected": False})

            reconnected = False
            for attempt in range(2):
                self.logger.info(f"[RECOVERY] Force reconnect attempt {attempt + 1}")
                if hasattr(driver, 'force_reconnect'):
                    reconnected = await driver.force_reconnect()
                if reconnected:
                    self.logger.info(f"[RECOVERY] Reconnected successfully")
                    break
                await asyncio.sleep(3.0)

            recovery_steps.append({"step": "force_reconnect", "success": reconnected})

            if not reconnected:
                return {
                    "robot_id": self.robot_id,
                    "recovery_success": False,
                    "recovery_steps": recovery_steps,
                    "error": "Could not reconnect. Try power cycling the robot."
                }
        else:
            recovery_steps.append({"step": "connection_check", "connected": True})

        # Step 1: Reset errors
        self.logger.info(f"[RECOVERY] Step 1: Resetting errors for {self.robot_id}")
        if hasattr(driver, 'reset_error'):
            try:
                error_reset_success = await driver.reset_error()
                recovery_steps.append({"step": "reset_errors", "success": error_reset_success})
                await asyncio.sleep(1.0)
            except Exception as e:
                self.logger.warning(f"Error reset failed: {e}")
                recovery_steps.append({"step": "reset_errors", "success": False, "error": str(e)})

        # Step 2: Check connection and reconnect if needed
        self.logger.info(f"Step 2: Checking connection for {self.robot_id}")
        try:
            status = await driver.get_status()
            is_connected = status.get("connected", False)
            recovery_steps.append({"step": "check_connection", "connected": is_connected})

            if not is_connected:
                self.logger.info(f"Step 2b: Reconnecting {self.robot_id}")
                reconnect_success = await driver.connect()
                recovery_steps.append({"step": "reconnect", "success": reconnect_success})

                if reconnect_success:
                    await self._attempt_activation_during_recovery(driver, recovery_steps)
        except Exception as e:
            self.logger.warning(f"Connection check/reconnect failed: {e}")
            recovery_steps.append({"step": "connection", "success": False, "error": str(e)})

        # Step 3: Get final status
        return await self._finalize_recovery(driver, recovery_steps)

    async def _attempt_activation_during_recovery(self, driver, recovery_steps: list) -> None:
        """Attempt activation during recovery sequence."""
        self.logger.info(f"Step 2c: Verifying activation for {self.robot_id}")
        try:
            activation_status = await driver.get_status()
            is_activated = activation_status.get("activation_status", False)
            is_homed = activation_status.get("homing_status", False)

            if not is_activated:
                self.logger.info(f"Robot not activated, attempting activation...")
                if hasattr(driver, '_robot') and driver._robot:
                    loop = asyncio.get_event_loop()
                    if hasattr(driver._robot, 'ActivateRobot'):
                        await loop.run_in_executor(driver._executor, driver._robot.ActivateRobot)
                        await asyncio.sleep(2.0)
                        self.logger.info(f"Activation command sent for {self.robot_id}")

            if not is_homed:
                self.logger.info(f"Robot not homed, attempting homing...")
                if hasattr(driver, '_robot') and driver._robot:
                    loop = asyncio.get_event_loop()
                    if hasattr(driver._robot, 'Home'):
                        await loop.run_in_executor(driver._executor, driver._robot.Home)
                        await asyncio.sleep(5.0)
                        self.logger.info(f"Homing command sent for {self.robot_id}")

            final_activation = await driver.get_status()
            recovery_steps.append({
                "step": "activation",
                "activated": final_activation.get("activation_status", False),
                "homed": final_activation.get("homing_status", False)
            })
        except Exception as activation_err:
            self.logger.error(f"Activation failed during recovery: {activation_err}")
            recovery_steps.append({
                "step": "activation",
                "success": False,
                "error": str(activation_err)
            })

    async def _finalize_recovery(self, driver, recovery_steps: list) -> Dict[str, Any]:
        """Finalize recovery and return status."""
        self.logger.info(f"Step 3: Getting final status for {self.robot_id}")
        recovery_success = False

        try:
            final_status = await driver.get_status()
            safety_status = {}
            if hasattr(driver, 'get_safety_status'):
                safety_status = await driver.get_safety_status()

            recovery_steps.append({
                "step": "final_status",
                "status": final_status,
                "safety": safety_status
            })

            if final_status.get("connected", False) and not safety_status.get("error_status", True):
                await self.state_manager.update_robot_state(
                    self.robot_id,
                    RobotState.IDLE,
                    reason="Recovery complete - awaiting activation"
                )
                recovery_success = True

                # Resume workflow from paused step
                try:
                    from dependencies import get_orchestrator
                    orchestrator = await get_orchestrator()

                    step_state = await orchestrator.state_manager.get_step_state(self.robot_id)
                    if step_state and step_state.paused:
                        await orchestrator.state_manager.resume_step(self.robot_id)
                        await orchestrator.resume_all_operations()
                        self.logger.info(f"Workflow resumed from step {step_state.step_index}")

                        if self.broadcaster_callback:
                            await self.broadcaster_callback("workflow_resumed", {
                                "robot_id": self.robot_id,
                                "step_index": step_state.step_index,
                                "resumed_from": "quick_recovery"
                            })
                        recovery_steps.append({
                            "step": "workflow_resumed",
                            "step_index": step_state.step_index,
                            "success": True
                        })
                except Exception as resume_error:
                    self.logger.warning(f"Failed to resume workflow: {resume_error}")
                    recovery_steps.append({
                        "step": "workflow_resume",
                        "success": False,
                        "error": str(resume_error)
                    })
            else:
                await self.state_manager.update_robot_state(
                    self.robot_id,
                    RobotState.ERROR,
                    reason="Recovery incomplete - manual intervention may be required"
                )

        except Exception as e:
            self.logger.error(f"Final status check failed: {e}")
            recovery_steps.append({"step": "final_status", "success": False, "error": str(e)})

        self.logger.info(f"Recovery sequence completed for {self.robot_id}: success={recovery_success}")

        return {
            "robot_id": self.robot_id,
            "recovery_success": recovery_success,
            "steps": recovery_steps,
            "next_action": "/confirm-activation" if recovery_success else "Check recovery status",
            "message": "Recovery complete. Call /confirm-activation to activate." if recovery_success else "Recovery incomplete."
        }

    async def move_to_safe_position_recovery(self, speed_percent: float = 10.0) -> Dict[str, Any]:
        """
        Move robot to safe position while in recovery mode.

        Uses very slow movement to safely reposition the robot when it's
        in an unknown or unsafe position after an emergency stop.

        Args:
            speed_percent: Movement speed as percentage (max 20% in recovery mode)

        Returns:
            Dictionary containing movement status
        """
        max_recovery_speed = 20.0
        if speed_percent > max_recovery_speed:
            self.logger.warning(f"Speed {speed_percent}% exceeds limit. Clamping to {max_recovery_speed}%")
            speed_percent = max_recovery_speed

        driver = self.async_wrapper.robot_driver

        # Verify recovery mode is active
        if hasattr(driver, 'get_safety_status'):
            safety_status = await driver.get_safety_status()
            if not safety_status.get("recovery_mode", False):
                return {
                    "success": False,
                    "recovery_mode": False,
                    "recovery_mode_active": False,
                    "connected": safety_status.get("is_connected", False),
                    "current_state": "error",
                    "error": "Recovery mode not active. Please re-enable recovery mode."
                }

        self.logger.warning(f"[WARNING] RECOVERY MOVEMENT for {self.robot_id} at {speed_percent}% speed")

        # Define safe home position
        safe_joints = self.robot_config.get("safe_joint_angles", [0, 0, 0, 0, 0, 0])

        # Set very slow speed for recovery
        original_speed = driver.speed if hasattr(driver, 'speed') else 100.0

        try:
            if hasattr(driver, '_robot') and driver._robot:
                loop = asyncio.get_event_loop()
                if hasattr(driver._robot, 'SetJointVel'):
                    await loop.run_in_executor(driver._executor, driver._robot.SetJointVel, speed_percent)
                    self.logger.info(f"Set recovery speed to {speed_percent}%")

            # Move to safe position using joint movement
            if hasattr(driver, '_robot') and driver._robot and hasattr(driver._robot, 'MoveJoints'):
                loop = asyncio.get_event_loop()
                self.logger.info(f"Moving to safe joint position: {safe_joints}")

                await loop.run_in_executor(driver._executor, driver._robot.MoveJoints, *safe_joints)

                if hasattr(driver, 'wait_idle'):
                    await driver.wait_idle(timeout=60.0)

                self.logger.info(f"[OK] Recovery movement complete for {self.robot_id}")

                return {
                    "robot_id": self.robot_id,
                    "movement_complete": True,
                    "target_position": safe_joints,
                    "speed_used": speed_percent,
                    "message": "Robot moved to safe position. You can now disable recovery mode."
                }
            else:
                raise HardwareError("MoveJoints not available for recovery movement", robot_id=self.robot_id)

        finally:
            try:
                if hasattr(driver, '_robot') and driver._robot and hasattr(driver._robot, 'SetJointVel'):
                    loop = asyncio.get_event_loop()
                    await loop.run_in_executor(driver._executor, driver._robot.SetJointVel, original_speed)
            except Exception as e:
                self.logger.warning(f"Could not restore original speed: {e}")

    async def start_safe_homing(self, speed_percent: int = 20) -> Dict[str, Any]:
        """
        Start safe homing at reduced speed with automatic recovery mode handling.

        This method follows the Mecademic SDK official recovery sequence:
        1. Enable recovery mode
        2. Move to safe home position at reduced speed
        3. Disable recovery mode
        4. Home the robot

        Args:
            speed_percent: Movement speed percentage (max 20% enforced)

        Returns:
            Dictionary with homing status
        """
        if speed_percent > 20:
            self.logger.warning(f"Speed {speed_percent}% clamped to 20% for safe homing")
            speed_percent = 20

        if self._safe_homing_active:
            raise ValidationError("Safe homing already in progress")

        self._safe_homing_active = True
        self._safe_homing_stop_requested = False

        self.logger.info(f"Starting safe homing for {self.robot_id} at {speed_percent}% speed")

        try:
            # Step 1: Enable recovery mode
            self.logger.info(f"Step 1: Enabling recovery mode for {self.robot_id}")
            enable_result = await self.enable_recovery_mode()
            if not enable_result.get("recovery_mode"):
                return {
                    "robot_id": self.robot_id,
                    "status": "failed",
                    "error": f"Failed to enable recovery mode",
                    "stopped": False
                }

            # Step 2: Move to safe position
            self.logger.info(f"Step 2: Moving to safe position at {speed_percent}% speed")
            move_result = await self.move_to_safe_position_recovery(speed_percent)

            # Step 3: Disable recovery mode
            self.logger.info(f"Step 3: Disabling recovery mode for {self.robot_id}")
            await self.disable_recovery_mode()

            if not move_result.get("movement_complete"):
                return {
                    "robot_id": self.robot_id,
                    "status": "failed",
                    "error": move_result.get("error"),
                    "stopped": self._safe_homing_stop_requested
                }

            # Step 4: Home the robot
            self.logger.info(f"Step 4: Homing robot {self.robot_id}")
            try:
                await self._home_robot_with_retry()
                self.logger.info(f"Robot {self.robot_id} homed successfully")
            except Exception as home_error:
                self.logger.warning(f"Homing failed (robot is safe): {home_error}")

            # Step 5: Restore normal speed after safe homing completes
            self.logger.info(f"Step 5: Restoring normal speed for {self.robot_id}")
            driver = self.async_wrapper.robot_driver
            try:
                await self._restore_speed_settings(driver)
            except Exception as speed_error:
                self.logger.warning(f"Could not restore speed after safe homing: {speed_error}")

            return {
                "robot_id": self.robot_id,
                "status": "completed",
                "speed_percent": speed_percent,
                "stopped": self._safe_homing_stop_requested,
                "message": "Safe homing completed successfully"
            }

        finally:
            self._safe_homing_active = False

    async def _home_robot_with_retry(self, max_retries: int = 2) -> None:
        """
        Home robot with retry logic.

        Args:
            max_retries: Maximum retry attempts
        """
        driver = self.async_wrapper.robot_driver
        last_error = None

        for attempt in range(max_retries):
            try:
                await driver.home_robot()
                await driver.wait_homed(timeout=30.0)
                return
            except Exception as e:
                last_error = e
                self.logger.warning(f"Homing attempt {attempt + 1} failed: {e}")
                await asyncio.sleep(1.0)

        raise HardwareError(f"Homing failed after {max_retries} attempts: {last_error}", robot_id=self.robot_id)

    async def stop_safe_homing(self) -> Dict[str, Any]:
        """
        Stop safe homing in progress - robot holds position.

        Returns:
            Dictionary with stop status
        """
        if not self._safe_homing_active:
            return {
                "robot_id": self.robot_id,
                "status": "not_active",
                "message": "No safe homing in progress"
            }

        self._safe_homing_stop_requested = True
        self.logger.warning(f"Stop requested for safe homing on {self.robot_id}")

        driver = self.async_wrapper.robot_driver
        if hasattr(driver, '_robot') and driver._robot:
            try:
                loop = asyncio.get_event_loop()
                if hasattr(driver._robot, 'PauseMotion'):
                    await loop.run_in_executor(driver._executor, driver._robot.PauseMotion)
                    self.logger.info(f"Motion paused for {self.robot_id}")
            except Exception as e:
                self.logger.error(f"Error pausing motion: {e}")
                raise HardwareError(f"Failed to pause motion: {e}", robot_id=self.robot_id)

        return {
            "robot_id": self.robot_id,
            "status": "stopped",
            "message": "Robot holding position - use resume_safe_homing to continue"
        }

    async def resume_safe_homing(self) -> Dict[str, Any]:
        """
        Resume safe homing from current position.

        Returns:
            Dictionary with resume status
        """
        if not self._safe_homing_stop_requested:
            return {
                "robot_id": self.robot_id,
                "status": "not_stopped",
                "message": "Safe homing was not stopped - nothing to resume"
            }

        self._safe_homing_stop_requested = False
        self.logger.info(f"Resuming safe homing for {self.robot_id}")

        driver = self.async_wrapper.robot_driver
        if hasattr(driver, '_robot') and driver._robot:
            try:
                loop = asyncio.get_event_loop()
                if hasattr(driver._robot, 'ResumeMotion'):
                    await loop.run_in_executor(driver._executor, driver._robot.ResumeMotion)
                    self.logger.info(f"Motion resumed for {self.robot_id}")
            except Exception as e:
                self.logger.error(f"Error resuming motion: {e}")
                raise HardwareError(f"Failed to resume motion: {e}", robot_id=self.robot_id)

        # Continue to home from current position
        self._safe_homing_active = True
        try:
            result = await self.move_to_safe_position_recovery(speed_percent=20)

            if result.get("movement_complete"):
                return {
                    "robot_id": self.robot_id,
                    "status": "completed",
                    "message": "Safe homing resumed and completed"
                }
            else:
                return {
                    "robot_id": self.robot_id,
                    "status": "failed",
                    "error": result.get("error")
                }

        finally:
            self._safe_homing_active = False
