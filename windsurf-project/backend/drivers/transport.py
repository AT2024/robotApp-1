"""
NIC-Binding TCP Transport Layer for Robotics Control.

Provides precise network interface control for robot connections,
ensuring traffic routes through specific NICs for network segmentation
and performance optimization.
"""

import asyncio
import socket
import time
from typing import Optional, Dict, Any, Tuple, List
from dataclasses import dataclass
from contextlib import asynccontextmanager
try:
    import netifaces
    NETIFACES_AVAILABLE = True
except ImportError:
    NETIFACES_AVAILABLE = False
    # Fallback for when netifaces is not available
from utils.logger import get_logger

# Initialize logger lazily to avoid startup issues
logger = None

def _get_logger():
    global logger
    if logger is None:
        logger = get_logger("transport")
    return logger


@dataclass
class ConnectionStats:
    """Connection statistics and metrics."""
    
    established_at: float
    bytes_sent: int = 0
    bytes_received: int = 0
    connection_attempts: int = 0
    last_activity: float = 0.0
    errors: int = 0
    
    @property
    def age_seconds(self) -> float:
        """Connection age in seconds."""
        return time.time() - self.established_at
    
    @property
    def seconds_since_activity(self) -> float:
        """Seconds since last activity."""
        return time.time() - self.last_activity


@dataclass
class TransportConfig:
    """Transport layer configuration."""
    
    # Connection parameters
    connect_timeout: float = 10.0
    read_timeout: float = 30.0
    write_timeout: float = 10.0
    
    # Socket options
    tcp_nodelay: bool = True
    tcp_keepalive: bool = True
    socket_bufsize: int = 8192
    
    # Retry behavior
    max_retries: int = 3
    retry_delay: float = 1.0
    retry_backoff: float = 2.0
    
    # NIC binding
    bind_interface: Optional[str] = None
    bind_ip: Optional[str] = None


class NetworkInterfaceError(Exception):
    """Raised when network interface operations fail."""
    pass


