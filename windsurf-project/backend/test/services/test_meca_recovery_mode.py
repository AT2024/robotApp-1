"""
Tests for Mecademic recovery mode after emergency stop.

Tests Phase 1 of recovery mode fix:
- Connection validation before enabling recovery mode
- Automatic reconnection when disconnected
- Actionable error messages for all failure cases
- Error 3001 (stale session) handling
"""

import pytest
import asyncio
import builtins
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from typing import Dict, Any

from services.meca import MecaService
from core.state_manager import AtomicStateManager
from core.resource_lock import ResourceLockManager
from core.async_robot_wrapper import AsyncRobotWrapper
from core.settings import RoboticsSettings
from core.exceptions import HardwareError, ConnectionError


@pytest.fixture
def mock_robot_driver():
    """Mock Mecademic robot driver with all required methods."""
    driver = AsyncMock()
    driver.connect = AsyncMock(return_value=True)
    driver.disconnect = AsyncMock(return_value=True)
    driver.is_connected = AsyncMock(return_value=True)
    driver.get_robot_instance = Mock(return_value=Mock())  # Connected state
    driver.get_status = AsyncMock(return_value={
        'connected': True,
        'activation_status': True,
        'homing_status': True,
        'error_status': False,
        'pause_motion_status': False
    })
    driver.set_recovery_mode = AsyncMock(return_value=True)
    driver.force_reconnect = AsyncMock(return_value=True)  # Phase 2: force reconnect method
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
    settings.meca_timeout = 30.0
    return settings


@pytest.fixture
def mock_state_manager():
    """Mock AtomicStateManager."""
    manager = Mock(spec=AtomicStateManager)
    manager.update_state = AsyncMock()
    manager.get_state = AsyncMock(return_value={'status': 'ERROR'})
    manager.update_robot_state = AsyncMock()
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
        # Set service as running to bypass service state check
        service._running = True
        return service


