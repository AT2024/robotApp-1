# Configuration Rules

## Settings Access

Always use centralized settings - NEVER hard-code IPs, ports, or credentials:

```python
from core.settings import get_settings

settings = get_settings()
meca_config = settings.get_robot_config("meca")
```

## Environment Variables

All environment variables use `ROBOTICS_` prefix:

```bash
ROBOTICS_MECA_IP=192.168.0.100
ROBOTICS_OT2_IP=169.254.49.202
ROBOTICS_LOG_LEVEL=INFO
ROBOTICS_TIMEZONE=Asia/Jerusalem
```

## Key Configuration Values

| Component | Value |
|-----------|-------|
| Mecademic IP | 192.168.0.100:10000 |
| OT2 | Requires `robot_id` from OT2 dashboard |
| Frontend | Port 3002 (external), 5173 (internal) |
| Backend | Port 8080 (external), 8000 (internal) |

## Logging Configuration

Log files are stored in `windsurf-project/backend/logs/`:

| File | Contents |
|------|----------|
| `app.log` | Application logs (services, websocket, core) |
| `robot.log` | Robot-related logs (meca, ot2, arduino, drivers) |
| `error.log` | ERROR and CRITICAL level logs only |

**Rotation Strategy:**
- Daily rotation at midnight (TimedRotatingFileHandler)
- 30-day retention with automatic cleanup
- Backup files named: `app.log.2026-01-29`, etc.
- Old files cleaned automatically on application startup

**Environment Variables:**
- `ROBOTICS_LOG_LEVEL`: DEBUG, INFO, WARNING, ERROR, CRITICAL (default: INFO)
- `ROBOTICS_TIMEZONE`: Timezone for log timestamps (default: Asia/Jerusalem)
