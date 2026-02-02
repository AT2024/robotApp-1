"""
Async robot wrapper for non-blocking robot operations.
Provides thread pool execution, connection pooling, and batched operations.
"""

import asyncio
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, Any, List, Optional, Callable, Union
from dataclasses import dataclass, field
from enum import Enum
from abc import ABC, abstractmethod

from .exceptions import HardwareError, ValidationError
from utils.logger import get_logger


class CommandType(Enum):
    """Types of robot commands"""
    MOVEMENT = "movement"
    STATUS_CHECK = "status_check"
    CONFIGURATION = "configuration"
    PROTOCOL = "protocol"
    EMERGENCY = "emergency"


@dataclass
class MovementCommand:
    """Represents a robot movement command"""
    command_type: str
    target_position: Optional[Dict[str, float]] = None
    speed: Optional[float] = None
    acceleration: Optional[float] = None
    force: Optional[float] = None
    tool_action: Optional[str] = None
    parameters: Dict[str, Any] = field(default_factory=dict)
    
    def validate(self) -> bool:
        """Validate command parameters"""
        if not self.command_type:
            raise ValidationError("Command type is required", field="command_type")
        
        if self.target_position:
            required_coords = {"x", "y", "z"}
            if not required_coords.issubset(self.target_position.keys()):
                raise ValidationError(
                    f"Position must include {required_coords}",
                    field="target_position"
                )
        
        return True


@dataclass
class CommandResult:
    """Result of a robot command execution"""
    command_id: str
    success: bool
    result: Any = None
    error: Optional[str] = None
    execution_time: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)