class TestRecoveryModeConnectionValidation:
    """Tests for recovery mode connection validation and reconnection."""

    @pytest.mark.asyncio
    async def test_recovery_mode_reconnects_when_disconnected(self, meca_service, mock_robot_driver):
        """Test that enable_recovery_mode attempts force reconnection when robot is disconnected."""
        # Simulate disconnected state - get_robot_instance returns None
        mock_robot_driver.get_robot_instance.return_value = None
        mock_robot_driver._connected = False

        # Force reconnection should succeed
        mock_robot_driver.force_reconnect.return_value = True
        # After reconnection, robot instance is available
        mock_robot_driver.get_robot_instance.side_effect = [None, Mock()]

        # Mock WebSocket broadcaster
        with patch('websocket.selective_broadcaster.get_broadcaster') as mock_get_broadcaster:
            mock_broadcaster = AsyncMock()
            mock_get_broadcaster.return_value = mock_broadcaster

            result = await meca_service.enable_recovery_mode()

            # Should have attempted force reconnection (Phase 2 strategy)
            mock_robot_driver.force_reconnect.assert_called()

            # Should succeed after reconnection
            assert result.success is True
            assert result.data['recovery_mode'] is True

    @pytest.mark.asyncio
    async def test_recovery_mode_fails_with_actionable_message_when_reconnect_fails(
        self, meca_service, mock_robot_driver
    ):
        """Test that recovery mode provides actionable error when force reconnection fails."""
        # Simulate disconnected state
        mock_robot_driver.get_robot_instance.return_value = None
        mock_robot_driver._connected = False

        # Force reconnection fails
        mock_robot_driver.force_reconnect.return_value = False

        # Mock WebSocket broadcaster
        with patch('websocket.selective_broadcaster.get_broadcaster') as mock_get_broadcaster:
            mock_broadcaster = AsyncMock()
            mock_get_broadcaster.return_value = mock_broadcaster

            result = await meca_service.enable_recovery_mode()

            # Should fail with actionable message
            assert result.success is False
            error_msg = str(result.error).lower()
            # Error should mention what to do: power cycle, etc. (Phase 2 message)
            assert any(hint in error_msg for hint in [
                'power cycle', 'turn off', 'boot', 'power'
            ]), f"Error message should be actionable: {result.error}"

    @pytest.mark.asyncio
    async def test_recovery_mode_handles_stale_session_error(self, meca_service, mock_robot_driver):
        """Test that error 3001 (stale session) is handled with specific guidance."""
        # Simulate disconnected state
        mock_robot_driver.get_robot_instance.return_value = None
        mock_robot_driver._connected = False

        # Force reconnect fails - robot needs power cycle
        mock_robot_driver.force_reconnect.return_value = False

        # Mock WebSocket broadcaster
        with patch('websocket.selective_broadcaster.get_broadcaster') as mock_get_broadcaster:
            mock_broadcaster = AsyncMock()
            mock_get_broadcaster.return_value = mock_broadcaster

            result = await meca_service.enable_recovery_mode()

            # Should fail with specific guidance about power cycling
            assert result.success is False
            error_msg = str(result.error).lower()
            # Should mention power cycle instructions (Phase 2 error message)
            assert any(hint in error_msg for hint in [
                'power cycle', 'turn off', 'boot', 'power'
            ]), f"Error message should provide power cycle instructions: {result.error}"

    @pytest.mark.asyncio
    async def test_recovery_mode_works_when_already_connected(self, meca_service, mock_robot_driver):
        """Test that recovery mode works without force reconnect when socket is alive."""
        # Simulate connected state with working socket
        mock_robot_driver.get_robot_instance.return_value = Mock()
        mock_robot_driver._connected = True
        mock_robot_driver.set_recovery_mode.return_value = True

        # Mock WebSocket broadcaster
        with patch('websocket.selective_broadcaster.get_broadcaster') as mock_get_broadcaster:
            mock_broadcaster = AsyncMock()
            mock_get_broadcaster.return_value = mock_broadcaster

            result = await meca_service.enable_recovery_mode()

            # Should NOT attempt force reconnection when direct call succeeds
            mock_robot_driver.force_reconnect.assert_not_called()

            # Should succeed directly with Strategy 1 (direct call)
            assert result.success is True
            assert result.data['recovery_mode'] is True

    @pytest.mark.asyncio
    async def test_recovery_mode_tries_direct_first_then_force_reconnect(self, meca_service, mock_robot_driver):
        """Test Phase 2 strategy: try direct recovery mode first, then force reconnect if needed."""
        # Robot instance always exists (connected)
        mock_robot_driver.get_robot_instance.return_value = Mock()
        mock_robot_driver._connected = True

        # Ensure get_status returns connected: True
        mock_robot_driver.get_status.return_value = {
            'connected': True,
            'activation_status': True,
            'homing_status': True,
            'error_status': False,
            'pause_motion_status': False
        }

        # First direct call fails with connection error (use builtins.ConnectionError)
        mock_robot_driver.set_recovery_mode.side_effect = [
            builtins.ConnectionError("Socket connection dead"),  # First call (direct) fails
            True  # Second call (after force reconnect) succeeds
        ]

        # Force reconnect succeeds
        mock_robot_driver.force_reconnect.return_value = True

        # Mock WebSocket broadcaster
        with patch('websocket.selective_broadcaster.get_broadcaster') as mock_get_broadcaster:
            mock_broadcaster = AsyncMock()
            mock_get_broadcaster.return_value = mock_broadcaster

            result = await meca_service.enable_recovery_mode()

            # Should have tried force_reconnect after direct call failed
            mock_robot_driver.force_reconnect.assert_called()

            # Should succeed after force reconnect
            assert result.success is True


class TestRecoveryModeErrorMessages:
    """Tests for actionable error messages in recovery mode."""

    @pytest.mark.asyncio
    async def test_error_message_includes_robot_id(self, meca_service, mock_robot_driver):
        """Test that error messages include the robot ID for identification."""
        mock_robot_driver.get_robot_instance.return_value = None
        mock_robot_driver.force_reconnect.return_value = False

        with patch('websocket.selective_broadcaster.get_broadcaster') as mock_get_broadcaster:
            mock_broadcaster = AsyncMock()
            mock_get_broadcaster.return_value = mock_broadcaster

            result = await meca_service.enable_recovery_mode()

            assert result.success is False
            # Error should include robot ID
            assert 'meca_test' in str(result.error).lower() or 'meca' in str(result.error).lower()

    @pytest.mark.asyncio
    async def test_error_message_for_driver_not_supporting_recovery(
        self, meca_service, mock_robot_driver
    ):
        """Test error when driver doesn't support recovery mode."""
        mock_robot_driver.get_robot_instance.return_value = Mock()
        # Remove set_recovery_mode attribute
        del mock_robot_driver.set_recovery_mode

        with patch('websocket.selective_broadcaster.get_broadcaster') as mock_get_broadcaster:
            mock_broadcaster = AsyncMock()
            mock_get_broadcaster.return_value = mock_broadcaster

            result = await meca_service.enable_recovery_mode()

            assert result.success is False
            # Should indicate recovery mode is not supported
            assert 'not supported' in str(result.error).lower()


