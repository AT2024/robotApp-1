# Browser Testing Skill Token Optimization Analysis

> **For Claude:** Analysis and recommendations for reducing token consumption in browser-testing skill.

**Goal:** Reduce browser automation token consumption from ~50k to ~5k per test session (90% reduction).

**Current State Analysis Date:** 2026-01-27

---

## Problem Analysis

### Observed Token Consumption (Real Session)

| Source | Tokens | Count | Total |
|--------|--------|-------|-------|
| MCP tool definitions | 10,200 | 1 (loaded once) | 10,200 |
| Screenshots | ~5,000 | ~10 | ~50,000 |
| read_page calls | ~500-2,000 | varies | ~5,000-15,000 |
| find calls | ~250 + results | varies | ~2,000-5,000 |
| **Session Total** | | | **~67,000-80,000** |

### Why Caching Was Not Used Effectively

**Problem 1: Instructions Not Clear Enough**
- SKILL.md describes caching but doesn't mandate it
- No explicit "ALWAYS do X before Y" directives
- Claude defaulted to screenshots because workflow wasn't explicit

**Problem 2: ref_ids Become Stale After Navigation**
- MCP browser tools assign ref_ids to DOM elements on current page snapshot
- Navigation or DOM updates invalidate all ref_ids
- Cache stores stale ref_ids that fail silently
- No mechanism to detect or recover from stale refs

**Problem 3: No Clear Screenshot Skip Directive**
- Instructions say screenshots save tokens but don't specify WHEN to skip
- Claude took screenshots "to be safe" at each step
- Each screenshot = 5,000 tokens wasted

---

## Root Cause Analysis

### Token Hierarchy (Highest to Lowest Cost)

1. **Screenshots** (~5,000 tokens each) - MOST EXPENSIVE
2. **read_page full DOM** (~1,000-2,000 tokens) - EXPENSIVE
3. **MCP tool definitions** (~10,200 one-time) - FIXED COST
4. **find results** (~250-500 tokens) - MODERATE
5. **Cached ref_id lookup** (~50 tokens) - CHEAPEST

### Caching Fundamental Flaw

The current cache stores `ref_id` values which are **ephemeral session identifiers** assigned by the browser automation tool. These refs:
- Are invalidated on any DOM change
- Are invalidated on page navigation
- Cannot be reused across sessions
- Cannot be reused even within the same session after navigation

**Solution:** Cache **selectors and coordinates** instead of ref_ids.

---

## Recommendations

### 1. Rewrite Workflow with Explicit Token-Aware Directives

**Current (Vague):**
```
For each test step:
1. Check cache for element ref_id
2. If cached: use directly
3. If not cached: use find or read_page
```

**Proposed (Explicit):**
```
For each test step, follow this EXACT order:

STEP A - NEVER SCREENSHOT unless explicitly required
  - Default: Do NOT take screenshot
  - Only screenshot when: step.requires_screenshot=true OR failure recovery

STEP B - Cache-First Element Location (MANDATORY)
  1. Run: python3 cache-manager.py get <url> <cache_key>
  2. If HIT with coordinates: Use mcp__computer(action=click, coordinates=[x,y])
  3. If HIT with selector: Use mcp__find(query=selector) - store new ref_id
  4. If MISS: Use mcp__find(query=target) - store result

STEP C - Execute Action
  - Use ref_id from Step B (NOT from cache)
  - Cache stores selectors, not ref_ids

STEP D - Verify (token-efficient)
  - For text verification: read_page(selector=specific_element) - NOT full page
  - For visibility: find(query=element) - check if found
  - For state: read_console_messages OR network_requests
```

### 2. Change Cache Strategy from ref_id to Selectors

**Current cache-manager.py stores:**
```json
{
  "ref_id": "ref_42",       // INVALID after any DOM change
  "coordinates": null
}
```

**Proposed change:**
```json
{
  "css_selector": "button.quick-recovery",    // Stable across sessions
  "aria_selector": "[aria-label='Quick Recovery']",
  "text_selector": "Quick Recovery button",
  "coordinates": {"x": 150, "y": 300},        // Stable if layout unchanged
  "viewport_hash": "1920x1080",               // Track viewport for coordinate validity
  "last_verified": "2026-01-27T10:00:00"
}
```

### 3. Add Explicit "Token Budget" to Test Scenarios

Add token awareness directly to test scenario JSON:

```json
{
  "name": "recovery-flow",
  "token_budget": {
    "max_screenshots": 2,       // Only on failure
    "max_read_page": 3,         // Use targeted reads
    "prefer": "coordinates"     // Use coordinates when available
  },
  "steps": [...]
}
```

### 4. Implement Verification Modes

Different verification modes with different token costs:

| Mode | Method | Token Cost | Use When |
|------|--------|------------|----------|
| `quick` | find(query) existence check | ~250 | Element visibility |
| `state` | read_page(selector=specific) | ~300-500 | Text/state verification |
| `visual` | screenshot | ~5,000 | Only on failure/debugging |
| `api` | curl to API endpoint | ~100 | State verification via backend |

### 5. Add Staleness Detection

Detect when cached data is likely stale:

```python
def is_cache_stale(elem, current_url, viewport):
    # URL changed = definitely stale
    if elem.get("cached_url") != current_url:
        return True

    # Viewport changed = coordinates invalid
    if elem.get("viewport_hash") != viewport:
        return True

    # More than 1 hour old = probably stale
    if time_since(elem.get("last_verified")) > 3600:
        return True

    return False
```

### 6. Rewrite SKILL.md with Mandatory Workflow

Replace current workflow section with explicit, non-negotiable directives.

---

## Implementation Plan

