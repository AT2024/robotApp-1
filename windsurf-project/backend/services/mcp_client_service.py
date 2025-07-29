"""
MCP Client Service for communicating with Model Context Protocol servers.
Provides base functionality for connecting to and interacting with MCP servers.
"""

import asyncio
import json
import uuid
from typing import Dict, Any, Optional, List, Callable
from datetime import datetime
import aiohttp
import websockets
from websockets.exceptions import ConnectionClosed, WebSocketException

from utils.logger import get_logger
from core.settings import RoboticsSettings
from core.state_manager import AtomicStateManager
from core.resource_lock import ResourceLockManager
from core.circuit_breaker import circuit_breaker
from services.base import BaseService


class MCPClient:
    """
    Base MCP client for communicating with MCP servers via WebSocket.
    Handles MCP protocol messages and connection management.
    """

    def __init__(self, server_url: str, server_name: str):
        self.server_url = server_url
        self.server_name = server_name
        self.logger = get_logger(f"mcp_client_{server_name}")
        self.websocket: Optional[websockets.WebSocketServerProtocol] = None
        self.is_connected = False
        self.pending_requests: Dict[str, asyncio.Future] = {}
        self.message_handlers: Dict[str, Callable] = {}
        self.connection_lock = asyncio.Lock()
        self._listen_task: Optional[asyncio.Task] = None

    async def connect(self) -> bool:
        """Connect to the MCP server"""
        async with self.connection_lock:
            if self.is_connected:
                return True

            try:
                # Convert HTTP URL to WebSocket URL
                ws_url = self.server_url.replace("http://", "ws://").replace("https://", "wss://")
                if not ws_url.endswith("/"):
                    ws_url += "/"
                # Use /message for Supergateway, /mcp for standard MCP servers
                if "gateway" in self.server_url:
                    ws_url += "message"
                else:
                    ws_url += "mcp"

                self.logger.info(f"Connecting to MCP server: {ws_url}")
                self.websocket = await websockets.connect(ws_url)
                self.is_connected = True

                # Start listening for messages
                self._listen_task = asyncio.create_task(self._listen_for_messages())

                # Send initialization message
                await self._send_initialize()

                self.logger.info(f"Connected to MCP server: {self.server_name}")
                return True

            except Exception as e:
                self.logger.error(f"Failed to connect to MCP server {self.server_name}: {e}")
                self.is_connected = False
                return False

    async def disconnect(self):
        """Disconnect from the MCP server"""
        async with self.connection_lock:
            if not self.is_connected:
                return

            try:
                # Cancel listen task
                if self._listen_task and not self._listen_task.done():
                    self._listen_task.cancel()
                    try:
                        await self._listen_task
                    except asyncio.CancelledError:
                        pass

                # Close WebSocket connection
                if self.websocket:
                    await self.websocket.close()

                # Cancel pending requests
                for future in self.pending_requests.values():
                    if not future.done():
                        future.cancel()
                self.pending_requests.clear()

                self.is_connected = False
                self.websocket = None
                self.logger.info(f"Disconnected from MCP server: {self.server_name}")

            except Exception as e:
                self.logger.error(f"Error during disconnect from {self.server_name}: {e}")

    async def _send_initialize(self):
        """Send MCP initialization message"""
        init_message = {
            "jsonrpc": "2.0",
            "id": str(uuid.uuid4()),
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {
                    "roots": {"list_changed": True},
                    "sampling": {}
                },
                "clientInfo": {
                    "name": "robotics-control-system",
                    "version": "1.0.0"
                }
            }
        }
        await self._send_message(init_message)

    async def _listen_for_messages(self):
        """Listen for incoming messages from MCP server"""
        try:
            async for message in self.websocket:
                try:
                    data = json.loads(message)
                    await self._handle_message(data)
                except json.JSONDecodeError as e:
                    self.logger.error(f"Invalid JSON received from {self.server_name}: {e}")
                except Exception as e:
                    self.logger.error(f"Error handling message from {self.server_name}: {e}")

        except ConnectionClosed:
            self.logger.warning(f"Connection to {self.server_name} closed")
            self.is_connected = False
        except WebSocketException as e:
            self.logger.error(f"WebSocket error with {self.server_name}: {e}")
            self.is_connected = False
        except Exception as e:
            self.logger.error(f"Unexpected error in message listener for {self.server_name}: {e}")
            self.is_connected = False

    async def _handle_message(self, data: Dict[str, Any]):
        """Handle incoming MCP message"""
        # Handle responses to our requests
        if "id" in data and data["id"] in self.pending_requests:
            future = self.pending_requests.pop(data["id"])
            if not future.done():
                if "error" in data:
                    future.set_exception(Exception(f"MCP Error: {data['error']}"))
                else:
                    future.set_result(data.get("result"))
            return

        # Handle notifications and other messages
        message_type = data.get("method", "unknown")
        if message_type in self.message_handlers:
            try:
                await self.message_handlers[message_type](data)
            except Exception as e:
                self.logger.error(f"Error in message handler for {message_type}: {e}")

    async def _send_message(self, message: Dict[str, Any]):
        """Send a message to the MCP server"""
        if not self.is_connected or not self.websocket:
            raise Exception(f"Not connected to MCP server {self.server_name}")

        try:
            await self.websocket.send(json.dumps(message))
        except Exception as e:
            self.logger.error(f"Failed to send message to {self.server_name}: {e}")
            raise

    async def send_request(self, method: str, params: Dict[str, Any] = None, timeout: float = 30.0) -> Any:
        """Send a request to the MCP server and wait for response"""
        if not self.is_connected:
            await self.connect()

        request_id = str(uuid.uuid4())
        message = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params or {}
        }

        # Create future for response
        future = asyncio.Future()
        self.pending_requests[request_id] = future

        try:
            # Send request
            await self._send_message(message)

            # Wait for response with timeout
            result = await asyncio.wait_for(future, timeout=timeout)
            return result

        except asyncio.TimeoutError:
            # Clean up pending request
            self.pending_requests.pop(request_id, None)
            raise Exception(f"Request to {self.server_name} timed out after {timeout}s")
        except Exception as e:
            # Clean up pending request
            self.pending_requests.pop(request_id, None)
            raise

    def register_message_handler(self, message_type: str, handler: Callable):
        """Register a handler for specific message types"""
        self.message_handlers[message_type] = handler

    async def health_check(self) -> Dict[str, Any]:
        """Check health of MCP connection"""
        try:
            if not self.is_connected:
                return {"healthy": False, "status": "disconnected"}

            # Try to ping the server or list capabilities
            result = await self.send_request("tools/list", timeout=5.0)
            return {
                "healthy": True,
                "status": "connected",
                "server_name": self.server_name,
                "tools_available": len(result.get("tools", [])) if result else 0
            }

        except Exception as e:
            return {
                "healthy": False,
                "status": "error",
                "error": str(e)
            }


