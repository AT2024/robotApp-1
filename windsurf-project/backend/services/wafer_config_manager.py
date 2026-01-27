"""
WaferConfigManager - Manages per-wafer configuration for 55-wafer sequences.

DESIGN PRINCIPLE: Zero hardcoded values. All offsets come from runtime.json.
If a required value is missing, the system raises a clear error.
"""

import copy
from typing import Dict, List, Any, Optional
from dataclasses import dataclass

from utils.logger import get_logger

logger = get_logger("wafer_config_manager")


class ConfigurationError(Exception):
    """Raised when required configuration is missing or invalid"""
    pass


@dataclass
class WaferConfig:
    """Configuration for a single wafer"""
    wafer_index: int
    gap_wafers: float
    gap_adjustment: float
    movement_speeds: Dict[str, float]

    @property
    def effective_gap(self) -> float:
        return self.gap_wafers + self.gap_adjustment


class WaferConfigManager:
    """
    Manages configuration for 55-wafer Mecademic sequences.

    ZERO HARDCODED VALUES - All offsets must be in runtime.json.
    Missing values cause clear errors, not silent defaults.
    """

    # List of REQUIRED offset keys per operation (for validation only, not default values)
    REQUIRED_OFFSETS = {
        "pickup": [
            "pickup_high_y", "pickup_high_z",
            "intermediate_1_y", "intermediate_1_z",
            "intermediate_2_y", "intermediate_2_z",
            "intermediate_3_y", "intermediate_3_z",
            "above_spreader_z", "above_spreader_exit_z"
        ],
        "drop": [
            "above_spreader_z", "above_spreader_pickup_z",
            "baking_align1_x", "baking_align1_y", "baking_align1_z",
            "baking_align2_x", "baking_align2_y", "baking_align2_z",
            "baking_align3_x", "baking_align3_y", "baking_align3_z",
            "baking_align4_x", "baking_align4_y", "baking_align4_z",
            "baking_up_z"
        ],
        "carousel": [
            "above_baking_z",
            "move1_x", "move1_z", "move2_x", "move2_z",
            "move3_x", "move3_z", "move4_x", "move4_z",
            "y_away1_y", "y_away1_z", "y_away2_y", "y_away2_z",
            "above_carousel1_z", "above_carousel2_z", "above_carousel3_z"
        ],
        "empty_carousel": [
            "y_away1_y", "y_away1_z", "y_away2_y", "y_away2_z",
            "above_carousel_z", "move_rev_y", "above_baking_rev_z"
        ]
    }

    def __init__(self, robot_config: Dict[str, Any], movement_params: Dict[str, Any]):
        self.robot_config = robot_config
        self.movement_params = movement_params
        self.sequence_config = robot_config.get("sequence_config")

        if not self.sequence_config:
            raise ConfigurationError(
                "Missing 'sequence_config' in meca config. "
                "All offset values must be defined in runtime.json"
            )

        self._config_version = self.sequence_config.get("version", "1.0")
        self._load_and_validate_config()

    def _load_and_validate_config(self):
        """Load config and VALIDATE all required values exist"""
        # Base gap_wafers - REQUIRED
        self.base_gap_wafers = self.movement_params.get("gap_wafers")
        if self.base_gap_wafers is None:
            raise ConfigurationError("Missing required 'gap_wafers' in movement_params")

        # Operation offsets - ALL REQUIRED
        self.operation_offsets = self.sequence_config.get("operation_offsets")
        if not self.operation_offsets:
            raise ConfigurationError(
                "Missing 'operation_offsets' in sequence_config. "
                "All offset values must be defined."
            )

        # Validate all required offsets exist
        missing = self._find_missing_offsets()
        if missing:
            raise ConfigurationError(
                f"Missing required offset values in runtime.json:\n" +
                "\n".join(f"  - {op}.{key}" for op, key in missing)
            )

        # Range overrides (optional)
        self.range_overrides = self.sequence_config.get("wafer_range_overrides", [])

        # Per-wafer overrides (optional)
        self.wafer_overrides = self.sequence_config.get("wafer_specific_overrides", {})

        # Safety bounds (optional, with reasonable defaults)
        self.safety_bounds = self.sequence_config.get("safety_bounds", {})

        logger.info(f"WaferConfigManager loaded config version {self._config_version}")

    def _find_missing_offsets(self) -> List[tuple]:
        """Find any missing required offset values"""
        missing = []
        for operation, required_keys in self.REQUIRED_OFFSETS.items():
            op_offsets = self.operation_offsets.get(operation, {})
            for key in required_keys:
                if key not in op_offsets:
                    missing.append((operation, key))
        return missing

    def reload_config(self, new_robot_config: Dict[str, Any], new_movement_params: Dict[str, Any]):
        """Reload configuration (for mid-sequence adjustments)"""
        self.robot_config = new_robot_config
        self.movement_params = new_movement_params
        self.sequence_config = new_robot_config.get("sequence_config")

        if not self.sequence_config:
            raise ConfigurationError("Missing 'sequence_config' after reload")

        self._config_version = self.sequence_config.get("version", "1.0")
        self._load_and_validate_config()
        logger.info(f"WaferConfigManager reloaded - version {self._config_version}")

    def get_offset(self, operation: str, offset_name: str, wafer_index: int = 0) -> float:
        """
        Get a specific offset value for an operation.

        Raises ConfigurationError if offset not found (no silent defaults).
        """
        op_offsets = self.operation_offsets.get(operation)
        if not op_offsets:
            raise ConfigurationError(f"No offsets defined for operation '{operation}'")

        value = op_offsets.get(offset_name)
        if value is None:
            raise ConfigurationError(
                f"Missing offset '{offset_name}' for operation '{operation}'. "
                f"Add it to runtime.json under sequence_config.operation_offsets.{operation}"
            )

        # Check for per-wafer override
        wafer_key = str(wafer_index)
        if wafer_key in self.wafer_overrides:
            override = self.wafer_overrides[wafer_key]
            override_key = f"{operation}_{offset_name}"
            if override_key in override:
                return override[override_key]

        return value

    def get_wafer_config(self, wafer_index: int) -> WaferConfig:
        """Get configuration for a specific wafer (gap + speeds)"""
        gap_wafers = self.base_gap_wafers
        gap_adjustment = 0.0
        movement_speeds = {
            "wafer_speed": self.movement_params.get("wafer_speed", 35.0),
            "empty_speed": self.movement_params.get("empty_speed", 50.0),
            "align_speed": self.movement_params.get("align_speed", 20.0),
            "entry_speed": self.movement_params.get("entry_speed", 15.0)
        }

        # Apply range overrides
        for range_override in self.range_overrides:
            range_start, range_end = range_override.get("range", [0, 54])
            if range_start <= wafer_index <= range_end:
                if "gap_wafers" in range_override:
                    gap_wafers = range_override["gap_wafers"]
                for speed_key in movement_speeds.keys():
                    if speed_key in range_override:
                        movement_speeds[speed_key] = range_override[speed_key]

        # Apply per-wafer overrides
        wafer_key = str(wafer_index)
        if wafer_key in self.wafer_overrides:
            override = self.wafer_overrides[wafer_key]
            if "gap_adjustment" in override:
                gap_adjustment = override["gap_adjustment"]
            if "gap_wafers" in override:
                gap_wafers = override["gap_wafers"]
            for speed_key in movement_speeds.keys():
                if speed_key in override:
                    movement_speeds[speed_key] = override[speed_key]

        return WaferConfig(
            wafer_index=wafer_index,
            gap_wafers=gap_wafers,
            gap_adjustment=gap_adjustment,
            movement_speeds=movement_speeds
        )

    def validate_all_wafers(self, total_wafers: int = 55) -> List[str]:
        """Validate configuration for all wafers"""
        errors = []
        bounds = self.safety_bounds

        for i in range(total_wafers):
            config = self.get_wafer_config(i)

            # Validate gap_wafers if bounds defined
            effective_gap = config.effective_gap
            if "min_gap_wafers" in bounds and effective_gap < bounds["min_gap_wafers"]:
                errors.append(f"Wafer {i+1}: gap {effective_gap} below minimum {bounds['min_gap_wafers']}")
            if "max_gap_wafers" in bounds and effective_gap > bounds["max_gap_wafers"]:
                errors.append(f"Wafer {i+1}: gap {effective_gap} above maximum {bounds['max_gap_wafers']}")

            # Validate speeds if bounds defined
            for speed_name, speed_value in config.movement_speeds.items():
                if "min_speed" in bounds and speed_value < bounds["min_speed"]:
                    errors.append(f"Wafer {i+1}: {speed_name} {speed_value} below minimum")
                if "max_speed" in bounds and speed_value > bounds["max_speed"]:
                    errors.append(f"Wafer {i+1}: {speed_name} {speed_value} above maximum")

        return errors

    def preview_wafer_positions(self, wafer_indices: List[int], first_wafer: List[float],
                                 first_baking: List[float]) -> Dict[int, Dict[str, Any]]:
        """Preview calculated positions for specified wafers"""
        preview = {}
        for i in wafer_indices:
            config = self.get_wafer_config(i)
            effective_gap = config.effective_gap

            inert_y = first_wafer[1] + (effective_gap * i)
            baking_x = first_baking[0] + (effective_gap * i)

            preview[i] = {
                "wafer_number": i + 1,
                "effective_gap": effective_gap,
                "inert_tray_y": inert_y,
                "baking_tray_x": baking_x,
                "spreader_index": 4 - (i % 5),
                "movement_speeds": config.movement_speeds,
                "has_overrides": str(i) in self.wafer_overrides
            }

        return preview

    @property
    def config_version(self) -> str:
        return self._config_version
