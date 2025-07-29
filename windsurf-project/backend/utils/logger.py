"""
Logging configuration module.
"""
import logging
import sys
from datetime import datetime
import os
from logging.handlers import RotatingFileHandler

def get_logger(name: str) -> logging.Logger:
    """
    Create and configure a logger instance with component-specific organization.
    
    Args:
        name (str): Name of the logger (e.g., "meca_service", "ot2_router")

    Returns:
        logging.Logger: Configured logger instance
    """
    # Create logger
    logger = logging.getLogger(name)
    
    if not logger.handlers:  # Only add handlers if they don't exist
        # Get environment setting for log level
        env_log_level = os.getenv('ROBOTICS_LOG_LEVEL', 'INFO').upper()
        is_production = os.getenv('ROBOTICS_ENV', 'development').lower() == 'production'
        
        # Set logger level based on environment
        if is_production:
            logger.setLevel(logging.ERROR)
            file_log_level = logging.ERROR
            console_log_level = logging.ERROR
        else:
            logger.setLevel(logging.DEBUG)
            file_log_level = logging.INFO
            console_log_level = logging.INFO

        # Create logs directory if it doesn't exist
        logs_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'logs')
        os.makedirs(logs_dir, exist_ok=True)

        # Determine component-specific log file name
        component_name = _get_component_name(name)
        log_file = os.path.join(logs_dir, f'{component_name}_{datetime.now().strftime("%Y%m%d")}.log')
        
        # Rotating file handler (10MB max, keep 5 files)
        file_handler = RotatingFileHandler(
            log_file, 
            maxBytes=10*1024*1024,  # 10MB
            backupCount=5
        )
        file_handler.setLevel(file_log_level)

        # Console handler
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(console_log_level)

        # Create formatters
        file_formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s'
        )
        console_formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        
        file_handler.setFormatter(file_formatter)
        console_handler.setFormatter(console_formatter)

        # Add handlers to the logger
        logger.addHandler(file_handler)
        logger.addHandler(console_handler)

    return logger


def _get_component_name(logger_name: str) -> str:
    """
    Map logger names to component-specific log files.
    
    Args:
        logger_name (str): The logger name
        
    Returns:
        str: Component name for log file
    """
    # Map logger names to component categories
    component_mapping = {
        # Mecademic robot components
        'meca_router': 'meca',
        'meca_service': 'meca',
        
        # OT2 robot components
        'ot2_router': 'ot2',
        'ot2_service': 'ot2',
        'protocol_service': 'ot2',
        
        # Arduino components
        'arduino_router': 'arduino',
        'arduino_service': 'arduino',
        
        # WebSocket components
        'websocket_handler': 'websocket',
        'connection_manager': 'websocket',
        'selective_broadcaster': 'websocket',
        
        # Database components
        'repositories': 'database',
        'init_db': 'database',
        
        # Core infrastructure
        'state_manager': 'core',
        'circuit_breaker': 'core',
        'hardware_manager': 'core',
        'resource_lock': 'core',
        'async_robot_wrapper': 'core',
        'cache_manager': 'core',
        'connection_pool': 'core',
        
        # Services
        'orchestrator': 'services',
        'command_service': 'services',
        'base': 'services',
        
        # System components
        'main': 'system',
        'robot_manager': 'system',
        
        # Other components
        'wiper_router': 'wiper',
        'wiper_service': 'wiper',
        'wiper_driver': 'wiper',
        'logs': 'system',
        'helpers': 'system',
    }
    
    return component_mapping.get(logger_name, 'general')
