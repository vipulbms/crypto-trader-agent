# Kryptos — Epics, Features, User Stories & Acceptance Criteria

**Product:** Kryptos — Autonomous Quantitative AI Trading Agent  
**Prepared by:** Business Analyst (Reverse Engineered from Codebase)  
**References:** `docs/business_requirements.md`, `docs/detailed_solution_design.md`  
**Date:** 5 April 2026

---

## Epic Index

| Epic ID | Name | Priority | Status |
| :--- | :--- | :--- | :--- |
| E1 | Market Data Ingestion | P0 | Done |
| E2 | Quantitative Signal Engine | P0 | Done |
| E3 | AI Cognitive Orchestrator | P0 | Done |
| E4 | Risk & Compliance Guard | P0 | Done |
| E5 | Trade Execution Engine | P0 | Done |
| E6 | Paper Trading & Simulation | P0 | Done |
| E7 | Audit & Observability | P1 | Done |
| E8 | Telegram Notification Framework | P1 | Done |
| E9 | Natural Language CLI | P1 | Done |
| E10 | Backtesting & Validation | P1 | Done |
| E11 | DevOps & Resilience | P2 | Done |

---

## E1 — Market Data Ingestion

**Goal:** Stream real-time prices, L2 order book, and historical candles from Kraken so the downstream quantitative layer always has a consistent, low-latency view of the market.

**Code:** `src/exchange/websocket_feed.py`, `src/exchange/kraken_client.py`, `src/exchange/historical_feed.py`

---

### Feature F1.1 — WebSocket OHLC Candle Stream

#### Story S1.1.1
**As a** quantitative analyst,  
**I want** the system to maintain a rolling buffer of 15-minute OHLCV candles for all 15 pairs,  
**so that** indicators have a consistent, live data source without polling REST every cycle.

**Acceptance Criteria:**
- [ ] AC1: WebSocket subscribes to `ohlc-15` channel for every pair listed in `config.yaml`.  
- [ ] AC2: On each incoming message, the buffer is updated and `get_candles(pair)` returns a `pd.DataFrame` with columns `[timestamp, open, high, low, close, volume]`.  
- [ ] AC3: If WS disconnects, the system attempts reconnection up to 5 times before raising an alert.  
- [ ] AC4: Historical candles are pre-loaded via `HistoricalFeed` on startup to fill the warm-up period.

**Code Association:** `websocket_feed.py::WsOhlcFeed._handle_message`, `historical_feed.py::HistoricalFeed.load`

---

### Feature F1.2 — L2 Order Book Imbalance (OBI)

#### Story S1.2.1
**As a** risk manager,  
**I want** to compute Order Book Imbalance from the live bid/ask spread,  
**so that** the system only enters trades when genuine buying pressure exists.

**Acceptance Criteria:**
- [ ] AC1: System subscribes to `ticker` channel alongside `ohlc`.  
- [ ] AC2: OBI is computed as `(BidVol - AskVol) / (BidVol + AskVol)` and stored per pair.  
- [ ] AC3: `get_obi(pair)` returns a float in range `[-1.0, +1.0]`.  
- [ ] AC4: A positive OBI (> 0) is a prerequisite for any `propose_buy` execution to proceed.

**Code Association:** `websocket_feed.py::WsOhlcFeed.get_obi`

---

### Feature F1.3 — Historical Feed for Backtesting

#### Story S1.3.1
**As a** developer,  
**I want** to replay historical candle data from JSON files,  
**so that** I can run backtests without a live exchange connection.

**Acceptance Criteria:**
- [ ] AC1: `HistoricalFeed` reads from `history/<PAIR>_candle.json` files in Kraken OHLC format.  
- [ ] AC2: Feed exposes the same `get_candles(pair)` interface as `WsOhlcFeed`.  
- [ ] AC3: OBI defaults to `0.5` (neutral) in backtest mode as real L2 data is unavailable.  
- [ ] AC4: Missing history files raise a clear `FileNotFoundError` with the expected path.

**Code Association:** `exchange/historical_feed.py`, `tests/test_backtest.py`

---

## E2 — Quantitative Signal Engine

**Goal:** Transform raw OHLCV candles into normalized, scored, per-pair signals that the LLM can reason about without ever seeing raw prices or noisy indicator arrays.

**Code:** `src/analysis/indicators.py`, `src/analysis/signals.py`, `src/analysis/features.py`

---

### Feature F2.1 — Trend & Momentum Indicators

#### Story S2.1.1
**As an** AI agent,  
**I want** computed EMA, MACD, and RSI values per pair,  
**so that** I can identify bullish or bearish momentum without interpreting raw prices.

**Acceptance Criteria:**
- [ ] AC1: `compute_indicators()` returns a dictionary containing: `ema_9`, `ema_21`, `ema_50`, `macd_histogram`, `macd_histogram_prev`, `rsi`, `atr`, `volume_sma_20`, `volume_ratio`.  
- [ ] AC2: EMA 9 and EMA 21 crossover produces `ema_cross_bullish: True` flag.  
- [ ] AC3: RSI is calculated over 14 periods. Value is bounded `[0, 100]`.  
- [ ] AC4: ATR is calculated over 14 periods using Wilder smoothing.  
- [ ] AC5: If fewer than 50 candles are available, indicators raise a `InsufficientDataError` and the pair is skipped.

**Code Association:** `indicators.py::compute_indicators`

---

### Feature F2.2 — Confluence Score & Signal Generation

