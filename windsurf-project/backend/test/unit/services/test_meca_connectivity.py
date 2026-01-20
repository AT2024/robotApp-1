"""
Unit tests for Mecademic service connectivity.
Tests connection flow, error handling, and state transitions.
"""
import pytest


@pytest.mark.unit
class TestMecaSimulatorConnectivity:
    """Tests for Mecademic simulator connection behavior."""

    @pytest.mark.asyncio
    async def test_connect_success(self, meca_simulator):
        """Test successful connection."""
        result = await meca_simulator.connect("192.168.0.100")

        assert result is True
        assert meca_simulator._connected is True

        history = meca_simulator.get_command_history()
        assert ('connect', '192.168.0.100') in history

    @pytest.mark.asyncio
    async def test_disconnect(self, meca_simulator):
        """Test disconnection."""
        await meca_simulator.connect("192.168.0.100")
        result = await meca_simulator.disconnect()

        assert result is True
        assert meca_simulator._connected is False
        assert meca_simulator._activated is False
        assert meca_simulator._homed is False

    @pytest.mark.asyncio
    async def test_get_status(self, meca_simulator):
        """Test status retrieval."""
        status = await meca_simulator.get_status()

        assert 'activation_status' in status
        assert 'homing_status' in status
        assert 'error_status' in status
        assert status['activation_status'] is False
        assert status['homing_status'] is False
        assert status['error_status'] is False

    @pytest.mark.asyncio
    async def test_get_joints(self, meca_simulator):
        """Test joint position retrieval."""
        joints = await meca_simulator.get_joints()

        assert len(joints) == 6
        assert all(j == 0.0 for j in joints)

    @pytest.mark.asyncio
    async def test_set_joints(self, meca_simulator):
        """Test setting joint positions for test setup."""
        test_joints = [10.0, 20.0, 30.0, 40.0, 50.0, 60.0]
        meca_simulator.set_joints(test_joints)

        joints = await meca_simulator.get_joints()
        assert joints == test_joints


@pytest.mark.unit
class TestMecaActivationSequence:
    """Tests for Mecademic activation and homing sequence."""

    @pytest.mark.asyncio
    async def test_activation_requires_connection(self, meca_simulator):
        """Test activation fails without connection."""
        with pytest.raises(Exception, match="Not connected"):
            await meca_simulator.activate_robot()

    @pytest.mark.asyncio
    async def test_homing_requires_activation(self, meca_simulator):
        """Test homing fails without activation."""
        await meca_simulator.connect("192.168.0.100")

        with pytest.raises(Exception, match="Not activated"):
            await meca_simulator.home_robot()

    @pytest.mark.asyncio
    async def test_full_activation_sequence(self, meca_simulator):
        """Test complete activation sequence: connect -> activate -> home."""
        # Connect
        await meca_simulator.connect("192.168.0.100")
        assert meca_simulator._connected is True

        # Activate
        await meca_simulator.activate_robot()
        assert meca_simulator._activated is True

        # Home
        await meca_simulator.home_robot()
        assert meca_simulator._homed is True

        # Verify status
        status = await meca_simulator.get_status()
        assert status['activation_status'] is True
        assert status['homing_status'] is True

    @pytest.mark.asyncio
    async def test_wait_homed_records_timeout(self, meca_simulator):
        """Test wait_homed records timeout parameter."""
        await meca_simulator.connect("192.168.0.100")
        await meca_simulator.activate_robot()

        await meca_simulator.wait_homed(timeout=60.0)

        history = meca_simulator.get_command_history()
        assert ('wait_homed', 60.0) in history


@pytest.mark.unit
class TestMecaErrorHandling:
    """Tests for Mecademic error handling."""

    @pytest.mark.asyncio
    async def test_error_injection(self, meca_simulator):
        """Test error state injection."""
        meca_simulator.inject_error(error_code=1042)

        status = await meca_simulator.get_status()
        assert status['error_status'] is True
        assert status['error_code'] == 1042

    @pytest.mark.asyncio
    async def test_reset_error(self, meca_simulator):
        """Test error reset."""
        meca_simulator.inject_error(error_code=1042)
        await meca_simulator.reset_error()

        status = await meca_simulator.get_status()
        assert status['error_status'] is False
        assert status['error_code'] is None

    @pytest.mark.asyncio
    async def test_resume_motion(self, meca_simulator):
        """Test resuming motion after pause."""
        meca_simulator._paused = True
        await meca_simulator.resume_motion()

        status = await meca_simulator.get_status()
        assert status['pause_motion_status'] is False

    @pytest.mark.asyncio
    async def test_error_recovery_sequence(self, meca_with_error):
        """Test full error recovery sequence."""
        # Verify error state
        status = await meca_with_error.get_status()
        assert status['error_status'] is True

        # Reset error
        await meca_with_error.reset_error()

        # Verify recovery
        status = await meca_with_error.get_status()
        assert status['error_status'] is False

        # Verify history
        history = meca_with_error.get_command_history()
        assert ('reset_error',) in history


@pytest.mark.unit
class TestMecaDriverMock:
    """Tests for mock_meca_driver fixture."""

    @pytest.mark.asyncio
    async def test_mock_driver_has_simulator(self, mock_meca_driver):
        """Test mock driver exposes simulator for assertions."""
        assert hasattr(mock_meca_driver, '_simulator')
        assert isinstance(mock_meca_driver._simulator, type(mock_meca_driver._simulator))

    @pytest.mark.asyncio
    async def test_mock_driver_connect(self, mock_meca_driver):
        """Test mock driver connect passes through to simulator."""
        result = await mock_meca_driver.connect("192.168.0.100")
        assert result is True

        history = mock_meca_driver._simulator.get_command_history()
        assert ('connect', '192.168.0.100') in history

    def test_mock_driver_sync_commands(self, mock_meca_driver):
        """Test mock driver exposes sync movement commands."""
        mock_meca_driver.MovePose(100.0, 200.0, 50.0, 0.0, 0.0, 0.0)
        mock_meca_driver.Delay(1.0)
        mock_meca_driver.GripperClose()

        history = mock_meca_driver._simulator.get_command_history()
        assert ('MovePose', [100.0, 200.0, 50.0, 0.0, 0.0, 0.0]) in history
        assert ('Delay', 1.0) in history
        assert ('GripperClose',) in history
