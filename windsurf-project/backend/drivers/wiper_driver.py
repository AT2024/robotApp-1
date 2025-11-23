"""
Wiper 6-55 hardware driver.
Provides low-level interface to the Wiper 6-55 cleaning hardware.
"""

import asyncio
import aiohttp
import json
from typing import Dict, Any, Optional
from dataclasses import dataclass
from enum import Enum

from core.hardware_manager import BaseRobotDriver
from core.exceptions import HardwareError, ConnectionError
from utils.logger import get_logger


class WiperState(Enum):
    """Wiper system states"""
    IDLE = "idle"
    CLEANING = "cleaning"
    DRYING = "drying"
    ERROR = "error"
    MAINTENANCE = "maintenance"


class WiperSpeed(Enum):
    """Wiper speed settings"""
    SLOW = "slow"
    NORMAL = "normal"
    FAST = "fast"


@dataclass
class WiperStatus:
    """Wiper system status information"""
    state: WiperState
    current_cycle: int
    total_cycles: int
    remaining_dry_time: float
    error_message: Optional[str] = None
    uptime_seconds: float = 0.0
    cycles_completed: int = 0


class WiperDriver(BaseRobotDriver):
    """
    Driver for Wiper 6-55 cleaning hardware.
    
    Provides interface for:
    - Cleaning cycle control
    - Drying operations
    - Status monitoring
    - Error handling
    """
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.logger = get_logger("WiperDriver")
        
        # Connection parameters - all required from config (no fallbacks)
        self.ip = config["ip"]
        self.port = config["port"]
        self.timeout = config["timeout"]
        self.base_url = f"http://{self.ip}:{self.port}"
        
        # Cleaning parameters
        cleaning_params = config.get("cleaning_params", {})
        self.default_cycles = cleaning_params.get("cycles", 3)
        self.default_dry_time = cleaning_params.get("dry_time")
        self.default_speed = cleaning_params.get("speed", "normal")
        
        # Connection state
        self._session: Optional[aiohttp.ClientSession] = None
        self._current_status = WiperStatus(
            state=WiperState.IDLE,
            current_cycle=0,
            total_cycles=0,
            remaining_dry_time=0.0
        )
    
    async def _connect_impl(self) -> bool:
        """Establish connection to Wiper 6-55 hardware"""
        try:
            # Create HTTP session
            timeout = aiohttp.ClientTimeout(total=self.timeout)
            self._session = aiohttp.ClientSession(timeout=timeout)
            
            # Test connection with status request
            status = await self._get_status()
            if status:
                self.logger.info(f"Connected to Wiper 6-55 at {self.base_url}")
                return True
            else:
                raise ConnectionError("Failed to get status from Wiper 6-55")
                
        except Exception as e:
            self.logger.error(f"Failed to connect to Wiper 6-55: {e}")
            if self._session:
                await self._session.close()
                self._session = None
            return False
    
    async def _disconnect_impl(self) -> bool:
        """Disconnect from Wiper 6-55 hardware"""
        try:
            if self._session:
                await self._session.close()
                self._session = None
            
            self.logger.info("Disconnected from Wiper 6-55")
            return True
            
        except Exception as e:
            self.logger.error(f"Error during Wiper 6-55 disconnect: {e}")
            return False
    
    async def _ping_impl(self) -> float:
        """Ping the Wiper 6-55 to check connectivity"""
        if not self._session:
            raise ConnectionError("Not connected to Wiper 6-55")
        
        try:
            import time
            start_time = time.time()
            
            async with self._session.get(f"{self.base_url}/ping") as response:
                if response.status == 200:
                    return time.time() - start_time
                else:
                    raise ConnectionError(f"Ping failed with status {response.status}")
                    
        except Exception as e:
            raise ConnectionError(f"Ping failed: {e}")
    
    async def _get_status_impl(self) -> Dict[str, Any]:
        """Get current status from Wiper 6-55"""
        status = await self._get_status()
        
        return {
            "state": status.state.value,
            "current_cycle": status.current_cycle,
            "total_cycles": status.total_cycles,
            "remaining_dry_time": status.remaining_dry_time,
            "error_message": status.error_message,
            "uptime_seconds": status.uptime_seconds,
            "cycles_completed": status.cycles_completed,
        }
    
    async def _emergency_stop_impl(self) -> bool:
        """Emergency stop the Wiper 6-55"""
        if not self._session:
            raise ConnectionError("Not connected to Wiper 6-55")
        
        try:
            async with self._session.post(f"{self.base_url}/emergency_stop") as response:
                if response.status == 200:
                    self.logger.info("Emergency stop executed on Wiper 6-55")
                    return True
                else:
                    raise HardwareError(f"Emergency stop failed with status {response.status}")
                    
        except Exception as e:
            self.logger.error(f"Emergency stop failed: {e}")
            return False
    
    async def _get_status(self) -> WiperStatus:
        """Internal method to get status from hardware"""
        if not self._session:
            raise ConnectionError("Not connected to Wiper 6-55")
        
        try:
            async with self._session.get(f"{self.base_url}/status") as response:
                if response.status == 200:
                    data = await response.json()
                    
                    # Parse status from hardware response
                    state_str = data.get("state", "idle").lower()
                    state = WiperState(state_str) if state_str in [s.value for s in WiperState] else WiperState.IDLE
                    
                    status = WiperStatus(
                        state=state,
                        current_cycle=data.get("current_cycle", 0),
                        total_cycles=data.get("total_cycles", 0),
                        remaining_dry_time=data.get("remaining_dry_time", 0.0),
                        error_message=data.get("error_message"),
                        uptime_seconds=data.get("uptime_seconds", 0.0),
                        cycles_completed=data.get("cycles_completed", 0)
                    )
                    
                    self._current_status = status
                    return status
                else:
                    raise HardwareError(f"Status request failed with status {response.status}")
                    
        except Exception as e:
            self.logger.error(f"Failed to get Wiper status: {e}")
            # Return cached status on error
            return self._current_status
    
    async def start_cleaning_cycle(
        self, 
        cycles: Optional[int] = None, 
        speed: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Start a cleaning cycle.
        
        Args:
            cycles: Number of cleaning cycles (default from config)
            speed: Cleaning speed - 'slow', 'normal', 'fast' (default from config)
        """
        if not self._session:
            raise ConnectionError("Not connected to Wiper 6-55")
        
        cycles = cycles or self.default_cycles
        speed = speed or self.default_speed
        
        # Validate speed
        if speed not in [s.value for s in WiperSpeed]:
            raise ValueError(f"Invalid speed '{speed}'. Must be one of: {[s.value for s in WiperSpeed]}")
        
        try:
            payload = {
                "cycles": cycles,
                "speed": speed
            }
            
            async with self._session.post(
                f"{self.base_url}/start_cleaning", 
                json=payload
            ) as response:
                if response.status == 200:
                    result = await response.json()
                    self.logger.info(f"Started cleaning cycle: {cycles} cycles at {speed} speed")
                    return result
                else:
                    error_text = await response.text()
                    raise HardwareError(f"Failed to start cleaning cycle: {response.status} - {error_text}")
                    
        except Exception as e:
            self.logger.error(f"Failed to start cleaning cycle: {e}")
            raise HardwareError(f"Cleaning cycle start failed: {e}")
    
    async def start_drying_cycle(self, dry_time: Optional[float] = None) -> Dict[str, Any]:
        """
        Start a drying cycle.
        
        Args:
            dry_time: Drying time in seconds (default from config)
        """
        if not self._session:
            raise ConnectionError("Not connected to Wiper 6-55")
        
        dry_time = dry_time or self.default_dry_time
        
        try:
            payload = {
                "dry_time": dry_time
            }
            
            async with self._session.post(
                f"{self.base_url}/start_drying", 
                json=payload
            ) as response:
                if response.status == 200:
                    result = await response.json()
                    self.logger.info(f"Started drying cycle: {dry_time} seconds")
                    return result
                else:
                    error_text = await response.text()
                    raise HardwareError(f"Failed to start drying cycle: {response.status} - {error_text}")
                    
        except Exception as e:
            self.logger.error(f"Failed to start drying cycle: {e}")
            raise HardwareError(f"Drying cycle start failed: {e}")
    
    async def stop_operation(self) -> Dict[str, Any]:
        """Stop current operation (cleaning or drying)"""
        if not self._session:
            raise ConnectionError("Not connected to Wiper 6-55")
        
        try:
            async with self._session.post(f"{self.base_url}/stop") as response:
                if response.status == 200:
                    result = await response.json()
                    self.logger.info("Stopped current operation")
                    return result
                else:
                    error_text = await response.text()
                    raise HardwareError(f"Failed to stop operation: {response.status} - {error_text}")
                    
        except Exception as e:
            self.logger.error(f"Failed to stop operation: {e}")
            raise HardwareError(f"Stop operation failed: {e}")
    
    def get_current_status(self) -> WiperStatus:
        """Get the cached current status"""
        return self._current_status