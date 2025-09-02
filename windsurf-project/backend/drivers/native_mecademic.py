"""
Native Mecademic Meca-500 Driver Implementation.

Direct TCP ASCII protocol implementation for Mecademic robots,
providing control and monitoring without external dependencies.
"""

import asyncio
import time
import json
from typing import Optional, Dict, Any, List, Tuple, Callable
from dataclasses import dataclass, field
from enum import Enum
from contextlib import asynccontextmanager
from utils.logger import get_logger

from .transport import BoundTCPClient, TransportConfig

logger = get_logger("native_mecademic")


class RobotState(Enum):
    """Robot operational states."""
    
    DISCONNECTED = "disconnected"
    CONNECTED = "connected"
    ACTIVATED = "activated"
    HOMED = "homed"
    ERROR = "error"
    MOVING = "moving"
    IDLE = "idle"


@dataclass
class RobotPosition:
    """Robot position in Cartesian coordinates."""
    
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    alpha: float = 0.0  # Rotation around X-axis
    beta: float = 0.0   # Rotation around Y-axis
    gamma: float = 0.0  # Rotation around Z-axis
    
    def to_dict(self) -> Dict[str, float]:
        return {
            "x": self.x, "y": self.y, "z": self.z,
            "alpha": self.alpha, "beta": self.beta, "gamma": self.gamma
        }


@dataclass
class RobotStatus:
    """Complete robot status information."""
    
    state: RobotState = RobotState.DISCONNECTED
    position: RobotPosition = field(default_factory=RobotPosition)
    is_activated: bool = False
    is_homed: bool = False
    is_in_error: bool = False
    is_moving: bool = False
    is_paused: bool = False
    error_code: Optional[int] = None
    error_message: Optional[str] = None
    timestamp: float = field(default_factory=time.time)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "state": self.state.value,
            "position": self.position.to_dict(),
            "is_activated": self.is_activated,
            "is_homed": self.is_homed,
            "is_in_error": self.is_in_error,
            "is_moving": self.is_moving,
            "is_paused": self.is_paused,
            "error_code": self.error_code,
            "error_message": self.error_message,
            "timestamp": self.timestamp,
        }


@dataclass
class MecademicConfig:
    """Configuration for Mecademic driver."""
    
    # Connection settings
    robot_ip: str = "192.168.0.100"
    control_port: int = 10000
    monitor_port: int = 10001
    
    # Network binding
    bind_interface: Optional[str] = None
    bind_ip: Optional[str] = None
    
    # Timeouts and retries
    connect_timeout: float = 10.0
    command_timeout: float = 30.0
    status_timeout: float = 5.0
    max_retries: int = 3
    
    # Movement parameters
    default_speed: float = 25.0
    default_acceleration: float = 25.0
    max_speed: float = 100.0
    max_acceleration: float = 100.0
    
    # Gripper parameters
    gripper_force: float = 100.0
    align_speed: float = 20.0
    
    # Monitoring
    status_poll_interval: float = 0.5  # 2Hz
    keepalive_interval: float = 30.0


