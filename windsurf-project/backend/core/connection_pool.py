"""
HTTP connection pool manager for optimized API calls.
Provides connection pooling, retry logic, and performance monitoring.
"""

import asyncio
import time
from typing import Dict, Any, Optional, List, Union
from dataclasses import dataclass, field
from enum import Enum
import logging

import aiohttp
from aiohttp import ClientTimeout, TCPConnector, ClientSession
from core.circuit_breaker import CircuitBreaker
from core.exceptions import ConnectionError, HardwareError


class ConnectionPoolType(Enum):
    """Types of connection pools"""
    OT2_API = "ot2_api"
    ROBOT_TELEMETRY = "robot_telemetry"
    EXTERNAL_SERVICES = "external_services"
    HEALTH_CHECKS = "health_checks"


@dataclass
class PoolConfig:
    """Configuration for connection pool"""
    name: str
    base_url: str
    max_connections: int = 20
    max_connections_per_host: int = 10
    connection_timeout: float = 30.0
    request_timeout: float = 60.0
    read_timeout: float = 30.0
    keepalive_timeout: float = 30.0
    retry_attempts: int = 3
    retry_delay: float = 1.0
    circuit_breaker_threshold: int = 5
    circuit_breaker_timeout: float = 60.0
    headers: Dict[str, str] = field(default_factory=dict)
    verify_ssl: bool = True


@dataclass
class RequestMetrics:
    """Metrics for HTTP requests"""
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    average_response_time: float = 0.0
    min_response_time: float = float('inf')
    max_response_time: float = 0.0
    active_connections: int = 0
    total_response_time: float = 0.0
    
    def add_request(self, response_time: float, success: bool):
        """Add request metrics"""
        self.total_requests += 1
        self.total_response_time += response_time
        
        if success:
            self.successful_requests += 1
        else:
            self.failed_requests += 1
        
        self.min_response_time = min(self.min_response_time, response_time)
        self.max_response_time = max(self.max_response_time, response_time)
        self.average_response_time = self.total_response_time / self.total_requests
    
    @property
    def success_rate(self) -> float:
        """Calculate success rate as percentage"""
        if self.total_requests == 0:
            return 100.0
        return (self.successful_requests / self.total_requests) * 100.0