class AsyncRobotWrapper:
    """
    Async wrapper for robot operations with performance optimizations.
    
    Provides non-blocking operations, connection pooling, command batching,
    and efficient thread pool management for synchronous robot drivers.
    """
    
    def __init__(
        self,
        robot_id: str,
        robot_driver: Any,  # Original synchronous robot driver
        max_workers: int = 4,
        command_timeout: float = 30.0,
        batch_size: int = 10,
        batch_timeout: float = 0.1
    ):
        self.robot_id = robot_id
        self.robot_driver = robot_driver
        self.max_workers = max_workers
        self.command_timeout = command_timeout
        self.batch_size = batch_size
        self.batch_timeout = batch_timeout
        
        # Thread pool for blocking operations
        self.executor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix=f"robot_{robot_id}"
        )
        
        # Command batching
        self._pending_commands: List[Dict[str, Any]] = []
        self._batch_lock = asyncio.Lock()
        self._batch_task: Optional[asyncio.Task] = None
        
        # Performance tracking
        self._command_stats = {
            "total_commands": 0,
            "successful_commands": 0,
            "failed_commands": 0,
            "average_execution_time": 0.0,
            "command_types": {}
        }
        
        # Connection state
        self._connected = False
        self._last_status_check = 0.0
        self._status_cache = {}
        self._status_cache_ttl = 1.0  # Cache status for 1 second
        
        self.logger = get_logger(f"async_robot_{robot_id}")
        
        # Start batch processing
        self._start_batch_processing()
    
    async def __aenter__(self):
        """Async context manager entry"""
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        await self.shutdown()
    
    def _start_batch_processing(self):
        """Start the batch processing task"""
        if self._batch_task is None or self._batch_task.done():
            self._batch_task = asyncio.create_task(self._process_command_batches())
    
    async def shutdown(self):
        """Shutdown the async wrapper"""
        # Cancel batch processing
        if self._batch_task:
            self._batch_task.cancel()
            try:
                await self._batch_task
            except asyncio.CancelledError:
                pass
        
        # Shutdown executor
        self.executor.shutdown(wait=True)
        self.logger.info(f"AsyncRobotWrapper for {self.robot_id} shutdown complete")
    
    async def get_status(self, use_cache: bool = True) -> Dict[str, Any]:
        """
        Get robot status with caching for performance.

        Args:
            use_cache: Whether to use cached status if available

        Returns:
            Robot status dictionary
        """
        current_time = time.time()

        # Use cache if available and fresh
        if (use_cache and
            self._status_cache and
            current_time - self._last_status_check < self._status_cache_ttl):
            return self._status_cache

        status_start_time = time.time()
        
        try:
            # Execute in thread pool to avoid blocking
            loop = asyncio.get_event_loop()
            status = await asyncio.wait_for(
                loop.run_in_executor(
                    self.executor,
                    self._get_status_sync
                ),
                timeout=self.command_timeout
            )
            
            # Update cache
            self._status_cache = status
            self._last_status_check = current_time

            return status
            
        except asyncio.TimeoutError:
            status_duration = time.time() - status_start_time
            error_msg = f"Status check timeout for robot {self.robot_id} after {status_duration:.3f}s"
            self.logger.error(error_msg)
            raise HardwareError(error_msg, robot_id=self.robot_id)
        except Exception as e:
            status_duration = time.time() - status_start_time
            error_msg = f"Status check failed for robot {self.robot_id} after {status_duration:.3f}s: {e}"
            self.logger.error(error_msg)
            raise HardwareError(error_msg, robot_id=self.robot_id)
    
    def _call_robot_method(self, robot, method_name: str, *args, log_info: str = None) -> bool:
        """Call a robot method if available, with optional info logging. Returns True if called."""
        if not hasattr(robot, method_name):
            self.logger.warning(f"{method_name} not available on robot {self.robot_id}")
            return False
        getattr(robot, method_name)(*args)
        if log_info:
            self.logger.info(f"{log_info} for {self.robot_id}")
        return True

    def _get_status_sync(self) -> Dict[str, Any]:
        """Synchronous status check (runs in thread pool)"""
        if hasattr(self.robot_driver, 'GetStatusRobot'):
            status = self.robot_driver.GetStatusRobot()
            return {
                "connected": True,
                "error_status": status.error_status if status else False,
                "homing_status": status.homing_status if status else False,
                "activation_status": status.activation_status if status else False,
                "paused": status.paused if status else False,
                "end_of_cycle": status.end_of_cycle if status else False
            }
        else:
            return {"connected": self._connected, "status": "unknown"}
    
    async def delay(self, milliseconds: int):
        """Non-blocking delay operation"""
        if milliseconds <= 0:
            return
        
        # Use asyncio.sleep instead of blocking robot delay
        await asyncio.sleep(milliseconds / 1000.0)
    
    async def execute_movement(self, command: MovementCommand) -> CommandResult:
        """
        Execute a movement command asynchronously.

        Args:
            command: Movement command to execute

        Returns:
            Command execution result
        """
        command.validate()

        command_id = f"{self.robot_id}_{int(time.time() * 1000)}"
        start_time = time.time()

        self.logger.info(f"Executing {command.command_type} command {command_id}")

        try:
            loop = asyncio.get_event_loop()
            result = await asyncio.wait_for(
                loop.run_in_executor(
                    self.executor,
                    self._execute_movement_sync,
                    command
                ),
                timeout=self.command_timeout
            )
            
            execution_time = time.time() - start_time
            
            await self._update_command_stats(CommandType.MOVEMENT, True, execution_time)

            self.logger.info(f"Command {command_id} completed in {execution_time:.3f}s")
            
            return CommandResult(
                command_id=command_id,
                success=True,
                result=result,
                execution_time=execution_time
            )
            
        except asyncio.TimeoutError:
            execution_time = time.time() - start_time
            await self._update_command_stats(CommandType.MOVEMENT, False, execution_time)
            error_msg = f"Movement timeout after {self.command_timeout}s"
            self.logger.error(f"Command {command_id} timed out: {error_msg}")
            return CommandResult(
                command_id=command_id,
                success=False,
                error=error_msg,
                execution_time=execution_time
            )
        except Exception as e:
            execution_time = time.time() - start_time
            await self._update_command_stats(CommandType.MOVEMENT, False, execution_time)
            self.logger.error(f"Command {command_id} failed: {e}")
            return CommandResult(
                command_id=command_id,
                success=False,
                error=str(e),
                execution_time=execution_time
            )

    async def wait_idle(self, timeout: float = 30.0) -> None:
        """Wait for all queued robot motions to complete with timeout protection.

        This method blocks until the robot's motion queue is empty,
        ensuring all previously queued commands have finished executing.
        Critical for preventing buffer overflow when queuing many commands.

        Args:
            timeout: Maximum time to wait in seconds (default: 30s, matches mecademicpy WaitHomed pattern)

        Raises:
            HardwareError: If timeout occurs or robot is in error/paused state
        """
        self.logger.debug(f"Waiting for robot {self.robot_id} motion queue (timeout={timeout}s)")

        try:
            robot = self.robot_driver.get_robot_instance()
            if robot and hasattr(robot, 'WaitIdle'):
                loop = asyncio.get_event_loop()

                # Add timeout protection to prevent infinite hang
                # If robot hits obstacle or enters error state, motion queue never completes
                await asyncio.wait_for(
                    loop.run_in_executor(
                        self.executor,
                        robot.WaitIdle
                    ),
                    timeout=timeout
                )
                self.logger.debug(f"Robot {self.robot_id} motion queue completed")
            else:
                self.logger.warning(f"WaitIdle not available for robot {self.robot_id}")

        except asyncio.TimeoutError:
            # Check robot status to diagnose why timeout occurred
            error_msg = f"WaitIdle timeout after {timeout}s for robot {self.robot_id}"

            if robot and hasattr(robot, 'GetStatusRobot'):
                try:
                    status = robot.GetStatusRobot()
                    error_status = getattr(status, 'error_status', False)
                    paused = getattr(status, 'pause_motion_status', False)

                    error_msg += f" - Robot status: error={error_status}, paused={paused}"

                    if error_status or paused:
                        error_msg += " (Likely collision or torque limit exceeded)"

                except Exception as status_e:
                    error_msg += f" (Could not read robot status: {status_e})"

            self.logger.error(error_msg)
            raise HardwareError(error_msg, robot_id=self.robot_id)

        except Exception as e:
            self.logger.error(f"Error waiting for robot {self.robot_id} to idle: {e}")
            raise

    def _execute_movement_sync(self, command: MovementCommand) -> Any:
        """Execute movement command synchronously (runs in thread pool)"""
        try:
            # Get the actual robot instance from the driver wrapper
            actual_robot = None
            if hasattr(self.robot_driver, 'get_robot_instance'):
                actual_robot = self.robot_driver.get_robot_instance()
            
            if not actual_robot:
                error_msg = f"No robot instance available for {self.robot_id} - command '{command.command_type}' cannot be executed"
                self.logger.error(f"{error_msg}. Check driver connection status.")
                raise HardwareError(f"Robot {self.robot_id} not connected", robot_id=self.robot_id)
            
            # Set movement parameters if provided
            if command.speed is not None and hasattr(actual_robot, 'SetJointVel'):
                actual_robot.SetJointVel(command.speed)

            if command.acceleration is not None and hasattr(actual_robot, 'SetJointAcc'):
                actual_robot.SetJointAcc(command.acceleration)
            
            # Execute movement based on command type
            if command.command_type == "move_joints":
                if hasattr(actual_robot, 'MoveJoints'):
                    actual_robot.MoveJoints(
                        command.target_position["joint1"],
                        command.target_position["joint2"],
                        command.target_position["joint3"],
                        command.target_position["joint4"],
                        command.target_position["joint5"],
                        command.target_position["joint6"]
                    )
                    self.logger.info(f"Executed MoveJoints command for {self.robot_id}")
                else:
                    self.logger.warning(f"MoveJoints not available on robot {self.robot_id}")
            
            elif command.command_type == "MovePose":
                if hasattr(actual_robot, 'MovePose'):
                    actual_robot.MovePose(
                        command.target_position["x"],
                        command.target_position["y"],
                        command.target_position["z"],
                        command.target_position.get("alpha", 0),
                        command.target_position.get("beta", 0),
                        command.target_position.get("gamma", 0)
                    )
                    self.logger.info(f"Executed MovePose command for {self.robot_id}: x={command.target_position['x']}, y={command.target_position['y']}, z={command.target_position['z']}")
                else:
                    self.logger.warning(f"MovePose not available on robot {self.robot_id}")
            
            elif command.command_type == "MoveLin":
                if hasattr(actual_robot, 'MoveLin'):
                    actual_robot.MoveLin(
                        command.target_position["x"],
                        command.target_position["y"],
                        command.target_position["z"],
                        command.target_position.get("alpha", 0),
                        command.target_position.get("beta", 0),
                        command.target_position.get("gamma", 0)
                    )
                    self.logger.info(f"Executed MoveLin command for {self.robot_id}")
                else:
                    self.logger.warning(f"MoveLin not available on robot {self.robot_id}")
            
            # Tool actions (via tool_action field or command_type)
            gripper_action = command.tool_action or (
                command.command_type if command.command_type in ("GripperOpen", "GripperClose", "MoveGripper") else None
            )

            if gripper_action in ("grip_open", "GripperOpen"):
                self._call_robot_method(actual_robot, 'GripperOpen', log_info="Executed GripperOpen")
            elif gripper_action in ("grip_close", "GripperClose"):
                self._call_robot_method(actual_robot, 'GripperClose', log_info="Executed GripperClose")
            elif gripper_action in ("grip_move", "MoveGripper"):
                width = command.parameters.get("width", 0) if command.parameters else 0
                self._call_robot_method(actual_robot, 'MoveGripper', width, log_info=f"MoveGripper to width {width}")
            
            # Delay command
            elif command.command_type == "Delay":
                duration = command.parameters.get("duration", 0) if command.parameters else 0
                if duration > 0:
                    # Prefer robot's Delay method to queue delay in motion buffer
                    if hasattr(actual_robot, 'Delay'):
                        actual_robot.Delay(duration)
                        self.logger.info(f"Queued robot Delay of {duration} seconds for {self.robot_id}")
                    else:
                        # Fallback to Python sleep if robot doesn't support Delay
                        self.logger.info(f"Executing Python sleep delay of {duration} seconds for {self.robot_id}")
                        time.sleep(duration)
                else:
                    self.logger.warning(f"Invalid delay duration: {duration} for {self.robot_id}")
            
            # Configuration commands
            elif command.command_type == "config":
                config_type = command.parameters.get("config_type")
                values = command.parameters.get("values", [])

                # Map config types to (method_name, required_args, log_description)
                config_map = {
                    "SetJointVel": (1, "joint velocity"),
                    "SetJointAcc": (1, "joint acceleration"),
                    "SetGripperForce": (1, "gripper force"),
                    "SetTorqueLimits": (6, "torque limits"),
                    "SetTorqueLimitsCfg": (2, "torque limits config"),
                    "SetBlending": (1, "blending"),
                    "SetConf": (3, "configuration"),
                    "SetCartVel": (1, "cartesian velocity"),
                    "SetCartAcc": (1, "cartesian acceleration"),
                }

                if config_type in config_map:
                    required_args, description = config_map[config_type]
                    if len(values) >= required_args:
                        args = values[:required_args]
                        self._call_robot_method(
                            actual_robot, config_type, *args,
                            log_info=f"Set {description} to {args[0] if required_args == 1 else values}"
                        )
                else:
                    self.logger.warning(f"Unknown config command: {config_type} with values {values}")
            
            elif command.command_type == "emergency_stop":
                self.logger.critical(f"EMERGENCY STOP triggered for {self.robot_id}")
                emergency_executed = False

                # Step 1: Immediate stop current movement
                if hasattr(actual_robot, 'PauseMotion'):
                    actual_robot.PauseMotion()
                    self.logger.critical(f"PauseMotion() executed for {self.robot_id}")
                    emergency_executed = True
                    if hasattr(self.robot_driver, '_software_estop_active'):
                        self.robot_driver._software_estop_active = True

                # Step 2: Clear remaining movement queue
                if hasattr(actual_robot, 'ClearMotion'):
                    actual_robot.ClearMotion()
                    self.logger.critical(f"ClearMotion() executed for {self.robot_id}")
                    emergency_executed = True

                    if hasattr(actual_robot, 'BrakesOn'):
                        try:
                            actual_robot.BrakesOn()
                            self.logger.critical(f"Brakes engaged for {self.robot_id}")
                        except Exception as brake_error:
                            self.logger.warning(f"Could not engage brakes: {brake_error}")
                
                # STEP 3: Fallback if neither PauseMotion nor ClearMotion available
                if not emergency_executed and hasattr(actual_robot, 'StopMotion'):
                    actual_robot.StopMotion()
                    self.logger.critical(f"StopMotion() fallback executed for {self.robot_id}")
                    emergency_executed = True

                if emergency_executed:
                    self.logger.critical(f"Emergency stop completed for {self.robot_id} - robot halted")
                else:
                    self.logger.error(f"Emergency stop FAILED for {self.robot_id} - no suitable methods")
            
            else:
                self.logger.warning(f"Unknown command type: {command.command_type} for robot {self.robot_id}")
            
            # Check for robot error state after command execution
            if hasattr(actual_robot, 'GetStatusRobot'):
                try:
                    robot_status = actual_robot.GetStatusRobot()
                    if robot_status and hasattr(robot_status, 'error_status'):
                        if robot_status.error_status:
                            error_msg = f"Robot {self.robot_id} entered error state after {command.command_type} command"
                            self.logger.error(error_msg)
                            raise HardwareError(error_msg, robot_id=self.robot_id)
                except Exception as status_error:
                    self.logger.warning(f"Could not check robot status after command for {self.robot_id}: {status_error}")
            
            return {"status": "completed", "command_type": command.command_type}
            
        except Exception as e:
            self.logger.error(f"Movement execution failed: {e}")
            raise HardwareError(f"Movement failed: {e}", robot_id=self.robot_id)
    
    async def execute_batch(self, commands: List[MovementCommand]) -> List[CommandResult]:
        """
        Execute multiple commands as a batch for efficiency.
        
        Args:
            commands: List of commands to execute
            
        Returns:
            List of command results
        """
        if not commands:
            return []
        
        # Validate all commands first
        for command in commands:
            command.validate()
        
        start_time = time.time()
        results = []
        
        try:
            # Execute batch in thread pool
            loop = asyncio.get_event_loop()
            batch_results = await asyncio.wait_for(
                loop.run_in_executor(
                    self.executor,
                    self._execute_batch_sync,
                    commands
                ),
                timeout=self.command_timeout * len(commands)
            )
            
            execution_time = time.time() - start_time
            
            # Create results
            for i, (command, result) in enumerate(zip(commands, batch_results)):
                command_id = f"{self.robot_id}_batch_{int(start_time * 1000)}_{i}"
                
                if isinstance(result, Exception):
                    results.append(CommandResult(
                        command_id=command_id,
                        success=False,
                        error=str(result),
                        execution_time=execution_time / len(commands)
                    ))
                else:
                    results.append(CommandResult(
                        command_id=command_id,
                        success=True,
                        result=result,
                        execution_time=execution_time / len(commands)
                    ))
            
            return results
            
        except Exception as e:
            execution_time = time.time() - start_time
            
            # Return error result for all commands
            for i, command in enumerate(commands):
                command_id = f"{self.robot_id}_batch_{int(start_time * 1000)}_{i}"
                results.append(CommandResult(
                    command_id=command_id,
                    success=False,
                    error=f"Batch execution failed: {e}",
                    execution_time=execution_time / len(commands)
                ))
            
            return results
    
    def _execute_batch_sync(self, commands: List[MovementCommand]) -> List[Any]:
        """Execute batch of commands synchronously"""
        results = []
        
        for command in commands:
            try:
                result = self._execute_movement_sync(command)
                results.append(result)
            except Exception as e:
                results.append(e)
        
        return results
    
    async def add_to_batch(self, command: MovementCommand):
        """Add command to pending batch for later execution"""
        async with self._batch_lock:
            self._pending_commands.append({
                "command": command,
                "timestamp": time.time()
            })
    
    async def _process_command_batches(self):
        """Background task to process command batches"""
        while True:
            try:
                await asyncio.sleep(self.batch_timeout)
                
                async with self._batch_lock:
                    if len(self._pending_commands) >= self.batch_size:
                        # Process full batch
                        batch = self._pending_commands[:self.batch_size]
                        self._pending_commands = self._pending_commands[self.batch_size:]
                        
                        commands = [item["command"] for item in batch]
                        await self.execute_batch(commands)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(f"Error in batch processing: {e}")
    
    async def _update_command_stats(
        self, 
        command_type: CommandType, 
        success: bool, 
        execution_time: float
    ):
        """Update command execution statistics"""
        self._command_stats["total_commands"] += 1
        
        if success:
            self._command_stats["successful_commands"] += 1
        else:
            self._command_stats["failed_commands"] += 1
        
        # Update average execution time
        total = self._command_stats["total_commands"]
        current_avg = self._command_stats["average_execution_time"]
        self._command_stats["average_execution_time"] = (
            (current_avg * (total - 1) + execution_time) / total
        )
        
        # Update command type stats
        type_key = command_type.value
        if type_key not in self._command_stats["command_types"]:
            self._command_stats["command_types"][type_key] = {
                "count": 0,
                "success_rate": 0.0,
                "avg_time": 0.0
            }
        
        type_stats = self._command_stats["command_types"][type_key]
        type_stats["count"] += 1

        # Log performance on failures only (success logged at command level)
        if not success:
            failure_rate = (self._command_stats["failed_commands"] / total) * 100
            self.logger.warning(f"Robot {self.robot_id} failure rate: {failure_rate:.1f}%")

        # Update success rate for this command type
        if success:
            type_stats["success_rate"] = (
                (type_stats["success_rate"] * (type_stats["count"] - 1) + 1.0) / 
                type_stats["count"]
            )
        else:
            type_stats["success_rate"] = (
                type_stats["success_rate"] * (type_stats["count"] - 1) / 
                type_stats["count"]
            )
        
        # Update average time for this command type
        type_stats["avg_time"] = (
            (type_stats["avg_time"] * (type_stats["count"] - 1) + execution_time) / 
            type_stats["count"]
        )
    
    async def get_performance_stats(self) -> Dict[str, Any]:
        """Get performance statistics"""
        return {
            "robot_id": self.robot_id,
            "executor_stats": {
                "max_workers": self.max_workers,
                "active_threads": self.executor._threads.__len__() if hasattr(self.executor, '_threads') else 0
            },
            "command_stats": self._command_stats.copy(),
            "batch_stats": {
                "pending_commands": len(self._pending_commands),
                "batch_size": self.batch_size,
                "batch_timeout": self.batch_timeout
            },
            "cache_stats": {
                "status_cache_age": time.time() - self._last_status_check,
                "status_cache_ttl": self._status_cache_ttl
            }
        }
    
    async def reset_stats(self):
        """Reset performance statistics"""
        self._command_stats = {
            "total_commands": 0,
            "successful_commands": 0,
            "failed_commands": 0,
            "average_execution_time": 0.0,
            "command_types": {}
        }
        self.logger.info(f"Performance stats reset for robot {self.robot_id}")


class AsyncRobotFactory:
    """Factory for creating AsyncRobotWrapper instances"""
    
    @staticmethod
    def create_meca_wrapper(
        robot_id: str,
        meca_robot,
        config: Dict[str, Any]
    ) -> AsyncRobotWrapper:
        """Create AsyncRobotWrapper for Mecademic robot"""
        return AsyncRobotWrapper(
            robot_id=robot_id,
            robot_driver=meca_robot,
            max_workers=config.get("max_workers", 4),
            command_timeout=config.get("timeout", 30.0),
            batch_size=config.get("batch_size", 10),
            batch_timeout=config.get("batch_timeout", 0.1)
        )
    
    @staticmethod
    def create_ot2_wrapper(
        robot_id: str,
        ot2_client,
        config: Dict[str, Any]
    ) -> AsyncRobotWrapper:
        """Create AsyncRobotWrapper for OT2 robot"""
        return AsyncRobotWrapper(
            robot_id=robot_id,
            robot_driver=ot2_client,
            max_workers=config.get("max_workers", 2),  # OT2 typically needs fewer workers
            command_timeout=config.get("timeout"),  # Longer timeout for protocols
            batch_size=config.get("batch_size", 5),
            batch_timeout=config.get("batch_timeout", 0.2)
        )