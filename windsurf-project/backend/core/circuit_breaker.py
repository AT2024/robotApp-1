"""
Circuit breaker pattern implementation for robust robot connections.
Prevents cascade failures and provides automatic recovery for unreliable services.
"""

import time
import asyncio
import logging
from enum import Enum
from typing import Callable, Any, Optional, Dict
from dataclasses import dataclass, field
from functools import wraps

from .exceptions import CircuitBreakerOpen, ConnectionError
from utils.logger import get_logger


class CircuitBreakerState(Enum):
    """Circuit breaker states"""
    CLOSED = "closed"       # Normal operation
    OPEN = "open"          # Failing, requests blocked
    HALF_OPEN = "half_open" # Testing if service recovered


@dataclass
class CircuitBreakerStats:
    """Statistics for circuit breaker monitoring"""
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    consecutive_failures: int = 0
    last_failure_time: Optional[float] = None
    last_success_time: Optional[float] = None
    state_changes: int = 0
    
    @property
    def success_rate(self) -> float:
        """Calculate success rate as percentage"""
        if self.total_requests == 0:
            return 100.0
        return (self.successful_requests / self.total_requests) * 100.0
    
    @property
    def failure_rate(self) -> float:
        """Calculate failure rate as percentage"""
        return 100.0 - self.success_rate


class CircuitBreaker:
    """
    Circuit breaker for protecting against cascading failures.
    
    Monitors failure rates and automatically opens to prevent further
    damage when failure threshold is exceeded.
    """
    
    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
        expected_exception: type = Exception,
        half_open_max_calls: int = 3
    ):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.expected_exception = expected_exception
        self.half_open_max_calls = half_open_max_calls
        
        self._state = CircuitBreakerState.CLOSED
        self._stats = CircuitBreakerStats()
        self._half_open_attempts = 0
        self._lock = asyncio.Lock()
        
        self.logger = get_logger("circuit_breaker")
    
    @property
    def state(self) -> CircuitBreakerState:
        """Current circuit breaker state"""
        return self._state
    
    @property
    def stats(self) -> CircuitBreakerStats:
        """Circuit breaker statistics"""
        return self._stats
    
    async def call(self, func: Callable, *args, **kwargs) -> Any:
        """
        Execute function through circuit breaker protection.
        
        Args:
            func: Function to execute
            *args: Function arguments
            **kwargs: Function keyword arguments
            
        Returns:
            Function result
            
        Raises:
            CircuitBreakerOpen: When circuit breaker is open
            Original exception: When function fails
        """
        async with self._lock:
            # Check if we can proceed with the call
            if not await self._can_proceed():
                raise CircuitBreakerOpen(
                    f"Circuit breaker '{self.name}' is OPEN",
                    service_name=self.name,
                    context={
                        "failure_threshold": self.failure_threshold,
                        "consecutive_failures": self._stats.consecutive_failures,
                        "last_failure_time": self._stats.last_failure_time,
                        "recovery_timeout": self.recovery_timeout
                    }
                )
            
            # Track the attempt
            self._stats.total_requests += 1
            
            try:
                # Execute the function
                if asyncio.iscoroutinefunction(func):
                    result = await func(*args, **kwargs)
                else:
                    result = func(*args, **kwargs)
                
                # Record success
                await self._record_success()
                return result
                
            except self.expected_exception as e:
                # Record failure
                await self._record_failure(e)
                raise
            except Exception as e:
                # Unexpected exception - still record as failure
                await self._record_failure(e)
                raise
    
    async def _can_proceed(self) -> bool:
        """Check if we can proceed with the operation"""
        current_time = time.time()
        
        if self._state == CircuitBreakerState.CLOSED:
            return True
        
        elif self._state == CircuitBreakerState.OPEN:
            # Check if recovery timeout has passed
            if (self._stats.last_failure_time and 
                current_time - self._stats.last_failure_time >= self.recovery_timeout):
                await self._transition_to_half_open()
                return True
            return False
        
        elif self._state == CircuitBreakerState.HALF_OPEN:
            # Allow limited calls to test recovery
            return self._half_open_attempts < self.half_open_max_calls
        
        return False
    
    async def _record_success(self):
        """Record successful operation"""
        self._stats.successful_requests += 1
        self._stats.consecutive_failures = 0
        self._stats.last_success_time = time.time()
        
        if self._state == CircuitBreakerState.HALF_OPEN:
            self._half_open_attempts += 1
            # If we've had enough successful attempts, close the circuit
            if self._half_open_attempts >= self.half_open_max_calls:
                await self._transition_to_closed()
        
        self.logger.debug(f"Success recorded. Success rate: {self._stats.success_rate:.1f}%")
    
    async def _record_failure(self, exception: Exception):
        """Record failed operation"""
        self._stats.failed_requests += 1
        self._stats.consecutive_failures += 1
        self._stats.last_failure_time = time.time()
        
        self.logger.warning(
            f"Failure recorded: {exception}. "
            f"Consecutive failures: {self._stats.consecutive_failures}"
        )
        
        # Check if we should open the circuit
        if (self._state == CircuitBreakerState.CLOSED and 
            self._stats.consecutive_failures >= self.failure_threshold):
            self.logger.warning(
                f"Circuit breaker '{self.name}' failure threshold reached: "
                f"{self._stats.consecutive_failures}/{self.failure_threshold} consecutive failures"
            )
            await self._transition_to_open()
        elif self._state == CircuitBreakerState.HALF_OPEN:
            # Any failure in half-open state opens the circuit again
            self.logger.warning(
                f"Circuit breaker '{self.name}' failed during recovery test "
                f"(attempt {self._half_open_attempts}/{self.half_open_max_calls})"
            )
            await self._transition_to_open()
    
    async def _transition_to_open(self):
        """Transition to OPEN state"""
        old_state = self._state
        self._state = CircuitBreakerState.OPEN
        self._stats.state_changes += 1
        
        self.logger.error(
            f"Circuit breaker '{self.name}' transition: {old_state.value} → OPEN. "
            f"Failure threshold breached: {self._stats.consecutive_failures}/{self.failure_threshold} consecutive failures. "
            f"Blocking requests for {self.recovery_timeout}s."
        )
    
    async def _transition_to_half_open(self):
        """Transition to HALF_OPEN state"""
        old_state = self._state
        self._state = CircuitBreakerState.HALF_OPEN
        self._half_open_attempts = 0
        self._stats.state_changes += 1
        
        recovery_time_elapsed = time.time() - (self._stats.last_failure_time or 0)
        self.logger.info(
            f"Circuit breaker '{self.name}' transition: {old_state.value} → HALF_OPEN. "
            f"Recovery timeout reached after {recovery_time_elapsed:.1f}s. "
            f"Testing service recovery with max {self.half_open_max_calls} attempts."
        )
    
    async def _transition_to_closed(self):
        """Transition to CLOSED state"""
        old_state = self._state
        self._state = CircuitBreakerState.CLOSED
        self._half_open_attempts = 0
        self._stats.state_changes += 1
        
        self.logger.info(
            f"Circuit breaker '{self.name}' transition: {old_state.value} → CLOSED. "
            f"Service recovered successfully. Success rate: {self._stats.success_rate:.1f}%"
        )
    
    async def force_open(self):
        """Manually force circuit breaker to OPEN state"""
        async with self._lock:
            await self._transition_to_open()
            self.logger.warning(f"Circuit breaker '{self.name}' manually forced to OPEN")
    
    async def force_close(self):
        """Manually force circuit breaker to CLOSED state"""
        async with self._lock:
            self._stats.consecutive_failures = 0
            await self._transition_to_closed()
            self.logger.info(f"Circuit breaker '{self.name}' manually forced to CLOSED")
    
    def get_status(self) -> Dict[str, Any]:
        """Get current circuit breaker status"""
        return {
            "name": self.name,
            "state": self._state.value,
            "stats": {
                "total_requests": self._stats.total_requests,
                "successful_requests": self._stats.successful_requests,
                "failed_requests": self._stats.failed_requests,
                "consecutive_failures": self._stats.consecutive_failures,
                "success_rate": self._stats.success_rate,
                "failure_rate": self._stats.failure_rate,
                "last_failure_time": self._stats.last_failure_time,
                "last_success_time": self._stats.last_success_time,
                "state_changes": self._stats.state_changes
            },
            "config": {
                "failure_threshold": self.failure_threshold,
                "recovery_timeout": self.recovery_timeout,
                "half_open_max_calls": self.half_open_max_calls
            }
        }


