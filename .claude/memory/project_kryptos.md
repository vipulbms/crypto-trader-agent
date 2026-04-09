---
name: Kryptos project context
description: Core architecture, known bugs, decisions, and conventions for the Kryptos crypto trading agent
type: project
---

Autonomous paper/live crypto trading agent on Kraken. Local LLM (deepseek-r1:7b via Ollama). 15 pairs. Python 3.11. SQLite. SGT timezone throughout.

**Why:** Product owner is new to crypto; agent must be conservative and capital-first.

**How to apply:** Use this context when making any code or config changes to understand the full system.

## Key files
- `main.py` — async agent runner, decision cycle loop
- `src/agent/trading_agent.py` — LLM orchestration per pair
- `src/exchange/paper_broker.py` — paper trading simulation
- `src/exchange/kraken_client.py` — live trading via ccxt
- `src/exchange/websocket_feed.py` — Kraken WS + REST backfill
- `src/reports/trade_report.py` — all report queries
- `src/cli/display.py` — Rich terminal output
- `config.yaml` — ALL parameters (no hardcoded values in source)
- `data/audit.db` — every decision audit trail
- `data/paper_trading.db` — paper positions, trades, wallet

## 15 trading pairs
BTC/USD (8%), ETH/USD (12%), BNB/USD (12%), SOL/USD (16%), XRP/USD (12%), TRX/USD (12%), DOGE/USD (20%), ADA/USD (12%), LTC/USD (8%), RAILS/USD (20%), AVAX/USD (12%), SUI/USD (20%), HYPE/USD (20%), UNI/USD (12%), INJ/USD (20%). Stop-loss fixed at 5% for all.

## LLM config (current)
- model: `deepseek-r1:7b` (fallback: same)
- timeout: 600 s
- deepseek-r1 emits `<think>` blocks; Ollama strips before `msg.tool_calls` — no impact on tool dispatch
- LLM references in code/docs are model-agnostic ("any tool-capable model"); do not hardcode deepseek-r1 anywhere.

## Live broker (KrakenClient)
Fully implemented to mirror PaperBroker interface: `get_balance()` uses DB entry cost + Kraken cash; positions tracked in `live_trading.db`; `close_position()` and `check_stops_and_tp()` both implemented. SL/TP check runs for both paper and live in `main.py`.

## Critical conventions
- `decision_type` values are `BUY`/`SELL`/`HOLD` (not `TRADE_BUY`)
- Tool execution always uses the signal `pair`, never `tool_args["pair"]` (LLM hallucinates pair names)
- `set_cycle_id()` must be called in `main.py` immediately after `audit.log_cycle()` — before signals are computed
- `PaperBroker.get_balance()` returns `total_usd` = cash + open position entry cost (not cash-only) — this fix has regressed twice; always verify it after any paper_broker.py edit
- `get_daily_pnl()` uses `total_usd` so buying doesn't count as a loss
- `paper_broker.py` requires `from datetime import datetime` — used in `close_position()`
- Always close DB connections AFTER all queries — never before
- `prompts.py` system prompt must stay aligned with signal scorer weights — never hardcode RSI thresholds as mandatory BUY conditions
- `prompts.py` must use an explicit decision tree (Signal=BUY → propose_buy) with an exhaustive list of override conditions — never vague "when in doubt, hold" language; the LLM will use any ambiguity to HOLD
- BB config: `bb_min_width_pct=0.5`, `bb_buy_tolerance_pct=0.5`, `bb_sell_tolerance_pct=0.5`
- BB squeeze fix is in `signals.py` logic, NOT in the config threshold — `near_lower` and `near_upper_for_sell` are mutually exclusive; if both fire simultaneously, neither is awarded. Do NOT raise `bb_min_width_pct` above 0.5% — it suppresses too many valid signals.

## GitHub
`vipulbms/crypto-trader-agent` — branch `main`

## Skills
- `/add-pair SYMBOL/USD tp_pct` — onboards new pair across all 7 files
- `/commit [optional message]` — safe commit + push, never stages .env/data/logs

## Signal scoring
- BUY is confluence-based: min score 5 from 10 contributors. No single hard gate except RSI ≥ 70 veto and ATR profit floor veto.
- `macd_histogram_prev` returned by `indicators.py` — turn from negative to positive = +3, staying positive = +1.
- Fear & Greed fetched once per cycle in `main.py`, injected as `fear_greed_index` into indicators dict before `generate_signal()`.
- Score weights all in `config.yaml` under `signals:`. Never hardcode them.