#### Story S2.2.1
**As a** risk manager,  
**I want** each pair evaluated by a weighted confluence score (0–10),  
**so that** only statistically strong setups are presented to the LLM as BUY candidates.

**Acceptance Criteria:**
- [ ] AC1: Score accumulates from documented contributors: MACD turn (+3), RSI oversold (+2), near lower BB (+2), volume confirms (+1), EMA cross bullish (+1), Fear & Greed index (+1/+2).  
- [ ] AC2: A score ≥ `signals.buy_min_score` (default 5) is required to generate a `BUY` direction.  
- [ ] AC3: Two hard vetoes exist: `RSI ≥ 70` and `ATR-based TP < profit_floor`. Either veto forces `HOLD` regardless of score.  
- [ ] AC4: All scoring decisions and veto reasons are returned as a `reasons: list[str]` alongside the signal.  
- [ ] AC5: `generate_signal()` returns `{"direction": "BUY|SELL|HOLD", "score": int, "reasons": list}`.

**Code Association:** `signals.py::generate_signal`

---

### Feature F2.3 — Hard Buy Gates (Trend & Volume)

#### Story S2.3.1
**As a** compliance system,  
**I want** automatic blocking of BUY signals during dead-zone market conditions,  
**so that** the system avoids false breakout entries.

**Acceptance Criteria:**
- [ ] AC1: `Price > EMA 50` is a mandatory condition. If false, `BLOCKED: Price below EMA50` is appended to reasons and direction is forced to `HOLD`.  
- [ ] AC2: `EMA 9 > EMA 21` (micro momentum) is a mandatory condition. Failure produces `BLOCKED: No bullish EMA crossover`.  
- [ ] AC3: Volume ratio < `signals.min_volume_ratio` (default 0.5) forces `BLOCKED: Volume dead zone`.  
- [ ] AC4: All block reasons are visible in `audit_signals` database table.  
- [ ] AC5: These gates apply to backtesting using the historical candle timestamp for time-of-day evaluation.

**Code Association:** `signals.py::generate_signal`, `risk_manager.py::validate_buy`

---

### Feature F2.4 — Volatility-Adaptive Sizing & TP

#### Story S2.4.1
**As a** portfolio manager,  
**I want** position sizes and take-profit levels to dynamically scale with ATR,  
**so that** trades capture more profit during high-volatility regimes and preserve capital during calm markets.

**Acceptance Criteria:**
- [ ] AC1: Volatility regime is classified as Low/Standard/High based on `atr / price` ratio.  
- [ ] AC2: ATR multiplier `k` ranges from `1.75x` (low vol) to `4.0x` (high vol).  
- [ ] AC3: Dynamic TP = `Entry + (k * ATR)`. Static TP from config is the fallback if `dynamic_tp.enabled: false`.  
- [ ] AC4: Dynamic SL = `min(Entry * 0.95, Entry - (ATR * Multiplier))`. Can never exceed 5%.  
- [ ] AC5: Both values are logged per-trade as `dynamic_sl` and `dynamic_tp` in `paper_positions`.

**Code Association:** `features.py::get_volatility_multiplier`, `features.py::compute_dynamic_sl_values`, `agent/tools.py::propose_buy`

---

## E3 — AI Cognitive Orchestrator

**Goal:** Use a local LLM to reason over normalized market data and produce structured trade decisions (buy, sell, hold) without ever having direct access to execution or risk parameters.

**Code:** `src/agent/trading_agent.py`, `src/agent/prompts.py`, `src/agent/tools.py`, `.claude/skills/trading-rules/SKILL.md`

---

### Feature F3.1 — SKILL.md Dynamic Rule Injection

#### Story S3.1.1
**As a** product owner,  
**I want** trading rules externalised to a SKILL.md file loaded at runtime,  
**so that** I can update the agent's constraints without modifying Python code or redeploying.

**Acceptance Criteria:**
- [ ] AC1: On startup, `prompts.py` reads `.claude/skills/trading-rules/SKILL.md` and embeds it into `SYSTEM_PROMPT`.  
- [ ] AC2: If `SKILL.md` is missing, a clear `FileNotFoundError` is raised with a warning in logs.  
- [ ] AC3: Changes to `SKILL.md` take effect on next agent restart without code changes.  
- [ ] AC4: `SYSTEM_PROMPT` contains: agent identity, all trading rules, tool documentation.  

**Code Association:** `agent/prompts.py::TRADING_RULES`, `.claude/skills/trading-rules/SKILL.md`

---

### Feature F3.2 — Normalized Multi-Pair Cycle Prompt

#### Story S3.2.1
**As an** LLM,  
**I want** to receive a compact, normalized summary of all 15 pairs in a single prompt,  
**so that** I can rank opportunities and make decisions without exceeding token limits.

**Acceptance Criteria:**
- [ ] AC1: `build_cycle_prompt()` produces a prompt under 2,000 tokens for all 15 pairs.  
- [ ] AC2: Each pair entry includes: `score`, `direction`, `regime`, `ema_cross_bullish`, `obi`, `reasons`, `open_position` flag.  
- [ ] AC3: Raw OHLCV prices are never included in the prompt — only derived metrics.  
- [ ] AC4: Portfolio state (cash, open positions, daily PNL%) is included in every prompt.  
- [ ] AC5: Time-of-day (UTC) and Fear & Greed index are included per cycle.  

**Code Association:** `agent/prompts.py::build_cycle_prompt`

---

### Feature F3.3 — JSON Tool-Call Enforcement

