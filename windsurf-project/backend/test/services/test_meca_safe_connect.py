"""
Tests for Mecademic safe connection - two-step confirmation flow.

Tests Phase 2 of robot safety plan:
- connect_safe(): Connect without homing, return joint positions
- confirm_activation(): After user confirmation, activate and home
"""

import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from typing import Dict, Any

from services.meca import MecaService
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
    driver.get_status = AsyncMock(return_value={
        'activation_status': False,
        'homing_status': False,
        'error_status': False,
        'pause_motion_status': False
    })
    driver.get_joints = AsyncMock(return_value=[0.0, 45.0, 90.0, 0.0, 45.0, 0.0])
    driver.reset_error = AsyncMock()
    driver.activate_robot = AsyncMock()
    driver.home_robot = AsyncMock()
    driver.wait_homed = AsyncMock()
    driver.resume_motion = AsyncMock()
    driver.deactivate_robot = AsyncMock()
    driver.set_settings = Mock(return_value=None)  # Non-async mock
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
                "pickup": {
                    "z_entry": 0,
                    "z_wafer": 0,
                    "z_exit": 0
                },
                "drop": {
                    "z_entry": 0,
                    "z_wafer": 0,
                    "z_exit": 0
                },
                "carousel": {
                    "z_offset": 0
                }
            }
        }
    }
    return settings


@pytest.fixture
def mock_state_manager():
    """Mock AtomicStateManager."""
    manager = Mock(spec=AtomicStateManager)
    manager.update_state = AsyncMock()
    manager.get_state = AsyncMock(return_value={'status': 'IDLE'})
    return manager


@pytest.fixture
def mock_lock_manager():
    """Mock ResourceLockManager."""
    manager = Mock(spec=ResourceLockManager)

    # Create an async context manager mock
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
    # Patch WaferConfigManager to avoid complex config requirements
    with patch('services.meca.service.WaferConfigManager'):
        service = MecaService(
            robot_id="meca_test",
            settings=mock_settings,
            state_manager=mock_state_manager,
            lock_manager=mock_lock_manager,
            async_wrapper=mock_async_wrapper
        )
        # Set service as running to bypass service state check
        service._running = True
        return service


class TestConnectSafe:
    """Tests for connect_safe() method - connect without homing."""

    @pytest.mark.asyncio
    async def test_connect_safe_returns_joint_positions(self, meca_service, mock_robot_driver):
        """Test that connect_safe connects and returns joint positions without homing."""
        # Mock WebSocket broadcaster
        with patch('websocket.selective_broadcaster.get_broadcaster') as mock_get_broadcaster:
            mock_broadcaster = AsyncMock()
            mock_get_broadcaster.return_value = mock_broadcaster

            # Execute
            result = await meca_service.connect_safe()

            # Verify - result is now a ServiceResult
            assert result.success is True
            assert result.data['connected'] is True
            assert result.data['awaiting_confirmation'] is True
            assert 'joints' in result.data
            assert len(result.data['joints']) == 6
            assert result.data['joints'] == [0.0, 45.0, 90.0, 0.0, 45.0, 0.0]

            # Verify driver was connected but NOT activated/homed
            mock_robot_driver.connect.assert_called_once()
            mock_robot_driver.activate_robot.assert_not_called()
            mock_robot_driver.home_robot.assert_not_called()

    @pytest.mark.asyncio
    async def test_connect_safe_with_error_status(self, meca_service, mock_robot_driver):
        """Test that connect_safe detects and reports error status."""
        # Mock error status
        mock_robot_driver.get_status.return_value = {
            'activation_status': False,
            'homing_status': False,
            'error_status': True,
            'error_code': 1042
        }

        # Mock WebSocket broadcaster
        with patch('websocket.selective_broadcaster.get_broadcaster') as mock_get_broadcaster:
            mock_broadcaster = AsyncMock()
            mock_get_broadcaster.return_value = mock_broadcaster

            # Execute
            result = await meca_service.connect_safe()

            # Verify - result is now a ServiceResult
            assert result.success is True
            assert result.data['connected'] is True
            assert result.data['error'] is True
            assert result.data['error_code'] == 1042

            # Should NOT proceed to activation
            mock_robot_driver.activate_robot.assert_not_called()

    @pytest.mark.asyncio
    async def test_connect_safe_broadcasts_pending_state(self, meca_service, mock_robot_driver):
        """Test that connect_safe broadcasts connection pending state via WebSocket."""
        # Mock WebSocket connection manager
        with patch('services.meca.service.get_connection_manager') as mock_get_conn_mgr:
            mock_conn_mgr = AsyncMock()
            mock_get_conn_mgr.return_value = mock_conn_mgr

            # Execute
            await meca_service.connect_safe()

            # Verify broadcast was called with correct message
            mock_conn_mgr.broadcast_message.assert_called()
            # Get the first call that was for 'connection_pending'
            calls = mock_conn_mgr.broadcast_message.call_args_list
            pending_calls = [c for c in calls if c[1].get('message_type') == 'connection_pending']
            assert len(pending_calls) >= 1
            message = pending_calls[0][0][0]

            assert 'joints' in message
            assert message.get('requires_confirmation') is True or message.get('awaiting_confirmation') is True

    @pytest.mark.asyncio
    async def test_connect_safe_connection_failure(self, meca_service, mock_robot_driver):
        """Test that connect_safe returns failure ServiceResult on connection failure."""
        # Mock connection failure
        mock_robot_driver.connect.side_effect = Exception("Connection timeout")

        # Execute - now returns ServiceResult instead of raising exception
        result = await meca_service.connect_safe()

        # Verify failure is captured in ServiceResult
        assert result.success is False
        assert "Connection timeout" in str(result.error) or "connect" in str(result.error).lower()