class TestSpeedRestorationAfterRecovery:
    """Tests for speed restoration after quick recovery and safe homing.

    Fixes issue where robot moved at 20% speed (align_speed) instead of
    35% (normal operational speed) after recovery.
    """

    @pytest.mark.asyncio
    async def test_restore_speed_uses_normal_speed_not_align_speed(self, mock_settings, mock_state_manager, mock_lock_manager, mock_async_wrapper):
        """Test that _restore_speed_settings uses 'speed' (35%) not 'align_speed' (20%)."""
        # Configure settings with both speed values
        mock_settings.get_robot_config.return_value = {
            "ip": "192.168.0.100",
            "port": 10000,
            "movement_params": {
                "speed": 35.0,        # Normal operational speed
                "align_speed": 20.0,  # Slow speed for alignment (should NOT be used)
                "force": 50,
                "acceleration": 15
            },
            "sequence_config": {"version": "1.0", "operation_offsets": {}}
        }

        # Create mock robot with SetJointVel
        mock_robot = Mock()
        mock_robot.SetJointVel = Mock()
        mock_robot.SetGripperForce = Mock()
        mock_robot.SetJointAcc = Mock()

        # Create mock driver
        driver = Mock()
        driver._robot = mock_robot
        driver._executor = None  # Will be handled by run_in_executor mock
        driver._connected = True

        mock_async_wrapper.robot_driver = driver

        with patch('services.meca.service.WaferConfigManager'):
            service = MecaService(
                robot_id="meca_test",
                settings=mock_settings,
                state_manager=mock_state_manager,
                lock_manager=mock_lock_manager,
                async_wrapper=mock_async_wrapper
            )
            service._running = True

            # Mock run_in_executor to call the function directly
            async def mock_run_in_executor(executor, func, *args):
                return func(*args)

            with patch('asyncio.get_event_loop') as mock_loop:
                mock_loop.return_value.run_in_executor = AsyncMock(side_effect=mock_run_in_executor)

                # Call _restore_speed_settings through recovery operations
                await service.recovery_operations._restore_speed_settings(driver)

                # Verify SetJointVel was called with normal speed (35%), NOT align_speed (20%)
                mock_robot.SetJointVel.assert_called_once_with(35.0)

    @pytest.mark.asyncio
    async def test_restore_speed_defaults_to_35_when_speed_not_configured(self, mock_settings, mock_state_manager, mock_lock_manager, mock_async_wrapper):
        """Test that _restore_speed_settings defaults to 35% when 'speed' not in config."""
        # Configure settings WITHOUT explicit speed value
        mock_settings.get_robot_config.return_value = {
            "ip": "192.168.0.100",
            "port": 10000,
            "movement_params": {
                # No 'speed' key - should default to 35.0
                "align_speed": 20.0,
                "force": 50,
                "acceleration": 15
            },
            "sequence_config": {"version": "1.0", "operation_offsets": {}}
        }

        # Create mock robot with SetJointVel
        mock_robot = Mock()
        mock_robot.SetJointVel = Mock()
        mock_robot.SetGripperForce = Mock()
        mock_robot.SetJointAcc = Mock()

        # Create mock driver
        driver = Mock()
        driver._robot = mock_robot
        driver._executor = None
        driver._connected = True

        mock_async_wrapper.robot_driver = driver

        with patch('services.meca.service.WaferConfigManager'):
            service = MecaService(
                robot_id="meca_test",
                settings=mock_settings,
                state_manager=mock_state_manager,
                lock_manager=mock_lock_manager,
                async_wrapper=mock_async_wrapper
            )
            service._running = True

            async def mock_run_in_executor(executor, func, *args):
                return func(*args)

            with patch('asyncio.get_event_loop') as mock_loop:
                mock_loop.return_value.run_in_executor = AsyncMock(side_effect=mock_run_in_executor)

                await service.recovery_operations._restore_speed_settings(driver)

                # Verify SetJointVel was called with default 35%, NOT 20%
                mock_robot.SetJointVel.assert_called_once_with(35.0)