#### Story S3.3.1
**As a** developer,  
**I want** the LLM to respond only via structured tool-calls,  
**so that** conversational text never reaches the execution layer and causes crashes.

**Acceptance Criteria:**
- [ ] AC1: Three tools are registered: `propose_buy(pair, usd_amount, reason)`, `propose_sell(pair, reason)`, `hold(reason)`.  
- [ ] AC2: Python execution only triggers on `message.tool_calls` — `message.content` is logged but never parsed for decisions.  
- [ ] AC3: Unrecognised tool names raise a `ValueError` logged to `audit_errors`.  
- [ ] AC4: `propose_buy` is limited to at most 3 calls per cycle.  
- [ ] AC5: LLM decisions (tool name, pair, reason, raw content) are written to `audit_llm_decisions`.

**Code Association:** `agent/trading_agent.py::run_cycle`, `agent/tools.py`

---

### Feature F3.4 — LLM Fallback & Timeout Handling

#### Story S3.4.1
**As an** ops engineer,  
**I want** the agent to fall back to a secondary model on timeout,  
**so that** a slow primary model does not halt the trading loop.

**Acceptance Criteria:**
- [ ] AC1: Primary model timeout is configurable via `llm.timeout_seconds` in `config.yaml`.  
- [ ] AC2: On timeout, agent retries once with fallback model defined in `llm.fallback_model`.  
- [ ] AC3: Timeout event is written to `audit_errors` and triggers a Telegram error alert.  
- [ ] AC4: If both models fail, the cycle exits gracefully with all signals treated as `HOLD`.

**Code Association:** `agent/trading_agent.py::_call_llm_with_retry`

---

## E4 — Risk & Compliance Guard

**Goal:** Act as a deterministic mathematical firewall between LLM proposals and actual exchange execution. Every proposed order must pass all guards or be rejected with a logged reason.

**Code:** `src/risk/risk_manager.py`

---

### Feature F4.1 — Buy Validation Guards

#### Story S4.1.1
**As a** compliance system,  
**I want** every `propose_buy` validated against a strict set of rules,  
**so that** no order is placed unless risk parameters are fully satisfied.

**Acceptance Criteria:**
- [ ] AC1: **Circuit Breaker** — If last 3 trades (within 4h) are all `stop_loss`, all buys are blocked for `risk.circuit_breaker.pause_hours` (default 4h). No separate state table — queried live from trade history.  
- [ ] AC2: **Daily Loss Limit** — If daily PNL ≤ `-risk.max_daily_loss_pct` (default 10%), all buys are blocked for the remainder of the day.  
- [ ] AC3: **Global Kill Switch** — If portfolio drawdown ≥ `risk.global_max_daily_loss_pct` (default 7%), all positions are market-sold and trading halts entirely.  
- [ ] AC4: **Max Open Positions** — Blocked if open positions ≥ `trading.max_open_positions` (default 3).  
- [ ] AC5: **Cash Reserve** — Blocked if available cash ≤ `trading.min_cash_reserve_pct` (default 10%).  
- [ ] AC6: **Fat Finger Guard** — Blocked if proposed USD > `available_cash * 0.98`.  
- [ ] AC7: **Minimum Order Size** — Blocked if proposed USD < `risk.min_order_usd` (default $5).  
- [ ] AC8: **Time-of-Day Gate** — Blocked if current UTC hour is outside `trading.allowed_trading_hours` (default 16:00–20:00 UTC). Backtest uses candle timestamp, not system clock.  
- [ ] AC9: All rejections are written to `audit_risk_checks` with the specific rule that triggered.

**Code Association:** `risk_manager.py::validate_buy`

---

### Feature F4.2 — Sell Validation (Minimum Profit Floor)

#### Story S4.2.1
**As a** fee protection system,  
**I want** to block any LLM sell where projected PNL is below the profit floor,  
**so that** fees + slippage never cause a net loss on voluntary exits.

**Acceptance Criteria:**
- [ ] AC1: `validate_sell()` computes `est_pnl_pct = ((current_price - entry_price) / entry_price) * 100`.  
- [ ] AC2: If `est_pnl_pct < trading.min_profit_floor_pct` (default 1.0%), the sell is rejected.  
- [ ] AC3: Rejection reason includes the exact projected PNL percentage in the message.  
- [ ] AC4: Automatic SL/TP exits (`stop_loss`, `take_profit`) bypass the profit floor — only agent-initiated sells are checked.  
- [ ] AC5: Rejection is written to `audit_risk_checks`.

**Code Association:** `risk_manager.py::validate_sell`

---

### Feature F4.3 — Position Sizing Cap

#### Story S4.3.1
**As a** portfolio manager,  
**I want** position size automatically capped and resized,  
**so that** no single trade exceeds defined risk limits even if the LLM requests more.

**Acceptance Criteria:**
- [ ] AC1: Max trade USD = `portfolio_balance * (max_position_pct / 100)` (default 30%).  
- [ ] AC2: If proposed amount exceeds cap, it is silently reduced (not rejected) and the cap reason is logged.  
- [ ] AC3: Final capped amount is returned alongside the approval in the tuple `(True, reason, capped_amount)`.  
- [ ] AC4: Capped trades use the ATR-proportional formula: `RiskAmount / (ATR * Multiplier)`.

**Code Association:** `risk_manager.py::validate_buy`, `features.py::compute_position_size`

---

## E5 — Trade Execution Engine

