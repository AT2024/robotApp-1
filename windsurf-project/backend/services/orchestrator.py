"""
Robot Orchestrator - Centralized coordination of all robot services.
Replaces the monolithic RobotManager with a clean service-oriented architecture.
"""

import asyncio
import time
from typing import Dict, Any, Optional, List, Set
from dataclasses import dataclass

from core.state_manager import AtomicStateManager, RobotState, SystemState
from core.resource_lock import ResourceLockManager  
from core.hardware_manager import HardwareConnectionManager
from core.settings import RoboticsSettings
from core.exceptions import ValidationError, ConfigurationError
from .base import BaseService, ServiceResult, OperationContext
from utils.logger import get_logger


@dataclass
class SystemStatus:
    """Overall system status information"""
    system_state: SystemState
    total_robots: int
    operational_robots: int
    error_robots: int
    active_operations: int
    last_updated: float
    robot_details: Dict[str, Dict[str, Any]]


class RobotOrchestrator(BaseService):
    """
    Central orchestrator for all robot services and system coordination.
    
    Responsibilities:
    - Coordinate between specialized robot services
    - Manage system-wide operations and workflows
    - Handle emergency stops and safety protocols
    - Provide unified status and monitoring
    - Coordinate resource allocation between robots
    """
    
    def __init__(
        self,
        settings: RoboticsSettings,
        state_manager: AtomicStateManager,
        lock_manager: ResourceLockManager,
        hardware_manager: HardwareConnectionManager
    ):
        super().__init__(settings, state_manager, lock_manager, "RobotOrchestrator")
        
        self.logger = get_logger("orchestrator")
        self.hardware_manager = hardware_manager
        
        # Service registry
        self._robot_services: Dict[str, 'RobotService'] = {}
        self._protocol_service: Optional['ProtocolExecutionService'] = None
        self._monitoring_service: Optional['MonitoringService'] = None
        
        # System coordination
        self._system_lock = asyncio.Lock()
        self._emergency_stop_active = False
        self._emergency_stopped_robots: Set[str] = set()  # Track which robots are e-stopped

        # Monitoring tasks
        self._status_monitor_task: Optional[asyncio.Task] = None
        self._health_check_task: Optional[asyncio.Task] = None
    
    async def _on_start(self):
        """Start orchestrator and monitoring tasks"""
        # SAFETY: Clear any stale emergency stop state from previous session
        # This is critical after Docker restart - the in-memory tracking
        # gets reset but we want to ensure a clean slate
        self._emergency_stop_active = False
        self._emergency_stopped_robots.clear()
        self.logger.info("Cleared stale emergency stop state on startup")

        # SAFETY: Clear all paused step states on startup
        # This prevents sequences from resuming after backend restart following e-stop.
        # When user presses e-stop, the step gets paused. If backend restarts and
        # user clicks "Continue", the paused step would resume - which is DANGEROUS.
        # By clearing step states, the frontend must start a new sequence.
        try:
            cleared_steps = await self.state_manager.clear_all_paused_steps()
            if cleared_steps:
                self.logger.warning(
                    f"[SAFETY] Cleared paused steps on startup to prevent accidental resume: {cleared_steps}"
                )
        except Exception as e:
            self.logger.error(f"Failed to clear paused steps on startup: {e}")

        # Start hardware manager
        await self.hardware_manager.start()
        
        # Start all registered services
        for service in self._robot_services.values():
            await service.start()
        
        if self._protocol_service:
            await self._protocol_service.start()
        
        if self._monitoring_service:
            await self._monitoring_service.start()
        
        # Start monitoring tasks
        self._status_monitor_task = asyncio.create_task(self._monitor_system_status())
        self._health_check_task = asyncio.create_task(self._periodic_health_checks())
        
        # Update system state
        await self.state_manager.update_system_state(
            SystemState.READY,
            reason="Orchestrator started successfully"
        )
    
    async def _on_stop(self):
        """Stop orchestrator and all services"""
        # Cancel monitoring tasks
        if self._status_monitor_task:
            self._status_monitor_task.cancel()
        if self._health_check_task:
            self._health_check_task.cancel()
        
        # Stop all services
        for service in self._robot_services.values():
            await service.stop()
        
        if self._protocol_service:
            await self._protocol_service.stop()
        
        if self._monitoring_service:
            await self._monitoring_service.stop()
        
        # Stop hardware manager
        await self.hardware_manager.stop()
        
        # Update system state
        await self.state_manager.update_system_state(
            SystemState.SHUTDOWN,
            reason="Orchestrator shutdown"
        )
    
    def register_robot_service(self, robot_id: str, service: 'RobotService'):
        """Register a robot service with the orchestrator"""
        self._robot_services[robot_id] = service
        self.logger.info(f"Registered robot service: {robot_id}")
    
    def register_protocol_service(self, service: 'ProtocolExecutionService'):
        """Register the protocol execution service"""
        self._protocol_service = service
        self.logger.info("Registered protocol execution service")
    
    def register_monitoring_service(self, service: 'MonitoringService'):
        """Register the monitoring service"""
        self._monitoring_service = service
        self.logger.info("Registered monitoring service")
    
    async def get_system_status(self) -> SystemStatus:
        """Get comprehensive system status"""
        async with self._system_lock:
            system_state = await self.state_manager.get_system_state()
            all_robots = await self.state_manager.get_all_robot_states()
            
            operational_count = 0
            error_count = 0
            robot_details = {}
            
            for robot_id, robot_info in all_robots.items():
                if robot_info.is_operational:
                    operational_count += 1
                elif robot_info.needs_attention:
                    error_count += 1
                
                # Get service-specific details
                service_health = {}
                if robot_id in self._robot_services:
                    service_health = await self._robot_services[robot_id].health_check()
                
                robot_details[robot_id] = {
                    "state": robot_info.current_state.value,
                    "operational": robot_info.is_operational,
                    "needs_attention": robot_info.needs_attention,
                    "uptime_seconds": robot_info.uptime_seconds,
                    "error_count": robot_info.error_count,
                    "service_health": service_health
                }
            
            # Count active operations across all services
            active_operations = len(self._operations)
            for service in self._robot_services.values():
                active_operations += len(await service.get_running_operations())
            
            return SystemStatus(
                system_state=system_state,
                total_robots=len(all_robots),
                operational_robots=operational_count,
                error_robots=error_count,
                active_operations=active_operations,
                last_updated=time.time(),
                robot_details=robot_details
            )
    
    async def emergency_stop_all(self, reason: str = "Emergency stop triggered") -> ServiceResult[Dict[str, bool]]:
        """Emergency stop all robots in the system"""
        context = OperationContext(
            operation_id=f"system_emergency_stop_{int(time.time() * 1000)}",
            robot_id="system",
            operation_type="emergency_stop_all",
            priority=100,
            metadata={"reason": reason}
        )
        
        async def _emergency_stop_all():
            # EMERGENCY BYPASS: Skip system lock for maximum speed
            self.logger.critical(f"[EMERGENCY] Emergency stop bypassing system lock for immediate execution")
            self._emergency_stop_active = True
            
            # Update system state (non-blocking)
            asyncio.create_task(self.state_manager.update_system_state(
                SystemState.ERROR,
                reason=f"Emergency stop: {reason}"
            ))
            
            # Execute all emergency stops in PARALLEL for maximum speed
            emergency_tasks = []
            
            # Hardware manager emergency stop
            if hasattr(self.hardware_manager, 'emergency_stop_all'):
                hardware_task = asyncio.create_task(self.hardware_manager.emergency_stop_all())
                emergency_tasks.append(("hardware_manager", hardware_task))
            
            # Service emergency stops - all in parallel
            for robot_id, service in self._robot_services.items():
                service_task = asyncio.create_task(self._execute_service_emergency_stop(robot_id, service))
                emergency_tasks.append((robot_id, service_task))
            
            # Wait for all emergency stops with timeout
            service_results = {}
            hardware_results = {}
            
            if emergency_tasks:
                self.logger.critical(f"[EMERGENCY] Executing {len(emergency_tasks)} emergency stops in parallel")
                
                # Execute with 2-second timeout per task to prevent hanging
                results = await asyncio.gather(
                    *[asyncio.wait_for(task, timeout=2.0) for name, task in emergency_tasks],
                    return_exceptions=True
                )
                
                # Process results
                for i, (name, task) in enumerate(emergency_tasks):
                    result = results[i]
                    
                    if isinstance(result, asyncio.TimeoutError):
                        self.logger.error(f"[TIMEOUT] Emergency stop timeout for {name}")
                        service_results[name] = False
                    elif isinstance(result, Exception):
                        self.logger.error(f"[ERROR] Emergency stop error for {name}: {result}")
                        service_results[name] = False
                    elif name == "hardware_manager":
                        hardware_results = result if isinstance(result, dict) else {"hardware": bool(result)}
                    else:
                        service_results[name] = result
            
            # Combine results
            all_results = {**hardware_results, **service_results}
            
            self.logger.critical(
                f"[STOPPED] Emergency stop completed in parallel. Results: {all_results}. Reason: {reason}"
            )
            
            return all_results
        
        return await self.execute_operation(context, _emergency_stop_all)
    
    async def _execute_service_emergency_stop(self, robot_id: str, service) -> bool:
        """Execute emergency stop for a single service"""
        try:
            result = await service.emergency_stop()
            success = result.success if hasattr(result, 'success') else bool(result)
            if success:
                self._emergency_stopped_robots.add(robot_id)
            self.logger.critical(f"[OK] Emergency stop completed for {robot_id}: {success}")
            return success
        except Exception as e:
            self.logger.error(f"[ERROR] Emergency stop failed for {robot_id}: {e}")
            return False

    async def emergency_stop_robot(
        self, robot_id: str, reason: str = "User triggered"
    ) -> ServiceResult[Dict[str, Any]]:
        """
        Emergency stop only the specified robot (not all robots).

        Args:
            robot_id: ID of the robot to stop (e.g., 'meca', 'ot2')
            reason: Reason for the emergency stop

        Returns:
            ServiceResult with stop status
        """
        context = OperationContext(
            operation_id=f"robot_emergency_stop_{robot_id}_{int(time.time() * 1000)}",
            robot_id=robot_id,
            operation_type="emergency_stop_robot",
            priority=100,
            metadata={"reason": reason}
        )

        async def _emergency_stop_robot():
            self.logger.critical(f"[EMERGENCY] Per-robot emergency stop for {robot_id}: {reason}")

            service = self._robot_services.get(robot_id)
            if not service:
                raise ValidationError(f"Unknown robot: {robot_id}")

            # Pause the robot's current step if active
            try:
                step_state = await self.state_manager.get_step_state(robot_id)
                if step_state and not step_state.paused:
                    await self.state_manager.pause_step(robot_id, reason=f"Emergency stop: {reason}")
                    self.logger.info(f"Paused step {step_state.step_index} for {robot_id}")
            except Exception as e:
                self.logger.warning(f"Could not pause step for {robot_id}: {e}")

            # Execute emergency stop on the single robot
            success = await self._execute_service_emergency_stop(robot_id, service)

            return {
                "robot_id": robot_id,
                "success": success,
                "reason": reason,
                "timestamp": time.time()
            }

        return await self.execute_operation(context, _emergency_stop_robot)

    def get_emergency_stopped_robots(self) -> Set[str]:
        """Get set of robot IDs that are currently emergency stopped."""
        return self._emergency_stopped_robots.copy()

    def is_robot_emergency_stopped(self, robot_id: str) -> bool:
        """Check if a specific robot is emergency stopped."""
        return robot_id in self._emergency_stopped_robots

    async def reset_emergency_stop(self) -> ServiceResult[bool]:
        """Reset emergency stop state"""
        context = OperationContext(
            operation_id=f"system_emergency_reset_{int(time.time() * 1000)}",
            robot_id="system",
            operation_type="emergency_reset"
        )
        
        async def _reset_emergency_stop():
            async with self._system_lock:
                if not self._emergency_stop_active:
                    return True
                
                # Check if all robots are in safe state
                all_robots = await self.state_manager.get_all_robot_states()
                unsafe_robots = [
                    robot_id for robot_id, info in all_robots.items()
                    if info.current_state not in {
                        RobotState.DISCONNECTED,
                        RobotState.IDLE,
                        RobotState.MAINTENANCE
                    }
                ]
                
                if unsafe_robots:
                    raise ValidationError(
                        f"Cannot reset emergency stop: robots still unsafe: {unsafe_robots}"
                    )
                
                self._emergency_stop_active = False
                self._emergency_stopped_robots.clear()

                all_step_states = await self.state_manager.get_all_step_states()
                paused_steps = [
                    robot_id for robot_id, step_state in all_step_states.items()
                    if step_state and step_state.paused
                ]
                if paused_steps:
                    self.logger.info(f"Emergency stop state reset. Paused steps preserved: {paused_steps}")

                await self.state_manager.update_system_state(
                    SystemState.READY,
                    reason="Emergency stop reset"
                )

                self.logger.info("Emergency stop state reset")
                return True

        return await self.execute_operation(context, _reset_emergency_stop)

    async def reset_robot_emergency_stop(self, robot_id: str) -> ServiceResult[bool]:
        """
        Reset emergency stop for a specific robot only.

        Args:
            robot_id: ID of the robot to reset

        Returns:
            ServiceResult with reset status
        """
        context = OperationContext(
            operation_id=f"robot_emergency_reset_{robot_id}_{int(time.time() * 1000)}",
            robot_id=robot_id,
            operation_type="emergency_reset_robot"
        )

        async def _reset_robot_emergency():
            if robot_id not in self._emergency_stopped_robots:
                self.logger.info(f"Robot {robot_id} was not emergency stopped")
                return True

            # Check if robot is in safe state
            robot_info = await self.state_manager.get_robot_state(robot_id)
            if robot_info and robot_info.current_state not in {
                RobotState.DISCONNECTED, RobotState.IDLE, RobotState.MAINTENANCE
            }:
                raise ValidationError(
                    f"Cannot reset {robot_id}: still in unsafe state {robot_info.current_state.value}"
                )

            self._emergency_stopped_robots.discard(robot_id)
            self.logger.info(f"Reset emergency stop for robot {robot_id}")

            # If no more robots are e-stopped, reset system state
            if not self._emergency_stopped_robots:
                self._emergency_stop_active = False
                await self.state_manager.update_system_state(
                    SystemState.READY,
                    reason=f"All robots recovered from emergency stop"
                )

            return True

        return await self.execute_operation(context, _reset_robot_emergency)
    
    async def execute_multi_robot_workflow(
        self,
        workflow_id: str,
        robot_operations: List[Dict[str, Any]],
        coordination_strategy: str = "sequential"
    ) -> ServiceResult[List[Any]]:
        """
        Execute coordinated operations across multiple robots.
        
        Args:
            workflow_id: Unique workflow identifier
            robot_operations: List of robot operations to execute
            coordination_strategy: "sequential", "parallel", or "dependency_based"
        """
        context = OperationContext(
            operation_id=workflow_id,
            robot_id="multi_robot",
            operation_type="workflow",
            metadata={
                "robot_count": len(robot_operations),
                "strategy": coordination_strategy
            }
        )
        
        async def _execute_workflow():
            if coordination_strategy == "sequential":
                return await self._execute_sequential_workflow(robot_operations)
            elif coordination_strategy == "parallel":
                return await self._execute_parallel_workflow(robot_operations)
            elif coordination_strategy == "dependency_based":
                return await self._execute_dependency_workflow(robot_operations)
            else:
                raise ValidationError(f"Unknown coordination strategy: {coordination_strategy}")
        
        return await self.execute_operation(context, _execute_workflow)
    
    async def _execute_sequential_workflow(self, operations: List[Dict[str, Any]]) -> List[Any]:
        """Execute operations sequentially"""
        results = []
        
        for i, operation in enumerate(operations):
            robot_id = operation["robot_id"]
            operation_type = operation["operation_type"]
            params = operation.get("parameters", {})
            
            if robot_id not in self._robot_services:
                raise ValidationError(f"Robot service not found: {robot_id}")
            
            service = self._robot_services[robot_id]
            
            # Execute operation on specific robot service
            if hasattr(service, operation_type):
                method = getattr(service, operation_type)
                result = await method(**params)
                results.append(result)
            else:
                raise ValidationError(f"Operation {operation_type} not supported by {robot_id}")
            
            self.logger.info(f"Workflow step {i+1}/{len(operations)} completed")
        
        return results
    
    async def _execute_parallel_workflow(self, operations: List[Dict[str, Any]]) -> List[Any]:
        """Execute operations in parallel"""
        tasks = []
        
        for operation in operations:
            robot_id = operation["robot_id"]
            operation_type = operation["operation_type"]
            params = operation.get("parameters", {})
            
            if robot_id not in self._robot_services:
                raise ValidationError(f"Robot service not found: {robot_id}")
            
            service = self._robot_services[robot_id]
            
            if hasattr(service, operation_type):
                method = getattr(service, operation_type)
                task = asyncio.create_task(method(**params))
                tasks.append(task)
            else:
                raise ValidationError(f"Operation {operation_type} not supported by {robot_id}")
        
        # Wait for all tasks to complete
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Check for exceptions
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                raise result
        
        return results
    
    async def _execute_dependency_workflow(self, operations: List[Dict[str, Any]]) -> List[Any]:
        """Execute operations based on dependencies"""
        # Implementation would include dependency resolution
        # For now, fall back to sequential execution
        self.logger.warning("Dependency-based workflow not yet implemented, using sequential")
        return await self._execute_sequential_workflow(operations)
    
    async def get_robot_service(self, robot_id: str) -> Optional['RobotService']:
        """Get robot service by ID"""
        return self._robot_services.get(robot_id)
    
    def list_robot_services(self) -> Dict[str, str]:
        """List all registered robot services"""
        return {robot_id: service.__class__.__name__ for robot_id, service in self._robot_services.items()}
    
    async def get_available_robots(self, robot_type: str = None) -> List[str]:
        """Get list of available robots, optionally filtered by type"""
        available = []
        
        self.logger.info(f"Checking available robots (filter: {robot_type})")
        
        for robot_id, service in self._robot_services.items():
            self.logger.debug(f"Checking robot {robot_id} (type: {service.robot_type})")
            
            if robot_type and service.robot_type != robot_type:
                self.logger.debug(f"Skipping robot {robot_id} - type mismatch ({service.robot_type} != {robot_type})")
                continue
            
            robot_info = await self.state_manager.get_robot_state(robot_id)
            if robot_info:
                self.logger.info(f"Robot {robot_id} state: {robot_info.current_state}, operational: {robot_info.is_operational}")
                if robot_info.is_operational:
                    available.append(robot_id)
                    self.logger.info(f"Added robot {robot_id} to available list")
                else:
                    self.logger.warning(f"Robot {robot_id} not operational (state: {robot_info.current_state})")
            else:
                self.logger.error(f"No state information available for robot {robot_id}")
        
        return available
    
    async def _monitor_system_status(self):
        """Background task to monitor system status"""
        while self._running:
            try:
                await asyncio.sleep(self.settings.robot_status_check_interval)
                
                # Check for problematic robots
                problematic = await self.state_manager.get_problematic_robots()
                if problematic:
                    self.logger.warning(f"Robots needing attention: {problematic}")
                
                # Update system state based on robot states
                # Note: Don't set system to ERROR just because no robots are operational
                # The backend system can be READY even with disconnected robots
                operational = await self.state_manager.get_operational_robots()
                current_state = await self.state_manager.get_system_state()
                
                # Only change to ERROR if there's an actual system-level problem
                # Individual robot disconnection doesn't make the whole system unusable
                if operational and current_state == SystemState.ERROR and not self._emergency_stop_active:
                    await self.state_manager.update_system_state(
                        SystemState.READY,
                        reason="System operational"
                    )
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(f"Error in system status monitoring: {e}")
    
    async def _periodic_health_checks(self):
        """Background task for periodic health checks"""
        while self._running:
            try:
                await asyncio.sleep(self.settings.health_check_interval)
                
                # Perform health checks on all services
                for robot_id, service in self._robot_services.items():
                    try:
                        health = await service.health_check()
                        if not health.get("healthy", False):
                            self.logger.warning(f"Health check failed for {robot_id}: {health}")
                    except Exception as e:
                        self.logger.error(f"Health check error for {robot_id}: {e}")
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(f"Error in health check monitoring: {e}")
    
    async def pause_all_operations(self, reason: str = "System pause", metadata: Optional[Dict[str, Any]] = None) -> ServiceResult[Dict[str, Any]]:
        """
        Pause all active operations across all robot services.
        
        Args:
            reason: Reason for the pause
            metadata: Additional metadata about the pause request
        """
        async with self._system_lock:
            try:
                paused_operations = []
                
                self.logger.info(f"Pausing all operations: {reason}")
                
                # Pause all robot services
                for robot_id, service in self._robot_services.items():
                    try:
                        if hasattr(service, 'pause_operations'):
                            result = await service.pause_operations(reason=reason)
                            if result.success:
                                paused_operations.extend(result.data.get('operations', []))
                                self.logger.info(f"Paused operations for {robot_id}")
                            else:
                                self.logger.warning(f"Failed to pause operations for {robot_id}: {result.error}")
                        else:
                            # Fallback: Update robot state to paused
                            await self.state_manager.update_robot_state(
                                robot_id, 
                                RobotState.MAINTENANCE,  # Use maintenance state for pause
                                reason=f"Paused - {reason}"
                            )
                            paused_operations.append(f"{robot_id}_maintenance_pause")
                    except Exception as e:
                        self.logger.error(f"Error pausing operations for {robot_id}: {e}")
                
                # Pause protocol service if available
                if self._protocol_service and hasattr(self._protocol_service, 'pause_all_protocols'):
                    try:
                        protocol_result = await self._protocol_service.pause_all_protocols(reason=reason)
                        if protocol_result.success:
                            paused_operations.extend(protocol_result.data.get('protocols', []))
                    except Exception as e:
                        self.logger.error(f"Error pausing protocols: {e}")
                
                # Update system state if needed
                await self.state_manager.update_system_state(
                    SystemState.MAINTENANCE,
                    reason=f"System paused - {reason}"
                )
                
                return ServiceResult.success_result({
                    "paused_operations": paused_operations,
                    "reason": reason,
                    "metadata": metadata or {},
                    "pause_time": time.time()
                })
                
            except Exception as e:
                self.logger.error(f"Failed to pause all operations: {e}")
                return ServiceResult.error_result(
                    error=f"Pause operation failed: {str(e)}",
                    error_code="PAUSE_FAILED"
                )
    
    async def resume_all_operations(self, metadata: Optional[Dict[str, Any]] = None) -> ServiceResult[Dict[str, Any]]:
        """
        Resume all paused operations across all robot services.
        
        Args:
            metadata: Additional metadata about the resume request
        """
        async with self._system_lock:
            try:
                resumed_operations = []
                
                self.logger.info("Resuming all operations")
                
                # Resume all robot services
                for robot_id, service in self._robot_services.items():
                    try:
                        if hasattr(service, 'resume_operations'):
                            result = await service.resume_operations()
                            if result.success:
                                resumed_operations.extend(result.data.get('operations', []))
                                self.logger.info(f"Resumed operations for {robot_id}")
                            else:
                                self.logger.warning(f"Failed to resume operations for {robot_id}: {result.error}")
                        else:
                            # Fallback: Update robot state back to idle
                            robot_info = await self.state_manager.get_robot_state(robot_id)
                            if robot_info and robot_info.current_state == RobotState.MAINTENANCE:
                                await self.state_manager.update_robot_state(
                                    robot_id, 
                                    RobotState.IDLE,
                                    reason="Resumed from pause"
                                )
                                resumed_operations.append(f"{robot_id}_resumed_from_pause")
                    except Exception as e:
                        self.logger.error(f"Error resuming operations for {robot_id}: {e}")
                
                # Resume protocol service if available
                if self._protocol_service and hasattr(self._protocol_service, 'resume_all_protocols'):
                    try:
                        protocol_result = await self._protocol_service.resume_all_protocols()
                        if protocol_result.success:
                            resumed_operations.extend(protocol_result.data.get('protocols', []))
                    except Exception as e:
                        self.logger.error(f"Error resuming protocols: {e}")
                
                # Update system state back to ready
                await self.state_manager.update_system_state(
                    SystemState.READY,
                    reason="System resumed from pause"
                )
                
                return ServiceResult.success_result({
                    "resumed_operations": resumed_operations,
                    "metadata": metadata or {},
                    "resume_time": time.time()
                })
                
            except Exception as e:
                self.logger.error(f"Failed to resume all operations: {e}")
                return ServiceResult.error_result(
                    error=f"Resume operation failed: {str(e)}",
                    error_code="RESUME_FAILED"
                )
    
    async def health_check(self) -> Dict[str, Any]:
        """Comprehensive orchestrator health check"""
        base_health = await super().health_check()
        
        # Check all registered services
        service_health = {}
        for robot_id, service in self._robot_services.items():
            try:
                service_health[robot_id] = await service.health_check()
            except Exception as e:
                service_health[robot_id] = {"healthy": False, "error": str(e)}
        
        system_status = await self.get_system_status()
        
        return {
            **base_health,
            "system_state": system_status.system_state.value,
            "emergency_stop_active": self._emergency_stop_active,
            "registered_services": len(self._robot_services),
            "operational_robots": system_status.operational_robots,
            "service_health": service_health
        }