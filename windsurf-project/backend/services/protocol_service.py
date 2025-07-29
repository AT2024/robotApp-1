"""
Protocol Execution Service - Complex multi-robot workflow orchestration.
Handles protocol lifecycle, parameter management, and multi-robot coordination.
"""

import asyncio
import json
import time
import uuid
from typing import Dict, Any, Optional, List, Union, TYPE_CHECKING
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from core.exceptions import ValidationError, ProtocolExecutionError, ConfigurationError
from core.state_manager import AtomicStateManager, RobotState, SystemState
from core.resource_lock import ResourceLockManager
from core.settings import RoboticsSettings
from .base import BaseService, ServiceResult, OperationContext
from utils.logger import get_logger

if TYPE_CHECKING:
    from .orchestrator import RobotOrchestrator


class ProtocolStatus(Enum):
    """Protocol execution status"""

    PENDING = "pending"
    INITIALIZING = "initializing"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class ProtocolStep:
    """Individual protocol step definition"""

    step_id: str
    robot_id: str
    operation_type: str
    parameters: Dict[str, Any]
    dependencies: List[str] = field(default_factory=list)
    timeout: Optional[float] = None
    retry_count: int = 0
    max_retries: int = 3
    status: str = "pending"
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    error: Optional[str] = None


@dataclass
class ProtocolDefinition:
    """Complete protocol definition"""

    protocol_id: str
    name: str
    description: str
    version: str
    steps: List[ProtocolStep]
    global_parameters: Dict[str, Any] = field(default_factory=dict)
    required_robots: List[str] = field(default_factory=list)
    estimated_duration: Optional[float] = None
    safety_requirements: List[str] = field(default_factory=list)


@dataclass
class ProtocolExecution:
    """Active protocol execution state"""

    execution_id: str
    protocol: ProtocolDefinition
    status: ProtocolStatus
    current_step: Optional[str] = None
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    total_steps: int = 0
    completed_steps: int = 0
    failed_steps: int = 0
    results: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None

    @property
    def progress_percentage(self) -> float:
        """Calculate execution progress as percentage"""
        if self.total_steps == 0:
            return 0.0
        return (self.completed_steps / self.total_steps) * 100.0


