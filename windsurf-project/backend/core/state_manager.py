"""
Atomic state management system for robotics control.
Provides centralized, thread-safe state management with validation and change tracking.
"""

import asyncio
import time
import logging
from datetime import datetime
from enum import Enum
from typing import Dict, Optional, List, Callable, Any, Set
from dataclasses import dataclass, field
from collections import defaultdict

from .exceptions import StateTransitionError, ValidationError


class RobotState(Enum):
    """Enumeration of possible robot states"""
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    IDLE = "idle"
    BUSY = "busy"
    ERROR = "error"
    MAINTENANCE = "maintenance"
    EMERGENCY_STOP = "emergency_stop"


class SystemState(Enum):
    """Enumeration of overall system states"""
    INITIALIZING = "initializing"
    READY = "ready"
    RUNNING = "running"
    ERROR = "error"
    MAINTENANCE = "maintenance"
    SHUTDOWN = "shutdown"


@dataclass
class StateTransition:
    """Represents a state transition event"""
    robot_id: str
    from_state: RobotState
    to_state: RobotState
    timestamp: float
    reason: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RobotInfo:
    """Information about a robot and its state"""
    robot_id: str
    robot_type: str
    current_state: RobotState
    last_updated: float
    last_transition: Optional[StateTransition] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    error_count: int = 0
    uptime_start: Optional[float] = None
    
    @property
    def uptime_seconds(self) -> float:
        """Calculate uptime in seconds"""
        if self.uptime_start is None:
            return 0.0
        return time.time() - self.uptime_start
    
    @property
    def is_operational(self) -> bool:
        """Check if robot is in operational state"""
        return self.current_state in {RobotState.IDLE, RobotState.BUSY}
    
    @property
    def needs_attention(self) -> bool:
        """Check if robot needs attention"""
        return self.current_state in {
            RobotState.ERROR, 
            RobotState.MAINTENANCE, 
            RobotState.EMERGENCY_STOP
        }


class StateChangeCallback:
    """Callback function wrapper for state changes"""
    
    def __init__(self, callback: Callable, robot_ids: Optional[Set[str]] = None):
        self.callback = callback
        self.robot_ids = robot_ids  # None means all robots
        self.call_count = 0
        self.last_called = None
    
    def should_call(self, robot_id: str) -> bool:
        """Check if callback should be called for this robot"""
        return self.robot_ids is None or robot_id in self.robot_ids
    
    async def call(self, transition: StateTransition):
        """Call the callback function"""
        try:
            if asyncio.iscoroutinefunction(self.callback):
                await self.callback(transition)
            else:
                self.callback(transition)
            self.call_count += 1
            self.last_called = time.time()
        except Exception as e:
            logging.getLogger("state_manager").error(
                f"Error in state change callback: {e}"
            )


