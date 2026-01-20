"""
Tests for Mecademic command sequences.
Verifies correct execution order and motion buffer behavior.
"""
import pytest


@pytest.mark.integration
class TestMovementCommandSequences:
    """Test movement command queueing in motion buffer."""

    def test_move_pose_queued(self, meca_simulator):
        """Test MovePose commands are queued in motion buffer."""
        meca_simulator.MovePose(100.0, 200.0, 50.0, 0.0, 90.0, 0.0)

        queue = meca_simulator.get_motion_queue()
        assert len(queue) == 1
        assert queue[0]['type'] == 'MovePose'
        assert queue[0]['params'] == [100.0, 200.0, 50.0, 0.0, 90.0, 0.0]

    def test_move_joints_queued(self, meca_simulator):
        """Test MoveJoints commands are queued in motion buffer."""
        meca_simulator.MoveJoints(0.0, 45.0, 90.0, 0.0, 45.0, 0.0)

        queue = meca_simulator.get_motion_queue()
        assert len(queue) == 1
        assert queue[0]['type'] == 'MoveJoints'
        assert queue[0]['params'] == [0.0, 45.0, 90.0, 0.0, 45.0, 0.0]

    def test_delay_queued_in_robot(self, meca_simulator):
        """
        CRITICAL: Test Delay is queued in robot buffer, not Python sleep.
        This is the fix for the robot rushing issue.
        """
        meca_simulator.Delay(1.0)

        queue = meca_simulator.get_motion_queue()
        assert len(queue) == 1
        assert queue[0]['type'] == 'Delay'
        assert queue[0]['duration'] == 1.0

        # Verify in command history
        history = meca_simulator.get_command_history()
        assert ('Delay', 1.0) in history

    def test_gripper_commands_queued(self, meca_simulator):
        """Test gripper commands are queued."""
        meca_simulator.GripperOpen()
        meca_simulator.GripperClose()

        queue = meca_simulator.get_motion_queue()
        assert len(queue) == 2
        assert queue[0]['type'] == 'GripperOpen'
        assert queue[1]['type'] == 'GripperClose'


@pytest.mark.integration
class TestPickupSequenceOrder:
    """Test correct ordering of pickup sequence commands."""

    def test_pickup_sequence_motion_order(self, meca_simulator):
        """
        Test pickup sequence maintains correct order:
        MovePose -> Delay -> GripperClose
        """
        # Simulate pickup sequence
        meca_simulator.MovePose(173.562, -175.178, 27.9714, 109.5547, 0.2877, -90.059)
        meca_simulator.Delay(1.0)
        meca_simulator.GripperClose()

        queue = meca_simulator.get_motion_queue()

        # Verify order
        assert queue[0]['type'] == 'MovePose'
        assert queue[1]['type'] == 'Delay'
        assert queue[2]['type'] == 'GripperClose'

    def test_delay_before_gripper_close_invariant(self, meca_simulator):
        """
        CRITICAL INVARIANT: Delay must be in motion buffer BEFORE GripperClose.
        This prevents the "rushing" bug.
        """
        # Simulate pickup with multiple delays
        meca_simulator.MovePose(100.0, 100.0, 50.0, 0.0, 0.0, 0.0)
        meca_simulator.Delay(0.5)
        meca_simulator.GripperClose()
        meca_simulator.Delay(0.5)
        meca_simulator.MovePose(100.0, 100.0, 100.0, 0.0, 0.0, 0.0)

        queue = meca_simulator.get_motion_queue()
        command_types = [cmd['type'] for cmd in queue]

        # Find all Delay and GripperClose positions
        delay_positions = [i for i, t in enumerate(command_types) if t == 'Delay']
        gripper_close_positions = [i for i, t in enumerate(command_types) if t == 'GripperClose']

        # At least one Delay must precede each GripperClose
        for gripper_pos in gripper_close_positions:
            delays_before = [d for d in delay_positions if d < gripper_pos]
            assert len(delays_before) > 0, \
                f"GripperClose at position {gripper_pos} has no preceding Delay!"


