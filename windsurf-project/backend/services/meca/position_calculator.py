"""
Position calculator for Mecademic robot operations.

Handles all position calculations for wafer handling, including:
- Wafer position calculations for inert, baking, and carousel trays
- Intermediate position calculations for safe movement sequences
"""

import copy
import math
from typing import Dict, List, Optional, Any
from dataclasses import dataclass

from core.exceptions import ValidationError
from utils.logger import get_logger


@dataclass
class WaferPosition:
    """Represents a wafer position with coordinates"""
    x: float
    y: float
    z: float
    alpha: float = 0.0
    beta: float = 0.0
    gamma: float = 0.0
    slot_id: Optional[str] = None


@dataclass
class CarouselPosition:
    """Represents a carousel position"""
    position_index: int
    coordinates: WaferPosition
    occupied: bool = False
    wafer_id: Optional[str] = None


class MecaPositionCalculator:
    """
    Calculates positions for Mecademic robot operations.

    Handles all coordinate calculations including wafer positions,
    intermediate positions for safe movement, and carousel positions.
    """

    def __init__(
        self,
        robot_config: Dict[str, Any],
        movement_params: Dict[str, Any],
        wafer_config_manager: Any
    ):
        """
        Initialize position calculator with configuration.

        Args:
            robot_config: Robot configuration from settings
            movement_params: Movement parameters from config
            wafer_config_manager: WaferConfigManager instance for sequence config
        """
        self.logger = get_logger("meca_position_calculator")
        self.wafer_config_manager = wafer_config_manager

        # Position constants from settings
        positions = robot_config.get("positions", {})
        self.FIRST_WAFER = positions.get("first_wafer", [173.562, -175.178, 27.9714, 109.5547, 0.2877, -90.059])
        self.GAP_WAFERS = movement_params.get("gap_wafers", 2.7)

        # Spreading Machine locations
        gen_drop_positions = positions.get("gen_drop", [])
        self.GEN_DROP = gen_drop_positions if gen_drop_positions else [
            [130.2207, 159.230, 123.400, 179.7538, -0.4298, -89.9617],
            [85.5707, 159.4300, 123.400, 179.7538, -0.4298, -89.6617],
            [41.0207, 159.4300, 123.400, 179.7538, -0.4298, -89.6617],
            [-3.5793, 159.3300, 123.400, 179.7538, -0.4298, -89.6617],
            [-47.9793, 159.2300, 123.400, 179.7538, -0.4298, -89.6617]
        ]

        # From baking tray to carousel
        self.FIRST_BAKING_TRAY = positions.get("first_baking", [-141.6702, -170.5871, 27.9420, -178.2908, -69.0556, 1.7626])

        # Carousel location
        self.CAROUSEL = positions.get("carousel", [133.8, -247.95, 101.9, 90, 0, -90])

        # Safe points and special locations
        self.SAFE_POINT = positions.get("safe_point", [135, -17.6177, 160, 123.2804, 40.9554, -101.3308])
        self.CAROUSEL_SAFEPOINT = positions.get("carousel_safe", [25.567, -202.630, 179.700, 90.546, 0.866, -90.882])
        self.T_PHOTOGATE = positions.get("t_photogate", [53.8, -217.2, 94.9, 90, 0, -90])
        self.C_PHOTOGATE = positions.get("c_photogate", [84.1, -217.2, 94.9, 90, 0, -90])

        # Converted WaferPosition objects
        self.safe_position = WaferPosition(
            x=self.SAFE_POINT[0], y=self.SAFE_POINT[1], z=self.SAFE_POINT[2],
            alpha=self.SAFE_POINT[3], beta=self.SAFE_POINT[4], gamma=self.SAFE_POINT[5]
        )
        self.carousel_safe_position = WaferPosition(
            x=self.CAROUSEL_SAFEPOINT[0], y=self.CAROUSEL_SAFEPOINT[1], z=self.CAROUSEL_SAFEPOINT[2],
            alpha=self.CAROUSEL_SAFEPOINT[3], beta=self.CAROUSEL_SAFEPOINT[4], gamma=self.CAROUSEL_SAFEPOINT[5]
        )

        # Initialize carousel positions
        self.carousel_positions: List[CarouselPosition] = []
        self._initialize_carousel_positions()

    def _initialize_carousel_positions(self) -> None:
        """Initialize carousel position mappings"""
        base_x, base_y, base_z = 100, 100, 50

        for i in range(24):  # 24 positions in carousel
            angle = (i * 15) * 3.14159 / 180  # 15 degrees per position
            radius = 80

            x = base_x + radius * math.cos(angle)
            y = base_y + radius * math.sin(angle)

            position = CarouselPosition(
                position_index=i,
                coordinates=WaferPosition(x=x, y=y, z=base_z)
            )
            self.carousel_positions.append(position)

    def calculate_wafer_position(self, wafer_index: int, tray_type: str) -> List[float]:
        """
        Calculate exact wafer position based on wafer index and tray type.

        Args:
            wafer_index: Wafer index (0-54 for wafers 1-55)
            tray_type: Type of tray ('inert', 'baking', 'carousel')

        Returns:
            List of 6 coordinates [x, y, z, alpha, beta, gamma]
        """
        if tray_type == "inert":
            base_position = copy.deepcopy(self.FIRST_WAFER)
            base_position[1] += self.GAP_WAFERS * wafer_index
            return base_position
        elif tray_type == "baking":
            base_position = copy.deepcopy(self.FIRST_BAKING_TRAY)
            base_position[0] += self.GAP_WAFERS * wafer_index
            return base_position
        elif tray_type == "carousel":
            return copy.deepcopy(self.CAROUSEL)
        else:
            raise ValidationError(f"Unknown tray type: {tray_type}")

    def calculate_intermediate_positions(self, wafer_index: int, operation: str) -> Dict[str, List[float]]:
        """
        Calculate intermediate positions for safe movement during wafer operations.
        All offset values are loaded from runtime.json via WaferConfigManager.

        Args:
            wafer_index: Wafer index (0-54 for wafers 1-55)
            operation: Operation type ('pickup', 'drop', 'carousel', 'empty_carousel')

        Returns:
            Dictionary of position names to coordinate lists
        """
        positions = {}

        # Get wafer-specific config (for effective_gap)
        wafer_config = self.wafer_config_manager.get_wafer_config(wafer_index)
        effective_gap = wafer_config.effective_gap

        # Helper to get offset from config
        def get_offset(offset_name: str) -> float:
            return self.wafer_config_manager.get_offset(operation, offset_name, wafer_index)

        if operation == "pickup":
            positions = self._calculate_pickup_positions(wafer_index, effective_gap, get_offset)
        elif operation == "drop":
            positions = self._calculate_drop_positions(wafer_index, effective_gap, get_offset)
        elif operation == "carousel":
            positions = self._calculate_carousel_positions(wafer_index, effective_gap, get_offset)
        elif operation == "empty_carousel":
            positions = self._calculate_empty_carousel_positions(wafer_index, effective_gap, get_offset)

        return positions

    def _calculate_pickup_positions(
        self, wafer_index: int, effective_gap: float, get_offset
    ) -> Dict[str, List[float]]:
        """Calculate positions for pickup operation."""
        positions = {}

        # High point above pickup position
        pickup_pos = self.calculate_wafer_position(wafer_index, "inert")
        high_point = copy.deepcopy(pickup_pos)
        high_point[1] += get_offset("pickup_high_y")
        high_point[2] += get_offset("pickup_high_z")
        positions["pickup_high"] = high_point

        # Intermediate movement positions
        intermediate_pos1 = copy.deepcopy(self.FIRST_WAFER)
        intermediate_pos1[1] += effective_gap * wafer_index + get_offset("intermediate_1_y")
        intermediate_pos1[2] += get_offset("intermediate_1_z")
        positions["intermediate_1"] = intermediate_pos1

        intermediate_pos2 = copy.deepcopy(intermediate_pos1)
        intermediate_pos2[1] += get_offset("intermediate_2_y")
        intermediate_pos2[2] += get_offset("intermediate_2_z")
        positions["intermediate_2"] = intermediate_pos2

        intermediate_pos3 = copy.deepcopy(intermediate_pos2)
        intermediate_pos3[1] += get_offset("intermediate_3_y")
        intermediate_pos3[2] += get_offset("intermediate_3_z")
        positions["intermediate_3"] = intermediate_pos3

        # Spreader positions
        spread_index = 4 - (wafer_index % 5)
        above_spreader = copy.deepcopy(self.GEN_DROP[spread_index])
        above_spreader[2] += get_offset("above_spreader_z")
        positions["above_spreader"] = above_spreader

        spreader = copy.deepcopy(self.GEN_DROP[spread_index])
        positions["spreader"] = spreader

        above_spreader_exit = copy.deepcopy(self.GEN_DROP[spread_index])
        above_spreader_exit[2] += get_offset("above_spreader_exit_z")
        positions["above_spreader_exit"] = above_spreader_exit

        return positions

    def _calculate_drop_positions(
        self, wafer_index: int, effective_gap: float, get_offset
    ) -> Dict[str, List[float]]:
        """Calculate positions for drop operation."""
        positions = {}

        # Drop sequence positions from spreader to baking tray
        spread_index = 4 - (wafer_index % 5)
        above_spreader = copy.deepcopy(self.GEN_DROP[spread_index])
        above_spreader[2] += get_offset("above_spreader_z")
        positions["above_spreader"] = above_spreader

        spreader = copy.deepcopy(self.GEN_DROP[spread_index])
        positions["spreader"] = spreader

        above_spreader_pickup = copy.deepcopy(self.GEN_DROP[spread_index])
        above_spreader_pickup[2] += get_offset("above_spreader_pickup_z")
        positions["above_spreader_pickup"] = above_spreader_pickup

        # Baking tray alignment positions
        baking_align1 = copy.deepcopy(self.FIRST_BAKING_TRAY)
        baking_align1[0] += effective_gap * wafer_index + get_offset("baking_align1_x")
        baking_align1[1] += get_offset("baking_align1_y")
        baking_align1[2] += get_offset("baking_align1_z")
        positions["baking_align1"] = baking_align1

        baking_align2 = copy.deepcopy(self.FIRST_BAKING_TRAY)
        baking_align2[0] += effective_gap * wafer_index + get_offset("baking_align2_x")
        baking_align2[1] += get_offset("baking_align2_y")
        baking_align2[2] += get_offset("baking_align2_z")
        positions["baking_align2"] = baking_align2

        baking_align3 = copy.deepcopy(self.FIRST_BAKING_TRAY)
        baking_align3[0] += effective_gap * wafer_index + get_offset("baking_align3_x")
        baking_align3[1] += get_offset("baking_align3_y")
        baking_align3[2] += get_offset("baking_align3_z")
        positions["baking_align3"] = baking_align3

        baking_align4 = copy.deepcopy(self.FIRST_BAKING_TRAY)
        baking_align4[0] += effective_gap * wafer_index + get_offset("baking_align4_x")
        baking_align4[1] += get_offset("baking_align4_y")
        baking_align4[2] += get_offset("baking_align4_z")
        positions["baking_align4"] = baking_align4

        baking_up = copy.deepcopy(self.FIRST_BAKING_TRAY)
        baking_up[0] += effective_gap * wafer_index
        baking_up[2] += get_offset("baking_up_z")
        positions["baking_up"] = baking_up

        return positions

    def _calculate_carousel_positions(
        self, wafer_index: int, effective_gap: float, get_offset
    ) -> Dict[str, List[float]]:
        """Calculate positions for carousel operation."""
        positions = {}

        # Carousel movement positions
        above_baking = copy.deepcopy(self.FIRST_BAKING_TRAY)
        above_baking[0] += effective_gap * wafer_index
        above_baking[2] += get_offset("above_baking_z")
        positions["above_baking"] = above_baking

        # Movement sequence positions
        move1 = copy.deepcopy(self.FIRST_BAKING_TRAY)
        move1[0] += effective_gap * wafer_index + get_offset("move1_x")
        move1[2] += get_offset("move1_z")
        positions["move1"] = move1

        move2 = copy.deepcopy(self.FIRST_BAKING_TRAY)
        move2[0] += effective_gap * wafer_index + get_offset("move2_x")
        move2[2] += get_offset("move2_z")
        positions["move2"] = move2

        move3 = copy.deepcopy(self.FIRST_BAKING_TRAY)
        move3[0] += effective_gap * wafer_index + get_offset("move3_x")
        move3[2] += get_offset("move3_z")
        positions["move3"] = move3

        move4 = copy.deepcopy(self.FIRST_BAKING_TRAY)
        move4[0] += effective_gap * wafer_index + get_offset("move4_x")
        move4[2] += get_offset("move4_z")
        positions["move4"] = move4

        # Carousel approach positions
        y_away1 = copy.deepcopy(self.CAROUSEL)
        y_away1[1] = get_offset("y_away1_y")
        y_away1[2] = get_offset("y_away1_z")
        positions["y_away1"] = y_away1

        y_away2 = copy.deepcopy(self.CAROUSEL)
        y_away2[1] = get_offset("y_away2_y")
        y_away2[2] = get_offset("y_away2_z")
        positions["y_away2"] = y_away2

        above_carousel1 = copy.deepcopy(self.CAROUSEL)
        above_carousel1[2] = get_offset("above_carousel1_z")
        positions["above_carousel1"] = above_carousel1

        above_carousel2 = copy.deepcopy(self.CAROUSEL)
        above_carousel2[2] = get_offset("above_carousel2_z")
        positions["above_carousel2"] = above_carousel2

        above_carousel3 = copy.deepcopy(self.CAROUSEL)
        above_carousel3[2] = get_offset("above_carousel3_z")
        positions["above_carousel3"] = above_carousel3

        return positions

    def _calculate_empty_carousel_positions(
        self, wafer_index: int, effective_gap: float, get_offset
    ) -> Dict[str, List[float]]:
        """Calculate positions for empty carousel operation."""
        positions = {}

        # Empty carousel positions (reverse of carousel)
        y_away1 = copy.deepcopy(self.CAROUSEL)
        y_away1[1] = get_offset("y_away1_y")
        y_away1[2] = get_offset("y_away1_z")
        positions["y_away1"] = y_away1

        y_away2 = copy.deepcopy(self.CAROUSEL)
        y_away2[1] = get_offset("y_away2_y")
        y_away2[2] = get_offset("y_away2_z")
        positions["y_away2"] = y_away2

        above_carousel = copy.deepcopy(self.CAROUSEL)
        above_carousel[2] = get_offset("above_carousel_z")
        positions["above_carousel"] = above_carousel

        # Reverse movement positions for baking tray
        move4_rev = copy.deepcopy(self.FIRST_BAKING_TRAY)
        move4_rev[0] += effective_gap * wafer_index + self.wafer_config_manager.get_offset("carousel", "move4_x", wafer_index)
        move4_rev[1] += get_offset("move_rev_y")
        move4_rev[2] += self.wafer_config_manager.get_offset("carousel", "move4_z", wafer_index)
        positions["move4_rev"] = move4_rev

        move3_rev = copy.deepcopy(self.FIRST_BAKING_TRAY)
        move3_rev[0] += effective_gap * wafer_index + self.wafer_config_manager.get_offset("carousel", "move3_x", wafer_index)
        move3_rev[1] += get_offset("move_rev_y")
        move3_rev[2] += self.wafer_config_manager.get_offset("carousel", "move3_z", wafer_index)
        positions["move3_rev"] = move3_rev

        move2_rev = copy.deepcopy(self.FIRST_BAKING_TRAY)
        move2_rev[0] += effective_gap * wafer_index + self.wafer_config_manager.get_offset("carousel", "move2_x", wafer_index)
        move2_rev[1] += get_offset("move_rev_y")
        move2_rev[2] += self.wafer_config_manager.get_offset("carousel", "move2_z", wafer_index)
        positions["move2_rev"] = move2_rev

        move1_rev = copy.deepcopy(self.FIRST_BAKING_TRAY)
        move1_rev[0] += effective_gap * wafer_index + self.wafer_config_manager.get_offset("carousel", "move1_x", wafer_index)
        move1_rev[1] += get_offset("move_rev_y")
        move1_rev[2] += self.wafer_config_manager.get_offset("carousel", "move1_z", wafer_index)
        positions["move1_rev"] = move1_rev

        above_baking_rev = copy.deepcopy(self.FIRST_BAKING_TRAY)
        above_baking_rev[0] += effective_gap * wafer_index
        above_baking_rev[2] += get_offset("above_baking_rev_z")
        positions["above_baking_rev"] = above_baking_rev

        return positions

    def get_wafer_position_preview(self, wafer_index: int) -> Dict[str, Any]:
        """
        Get position preview data for a single wafer.
        Used by test endpoint to verify position calculations.

        Args:
            wafer_index: Wafer index (0-based, 0-54)

        Returns:
            Dictionary with calculated positions for the wafer
        """
        wafer_number = wafer_index + 1
        baking_position = self.calculate_wafer_position(wafer_index, "baking")
        carousel_position = self.calculate_wafer_position(wafer_index, "carousel")
        carousel_positions = self.calculate_intermediate_positions(wafer_index, "carousel")

        return {
            "wafer_number": wafer_number,
            "wafer_index": wafer_index,
            "positions": {
                "baking_tray": {
                    "coordinates": baking_position,
                    "x": baking_position[0],
                    "y": baking_position[1],
                    "z": baking_position[2],
                },
                "carousel": {"coordinates": carousel_position},
                "intermediate_positions": {
                    "above_baking": carousel_positions.get("above_baking"),
                    "move_sequence": [
                        carousel_positions.get("move1"),
                        carousel_positions.get("move2"),
                        carousel_positions.get("move3"),
                        carousel_positions.get("move4"),
                    ],
                },
            },
            "verification": {
                "calculated_x": baking_position[0],
                "expected_x_wafer_55": 4.1298,
                "matches_expected": abs(baking_position[0] - 4.1298) < 0.001 if wafer_number == 55 else "N/A",
            },
        }
