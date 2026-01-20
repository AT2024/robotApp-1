# Robotics Safety Rules

**Golden Rule: If unsure, stop the robot first.**

## Required Safety Pattern

Every robot operation MUST:
1. Call `get_robot_status()` before execution
2. Wrap in try/except with `emergency_stop()` in except block
3. Use `ResourceLockManager` for shared hardware
4. Log with context: `f"Robot {robot_id} failed during {operation}: {error}"`

## Reference Implementation

```python
try:
    status = await service.get_robot_status()
    if not status.is_ready:
        raise HardwareError(f"Robot {robot_id} not ready: {status.state}")
    async with lock_manager.acquire(f"robot_{robot_id}"):
        result = await service.execute_operation(params)
except Exception as e:
    logger.error(f"Robot {robot_id} failed during {operation_name}: {e}")
    await service.emergency_stop()
    raise
```

## Emergency Stop Protocol

- Never catch and suppress robot exceptions silently
- Always call `emergency_stop()` before re-raising
- Log full stack trace with `exc_info=True`