**Goal:** Translate approved trade intents into precise, fee-optimised Kraken API calls using Maker-only Limit orders with a chase mechanism.

**Code:** `src/exchange/kraken_client.py`, `src/exchange/paper_broker.py`

---

### Feature F5.1 — Post-Only Maker Limit Orders

#### Story S5.1.1
**As a** trader,  
**I want** all entries placed as Post-Only Limit orders at the current Best Bid,  
**so that** I always pay Maker fees (~0.16%) rather than Taker fees (~0.26%) and save ~1-2% per week.

**Acceptance Criteria:**
- [ ] AC1: `place_order()` always calls `create_limit_buy_order()` with `params={"postOnly": True}`.  
- [ ] AC2: Entry price is sourced from `get_latest_price(pair)` at the moment of tool execution (JIT re-fetch).  
- [ ] AC3: Volume is computed as `usd_amount / current_price` and then rounded via `amount_to_precision()` to match Kraken lot increments.  
- [ ] AC4: Price is rounded via `price_to_precision()` to match Kraken tick size rules.  
- [ ] AC5: Entry order ID is stored in `live_positions` as `entry_order_id` for status polling.

**Code Association:** `kraken_client.py::place_order`

---

### Feature F5.2 — 60-Second Limit Order Chase

#### Story S5.2.1
**As a** trading engine,  
**I want** unfilled limit orders to be cancelled and replaced at the new Best Bid after 60 seconds,  
**so that** the order always stays competitive without crossing the spread.

**Acceptance Criteria:**
- [ ] AC1: `check_stops_and_tp()` checks `placed_at` timestamp for every `pending_fill` position.  
- [ ] AC2: If `now - placed_at > 60s` and order status is still `open`, cancel and re-place at new `current_price`.  
- [ ] AC3: If the primary order was `canceled` by Kraken (e.g., spread too wide), position is removed from DB and no SL/TP is placed.  
- [ ] AC4: Chased orders reset the `placed_at` timestamp.  
- [ ] AC5: Chase events are logged with `[LIMIT_CHASE]` prefix.

**Code Association:** `kraken_client.py::check_stops_and_tp`

---

### Feature F5.3 — Deferred SL/TP Placement

#### Story S5.3.1
**As a** risk system,  
**I want** Stop-Loss and Take-Profit orders placed only after the entry order is confirmed filled,  
**so that** Kraken never receives SL/TP orders for positions that don't yet exist.

**Acceptance Criteria:**
- [ ] AC1: SL/TP placement is deferred until `fetch_order(entry_order_id)` returns `status == "closed"`.  
- [ ] AC2: On each `check_stops_and_tp()` tick, unfilled pending orders are polled via REST.  
- [ ] AC3: Once filled, SL is placed as a stop-market at `dynamic_sl_price`. TP is placed as a limit at `dynamic_tp_price`.  
- [ ] AC4: If native SL/TP fire on Kraken, position is marked `closed` in DB with appropriate `exit_reason`.  
- [ ] AC5: Fallback price-based SL/TP fires a `create_market_sell_order()` with `exit_reason = "fallback_stop_loss"` if native order polling is unreliable.

**Code Association:** `kraken_client.py::_place_sl_tp_orders`, `kraken_client.py::close_position`

---

## E6 — Paper Trading & Simulation

**Goal:** Allow full end-to-end strategy validation with zero financial risk using a virtual balance that mirrors live execution logic faithfully.

**Code:** `src/exchange/paper_broker.py`

---

### Feature F6.1 — Virtual Order Execution

#### Story S6.1.1
**As a** developer,  
**I want** paper trades to execute against live public WebSocket prices,  
**so that** the simulation reflects real market conditions without touching real funds.

**Acceptance Criteria:**
- [ ] AC1: `PaperBroker.place_order()` deducts `actual_cost + maker_fee` from virtual cash balance.  
- [ ] AC2: Entry slippage of 0.05% is applied to simulate order fill price vs WebSocket price.  
- [ ] AC3: Maker fee is 0.16% (simulating Post-Only fills). Taker fee fallback is 0.26%.  
- [ ] AC4: Virtual positions are persisted to `data/paper_trading.db` — survives restarts.  
- [ ] AC5: `get_balance()` returns `{"total_usd": cash + Σ(usd_value of open positions), "available_cash_usd": cash}`.

**Code Association:** `paper_broker.py::place_order`, `paper_broker.py::get_balance`

---

### Feature F6.2 — SL/TP Monitoring in Paper Mode

#### Story S6.2.1
**As a** paper trading system,  
**I want** stop-loss and take-profit levels monitored on every cycle tick,  
**so that** positions close automatically at the correct price levels.

**Acceptance Criteria:**
- [ ] AC1: `check_stops_and_tp()` runs on every cycle before the LLM is called.  
- [ ] AC2: If `current_price ≤ stop_loss_price`, position closes with `exit_reason = "stop_loss"`.  
- [ ] AC3: If `current_price ≥ take_profit_price`, position closes with `exit_reason = "take_profit"`.  
- [ ] AC4: Exit slippage of 0.05% and exit fee of 0.26% are applied to proceeds.  
- [ ] AC5: Closed trade PNL is written to `paper_trades` and `daily_pnl` tables.

**Code Association:** `paper_broker.py::check_stops_and_tp`, `paper_broker.py::close_position`

---

### Feature F6.3 — Backtesting Teardown & Clean Slate

#### Story S6.3.1
**As a** developer,  
**I want** backtest runs to start with a fully clean database and log,  
**so that** previous runs don't contaminate results.

