"""
Logging configuration module.
Provides centralized logging with timezone support, log consolidation, and automatic cleanup.

Logging Strategy:
- Daily rotation at midnight (TimedRotatingFileHandler)
- 30-day retention with automatic cleanup
- Three log categories: app.log, robot.log, error.log
- Backup files named: app.2026-01-29.log, etc.
- Optional JSON structured logging for machine-parseable output
"""
import logging
import sys
import os
import glob
import time
import json
from datetime import datetime
from logging.handlers import TimedRotatingFileHandler
from typing import Optional, Dict, Any

# Try to import zoneinfo (Python 3.9+), fallback to pytz
try:
    from zoneinfo import ZoneInfo
except ImportError:
    try:
        from pytz import timezone as ZoneInfo
    except ImportError:
        ZoneInfo = None


class TimezoneFormatter(logging.Formatter):
    """
    Custom formatter that uses a specified timezone for timestamps.
    Defaults to Asia/Jerusalem if no timezone specified.
    """

    def __init__(self, fmt: str, datefmt: Optional[str] = None, timezone: str = "Asia/Jerusalem"):
        super().__init__(fmt, datefmt)
        self.timezone_name = timezone
        self._tz = None

        if ZoneInfo is not None:
            try:
                self._tz = ZoneInfo(timezone)
            except Exception:
                # Fallback if timezone not found
                self._tz = None

    def formatTime(self, record: logging.LogRecord, datefmt: Optional[str] = None) -> str:
        """Format time with the specified timezone."""
        # Convert timestamp to datetime
        ct = datetime.fromtimestamp(record.created)

        if self._tz is not None:
            try:
                # Convert to specified timezone
                ct = datetime.fromtimestamp(record.created, tz=self._tz)
            except Exception:
                pass  # Use local time if timezone conversion fails

        if datefmt:
            return ct.strftime(datefmt)
        else:
            # Default format with milliseconds
            return ct.strftime("%Y-%m-%d %H:%M:%S") + f",{int(record.msecs):03d}"


class StructuredFormatter(logging.Formatter):
    """
    JSON structured formatter for machine-parseable log output.

    Outputs logs in JSON format:
    {
        "timestamp": "2026-01-29T10:15:32.123",
        "level": "INFO",
        "logger": "meca_service",
        "message": "Pickup completed",
        "func": "execute_pickup",
        "line": 123,
        "correlation_id": "pickup-abc123",
        "wafer_id": 3,
        "robot_id": "meca"
    }

    Extra fields from log records (correlation_id, wafer_id, robot_id)
    are automatically included in the JSON output.
    """

    def __init__(self, timezone: str = "Asia/Jerusalem"):
        super().__init__()
        self.timezone_name = timezone
        self._tz = None

        if ZoneInfo is not None:
            try:
                self._tz = ZoneInfo(timezone)
            except Exception:
                self._tz = None

    def _get_timestamp(self, record: logging.LogRecord) -> str:
        """Get ISO8601 formatted timestamp with timezone."""
        ct = datetime.fromtimestamp(record.created)

        if self._tz is not None:
            try:
                ct = datetime.fromtimestamp(record.created, tz=self._tz)
            except Exception:
                pass

        # ISO8601 format with milliseconds
        return ct.strftime("%Y-%m-%dT%H:%M:%S") + f".{int(record.msecs):03d}"

    def format(self, record: logging.LogRecord) -> str:
        """Format the log record as JSON."""
        # Base log entry
        log_entry: Dict[str, Any] = {
            "timestamp": self._get_timestamp(record),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "func": record.funcName,
            "line": record.lineno,
        }

        # Add extra fields from CorrelationFilter or manual extras
        # These are added to the record by filters or logger.info("msg", extra={...})
        extra_fields = ["correlation_id", "wafer_id", "robot_id", "operation_type"]
        for field in extra_fields:
            value = getattr(record, field, None)
            if value is not None:
                log_entry[field] = value

        # Include exception info if present
        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_entry, default=str)


def _get_component_category(logger_name: str) -> str:
    """
    Map logger names to consolidated log file categories.

    Categories:
    - robot: All robot-related logs (meca, ot2, arduino, drivers)
    - app: Application logs (services, websocket, core infrastructure)
    - error: Errors only (separate file for easy monitoring)

    Args:
        logger_name: The logger name

    Returns:
        Category name: 'robot', 'app', or 'general'
    """
    # Robot components -> robot.log
    robot_patterns = [
        'meca', 'ot2', 'arduino', 'wiper', 'carousel',
        'mecademic', 'opentrons', 'driver'
    ]

    # Check if any robot pattern matches
    name_lower = logger_name.lower()
    for pattern in robot_patterns:
        if pattern in name_lower:
            return 'robot'

    # Everything else goes to app.log
    return 'app'


