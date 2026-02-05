# Active Context

## Current Focus
No active debugging or implementation task.

### Ready for Next Task
Previous work completed:
- Database Selection Research -> PostgreSQL + pgAudit recommended
- Meca slow speed after recovery -> FIXED (E-stop state clearing)

## Active Decisions
| Decision | Choice | Why |
|----------|--------|-----|
| Database | PostgreSQL + pgAudit | Best audit + async + compliance |
| Cache strategy | Selectors + coordinates | ref_ids are ephemeral, selectors are stable |
| Screenshot policy | NEVER by default | 5000 tokens each, only on failure |

## Key Learnings
- **Meca TCP**: Keep socket open entire session (robot loses state if closed)
- **E-stop recovery**: Must properly clear E-stop state before resuming
- **Speed restoration**: Set speed BEFORE calling `resume_motion()`
- **ref_ids are ephemeral**: Assigned per DOM snapshot, invalidated on any change
- **Token hierarchy**: screenshot (5k) > read_page (2k) > find (250) > cached coords (50)

## Key Code Locations
| Feature | Location |
|---------|----------|
| Speed helper | `wafer_sequences.py:88-130` (`_get_resume_speed()`) |
| Resume pickup | `wafer_sequences.py:891-949` (`_resume_pickup_sequence()`) |
| Resume drop | `wafer_sequences.py:951-1010` (`_resume_drop_sequence()`) |
| Quick recovery | `recovery_operations.py:350-500` (`quick_recovery()`) |
| Connect flow | `connection_manager.py:429-497` (`confirm_activation()`) |

## References
- Database plan: `C:\Users\amitaik\.claude\plans\agile-toasting-lagoon.md`
- Browser testing plan: `docs/plans/2026-01-27-browser-testing-token-optimization.md`

## Remaining Work (Low Priority)
- Phase 2: Add API endpoints for safe connection
- Phase 2: Create frontend confirmation dialog
- Phase 3: Fix OT2 double-start race condition
- Phase 4: Add disconnect button
- Phase 5: Fix documentation (CLAUDE.md header value)

## Last Updated
2026-02-04
