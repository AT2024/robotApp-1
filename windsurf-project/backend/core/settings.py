"""
Centralized configuration management using Pydantic Settings.
Provides environment-specific configuration with validation and type safety.
"""

import os
import json
from typing import Optional, List, Dict, Any
from pydantic import BaseSettings, Field, validator, root_validator
from enum import Enum
import logging


class Environment(str, Enum):
    """Environment types"""

    DEVELOPMENT = "development"
    TESTING = "testing"
    STAGING = "staging"
    PRODUCTION = "production"


class LogLevel(str, Enum):
    """Logging levels"""

    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class RoboticsSettings(BaseSettings):
    """
    Centralized configuration for the robotics control system.

    Uses Pydantic Settings for type validation, environment variable support,
    and configuration file loading.
    """

    # Environment
    environment: Environment = Field(default=Environment.DEVELOPMENT)
    debug: bool = Field(default=False)

    # Server configuration
    host: str = Field(default="0.0.0.0")
    port: int = Field(default=8000, ge=1024, le=65535)
    workers: int = Field(default=1, ge=1)

    # Logging
    log_level: LogLevel = Field(default=LogLevel.INFO)
    log_file: Optional[str] = Field(default=None)
    log_rotation: str = Field(default="1 day")
    log_retention: str = Field(default="30 days")
    
    # Debug logging for robot operations
    enable_debug_logging: bool = Field(default=False, description="Enable detailed debug logging for robot operations")

    # Database
    database_url: str = Field(default="sqlite+aiosqlite:///./robotics.db")
    database_echo: bool = Field(default=False)
    database_pool_size: int = Field(default=10, ge=1)
    database_max_overflow: int = Field(default=20, ge=0)

    # Meca Robot Configuration
    meca_enabled: bool = Field(default=True)
    meca_ip: str  # Required field from environment - no default to enforce explicit configuration
    meca_port: int = Field(default=10000, ge=1, le=65535)
    meca_timeout: float = Field(default=30.0, gt=0)
    meca_retry_attempts: int = Field(default=3, ge=1)
    meca_retry_delay: float = Field(default=1.0, gt=0)

    # Meca Movement Parameters (from legacy Meca_FullCode.py)
    meca_force: float = Field(default=100.0, gt=0)  # Gripper force
    meca_acceleration: float = Field(default=50.0, gt=0)  # ACC - acceleration percentage
    meca_speed: float = Field(default=35.0, gt=0)  # SPEED - general speed
    meca_wafer_speed: float = Field(default=35.0, gt=0)  # WAFER_SPEED - speed when carrying wafer
    meca_empty_speed: float = Field(default=50.0, gt=0)  # EMPTY_SPEED - speed when empty
    meca_align_speed: float = Field(default=20.0, gt=0)  # ALIGN_SPEED - speed when aligning
    meca_entry_speed: float = Field(default=15.0, gt=0)  # ENTRY_SPEED - carousel entry speed
    meca_close_width: float = Field(default=1.0, gt=0)  # CLOSE_WIDTH - gripper close width
    meca_spread_wait: float = Field(default=2.0, gt=0)  # SPREAD_WAIT - spreading wait time
    meca_gap_wafers: float = Field(default=2.7, gt=0)  # GAP_WAFERS - distance between wafers
    
    # Meca Position Coordinates (JSON format: [x, y, z, alpha, beta, gamma])
    meca_first_wafer: str = Field(default="[173.562, -175.178, 27.9714, 109.5547, 0.2877, -90.059]")
    meca_first_baking: str = Field(default="[-141.6702, -170.5871, 27.9420, -178.2908, -69.0556, 1.7626]")
    meca_carousel: str = Field(default="[133.8, -247.95, 101.9, 90.0, 0.0, -90.0]")
    meca_safe_point: str = Field(default="[135.0, -17.6177, 160.0, 123.2804, 40.9554, -101.3308]")
    meca_carousel_safe: str = Field(default="[25.567, -202.630, 179.700, 90.546, 0.866, -90.882]")
    meca_t_photogate: str = Field(default="[53.8, -217.2, 94.9, 90.0, 0.0, -90.0]")
    meca_c_photogate: str = Field(default="[84.1, -217.2, 94.9, 90.0, 0.0, -90.0]")
    meca_gen_drop_positions: str = Field(default="[[130.2207, 159.230, 123.400, 179.7538, -0.4298, -89.9617], [85.5707, 159.4300, 123.400, 179.7538, -0.4298, -89.6617], [41.0207, 159.4300, 123.400, 179.7538, -0.4298, -89.6617], [-3.5793, 159.3300, 123.400, 179.7538, -0.4298, -89.6617], [-47.9793, 159.2300, 123.400, 179.7538, -0.4298, -89.6617]]")

    # OT2 Robot Configuration
    ot2_enabled: bool = Field(default=True)
    ot2_ip: str = Field(default="169.254.49.202")
    ot2_port: int = Field(default=31950, ge=1, le=65535)
    ot2_timeout: float = Field(default=30.0, gt=0)  # Reduced from 60s for faster startup
    ot2_retry_attempts: int = Field(default=3, ge=1)
    ot2_retry_delay: float = Field(default=1.0, gt=0)  # Reduced from 2s for faster retries
    
    # OT2 HTTP Configuration
    ot2_http_total_timeout: float = Field(default=30.0, gt=0)  # Total timeout for HTTP requests
    ot2_http_connect_timeout: float = Field(default=10.0, gt=0)  # Connection timeout
    ot2_http_connector_limit: int = Field(default=10, ge=1)  # TCP connector limit
    ot2_api_version: str = Field(default="2")  # Opentrons API version
    
    # OT2 Protocol Configuration
    ot2_protocol_directory: str = Field(default="protocols/")  # Default protocol directory
    ot2_default_protocol_file: str = Field(default="ot2Protocole.py")  # Default protocol filename
    ot2_protocol_execution_timeout: float = Field(default=3600.0, gt=0)  # 1 hour for protocol execution
    ot2_protocol_monitoring_interval: float = Field(default=2.0, gt=0)  # Status monitoring interval
    
    # OT2 Protocol Runtime Parameters (configurable via environment variables)
    ot2_num_generators: int = Field(default=5, ge=1, le=20)  # Number of generators
    ot2_radioactive_vol: float = Field(default=6.6, gt=0)  # Radioactive volume in µL
    ot2_sds_vol: float = Field(default=1.0, gt=0)  # SDS volume in µL  
    ot2_cur: int = Field(default=2, ge=1)  # Current setting
    ot2_tip_location: str = Field(default="1")  # Tip location
    ot2_tray_number: int = Field(default=1, ge=1)  # Tray number
    ot2_vial_number: int = Field(default=1, ge=1)  # Vial number
    
    # OT2 Protocol Coordinate Parameters (JSON strings for complex data)
    ot2_sds_location: str = Field(default="[287.0, 226.0, 40.0]")  # SDS location coordinates
    ot2_generators_locations: str = Field(default="[[4.0, 93.0, 133.0], [4.0, 138.0, 133.0], [4.0, 183.0, 133.0], [4.0, 228.0, 133.0], [4.0, 273.0, 133.0]]")  # Generator positions
    ot2_home_location: str = Field(default="[350.0, 350.0, 147.0]")  # Home position
    ot2_temp_location: str = Field(default="[8.0, 350.0, 147.0]")  # Temporary position
    ot2_height_home_location: str = Field(default="[302.0, 302.0, 147.0]")  # High home position
    ot2_height_temp_location: str = Field(default="[8.0, 228.0, 147.0]")  # High temp position
    ot2_radioactive_location: str = Field(default="[354.0, 225.0, 40.0]")  # Radioactive/thorium location

    # Arduino Configuration
    arduino_enabled: bool = Field(default=True)
    arduino_port: str = Field(default="/dev/ttyUSB0")
    arduino_baudrate: int = Field(default=9600, gt=0)
    arduino_timeout: float = Field(default=5.0, gt=0)

    # Wiper 6-55 Configuration
    wiper_enabled: bool = Field(default=True)
    wiper_ip: str = Field(default="192.168.0.200")
    wiper_port: int = Field(default=8080, ge=1, le=65535)
    wiper_timeout: float = Field(default=30.0, gt=0)
    wiper_retry_attempts: int = Field(default=3, ge=1)
    wiper_retry_delay: float = Field(default=2.0, gt=0)
    wiper_cleaning_cycles: int = Field(default=3, ge=1, le=10)
    wiper_dry_time: float = Field(default=30.0, gt=0)  # seconds
    wiper_speed: str = Field(default="normal")  # slow, normal, fast

    # Circuit Breaker Configuration
    circuit_breaker_failure_threshold: int = Field(default=5, ge=1)
    circuit_breaker_recovery_timeout: float = Field(default=60.0, gt=0)
    circuit_breaker_half_open_max_calls: int = Field(default=3, ge=1)

    # Resource Lock Configuration
    resource_lock_default_timeout: float = Field(default=30.0, gt=0)
    resource_lock_cleanup_interval: float = Field(default=60.0, gt=0)
    resource_lock_max_lease_duration: float = Field(default=300.0, gt=0)

    # State Manager Configuration
    state_manager_max_history: int = Field(default=1000, ge=100)
    state_manager_cleanup_interval: float = Field(default=300.0, gt=0)

    # WebSocket Configuration
    websocket_ping_interval: float = Field(default=20.0, gt=0)
    websocket_ping_timeout: float = Field(default=10.0, gt=0)
    websocket_max_connections: int = Field(default=100, ge=1)

    # Protocol Execution
    protocol_execution_timeout: float = Field(default=3600.0, gt=0)  # 1 hour
    protocol_max_retries: int = Field(default=2, ge=0)
    protocols_directory: str = Field(default="protocols/")
    max_concurrent_robot_commands: int = Field(default=5, ge=1)

    # Safety Configuration
    emergency_stop_timeout: float = Field(default=5.0, gt=0)
    operation_timeout: float = Field(default=300.0, gt=0)  # 5 minutes
    connection_timeout: float = Field(default=30.0, gt=0)  # General connection timeout

    # Monitoring and Health Checks
    health_check_interval: float = Field(default=30.0, gt=0)
    robot_status_check_interval: float = Field(default=5.0, gt=0)

    # CORS Configuration
    cors_origins: List[str] = Field(
        default=[
            "http://localhost:3000",
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://127.0.0.1:3000",
        ]
    )
    cors_allow_credentials: bool = Field(default=True)
    cors_allow_methods: List[str] = Field(default=["*"])
    cors_allow_headers: List[str] = Field(default=["*"])

    # Security
    secret_key: str = Field(default="your-secret-key-here-change-in-production")
    access_token_expire_minutes: int = Field(default=30, ge=1)

    # Development features
    auto_reload: bool = Field(default=False)
    profiling_enabled: bool = Field(default=False)

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False

        # Environment variable prefix
        env_prefix = "ROBOTICS_"

        # Field aliases for backward compatibility
        fields = {
            "database_url": {"env": ["DATABASE_URL", "ROBOTICS_DATABASE_URL"]},
            "secret_key": {"env": ["SECRET_KEY", "ROBOTICS_SECRET_KEY"]},
        }

    @validator("environment", pre=True)
    def validate_environment(cls, v):
        """Validate environment value"""
        if isinstance(v, str):
            return v.lower()
        return v

    @validator("log_level", pre=True)
    def validate_log_level(cls, v):
        """Validate log level value"""
        if isinstance(v, str):
            return v.upper()
        return v

    @validator("meca_ip", "ot2_ip")
    def validate_ip_address(cls, v):
        """Validate IP address format"""
        import ipaddress

        try:
            ipaddress.ip_address(v)
            return v
        except ValueError:
            raise ValueError(f"Invalid IP address: {v}")

    @validator("database_url")
    def validate_database_url(cls, v):
        """Validate database URL format"""
        if not v.startswith(("sqlite", "postgresql", "mysql")):
            raise ValueError(
                "Database URL must start with sqlite, postgresql, or mysql"
            )
        return v

    @root_validator
    def validate_production_settings(cls, values):
        """Validate production-specific settings"""
        environment = values.get("environment")
        if environment == Environment.PRODUCTION:
            # Ensure security settings are properly configured
            if values.get("secret_key") == "your-secret-key-here-change-in-production":
                raise ValueError("Secret key must be changed in production")

            if values.get("debug", False):
                raise ValueError("Debug mode must be disabled in production")

            # Ensure proper database configuration for production
            db_url = values.get("database_url", "")
            if db_url.startswith("sqlite"):
                raise ValueError("SQLite should not be used in production")

        return values
    
    def _parse_position_json(self, position_str: str) -> List[float]:
        """Parse position coordinates from JSON string format"""
        try:
            parsed = json.loads(position_str)
            if isinstance(parsed, list):
                return parsed
            else:
                raise ValueError(f"Position data must be a list, got {type(parsed)}")
        except (json.JSONDecodeError, ValueError) as e:
            logger = logging.getLogger(__name__)
            logger.warning(f"Failed to parse position JSON '{position_str}': {e}")
            # Return empty list as fallback
            return []

    def get_robot_config(self, robot_type: str) -> Dict[str, Any]:
        """Get configuration for a specific robot type"""
        configs = {
            "meca": {
                "enabled": self.meca_enabled,
                "ip": self.meca_ip,
                "port": self.meca_port,
                "timeout": self.meca_timeout,
                "retry_attempts": self.meca_retry_attempts,
                "retry_delay": self.meca_retry_delay,
                "movement_params": {
                    "force": self.meca_force,
                    "acceleration": self.meca_acceleration,
                    "speed": self.meca_speed,
                    "wafer_speed": self.meca_wafer_speed,
                    "empty_speed": self.meca_empty_speed,
                    "align_speed": self.meca_align_speed,
                    "entry_speed": self.meca_entry_speed,
                    "close_width": self.meca_close_width,
                    "spread_wait": self.meca_spread_wait,
                    "gap_wafers": self.meca_gap_wafers,
                },
                "positions": {
                    "first_wafer": self._parse_position_json(self.meca_first_wafer),
                    "first_baking": self._parse_position_json(self.meca_first_baking),
                    "carousel": self._parse_position_json(self.meca_carousel),
                    "safe_point": self._parse_position_json(self.meca_safe_point),
                    "carousel_safe": self._parse_position_json(self.meca_carousel_safe),
                    "t_photogate": self._parse_position_json(self.meca_t_photogate),
                    "c_photogate": self._parse_position_json(self.meca_c_photogate),
                    "gen_drop": self._parse_position_json(self.meca_gen_drop_positions)
                },
            },
            "ot2": {
                "enabled": self.ot2_enabled,
                "ip": self.ot2_ip,
                "port": self.ot2_port,
                "timeout": self.ot2_timeout,
                "retry_attempts": self.ot2_retry_attempts,
                "retry_delay": self.ot2_retry_delay,
                "http_config": {
                    "total_timeout": self.ot2_http_total_timeout,
                    "connect_timeout": self.ot2_http_connect_timeout,
                    "connector_limit": self.ot2_http_connector_limit,
                    "api_version": self.ot2_api_version,
                },
                "protocol_config": {
                    "directory": self.ot2_protocol_directory,
                    "default_file": self.ot2_default_protocol_file,
                    "execution_timeout": self.ot2_protocol_execution_timeout,
                    "monitoring_interval": self.ot2_protocol_monitoring_interval,
                },
                "protocol_parameters": {
                    "NUM_OF_GENERATORS": self.ot2_num_generators,
                    "radioactive_VOL": self.ot2_radioactive_vol,
                    "SDS_VOL": self.ot2_sds_vol,
                    "CUR": self.ot2_cur,
                    "tip_location": self.ot2_tip_location,
                    "trayNumber": self.ot2_tray_number,
                    "vialNumber": self.ot2_vial_number,
                    "sds_lct": self._parse_position_json(self.ot2_sds_location),
                    "generators_locations": self._parse_position_json(self.ot2_generators_locations),
                    "home_lct": self._parse_position_json(self.ot2_home_location),
                    "temp_lct": self._parse_position_json(self.ot2_temp_location),
                    "hight_home_lct": self._parse_position_json(self.ot2_height_home_location),
                    "hight_temp_lct": self._parse_position_json(self.ot2_height_temp_location),
                    "radioactive_lct": self._parse_position_json(self.ot2_radioactive_location),
                    "thorium_lct": self._parse_position_json(self.ot2_radioactive_location),  # Alias for compatibility
                },
            },
            "arduino": {
                "enabled": self.arduino_enabled,
                "port": self.arduino_port,
                "baudrate": self.arduino_baudrate,
                "timeout": self.arduino_timeout,
            },
            "wiper": {
                "enabled": self.wiper_enabled,
                "ip": self.wiper_ip,
                "port": self.wiper_port,
                "timeout": self.wiper_timeout,
                "retry_attempts": self.wiper_retry_attempts,
                "retry_delay": self.wiper_retry_delay,
                "cleaning_params": {
                    "cycles": self.wiper_cleaning_cycles,
                    "dry_time": self.wiper_dry_time,
                    "speed": self.wiper_speed,
                },
            },
        }

        return configs.get(robot_type, {})

    def get_circuit_breaker_config(self) -> Dict[str, Any]:
        """Get circuit breaker configuration"""
        return {
            "failure_threshold": self.circuit_breaker_failure_threshold,
            "recovery_timeout": self.circuit_breaker_recovery_timeout,
            "half_open_max_calls": self.circuit_breaker_half_open_max_calls,
        }

    def get_resource_lock_config(self) -> Dict[str, Any]:
        """Get resource lock configuration"""
        return {
            "default_timeout": self.resource_lock_default_timeout,
            "cleanup_interval": self.resource_lock_cleanup_interval,
            "max_lease_duration": self.resource_lock_max_lease_duration,
        }

    def is_development(self) -> bool:
        """Check if running in development mode"""
        return self.environment == Environment.DEVELOPMENT

    def is_production(self) -> bool:
        """Check if running in production mode"""
        return self.environment == Environment.PRODUCTION

    def is_testing(self) -> bool:
        """Check if running in testing mode"""
        return self.environment == Environment.TESTING

    def get_log_config(self) -> Dict[str, Any]:
        """Get logging configuration"""
        return {
            "level": self.log_level.value,
            "file": self.log_file,
            "rotation": self.log_rotation,
            "retention": self.log_retention,
        }

    def get_cors_config(self) -> Dict[str, Any]:
        """Get CORS configuration"""
        return {
            "allow_origins": self.cors_origins,
            "allow_credentials": self.cors_allow_credentials,
            "allow_methods": self.cors_allow_methods,
            "allow_headers": self.cors_allow_headers,
        }


# Global settings instance
settings: Optional[RoboticsSettings] = None


def get_settings() -> RoboticsSettings:
    """
    Get the global settings instance.
    Creates the instance if it doesn't exist.
    """
    global settings
    if settings is None:
        settings = RoboticsSettings()
    return settings


def reload_settings() -> RoboticsSettings:
    """
    Reload settings from environment and config files.
    Useful for testing or configuration updates.
    """
    global settings
    settings = RoboticsSettings()
    return settings


# Convenience function for FastAPI dependency injection
def get_settings_dependency() -> RoboticsSettings:
    """FastAPI dependency for injecting settings"""
    return get_settings()
