"""
Dependency Injection Configuration for the Robotics Control System.
Provides centralized dependency management for all services and components.
"""

import asyncio
from typing import Dict, Any, Optional
from functools import lru_cache

from fastapi import Depends

from core.settings import RoboticsSettings
from core.state_manager import AtomicStateManager, RobotState
from core.resource_lock import ResourceLockManager
from core.hardware_manager import HardwareConnectionManager
from core.circuit_breaker import CircuitBreakerRegistry
from core.async_robot_wrapper import AsyncRobotWrapper
from drivers.mecademic_driver import MecademicDriverFactory
from core.cache_manager import get_cache_manager, get_robot_cache
from core.connection_pool import (
    get_pool_manager,
    get_or_create_pool,
    ConnectionPoolType,
)
from websocket.selective_broadcaster import get_broadcaster

from services.orchestrator import RobotOrchestrator
from services.meca_service import MecaService
from services.ot2_service import OT2Service
from services.protocol_service import ProtocolExecutionService
from services.command_service import RobotCommandService


class DependencyContainer:
    """
    Central container for all application dependencies.
    Implements singleton pattern to ensure single instances.
    """

    def __init__(self):
        self._settings: Optional[RoboticsSettings] = None
        self._state_manager: Optional[AtomicStateManager] = None
        self._lock_manager: Optional[ResourceLockManager] = None
        self._hardware_manager: Optional[HardwareConnectionManager] = None
        self._circuit_breaker_registry: Optional[CircuitBreakerRegistry] = None

        # Performance optimization components
        self._cache_manager: Optional[Any] = None
        self._robot_cache: Optional[Any] = None
        self._connection_pool_manager: Optional[Any] = None
        self._broadcaster: Optional[Any] = None

        # Services
        self._orchestrator: Optional[RobotOrchestrator] = None
        self._meca_service: Optional[MecaService] = None
        self._ot2_service: Optional[OT2Service] = None
        self._protocol_service: Optional[ProtocolExecutionService] = None
        self._command_service: Optional[RobotCommandService] = None

        # Service registry
        self._robot_services: Dict[str, Any] = {}

        # Initialization state
        self._initialized = False
        self._init_lock = asyncio.Lock()

    async def initialize(self):
        """Initialize all dependencies in correct order"""
        async with self._init_lock:
            if self._initialized:
                return

            # Step 1: Initialize core infrastructure
            await self._init_core_infrastructure()

            # Step 2: Initialize services
            await self._init_services()

            # Step 3: Register services with orchestrator
            await self._register_services()

            # Step 4: Start all services
            await self._start_services()

            self._initialized = True

    async def _init_core_infrastructure(self):
        """Initialize core infrastructure components"""
        # Settings
        self._settings = RoboticsSettings()

        # State manager
        self._state_manager = AtomicStateManager()

        # Resource lock manager
        self._lock_manager = ResourceLockManager()

        # Circuit breaker registry
        self._circuit_breaker_registry = CircuitBreakerRegistry()

        # Hardware manager
        self._hardware_manager = HardwareConnectionManager(
            self._settings, self._state_manager
        )

        # Performance optimization components
        self._cache_manager = await get_cache_manager()
        self._robot_cache = await get_robot_cache()
        self._connection_pool_manager = await get_pool_manager()
        self._broadcaster = await get_broadcaster()

        # Initialize connection pools for robots
        if self._settings.ot2_ip:
            await get_or_create_pool(
                ConnectionPoolType.OT2_API,
                f"http://{self._settings.ot2_ip}:{self._settings.ot2_port}",
            )

    async def _init_services(self):
        """Initialize all services"""
        # Robot orchestrator
        self._orchestrator = RobotOrchestrator(
            self._settings,
            self._state_manager,
            self._lock_manager,
            self._hardware_manager,
        )

        # Initialize robot services with proper error handling
        try:
            self._ot2_service = OT2Service(
                robot_id="ot2",
                settings=self._settings,
                state_manager=self._state_manager,
                lock_manager=self._lock_manager,
            )
        except Exception as e:
            print(f"Warning: Failed to initialize OT2 service: {e}")
            self._ot2_service = None

        # Initialize Meca service with proper robot driver
        try:
            # Create Mecademic driver
            meca_driver = MecademicDriverFactory.create_driver("meca", self._settings)

            # Create async wrapper for the driver
            meca_wrapper = AsyncRobotWrapper(
                robot_id="meca",
                robot_driver=meca_driver,
                max_workers=4,
                command_timeout=self._settings.meca_timeout,
                batch_size=10,
                batch_timeout=0.1,
            )

            # Create MecaService
            self._meca_service = MecaService(
                robot_id="meca",
                settings=self._settings,
                state_manager=self._state_manager,
                lock_manager=self._lock_manager,
                async_wrapper=meca_wrapper,
            )

            # Register the driver with hardware manager
            self._hardware_manager.register_robot_driver("meca", meca_driver)

        except Exception as e:
            print(f"Warning: Failed to initialize Meca service: {e}")
            self._meca_service = None

        # Register robot services FIRST (only if initialized)
        self._robot_services = {}
        if self._meca_service:
            self._robot_services["meca"] = self._meca_service
        if self._ot2_service:
            self._robot_services["ot2"] = self._ot2_service

        # Protocol execution service
        self._protocol_service = ProtocolExecutionService(
            self._settings, self._state_manager, self._lock_manager, self._orchestrator
        )
        #print(f"*** DEPENDENCIES DEBUG: Created protocol service: {self._protocol_service}")
        #print(f"*** DEPENDENCIES DEBUG: Protocol service type: {type(self._protocol_service)}")

        # Command service - create AFTER robot services are in registry
        self._command_service = RobotCommandService(
            self._settings, self._state_manager, self._lock_manager, self._orchestrator
        )

    async def _register_services(self):
        """Register services with orchestrator"""
        print(f"*** DEPENDENCIES DEBUG: Starting service registration")
        print(f"*** DEPENDENCIES DEBUG: Orchestrator before registration: {self._orchestrator}")
        print(f"*** DEPENDENCIES DEBUG: Protocol service to register: {self._protocol_service}")
        
        # Register robot services
        for robot_id, service in self._robot_services.items():
            self._orchestrator.register_robot_service(robot_id, service)
            print(f"*** DEPENDENCIES DEBUG: Registered robot service {robot_id}: {service}")

        # Register other services
        print(f"*** DEPENDENCIES DEBUG: Registering protocol service...")
        self._orchestrator.register_protocol_service(self._protocol_service)
        print(f"*** DEPENDENCIES DEBUG: Protocol service registered. Orchestrator._protocol_service: {getattr(self._orchestrator, '_protocol_service', 'NOT_FOUND')}")

    async def _start_services(self):
        """Start all services"""
        # Start orchestrator (which starts registered services)
        await self._orchestrator.start()

        # Start command service
        await self._command_service.start()

    async def shutdown(self):
        """Shutdown all dependencies in reverse order"""
        if not self._initialized:
            return

        # Stop services
        if self._command_service:
            await self._command_service.stop()

        if self._orchestrator:
            await self._orchestrator.stop()

        # Shutdown performance optimization components
        if self._cache_manager:
            from core.cache_manager import shutdown_cache

            await shutdown_cache()

        if self._connection_pool_manager:
            from core.connection_pool import shutdown_pools

            await shutdown_pools()

        if self._broadcaster:
            from websocket.selective_broadcaster import shutdown_broadcaster

            await shutdown_broadcaster()

        # Shutdown core infrastructure
        if self._hardware_manager:
            await self._hardware_manager.stop()

        # Note: state_manager and lock_manager don't require explicit shutdown

        self._initialized = False

    # Dependency getters
    def get_settings(self) -> RoboticsSettings:
        if not self._settings:
            raise RuntimeError("Settings not initialized")
        return self._settings

    def get_state_manager(self) -> AtomicStateManager:
        if not self._state_manager:
            raise RuntimeError("State manager not initialized")
        return self._state_manager

    def get_lock_manager(self) -> ResourceLockManager:
        if not self._lock_manager:
            raise RuntimeError("Lock manager not initialized")
        return self._lock_manager

    def get_hardware_manager(self) -> HardwareConnectionManager:
        if not self._hardware_manager:
            raise RuntimeError("Hardware manager not initialized")
        return self._hardware_manager

    def get_orchestrator(self) -> RobotOrchestrator:
        if not self._orchestrator:
            raise RuntimeError("Orchestrator not initialized")
        return self._orchestrator

    def get_meca_service(self) -> Optional[MecaService]:
        return self._meca_service

    def get_ot2_service(self) -> Optional[OT2Service]:
        return self._ot2_service

    def get_protocol_service(self) -> ProtocolExecutionService:
        if not self._protocol_service:
            raise RuntimeError("Protocol service not initialized")
        return self._protocol_service

    def get_command_service(self) -> RobotCommandService:
        if not self._command_service:
            raise RuntimeError("Command service not initialized")
        return self._command_service

    def get_robot_service(self, robot_id: str):
        """Get robot service by ID"""
        return self._robot_services.get(robot_id)

    def list_robot_services(self) -> Dict[str, Any]:
        """List all robot services"""
        return self._robot_services.copy()

    def get_cache_manager(self):
        """Get cache manager instance"""
        return self._cache_manager

    def get_robot_cache(self):
        """Get robot cache instance"""
        return self._robot_cache

    def get_connection_pool_manager(self):
        """Get connection pool manager instance"""
        return self._connection_pool_manager

    def get_broadcaster(self):
        """Get selective broadcaster instance"""
        return self._broadcaster


