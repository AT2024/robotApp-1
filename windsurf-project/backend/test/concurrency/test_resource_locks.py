"""
Tests for resource lock concurrency.
Verifies thread safety and deadlock prevention.
"""
import pytest
import asyncio


@pytest.mark.concurrency
class TestResourceLockConcurrency:
    """Tests for concurrent resource locking."""

    @pytest.mark.asyncio
    async def test_concurrent_lock_requests(self, mock_lock_manager):
        """Test multiple concurrent lock requests."""
        results = []

        async def acquire_and_record(resource_id: str, task_id: int):
            async with mock_lock_manager.acquire(resource_id):
                results.append(f"task_{task_id}_acquired")
                await asyncio.sleep(0.01)
                results.append(f"task_{task_id}_released")

        # Run multiple tasks concurrently
        await asyncio.gather(
            acquire_and_record('shared_resource', 1),
            acquire_and_record('shared_resource', 2),
            acquire_and_record('shared_resource', 3),
        )

        # All tasks should complete
        assert len(results) == 6

    @pytest.mark.asyncio
    async def test_independent_resources_parallel(self, mock_lock_manager):
        """Test independent resources can be locked in parallel."""
        lock_order = []

        async def lock_resource(resource_id: str):
            async with mock_lock_manager.acquire(resource_id):
                lock_order.append(f"acquired_{resource_id}")
                await asyncio.sleep(0.01)
                lock_order.append(f"released_{resource_id}")

        await asyncio.gather(
            lock_resource('meca_arm'),
            lock_resource('ot2_robot'),
            lock_resource('carousel'),
        )

        # All should acquire and release
        assert 'acquired_meca_arm' in lock_order
        assert 'acquired_ot2_robot' in lock_order
        assert 'acquired_carousel' in lock_order

    @pytest.mark.asyncio
    async def test_lock_release_order(self, mock_lock_manager):
        """Test locks are released in correct order with nested locks."""
        async with mock_lock_manager.acquire('outer'):
            assert mock_lock_manager.is_locked('outer')

            async with mock_lock_manager.acquire('inner'):
                assert mock_lock_manager.is_locked('inner')

            assert not mock_lock_manager.is_locked('inner')
            assert mock_lock_manager.is_locked('outer')

        assert not mock_lock_manager.is_locked('outer')


@pytest.mark.concurrency
class TestRobotCoordinationLocking:
    """Tests for multi-robot coordination locking patterns."""

    @pytest.mark.asyncio
    async def test_meca_ot2_carousel_coordination(self, mock_lock_manager):
        """Test Meca and OT2 can coordinate on shared carousel."""
        operations = []

        async def meca_to_carousel():
            async with mock_lock_manager.acquire('meca_arm'):
                operations.append('meca_start')
                async with mock_lock_manager.acquire('carousel'):
                    operations.append('meca_carousel_access')
                    await asyncio.sleep(0.01)
                operations.append('meca_done')

        async def ot2_from_carousel():
            async with mock_lock_manager.acquire('ot2_robot'):
                operations.append('ot2_start')
                async with mock_lock_manager.acquire('carousel'):
                    operations.append('ot2_carousel_access')
                    await asyncio.sleep(0.01)
                operations.append('ot2_done')

        await asyncio.gather(
            meca_to_carousel(),
            ot2_from_carousel(),
        )

        # Both should complete
        assert 'meca_done' in operations
        assert 'ot2_done' in operations
        assert 'meca_carousel_access' in operations
        assert 'ot2_carousel_access' in operations

    @pytest.mark.asyncio
    async def test_spreading_machine_exclusive_access(self, mock_lock_manager):
        """Test spreading machine has exclusive access during operation."""
        access_log = []

        async def wafer_spread_operation(wafer_id: int):
            async with mock_lock_manager.acquire('spreading_machine'):
                access_log.append(f"wafer_{wafer_id}_start")
                await asyncio.sleep(0.005)  # Simulate spread time
                access_log.append(f"wafer_{wafer_id}_end")

        await asyncio.gather(
            wafer_spread_operation(1),
            wafer_spread_operation(2),
            wafer_spread_operation(3),
        )

        # All wafers should be processed
        assert len(access_log) == 6


@pytest.mark.concurrency
class TestLockTimeouts:
    """Tests for lock timeout behavior."""

    @pytest.mark.asyncio
    async def test_lock_with_timeout(self, mock_lock_manager):
        """Test lock acquisition with timeout."""
        # Mock doesn't actually enforce timeout, but tests the API
        async with mock_lock_manager.acquire('resource', timeout=5.0):
            assert mock_lock_manager.is_locked('resource')

    @pytest.mark.asyncio
    async def test_rapid_lock_release_cycles(self, mock_lock_manager):
        """Test rapid lock/unlock cycles don't cause issues."""
        for i in range(100):
            async with mock_lock_manager.acquire(f'resource_{i % 5}'):
                pass

        # All locks should be released
        for i in range(5):
            assert not mock_lock_manager.is_locked(f'resource_{i}')


@pytest.mark.concurrency
class TestDeadlockPrevention:
    """Tests for deadlock prevention patterns."""

    @pytest.mark.asyncio
    async def test_consistent_lock_ordering(self, mock_lock_manager):
        """
        Test consistent lock ordering prevents deadlock.
        Always acquire in same order: meca -> carousel -> ot2
        """
        operations = []

        async def task_a():
            # Consistent order: meca first, then carousel
            async with mock_lock_manager.acquire('meca'):
                operations.append('a_meca')
                async with mock_lock_manager.acquire('carousel'):
                    operations.append('a_carousel')
                    await asyncio.sleep(0.01)

        async def task_b():
            # Same order: meca first, then carousel
            async with mock_lock_manager.acquire('meca'):
                operations.append('b_meca')
                async with mock_lock_manager.acquire('carousel'):
                    operations.append('b_carousel')
                    await asyncio.sleep(0.01)

        await asyncio.gather(task_a(), task_b())

        # Both should complete without deadlock
        assert 'a_carousel' in operations
        assert 'b_carousel' in operations

    @pytest.mark.asyncio
    async def test_lock_history_for_debugging(self, mock_lock_manager):
        """Test lock history helps debug ordering issues."""
        async with mock_lock_manager.acquire('resource_1'):
            async with mock_lock_manager.acquire('resource_2'):
                pass

        history = mock_lock_manager.get_lock_history()

        # Should show acquire/release pairs
        assert ('acquire', 'resource_1') in history
        assert ('acquire', 'resource_2') in history
        assert ('release', 'resource_2') in history
        assert ('release', 'resource_1') in history

        # Release order should be reverse of acquire
        acquire_1_idx = history.index(('acquire', 'resource_1'))
        acquire_2_idx = history.index(('acquire', 'resource_2'))
        release_2_idx = history.index(('release', 'resource_2'))
        release_1_idx = history.index(('release', 'resource_1'))

        assert acquire_1_idx < acquire_2_idx
        assert release_2_idx < release_1_idx
