"""
Logging configuration module.
Provides centralized logging with timezone support, log consolidation, and automatic cleanup.
"""
import logging
import sys
import os
import glob
import time
from datetime import datetime
from logging.handlers import RotatingFileHandler
from typing import Optional

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

        # Create timezone-aware formatters
        file_formatter = TimezoneFormatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s',
            timezone=timezone
        )
        console_formatter = TimezoneFormatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            timezone=timezone
        )

        # Main file handler (10MB max, keep 5 files)
        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=10*1024*1024,  # 10MB
            backupCount=5
        )
        file_handler.setLevel(file_log_level)
        file_handler.setFormatter(file_formatter)
        logger.addHandler(file_handler)

        # Error-only file handler (always captures ERROR and CRITICAL)
        error_handler = RotatingFileHandler(
            error_log_file,
            maxBytes=10*1024*1024,  # 10MB
            backupCount=5
        )
        error_handler.setLevel(logging.ERROR)
        error_handler.setFormatter(file_formatter)
        logger.addHandler(error_handler)

        # Console handler
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(console_log_level)
        console_handler.setFormatter(console_formatter)
        logger.addHandler(console_handler)

    return logger


def cleanup_old_logs(logs_dir: Optional[str] = None, max_age_days: int = 7) -> int:
    """
    Remove old log files that exceed the maximum age.

    Args:
        logs_dir: Directory containing log files. Defaults to backend/logs.
        max_age_days: Maximum age in days for log files. Default 7 days.

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