# Global dependency container instance
_container: Optional[DependencyContainer] = None


async def get_container() -> DependencyContainer:
    """Get the global dependency container"""
    global _container
    if _container is None:
        _container = DependencyContainer()
        await _container.initialize()
    return _container


# FastAPI dependency functions
@lru_cache()
def get_settings() -> RoboticsSettings:
    """FastAPI dependency to get settings"""
    # For FastAPI dependencies, we need to handle this differently
    # since we can't use async in dependency functions
    if _container is None:
        # Return a basic settings instance for now
        return RoboticsSettings()
    return _container.get_settings()


async def get_state_manager() -> AtomicStateManager:
    """FastAPI dependency to get state manager"""
    container = await get_container()
    return container.get_state_manager()


async def get_lock_manager() -> ResourceLockManager:
    """FastAPI dependency to get lock manager"""
    container = await get_container()
    return container.get_lock_manager()


async def get_hardware_manager() -> HardwareConnectionManager:
    """FastAPI dependency to get hardware manager"""
    container = await get_container()
    return container.get_hardware_manager()


async def get_orchestrator() -> RobotOrchestrator:
    """FastAPI dependency to get orchestrator"""
    container = await get_container()
    return container.get_orchestrator()


async def get_meca_service() -> Optional[MecaService]:
    """FastAPI dependency to get Meca service"""
    container = await get_container()
    return container.get_meca_service()


