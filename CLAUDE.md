# CC10x Orchestration (Always On)

IMPORTANT: ALWAYS invoke cc10x-router on ANY development task. First action, no exceptions.
IMPORTANT: Explore project first, then invoke the router.
IMPORTANT: Prefer retrieval-led reasoning over pre-training-led reasoning.
IMPORTANT: Never bypass the router. It is the system.
IMPORTANT: NEVER use Edit, Write, or Bash (for code changes) without first invoking cc10x-router.

**Skip CC10x ONLY when:**
- User EXPLICITLY says "don't use cc10x", "without cc10x", or "skip cc10x"
- No interpretation. No guessing. Only these exact opt-out phrases.

[CC10x] | entry: ./plugins/cc10x/skills/cc10x-router/SKILL.md

---

# CLAUDE.md

Laboratory automation controlling Mecademic arm, Opentrons OT-2, Arduino, and Carousel.

**Architecture**: `Frontend (React/Vite) ↔ API ↔ Services ↔ Core ↔ Hardware`

## Quick Start

```bash
cd windsurf-project && docker-compose up -d
# Frontend: http://localhost:3002 | Backend: http://localhost:8080
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