class ProtocolExecutionService(BaseService):
    """
    Service for executing complex multi-robot protocols.

    Responsibilities:
    - Load and validate protocol definitions
    - Coordinate multi-robot operations
    - Handle protocol lifecycle (start, pause, resume, stop)
    - Manage step dependencies and execution order
    - Provide real-time progress tracking
    - Handle error recovery and retries
    """

    def __init__(
        self,
        settings: RoboticsSettings,
        state_manager: AtomicStateManager,
        lock_manager: ResourceLockManager,
        orchestrator: Optional["RobotOrchestrator"] = None,
    ):
        super().__init__(
            settings, state_manager, lock_manager, "ProtocolExecutionService"
        )
        self.orchestrator = orchestrator
        
        self.logger = get_logger("protocol_service")

        # Protocol management
        self._active_protocols: Dict[str, ProtocolExecution] = {}
        self._protocol_templates: Dict[str, ProtocolDefinition] = {}
        self._protocols_lock = asyncio.Lock()

        # Protocol directories
        self.protocols_dir = Path("protocols")  # Default protocols directory
        self.templates_dir = self.protocols_dir / "templates"
        self.active_dir = self.protocols_dir / "active"

        # Ensure directories exist
        self.protocols_dir.mkdir(exist_ok=True)
        self.templates_dir.mkdir(exist_ok=True)
        self.active_dir.mkdir(exist_ok=True)

    async def _on_start(self):
        """Initialize protocol service"""
        # Load protocol templates
        await self._load_protocol_templates()

        # Resume any active protocols from previous session
        await self._resume_active_protocols()

    async def _on_stop(self):
        """Cleanup protocol service"""
        # Save state of active protocols
        await self._save_active_protocols()

        # Cancel running protocols gracefully
        async with self._protocols_lock:
            for execution in self._active_protocols.values():
                if execution.status == ProtocolStatus.RUNNING:
                    await self._cancel_protocol_execution(
                        execution.execution_id, "Service shutdown"
                    )

    async def _load_protocol_templates(self):
        """Load protocol templates from disk"""
        try:
            for template_file in self.templates_dir.glob("*.json"):
                with open(template_file, "r") as f:
                    template_data = json.load(f)

                protocol = self._parse_protocol_definition(template_data)
                self._protocol_templates[protocol.protocol_id] = protocol

                self.logger.info(f"Loaded protocol template: {protocol.name}")

        except Exception as e:
            self.logger.error(f"Error loading protocol templates: {e}")

    async def _resume_active_protocols(self):
        """Resume protocols that were active before shutdown"""
        try:
            for active_file in self.active_dir.glob("*.json"):
                with open(active_file, "r") as f:
                    execution_data = json.load(f)

                execution = self._parse_protocol_execution(execution_data)

                # Only resume protocols that were running or paused
                if execution.status in {ProtocolStatus.RUNNING, ProtocolStatus.PAUSED}:
                    execution.status = ProtocolStatus.PAUSED
                    self._active_protocols[execution.execution_id] = execution
                    self.logger.info(
                        f"Resumed protocol execution: {execution.execution_id}"
                    )

        except Exception as e:
            self.logger.error(f"Error resuming active protocols: {e}")

    async def _save_active_protocols(self):
        """Save active protocol states to disk"""
        async with self._protocols_lock:
            for execution in self._active_protocols.values():
                if execution.status in {ProtocolStatus.RUNNING, ProtocolStatus.PAUSED}:
                    try:
                        active_file = self.active_dir / f"{execution.execution_id}.json"
                        with open(active_file, "w") as f:
                            json.dump(
                                self._serialize_protocol_execution(execution),
                                f,
                                indent=2,
                            )
                    except Exception as e:
                        self.logger.error(
                            f"Error saving protocol {execution.execution_id}: {e}"
                        )

    async def create_ot2_protocol_execution(
        self,
        protocol_name: str = "OT2_Liquid_Handling",
        parameters: Dict[str, Any] = None,
    ) -> ServiceResult[str]:
        """
        Create an OT2 protocol execution based on existing ot2Protocole.py.

        Args:
            protocol_name: Name for the protocol execution
            parameters: Protocol parameters (defaults to parameters.json if not provided)
        """
        context = OperationContext(
            operation_id=f"create_ot2_protocol_{int(time.time() * 1000)}",
            robot_id="ot2",
            operation_type="create_protocol",
        )

        async def _create_ot2_protocol():
            # Load default parameters if none provided
            if parameters is None:
                params_file = (
                    self.protocols_dir.parent / "protocols" / "parameters.json"
                )
                try:
                    with open(params_file, "r") as f:
                        protocol_params = json.load(f)
                except Exception as e:
                    self.logger.warning(
                        f"Could not load parameters.json: {e}, using defaults"
                    )
                    protocol_params = {
                        "NUM_OF_GENERATORS": 5,
                        "radioactive_VOL": 6.6,
                        "SDS_VOL": 1.0,
                        "tip_location": "1",
                    }
            else:
                protocol_params = parameters.copy()

            # Create protocol steps based on OT2 protocol structure
            steps = []

            # Step 1: Initialize OT2 and load labware
            # Resolve protocol file to full path
            protocol_file_path = (
                self.protocols_dir.parent / "protocols" / "ot2Protocole.py"
            )
            steps.append(
                ProtocolStep(
                    step_id="init_ot2",
                    robot_id="ot2",
                    operation_type="initialize_protocol",
                    parameters={
                        "protocol_file": str(protocol_file_path),
                        "protocol_parameters": protocol_params,
                    },
                    timeout=60.0,
                )
            )

            # Step 2: Execute protocol
            steps.append(
                ProtocolStep(
                    step_id="execute_ot2_protocol",
                    robot_id="ot2",
                    operation_type="run_protocol",
                    parameters=protocol_params,
                    dependencies=["init_ot2"],
                    timeout=1800.0,  # 30 minutes max
                )
            )

            # Create protocol definition
            protocol_def = ProtocolDefinition(
                protocol_id=f"ot2_{uuid.uuid4().hex[:8]}",
                name=protocol_name,
                description="OT2 liquid handling protocol for radioactive sample processing",
                version="1.0",
                steps=steps,
                global_parameters=protocol_params,
                required_robots=["ot2"],
                estimated_duration=1800.0,
                safety_requirements=[
                    "Radioactive material handling protocols must be followed",
                    "Proper PPE required",
                    "Emergency stop procedures must be understood",
                ],
            )

            # Create execution
            execution_id = await self._create_protocol_execution(protocol_def)
            return execution_id

        return await self.execute_operation(context, _create_ot2_protocol)

    async def create_multi_robot_workflow(
        self,
        workflow_name: str,
        robot_operations: List[Dict[str, Any]],
        coordination_strategy: str = "sequential",
    ) -> ServiceResult[str]:
        """
        Create a multi-robot workflow protocol.

        Args:
            workflow_name: Name for the workflow
            robot_operations: List of robot operations
            coordination_strategy: How to coordinate operations
        """
        context = OperationContext(
            operation_id=f"create_workflow_{int(time.time() * 1000)}",
            robot_id="multi_robot",
            operation_type="create_workflow",
        )

        async def _create_workflow():
            steps = []
            required_robots = set()

            for i, operation in enumerate(robot_operations):
                robot_id = operation["robot_id"]
                operation_type = operation["operation_type"]
                parameters = operation.get("parameters", {})

                required_robots.add(robot_id)

                # Create dependencies based on coordination strategy
                dependencies = []
                if coordination_strategy == "sequential" and i > 0:
                    # Each step depends on the previous one
                    dependencies = [f"step_{i-1}"]
                elif coordination_strategy == "dependency_based":
                    # Use explicit dependencies if provided
                    dependencies = operation.get("dependencies", [])

                step = ProtocolStep(
                    step_id=f"step_{i}",
                    robot_id=robot_id,
                    operation_type=operation_type,
                    parameters=parameters,
                    dependencies=dependencies,
                    timeout=operation.get("timeout", 300.0),
                )
                steps.append(step)

            # Create protocol definition
            protocol_def = ProtocolDefinition(
                protocol_id=f"workflow_{uuid.uuid4().hex[:8]}",
                name=workflow_name,
                description=f"Multi-robot workflow with {coordination_strategy} coordination",
                version="1.0",
                steps=steps,
                global_parameters={"coordination_strategy": coordination_strategy},
                required_robots=list(required_robots),
                estimated_duration=sum(step.timeout or 300.0 for step in steps),
            )

            # Create execution
            execution_id = await self._create_protocol_execution(protocol_def)
            return execution_id

        return await self.execute_operation(context, _create_workflow)

    async def _create_protocol_execution(self, protocol: ProtocolDefinition) -> str:
        """Create a new protocol execution"""
        execution_id = f"exec_{uuid.uuid4().hex[:8]}"

        execution = ProtocolExecution(
            execution_id=execution_id,
            protocol=protocol,
            status=ProtocolStatus.PENDING,
            total_steps=len(protocol.steps),
        )

        async with self._protocols_lock:
            self._active_protocols[execution_id] = execution

        self.logger.info(
            f"Created protocol execution: {execution_id} for protocol: {protocol.name}"
        )
        return execution_id

    async def start_protocol_execution(self, execution_id: str) -> ServiceResult[bool]:
        """Start executing a protocol"""
        context = OperationContext(
            operation_id=f"start_protocol_{execution_id}",
            robot_id="protocol_service",
            operation_type="start_protocol",
        )

        async def _start_execution():
            async with self._protocols_lock:
                if execution_id not in self._active_protocols:
                    raise ValidationError(
                        f"Protocol execution not found: {execution_id}"
                    )

                execution = self._active_protocols[execution_id]

                if execution.status != ProtocolStatus.PENDING:
                    raise ValidationError(
                        f"Protocol {execution_id} is not in pending state"
                    )

                # Validate required robots are available
                await self._validate_robot_availability(
                    execution.protocol.required_robots
                )

                # Update status and start execution
                execution.status = ProtocolStatus.INITIALIZING
                execution.start_time = time.time()

                # Start execution task
                asyncio.create_task(self._execute_protocol(execution))

                return True

        return await self.execute_operation(context, _start_execution)

    async def _validate_robot_availability(self, required_robots: List[str]):
        """Validate that all required robots are available"""
        if not self.orchestrator:
            raise ConfigurationError("Orchestrator not available for robot validation")

        available_robots = await self.orchestrator.get_available_robots()

        for robot_id in required_robots:
            if robot_id not in available_robots:
                robot_info = await self.state_manager.get_robot_state(robot_id)
                if not robot_info or not robot_info.is_operational:
                    raise ValidationError(f"Required robot not available: {robot_id}")

    async def _execute_protocol(self, execution: ProtocolExecution):
        """Execute protocol steps"""
        try:
            execution.status = ProtocolStatus.RUNNING
            self.logger.info(f"Starting protocol execution: {execution.execution_id}")

            # Build dependency graph
            dependency_graph = self._build_dependency_graph(execution.protocol.steps)

            # Execute steps based on dependencies
            completed_steps = set()

            while len(completed_steps) < len(execution.protocol.steps):
                # Find steps ready to execute
                ready_steps = []
                for step in execution.protocol.steps:
                    if (
                        step.step_id not in completed_steps
                        and step.status == "pending"
                        and all(dep in completed_steps for dep in step.dependencies)
                    ):
                        ready_steps.append(step)

                if not ready_steps:
                    # Check if there are failed steps blocking progress
                    failed_steps = [
                        s for s in execution.protocol.steps if s.status == "failed"
                    ]
                    if failed_steps:
                        raise ProtocolExecutionError(
                            f"Protocol blocked by failed steps: {[s.step_id for s in failed_steps]}"
                        )
                    else:
                        # This shouldn't happen with a valid dependency graph
                        raise ProtocolExecutionError(
                            "Protocol execution deadlock - no steps ready to execute"
                        )

                # Execute ready steps
                if (
                    execution.protocol.global_parameters.get("coordination_strategy")
                    == "parallel"
                ):
                    # Execute all ready steps in parallel
                    tasks = [
                        self._execute_step(execution, step) for step in ready_steps
                    ]
                    await asyncio.gather(*tasks, return_exceptions=True)
                else:
                    # Execute steps sequentially
                    for step in ready_steps:
                        await self._execute_step(execution, step)

                # Update completed steps
                for step in ready_steps:
                    if step.status == "completed":
                        completed_steps.add(step.step_id)
                        execution.completed_steps += 1
                    elif step.status == "failed":
                        execution.failed_steps += 1
                        if step.retry_count >= step.max_retries:
                            # Step failed permanently
                            break

            # Check final status
            if execution.failed_steps == 0:
                execution.status = ProtocolStatus.COMPLETED
                execution.end_time = time.time()
                self.logger.info(
                    f"Protocol execution completed successfully: {execution.execution_id}"
                )
            else:
                execution.status = ProtocolStatus.FAILED
                execution.end_time = time.time()
                execution.error = (
                    f"Protocol failed with {execution.failed_steps} failed steps"
                )
                self.logger.error(
                    f"Protocol execution failed: {execution.execution_id}"
                )

        except Exception as e:
            execution.status = ProtocolStatus.FAILED
            execution.end_time = time.time()
            execution.error = str(e)
            self.logger.error(
                f"Protocol execution error: {execution.execution_id}: {e}"
            )

    async def _execute_step(self, execution: ProtocolExecution, step: ProtocolStep):
        """Execute a single protocol step"""
        try:
            step.status = "running"
            step.start_time = time.time()
            execution.current_step = step.step_id

            self.logger.info(f"Executing step {step.step_id} on robot {step.robot_id}")

            # Get robot service from orchestrator
            if not self.orchestrator:
                raise ConfigurationError("Orchestrator not available")

            robot_service = await self.orchestrator.get_robot_service(step.robot_id)
            if not robot_service:
                raise ValidationError(f"Robot service not found: {step.robot_id}")

            # Execute the operation
            if hasattr(robot_service, step.operation_type):
                method = getattr(robot_service, step.operation_type)

                # Set timeout if specified
                if step.timeout:
                    result = await asyncio.wait_for(
                        method(**step.parameters), timeout=step.timeout
                    )
                else:
                    result = await method(**step.parameters)

                # Store result
                execution.results[step.step_id] = result
                step.status = "completed"
                step.end_time = time.time()

                self.logger.info(f"Step {step.step_id} completed successfully")

            else:
                raise ValidationError(
                    f"Operation {step.operation_type} not supported by robot {step.robot_id}"
                )

        except asyncio.TimeoutError:
            step.status = "failed"
            step.end_time = time.time()
            step.error = f"Step timed out after {step.timeout}s"
            step.retry_count += 1

            self.logger.error(f"Step {step.step_id} timed out")

            # Retry if possible
            if step.retry_count <= step.max_retries:
                step.status = "pending"
                self.logger.info(
                    f"Retrying step {step.step_id} (attempt {step.retry_count + 1})"
                )

        except Exception as e:
            step.status = "failed"
            step.end_time = time.time()
            step.error = str(e)
            step.retry_count += 1

            self.logger.error(f"Step {step.step_id} failed: {e}")

            # Retry if possible
            if step.retry_count <= step.max_retries:
                step.status = "pending"
                self.logger.info(
                    f"Retrying step {step.step_id} (attempt {step.retry_count + 1})"
                )

    def _build_dependency_graph(
        self, steps: List[ProtocolStep]
    ) -> Dict[str, List[str]]:
        """Build dependency graph for protocol steps"""
        graph = {}
        for step in steps:
            graph[step.step_id] = step.dependencies.copy()
        return graph

    async def get_protocol_execution_status(
        self, execution_id: str
    ) -> ServiceResult[Dict[str, Any]]:
        """Get current status of a protocol execution"""
        async with self._protocols_lock:
            if execution_id not in self._active_protocols:
                return ServiceResult.error_result(
                    f"Protocol execution not found: {execution_id}"
                )

            execution = self._active_protocols[execution_id]

            status_info = {
                "execution_id": execution.execution_id,
                "protocol_name": execution.protocol.name,
                "status": execution.status.value,
                "progress_percentage": execution.progress_percentage,
                "current_step": execution.current_step,
                "total_steps": execution.total_steps,
                "completed_steps": execution.completed_steps,
                "failed_steps": execution.failed_steps,
                "start_time": execution.start_time,
                "end_time": execution.end_time,
                "error": execution.error,
                "step_details": [
                    {
                        "step_id": step.step_id,
                        "robot_id": step.robot_id,
                        "operation_type": step.operation_type,
                        "status": step.status,
                        "retry_count": step.retry_count,
                        "error": step.error,
                    }
                    for step in execution.protocol.steps
                ],
            }

            return ServiceResult.success_result(status_info)

    async def pause_protocol_execution(self, execution_id: str) -> ServiceResult[bool]:
        """Pause a running protocol execution"""
        async with self._protocols_lock:
            if execution_id not in self._active_protocols:
                return ServiceResult.error_result(
                    f"Protocol execution not found: {execution_id}"
                )

            execution = self._active_protocols[execution_id]

            if execution.status != ProtocolStatus.RUNNING:
                return ServiceResult.error_result(
                    f"Protocol {execution_id} is not running"
                )

            execution.status = ProtocolStatus.PAUSED
            self.logger.info(f"Protocol execution paused: {execution_id}")

            return ServiceResult.success_result(True)

    async def resume_protocol_execution(self, execution_id: str) -> ServiceResult[bool]:
        """Resume a paused protocol execution"""
        async with self._protocols_lock:
            if execution_id not in self._active_protocols:
                return ServiceResult.error_result(
                    f"Protocol execution not found: {execution_id}"
                )

            execution = self._active_protocols[execution_id]

            if execution.status != ProtocolStatus.PAUSED:
                return ServiceResult.error_result(
                    f"Protocol {execution_id} is not paused"
                )

            # Restart execution task
            execution.status = ProtocolStatus.RUNNING
            asyncio.create_task(self._execute_protocol(execution))

            self.logger.info(f"Protocol execution resumed: {execution_id}")
            return ServiceResult.success_result(True)

    async def cancel_protocol_execution(
        self, execution_id: str, reason: str = "User cancelled"
    ) -> ServiceResult[bool]:
        """Cancel a protocol execution"""
        return await self._cancel_protocol_execution(execution_id, reason)

    async def _cancel_protocol_execution(
        self, execution_id: str, reason: str
    ) -> ServiceResult[bool]:
        """Internal method to cancel protocol execution"""
        async with self._protocols_lock:
            if execution_id not in self._active_protocols:
                return ServiceResult.error_result(
                    f"Protocol execution not found: {execution_id}"
                )

            execution = self._active_protocols[execution_id]
            execution.status = ProtocolStatus.CANCELLED
            execution.end_time = time.time()
            execution.error = reason

            self.logger.info(f"Protocol execution cancelled: {execution_id} - {reason}")
            return ServiceResult.success_result(True)

    def _parse_protocol_definition(self, data: Dict[str, Any]) -> ProtocolDefinition:
        """Parse protocol definition from dictionary"""
        steps = []
        for step_data in data.get("steps", []):
            step = ProtocolStep(
                step_id=step_data["step_id"],
                robot_id=step_data["robot_id"],
                operation_type=step_data["operation_type"],
                parameters=step_data.get("parameters", {}),
                dependencies=step_data.get("dependencies", []),
                timeout=step_data.get("timeout"),
                max_retries=step_data.get("max_retries", 3),
            )
            steps.append(step)

        return ProtocolDefinition(
            protocol_id=data["protocol_id"],
            name=data["name"],
            description=data.get("description", ""),
            version=data.get("version", "1.0"),
            steps=steps,
            global_parameters=data.get("global_parameters", {}),
            required_robots=data.get("required_robots", []),
            estimated_duration=data.get("estimated_duration"),
            safety_requirements=data.get("safety_requirements", []),
        )

    def _parse_protocol_execution(self, data: Dict[str, Any]) -> ProtocolExecution:
        """Parse protocol execution from dictionary"""
        protocol_data = data["protocol"]
        protocol = self._parse_protocol_definition(protocol_data)

        return ProtocolExecution(
            execution_id=data["execution_id"],
            protocol=protocol,
            status=ProtocolStatus(data["status"]),
            current_step=data.get("current_step"),
            start_time=data.get("start_time"),
            end_time=data.get("end_time"),
            total_steps=data["total_steps"],
            completed_steps=data["completed_steps"],
            failed_steps=data["failed_steps"],
            results=data.get("results", {}),
            error=data.get("error"),
        )

    def _serialize_protocol_execution(
        self, execution: ProtocolExecution
    ) -> Dict[str, Any]:
        """Serialize protocol execution to dictionary"""
        return {
            "execution_id": execution.execution_id,
            "protocol": {
                "protocol_id": execution.protocol.protocol_id,
                "name": execution.protocol.name,
                "description": execution.protocol.description,
                "version": execution.protocol.version,
                "steps": [
                    {
                        "step_id": step.step_id,
                        "robot_id": step.robot_id,
                        "operation_type": step.operation_type,
                        "parameters": step.parameters,
                        "dependencies": step.dependencies,
                        "timeout": step.timeout,
                        "max_retries": step.max_retries,
                        "status": step.status,
                        "retry_count": step.retry_count,
                        "start_time": step.start_time,
                        "end_time": step.end_time,
                        "error": step.error,
                    }
                    for step in execution.protocol.steps
                ],
                "global_parameters": execution.protocol.global_parameters,
                "required_robots": execution.protocol.required_robots,
                "estimated_duration": execution.protocol.estimated_duration,
                "safety_requirements": execution.protocol.safety_requirements,
            },
            "status": execution.status.value,
            "current_step": execution.current_step,
            "start_time": execution.start_time,
            "end_time": execution.end_time,
            "total_steps": execution.total_steps,
            "completed_steps": execution.completed_steps,
            "failed_steps": execution.failed_steps,
            "results": execution.results,
            "error": execution.error,
        }

    async def list_active_protocols(self) -> ServiceResult[List[Dict[str, Any]]]:
        """List all active protocol executions"""
        async with self._protocols_lock:
            protocols_info = []
            for execution in self._active_protocols.values():
                protocols_info.append(
                    {
                        "execution_id": execution.execution_id,
                        "protocol_name": execution.protocol.name,
                        "status": execution.status.value,
                        "progress_percentage": execution.progress_percentage,
                        "start_time": execution.start_time,
                        "estimated_duration": execution.protocol.estimated_duration,
                    }
                )

            return ServiceResult.success_result(protocols_info)

    async def health_check(self) -> Dict[str, Any]:
        """Protocol service health check"""
        base_health = await super().health_check()

        async with self._protocols_lock:
            active_count = len(self._active_protocols)
            running_count = sum(
                1
                for e in self._active_protocols.values()
                if e.status == ProtocolStatus.RUNNING
            )

        return {
            **base_health,
            "template_count": len(self._protocol_templates),
            "active_protocols": active_count,
            "running_protocols": running_count,
            "protocols_directory": str(self.protocols_dir),
        }
