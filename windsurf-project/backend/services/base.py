"""
Base service classes and interfaces for the robotics control system.
Provides common functionality and patterns for all services.
"""

import asyncio
import time
import logging
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, List, Generic, TypeVar
from dataclasses import dataclass, field

from core.exceptions import RoboticsException, ValidationError
from core.state_manager import AtomicStateManager, RobotState
from core.resource_lock import ResourceLockManager
from core.settings import RoboticsSettings
from utils.logger import get_logger


T = TypeVar('T')


@dataclass
class ServiceResult(Generic[T]):
    """Standard result wrapper for service operations"""
    success: bool
    data: Optional[T] = None
    error: Optional[str] = None
    error_code: Optional[str] = None
    execution_time: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    @classmethod
    def success_result(cls, data: T, execution_time: float = 0.0, **metadata) -> 'ServiceResult[T]':
        """Create a successful result"""
        return cls(
            success=True,
            data=data,
            execution_time=execution_time,
            metadata=metadata
        )
    
    @classmethod
    def error_result(cls, error: str, error_code: str = None, execution_time: float = 0.0) -> 'ServiceResult[T]':
        """Create an error result"""
        return cls(
            success=False,
            error=error,
            error_code=error_code,
            execution_time=execution_time
        )
    
    @classmethod
    def from_exception(cls, exc: Exception, execution_time: float = 0.0) -> 'ServiceResult[T]':
        """Create error result from exception"""
        if isinstance(exc, RoboticsException):
            return cls(
                success=False,
                error=str(exc),
                error_code=exc.error_code,
                execution_time=execution_time,
                metadata=exc.context
            )
        else:
            return cls(
                success=False,
                error=str(exc),
                error_code="UNKNOWN_ERROR",
                execution_time=execution_time
            )


@dataclass
class OperationContext:
    """Context information for robot operations"""
    operation_id: str
    robot_id: str
    operation_type: str
    user_id: Optional[str] = None
    priority: int = 0
    timeout: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def __post_init__(self):
        if not self.operation_id:
            self.operation_id = f"{self.robot_id}_{self.operation_type}_{int(time.time() * 1000)}"


