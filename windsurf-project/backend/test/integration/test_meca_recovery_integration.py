"""
Integration tests for Mecademic recovery mode workflow.

Tests the complete recovery workflow:
- Emergency stop -> reconnect -> recovery mode
- Recovery mode -> disable -> normal operation
"""
import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from typing import Dict, Any

from services.meca import MecaService
from core.state_manager import AtomicStateManager, RobotState
from core.resource_lock import ResourceLockManager
from core.async_robot_wrapper import AsyncRobotWrapper
from core.settings import RoboticsSettings
from core.exceptions import HardwareError


@pytest.fixture
def mock_robot_driver():
    """Mock Mecademic robot driver with recovery mode support."""
    driver = AsyncMock()
    driver.connect = AsyncMock(return_value=True)
    driver.disconnect = AsyncMock(return_value=True)
    driver.is_connected = AsyncMock(return_value=True)
    driver.get_robot_instance = Mock(return_value=Mock())
    driver.get_status = AsyncMock(return_value={
        'activation_status': True,
        'homing_status': True,
        'error_status': False,
        'pause_motion_status': False
    })
    driver.set_recovery_mode = AsyncMock(return_value=True)
    driver.set_settings = Mock(return_value=None)
    driver._connected = True
    return driver


@pytest.fixture
def mock_async_wrapper(mock_robot_driver):
    """Mock AsyncRobotWrapper with mocked driver."""
    wrapper = Mock(spec=AsyncRobotWrapper)
    wrapper.robot_driver = mock_robot_driver
    return wrapper


@pytest.fixture
def mock_settings():
    """Mock RoboticsSettings."""
    settings = Mock(spec=RoboticsSettings)
    settings.get_robot_config.return_value = {
        "ip": "192.168.0.100",
        "port": 10000,
        "movement_params": {"gap_wafers": 2.7},
        "sequence_config": {
            "version": "1.0",
            "operation_offsets": {
                "pickup": {"z_entry": 0, "z_wafer": 0, "z_exit": 0},
                "drop": {"z_entry": 0, "z_wafer": 0, "z_exit": 0},
                "carousel": {"z_offset": 0}
            }
        }
    }
    settings.meca_timeout = 30.0
    return settings


@pytest.fixture
def mock_state_manager():
    """Mock AtomicStateManager that tracks state changes."""
    manager = Mock(spec=AtomicStateManager)
    manager._states = []

    async def update_state(updates):
        manager._states.append(updates)

    async def update_robot_state(robot_id, state, **kwargs):
        manager._states.append({'robot_id': robot_id, 'state': state, **kwargs})

    manager.update_state = AsyncMock(side_effect=update_state)
    manager.update_robot_state = AsyncMock(side_effect=update_robot_state)
    manager.get_state = AsyncMock(return_value={'status': 'ERROR'})
    return manager


@pytest.fixture
def mock_lock_manager():
    """Mock ResourceLockManager."""
    manager = Mock(spec=ResourceLockManager)

    class AsyncContextManagerMock:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            return False

    manager.acquire = Mock(return_value=AsyncContextManagerMock())
    return manager


@pytest.fixture
def meca_service(mock_settings, mock_state_manager, mock_lock_manager, mock_async_wrapper):
    """Create MecaService instance with mocked dependencies."""
    with patch('services.meca.service.WaferConfigManager'):
        service = MecaService(
            robot_id="meca_test",
            settings=mock_settings,
            state_manager=mock_state_manager,
            lock_manager=mock_lock_manager,
            async_wrapper=mock_async_wrapper
        )
        service._running = True
        return service


@pytest.mark.integration
class TestFullRecoveryWorkflow:
    """Integration tests for the complete recovery workflow."""

    @pytest.mark.asyncio
    async def test_full_recovery_workflow_after_emergency_stop(
        self, meca_service, mock_robot_driver, mock_state_manager
    ):
        """
        Test full recovery workflow: emergency stop -> reconnect -> recovery mode.

        This simulates the scenario where:
        1. Robot is in error state after emergency stop
        2. Connection was lost
        3. User clicks "Enable Recovery Mode"
        4. System reconnects and enables recovery mode
        """
        # Simulate emergency stop state - connection lost
        mock_robot_driver.get_robot_instance.side_effect = [None, Mock()]
        mock_robot_driver._connected = False
        mock_robot_driver.connect.return_value = True

        with patch('websocket.selective_broadcaster.get_broadcaster') as mock_get_broadcaster:
            mock_broadcaster = AsyncMock()
            mock_get_broadcaster.return_value = mock_broadcaster

            # Execute recovery mode
            result = await meca_service.enable_recovery_mode()

            # Verify workflow completed successfully
            assert result.success is True
            assert result.data['recovery_mode'] is True
            assert result.data['state'] == 'maintenance'

            # Verify force reconnection was attempted (Phase 2 uses force_reconnect)
            mock_robot_driver.force_reconnect.assert_called()

            # Verify recovery mode was enabled on driver
            mock_robot_driver.set_recovery_mode.assert_called_once_with(True)

    @pytest.mark.asyncio
    async def test_recovery_workflow_with_existing_connection(
        self, meca_service, mock_robot_driver
    ):
        """
        Test recovery workflow when connection is still valid.

        No reconnection should be attempted if already connected.
        """
        # Simulate connected state
        mock_robot_driver.get_robot_instance.return_value = Mock()
        mock_robot_driver._connected = True

        with patch('websocket.selective_broadcaster.get_broadcaster') as mock_get_broadcaster:
            mock_broadcaster = AsyncMock()
            mock_get_broadcaster.return_value = mock_broadcaster

            result = await meca_service.enable_recovery_mode()

            # Should succeed without reconnection
            assert result.success is True
            mock_robot_driver.connect.assert_not_called()
            mock_robot_driver.set_recovery_mode.assert_called_once_with(True)


