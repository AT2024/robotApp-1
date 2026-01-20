"""
Robot simulators implementing driver protocols.
These MUST match the real driver APIs exactly.
"""
from typing import List, Dict, Any, Optional


class MecaSimulator:
    """Simulates Mecademic robot for testing without hardware."""

    def __init__(self):
        self._connected = False
        self._activated = False
        self._homed = False
        self._error_state = False
        self._error_code: Optional[int] = None
        self._paused = False
        self._joints = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
        self._gripper_open = True
        self._motion_queue: List[Dict] = []  # Robot's internal motion buffer
        self._command_history: List[tuple] = []  # All commands for verification

    # ===== Connection Methods =====
    async def connect(self, ip: str) -> bool:
        self._command_history.append(('connect', ip))
        self._connected = True
        return True

    async def disconnect(self) -> bool:
        self._command_history.append(('disconnect',))
        self._connected = False
        self._activated = False
        self._homed = False
        return True

    # ===== Status Methods =====
    async def get_status(self) -> Dict[str, Any]:
        return {
            'activation_status': self._activated,
            'homing_status': self._homed,
            'error_status': self._error_state,
            'error_code': self._error_code,
            'pause_motion_status': self._paused
        }

    async def get_joints(self) -> List[float]:
        return self._joints.copy()

    # ===== Activation/Homing =====
    async def activate_robot(self) -> None:
        self._command_history.append(('activate_robot',))
        if not self._connected:
            raise Exception("Not connected")
        self._activated = True

    async def home_robot(self) -> None:
        self._command_history.append(('home_robot',))
        if not self._activated:
            raise Exception("Not activated")
        self._homed = True

    async def wait_homed(self, timeout: float = 30.0) -> None:
        self._command_history.append(('wait_homed', timeout))

    # ===== Movement Commands (sync - queued in motion buffer) =====
    def MovePose(self, x: float, y: float, z: float, rx: float, ry: float, rz: float) -> None:
        self._command_history.append(('MovePose', [x, y, z, rx, ry, rz]))
        self._motion_queue.append({'type': 'MovePose', 'params': [x, y, z, rx, ry, rz]})

    def MoveJoints(self, *joints: float) -> None:
        self._command_history.append(('MoveJoints', list(joints)))
        self._motion_queue.append({'type': 'MoveJoints', 'params': list(joints)})

    def Delay(self, duration: float) -> None:
        """CRITICAL: Queues delay in robot buffer, NOT Python sleep."""
        self._command_history.append(('Delay', duration))
        self._motion_queue.append({'type': 'Delay', 'duration': duration})

    def GripperOpen(self) -> None:
        self._command_history.append(('GripperOpen',))
        self._motion_queue.append({'type': 'GripperOpen'})
        self._gripper_open = True

    def GripperClose(self) -> None:
        self._command_history.append(('GripperClose',))
        self._motion_queue.append({'type': 'GripperClose'})
        self._gripper_open = False

    # ===== Configuration Commands =====
    def SetGripperForce(self, force: int) -> None:
        self._command_history.append(('SetGripperForce', force))

    def SetJointAcc(self, acc: int) -> None:
        self._command_history.append(('SetJointAcc', acc))

    def SetJointVel(self, vel: int) -> None:
        self._command_history.append(('SetJointVel', vel))

    def SetTorqueLimits(self, *limits: float) -> None:
        self._command_history.append(('SetTorqueLimits', list(limits)))

    def SetTorqueLimitsCfg(self, *cfg: int) -> None:
        self._command_history.append(('SetTorqueLimitsCfg', list(cfg)))

    def SetBlending(self, blending: int) -> None:
        self._command_history.append(('SetBlending', blending))

    def SetConf(self, *conf: int) -> None:
        self._command_history.append(('SetConf', list(conf)))

    # ===== Error Handling =====
    async def reset_error(self) -> None:
        self._command_history.append(('reset_error',))
        self._error_state = False
        self._error_code = None

    async def resume_motion(self) -> None:
        self._command_history.append(('resume_motion',))
        self._paused = False

    # ===== Test Helpers =====
    def get_command_history(self) -> List[tuple]:
        """Return all commands for verification."""
        return self._command_history.copy()

    def get_motion_queue(self) -> List[Dict]:
        """Return motion buffer for sequence verification."""
        return self._motion_queue.copy()

    def clear_history(self) -> None:
        """Reset command tracking for next test."""
        self._command_history.clear()
        self._motion_queue.clear()

    def inject_error(self, error_code: int = 1042) -> None:
        """Simulate robot error."""
        self._error_state = True
        self._error_code = error_code

    def set_joints(self, joints: List[float]) -> None:
        """Set joint positions for testing."""
        self._joints = joints.copy()

    def is_gripper_open(self) -> bool:
        """Check gripper state."""
        return self._gripper_open


class OT2Simulator:
    """Simulates OT-2 robot for testing without hardware."""

    def __init__(self):
        self._connected = False
        self._homed = False
        self._error_state = False
        self._runs: Dict[str, Dict] = {}
        self._command_history: List[tuple] = []
        self._run_counter = 0

    # ===== Connection Methods =====
    async def connect(self) -> bool:
        self._command_history.append(('connect',))
        self._connected = True
        return True

    async def disconnect(self) -> bool:
        self._command_history.append(('disconnect',))
        self._connected = False
        return True

    # ===== Status Methods =====
    async def get_health(self) -> Dict[str, Any]:
        return {
            'status': 'healthy' if self._connected else 'disconnected',
            'api_version': '2.0.0',
            'robot_model': 'OT-2 Simulator'
        }

    async def get_runs(self) -> List[Dict[str, Any]]:
        return list(self._runs.values())

    # ===== Protocol Execution =====
    async def create_run(self, protocol_id: str) -> Dict[str, Any]:
        self._command_history.append(('create_run', protocol_id))
        self._run_counter += 1
        run_id = f"run_{self._run_counter}"
        self._runs[run_id] = {
            'id': run_id,
            'protocol_id': protocol_id,
            'status': 'idle',
            'current_step': 0
        }
        return self._runs[run_id]

    async def execute_run(self, run_id: str) -> Dict[str, Any]:
        self._command_history.append(('execute_run', run_id))
        if run_id not in self._runs:
            raise ValueError(f"Run {run_id} not found")
        self._runs[run_id]['status'] = 'running'
        return self._runs[run_id]

    async def get_run_status(self, run_id: str) -> Dict[str, Any]:
        if run_id not in self._runs:
            raise ValueError(f"Run {run_id} not found")
        return self._runs[run_id]

    # ===== Commands =====
    async def home(self) -> None:
        self._command_history.append(('home',))
        self._homed = True

    async def stop(self) -> None:
        self._command_history.append(('stop',))
        for run in self._runs.values():
            if run['status'] == 'running':
                run['status'] = 'stopped'

    # ===== Test Helpers =====
    def get_command_history(self) -> List[tuple]:
        return self._command_history.copy()

    def clear_history(self) -> None:
        self._command_history.clear()
        self._runs.clear()
        self._run_counter = 0

    def inject_error(self) -> None:
        self._error_state = True

    def complete_run(self, run_id: str) -> None:
        """Mark a run as completed for testing."""
        if run_id in self._runs:
            self._runs[run_id]['status'] = 'succeeded'

    def fail_run(self, run_id: str, error_message: str = "Simulated error") -> None:
        """Mark a run as failed for testing."""
        if run_id in self._runs:
            self._runs[run_id]['status'] = 'failed'
            self._runs[run_id]['error'] = error_message