class ManagedConnectionPool:
    """
    Managed HTTP connection pool with circuit breaker protection.
    """

    def __init__(self, config: PoolConfig):
        self.config = config
        self.session: Optional[ClientSession] = None
        self.circuit_breaker: Optional[CircuitBreaker] = None
        self.metrics = RequestMetrics()
        self.logger = logging.getLogger(f"connection_pool.{config.name}")
        self._lock = asyncio.Lock()

    async def initialize(self):
        """Initialize the connection pool"""
        async with self._lock:
            if self.session is not None:
                return  # Already initialized

            # Create TCP connector
            connector = TCPConnector(
                limit=self.config.max_connections,
                limit_per_host=self.config.max_connections_per_host,
                keepalive_timeout=self.config.keepalive_timeout,
                enable_cleanup_closed=True,
                verify_ssl=self.config.verify_ssl
            )

            # Create timeout configuration
            timeout = ClientTimeout(
                total=self.config.request_timeout,
                connect=self.config.connection_timeout,
                sock_read=self.config.read_timeout
            )

            # Create session
            self.session = ClientSession(
                connector=connector,
                timeout=timeout,
                headers=self.config.headers,
                base_url=self.config.base_url
            )

            # Initialize circuit breaker
            self.circuit_breaker = CircuitBreaker(
                name=f"{self.config.name}_pool",
                failure_threshold=self.config.circuit_breaker_threshold,
                recovery_timeout=self.config.circuit_breaker_timeout,
                expected_exception=aiohttp.ClientError
            )

            self.logger.info(f"Connection pool '{self.config.name}' initialized")

    async def close(self):
        """Close the connection pool"""
        async with self._lock:
            if self.session:
                await self.session.close()
                self.session = None
                self.logger.info(f"Connection pool '{self.config.name}' closed")

    async def request(
        self,
        method: str,
        url: str,
        retries: Optional[int] = None,
        **kwargs
    ) -> aiohttp.ClientResponse:
        """
        Make HTTP request with circuit breaker protection and retries.
        
        Args:
            method: HTTP method
            url: Request URL (relative to base_url)
            retries: Number of retry attempts (uses pool config if None)
            **kwargs: Additional request parameters
            
        Returns:
            HTTP response
            
        Raises:
            ConnectionError: When circuit breaker is open or connection fails
            HardwareError: When request fails after retries
        """
        if self.session is None:
            await self.initialize()

        retries = retries if retries is not None else self.config.retry_attempts
        last_exception = None

        for attempt in range(retries + 1):
            try:
                start_time = time.time()
                
                # Execute request through circuit breaker
                response = await self.circuit_breaker.call(
                    self._make_request,
                    method,
                    url,
                    **kwargs
                )
                
                response_time = time.time() - start_time
                self.metrics.add_request(response_time, True)
                
                # Check for HTTP errors
                if response.status >= 400:
                    error_text = await response.text()
                    raise HardwareError(
                        f"HTTP {response.status}: {error_text}",
                        service_name=self.config.name,
                        context={
                            "method": method,
                            "url": url,
                            "status": response.status,
                            "attempt": attempt + 1
                        }
                    )
                
                self.logger.debug(
                    f"Request successful: {method} {url} "
                    f"({response_time:.3f}s, attempt {attempt + 1})"
                )
                
                return response

            except Exception as e:
                response_time = time.time() - start_time
                self.metrics.add_request(response_time, False)
                last_exception = e
                
                self.logger.warning(
                    f"Request failed: {method} {url} "
                    f"(attempt {attempt + 1}/{retries + 1}): {e}"
                )
                
                # Don't retry on final attempt
                if attempt < retries:
                    delay = self.config.retry_delay * (2 ** attempt)  # Exponential backoff
                    await asyncio.sleep(delay)
                else:
                    break

        # All retries exhausted
        raise HardwareError(
            f"Request failed after {retries + 1} attempts",
            service_name=self.config.name,
            context={
                "method": method,
                "url": url,
                "last_error": str(last_exception),
                "total_attempts": retries + 1
            }
        ) from last_exception

    async def _make_request(
        self,
        method: str,
        url: str,
        **kwargs
    ) -> aiohttp.ClientResponse:
        """Make the actual HTTP request"""
        self.metrics.active_connections += 1
        try:
            response = await self.session.request(method, url, **kwargs)
            return response
        finally:
            self.metrics.active_connections -= 1

    async def get(self, url: str, **kwargs) -> aiohttp.ClientResponse:
        """Make GET request"""
        return await self.request("GET", url, **kwargs)

    async def post(self, url: str, **kwargs) -> aiohttp.ClientResponse:
        """Make POST request"""
        return await self.request("POST", url, **kwargs)

    async def put(self, url: str, **kwargs) -> aiohttp.ClientResponse:
        """Make PUT request"""
        return await self.request("PUT", url, **kwargs)

    async def delete(self, url: str, **kwargs) -> aiohttp.ClientResponse:
        """Make DELETE request"""
        return await self.request("DELETE", url, **kwargs)

    async def head(self, url: str, **kwargs) -> aiohttp.ClientResponse:
        """Make HEAD request"""
        return await self.request("HEAD", url, **kwargs)

    async def health_check(self) -> Dict[str, Any]:
        """Perform health check on the connection pool"""
        try:
            # Simple connectivity test
            start_time = time.time()
            response = await self.head("/", timeout=ClientTimeout(total=5.0))
            response_time = time.time() - start_time
            
            is_healthy = response.status < 500
            
            return {
                "healthy": is_healthy,
                "response_time": response_time,
                "status_code": response.status,
                "circuit_breaker_state": self.circuit_breaker.state.value if self.circuit_breaker else "unknown",
                "metrics": self.get_metrics()
            }
            
        except Exception as e:
            return {
                "healthy": False,
                "error": str(e),
                "circuit_breaker_state": self.circuit_breaker.state.value if self.circuit_breaker else "unknown",
                "metrics": self.get_metrics()
            }

    def get_metrics(self) -> Dict[str, Any]:
        """Get connection pool metrics"""
        return {
            "total_requests": self.metrics.total_requests,
            "successful_requests": self.metrics.successful_requests,
            "failed_requests": self.metrics.failed_requests,
            "success_rate": self.metrics.success_rate,
            "average_response_time": self.metrics.average_response_time,
            "min_response_time": self.metrics.min_response_time if self.metrics.min_response_time != float('inf') else 0.0,
            "max_response_time": self.metrics.max_response_time,
            "active_connections": self.metrics.active_connections,
            "pool_config": {
                "max_connections": self.config.max_connections,
                "max_connections_per_host": self.config.max_connections_per_host,
                "base_url": self.config.base_url
            }
        }