class NativeMecademicDriver:
    """
    Native Mecademic robot driver with dual TCP connections.
    
    Implements direct ASCII protocol communication:
    - Control connection (port 10000): Send commands
    - Monitor connection (port 10001): Receive status updates
    """
    
    def __init__(self, config: MecademicConfig):
        self.config = config
        
        # Transport clients for dual connections
        transport_config = TransportConfig(
            bind_interface=config.bind_interface,
            bind_ip=config.bind_ip,
            connect_timeout=config.connect_timeout,
        )
        
        self._control_client = BoundTCPClient(transport_config)
        self._monitor_client = BoundTCPClient(transport_config)
        
        # Connection state
        self._connected = False
        self._monitoring = False
        self._monitor_task: Optional[asyncio.Task] = None
        
        # Robot state
        self._status = RobotStatus()
        self._status_callbacks: List[Callable[[RobotStatus], None]] = []
        
        # Command sequencing
        self._command_lock = asyncio.Lock()
        
        # Parameter initialization state
        self._parameters_initialized = False
        
        logger.info(
            f"NativeMecademicDriver initialized for {config.robot_ip}:"
            f"{config.control_port}/{config.monitor_port}"
        )
    
    async def connect(self) -> bool:
        """
        Establish dual connections to robot.
        
        Returns:
            True if both connections successful
        """
        try:
            logger.info(f"Connecting to Mecademic robot at {self.config.robot_ip}")
            
            # Connect control channel
            control_success = await self._control_client.connect(
                self.config.robot_ip, 
                self.config.control_port
            )
            
            if not control_success:
                logger.error("Failed to establish control connection")
                return False
            
            # Connect monitor channel
            monitor_success = await self._monitor_client.connect(
                self.config.robot_ip,
                self.config.monitor_port
            )
            
            if not monitor_success:
                logger.error("Failed to establish monitor connection")
                await self._control_client.disconnect()
                return False
            
            # Update state
            self._connected = True
            self._status.state = RobotState.CONNECTED
            self._status.timestamp = time.time()
            
            # Send essential protocol handshake command for Mecademic communication
            # This is required immediately after TCP connection to establish proper protocol
            logger.info("Sending Mecademic protocol handshake")
            await self._send_command("SetBlending(0)")
            
            # Start monitoring
            await self._start_monitoring()
            
            logger.info("✅ Successfully connected to Mecademic robot")
            return True
        
        except Exception as e:
            logger.error(f"Connection failed: {e}")
            await self.disconnect()
            return False
    
    async def disconnect(self) -> None:
        """Disconnect from robot and cleanup resources."""
        logger.info("Disconnecting from robot")
        
        # Stop monitoring
        await self._stop_monitoring()
        
        # Disconnect transport clients
        if self._control_client:
            await self._control_client.disconnect()
        
        if self._monitor_client:
            await self._monitor_client.disconnect()
        
        # Update state
        self._connected = False
        self._status.state = RobotState.DISCONNECTED
        self._status.timestamp = time.time()
        
        logger.info("Disconnected from robot")
    
    async def _start_monitoring(self) -> None:
        """Start background monitoring task."""
        if self._monitoring:
            return
        
        self._monitoring = True
        self._monitor_task = asyncio.create_task(self._monitor_loop())
        logger.debug("Started monitoring task")
    
    async def _stop_monitoring(self) -> None:
        """Stop background monitoring task."""
        if not self._monitoring:
            return
        
        self._monitoring = False
        
        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
            self._monitor_task = None
        
        logger.debug("Stopped monitoring task")
    
    async def _monitor_loop(self) -> None:
        """Background task for monitoring robot status."""
        try:
            while self._monitoring:
                try:
                    # Read monitoring data
                    if self._monitor_client.is_connected:
                        data = await self._monitor_client.receive(4096)
                        
                        if data:
                            await self._process_monitor_data(data)
                    
                    # Brief pause to prevent busy polling
                    await asyncio.sleep(self.config.status_poll_interval)
                
                except Exception as e:
                    logger.warning(f"Monitor loop error: {e}")
                    await asyncio.sleep(1.0)  # Longer pause on error
        
        except asyncio.CancelledError:
            logger.debug("Monitor loop cancelled")
        
        except Exception as e:
            logger.error(f"Monitor loop failed: {e}")
    
    async def _process_monitor_data(self, data: bytes) -> None:
        """
        Process incoming monitoring data from robot.
        
        Args:
            data: Raw bytes from monitor connection
        """
        try:
            # Decode ASCII data
            text = data.decode('ascii', errors='ignore').strip()
            
            if not text:
                return
            
            # Split multiple messages (newline separated)
            messages = [msg.strip() for msg in text.split('\n') if msg.strip()]
            
            for message in messages:
                await self._parse_status_message(message)
        
        except Exception as e:
            logger.warning(f"Error processing monitor data: {e}")
    
    async def _parse_status_message(self, message: str) -> None:
        """
        Parse individual status message from robot.
        
        Args:
            message: Single line status message
        """
        try:
            # Update timestamp
            self._status.timestamp = time.time()
            
            # Parse common status messages
            if message == '[0]':
                # Robot is deactivated
                self._status.is_activated = False
                self._status.state = RobotState.DISCONNECTED
            elif message == '[1]':
                # Robot is activated
                self._status.is_activated = True
                self._status.state = RobotState.ACTIVATED
            
            elif message.startswith('[1]') and ',' in message:
                # Homing status: [1,0] = not homed, [1,1] = homed
                self._status.is_homed = '[1,1]' in message
                if self._status.is_homed and self._status.is_activated:
                    self._status.state = RobotState.HOMED
            
            elif message.startswith('[2]'):
                # Error status: [2,0] = no error, [2,1] = error
                self._status.is_in_error = '[2,1]' in message
                if self._status.is_in_error:
                    self._status.state = RobotState.ERROR
                    # Parse error code if present
                    if ',' in message:
                        parts = message.split(',')
                        if len(parts) > 2:
                            try:
                                self._status.error_code = int(parts[2].strip('[]'))
                            except ValueError:
                                pass
            
            elif message.startswith('[3]'):
                # Pause status: [3,0] = not paused, [3,1] = paused
                self._status.is_paused = '[3,1]' in message
            
            elif message.startswith('[4]'):
                # End of cycle status: [4,1] = motion complete
                motion_complete = '[4,1]' in message
                self._status.is_moving = not motion_complete
                if motion_complete and not self._status.is_in_error:
                    self._status.state = RobotState.IDLE
                elif self._status.is_moving:
                    self._status.state = RobotState.MOVING
            
            elif message.startswith('[5]'):
                # Position data: [5,x,y,z,alpha,beta,gamma]
                await self._parse_position_data(message)
            
            # Notify status callbacks
            for callback in self._status_callbacks:
                try:
                    callback(self._status)
                except Exception as e:
                    logger.warning(f"Status callback error: {e}")
        
        except Exception as e:
            logger.debug(f"Error parsing status message '{message}': {e}")
    
    async def _parse_position_data(self, message: str) -> None:
        """Parse position data from status message."""
        try:
            # Format: [5,x,y,z,alpha,beta,gamma]
            parts = message.strip('[]').split(',')
            if len(parts) >= 7:
                self._status.position = RobotPosition(
                    x=float(parts[1]),
                    y=float(parts[2]),
                    z=float(parts[3]),
                    alpha=float(parts[4]),
                    beta=float(parts[5]),
                    gamma=float(parts[6]),
                )
        except (ValueError, IndexError) as e:
            logger.debug(f"Error parsing position from '{message}': {e}")
    
    async def _send_command(self, command: str, expect_response: bool = True) -> Optional[str]:
        """
        Send command to robot control connection.
        
        Args:
            command: ASCII command string
            expect_response: Whether to wait for command acknowledgment
            
        Returns:
            Response string if expect_response=True, None otherwise
        """
        if not self._connected or not self._control_client.is_connected:
            raise ConnectionError("Robot not connected")
        
        async with self._command_lock:
            try:
                # Format command with null terminator
                cmd_bytes = f"{command}\0".encode('ascii')
                
                logger.debug(f"Sending command: {command}")
                await self._control_client.send(cmd_bytes)
                
                if expect_response:
                    # Wait for acknowledgment
                    response_data = await asyncio.wait_for(
                        self._control_client.receive(1024),
                        timeout=self.config.command_timeout
                    )
                    
                    if response_data:
                        response = response_data.decode('ascii', errors='ignore').strip('\0')
                        logger.debug(f"Command response: {response}")
                        return response
                
                return None
            
            except asyncio.TimeoutError:
                logger.error(f"Command timeout: {command}")
                raise
            except Exception as e:
                logger.error(f"Command failed '{command}': {e}")
                raise
    
    # Robot Control Commands
    
    async def activate(self) -> bool:
        """Activate the robot for operation."""
        try:
            # Ensure connection is valid before sending command
            if not self.is_connected or not self._control_client or not self._control_client.is_connected:
                logger.warning("Connection lost before activation, attempting to reconnect...")
                reconnect_success = await self.connect()
                if not reconnect_success:
                    logger.error("Failed to reconnect before activation")
                    return False
            
            await self._send_command("ActivateRobot")
            logger.info("Robot activation command sent")
            
            # Wait for activation confirmation
            start_time = time.time()
            while time.time() - start_time < 10.0:  # 10 second timeout
                if self._status.is_activated:
                    logger.info("✅ Robot activated successfully")
                    return True
                await asyncio.sleep(0.1)
            
            logger.warning("Robot activation timeout")
            return False
        
        except Exception as e:
            logger.error(f"Robot activation failed: {e}")
            # If activation failed due to connection issue, try to reconnect for next attempt
            if "closed" in str(e).lower() or "connection" in str(e).lower():
                logger.info("Detected connection issue, will attempt reconnection on next command")
                self._connected = False
            return False
    
    async def deactivate(self) -> bool:
        """Deactivate the robot."""
        try:
            await self._send_command("DeactivateRobot")
            logger.info("Robot deactivation command sent")
            return True
        
        except Exception as e:
            logger.error(f"Robot deactivation failed: {e}")
            return False
    
    async def home(self) -> bool:
        """Home the robot to reference position."""
        try:
            # Ensure connection is valid before sending command
            if not self.is_connected or not self._control_client or not self._control_client.is_connected:
                logger.warning("Connection lost before homing, attempting to reconnect...")
                reconnect_success = await self.connect()
                if not reconnect_success:
                    logger.error("Failed to reconnect before homing")
                    return False
            
            await self._send_command("Home")
            logger.info("Robot homing command sent")
            
            # Wait for homing completion
            start_time = time.time()
            while time.time() - start_time < 60.0:  # 60 second timeout
                if self._status.is_homed:
                    logger.info("✅ Robot homed successfully")
                    return True
                await asyncio.sleep(0.1)
            
            logger.warning("Robot homing timeout")
            return False
        
        except Exception as e:
            logger.error(f"Robot homing failed: {e}")
            # If homing failed due to connection issue, try to reconnect for next attempt
            if "closed" in str(e).lower() or "connection" in str(e).lower():
                logger.info("Detected connection issue during homing, will attempt reconnection on next command")
                self._connected = False
            return False
    
    async def clear_motion(self) -> bool:
        """Clear all queued motion commands."""
        try:
            await self._send_command("ClearMotion")
            logger.info("Motion queue cleared")
            return True
        
        except Exception as e:
            logger.error(f"Clear motion failed: {e}")
            return False
    
    async def pause_motion(self) -> bool:
        """Pause robot motion."""
        try:
            await self._send_command("PauseMotion")
            logger.info("Robot motion paused")
            return True
        
        except Exception as e:
            logger.error(f"Pause motion failed: {e}")
            return False
    
    async def resume_motion(self) -> bool:
        """Resume robot motion."""
        try:
            await self._send_command("ResumeMotion")
            logger.info("Robot motion resumed")
            return True
        
        except Exception as e:
            logger.error(f"Resume motion failed: {e}")
            return False
    
    async def reset_error(self) -> bool:
        """Reset robot error state."""
        try:
            await self._send_command("ResetError")
            logger.info("Robot error reset")
            return True
        
        except Exception as e:
            logger.error(f"Reset error failed: {e}")
            return False
    
    async def move_pose(self, x: float, y: float, z: float, 
                       alpha: float, beta: float, gamma: float) -> bool:
        """
        Move to specified Cartesian pose.
        
        Args:
            x, y, z: Cartesian coordinates (mm)
            alpha, beta, gamma: Orientation angles (degrees)
        """
        try:
            command = f"MovePose({x:.3f},{y:.3f},{z:.3f},{alpha:.3f},{beta:.3f},{gamma:.3f})"
            await self._send_command(command)
            logger.info(f"Move pose command sent: ({x}, {y}, {z}, {alpha}, {beta}, {gamma})")
            return True
        
        except Exception as e:
            logger.error(f"Move pose failed: {e}")
            return False
    
    async def set_joint_vel(self, velocity: float) -> bool:
        """Set joint velocity percentage (0-100)."""
        try:
            velocity = max(0, min(100, velocity))  # Clamp to valid range
            await self._send_command(f"SetJointVel({velocity:.1f})")
            logger.info(f"Joint velocity set to {velocity}%")
            return True
        
        except Exception as e:
            logger.error(f"Set joint velocity failed: {e}")
            return False
    
    async def set_joint_acc(self, acceleration: float) -> bool:
        """Set joint acceleration percentage (0-100)."""
        try:
            acceleration = max(0, min(100, acceleration))  # Clamp to valid range
            await self._send_command(f"SetJointAcc({acceleration:.1f})")
            logger.info(f"Joint acceleration set to {acceleration}%")
            return True
        
        except Exception as e:
            logger.error(f"Set joint acceleration failed: {e}")
            return False
    
    async def wait_idle(self, timeout: float = 30.0) -> bool:
        """
        Wait for robot to finish motion using existing status monitoring.
        
        Args:
            timeout: Maximum time to wait in seconds
            
        Returns:
            True if robot becomes idle, False if timeout
        """
        start_time = time.time()
        while time.time() - start_time < timeout:
            if not self._status.is_moving and self._status.state == RobotState.IDLE:
                logger.debug(f"Robot motion completed after {time.time() - start_time:.2f}s")
                return True
            await asyncio.sleep(0.1)
        
        logger.warning(f"Wait idle timeout after {timeout}s")
        return False
    
    def GripperOpen(self) -> None:
        """Synchronous gripper open using existing command infrastructure."""
        if not self._connected:
            logger.warning("Cannot open gripper - robot not connected")
            return
        
        # Create task to send command asynchronously
        asyncio.create_task(self._send_command("GripperOpen", expect_response=False))
        logger.debug("Gripper open command queued")
    
    def GripperClose(self) -> None:
        """Synchronous gripper close using existing command infrastructure."""
        if not self._connected:
            logger.warning("Cannot close gripper - robot not connected")
            return
        
        # Create task to send command asynchronously  
        asyncio.create_task(self._send_command("GripperClose", expect_response=False))
        logger.debug("Gripper close command queued")
    
    def MoveGripper(self, width: float) -> None:
        """Move gripper to specified width."""
        if not self._connected:
            logger.warning("Cannot move gripper - robot not connected")
            return
        
        # Create task to send command asynchronously
        asyncio.create_task(self._send_command(f"MoveGripper({width:.2f})", expect_response=False))
        logger.debug(f"Gripper move command queued: width={width}")
    
    async def set_gripper_force(self, force: float) -> bool:
        """Set gripper force."""
        try:
            force = max(0, min(100, force))  # Clamp to valid range
            await self._send_command(f"SetGripperForce({force:.1f})")
            logger.info(f"Gripper force set to {force}%")
            return True
        
        except Exception as e:
            logger.error(f"Set gripper force failed: {e}")
            return False
    
    async def set_torque_limits(self, *limits) -> bool:
        """Set torque limits for all joints."""
        try:
            if len(limits) == 6:
                limits_str = ','.join(str(limit) for limit in limits)
                await self._send_command(f"SetTorqueLimits({limits_str})")
                logger.info(f"Torque limits set to {limits}")
                return True
            else:
                logger.error("SetTorqueLimits requires exactly 6 values")
                return False
        
        except Exception as e:
            logger.error(f"Set torque limits failed: {e}")
            return False
    
    async def set_torque_limits_cfg(self, option1: int, option2: int) -> bool:
        """Set torque limits configuration."""
        try:
            await self._send_command(f"SetTorqueLimitsCfg({option1},{option2})")
            logger.info(f"Torque limits config set to {option1},{option2}")
            return True
        
        except Exception as e:
            logger.error(f"Set torque limits config failed: {e}")
            return False
    
    async def set_blending(self, value: float) -> bool:
        """Set motion blending."""
        try:
            await self._send_command(f"SetBlending({value:.1f})")
            logger.info(f"Blending set to {value}")
            return True
        
        except Exception as e:
            logger.error(f"Set blending failed: {e}")
            return False
    
    async def set_conf(self, a: int, b: int, c: int) -> bool:
        """Set robot configuration."""
        try:
            await self._send_command(f"SetConf({a},{b},{c})")
            logger.info(f"Configuration set to {a},{b},{c}")
            return True
        
        except Exception as e:
            logger.error(f"Set configuration failed: {e}")
            return False
    
    async def initialize_robot_parameters(self) -> bool:
        """
        Initialize robot with parameters using configuration values.
        
        This replicates the exact initialization sequence from the working code
        using environment/config values instead of hardcoded numbers.
        
        Should only be called AFTER robot is activated and homed.
        """
        # Check if already initialized to prevent duplicate calls
        if self._parameters_initialized:
            logger.debug("Robot parameters already initialized, skipping")
            return True
            
        try:
            logger.info("Initializing robot parameters after activation and homing...")
            
            # Use config values from MecademicConfig
            # Set gripper force from config
            await self.set_gripper_force(self.config.gripper_force)
            
            # Set joint acceleration using config default
            await self.set_joint_acc(self.config.default_acceleration)
            
            # Set torque limits (from InitialStatements - these are Mecademic specific constants)
            await self.set_torque_limits(40, 40, 40, 40, 40, 40)
            
            # Set torque limits configuration (Mecademic specific constants)
            await self.set_torque_limits_cfg(2, 1)
            
            # Set blending off (standard initialization)
            await self.set_blending(0)
            
            # Set joint velocity to align speed from config
            await self.set_joint_vel(self.config.align_speed)
            
            # Set robot configuration (standard Mecademic configuration)
            await self.set_conf(1, 1, 1)
            
            # Open gripper and delay (from InitialStatements)
            await self._send_command("GripperOpen")
            await asyncio.sleep(1.0)  # Standard delay after gripper open
            
            # Mark as initialized
            self._parameters_initialized = True
            
            logger.info("✅ Robot parameters initialized successfully")
            return True
        
        except Exception as e:
            logger.error(f"Robot parameter initialization failed: {e}")
            return False
    
    # Status and Information
    
    @property
    def is_connected(self) -> bool:
        """Check if robot is connected."""
        return self._connected
    
    @property
    def status(self) -> RobotStatus:
        """Get current robot status."""
        return self._status
    
    def add_status_callback(self, callback: Callable[[RobotStatus], None]) -> None:
        """Add callback for status updates."""
        self._status_callbacks.append(callback)
    
    def remove_status_callback(self, callback: Callable[[RobotStatus], None]) -> None:
        """Remove status callback."""
        if callback in self._status_callbacks:
            self._status_callbacks.remove(callback)
    
    def get_robot_instance(self):
        """
        Get robot instance for service layer compatibility.
        
        This method provides interface compatibility with the legacy mecademicpy
        driver. Returns self when connected, None when disconnected.
        
        Returns:
            self if robot is connected and ready, None otherwise
        """
        if self.is_connected:
            return self
        return None
    
    @property
    def connection_info(self) -> Dict[str, Any]:
        """Get detailed connection information."""
        return {
            "connected": self.is_connected,
            "robot_ip": self.config.robot_ip,
            "control_port": self.config.control_port,
            "monitor_port": self.config.monitor_port,
            "bind_interface": self.config.bind_interface,
            "bind_ip": self.config.bind_ip,
            "monitoring": self._monitoring,
            "control_transport": self._control_client.connection_info,
            "monitor_transport": self._monitor_client.connection_info,
            "status": self._status.to_dict(),
        }
    
    @asynccontextmanager
    async def robot_connection(self):
        """
        Context manager for automatic connection management.
        
        Usage:
            async with driver.robot_connection():
                await driver.activate()
                await driver.home()
                await driver.move_pose(100, 0, 200, 0, 0, 0)
        """
        try:
            if not await self.connect():
                raise ConnectionError(f"Failed to connect to robot {self.config.robot_ip}")
            yield self
        finally:
            await self.disconnect()


