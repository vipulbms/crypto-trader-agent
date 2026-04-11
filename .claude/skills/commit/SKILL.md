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

### 1. Create a branch for the issue
**Always commit on a dedicated branch — never commit directly to `main`.**

Determine the branch type from the GitHub issue:
- Bug fix / regression → `defect/<issue-number>` (e.g. `defect/173`)
- New feature / enhancement → `feature/<issue-number>` (e.g. `feature/165`)

If there is no issue number yet, create the GitHub issue first (per the mandatory workflow rule in user memory).

```bash
git checkout main
git pull                             # ensure main is up-to-date
git checkout -b feature/<N>          # or defect/<N>
```

If the branch already exists (e.g. partially committed earlier), check it out instead:
```bash
git checkout feature/<N>
```

### 2. Identify what to commit
Review the changed files above. Never stage:
- `.env` — contains API keys
- `data/` — runtime databases
- `logs/` — runtime log files
- `__pycache__/` — compiled bytecode
- `*.pyc` — compiled bytecode
- `agent.log` — runtime log

Only stage source files: `.py`, `.yaml`, `.md`, `.txt`, `.json`, skill files under `.claude/`.

**Never stage** `scripts/create_github_issues.sh` — this file is a historical record of all planned epics and stories. It must not be modified or re-committed. If new issues are needed, create a new script (e.g. `scripts/create_github_issues_v2.sh`) or open issues manually via `gh issue create`.

### 3. Save session notes
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

### 4. Update CLAUDE.md
Review `CLAUDE.md` in the project root and update it to reflect any changes made in this session:
- Add new pairs to the pairs table if any were added
- Update "Known Behaviours / Gotchas" if any new quirks were discovered
- Update "Session Notes" table with the new session file
- Update architecture section if any new files/modules were added

### 5. Update documentation files
Review and update the following documents to reflect changes made in this session. Only update sections that are genuinely stale — do not rewrite content that is still accurate.

**Complexity guide:**
- **Minor change** (1-2 files, bug fix, small config tweak) → update affected sections only
- **Moderate change** (new feature, multiple files) → update all affected sections across all docs
- **Large change** (new module, architectural decision, new pair) → consider full rewrite of impacted docs

#### `plan.md`
Tick off completed items. Add new planned work if discussed this session. Never remove items — mark them `[x]` or strike through.

#### `README.md`
Update setup instructions, feature list, configuration reference, or usage examples if anything changed. Rewrite if the scope of changes is large (e.g. a new major feature or architectural shift).

#### `docs/codebase.md`
This is the primary developer reference. It is generated using the `/explain` skill — read each changed module and update the corresponding section(s):
- Module deep-dives (function signatures, purpose, dependencies)
- Config reference table
- Data flow section
- Design patterns section
Rewrite the entire document if multiple modules changed significantly.

#### `docs/business_requirements.md`
Update only if a change alters a functional requirement, business rule, or pair configuration:
- Add/modify FRs in the appropriate section
- Update the pair TP/SL table if pairs changed
- Update business rules if risk thresholds changed (profit floor, kill switch, circuit breaker)
Do **not** rewrite — this is a formal BRD; append or surgically edit.

#### `docs/detailed_solution_design.md`
Update if a change affects architecture, system design, or integration contracts:
- Update sequence diagrams if a new flow was added
- Update the ADR section if an architectural decision was made
- Update the relevant module's technical description
Rewrite a section only if the flow fundamentally changed (e.g. limit order chase logic, kill switch sequence).

#### `docs/epics_stories_ac.md`
Update if new features were added or stories were completed:
- Tick off completed stories
- Add new stories under the appropriate Epic if new work was scoped
- Update Acceptance Criteria if behaviour changed
Do **not** rewrite the entire document — append or edit targeted stories only.

### 6. Update CHANGELOG.md
Append a new entry to `CHANGELOG.md` summarising the changes in this commit:
- Add a new `## Session: <today's date>` section if one does not exist for today, or append to the existing one
- Include: bugs fixed (root cause + fix), features added, files changed
- Keep it concise — bullet points or a table, not prose

### 7. Update memory
Update the relevant memory file at:
`~/.claude/projects/-Users-vipulsanghrajka-Documents-myworkdir-crypto-trader-agent/memory/project_kryptos.md`

Add any new critical conventions, config values, or architectural decisions that future sessions should know. Do not duplicate what is already there — only add what is new or changed.

### 8. Draft commit message
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

Closes #<issue-number>  ← include if a GitHub issue is fully resolved by this commit
Refs #<issue-number>    ← include if this commit is partial progress toward an issue

Co-Authored-By: Claude Sonnet 4.6
```

Always check if the changes relate to an open GitHub issue. If so:
- Use `Closes #N` in the commit body if the issue is fully resolved — GitHub will auto-close it on push.
- Use `Refs #N` if this commit is part of a larger issue that is not yet complete.
- Use `gh issue list --repo vipulbms/crypto-trader-agent` to look up issue numbers if unsure.

### 9. Stage only the appropriate files
Use `git add <specific files>` — never `git add -A` or `git add .` to avoid accidentally staging secrets or large runtime files.

Always include these documentation files when they were updated:
- `CHANGELOG.md`
- `CLAUDE.md`
- `README.md`
- `plan.md`
- `docs/codebase.md`
- `docs/business_requirements.md`
- `docs/detailed_solution_design.md`
- `docs/epics_stories_ac.md`
- The new session notes file (e.g. `docs/sessions/session_2026_04_05g.md`)

Only stage a doc file if it was actually modified in this session.

### 10. Commit and push the branch
```bash
git commit -m "..."
git push -u origin feature/<N>   # or defect/<N>
```

### 11. Raise a Pull Request
Open a PR from the feature/defect branch to `main`:
```bash
gh pr create \
  --repo vipulbms/crypto-trader-agent \
  --base main \
  --head feature/<N> \
  --title "<commit subject line>" \
  --body "Closes #<N>"
```
- Use `defect/<N>` in `--head` for defect branches.
- The PR body must include `Closes #<N>` so GitHub auto-closes the issue on merge.
- If `gh pr create` is unavailable, provide the GitHub compare URL:
  `https://github.com/vipulbms/crypto-trader-agent/compare/feature/<N>`

### 12. Confirm
Report the commit hash, branch name, PR URL, and the GitHub repo URL:
`https://github.com/vipulbms/crypto-trader-agent`
