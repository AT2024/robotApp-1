---
paths:
  - "windsurf-project/backend/services/**/*.py"
---

# Service Layer Patterns

## Service Class Template

All robot services MUST extend `RobotService` base class:

```python
class NewRobotService(RobotService):
    def __init__(self, robot_id: str, settings: RoboticsSettings,
                 state_manager: AtomicStateManager, lock_manager: ResourceLockManager):
        super().__init__(
            robot_id=robot_id,
            robot_type="new_robot",
            settings=settings,
            state_manager=state_manager,
            lock_manager=lock_manager,
            service_name="NewRobotService"
        )
        self.robot_config = settings.get_robot_config("new_robot")

    @circuit_breaker("new_robot_connect")
    async def connect(self) -> ServiceResult[bool]:
        pass
```

## Key Requirements

- Use `@circuit_breaker` decorator for all external connections
- Return `ServiceResult[T]` from all public methods
- Get config via `settings.get_robot_config()` - never hard-code IPs/ports
- Use `AtomicStateManager` for all state changes
- Acquire locks via `ResourceLockManager` before shared resource access

## Performance Targets

- Robot commands: <2s response time
- Status checks: <100ms