async def get_ot2_service() -> Optional[OT2Service]:
    """FastAPI dependency to get OT2 service"""
    container = await get_container()
    return container.get_ot2_service()


async def get_protocol_service() -> ProtocolExecutionService:
    """FastAPI dependency to get protocol service"""
    container = await get_container()
    return container.get_protocol_service()


async def get_command_service() -> RobotCommandService:
    """FastAPI dependency to get command service"""
    container = await get_container()
    return container.get_command_service()


# Convenience functions for getting specific robot services
async def get_robot_service_by_id(robot_id: str):
    """FastAPI dependency to get robot service by ID"""
    container = await get_container()
    service = container.get_robot_service(robot_id)
    if not service:
        raise ValueError(f"Robot service not found: {robot_id}")
    return service


def MecaServiceDep():
    """FastAPI dependency function for Meca service"""
    return Depends(get_meca_service)


def OT2ServiceDep():
    """FastAPI dependency function for OT2 service"""
    return Depends(get_ot2_service)


def OrchestratorDep():
    """FastAPI dependency function for orchestrator"""
    return Depends(get_orchestrator)


def ProtocolServiceDep():
    """FastAPI dependency function for protocol service"""
    return Depends(get_protocol_service)


def CommandServiceDep():
    """FastAPI dependency function for command service"""
    return Depends(get_command_service)


