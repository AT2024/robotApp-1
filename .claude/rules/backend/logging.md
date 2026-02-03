# Logging Rules

**Path scope:** `windsurf-project/backend/**/*.py`

**Golden Rule:** Always include context - robot_id, wafer_id, operation name.

---

## Log Level Guidelines

| Level | When to Use | Example |
|-------|-------------|---------|
| DEBUG | Development tracing, detailed state, position calculations | `logger.debug(f"Joint positions: {positions}")` |
| INFO | Normal operation milestones | `logger.info(f"Pickup completed for wafer {wafer_id}")` |
| WARNING | Recoverable issues, retries, degraded operation | `logger.warning(f"Connection retry {attempt}/3")` |
| ERROR | Operation failures, exceptions | `logger.error(f"Robot {robot_id} failed: {e}", exc_info=True)` |
| CRITICAL | System-wide failures, emergency stops | `logger.critical(f"Emergency stop triggered: {reason}")` |

---

## Logger Initialization

Use `get_logger()` from `utils.logger`. The logger name determines file routing:

```python
from utils.logger import get_logger

# Robot loggers -> robot.log
logger = get_logger("meca_service")     # Contains "meca" -> robot.log
logger = get_logger("ot2_router")       # Contains "ot2" -> robot.log
logger = get_logger("arduino_driver")   # Contains "arduino" -> robot.log

# Application loggers -> app.log
logger = get_logger("command_service")  # No robot pattern -> app.log
logger = get_logger("websocket")        # No robot pattern -> app.log
```

**Routing patterns for robot.log:**
- `meca`, `mecademic`
- `ot2`, `opentrons`
- `arduino`
- `carousel`, `wiper`
- `driver`

Everything else routes to `app.log`.

---

## Correlation ID Usage

For multi-step operations, use correlation IDs to trace the entire flow:

```python
from utils.correlation import start_operation, clear_context, get_correlation_id

async def pickup_wafer(wafer_id: int):
    # Start operation context - all logs auto-include correlation_id
    correlation_id = start_operation(
        "pickup",
        wafer_id=wafer_id,
        robot_id=self.robot_id
    )
    try:
        logger.info(f"Starting pickup for wafer {wafer_id}")
        # ... operation steps ...
        # All logs here automatically include correlation_id, wafer_id, robot_id
        logger.debug(f"Moving to position {position}")
        logger.info(f"Pickup completed for wafer {wafer_id}")
    except Exception as e:
        logger.error(f"Pickup failed: {e}", exc_info=True)
        raise
    finally:
        clear_context()  # Always clear when done
```

**Correlation functions:**

| Function | Purpose |
|----------|---------|
| `start_operation(type, wafer_id=, robot_id=)` | Start new context, returns correlation_id |
| `get_correlation_id()` | Get current correlation_id |
| `get_context()` | Get full CorrelationContext object |
| `update_context(wafer_id=, robot_id=)` | Update context mid-operation |
| `clear_context()` | Clear context (call in finally block) |

---

## Error Logging Pattern

Always include full context and stack trace:

```python
# GOOD - Full context with stack trace
logger.error(
    f"Robot {robot_id} failed during {operation}: {e}",
    exc_info=True
)

# GOOD - With extra structured data (for JSON format)
logger.error(
    f"Pickup failed for wafer {wafer_id}",
    exc_info=True,
    extra={"wafer_id": wafer_id, "robot_id": robot_id}
)

# BAD - Missing context
logger.error(f"Failed: {e}")

# BAD - No stack trace for exceptions
logger.error(f"Error occurred: {e}")
```

---

## Log File Organization

| File | Contents | Use Case |
|------|----------|----------|
| `app.log` | Application logs (services, websocket, core) | General debugging |
| `robot.log` | Robot-related logs (meca, ot2, arduino, drivers) | Hardware debugging |
| `error.log` | ERROR and CRITICAL level only | Quick error scanning |

**Rotation:**
- Daily rotation at midnight (TimedRotatingFileHandler)
- 30-day retention
- Backup format: `app.log.2026-01-29`

---

## Log Search API

Use these endpoints to trace operations:

| Endpoint | Purpose |
|----------|---------|
| `GET /api/logs/search?correlation_id=pickup-abc123` | Find all logs for an operation |
| `GET /api/logs/search?wafer_id=3` | Find all logs for a wafer |
| `GET /api/logs/search?level=ERROR` | Find all errors |
| `GET /api/logs/search?pattern=timeout` | Regex search in messages |
| `GET /api/logs/trace/{correlation_id}` | Trace full operation |
| `GET /api/logs/wafer/{wafer_id}/logs` | All logs for a wafer |
| `GET /api/logs/stats` | Log file statistics |

---

## Environment Variables

| Variable | Values | Default |
|----------|--------|---------|
| `ROBOTICS_LOG_LEVEL` | DEBUG, INFO, WARNING, ERROR, CRITICAL | INFO |
| `ROBOTICS_LOG_FORMAT` | text, json | text |
| `ROBOTICS_TIMEZONE` | Any valid timezone | Asia/Jerusalem |
| `ROBOTICS_ENV` | development, production | development |

**JSON format output (when ROBOTICS_LOG_FORMAT=json):**
```json
{
  "timestamp": "2026-01-29T10:15:32.123",
  "level": "INFO",
  "logger": "meca_service",
  "message": "Pickup completed",
  "func": "execute_pickup",
  "line": 123,
  "correlation_id": "pickup-abc123",
  "wafer_id": 3,
  "robot_id": "meca"
}
```

---

## Anti-Patterns

| Anti-Pattern | Problem | Fix |
|--------------|---------|-----|
| `logger.error(f"Error: {e}")` | No context, no stack trace | Add context and `exc_info=True` |
| `print(f"Debug: {value}")` | Not captured in logs | Use `logger.debug()` |
| `logging.getLogger(__name__)` | Missing correlation filter | Use `get_logger()` |
| Missing `clear_context()` | Stale correlation data | Always use finally block |
| Hard-coded log paths | Breaks in different environments | Use LOGS_DIR from settings |
| Logging sensitive data | Security risk | Never log passwords, tokens, keys |
| `logger.exception()` alone | Missing context | Add descriptive message before exception |

---

## Complete Example

```python
from utils.logger import get_logger
from utils.correlation import start_operation, clear_context

logger = get_logger("meca_wafer_sequences")

async def execute_pickup_sequence(wafer_id: int, position: dict):
    """Execute wafer pickup with full logging."""
    correlation_id = start_operation(
        "pickup",
        wafer_id=wafer_id,
        robot_id="meca"
    )
    try:
        logger.info(f"Starting pickup sequence for wafer {wafer_id}")
        logger.debug(f"Target position: {position}")

        # Check robot status
        status = await self.get_robot_status()
        if not status.is_ready:
            logger.warning(f"Robot not ready, current state: {status.state}")
            raise HardwareError(f"Robot not ready: {status.state}")

        # Execute pickup
        logger.debug("Moving to pickup position")
        await self._move_to_position(position)

        logger.debug("Activating gripper")
        await self._activate_gripper()

        logger.info(f"Pickup completed for wafer {wafer_id}")
        return {"success": True, "correlation_id": correlation_id}

    except Exception as e:
        logger.error(
            f"Pickup failed for wafer {wafer_id}: {e}",
            exc_info=True
        )
        await self.emergency_stop()
        raise
    finally:
        clear_context()
```