@pytest.mark.integration
class TestConfigurationCommandSequence:
    """Test configuration commands are recorded correctly."""

    def test_parameter_initialization_commands(self, meca_simulator):
        """Test all parameter init commands are recorded."""
        # Simulate initialization sequence
        meca_simulator.SetGripperForce(100)
        meca_simulator.SetJointAcc(50)
        meca_simulator.SetTorqueLimits(40, 40, 40, 40, 40, 40)
        meca_simulator.SetTorqueLimitsCfg(2, 1)
        meca_simulator.SetBlending(0)

        history = meca_simulator.get_command_history()

        # Verify all commands recorded
        assert ('SetGripperForce', 100) in history
        assert ('SetJointAcc', 50) in history
        assert ('SetTorqueLimits', [40, 40, 40, 40, 40, 40]) in history
        assert ('SetTorqueLimitsCfg', [2, 1]) in history
        assert ('SetBlending', 0) in history

    def test_carousel_setconf(self, meca_simulator):
        """Test SetConf for carousel operations."""
        meca_simulator.SetConf(1, 1, -1)
        meca_simulator.Delay(3)

        history = meca_simulator.get_command_history()
        assert ('SetConf', [1, 1, -1]) in history
        assert ('Delay', 3) in history


@pytest.mark.integration
class TestFullPickupSequenceSimulation:
    """Test complete pickup sequence simulation."""

    def test_single_wafer_pickup(self, meca_simulator):
        """Simulate picking up a single wafer."""
        # Initialize parameters
        meca_simulator.SetGripperForce(100)
        meca_simulator.SetJointAcc(50)
        meca_simulator.SetBlending(0)

        # Open gripper
        meca_simulator.GripperOpen()

        # Move to position
        meca_simulator.MovePose(173.562, -175.178, 50.0, 109.5547, 0.2877, -90.059)  # Entry
        meca_simulator.MovePose(173.562, -175.178, 27.9714, 109.5547, 0.2877, -90.059)  # Wafer level

        # Pick up
        meca_simulator.Delay(1.0)
        meca_simulator.GripperClose()
        meca_simulator.Delay(0.5)

        # Exit
        meca_simulator.SetJointVel(35)
        meca_simulator.MovePose(173.562, -175.178, 50.0, 109.5547, 0.2877, -90.059)

        # Verify sequence
        queue = meca_simulator.get_motion_queue()
        assert len(queue) > 5  # At least 5 motion commands

        # Verify gripper state
        assert meca_simulator.is_gripper_open() is False

    def test_batch_sequence_records_all_commands(self, meca_simulator):
        """Test multiple wafer operations record all commands."""
        for i in range(3):
            meca_simulator.GripperOpen()
            meca_simulator.MovePose(100.0 + i, 200.0, 50.0, 0.0, 0.0, 0.0)
            meca_simulator.Delay(0.5)
            meca_simulator.GripperClose()
            meca_simulator.Delay(0.5)
            meca_simulator.MovePose(100.0 + i, 200.0, 100.0, 0.0, 0.0, 0.0)

        queue = meca_simulator.get_motion_queue()
        # 6 commands per wafer * 3 wafers = 18 commands
        assert len(queue) == 18


@pytest.mark.integration
class TestClearHistory:
    """Test history clearing between tests."""

    def test_clear_command_history(self, meca_simulator):
        """Test clear_history resets tracking."""
        meca_simulator.MovePose(100.0, 100.0, 100.0, 0.0, 0.0, 0.0)
        meca_simulator.Delay(1.0)

        assert len(meca_simulator.get_command_history()) == 2
        assert len(meca_simulator.get_motion_queue()) == 2

        meca_simulator.clear_history()

        assert len(meca_simulator.get_command_history()) == 0
        assert len(meca_simulator.get_motion_queue()) == 0