class BaseService(ABC):
    """
    Base class for all robotics services.
    
    Provides common functionality including logging, error handling,
    state management, and resource coordination.
    """
    
    def __init__(
        self,
        settings: RoboticsSettings,
        state_manager: AtomicStateManager,
        lock_manager: ResourceLockManager,
        service_name: str = None
    ):
        self.settings = settings
        self.state_manager = state_manager
        self.lock_manager = lock_manager
        self.service_name = service_name or self.__class__.__name__
        
        # Service state
        self._running = False
        self._operations: Dict[str, OperationContext] = {}
        self._operation_lock = asyncio.Lock()
        
        # Health monitoring
        self._health_monitoring_task: Optional[asyncio.Task] = None
        self._last_connection_state: Optional[bool] = None
        
        # Metrics
        self._metrics = {
            "total_operations": 0,
            "successful_operations": 0,
            "failed_operations": 0,
            "average_execution_time": 0.0,
            "operation_types": {}
        }
        
        self.logger = get_logger("base")
    
    async def start(self):
        """Start the service"""
        if self._running:
            return
        
        self._running = True
        await self._on_start()
        
        # Start health monitoring for robot services
        if isinstance(self, RobotService):
            await self._start_health_monitoring()
        
        self.logger.info(f"{self.service_name} service started")
    
    async def stop(self):
        """Stop the service"""
        if not self._running:
            return
        
        self._running = False
        
        # Stop health monitoring
        await self._stop_health_monitoring()
        
        # Cancel all running operations
        async with self._operation_lock:
            if self._operations:
                self.logger.warning(f"Stopping service with {len(self._operations)} running operations")
                self._operations.clear()
        
        await self._on_stop()
        self.logger.info(f"{self.service_name} service stopped")
    
    async def _on_start(self):
        """Override for service-specific startup logic"""
        pass
    
    async def _on_stop(self):
        """Override for service-specific shutdown logic"""
        pass
    
    # Health monitoring methods - only used by robot services
    async def _check_robot_connection(self) -> bool:
        """
        Check if the robot is connected and accessible.
        Should be implemented by robot services.
        
        Returns:
            bool: True if robot is connected, False otherwise
        """
        return True  # Default implementation for non-robot services
    
    async def _start_health_monitoring(self):
        """Start background health monitoring task"""
        if self._health_monitoring_task and not self._health_monitoring_task.done():
            return
        
        self._health_monitoring_task = asyncio.create_task(self._health_monitoring_loop())
        self.logger.info(f"Started health monitoring for {self.service_name}")
    
    async def _stop_health_monitoring(self):
        """Stop background health monitoring task"""
        if self._health_monitoring_task and not self._health_monitoring_task.done():
            self._health_monitoring_task.cancel()
            try:
                await self._health_monitoring_task
            except asyncio.CancelledError:
                pass
        self.logger.info(f"Stopped health monitoring for {self.service_name}")
    
    async def _health_monitoring_loop(self):
        """Background health monitoring loop"""
        while self._running:
            try:
                # Check robot connection with timeout
                check_timeout = min(self.settings.robot_status_check_interval - 1, 3.0)
                is_connected = await asyncio.wait_for(
                    self._check_robot_connection(),
                    timeout=check_timeout
                )
                
                # Detect state change
                if self._last_connection_state != is_connected:
                    self.logger.info(
                        f"Robot connection state changed: {self._last_connection_state} -> {is_connected}"
                    )
                    
                    # Update last known state
                    self._last_connection_state = is_connected
                    
                    # Handle state change
                    await self._handle_connection_state_change(is_connected)
                
            except asyncio.TimeoutError:
                self.logger.warning(f"Connection check timeout for {self.service_name}")
                if self._last_connection_state is not False:
                    self._last_connection_state = False
                    await self._handle_connection_state_change(False)
            except Exception as e:
                self.logger.error(f"Health monitoring error in {self.service_name}: {e}")
                if self._last_connection_state is not False:
                    self._last_connection_state = False
                    await self._handle_connection_state_change(False)
            
            # Wait for next check
            try:
                await asyncio.sleep(self.settings.robot_status_check_interval)
            except asyncio.CancelledError:
                break
    
    async def _handle_connection_state_change(self, is_connected: bool):
        """
        Handle robot connection state change.
        Override in subclasses for robot-specific behavior.
        """
        # Default implementation - can be overridden by subclasses
        self.logger.info(f"Robot connection state: {'connected' if is_connected else 'disconnected'}")
    
    async def execute_operation(
        self,
        context: OperationContext,
        operation_func,
        *args,
        **kwargs
    ) -> ServiceResult:
        """
        Execute an operation with proper tracking and error handling.
        
        Args:
            context: Operation context
            operation_func: Function to execute
            *args: Function arguments
            **kwargs: Function keyword arguments
            
        Returns:
            ServiceResult with operation outcome
        """
        start_time = time.time()
        
        # Validate service is running
        if not self._running:
            return ServiceResult.error_result(
                f"Service {self.service_name} is not running",
                error_code="SERVICE_NOT_RUNNING"
            )
        
        # Register operation
        async with self._operation_lock:
            self._operations[context.operation_id] = context
        
        try:
            self.logger.info(
                f"Starting operation {context.operation_id}: {context.operation_type} "
                f"for robot {context.robot_id}"
            )
            
            # Execute with timeout if specified
            if context.timeout:
                result = await asyncio.wait_for(
                    operation_func(*args, **kwargs),
                    timeout=context.timeout
                )
            else:
                result = await operation_func(*args, **kwargs)
            
            execution_time = time.time() - start_time
            
            # Update metrics
            await self._update_metrics(context.operation_type, True, execution_time)
            
            self.logger.info(
                f"Operation {context.operation_id} completed successfully "
                f"in {execution_time:.2f}s"
            )
            
            return ServiceResult.success_result(
                data=result,
                execution_time=execution_time,
                operation_id=context.operation_id
            )
            
        except asyncio.TimeoutError:
            execution_time = time.time() - start_time
            await self._update_metrics(context.operation_type, False, execution_time)
            
            error_msg = f"Operation {context.operation_id} timed out after {context.timeout}s"
            self.logger.error(error_msg)
            
            return ServiceResult.error_result(
                error=error_msg,
                error_code="OPERATION_TIMEOUT",
                execution_time=execution_time
            )
            
        except Exception as e:
            execution_time = time.time() - start_time
            await self._update_metrics(context.operation_type, False, execution_time)
            
            self.logger.error(
                f"Operation {context.operation_id} failed: {e}",
                exc_info=True
            )
            
            return ServiceResult.from_exception(e, execution_time)
            
        finally:
            # Unregister operation
            async with self._operation_lock:
                self._operations.pop(context.operation_id, None)
    
    async def _update_metrics(self, operation_type: str, success: bool, execution_time: float):
        """Update service metrics"""
        self._metrics["total_operations"] += 1
        
        if success:
            self._metrics["successful_operations"] += 1
        else:
            self._metrics["failed_operations"] += 1
        
        # Update average execution time
        total = self._metrics["total_operations"]
        current_avg = self._metrics["average_execution_time"]
        self._metrics["average_execution_time"] = (
            (current_avg * (total - 1) + execution_time) / total
        )
        
        # Update operation type metrics
        if operation_type not in self._metrics["operation_types"]:
            self._metrics["operation_types"][operation_type] = {
                "count": 0,
                "success_count": 0,
                "avg_time": 0.0
            }
        
        type_metrics = self._metrics["operation_types"][operation_type]
        type_metrics["count"] += 1
        
        if success:
            type_metrics["success_count"] += 1
        
        # Update average time for this operation type
        type_metrics["avg_time"] = (
            (type_metrics["avg_time"] * (type_metrics["count"] - 1) + execution_time) /
            type_metrics["count"]
        )
    
    async def get_running_operations(self) -> List[OperationContext]:
        """Get list of currently running operations"""
        async with self._operation_lock:
            return list(self._operations.values())
    
    async def cancel_operation(self, operation_id: str) -> bool:
        """Cancel a running operation"""
        async with self._operation_lock:
            if operation_id in self._operations:
                # Note: Actual cancellation depends on operation implementation
                self.logger.warning(f"Requested cancellation of operation {operation_id}")
                return True
            return False
    
    def get_metrics(self) -> Dict[str, Any]:
        """Get service performance metrics"""
        return {
            "service_name": self.service_name,
            "running": self._running,
            "active_operations": len(self._operations),
            "metrics": self._metrics.copy()
        }
    
    async def health_check(self) -> Dict[str, Any]:
        """Perform health check of the service"""
        return {
            "service": self.service_name,
            "healthy": self._running,
            "active_operations": len(self._operations),
            "last_check": time.time()
        }


