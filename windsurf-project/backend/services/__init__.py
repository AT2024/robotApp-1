"""
Services layer for the robotics control system.

This package contains all business logic services that orchestrate
robot operations, protocol execution, and system coordination.
"""

# Re-export MecaService from the new module structure for backwards compatibility
from .meca import MecaService

__all__ = ["MecaService"]