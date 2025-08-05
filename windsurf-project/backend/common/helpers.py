"""
Common helper functions to reduce code duplication across services and routers.
"""

import time
from typing import Any, Callable, Dict, Optional, Union
from fastapi import HTTPException
from utils.logger import get_logger

from core.state_manager import AtomicStateManager, RobotState
from core.exceptions import HardwareError
from services.base import ServiceResult, OperationContext
from services.command_service import RobotCommandService, CommandType, CommandPriority


class RouterHelper:
    """Helper functions for consistent router error handling and response formatting."""
    
    @staticmethod
    async def execute_service_operation(
        service_method: Callable,
        operation_name: str,
        logger,
        *args,
        **kwargs
    ) -> Any:
        """
        Standard error handling wrapper for service operations in routers.
        
        Args:
            service_method: The service method to execute
            operation_name: Name of the operation for logging
            logger: Logger instance
            *args, **kwargs: Arguments to pass to the service method
            
        Returns:
            The result data from the service method
            
        Raises:
            HTTPException: With appropriate status code and error message
        """
        try:
            result = await service_method(*args, **kwargs)
            
            # Handle ServiceResult objects
            if hasattr(result, 'success'):
                if not result.success:
                    raise HTTPException(status_code=500, detail=result.error)
                return result.data
            
            # Handle direct results
            return result
            
        except HTTPException:
            # Re-raise HTTP exceptions as-is
            raise
        except Exception as e:
            logger.error(f"Error in {operation_name}: {e}")
            raise HTTPException(status_code=500, detail=str(e))


class CommandHelper:
    """Helper functions for consistent command submission and response formatting."""
    
    @staticmethod
    async def submit_robot_command(
        command_service: RobotCommandService,
        robot_id: str,
        command_type: CommandType,
        parameters: Dict[str, Any] = None,
        priority: CommandPriority = CommandPriority.NORMAL,
        timeout: float = 120.0,
        success_message: str = "Command submitted"
    ) -> Dict[str, Any]:
        """
        Standard command submission with consistent response formatting.
        
        Args:
            command_service: The command service instance
            robot_id: Target robot identifier
            command_type: Type of command to execute
            parameters: Command parameters
            priority: Command priority level
            timeout: Command timeout in seconds
            success_message: Success message to return
            
        Returns:
            Dictionary with status, command_id, and message
            
        Raises:
            HTTPException: If command submission fails
        """
        result = await command_service.submit_command(
            robot_id=robot_id,
            command_type=command_type,
            parameters=parameters or {},
            priority=priority,
            timeout=timeout
        )
        
        if not result.success:
            raise HTTPException(status_code=500, detail=result.error)
        
        return {
            "status": "success",
            "command_id": result.data,
            "message": success_message
        }


class ResponseHelper:
    """Helper functions for consistent response formatting."""
    
    @staticmethod
    def create_success_response(
        data: Any = None,
        message: str = "Operation completed successfully",
        **additional_fields
    ) -> Dict[str, Any]:
        """
        Standard success response formatting.
        
        Args:
            data: The response data
            message: Success message
            **additional_fields: Additional fields to include in response
            
        Returns:
            Dictionary with standardized success response format
        """
        response = {
            "status": "success",
            "message": message
        }
        
        if data is not None:
            response["data"] = data
        
        response.update(additional_fields)
        return response
    
    @staticmethod
    def create_error_response(
        error: str,
        error_code: str = "OPERATION_FAILED",
        **additional_fields
    ) -> Dict[str, Any]:
        """
        Standard error response formatting.
        
        Args:
            error: Error message
            error_code: Error code
            **additional_fields: Additional fields to include in response
            
        Returns:
            Dictionary with standardized error response format
        """
        response = {
            "status": "error",
            "error": error,
            "error_code": error_code
        }
        
        response.update(additional_fields)
        return response


class StateManagerHelper:
    """Helper functions for consistent state management patterns."""
    
    @staticmethod
    async def with_robot_state_management(
        state_manager: AtomicStateManager,
        robot_id: str,
        operation_func: Callable,
        operation_name: str
    ) -> Any:
        """
        Execute operation with automatic state management.
        
        Args:
            state_manager: The state manager instance
            robot_id: Target robot identifier
            operation_func: The operation function to execute
            operation_name: Name of the operation for logging
            
        Returns:
            The result from the operation function
            
        Raises:
            Exception: Any exception from the operation function
        """
        await state_manager.update_robot_state(
            robot_id,
            RobotState.BUSY,
            reason=f"Starting {operation_name}"
        )
        
        try:
            result = await operation_func()
            await state_manager.update_robot_state(
                robot_id,
                RobotState.IDLE,
                reason=f"Completed {operation_name}"
            )
            return result
        except Exception as e:
            await state_manager.update_robot_state(
                robot_id,
                RobotState.ERROR,
                reason=f"Failed {operation_name}: {str(e)}"
            )
            raise