# Factory functions

def create_mecademic_driver(
    robot_ip: str = "192.168.0.100",
    bind_interface: Optional[str] = None,
    bind_ip: Optional[str] = None,
    **kwargs
) -> NativeMecademicDriver:
    """
    Create Mecademic driver with common configuration.
    
    Args:
        robot_ip: Robot IP address
        bind_interface: Network interface to bind to
        bind_ip: IP address to bind to
        **kwargs: Additional configuration options
        
    Returns:
        Configured NativeMecademicDriver instance
    """
    config = MecademicConfig(
        robot_ip=robot_ip,
        bind_interface=bind_interface,
        bind_ip=bind_ip,
        **kwargs
    )
    return NativeMecademicDriver(config)


async def test_robot_connection(
    robot_ip: str = "192.168.0.100",
    bind_interface: Optional[str] = None,
    timeout: float = 10.0
) -> Dict[str, Any]:
    """
    Test connection to Mecademic robot.
    
    Args:
        robot_ip: Robot IP address
        bind_interface: Interface to bind to
        timeout: Connection timeout
        
    Returns:
        Test results dictionary
    """
    config = MecademicConfig(
        robot_ip=robot_ip,
        bind_interface=bind_interface,
        connect_timeout=timeout
    )
    
    driver = NativeMecademicDriver(config)
    
    start_time = time.time()
    
    try:
        success = await driver.connect()
        connect_time = time.time() - start_time
        
        result = {
            "success": success,
            "connect_time": connect_time,
            "robot_ip": robot_ip,
            "bind_interface": bind_interface,
        }
        
        if success:
            # Get status after brief wait
            await asyncio.sleep(0.5)
            result["status"] = driver.status.to_dict()
            result["connection_info"] = driver.connection_info
        
        return result
    
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "connect_time": time.time() - start_time,
            "robot_ip": robot_ip,
            "bind_interface": bind_interface,
        }
    
    finally:
        await driver.disconnect()