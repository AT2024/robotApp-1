# Project Patterns

## TDD Patterns
- Always write tests first (RED phase)
- Verify tests fail for the right reason (feature missing, not typos)
- Implement minimal code to pass (GREEN phase)
- Run all tests to verify no regressions

## Testing Patterns - Mocking Complex Dependencies
- Use `patch()` to mock complex initializations (e.g., WaferConfigManager)
- Patch at the import location, not the definition location
- Example: `patch('services.meca_service.WaferConfigManager')` instead of `patch('services.wafer_config_manager.WaferConfigManager')`

## MecaService Patterns
- Robot methods follow pattern: get driver → execute operation → broadcast state → return result
- WebSocket broadcasting uses `selective_broadcaster.get_broadcaster()`
- Import broadcaster inside method (not at module level) to avoid circular imports
- Emergency stop must be called on critical failures before re-raising exception

## Safety Patterns (Robotics)
- Connection should NOT automatically activate/home if robot state unknown
- Two-step confirmation: connect → show position → user confirms → activate/home
- Always check error status before operations
- Reset errors before activation if present
- Check pause status after homing and resume if needed
- Emergency stop on activation failures

## WebSocket Broadcasting Pattern
```python
try:
    from websocket.selective_broadcaster import get_broadcaster, MessageType
    broadcaster = await get_broadcaster()
    await broadcaster.broadcast_message(
        {"type": "event_type", "data": data},
        message_type=MessageType.ROBOT_STATUS
    )
except Exception as e:
    logger.warning(f"Failed to broadcast: {e}")
```

## Error Handling Pattern (HardwareError)
```python
try:
    # hardware operation
except Exception as e:
    logger.error(f"Operation failed: {e}")
    await self._execute_emergency_stop()  # safety first
    raise HardwareError(f"Message: {e}", robot_id=self.robot_id)
```

## MCP Server Installation (Windows)
- **npm bug #4828**: Optional native dependencies may not install with `npx -y`
- **Fix**: Install globally with explicit native binding:
  ```bash
  npm install -g <package> @napi-rs/keyring-win32-x64-msvc
  ```
- **Cleanup**: `npm cache clean --force` and remove global package before reinstall

## React Button Component Pattern
**Problem**: Internal disabled logic conflicts with external disabled prop
```jsx
// BAD - spread operator overwrites internal logic
const Button = ({ internalCondition, ...props }) => (
  <button disabled={internalCondition} {...props}>{/*...*/}</button>
);
// Parent: <Button disabled={externalCondition} /> // overwrites internal!

// GOOD - explicitly combine both conditions
const Button = ({ internalCondition, disabled, ...props }) => {
  const isDisabled = internalCondition || disabled;
  return <button disabled={isDisabled} {...props}>{/*...*/}</button>;
};
```

## WebSocket Command Pattern (Frontend)
**Always wrap `websocketService.send()` in try-catch with user feedback:**
```jsx
const handleCommand = useCallback(() => {
  // Check connection first
  if (!wsConnected) {
    toast.error('WebSocket disconnected');
    return;
  }

  try {
    websocketService.send({ type: 'command', ... });
  } catch (error) {
    setLastError(error.message);
    toast.error(`Command failed: ${error.message}`);
    // Rollback any optimistic state updates
  }
}, [wsConnected]);
```

## Common Gotchas
- **Gotcha**: WebSocket `send()` throws when disconnected - wrap in try-catch
- **Gotcha**: React props spread operator overwrites earlier props - destructure explicitly
- **Gotcha**: force_reconnect() calls DeactivateRobot() - you CANNOT skip activation after this
- **Gotcha**: Quick recovery should NOT force_reconnect if connection is alive - it destroys speed settings
- **Gotcha**: `get_connection_manager()` creates NEW instance with empty connections - use singleton from `app.state.connection_manager`
- **Gotcha**: Frontend expects `{type: "operation_update", data: {event: "wafer_progress"}}` format - not bare `{type: "wafer_progress"}`
- **Gotcha**: Initial setup in `execute_pickup_sequence()` has `GripperOpen` - MUST skip on resume or it drops wafer
- **Gotcha**: TaskCreate without checking TaskList first - leads to duplicate tasks; always check existing tasks before creating new ones
