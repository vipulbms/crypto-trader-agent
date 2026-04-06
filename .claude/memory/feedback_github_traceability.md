---
name: GitHub issue traceability requirement
description: Every code/config change must have a corresponding GitHub issue before work begins
type: feedback
---

Every change — bug fix, config tweak, feature, refactor — must have a corresponding GitHub issue before the work is done. No exceptions.

**Why:** The user requires full traceability between commits and intent. A commit without an issue has no documented rationale (what the problem was, why the fix was chosen). This was explicitly called out after session_2026_04_07a where a config fix was committed without an issue.

**How to apply:**
1. Before making any change, check if an issue already exists: `gh issue list --repo vipulbms/crypto-trader-agent`
2. If no issue exists, create one first:
   ```
   gh issue create --repo vipulbms/crypto-trader-agent \
     --title "..." \
     --body "## What\n...\n## Why\n...\n## How to fix\n..."
   ```
   The issue body must include: **What** (the problem/feature), **Why** (motivation), **How to fix** (proposed approach).
3. Reference the issue in the commit message: `Closes #N` (fully resolved) or `Refs #N` (partial).
4. When closing an issue, leave a comment summarising what was done and which files changed.

This applies to ALL change types: bug fixes, config changes, documentation updates, test additions, refactors.