class ServiceOperationHelper:
    """Helper functions for consistent service operation execution."""
    
    @staticmethod
    def create_operation_context(
        robot_id: str,
        operation_type: str,
        timeout: Optional[float] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> OperationContext:
        """
        Create a standardized operation context.
        
        Args:
            robot_id: Target robot identifier
            operation_type: Type of operation
            timeout: Operation timeout in seconds
            metadata: Additional metadata
            
        Returns:
            OperationContext instance
        """
        return OperationContext(
            operation_id=f"{robot_id}_{operation_type}_{int(time.time() * 1000)}",
            robot_id=robot_id,
            operation_type=operation_type,
            timeout=timeout,
            metadata=metadata or {}
        )


class HttpHelper:
    """Helper functions for consistent HTTP request handling."""
    
    @staticmethod
    def create_robot_headers(api_version: str = None) -> Dict[str, str]:
        """
        Create standard headers for robot API requests.
        
        Args:
            api_version: API version header value
            
        Returns:
            Dictionary of headers
        """
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
        
        if api_version:
            headers["Opentrons-Version"] = api_version
        
        return headers
    
    @staticmethod
    def handle_http_error(
        status_code: int,
        error_text: str,
        robot_id: Optional[str] = None
    ) -> HardwareError:
        """
        Create standardized HTTP error.
        
        Args:
            status_code: HTTP status code
            error_text: Error message text
            robot_id: Target robot identifier
            
        Returns:
            HardwareError instance
        """
        return HardwareError(
            f"HTTP error: {status_code} - {error_text}",
            robot_id=robot_id
        )


class HealthCheckHelper:
    """Helper functions for consistent health check patterns."""
    
    @staticmethod
    async def create_robot_health_check(
        robot_id: str,
        robot_type: str,
        state_manager: AtomicStateManager,
        base_health: Dict[str, Any],
        additional_checks: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Standard robot service health check with consistent format.
        
        Args:
            robot_id: Robot identifier
            robot_type: Type of robot
            state_manager: State manager instance
            base_health: Base health data from parent class
            additional_checks: Additional service-specific health data
            
        Returns:
            Dictionary with standardized health check format
        """
        robot_info = await state_manager.get_robot_state(robot_id)
        
        health_data = {
            **base_health,
            "robot_id": robot_id,
            "robot_type": robot_type,
            "robot_state": robot_info.current_state.value if robot_info else "unknown",
            "robot_operational": robot_info.is_operational if robot_info else False,
            "robot_uptime": robot_info.uptime_seconds if robot_info else 0,
            "robot_error_count": robot_info.error_count if robot_info else 0
        }
        
        if additional_checks:
            health_data.update(additional_checks)
        
        return health_data


class ValidationHelper:
    """Helper functions for consistent parameter validation."""
    
    @staticmethod
    def validate_required_parameter(
        param_name: str,
        param_value: Any,
        param_type: type = None
    ) -> None:
        """
        Validate that a required parameter is present and optionally of correct type.
        
        Args:
            param_name: Parameter name
            param_value: Parameter value
            param_type: Expected parameter type
            
        Raises:
            ValidationError: If validation fails
        """
        from core.exceptions import ValidationError
        
        if param_value is None:
            raise ValidationError(f"Required parameter missing: {param_name}")
        
        if param_type and not isinstance(param_value, param_type):
            raise ValidationError(
                f"Parameter {param_name} must be of type {param_type.__name__}"
            )
    
    @staticmethod
    def validate_parameter_range(
        param_name: str,
        param_value: Union[int, float],
        min_value: Optional[Union[int, float]] = None,
        max_value: Optional[Union[int, float]] = None
    ) -> None:
        """
        Validate that a parameter is within specified range.
        
        Args:
            param_name: Parameter name
            param_value: Parameter value
            min_value: Minimum allowed value
            max_value: Maximum allowed value
            
        Raises:
            ValidationError: If validation fails
        """
        from core.exceptions import ValidationError
        
        if min_value is not None and param_value < min_value:
            raise ValidationError(
                f"Parameter {param_name} must be >= {min_value}"
            )
        
        if max_value is not None and param_value > max_value:
            raise ValidationError(
                f"Parameter {param_name} must be <= {max_value}"
            )
    
    @staticmethod
    def validate_parameter_choices(
        param_name: str,
        param_value: Any,
        allowed_values: list
    ) -> None:
        """
        Validate that a parameter is one of allowed values.
        
        Args:
            param_name: Parameter name
            param_value: Parameter value
            allowed_values: List of allowed values
            
        Raises:
            ValidationError: If validation fails
        """
        from core.exceptions import ValidationError
        
        if param_value not in allowed_values:
            raise ValidationError(
                f"Parameter {param_name} must be one of: {allowed_values}"
            )