def get_logger(name: str) -> logging.Logger:
    """
    Create and configure a logger instance with consolidated file organization.

    Log files:
    - app.log: Application logs (services, websocket, core)
    - robot.log: Robot-related logs (meca, ot2, arduino, drivers)
    - error.log: ERROR and CRITICAL level logs only

    Args:
        name (str): Name of the logger (e.g., "meca_service", "ot2_router")

    Returns:
        logging.Logger: Configured logger instance
    """
    # Create logger
    logger = logging.getLogger(name)

    if not logger.handlers:  # Only add handlers if they don't exist
        # Get environment settings
        env_log_level = os.getenv('ROBOTICS_LOG_LEVEL', 'INFO').upper()
        is_production = os.getenv('ROBOTICS_ENV', 'development').lower() == 'production'
        timezone = os.getenv('ROBOTICS_TIMEZONE', 'Asia/Jerusalem')
        log_format = os.getenv('ROBOTICS_LOG_FORMAT', 'text').lower()  # 'text' or 'json'

        # Set logger level based on environment
        log_level_map = {
            'DEBUG': logging.DEBUG,
            'INFO': logging.INFO,
            'WARNING': logging.WARNING,
            'ERROR': logging.ERROR,
            'CRITICAL': logging.CRITICAL
        }

        if is_production:
            logger.setLevel(logging.ERROR)
            file_log_level = logging.ERROR
            console_log_level = logging.ERROR
        else:
            desired_level = log_level_map.get(env_log_level, logging.INFO)
            logger.setLevel(desired_level)
            file_log_level = desired_level
            console_log_level = desired_level

        # Create logs directory if it doesn't exist
        logs_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'logs')
        os.makedirs(logs_dir, exist_ok=True)

        # Determine consolidated log file (no date suffix)
        category = _get_component_category(name)
        log_file = os.path.join(logs_dir, f'{category}.log')
        error_log_file = os.path.join(logs_dir, 'error.log')

        # Create formatters based on log format setting
        if log_format == 'json':
            # JSON structured logging for machine-parseable output
            file_formatter = StructuredFormatter(timezone=timezone)
            console_formatter = StructuredFormatter(timezone=timezone)
        else:
            # Default text format with timezone support
            file_formatter = TimezoneFormatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s',
                timezone=timezone
            )
            console_formatter = TimezoneFormatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                timezone=timezone
            )

        # Main file handler (daily rotation at midnight, keep 30 days)
        file_handler = TimedRotatingFileHandler(
            log_file,
            when='midnight',
            interval=1,
            backupCount=30,  # Keep 30 days of logs
            encoding='utf-8'
        )
        file_handler.suffix = '%Y-%m-%d'  # Produces: app.log.2026-01-29
        file_handler.setLevel(file_log_level)
        file_handler.setFormatter(file_formatter)
        logger.addHandler(file_handler)

        # Error-only file handler (daily rotation, keep 30 days)
        error_handler = TimedRotatingFileHandler(
            error_log_file,
            when='midnight',
            interval=1,
            backupCount=30,  # Keep 30 days of logs
            encoding='utf-8'
        )
        error_handler.suffix = '%Y-%m-%d'  # Produces: error.log.2026-01-29
        error_handler.setLevel(logging.ERROR)
        error_handler.setFormatter(file_formatter)
        logger.addHandler(error_handler)

        # Console handler
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(console_log_level)
        console_handler.setFormatter(console_formatter)
        logger.addHandler(console_handler)

        # Add correlation filter for automatic context tracking
        from utils.correlation import CorrelationFilter
        logger.addFilter(CorrelationFilter())

    return logger


def cleanup_old_logs(logs_dir: Optional[str] = None, max_age_days: int = 30) -> int:
    """
    Remove old log files that exceed the maximum age.

    Called automatically on application startup to clean legacy files
    and maintain 30-day retention policy.

    Args:
        logs_dir: Directory containing log files. Defaults to backend/logs.
        max_age_days: Maximum age in days for log files. Default 30 days.

    Returns:
        Number of files removed
    """
    if logs_dir is None:
        logs_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'logs')

    if not os.path.exists(logs_dir):
        return 0

    removed_count = 0
    cutoff_time = time.time() - (max_age_days * 24 * 60 * 60)

    # Find all log files including rotated ones (*.log, *.log.1, *.log.2, etc.)
    log_patterns = [
        os.path.join(logs_dir, '*.log'),
        os.path.join(logs_dir, '*.log.*'),
    ]

    for pattern in log_patterns:
        for log_file in glob.glob(pattern):
            try:
                file_mtime = os.path.getmtime(log_file)
                if file_mtime < cutoff_time:
                    os.remove(log_file)
                    removed_count += 1
            except OSError:
                pass  # File might be in use or already deleted

    # Also clean up old date-suffixed files from previous logging system
    old_date_pattern = os.path.join(logs_dir, '*_[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9].log')
    for log_file in glob.glob(old_date_pattern):
        try:
            file_mtime = os.path.getmtime(log_file)
            if file_mtime < cutoff_time:
                os.remove(log_file)
                removed_count += 1
        except OSError:
            pass

    return removed_count
