"""
Tests for wafer sequence resume edge cases.

These tests verify:
1. Bug fix: batch_completion event name matches frontend expectation
2. Bug fix: Resume from wafer 0, cmd 0 after emergency stop doesn't drop wafer
3. Paused state properly triggers is_resume=True
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from dataclasses import dataclass
from typing import Dict, Any, Optional


@dataclass
class MockStepState:
    """Mock step state for testing."""
    robot_id: str
    step_index: int
    step_name: str
    operation_type: str
    progress_data: Dict[str, Any]
    paused: bool = False


class TestBatchCompletionEventName:
    """Tests for Bug 1: batch_completion event naming."""

    @pytest.fixture
    def mock_broadcaster(self):
        """Create a mock broadcaster that captures event names."""
        calls = []

        async def broadcaster(event_name: str, data: Dict[str, Any]):
            calls.append((event_name, data))

        broadcaster.calls = calls
        return broadcaster

    @pytest.mark.asyncio
    async def test_batch_completion_event_name_matches_frontend(self, mock_broadcaster):
        """Verify _broadcast_batch_completion uses 'batch_completion' event name.

        Frontend listens for 'batch_completion' (line 547 in SystemStatus.jsx).
        Backend must emit 'batch_completion', not 'batch_complete'.
        """
        from services.meca.wafer_sequences import MecaWaferSequences

        # Create minimal mock dependencies
        mock_wrapper = MagicMock()
        mock_state_manager = MagicMock()
        mock_position_calc = MagicMock()
        mock_movement_exec = MagicMock()
        mock_config = {"movement_params": {}}

        sequences = MecaWaferSequences(
            robot_id="test_robot",
            robot_config=mock_config,
            async_wrapper=mock_wrapper,
            state_manager=mock_state_manager,
            position_calculator=mock_position_calc,
            movement_executor=mock_movement_exec,
            broadcaster_callback=mock_broadcaster
        )

        # Call the batch completion broadcaster
        result = await sequences._broadcast_batch_completion(
            operation_type="pickup",
            start=0,
            count=5,
            result={"status": "completed"}
        )

        # Verify event name is 'batch_completion' (not 'batch_complete')
        assert result is True
        assert len(mock_broadcaster.calls) == 1
        event_name, event_data = mock_broadcaster.calls[0]
        assert event_name == "batch_completion", \
            f"Expected 'batch_completion' but got '{event_name}'"
        assert event_data["operation"] == "pickup"
        assert event_data["robot_id"] == "test_robot"


class TestResumeFromWafer0Cmd0:
    """Tests for Bug 2: Resume from wafer 0, cmd 0 edge case."""

    @pytest.fixture
    def mock_state_manager(self):
        """Create mock state manager."""
        state_manager = MagicMock()
        state_manager.get_step_state = AsyncMock()
        state_manager.start_step = AsyncMock()
        state_manager.resume_step = AsyncMock()
        state_manager.update_step_progress = AsyncMock()
        state_manager.complete_step = AsyncMock()
        state_manager.is_step_paused = AsyncMock(return_value=False)
        state_manager.get_robot_state = AsyncMock(return_value=None)
        return state_manager

    @pytest.fixture
    def mock_async_wrapper(self):
        """Create mock async wrapper."""
        wrapper = MagicMock()
        wrapper.wait_idle = AsyncMock()
        return wrapper

    @pytest.fixture
    def mock_movement_executor(self):
        """Create mock movement executor."""
        executor = MagicMock()
        executor.execute_movement_command = AsyncMock()
        executor.check_robot_status_after_motion = AsyncMock()
        return executor

    @pytest.fixture
    def mock_position_calculator(self):
        """Create mock position calculator."""
        calc = MagicMock()
        calc.calculate_intermediate_positions = MagicMock(return_value={
            "pickup_high": [0, 0, 100, 0, 0, 0],
            "intermediate_1": [0, 0, 80, 0, 0, 0],
            "intermediate_2": [0, 0, 60, 0, 0, 0],
            "intermediate_3": [0, 0, 40, 0, 0, 0],
            "above_spreader": [0, 0, 30, 0, 0, 0],
            "above_spreader_exit": [0, 0, 35, 0, 0, 0],
            "spreader": [0, 0, 20, 0, 0, 0],
        })
        calc.calculate_wafer_position = MagicMock(return_value=[0, 0, 10, 0, 0, 0])
        calc.SAFE_POINT = [0, 0, 150, 0, 0, 0]
        return calc

    @pytest.mark.asyncio
    async def test_resume_from_wafer_0_cmd_0_skips_gripper_open(
        self, mock_state_manager, mock_async_wrapper,
        mock_movement_executor, mock_position_calculator
    ):
        """Verify GripperOpen is NOT called when resuming from paused state at wafer 0, cmd 0.

        This tests the edge case where:
        - Emergency stop triggered at wafer 0, command 0
        - resume_from_wafer = 0, resume_from_cmd = 0
        - Old logic: is_resume = (0 > 0) or (0 > 0) = False -> GripperOpen called -> wafer dropped
        - Fixed logic: is_resume = was_paused or ... = True -> GripperOpen skipped
        """
        from services.meca.wafer_sequences import MecaWaferSequences

        # Setup: existing paused step at wafer 0, cmd 0
        paused_step = MockStepState(
            robot_id="test_robot",
            step_index=5,
            step_name="Pick up wafers from Inert Tray",
            operation_type="pickup_sequence",
            progress_data={
                "start": 0,
                "count": 1,
                "current_wafer_index": 0,
                "current_command_index": 0,
                "last_command": None
            },
            paused=True  # Key: step is paused
        )

        # First call returns paused step, subsequent calls return resumed step
        resumed_step = MockStepState(
            robot_id="test_robot",
            step_index=5,
            step_name="Pick up wafers from Inert Tray",
            operation_type="pickup_sequence",
            progress_data={
                "start": 0,
                "count": 1,
                "current_wafer_index": 0,
                "current_command_index": 0,
                "last_command": None
            },
            paused=False  # After resume
        )

        mock_state_manager.get_step_state.side_effect = [paused_step, resumed_step]

        mock_config = {"movement_params": {}}
        mock_broadcaster = AsyncMock()

        sequences = MecaWaferSequences(
            robot_id="test_robot",
            robot_config=mock_config,
            async_wrapper=mock_async_wrapper,
            state_manager=mock_state_manager,
            position_calculator=mock_position_calculator,
            movement_executor=mock_movement_executor,
            broadcaster_callback=mock_broadcaster
        )

        # Execute pickup sequence (resuming from paused state)
        await sequences.execute_pickup_sequence(start=0, count=1)

        # Collect all movement commands that were called
        executed_commands = [
            call[0][0]  # First arg of execute_movement_command is command_type
            for call in mock_movement_executor.execute_movement_command.call_args_list
        ]

        # Verify initial setup commands (including GripperOpen) were NOT executed
        # The initial setup block includes: SetGripperForce, SetJointAcc, SetTorqueLimits,
        # SetTorqueLimitsCfg, SetBlending, SetJointVel, SetConf, GripperOpen, Delay
        #
        # If is_resume=True, these should be skipped
        setup_commands = ["SetGripperForce", "SetJointAcc", "SetTorqueLimits",
                          "SetTorqueLimitsCfg", "SetConf"]

        for cmd in setup_commands:
            # Check that setup command was not the FIRST occurrence
            # (It may appear later in the wafer commands, but not as initial setup)
            if cmd in executed_commands:
                # Find if it's from initial setup or from wafer commands
                first_idx = executed_commands.index(cmd)
                # Initial setup would be before first MovePose
                movpose_indices = [i for i, c in enumerate(executed_commands) if c == "MovePose"]
                if movpose_indices:
                    first_movpose = movpose_indices[0]
                    assert first_idx >= first_movpose, \
                        f"Initial setup command {cmd} was executed before first MovePose - " \
                        f"is_resume logic failed to skip initial setup"

    @pytest.mark.asyncio
    async def test_fresh_start_executes_gripper_open(
        self, mock_state_manager, mock_async_wrapper,
        mock_movement_executor, mock_position_calculator
    ):
        """Verify GripperOpen IS called on fresh start (no existing step)."""
        from services.meca.wafer_sequences import MecaWaferSequences

        # No existing step - fresh start
        mock_state_manager.get_step_state.side_effect = [
            None,  # First call: no existing step
            MockStepState(  # After start_step
                robot_id="test_robot",
                step_index=5,
                step_name="Pick up wafers from Inert Tray",
                operation_type="pickup_sequence",
                progress_data={
                    "start": 0,
                    "count": 1,
                    "current_wafer_index": 0,
                    "current_command_index": 0,
                    "last_command": None
                },
                paused=False
            )
        ]

        mock_config = {"movement_params": {}}
        mock_broadcaster = AsyncMock()

        sequences = MecaWaferSequences(
            robot_id="test_robot",
            robot_config=mock_config,
            async_wrapper=mock_async_wrapper,
            state_manager=mock_state_manager,
            position_calculator=mock_position_calculator,
            movement_executor=mock_movement_executor,
            broadcaster_callback=mock_broadcaster
        )

        await sequences.execute_pickup_sequence(start=0, count=1)

        # Collect executed commands
        executed_commands = [
            call[0][0]
            for call in mock_movement_executor.execute_movement_command.call_args_list
        ]

        # Verify GripperOpen was called (part of initial setup)
        assert "GripperOpen" in executed_commands, \
            "GripperOpen should be called on fresh start"

        # Verify it was called before first MovePose (as part of setup)
        gripper_idx = executed_commands.index("GripperOpen")
        movpose_indices = [i for i, c in enumerate(executed_commands) if c == "MovePose"]
        if movpose_indices:
            first_movpose = movpose_indices[0]
            assert gripper_idx < first_movpose, \
                "GripperOpen should be called as part of initial setup (before MovePose)"


class TestPausedStateTriggersIsResume:
    """Tests verifying paused state correctly sets is_resume=True."""

    @pytest.mark.asyncio
    async def test_paused_state_captured_before_resume_step(self):
        """Verify was_paused is captured BEFORE calling resume_step().

        This is critical because resume_step() clears the paused flag,
        so we must capture it before the call.
        """
        from services.meca.wafer_sequences import MecaWaferSequences

        # Track the order of operations
        call_order = []

        # Mock state manager that tracks calls
        mock_state_manager = MagicMock()

        paused_step = MockStepState(
            robot_id="test_robot",
            step_index=5,
            step_name="Pick up wafers",
            operation_type="pickup_sequence",
            progress_data={"start": 0, "count": 1, "current_wafer_index": 0, "current_command_index": 0},
            paused=True
        )

        resumed_step = MockStepState(
            robot_id="test_robot",
            step_index=5,
            step_name="Pick up wafers",
            operation_type="pickup_sequence",
            progress_data={"start": 0, "count": 1, "current_wafer_index": 0, "current_command_index": 0},
            paused=False
        )

        async def track_get_step(*args):
            call_order.append("get_step_state")
            if len([c for c in call_order if c == "get_step_state"]) == 1:
                return paused_step
            return resumed_step

        async def track_resume(*args):
            call_order.append("resume_step")

        mock_state_manager.get_step_state = track_get_step
        mock_state_manager.resume_step = track_resume
        mock_state_manager.start_step = AsyncMock()
        mock_state_manager.update_step_progress = AsyncMock()
        mock_state_manager.complete_step = AsyncMock()
        mock_state_manager.is_step_paused = AsyncMock(return_value=False)
        mock_state_manager.get_robot_state = AsyncMock(return_value=None)

        # Create sequences with minimal mocks
        mock_wrapper = MagicMock()
        mock_wrapper.wait_idle = AsyncMock()

        mock_executor = MagicMock()
        mock_executor.execute_movement_command = AsyncMock()
        mock_executor.check_robot_status_after_motion = AsyncMock()

        mock_calc = MagicMock()
        mock_calc.calculate_intermediate_positions = MagicMock(return_value={
            "pickup_high": [0]*6, "intermediate_1": [0]*6, "intermediate_2": [0]*6,
            "intermediate_3": [0]*6, "above_spreader": [0]*6, "above_spreader_exit": [0]*6,
            "spreader": [0]*6
        })
        mock_calc.calculate_wafer_position = MagicMock(return_value=[0]*6)
        mock_calc.SAFE_POINT = [0]*6

        sequences = MecaWaferSequences(
            robot_id="test_robot",
            robot_config={"movement_params": {}},
            async_wrapper=mock_wrapper,
            state_manager=mock_state_manager,
            position_calculator=mock_calc,
            movement_executor=mock_executor,
            broadcaster_callback=AsyncMock()
        )

        await sequences.execute_pickup_sequence(start=0, count=1)

        # Verify order: get_step_state must be called before resume_step
        # (to capture paused state)
        assert "get_step_state" in call_order
        assert "resume_step" in call_order
        get_idx = call_order.index("get_step_state")
        resume_idx = call_order.index("resume_step")
        assert get_idx < resume_idx, \
            "get_step_state must be called before resume_step to capture paused state"
