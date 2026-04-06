---
name: Coding and collaboration preferences
description: How the user prefers to work — response style, commit format, when to ask vs act
type: feedback
---

Keep responses short and direct. No trailing summaries after tool calls.

**Why:** User can read the diff; recapping what was just done adds no value.

**How to apply:** Lead with the action or finding. Only explain when something is non-obvious or needs a decision.

---

Always prepare a git commit statement for review before executing, unless the user says "commit" directly or invokes /commit.

**Why:** User wants to review commit messages before they're pushed.

**How to apply:** When changes are ready, show the proposed commit message as a code block. Only execute when asked.

---

When bugs are found while investigating something else, fix them immediately and mention them concisely.

**Why:** User expects proactive fixes, not just reports.

**How to apply:** Fix the bug, show a one-liner explanation, move on.

---

Always check the agent.log when the user opens it — they're signalling they want a diagnosis.

**Why:** User uses the IDE file open as a signal to investigate.

**How to apply:** Read the tail of the log immediately and report the latest error or status.

---

Delegate downloads, model pulls, and any other human-executable tasks to the user instead of running them via Bash.

**Why:** HITL preference — user wants to conserve tokens and handle non-code tasks themselves.

**How to apply:** When a download or install is needed (e.g. `ollama pull`, `pip install`, `brew install`), give the exact command for the user to run rather than executing it. Do not use Bash for these.
