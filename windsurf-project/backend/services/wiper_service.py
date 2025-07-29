"""
Wiper 6-55 service - Specialized service for Wiper 6-55 cleaning operations.
Handles cleaning cycles, drying operations, and maintenance procedures.
"""

import asyncio
import time
from typing import Dict, Any, List, Optional
from dataclasses import dataclass
from enum import Enum

from core.state_manager import AtomicStateManager, RobotState
from core.resource_lock import ResourceLockManager
from core.async_robot_wrapper import AsyncRobotWrapper, MovementCommand
from core.circuit_breaker import circuit_breaker
from core.settings import RoboticsSettings
from core.exceptions import HardwareError, ValidationError, ResourceLockTimeout
from .base import RobotService, ServiceResult, OperationContext
from utils.logger import get_logger


class WiperOperationType(Enum):
    """Types of Wiper operations"""
    CLEANING_CYCLE = "cleaning_cycle"
    DRYING_CYCLE = "drying_cycle"
    FULL_CLEAN_DRY = "full_clean_dry"
    MAINTENANCE = "maintenance"
    STATUS_CHECK = "status_check"


@dataclass
class CleaningParameters:
    """Parameters for cleaning operations"""
    cycles: int = 3
    speed: str = "normal"  # slow, normal, fast
    dry_time: float = 30.0  # seconds
    full_cycle: bool = True  # Include drying


