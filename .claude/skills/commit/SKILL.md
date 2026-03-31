---
name: commit
description: Commit and push changes to GitHub for the Kryptos project. Use when the user asks to commit, save, or push changes.
argument-hint: "[optional commit message]"
---

# Commit and Push to GitHub

## Current state
!`git status --short`

## Recent commits for style reference
!`git log --oneline -5`

## Staged and unstaged diff
!`git diff HEAD`

## Steps

### 1. Identify what to commit
Review the changed files above. Never stage:
- `.env` — contains API keys
- `data/` — runtime databases
- `logs/` — runtime log files
- `__pycache__/` — compiled bytecode
- `*.pyc` — compiled bytecode
- `agent.log` — runtime log

Only stage source files: `.py`, `.yaml`, `.md`, `.txt`, `.json`, skill files under `.claude/`.

### 2. Save session notes
Write a new session notes file at `docs/sessions/session_<date>_<part>.md` (e.g. `session_2026_03_31i.md`).

Determine the next part letter by looking at existing files in `docs/sessions/` for today's date and incrementing.

Session notes format:
```markdown
# Session Notes — <date> (Part <X>)

## Changes

### 1. <Title>

**Bug report / Feature request:** <what prompted this>

**Root cause / Motivation:** <why>

**Fix / Implementation:** <what changed and in which files>

---
```
Include one section per significant change. Be specific: file paths, function names, before/after behaviour where relevant.

### 3. Update CLAUDE.md
Review `CLAUDE.md` in the project root and update it to reflect any changes made in this session:
- Add new pairs to the pairs table if any were added
- Update "Known Behaviours / Gotchas" if any new quirks were discovered
- Update "Session Notes" table with the new session file
- Update architecture section if any new files/modules were added

### 4. Update business-requirement.md, README.md, and plan.md
Review `business-requirement.md`, `README.md`, and `plan.md` and update them to reflect any changes made in this session:
- `business-requirement.md` — update if new features or pairs change the product scope
- `README.md` — update setup instructions, feature list, or usage examples if anything changed
- `plan.md` — tick off completed items; add new planned work if discussed

Only update sections that are genuinely stale. Do not rewrite content that is still accurate.

### 5. Update CHANGELOG.md
Append a new entry to `CHANGELOG.md` summarising the changes in this commit:
- Add a new `## Session: <today's date>` section if one does not exist for today, or append to the existing one
- Include: bugs fixed (root cause + fix), features added, files changed
- Keep it concise — bullet points or a table, not prose

### 6. Update memory
Update the relevant memory file at:
`~/.claude/projects/-Users-vipulsanghrajka-Documents-myworkdir-crypto-trader-agent/memory/project_kryptos.md`

Add any new critical conventions, config values, or architectural decisions that future sessions should know. Do not duplicate what is already there — only add what is new or changed.

### 7. Draft commit message
If the user provided a message in `$ARGUMENTS`, use it as the subject line.
Otherwise, derive a message from the diff following the project's commit style:
- `fix:` for bug fixes
- `feat:` for new features
- `docs:` for documentation-only changes
- `refactor:` for code restructuring without behaviour change

Format:
```
<type>: <short subject under 70 chars>

<body — what changed and why, 2-5 bullet points if needed>

Co-Authored-By: Claude Sonnet 4.6
```

### 8. Stage only the appropriate files
Use `git add <specific files>` — never `git add -A` or `git add .` to avoid accidentally staging secrets or large runtime files. Always include `CHANGELOG.md`, `CLAUDE.md`, `README.md`, `plan.md`, `business-requirement.md`, and the new session notes file.

### 9. Commit and push
```bash
git commit -m "..."
git push
```

### 10. Confirm
Report the commit hash, message, and the GitHub URL:
`https://github.com/vipulbms/crypto-trader-agent`
