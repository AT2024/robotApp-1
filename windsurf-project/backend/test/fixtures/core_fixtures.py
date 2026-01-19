"""
Core component fixtures for testing.
Provides mocked StateManager, LockManager, and Settings.
"""
from typing import Dict, Any, Optional
from unittest.mock import Mock, AsyncMock
import asyncio


class MockStateManager:
    """
    Mock implementation of AtomicStateManager for testing.
    Tracks state updates and provides inspection methods.
    """

    def __init__(self):
        self._state: Dict[str, Any] = {'status': 'IDLE'}
        self._robot_states: Dict[str, Dict[str, Any]] = {}
        self._state_history: list = []
        self._update_count = 0

    async def update_state(self, updates: Dict[str, Any]) -> None:
        """Update global state."""
        self._state.update(updates)
        self._state_history.append(('update_state', updates.copy()))
        self._update_count += 1

    async def get_state(self) -> Dict[str, Any]:
        """Get current global state."""
        return self._state.copy()

    async def update_robot_state(self, robot_id: str, state: Dict[str, Any]) -> None:
        """Update state for a specific robot."""
        if robot_id not in self._robot_states:
            self._robot_states[robot_id] = {}
        self._robot_states[robot_id].update(state)
        self._state_history.append(('update_robot_state', robot_id, state.copy()))

    async def get_robot_state(self, robot_id: str) -> Optional[Dict[str, Any]]:
        """Get state for a specific robot."""
        return self._robot_states.get(robot_id, {}).copy()

    # Test helpers
    def get_state_history(self) -> list:
        """Return all state updates for verification."""
        return self._state_history.copy()

    def get_update_count(self) -> int:
        """Return number of state updates."""
        return self._update_count

    def reset(self) -> None:
        """Reset to initial state."""
        self._state = {'status': 'IDLE'}
        self._robot_states.clear()
        self._state_history.clear()
        self._update_count = 0


class MockLockManager:
    """
    Mock implementation of ResourceLockManager for testing.
    Tracks lock acquisitions and releases.
    """

    def __init__(self):
        self._locks: Dict[str, bool] = {}
        self._lock_history: list = []
        self._contention_simulation = False

    def acquire(self, resource_id: str, timeout: float = 10.0):
        """
        Return an async context manager for resource locking.
        """
        return _AsyncLockContext(self, resource_id, timeout)

    def is_locked(self, resource_id: str) -> bool:
        """Check if a resource is currently locked."""
        return self._locks.get(resource_id, False)

    def get_lock_history(self) -> list:
        """Return all lock operations for verification."""
        return self._lock_history.copy()

    def simulate_contention(self, enabled: bool = True) -> None:
        """Enable contention simulation for deadlock testing."""
        self._contention_simulation = enabled

    def reset(self) -> None:
        """Reset all locks."""
        self._locks.clear()
        self._lock_history.clear()
        self._contention_simulation = False


class _AsyncLockContext:
    """Async context manager for mock lock acquisition."""

    def __init__(self, manager: MockLockManager, resource_id: str, timeout: float):
        self._manager = manager
        self._resource_id = resource_id
        self._timeout = timeout

    async def __aenter__(self):
        if self._manager._contention_simulation and self._manager._locks.get(self._resource_id, False):
            # Simulate contention - wait briefly then proceed
            await asyncio.sleep(0.01)

        self._manager._locks[self._resource_id] = True
        self._manager._lock_history.append(('acquire', self._resource_id))
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        self._manager._locks[self._resource_id] = False
        self._manager._lock_history.append(('release', self._resource_id))
        return False


class MockSettings:
    """
    Mock implementation of RoboticsSettings for testing.
    Provides configurable robot configurations.
    """

    def __init__(self):
        self._robot_configs: Dict[str, Dict[str, Any]] = {
            'meca': self._default_meca_config(),
            'ot2': self._default_ot2_config(),
        }

    def get_robot_config(self, robot_type: str) -> Dict[str, Any]:
        """Get configuration for a robot type."""
        if robot_type not in self._robot_configs:
            raise ValueError(f"Unknown robot type: {robot_type}")
        return self._robot_configs[robot_type].copy()

    def set_robot_config(self, robot_type: str, config: Dict[str, Any]) -> None:
        """Set custom configuration for testing."""
        self._robot_configs[robot_type] = config.copy()

    def _default_meca_config(self) -> Dict[str, Any]:
        """Default Mecademic configuration."""
        return {
            "ip": "192.168.0.100",
            "port": 10000,
            "movement_params": {
                "gap_wafers": 2.7,
                "acceleration": 50.0,
                "empty_speed": 50.0,
                "wafer_speed": 35.0,
                "force": 100.0,
            },
            "positions": {
                "first_wafer": [173.562, -175.178, 27.9714, 109.5547, 0.2877, -90.059],
                "safe_point": [135, -17.6177, 160, 123.2804, 40.9554, -101.3308],
                "carousel": [133.8, -247.95, 101.9, 90, 0, -90],
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

    def _default_ot2_config(self) -> Dict[str, Any]:
        """Default OT-2 configuration."""
        return {
            "ip": "169.254.49.202",
            "port": 31950,
            "protocol_config": {
                "directory": "protocols/",
                "default_file": "ot2Protocole.py",
                "execution_timeout": 3600.0,
                "monitoring_interval": 2.0
            }
        }


class MockWebSocketBroadcaster:
    """
    Mock WebSocket broadcaster for testing state broadcasts.
    """

    def __init__(self):
        self._messages: list = []
        self._subscribers: int = 0

    async def broadcast_message(self, message: Dict[str, Any]) -> None:
        """Record broadcast message."""
        self._messages.append(message.copy())

    def get_messages(self) -> list:
        """Return all broadcast messages."""
        return self._messages.copy()

    def get_last_message(self) -> Optional[Dict[str, Any]]:
        """Return the most recent broadcast message."""
        return self._messages[-1].copy() if self._messages else None

    def get_messages_by_type(self, msg_type: str) -> list:
        """Return messages filtered by type."""
        return [m for m in self._messages if m.get('type') == msg_type]

    def reset(self) -> None:
        """Clear all recorded messages."""
        self._messages.clear()
