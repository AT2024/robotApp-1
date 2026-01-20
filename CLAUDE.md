# CLAUDE.md

Laboratory automation controlling Mecademic arm, Opentrons OT-2, Arduino, and Carousel.

**Architecture**: `Frontend (React/Vite) ↔ API ↔ Services ↔ Core ↔ Hardware`

## Quick Start

```bash
cd windsurf-project && docker-compose up -d
# Frontend: http://localhost:3000 | Backend: http://localhost:8080
```

## Critical Quirks

- **Mecademic TCP**: Keep socket open entire session (robot loses state if closed)
- **OT2 Header**: Always include `Opentrons-Version: 2` in requests
- **Pydantic**: Must use `pydantic<2.0.0` for OT2 SDK compatibility
- **State Sync**: Use ResourceLockManager to prevent MecaService desync
- **robot_id**: Required for OT2Service constructor (check OT2 dashboard)

## Core Principles

- **Safety First**: If unsure, stop the robot first
- Always use service layer (never direct robot access from routers)
- All state changes through AtomicStateManager
- Mock hardware for unit tests, real hardware for integration only

## Detailed Rules

See `.claude/rules/` for domain-specific guidelines:
- `robotics-safety.md` - Safety protocols and error handling
- `backend/service-patterns.md` - Service layer patterns
- `backend/api-patterns.md` - FastAPI endpoint patterns
- `frontend/react-patterns.md` - React conventions
- `configuration.md` - Environment and settings
- `naming-conventions.md` - Naming standards
- `troubleshooting.md` - Common issues and performance targets
