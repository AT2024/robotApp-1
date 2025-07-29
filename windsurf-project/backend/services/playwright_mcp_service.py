"""
Playwright MCP Service - Wrapper for the Playwright MCP server running on localhost:3004.
Provides browser automation capabilities through the MCP protocol.
"""

from typing import Dict, Any, Optional, List
from datetime import datetime
import base64

from utils.logger import get_logger
from core.settings import RoboticsSettings
from core.state_manager import AtomicStateManager
from core.resource_lock import ResourceLockManager
from core.circuit_breaker import circuit_breaker
from services.base import BaseService
from services.mcp_client_service import MCPClientService


class PlaywrightMCPService(BaseService):
    """
    Service wrapper for Playwright MCP server.
    Provides high-level browser automation methods.
    """

    def __init__(
        self,
        settings: RoboticsSettings,
        state_manager: AtomicStateManager,
        lock_manager: ResourceLockManager,
        mcp_client_service: MCPClientService
    ):
        super().__init__(settings, state_manager, lock_manager, "playwright_mcp")
        self.mcp_client = mcp_client_service
        self.logger = get_logger("playwright_mcp_service")
        
        # Playwright MCP server name
        self.server_name = "playwright"
        
        # Browser state tracking
        self.browser_state = {
            "is_open": False,
            "current_url": None,
            "current_page_title": None,
            "tabs": [],
            "last_action": None,
            "last_action_time": None
        }

    async def start(self):
        """Start the Playwright MCP service"""
        try:
            self.logger.info("Starting Playwright MCP Service...")
            
            # Ensure MCP client is running
            if not self.mcp_client.is_running:
                await self.mcp_client.start()
            
            # Test connection to Playwright MCP server
            await self._test_connection()
            
            self.logger.info("Playwright MCP Service started successfully")
            
        except Exception as e:
            self.logger.error(f"Failed to start Playwright MCP Service: {e}")
            raise

    async def stop(self):
        """Stop the Playwright MCP service"""
        try:
            self.logger.info("Stopping Playwright MCP Service...")
            
            # Close any open browser sessions
            try:
                await self.close_browser()
            except Exception as e:
                self.logger.warning(f"Error closing browser during shutdown: {e}")
            
            self.logger.info("Playwright MCP Service stopped successfully")
            
        except Exception as e:
            self.logger.error(f"Error stopping Playwright MCP Service: {e}")

    async def _test_connection(self):
        """Test connection to Playwright MCP server"""
        try:
            tools = await self.mcp_client.get_available_tools(self.server_name)
            self.logger.info(f"Playwright MCP server has {len(tools)} tools available")
            return True
        except Exception as e:
            self.logger.error(f"Failed to connect to Playwright MCP server: {e}")
            raise

    @circuit_breaker("playwright_mcp")
    async def _call_tool(self, tool_name: str, arguments: Dict[str, Any] = None) -> Any:
        """Call a tool on the Playwright MCP server"""
        try:
            result = await self.mcp_client.call_tool(
                self.server_name, 
                tool_name, 
                arguments or {}
            )
            
            # Update last action tracking
            self.browser_state["last_action"] = tool_name
            self.browser_state["last_action_time"] = datetime.now().isoformat()
            
            return result
            
        except Exception as e:
            self.logger.error(f"Failed to call Playwright tool {tool_name}: {e}")
            raise

    # Browser Management Methods
    
    async def navigate(self, url: str) -> Dict[str, Any]:
        """Navigate to a URL"""
        try:
            result = await self._call_tool("browser_navigate", {
                "url": url
            })
            
            # Update browser state
            self.browser_state["is_open"] = True
            self.browser_state["current_url"] = url
            
            self.logger.info(f"Navigated to: {url}")
            return {
                "success": True,
                "url": url,
                "result": result
            }
            
        except Exception as e:
            self.logger.error(f"Failed to navigate to {url}: {e}")
            return {
                "success": False,
                "error": str(e),
                "url": url
            }

    async def take_screenshot(self, full_page: bool = False, element_ref: str = None) -> Dict[str, Any]:
        """Take a screenshot of the current page"""
        try:
            arguments = {
                "fullPage": full_page
            }
            
            if element_ref:
                arguments["element"] = "screenshot target element"
                arguments["ref"] = element_ref
            
            result = await self._call_tool("browser_take_screenshot", arguments)
            
            self.logger.info("Screenshot taken successfully")
            return {
                "success": True,
                "screenshot_data": result,
                "full_page": full_page,
                "timestamp": datetime.now().isoformat()
            }
            
        except Exception as e:
            self.logger.error(f"Failed to take screenshot: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    async def get_page_snapshot(self) -> Dict[str, Any]:
        """Get accessibility snapshot of the current page"""
        try:
            result = await self._call_tool("browser_snapshot")
            
            self.logger.info("Page snapshot captured successfully")
            return {
                "success": True,
                "snapshot": result,
                "timestamp": datetime.now().isoformat()
            }
            
        except Exception as e:
            self.logger.error(f"Failed to get page snapshot: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    async def click_element(self, element_description: str, element_ref: str, button: str = "left") -> Dict[str, Any]:
        """Click an element on the page"""
        try:
            result = await self._call_tool("browser_click", {
                "element": element_description,
                "ref": element_ref,
                "button": button
            })
            
            self.logger.info(f"Clicked element: {element_description}")
            return {
                "success": True,
                "element": element_description,
                "result": result
            }
            
        except Exception as e:
            self.logger.error(f"Failed to click element {element_description}: {e}")
            return {
                "success": False,
                "error": str(e),
                "element": element_description
            }

    async def type_text(self, element_description: str, element_ref: str, text: str, submit: bool = False) -> Dict[str, Any]:
        """Type text into an element"""
        try:
            result = await self._call_tool("browser_type", {
                "element": element_description,
                "ref": element_ref,
                "text": text,
                "submit": submit
            })
            
            self.logger.info(f"Typed text into element: {element_description}")
            return {
                "success": True,
                "element": element_description,
                "text": text,
                "result": result
            }
            
        except Exception as e:
            self.logger.error(f"Failed to type text into {element_description}: {e}")
            return {
                "success": False,
                "error": str(e),
                "element": element_description
            }

    async def evaluate_javascript(self, function_code: str, element_ref: str = None) -> Dict[str, Any]:
        """Evaluate JavaScript on the page"""
        try:
            arguments = {
                "function": function_code
            }
            
            if element_ref:
                arguments["element"] = "target element for evaluation"
                arguments["ref"] = element_ref
            
            result = await self._call_tool("browser_evaluate", arguments)
            
            self.logger.info("JavaScript evaluation completed")
            return {
                "success": True,
                "function": function_code,
                "result": result
            }
            
        except Exception as e:
            self.logger.error(f"Failed to evaluate JavaScript: {e}")
            return {
                "success": False,
                "error": str(e),
                "function": function_code
            }

    async def wait_for_element(self, text: str = None, text_gone: str = None, time_seconds: float = None) -> Dict[str, Any]:
        """Wait for text to appear/disappear or time to pass"""
        try:
            arguments = {}
            if text:
                arguments["text"] = text
            if text_gone:
                arguments["textGone"] = text_gone
            if time_seconds:
                arguments["time"] = time_seconds
            
            result = await self._call_tool("browser_wait_for", arguments)
            
            self.logger.info("Wait condition completed")
            return {
                "success": True,
                "result": result
            }
            
        except Exception as e:
            self.logger.error(f"Failed to wait for condition: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    # Tab Management
    
    async def list_tabs(self) -> Dict[str, Any]:
        """List all browser tabs"""
        try:
            result = await self._call_tool("browser_tab_list")
            
            self.browser_state["tabs"] = result.get("tabs", []) if result else []
            
            return {
                "success": True,
                "tabs": self.browser_state["tabs"]
            }
            
        except Exception as e:
            self.logger.error(f"Failed to list tabs: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    async def new_tab(self, url: str = None) -> Dict[str, Any]:
        """Open a new tab"""
        try:
            arguments = {}
            if url:
                arguments["url"] = url
            
            result = await self._call_tool("browser_tab_new", arguments)
            
            self.logger.info(f"New tab opened{f' with URL: {url}' if url else ''}")
            return {
                "success": True,
                "url": url,
                "result": result
            }
            
        except Exception as e:
            self.logger.error(f"Failed to open new tab: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    async def select_tab(self, tab_index: int) -> Dict[str, Any]:
        """Select a tab by index"""
        try:
            result = await self._call_tool("browser_tab_select", {
                "index": tab_index
            })
            
            self.logger.info(f"Selected tab: {tab_index}")
            return {
                "success": True,
                "tab_index": tab_index,
                "result": result
            }
            
        except Exception as e:
            self.logger.error(f"Failed to select tab {tab_index}: {e}")
            return {
                "success": False,
                "error": str(e),
                "tab_index": tab_index
            }

    async def close_tab(self, tab_index: int = None) -> Dict[str, Any]:
        """Close a tab (current tab if index not specified)"""
        try:
            arguments = {}
            if tab_index is not None:
                arguments["index"] = tab_index
            
            result = await self._call_tool("browser_tab_close", arguments)
            
            self.logger.info(f"Closed tab{f': {tab_index}' if tab_index is not None else ' (current)'}")
            return {
                "success": True,
                "tab_index": tab_index,
                "result": result
            }
            
        except Exception as e:
            self.logger.error(f"Failed to close tab: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    async def install_browser(self) -> Dict[str, Any]:
        """Install browsers for Playwright (can take several minutes)"""
        try:
            self.logger.info("Starting browser installation - this may take several minutes...")
            
            # Browser installation can take a long time, so use extended timeout
            params = {
                "name": "browser_install",
                "arguments": {}
            }
            result = await self.mcp_client.send_request(
                self.server_name, 
                "tools/call", 
                params,
                timeout=600.0  # 10 minutes timeout for browser installation
            )
            
            self.logger.info("Browsers installed successfully")
            return {
                "success": True,
                "result": result,
                "timestamp": datetime.now().isoformat()
            }
            
        except Exception as e:
            self.logger.error(f"Failed to install browsers: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    async def close_browser(self) -> Dict[str, Any]:
        """Close the browser"""
        try:
            result = await self._call_tool("browser_close")
            
            # Reset browser state
            self.browser_state = {
                "is_open": False,
                "current_url": None,
                "current_page_title": None,
                "tabs": [],
                "last_action": "close_browser",
                "last_action_time": datetime.now().isoformat()
            }
            
            self.logger.info("Browser closed successfully")
            return {
                "success": True,
                "result": result
            }
            
        except Exception as e:
            self.logger.error(f"Failed to close browser: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    async def get_browser_state(self) -> Dict[str, Any]:
        """Get current browser state"""
        return {
            "success": True,
            "state": self.browser_state.copy(),
            "timestamp": datetime.now().isoformat()
        }

    async def health_check(self) -> Dict[str, Any]:
        """Check health of Playwright MCP service"""
        try:
            # Check MCP client health
            mcp_health = await self.mcp_client.health_check()
            playwright_server_health = mcp_health["servers"].get(self.server_name, {})
            
            health_info = {
                "healthy": playwright_server_health.get("healthy", False),
                "service_name": self.service_name,
                "mcp_server": self.server_name,
                "browser_state": self.browser_state.copy(),
                "server_health": playwright_server_health
            }
            
            # Try to get available tools as additional health check
            if health_info["healthy"]:
                try:
                    tools = await self.mcp_client.get_available_tools(self.server_name)
                    health_info["available_tools"] = len(tools)
                except Exception as e:
                    health_info["healthy"] = False
                    health_info["tool_check_error"] = str(e)
            
            return health_info
            
        except Exception as e:
            return {
                "healthy": False,
                "service_name": self.service_name,
                "error": str(e)
            }