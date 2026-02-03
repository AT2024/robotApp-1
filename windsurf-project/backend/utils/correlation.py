"""
Correlation ID system for tracing operations across services.

Provides context-based correlation tracking to trace operations end-to-end,
making it easy to follow a wafer through the entire processing pipeline.

Usage:
    from utils.correlation import start_operation, get_correlation_id, clear_context

    # Start a new operation context
    start_operation("pickup", wafer_id=3, robot_id="meca")

    # All subsequent logs will include the correlation ID
    logger.info("Processing wafer")  # Includes correlation_id automatically

    # Clear context when done
    clear_context()
"""

import uuid
import logging
from contextvars import ContextVar
from typing import Optional, Dict, Any
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class CorrelationContext:
    """Context data for correlation tracking."""
    correlation_id: str
    operation_type: str
    wafer_id: Optional[int] = None
    robot_id: Optional[str] = None
    started_at: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)


# Thread-local context variable for correlation data
_correlation_context: ContextVar[Optional[CorrelationContext]] = ContextVar(
    'correlation_context', default=None
)


def generate_correlation_id(operation_type: str) -> str:
    """
    Generate a unique correlation ID for an operation.

    Format: {operation_type}-{short_uuid}
    Example: pickup-abc12345

    Args:
        operation_type: Type of operation (pickup, drop, carousel, etc.)

    Returns:
        Unique correlation ID string
    """
    short_uuid = uuid.uuid4().hex[:8]
    return f"{operation_type}-{short_uuid}"


def start_operation(
    operation_type: str,
    wafer_id: Optional[int] = None,
    robot_id: Optional[str] = None,
    correlation_id: Optional[str] = None,
    **metadata
) -> str:
    """
    Start a new correlation context for an operation.

    This sets up the context that will be automatically added to all
    subsequent log messages until clear_context() is called.

    Args:
        operation_type: Type of operation (pickup, drop, carousel, etc.)
        wafer_id: Optional wafer being processed
        robot_id: Optional robot performing the operation
        correlation_id: Optional existing correlation ID (for chained operations)
        **metadata: Additional metadata to include in logs

    Returns:
        The correlation ID for this operation
    """
    if correlation_id is None:
        correlation_id = generate_correlation_id(operation_type)

    context = CorrelationContext(
        correlation_id=correlation_id,
        operation_type=operation_type,
        wafer_id=wafer_id,
        robot_id=robot_id,
        metadata=metadata
    )

    _correlation_context.set(context)
    return correlation_id


def get_correlation_id() -> Optional[str]:
    """
    Get the current correlation ID.

    Returns:
        Current correlation ID or None if no context is active
    """
    context = _correlation_context.get()
    return context.correlation_id if context else None


def get_context() -> Optional[CorrelationContext]:
    """
    Get the full correlation context.

    Returns:
        Current CorrelationContext or None if no context is active
    """
    return _correlation_context.get()


def update_context(
    wafer_id: Optional[int] = None,
    robot_id: Optional[str] = None,
    **metadata
) -> None:
    """
    Update the current correlation context with additional data.

    Useful for adding information as an operation progresses.

    Args:
        wafer_id: Update wafer ID
        robot_id: Update robot ID
        **metadata: Additional metadata to merge
    """
    context = _correlation_context.get()
    if context:
        if wafer_id is not None:
            context.wafer_id = wafer_id
        if robot_id is not None:
            context.robot_id = robot_id
        context.metadata.update(metadata)


def clear_context() -> None:
    """
    Clear the current correlation context.

    Call this when an operation completes to ensure
    subsequent logs don't carry stale correlation data.
    """
    _correlation_context.set(None)


class CorrelationFilter(logging.Filter):
    """
    Logging filter that automatically adds correlation context to log records.

    Add this filter to loggers to automatically include correlation_id,
    wafer_id, and robot_id in all log messages when a context is active.

    Usage:
        logger = logging.getLogger("my_logger")
        logger.addFilter(CorrelationFilter())
    """

    def filter(self, record: logging.LogRecord) -> bool:
        """
        Add correlation context to the log record.

        Args:
            record: The log record to modify

        Returns:
            True (always allows the record through)
        """
        context = _correlation_context.get()

        if context:
            record.correlation_id = context.correlation_id
            record.wafer_id = context.wafer_id
            record.robot_id = context.robot_id
            record.operation_type = context.operation_type
        else:
            # Set defaults so StructuredFormatter doesn't fail
            record.correlation_id = None
            record.wafer_id = None
            record.robot_id = None
            record.operation_type = None

        return True


def add_correlation_filter(logger: logging.Logger) -> None:
    """
    Add the CorrelationFilter to a logger.

    Convenience function to add correlation tracking to an existing logger.

    Args:
        logger: The logger to add the filter to
    """
    # Check if filter already added
    for f in logger.filters:
        if isinstance(f, CorrelationFilter):
            return

    logger.addFilter(CorrelationFilter())
