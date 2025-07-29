"""
Configuration API router for exposing robot and system configuration to frontend.
Provides REST endpoints for getting and updating configuration parameters.
"""

from typing import Dict, Any
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from core.settings import RoboticsSettings, get_settings

router = APIRouter(
    prefix="/config",
    tags=["configuration"],
    responses={404: {"description": "Configuration not found"}},
)


class ConfigUpdate(BaseModel):
    """Request model for configuration updates"""
    key: str
    value: Any


@router.get("/", response_model=Dict[str, Any])
async def get_all_config(settings: RoboticsSettings = Depends(get_settings)):
    """
    Get complete system configuration including all robot configs.
    Returns all available configuration parameters for the frontend.
    """
    try:
        return {
            "system": {
                "environment": settings.environment.value,
                "debug": settings.debug,
                "log_level": settings.log_level.value,
                "host": settings.host,
                "port": settings.port,
            },
            "robots": {
                "meca": settings.get_robot_config("meca"),
                "ot2": settings.get_robot_config("ot2"),
                "arduino": settings.get_robot_config("arduino"),
                "wiper": settings.get_robot_config("wiper"),
            },
            "circuit_breaker": settings.get_circuit_breaker_config(),
            "resource_locks": settings.get_resource_lock_config(),
            "websocket": {
                "ping_interval": settings.websocket_ping_interval,
                "ping_timeout": settings.websocket_ping_timeout,
                "max_connections": settings.websocket_max_connections,
            },
            "protocols": {
                "execution_timeout": settings.protocol_execution_timeout,
                "max_retries": settings.protocol_max_retries,
                "directory": settings.protocols_directory,
            },
            "safety": {
                "emergency_stop_timeout": settings.emergency_stop_timeout,
                "operation_timeout": settings.operation_timeout,
                "connection_timeout": settings.connection_timeout,
            },
            "monitoring": {
                "health_check_interval": settings.health_check_interval,
                "robot_status_check_interval": settings.robot_status_check_interval,
            },
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get configuration: {str(e)}")


@router.get("/robots", response_model=Dict[str, Any])
async def get_robot_configs(settings: RoboticsSettings = Depends(get_settings)):
    """
    Get all robot configurations (Meca, OT2, Arduino, Wiper).
    Focused endpoint for robot-specific configuration data.
    """
    try:
        return {
            "meca": settings.get_robot_config("meca"),
            "ot2": settings.get_robot_config("ot2"),
            "arduino": settings.get_robot_config("arduino"),
            "wiper": settings.get_robot_config("wiper"),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get robot configurations: {str(e)}")


@router.get("/robots/{robot_type}", response_model=Dict[str, Any])
async def get_robot_config(robot_type: str, settings: RoboticsSettings = Depends(get_settings)):
    """
    Get configuration for a specific robot type.
    
    Args:
        robot_type: One of 'meca', 'ot2', 'arduino', 'wiper'
    """
    valid_robots = ["meca", "ot2", "arduino", "wiper"]
    if robot_type not in valid_robots:
        raise HTTPException(
            status_code=404, 
            detail=f"Robot type '{robot_type}' not found. Valid types: {valid_robots}"
        )
    
    try:
        config = settings.get_robot_config(robot_type)
        if not config:
            raise HTTPException(
                status_code=404, 
                detail=f"Configuration for robot type '{robot_type}' not found"
            )
        return config
    except Exception as e:
        raise HTTPException(
            status_code=500, 
            detail=f"Failed to get {robot_type} configuration: {str(e)}"
        )


@router.get("/system", response_model=Dict[str, Any])
async def get_system_config(settings: RoboticsSettings = Depends(get_settings)):
    """
    Get system-level configuration (environment, logging, server settings).
    """
    try:
        return {
            "environment": settings.environment.value,
            "debug": settings.debug,
            "log_level": settings.log_level.value,
            "host": settings.host,
            "port": settings.port,
            "database_url": settings.database_url,
            "database_echo": settings.database_echo,
            "secret_key": "***HIDDEN***",  # Never expose secret key
            "cors_origins": settings.cors_origins,
            "cors_allow_credentials": settings.cors_allow_credentials,
            "auto_reload": settings.auto_reload,
            "profiling_enabled": settings.profiling_enabled,
            "log_config": settings.get_log_config(),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get system configuration: {str(e)}")


@router.get("/summary", response_model=Dict[str, Any])
async def get_config_summary(settings: RoboticsSettings = Depends(get_settings)):
    """
    Get a summary of key configuration parameters for dashboard display.
    Lightweight endpoint with essential information only.
    """
    try:
        return {
            "environment": settings.environment.value,
            "robots_enabled": {
                "meca": settings.meca_enabled,
                "ot2": settings.ot2_enabled,
                "arduino": settings.arduino_enabled,
                "wiper": settings.wiper_enabled,
            },
            "robot_endpoints": {
                "meca": f"{settings.meca_ip}:{settings.meca_port}",
                "ot2": f"{settings.ot2_ip}:{settings.ot2_port}",
                "arduino": settings.arduino_port,
                "wiper": f"{settings.wiper_ip}:{settings.wiper_port}",
            },
            "safety": {
                "emergency_stop_timeout": settings.emergency_stop_timeout,
                "operation_timeout": settings.operation_timeout,
            },
            "circuit_breaker": {
                "failure_threshold": settings.circuit_breaker_failure_threshold,
                "recovery_timeout": settings.circuit_breaker_recovery_timeout,
            },
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get configuration summary: {str(e)}")