## Circuit breaker
- `RiskManager.is_circuit_open()` queries `paper_trades`/`live_trades` with `WHERE closed_at >= <now - pause_hours>`. If last N rows are all `stop_loss` → blocked.
- No extra DB table. Survives restarts. Config: `risk.circuit_breaker.consecutive_stops` and `pause_hours`.
- `RiskManager` requires `db_path` param — injected in `main.py`.
- Tests in `tests/test_circuit_breaker.py` — run after any `risk_manager.py` changes.

## Heartbeat
- `notifier.send_heartbeat()` called every `notifications.heartbeat_interval_minutes` (60) in live mode. Skipped in backtest.

## Minimum Profit Floor & Quant Constraints
- `min_profit_floor_pct = 1.0` enforced in `validate_sell` (risk_manager) as the sell floor.
- ATR signal gate in `signals.py` uses `dynamic_tp.atr_tp_min_pct: 0.3` (NOT `min_profit_floor_pct`) — decoupled to allow large-cap pairs (BTC ATR% ~0.625%) to pass.
- `validate_sell()` code-enforces the 80% TP proximity guard (BRD FR-20): LLM cannot exit until P&L ≥ 80% of the position's `take_profit_pct`. Automatic SL/TP exits bypass this.
- LLM trading rules in `.claude/skills/trading-rules/SKILL.md` — keep SKILL.md in sync whenever signal logic or risk rules change.

## Trading Hours
- Time-of-day guard is **disabled** (`allowed_trading_hours.enabled: false`). Agent trades at any hour.
- `config.yaml`: `start_hour_utc: 19`, `end_hour_utc: 20` (retained for easy re-enable, but inactive).
- `end_hour_utc` is EXCLUSIVE when enabled.
- Volume dead zone check (`min_volume_ratio`) in `signals.py` is always active regardless of `enabled` flag.

## Trailing Stop (updated 2026-04-08)
- Global: `trail_pct: 5.0%`, `activate_after_pct: 3.0%` (was 3%/1.5%).
- `per_pair_overrides` now uses dict format `{trail_pct, activate_after_pct}`:
  DOGE/RAILS/HYPE: 7%/5.0%, SUI: 6%/4.0%.
- `paper_broker.py` and `kraken_client.py` read dict overrides (backward-compatible with scalar floats).

## ATR/BB Signal Gates (updated 2026-04-09b)
- `dynamic_tp.atr_tp_min_pct: 0.30` (global fallback only). Per-pair `atr_tp_min_pct` in config overrides this (BTC=0.14, TRX=0.12, INJ=0.34, etc.).
- ATR floor priority chain in `signals.py` Hard Blocker 2: `indicators["adaptive_atr_floor_pct"]` (injected, adaptive) → `pair_cfg["atr_tp_min_pct"]` (per-pair static) → `dynamic_tp.atr_tp_min_pct` (global) → `min_profit_floor_pct`.
- `compute_dynamic_tp()` BB squeeze guard: threshold is per-pair `bb_squeeze_threshold_pct` → global `squeeze_threshold_pct` (1.0%). When BB width < threshold, TP clamps to pair floor.
- BB squeeze thresholds: BTC=0.7%, ETH=1.3%, BNB=0.9%, SOL=1.8%, XRP=1.4%, TRX=0.8%, DOGE=1.8%, ADA=1.9%, LTC=1.5%, AVAX=2.0%, SUI=2.1%, UNI=2.1%, INJ=2.5%.
- `compute_dynamic_tp()` pair floor: `min_tp = max(global_min_tp, pair_static_tp)` — dynamic TP never goes below pair's configured target.

## Per-pair signal thresholds (added 2026-04-09a)
- **RSI**: `rsi_oversold` and `rsi_overbought` per pair in config. `signals.py` reads `pair_cfg` first, then global fallback. TRX oversold=35 (noisy), BNB/XRP/LTC=28 (rare), TRX overbought=65, INJ/XRP/DOGE/ADA/LTC/SUI=72, others=75.
- **Volume**: `min_volume_ratio` per pair. BNB/UNI/INJ=0.30 (dead zone fix), TRX/DOGE/ADA/LTC/AVAX=0.40, BTC/ETH/SOL/XRP/SUI=0.50. Hard Blocker 3 in `signals.py` also supports `rolling_volume_p15` injection (adaptive).
- **Adaptive ATR floor lookback**: All 13 current pairs use 400-candle lookback (CV analysis: 400 gives lowest CV=0.28–0.47 vs 0.46–0.87 at 50 candles). Per-pair `adaptive_atr_floor_lookback` field exists for future RAILS/HYPE override.
- `tests/test_per_pair_params.py` — 20 tests covering all per-pair threshold behaviours. Run after any `signals.py` or `features.py` edit.

