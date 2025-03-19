import pytest
from backend.core.robot_manager import RobotManager

def test_import_robot_manager():
    assert RobotManager is not None
