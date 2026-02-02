"""
Backwards compatibility module for meca_service.

This file re-exports MecaService from the new module structure.
All functionality has been moved to services/meca/ directory.

DEPRECATED: Import from services.meca instead:
    from services.meca import MecaService
"""

# Re-export for backwards compatibility
from services.meca import (
    MecaService,
    MecaConnectionManager,
    MecaRecoveryOperations,
    MecaPositionCalculator,
    MecaMovementExecutor,
    MecaWaferSequences,
)

# Also re-export position types for any legacy code
from services.meca.position_calculator import WaferPosition, CarouselPosition

# Re-export WaferConfigManager for patch compatibility in tests
from services.wafer_config_manager import WaferConfigManager

__all__ = [
    "MecaService",
    "MecaConnectionManager",
    "MecaRecoveryOperations",
    "MecaPositionCalculator",
    "MecaMovementExecutor",
    "MecaWaferSequences",
    "WaferPosition",
    "CarouselPosition",
    "WaferConfigManager",
]