class BoundTCPClient:
    """
    TCP client with NIC-specific binding capabilities.
    
    Supports binding to specific network interfaces or IP addresses
    to control routing for robot connections.
    """
    
    def __init__(self, config: TransportConfig):
        self.config = config
        self.stats = ConnectionStats(established_at=time.time())
        self._reader: Optional[asyncio.StreamReader] = None
        self._writer: Optional[asyncio.StreamWriter] = None
        self._bound_socket: Optional[socket.socket] = None
        self._connected = False
        
        # Resolve bind interface to IP if needed
        self._bind_ip = self._resolve_bind_address()
        
        _get_logger().info(
            f"BoundTCPClient initialized with config: "
            f"interface={config.bind_interface}, ip={config.bind_ip}, "
            f"resolved_ip={self._bind_ip}"
        )
    
    def _resolve_bind_address(self) -> Optional[str]:
        """
        Resolve bind interface name to IP address.
        
        Returns:
            IP address to bind to, or None for default routing
        """
        # Direct IP takes precedence
        if self.config.bind_ip:
            return self.config.bind_ip
        
        # No interface specified
        if not self.config.bind_interface:
            return None
        
        if not NETIFACES_AVAILABLE:
            _get_logger().warning(
                f"netifaces not available, cannot bind to interface {self.config.bind_interface}. "
                "Using default routing instead."
            )
            return None
        
        try:
            # Get interface addresses
            interface_info = netifaces.ifaddresses(self.config.bind_interface)
            
            # Prefer IPv4 addresses
            if netifaces.AF_INET in interface_info:
                ipv4_addresses = interface_info[netifaces.AF_INET]
                if ipv4_addresses:
                    bind_ip = ipv4_addresses[0]['addr']
                    _get_logger().info(f"Resolved interface {self.config.bind_interface} to IP {bind_ip}")
                    return bind_ip
            
            # Fallback to IPv6 if available
            if netifaces.AF_INET6 in interface_info:
                ipv6_addresses = interface_info[netifaces.AF_INET6]
                if ipv6_addresses:
                    bind_ip = ipv6_addresses[0]['addr']
                    _get_logger().info(f"Resolved interface {self.config.bind_interface} to IPv6 {bind_ip}")
                    return bind_ip
            
            raise NetworkInterfaceError(
                f"No IP addresses found for interface {self.config.bind_interface}"
            )
        
        except (OSError, KeyError) as e:
            # Log available interfaces for troubleshooting
            available = self.get_available_interfaces()
            _get_logger().error(
                f"Failed to resolve interface {self.config.bind_interface}: {e}. "
                f"Available interfaces: {available}"
            )
            raise NetworkInterfaceError(
                f"Interface {self.config.bind_interface} not found or has no addresses"
            ) from e
    
    @staticmethod
    def get_available_interfaces() -> List[str]:
        """Get list of available network interfaces."""
        if not NETIFACES_AVAILABLE:
            _get_logger().warning("netifaces not available, cannot list network interfaces")
            return []
        try:
            return netifaces.interfaces()
        except Exception as e:
            _get_logger().warning(f"Failed to get network interfaces: {e}")
            return []
    
    @staticmethod
    def get_interface_info(interface: str) -> Dict[str, Any]:
        """
        Get detailed information about a network interface.
        
        Args:
            interface: Interface name (e.g., 'eth0', 'en0')
            
        Returns:
            Dictionary with interface details
        """
        if not NETIFACES_AVAILABLE:
            return {"name": interface, "error": "netifaces not available"}
        
        try:
            info = netifaces.ifaddresses(interface)
            result = {"name": interface, "addresses": {}}
            
            # IPv4 addresses
            if netifaces.AF_INET in info:
                result["addresses"]["ipv4"] = info[netifaces.AF_INET]
            
            # IPv6 addresses
            if netifaces.AF_INET6 in info:
                result["addresses"]["ipv6"] = info[netifaces.AF_INET6]
            
            return result
        
        except Exception as e:
            return {"name": interface, "error": str(e)}
    
    async def connect(self, host: str, port: int) -> bool:
        """
        Establish connection to remote host with NIC binding.
        
        Args:
            host: Remote host address
            port: Remote port number
            
        Returns:
            True if connection successful, False otherwise
        """
        if self._connected:
            _get_logger().warning("Already connected, disconnecting first")
            await self.disconnect()
        
        self.stats.connection_attempts += 1
        
        for attempt in range(self.config.max_retries + 1):
            try:
                _get_logger().info(
                    f"Connection attempt {attempt + 1}/{self.config.max_retries + 1} "
                    f"to {host}:{port}"
                    f"{f' via {self._bind_ip}' if self._bind_ip else ''}"
                )
                
                # Create and configure socket
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self._bound_socket = sock
                
                # Apply socket options
                if self.config.tcp_nodelay:
                    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                
                if self.config.tcp_keepalive:
                    sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
                
                # Set buffer sizes
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, self.config.socket_bufsize)
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, self.config.socket_bufsize)
                
                # Bind to specific interface if configured
                if self._bind_ip:
                    _get_logger().debug(f"Binding socket to local address {self._bind_ip}")
                    sock.bind((self._bind_ip, 0))  # 0 = any available port
                
                # Set non-blocking and connect
                sock.setblocking(False)
                
                try:
                    # Connect with timeout
                    await asyncio.wait_for(
                        asyncio.get_event_loop().sock_connect(sock, (host, port)),
                        timeout=self.config.connect_timeout
                    )
                    
                    # Create streams from connected socket
                    self._reader, self._writer = await asyncio.open_connection(sock=sock)
                    
                    # Update connection state
                    self._connected = True
                    self.stats.established_at = time.time()
                    self.stats.last_activity = time.time()
                    
                    _get_logger().info(
                        f"✅ Connected to {host}:{port}"
                        f"{f' via {self._bind_ip}' if self._bind_ip else ''}"
                    )
                    return True
                
                except asyncio.TimeoutError:
                    _get_logger().warning(f"Connection timeout to {host}:{port} (attempt {attempt + 1})")
                    sock.close()
                    
                except Exception as e:
                    _get_logger().warning(f"Connection failed to {host}:{port}: {e} (attempt {attempt + 1})")
                    sock.close()
                    raise
            
            except Exception as e:
                self.stats.errors += 1
                if attempt == self.config.max_retries:
                    _get_logger().error(f"All connection attempts failed to {host}:{port}: {e}")
                    return False
                
                # Wait before retry with backoff
                wait_time = self.config.retry_delay * (self.config.retry_backoff ** attempt)
                _get_logger().debug(f"Retrying in {wait_time:.1f}s...")
                await asyncio.sleep(wait_time)
        
        return False
    
    async def disconnect(self) -> None:
        """Close the connection and cleanup resources."""
        if self._writer:
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except Exception as e:
                _get_logger().debug(f"Error closing writer: {e}")
            finally:
                self._writer = None
        
        if self._bound_socket:
            try:
                self._bound_socket.close()
            except Exception as e:
                _get_logger().debug(f"Error closing socket: {e}")
            finally:
                self._bound_socket = None
        
        self._reader = None
        self._connected = False
        _get_logger().debug("Disconnected and cleaned up resources")
    
    async def send(self, data: bytes) -> int:
        """
        Send data to remote host.
        
        Args:
            data: Bytes to send
            
        Returns:
            Number of bytes sent
            
        Raises:
            ConnectionError: If not connected or send fails
        """
        if not self._connected or not self._writer:
            raise ConnectionError("Not connected")
        
        try:
            self._writer.write(data)
            await asyncio.wait_for(
                self._writer.drain(), 
                timeout=self.config.write_timeout
            )
            
            bytes_sent = len(data)
            self.stats.bytes_sent += bytes_sent
            self.stats.last_activity = time.time()
            
            _get_logger().debug(f"Sent {bytes_sent} bytes")
            return bytes_sent
        
        except Exception as e:
            self.stats.errors += 1
            _get_logger().error(f"Send failed: {e}")
            raise ConnectionError(f"Send failed: {e}") from e
    
    async def receive(self, max_bytes: int = 1024) -> bytes:
        """
        Receive data from remote host.
        
        Args:
            max_bytes: Maximum bytes to receive
            
        Returns:
            Received bytes (may be empty)
            
        Raises:
            ConnectionError: If not connected or receive fails
        """
        if not self._connected or not self._reader:
            raise ConnectionError("Not connected")
        
        try:
            data = await asyncio.wait_for(
                self._reader.read(max_bytes),
                timeout=self.config.read_timeout
            )
            
            bytes_received = len(data)
            self.stats.bytes_received += bytes_received
            if bytes_received > 0:
                self.stats.last_activity = time.time()
            
            _get_logger().debug(f"Received {bytes_received} bytes")
            return data
        
        except asyncio.TimeoutError:
            _get_logger().debug("Receive timeout (no data available)")
            return b""
        
        except Exception as e:
            self.stats.errors += 1
            _get_logger().error(f"Receive failed: {e}")
            raise ConnectionError(f"Receive failed: {e}") from e
    
    @property
    def is_connected(self) -> bool:
        """Check if connection is active."""
        return self._connected and self._writer is not None
    
    @property
    def connection_info(self) -> Dict[str, Any]:
        """Get connection information and statistics."""
        return {
            "connected": self.is_connected,
            "bind_ip": self._bind_ip,
            "bind_interface": self.config.bind_interface,
            "stats": {
                "established_at": self.stats.established_at,
                "age_seconds": self.stats.age_seconds,
                "bytes_sent": self.stats.bytes_sent,
                "bytes_received": self.stats.bytes_received,
                "connection_attempts": self.stats.connection_attempts,
                "last_activity": self.stats.last_activity,
                "seconds_since_activity": self.stats.seconds_since_activity,
                "errors": self.stats.errors,
            },
            "config": {
                "connect_timeout": self.config.connect_timeout,
                "read_timeout": self.config.read_timeout,
                "write_timeout": self.config.write_timeout,
                "tcp_nodelay": self.config.tcp_nodelay,
                "tcp_keepalive": self.config.tcp_keepalive,
                "max_retries": self.config.max_retries,
            }
        }
    
    @asynccontextmanager
    async def connection(self, host: str, port: int):
        """
        Async context manager for automatic connection management.
        
        Usage:
            async with client.connection("192.168.1.100", 10000):
                await client.send(b"command\0")
                response = await client.receive()
        """
        try:
            if not await self.connect(host, port):
                raise ConnectionError(f"Failed to connect to {host}:{port}")
            yield self
        finally:
            await self.disconnect()