class AtomicStateManager:
    """
    Thread-safe state manager for robotics system.
    
    Provides atomic state updates, validation, change tracking,
    and callback notifications for robot state changes.
    """
    
    # Valid state transitions
    VALID_TRANSITIONS = {
        RobotState.DISCONNECTED: {
            RobotState.CONNECTING, 
            RobotState.MAINTENANCE,
            RobotState.EMERGENCY_STOP
        },
        RobotState.CONNECTING: {
            RobotState.IDLE, 
            RobotState.ERROR, 
            RobotState.DISCONNECTED,
            RobotState.EMERGENCY_STOP
        },
        RobotState.IDLE: {
            RobotState.BUSY, 
            RobotState.ERROR, 
            RobotState.MAINTENANCE,
            RobotState.DISCONNECTED,
            RobotState.EMERGENCY_STOP
        },
        RobotState.BUSY: {
            RobotState.IDLE, 
            RobotState.ERROR, 
            RobotState.MAINTENANCE,
            RobotState.DISCONNECTED,
            RobotState.EMERGENCY_STOP
        },
        RobotState.ERROR: {
            RobotState.IDLE, 
            RobotState.MAINTENANCE, 
            RobotState.DISCONNECTED,
            RobotState.EMERGENCY_STOP
        },
        RobotState.MAINTENANCE: {
            RobotState.IDLE, 
            RobotState.DISCONNECTED,
            RobotState.EMERGENCY_STOP
        },
        RobotState.EMERGENCY_STOP: {
            RobotState.MAINTENANCE,
            RobotState.DISCONNECTED
        }
    }
    
    def __init__(self, max_history: int = 1000):
        self.max_history = max_history
        
        # Robot state tracking
        self._robots: Dict[str, RobotInfo] = {}
        self._system_state = SystemState.INITIALIZING
        
        # State change history
        self._history: List[StateTransition] = []
        
        # Callbacks for state changes
        self._callbacks: List[StateChangeCallback] = []
        
        # Statistics
        self._stats = defaultdict(int)
        
        # Thread safety
        self._lock = asyncio.Lock()
        
        # System metadata
        self._system_metadata: Dict[str, Any] = {}
        
        self.logger = logging.getLogger("state_manager")
        self.logger.info("AtomicStateManager initialized")
    
    async def register_robot(
        self, 
        robot_id: str, 
        robot_type: str, 
        initial_state: RobotState = RobotState.DISCONNECTED,
        metadata: Optional[Dict[str, Any]] = None
    ):
        """
        Register a new robot with the state manager.
        
        Args:
            robot_id: Unique identifier for the robot
            robot_type: Type of robot (e.g., 'meca', 'ot2', 'arduino')
            initial_state: Initial state for the robot
            metadata: Additional metadata about the robot
        """
        async with self._lock:
            if robot_id in self._robots:
                self.logger.warning(f"Robot {robot_id} already registered")
                return
            
            now = time.time()
            uptime_start = now if initial_state in {RobotState.IDLE, RobotState.BUSY} else None
            
            robot_info = RobotInfo(
                robot_id=robot_id,
                robot_type=robot_type,
                current_state=initial_state,
                last_updated=now,
                metadata=metadata or {},
                uptime_start=uptime_start
            )
            
            self._robots[robot_id] = robot_info
            self._stats[f"robot_{robot_type}_registered"] += 1
            
            self.logger.info(
                f"Robot registered: {robot_id} (type: {robot_type}, "
                f"initial_state: {initial_state.value})"
            )
    
    async def update_robot_state(
        self, 
        robot_id: str, 
        new_state: RobotState, 
        reason: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Update robot state with atomic operation and validation.
        
        Args:
            robot_id: Robot identifier
            new_state: New state to transition to
            reason: Reason for state change
            metadata: Additional metadata for the transition
            
        Returns:
            True if state was updated, False otherwise
            
        Raises:
            ValidationError: If robot_id is invalid
            StateTransitionError: If transition is not allowed
        """
        async with self._lock:
            # Validate robot exists
            if robot_id not in self._robots:
                raise ValidationError(
                    f"Robot '{robot_id}' not registered",
                    field="robot_id",
                    value=robot_id
                )
            
            robot_info = self._robots[robot_id]
            current_state = robot_info.current_state
            
            # Skip if already in target state - do this BEFORE validation
            if current_state == new_state:
                self.logger.debug(f"Robot {robot_id} already in state {new_state.value}")
                return False
            
            # Check if transition is valid
            if not await self._is_valid_transition(current_state, new_state):
                raise StateTransitionError(
                    f"Invalid state transition for robot '{robot_id}': "
                    f"{current_state.value} -> {new_state.value}",
                    current_state=current_state.value,
                    attempted_state=new_state.value,
                    robot_id=robot_id
                )
            
            # Create transition record
            transition = StateTransition(
                robot_id=robot_id,
                from_state=current_state,
                to_state=new_state,
                timestamp=time.time(),
                reason=reason,
                metadata=metadata or {}
            )
            
            # Update robot state
            robot_info.current_state = new_state
            robot_info.last_updated = transition.timestamp
            robot_info.last_transition = transition
            
            # Update error count
            if new_state == RobotState.ERROR:
                robot_info.error_count += 1
            elif new_state in {RobotState.IDLE, RobotState.BUSY}:
                robot_info.error_count = 0  # Reset on successful operation
            
            # Update uptime tracking
            if new_state in {RobotState.IDLE, RobotState.BUSY} and robot_info.uptime_start is None:
                robot_info.uptime_start = transition.timestamp
            elif new_state not in {RobotState.IDLE, RobotState.BUSY}:
                robot_info.uptime_start = None
            
            # Add to history
            self._history.append(transition)
            if len(self._history) > self.max_history:
                self._history.pop(0)
            
            # Update statistics
            self._stats[f"transition_{current_state.value}_to_{new_state.value}"] += 1
            self._stats["total_transitions"] += 1
            
            self.logger.info(
                f"State transition: {robot_id} {current_state.value} -> {new_state.value}"
                + (f" (reason: {reason})" if reason else "")
            )
            
            # Notify callbacks (outside the lock to prevent deadlock)
            await self._notify_callbacks(transition)
            
            return True
    
    async def _is_valid_transition(
        self, from_state: RobotState, to_state: RobotState
    ) -> bool:
        """Check if state transition is valid"""
        return to_state in self.VALID_TRANSITIONS.get(from_state, set())
    
    async def get_robot_state(self, robot_id: str) -> Optional[RobotInfo]:
        """Get current state information for a robot"""
        async with self._lock:
            return self._robots.get(robot_id)
    
    async def get_all_robot_states(self) -> Dict[str, RobotInfo]:
        """Get state information for all robots"""
        async with self._lock:
            return self._robots.copy()
    
    async def get_robots_by_state(self, state: RobotState) -> List[RobotInfo]:
        """Get all robots in a specific state"""
        async with self._lock:
            return [
                robot for robot in self._robots.values()
                if robot.current_state == state
            ]
    
    async def get_system_state(self) -> SystemState:
        """Get overall system state"""
        async with self._lock:
            return self._system_state
    
    async def update_system_state(self, new_state: SystemState, reason: str = None):
        """Update overall system state"""
        async with self._lock:
            old_state = self._system_state
            self._system_state = new_state
            
            self.logger.info(
                f"System state changed: {old_state.value} -> {new_state.value}"
                + (f" (reason: {reason})" if reason else "")
            )
    
    async def register_callback(
        self, 
        callback: Callable, 
        robot_ids: Optional[Set[str]] = None
    ):
        """
        Register callback for state changes.
        
        Args:
            callback: Function to call on state changes
            robot_ids: Set of robot IDs to monitor (None for all)
        """
        async with self._lock:
            wrapper = StateChangeCallback(callback, robot_ids)
            self._callbacks.append(wrapper)
            self.logger.debug(f"State change callback registered for robots: {robot_ids}")
    
    async def _notify_callbacks(self, transition: StateTransition):
        """Notify all relevant callbacks of state change"""
        for callback_wrapper in self._callbacks:
            if callback_wrapper.should_call(transition.robot_id):
                try:
                    await callback_wrapper.call(transition)
                except Exception as e:
                    self.logger.error(f"Error in state change callback: {e}")
    
    async def get_state_history(
        self, 
        robot_id: Optional[str] = None, 
        limit: int = 100
    ) -> List[StateTransition]:
        """Get state change history"""
        async with self._lock:
            history = self._history
            
            if robot_id:
                history = [t for t in history if t.robot_id == robot_id]
            
            return list(reversed(history[-limit:]))
    
    async def get_statistics(self) -> Dict[str, Any]:
        """Get state manager statistics"""
        async with self._lock:
            robot_counts = defaultdict(int)
            for robot in self._robots.values():
                robot_counts[robot.current_state.value] += 1
            
            return {
                "total_robots": len(self._robots),
                "system_state": self._system_state.value,
                "robot_states": dict(robot_counts),
                "total_transitions": self._stats.get("total_transitions", 0),
                "transition_counts": {
                    k: v for k, v in self._stats.items()
                    if k.startswith("transition_")
                },
                "history_length": len(self._history),
                "callback_count": len(self._callbacks)
            }
    
    async def emergency_stop_all(self, reason: str = "Emergency stop triggered"):
        """Emergency stop all robots"""
        async with self._lock:
            robots_stopped = []
            
            for robot_id, robot_info in self._robots.items():
                if robot_info.current_state != RobotState.EMERGENCY_STOP:
                    try:
                        await self.update_robot_state(
                            robot_id, 
                            RobotState.EMERGENCY_STOP, 
                            reason=reason
                        )
                        robots_stopped.append(robot_id)
                    except Exception as e:
                        self.logger.error(
                            f"Failed to emergency stop robot {robot_id}: {e}"
                        )
            
            await self.update_system_state(SystemState.ERROR, reason=reason)
            
            self.logger.critical(
                f"Emergency stop executed. Stopped robots: {robots_stopped}. "
                f"Reason: {reason}"
            )
            
            return robots_stopped
    
    async def get_operational_robots(self) -> List[str]:
        """Get list of robots that are operational (idle or busy)"""
        async with self._lock:
            return [
                robot_id for robot_id, robot_info in self._robots.items()
                if robot_info.is_operational
            ]
    
    async def get_problematic_robots(self) -> List[str]:
        """Get list of robots that need attention"""
        async with self._lock:
            return [
                robot_id for robot_id, robot_info in self._robots.items()
                if robot_info.needs_attention
            ]
    
    async def cleanup_disconnected_robots(self, max_age_seconds: float = 300):
        """Remove robots that have been disconnected for too long"""
        async with self._lock:
            current_time = time.time()
            to_remove = []
            
            for robot_id, robot_info in self._robots.items():
                if (robot_info.current_state == RobotState.DISCONNECTED and
                    current_time - robot_info.last_updated > max_age_seconds):
                    to_remove.append(robot_id)
            
            for robot_id in to_remove:
                del self._robots[robot_id]
                self.logger.info(f"Removed disconnected robot: {robot_id}")
            
            return to_remove