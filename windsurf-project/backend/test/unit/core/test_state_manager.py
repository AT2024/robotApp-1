"""
Unit tests for AtomicStateManager.
Tests state update atomicity and robot state management.
"""
import pytest
import asyncio


@pytest.mark.unit
class TestMockStateManager:
    """Tests for the MockStateManager fixture."""

    @pytest.mark.asyncio
    async def test_initial_state(self, mock_state_manager):
        """Test initial state is IDLE."""
        state = await mock_state_manager.get_state()
        assert state['status'] == 'IDLE'

    @pytest.mark.asyncio
    async def test_update_state(self, mock_state_manager):
        """Test state updates are applied."""
        await mock_state_manager.update_state({'status': 'RUNNING', 'operation': 'pickup'})

        state = await mock_state_manager.get_state()
        assert state['status'] == 'RUNNING'
        assert state['operation'] == 'pickup'

    @pytest.mark.asyncio
    async def test_update_preserves_other_fields(self, mock_state_manager):
        """Test partial updates don't erase other fields."""
        await mock_state_manager.update_state({'status': 'RUNNING'})
        await mock_state_manager.update_state({'progress': 50})

        state = await mock_state_manager.get_state()
        assert state['status'] == 'RUNNING'
        assert state['progress'] == 50

    @pytest.mark.asyncio
    async def test_robot_state_isolation(self, mock_state_manager):
        """Test robot states are isolated from each other."""
        await mock_state_manager.update_robot_state('meca_1', {'connected': True})
        await mock_state_manager.update_robot_state('ot2_1', {'connected': False})

        meca_state = await mock_state_manager.get_robot_state('meca_1')
        ot2_state = await mock_state_manager.get_robot_state('ot2_1')

        assert meca_state['connected'] is True
        assert ot2_state['connected'] is False

    @pytest.mark.asyncio
    async def test_state_history_tracking(self, mock_state_manager):
        """Test state change history is recorded."""
        await mock_state_manager.update_state({'status': 'RUNNING'})
        await mock_state_manager.update_state({'status': 'COMPLETE'})

        history = mock_state_manager.get_state_history()
        assert len(history) == 2
        assert history[0] == ('update_state', {'status': 'RUNNING'})
        assert history[1] == ('update_state', {'status': 'COMPLETE'})

    @pytest.mark.asyncio
    async def test_update_count(self, mock_state_manager):
        """Test update counter increments."""
        assert mock_state_manager.get_update_count() == 0

        await mock_state_manager.update_state({'status': 'RUNNING'})
        assert mock_state_manager.get_update_count() == 1

        await mock_state_manager.update_state({'status': 'IDLE'})
        assert mock_state_manager.get_update_count() == 2

    @pytest.mark.asyncio
    async def test_reset(self, mock_state_manager):
        """Test reset clears all state."""
        await mock_state_manager.update_state({'status': 'RUNNING'})
        await mock_state_manager.update_robot_state('meca_1', {'connected': True})

        mock_state_manager.reset()

        state = await mock_state_manager.get_state()
        assert state['status'] == 'IDLE'
        assert len(mock_state_manager.get_state_history()) == 0


@pytest.mark.unit
class TestStateManagerConcurrency:
    """Tests for concurrent state access patterns."""

    @pytest.mark.asyncio
    async def test_concurrent_updates(self, mock_state_manager):
        """Test concurrent updates don't lose data."""
        async def update_task(key: str, value: int):
            await mock_state_manager.update_state({key: value})

        # Run multiple updates concurrently
        await asyncio.gather(
            update_task('a', 1),
            update_task('b', 2),
            update_task('c', 3),
        )

        state = await mock_state_manager.get_state()
        assert state['a'] == 1
        assert state['b'] == 2
        assert state['c'] == 3

    @pytest.mark.asyncio
    async def test_rapid_state_changes(self, mock_state_manager):
        """Test rapid sequential state changes."""
        for i in range(100):
            await mock_state_manager.update_state({'counter': i})

        state = await mock_state_manager.get_state()
        assert state['counter'] == 99
        assert mock_state_manager.get_update_count() == 100