# Convenience functions for common use cases

def create_default_transport(
    bind_interface: Optional[str] = None,
    bind_ip: Optional[str] = None
) -> BoundTCPClient:
    """
    Create a transport client with sensible defaults.
    
    Args:
        bind_interface: Network interface name to bind to
        bind_ip: IP address to bind to (takes precedence over interface)
        
    Returns:
        Configured BoundTCPClient instance
    """
    config = TransportConfig(
        bind_interface=bind_interface,
        bind_ip=bind_ip,
        connect_timeout=10.0,
        tcp_nodelay=True,
        tcp_keepalive=True,
    )
    return BoundTCPClient(config)


async def test_connectivity(
    host: str, 
    port: int, 
    bind_interface: Optional[str] = None,
    timeout: float = 5.0
) -> Dict[str, Any]:
    """
    Test connectivity to a remote host with optional NIC binding.
    
    Args:
        host: Target host
        port: Target port
        bind_interface: Interface to bind to (optional)
        timeout: Connection timeout
        
    Returns:
        Test results dictionary
    """
    config = TransportConfig(
        bind_interface=bind_interface,
        connect_timeout=timeout
    )
    client = BoundTCPClient(config)
    
    start_time = time.time()
    
    try:
        success = await client.connect(host, port)
        connect_time = time.time() - start_time
        
        result = {
            "success": success,
            "connect_time": connect_time,
            "host": host,
            "port": port,
            "bind_interface": bind_interface,
            "bind_ip": client._bind_ip,
        }
        
        if success:
            result.update(client.connection_info)
        
        return result
    
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "connect_time": time.time() - start_time,
            "host": host,
            "port": port,
            "bind_interface": bind_interface,
        }
    
    finally:
        await client.disconnect()