**Acceptance Criteria:**
- [ ] AC1: `tests/test_backtest.py` deletes `data/backtest_paper.db` and `data/backtest_audit.db` before each run.  
- [ ] AC2: `backtest_run.log` is truncated to empty at the start of each run.  
- [ ] AC3: Production databases (`data/paper_trading.db`, `data/audit.db`) are never touched by backtest teardown.  
- [ ] AC4: Teardown is logged with `[BACKTEST INIT] Cleansing state...` prefix.

**Code Association:** `tests/test_backtest.py`

---

## E7 — Audit & Observability

**Goal:** Record every signal, decision, trade, and error with sufficient detail to reconstruct exactly why the agent made any decision at any point in time.

**Code:** `src/storage/audit_logger.py`, `src/storage/database.py`

---

### Feature F7.1 — Full Decision Audit Trail

#### Story S7.1.1
**As an** auditor,  
**I want** every cycle's signals, LLM decisions, risk checks, and trades logged in SQLite,  
**so that** I can reconstruct any trading decision long after it was made.

**Acceptance Criteria:**
- [ ] AC1: Every cycle writes to `audit_cycles` (start time, end time, cycle ID).  
- [ ] AC2: Every pair signal is written to `audit_signals` (pair, score, direction, reasons, all indicator values).  
- [ ] AC3: Every LLM tool call is written to `audit_llm_decisions` (tool, pair, reason, raw content).  
- [ ] AC4: Every risk check is written to `audit_risk_checks` (action, pair, approved, rejection_reason).  
- [ ] AC5: Every HOLD decision (including implicit holds for all non-actioned pairs) is audited.  
- [ ] AC6: Errors are written to `audit_errors` (component, message, stack trace).

**Code Association:** `storage/audit_logger.py`

---

### Feature F7.2 — Balance Snapshots

#### Story S7.2.1
**As a** portfolio manager,  
**I want** balance snapshots taken after every trade executes,  
**so that** I have a precise equity curve for performance analysis.

**Acceptance Criteria:**
- [ ] AC1: Balance snapshot is taken immediately after `close_position()` completes.  
- [ ] AC2: Snapshot includes: `total_usd`, `cash_usd`, `open_positions_count`, `timestamp`.  
- [ ] AC3: Snapshots are written to `audit_balance_snapshots` table.  
- [ ] AC4: `daily_pnl` table is updated with realized PNL after every closed trade.

**Code Association:** `storage/audit_logger.py::log_balance_snapshot`

---

### Feature F7.3 — Rejection Analysis Script

#### Story S7.3.1
**As a** developer,  
**I want** a CLI script that summarises exactly why trades were blocked,  
**so that** I can quickly diagnose when the bot is over-filtering or under-trading.

**Acceptance Criteria:**
- [ ] AC1: `scripts/audit_rejections.py` queries `audit_signals`, `audit_llm_decisions`, `audit_risk_checks`.  
- [ ] AC2: Output groups block reasons by layer (Indicator → LLM → Risk Manager).  
- [ ] AC3: Prints count per reason, session totals, and win/loss/hold summary.  
- [ ] AC4: Script supports an optional `--mode paper|backtest|live` flag.

**Code Association:** `scripts/audit_rejections.py`

---

## E8 — Telegram Notification Framework

**Goal:** Provide real-time operational awareness via Telegram so the owner can monitor the bot's health, trades, and P&L without tailing logs.

**Code:** `src/notifications/notifier.py`

---

### Feature F8.1 — Trade Lifecycle Alerts

#### Story S8.1.1
**As a** trader,  
**I want** Telegram messages for every buy and sell event,  
**so that** I am immediately informed of capital movements.

**Acceptance Criteria:**
- [ ] AC1: BUY alert includes: pair, entry price, quantity, invested USD, dynamic SL price, dynamic TP price, fee paid.  
- [ ] AC2: SELL alert includes: pair, exit reason, exit price, gross PNL%, net PNL USD, hold duration.  
- [ ] AC3: Messages are sent asynchronously and do not block the trading loop on failure.  
- [ ] AC4: If Telegram API fails, the error is logged but the trade still executes.

**Code Association:** `notifier.py::send_buy_alert`, `notifier.py::send_sell_alert`

---

### Feature F8.2 — 2-Hour Heartbeat

#### Story S8.2.1
**As an** operator,  
**I want** a Telegram heartbeat every 2 hours,  
**so that** I know the bot is alive even during periods of no trading activity.

**Acceptance Criteria:**
- [ ] AC1: Heartbeat fires every 120 minutes (8 cycles at 15-min interval).  
- [ ] AC2: Message contains: uptime, current balance, hourly PNL%, open positions, circuit breaker status.  
- [ ] AC3: Live mode only — heartbeat is suppressed in paper and backtest modes.

**Code Association:** `notifier.py::send_heartbeat`, `main.py`

---

### Feature F8.3 — 6-Hour P&L Report

#### Story S8.3.1
**As a** portfolio manager,  
**I want** a P&L summary every 6 hours,  
**so that** I can track whether the session is on track for the weekly target.

**Acceptance Criteria:**
- [ ] AC1: PNL report fires every 360 minutes (24 cycles).  
- [ ] AC2: Report includes: start-of-day balance, current balance, realized PNL USD, PNL%, win/loss trade count.  
- [ ] AC3: Report is sent in both paper and live modes.

**Code Association:** `notifier.py::send_pnl_report`

