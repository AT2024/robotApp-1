# Troubleshooting Guide

## Common Issues

| Issue | Check |
|-------|-------|
| OT2 connection fails | `robot_id` matches dashboard, `Opentrons-Version: 2` header present, pydantic<2.0.0 installed |
| Mecademic connection fails | IP 192.168.0.100:10000 reachable, socket kept open, safety system enabled |
| Docker build fails | Use `--no-cache` flag, check Alpine vs Debian packages, verify memory allocation |
| State desync | ResourceLockManager in use, AtomicStateManager for state changes |
| "invalid high surrogate" error | Plan contains Unicode; use `/text-cleaner` to fix, follow `unicode-safety.md` rules |

## Tool Selection

| Need | Tool |
|------|------|
| Read file content | Read |
| Search code patterns | Grep |
| Find files | Glob |
| Open research | Task (Explore agent) |
| External documentation | WebFetch/WebSearch |

## Performance Targets

| Metric | Target |
|--------|--------|
| API status | <100ms |
| API operations | <2s |
| Robot commands | <2s |
| WebSocket | <50ms |
| Database | <100ms |
