"""
Wafer sequence operations for Mecademic robot.

Handles all wafer handling sequences including:
- Pickup sequences from inert tray to spreader
- Drop sequences from spreader to baking tray
- Carousel sequences (to and from carousel)
"""

import asyncio
import copy
from typing import Dict, List, Any, Optional

from core.async_robot_wrapper import AsyncRobotWrapper
from core.state_manager import AtomicStateManager, RobotState
from core.exceptions import HardwareError
from services.base import ServiceResult
from utils.logger import get_logger

from .position_calculator import MecaPositionCalculator
from .movement_executor import MecaMovementExecutor


class MecaWaferSequences:
    """
    Executes wafer handling sequences for Mecademic robot.

    Provides methods for pickup, drop, and carousel sequences
    with proper state tracking and error handling.
    """

    def __init__(
        self,
        robot_id: str,
        robot_config: Dict[str, Any],
        async_wrapper: AsyncRobotWrapper,
        state_manager: AtomicStateManager,
        position_calculator: MecaPositionCalculator,
        movement_executor: MecaMovementExecutor,
        broadcaster_callback=None
    ):
        """
        Initialize wafer sequences.

        Args:
            robot_id: Robot identifier
            robot_config: Robot configuration
            async_wrapper: AsyncRobotWrapper for robot communication
            state_manager: AtomicStateManager for state tracking
            position_calculator: MecaPositionCalculator for position calculations
            movement_executor: MecaMovementExecutor for movement commands
            broadcaster_callback: Optional callback for broadcasting messages
        """
        self.robot_id = robot_id
        self.robot_config = robot_config
        self.async_wrapper = async_wrapper
        self.state_manager = state_manager
        self.position_calculator = position_calculator
        self.movement_executor = movement_executor
        self.broadcaster_callback = broadcaster_callback
        self.logger = get_logger("meca_wafer_sequences")

        # Speed settings from config (defaults match original meca_service.py values)
        movement_params = robot_config.get("movement_params", {})
        self.FORCE = movement_params.get("force", 100)
        self.ACC = movement_params.get("acceleration", 50)
        self.WAFER_SPEED = movement_params.get("wafer_speed", 35)
        self.SPEED = movement_params.get("speed", 35)
        self.ALIGN_SPEED = movement_params.get("align_speed", 20)
        self.ENTRY_SPEED = movement_params.get("entry_speed", 15)
        self.EMPTY_SPEED = movement_params.get("empty_speed", 50)
        self.SPREAD_WAIT = movement_params.get("spread_wait", 25)

        # Log speed settings for diagnostics
        self.logger.info(
            f"[WAFER SEQ SPEED] Speed settings: WAFER={self.WAFER_SPEED}, "
            f"SPEED={self.SPEED}, ALIGN={self.ALIGN_SPEED}, ENTRY={self.ENTRY_SPEED}, "
            f"EMPTY={self.EMPTY_SPEED}"
        )

        # Resume task reference
        self._resume_task: Optional[asyncio.Task] = None

    async def _execute_command(self, command_type: str, parameters: List[Any] = None) -> None:
        """Execute movement command through the movement executor."""
        await self.movement_executor.execute_movement_command(command_type, parameters)

    async def _broadcast_wafer_progress(
        self,
        operation: str,
        wafer_num: int,
        index: int,
        start: int,
        count: int
    ) -> None:
        """Broadcast wafer progress message."""
        if self.broadcaster_callback:
            await self.broadcaster_callback("wafer_progress", {
                "robot_id": self.robot_id,
                "operation": operation,
                "wafer_num": wafer_num,
                "wafer_index": index,
                "start": start,
                "count": count,
                "progress": ((index - start + 1) / count) * 100
            })

    async def _broadcast_batch_completion(
        self,
        operation_type: str,
        start: int,
        count: int,
        result: Dict[str, Any]
    ) -> bool:
        """Broadcast batch completion message."""
        if self.broadcaster_callback:
            try:
                await self.broadcaster_callback("batch_completion", {
                    "robot_id": self.robot_id,
                    "operation_type": operation_type,
                    "start": start,
                    "count": count,
                    "result": result
                })
                return True
            except Exception as e:
                self.logger.warning(f"Failed to broadcast batch completion: {e}")
                return False
        return False

    async def execute_pickup_sequence(
        self, start: int, count: int, retry_wafers: Optional[List[int]] = None
    ) -> Dict[str, Any]:
        """
        Execute wafer pickup sequence from inert tray to spreader.

        Supports true mid-resume: if interrupted mid-wafer, resumes from the exact
        command position (not restarting the wafer).

        Args:
            start: Starting wafer index (0-based)
            count: Number of wafers to process
            retry_wafers: Optional list of specific wafer indices to retry

        Returns:
            Dictionary with sequence results
        """
        # Start step tracking
        # Capture paused state BEFORE calling resume_step() - needed for is_resume calculation
        existing_step = await self.state_manager.get_step_state(self.robot_id)
        was_paused = existing_step is not None and existing_step.paused

        if not existing_step:
            # No existing step - create new one
            await self.state_manager.start_step(
                robot_id=self.robot_id,
                step_index=5,
                step_name="Pick up wafers from Inert Tray",
                operation_type="pickup_sequence",
                progress_data={
                    "start": start,
                    "count": count,
                    "current_wafer_index": start,
                    "current_command_index": 0,
                    "last_command": None
                }
            )
        elif existing_step.paused:
            # Step exists but is paused - resume it (preserves progress_data)
            await self.state_manager.resume_step(self.robot_id)
            self.logger.info(
                f"Resumed paused pickup sequence from wafer {existing_step.progress_data.get('current_wafer_index', start)}"
            )

        self.logger.info(f"Starting pickup sequence for wafers {start+1} to {start+count}")

        # Determine resume state FIRST (before any robot commands)
        step_state = await self.state_manager.get_step_state(self.robot_id)
        resume_from_wafer = step_state.progress_data.get("current_wafer_index", 0) if step_state else 0
        resume_from_cmd = step_state.progress_data.get("current_command_index", 0) if step_state else 0
        # Include was_paused to handle edge case: resume from wafer 0, cmd 0 after emergency stop
        is_resume = was_paused or resume_from_wafer > start or resume_from_cmd > 0

        # Initial setup - apply ONLY on fresh start, NOT on resume
        # On resume, gripper may be holding a wafer - opening it would drop the wafer
        if not is_resume:
            await self._execute_command("SetGripperForce", [self.FORCE])
            await self._execute_command("SetJointAcc", [self.ACC])
            await self._execute_command("SetTorqueLimits", [40, 40, 40, 40, 40, 40])
            await self._execute_command("SetTorqueLimitsCfg", [2, 1])
            await self._execute_command("SetBlending", [0])
            await self._execute_command("SetJointVel", [self.ALIGN_SPEED])
            await self._execute_command("SetConf", [1, 1, 1])
            await self._execute_command("GripperOpen", [])
            await self._execute_command("Delay", [1])
        else:
            self.logger.info(
                f"[RESUME] Skipping initial setup - resuming from wafer {resume_from_wafer}, cmd {resume_from_cmd}"
            )

        processed_wafers = []
        failed_wafers = []

        # Use already-computed resume values for wafer indices
        wafer_indices = retry_wafers if retry_wafers else list(range(max(start, resume_from_wafer), start + count))

        self.logger.info(
            f"Resume state: wafer_index={resume_from_wafer}, cmd_index={resume_from_cmd}, "
            f"wafers_to_process={wafer_indices}"
        )

        for i in wafer_indices:
            wafer_num = i + 1

            # Handle pause
            if await self.state_manager.is_step_paused(self.robot_id):
                await self.state_manager.update_step_progress(
                    self.robot_id,
                    {"current_wafer_index": i, "total_wafers": count}
                )
                while await self.state_manager.is_step_paused(self.robot_id):
                    await asyncio.sleep(1.0)

            # Check emergency stop
            robot_info = await self.state_manager.get_robot_state(self.robot_id)
            if robot_info and robot_info.current_state == RobotState.EMERGENCY_STOP:
                self.logger.critical(f"Emergency stop - aborting at wafer {wafer_num}")
                break

            try:
                await self._broadcast_wafer_progress("pickup", wafer_num, i, start, count)
                self.logger.info(f"[WAFER {wafer_num}/{start+count}] Starting pickup from inert tray")

                positions = self.position_calculator.calculate_intermediate_positions(i, "pickup")
                pickup_position = self.position_calculator.calculate_wafer_position(i, "inert")

                # Build command list for this wafer
                commands = [
                    ("MovePose", positions["pickup_high"], "move_to_pickup_high"),
                    ("MovePose", pickup_position, "move_to_pickup"),
                    ("Delay", [1], "delay_before_grip"),
                    ("GripperClose", [], "grip_wafer"),
                    ("Delay", [1], "delay_after_grip"),
                    ("SetJointVel", [self.WAFER_SPEED], "set_wafer_speed"),
                    ("MovePose", positions["intermediate_1"], "move_intermediate_1"),
                    ("SetBlending", [100], "enable_blending"),
                    ("MovePose", positions["intermediate_2"], "move_intermediate_2"),
                    ("MoveLin", positions["intermediate_3"], "move_intermediate_3"),
                    ("SetBlending", [0], "disable_blending"),
                    ("MovePose", self.position_calculator.SAFE_POINT, "move_to_safe"),
                    ("SetJointVel", [self.ALIGN_SPEED], "set_align_speed"),
                    ("MovePose", positions["above_spreader"], "move_above_spreader"),
                    ("MovePose", positions["spreader"], "move_to_spreader"),
                    ("Delay", [1], "delay_before_release"),
                    ("GripperOpen", [], "release_wafer"),
                    ("Delay", [1], "delay_after_release"),
                    ("MovePose", positions["above_spreader_exit"], "exit_spreader"),
                    ("SetJointVel", [self.EMPTY_SPEED], "set_empty_speed"),
                    ("MovePose", self.position_calculator.SAFE_POINT, "return_to_safe"),
                ]

                # Determine command resume point for this wafer
                cmd_start = 0
                if i == resume_from_wafer and resume_from_cmd > 0:
                    cmd_start = resume_from_cmd
                    self.logger.info(
                        f"[MID-RESUME] Wafer {wafer_num}: resuming from command {cmd_start} "
                        f"(skipping {cmd_start} completed commands)"
                    )

                # Execute commands with tracking
                for cmd_idx, (cmd_type, params, cmd_name) in enumerate(commands):
                    # Skip completed commands on resume
                    if cmd_idx < cmd_start:
                        self.logger.debug(f"Skipping completed command {cmd_idx}: {cmd_name}")
                        continue

                    # Update progress before each command
                    await self.state_manager.update_step_progress(
                        self.robot_id,
                        {
                            "current_wafer_index": i,
                            "current_wafer_num": wafer_num,
                            "total_wafers": count,
                            "current_command_index": cmd_idx,
                            "last_command": cmd_name,
                            "total_commands": len(commands)
                        }
                    )

                    # Execute the command
                    await self._execute_command(cmd_type, params)
                    self.logger.debug(f"[WAFER {wafer_num}] Executed: {cmd_name} ({cmd_idx+1}/{len(commands)})")

                # Reset command index for next wafer
                resume_from_cmd = 0

                # Wait for robot to be idle
                await self.async_wrapper.wait_idle(timeout=60.0)
                await self.movement_executor.check_robot_status_after_motion(wafer_num)
                self.logger.info(f"[WAFER {wafer_num}/{start+count}] Pickup completed")

                # Spread wait every 5th wafer
                if (4 - (i % 5)) == 0:
                    await self._execute_command("Delay", [self.SPREAD_WAIT])

                processed_wafers.append(wafer_num)

                # Clear command tracking after successful wafer completion
                await self.state_manager.update_step_progress(
                    self.robot_id,
                    {
                        "current_wafer_index": i + 1,
                        "current_command_index": 0,
                        "last_command": None
                    }
                )

            except Exception as e:
                self.logger.error(f"Failed wafer {wafer_num}: {e}")
                failed_wafers.append({"wafer_num": wafer_num, "error": str(e)})
                raise

        # Calculate success rate
        total_attempted = len(retry_wafers) if retry_wafers else count
        success_rate = (len(processed_wafers) / total_attempted * 100) if total_attempted > 0 else 0

        result = {
            "status": "completed" if not failed_wafers else "partial_success",
            "wafers_processed": len(processed_wafers),
            "wafers_succeeded": processed_wafers,
            "wafers_failed": [fw["wafer_num"] for fw in failed_wafers],
            "start_wafer": start + 1,
            "end_wafer": start + count,
            "success_rate": f"{success_rate:.1f}%",
            "retry_mode": retry_wafers is not None
        }

        await self.state_manager.complete_step(self.robot_id)
        await self._broadcast_batch_completion("pickup", start, count, result)

        self.logger.info(f"Pickup sequence completed: {len(processed_wafers)}/{total_attempted} wafers")
        return result

    async def execute_drop_sequence(
        self, start: int, count: int, retry_wafers: Optional[List[int]] = None
    ) -> Dict[str, Any]:
        """
        Execute wafer drop sequence from spreader to baking tray.

        Supports true mid-resume: if interrupted mid-wafer, resumes from the exact
        command position (not restarting the wafer).

        Args:
            start: Starting wafer index (0-based)
            count: Number of wafers to process
            retry_wafers: Optional list of specific wafer indices to retry

        Returns:
            Dictionary with sequence results
        """
        existing_step = await self.state_manager.get_step_state(self.robot_id)
        if not existing_step:
            # No existing step - create new one
            await self.state_manager.start_step(
                robot_id=self.robot_id,
                step_index=7,
                step_name="Move to Baking Tray",
                operation_type="drop_sequence",
                progress_data={
                    "start": start,
                    "count": count,
                    "current_wafer_index": start,
                    "current_command_index": 0,
                    "last_command": None
                }
            )
        elif existing_step.paused:
            # Step exists but is paused - resume it (preserves progress_data)
            await self.state_manager.resume_step(self.robot_id)
            self.logger.info(
                f"Resumed paused drop sequence from wafer {existing_step.progress_data.get('current_wafer_index', start)}"
            )

        self.logger.info(f"Starting drop sequence for wafers {start+1} to {start+count}")

        processed_wafers = []
        failed_wafers = []

        # Determine starting point (wafer-level and command-level)
        step_state = await self.state_manager.get_step_state(self.robot_id)
        resume_from_wafer = step_state.progress_data.get("current_wafer_index", 0) if step_state else 0
        resume_from_cmd = step_state.progress_data.get("current_command_index", 0) if step_state else 0
        wafer_indices = retry_wafers if retry_wafers else list(range(max(start, resume_from_wafer), start + count))

        self.logger.info(
            f"Resume state: wafer_index={resume_from_wafer}, cmd_index={resume_from_cmd}, "
            f"wafers_to_process={wafer_indices}"
        )

        for i in wafer_indices:
            wafer_num = i + 1

            # Handle pause
            if await self.state_manager.is_step_paused(self.robot_id):
                await self.state_manager.update_step_progress(
                    self.robot_id,
                    {"current_wafer_index": i, "total_wafers": count}
                )
                while await self.state_manager.is_step_paused(self.robot_id):
                    await asyncio.sleep(1.0)

            try:
                await self._broadcast_wafer_progress("drop", wafer_num, i, start, count)
                self.logger.info(f"[WAFER {wafer_num}/{start+count}] Starting drop to baking tray")

                positions = self.position_calculator.calculate_intermediate_positions(i, "drop")

                # Build command list for this wafer
                commands = [
                    ("SetJointVel", [self.ALIGN_SPEED], "set_align_speed"),
                    ("MovePose", positions["above_spreader"], "move_above_spreader"),
                    ("Delay", [1], "delay_above_spreader"),
                    ("MovePose", positions["spreader"], "move_to_spreader"),
                    ("Delay", [1], "delay_at_spreader"),
                    ("GripperClose", [], "grip_wafer"),
                    ("Delay", [1], "delay_after_grip"),
                    ("MovePose", positions["above_spreader_pickup"], "move_up_from_spreader"),
                    ("SetJointVel", [self.SPEED], "set_travel_speed"),
                    ("MovePose", self.position_calculator.SAFE_POINT, "move_to_safe"),
                    ("MovePose", positions["baking_align1"], "move_baking_align1"),
                    ("SetJointVel", [self.ALIGN_SPEED], "set_align_speed_baking"),
                    ("SetBlending", [100], "enable_blending"),
                    ("MovePose", positions["baking_align2"], "move_baking_align2"),
                    ("MovePose", positions["baking_align3"], "move_baking_align3"),
                    ("MovePose", positions["baking_align4"], "move_baking_align4"),
                    ("Delay", [1], "delay_before_release"),
                    ("GripperOpen", [], "release_wafer"),
                    ("Delay", [0.5], "delay_after_release"),
                    ("MovePose", positions["baking_up"], "move_up_from_baking"),
                    ("SetJointVel", [self.SPEED], "set_return_speed"),
                    ("SetBlending", [0], "disable_blending"),
                    ("MovePose", self.position_calculator.SAFE_POINT, "return_to_safe"),
                ]

                # Determine command resume point for this wafer
                cmd_start = 0
                if i == resume_from_wafer and resume_from_cmd > 0:
                    cmd_start = resume_from_cmd
                    self.logger.info(
                        f"[MID-RESUME] Wafer {wafer_num}: resuming from command {cmd_start} "
                        f"(skipping {cmd_start} completed commands)"
                    )

                # Execute commands with tracking
                for cmd_idx, (cmd_type, params, cmd_name) in enumerate(commands):
                    # Skip completed commands on resume
                    if cmd_idx < cmd_start:
                        self.logger.debug(f"Skipping completed command {cmd_idx}: {cmd_name}")
                        continue

                    # Update progress before each command
                    await self.state_manager.update_step_progress(
                        self.robot_id,
                        {
                            "current_wafer_index": i,
                            "current_wafer_num": wafer_num,
                            "total_wafers": count,
                            "current_command_index": cmd_idx,
                            "last_command": cmd_name,
                            "total_commands": len(commands)
                        }
                    )

                    # Execute the command
                    await self._execute_command(cmd_type, params)
                    self.logger.debug(f"[WAFER {wafer_num}] Executed: {cmd_name} ({cmd_idx+1}/{len(commands)})")

                # Reset command index for next wafer
                resume_from_cmd = 0

                await self.async_wrapper.wait_idle(timeout=60.0)

                processed_wafers.append(wafer_num)
                self.logger.info(f"[WAFER {wafer_num}/{start+count}] Drop completed")

                # Clear command tracking after successful wafer completion
                await self.state_manager.update_step_progress(
                    self.robot_id,
                    {
                        "current_wafer_index": i + 1,
                        "current_command_index": 0,
                        "last_command": None
                    }
                )

            except Exception as e:
                self.logger.error(f"Failed wafer {wafer_num}: {e}")
                failed_wafers.append({"wafer_num": wafer_num, "error": str(e)})

                # Attempt recovery
                try:
                    await self._execute_command("SetJointVel", [self.SPEED])
                    await self._execute_command("MovePose", self.position_calculator.SAFE_POINT)
                    await self._execute_command("GripperOpen", [])
                except Exception as recovery_error:
                    raise HardwareError(f"Drop failed and recovery failed: {e}", robot_id=self.robot_id)

                continue

        total_attempted = len(retry_wafers) if retry_wafers else count
        success_rate = (len(processed_wafers) / total_attempted * 100) if total_attempted > 0 else 0

        result = {
            "status": "completed" if not failed_wafers else "partial_success",
            "wafers_processed": len(processed_wafers),
            "wafers_succeeded": processed_wafers,
            "wafers_failed": [fw["wafer_num"] for fw in failed_wafers],
            "start_wafer": start + 1,
            "end_wafer": start + count,
            "success_rate": f"{success_rate:.1f}%",
            "retry_mode": retry_wafers is not None
        }

        await self.state_manager.complete_step(self.robot_id)
        broadcast_success = await self._broadcast_batch_completion("drop", start, count, result)
        result["broadcast_sent"] = broadcast_success

        self.logger.info(f"Drop sequence completed for wafers {start+1} to {start+count}")
        return result

    async def execute_carousel_sequence(self, start: int, count: int) -> Dict[str, Any]:
        """
        Execute carousel sequence from baking tray to carousel.

        Args:
            start: Starting wafer index (0-based)
            count: Number of wafers to process (typically 11)

        Returns:
            Dictionary with sequence results
        """
        self.logger.info(f"Starting carousel sequence for wafers {start+1} to {start+count}")

        # Configuration specific to carousel movement
        await self._execute_command("SetConf", [1, 1, -1])
        await self._execute_command("Delay", [3])

        for i in range(start, start + count):
            wafer_num = i + 1
            self.logger.info(f"Processing wafer {wafer_num} from baking tray to carousel")

            if wafer_num % 11 == 1 and wafer_num >= 1:
                await self._execute_command("Delay", [5])

            await self._execute_command("GripperOpen", [])
            await self._execute_command("Delay", [1])

            positions = self.position_calculator.calculate_intermediate_positions(i, "carousel")
            baking_position = self.position_calculator.calculate_wafer_position(i, "baking")

            # Move to above baking tray
            await self._execute_command("SetJointVel", [self.SPEED])
            await self._execute_command("MovePose", positions["above_baking"])
            await self._execute_command("SetJointVel", [self.ALIGN_SPEED])
            await self._execute_command("SetBlending", [0])

            # Pick up wafer from baking tray
            await self._execute_command("MovePose", baking_position)
            await self._execute_command("Delay", [0.5])
            await self._execute_command("GripperClose", [])
            await self._execute_command("Delay", [0.5])

            # Movement path to carousel
            await self._execute_command("SetBlending", [100])
            await self._execute_command("MovePose", positions["move1"])
            await self._execute_command("SetJointVel", [self.SPEED])
            await self._execute_command("MovePose", positions["move2"])
            await self._execute_command("MovePose", positions["move3"])
            await self._execute_command("MovePose", positions["move4"])
            await self._execute_command("Delay", [0.5])
            await self._execute_command("SetBlending", [80])

            # Move through photogate
            await self._execute_command("MovePose", self.position_calculator.T_PHOTOGATE)
            await self._execute_command("MovePose", self.position_calculator.C_PHOTOGATE)

            # Y Away approach
            await self._execute_command("MovePose", positions["y_away1"])
            await self._execute_command("SetBlending", [0])
            await self._execute_command("Delay", [1])
            await self._execute_command("SetJointVel", [self.ENTRY_SPEED])
            await self._execute_command("MovePose", positions["y_away2"])

            # Approach carousel
            await self._execute_command("MovePose", positions["above_carousel1"])
            await self._execute_command("MovePose", positions["above_carousel2"])
            await self._execute_command("MovePose", positions["above_carousel3"])

            # Release wafer at carousel
            await self._execute_command("MovePose", self.position_calculator.CAROUSEL)
            await self._execute_command("Delay", [0.5])
            await self._execute_command("MoveGripper", [2.9])
            await self._execute_command("Delay", [0.5])

            # Exit carousel
            await self._execute_command("SetJointVel", [self.EMPTY_SPEED])
            await self._execute_command("MovePose", positions["above_carousel3"])
            await self._execute_command("MovePose", positions["above_carousel2"])
            await self._execute_command("MovePose", positions["above_carousel1"])
            await self._execute_command("MovePose", positions["y_away2"])
            await self._execute_command("MovePose", positions["y_away1"])

            # Return to safe point
            await self._execute_command("MovePose", self.position_calculator.CAROUSEL_SAFEPOINT)
            await self._execute_command("SetBlending", [100])

            self.logger.info(f"[WAFER {wafer_num}/{start+count}] Carousel placement completed")

        result = {
            "status": "completed",
            "wafers_processed": count,
            "start_wafer": start + 1,
            "end_wafer": start + count
        }

        self.logger.info(f"Carousel sequence completed for wafers {start+1} to {start+count}")
        return result

    async def execute_empty_carousel_sequence(self, start: int, count: int) -> Dict[str, Any]:
        """
        Execute empty carousel sequence from carousel back to baking tray.

        Args:
            start: Starting wafer index (0-based)
            count: Number of wafers to process (typically 11)

        Returns:
            Dictionary with sequence results
        """
        self.logger.info(f"Starting empty carousel sequence for wafers {start+1} to {start+count}")

        for i in range(start, start + count):
            wafer_num = i + 1
            self.logger.info(f"Processing wafer {wafer_num} from carousel to baking tray")

            if wafer_num % 11 == 1:
                await self._execute_command("Delay", [7.5])
            else:
                await self._execute_command("Delay", [1])

            await self._execute_command("GripperOpen", [])
            await self._execute_command("Delay", [1])

            positions = self.position_calculator.calculate_intermediate_positions(i, "empty_carousel")

            # Move to Y-away positions
            await self._execute_command("MovePose", positions["y_away1"])
            await self._execute_command("MovePose", positions["y_away2"])
            await self._execute_command("MovePose", positions["above_carousel"])

            # Prepare to pick up from carousel
            await self._execute_command("SetBlending", [0])
            await self._execute_command("SetJointVel", [self.ENTRY_SPEED])
            await self._execute_command("MoveGripper", [3.7])
            await self._execute_command("Delay", [0.5])

            # Staged approach to carousel (reverse order)
            above_carousel5 = copy.deepcopy(self.position_calculator.CAROUSEL)
            above_carousel5[2] = 109.9
            await self._execute_command("MovePose", above_carousel5)

            above_carousel4 = copy.deepcopy(self.position_calculator.CAROUSEL)
            above_carousel4[2] = 103.9
            await self._execute_command("MovePose", above_carousel4)

            # Grab wafer from carousel
            await self._execute_command("MovePose", self.position_calculator.CAROUSEL)
            await self._execute_command("Delay", [0.5])
            await self._execute_command("GripperClose", [])
            await self._execute_command("SetJointVel", [self.ALIGN_SPEED])
            await self._execute_command("Delay", [0.5])

            # Staged exit from carousel
            above_carousel3 = copy.deepcopy(self.position_calculator.CAROUSEL)
            above_carousel3[2] = 103.9
            await self._execute_command("MovePose", above_carousel3)

            above_carousel2 = copy.deepcopy(self.position_calculator.CAROUSEL)
            above_carousel2[2] = 109.9
            await self._execute_command("MovePose", above_carousel2)

            above_carousel1 = copy.deepcopy(self.position_calculator.CAROUSEL)
            above_carousel1[2] = 115.9
            await self._execute_command("MovePose", above_carousel1)

            # Move through Y-away positions
            move8_rev = copy.deepcopy(self.position_calculator.CAROUSEL)
            move8_rev[1] = -245.95
            move8_rev[2] = 115.9
            await self._execute_command("MovePose", move8_rev)
            await self._execute_command("Delay", [0.5])
            await self._execute_command("SetBlending", [80])
            await self._execute_command("SetJointVel", [self.SPEED])

            move7_rev = copy.deepcopy(self.position_calculator.CAROUSEL)
            move7_rev[1] = -216.95
            move7_rev[2] = 120.0
            await self._execute_command("MovePose", move7_rev)

            # Through photogate in reverse
            await self._execute_command("MovePose", self.position_calculator.C_PHOTOGATE)
            await self._execute_command("MovePose", self.position_calculator.T_PHOTOGATE)
            await self._execute_command("Delay", [0.5])

            # Move through baking tray alignment (reverse)
            await self._execute_command("MovePose", positions["move4_rev"])
            await self._execute_command("SetJointVel", [self.ALIGN_SPEED])
            await self._execute_command("Delay", [0.5])
            await self._execute_command("SetBlending", [100])
            await self._execute_command("MovePose", positions["move3_rev"])
            await self._execute_command("MovePose", positions["move2_rev"])
            await self._execute_command("MovePose", positions["move1_rev"])
            await self._execute_command("Delay", [1])

            # Release wafer
            await self._execute_command("GripperOpen", [])
            await self._execute_command("Delay", [0.5])

            # Move up from baking tray
            await self._execute_command("MovePose", positions["above_baking_rev"])
            await self._execute_command("SetJointVel", [self.EMPTY_SPEED])
            await self._execute_command("Delay", [0.2])
            await self._execute_command("SetBlending", [100])

            # Return to safe point
            await self._execute_command("MovePose", self.position_calculator.CAROUSEL_SAFEPOINT)

            self.logger.info(f"[WAFER {wafer_num}/{start+count}] Carousel retrieval completed")

        result = {
            "status": "completed",
            "wafers_processed": count,
            "start_wafer": start + 1,
            "end_wafer": start + count
        }

        self.logger.info(f"Empty carousel sequence completed for wafers {start+1} to {start+count}")
        return result

    async def resume_operations(self) -> ServiceResult[Dict[str, Any]]:
        """
        Resume interrupted operations based on step state.
        Called by orchestrator.resume_all_operations().

        Supports true mid-resume: resumes from the exact command position within a wafer.

        Returns:
            ServiceResult with resume status
        """
        try:
            step_state = await self.state_manager.get_step_state(self.robot_id)

            if not step_state:
                self.logger.info(f"No step state to resume for {self.robot_id}")
                return ServiceResult.success_result({"resumed": False, "reason": "no_step_state"})

            operation_type = step_state.operation_type
            progress = step_state.progress_data or {}

            self.logger.info(f"Resuming {operation_type} for {self.robot_id} from progress: {progress}")

            # Extract resume parameters (wafer-level and command-level)
            start = progress.get("start", 0)
            count = progress.get("count", 5)
            current_index = progress.get("current_wafer_index", start)
            current_cmd_index = progress.get("current_command_index", 0)
            last_command = progress.get("last_command", None)
            remaining_wafers = list(range(current_index, start + count))

            self.logger.info(
                f"[MID-RESUME] Resume parameters: start={start}, count={count}, "
                f"wafer_index={current_index}, cmd_index={current_cmd_index}, "
                f"last_command={last_command}, remaining_wafers={remaining_wafers}"
            )

            if operation_type == "pickup_sequence" and remaining_wafers:
                self._resume_task = asyncio.create_task(
                    self._resume_pickup_sequence(start, count, remaining_wafers)
                )
                return ServiceResult.success_result({
                    "resumed": True,
                    "operation": "pickup_sequence",
                    "from_wafer": current_index,
                    "from_command": current_cmd_index,
                    "last_command": last_command,
                    "remaining": len(remaining_wafers),
                    "mid_wafer_resume": current_cmd_index > 0
                })

            elif operation_type == "drop_sequence" and remaining_wafers:
                self._resume_task = asyncio.create_task(
                    self._resume_drop_sequence(start, count, remaining_wafers)
                )
                return ServiceResult.success_result({
                    "resumed": True,
                    "operation": "drop_sequence",
                    "from_wafer": current_index,
                    "from_command": current_cmd_index,
                    "last_command": last_command,
                    "remaining": len(remaining_wafers),
                    "mid_wafer_resume": current_cmd_index > 0
                })

            self.logger.warning(f"Unknown operation type: {operation_type}")
            return ServiceResult.success_result({
                "resumed": False,
                "reason": f"unknown_operation: {operation_type}"
            })

        except Exception as e:
            self.logger.error(f"Failed to resume operations: {e}")
            return ServiceResult.error_result(str(e))

    async def _resume_pickup_sequence(self, start: int, count: int, remaining_wafers: List[int]) -> None:
        """Resume pickup sequence from interrupted point."""
        try:
            self.logger.info(f"Resuming pickup sequence: remaining_wafers={remaining_wafers}")

            # Reset errors and clear motion queue before wait_idle
            try:
                await self.async_wrapper.reset_error()
            except Exception as e:
                self.logger.warning(f"Could not reset errors: {e}")

            try:
                await self.async_wrapper.clear_motion()
            except Exception as e:
                self.logger.warning(f"Could not clear motion: {e}")

            try:
                await self.async_wrapper.resume_motion()
            except Exception as e:
                self.logger.warning(f"Could not resume motion: {e}")

            await self.async_wrapper.wait_idle(timeout=10.0)

            result = await self.execute_pickup_sequence(
                start=start,
                count=count,
                retry_wafers=remaining_wafers
            )
            if self.broadcaster_callback:
                await self.broadcaster_callback("pickup_resumed_complete", result)
        except Exception as e:
            self.logger.error(f"Resumed pickup sequence failed: {e}")
            if self.broadcaster_callback:
                await self.broadcaster_callback("pickup_resumed_error", {"error": str(e)})
        finally:
            self._resume_task = None

    async def _resume_drop_sequence(self, start: int, count: int, remaining_wafers: List[int]) -> None:
        """Resume drop sequence from interrupted point."""
        try:
            self.logger.info(f"Resuming drop sequence: remaining_wafers={remaining_wafers}")

            try:
                await self.async_wrapper.reset_error()
            except Exception as e:
                self.logger.warning(f"Could not reset errors: {e}")

            try:
                await self.async_wrapper.clear_motion()
            except Exception as e:
                self.logger.warning(f"Could not clear motion: {e}")

            try:
                await self.async_wrapper.resume_motion()
            except Exception as e:
                self.logger.warning(f"Could not resume motion: {e}")

            await self.async_wrapper.wait_idle(timeout=10.0)

            result = await self.execute_drop_sequence(
                start=start,
                count=count,
                retry_wafers=remaining_wafers
            )
            if self.broadcaster_callback:
                await self.broadcaster_callback("drop_resumed_complete", result)
        except Exception as e:
            self.logger.error(f"Resumed drop sequence failed: {e}")
            if self.broadcaster_callback:
                await self.broadcaster_callback("drop_resumed_error", {"error": str(e)})
        finally:
            self._resume_task = None
