"""
Hardware connection manager for robust robot connections.
Provides centralized connection management, health monitoring, and recovery.
"""

import asyncio
import time
import logging
from typing import Dict, Optional, Any, Callable, Protocol
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum

from .exceptions import ConnectionError, HardwareError, ConfigurationError
from .circuit_breaker import CircuitBreaker, circuit_breaker_registry
from .state_manager import RobotState, AtomicStateManager
from .settings import RoboticsSettings
from utils.logger import get_logger


class ConnectionStatus(Enum):
    """Connection status enumeration"""
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    ERROR = "error"
    RECONNECTING = "reconnecting"


@dataclass
class ConnectionHealth:
    """Health information for a robot connection"""
    robot_id: str
    status: ConnectionStatus
    last_ping: Optional[float] = None
    ping_latency: Optional[float] = None
    connection_time: Optional[float] = None
    error_count: int = 0
    last_error: Optional[str] = None
    uptime_seconds: float = 0.0
    reconnect_attempts: int = 0
    
    @property
    def is_healthy(self) -> bool:
        """Check if connection is healthy"""
        return (
            self.status == ConnectionStatus.CONNECTED and
            self.last_ping is not None and
            time.time() - self.last_ping < self.settings.robot_status_check_interval
        )


class RobotDriver(Protocol):
    """Protocol defining the interface for robot drivers"""
    
    async def connect(self) -> bool:
        """Connect to the robot"""
        ...
    
    async def disconnect(self) -> bool:
        """Disconnect from the robot"""
        ...
    
    async def is_connected(self) -> bool:
        """Check if robot is connected"""
        ...
    
    async def ping(self) -> float:
        """Ping robot and return latency in seconds"""
        ...
    
    async def get_status(self) -> Dict[str, Any]:
        """Get robot status information"""
        ...
    
    async def emergency_stop(self) -> bool:
        """Emergency stop the robot"""
        ...


class BaseRobotDriver(ABC):
    """Base class for robot drivers with common functionality"""
    
    def __init__(self, robot_id: str, config: Dict[str, Any]):
        self.robot_id = robot_id
        self.config = config
        self.logger = get_logger("hardware_manager")
        self._connected = False
        self._last_ping = None
    
    @abstractmethod
    async def _connect_impl(self) -> bool:
        """Implementation-specific connection logic"""
        pass
    
    @abstractmethod
    async def _disconnect_impl(self) -> bool:
        """Implementation-specific disconnection logic"""
        pass
    
    @abstractmethod
    async def _ping_impl(self) -> float:
        """Implementation-specific ping logic"""
        pass
    
    @abstractmethod
    async def _get_status_impl(self) -> Dict[str, Any]:
        """Implementation-specific status logic"""
        pass
    
    @abstractmethod
    async def _emergency_stop_impl(self) -> bool:
        """Implementation-specific emergency stop logic"""
        pass
    
    async def connect(self) -> bool:
        """Connect to the robot with error handling"""
        try:
            result = await self._connect_impl()
            self._connected = result
            if result:
                self.logger.info(f"Successfully connected to {self.robot_id}")
            return result
        except Exception as e:
            self.logger.error(f"Failed to connect to {self.robot_id}: {e}")
            self._connected = False
            raise ConnectionError(f"Connection failed: {e}", robot_id=self.robot_id)
    
    async def disconnect(self) -> bool:
        """Disconnect from the robot with error handling"""
        try:
            result = await self._disconnect_impl()
            self._connected = False
            self.logger.info(f"Disconnected from {self.robot_id}")
            return result
        except Exception as e:
            self.logger.error(f"Error disconnecting from {self.robot_id}: {e}")
            self._connected = False
            return False
    
    async def is_connected(self) -> bool:
        """Check if robot is connected"""
        return self._connected
    
    async def ping(self) -> float:
        """Ping robot and return latency"""
        if not self._connected:
            raise ConnectionError(f"Robot {self.robot_id} not connected", robot_id=self.robot_id)
        
        start_time = time.time()
        try:
            latency = await self._ping_impl()
            self._last_ping = time.time()
            return latency
        except Exception as e:
            self.logger.warning(f"Ping failed for {self.robot_id}: {e}")
            raise ConnectionError(f"Ping failed: {e}", robot_id=self.robot_id)
    
    async def get_status(self) -> Dict[str, Any]:
        """Get robot status with error handling"""
        if not self._connected:
            raise ConnectionError(f"Robot {self.robot_id} not connected", robot_id=self.robot_id)
        
        try:
            status = await self._get_status_impl()
            return {
                "robot_id": self.robot_id,
                "connected": self._connected,
                "last_ping": self._last_ping,
                **status
            }
        except Exception as e:
            self.logger.error(f"Failed to get status for {self.robot_id}: {e}")
            raise HardwareError(f"Status check failed: {e}", robot_id=self.robot_id)
    
    async def emergency_stop(self) -> bool:
        """Emergency stop with error handling"""
        try:
            result = await self._emergency_stop_impl()
            self.logger.critical(f"Emergency stop executed for {self.robot_id}")
            return result
        except Exception as e:
            self.logger.error(f"Emergency stop failed for {self.robot_id}: {e}")
            raise HardwareError(f"Emergency stop failed: {e}", robot_id=self.robot_id)