def circuit_breaker(
    name: str,
    failure_threshold: int = 5,
    recovery_timeout: float = 60.0,
    expected_exception: type = Exception
):
    """
    Decorator for applying circuit breaker pattern to functions.
    
    Args:
        name: Circuit breaker name
        failure_threshold: Number of failures before opening
        recovery_timeout: Seconds to wait before testing recovery
        expected_exception: Exception type that triggers circuit breaker
    """
    breaker = CircuitBreaker(
        name=name,
        failure_threshold=failure_threshold,
        recovery_timeout=recovery_timeout,
        expected_exception=expected_exception
    )
    
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            return await breaker.call(func, *args, **kwargs)
        
        # Attach circuit breaker instance to function for monitoring
        wrapper._circuit_breaker = breaker
        return wrapper
    
    return decorator


class CircuitBreakerRegistry:
    """Registry for managing multiple circuit breakers"""
    
    def __init__(self):
        self._breakers: Dict[str, CircuitBreaker] = {}
    
    def register(self, breaker: CircuitBreaker):
        """Register a circuit breaker"""
        self._breakers[breaker.name] = breaker
    
    def get(self, name: str) -> Optional[CircuitBreaker]:
        """Get circuit breaker by name"""
        return self._breakers.get(name)
    
    def get_all_status(self) -> Dict[str, Dict[str, Any]]:
        """Get status of all circuit breakers"""
        return {name: breaker.get_status() for name, breaker in self._breakers.items()}
    
    async def force_open_all(self):
        """Force all circuit breakers to OPEN state"""
        for breaker in self._breakers.values():
            await breaker.force_open()
    
    async def force_close_all(self):
        """Force all circuit breakers to CLOSED state"""
        for breaker in self._breakers.values():
            await breaker.force_close()


# Global registry instance
circuit_breaker_registry = CircuitBreakerRegistry()