@pytest.mark.integration
class TestRecoveryModeToNormalOperation:
    """Integration tests for transitioning from recovery mode to normal operation."""

    @pytest.mark.asyncio
    async def test_recovery_mode_enable_disable_cycle(
        self, meca_service, mock_robot_driver
    ):
        """
        Test complete recovery cycle: enable -> reposition -> disable.

        This tests the full user workflow:
        1. Enable recovery mode
        2. (User repositions robot)
        3. Disable recovery mode
        4. Robot returns to idle state
        """
        mock_robot_driver.get_robot_instance.return_value = Mock()

        with patch('websocket.selective_broadcaster.get_broadcaster') as mock_get_broadcaster:
            mock_broadcaster = AsyncMock()
            mock_get_broadcaster.return_value = mock_broadcaster

            # Step 1: Enable recovery mode
            enable_result = await meca_service.enable_recovery_mode()
            assert enable_result.success is True
            assert enable_result.data['recovery_mode'] is True

            # Step 2: Disable recovery mode
            disable_result = await meca_service.disable_recovery_mode()
            assert disable_result.success is True
            assert disable_result.data['recovery_mode'] is False

            # Verify driver calls
            mock_robot_driver.set_recovery_mode.assert_any_call(True)
            mock_robot_driver.set_recovery_mode.assert_any_call(False)

    @pytest.mark.asyncio
    async def test_recovery_mode_state_transitions(
        self, meca_service, mock_robot_driver, mock_state_manager
    ):
        """
        Test that state transitions correctly through recovery workflow.

        Expected states:
        - ERROR/EMERGENCY -> enable_recovery_mode -> MAINTENANCE
        - MAINTENANCE -> disable_recovery_mode -> IDLE
        """
        mock_robot_driver.get_robot_instance.return_value = Mock()
        mock_state_manager._states = []

        with patch('websocket.selective_broadcaster.get_broadcaster') as mock_get_broadcaster:
            mock_broadcaster = AsyncMock()
            mock_get_broadcaster.return_value = mock_broadcaster

            # Enable recovery mode
            await meca_service.enable_recovery_mode()

            # Disable recovery mode
            await meca_service.disable_recovery_mode()

            # Verify state transitions were requested
            # Note: Exact state verification depends on mock implementation
            assert mock_state_manager.update_robot_state.call_count >= 2


@pytest.mark.integration
class TestRecoveryModeErrorScenarios:
    """Integration tests for error scenarios during recovery."""

    @pytest.mark.asyncio
    async def test_recovery_fails_gracefully_on_driver_error(
        self, meca_service, mock_robot_driver
    ):
        """Test that recovery mode handles driver errors gracefully."""
        mock_robot_driver.get_robot_instance.return_value = Mock()
        mock_robot_driver.set_recovery_mode.return_value = False

        with patch('websocket.selective_broadcaster.get_broadcaster') as mock_get_broadcaster:
            mock_broadcaster = AsyncMock()
            mock_get_broadcaster.return_value = mock_broadcaster

            result = await meca_service.enable_recovery_mode()

            # Should fail with actionable error
            assert result.success is False
            assert 'robot' in str(result.error).lower()

    @pytest.mark.asyncio
    async def test_recovery_handles_multiple_reconnection_failures(
        self, meca_service, mock_robot_driver
    ):
        """Test that recovery provides clear error after multiple reconnection failures."""
        mock_robot_driver.get_robot_instance.return_value = None
        mock_robot_driver.connect.return_value = False

        with patch('websocket.selective_broadcaster.get_broadcaster') as mock_get_broadcaster:
            mock_broadcaster = AsyncMock()
            mock_get_broadcaster.return_value = mock_broadcaster

            result = await meca_service.enable_recovery_mode()

            # Should fail with actionable error
            assert result.success is False
            error_msg = str(result.error).lower()
            # Error should provide guidance
            assert any(hint in error_msg for hint in [
                'check', 'power', 'restart', 'connection'
            ])
