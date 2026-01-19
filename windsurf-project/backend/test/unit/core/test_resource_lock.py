"""
Unit tests for ResourceLockManager.
Tests lock acquisition, release, and contention handling.
"""
import pytest
import asyncio


@pytest.mark.unit
class TestMockLockManager:
    """Tests for the MockLockManager fixture."""

    @pytest.mark.asyncio
    async def test_lock_acquisition(self, mock_lock_manager):
        """Test basic lock acquisition."""
        async with mock_lock_manager.acquire('resource_1'):
            assert mock_lock_manager.is_locked('resource_1')

        assert not mock_lock_manager.is_locked('resource_1')

    @pytest.mark.asyncio
    async def test_lock_release_on_exit(self, mock_lock_manager):
        """Test lock is released when context exits."""
        async with mock_lock_manager.acquire('test_resource'):
            pass

        assert not mock_lock_manager.is_locked('test_resource')

    @pytest.mark.asyncio
    async def test_multiple_resources(self, mock_lock_manager):
        """Test locking multiple resources independently."""
        async with mock_lock_manager.acquire('resource_a'):
            assert mock_lock_manager.is_locked('resource_a')
            assert not mock_lock_manager.is_locked('resource_b')

            async with mock_lock_manager.acquire('resource_b'):
                assert mock_lock_manager.is_locked('resource_a')
                assert mock_lock_manager.is_locked('resource_b')

            assert mock_lock_manager.is_locked('resource_a')
            assert not mock_lock_manager.is_locked('resource_b')

    @pytest.mark.asyncio
    async def test_lock_history(self, mock_lock_manager):
        """Test lock operation history is recorded."""
        async with mock_lock_manager.acquire('meca_arm'):
            pass

        history = mock_lock_manager.get_lock_history()
        assert ('acquire', 'meca_arm') in history
        assert ('release', 'meca_arm') in history

    @pytest.mark.asyncio
    async def test_lock_release_on_exception(self, mock_lock_manager):
        """Test lock is released even when exception occurs."""
        with pytest.raises(ValueError):
            async with mock_lock_manager.acquire('test_resource'):
                assert mock_lock_manager.is_locked('test_resource')
                raise ValueError("Simulated error")

        # Lock should be released despite exception
        assert not mock_lock_manager.is_locked('test_resource')

    @pytest.mark.asyncio
    async def test_reset_clears_locks(self, mock_lock_manager):
        """Test reset clears all lock state."""
        # Acquire and release a lock
        async with mock_lock_manager.acquire('resource_1'):
            pass

        # Verify we have history
        assert len(mock_lock_manager.get_lock_history()) > 0

        # Reset should clear everything
        mock_lock_manager.reset()

        # After reset, lock should be cleared
        assert not mock_lock_manager.is_locked('resource_1')
        assert len(mock_lock_manager.get_lock_history()) == 0


@pytest.mark.unit
class TestLockContention:
    """Tests for lock contention scenarios."""

    @pytest.mark.asyncio
    async def test_contention_simulation(self, mock_lock_manager):
        """Test contention simulation mode."""
        mock_lock_manager.simulate_contention(enabled=True)

        # First acquire
        async with mock_lock_manager.acquire('shared_resource'):
            # Second acquire should still work (mock doesn't block)
            # but simulates delay
            async with mock_lock_manager.acquire('shared_resource'):
                pass

    @pytest.mark.asyncio
    async def test_sequential_lock_acquisition(self, mock_lock_manager):
        """Test locks can be acquired sequentially."""
        resources_accessed = []

        async with mock_lock_manager.acquire('carousel'):
            resources_accessed.append('carousel')

        async with mock_lock_manager.acquire('carousel'):
            resources_accessed.append('carousel_again')

        assert len(resources_accessed) == 2


@pytest.mark.unit
class TestRobotResourceLocking:
    """Tests for robot-specific locking patterns."""

    @pytest.mark.asyncio
    async def test_meca_operation_locking(self, mock_lock_manager):
        """Test Mecademic robot operation locking."""
        async with mock_lock_manager.acquire('robot_meca'):
            # Simulate operation
            await asyncio.sleep(0.001)

        history = mock_lock_manager.get_lock_history()
        assert ('acquire', 'robot_meca') in history
        assert ('release', 'robot_meca') in history

    @pytest.mark.asyncio
    async def test_carousel_shared_resource(self, mock_lock_manager):
        """Test carousel as shared resource between robots."""
        operations = []

        async def meca_carousel_op():
            async with mock_lock_manager.acquire('carousel'):
                operations.append('meca_access')
                await asyncio.sleep(0.001)

        async def ot2_carousel_op():
            async with mock_lock_manager.acquire('carousel'):
                operations.append('ot2_access')
                await asyncio.sleep(0.001)

        # Run sequentially (mock doesn't actually block)
        await meca_carousel_op()
        await ot2_carousel_op()

        assert 'meca_access' in operations
        assert 'ot2_access' in operations

    @pytest.mark.asyncio
    async def test_nested_resource_locks(self, mock_lock_manager):
        """Test acquiring multiple resources for complex operations."""
        async with mock_lock_manager.acquire('robot_meca'):
            async with mock_lock_manager.acquire('carousel'):
                async with mock_lock_manager.acquire('spreading_machine'):
                    # All three resources locked
                    assert mock_lock_manager.is_locked('robot_meca')
                    assert mock_lock_manager.is_locked('carousel')
                    assert mock_lock_manager.is_locked('spreading_machine')

        # All released
        assert not mock_lock_manager.is_locked('robot_meca')
        assert not mock_lock_manager.is_locked('carousel')
        assert not mock_lock_manager.is_locked('spreading_machine')
