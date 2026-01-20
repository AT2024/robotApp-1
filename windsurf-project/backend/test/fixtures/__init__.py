"""
Test fixtures package.
Provides simulators, mocks, and test data for robot automation testing.
"""
from .robot_simulators import MecaSimulator, OT2Simulator
from .core_fixtures import (
    MockStateManager,
    MockLockManager,
    MockSettings,
    MockWebSocketBroadcaster
)
from .protocols import (
    MecaDriverProtocol,
    OT2DriverProtocol,
    verify_protocol_compliance
)

__all__ = [
    'MecaSimulator',
    'OT2Simulator',
    'MockStateManager',
    'MockLockManager',
    'MockSettings',
    'MockWebSocketBroadcaster',
    'MecaDriverProtocol',
    'OT2DriverProtocol',
    'verify_protocol_compliance',
]
