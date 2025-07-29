"""
Custom exception hierarchy for the robotics control system.
Provides specific, recoverable error types for better error handling and debugging.
"""

import time
from typing import Optional, Dict, Any
from enum import Enum


class ErrorSeverity(Enum):
    """Severity levels for robotics errors"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class RoboticsException(Exception):
    """
    Base exception for all robotics operations.
    
    Provides context about the robot involved, error severity,
    and whether the operation can be retried.
    """
    
    def __init__(
        self, 
        message: str, 
        robot_id: Optional[str] = None, 
        recoverable: bool = True,
        severity: ErrorSeverity = ErrorSeverity.MEDIUM,
        error_code: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None
    ):
        super().__init__(message)
        self.robot_id = robot_id
        self.recoverable = recoverable
        self.severity = severity
        self.error_code = error_code
        self.context = context or {}
        self.timestamp = time.time()
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert exception to dictionary for logging/API responses"""
        return {
            "error_type": self.__class__.__name__,
            "message": str(self),
            "robot_id": self.robot_id,
            "recoverable": self.recoverable,
            "severity": self.severity.value,
            "error_code": self.error_code,
            "context": self.context,
            "timestamp": self.timestamp
        }


class ConnectionError(RoboticsException):
    """Robot connection failed or was lost"""
    
    def __init__(self, message: str, robot_id: str, **kwargs):
        super().__init__(
            message, 
            robot_id=robot_id, 
            recoverable=True,
            severity=ErrorSeverity.HIGH,
            **kwargs
        )


class ProtocolExecutionError(RoboticsException):
    """Protocol execution failed"""
    
    def __init__(self, message: str, protocol_id: str = None, **kwargs):
        context = kwargs.get('context', {})
        if protocol_id:
            context['protocol_id'] = protocol_id
        kwargs['context'] = context
        
        super().__init__(
            message,
            recoverable=False,  # Protocol failures usually require intervention
            severity=ErrorSeverity.HIGH,
            **kwargs
        )


class HardwareError(RoboticsException):
    """Physical hardware malfunction"""
    
    def __init__(self, message: str, robot_id: str, **kwargs):
        super().__init__(
            message,
            robot_id=robot_id,
            recoverable=False,  # Hardware issues require physical intervention
            severity=ErrorSeverity.CRITICAL,
            **kwargs
        )


class StateTransitionError(RoboticsException):
    """Invalid state transition attempted"""
    
    def __init__(self, message: str, current_state: str, attempted_state: str, **kwargs):
        context = kwargs.get('context', {})
        context.update({
            'current_state': current_state,
            'attempted_state': attempted_state
        })
        kwargs['context'] = context
        
        super().__init__(
            message,
            recoverable=True,
            severity=ErrorSeverity.MEDIUM,
            **kwargs
        )


class ResourceLockTimeout(RoboticsException):
    """Failed to acquire resource lock within timeout"""
    
    def __init__(self, message: str, resource_id: str, timeout: float, **kwargs):
        context = kwargs.get('context', {})
        context.update({
            'resource_id': resource_id,
            'timeout': timeout
        })
        kwargs['context'] = context
        
        super().__init__(
            message,
            recoverable=True,
            severity=ErrorSeverity.MEDIUM,
            **kwargs
        )


class ValidationError(RoboticsException):
    """Input validation failed"""
    
    def __init__(self, message: str, field: str = None, value: Any = None, **kwargs):
        context = kwargs.get('context', {})
        if field:
            context['field'] = field
        if value is not None:
            context['invalid_value'] = str(value)
        kwargs['context'] = context
        
        super().__init__(
            message,
            recoverable=True,
            severity=ErrorSeverity.LOW,
            **kwargs
        )


class CircuitBreakerOpen(RoboticsException):
    """Circuit breaker is open, preventing operation"""
    
    def __init__(self, message: str, service_name: str, **kwargs):
        context = kwargs.get('context', {})
        context['service_name'] = service_name
        kwargs['context'] = context
        
        super().__init__(
            message,
            recoverable=True,
            severity=ErrorSeverity.HIGH,
            **kwargs
        )


class ConfigurationError(RoboticsException):
    """System configuration error"""
    
    def __init__(self, message: str, config_key: str = None, **kwargs):
        context = kwargs.get('context', {})
        if config_key:
            context['config_key'] = config_key
        kwargs['context'] = context
        
        super().__init__(
            message,
            recoverable=False,  # Config errors usually require restart
            severity=ErrorSeverity.HIGH,
            **kwargs
        )


class EmergencyStopTriggered(RoboticsException):
    """Emergency stop was triggered"""
    
    def __init__(self, message: str, triggered_by: str = None, **kwargs):
        context = kwargs.get('context', {})
        if triggered_by:
            context['triggered_by'] = triggered_by
        kwargs['context'] = context
        
        super().__init__(
            message,
            recoverable=False,
            severity=ErrorSeverity.CRITICAL,
            **kwargs
        )