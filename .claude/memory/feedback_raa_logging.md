---
name: RAA logging conventions
description: How the ResearchAnalystAgent writes to the three shared log files
type: feedback
---

All three log files must be wired up in every standalone runtime process (research_analyst.py, data_collector.py, etc.), not just main.py.

**Why:** The RAA had scarce logs because it used `logging.basicConfig()` (stdout only) and never called `init_llm_logger` / `init_cycle_logger`. The pattern was already established in `main.py` but not carried over.

**How to apply:**

1. **agent.log** — in `main()`, replace `logging.basicConfig()` with a `RotatingFileHandler` on `agent.log` (same `log_dir`/`max_bytes`/`backup_count` from config). Add a `StreamHandler` only when `sys.stdout.isatty()` to avoid duplicate lines in background mode.

2. **agent-llm-prompts.log** — call `init_llm_logger(log_dir, config)` at startup; call `log_llm_interaction(...)` after every `ai_client.chat_with_tools()` response. Use a module-level `_SESSION_ID = uuid.uuid4().hex[:8]` and a per-module cycle counter. Pass `prompt_template` to distinguish RAA records from main-agent records (e.g. `"raa_batch_universe_decision"`).

3. **cycle_decisions.log** — call `init_cycle_logger(log_dir, config)` at startup; call `write_raa_cycle_report(cycle_id, duration_ms, candidates, decisions, persistence_data)` at the end of each `run_cycle()`. The RAA record includes `"source": "RAA"` so it can be filtered from main-agent records.

`write_raa_cycle_report` lives in `src/utils/cycle_logger.py` alongside `write_cycle_report` (main agent).
