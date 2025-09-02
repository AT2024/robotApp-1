"""
Fake Mecademic Server for Testing.

Simulates Mecademic robot behavior on control and monitor ports
for integration testing without hardware dependency.
"""

import asyncio
import time
import json
import math
from typing import Dict, Any, Optional, Set, List, Tuple
from dataclasses import dataclass, field
from enum import Enum
from utils.logger import get_logger

logger = get_logger("fake_meca_server")


@dataclass
class FakeRobotState:
    """Internal state of fake robot."""
    
    # Robot state
    is_activated: bool = False
    is_homed: bool = False
    is_in_error: bool = False
    error_code: Optional[int] = None
    is_paused: bool = False
    is_moving: bool = False
    
    # Position (mm and degrees)
    x: float = 0.0
    y: float = 0.0
    z: float = 200.0  # Start at safe height
    alpha: float = 0.0
    beta: float = 0.0
    gamma: float = 0.0
    
    # Movement parameters
    joint_vel: float = 25.0  # Percentage
    joint_acc: float = 25.0  # Percentage
    
    # Movement simulation
    target_x: Optional[float] = None
    target_y: Optional[float] = None
    target_z: Optional[float] = None
    target_alpha: Optional[float] = None
    target_beta: Optional[float] = None
    target_gamma: Optional[float] = None
    move_start_time: Optional[float] = None
    move_duration: Optional[float] = None
    
    def is_at_target(self, tolerance: float = 1.0) -> bool:
        """Check if robot is at target position within tolerance."""
        if None in (self.target_x, self.target_y, self.target_z):
            return True
        
        dx = abs(self.x - self.target_x)
        dy = abs(self.y - self.target_y) 
        dz = abs(self.z - self.target_z)
        
        return dx < tolerance and dy < tolerance and dz < tolerance
    
    def update_position(self):
        """Update position during movement simulation."""
        if not self.is_moving or None in (self.target_x, self.target_y, self.target_z):
            return
        
        if self.move_start_time is None or self.move_duration is None:
            return
        
        elapsed = time.time() - self.move_start_time
        progress = min(1.0, elapsed / self.move_duration)
        
        # Linear interpolation to target
        start_x, start_y, start_z = self.x, self.y, self.z
        
        # Smooth motion using sine curve
        smooth_progress = 0.5 * (1 - math.cos(progress * math.pi))
        
        self.x = start_x + (self.target_x - start_x) * smooth_progress
        self.y = start_y + (self.target_y - start_y) * smooth_progress
        self.z = start_z + (self.target_z - start_z) * smooth_progress
        
        # Update orientations similarly
        if self.target_alpha is not None:
            start_alpha = self.alpha
            self.alpha = start_alpha + (self.target_alpha - start_alpha) * smooth_progress
        
        if self.target_beta is not None:
            start_beta = self.beta
            self.beta = start_beta + (self.target_beta - start_beta) * smooth_progress
        
        if self.target_gamma is not None:
            start_gamma = self.gamma
            self.gamma = start_gamma + (self.target_gamma - start_gamma) * smooth_progress
        
        # Check if movement is complete
        if progress >= 1.0 or self.is_at_target():
            self.is_moving = False
            self.target_x = None
            self.target_y = None
            self.target_z = None
            self.target_alpha = None
            self.target_beta = None
            self.target_gamma = None
            logger.debug("Fake robot reached target position")