---

### Feature F8.4 — Start, Stop & Error Alerts

#### Story S8.4.1
**As an** operator,  
**I want** Telegram alerts when the bot starts, stops, or crashes,  
**so that** I can immediately investigate unexpected shutdowns.

**Acceptance Criteria:**
- [ ] AC1: `send_agent_started(mode)` is sent immediately after successful initialization.  
- [ ] AC2: `send_agent_stopped(mode)` is sent in the `finally` block ensuring it fires on both clean exits and crashes.  
- [ ] AC3: `send_error_alert(component, message)` is triggered on any unhandled exception with the first 200 chars of the error.  
- [ ] AC4: HTTP Webhook (`healthcheck_url`) is pinged every 15 minutes via `ping_healthcheck()` to support uptime monitoring via healthchecks.io.

**Code Association:** `notifier.py`, `main.py`

---

## E9 — Natural Language CLI

**Goal:** Allow the owner to interrogate the running agent, view reports, and manage the bot via natural English commands rather than raw database queries.

**Code:** `src/cli/nl_parser.py`, `src/cli/commands.py`, `src/cli/display.py`, `src/cli/agent_manager.py`, `src/reports/trade_report.py`

---

### Feature F9.1 — Natural Language Command Parsing

#### Story S9.1.1
**As a** trader,  
**I want** to type commands like `"show me BTC trades this week"` in the CLI,  
**so that** I don't need to write SQL queries to interrogate the audit database.

**Acceptance Criteria:**
- [ ] AC1: `nl_parser.py` maps natural language intents to structured CLI commands.  
- [ ] AC2: Supported intents: `report`, `balance`, `positions`, `trades [pair] [period]`, `start`, `stop`.  
- [ ] AC3: Unrecognised inputs display a help menu rather than crashing.  
- [ ] AC4: CLI supports both interactive REPL mode and single-command mode (`python kryptos.py balance`).

**Code Association:** `cli/nl_parser.py`, `cli/commands.py`

---

### Feature F9.2 — Trade Report & P&L Display

#### Story S9.2.1
**As a** trader,  
**I want** a formatted trade report with per-trade P&L, win rate, and exit reasons,  
**so that** I can evaluate system performance without opening the SQLite database.

**Acceptance Criteria:**
- [ ] AC1: `report` command displays a rich terminal table with: Trade ID, pair, entry/exit dates, invested USD, entry/exit price, PNL%, PNL USD, exit reason.  
- [ ] AC2: Win rate (wins/total) and average PNL% per trade are shown as a summary row.  
- [ ] AC3: Times are displayed in Singapore timezone (SGT) via `utils/tz.py`.  
- [ ] AC4: `report mode=backtest` queries `data/backtest_paper.db` instead of the live database.

**Code Association:** `reports/trade_report.py`, `cli/display.py`, `utils/tz.py`

---

## E10 — Backtesting & Validation

**Goal:** Allow strategy validation over 12 months of historical data to verify that quantitative rules produce positive expectancy before risking real capital.

**Code:** `tests/test_backtest.py`, `tests/trades_to_candle_converter.py`

---

### Feature F10.1 — Historical Candle Conversion

#### Story S10.1.1
**As a** developer,  
**I want** to convert raw Kraken trade CSV exports into the OHLCV JSON format consumed by the backtester,  
**so that** I can backtest over real 12-month exchange data.

**Acceptance Criteria:**
- [ ] AC1: `tests/trades_to_candle_converter.py` accepts `<source.csv>|<target.json>` batch arguments.  
- [ ] AC2: Input CSV format is `unix_timestamp,price,volume` (headerless or headered auto-detected).  
- [ ] AC3: Output JSON matches Kraken OHLC format: `[time, open, high, low, close, vwap, volume, count]` per 15-minute interval.  
- [ ] AC4: VWAP is computed as `Σ(price*volume) / Σ(volume)` per interval.  
- [ ] AC5: Empty intervals (no trades) are filled with zero-volume candles when `--sparse` is not set.  
- [ ] AC6: Pair key is inferred from the target filename (e.g., `SOLUSD_candle.json` → `SOLUSD`).

**Code Association:** `tests/trades_to_candle_converter.py`

---

### Feature F10.2 — Full Strategy Backtest

#### Story S10.2.1
**As a** quant analyst,  
**I want** to run the full agent loop over historical data,  
**so that** I can measure win rate, expectancy, and drawdown before going live.

**Acceptance Criteria:**
- [ ] AC1: `tests/test_backtest.py --candles N` replays N candles from `history/` JSON files.  
- [ ] AC2: The LLM cycle runs for each candle using `HistoricalFeed`. All risk rules apply identically to live mode.  
- [ ] AC3: Time-of-Day guard uses candle timestamp (not system clock) — verified by unit test at 10:00 UTC (rejected) and 17:00 UTC (approved).  
- [ ] AC4: Output written to `backtest_run.log` (auto-cleared at start). Never writes to production databases.  
- [ ] AC5: Final summary includes: total cycles, total trades, win rate, net PNL%, max drawdown%, Sharpe ratio.

**Code Association:** `tests/test_backtest.py`, `exchange/historical_feed.py`

---

## E11 — DevOps & Resilience

**Goal:** Ensure the bot can be reliably deployed, monitored, and restarted without data loss or financial exposure.

---

### Feature F11.1 — Dependency Locking

#### Story S11.1.1
**As a** DevOps engineer,  
**I want** all Python dependencies pinned to exact versions,  
**so that** the bot behaves identically across all environments and future package updates never break it silently.

