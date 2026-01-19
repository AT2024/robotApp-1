"""
Tests for OT-2 protocol execution.
Verifies run lifecycle, status tracking, and error handling.
"""
import pytest


@pytest.mark.integration
class TestOT2SimulatorConnectivity:
    """Tests for OT-2 simulator connection behavior."""

    @pytest.mark.asyncio
    async def test_connect_success(self, ot2_simulator):
        """Test successful connection."""
        result = await ot2_simulator.connect()

        assert result is True
        assert ot2_simulator._connected is True

        history = ot2_simulator.get_command_history()
        assert ('connect',) in history

    @pytest.mark.asyncio
    async def test_disconnect(self, ot2_simulator):
        """Test disconnection."""
        await ot2_simulator.connect()
        result = await ot2_simulator.disconnect()

        assert result is True
        assert ot2_simulator._connected is False

    @pytest.mark.asyncio
    async def test_get_health(self, ot2_simulator):
        """Test health status retrieval."""
        await ot2_simulator.connect()
        health = await ot2_simulator.get_health()

        assert health['status'] == 'healthy'
        assert health['api_version'] == '2.0.0'
        assert 'robot_model' in health

    @pytest.mark.asyncio
    async def test_health_disconnected(self, ot2_simulator):
        """Test health status when disconnected."""
        health = await ot2_simulator.get_health()
        assert health['status'] == 'disconnected'


@pytest.mark.integration
class TestOT2RunLifecycle:
    """Tests for OT-2 protocol run lifecycle."""

    @pytest.mark.asyncio
    async def test_create_run(self, ot2_simulator):
        """Test creating a new run."""
        await ot2_simulator.connect()
        run = await ot2_simulator.create_run('test_protocol')

        assert 'id' in run
        assert run['protocol_id'] == 'test_protocol'
        assert run['status'] == 'idle'

    @pytest.mark.asyncio
    async def test_execute_run(self, ot2_simulator):
        """Test executing a run."""
        await ot2_simulator.connect()
        run = await ot2_simulator.create_run('test_protocol')
        run_id = run['id']

        result = await ot2_simulator.execute_run(run_id)

        assert result['status'] == 'running'

    @pytest.mark.asyncio
    async def test_execute_nonexistent_run(self, ot2_simulator):
        """Test executing a run that doesn't exist."""
        with pytest.raises(ValueError, match="not found"):
            await ot2_simulator.execute_run('nonexistent_run')

    @pytest.mark.asyncio
    async def test_get_run_status(self, ot2_simulator):
        """Test getting run status."""
        await ot2_simulator.connect()
        run = await ot2_simulator.create_run('test_protocol')
        run_id = run['id']

        status = await ot2_simulator.get_run_status(run_id)

        assert status['id'] == run_id
        assert 'status' in status

    @pytest.mark.asyncio
    async def test_get_runs(self, ot2_simulator):
        """Test getting all runs."""
        await ot2_simulator.connect()
        await ot2_simulator.create_run('protocol_1')
        await ot2_simulator.create_run('protocol_2')

        runs = await ot2_simulator.get_runs()

        assert len(runs) == 2


@pytest.mark.integration
class TestOT2Commands:
    """Tests for OT-2 robot commands."""

    @pytest.mark.asyncio
    async def test_home(self, ot2_simulator):
        """Test homing command."""
        await ot2_simulator.home()

        assert ot2_simulator._homed is True
        history = ot2_simulator.get_command_history()
        assert ('home',) in history

    @pytest.mark.asyncio
    async def test_stop(self, ot2_simulator):
        """Test stop command."""
        await ot2_simulator.connect()
        run = await ot2_simulator.create_run('test_protocol')
        await ot2_simulator.execute_run(run['id'])

        await ot2_simulator.stop()

        status = await ot2_simulator.get_run_status(run['id'])
        assert status['status'] == 'stopped'


@pytest.mark.integration
class TestOT2TestHelpers:
    """Tests for OT-2 simulator test helper methods."""

    @pytest.mark.asyncio
    async def test_complete_run(self, ot2_simulator):
        """Test marking a run as completed."""
        await ot2_simulator.connect()
        run = await ot2_simulator.create_run('test_protocol')
        run_id = run['id']

        ot2_simulator.complete_run(run_id)

        status = await ot2_simulator.get_run_status(run_id)
        assert status['status'] == 'succeeded'

    @pytest.mark.asyncio
    async def test_fail_run(self, ot2_simulator):
        """Test marking a run as failed."""
        await ot2_simulator.connect()
        run = await ot2_simulator.create_run('test_protocol')
        run_id = run['id']

        ot2_simulator.fail_run(run_id, "Pipette collision detected")

        status = await ot2_simulator.get_run_status(run_id)
        assert status['status'] == 'failed'
        assert status['error'] == "Pipette collision detected"

    @pytest.mark.asyncio
    async def test_clear_history(self, ot2_simulator):
        """Test clearing command history."""
        await ot2_simulator.connect()
        await ot2_simulator.create_run('test_protocol')
        await ot2_simulator.home()

        assert len(ot2_simulator.get_command_history()) > 0

        ot2_simulator.clear_history()

        assert len(ot2_simulator.get_command_history()) == 0

    @pytest.mark.asyncio
    async def test_inject_error(self, ot2_simulator):
        """Test error injection."""
        ot2_simulator.inject_error()
        assert ot2_simulator._error_state is True


@pytest.mark.integration
class TestOT2DriverMock:
    """Tests for mock_ot2_driver fixture."""

    @pytest.mark.asyncio
    async def test_mock_driver_has_simulator(self, mock_ot2_driver):
        """Test mock driver exposes simulator for assertions."""
        assert hasattr(mock_ot2_driver, '_simulator')

    @pytest.mark.asyncio
    async def test_mock_driver_passthrough(self, mock_ot2_driver):
        """Test mock driver passes through to simulator."""
        await mock_ot2_driver.connect()
        run = await mock_ot2_driver.create_run('test_protocol')

        history = mock_ot2_driver._simulator.get_command_history()
        assert ('connect',) in history
        assert ('create_run', 'test_protocol') in history


@pytest.mark.integration
class TestOT2FullWorkflow:
    """Test complete OT-2 workflow scenarios."""

    @pytest.mark.asyncio
    async def test_complete_protocol_execution(self, ot2_simulator):
        """Test complete protocol execution workflow."""
        # Connect
        await ot2_simulator.connect()
        assert ot2_simulator._connected

        # Home
        await ot2_simulator.home()
        assert ot2_simulator._homed

        # Create and execute run
        run = await ot2_simulator.create_run('spreading_protocol')
        run_id = run['id']
        await ot2_simulator.execute_run(run_id)

        # Simulate completion
        ot2_simulator.complete_run(run_id)

        # Verify final state
        status = await ot2_simulator.get_run_status(run_id)
        assert status['status'] == 'succeeded'

        # Disconnect
        await ot2_simulator.disconnect()
        assert not ot2_simulator._connected

    @pytest.mark.asyncio
    async def test_multiple_consecutive_runs(self, ot2_simulator):
        """Test multiple protocol runs in sequence."""
        await ot2_simulator.connect()

        for i in range(3):
            run = await ot2_simulator.create_run(f'protocol_{i}')
            await ot2_simulator.execute_run(run['id'])
            ot2_simulator.complete_run(run['id'])

        runs = await ot2_simulator.get_runs()
        assert len(runs) == 3
        assert all(r['status'] == 'succeeded' for r in runs)