class MCPClientService(BaseService):
    """
    Service for managing MCP client connections and providing a unified interface
    to interact with multiple MCP servers.
    """

    def __init__(
        self,
        settings: RoboticsSettings,
        state_manager: AtomicStateManager,
        lock_manager: ResourceLockManager,
        mcp_servers: Dict[str, str] = None
    ):
        super().__init__(settings, state_manager, lock_manager, "mcp_client")
        self.logger = get_logger("mcp_client_service")
        
        # Default MCP servers (can be overridden)
        self.mcp_servers = mcp_servers or {
            "playwright": "http://localhost:3004",
            "magic": "http://localhost:3003",
            "context7": "http://localhost:3001"
        }
        
        self.clients: Dict[str, MCPClient] = {}
        self.is_running = False

    async def start(self):
        """Start the MCP client service"""
        if self.is_running:
            return

        try:
            self.logger.info("Starting MCP Client Service...")

            # Initialize MCP clients
            for server_name, server_url in self.mcp_servers.items():
                client = MCPClient(server_url, server_name)
                self.clients[server_name] = client

                # Try to connect (don't fail if some servers are unavailable)
                try:
                    await client.connect()
                    self.logger.info(f"Connected to MCP server: {server_name}")
                except Exception as e:
                    self.logger.warning(f"Failed to connect to MCP server {server_name}: {e}")

            self.is_running = True
            self.logger.info("MCP Client Service started successfully")

        except Exception as e:
            self.logger.error(f"Failed to start MCP Client Service: {e}")
            raise

    async def stop(self):
        """Stop the MCP client service"""
        if not self.is_running:
            return

        try:
            self.logger.info("Stopping MCP Client Service...")

            # Disconnect all clients
            for client in self.clients.values():
                await client.disconnect()

            self.clients.clear()
            self.is_running = False
            self.logger.info("MCP Client Service stopped successfully")

        except Exception as e:
            self.logger.error(f"Error stopping MCP Client Service: {e}")

    @circuit_breaker("mcp_request")
    async def send_request(
        self,
        server_name: str,
        method: str,
        params: Dict[str, Any] = None,
        timeout: float = 30.0
    ) -> Any:
        """Send a request to a specific MCP server"""
        if not self.is_running:
            raise Exception("MCP Client Service not running")

        if server_name not in self.clients:
            raise Exception(f"MCP server not found: {server_name}")

        client = self.clients[server_name]
        
        # Ensure client is connected
        if not client.is_connected:
            await client.connect()

        return await client.send_request(method, params, timeout)

    async def get_available_tools(self, server_name: str) -> List[Dict[str, Any]]:
        """Get available tools from an MCP server"""
        try:
            result = await self.send_request(server_name, "tools/list")
            return result.get("tools", []) if result else []
        except Exception as e:
            self.logger.error(f"Failed to get tools from {server_name}: {e}")
            return []

    async def call_tool(
        self,
        server_name: str,
        tool_name: str,
        arguments: Dict[str, Any] = None
    ) -> Any:
        """Call a tool on an MCP server"""
        params = {
            "name": tool_name,
            "arguments": arguments or {}
        }
        return await self.send_request(server_name, "tools/call", params)

    async def health_check(self) -> Dict[str, Any]:
        """Check health of all MCP connections"""
        health_info = {
            "healthy": True,
            "service_name": self.service_name,
            "is_running": self.is_running,
            "servers": {}
        }

        if not self.is_running:
            health_info["healthy"] = False
            return health_info

        # Check each client
        for server_name, client in self.clients.items():
            server_health = await client.health_check()
            health_info["servers"][server_name] = server_health
            
            if not server_health["healthy"]:
                health_info["healthy"] = False

        return health_info

    def get_client(self, server_name: str) -> Optional[MCPClient]:
        """Get a specific MCP client"""
        return self.clients.get(server_name)

    def list_servers(self) -> List[str]:
        """List available MCP servers"""
        return list(self.clients.keys())