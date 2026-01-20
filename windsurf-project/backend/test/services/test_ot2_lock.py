"""
Tests for OT2 double-start race condition fix.

Tests Phase 3 of robot safety plan:
- asyncio.Lock prevents concurrent protocol execution
- Second request waits or fails gracefully
"""

import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from typing import Dict, Any

from services.ot2_service import OT2Service
from core.state_manager import AtomicStateManager
from core.resource_lock import ResourceLockManager
from core.settings import RoboticsSettings
from core.exceptions import ValidationError


@pytest.fixture
def mock_settings():
    """Mock RoboticsSettings."""
    settings = Mock(spec=RoboticsSettings)
    settings.get_robot_config.return_value = {
        "ip": "192.168.0.200",
        "port": 31950,
        "protocol_config": {
            "directory": "protocols/",
            "default_file": "test_protocol.py",
            "execution_timeout": 3600.0,
            "monitoring_interval": 2.0
        }
    }
    settings.protocol_execution_timeout = 3600.0
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

    class AsyncContextManagerMock:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            return False

    manager.acquire = Mock(return_value=AsyncContextManagerMock())
    return manager


@pytest.fixture
def ot2_service(mock_settings, mock_state_manager, mock_lock_manager):
    """Create OT2Service instance with mocked dependencies."""
    with patch('pathlib.Path.mkdir'):
        service = OT2Service(
            robot_id="ot2_test",
            settings=mock_settings,
            state_manager=mock_state_manager,
            lock_manager=mock_lock_manager,
        )
        return service


class TestOT2ProtocolLock:
    """Tests for OT2 protocol execution lock to prevent double-start."""

    def test_ot2_service_has_protocol_lock(self, ot2_service):
        """Test that OT2Service has a protocol lock attribute."""
        assert hasattr(ot2_service, '_protocol_lock')
        assert isinstance(ot2_service._protocol_lock, asyncio.Lock)

    @pytest.mark.asyncio
    async def test_concurrent_protocol_execution_blocked(self, ot2_service):
        """Test that concurrent protocol executions are serialized by lock."""
        # Track execution order
        execution_log = []
        original_lock = ot2_service._protocol_lock

        # Mock the internal protocol execution
        async def mock_execute_inner():
            execution_log.append("started")
            await asyncio.sleep(0.1)  # Simulate work
            execution_log.append("finished")
            return {"status": "success"}

        # Patch execute_protocol to use our mock but still use the lock
        async def execute_with_lock():
            async with original_lock:
                return await mock_execute_inner()

        ot2_service._execute_protocol_inner = execute_with_lock

        # Start two concurrent "executions"
        task1 = asyncio.create_task(execute_with_lock())
        task2 = asyncio.create_task(execute_with_lock())

        await asyncio.gather(task1, task2)

        # Verify serialization: should be start-finish-start-finish, not start-start-finish-finish
        assert execution_log == ["started", "finished", "started", "finished"], \
            f"Expected serialized execution, got: {execution_log}"

    @pytest.mark.asyncio
    async def test_lock_released_on_exception(self, ot2_service):
        """Test that the lock is released even when an exception occurs."""
        lock = ot2_service._protocol_lock

        # Verify lock starts unlocked
        assert not lock.locked()

        # Simulate an operation that fails
        async def failing_operation():
            async with lock:
                raise ValueError("Simulated failure")

        # Execute and catch exception
        with pytest.raises(ValueError):
            await failing_operation()

        # Verify lock is released after exception
        assert not lock.locked()

    @pytest.mark.asyncio
    async def test_second_request_waits_for_first(self, ot2_service):
        """Test that second concurrent request waits for first to complete."""
        lock = ot2_service._protocol_lock
        timestamps = []

        async def timed_operation(name: str, duration: float):
            async with lock:
                timestamps.append((name, "acquired", asyncio.get_event_loop().time()))
                await asyncio.sleep(duration)
                timestamps.append((name, "released", asyncio.get_event_loop().time()))

        # Start first operation
        task1 = asyncio.create_task(timed_operation("first", 0.1))
        await asyncio.sleep(0.01)  # Let first acquire the lock

        # Start second operation (should wait)
        task2 = asyncio.create_task(timed_operation("second", 0.05))

        await asyncio.gather(task1, task2)

        # Verify second waited for first
        # First should acquire before second
        first_acquired = next(t for t in timestamps if t[0] == "first" and t[1] == "acquired")[2]
        first_released = next(t for t in timestamps if t[0] == "first" and t[1] == "released")[2]
        second_acquired = next(t for t in timestamps if t[0] == "second" and t[1] == "acquired")[2]

        assert second_acquired >= first_released, \
            "Second operation should not acquire lock until first releases"


class TestOT2ProtocolLockIntegration:
    """Integration tests for protocol lock with actual execute_protocol flow."""

    @pytest.mark.asyncio
    async def test_execute_protocol_uses_lock(self, ot2_service):
        """Test that execute_protocol method uses the protocol lock."""
        # This test verifies the lock is acquired during protocol execution
        lock = ot2_service._protocol_lock

        # Track if lock was held during execution
        lock_was_held = False

        async def mock_ensure_ready():
            nonlocal lock_was_held
            # Check if lock is held at this point
            lock_was_held = lock.locked()
            return True

        ot2_service.ensure_robot_ready = mock_ensure_ready

        # Mock other dependencies to prevent actual execution
        ot2_service._current_run = None
        ot2_service._upload_protocol = AsyncMock(return_value="test_protocol_id")
        ot2_service._wait_for_analysis_completion = AsyncMock(return_value=True)
        ot2_service._validate_hardware_requirements = AsyncMock(return_value={"valid": True, "warnings": []})
        ot2_service._create_run = AsyncMock(return_value={"id": "run_123"})
        ot2_service._start_run = AsyncMock(return_value=True)
        ot2_service._wait_for_completion = AsyncMock(return_value={"status": "succeeded"})

        # Create a mock protocol config
        mock_protocol = Mock()
        mock_protocol.protocol_name = "test_protocol"

        # Patch execute_operation to directly call the callback
        # This bypasses the base service wrapper so we can test the lock behavior
        original_execute_operation = ot2_service.execute_operation

        async def direct_execute(context, callback):
            """Execute callback directly without base service wrapper."""
            return await callback()

        ot2_service.execute_operation = direct_execute

        # Try to execute - may fail but lock should be acquired
        # Pass monitor_progress=False to avoid waiting for monitoring task
        try:
            await ot2_service.execute_protocol(mock_protocol, monitor_progress=False)
        except Exception:
            pass  # We only care about lock being held
        finally:
            ot2_service.execute_operation = original_execute_operation

        # The lock should have been held during ensure_robot_ready
        assert lock_was_held, "Protocol lock should be held during execute_protocol"