**Acceptance Criteria:**
- [ ] AC1: `requirements.txt` contains fully pinned versions (e.g., `pandas==2.2.1`) from `pip freeze`.  
- [ ] AC2: Installation via `pip install -r requirements.txt` produces no version conflicts.  
- [ ] AC3: `requirements.txt` is validated in CI before merge.

**Code Association:** `requirements.txt`

---

### Feature F11.2 — Crash Recovery & Position Persistence

#### Story S11.2.1
**As a** trader,  
**I want** the bot to resume monitoring all open positions after a power loss or crash,  
**so that** no position is left unmonitored.

**Acceptance Criteria:**
- [ ] AC1: On startup, `broker.get_open_positions()` queries `paper_positions` / `live_positions` for all `status='open'` rows.  
- [ ] AC2: Recovered positions immediately enter the `check_stops_and_tp()` monitoring loop.  
- [ ] AC3: Hot-path startup log line: `"Recovered N open positions for monitoring."` is emitted.  
- [ ] AC4: SQLite WAL mode is enabled to protect against mid-write corruption on power loss.

**Code Association:** `exchange/paper_broker.py::get_open_positions`, `storage/database.py`

---

### Feature F11.3 — Health Check Webhook

#### Story S11.3.1
**As an** operator,  
**I want** an external uptime monitor pinged every 15 minutes,  
**so that** I receive an alert if the trading loop silently deadlocks.

**Acceptance Criteria:**
- [ ] AC1: `notifier.ping_healthcheck()` makes a `GET` request to `notifications.healthcheck_url` after every cycle completes.  
- [ ] AC2: Ping timeout is 5 seconds — never blocks the trading loop.  
- [ ] AC3: If `healthcheck_url` is empty in config, the feature is silently disabled.  
- [ ] AC4: Compatible with healthchecks.io and any HTTP-based uptime monitor.

**Code Association:** `notifier.py::ping_healthcheck`, `main.py`

---

## Epic E12 — Stop-Loss Protection & Gain Preservation

**Goal:** Protect accumulated gains and reduce maximum drawdown per trade by adding adaptive stop-loss mechanisms that respond to price movement after entry.

