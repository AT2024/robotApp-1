"""
Async robot wrapper for non-blocking robot operations.
Provides thread pool execution, connection pooling, and batched operations.
"""

import asyncio
import time
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, Any, List, Optional, Callable, Union
from dataclasses import dataclass, field
from enum import Enum
from abc import ABC, abstractmethod

from .exceptions import HardwareError, ValidationError


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
        
        self.logger = logging.getLogger(f"async_robot.{robot_id}")
        
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
            self.logger.debug(f"Using cached status for robot {self.robot_id} (age: {current_time - self._last_status_check:.3f}s)")
            return self._status_cache
        
        status_start_time = time.time()
        self.logger.debug(f"Requesting fresh status from robot {self.robot_id}")
        
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
            
            status_duration = time.time() - status_start_time
            
            # Update cache
            self._status_cache = status
            self._last_status_check = current_time
            
            self.logger.debug(f"Robot {self.robot_id} status retrieved in {status_duration:.3f}s: {status}")
            
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
        
        # Log command transmission
        self.logger.info(f"Transmitting movement command {command_id} to robot {self.robot_id}")
        self.logger.debug(f"Command details: type={command.command_type}, position={command.target_position}, speed={command.speed}")
        
        try:
            # Execute in thread pool
            self.logger.debug(f"Executing movement command {command_id} in thread pool")
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
            
            # Update statistics
            await self._update_command_stats(CommandType.MOVEMENT, True, execution_time)
            
            self.logger.info(f"Movement command {command_id} completed successfully in {execution_time:.3f}s")
            
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
            self.logger.error(f"Movement command {command_id} timed out after {execution_time:.3f}s (timeout: {self.command_timeout}s)")
            
            return CommandResult(
                command_id=command_id,
                success=False,
                error=error_msg,
                execution_time=execution_time
            )
        except Exception as e:
            execution_time = time.time() - start_time
            await self._update_command_stats(CommandType.MOVEMENT, False, execution_time)
            
            self.logger.error(f"Movement command {command_id} failed after {execution_time:.3f}s: {str(e)}")
            
            return CommandResult(
                command_id=command_id,
                success=False,
                error=str(e),
                execution_time=execution_time
            )
    
    def _execute_movement_sync(self, command: MovementCommand) -> Any:
        """Execute movement command synchronously (runs in thread pool)"""
        try:
            # Get the actual robot instance from the driver wrapper
            actual_robot = None
            if hasattr(self.robot_driver, 'get_robot_instance'):
                actual_robot = self.robot_driver.get_robot_instance()
            
            if not actual_robot:
                # CRITICAL: Do not fall back to simulation - this indicates a connection problem
                error_msg = f"❌ No robot instance available for {self.robot_id} - command '{command.command_type}' cannot be executed"
                self.logger.error(error_msg)
                self.logger.error(f"💡 Robot connection may have failed. Check driver connection status.")
                raise HardwareError(f"Robot {self.robot_id} not connected: {error_msg}", robot_id=self.robot_id)
            
            self.logger.debug(f"✅ Using actual robot instance for {self.robot_id} hardware commands")
            
            # Set movement parameters if provided
            if command.speed is not None:
                if hasattr(actual_robot, 'SetJointVel'):
                    actual_robot.SetJointVel(command.speed)
                    self.logger.debug(f"Set joint velocity to {command.speed} for {self.robot_id}")
            
            if command.acceleration is not None:
                if hasattr(actual_robot, 'SetJointAcc'):
                    actual_robot.SetJointAcc(command.acceleration)
                    self.logger.debug(f"Set joint acceleration to {command.acceleration} for {self.robot_id}")
            
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
            
            # Tool actions
            if command.tool_action == "grip_open":
                if hasattr(actual_robot, 'GripperOpen'):
                    actual_robot.GripperOpen()
                    self.logger.info(f"Executed GripperOpen command for {self.robot_id}")
                else:
                    self.logger.warning(f"GripperOpen not available on robot {self.robot_id}")
            elif command.tool_action == "grip_close":
                if hasattr(actual_robot, 'GripperClose'):
                    actual_robot.GripperClose()
                    self.logger.info(f"Executed GripperClose command for {self.robot_id}")
                else:
                    self.logger.warning(f"GripperClose not available on robot {self.robot_id}")
            elif command.tool_action == "grip_move":
                width = command.parameters.get("width", 0) if command.parameters else 0
                if hasattr(actual_robot, 'MoveGripper'):
                    actual_robot.MoveGripper(width)
                    self.logger.info(f"Executed MoveGripper to width {width} for {self.robot_id}")
                else:
                    self.logger.warning(f"MoveGripper not available on robot {self.robot_id}")
            
            # Direct gripper command types (alternative to tool_action)
            elif command.command_type == "GripperOpen":
                if hasattr(actual_robot, 'GripperOpen'):
                    actual_robot.GripperOpen()
                    self.logger.info(f"Executed GripperOpen command for {self.robot_id}")
                else:
                    self.logger.warning(f"GripperOpen not available on robot {self.robot_id}")
            
            elif command.command_type == "GripperClose":
                if hasattr(actual_robot, 'GripperClose'):
                    actual_robot.GripperClose()
                    self.logger.info(f"Executed GripperClose command for {self.robot_id}")
                else:
                    self.logger.warning(f"GripperClose not available on robot {self.robot_id}")
            
            elif command.command_type == "MoveGripper":
                width = command.parameters.get("width", 0) if command.parameters else 0
                if hasattr(actual_robot, 'MoveGripper'):
                    actual_robot.MoveGripper(width)
                    self.logger.info(f"Executed MoveGripper to width {width} for {self.robot_id}")
                else:
                    self.logger.warning(f"MoveGripper not available on robot {self.robot_id}")
            
            # Delay command
            elif command.command_type == "Delay":
                duration = command.parameters.get("duration", 0) if command.parameters else 0
                if duration > 0:
                    self.logger.info(f"Executing delay of {duration} seconds for {self.robot_id}")
                    time.sleep(duration)  # Synchronous sleep in thread pool is OK
                else:
                    self.logger.warning(f"Invalid delay duration: {duration} for {self.robot_id}")
            
            # Configuration commands
            elif command.command_type == "config":
                config_type = command.parameters.get("config_type")
                values = command.parameters.get("values", [])
                
                self.logger.debug(f"Executing configuration command '{config_type}' with values {values} for {self.robot_id}")
                
                if config_type == "SetJointVel" and len(values) >= 1:
                    if hasattr(actual_robot, 'SetJointVel'):
                        actual_robot.SetJointVel(values[0])
                        self.logger.info(f"Set joint velocity to {values[0]} for {self.robot_id}")
                    else:
                        self.logger.warning(f"SetJointVel not available on robot {self.robot_id}")
                        
                elif config_type == "SetJointAcc" and len(values) >= 1:
                    if hasattr(actual_robot, 'SetJointAcc'):
                        actual_robot.SetJointAcc(values[0])
                        self.logger.info(f"Set joint acceleration to {values[0]} for {self.robot_id}")
                    else:
                        self.logger.warning(f"SetJointAcc not available on robot {self.robot_id}")
                        
                elif config_type == "SetGripperForce" and len(values) >= 1:
                    if hasattr(actual_robot, 'SetGripperForce'):
                        actual_robot.SetGripperForce(values[0])
                        self.logger.info(f"Set gripper force to {values[0]} for {self.robot_id}")
                    else:
                        self.logger.warning(f"SetGripperForce not available on robot {self.robot_id}")
                        
                elif config_type == "SetTorqueLimits" and len(values) >= 6:
                    if hasattr(actual_robot, 'SetTorqueLimits'):
                        actual_robot.SetTorqueLimits(values[0], values[1], values[2], values[3], values[4], values[5])
                        self.logger.info(f"Set torque limits to {values} for {self.robot_id}")
                    else:
                        self.logger.warning(f"SetTorqueLimits not available on robot {self.robot_id}")
                        
                elif config_type == "SetTorqueLimitsCfg" and len(values) >= 2:
                    if hasattr(actual_robot, 'SetTorqueLimitsCfg'):
                        actual_robot.SetTorqueLimitsCfg(values[0], values[1])
                        self.logger.info(f"Set torque limits config to {values} for {self.robot_id}")
                    else:
                        self.logger.warning(f"SetTorqueLimitsCfg not available on robot {self.robot_id}")
                        
                elif config_type == "SetBlending" and len(values) >= 1:
                    if hasattr(actual_robot, 'SetBlending'):
                        actual_robot.SetBlending(values[0])
                        self.logger.info(f"Set blending to {values[0]} for {self.robot_id}")
                    else:
                        self.logger.warning(f"SetBlending not available on robot {self.robot_id}")
                        
                elif config_type == "SetConf" and len(values) >= 3:
                    if hasattr(actual_robot, 'SetConf'):
                        actual_robot.SetConf(values[0], values[1], values[2])
                        self.logger.info(f"Set configuration to {values} for {self.robot_id}")
                    else:
                        self.logger.warning(f"SetConf not available on robot {self.robot_id}")
                        
                elif config_type == "SetCartVel" and len(values) >= 1:
                    if hasattr(actual_robot, 'SetCartVel'):
                        actual_robot.SetCartVel(values[0])
                        self.logger.info(f"Set cartesian velocity to {values[0]} for {self.robot_id}")
                    else:
                        self.logger.warning(f"SetCartVel not available on robot {self.robot_id}")
                        
                elif config_type == "SetCartAcc" and len(values) >= 1:
                    if hasattr(actual_robot, 'SetCartAcc'):
                        actual_robot.SetCartAcc(values[0])
                        self.logger.info(f"Set cartesian acceleration to {values[0]} for {self.robot_id}")
                    else:
                        self.logger.warning(f"SetCartAcc not available on robot {self.robot_id}")
                        
                else:
                    self.logger.warning(f"Unknown configuration command: {config_type} with values {values} for {self.robot_id}")
            
            elif command.command_type == "emergency_stop":
                # EMERGENCY STOP: Immediate halt using proper Mecademic API methods
                self.logger.critical(f"🚨 EMERGENCY STOP triggered for {self.robot_id}")
                
                emergency_executed = False
                
                # STEP 1: Immediate stop current movement
                if hasattr(actual_robot, 'PauseMotion'):
                    actual_robot.PauseMotion()
                    self.logger.critical(f"✅ PauseMotion() immediate stop executed for {self.robot_id}")
                    emergency_executed = True

                # STEP 2: Clear remaining movement queue  
                if hasattr(actual_robot, 'ClearMotion'):
                    actual_robot.ClearMotion()
                    self.logger.critical(f"✅ ClearMotion() queue cleared for {self.robot_id}")
                    emergency_executed = True
                    
                    # Also engage brakes if available for additional safety
                    if hasattr(actual_robot, 'BrakesOn'):
                        try:
                            actual_robot.BrakesOn()
                            self.logger.critical(f"✅ Emergency brakes engaged for {self.robot_id}")
                        except Exception as brake_error:
                            self.logger.warning(f"⚠️ Could not engage brakes during emergency stop: {brake_error}")
                
                # STEP 3: Fallback if neither PauseMotion nor ClearMotion available
                if not emergency_executed and hasattr(actual_robot, 'StopMotion'):
                    actual_robot.StopMotion()
                    self.logger.critical(f"✅ StopMotion() fallback executed for {self.robot_id}")
                    emergency_executed = True
                
                else:
                    self.logger.error(f"❌ No emergency stop methods available for {self.robot_id}")
                    # Try alternative stop methods if available
                    if hasattr(actual_robot, 'StopMotion'):
                        actual_robot.StopMotion()
                        self.logger.warning(f"⚠️ StopMotion() used as fallback for {self.robot_id}")
                        emergency_executed = True
                
                if emergency_executed:
                    self.logger.critical(f"🛑 Emergency stop completed for {self.robot_id} - robot halted in place")
                    # Note: No gripper state change, no movement to safe position (as requested)
                else:
                    self.logger.error(f"❌ Emergency stop FAILED for {self.robot_id} - no suitable methods available")
            
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
        
        # Log performance metrics
        success_rate = (self._command_stats["successful_commands"] / total) * 100
        self.logger.info(f"Robot {self.robot_id} performance: {total} commands, {success_rate:.1f}% success rate, {execution_time:.3f}s execution time")
        
        if not success:
            failure_rate = (self._command_stats["failed_commands"] / total) * 100
            self.logger.warning(f"Robot {self.robot_id} command failure: failure rate now {failure_rate:.1f}%")
        
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