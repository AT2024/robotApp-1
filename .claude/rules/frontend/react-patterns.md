---
paths:
  - "windsurf-project/frontend/src/**/*.js"
  - "windsurf-project/frontend/src/**/*.jsx"
  - "windsurf-project/frontend/src/**/*.ts"
  - "windsurf-project/frontend/src/**/*.tsx"
---

# Frontend Patterns

## Directory Structure

```
frontend/src/
├── components/    # Reusable UI components
├── pages/         # Route-level page components
└── utils/         # API clients and helpers
```

## API Client Pattern

Use utilities in `src/utils/` for backend communication.
Backend API is at `http://localhost:8080`.

## Port Mapping

- Frontend runs on port 5173 internally
- Mapped to port 3000 externally
- Ignore port 3002 references in docker-compose
