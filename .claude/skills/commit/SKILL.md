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

### 2. Draft commit message
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

### 3. Stage only the appropriate files
Use `git add <specific files>` — never `git add -A` or `git add .` to avoid accidentally staging secrets or large runtime files.

### 4. Commit and push
```bash
git commit -m "..."
git push
```

### 5. Confirm
Report the commit hash, message, and the GitHub URL:
`https://github.com/vipulbms/crypto-trader-agent`