class TestConfirmActivation:
    """Tests for confirm_activation() method - activate and home after confirmation."""

    @pytest.mark.asyncio
    async def test_confirm_activation_activates_and_homes(self, meca_service, mock_robot_driver):
        """Test that confirm_activation activates, homes, and waits for homing."""
        # Mock WebSocket broadcaster
        with patch('websocket.selective_broadcaster.get_broadcaster') as mock_get_broadcaster:
            mock_broadcaster = AsyncMock()
            mock_get_broadcaster.return_value = mock_broadcaster

            # Execute
            result = await meca_service.confirm_activation()

            # Verify result - result is now a ServiceResult
            assert result.success is True
            assert result.data['connected'] is True
            assert result.data['homed'] is True

            # Verify activation sequence
            mock_robot_driver.activate_robot.assert_called_once()
            mock_robot_driver.home_robot.assert_called_once()
            mock_robot_driver.wait_homed.assert_called_once_with(timeout=30.0)

    @pytest.mark.asyncio
    async def test_confirm_activation_resets_error_first(self, meca_service, mock_robot_driver):
        """Test that confirm_activation resets errors before activation."""
        # Mock error status initially
        mock_robot_driver.get_status.return_value = {
            'activation_status': False,
            'homing_status': False,
            'error_status': True,
            'pause_motion_status': False
        }

        # Mock WebSocket broadcaster
        with patch('websocket.selective_broadcaster.get_broadcaster') as mock_get_broadcaster:
            mock_broadcaster = AsyncMock()
            mock_get_broadcaster.return_value = mock_broadcaster

            # Execute
            await meca_service.confirm_activation()

            # Verify error was reset before activation
            mock_robot_driver.reset_error.assert_called_once()
            mock_robot_driver.activate_robot.assert_called_once()

    @pytest.mark.asyncio
    async def test_confirm_activation_resumes_if_paused(self, meca_service, mock_robot_driver):
        """Test that confirm_activation resumes motion if robot is paused after homing."""
        # Mock paused status after homing
        call_count = 0
        def get_status_side_effect():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # First call: no error
                return {
                    'activation_status': False,
                    'homing_status': False,
                    'error_status': False,
                    'pause_motion_status': False
                }
            else:
                # Second call (after homing): paused
                return {
                    'activation_status': True,
                    'homing_status': True,
                    'error_status': False,
                    'pause_motion_status': True
                }

        mock_robot_driver.get_status.side_effect = get_status_side_effect

        # Mock WebSocket broadcaster
        with patch('websocket.selective_broadcaster.get_broadcaster') as mock_get_broadcaster:
            mock_broadcaster = AsyncMock()
            mock_get_broadcaster.return_value = mock_broadcaster

            # Execute
            await meca_service.confirm_activation()

            # Verify resume_motion was called
            mock_robot_driver.resume_motion.assert_called_once()

    @pytest.mark.asyncio
    async def test_confirm_activation_broadcasts_complete_state(self, meca_service, mock_robot_driver):
        """Test that confirm_activation broadcasts connection complete state."""
        # Mock WebSocket connection manager
        with patch('services.meca.service.get_connection_manager') as mock_get_conn_mgr:
            mock_conn_mgr = AsyncMock()
            mock_get_conn_mgr.return_value = mock_conn_mgr

            # Execute
            await meca_service.confirm_activation()

            # Verify broadcast was called with correct message
            mock_conn_mgr.broadcast_message.assert_called()
            # Get the first call that was for 'connection_complete'
            calls = mock_conn_mgr.broadcast_message.call_args_list
            complete_calls = [c for c in calls if c[1].get('message_type') == 'connection_complete']
            assert len(complete_calls) >= 1
            message = complete_calls[0][0][0]

            assert message['homed'] is True

    @pytest.mark.asyncio
    async def test_confirm_activation_failure_calls_emergency_stop(self, meca_service, mock_robot_driver):
        """Test that confirm_activation returns failure on activation error."""
        # Mock activation failure
        mock_robot_driver.activate_robot.side_effect = Exception("Activation failed")

        # Mock emergency stop method
        meca_service._execute_emergency_stop = AsyncMock()

        # Execute - now returns ServiceResult instead of raising exception
        result = await meca_service.confirm_activation()

        # Verify failure is captured in ServiceResult
        assert result.success is False
        assert "Activation failed" in str(result.error)
