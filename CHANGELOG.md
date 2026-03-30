# Kryptos — Session Changelog

---

## Session: 2026-03-30

### Bugs Fixed

| Bug | Root Cause | Fix |
|---|---|---|
| Daily loss limit fires immediately after every BUY (30.1% false loss) | `PaperBroker.get_balance()` returned `total_usd = cash` only, not including open position entry values. `get_daily_pnl()` used `available_cash_usd` instead of `total_usd`. After buying BNB for $209.77, cash dropped from $699.22 to $488.90, which looked like a 30.1% loss | `get_balance()` now queries `usd_value` from open positions and adds to cash for `total_usd`. `get_daily_pnl()` now uses `total_usd` |
| `close_position()` would crash on first real stop-loss or take-profit | `datetime.fromisoformat()` used inside `close_position()` but `datetime` was never imported | Added `from datetime import datetime` |
| LLM overrides valid BUY signals with HOLD (e.g. XRP BUY 0.60 → HOLD) | System prompt said "when signals are not strongly aligned, hold() is correct" — gave LLM discretion to re-evaluate raw indicators (RSI, MACD) and override the scorer. LLM saw RSI=77.1 on adjacent TRX pair and applied it to XRP reasoning | Replaced vague guidance with explicit decision rule: Signal=BUY → propose_buy, with exhaustive list of only 4 valid override conditions |

### Key Insight (prompts.py)
The LLM must not be given discretion to re-evaluate individual raw indicators after the scorer has already produced a BUY signal. The scorer weighs all indicators together — a high RSI on one pair does not cancel a BUY score that was built from MACD + BB confluence. The prompt must be a decision tree, not guidance.

### Key Insight (paper_broker.py)
This `get_balance()` / `get_daily_pnl()` bug has regressed twice. The correct invariant: `total_usd = cash + sum(usd_value of open positions)`. Buying converts cash into a position of equal entry value — `total_usd` stays flat. Only price movement or realised losses should change it.

### Critical Conventions (reinforced)
- `PaperBroker.get_balance()` must return `total_usd = cash + open_position_entry_values` — never cash-only
- `get_daily_pnl()` must use `total_usd`, never `available_cash_usd`
- `from datetime import datetime` must be present in `paper_broker.py`
- LLM prompt must give an explicit decision tree for BUY/SELL/HOLD — never vague "when in doubt, hold" language

### Files Changed

| File | Change |
|---|---|
| `src/exchange/paper_broker.py` | `get_balance()` includes open position `usd_value`; `get_daily_pnl()` uses `total_usd`; added `from datetime import datetime` |
| `src/agent/prompts.py` | Explicit decision rule: Signal=BUY → propose_buy; 4 valid override conditions listed; removed "when in doubt hold" instruction |

---

## Session: 2026-03-29 (continued — night)

### Bugs Fixed

| Bug | Root Cause | Fix |
|---|---|---|
| All pairs returning HOLD strength=0 after BB config change | `bb_min_width_pct=1.5%` was suppressing BB signals on pairs with band widths of 0.7–1.4% (most pairs) | Reverted `bb_min_width_pct` to 0.5%; fixed the real problem in `signals.py` instead |
| Simultaneous upper+lower BB signals on narrow bands | BB buy and sell checks were independent — both could fire when price was between tight bands | `near_lower` and `near_upper_for_sell` now computed once and are mutually exclusive; if both fire, neither is awarded |

### Files Changed

| File | Change |
|---|---|
| `src/analysis/signals.py` | BB upper/lower checks now mutually exclusive — simultaneous touch awards neither |
| `config.yaml` | `bb_min_width_pct` reverted to 0.5%; `bb_buy_tolerance_pct` and `bb_sell_tolerance_pct` kept at 0.5% |

### Key Insight
The BB squeeze fix belongs in the **signal logic** (mutual exclusion), not in the config threshold. Raising `bb_min_width_pct` to catch squeeze suppresses too many valid signals. The correct fix is: if price is simultaneously near both bands, award neither — the bands are too tight to be meaningful regardless of the width threshold.

### Current market state (2026-03-29 23:xx SGT)
MACD histogram is negative across all 10 pairs — genuine bearish momentum phase. No BUY signals expected until MACD turns positive or RSI drops below 30 on at least one pair. Agent correctly HOLDing.

---

## Session: 2026-03-29 (continued — evening)

### Bugs Fixed

| Bug | Root Cause | Fix |
|---|---|---|
| `Cannot operate on a closed database` in Decision Breakdown report | `risk_by_pair` query placed after `ac.close()` in `get_llm_decision_patterns()` | Moved `ac.close()` to after all queries; also removed duplicate `ac.close()` |
| BB tolerance overlap — most pairs showing both upper and lower BB signals simultaneously | `bb_buy_tolerance_pct` and `bb_sell_tolerance_pct` both 1.0% caused overlap when band width was only ~0.88%; `bb_min_width_pct` of 0.5% was too low to catch it | Raised `bb_min_width_pct` to 1.5%, reduced tolerances to 0.5% |
| LLM overriding valid BUY signals (e.g. XRP score 6/10) with HOLD | System prompt hardcoded `RSI < 35` as mandatory BUY condition; LLM ignored MACD+BB confluence when RSI was neutral | Updated `prompts.py` to tell LLM to trust the signal scorer; RSI < 30 is a bonus not a requirement |
| No BUY executions despite XRP generating BUY signal every cycle | Combination of above two bugs — BB false signals on other pairs + LLM RSI fixation | Both fixed above |

### Files Changed

| File | Change |
|---|---|
| `src/reports/trade_report.py` | Moved `ac.close()` after `risk_by_pair` query; removed duplicate close |
| `src/agent/prompts.py` | Removed hardcoded `RSI < 35` mandatory BUY rule; LLM now trusts signal scorer |
| `config.yaml` | `bb_min_width_pct` 0.5→1.5; `bb_buy_tolerance_pct` and `bb_sell_tolerance_pct` 1.0→0.5 |

### Key Insight
The signal scorer and the LLM prompt were misaligned. The scorer awards points for MACD+BB confluence without requiring RSI oversold — but the prompt told the LLM RSI < 35 was mandatory. Always keep the prompt aligned with the scoring system.

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
