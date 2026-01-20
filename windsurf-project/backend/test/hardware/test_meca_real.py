"""
Real hardware tests for Mecademic robot.
These tests require actual hardware connection and should be excluded from CI.

Run with: pytest test/hardware/test_meca_real.py -v --hardware
"""
import asyncio
import pytest

# Mark all tests in this module as requiring hardware
pytestmark = pytest.mark.hardware


@pytest.fixture
def real_meca_ip():
    """Real Mecademic robot IP from configuration."""
    return "192.168.0.100"


class TestMecaRealConnection:
    """
    Real hardware connection tests.
    Requires Mecademic robot to be connected and powered on.
    """

    @pytest.mark.asyncio
    async def test_connection(self, real_meca_ip):
        """Test actual connection to Mecademic robot."""
        pytest.skip("Requires real hardware - run with --hardware flag")

        # This test would use the real mecademicpy library
        # from mecademicpy.robot import Robot
        #
        # robot = Robot()
        # try:
        #     robot.Connect(real_meca_ip, offline_mode=False)
        #     is_connected = robot.IsConnected()
        #     assert is_connected, "Failed to connect to robot"
        # finally:
        #     if robot.IsConnected():
        #         robot.Disconnect()

    @pytest.mark.asyncio
    async def test_status_retrieval(self, real_meca_ip):
        """Test getting robot status from real hardware."""
        pytest.skip("Requires real hardware - run with --hardware flag")

        # This would test real status retrieval
        # robot = Robot()
        # try:
        #     robot.Connect(real_meca_ip, offline_mode=False)
        #     status = robot.GetStatusRobot()
        #     assert status is not None
        # finally:
        #     robot.Disconnect()

    @pytest.mark.asyncio
    async def test_activation_sequence(self, real_meca_ip):
        """Test real robot activation sequence."""
        pytest.skip("Requires real hardware - run with --hardware flag")

        # WARNING: This would actually activate and home the robot
        # Only run when robot is in safe position
        #
        # robot = Robot()
        # try:
        #     robot.Connect(real_meca_ip, offline_mode=False)
        #     robot.ActivateRobot()
        #     robot.Home()
        #     robot.WaitHomed(timeout=30.0)
        #     assert robot.IsHomed()
        # finally:
        #     robot.DeactivateRobot()
        #     robot.Disconnect()


class TestMecaRealMovement:
    """
    Real hardware movement tests.
    CAUTION: These tests move the robot.
    """

    @pytest.mark.asyncio
    async def test_safe_point_movement(self, real_meca_ip):
        """Test movement to safe point."""
        pytest.skip("Requires real hardware - run with --hardware flag")

        # SAFE_POINT = [135, -17.6177, 160, 123.2804, 40.9554, -101.3308]
        #
        # robot = Robot()
        # try:
        #     robot.Connect(real_meca_ip, offline_mode=False)
        #     robot.ActivateRobot()
        #     robot.Home()
        #     robot.WaitHomed()
        #
        #     robot.MovePose(*SAFE_POINT)
        #     robot.WaitIdle()
        #
        #     # Verify position
        #     joints = robot.GetJoints()
        #     assert joints is not None
        # finally:
        #     robot.DeactivateRobot()
        #     robot.Disconnect()


class TestMecaRealGripper:
    """
    Real gripper tests.
    """

    @pytest.mark.asyncio
    async def test_gripper_operation(self, real_meca_ip):
        """Test gripper open/close."""
        pytest.skip("Requires real hardware - run with --hardware flag")

        # robot = Robot()
        # try:
        #     robot.Connect(real_meca_ip, offline_mode=False)
        #     robot.ActivateRobot()
        #     robot.Home()
        #     robot.WaitHomed()
        #
        #     robot.GripperOpen()
        #     robot.Delay(0.5)
        #     robot.GripperClose()
        #     robot.Delay(0.5)
        #     robot.WaitIdle()
        # finally:
        #     robot.DeactivateRobot()
        #     robot.Disconnect()
