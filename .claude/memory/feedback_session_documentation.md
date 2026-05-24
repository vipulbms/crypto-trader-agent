---
name: session_documentation_workflow
description: Always update session notes and README when committing code to maintain decision history
metadata:
  type: feedback
---

## Rule
Every code commit must include:
1. **Session notes** — new file `docs/sessions/session_YYYY_MM_DDx.md` documenting what changed and why
2. **README.md** update — if the feature is user-facing or affects trading behavior
3. **CLAUDE.md** update — if the feature is architectural or impacts known behaviors

**Why:** The repo must contain a complete decision trail. Commits without documentation leave future context gaps. Session notes are the source of truth for "why did we build this?"

**How to apply:**
- When using `/commit`, always create a corresponding session note (even for hotfixes)
- Session notes should include: issue #, root cause (if bug), what changed, testing, related sessions
- README updates needed for: new personas, trading mechanics, CLI commands, config changes
- CLAUDE.md updates needed for: architecture changes, known behaviors, critical design decisions
- All three should be committed in the same git commit (atomic documentation + code)

## Example Pattern

```bash
# User requests a feature
# → Implement code
# → Write session note (docs/sessions/session_2026_05_24a.md)
# → Update README/CLAUDE.md if user-facing
# → Single commit: "Feat: X + Docs: session notes + README update"
```

This ensures every decision in the repo is traceable.
