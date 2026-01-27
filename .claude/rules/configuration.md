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
```

## Key Configuration Values

| Component | Value |
|-----------|-------|
| Mecademic IP | 192.168.0.100:10000 |
| OT2 | Requires `robot_id` from OT2 dashboard |
| Frontend | Port 3002 (external), 5173 (internal) |
| Backend | Port 8080 (external), 8000 (internal) |