## Adaptive injections (added 2026-04-09b)
Each cycle, `main.py run_cycle()` injects 3 adaptive values into indicators before `generate_signal()`:
1. `adaptive_atr_floor_pct` — rolling p25 ATR% × scaling_factor (0.8), min_cap 0.10%. Config: `adaptive_atr_floor.{enabled, scaling_factor, min_cap_pct, lookback_candles}`.
2. `_rolling_bb_p10_pct` — rolling p10 BB width%. Config: `adaptive_bb_squeeze.{enabled, lookback_candles, percentile}`.
3. `rolling_volume_p15` — rolling p15 raw volume. Config: `adaptive_volume_floor.{enabled, lookback_candles, percentile}`.
All three use 400-candle lookback globally; per-pair ATR lookback overrideable via `adaptive_atr_floor_lookback`.

## MACD decay (updated 2026-04-09b)
- `exit_timing.macd_decay_threshold_pct: -0.005` replaces old absolute `-0.0005`.
- `check_exit_timing()` computes `macd_hist / price × 100` before comparing. Price-scale agnostic.

## Position sizing (updated 2026-04-09c — Fix #130)
- `max_open_positions: 13`, `max_position_pct: 20%` (was 15%), `max_buys_per_cycle: 7` (was 5).
- `position_sizing.base_position_pct: 16%` (was 12%), `position_sizing.max_position_pct: 20%` (was 15%).
- `min_cash_reserve_pct: 5%` (was 10%) — agent can deploy up to 95% capital.

## Per-pair caution_factor_bearish (added 2026-04-09c — Fix #124)
- In bearish regime, `main.py` injects `sig["pair_max_usd"]` per signal using `pair_cfg.get("caution_factor_bearish", global_caution)`.
- Winners (ETH/BNB/DOGE) = 1.0 (buy the dip, full size). Underperformers (INJ/SUI) = 0.35. RAILS/HYPE = 0.40.
- Global fallback `bearish_caution_factor: 0.5` applies for pairs without a per-pair override.
- `pair_max_usd` is shown per-pair in the LLM prompt ("Max buy size: $X"). Volatile regime still uses global caution uniformly.

## Per-pair buy_min_score (added 2026-04-09c — Fix #128)
- `signals.py` reads `pair_cfg.get("buy_min_score", global_buy_min_score)` before scoring.
- INJ=7, SOL/UNI=6. ETH/BNB/DOGE=5 (global default, explicitly set). All others use global 5.
- Based on 2026-04-09 backtest win rates: INJ 30%, SOL/UNI ~44-50% at score threshold 5.

## Signal driver report (added 2026-04-09b)
- `kryptos.py drivers [--days 30] [--top 10]` — shows top blockers and BUY drivers per pair and globally.
- `trade_report.get_signal_driver_report()` queries `audit_signals.signal_reasons` JSON.
- `display.print_signal_driver_report()` formats as Rich tables.

## Parameter calibration utility (added 2026-04-09b)
- `scripts/calibrate_params.py --start-date 2025-01-01 [--output rec.yaml]`
- Loads candles from SQLite DB or Kraken REST API; computes per-pair recommendations for all 5 signal parameters.
- Outputs YAML diff of recommended vs current config.

## Live Trading Limits & Async
- Limit Orders in live (`KrakenClient`) must resolve to 'closed' before SL/TP orders are attached. `check_stops_and_tp` handles polling.
- System handles a global Max Daily Loss (7.0%) acting as a Kill Switch to cancel and market-sell positions.
- Test execution scripts self-clean backtest_run.log and backtesting sqlite environments automatically.

## GitHub issues
- `scripts/create_github_issues.sh` — run once to create all epics (E1–E12) and 28 stories with full AC, BRD FR-XX, DSD §X.X, and NFR-XX traceability.
- E12 = Stop-Loss Protection & Gain Preservation: S12.1.1 (closed #83), S12.2.1 trailing stop, S12.3.1 breakeven stop, S12.4.1 ATR-based SL, S12.5.1 partial TP.

## Documentation structure
- `docs/codebase.md` — developer reference; regenerate with /explain skill when multiple modules change.
- `docs/how_to_debug.md` — debug runbook; SQL queries, log grep patterns.
- `docs/business_requirements.md` — formal BRD v2.0; surgical edits only, never full rewrite.
- `docs/detailed_solution_design.md` — architecture with Mermaid diagrams + ADRs 1-7.
- `docs/epics_stories_ac.md` — backlog; append new stories or tick completed ones only.
- `docs/business_requirements.md` is the single source of truth (root-level `business-requirement.md` deleted).