**Acceptance Criteria (Epic-level):**
- [x] S12.1.1: LLM cannot exit early via `propose_sell` unless at ≥80% of TP target (#83 — closed)
- [x] S12.2.1: Trailing stop moves SL upward as price rises (#84 — closed)
- [x] S12.3.1: Breakeven stop moves SL to entry once in profit (#85 — closed)
- [x] S12.4.1: ATR-based SL sets volatility-proportional stop-loss at entry (#86 — closed)
- [x] S12.5.1: Partial take-profit closes 50% at mid-target (#87 — closed)

---

### Feature F12.1 — 80% TP Proximity Guard (completed)

#### Story S12.1.1 ✅
**As a** risk manager,  
**I want** the LLM blocked from calling `propose_sell` until the position is ≥80% towards its TP target,  
**so that** early exits cannot undercut the profit floor.

**Acceptance Criteria:**
- [x] AC1: `validate_sell()` calculates `pnl_pct / take_profit_pct` proximity ratio.
- [x] AC2: If proximity < 0.80 and pnl_pct < `min_profit_floor_pct`, sell is rejected.
- [x] AC3: Automatic SL/TP hits are exempt from this guard.
- [x] AC4: 5 unit tests cover all proximity scenarios.

**Code Association:** `risk_manager.py::validate_sell`, `config.yaml::risk.tp_proximity_threshold: 0.8`

---

### Feature F12.2 — Trailing Stop (completed)

#### Story S12.2.1 ✅
**As a** trader,  
**I want** the stop-loss to trail upward as price rises,  
**so that** profits are locked in during strong uptrends.

**Acceptance Criteria:**
- [x] AC1: `check_stops_and_tp()` tracks `highest_price_seen` per position in DB.
- [x] AC2: Trailing SL activates only after gain ≥ `activate_after_pct` (default 1.5%).
- [x] AC3: Trailing SL = `highest_price_seen × (1 − trail_pct/100)`.
- [x] AC4: SL is only raised (never lowered) by trailing logic.
- [x] AC5: Per-pair `trail_pct` overrides supported (DOGE/RAILS/HYPE: 5%, SUI: 4%).
- [x] AC6: `highest_price_seen` persists in SQLite — survives restarts.
- [x] AC7: 4 unit tests cover activation threshold, SL raise, per-pair override, and SL close.
- [x] AC8: Mirrored in `kraken_client.py` for live trading parity.
- [x] AC9: Trailing stop and breakeven stop are mutually exclusive — `ConfigError` at startup if both enabled.

**Code Association:** `paper_broker.py::check_stops_and_tp`, `kraken_client.py::check_stops_and_tp`, `database.py` (migration), `config.yaml::trailing_stop`

---

### Feature F12.3 — Breakeven Stop (completed)

#### Story S12.3.1 ✅
**As a** trader,  
**I want** the stop-loss moved to my entry price once the position reaches a profit threshold,  
**so that** I cannot lose money on a trade that was once in profit.

**Acceptance Criteria:**
- [x] AC1: When `current_price >= entry_price × (1 + trigger_pct/100)`, SL is set to `entry_price`.
- [x] AC2: Guard: SL only moves if `sl_price < entry_price` (prevents re-fire).
- [x] AC3: Trailing stop takes precedence — breakeven is `elif` branch (mutually exclusive).
- [x] AC4: 3 unit tests: fires at trigger, silent before threshold, no-re-fire guard.
- [x] AC5: Mirrored in `kraken_client.py`.

**Code Association:** `paper_broker.py::check_stops_and_tp`, `kraken_client.py::check_stops_and_tp`, `config.yaml::breakeven_stop`

---

### Feature F12.4 — ATR-Based Stop-Loss at Entry (completed)

#### Story S12.4.1 ✅
**As a** quant,  
**I want** the initial stop-loss set proportional to the pair's ATR rather than a fixed percentage,  
**so that** volatile pairs get wider stops and calm pairs get tighter stops.

**Acceptance Criteria:**
- [x] AC1: `RiskManager.get_stop_loss_pct(pair, atr, price)` returns `atr_multiplier × ATR / price × 100`.
- [x] AC2: Result is clamped to `[min_stop_loss_pct, max_stop_loss_pct]` (default 1%–5%).
- [x] AC3: Falls back to static `risk.stop_loss_pct` if `atr_stop_loss.enabled: false` or ATR is None.
- [x] AC4: `TradingTools.propose_buy()` calls `get_stop_loss_pct()` and passes dynamic SL to broker.
- [x] AC5: Logged as `[ATR_SL]`.

**Code Association:** `risk_manager.py::get_stop_loss_pct`, `tools.py::propose_buy`, `config.yaml::atr_stop_loss`

---

### Feature F12.5 — Partial Take-Profit (completed)

#### Story S12.5.1 ✅
**As a** trader,  
**I want** to automatically close 50% of a position when it reaches 50% of its TP target,  
**so that** I lock in real profit while leaving half exposed to further upside.

**Acceptance Criteria:**
- [x] AC1: When `current_price >= entry_price × (1 + tp_pct × 0.5 / 100)`, close 50% of volume.
- [x] AC2: `partial_exited` flag in DB prevents double-fire.
- [x] AC3: Remaining 50% continues with original SL/TP.
- [x] AC4: If `move_sl_to_breakeven: true`, SL is moved to entry after partial exit.
- [x] AC5: Exit reason logged as `"partial_take_profit"` in trades table.
- [x] AC6: `trade_report.py` handles `partial_take_profit` exit reason (via dynamic `exit_reason_counts`).
- [x] AC7: 5 unit tests cover partial close, no-second-fire, SL move, report display.
- [x] AC8: Mirrored in `kraken_client.py`.

**Code Association:** `paper_broker.py::check_stops_and_tp`, `paper_broker.py::close_position`, `kraken_client.py`, `database.py`, `trade_report.py`, `config.yaml::partial_take_profit`

---

## Traceability Matrix

| Story | Epic | BRD FR | NFR | Code File(s) |
| :--- | :--- | :--- | :--- | :--- |
| S1.1.1 | E1 | FR2 | NFR-Latency | `websocket_feed.py` |
| S1.2.1 | E1 | FR2 | NFR-Determinism | `websocket_feed.py` |
| S2.1.1 | E2 | FR2 | NFR-Accuracy | `indicators.py` |
| S2.2.1 | E2 | FR2 | NFR-Accuracy | `signals.py` |
| S2.3.1 | E2 | FR4 | NFR-Determinism | `signals.py`, `risk_manager.py` |
| S2.4.1 | E2 | FR2, FR4 | NFR-Adaptability | `features.py` |
| S3.1.1 | E3 | FR3 | NFR-Maintainability | `prompts.py`, `SKILL.md` |
| S3.2.1 | E3 | FR3 | NFR-TokenEfficiency | `prompts.py` |
| S3.3.1 | E3 | FR3 | NFR-Determinism | `trading_agent.py`, `tools.py` |
| S4.1.1 | E4 | FR4 | NFR-Safety | `risk_manager.py` |
| S4.2.1 | E4 | FR4 | NFR-FeeProtection | `risk_manager.py` |
| S5.1.1 | E5 | FR5 | NFR-CostEfficiency | `kraken_client.py` |
| S5.2.1 | E5 | FR5 | NFR-CostEfficiency | `kraken_client.py` |
| S6.1.1 | E6 | FR1 | NFR-Fidelity | `paper_broker.py` |
| S7.1.1 | E7 | FR4 | NFR-Auditability | `audit_logger.py` |
| S8.1.1 | E8 | FR7 | NFR-Observability | `notifier.py` |
| S9.1.1 | E9 | FR6 | NFR-Usability | `nl_parser.py`, `commands.py` |
| S10.2.1 | E10 | FR1 | NFR-Validation | `test_backtest.py` |
| S11.2.1 | E11 | FR1 | NFR-Resilience | `paper_broker.py`, `database.py` |
| S11.3.1 | E11 | FR7 | NFR-Resilience | `notifier.py`, `main.py` |
| S12.1.1 | E12 | FR4, FR20 | NFR-Safety | `risk_manager.py` |
| S12.2.1 | E12 | FR4 | NFR-Safety | `paper_broker.py`, `kraken_client.py`, `database.py` |
| S12.3.1 | E12 | FR4 | NFR-Safety | `paper_broker.py`, `kraken_client.py` |
| S12.4.1 | E12 | FR4 | NFR-Safety | `risk_manager.py`, `tools.py` |
| S12.5.1 | E12 | FR4 | NFR-Safety | `paper_broker.py`, `kraken_client.py`, `database.py`, `trade_report.py` |
