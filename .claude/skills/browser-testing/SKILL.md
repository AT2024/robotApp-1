---
name: browser-testing
description: Test robot app via browser automation using Playwright MCP (primary) or claude-in-chrome (fallback). Includes debug mode for network inspection.
allowed-tools: mcp__playwright__*, mcp__claude-in-chrome__*, Read, Write, Bash(python3:*), Bash(curl:*)
argument-hint: [scenario-name|url] [action:test|verify|fix|debug]
---

# Browser Testing Skill

End-to-end testing for the robot control app with intelligent tool selection.

## Architecture

```
Claude Code
    |
    +-> Playwright MCP (PRIMARY - ~40% fewer tokens)
    |       +-> UI testing, clicks, form fills
    |       +-> Accessibility tree based (no screenshots needed)
    |       +-> Cross-browser (Chrome/Firefox/WebKit)
    |
    +-> claude-in-chrome (FALLBACK)
    |       +-> Quick visual checks
    |       +-> Authenticated sessions
    |       +-> GIF recording
    |
    +-> Debug Mode (curl + console)
            +-> Network request verification
            +-> API response checking
            +-> Console error capture
```

## Tool Selection Rules

| Task | Use Playwright | Use claude-in-chrome |
|------|---------------|---------------------|
| Click elements | Yes (getByRole, getByText) | Fallback if PW unavailable |
| Form input | Yes (fill) | Fallback |
| Verify text | Yes (accessibility snapshot) | Fallback |
| Take screenshot | No (use PW snapshot) | Yes, for visual debugging |
| Record GIF | No | Yes (gif_creator) |
| Network inspection | Use curl/debug mode | read_network_requests |
| Console errors | Use debug mode | read_console_messages |

## Token Efficiency (MANDATORY)

### Token Costs Reference
| Operation | Playwright | claude-in-chrome |
|-----------|-----------|------------------|
| Setup | ~1.2k | ~2k |
| Element locate | ~100 | ~250 (find) |
| Click/Type | ~100 | ~300 |
| Page snapshot | ~500 | ~2000 (read_page) |
| Screenshot | N/A | ~5000 |

**Savings: Playwright uses ~40% fewer tokens than claude-in-chrome**

### NEVER Do These
- NEVER screenshot unless debugging a failure
- NEVER full page read_page without ref_id scope
- NEVER use cached ref_ids directly (stale after DOM changes)

### ALWAYS Do These
- ALWAYS prefer Playwright MCP when available
- ALWAYS use accessibility-based selectors (getByRole, getByText)
- ALWAYS verify via API when possible
- ALWAYS check cache for known selectors

## Quick Start

```
/browser-testing recovery-flow test          # Run test with Playwright
/browser-testing connection-flow test        # Run connection test
/browser-testing http://localhost:3002 verify # Quick verification
/browser-testing debug recovery-flow         # Debug with network inspection
/browser-testing fix                         # Analyze and fix last failure
```

## Workflow: Playwright MCP (Primary)

### Phase 1: Setup
1. Launch browser: `mcp__playwright__browser_navigate` to URL
2. Browser opens in visible window (supports manual login if needed)

### Phase 2: Test Execution
For each test step:
1. **Locate element** using accessibility selectors:
   - `browser_snapshot` - Get accessibility tree
   - Elements identified by role/name: `button "Submit"`, `textbox "Email"`
2. **Execute action**:
   - `browser_click(element="button \"Quick Recovery\"")`
   - `browser_type(element="textbox \"Username\"", text="admin")`
3. **Verify state**:
   - Check snapshot for expected text/elements
   - Or verify via API: `curl http://localhost:8080/api/meca/status`

### Phase 3: Failure Recovery
If a step fails:
1. Take snapshot for debugging
2. Check with claude-in-chrome screenshot if visual issue suspected
3. Check console for errors
4. Try alternative selectors

## Workflow: claude-in-chrome (Fallback)

Use when Playwright MCP is unavailable or for:
- GIF recording of test runs
- Visual verification requiring actual screenshots
- Authenticated sessions already established

### Phase 1: Setup
1. Get tab context via `tabs_context_mcp`
2. Create new tab if needed via `tabs_create_mcp`
3. Load cache: `python3 .claude/skills/browser-testing/scripts/cache-manager.py get <url> <key>`

### Phase 2: Test Execution
For each test step:
1. **Check cache**: `cache-manager.py get <url> <cache_key>`
2. **If HIT with matching viewport**: Click coordinates directly
3. **If MISS**: Use `find(query=target)` to locate (~250 tokens)
4. **Store result**: `cache-manager.py store <url> <key> --selector "..." --coords "x,y"`
5. **Execute action** (click, type, etc.)

## Debug Mode

Run with `debug` action for detailed diagnostics:

```
/browser-testing debug recovery-flow
```

Debug mode includes:
1. **Pre-test API check**: Verify backend is running
2. **Network monitoring**: Log all API calls during test
3. **Console capture**: Capture JavaScript errors
4. **Step-by-step verification**: Pause and verify each step

### Debug Commands
```bash
# Check API endpoint
curl -s http://localhost:8080/api/meca/status | python3 -m json.tool

# Check backend health
curl -s http://localhost:8080/api/health

# Monitor WebSocket (if needed)
# Use read_network_requests with urlPattern="/ws"
```

## Test Scenarios

Located in `test-scenarios/*.json`:
```json
{
  "name": "recovery-flow",
  "url": "http://localhost:3002",
  "token_budget": {
    "max_screenshots": 2,
    "prefer_api_verify": true
  },
  "steps": [...],
  "playwright_selectors": {
    "quick-recovery-btn": "button \"Quick Recovery\"",
    "system-status": "region \"System Status\""
  }
}
```

## Playwright Selector Syntax

Playwright MCP uses accessibility-based selectors:

| Type | Syntax | Example |
|------|--------|---------|
| Button | `button "text"` | `button "Quick Recovery"` |
| Link | `link "text"` | `link "Settings"` |
| Textbox | `textbox "label"` | `textbox "Username"` |
| Checkbox | `checkbox "label"` | `checkbox "Remember me"` |
| By test-id | `[data-testid="id"]` | `[data-testid="meca-status"]` |

## Commands

- `test <scenario>`: Run test scenario (Playwright primary)
- `verify`: Verify current state via accessibility snapshot
- `fix`: Analyze last failure and suggest fixes
- `debug <scenario>`: Run with network/console inspection
- `cache show`: Display cache statistics
- `cache clear [key]`: Invalidate cache entries

## Fix-On-Spot Workflow

When a test fails:
1. **Capture Failure** - Snapshot + console errors
2. **Analyze** - Compare expected vs actual
3. **Suggest Fix** - Generate specific code changes
4. **Re-run** - Only failing step, not entire test

## Cache Strategy

The cache stores **persistent selectors**, NOT ephemeral ref_ids:

```json
{
  "playwright_selector": "button \"Quick Recovery\"",
  "css_selector": "button.quick-recovery",
  "text_selector": "Quick Recovery button",
  "coordinates": {"x": 150, "y": 300},
  "viewport_size": "1536x643"
}
```

- Playwright selectors are preferred (accessibility-based)
- CSS/text selectors as fallback for claude-in-chrome
- Coordinates valid when viewport matches
- ref_ids are NEVER cached (always stale)

## Migration Notes

Previous versions used claude-in-chrome exclusively. Key changes:
1. Playwright MCP is now primary (~40% token savings)
2. claude-in-chrome remains for GIF recording and fallback
3. Debug mode added for network inspection
4. Test scenarios now include `playwright_selectors` field
