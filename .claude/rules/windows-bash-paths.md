# Windows Bash Path Rules

## Critical Rule

When running bash commands on Windows (Git Bash or WSL), use Unix-style paths:

| Format | Example | Status |
|--------|---------|--------|
| Unix-style | `/c/Users/amitaik/Desktop/robotApp-1/...` | CORRECT |
| Windows-style | `C:\Users\amitaik\Desktop\robotApp-1\...` | WRONG |

## Conversion Pattern

| Windows | Unix |
|---------|------|
| `C:\` | `/c/` |
| `D:\` | `/d/` |
| `\` (backslash) | `/` (forward slash) |

## Why This Matters

- Git Bash does not understand Windows-style paths
- Backslashes are interpreted as escape characters in bash
- Causes "No such file or directory" errors

## Examples

```bash
# WRONG - will fail
cd C:\Users\amitaik\Desktop\robotApp-1
cat C:\Users\amitaik\Desktop\robotApp-1\CLAUDE.md

# CORRECT - will work
cd /c/Users/amitaik/Desktop/robotApp-1
cat /c/Users/amitaik/Desktop/robotApp-1/CLAUDE.md
```

## Quick Reference

Working directory shown as `C:\Users\amitaik\Desktop\robotApp-1` in env context should be converted to `/c/Users/amitaik/Desktop/robotApp-1` for all bash commands.
