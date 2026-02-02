"""
Mecademic robot service module.

This module provides all functionality for controlling the Mecademic robot,
including connection management, wafer handling, position calculations,
and recovery operations.

Re-exports MecaService as the main public API.
"""

from .service import MecaService

# Re-export supporting classes for advanced usage
from .connection_manager import MecaConnectionManager
from .recovery_operations import MecaRecoveryOperations
from .position_calculator import MecaPositionCalculator
from .movement_executor import MecaMovementExecutor
from .wafer_sequences import MecaWaferSequences

__all__ = [
    "MecaService",
    "MecaConnectionManager",
    "MecaRecoveryOperations",
    "MecaPositionCalculator",
    "MecaMovementExecutor",
    "MecaWaferSequences",
]