class ConnectionPoolManager:
    """
    Manager for multiple HTTP connection pools.
    """

    def __init__(self):
        self._pools: Dict[str, ManagedConnectionPool] = {}
        self.logger = logging.getLogger("connection_pool_manager")

    async def create_pool(self, config: PoolConfig) -> ManagedConnectionPool:
        """
        Create and register a new connection pool.
        
        Args:
            config: Pool configuration
            
        Returns:
            Managed connection pool
        """
        if config.name in self._pools:
            await self._pools[config.name].close()

        pool = ManagedConnectionPool(config)
        await pool.initialize()
        
        self._pools[config.name] = pool
        self.logger.info(f"Created connection pool: {config.name}")
        
        return pool

    def get_pool(self, name: str) -> Optional[ManagedConnectionPool]:
        """
        Get connection pool by name.
        
        Args:
            name: Pool name
            
        Returns:
            Connection pool or None if not found
        """
        return self._pools.get(name)

    async def close_pool(self, name: str) -> bool:
        """
        Close and remove connection pool.
        
        Args:
            name: Pool name
            
        Returns:
            True if pool was closed
        """
        if name in self._pools:
            await self._pools[name].close()
            del self._pools[name]
            self.logger.info(f"Closed connection pool: {name}")
            return True
        return False

    async def close_all(self):
        """Close all connection pools"""
        for name in list(self._pools.keys()):
            await self.close_pool(name)

    async def health_check_all(self) -> Dict[str, Any]:
        """Health check all pools"""
        results = {}
        
        for name, pool in self._pools.items():
            try:
                results[name] = await pool.health_check()
            except Exception as e:
                results[name] = {
                    "healthy": False,
                    "error": str(e)
                }
        
        return results

    def get_all_metrics(self) -> Dict[str, Any]:
        """Get metrics for all pools"""
        return {
            name: pool.get_metrics()
            for name, pool in self._pools.items()
        }


# Global connection pool manager
_pool_manager: Optional[ConnectionPoolManager] = None


async def get_pool_manager() -> ConnectionPoolManager:
    """Get global connection pool manager"""
    global _pool_manager
    if _pool_manager is None:
        _pool_manager = ConnectionPoolManager()
    return _pool_manager


async def get_or_create_pool(
    pool_type: ConnectionPoolType,
    base_url: str,
    **config_kwargs
) -> ManagedConnectionPool:
    """
    Get or create a connection pool for specific type.
    
    Args:
        pool_type: Type of connection pool
        base_url: Base URL for the pool
        **config_kwargs: Additional configuration options
        
    Returns:
        Managed connection pool
    """
    manager = await get_pool_manager()
    pool_name = pool_type.value
    
    # Check if pool already exists
    existing_pool = manager.get_pool(pool_name)
    if existing_pool:
        return existing_pool
    
    # Create pool configuration based on type
    if pool_type == ConnectionPoolType.OT2_API:
        config = PoolConfig(
            name=pool_name,
            base_url=base_url,
            max_connections=10,
            max_connections_per_host=5,
            connection_timeout=10.0,
            request_timeout=30.0,
            headers={"Opentrons-Version": "2"},
            **config_kwargs
        )
    
    elif pool_type == ConnectionPoolType.ROBOT_TELEMETRY:
        config = PoolConfig(
            name=pool_name,
            base_url=base_url,
            max_connections=20,
            max_connections_per_host=10,
            connection_timeout=5.0,
            request_timeout=15.0,
            **config_kwargs
        )
    
    elif pool_type == ConnectionPoolType.HEALTH_CHECKS:
        config = PoolConfig(
            name=pool_name,
            base_url=base_url,
            max_connections=5,
            max_connections_per_host=5,
            connection_timeout=3.0,
            request_timeout=10.0,
            retry_attempts=1,
            **config_kwargs
        )
    
    else:  # EXTERNAL_SERVICES
        config = PoolConfig(
            name=pool_name,
            base_url=base_url,
            **config_kwargs
        )
    
    return await manager.create_pool(config)


async def shutdown_pools():
    """Shutdown all connection pools"""
    global _pool_manager
    if _pool_manager:
        await _pool_manager.close_all()
        _pool_manager = None