class HardwareConnectionManager:
    """
    Manages connections to all robots with health monitoring and recovery.
    
    Provides centralized connection management, automatic reconnection,
    health monitoring, and circuit breaker protection.
    """
    
    def __init__(
        self,
        settings: RoboticsSettings,
        state_manager: AtomicStateManager
    ):
        self.settings = settings
        self.state_manager = state_manager
        
        # Connection tracking
        self._drivers: Dict[str, BaseRobotDriver] = {}
        self._health: Dict[str, ConnectionHealth] = {}
        self._circuit_breakers: Dict[str, CircuitBreaker] = {}
        
        # Monitoring tasks
        self._monitoring_task: Optional[asyncio.Task] = None
        self._reconnect_tasks: Dict[str, asyncio.Task] = {}
        self._running = False
        
        # Configuration
        self.health_check_interval = settings.health_check_interval
        self.max_reconnect_attempts = 5
        self.reconnect_base_delay = 1.0
        self.reconnect_max_delay = 60.0
        
        self.logger = get_logger("hardware_manager")
    
    async def start(self):
        """Start the hardware connection manager"""
        if self._running:
            return
        
        self._running = True
        
        # Start monitoring task
        self._monitoring_task = asyncio.create_task(self._monitor_connections())
        
        self.logger.info("HardwareConnectionManager started")
    
    async def stop(self):
        """Stop the hardware connection manager"""
        if not self._running:
            return
        
        self._running = False
        
        # Cancel monitoring task
        if self._monitoring_task:
            self._monitoring_task.cancel()
            try:
                await self._monitoring_task
            except asyncio.CancelledError:
                pass
        
        # Cancel reconnect tasks
        for task in self._reconnect_tasks.values():
            task.cancel()
        
        if self._reconnect_tasks:
            await asyncio.gather(*self._reconnect_tasks.values(), return_exceptions=True)
        
        # Disconnect all robots
        for driver in self._drivers.values():
            try:
                await driver.disconnect()
            except Exception as e:
                self.logger.error(f"Error disconnecting robot: {e}")
        
        self.logger.info("HardwareConnectionManager stopped")
    
    def register_robot_driver(self, robot_id: str, driver: BaseRobotDriver):
        """Register a robot driver"""
        self._drivers[robot_id] = driver
        self._health[robot_id] = ConnectionHealth(
            robot_id=robot_id,
            status=ConnectionStatus.DISCONNECTED
        )
        
        # Create circuit breaker for this robot
        breaker_config = self.settings.get_circuit_breaker_config()
        circuit_breaker = CircuitBreaker(
            name=f"robot_{robot_id}",
            failure_threshold=breaker_config["failure_threshold"],
            recovery_timeout=breaker_config["recovery_timeout"],
            expected_exception=ConnectionError
        )
        self._circuit_breakers[robot_id] = circuit_breaker
        circuit_breaker_registry.register(circuit_breaker)
        
        self.logger.info(f"Registered robot driver: {robot_id}")
    
    async def connect_robot(self, robot_id: str, timeout: float = 30.0) -> bool:
        """
        Connect to a specific robot with circuit breaker protection.
        
        Args:
            robot_id: Robot identifier
            timeout: Connection timeout in seconds
            
        Returns:
            True if connected successfully
        """
        if robot_id not in self._drivers:
            self.logger.error(f"Connection failed: Robot {robot_id} not registered")
            raise ConfigurationError(f"Robot {robot_id} not registered")
        
        driver = self._drivers[robot_id]
        health = self._health[robot_id]
        circuit_breaker = self._circuit_breakers[robot_id]
        
        # Log connection attempt details
        self.logger.info(f"Attempting connection to robot {robot_id} (timeout: {timeout}s)")
        self.logger.debug(f"Robot {robot_id} config: IP={driver.config.get('ip', 'unknown')}, Port={driver.config.get('port', 'unknown')}")
        self.logger.debug(f"Circuit breaker status for {robot_id}: {circuit_breaker.get_status()}")
        
        # Update state to connecting
        health.status = ConnectionStatus.CONNECTING
        await self.state_manager.update_robot_state(
            robot_id, RobotState.CONNECTING, reason="Connection attempt"
        )
        
        connection_start_time = time.time()
        
        try:
            # Use circuit breaker protection
            self.logger.debug(f"Starting TCP connection to robot {robot_id}")
            result = await asyncio.wait_for(
                circuit_breaker.call(driver.connect),
                timeout=timeout
            )
            
            connection_duration = time.time() - connection_start_time
            
            if result:
                health.status = ConnectionStatus.CONNECTED
                health.connection_time = time.time()
                health.error_count = 0
                health.reconnect_attempts = 0
                
                await self.state_manager.update_robot_state(
                    robot_id, RobotState.IDLE, reason="Connected successfully"
                )
                
                self.logger.info(f"Robot {robot_id} connected successfully in {connection_duration:.2f}s")
                return True
            else:
                self.logger.warning(f"Robot {robot_id} connection returned False after {connection_duration:.2f}s")
                await self._handle_connection_failure(robot_id, "Connection returned False")
                return False
                
        except asyncio.TimeoutError:
            connection_duration = time.time() - connection_start_time
            error_msg = f"Connection timeout ({timeout}s) after {connection_duration:.2f}s"
            self.logger.error(f"Robot {robot_id} TCP connection timeout: {error_msg}")
            await self._handle_connection_failure(robot_id, error_msg)
            return False
        except Exception as e:
            connection_duration = time.time() - connection_start_time
            error_msg = f"TCP connection error after {connection_duration:.2f}s: {str(e)}"
            self.logger.error(f"Robot {robot_id} connection failed: {error_msg}")
            await self._handle_connection_failure(robot_id, str(e))
            return False
    
    async def disconnect_robot(self, robot_id: str) -> bool:
        """Disconnect from a specific robot"""
        if robot_id not in self._drivers:
            return False
        
        driver = self._drivers[robot_id]
        health = self._health[robot_id]
        
        # Cancel any reconnect task
        if robot_id in self._reconnect_tasks:
            self._reconnect_tasks[robot_id].cancel()
            del self._reconnect_tasks[robot_id]
        
        try:
            result = await driver.disconnect()
            health.status = ConnectionStatus.DISCONNECTED
            health.connection_time = None
            
            await self.state_manager.update_robot_state(
                robot_id, RobotState.DISCONNECTED, reason="Disconnected"
            )
            
            return result
        except Exception as e:
            self.logger.error(f"Error disconnecting robot {robot_id}: {e}")
            return False
    
    async def get_robot_status(self, robot_id: str) -> Optional[Dict[str, Any]]:
        """Get status of a specific robot"""
        if robot_id not in self._drivers:
            return None
        
        driver = self._drivers[robot_id]
        health = self._health[robot_id]
        circuit_breaker = self._circuit_breakers[robot_id]
        
        try:
            if health.status == ConnectionStatus.CONNECTED:
                status = await circuit_breaker.call(driver.get_status)
            else:
                status = {"connected": False}
            
            return {
                **status,
                "health": {
                    "status": health.status.value,
                    "last_ping": health.last_ping,
                    "ping_latency": health.ping_latency,
                    "uptime_seconds": health.uptime_seconds,
                    "error_count": health.error_count,
                    "reconnect_attempts": health.reconnect_attempts,
                    "is_healthy": health.is_healthy
                },
                "circuit_breaker": circuit_breaker.get_status()
            }
        except Exception as e:
            self.logger.error(f"Error getting status for robot {robot_id}: {e}")
            return {"error": str(e), "connected": False}
    
    async def get_all_robot_status(self) -> Dict[str, Dict[str, Any]]:
        """Get status of all robots"""
        status = {}
        for robot_id in self._drivers:
            status[robot_id] = await self.get_robot_status(robot_id)
        return status
    
    async def emergency_stop_robot(self, robot_id: str) -> bool:
        """Emergency stop a specific robot"""
        if robot_id not in self._drivers:
            return False
        
        driver = self._drivers[robot_id]
        
        try:
            result = await driver.emergency_stop()
            await self.state_manager.update_robot_state(
                robot_id, RobotState.EMERGENCY_STOP, reason="Emergency stop triggered"
            )
            return result
        except Exception as e:
            self.logger.error(f"Emergency stop failed for robot {robot_id}: {e}")
            return False
    
    async def emergency_stop_all(self) -> Dict[str, bool]:
        """Emergency stop all robots"""
        results = {}
        for robot_id in self._drivers:
            results[robot_id] = await self.emergency_stop_robot(robot_id)
        
        # Update system state
        await self.state_manager.update_system_state(
            self.state_manager.SystemState.ERROR,
            reason="Emergency stop all robots"
        )
        
        return results
    
    async def _handle_connection_failure(self, robot_id: str, error_message: str):
        """Handle connection failure and update state"""
        health = self._health[robot_id]
        previous_status = health.status
        health.status = ConnectionStatus.ERROR
        health.error_count += 1
        health.last_error = error_message
        
        self.logger.error(f"Connection failure for robot {robot_id}: {error_message}")
        self.logger.error(f"Robot {robot_id} error count: {health.error_count}, previous status: {previous_status.value}")
        
        await self.state_manager.update_robot_state(
            robot_id, RobotState.ERROR, reason=f"Connection failed: {error_message}"
        )
        
        # Start automatic reconnection if enabled
        if robot_id not in self._reconnect_tasks:
            self.logger.info(f"Starting auto-reconnection task for robot {robot_id}")
            self._reconnect_tasks[robot_id] = asyncio.create_task(
                self._auto_reconnect(robot_id)
            )
        else:
            self.logger.debug(f"Auto-reconnection task already running for robot {robot_id}")
    
    async def _auto_reconnect(self, robot_id: str):
        """Automatically attempt to reconnect to a robot"""
        health = self._health[robot_id]
        
        self.logger.info(f"Starting auto-reconnection sequence for robot {robot_id}")
        
        for attempt in range(1, self.max_reconnect_attempts + 1):
            if not self._running:
                self.logger.info(f"Auto-reconnection cancelled for robot {robot_id} (service stopping)")
                break
            
            health.reconnect_attempts = attempt
            health.status = ConnectionStatus.RECONNECTING
            
            # Exponential backoff
            delay = min(
                self.reconnect_base_delay * (2 ** (attempt - 1)),
                self.reconnect_max_delay
            )
            
            self.logger.info(
                f"Auto-reconnection attempt {attempt}/{self.max_reconnect_attempts} "
                f"for robot {robot_id} starting in {delay:.1f}s"
            )
            
            await asyncio.sleep(delay)
            
            reconnect_start_time = time.time()
            try:
                self.logger.info(f"Executing reconnection attempt {attempt} for robot {robot_id}")
                if await self.connect_robot(robot_id):
                    reconnect_duration = time.time() - reconnect_start_time
                    self.logger.info(f"Robot {robot_id} auto-reconnected successfully on attempt {attempt} in {reconnect_duration:.2f}s")
                    break
            except Exception as e:
                reconnect_duration = time.time() - reconnect_start_time
                self.logger.warning(f"Auto-reconnection attempt {attempt} failed for {robot_id} after {reconnect_duration:.2f}s: {e}")
        else:
            self.logger.error(f"Auto-reconnection failed for robot {robot_id} after {self.max_reconnect_attempts} attempts")
        
        # Clean up task reference
        if robot_id in self._reconnect_tasks:
            del self._reconnect_tasks[robot_id]
            self.logger.debug(f"Auto-reconnection task cleaned up for robot {robot_id}")
    
    async def _monitor_connections(self):
        """Background task to monitor connection health"""
        while self._running:
            try:
                await self._check_all_connections()
                await asyncio.sleep(self.health_check_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(f"Error in connection monitoring: {e}")
                await asyncio.sleep(self.health_check_interval)
    
    async def _check_all_connections(self):
        """Check health of all connections"""
        for robot_id, driver in self._drivers.items():
            health = self._health[robot_id]
            
            if health.status == ConnectionStatus.CONNECTED:
                try:
                    # Ping the robot
                    ping_start_time = time.time()
                    self.logger.debug(f"Starting ping check for robot {robot_id}")
                    
                    latency = await driver.ping()
                    ping_duration = time.time() - ping_start_time
                    
                    health.last_ping = time.time()
                    health.ping_latency = latency
                    
                    # Update uptime
                    if health.connection_time:
                        health.uptime_seconds = time.time() - health.connection_time
                    
                    self.logger.debug(f"Robot {robot_id} ping successful: {latency:.3f}s latency, {ping_duration:.3f}s total")
                    
                except Exception as e:
                    ping_duration = time.time() - ping_start_time
                    error_msg = f"Ping failed after {ping_duration:.3f}s: {str(e)}"
                    self.logger.warning(f"Health check failed for robot {robot_id}: {error_msg}")
                    await self._handle_connection_failure(robot_id, f"Health check failed: {e}")
    
    def get_connection_statistics(self) -> Dict[str, Any]:
        """Get connection statistics"""
        stats = {
            "total_robots": len(self._drivers),
            "connected_robots": 0,
            "error_robots": 0,
            "reconnecting_robots": 0,
            "circuit_breakers": {}
        }
        
        for robot_id, health in self._health.items():
            if health.status == ConnectionStatus.CONNECTED:
                stats["connected_robots"] += 1
            elif health.status == ConnectionStatus.ERROR:
                stats["error_robots"] += 1
            elif health.status == ConnectionStatus.RECONNECTING:
                stats["reconnecting_robots"] += 1
            
            # Add circuit breaker stats
            if robot_id in self._circuit_breakers:
                stats["circuit_breakers"][robot_id] = self._circuit_breakers[robot_id].get_status()
        
        return stats