class RobotService(BaseService):
    """
    Base class for robot-specific services.
    
    Extends BaseService with robot-specific functionality including
    state management, connection handling, and safety features.
    """
    
    def __init__(
        self,
        robot_id: str,
        robot_type: str,
        settings: RoboticsSettings,
        state_manager: AtomicStateManager,
        lock_manager: ResourceLockManager,
        service_name: str = None
    ):
        super().__init__(settings, state_manager, lock_manager, service_name)
        self.robot_id = robot_id
        self.robot_type = robot_type
        
        # Robot-specific state
        self._last_status_check = 0.0
        self._status_check_interval = 5.0
    
    async def _on_start(self):
        """Register robot with state manager on service start"""
        await super()._on_start()
        
        # Register robot with state manager
        await self.state_manager.register_robot(
            self.robot_id,
            self.robot_type,
            initial_state=RobotState.DISCONNECTED,
            metadata={"service": self.service_name}
        )
        
        self.logger.info(f"Registered robot {self.robot_id} with state manager")
    
    async def ensure_robot_ready(self, allow_busy: bool = True) -> bool:
        """Ensure robot is in a ready state for operations"""
        self.logger.debug(f"Checking robot readiness for {self.robot_id} (allow_busy: {allow_busy})")
        
        robot_info = await self.state_manager.get_robot_state(self.robot_id)
        
        if not robot_info:
            self.logger.error(f"Robot {self.robot_id} not registered in state manager")
            raise ValidationError(f"Robot {self.robot_id} not registered")
        
        # Allow IDLE state for new operations, and BUSY state for operations already in progress
        allowed_states = [RobotState.IDLE]
        if allow_busy:
            allowed_states.append(RobotState.BUSY)
        
        self.logger.debug(f"Robot {self.robot_id} current state: {robot_info.current_state.value}, allowed states: {[s.value for s in allowed_states]}")
        
        if robot_info.current_state not in allowed_states:
            state_names = [state.value for state in allowed_states]
            error_msg = f"Robot {self.robot_id} not ready (state: {robot_info.current_state.value}). Robot must be in one of: {state_names}"
            self.logger.error(error_msg)
            raise ValidationError(error_msg)
        
        self.logger.debug(f"Robot {self.robot_id} readiness check passed")
        return True
    
    async def update_robot_state(
        self, 
        new_state: RobotState, 
        reason: str = None
    ) -> bool:
        """Update robot state with logging"""
        return await self.state_manager.update_robot_state(
            self.robot_id,
            new_state,
            reason=reason
        )
    
    async def emergency_stop(self) -> ServiceResult[bool]:
        """Emergency stop the robot"""
        context = OperationContext(
            operation_id=f"{self.robot_id}_emergency_stop_{int(time.time() * 1000)}",
            robot_id=self.robot_id,
            operation_type="emergency_stop",
            priority=100  # Highest priority
        )
        
        async def _emergency_stop():
            await self.update_robot_state(
                RobotState.EMERGENCY_STOP,
                reason="Emergency stop triggered"
            )
            return await self._execute_emergency_stop()
        
        return await self.execute_operation(context, _emergency_stop)
    
    @abstractmethod
    async def _execute_emergency_stop(self) -> bool:
        """Implementation-specific emergency stop logic"""
        pass
    
    async def health_check(self) -> Dict[str, Any]:
        """Robot service health check"""
        base_health = await super().health_check()
        
        robot_info = await self.state_manager.get_robot_state(self.robot_id)
        
        return {
            **base_health,
            "robot_id": self.robot_id,
            "robot_type": self.robot_type,
            "robot_state": robot_info.current_state.value if robot_info else "unknown",
            "robot_operational": robot_info.is_operational if robot_info else False
        }