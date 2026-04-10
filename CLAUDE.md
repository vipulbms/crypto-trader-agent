# Kryptos — AI Crypto Trading Agent

<!-- Shared context — applies to all contributors and Claude sessions -->
@.claude/memory/project_kryptos.md
@.claude/memory/feedback_coding_style.md
@.claude/memory/feedback_testing.md
@.claude/memory/feedback_github_traceability.md

## Project Overview

Kryptos is an automated crypto trading agent that uses a local LLM (Ollama) to make trading decisions on Kraken exchange. It operates in paper mode (virtual money) or live mode (real money).

**Entry points:**
- `python main.py --paper` — background trading loop
- `python kryptos.py` — interactive CLI

---

## Architecture

```
main.py                    — trading loop runner
kryptos.py                 — interactive CLI entry point
config.yaml                — all tunable parameters
src/
  agent/
    trading_agent.py       — LLM call loop, retry, fallback model
    tools.py               — propose_buy / propose_sell / hold tools
    prompts.py             — SYSTEM_PROMPT + build_cycle_prompt()
  analysis/
    indicators.py          — RSI, MACD, ATR, Bollinger Bands
    signals.py             — BUY/SELL/HOLD signal generation
    features.py            — regime, sentiment, patterns, exit_timing, sizing, dynamic_tp
  exchange/
    paper_broker.py        — virtual order execution, SL/TP monitoring
    kraken_client.py       — live Kraken REST API client
    websocket_feed.py      — Kraken WS v2 price feed + candle buffer
  risk/
    risk_manager.py        — position sizing, config validation, TP/SL config
  storage/
    database.py            — SQLite connection helper (audit.db, paper_trading.db)
    audit_logger.py        — full audit trail: cycles, signals, trades, balance snapshots
  notifications/
    notifier.py            — Telegram alerts for trades, errors, daily summary
  cli/
    commands.py            — CLI command handlers
    display.py             — rich terminal display
    nl_parser.py           — natural language CLI input parser
  reports/
    trade_report.py        — P&L and trade history reports
    daily_report.py        — Full daily P&L report (run_daily_report)
    review_report.py       — N-day performance review with verdict (run_review)
  utils/
    tz.py                  — Singapore timezone helpers
    timing.py              — @timed decorator, cycle_id propagation
```

---

## Key Design Decisions

### Stop-loss / Take-profit
- SL is always 5% below entry (non-negotiable, enforced by broker)
- TP is configurable per pair (5 / 8 / 12 / 16 / 20%)
- `check_stops_and_tp()` runs on every loop iteration **before** the LLM cycle — highest priority
- SL/TP are price-tick based in paper mode (no order book); they fire when `current_price` crosses the stored level

### LLM Decision Cycle
- Single LLM call per cycle covering all pairs (ranked multi-pair prompt)
- Agent may call `propose_buy` for top-3 signals only; `propose_sell` only with strong conditions
- **Early sell guardrails (critical):** agent cannot call `propose_sell` unless P&L > +2%; for early TP capture, position must be at ≥60% of TP target with confirmed reversal
- Fallback model configured in `config.yaml → llm.fallback_model` if primary times out

