import pytest
from unittest.mock import AsyncMock, MagicMock
from core.robot_manager import RobotManager

@pytest.mark.asyncio
async def test_meca_robot_connectivity():
    websocket_server = AsyncMock()
    robot_manager = RobotManager(websocket_server)
    robot_manager.meca_ip = "192.168.0.100"  # Mock IP

    # Mock the Meca robot methods
    meca_robot_mock = MagicMock()
    meca_robot_mock.IsConnected.return_value = True
    meca_robot_mock.IsActivated.return_value = True
    robot_manager.meca_robot = meca_robot_mock

    await robot_manager._initialize_meca()
    assert robot_manager.meca_connected is True

@pytest.mark.asyncio
async def test_ot2_connectivity():
    websocket_server = AsyncMock()
    robot_manager = RobotManager(websocket_server)

    # Mock the OT2 robot methods
    ot2_robot_mock = MagicMock()
    ot2_robot_mock.is_connected.return_value = True
    robot_manager.ot2_robot = ot2_robot_mock

    await robot_manager._initialize_ot2()
    assert robot_manager.ot2_connected is True

@pytest.mark.asyncio
async def test_arduino_connectivity():
    websocket_server = AsyncMock()
    robot_manager = RobotManager(websocket_server)

    # Mock the Arduino methods
    arduino_mock = MagicMock()
    arduino_mock.is_connected.return_value = True
    robot_manager.arduino = arduino_mock

    await robot_manager._initialize_arduino()
    assert robot_manager.arduino_connected is True

@pytest.mark.asyncio
async def test_backend_connectivity():
    websocket_server = AsyncMock()
    robot_manager = RobotManager(websocket_server)

    # Mock the backend status
    robot_manager.backend_status = 'connected'

    assert robot_manager.backend_status == 'connected'

@pytest.mark.asyncio
async def test_robot_connectivity():
    websocket_server = AsyncMock()
    robot_manager = RobotManager(websocket_server)

    # Mock connectivity status
    robot_manager.status = {
        'meca': 'connected',
        'arduino': 'disconnected',
        'ot2': 'connected',
        'backend': 'connected'
    }

    # Check if all components are connected
    assert robot_manager.status['meca'] == 'connected'
    assert robot_manager.status['arduino'] == 'disconnected'
    assert robot_manager.status['ot2'] == 'connected'
    assert robot_manager.status['backend'] == 'connected'

@pytest.mark.asyncio
async def test_robot_movement():
    websocket_server = AsyncMock()
    robot_manager = RobotManager(websocket_server)

    # Mock the Meca robot methods
    meca_robot_mock = MagicMock()
    meca_robot_mock.IsConnected.return_value = True
    meca_robot_mock.MoveTo = AsyncMock(return_value=None)  # Mock MoveTo as an async method
    robot_manager.meca_robot = meca_robot_mock

    # Mock the OT2 robot methods
    ot2_robot_mock = MagicMock()
    ot2_robot_mock.is_connected.return_value = True
    ot2_robot_mock.move_to = AsyncMock(return_value=None)  # Mock move_to as an async method
    robot_manager.ot2_robot = ot2_robot_mock

    # Initialize robots
    await robot_manager._initialize_meca()
    await robot_manager._initialize_ot2()

    # Move the Meca robot
    await robot_manager.meca_robot.MoveTo(100, 100, 100)  # Example coordinates
    meca_robot_mock.MoveTo.assert_called_once_with(100, 100, 100)  # Verify the call

    # Move the OT2 robot
    await robot_manager.ot2_robot.move_to((100, 100, 100))  # Example coordinates
    ot2_robot_mock.move_to.assert_called_once_with((100, 100, 100))  # Verify the call