### Phase 1: Update Cache Strategy (Breaking Change)

**File:** `.claude/skills/browser-testing/scripts/cache-manager.py`

Changes:
- Store CSS/aria selectors instead of ref_ids
- Add viewport hash tracking
- Add staleness detection
- Add `refresh` command to re-verify cached elements

### Phase 2: Update SKILL.md with Explicit Workflow

**File:** `.claude/skills/browser-testing/SKILL.md`

Changes:
- Add "Token Efficiency Rules" section at top (MANDATORY)
- Rewrite workflow with explicit IF/THEN directives
- Add "NEVER" and "ALWAYS" lists
- Add token budget awareness

### Phase 3: Update Test Scenarios

**Files:** `.claude/skills/browser-testing/test-scenarios/*.json`

Changes:
- Add `token_budget` to each scenario
- Add `verification_mode` to each step
- Add `requires_screenshot: false` default

### Phase 4: Add Token Tracking

**New File:** `.claude/skills/browser-testing/scripts/token-tracker.py`

Purpose:
- Track estimated tokens used per session
- Warn when approaching budget
- Report actual vs expected token usage

---

## Specific SKILL.md Rewrite

### Token Efficiency Rules (Add to Top)

```markdown
## Token Efficiency Rules (MANDATORY)

### NEVER Do These (Token Wasters)
- NEVER take screenshot unless step.requires_screenshot=true OR failure recovery
- NEVER use read_page without selector parameter
- NEVER use ref_ids from cache (they're stale)
- NEVER verify by screenshot when API check works

### ALWAYS Do These (Token Savers)
- ALWAYS check cache-manager.py FIRST for selectors/coordinates
- ALWAYS use coordinates when viewport matches
- ALWAYS use targeted read_page(selector=...) for text verification
- ALWAYS use find(query=...) existence check for visibility
- ALWAYS prefer API verification over screenshot verification

### Token Cost Reference
| Operation | Tokens | When to Use |
|-----------|--------|-------------|
| Screenshot | ~5,000 | ONLY on failure |
| read_page (full) | ~2,000 | NEVER - use selector |
| read_page (selector) | ~300 | Text verification |
| find | ~250 | Element discovery |
| computer(click) | ~100 | Actions |
| Cached coordinates | ~50 | PREFERRED for clicks |
```

### Workflow Rewrite

```markdown
## Execution Workflow (STRICT ORDER)

### Pre-Test Setup
1. Load cache: `python3 cache-manager.py list`
2. Get viewport: `mcp__tabs_context_mcp` (save for coordinate validation)
3. Navigate ONCE: `mcp__navigate(url=...)`

### For Each Step (EXACT ORDER)

**A. Skip Screenshot (DEFAULT)**
```
IF step.requires_screenshot != true:
    DO NOT take screenshot
    PROCEED to Step B
```

**B. Element Location (Cache-First)**
```
1. RUN: python3 cache-manager.py get <url> <cache_key>

2. IF HIT with coordinates AND viewport matches:
   USE coordinates directly: mcp__computer(action=click, coordinates=[x,y])
   SKIP find call

3. IF HIT with selector (no coordinates):
   RUN: mcp__find(query=cached_selector)
   STORE new coordinates from result
   USE returned ref_id

4. IF MISS:
   RUN: mcp__find(query=step.target)
   STORE selector AND coordinates in cache
   USE returned ref_id
```

**C. Action Execution**
```
USE ref_id from Step B (NOT from cache)
RUN: mcp__computer(action=step.action, ref=ref_id)
```

**D. Verification (Token-Efficient)**
```
IF step.verify.type == "element_visible":
    RUN: mcp__find(query=expected_element)
    CHECK: result contains element

IF step.verify.type == "text_contains":
    RUN: mcp__read_page(selector=target_element)  # NOT full page
    CHECK: text contains expected

IF step.verify.type == "api_state":
    RUN: curl <api_endpoint>
    CHECK: response matches expected

IF step.verify.type == "screenshot":  # ONLY when explicitly required
    RUN: mcp__screenshot
    ANALYZE: visual state
```

### On Failure
```
ONLY NOW take screenshot for diagnosis
TRY alternative selectors from cache
IF still failing: analyze and suggest fix
```
```

---

## Expected Outcomes

### Before Optimization
| Metric | Value |
|--------|-------|
| Screenshots per test | ~10 |
| read_page calls (full) | ~5 |
| Cache hit rate | 0% (ref_ids always stale) |
| Total tokens | ~70,000 |

### After Optimization
| Metric | Value |
|--------|-------|
| Screenshots per test | 0-2 (only on failure) |
| read_page calls (targeted) | ~5 |
| Cache hit rate | 60-80% (selectors are stable) |
| Total tokens | ~5,000-8,000 |

### Token Savings
- **90% reduction** in per-test token consumption
- **97% reduction** in screenshot-related tokens
- **70% reduction** in element location tokens

---

## Confidence Score: 7/10

**Factors:**
- (+1) Clear problem identification with real data
- (+1) Root cause analysis of ref_id staleness issue
- (+1) Specific code changes outlined
- (+1) Token cost hierarchy documented
- (-1) No external research on browser automation best practices
- (-1) Implementation not tested
- (-1) MCP tool behavior assumptions may need verification

**To improve confidence:**
- Test cache-manager.py changes with actual MCP tools
- Verify coordinate-based clicking works reliably
- Confirm viewport hash detection method

---

## References

- Current skill: `.claude/skills/browser-testing/SKILL.md`
- Cache manager: `.claude/skills/browser-testing/scripts/cache-manager.py`
- Test scenarios: `.claude/skills/browser-testing/test-scenarios/*.json`
