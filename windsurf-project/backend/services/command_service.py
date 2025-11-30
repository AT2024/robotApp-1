"""
Robot Command Service - Common robot operations and command processing.
Provides standardized command interface for all robot types.
"""

import asyncio
import time
import traceback
import uuid
from typing import Dict, Any, Optional, List, Union, Callable, TYPE_CHECKING
from dataclasses import dataclass, field
from enum import Enum

from core.exceptions import ValidationError, RoboticsException, HardwareError
from core.state_manager import AtomicStateManager, RobotState
from core.resource_lock import ResourceLockManager
from core.settings import RoboticsSettings
from .base import BaseService, ServiceResult, OperationContext
from utils.logger import get_logger

if TYPE_CHECKING:
    from .orchestrator import RobotOrchestrator


class CommandType(Enum):
    """Standard robot command types"""
    MOVE = "move"
    PICK = "pick"
    PLACE = "place"
    HOME = "home"
    STOP = "stop"
    CALIBRATE = "calibrate"
    STATUS = "status"
    CONNECT = "connect"
    DISCONNECT = "disconnect"
    EMERGENCY_STOP = "emergency_stop"
    RESET = "reset"
    
    # High-level sequence command types
    PICKUP_SEQUENCE = "pickup_sequence"
    DROP_SEQUENCE = "drop_sequence"
    CAROUSEL_SEQUENCE = "carousel_sequence"
    CAROUSEL_MOVE = "carousel_move"
    
    # OT2 specific command types
    PROTOCOL_EXECUTION = "protocol_execution"


class CommandPriority(Enum):
    """Command execution priority levels"""
    LOW = 1
    NORMAL = 2
    HIGH = 3
    CRITICAL = 4
    EMERGENCY = 5


@dataclass
class RobotCommand:
    """Standard robot command structure"""
    command_id: str
    robot_id: str
    command_type: CommandType
    parameters: Dict[str, Any] = field(default_factory=dict)
    priority: CommandPriority = CommandPriority.NORMAL
    timeout: Optional[float] = None
    retry_count: int = 0
    max_retries: int = 3
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    status: str = "pending"
    result: Optional[Any] = None
    error: Optional[str] = None
    correlation_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CommandValidationRule:
    """Command validation rule"""
    parameter_name: str
    required: bool = True
    data_type: type = str
    min_value: Optional[Union[int, float]] = None
    max_value: Optional[Union[int, float]] = None
    allowed_values: Optional[List[Any]] = None
    validator_func: Optional[Callable] = None


