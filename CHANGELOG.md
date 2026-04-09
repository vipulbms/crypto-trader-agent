# Kryptos — Session Changelog

---

## Session: 2026-04-09 (Part D) — Backtest Clean-Slate Teardown Fix (#122)

### Bug Fixed
- **[#122] Stale DB contamination in backtest**: `test_backtest.py` teardown used a manually constructed `data_dir` path that could diverge from `database.py`'s `get_connection()` path. Also had no post-teardown validation — contaminated state could silently proceed.

### Changed
- **`src/storage/database.py`**: Added `get_db_path()` public alias for `_get_db_path()`.
- **`tests/test_backtest.py`**:
  - Teardown now uses `get_db_path()` — same resolution as `get_connection()`.
  - After deletion, explicitly re-inits paper and audit DBs.
  - Asserts 0 open positions and `cash == starting_balance` before feed starts; aborts on contamination.
  - Logs `Validated: 0 open positions, wallet=$X.XX` at startup.

---

## Session: 2026-04-09 (Part C) — Disable Time-of-Day Guard

### Changed
- **[#121] `config.yaml`**: `allowed_trading_hours.enabled: false` — time-of-day guard disabled; agent now trades at any hour.
- **[#121] `.claude/skills/trading-rules/SKILL.md`**: Updated Volume & Time-of-Day Guard rule to reflect disabled state.
- **[#121] `.claude/memory/project_kryptos.md`**: Trading Hours section updated.

Note: Volume dead zone check (`min_volume_ratio` / `rolling_volume_p15`) remains always-on in `signals.py` Hard Blocker 3.

---

## Session: 2026-04-09 (Part B) — Adaptive Injections, MACD Normalisation, 90% Capital, Signal Drivers

### Fixed
- **[#108] `main.py` + `config.yaml`**: Adaptive ATR floor — rolling p25 ATR% × 0.8 injected as `adaptive_atr_floor_pct` per cycle. Config: `adaptive_atr_floor.{enabled, scaling_factor: 0.8, min_cap_pct: 0.10, lookback_candles: 400}`.
- **[#112] `src/analysis/features.py` + `config.yaml`**: MACD decay threshold normalised — `macd_decay_threshold_pct: -0.005` (% of price) replaces absolute `-0.0005`. Fires consistently regardless of pair price scale.
- **[#115] `src/exchange/paper_broker.py`**: `hold_secs` in backtest computed from candle `timestamp_override`, not wall clock `now_sgt()`.

### Added
- **[#113] `main.py` + `config.yaml`**: Adaptive BB squeeze — rolling p10 BB width% injected as `_rolling_bb_p10_pct` per cycle. Config: `adaptive_bb_squeeze.{enabled, lookback_candles: 400, percentile: 10}`.
- **[#114] `main.py` + `config.yaml`**: Adaptive volume floor — rolling p15 raw volume injected as `rolling_volume_p15` per cycle. Config: `adaptive_volume_floor.{enabled, lookback_candles: 400, percentile: 15}`.
- **[#116] `config.yaml`**: Position cap removed — `max_open_positions: 13`, `max_position_pct: 15%`, `max_buys_per_cycle: 5`. Up to 90% capital deployment with 10% cash floor.
- **[#117] `src/reports/trade_report.py` + `src/cli/commands.py` + `src/cli/display.py` + `kryptos.py`**: Signal driver report. `kryptos.py drivers [--days 30] [--top 10]` shows top blockers/drivers per pair.
- **[#118] `scripts/calibrate_params.py`**: Parameter calibration utility. Analyses historical candles and outputs recommended config YAML changes for all 5 per-pair signal parameters.

### Tests
- `tests/test_adaptive_atr_floor.py`: 7 tests for adaptive ATR floor computation and signal integration.
- `tests/test_candle_timestamps.py`: 3 tests verifying candle timestamps in opened_at, closed_at, hold_secs.

---

## Session: 2026-04-09 (Part A) — Per-Pair Signal Parameters, Backtest Hours Fix, Analysis Scripts

### Fixed
- **[#106] `tests/test_backtest.py`**: Backtest now forces `allowed_trading_hours.enabled=False` — previously the 1-hour trading window caused only ~84 LLM calls per 2,016-candle backtest (96% suppression).
- **[#107] `config.yaml` + `src/analysis/signals.py`**: Per-pair `atr_tp_min_pct` replaces broken global 1.0% floor. Global floor was blocking 93–99.8% of all signals with zero selectivity. Per-pair values (BTC=0.14%, TRX=0.12%, INJ=0.34%) derived from p25 ATR% × 0.8 with min cap.
- **[#109] `config.yaml` + `src/analysis/signals.py`**: Per-pair `rsi_oversold` (BNB/XRP/LTC→28, TRX→35) and `rsi_overbought` (TRX→65, XRP/DOGE/ADA/LTC/SUI/INJ→72) — calibrated so each pair fires oversold/overbought ~5–8% of candles.
- **[#110] `config.yaml` + `src/analysis/features.py`**: Per-pair `bb_squeeze_threshold_pct` (BTC=0.7%, INJ=2.5%) — global 1.0% was incorrectly declaring SOL/SUI/UNI/INJ in squeeze most of the time, clamping dynamic TP to minimum.
- **[#111] `config.yaml` + `src/analysis/signals.py`**: Per-pair `min_volume_ratio` — BNB/UNI/INJ→0.30 (dead zone was blocking 57–58% of candles at global 0.50).

### Added
- **`scripts/analyse_atr_profile.py`**: ATR% distribution per pair from historical candles.
- **`scripts/analyse_pair_params.py`**: Full statistical analysis of RSI, MACD, BB, volume per pair.
- **`scripts/analyse_rolling_windows.py`**: Rolling-window stability (CV) + buy/sell signal win rate analysis.
- **`docs/plan_per_pair_params.md`**: Full plan for all 12 parameter changes with data-derived recommendations.
- **`tests/test_per_pair_params.py`**: 20 new tests covering per-pair ATR floor, RSI, BB squeeze, volume ratio, and adaptive injection overrides.
- **GitHub issues #107–#118**: All 12 planned changes documented with What/Why/How.

### Infra
- `adaptive_atr_floor_lookback: 400` added per-pair in config — placeholder for future adaptive floor injection from `main.py` (Fix #108, pending).
- ATR floor priority chain documented: injected adaptive → per-pair static → global fallback → min_profit_floor.

---

## Session: 2026-04-08 (Part C) — Trailing Stop Tuning, ATR Floor, BB Squeeze TP, Trading Hours

### Fixed
- **[#102] `config.yaml` + `paper_broker.py` + `kraken_client.py`**: Trailing stop `trail_pct` 3→5%, `activate_after_pct` 1.5→3.0%. Per-pair overrides now support dict `{trail_pct, activate_after_pct}`: DOGE/RAILS/HYPE 7%/5.0%, SUI 6%/4.0%. Prevents SOL/AVAX-style near-breakeven exits from 2% consolidations.
- **[#103] `config.yaml`**: `atr_tp_min_pct` 0.3→1.0% — blocks entries in compressed markets where ATR% is too small to justify 5% SL risk (root cause of DOGE/UNI/INJ full -5.29% SL hits).
- **[#104] `src/analysis/features.py:compute_dynamic_tp()`**: Implemented BB squeeze guard — when BB width < `squeeze_threshold_pct` (1.0%), TP clamps to pair floor. `bb_width_scale: true` config was previously a no-op.
- **[#95] `src/analysis/features.py:compute_dynamic_tp()`**: Dynamic TP now uses `max(global_min, pair_static_tp)` as floor — DOGE/RAILS/HYPE no longer get 5% TP in low-ATR conditions.
- **[#105] `config.yaml`**: Trading window narrowed to 03:00–04:00 SGT (19:00–19:59 UTC, 1 hour) for focused testing.
- **59 tests pass** (1 pre-existing import error unrelated to these changes)

---

## Session: 2026-04-08 (Part B) — Backtest Timestamps, Chart Legend, Charts in Reports

### Fixed
- **`src/exchange/paper_broker.py`** — `place_order()` / `close_position()` accept `timestamp_override: Optional[str]`; new `_ts(override)` helper uses candle timestamp in backtest, wall clock in live — closes #98
- **`src/exchange/historical_feed.py`** — `current_candle_time: int` property exposes the last-advanced candle epoch so `main.py` can pass it into the broker
- **`src/agent/tools.py`** — `propose_buy()` / `propose_sell()` pass candle ISO timestamp to broker as `timestamp_override`
- **`main.py`** — passes `candle_ts=feed.current_candle_time` to `broker.check_stops_and_tp()`

### Added
- **`src/reports/chart_generator.py`** — core charting engine (extracted from `scripts/chart_trades.py`); public API: `generate_charts()`, `render_trade_chart()`; full proxy-artists legend (BUY ▲, TP ▼, SL ▼, SELL ▼, PARTIAL TP ▼, entry/exit price dashes) — closes #99 / #100
- **`scripts/chart_trades.py`** — reduced to thin 54-line wrapper
- **`src/cli/commands.py`** — `cmd_charts()` added; `cmd_daily_report()` / `cmd_review()` accept `charts: bool` flag — closes #100
- **`kryptos.py`** — `charts` subcommand; `--charts` flag on `daily` and `review`; `--pair`, `--out`, `--window` args on `charts`
- **`tests/test_backtest_timestamps.py`** — 6 new tests for timestamp fix
- **`tests/test_chart_generator.py`** — 23 new tests for chart engine
- **Full test suite: 80 tests pass**

---

## Session: 2026-04-07 (Part C) — HistoricalFeed Timestamp-Based Lookup Fix

### Fixed
- **`src/exchange/historical_feed.py`** — complete rewrite to use timestamp-based candle lookup instead of position-based indexing
  - **Root cause:** single global `_position` counter clamped via `min(pos, len-1)` always returned the last candle for shorter pairs (BNB/USD: 24k candles vs BTC/USD: 429k candles). Prices were frozen at the entry value forever — positions never hit SL or TP.
  - **Fix:** `_ref_pair` tracks the pair with the most candles. `_current_ts` is the timestamp of the current reference candle. Each pair uses `bisect.bisect_right` on its sorted timestamp list to find the correct candle for the current cycle.
  - Shorter pairs with no data at `_current_ts` return `None` / `[]` (guarded by `is_ready()` in main loop), so pairs like HYPE/USD with limited history are safely skipped before their data begins.
- All 51 tests pass.

---

## Session: 2026-04-07 (Part B) — Migrate Claude Memory to Project Scope

### Added
- **`.claude/memory/`** directory with 4 files committed to git: `project_kryptos.md`, `feedback_coding_style.md`, `feedback_testing.md`, `feedback_github_traceability.md`
- **`CLAUDE.md`**: added `@.claude/memory/*.md` import directives so all contributors and Claude sessions auto-load the shared context — closes #91

---

## Session: 2026-04-07 (Part A) — Trading Hours Window Fix (SGT)

### Fixed
- **`config.yaml`** `allowed_trading_hours`: corrected to `start_hour_utc: 22` / `end_hour_utc: 20` (06:00–04:00 SGT, cross-midnight UTC window). Previous values (`start: 06`, `end: 23/24`) were left-over from UTC-centric tuning and blocked the 23:00 UTC (07:00 SGT) hour due to exclusive `<` comparison.
- **`.claude/skills/trading-rules/SKILL.md`**: updated Time-of-Day Guard description to show `06:00–04:00 SGT / 22:00–20:00 UTC, cross-midnight`.
- No code changes — the cross-midnight logic (`current_hour >= start OR current_hour < end`) was already in `risk_manager.py`.

---

## Session: 2026-04-06 (Part E) — Partial Take-Profit

### Added
- **`partial_take_profit` config block** (`config.yaml`): enabled flag, trigger_pct_of_tp (50%), close_fraction (0.5), move_sl_to_breakeven
- **`close_position(volume_override)` parameter** (`paper_broker.py`, `kraken_client.py`): partial close reduces volume/usd_value in DB; position stays open; `partial_exited=1` set
- **Step 3 partial TP in `check_stops_and_tp()`** (`paper_broker.py`, `kraken_client.py`): fires when price ≥ entry×(1+tp_pct×trigger_ratio/100); guarded by `partial_exited` flag; optionally moves SL to entry after close
- **`tests/test_partial_tp.py`** (5 tests): fires at trigger, silent before trigger, no double-fire, SL-to-entry after partial, wallet credit check
- Full test suite: **51 tests pass** — closes #87

---

## Session: 2026-04-06 (Part D) — Breakeven Stop Tests

### Added
- **`tests/test_breakeven_stop.py`** (3 tests): SL moves to entry at trigger, no-move before threshold, no re-fire guard — closes #85

---

## Session: 2026-04-06 (Part C) — Signal Coverage & Profit Margin Fixes

### Fixed
- **ATR floor decoupled** (`signals.py`, `config.yaml`): `dynamic_tp.atr_tp_min_pct: 0.3` — BTC/ETH/SOL now pass ATR gate (was blocked by 1% floor)
- **RSI overbought 60→65** (`config.yaml`): Reduces premature SELL signals before TP targets are reached
- **validate_sell() TP proximity guard** (`risk_manager.py`, `config.yaml`): Code-enforces BRD FR-20 — LLM blocked until P&L ≥ 80% of TP target; closes #83
- **5 unit tests** (`tests/test_risk_manager.py`): All proximity guard scenarios covered

---

## Session: 2026-04-06 (Part A) — Backtest Analysis & GitHub Issues Shell Script

### Analysis
- Diagnosed early-sell bug from 3,931-cycle backtest: `validate_sell()` has no upper-side proximity guard → LLM exits at 2–4% despite TP targets of 5–20%
- Root cause: BRD FR-20 (80% TP proximity before early exit) is prompt-only, not code-enforced

### Added
- `scripts/create_github_issues.sh` — comprehensive script creating all 12 epics (E1–E12) and 28 stories as GitHub issues with full AC and traceability to BRD FR-XX, DSD §X.X, NFR-XX, code file::function
- Stories are registered as GitHub sub-issues under their parent epic via `gh api POST /repos/{owner}/{repo}/issues/{num}/sub_issues`
- E12 (new epic) covers: propose_sell proximity guard (bug), trailing stop, breakeven stop, ATR-based SL, partial take-profit

---

## Session: 2026-04-05 (Part F) — Documentation: BRD, Detailed Design, Epics/Stories

### Added

| Artifact | File | Summary |
|---|---|---|
| Business Requirements Document | `docs/business_requirements.md` | 8 FRs, 6 NFRs, bug resolution table, setup guide |
| Detailed Solution Design | `docs/detailed_solution_design.md` | 10 sections, 9 Mermaid diagrams, 7 ADRs, LLM architecture deep-dive, Skills system docs |
| Epics, Stories & AC | `docs/epics_stories_ac.md` | 11 Epics, 40+ Stories with Gherkin AC, traceability matrix |

### Removed
- Deleted `random_execution_kraken.py` — stale exploration prototype
- Deleted `test_ws.py` — stale WebSocket exploration script

---

## Session: 2026-04-05 (Part E) — Global Kill Switch & Backtest Telemetry

### Features Added

| Feature | Files | Notes |
|---|---|---|
| Global Max Daily Loss (Kill Switch) | `config.yaml`, `main.py`, `kraken_client.py` | Protects the portfolio at 7% drawdown; executes a mass limit-cancellation and market-sell out of crypto. |
| Backtesting Lifecycle Refinement | `test_backtest.py` | Native flush of `backtest_paper.db` and log rotations allowing sterile execution runs. |
| Audit Rejection Utility | `scripts/audit_rejections.py` | Extracts telemetry indicating why algorithmic blocks triggered. |

---

## Session: 2026-04-05 (Part B) — Confluence scoring, circuit breaker, heartbeat

### Features Added

| Feature | Files | Notes |
|---|---|---|
| Multi-indicator confluence BUY scoring | `signals.py`, `indicators.py`, `config.yaml` | 10 contributors, min score 5; removed all hard EMA gates |
| MACD histogram turn detection | `indicators.py` | `macd_histogram_prev` added; turn = +3, continuation = +1 |
| Fear & Greed injected into signal scoring | `main.py`, `signals.py` | Fetched once/cycle; +1 fear ≤40, +2 extreme fear ≤25 |
| ATR profit floor veto | `signals.py` | Blocks entry if ATR-based TP < `min_profit_floor_pct` |
| Circuit breaker (DB-backed) | `risk_manager.py`, `config.yaml` | Reads last 3 trades within 4h window; no extra table needed |
| Heartbeat notification | `notifier.py`, `main.py`, `config.yaml` | Hourly Telegram summary in live mode |
| Circuit breaker tests | `tests/test_circuit_breaker.py` | 4 Gherkin-annotated test cases |

### Files Changed

| File | Change |
|---|---|
| `src/analysis/signals.py` | Full rewrite — confluence scoring, two vetoes, helper functions |
| `src/analysis/indicators.py` | Added `macd_histogram_prev`; removed candle-counting reversal detector |
| `src/risk/risk_manager.py` | Circuit breaker reads trade history via SQL time window; `db_path` param |
| `src/notifications/notifier.py` | Added `send_heartbeat()` and `send_circuit_breaker_tripped()` |
| `main.py` | Fear & Greed injection; heartbeat loop; circuit breaker wiring; `run_cycle` returns buy/sell counts |
| `config.yaml` | New signal score weights; circuit breaker block; heartbeat interval |
| `.claude/skills/trading-rules/SKILL.md` | Aligned with confluence scoring and circuit breaker rules |

---

## Session: 2026-04-01 (Part C) — Backtesting pipeline

### Features Added

| Feature | Files | Notes |
|---|---|---|
| Candle data loader | `tests/backtest/loader.py` | Maps 15 pairs to history JSON files; normalises Kraken tick arrays |
| In-memory BacktestBroker | `tests/backtest/broker.py` | PaperBroker equivalent; intra-candle SL/TP using high/low |
| Backtest runner | `tests/backtest/runner.py` | Slides candle window; deterministic signal-following agent |
| Report generator | `tests/backtest/report.py` | P&L, per-pair stats, trade log, Sharpe ratio, balance history |
| Backtest entry point | `tests/test_backtest.py` | `python tests/test_backtest.py`; prints report + bug list |

### Bugs Fixed (in backtest code)

| Bug | Fix |
|---|---|
| `hold_candles` was epoch-seconds delta not candle count | Divide by `15 * 60` to convert to candle count |

### Bugs Identified (production + data)

| # | Bug | Severity |
|---|---|---|
| BUG-1 | `AVAXSD_candle.json` filename missing 'U' | Low |
| BUG-2 | `indicators.py` returns `ema_50` key even when `ema_slow=200` | Low |
| BUG-3 | Kraken OHLC API 720-candle cap — only 7.5 days returned, not 12 months | High |
| BUG-4 | CLAUDE.md INJ/USD TP listed as 16%, config says 20% | Low |
| BUG-5 | SL/TP checked once per 30-min cycle — flash crash risk | Medium |

### Backtest Results (7.5-day window, March 24–April 1, 2026)

| Metric | Value |
|---|---|
| P&L | -$18.33 (-1.83%) |
| Win rate | 63.6% |
| Win/Loss ratio | 0.67x |
| TP hits / SL hits | 0 / 4 |

---

## Session: 2026-04-01 (Part B) — LLM model switch + live broker parity

### Bugs Fixed

| Bug | Root Cause | Fix |
|---|---|---|
| LLM timeout every cycle since midnight | `qwen2.5:14b` runs on CPU (no GPU) — 700–900 s per inference, consuming full 900 s timeout. Fallback `llama3.1:8b` was never installed, producing 404 with no recovery | Switched to `deepseek-r1:7b` (half size, ~2× faster); fallback to `deepseek-r1:7b`; timeout reduced to 600 s |
| Prompts.py said "every 15 minutes" | Stale copy from before cycle interval was doubled to 30 min | Updated SYSTEM_PROMPT to say "every 30 minutes" |
| Live mode non-functional | `KrakenClient.get_balance()` used market value; `get_open_positions()` called `fetch_open_orders()` (wrong); `close_position()` and `check_stops_and_tp()` missing | Complete `KrakenClient` rewrite — all methods now mirror `PaperBroker` interface, positions tracked in `live_trading.db` |
| SL/TP loop only ran in paper mode | `if mode == "paper":` guard in `main.py` prevented live SL/TP checks | Removed guard — SL/TP loop now runs for both paper and live |

### Files Changed

| File | Change |
|---|---|
| `config.yaml` | `model` → `deepseek-r1:7b`; `fallback_model` → `deepseek-r1:7b`; `timeout_seconds` 900 → 600 |
| `src/agent/prompts.py` | Cycle interval doc fix: 15 min → 30 min |
| `src/exchange/kraken_client.py` | Full rewrite — `live_db` param; `get_balance()` mirrors PaperBroker; `get_open_positions()` from DB; `close_position()` new; `check_stops_and_tp()` new |
| `main.py` | Wire `live_db` to `KrakenClient`; remove `if mode == "paper":` guard from SL/TP loop |

---

## Session: 2026-04-01 (Part A) — Regime caution factor + dynamic TP code-enforced; tests added

### Bugs Fixed

| Bug | Root Cause | Fix |
|---|---|---|
| `caution_factor` computed but never applied | `detect_market_regime()` returned `caution_factor` (0.5/0.7) in `ai_context["regime_data"]` but nothing in `main.py` consumed it — position size was never actually reduced in bearish/volatile markets | After `build_ai_context()`, `portfolio["max_per_trade"]` is now scaled by `caution_factor` before the LLM cycle |
| Dynamic TP advisory only — not used at order placement | `compute_dynamic_tp()` computed ATR/BB-adjusted TP and injected text into LLM prompt, but `propose_buy()` always called `self._risk.get_take_profit_pct(pair)` (static config) — actual TP stored in `paper_positions` was always the static value | Added `compute_dynamic_tp_values()` to `features.py`; wired through `build_ai_context()` → `trading_agent.run_cycle()` → `TradingTools.set_dynamic_tp_values()` → `propose_buy()` |

### Features Added

| Feature | Files | Notes |
|---|---|---|
| `compute_dynamic_tp_values()` | `src/analysis/features.py` | Returns `{pair: tp_pct}` for all pairs; included in `build_ai_context()` output as `"dynamic_tp_values"` |
| `set_dynamic_tp_values()` on `TradingTools` | `src/agent/tools.py` | Called once per cycle by `TradingAgent`; values used in `propose_buy()` |
| Regime caution scaling | `main.py` | Logs `[REGIME]` when caution applied |
| 18 unit tests | `tests/test_regime_and_dynamic_tp.py` | Covers dynamic TP clamping, `build_ai_context` keys, `propose_buy` TP override, caution factor scaling and regime detection |

### Docs Updated

- `CLAUDE.md` — session notes table updated; two new gotchas added
- `README.md` — pairs table updated to 15 pairs
- `plan.md` — pairs list updated (10→15); cycle interval corrected (15→30 min); decision cycle step updated for single-LLM-call architecture and AI context
- `business-requirement.md` — FR-01 and scope updated to 15 pairs
- `.claude/skills/commit/SKILL.md` — steps 2–4 added (session notes, CLAUDE.md, docs review)

### Files Changed

| File | Change |
|---|---|
| `main.py` | Apply `caution_factor` to `portfolio["max_per_trade"]` after `build_ai_context()` |
| `src/analysis/features.py` | `compute_dynamic_tp_values()` added; `build_ai_context()` returns `"dynamic_tp_values"` |
| `src/agent/tools.py` | `_dynamic_tp_values` field; `set_dynamic_tp_values()`; `propose_buy()` uses dynamic TP |
| `src/agent/trading_agent.py` | `set_dynamic_tp_values()` called in `run_cycle()` |
| `tests/test_regime_and_dynamic_tp.py` | NEW — 18 unit tests |
| `.claude/skills/commit/SKILL.md` | Extended pre-commit steps |

---

## Session: 2026-03-30 (Part B) — AI Features, New Pairs, Config Refactor

### AI Features Added (src/analysis/features.py)

All 7 features are config-driven — no literals hardcoded in Python. All controlled via `config.yaml`.

| # | Feature | Description | Config Key |
|---|---|---|---|
| 1 | **Position Sizing** | Scale trade size by signal strength × ATR volatility. Weak signals get smaller size; high ATR reduces size to control risk | `position_sizing` |
| 2 | **Dynamic Take-Profit** | ATR-based TP: `ATR × multiplier / entry_price × 100`. Reduced to `min_tp_pct` when Bollinger Bands squeeze (low volatility) | `dynamic_tp` |
| 3 | **Market Regime Detection** | Count pairs with negative/positive MACD histogram. Classify as bearish/bullish/volatile/ranging. Inject `caution_factor` into LLM context | `regime` |
| 4 | **Fear & Greed Sentiment** | Fetch Alternative.me Fear & Greed Index (0–100). Cached for `cache_minutes`. Extreme Fear → LLM warned to be conservative | `sentiment` |
| 5 | **Pattern Analysis** | Query closed paper trades for per-pair win rate, avg P&L, most common exit reason. Injected as LLM advisory context | `pattern_analysis` |
| 6 | **Exit Timing** | Detect open position momentum decay: MACD histogram decay, RSI overbought, price stalled vs ATR. Returns advisory reason string | `exit_timing` |
| 7 | **Post-Trade LLM Analysis** | After each closed trade (agent sell, SL, or TP), LLM writes 2–3 sentences on why the trade succeeded or failed | `post_trade` |

### AI Feature Wiring

| File | Change |
|---|---|
| `src/analysis/features.py` | New file — all 7 features implemented |
| `main.py` | `build_ai_context()` called before each LLM cycle; `llm_client` passed to `TradingTools`; post-trade analysis triggered on SL/TP close |
| `src/agent/trading_agent.py` | `run_cycle()` accepts `ai_context` param; passed to `build_cycle_prompt()` |
| `src/agent/tools.py` | `llm_client` stored; `_run_post_trade_analysis()` added; called from `propose_sell` and SL/TP loop |
| `src/agent/prompts.py` | `build_cycle_prompt()` injects all 6 AI context blocks (regime, sentiment, patterns, exit_timing, position_sizing, dynamic_tp) |
| `config.yaml` | 7 new sections added with full literal configuration |

### Exit Timing Prompt Fix

- **Bug**: LLM treated Feature 6 exit timing alerts as commands — sold BNB at -0.14% when SL was at -5% and TP was +12%
- **Fix**: Added `EXIT MANAGEMENT` section to `SYSTEM_PROMPT`:
  - SL/TP owns all exits — LLM must not call `propose_sell` on stalled positions
  - Exit timing alerts are INFORMATIONAL only
  - `propose_sell` on open position only if Signal=SELL AND clear momentum reversal confirmed

### New Trading Pairs (15 total)

| Pair | WS Name | REST Name | TP% | Rationale |
|---|---|---|---|---|
| AVAX/USD | AVAX/USD | AVAXUSD | 15% | High volatility L1 |
| SUI/USD | SUI/USD | SUIUSD | 20% | High-beta L1 |
| HYPE/USD | HYPE/USD | HYPEUSD | 20% | High volatility DeFi |
| UNI/USD | UNI/USD | UNIUSD | 15% | DeFi blue chip |
| INJ/USD | INJ/USD | INJUSD | 20% | DeFi/L1 hybrid |

### Config-Driven Pair Maps (Architecture Refactor)

**Before**: `PAIR_MAP`, `REST_PAIR_MAP`, `KRAKEN_PAIR_MAP` hardcoded in Python files — adding a pair required editing 7+ files.

**After**: `config.yaml` is the single source of truth:
```yaml
- pair: BTC/USD
  ws_name: XBT/USD      # Kraken WebSocket v2 symbol
  rest_name: XBTUSD     # Kraken public REST OHLC symbol
  take_profit_pct: 8
  stop_loss_pct: 5
```
Adding a new pair now only requires editing `config.yaml` (plus prompts/display for the pair list text).

### Backfill Key Bug Fix

- **Bug**: `_backfill_pair()` called `result.get(rest_pair)` but Kraken REST returns data under its internal key (`XXBTZUSD` for BTC, `XDGZUSD` for DOGE) — not the name we sent
- **Fix** (`websocket_feed.py`):
  ```python
  result_key = next((k for k in result if k != "last"), None)
  candles_raw = result.get(result_key, []) if result_key else []
  ```

### Daily Loss Limit Notification Spam Fix

- **Bug**: `send_daily_loss_limit_reached()` called every 15-minute cycle after limit hit — hundreds of alerts per day
- **Fix** (`main.py`): `loop_state = {"daily_loss_notified_date": None}` shared across cycles; notification sent only once per calendar date; resets at midnight

### LLM Debug Logging

- **New**: Full LLM prompt + HTTP response logged at DEBUG level in `logs/agent.log`
- **Config**: `storage.llm_debug_logging: false` — set `true` to enable
- Console stays at INFO; file log receives DEBUG (prompts, requests, responses, token counts)
- Log tags: `[LLM PROMPT]`, `[LLM REQUEST]`, `[LLM RESPONSE]`

### New Tool: rsi_verifier.py

- Fetches live RSI from Kraken public REST API for all monitored pairs
- Reads pairs from `config.yaml` — no hardcoded list
- Args: `--interval` (candle minutes), `--window` (RSI period), `--threshold` (overbought level)

### Updated: add-pair Skill

- Old skill referenced now-removed `PAIR_MAP`/`REST_PAIR_MAP`/`KRAKEN_PAIR_MAP`
- New skill: only update `config.yaml` (with `ws_name`+`rest_name`) + prompts/display/nl_parser/random_execution_kraken
- Includes live Kraken API verification step

### Bugs Fixed This Session

| Bug | Root Cause | Fix |
|---|---|---|
| LLM closes open positions on stall signal | Feature 6 exit timing alert injected into prompt; LLM treated it as action command | Added EXIT MANAGEMENT rules to SYSTEM_PROMPT |
| Daily loss limit notification spam | No deduplication — fired every cycle after limit hit | `loop_state` date tracking; notify once per day |
| REST backfill fetching wrong candles | Kraken response key differs from request name (e.g. `XXBTZUSD` ≠ `XBTUSD`) | Use `next(k for k in result if k != "last")` |

### Files Changed This Session

| File | Change |
|---|---|
| `src/analysis/features.py` | NEW — all 7 AI features |
| `config.yaml` | `ws_name`/`rest_name` on all pairs; 5 new pairs; 7 AI feature sections; `llm_debug_logging` |
| `src/agent/prompts.py` | EXIT MANAGEMENT section; AI context blocks injected |
| `src/agent/trading_agent.py` | `ai_context` param; LLM prompt/response debug logging |
| `src/agent/tools.py` | `llm_client`; `_run_post_trade_analysis()`; all 15 pairs in docstring |
| `src/exchange/websocket_feed.py` | Config-driven pair maps; backfill key bug fix |
| `src/exchange/kraken_client.py` | Config-driven pair map; `config` param in `__init__` |
| `src/cli/display.py` | Welcome banner updated to 15 pairs |
| `src/cli/nl_parser.py` | PAIRS list and LLM prompt updated for 15 pairs |
| `main.py` | Daily loss spam fix; `build_ai_context` wired; `config` to KrakenClient; DEBUG logging |
| `rsi_verifier.py` | NEW — live RSI verifier |
| `random_execution_kraken.py` | PAIRS updated to 14 pairs |
| `.claude/skills/add-pair/SKILL.md` | Updated to config-driven architecture |
| `docs/sessions/session_2026_03_30b.md` | Session notes |

### Commit
| Hash | Message |
|---|---|
| `4b08e80` | feat: 5 new pairs, config-driven pair maps, AI features 1-7, LLM debug logging |

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

## Session: 2026-04-04 (Part A) — Volatility-Adaptive Quant Migration

### Features Added

| Feature                 | Files                                                      | Notes                                                              |
|-------------------------|------------------------------------------------------------|--------------------------------------------------------------------|
| Trend & Momentum        | `src/analysis/indicators.py`, `src/analysis/signals.py`    | Overhauled EMA 9/21/50 usage, removed strict 8-red/4-green block.  |
| Adaptive Risk Mgmt      | `src/analysis/features.py`, `src/risk/risk_manager.py`     | Position sizing/TP/SL naturally scales dynamically by ATR.         |
| Order Book Imbalance    | `src/exchange/websocket_feed.py`                           | Added real-time L2 order book streaming for Imbalance constraints. |
| Limit Orders            | `src/exchange/paper_broker.py`, `KrakenClient`             | Maker limit orders implemented over taker market orders.          |
| Unified Backtesting     | `tests/test_backtest.py`                                   | Full production backtest rig overriding legacy determinism script. |

---

## Session: 2026-04-05 (Part A) — Minimum Profit Floor and Trading Rules SKILL

### Features Added
- **Minimum Profit Floor**: Added a 1.0% minimum profit floor to prevent the agent from closing trades for micro-profits that would map to net losses after Kraken Maker/Taker fees.
- **Configurable Profit Floor**: Added `min_profit_floor_pct` to `config.yaml`.
- **Trading Rules SKILL**: Moved hardcoded trading rules from the agent prompt into `.claude/skills/trading-rules/SKILL.md` to be dynamically loaded, deduplicating logic.
- **Strict PNL Validation**: Updated `src/risk/risk_manager.py` to strictly reject sell requests that do not meet the minimum profit floor. The live execution price from the WebSocket is now used to calculate the estimated PNL during `propose_sell`.

## Session: 2026-04-05 (Part C) — Live API Execution Fixes

### Bugs Fixed
- **Kraken Client Limits**: Fixed a critical execution sequence bugs where Stop-Loss/Take-Profit orders were placed instantly right after a Limit Buy Order in `kraken_client.py`, triggering 'Insufficient Funds'. Orders are now gracefully queued until the initial Limit executes.
- **Kraken Client Fallbacks**: Fixed a fallback exit bug where missed native SL/TP triggers incorrectly just canceled orders instead of issuing a market sell.

### Features Added
- **VPS Telemetry**: Built 2-Hour Heartbeats, 6-Hour PnL reports, and explicit start/stop telemetry events.
- **Dependency Locking**: Generated a strict `requirements.txt` pinned version file.
- **Defensive Unit Testing**: Constructed `tests/test_indicators.py` explicitly verifying indicators and ATR stop loss dynamic ranges.

## Session: 2026-04-05 (Part C) — Live API Execution Fixes

### Bugs Fixed
- **Kraken Client Limits**: Fixed a critical execution sequence bugs where Stop-Loss/Take-Profit orders were placed instantly right after a Limit Buy Order in `kraken_client.py`, triggering 'Insufficient Funds'. Orders are now gracefully queued until the initial Limit executes.
- **Kraken Client Fallbacks**: Fixed a fallback exit bug where missed native SL/TP triggers incorrectly just canceled orders instead of issuing a market sell.

### Features Added
- **VPS Telemetry**: Built 2-Hour Heartbeats, 6-Hour PnL reports, and explicit start/stop telemetry events.
- **Dependency Locking**: Generated a strict `requirements.txt` pinned version file.
- **Defensive Unit Testing**: Constructed `tests/test_indicators.py` explicitly verifying indicators and ATR stop loss dynamic ranges.

## Session: 2026-04-05 (Part B) — Fat Finger and Balance Guards

### Features Added
- **Fat Finger Guard**: Dynamic Balance Validation. Added `max_safe_allocation = available_cash_usd * 0.98` to buffer 2% cash and protect from failed execution. Added strict checks to prevent enormous token quantity purchases caused by floating point limits or order fat fingers.
- **Flash Crash Anomaly Detection**: Rejected orders when current asset price plummets below macroscopic baseline pricing limits.

## [Unreleased]
### Added
- Execution: Post-Only limit orders with 60-second replacement chase logic to mitigate taker fees.
- Strategy: Time-of-Day filter (16:00-20:00 UTC) and Volume guards (>50% 20-SMA).
- Architectural: Healthcheck webhook ping on agent loop completion to monitor for deadlocks.

## Session: 2026-04-05 (Part G) — Documentation Suite

### Documentation Added / Updated
- **README.md rewrite**: Full rewrite reflecting quantitative migration — confluence scoring, ATR sizing, dynamic TP, OBI, limit orders, profit floor, kill switch, heartbeat, healthchecks.io. All 15 pairs listed with correct TP%. Configuration reference table and architecture section added.
- **docs/business_requirements.md (BRD v2.0)**: Formal rewrite from scratch — 13 sections, 99+ numbered FRs, 15 Business Rules, 23-term glossary, revision history table, pair configuration table.
- **docs/codebase.md** (new): Developer reference covering all 13 modules with function signatures, DB schema, config.yaml parameter reference, data-flow section, and 6 Design Patterns (744 lines).
- **docs/how_to_debug.md** (new): Operational runbook — 5-step debug workflow, SQL snippets, log grep patterns, paper vs live differences, common failure scenarios (616 lines).
- **commit SKILL.md expanded**: Step 4 now includes per-file update guidance for all 6 docs with complexity guide. Step 8 stage list updated to include all 6 docs.
- **business-requirement.md deleted**: Stale root-level file removed; `docs/business_requirements.md` is now the single source of truth.
- **CLAUDE.md**: Model `<think>` block note generalised to cover any reasoning model (not just deepseek-r1).
- **plan.md**: Architecture diagram LLM label updated to `(tool-capable)`.

## Session: 2026-04-06 (Part B) — GitHub Sub-Issues API Fix

### Bug Fixed
- **`create_story()` sub-issue linking**: Fixed broken `gh api` call in `scripts/create_github_issues.sh` — added required `Accept: application/vnd.github+json` and `X-GitHub-Api-Version: 2026-03-10` headers; changed `--field` to `-F` for the POST body parameter.

### Scripts Added
- **`scripts/link_epics.sh`**: Retroactive sub-issue linker — discovers existing Epic and Story issues by label and links each Story as a GitHub Sub-Issue of its parent Epic. Idempotent (safe to re-run).