class FakeMecaServer:
    """
    Fake Mecademic server implementation.
    
    Simulates robot behavior on dual TCP connections:
    - Control port: Receives ASCII commands
    - Monitor port: Sends periodic status updates
    """
    
    def __init__(self, host: str = "127.0.0.1", control_port: int = 10010, monitor_port: int = 10011):
        self.host = host
        self.control_port = control_port
        self.monitor_port = monitor_port
        
        # Robot state
        self.state = FakeRobotState()
        
        # Server state
        self.running = False
        self.control_server: Optional[asyncio.Server] = None
        self.monitor_server: Optional[asyncio.Server] = None
        
        # Connected clients
        self.control_clients: Set[asyncio.StreamWriter] = set()
        self.monitor_clients: Set[asyncio.StreamWriter] = set()
        
        # Background tasks
        self.position_update_task: Optional[asyncio.Task] = None
        self.status_broadcast_task: Optional[asyncio.Task] = None
        
        logger.info(f"FakeMecaServer initialized on {host}:{control_port}/{monitor_port}")
    
    async def start(self) -> bool:
        """Start the fake robot server."""
        try:
            logger.info("Starting fake Mecademic server...")
            
            # Start control server
            self.control_server = await asyncio.start_server(
                self._handle_control_client,
                self.host,
                self.control_port
            )
            
            # Start monitor server
            self.monitor_server = await asyncio.start_server(
                self._handle_monitor_client,
                self.host,
                self.monitor_port
            )
            
            # Start background tasks
            self.position_update_task = asyncio.create_task(self._position_update_loop())
            self.status_broadcast_task = asyncio.create_task(self._status_broadcast_loop())
            
            self.running = True
            
            logger.info(f"✅ Fake Mecademic server started on {self.host}:{self.control_port}/{self.monitor_port}")
            return True
        
        except Exception as e:
            logger.error(f"Failed to start fake server: {e}")
            await self.stop()
            return False
    
    async def stop(self) -> None:
        """Stop the fake robot server."""
        logger.info("Stopping fake Mecademic server...")
        
        self.running = False
        
        # Stop background tasks
        for task in [self.position_update_task, self.status_broadcast_task]:
            if task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        
        # Close all client connections
        for clients in [self.control_clients, self.monitor_clients]:
            for writer in clients.copy():
                try:
                    writer.close()
                    await writer.wait_closed()
                except Exception:
                    pass
        
        self.control_clients.clear()
        self.monitor_clients.clear()
        
        # Stop servers
        if self.control_server:
            self.control_server.close()
            await self.control_server.wait_closed()
        
        if self.monitor_server:
            self.monitor_server.close()
            await self.monitor_server.wait_closed()
        
        logger.info("Fake Mecademic server stopped")
    
    async def _handle_control_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        """Handle control connection client."""
        client_addr = writer.get_extra_info('peername')
        logger.info(f"Control client connected from {client_addr}")
        
        self.control_clients.add(writer)
        
        try:
            while self.running and not writer.is_closing():
                try:
                    # Read command (null-terminated)
                    data = await asyncio.wait_for(reader.readuntil(b'\0'), timeout=30.0)
                    
                    if not data:
                        break
                    
                    # Process command
                    command = data.decode('ascii', errors='ignore').strip('\0').strip()
                    if command:
                        response = await self._process_command(command)
                        
                        if response:
                            # Send response
                            writer.write(f"{response}\0".encode('ascii'))
                            await writer.drain()
                
                except asyncio.TimeoutError:
                    # Client idle, continue
                    continue
                
                except Exception as e:
                    logger.warning(f"Control client error: {e}")
                    break
        
        finally:
            self.control_clients.discard(writer)
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass
            
            logger.info(f"Control client {client_addr} disconnected")
    
    async def _handle_monitor_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        """Handle monitor connection client."""
        client_addr = writer.get_extra_info('peername')
        logger.info(f"Monitor client connected from {client_addr}")
        
        self.monitor_clients.add(writer)
        
        try:
            # Send initial status
            await self._send_status_to_client(writer)
            
            # Keep connection alive (monitor is receive-only)
            while self.running and not writer.is_closing():
                await asyncio.sleep(1.0)
        
        except Exception as e:
            logger.warning(f"Monitor client error: {e}")
        
        finally:
            self.monitor_clients.discard(writer)
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass
            
            logger.info(f"Monitor client {client_addr} disconnected")
    
    async def _process_command(self, command: str) -> Optional[str]:
        """Process robot command and return response."""
        logger.debug(f"Processing command: {command}")
        
        try:
            # Parse command
            cmd = command.upper().strip()
            
            if cmd == "ACTIVATEROBOT":
                if not self.state.is_in_error:
                    self.state.is_activated = True
                    logger.info("Fake robot activated")
                    return "ACTIVATED"
                else:
                    return "ERROR:CANNOT_ACTIVATE_IN_ERROR"
            
            elif cmd == "DEACTIVATEROBOT":
                self.state.is_activated = False
                self.state.is_homed = False
                logger.info("Fake robot deactivated")
                return "DEACTIVATED"
            
            elif cmd == "HOME":
                if self.state.is_activated and not self.state.is_in_error:
                    # Simulate homing movement
                    await self._start_movement(0.0, 0.0, 200.0, 0.0, 0.0, 0.0, duration=3.0)
                    self.state.is_homed = True
                    logger.info("Fake robot homing started")
                    return "HOMING"
                else:
                    return "ERROR:NOT_ACTIVATED"
            
            elif cmd == "CLEARMOTION":
                self.state.is_moving = False
                self.state.is_paused = False
                self.state.target_x = None
                self.state.target_y = None
                self.state.target_z = None
                logger.info("Fake robot motion cleared")
                return "MOTION_CLEARED"
            
            elif cmd == "PAUSEMOTION":
                if self.state.is_moving:
                    self.state.is_paused = True
                    logger.info("Fake robot motion paused")
                    return "MOTION_PAUSED"
                else:
                    return "NO_MOTION_TO_PAUSE"
            
            elif cmd == "RESUMEMOTION":
                if self.state.is_paused:
                    self.state.is_paused = False
                    logger.info("Fake robot motion resumed")
                    return "MOTION_RESUMED"
                else:
                    return "NO_MOTION_TO_RESUME"
            
            elif cmd == "RESETERROR":
                self.state.is_in_error = False
                self.state.error_code = None
                logger.info("Fake robot error reset")
                return "ERROR_RESET"
            
            elif cmd.startswith("MOVEPOSE("):
                return await self._process_move_command(cmd)
            
            elif cmd.startswith("SETJOINTVEL("):
                return self._process_set_velocity(cmd)
            
            elif cmd.startswith("SETJOINTACC("):
                return self._process_set_acceleration(cmd)
            
            else:
                logger.warning(f"Unknown command: {command}")
                return "ERROR:UNKNOWN_COMMAND"
        
        except Exception as e:
            logger.error(f"Command processing error: {e}")
            return f"ERROR:PROCESSING_FAILED"
    
    async def _process_move_command(self, cmd: str) -> str:
        """Process MovePose command."""
        try:
            # Parse: MOVEPOSE(x,y,z,alpha,beta,gamma)
            params_str = cmd[9:-1]  # Remove "MOVEPOSE(" and ")"
            params = [float(p.strip()) for p in params_str.split(',')]
            
            if len(params) != 6:
                return "ERROR:INVALID_MOVE_PARAMS"
            
            x, y, z, alpha, beta, gamma = params
            
            if not self.state.is_activated or not self.state.is_homed:
                return "ERROR:NOT_READY_FOR_MOVEMENT"
            
            if self.state.is_in_error:
                return "ERROR:ROBOT_IN_ERROR"
            
            # Calculate movement duration based on distance and speed
            distance = math.sqrt(
                (x - self.state.x) ** 2 +
                (y - self.state.y) ** 2 +
                (z - self.state.z) ** 2
            )
            
            # Base duration on distance and velocity
            base_speed = 100.0  # mm/s at 100% velocity
            actual_speed = base_speed * (self.state.joint_vel / 100.0)
            duration = max(0.5, distance / actual_speed)  # Minimum 0.5s
            
            await self._start_movement(x, y, z, alpha, beta, gamma, duration)
            
            logger.info(f"Fake robot moving to ({x}, {y}, {z}) in {duration:.1f}s")
            return "MOVE_STARTED"
        
        except Exception as e:
            logger.error(f"Move command error: {e}")
            return "ERROR:INVALID_MOVE_COMMAND"
    
    def _process_set_velocity(self, cmd: str) -> str:
        """Process SetJointVel command."""
        try:
            # Parse: SETJOINTVEL(velocity)
            velocity_str = cmd[12:-1]  # Remove "SETJOINTVEL(" and ")"
            velocity = float(velocity_str)
            
            if 0.1 <= velocity <= 100.0:
                self.state.joint_vel = velocity
                logger.info(f"Fake robot velocity set to {velocity}%")
                return f"VELOCITY_SET:{velocity}"
            else:
                return "ERROR:INVALID_VELOCITY_RANGE"
        
        except Exception as e:
            logger.error(f"Set velocity error: {e}")
            return "ERROR:INVALID_VELOCITY_COMMAND"
    
    def _process_set_acceleration(self, cmd: str) -> str:
        """Process SetJointAcc command."""
        try:
            # Parse: SETJOINTACC(acceleration)
            acc_str = cmd[12:-1]  # Remove "SETJOINTACC(" and ")"
            acceleration = float(acc_str)
            
            if 0.1 <= acceleration <= 100.0:
                self.state.joint_acc = acceleration
                logger.info(f"Fake robot acceleration set to {acceleration}%")
                return f"ACCELERATION_SET:{acceleration}"
            else:
                return "ERROR:INVALID_ACCELERATION_RANGE"
        
        except Exception as e:
            logger.error(f"Set acceleration error: {e}")
            return "ERROR:INVALID_ACCELERATION_COMMAND"
    
    async def _start_movement(self, x: float, y: float, z: float, 
                            alpha: float, beta: float, gamma: float, 
                            duration: float):
        """Start robot movement simulation."""
        self.state.target_x = x
        self.state.target_y = y
        self.state.target_z = z
        self.state.target_alpha = alpha
        self.state.target_beta = beta
        self.state.target_gamma = gamma
        self.state.move_start_time = time.time()
        self.state.move_duration = duration
        self.state.is_moving = True
        self.state.is_paused = False
    
    async def _position_update_loop(self):
        """Background task to update robot position during movement."""
        try:
            while self.running:
                if self.state.is_moving and not self.state.is_paused:
                    self.state.update_position()
                
                await asyncio.sleep(0.05)  # 20Hz update rate
        
        except asyncio.CancelledError:
            pass
    
    async def _status_broadcast_loop(self):
        """Background task to broadcast status to monitor clients."""
        try:
            while self.running:
                if self.monitor_clients:
                    # Send status to all monitor clients
                    for writer in self.monitor_clients.copy():
                        try:
                            await self._send_status_to_client(writer)
                        except Exception as e:
                            logger.debug(f"Status broadcast failed: {e}")
                            self.monitor_clients.discard(writer)
                
                await asyncio.sleep(0.1)  # 10Hz status updates
        
        except asyncio.CancelledError:
            pass
    
    async def _send_status_to_client(self, writer: asyncio.StreamWriter):
        """Send status messages to a monitor client."""
        try:
            # Mecademic status format (simplified)
            messages = [
                f"[0,{1 if self.state.is_activated else 0}]",  # Activation status
                f"[1,{1 if self.state.is_homed else 0}]",      # Homing status
                f"[2,{1 if self.state.is_in_error else 0}" + 
                (f",{self.state.error_code}" if self.state.error_code else "") + "]",  # Error status
                f"[3,{1 if self.state.is_paused else 0}]",     # Pause status
                f"[4,{0 if self.state.is_moving else 1}]",     # End of cycle (motion complete)
                f"[5,{self.state.x:.3f},{self.state.y:.3f},{self.state.z:.3f},"
                f"{self.state.alpha:.3f},{self.state.beta:.3f},{self.state.gamma:.3f}]"  # Position
            ]
            
            for message in messages:
                writer.write(f"{message}\n".encode('ascii'))
            
            await writer.drain()
        
        except Exception as e:
            logger.debug(f"Send status error: {e}")
            raise
    
    def get_state_info(self) -> Dict[str, Any]:
        """Get current fake robot state information."""
        return {
            "server_running": self.running,
            "host": self.host,
            "control_port": self.control_port,
            "monitor_port": self.monitor_port,
            "control_clients": len(self.control_clients),
            "monitor_clients": len(self.monitor_clients),
            "robot_state": {
                "is_activated": self.state.is_activated,
                "is_homed": self.state.is_homed,
                "is_in_error": self.state.is_in_error,
                "error_code": self.state.error_code,
                "is_paused": self.state.is_paused,
                "is_moving": self.state.is_moving,
                "position": {
                    "x": self.state.x,
                    "y": self.state.y,
                    "z": self.state.z,
                    "alpha": self.state.alpha,
                    "beta": self.state.beta,
                    "gamma": self.state.gamma,
                },
                "parameters": {
                    "joint_vel": self.state.joint_vel,
                    "joint_acc": self.state.joint_acc,
                },
                "target": {
                    "x": self.state.target_x,
                    "y": self.state.target_y,
                    "z": self.state.target_z,
                    "alpha": self.state.target_alpha,
                    "beta": self.state.target_beta,
                    "gamma": self.state.target_gamma,
                } if self.state.target_x is not None else None,
            }
        }
    
    # Context manager support
    
    async def __aenter__(self):
        """Async context manager entry."""
        await self.start()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.stop()


# Standalone execution for testing

async def main():
    """Run fake server for standalone testing."""
    import sys
    import signal
    
    # Parse command line arguments
    host = sys.argv[1] if len(sys.argv) > 1 else "127.0.0.1"
    control_port = int(sys.argv[2]) if len(sys.argv) > 2 else 10010
    monitor_port = int(sys.argv[3]) if len(sys.argv) > 3 else 10011
    
    # Create and start server
    server = FakeMecaServer(host, control_port, monitor_port)
    
    # Handle shutdown signals
    def signal_handler(sig, frame):
        logger.info(f"Received signal {sig}, shutting down...")
        asyncio.create_task(server.stop())
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    try:
        await server.start()
        
        # Keep running until stopped
        while server.running:
            await asyncio.sleep(1.0)
    
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
    
    finally:
        await server.stop()


if __name__ == "__main__":
    asyncio.run(main())