class RobotCommandService(BaseService):
    """
    Service for processing and executing robot commands.
    
    Responsibilities:
    - Standardize command interface across all robot types
    - Validate command parameters and prerequisites
    - Queue and prioritize commands
    - Handle command retries and error recovery
    - Provide command history and audit trail
    - Coordinate with robot-specific services
    """
    
    def __init__(
        self,
        settings: RoboticsSettings,
        state_manager: AtomicStateManager,
        lock_manager: ResourceLockManager,
        orchestrator: 'RobotOrchestrator' = None
    ):
        super().__init__(settings, state_manager, lock_manager, "RobotCommandService")
        self.orchestrator = orchestrator
        
        self.logger = get_logger("command_service")
        
        # Command management
        self._command_queue: asyncio.PriorityQueue = asyncio.PriorityQueue()
        self._active_commands: Dict[str, RobotCommand] = {}
        self._command_history: List[RobotCommand] = []
        self._commands_lock = asyncio.Lock()
        
        # Command validation rules
        self._validation_rules: Dict[CommandType, List[CommandValidationRule]] = {}
        self._setup_validation_rules()
        
        # Command processors
        self._command_processors: Dict[str, Callable] = {}
        self._setup_command_processors()
        
        # Processing tasks
        self._processor_task: Optional[asyncio.Task] = None
        self._max_concurrent_commands = 10  # Default max concurrent commands
        self._processing_semaphore = asyncio.Semaphore(self._max_concurrent_commands)
    
    async def _on_start(self):
        """Start command processing"""
        self.logger.info("Starting Robot command service...")
        
        # Log orchestrator status
        if self.orchestrator:
            registered_services = self.orchestrator.list_robot_services()
            self.logger.info(f"Orchestrator available with registered services: {registered_services}")
        else:
            self.logger.error("NO ORCHESTRATOR AVAILABLE!")
        
        # Log available command processors
        self.logger.info(f"Available command processors: {list(self._command_processors.keys())}")
        
        # Start the command queue processor
        self._processor_task = asyncio.create_task(self._process_command_queue())
        self.logger.info("Robot command service started with command queue processor")
    
    async def _on_stop(self):
        """Stop command processing"""
        if self._processor_task:
            self._processor_task.cancel()
            try:
                await self._processor_task
            except asyncio.CancelledError:
                pass
        
        # Cancel active commands
        async with self._commands_lock:
            for command in self._active_commands.values():
                if command.status == "running":
                    command.status = "cancelled"
                    command.error = "Service shutdown"
                    command.completed_at = time.time()
        
        self.logger.info("Robot command service stopped")
    
    def _setup_validation_rules(self):
        """Setup command validation rules"""
        # Move command validation
        self._validation_rules[CommandType.MOVE] = [
            CommandValidationRule("position", required=True, data_type=dict),
            CommandValidationRule("speed", required=False, data_type=float, min_value=0.1, max_value=100.0),
            CommandValidationRule("acceleration", required=False, data_type=float, min_value=0.1, max_value=100.0)
        ]
        
        # Pick command validation
        self._validation_rules[CommandType.PICK] = [
            CommandValidationRule("position", required=True, data_type=dict),
            CommandValidationRule("force", required=False, data_type=float, min_value=0.1, max_value=50.0),
            CommandValidationRule("approach_height", required=False, data_type=float, min_value=1.0, max_value=100.0)
        ]
        
        # Place command validation
        self._validation_rules[CommandType.PLACE] = [
            CommandValidationRule("position", required=True, data_type=dict),
            CommandValidationRule("force", required=False, data_type=float, min_value=0.1, max_value=50.0),
            CommandValidationRule("approach_height", required=False, data_type=float, min_value=1.0, max_value=100.0)
        ]
        
        # Home command validation
        self._validation_rules[CommandType.HOME] = [
            CommandValidationRule("axis", required=False, data_type=str, 
                                allowed_values=["all", "x", "y", "z", "rx", "ry", "rz"])
        ]
        
        # Calibrate command validation
        self._validation_rules[CommandType.CALIBRATE] = [
            CommandValidationRule("calibration_type", required=True, data_type=str,
                                allowed_values=["position", "force", "vision", "all"])
        ]
        
        # Sequence command validation rules
        self._validation_rules[CommandType.PICKUP_SEQUENCE] = [
            CommandValidationRule("start", required=False, data_type=int, min_value=0),
            CommandValidationRule("count", required=False, data_type=int, min_value=1, max_value=55),
            CommandValidationRule("operation_type", required=False, data_type=str),
            CommandValidationRule("is_last_batch", required=False, data_type=bool)
        ]
        
        self._validation_rules[CommandType.DROP_SEQUENCE] = [
            CommandValidationRule("start", required=False, data_type=int, min_value=0),
            CommandValidationRule("count", required=False, data_type=int, min_value=1, max_value=55),
            CommandValidationRule("operation_type", required=False, data_type=str),
            CommandValidationRule("is_last_batch", required=False, data_type=bool)
        ]
        
        self._validation_rules[CommandType.CAROUSEL_SEQUENCE] = [
            CommandValidationRule("start", required=False, data_type=int, min_value=0),
            CommandValidationRule("count", required=False, data_type=int, min_value=1, max_value=11),
            CommandValidationRule("operation_type", required=False, data_type=str),
            CommandValidationRule("is_last_batch", required=False, data_type=bool)
        ]
        
        self._validation_rules[CommandType.CAROUSEL_MOVE] = [
            CommandValidationRule("position", required=True, data_type=int, min_value=0, max_value=23),
            CommandValidationRule("operation", required=False, data_type=str, allowed_values=["pickup", "drop"]),
            CommandValidationRule("wafer_id", required=False, data_type=str)
        ]
        
        # Protocol execution validation rules
        self._validation_rules[CommandType.PROTOCOL_EXECUTION] = [
            CommandValidationRule("protocol_name", required=False, data_type=str),
            CommandValidationRule("volume", required=False, data_type=float, min_value=0.1, max_value=1000.0),
            CommandValidationRule("source_well", required=False, data_type=str),
            CommandValidationRule("dest_well", required=False, data_type=str),
            CommandValidationRule("source_labware", required=False, data_type=str),
            CommandValidationRule("dest_labware", required=False, data_type=str),
            CommandValidationRule("pipette_name", required=False, data_type=str)
        ]
    
    def _setup_command_processors(self):
        """Setup command processors for different robot types"""
        self._command_processors = {
            "meca": self._process_meca_command,
            "ot2": self._process_ot2_command,
            "arduino": self._process_arduino_command,
            "carousel": self._process_carousel_command
        }
    
    async def submit_command(
        self,
        robot_id: str,
        command_type: Union[CommandType, str],
        parameters: Dict[str, Any] = None,
        priority: CommandPriority = CommandPriority.NORMAL,
        timeout: Optional[float] = None
    ) -> ServiceResult[str]:
        """
        Submit a command for execution.
        
        Args:
            robot_id: Target robot identifier
            command_type: Type of command to execute
            parameters: Command parameters
            priority: Command priority level
            timeout: Command timeout in seconds
            
        Returns:
            ServiceResult containing command ID
        """
        context = OperationContext(
            operation_id=f"submit_command_{int(time.time() * 1000)}",
            robot_id=robot_id,
            operation_type="submit_command"
        )
        
        async def _submit_command():
            # Convert string to enum if needed
            if isinstance(command_type, str):
                try:
                    cmd_type = CommandType(command_type.lower())
                    self.logger.debug(f"Converted command type '{command_type}' to enum {cmd_type}")
                except ValueError:
                    self.logger.error(f"Invalid command type: {command_type}")
                    raise ValidationError(f"Invalid command type: {command_type}")
            else:
                cmd_type = command_type
            
            # Create command with correlation ID
            command_id = f"cmd_{robot_id}_{int(time.time() * 1000)}"
            command = RobotCommand(
                command_id=command_id,
                robot_id=robot_id,
                command_type=cmd_type,
                parameters=parameters or {},
                priority=priority,
                timeout=timeout
            )
            
            # Log with correlation ID for end-to-end tracking
            self.logger.info(f"[{command.correlation_id}] Submitting command: type={command_type}, robot={robot_id}, command_id={command_id}")
            self.logger.debug(f"[{command.correlation_id}] Command parameters: {parameters}")
            
            # Validate robot exists and is available
            self.logger.debug(f"[{command.correlation_id}] Checking robot state for {robot_id}")
            robot_info = await self.state_manager.get_robot_state(robot_id)
            if not robot_info:
                self.logger.error(f"[{command.correlation_id}] Robot not found in state manager: {robot_id}")
                raise ValidationError(f"Robot not found: {robot_id}")
            
            self.logger.info(f"[{command.correlation_id}] Robot {robot_id} state: {robot_info.current_state}, operational: {robot_info.is_operational}")
            
            if not robot_info.is_operational:
                self.logger.error(f"[{command.correlation_id}] Robot {robot_id} not operational (state: {robot_info.current_state})")
                raise ValidationError(f"Robot not operational: {robot_id}")
            
            self.logger.debug(f"[{command.correlation_id}] Created command: {command_id}")
            
            # Validate command parameters
            await self._validate_command(command)
            self.logger.debug(f"[{command.correlation_id}] Command validation passed for {command_id}")
            
            # Add to queue
            queue_priority = priority.value * -1
            self.logger.info(f"[{command.correlation_id}] Adding command {command_id} to queue with priority {queue_priority}")
            await self._command_queue.put((queue_priority, time.time(), command))
            
            async with self._commands_lock:
                self._active_commands[command_id] = command
            
            self.logger.info(f"[{command.correlation_id}] Command submitted successfully: {command_id} for robot {robot_id}, queue size: {self._command_queue.qsize()}")
            return command_id
        
        return await self.execute_operation(context, _submit_command)
    
    async def _validate_command(self, command: RobotCommand):
        """Validate command parameters"""
        self.logger.debug(f"[{command.correlation_id}] Validating command {command.command_id}: type={command.command_type.value}, parameters={command.parameters}")
        
        if command.command_type not in self._validation_rules:
            self.logger.debug(f"[{command.correlation_id}] No validation rules defined for command type: {command.command_type.value}")
            return  # No validation rules defined
        
        rules = self._validation_rules[command.command_type]
        self.logger.debug(f"[{command.correlation_id}] Applying {len(rules)} validation rules for command type: {command.command_type.value}")
        
        validation_results = []
        
        for rule in rules:
            param_name = rule.parameter_name
            param_value = command.parameters.get(param_name)
            
            # Check required parameters
            if rule.required and param_value is None:
                error_msg = f"Required parameter missing: {param_name}"
                self.logger.error(f"[{command.correlation_id}] Command {command.command_id} validation failed: {error_msg}")
                raise ValidationError(error_msg)
            
            if param_value is not None:
                # Check data type
                if not isinstance(param_value, rule.data_type):
                    error_msg = f"Parameter {param_name} must be of type {rule.data_type.__name__}"
                    self.logger.error(f"[{command.correlation_id}] Command {command.command_id} validation failed: {error_msg} (got {type(param_value).__name__})")
                    raise ValidationError(error_msg)
                
                # Check numeric ranges
                if rule.min_value is not None and param_value < rule.min_value:
                    error_msg = f"Parameter {param_name} must be >= {rule.min_value}"
                    self.logger.error(f"[{command.correlation_id}] Command {command.command_id} validation failed: {error_msg} (got {param_value})")
                    raise ValidationError(error_msg)
                
                if rule.max_value is not None and param_value > rule.max_value:
                    error_msg = f"Parameter {param_name} must be <= {rule.max_value}"
                    self.logger.error(f"[{command.correlation_id}] Command {command.command_id} validation failed: {error_msg} (got {param_value})")
                    raise ValidationError(error_msg)
                
                # Check allowed values
                if rule.allowed_values and param_value not in rule.allowed_values:
                    error_msg = f"Parameter {param_name} must be one of: {rule.allowed_values}"
                    self.logger.error(f"[{command.correlation_id}] Command {command.command_id} validation failed: {error_msg} (got {param_value})")
                    raise ValidationError(error_msg)
                
                # Custom validation function
                if rule.validator_func:
                    try:
                        rule.validator_func(param_value)
                    except Exception as e:
                        error_msg = f"Parameter {param_name} validation failed: {e}"
                        self.logger.error(f"[{command.correlation_id}] Command {command.command_id} custom validation failed: {error_msg}")
                        raise ValidationError(error_msg)
                
                validation_results.append(f"{param_name}={param_value}")
            else:
                validation_results.append(f"{param_name}=<not_provided>")
        
        self.logger.info(f"[{command.correlation_id}] Command {command.command_id} validation passed: {', '.join(validation_results)}")
    
    async def _process_command_queue(self):
        """Background task to process command queue"""
        self.logger.info("Command queue processor started")
        while self._running:
            try:
                # Get next command from queue
                try:
                    self.logger.debug("Waiting for command from queue...")
                    priority, timestamp, command = await asyncio.wait_for(
                        self._command_queue.get(), timeout=1.0
                    )
                    self.logger.info(f"Dequeued command: {command.command_id} (type: {command.command_type.value}, robot: {command.robot_id})")
                except asyncio.TimeoutError:
                    # This is normal - just continue waiting
                    continue
                
                # Process command with concurrency control
                self.logger.debug(f"Acquiring semaphore for command {command.command_id}")
                async with self._processing_semaphore:
                    self.logger.info(f"Starting execution of command {command.command_id}")
                    await self._execute_command(command)
                
            except asyncio.CancelledError:
                self.logger.info("Command queue processor cancelled")
                break
            except Exception as e:
                self.logger.error(f"Error in command queue processing: {e}")
                self.logger.debug(f"Command queue error traceback: {traceback.format_exc()}")
    
    async def _execute_command(self, command: RobotCommand):
        """Execute a single command"""
        try:
            self.logger.info(f"*** EXECUTING COMMAND {command.command_id} ***")
            self.logger.info(f"Command details: robot={command.robot_id}, type={command.command_type.value}, params={command.parameters}")
            
            command.status = "running"
            command.started_at = time.time()
            
            # Get current state before changing
            current_state = await self.state_manager.get_robot_state(command.robot_id)
            self.logger.info(f"Setting robot {command.robot_id} state to BUSY (current state: {current_state.current_state.value if current_state else 'unknown'})")
            
            # Update robot state to busy
            await self.state_manager.update_robot_state(
                command.robot_id,
                RobotState.BUSY,
                reason=f"Executing command: {command.command_type.value}"
            )
            
            # Verify state change
            updated_state = await self.state_manager.get_robot_state(command.robot_id)
            self.logger.info(f"Robot {command.robot_id} state updated to BUSY (verified: {updated_state.current_state.value if updated_state else 'unknown'})")
            
            # Get robot type to determine processor
            robot_info = await self.state_manager.get_robot_state(command.robot_id)
            robot_type = robot_info.robot_type if robot_info else "unknown"
            
            self.logger.info(f"Robot type: {robot_type}, available processors: {list(self._command_processors.keys())}")
            
            # Execute command with appropriate processor
            if robot_type in self._command_processors:
                processor = self._command_processors[robot_type]
                self.logger.info(f"Using processor: {processor}")
                
                if command.timeout:
                    self.logger.debug(f"Executing command with timeout: {command.timeout}s")
                    result = await asyncio.wait_for(
                        processor(command),
                        timeout=command.timeout
                    )
                else:
                    self.logger.debug("Executing command without timeout")
                    result = await processor(command)
                
                command.result = result
                command.status = "completed"
                command.completed_at = time.time()
                
                self.logger.info(f"Command {command.command_id} completed successfully with result: {result}")
                
            else:
                error_msg = f"No processor found for robot type: {robot_type}"
                self.logger.error(error_msg)
                raise ValidationError(error_msg)
            
            # Update robot state back to idle
            current_state = await self.state_manager.get_robot_state(command.robot_id)
            self.logger.info(f"Setting robot {command.robot_id} state back to IDLE (current state: {current_state.current_state.value if current_state else 'unknown'})")
            await self.state_manager.update_robot_state(
                command.robot_id,
                RobotState.IDLE,
                reason="Command completed"
            )
            # Verify state change
            updated_state = await self.state_manager.get_robot_state(command.robot_id)
            self.logger.info(f"Robot {command.robot_id} state updated to IDLE (verified: {updated_state.current_state.value if updated_state else 'unknown'})")
            
        except asyncio.TimeoutError:
            command.status = "timeout"
            command.error = f"Command timed out after {command.timeout}s"
            command.completed_at = time.time()
            command.retry_count += 1
            
            self.logger.error(f"Command {command.command_id} timed out")
            
            # Reset robot state from busy on timeout
            try:
                current_state = await self.state_manager.get_robot_state(command.robot_id)
                self.logger.warning(f"Resetting robot {command.robot_id} state to IDLE after timeout (current state: {current_state.current_state.value if current_state else 'unknown'})")
                await self.state_manager.update_robot_state(
                    command.robot_id,
                    RobotState.IDLE,
                    reason="Command timed out, resetting to idle"
                )
                # Verify state change
                updated_state = await self.state_manager.get_robot_state(command.robot_id)
                self.logger.info(f"Robot {command.robot_id} state reset to IDLE after timeout (verified: {updated_state.current_state.value if updated_state else 'unknown'})")
            except Exception as state_error:
                self.logger.error(f"Failed to reset robot state after timeout: {state_error}")
            
            # Retry if possible
            if command.retry_count <= command.max_retries:
                await self._retry_command(command)
            else:
                await self._handle_command_failure(command)
            
        except Exception as e:
            command.status = "failed"
            command.error = str(e)
            command.completed_at = time.time()
            command.retry_count += 1
            
            self.logger.error(f"Command {command.command_id} failed: {e}")
            
            # Reset robot state from busy on failure
            try:
                current_state = await self.state_manager.get_robot_state(command.robot_id)
                self.logger.warning(f"Resetting robot {command.robot_id} state to IDLE after failure (current state: {current_state.current_state.value if current_state else 'unknown'})")
                await self.state_manager.update_robot_state(
                    command.robot_id,
                    RobotState.IDLE,
                    reason="Command failed, resetting to idle"
                )
                # Verify state change
                updated_state = await self.state_manager.get_robot_state(command.robot_id)
                self.logger.info(f"Robot {command.robot_id} state reset to IDLE after failure (verified: {updated_state.current_state.value if updated_state else 'unknown'})")
            except Exception as state_error:
                self.logger.error(f"Failed to reset robot state after failure: {state_error}")
            
            # Retry if possible
            if command.retry_count <= command.max_retries:
                await self._retry_command(command)
            else:
                await self._handle_command_failure(command)
        
        finally:
            # Move to history and cleanup
            await self._finalize_command(command)
    
    async def _retry_command(self, command: RobotCommand):
        """Retry a failed command"""
        self.logger.info(f"Retrying command {command.command_id} (attempt {command.retry_count + 1})")
        
        # Reset command state
        command.status = "pending"
        command.started_at = None
        command.result = None
        
        # Re-queue with higher priority
        retry_priority = min(command.priority.value + 1, CommandPriority.EMERGENCY.value)
        await self._command_queue.put((retry_priority * -1, time.time(), command))
    
    async def _handle_command_failure(self, command: RobotCommand):
        """Handle permanent command failure"""
        self.logger.error(f"Command {command.command_id} failed permanently after {command.retry_count} attempts")
        
        # For permanent failures, reset to idle state rather than error
        # This allows the robot to be available for future commands
        try:
            await self.state_manager.update_robot_state(
                command.robot_id,
                RobotState.IDLE,
                reason=f"Command failed permanently, resetting to idle: {command.error}"
            )
        except Exception as state_error:
            self.logger.error(f"Failed to reset robot state after permanent failure: {state_error}")
            # As a fallback, try to set to error state
            try:
                await self.state_manager.update_robot_state(
                    command.robot_id,
                    RobotState.ERROR,
                    reason=f"Command failed and state reset failed: {command.error}"
                )
            except Exception as final_error:
                self.logger.error(f"Failed to set robot to error state: {final_error}")
    
    async def _finalize_command(self, command: RobotCommand):
        """Finalize command execution"""
        async with self._commands_lock:
            # Remove from active commands
            self._active_commands.pop(command.command_id, None)
            
            # Add to history
            self._command_history.append(command)
            
            # Keep history size manageable
            max_history = 1000
            if len(self._command_history) > max_history:
                self._command_history = self._command_history[-max_history:]
    
    async def _process_meca_command(self, command: RobotCommand) -> Any:
        """Process Mecademic robot command"""
        self.logger.info(f"Processing Meca command: {command.command_id} for robot {command.robot_id}")
        
        if not self.orchestrator:
            self.logger.error("Orchestrator not available for Meca command processing")
            raise ValidationError("Orchestrator not available")
        
        self.logger.debug(f"Looking for Meca service with robot_id: {command.robot_id}")
        meca_service = await self.orchestrator.get_robot_service(command.robot_id)
        
        if not meca_service:
            # Log available robot services for debugging
            available_services = self.orchestrator.list_robot_services()
            self.logger.error(f"Meca service not found for robot: {command.robot_id}. Available services: {available_services}")
            raise ValidationError(f"Meca service not found for robot: {command.robot_id}")
        
        self.logger.info(f"Found Meca service: {meca_service} for robot {command.robot_id}")
        
        # Map command types to service methods
        command_mapping = {
            CommandType.MOVE: "move_to_position",
            CommandType.PICK: "pick_wafer",
            CommandType.PLACE: "place_wafer",
            CommandType.HOME: "home_robot",
            CommandType.STOP: "stop_robot",
            CommandType.CALIBRATE: "calibrate_robot",
            CommandType.STATUS: "get_status",
            CommandType.CONNECT: "connect",
            CommandType.DISCONNECT: "disconnect",
            CommandType.EMERGENCY_STOP: "emergency_stop",
            CommandType.RESET: "reset_robot",
            
            # High-level sequence operations
            CommandType.PICKUP_SEQUENCE: "execute_pickup_sequence",
            CommandType.DROP_SEQUENCE: "execute_drop_sequence",
            CommandType.CAROUSEL_SEQUENCE: "execute_carousel_sequence",
            CommandType.CAROUSEL_MOVE: "carousel_wafer_operation"
        }
        
        method_name = command_mapping.get(command.command_type)
        if not method_name:
            raise ValidationError(f"Command type {command.command_type} not supported for Meca robot")
        
        if hasattr(meca_service, method_name):
            method = getattr(meca_service, method_name)
            
            # Transform parameters for specific command types
            if command.command_type == CommandType.PICKUP_SEQUENCE:
                # Transform WebSocket parameters to method parameters
                transformed_params = await self._transform_pickup_sequence_params(command.parameters)
                return await method(**transformed_params)
            elif command.command_type == CommandType.DROP_SEQUENCE:
                # Transform WebSocket parameters to method parameters  
                transformed_params = await self._transform_drop_sequence_params(command.parameters)
                return await method(**transformed_params)
            elif command.command_type == CommandType.CAROUSEL_SEQUENCE:
                # Transform WebSocket parameters to method parameters
                transformed_params = await self._transform_carousel_sequence_params(command.parameters)
                return await method(**transformed_params)
            elif command.command_type == CommandType.CAROUSEL_MOVE:
                # Transform WebSocket parameters to method parameters
                transformed_params = await self._transform_carousel_move_params(command.parameters)
                return await method(**transformed_params)
            else:
                # For other commands, use parameters directly
                return await method(**command.parameters)
        else:
            raise ValidationError(f"Method {method_name} not found in Meca service")
    
    async def _process_ot2_command(self, command: RobotCommand) -> Any:
        """Process OT2 robot command"""
        if not self.orchestrator:
            raise ValidationError("Orchestrator not available")
        
        ot2_service = await self.orchestrator.get_robot_service(command.robot_id)
        if not ot2_service:
            raise ValidationError(f"OT2 service not found for robot: {command.robot_id}")
        
        # Map command types to service methods
        command_mapping = {
            CommandType.MOVE: "move_to_position",
            CommandType.HOME: "home_robot",
            CommandType.STOP: "stop_robot",
            CommandType.CALIBRATE: "calibrate_robot",
            CommandType.STATUS: "get_status",
            CommandType.CONNECT: "connect",
            CommandType.DISCONNECT: "disconnect",
            CommandType.EMERGENCY_STOP: "emergency_stop",
            CommandType.RESET: "reset_robot",
            CommandType.PROTOCOL_EXECUTION: "execute_protocol"
        }
        
        method_name = command_mapping.get(command.command_type)
        if not method_name:
            raise ValidationError(f"Command type {command.command_type} not supported for OT2 robot")
        
        if hasattr(ot2_service, method_name):
            method = getattr(ot2_service, method_name)
            
            # Transform parameters for specific command types
            if command.command_type == CommandType.PROTOCOL_EXECUTION:
                # DISABLED: This interferes with the proper orchestrated protocol execution
                # The proper protocol execution should go through ProtocolExecutionService
                # via the /api/ot2/run-protocol endpoint, not through command service
                self.logger.warning(f"PROTOCOL_EXECUTION command ignored to prevent interference with orchestrated execution")
                return {"status": "ignored", "reason": "Use orchestrated protocol execution instead"}
                
                # OLD CODE (commented out to prevent interference):
                # transformed_params = await self._transform_protocol_execution_params(command.parameters)
                # return await method(transformed_params)
            else:
                # For other commands, use parameters directly
                return await method(**command.parameters)
        else:
            raise ValidationError(f"Method {method_name} not found in OT2 service")
    
    async def _process_arduino_command(self, command: RobotCommand) -> Any:
        """Process Arduino system command"""
        # Arduino commands would be processed here
        # For now, just return success
        return {"status": "success", "command": command.command_type.value}
    
    async def _process_carousel_command(self, command: RobotCommand) -> Any:
        """Process Carousel system command"""
        # Carousel commands would be processed here
        # For now, just return success
        return {"status": "success", "command": command.command_type.value}
    
    async def get_command_status(self, command_id: str) -> ServiceResult[Dict[str, Any]]:
        """Get status of a specific command"""
        async with self._commands_lock:
            # Check active commands first
            if command_id in self._active_commands:
                command = self._active_commands[command_id]
            else:
                # Check history
                command = None
                for cmd in self._command_history:
                    if cmd.command_id == command_id:
                        command = cmd
                        break
                
                if not command:
                    return ServiceResult.error_result(f"Command not found: {command_id}")
            
            status_info = {
                "command_id": command.command_id,
                "robot_id": command.robot_id,
                "command_type": command.command_type.value,
                "status": command.status,
                "priority": command.priority.value,
                "parameters": command.parameters,
                "created_at": command.created_at,
                "started_at": command.started_at,
                "completed_at": command.completed_at,
                "retry_count": command.retry_count,
                "result": command.result,
                "error": command.error,
                "execution_time": (
                    command.completed_at - command.started_at 
                    if command.started_at and command.completed_at 
                    else None
                )
            }
            
            return ServiceResult.success_result(status_info)
    
    async def cancel_command(self, command_id: str) -> ServiceResult[bool]:
        """Cancel a pending or running command"""
        async with self._commands_lock:
            if command_id not in self._active_commands:
                return ServiceResult.error_result(f"Command not found: {command_id}")
            
            command = self._active_commands[command_id]
            
            if command.status in ["completed", "failed", "cancelled"]:
                return ServiceResult.error_result(f"Command {command_id} cannot be cancelled (status: {command.status})")
            
            command.status = "cancelled"
            command.error = "Cancelled by user"
            command.completed_at = time.time()
            
            self.logger.info(f"Command cancelled: {command_id}")
            return ServiceResult.success_result(True)
    
    async def list_active_commands(self, robot_id: Optional[str] = None) -> ServiceResult[List[Dict[str, Any]]]:
        """List active commands, optionally filtered by robot"""
        async with self._commands_lock:
            commands_info = []
            
            for command in self._active_commands.values():
                if robot_id and command.robot_id != robot_id:
                    continue
                
                commands_info.append({
                    "command_id": command.command_id,
                    "robot_id": command.robot_id,
                    "command_type": command.command_type.value,
                    "status": command.status,
                    "priority": command.priority.value,
                    "created_at": command.created_at,
                    "started_at": command.started_at
                })
            
            # Sort by priority and creation time
            commands_info.sort(key=lambda x: (x["priority"], x["created_at"]), reverse=True)
            
            return ServiceResult.success_result(commands_info)
    
    async def get_command_history(
        self, 
        robot_id: Optional[str] = None,
        limit: int = 100
    ) -> ServiceResult[List[Dict[str, Any]]]:
        """Get command execution history"""
        async with self._commands_lock:
            history = []
            
            # Get recent commands from history
            recent_commands = self._command_history[-limit:]
            
            for command in recent_commands:
                if robot_id and command.robot_id != robot_id:
                    continue
                
                history.append({
                    "command_id": command.command_id,
                    "robot_id": command.robot_id,
                    "command_type": command.command_type.value,
                    "status": command.status,
                    "created_at": command.created_at,
                    "completed_at": command.completed_at,
                    "execution_time": (
                        command.completed_at - command.started_at 
                        if command.started_at and command.completed_at 
                        else None
                    ),
                    "retry_count": command.retry_count,
                    "error": command.error
                })
            
            # Sort by completion time (most recent first)
            history.sort(key=lambda x: x["completed_at"] or 0, reverse=True)
            
            return ServiceResult.success_result(history)
    
    async def health_check(self) -> Dict[str, Any]:
        """Command service health check"""
        base_health = await super().health_check()
        
        async with self._commands_lock:
            active_count = len(self._active_commands)
            queue_size = self._command_queue.qsize()
            
            # Count commands by status
            status_counts = {}
            for command in self._active_commands.values():
                status_counts[command.status] = status_counts.get(command.status, 0) + 1
        
        return {
            **base_health,
            "active_commands": active_count,
            "queue_size": queue_size,
            "command_status_counts": status_counts,
            "max_concurrent_commands": self._max_concurrent_commands,
            "history_size": len(self._command_history)
        }
    
    async def _transform_pickup_sequence_params(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Transform WebSocket pickup sequence parameters to MecaService method parameters"""
        # Pass through start, count, and retry_wafers parameters to execute_pickup_sequence
        result = {
            "start": params.get("start", 0),
            "count": params.get("count", 5)
        }
        # Only include retry_wafers if it's provided (for error recovery)
        if params.get("retry_wafers"):
            result["retry_wafers"] = params["retry_wafers"]
        return result

    async def _transform_drop_sequence_params(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Transform WebSocket drop sequence parameters to MecaService method parameters"""
        # Pass through start, count, and retry_wafers parameters to execute_drop_sequence
        result = {
            "start": params.get("start", 0),
            "count": params.get("count", 5)
        }
        # Only include retry_wafers if it's provided (for error recovery)
        if params.get("retry_wafers"):
            result["retry_wafers"] = params["retry_wafers"]
        return result
    
    async def _transform_carousel_sequence_params(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Transform WebSocket carousel sequence parameters to MecaService method parameters"""
        # Get parameters from the API request
        start_position = params.get("start", 0)
        count = params.get("count", 11)
        
        # carousel_wafer_operation expects: operation, wafer_id, carousel_position
        # For now, we'll default to "drop" operation and use first position
        # This should be enhanced to support sequences properly
        return {
            "operation": "drop",  # Default operation
            "wafer_id": f"wafer_carousel_{start_position}_{count}",
            "carousel_position": start_position  # Use start position as carousel position
        }
    
    async def _transform_carousel_move_params(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Transform WebSocket carousel move parameters to MecaService method parameters"""
        # Get parameters from the API request
        position = params.get("position", 0)
        operation = params.get("operation", "drop")
        wafer_id = params.get("wafer_id", f"wafer_carousel_{position}")
        
        # carousel_wafer_operation expects: operation, wafer_id, carousel_position
        return {
            "operation": operation,
            "wafer_id": wafer_id,
            "carousel_position": position
        }
    
    async def _transform_protocol_execution_params(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Transform WebSocket protocol execution parameters to OT2Service method parameters"""
        from services.ot2_service import ProtocolConfig
        from pathlib import Path
        
        # Get protocol file with user override capability
        protocol_file = params.get("protocol_file")
        if not protocol_file:
            # Default to the standard OT2 protocol file
            default_proto_conf = self.settings.get_robot_config("ot2").get("protocol_config", {})
            directory = default_proto_conf.get("directory", "protocols/")
            default_file = default_proto_conf.get("default_file", "ot2Protocole.py")
            protocol_file = str(Path(directory) / default_file)
        
        # Create protocol configuration from WebSocket parameters
        protocol_config = ProtocolConfig(
            protocol_name=params.get("protocol_name", "liquid_handling"),
            protocol_file=protocol_file,
            parameters={
                "volume": params.get("volume", 50.0),
                "source_well": params.get("source_well", "A1"),
                "dest_well": params.get("dest_well", "B1"),
                "source_labware": params.get("source_labware", "plate_96"),
                "dest_labware": params.get("dest_labware", "plate_96"),
                "pipette_name": params.get("pipette_name", "right")
            },
            labware_setup={
                "source": params.get("source_labware", "plate_96"),
                "dest": params.get("dest_labware", "plate_96")
            },
            calibration_required=False  # Skip calibration for now
        )
        
        return protocol_config