### Paper Broker
- `place_order()`: applies entry slippage (0.05%, now symmetric with exit #140), deducts `actual_cost + fee_usd` from cash
- `usd_value` stored in `paper_positions` = `actual_cost` (entry cost, fee excluded)
- `close_position()`: applies exit slippage (0.05%) + exit fee (0.26% hardcoded in method)
- `get_balance()`: `total_usd = cash + Σ(usd_value of open positions)`

### Audit Trail
- Every cycle, signal, trade, balance snapshot, and error is written to `audit.db`
- Balance snapshots are taken **after** trades execute (post-trade re-fetch)

---

## Pairs and Take-Profit Targets

| Pair | TP% | Notes |
|---|---|---|
| BTC/USD | 8% | Slow mover |
| ETH/USD | 12% | |
| BNB/USD | 12% | |
| SOL/USD | 16% | Volatile |
| XRP/USD | 12% | News-driven |
| TRX/USD | 12% | |
| DOGE/USD | 20% | Meme coin |
| ADA/USD | 12% | |
| LTC/USD | 8% | |
| ~~RAILS/USD~~ | ~~20%~~ | **Disabled** — 25% win rate, 3/4 stop losses (#132) |
| AVAX/USD | 12% | |
| SUI/USD | 16% | |
| HYPE/USD | 20% | |
| UNI/USD | 12% | |
| INJ/USD | 16% | |
| WIF/USD | 20% | Solana meme; buy_min_score=6; caution=0.40 (#145) |
| TON/USD | 16% | Telegram blockchain; clean RSI cycles (#146) |
| OP/USD | 16% | Optimism L2; buy_min_score=6 (#147) |
| ARB/USD | 16% | Arbitrum L2; largest ETH L2 by TVL (#148) |
| JUP/USD | 20% | Jupiter DEX (Solana); buy_min_score=7; caution=0.35 (#149) |
| PEPE/USD | 20% | Extreme meme; buy_min_score=8; caution=0.25 (#150) |
| TIA/USD | 20% | Celestia modular; buy_min_score=7; caution=0.35 (#151) |
| RENDER/USD | 16% | AI GPU compute; caution=0.50 (#152) |
| FET/USD | 16% | ASI Alliance AI; caution=0.45 (#153) |
| STX/USD | 16% | Bitcoin L2 (Stacks); caution=0.50 (#154) |

All pairs use 5% stop-loss.

---

## Risk Rules (enforced)
- Max position size: 30% of portfolio per trade
- Max open positions: 3 simultaneously
- Min cash reserve: 10% of portfolio
- Daily loss limit: 10% — halts all trading for the day

---

## Environment Variables

```
KRAKEN_API_KEY        # Live mode only
KRAKEN_API_SECRET     # Live mode only
TELEGRAM_BOT_TOKEN    # Optional — notifications
TELEGRAM_CHAT_ID      # Optional — notifications
```

---

## Common Commands

```bash
# Run paper trading
python main.py --paper

# Interactive CLI
python kryptos.py

# View recent trades
python kryptos.py report

# Check balance
python kryptos.py balance
```

---

## Session Notes

Development history is documented in `docs/sessions/`. Each file covers one session's changes:

| File | Summary |
|---|---|
| session_2026_03_30b–d | Early architecture, WebSocket feed, paper broker |
| session_2026_03_31a | LLM INFO logging; TP tuning |
| session_2026_03_31b | Multi-pair ranked prompt; signal confluence |
| session_2026_03_31c | Position sizing; regime detection |
| session_2026_03_31d | Dynamic TP; sentiment; pattern analysis |
| session_2026_03_31e | Exit timing; post-trade analysis |
| session_2026_03_31f | Timeout handling across LLM/DB/WebSocket |
| session_2026_03_31g | Telegram notification: add invested USD amount |
| session_2026_03_31h | Balance mismatch fix (fee visibility, stale snapshot); SL priority; early-sell guardrails |
| session_2026_04_01a | caution_factor code-enforced; dynamic TP wired to place_order(); 18 tests added; commit skill extended |
| session_2026_04_01b | LLM switched to deepseek-r1:7b; KrakenClient full live broker parity rewrite |
| session_2026_04_01c | Backtesting pipeline added; 5 bugs identified; 7.5-day backtest run and reported |
| session_2026_04_04a | Volatility-Adaptive Quant Migration; OBI implementation; Limit orders |
| session_2026_04_05a | Minimum Profit Floor implementation; extracted trading rules to SKILL.md |
| session_2026_04_05b | Multi-indicator confluence scoring; circuit breaker (DB-backed); heartbeat |
| session_2026_04_05c | Live API Limit orders / fallbacks; 2-hour heartbeat, 6-hour PnL report |
| session_2026_04_05d | Post-only limit chase orders, volume/time-of-day filters, healthcheck webhook |
| session_2026_04_05e | Global kill switch (-7% daily drawdown); backtest clean-slate teardown; audit_rejections.py |
| session_2026_04_05f | Documentation: BRD, detailed solution design (10 sections, 9 Mermaid diagrams, 7 ADRs), epics/stories/AC; removed stale scripts |
| session_2026_04_05g | Documentation: README rewrite; BRD v2.0 formal rewrite; new docs/codebase.md (developer reference); new docs/how_to_debug.md; commit SKILL.md expanded to 6 docs; model references generalised |
| session_2026_04_06a | Backtest analysis (3,931 cycles): root-caused early-sell bug + 5 SL/TP improvements; GitHub issues shell script (E1–E12, 28 stories, sub-issues API) |
| session_2026_04_06b | Fix GitHub Sub-Issues API headers in `create_story()`; create `link_epics.sh` retroactive linker |
| session_2026_04_06c | Fix: ATR floor decoupled (atr_tp_min_pct=0.3); rsi_overbought raised 60→65; validate_sell 80% TP proximity guard; 5 new tests; closes #83 |
| session_2026_04_06d | S12.3.1: Breakeven stop tests (3 tests); closes #85 |
| session_2026_04_06e | S12.5.1: Partial take-profit (paper + live broker, 5 tests, closes #87); all 51 tests pass |
| session_2026_04_07a | Fix: trading hours window corrected to 06:00–04:00 SGT (22:00–20:00 UTC cross-midnight) |
| session_2026_04_07b | Chore: migrate Claude memory files to project scope (.claude/memory/); closes #91 |
| session_2026_04_07c | Fix: HistoricalFeed timestamp-based price lookup — shorter pairs (BNB/AVAX/UNI) were stuck at last candle price forever |
| session_2026_04_08a | Integrate daily_report + review_report into src/reports/ and kryptos CLI (daily/review subcommands) |
| session_2026_04_08b | Fix backtest timestamps (#98), add full chart legend (#99), charts integral to reports (#100); 80 tests passing |
| session_2026_04_08c | Fix trailing stop thresholds (#102), ATR floor 0.3→1.0% (#103), BB squeeze TP (#104), dynamic TP pair min (#95), trading hours 03:00–04:00 SGT (#105) |
| session_2026_04_09a | Per-pair atr_tp_min_pct/RSI/BB squeeze/volume ratio; backtest hours fix (#106); 20 new tests; analysis scripts; 12 GitHub issues #107–#118 created |
| session_2026_04_09b | Adaptive ATR floor (#108), adaptive BB/volume injection (#113,#114), MACD decay normalised (#112), candle timestamps (#115), 90% capital deployment (#116), signal driver report (#117), calibrate_params.py (#118) |
| session_2026_04_09c | Chore: disable time-of-day trading hours guard (#121); volume floor remains always-on |
| session_2026_04_09d | Fix: backtest clean-slate teardown — get_db_path(), pre-run validation (#122) |
| session_2026_04_09e | Fix: trailing stop exits mislabelled as stop_loss — trailing_stop label + circuit breaker exclusion (#123) |
| session_2026_04_09f | Feat: per-pair caution_factor_bearish (#124), per-pair buy_min_score (#128), aggressive position sizing 20%/5% reserve (#130) |
| session_2026_04_09g | Fix: trailing_stop in display/reporting (#125); min_order_usd raised to $20 + Guard 0.5 (#126); force_close_all at backtest end (#127); overdraw guard in place_order() (#129) |
| session_2026_04_10a | Fix: RAILS buy_min_score=7, caution_factor_bearish 0.40→0.25; unambiguous propose_sell gate (all three conditions required, not disjunctive); SKILL.md frontmatter fix (#131) |
| session_2026_04_10b | Chore: disable RAILS/USD (25% win rate, 3/4 stops); reset paper trading to clean $1,000 slate (#132) |
| session_2026_04_10c | Fix: total value in balance report used stale audit snapshot — now computed live for paper mode (#133) |
| session_2026_04_10d | Fix: early-sell TP proximity guard reduced from 80% to 60% — avoids asymmetric trap; configurable via `early_sell_min_tp_proximity_pct` (#138) |
| session_2026_04_11a | Feat: ADX trend strength filter (#134); RSI divergence detection (#135); fast backtest `--no-llm` flag (signal-only, seconds vs 2h) |
| session_2026_04_11b | Feat: OBV accumulation signal +1 BUY (#136); BB squeeze release +2 BUY (#137); per-pair obv_trend_period; max_score 22→25; 96 tests |
| session_2026_04_11c | Fix: Shorten adaptive lookback 400→200 (#141); enable partial TP (#142); correlation cluster guard (#139); graduated circuit breaker 1h/2h/4h (#143); 169 tests |
| session_2026_04_11d | Fix: Entry slippage added to place_order() (#140); prompt "TOP 3" → dynamic max_buys_per_cycle (#144); 172 tests |
| session_2026_04_11e | Fix: max_open_positions 13→5, compute_position_size floor at min_order_usd, config sanity warning, prompt min_order guard (#159); 180 tests |
| session_2026_04_11f | Feat: add 10 new trading pairs WIF/TON/OP/ARB/JUP/PEPE/TIA/RENDER/FET/STX (#145–#154); backtest 55% win; WIF+OP buy_min_score→7, TIA→8; 174 tests |
| session_2026_04_11g | Chore: add-pair skill updated — step 5(i) trailing_stop tier table, step 5(j) correlation_clusters review; closes #162 |
| session_2026_04_11h | Chore: add scripts/reset_paper.py — reset paper_trading.db + audit.db paper rows to clean $1,000 slate; closes #163 |
| session_2026_04_11i | Fix: position gate uses remaining cash — max_open_positions count cap now only fires when count≥max AND deployable<min_order_usd; max_per_trade uses cash_usd not total_usd (#165) |

---

## Known Behaviours / Gotchas

- **Realized P&L at TP is slightly below configured %**: full round-trip friction = entry slippage (0.05%) + entry fee (0.26%) + exit slippage (0.05%) + exit fee (0.26%) ≈ 0.62% per trade. This is intentional simulation of real Kraken maker-fee trading costs (#140).
- **`usd_value` ≠ cash deducted**: `usd_value` in DB = entry cost only; actual cash deducted = entry cost + entry fee. The fee is shown in Telegram notifications but not in `paper_positions.usd_value`.
- **`agent_sell` vs `take_profit`**: `exit_reason` in DB distinguishes LLM-initiated sells from automatic TP hits. If you see small-gain exits, check if `exit_reason = agent_sell` — means the LLM sold early.
- **Cycle interval**: 30 minutes. SL/TP checks happen every cycle start, not on every price tick. Price can blow past SL between cycles without firing.
- **caution_factor is now per-pair (#124)**: In bearish regime, `main.py` injects `sig["pair_max_usd"]` per signal using `pair_cfg.get("caution_factor_bearish", global_caution)`. Winners (ETH/BNB/DOGE) = 1.0 (buy the dip, full size). Underperformers (INJ/SUI) = 0.35. RAILS = 0.25 (#131, was 0.40 — 3/4 stop losses in production). HYPE = 0.40. Global fallback (`bearish_caution_factor: 0.5`) applies for pairs without an explicit override. The LLM sees per-pair "Max buy size" in the prompt. Volatile regime still applies global caution uniformly.
- **Dynamic TP is now order-level**: `TradingTools.propose_buy()` uses ATR/BB-adjusted TP from `ai_context["dynamic_tp_values"]` instead of static config. Falls back to static if `dynamic_tp.enabled: false` or pair not in values. Logged as `[DYNAMIC_TP]`.
- **Reasoning model `<think>` blocks**: some models (e.g. DeepSeek-R1, QwQ) emit chain-of-thought `<think>…</think>` before their response. Ollama strips these before populating `msg.tool_calls`, so tool dispatch is unaffected. If you see verbose `content` in debug logs, that's the reasoning block.
- **Live broker parity**: `KrakenClient` now has the same interface as `PaperBroker` — `get_balance()`, `get_open_positions()`, `close_position()`, `check_stops_and_tp()` all implemented. Positions are tracked in `live_trading.db` (same SQLite pattern as paper mode).
- **Minimum Profit Floor**: The agent is blocked by `validate_sell` from closing a trade manually if the PNL is below `min_profit_floor_pct` (1.0%), guarding against net losses from Kraken exit fees.
- **Signal scoring is confluence-based**: No single indicator triggers a BUY. Score must reach `buy_min_score` (5) from up to 10 contributors. The two hard vetoes are RSI ≥ 70 and ATR-based TP < profit floor. See `signals.py` for full weight table.
- **MACD histogram turn vs positive**: `indicators.py` returns both `macd_histogram` (current) and `macd_histogram_prev` (previous candle). A turn from negative to positive scores +3; merely being positive scores +1.
- **Fear & Greed injected into signals**: `main.py` fetches Fear & Greed once per cycle and injects it as `fear_greed_index` into each pair's indicators dict before `generate_signal()` runs. Scores +1 (fear ≤ 40) or +2 (extreme fear ≤ 25).
- **Circuit breaker reads trade history**: `RiskManager.is_circuit_open()` uses a graduated backoff (#143): fires are counted in `tier_reset_hours` (24h) via `_count_circuit_fires_in_window()`. Pause = `pause_tiers_hours[fires-1]` clamped to max tier (1h → 2h → 4h). No new DB tables — derived from trade history. Backward compat: if `pause_hours` present without `pause_tiers_hours`, uses flat override.
- **Heartbeat (live mode only)**: Every 60 minutes, `notifier.send_heartbeat()` sends a Telegram summary: balance, hourly P&L, cycles, buys/sells, circuit breaker state. Skipped in backtest mode.
- **Volatility Windows & Dead Zones**: Time-of-day guard is **disabled** (`allowed_trading_hours.enabled: false`) — agent trades at any hour. Volume dead zone check in `signals.py` is always active regardless of `enabled` flag. **`min_volume_ratio` is per-pair**: BNB/UNI/INJ=0.30, TRX/DOGE/ADA/LTC/AVAX=0.40, BTC/ETH/SOL/XRP/SUI=0.50. `end_hour_utc` is exclusive (retained in config for easy re-enable). Backtest also bypasses time guard since `enabled=False`.
- **Per-pair signal thresholds**: As of session_2026_04_09a, `atr_tp_min_pct`, `rsi_oversold`, `rsi_overbought`, `bb_squeeze_threshold_pct`, `min_volume_ratio`, and `adaptive_atr_floor_lookback` are all configurable per pair in `trading.pairs[]`. Global values in `dynamic_tp` and `indicators` sections are fallbacks only. Per-pair values derived from 2025-01-01 rolling-window analysis.
- **ATR floor priority chain**: `indicators["adaptive_atr_floor_pct"]` (injected by main.py, rolling p25 ATR% × 0.8) → `pair_cfg["atr_tp_min_pct"]` → `dynamic_tp.atr_tp_min_pct` (0.30% fallback) → `trading.min_profit_floor_pct`. Adaptive injection enabled by `adaptive_atr_floor.enabled: true`; lookback=**200** candles global (was 400, #141), overrideable per-pair via `adaptive_atr_floor_lookback`.
- **MACD decay threshold is now % of price**: `exit_timing.macd_decay_threshold_pct: -0.005` replaces old absolute `-0.0005`. `check_exit_timing()` computes `macd_hist / price × 100` before comparing. This makes the threshold price-scale agnostic (works for both TRX and BTC).
- **Adaptive BB squeeze and volume floor**: `main.py` also injects `_rolling_bb_p10_pct` (p10 BB width per pair, 400-candle lookback) and `rolling_volume_p15` (p15 raw volume, 400-candle lookback) each cycle. `features.py compute_dynamic_tp()` uses `_rolling_bb_p10_pct` first; `signals.py Hard Blocker 3` uses `rolling_volume_p15` first.
- **Position sizing updated (Fix #130, revised #159, #165)**: `max_open_positions: 5` (was 13 — 13×16%=208% was impossible; floor(95/16)=5), `max_position_pct: 20%` (was 15%), `max_buys_per_cycle: 7` (was 5), `base_position_pct: 16%` (was 12%), `min_cash_reserve_pct: 5%` (was 10%). `max_per_trade` is now computed as `cash_usd × max_position_pct` (was `total_usd × ...`) so the LLM sees the ceiling proportional to remaining cash. The `max_open_positions` count cap only fires when count≥max **and** deployable cash < `min_order_usd` (#165); when cash is available the count gate is bypassed, letting cash reserve guards be the real limiter.
- **Per-pair buy_min_score (#128, updated #131)**: `signals.py` reads `pair_cfg.get("buy_min_score", global_min_score)`. INJ=7, RAILS=7 (3/4 stop-loss rate in production — #131), SOL/UNI=6 (underperformers per 2026-04-09 backtest). ETH/BNB/DOGE=5 (explicit). Global default = 5.
- **Signal driver report**: `python kryptos.py drivers [--days 30] [--top 10]` shows top blocking reasons per pair and globally. Backed by `get_signal_driver_report()` in `trade_report.py` and `print_signal_driver_report()` in `display.py`.
- **Parameter calibration utility**: `scripts/calibrate_params.py --start-date 2025-01-01 --output rec.yaml` analyses historical candles and outputs recommended config YAML changes for all 5 per-pair signal parameters.
- **`trailing_stop` exit reason (#125)**: Exit Reasons panel in `kryptos.py report` now shows both count and total P&L per exit reason (green/red). `trailing_stop` is a distinct reason from `stop_loss` — these are profitable exits where the trailing SL had been raised above entry and then hit. `backtest_end` is used for positions force-closed at the final candle (mark-to-market).
- **Minimum order floor is $20 (#126)**: `risk.min_order_usd` raised from $5 to $20. Guard 0.5 in `validate_buy()` fires first (before Guard 1) when deployable cash < `min_order_usd`, logging `[RISK] Skipping BUY {pair} — deployable cash $X below min_order_usd $Y`. Hardcoded `capped < 5.0` replaced by `capped < self._min_order_usd`.
- **Backtest mark-to-market close (#127)**: After `asyncio.run(run_agent(...))`, `tests/test_backtest.py` calls `PaperBroker.force_close_all(last_prices)` to close all remaining open positions with `exit_reason='backtest_end'` at the last candle price. The summary prints forced-close count and total P&L.
- **Overdraw guard (#129)**: `PaperBroker.place_order()` now raises `ValueError("Insufficient funds: need $X, have $Y")` if `new_cash < 0` after deducting `actual_cost + fee_usd`. Logged at ERROR level with `[PAPER] OVERDRAW BLOCKED`. This is independent of `validate_buy()`'s pre-check and closes the TOCTOU gap.
- **Partial Take-Profit**: Enabled (#142). Fires once per position (guarded by `partial_exited` DB column). Closes `close_fraction` (50%) of volume at `trigger_pct_of_tp`% (50%) of the way to full TP. Remaining half continues with original SL/TP. If `move_sl_to_breakeven: true`, SL is moved to entry after partial close. `close_position(volume_override=...)` handles partial math; P&L is proportional to the fraction closed.
- **Stop-Loss execution order** in `check_stops_and_tp()`: (1) update highest_price_seen, (2a) trailing SL raise OR (2b) breakeven SL OR none, (3) partial TP check, (4) full SL/TP check. Trailing and breakeven are mutually exclusive (ConfigError if both enabled).
- **`trailing_stop` vs `stop_loss` exit labels**: When trailing stop is enabled and `stop_loss_price` has been raised above the original hard floor (`entry_price × (1 - sl_pct/100)`), a SL hit is labelled `trailing_stop` not `stop_loss`. Hard floor hits remain `stop_loss`. Circuit breaker only counts `stop_loss` and `fallback_stop_loss` — `trailing_stop` exits (which are often profitable) do not contribute to the consecutive-stop streak.
- **ADX trend filter (#134)**: `compute_indicators()` now returns `adx_14` (ADX period 14 via `ta.trend.ADXIndicator`). `signals.py` applies a soft ±1 BUY score modifier: ADX > 40 → +1 (strong trend); ADX < 20 → −1 (ranging, choppy). Not a hard veto — strong confluence can still fire BUY in a ranging market. `max_score` updated from 16 to 22 to account for all new signals.
- **RSI divergence (#135)**: `compute_indicators()` returns `rsi_series` and `close_series` (last 30 candles as lists). `detect_rsi_divergence(prices, rsi, lookback)` in `indicators.py` uses a split-half swing detection approach. `signals.py` scores: bullish_regular +2 BUY, hidden_bullish +1 BUY, bearish_regular +2 SELL. Per-pair `rsi_divergence_lookback` override: BTC/LTC=25 (slow movers), TRX/DOGE/HYPE=15 (fast/noisy), global default=20.
- **Fast backtest `--no-llm`**: `tests/test_backtest.py --no-llm` replaces the LLM with a deterministic rule engine (Signal=BUY → place_order, Signal=SELL → close_position). Runs in ~30 seconds vs ~2 hours. Use for signal parameter calibration. Full pipeline with LLM is still available without the flag. `tests/test_backtest_fast.py` is the underlying implementation.
- **OBV trend signal (#136)**: `indicators.py` returns `obv_series` (last 30 values). `signals.py` calls `_compute_obv_trend(obv_series, period)` — compares OBV[now] vs OBV[now-period] with 0.1% noise floor. OBV rising → +1 BUY. OBV falling → distribution warning in reasons (no penalty). Per-pair `obv_trend_period` override in `trading.pairs[]`; global default `indicators.obv_trend_period: 10`. Estimation: BTC/LTC=14, mid-tier=10, meme=7.
- **BB squeeze release (#137)**: `indicators.py` returns `bb_width_series` (last 10 values, % of price). `detect_bb_squeeze_release()` in `indicators.py` checks: (1) prior `lookback` candles in squeeze (width < per-pair `bb_squeeze_threshold_pct`), (2) current width > threshold × `bb_squeeze_release_expansion_factor` (1.2), (3) price > `bb_mid` (upward only). Awards +2 BUY. Downward breakouts explicitly rejected. Config: `bb_squeeze_release_weight: 2`, `bb_squeeze_release_lookback: 3`, `bb_squeeze_release_expansion_factor: 1.2`. `max_score` is now 25.
