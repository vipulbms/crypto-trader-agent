# Kryptos — Session Changelog

---

## Session: 2026-03-29

### Bugs Fixed

| Bug | Root Cause | Fix |
|---|---|---|
| Daily loss limit trips after first trade | `PaperBroker.get_balance()` returned cash-only as `total_usd`; buying $300 of ADA looked like a $300 loss | `total_usd` now includes open position entry cost; `get_daily_pnl()` uses `total_usd` not `available_cash_usd` |
| `AttributeError` in live mode | `KrakenClient` was missing `get_daily_pnl()` and `get_open_positions_count()` | Both methods added to `KrakenClient` |
| Decision Breakdown shows BUY=0 | `decision_type` stored as `TRADE_BUY`/`TRADE_SELL`; report expected `BUY`/`SELL` | Changed to `BUY`/`SELL` in `trading_agent.py`; migrated 3 existing DB rows |
| LLM hallucinated pair names (`SLAY/USD`, `SPICE/USD`) | Tool execution used `tool_args.get("pair")` — trusted the LLM's pair argument | Always use the signal's known `pair` variable; 38 hallucinated DB rows deleted |
| `generate_signal` logging `cycle=0` | `set_cycle_id()` called inside `TradingAgent` but signals computed before that in `main.py` | `set_cycle_id()` now called immediately after `audit.log_cycle()` in `main.py` |
| `config.yaml` `pair: 3` crash | `BTC/USD` accidentally edited to `3` in config | Restored to `BTC/USD` |
| RAILS/USD WebSocket updates dropped | `RAILS/USD` was in `REST_PAIR_MAP` but missing from `PAIR_MAP` | Added to `PAIR_MAP` in `websocket_feed.py` |

### Features Added

- **Decision Breakdown by Pair** report now shows 8 columns: LLM Buy, LLM Sell, LLM Hold, Risk ✓, Risk ✗, Executed, Final Hold
- **RAILS/USD** added as 10th trading pair (TP 20%, SL 5%) across all config and source files
- **`/add-pair` Claude Code skill** — onboards a new pair across all 7 required files in one command
- **`/commit` Claude Code skill** — stages safe files, derives conventional commit message, pushes to GitHub

### Files Changed

| File | Change |
|---|---|
| `src/exchange/paper_broker.py` | `get_balance()` includes open position value; `get_daily_pnl()` uses `total_usd` |
| `src/exchange/kraken_client.py` | Added `get_daily_pnl()`, `get_open_positions_count()`, `RAILS/USD` to pair map |
| `src/exchange/websocket_feed.py` | Added `RAILS/USD` to `PAIR_MAP` |
| `src/agent/trading_agent.py` | `TRADE_BUY`→`BUY`, `TRADE_SELL`→`SELL`; tool execution uses signal pair not LLM pair |
| `src/storage/audit_logger.py` | Updated `decision_type` comment |
| `src/reports/trade_report.py` | Decision patterns query now fetches risk approval/rejection per pair |
| `src/cli/display.py` | Decision Breakdown table expanded to 8 columns; RAILS/USD in welcome screen |
| `main.py` | `set_cycle_id()` called immediately after `audit.log_cycle()` |
| `config.yaml` | `BTC/USD` restored; `RAILS/USD` added |
| `data/audit.db` | Migrated `TRADE_BUY`→`BUY`, `TRADE_SELL`→`SELL`; deleted 38 hallucinated pair rows |
| `.claude/skills/add-pair/SKILL.md` | New skill created |
| `.claude/skills/commit/SKILL.md` | New skill created |
| `README.md` | Claude Code Skills section added; file tree updated; docs table updated |
| `business-requirement.md` | Revision 1.3; FR-76, FR-77 added; RAILS/USD in all tables; 10 pairs throughout |
| `plan.md` | Updated pair count to 10 in LLM system prompt section |

### Key Architectural Decisions

- **Broker interface contract**: Both `PaperBroker` and `KrakenClient` must implement the same methods. An abstract base class (`BaseBroker`) was recommended to enforce this — not yet implemented.
- **LLM output validation**: Never trust pair names from LLM tool arguments. Always use the known pair from the signal loop.
- **Cycle ID propagation**: `set_cycle_id()` must be called at the top of `run_cycle()` in `main.py`, before any `@timed` decorated functions run.
- **Decision type constants**: `BUY`/`SELL`/`HOLD` are used throughout. A shared constants file was recommended to prevent future mismatches.

### Commits

| Hash | Message |
|---|---|
| `34e2d6a` | fix: daily loss limit trips after first trade in paper mode |
| `9517c6b` | fix: multiple bugs + add RAILS/USD as 10th trading pair |
| `68ba58e` | docs: add /add-pair Claude Code skill usage to README and requirements |
| `28412c9` | feat: add /commit Claude Code skill and update docs |

---
