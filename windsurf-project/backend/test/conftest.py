"""
Root conftest with fixtures and protocol verification.
Shared fixtures for all test modules.
"""
import pytest
import asyncio
import sys
from pathlib import Path
from unittest.mock import Mock, AsyncMock, patch

# Ensure backend is in path for imports
backend_path = Path(__file__).parent.parent
if str(backend_path) not in sys.path:
    sys.path.insert(0, str(backend_path))

from test.fixtures.robot_simulators import MecaSimulator, OT2Simulator
from test.fixtures.core_fixtures import (
    MockStateManager,
    MockLockManager,
    MockSettings,
    MockWebSocketBroadcaster
)


# ===== Protocol Verification on Test Start =====
def pytest_configure(config):
    """Verify simulators implement protocols before running tests."""
    # Register custom markers
    config.addinivalue_line("markers", "unit: Fast unit tests (no external deps)")
    config.addinivalue_line("markers", "integration: Service integration tests")
    config.addinivalue_line("markers", "concurrency: Thread safety tests")
    config.addinivalue_line("markers", "edge_case: Error handling tests")
    config.addinivalue_line("markers", "hardware: Real hardware tests (CI-excluded)")
    config.addinivalue_line("markers", "slow: Tests >5 seconds")

    # Verify protocol compliance
    try:
        from test.fixtures.protocols import verify_protocol_compliance
        verify_protocol_compliance()
    except ImportError:
        # Allow tests to run even if protocol verification fails on import
        pass


# ===== Mecademic Fixtures =====
@pytest.fixture
def meca_simulator():
    """Fresh Mecademic simulator for each test."""
    return MecaSimulator()


@pytest.fixture
def mock_meca_driver(meca_simulator):
    """Mock driver wrapping simulator with test hooks."""
    driver = AsyncMock()

    # Bind all simulator methods
    driver.connect = meca_simulator.connect
    driver.disconnect = meca_simulator.disconnect
    driver.get_status = meca_simulator.get_status
    driver.get_joints = meca_simulator.get_joints
    driver.activate_robot = meca_simulator.activate_robot
    driver.home_robot = meca_simulator.home_robot
    driver.wait_homed = meca_simulator.wait_homed
    driver.reset_error = meca_simulator.reset_error
    driver.resume_motion = meca_simulator.resume_motion

    # Sync methods
    driver.MovePose = meca_simulator.MovePose
    driver.MoveJoints = meca_simulator.MoveJoints
    driver.Delay = meca_simulator.Delay
    driver.GripperOpen = meca_simulator.GripperOpen
    driver.GripperClose = meca_simulator.GripperClose
    driver.SetGripperForce = meca_simulator.SetGripperForce
    driver.SetJointAcc = meca_simulator.SetJointAcc
    driver.SetJointVel = meca_simulator.SetJointVel
    driver.SetTorqueLimits = meca_simulator.SetTorqueLimits
    driver.SetTorqueLimitsCfg = meca_simulator.SetTorqueLimitsCfg
    driver.SetBlending = meca_simulator.SetBlending
    driver.SetConf = meca_simulator.SetConf

    # Expose simulator for test assertions
    driver._simulator = meca_simulator
    return driver


# ===== OT-2 Fixtures =====
@pytest.fixture
def ot2_simulator():
    """Fresh OT-2 simulator for each test."""
    return OT2Simulator()


@pytest.fixture
def mock_ot2_driver(ot2_simulator):
    """Mock OT-2 driver with simulator backend."""
    driver = AsyncMock()

    driver.connect = ot2_simulator.connect
    driver.disconnect = ot2_simulator.disconnect
    driver.get_health = ot2_simulator.get_health
    driver.get_runs = ot2_simulator.get_runs
    driver.create_run = ot2_simulator.create_run
    driver.execute_run = ot2_simulator.execute_run
    driver.get_run_status = ot2_simulator.get_run_status
    driver.home = ot2_simulator.home
    driver.stop = ot2_simulator.stop

    driver._simulator = ot2_simulator
    return driver


# ===== Core Component Fixtures =====
@pytest.fixture
def mock_settings():
    """Mock RoboticsSettings."""
    return MockSettings()


@pytest.fixture
def mock_state_manager():
    """Mock AtomicStateManager."""
    return MockStateManager()


@pytest.fixture
def mock_lock_manager():
    """Mock ResourceLockManager."""
    return MockLockManager()


@pytest.fixture
def mock_websocket_broadcaster():
    """Mock WebSocket broadcaster."""
    broadcaster = MockWebSocketBroadcaster()
    with patch('websocket.selective_broadcaster.get_broadcaster', return_value=broadcaster):
        yield broadcaster


# ===== Async Wrapper Fixtures =====
@pytest.fixture
def mock_async_wrapper(mock_meca_driver):
    """Mock AsyncRobotWrapper with mocked driver."""
    wrapper = Mock()
    wrapper.robot_driver = mock_meca_driver
    return wrapper


# ===== Event Loop Configuration =====
@pytest.fixture(scope="session")
def event_loop_policy():
    """Return the event loop policy."""
    return asyncio.DefaultEventLoopPolicy()


# ===== Test Data Fixtures =====
@pytest.fixture
def sample_wafer_positions():
    """Sample wafer positions for testing."""
    return [
        {'x': 173.562, 'y': -175.178, 'z': 27.9714, 'rx': 109.5547, 'ry': 0.2877, 'rz': -90.059},
        {'x': 173.562, 'y': -175.178, 'z': 30.6714, 'rx': 109.5547, 'ry': 0.2877, 'rz': -90.059},
        {'x': 173.562, 'y': -175.178, 'z': 33.3714, 'rx': 109.5547, 'ry': 0.2877, 'rz': -90.059},
    ]


@pytest.fixture
def sample_carousel_position():
    """Sample carousel position for testing."""
    return {'x': 133.8, 'y': -247.95, 'z': 101.9, 'rx': 90, 'ry': 0, 'rz': -90}


# ===== Error Injection Fixtures =====
@pytest.fixture
def meca_with_error(meca_simulator):
    """Mecademic simulator pre-configured with error state."""
    meca_simulator.inject_error(error_code=1042)
    return meca_simulator


@pytest.fixture
def ot2_with_error(ot2_simulator):
    """OT2 simulator pre-configured with error state."""
    ot2_simulator.inject_error()
    return ot2_simulator
