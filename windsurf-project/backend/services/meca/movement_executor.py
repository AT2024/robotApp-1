"""
Movement executor for Mecademic robot operations.

Handles low-level movement command execution, including:
- Command building and validation
- Gripper control
- Movement parameter validation
"""

from typing import Dict, List, Any, Optional

from core.async_robot_wrapper import AsyncRobotWrapper, MovementCommand
from core.state_manager import AtomicStateManager, RobotState
from core.exceptions import HardwareError, ValidationError
from utils.logger import get_logger


class MecaMovementExecutor:
    """
    Executes movement commands for Mecademic robot.

    Provides low-level movement execution with parameter validation,
    gripper control, and safety checks.
    """

    def __init__(
        self,
        robot_id: str,
        async_wrapper: AsyncRobotWrapper,
        state_manager: AtomicStateManager,
        movement_params: Dict[str, Any]
    ):
        """
        Initialize movement executor.

        Args:
            robot_id: Robot identifier
            async_wrapper: AsyncRobotWrapper for command execution
            state_manager: AtomicStateManager for state tracking
            movement_params: Movement parameters from config
        """
        self.robot_id = robot_id
        self.async_wrapper = async_wrapper
        self.state_manager = state_manager
        self.movement_params = movement_params
        self.logger = get_logger("meca_movement_executor")

        # Gripper state
        self._gripper_open = True

    @property
    def gripper_open(self) -> bool:
        """Check if gripper is open."""
        return self._gripper_open

    async def execute_movement_command(self, command_type: str, parameters: List[Any] = None) -> None:
        """
        Execute movement command through the async wrapper.

        Args:
            command_type: Type of command (MovePose, GripperOpen, etc.)
            parameters: Command parameters

        Raises:
            RuntimeError: If emergency stop is active
            ValidationError: If parameters are invalid
            HardwareError: If command execution fails
        """
        if parameters is None:
            parameters = []

        # Safety check: abort if emergency stop is active
        robot_info = await self.state_manager.get_robot_state(self.robot_id)
        if robot_info and robot_info.current_state == RobotState.EMERGENCY_STOP:
            raise RuntimeError(f"Emergency stop activated during {command_type}")

        # Validate parameters
        self._validate_robot_parameters(command_type, parameters)

        # Build command
        command = self._build_movement_command(command_type, parameters)

        # Execute
        self.logger.debug(f"Executing {command_type}")
        result = await self.async_wrapper.execute_movement(command)
        if not result.success:
            raise HardwareError(f"Command {command_type} failed: {result.error}", robot_id=self.robot_id)

    def _validate_robot_parameters(self, command_type: str, parameters: List[Any]) -> bool:
        """
        Validate robot command parameters to prevent sending values that could cause errors.

        Args:
            command_type: Type of command (SetJointVel, MovePose, etc.)
            parameters: Parameters to validate

        Returns:
            True if parameters are valid

        Raises:
            ValidationError: If parameters are invalid
        """
        if not parameters:
            return True

        # Speed and acceleration validation (should be percentages: 1-100)
        if command_type in ["SetJointVel", "SetJointAcc", "SetCartVel", "SetCartAcc"]:
            if len(parameters) >= 1:
                value = parameters[0]
                if not (1 <= value <= 100):
                    raise ValidationError(
                        f"{command_type} parameter {value} is out of range (1-100)",
                        field="speed_acceleration"
                    )

        # Force validation (should be reasonable: 1-200)
        elif command_type == "SetGripperForce":
            if len(parameters) >= 1:
                value = parameters[0]
                if not (1 <= value <= 200):
                    raise ValidationError(
                        f"SetGripperForce parameter {value} is out of range (1-200)",
                        field="gripper_force"
                    )

        # Torque limits validation (should be reasonable: 1-100 for each joint)
        elif command_type == "SetTorqueLimits":
            if len(parameters) >= 6:
                for i, value in enumerate(parameters[:6]):
                    if not (1 <= value <= 100):
                        raise ValidationError(
                            f"SetTorqueLimits joint {i+1} parameter {value} is out of range (1-100)",
                            field="torque_limits"
                        )

        # Configuration validation (should be valid configurations: -1, 0, or 1)
        elif command_type == "SetConf":
            if len(parameters) >= 3:
                for i, value in enumerate(parameters[:3]):
                    if value not in [-1, 0, 1]:
                        raise ValidationError(
                            f"SetConf parameter {i+1} value {value} is invalid (must be -1, 0, or 1)",
                            field="robot_configuration"
                        )

        # Position validation (basic workspace check for Mecademic Meca500)
        elif command_type in ["MovePose", "MoveLin"]:
            if len(parameters) >= 6:
                x, y, z = parameters[0], parameters[1], parameters[2]
                alpha, beta, gamma = parameters[3], parameters[4], parameters[5]

                # Basic workspace validation for Meca500 (approximate)
                if not (-500 <= x <= 500):
                    raise ValidationError(
                        f"{command_type} X coordinate {x} is out of workspace (-500 to +500 mm)",
                        field="position_x"
                    )
                if not (-500 <= y <= 500):
                    raise ValidationError(
                        f"{command_type} Y coordinate {y} is out of workspace (-500 to +500 mm)",
                        field="position_y"
                    )
                if not (-100 <= z <= 400):
                    raise ValidationError(
                        f"{command_type} Z coordinate {z} is out of workspace (-100 to +400 mm)",
                        field="position_z"
                    )

                # Orientation validation (degrees)
                for angle, name in [(alpha, "Alpha"), (beta, "Beta"), (gamma, "Gamma")]:
                    if not (-180.1 <= angle <= 180.1):
                        self.logger.warning(
                            f"{command_type} {name} angle {angle} is at limit (-180 to +180 degrees)"
                        )
                    if not (-360 <= angle <= 360):
                        raise ValidationError(
                            f"{command_type} {name} angle {angle} is severely out of range (-360 to +360 degrees)",
                            field=f"orientation_{name.lower()}"
                        )

        # Delay validation (should be reasonable: 0.1 to 10 seconds)
        elif command_type == "Delay":
            if len(parameters) >= 1:
                value = parameters[0]
                if not (0.1 <= value <= 10.0):
                    raise ValidationError(
                        f"Delay parameter {value} is out of range (0.1 to 10.0 seconds)",
                        field="delay_duration"
                    )

        return True

    def _build_movement_command(self, command_type: str, parameters: List[Any]) -> MovementCommand:
        """
        Build MovementCommand from command type and parameters.

        Args:
            command_type: Type of command
            parameters: Command parameters

        Returns:
            MovementCommand object
        """
        # Position commands with 6 coordinates
        if command_type in ("MovePose", "MoveLin") and len(parameters) == 6:
            return MovementCommand(
                command_type=command_type,
                target_position={
                    "x": parameters[0], "y": parameters[1], "z": parameters[2],
                    "alpha": parameters[3], "beta": parameters[4], "gamma": parameters[5]
                }
            )

        # Gripper commands
        if command_type == "GripperOpen":
            return MovementCommand(command_type="GripperOpen", tool_action="grip_open")
        if command_type == "GripperClose":
            return MovementCommand(command_type="GripperClose", tool_action="grip_close")
        if command_type == "MoveGripper" and len(parameters) == 1:
            return MovementCommand(
                command_type="MoveGripper",
                tool_action="grip_move",
                parameters={"width": parameters[0]}
            )

        # Delay command
        if command_type == "Delay" and len(parameters) == 1:
            return MovementCommand(command_type="Delay", parameters={"duration": parameters[0]})

        # Configuration commands (Set*)
        if command_type.startswith("Set"):
            return MovementCommand(
                command_type="config",
                parameters={"config_type": command_type, "values": parameters}
            )

        # Generic fallback
        return MovementCommand(
            command_type=command_type.lower(),
            parameters={"values": parameters} if parameters else {}
        )

    async def open_gripper(self) -> None:
        """Open the gripper."""
        if self._gripper_open:
            return  # Already open

        command = MovementCommand(command_type="gripper_open", tool_action="grip_open")
        result = await self.async_wrapper.execute_movement(command)
        if result.success:
            self._gripper_open = True
        else:
            raise HardwareError(f"Failed to open gripper: {result.error}", robot_id=self.robot_id)

    async def close_gripper(self) -> None:
        """Close the gripper."""
        if not self._gripper_open:
            return  # Already closed

        command = MovementCommand(command_type="gripper_close", tool_action="grip_close")
        result = await self.async_wrapper.execute_movement(command)
        if result.success:
            self._gripper_open = False
        else:
            raise HardwareError(f"Failed to close gripper: {result.error}", robot_id=self.robot_id)

    async def move_to_position(self, position: Any, move_type: str = "linear") -> Any:
        """
        Internal method to move robot to specified position.

        Args:
            position: WaferPosition object with coordinates
            move_type: Movement type ('linear' or 'pose')

        Returns:
            Movement result
        """
        command = MovementCommand(
            command_type="MoveLin" if move_type == "linear" else "MovePose",
            target_position={
                "x": position.x,
                "y": position.y,
                "z": position.z,
                "alpha": position.alpha,
                "beta": position.beta,
                "gamma": position.gamma
            },
            speed=self.movement_params.get("speed", 35.0),
            acceleration=self.movement_params.get("acceleration", 50.0)
        )

        result = await self.async_wrapper.execute_movement(command)
        if not result.success:
            raise HardwareError(f"Movement failed: {result.error}", robot_id=self.robot_id)

        return result

    async def initialize_gripper(self) -> None:
        """Initialize gripper to known state."""
        try:
            await self.open_gripper()
            self.logger.info("Gripper initialized to open state")
        except Exception as e:
            self.logger.warning(f"Gripper initialization failed: {e}")

    async def check_robot_status_after_motion(self, wafer_num: int) -> None:
        """
        Check robot status after motion sequence to detect collisions/errors.

        Args:
            wafer_num: Wafer number being processed
        """
        driver = self.async_wrapper.robot_driver
        if not hasattr(driver, 'get_robot_instance'):
            return

        robot_instance = driver.get_robot_instance()
        if not robot_instance or not hasattr(robot_instance, 'GetStatusRobot'):
            return

        try:
            status = robot_instance.GetStatusRobot()
            if getattr(status, 'error_status', False):
                raise HardwareError(f"Robot error after wafer {wafer_num}", robot_id=self.robot_id)
            if getattr(status, 'pause_motion_status', False):
                raise HardwareError(f"Robot paused after wafer {wafer_num}", robot_id=self.robot_id)
        except HardwareError:
            raise
        except Exception as e:
            self.logger.debug(f"Status check warning: {e}")
