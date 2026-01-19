"""
Tests for error recovery scenarios.
Verifies robot behavior under error conditions.
"""
import pytest


@pytest.mark.edge_case
class TestMecaErrorRecovery:
    """Tests for Mecademic error recovery."""

    @pytest.mark.asyncio
    async def test_error_detection(self, meca_simulator):
        """Test error state is properly detected."""
        meca_simulator.inject_error(error_code=1042)

        status = await meca_simulator.get_status()

        assert status['error_status'] is True
        assert status['error_code'] == 1042

    @pytest.mark.asyncio
    async def test_error_reset(self, meca_simulator):
        """Test error can be reset."""
        meca_simulator.inject_error(error_code=1042)
        await meca_simulator.reset_error()

        status = await meca_simulator.get_status()

        assert status['error_status'] is False
        assert status['error_code'] is None

    @pytest.mark.asyncio
    async def test_recovery_after_error(self, meca_simulator):
        """Test robot can operate after error recovery."""
        # Put in error state
        meca_simulator.inject_error()

        # Recover
        await meca_simulator.reset_error()

        # Should be able to send commands
        await meca_simulator.connect("192.168.0.100")
        meca_simulator.MovePose(100.0, 100.0, 100.0, 0.0, 0.0, 0.0)

        assert len(meca_simulator.get_command_history()) > 0

    @pytest.mark.asyncio
    async def test_pause_and_resume(self, meca_simulator):
        """Test motion pause and resume."""
        meca_simulator._paused = True

        status = await meca_simulator.get_status()
        assert status['pause_motion_status'] is True

        await meca_simulator.resume_motion()

        status = await meca_simulator.get_status()
        assert status['pause_motion_status'] is False


@pytest.mark.edge_case
class TestOT2ErrorRecovery:
    """Tests for OT-2 error recovery."""

    @pytest.mark.asyncio
    async def test_run_failure_detection(self, ot2_simulator):
        """Test failed run is properly detected."""
        await ot2_simulator.connect()
        run = await ot2_simulator.create_run('test_protocol')

        ot2_simulator.fail_run(run['id'], "Pipette collision")

        status = await ot2_simulator.get_run_status(run['id'])

        assert status['status'] == 'failed'
        assert status['error'] == "Pipette collision"

    @pytest.mark.asyncio
    async def test_stop_running_protocol(self, ot2_simulator):
        """Test stopping a running protocol."""
        await ot2_simulator.connect()
        run = await ot2_simulator.create_run('test_protocol')
        await ot2_simulator.execute_run(run['id'])

        # Verify running
        status = await ot2_simulator.get_run_status(run['id'])
        assert status['status'] == 'running'

        # Stop
        await ot2_simulator.stop()

        # Verify stopped
        status = await ot2_simulator.get_run_status(run['id'])
        assert status['status'] == 'stopped'

    @pytest.mark.asyncio
    async def test_recovery_after_failed_run(self, ot2_simulator):
        """Test can start new run after failure."""
        await ot2_simulator.connect()

        # First run fails
        run1 = await ot2_simulator.create_run('failing_protocol')
        await ot2_simulator.execute_run(run1['id'])
        ot2_simulator.fail_run(run1['id'], "Error")

        # Should be able to start a new run
        run2 = await ot2_simulator.create_run('recovery_protocol')
        await ot2_simulator.execute_run(run2['id'])

        status = await ot2_simulator.get_run_status(run2['id'])
        assert status['status'] == 'running'


@pytest.mark.edge_case
class TestConnectionFailures:
    """Tests for connection failure scenarios."""

    @pytest.mark.asyncio
    async def test_meca_activation_without_connection(self, meca_simulator):
        """Test activation fails without connection."""
        with pytest.raises(Exception, match="Not connected"):
            await meca_simulator.activate_robot()

    @pytest.mark.asyncio
    async def test_meca_homing_without_activation(self, meca_simulator):
        """Test homing fails without activation."""
        await meca_simulator.connect("192.168.0.100")

        with pytest.raises(Exception, match="Not activated"):
            await meca_simulator.home_robot()

    @pytest.mark.asyncio
    async def test_ot2_run_nonexistent(self, ot2_simulator):
        """Test accessing nonexistent run."""
        with pytest.raises(ValueError, match="not found"):
            await ot2_simulator.get_run_status("fake_run_id")

    @pytest.mark.asyncio
    async def test_ot2_execute_nonexistent_run(self, ot2_simulator):
        """Test executing nonexistent run."""
        with pytest.raises(ValueError, match="not found"):
            await ot2_simulator.execute_run("fake_run_id")


@pytest.mark.edge_case
class TestStateConsistency:
    """Tests for state consistency after errors."""

    @pytest.mark.asyncio
    async def test_meca_state_after_disconnect(self, meca_simulator):
        """Test state is reset after disconnect."""
        # Full activation
        await meca_simulator.connect("192.168.0.100")
        await meca_simulator.activate_robot()
        await meca_simulator.home_robot()

        # Disconnect
        await meca_simulator.disconnect()

        # State should be reset
        assert meca_simulator._connected is False
        assert meca_simulator._activated is False
        assert meca_simulator._homed is False

    @pytest.mark.asyncio
    async def test_ot2_state_after_disconnect(self, ot2_simulator):
        """Test state is maintained correctly after disconnect."""
        await ot2_simulator.connect()
        await ot2_simulator.home()

        await ot2_simulator.disconnect()

        assert ot2_simulator._connected is False
        # Note: homed state persists per simulator design


@pytest.mark.edge_case
class TestInvalidParameters:
    """Tests for invalid parameter handling."""

    def test_meca_delay_recorded(self, meca_simulator):
        """Test various delay values are recorded."""
        # Valid delays
        meca_simulator.Delay(0.1)
        meca_simulator.Delay(5.0)
        meca_simulator.Delay(10.0)

        history = meca_simulator.get_command_history()

        assert ('Delay', 0.1) in history
        assert ('Delay', 5.0) in history
        assert ('Delay', 10.0) in history

    def test_meca_joint_values(self, meca_simulator):
        """Test setting extreme joint values."""
        extreme_joints = [-180.0, 180.0, 0.0, -90.0, 90.0, 360.0]
        meca_simulator.set_joints(extreme_joints)

        # Values should be stored as-is (validation is in service layer)
        assert meca_simulator._joints == extreme_joints


@pytest.mark.edge_case
class TestEmergencyStop:
    """Tests for emergency stop behavior."""

    @pytest.mark.asyncio
    async def test_meca_commands_after_error(self, meca_with_error):
        """Test commands can still be sent after error injection."""
        # Even in error state, simulator accepts commands
        # Real robot would reject, but simulator records for testing
        meca_with_error.MovePose(0.0, 0.0, 0.0, 0.0, 0.0, 0.0)

        history = meca_with_error.get_command_history()
        assert len(history) > 0

    @pytest.mark.asyncio
    async def test_ot2_stop_affects_all_running(self, ot2_simulator):
        """Test stop affects all running protocols."""
        await ot2_simulator.connect()

        run1 = await ot2_simulator.create_run('protocol_1')
        await ot2_simulator.execute_run(run1['id'])

        run2 = await ot2_simulator.create_run('protocol_2')
        await ot2_simulator.execute_run(run2['id'])

        # Stop all
        await ot2_simulator.stop()

        # Both should be stopped
        status1 = await ot2_simulator.get_run_status(run1['id'])
        status2 = await ot2_simulator.get_run_status(run2['id'])

        assert status1['status'] == 'stopped'
        assert status2['status'] == 'stopped'