class WiperService(RobotService):
    """
    Service for Wiper 6-55 cleaning operations.
    
    Provides high-level operations for:
    - Automated cleaning cycles
    - Drying operations  
    - Combined clean-dry workflows
    - Maintenance procedures
    """
    
    def __init__(
        self,
        robot_id: str,
        settings: RoboticsSettings,
        state_manager: AtomicStateManager,
        lock_manager: ResourceLockManager,
        async_wrapper: AsyncRobotWrapper
    ):
        super().__init__(
            robot_id=robot_id,
            robot_type="wiper",
            settings=settings,
            state_manager=state_manager,
            lock_manager=lock_manager,
            service_name="WiperService"
        )
        
        self.logger = get_logger("wiper_service")
        
        self.async_wrapper = async_wrapper
        self.robot_config = settings.get_robot_config("wiper")
        
        # Cleaning parameters from config
        cleaning_params = self.robot_config.get("cleaning_params", {})
        self.default_cleaning_params = CleaningParameters(
            cycles=cleaning_params.get("cycles", 3),
            speed=cleaning_params.get("speed", "normal"),
            dry_time=cleaning_params.get("dry_time", 30.0),
            full_cycle=True
        )
        
        # Operation tracking
        self._last_cleaning_time = 0.0
        self._total_cycles_completed = 0
        self._maintenance_required = False
    
    async def _execute_emergency_stop(self) -> bool:
        """Emergency stop implementation for Wiper 6-55"""
        try:
            # Emergency stop through hardware
            if hasattr(self.async_wrapper.robot_driver, 'emergency_stop'):
                await self.async_wrapper.execute_movement(
                    MovementCommand(command_type="emergency_stop")
                )
            
            return True
        except Exception as e:
            self.logger.error(f"Emergency stop failed: {e}")
            return False
    
    @circuit_breaker("wiper_cleaning", failure_threshold=3, recovery_timeout=60)
    async def start_cleaning_cycle(
        self,
        cycles: Optional[int] = None,
        speed: Optional[str] = None,
        include_drying: bool = True,
        dry_time: Optional[float] = None
    ) -> ServiceResult[Dict[str, Any]]:
        """
        Start a cleaning cycle with optional drying.
        
        Args:
            cycles: Number of cleaning cycles (default from config)
            speed: Cleaning speed - 'slow', 'normal', 'fast'
            include_drying: Whether to include drying phase
            dry_time: Drying time in seconds (if include_drying=True)
        """
        # Use defaults if not specified
        cycles = cycles or self.default_cleaning_params.cycles
        speed = speed or self.default_cleaning_params.speed
        dry_time = dry_time or self.default_cleaning_params.dry_time
        
        context = OperationContext(
            operation_id=f"{self.robot_id}_cleaning_{int(time.time() * 1000)}",
            robot_id=self.robot_id,
            operation_type=WiperOperationType.FULL_CLEAN_DRY.value if include_drying else WiperOperationType.CLEANING_CYCLE.value,
            timeout=self.settings.operation_timeout,
            metadata={
                "cycles": cycles,
                "speed": speed,
                "include_drying": include_drying,
                "dry_time": dry_time
            }
        )
        
        async def _cleaning_sequence():
            # Ensure robot is ready
            await self.ensure_robot_ready()
            
            # Update state to busy
            await self.update_robot_state(
                RobotState.BUSY,
                reason=f"Starting cleaning cycle: {cycles} cycles at {speed} speed"
            )
            
            results = {}
            
            try:
                # Phase 1: Cleaning
                self.logger.info(f"Starting cleaning phase: {cycles} cycles at {speed} speed")
                
                cleaning_command = MovementCommand(
                    command_type="start_cleaning_cycle",
                    parameters={
                        "cycles": cycles,
                        "speed": speed
                    }
                )
                
                cleaning_result = await self.async_wrapper.execute_movement(cleaning_command)
                results['cleaning'] = cleaning_result
                
                # Monitor cleaning progress
                await self._monitor_cleaning_progress(cycles)
                
                # Phase 2: Drying (if requested)
                if include_drying:
                    self.logger.info(f"Starting drying phase: {dry_time} seconds")
                    
                    await self.update_robot_state(
                        RobotState.BUSY,
                        reason=f"Drying cycle in progress: {dry_time}s remaining"
                    )
                    
                    drying_command = MovementCommand(
                        command_type="start_drying_cycle",
                        parameters={
                            "dry_time": dry_time
                        }
                    )
                    
                    drying_result = await self.async_wrapper.execute_movement(drying_command)
                    results['drying'] = drying_result
                    
                    # Monitor drying progress
                    await self._monitor_drying_progress(dry_time)
                
                # Update completion statistics
                self._last_cleaning_time = time.time()
                self._total_cycles_completed += cycles
                
                # Update state to idle
                await self.update_robot_state(
                    RobotState.IDLE,
                    reason="Cleaning cycle completed successfully"
                )
                
                results.update({
                    'total_cycles': cycles,
                    'speed': speed,
                    'included_drying': include_drying,
                    'dry_time': dry_time if include_drying else 0,
                    'completion_time': time.time(),
                    'total_cycles_completed': self._total_cycles_completed
                })
                
                return results
                
            except Exception as e:
                await self.update_robot_state(
                    RobotState.ERROR,
                    reason=f"Cleaning cycle failed: {str(e)}"
                )
                raise
        
        return await self.execute_operation(context, _cleaning_sequence)
    
    async def start_drying_cycle(
        self,
        dry_time: Optional[float] = None
    ) -> ServiceResult[Dict[str, Any]]:
        """
        Start a standalone drying cycle.
        
        Args:
            dry_time: Drying time in seconds (default from config)
        """
        dry_time = dry_time or self.default_cleaning_params.dry_time
        
        context = OperationContext(
            operation_id=f"{self.robot_id}_drying_{int(time.time() * 1000)}",
            robot_id=self.robot_id,
            operation_type=WiperOperationType.DRYING_CYCLE.value,
            timeout=dry_time + self.settings.operation_timeout,  # Add buffer time
            metadata={"dry_time": dry_time}
        )
        
        async def _drying_sequence():
            await self.ensure_robot_ready()
            
            await self.update_robot_state(
                RobotState.BUSY,
                reason=f"Drying cycle in progress: {dry_time}s"
            )
            
            try:
                drying_command = MovementCommand(
                    command_type="start_drying_cycle",
                    parameters={"dry_time": dry_time}
                )
                
                result = await self.async_wrapper.execute_movement(drying_command)
                
                # Monitor drying progress
                await self._monitor_drying_progress(dry_time)
                
                await self.update_robot_state(
                    RobotState.IDLE,
                    reason="Drying cycle completed"
                )
                
                return {
                    'dry_time': dry_time,
                    'completion_time': time.time(),
                    'result': result
                }
                
            except Exception as e:
                await self.update_robot_state(
                    RobotState.ERROR,
                    reason=f"Drying cycle failed: {str(e)}"
                )
                raise
        
        return await self.execute_operation(context, _drying_sequence)
    
    async def stop_current_operation(self) -> ServiceResult[Dict[str, Any]]:
        """Stop any current cleaning or drying operation"""
        context = OperationContext(
            operation_id=f"{self.robot_id}_stop_{int(time.time() * 1000)}",
            robot_id=self.robot_id,
            operation_type="stop_operation",
            timeout=30.0
        )
        
        async def _stop_sequence():
            self.logger.info("Stopping current Wiper operation")
            
            stop_command = MovementCommand(
                command_type="stop_operation",
                parameters={}
            )
            
            result = await self.async_wrapper.execute_movement(stop_command)
            
            await self.update_robot_state(
                RobotState.IDLE,
                reason="Operation stopped by user"
            )
            
            return {
                'stopped_at': time.time(),
                'result': result
            }
        
        return await self.execute_operation(context, _stop_sequence)
    
    async def get_detailed_status(self) -> ServiceResult[Dict[str, Any]]:
        """Get detailed status including operational statistics"""
        try:
            # Get hardware status
            status_command = MovementCommand(
                command_type="get_status",
                parameters={}
            )
            
            hardware_status = await self.async_wrapper.execute_movement(status_command)
            
            # Get robot state
            robot_info = await self.state_manager.get_robot_state(self.robot_id)
            
            detailed_status = {
                'hardware_status': hardware_status,
                'robot_state': robot_info.current_state.value if robot_info else 'unknown',
                'last_cleaning_time': self._last_cleaning_time,
                'total_cycles_completed': self._total_cycles_completed,
                'maintenance_required': self._maintenance_required,
                'default_parameters': {
                    'cycles': self.default_cleaning_params.cycles,
                    'speed': self.default_cleaning_params.speed,
                    'dry_time': self.default_cleaning_params.dry_time
                }
            }
            
            return ServiceResult.success_result(detailed_status)
            
        except Exception as e:
            return ServiceResult.error_result(
                error=f"Failed to get detailed status: {str(e)}",
                error_code="STATUS_QUERY_FAILED"
            )
    
    async def _monitor_cleaning_progress(self, total_cycles: int) -> None:
        """Monitor cleaning progress and update status"""
        monitoring_interval = 5.0  # seconds
        start_time = time.time()
        
        while True:
            try:
                # Get current status
                status_command = MovementCommand(
                    command_type="get_status",
                    parameters={}
                )
                
                status = await self.async_wrapper.execute_movement(status_command)
                
                if status and status.get('state') == 'cleaning':
                    current_cycle = status.get('current_cycle', 0)
                    
                    # Update robot state with progress
                    progress_reason = f"Cleaning cycle {current_cycle}/{total_cycles} in progress"
                    await self.update_robot_state(
                        RobotState.BUSY,
                        reason=progress_reason
                    )
                    
                    self.logger.debug(f"Cleaning progress: cycle {current_cycle}/{total_cycles}")
                    
                elif status and status.get('state') in ['idle', 'drying']:
                    # Cleaning phase completed
                    break
                    
                elif status and status.get('state') == 'error':
                    error_msg = status.get('error_message', 'Unknown error')
                    raise HardwareError(f"Cleaning failed: {error_msg}", robot_id=self.robot_id)
                
                await asyncio.sleep(monitoring_interval)
                
                # Timeout check (generous timeout for cleaning)
                if time.time() - start_time > (total_cycles * 60 + 300):  # 1 min per cycle + 5 min buffer
                    raise TimeoutError(f"Cleaning monitoring timed out after {total_cycles} cycles")
                    
            except Exception as e:
                self.logger.error(f"Error monitoring cleaning progress: {e}")
                raise
    
    async def _monitor_drying_progress(self, dry_time: float) -> None:
        """Monitor drying progress and update status"""
        monitoring_interval = 10.0  # seconds
        start_time = time.time()
        
        while True:
            try:
                # Get current status
                status_command = MovementCommand(
                    command_type="get_status", 
                    parameters={}
                )
                
                status = await self.async_wrapper.execute_movement(status_command)
                
                if status and status.get('state') == 'drying':
                    remaining_time = status.get('remaining_dry_time', 0)
                    
                    # Update robot state with remaining time
                    progress_reason = f"Drying: {remaining_time:.0f}s remaining"
                    await self.update_robot_state(
                        RobotState.BUSY,
                        reason=progress_reason
                    )
                    
                    self.logger.debug(f"Drying progress: {remaining_time:.0f}s remaining")
                    
                elif status and status.get('state') == 'idle':
                    # Drying completed
                    break
                    
                elif status and status.get('state') == 'error':
                    error_msg = status.get('error_message', 'Unknown error')
                    raise HardwareError(f"Drying failed: {error_msg}", robot_id=self.robot_id)
                
                await asyncio.sleep(monitoring_interval)
                
                # Timeout check
                if time.time() - start_time > (dry_time + 120):  # dry_time + 2 min buffer
                    raise TimeoutError(f"Drying monitoring timed out after {dry_time}s")
                    
            except Exception as e:
                self.logger.error(f"Error monitoring drying progress: {e}")
                raise
    
    def get_operational_statistics(self) -> Dict[str, Any]:
        """Get operational statistics"""
        return {
            'total_cycles_completed': self._total_cycles_completed,
            'last_cleaning_time': self._last_cleaning_time,
            'maintenance_required': self._maintenance_required,
            'uptime_since_last_cleaning': time.time() - self._last_cleaning_time if self._last_cleaning_time > 0 else 0
        }