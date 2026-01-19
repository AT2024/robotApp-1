"""
Tests for Mecademic disconnect_safe - graceful disconnection.

Tests Phase 4 of robot safety plan:
- disconnect_safe(): Gracefully disconnect from robot
- Deactivates robot before disconnect
- Handles disconnect when not connected
"""

import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from typing import Dict, Any

from services.meca_service import MecaService
from core.state_manager import AtomicStateManager
from core.resource_lock import ResourceLockManager
from core.async_robot_wrapper import AsyncRobotWrapper
from core.settings import RoboticsSettings
from core.exceptions import HardwareError


@pytest.fixture
def mock_robot_driver():
    """Mock Mecademic robot driver with all required methods."""
    driver = AsyncMock()
    driver.connect = AsyncMock(return_value=True)
    driver.disconnect = AsyncMock(return_value=True)
    driver.is_connected = AsyncMock(return_value=True)
    driver.get_status = AsyncMock(return_value={
        'activation_status': True,
        'homing_status': True,
        'error_status': False,
        'pause_motion_status': False
    })
    driver.deactivate_robot = AsyncMock()
    driver.set_settings = Mock(return_value=None)
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
        "movement_params": {
            "gap_wafers": 2.7
        },
        "sequence_config": {
            "version": "1.0",
            "operation_offsets": {
                "pickup": {"z_entry": 0, "z_wafer": 0, "z_exit": 0},
                "drop": {"z_entry": 0, "z_wafer": 0, "z_exit": 0},
                "carousel": {"z_offset": 0}
            }
        }
    }
    return settings


@pytest.fixture
def mock_state_manager():
    """Mock AtomicStateManager."""
    manager = Mock(spec=AtomicStateManager)
    manager.update_state = AsyncMock()
    manager.get_state = AsyncMock(return_value={'status': 'CONNECTED'})
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
    with patch('services.meca_service.WaferConfigManager'):
        service = MecaService(
            robot_id="meca_test",
            settings=mock_settings,
            state_manager=mock_state_manager,
            lock_manager=mock_lock_manager,
            async_wrapper=mock_async_wrapper
        )
        return service


class TestDisconnectSafe:
    """Tests for disconnect_safe() method - graceful disconnection."""

    @pytest.mark.asyncio
    async def test_disconnect_safe_deactivates_before_disconnect(self, meca_service, mock_robot_driver):
        """Test that disconnect_safe deactivates robot before disconnecting."""
        # Mock WebSocket broadcaster
        with patch('websocket.selective_broadcaster.get_broadcaster') as mock_get_broadcaster:
            mock_broadcaster = AsyncMock()
            mock_get_broadcaster.return_value = mock_broadcaster

            # Execute
            result = await meca_service.disconnect_safe()

            # Verify result
            assert result['disconnected'] is True
            assert result['was_connected'] is True

            # Verify deactivation before disconnect
            mock_robot_driver.deactivate_robot.assert_called_once()
            mock_robot_driver.disconnect.assert_called_once()

            # Verify order: deactivate should be called before disconnect
            deactivate_call_order = mock_robot_driver.deactivate_robot.call_count
            disconnect_call_order = mock_robot_driver.disconnect.call_count
            assert deactivate_call_order == 1
            assert disconnect_call_order == 1

    @pytest.mark.asyncio
    async def test_disconnect_safe_when_not_connected(self, meca_service, mock_robot_driver):
        """Test that disconnect_safe handles case when robot is not connected."""
        # Mock not connected state
        mock_robot_driver.is_connected.return_value = False

        # Mock WebSocket broadcaster
        with patch('websocket.selective_broadcaster.get_broadcaster') as mock_get_broadcaster:
            mock_broadcaster = AsyncMock()
            mock_get_broadcaster.return_value = mock_broadcaster

            # Execute
            result = await meca_service.disconnect_safe()

            # Verify result
            assert result['disconnected'] is True
            assert result['was_connected'] is False

            # Verify no deactivation or disconnect calls
            mock_robot_driver.deactivate_robot.assert_not_called()
            mock_robot_driver.disconnect.assert_not_called()

    @pytest.mark.asyncio
    async def test_disconnect_safe_updates_state(self, meca_service, mock_robot_driver, mock_state_manager):
        """Test that disconnect_safe updates state to DISCONNECTED."""
        # Mock WebSocket broadcaster
        with patch('websocket.selective_broadcaster.get_broadcaster') as mock_get_broadcaster:
            mock_broadcaster = AsyncMock()
            mock_get_broadcaster.return_value = mock_broadcaster

            # Execute
            await meca_service.disconnect_safe()

            # Verify state was updated to DISCONNECTED
            mock_state_manager.update_state.assert_called()
            call_args = mock_state_manager.update_state.call_args
            assert "DISCONNECTED" in str(call_args) or call_args[0][1].get('status') == 'DISCONNECTED'

    @pytest.mark.asyncio
    async def test_disconnect_safe_broadcasts_disconnected_state(self, meca_service, mock_robot_driver):
        """Test that disconnect_safe broadcasts disconnected state via WebSocket."""
        # Mock WebSocket broadcaster
        with patch('websocket.selective_broadcaster.get_broadcaster') as mock_get_broadcaster:
            mock_broadcaster = AsyncMock()
            mock_get_broadcaster.return_value = mock_broadcaster

            # Execute
            await meca_service.disconnect_safe()

            # Verify broadcast was called
            mock_broadcaster.broadcast_message.assert_called_once()
            call_args = mock_broadcaster.broadcast_message.call_args
            message = call_args[0][0]

            assert message['type'] == 'disconnected'
            assert message['disconnected'] is True

    @pytest.mark.asyncio
    async def test_disconnect_safe_forces_disconnect_on_error(self, meca_service, mock_robot_driver):
        """Test that disconnect_safe forces disconnect even if deactivate fails."""
        # Mock deactivation failure
        mock_robot_driver.deactivate_robot.side_effect = Exception("Deactivation failed")

        # Mock WebSocket broadcaster
        with patch('websocket.selective_broadcaster.get_broadcaster') as mock_get_broadcaster:
            mock_broadcaster = AsyncMock()
            mock_get_broadcaster.return_value = mock_broadcaster

            # Execute - should still disconnect despite deactivation failure
            with pytest.raises(HardwareError):
                await meca_service.disconnect_safe()

            # Verify disconnect was still called (forced disconnect on error)
            mock_robot_driver.disconnect.assert_called_once()