def StateManagerDep():
    """FastAPI dependency function for state manager"""
    return Depends(get_state_manager)


def LockManagerDep():
    """FastAPI dependency function for lock manager"""
    return Depends(get_lock_manager)


def HardwareManagerDep():
    """FastAPI dependency function for hardware manager"""
    return Depends(get_hardware_manager)


# Application lifecycle management
async def startup_dependencies():
    """Initialize dependencies at application startup"""
    await get_container()


async def shutdown_dependencies():
    """Cleanup dependencies at application shutdown"""
    global _container
    if _container:
        await _container.shutdown()
        _container = None


# Health check functions
async def check_dependencies_health() -> Dict[str, Any]:
    """Check health of all dependencies"""
    if not _container or not _container._initialized:
        return {"status": "not_initialized", "healthy": False}

    health_info = {"status": "initialized", "healthy": True, "components": {}}

    try:
        # Check orchestrator health
        orchestrator_health = await _container._orchestrator.health_check()
        health_info["components"]["orchestrator"] = orchestrator_health

        # Check service health
        if _container._command_service:
            command_health = await _container._command_service.health_check()
            health_info["components"]["command_service"] = command_health

        if _container._protocol_service:
            protocol_health = await _container._protocol_service.health_check()
            health_info["components"]["protocol_service"] = protocol_health

        # Check robot services
        robot_health = {}
        for robot_id, service in _container._robot_services.items():
            try:
                service_health = await service.health_check()
                robot_health[robot_id] = service_health
            except Exception as e:
                robot_health[robot_id] = {"healthy": False, "error": str(e)}

        health_info["components"]["robot_services"] = robot_health

        # Check if any component is unhealthy
        def is_component_healthy(component):
            if isinstance(component, dict):
                if "healthy" in component:
                    return component["healthy"]
                # Recursively check nested components
                return all(is_component_healthy(v) for v in component.values())
            return True

        health_info["healthy"] = is_component_healthy(health_info["components"])

    except Exception as e:
        health_info["healthy"] = False
        health_info["error"] = str(e)

    return health_info


# Configuration validation
def validate_dependencies_config() -> Dict[str, Any]:
    """Validate dependency configuration"""
    try:
        settings = RoboticsSettings()

        validation_results = {
            "valid": True,
            "settings": {
                "meca_ip": settings.meca_ip,
                "ot2_ip": settings.ot2_ip,
                "database_url": settings.database_url,
                "redis_url": (
                    settings.redis_url
                    if hasattr(settings, "redis_url")
                    else "not_configured"
                ),
            },
            "issues": [],
        }

        # Check for potential issues
        # Note: Removed hardcoded IP comparisons - all config should come from runtime.json

        return validation_results

    except Exception as e:
        return {"valid": False, "error": str(e), "issues": ["Failed to load settings"]}


# Export main functions for external use
__all__ = [
    "get_container",
    "startup_dependencies",
    "shutdown_dependencies",
    "check_dependencies_health",
    "validate_dependencies_config",
    "get_settings",
    "MecaServiceDep",
    "OT2ServiceDep",
    "OrchestratorDep",
    "ProtocolServiceDep",
    "CommandServiceDep",
    "StateManagerDep",
    "LockManagerDep",
    "HardwareManagerDep",
]