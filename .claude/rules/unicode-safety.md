# Unicode Safety Rules

When writing text content (plans, documentation, comments, markdown), use ONLY ASCII-safe characters to prevent API encoding errors.

## Prohibited Characters - NEVER Use These

| Category | Prohibited | Use Instead |
|----------|-----------|-------------|
| Emoji | Any emoji | Text: `[WARNING]`, `[OK]`, `[NOTE]` |
| Curly quotes | " " ' ' | Straight quotes: `"` `'` |
| Arrows | -> <- => | ASCII: `->` `<-` `=>` |
| Box drawing | Any Unicode boxes | ASCII: `+` `-` `|` |
| Em/en dash | -- - | ASCII: `--` `-` |
| Ellipsis | ... | Three periods: `...` |
| Bullets | * o | ASCII: `*` `-` |

## Safe Patterns

```
GOOD: **WARNING**: This action is irreversible
BAD:  [warning emoji] This action is irreversible

GOOD: Status: [OK] - Connection established
BAD:  Status: [checkmark emoji] - Connection established

GOOD: Flow: Input -> Process -> Output
BAD:  Flow: Input [arrow emoji] Process [arrow emoji] Output
```

## Applies To
- Plan files (`.claude/plans/*.md`)
- Documentation (`*.md`, `README*`)
- Code comments
- Any natural language text output

## Recovery
If "invalid high surrogate" error occurs:
1. Use `/text-cleaner analyze <filepath>` to find issues
2. Use `/text-cleaner clean <filepath>` to fix
3. Do NOT read corrupted files with Read tool first
