# DEPRECATED: This test file is for legacy imports
# TODO: Update to test new service layer imports

import pytest
from dependencies import get_container
from services.orchestrator import RobotOrchestrator
from services.command_service import RobotCommandService

def test_import_new_services():
    """Test that new service layer imports work"""
    assert RobotOrchestrator is not None
    assert RobotCommandService is not None
    assert get_container is not None

# Legacy test - commented out
# def test_import_robot_manager():
#     from backend.core.robot_manager import RobotManager  # LEGACY
#     assert RobotManager is not None
