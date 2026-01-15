---
paths:
  - "windsurf-project/backend/routers/**/*.py"
---

# API Endpoint Patterns

## Router Endpoint Template

```python
@router.post("/operation-name")
async def operation_name(
    data: dict = Body(default={}),
    service: RobotService = ServiceDep()
):
    try:
        param1 = data.get("param1", default_value)
        logger.info(f"Starting operation: param1={param1}")
        result = await service.execute_operation(param1)
        if not result.success:
            raise HTTPException(status_code=500, detail=result.error)
        return {
            "status": "success",
            "data": result.data,
            "message": "Operation completed"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in operation: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
```

## Key Requirements

- Routers are THIN - delegate all business logic to services
- Never access hardware directly from routers
- Use `Body(default={})` for optional request bodies
- Re-raise `HTTPException` without wrapping
- Log errors with `exc_info=True` for full stack traces

## Response Format

Always return: `{"status": "success|error", "data": ..., "message": "..."}`

## Performance Targets

- Status endpoints: <100ms
- Operation endpoints: <2s
