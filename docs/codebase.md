# Kryptos — Codebase Reference Guide

> Developer reference for the Kryptos AI Crypto Trading Agent.  
> For product requirements see [docs/business_requirements.md](business_requirements.md).  
> For architecture decisions see [docs/detailed_solution_design.md](detailed_solution_design.md).

---

## Table of Contents

1. [Repository Overview](#1-repository-overview)
2. [Technology Stack](#2-technology-stack)
3. [Directory Layout](#3-directory-layout)
4. [Entry Points](#4-entry-points)
5. [Module Deep-Dives](#5-module-deep-dives)
6. [One Full Cycle — End-to-End Data Flow](#6-one-full-cycle--end-to-end-data-flow)
7. [Database Schema](#7-database-schema)
8. [Configuration Reference](#8-configuration-reference)
9. [Key Design Patterns](#9-key-design-patterns)
10. [Test Suite](#10-test-suite)
11. [Scripts](#11-scripts)
12. [Skills System](#12-skills-system)
13. [Environment Variables](#13-environment-variables)

---

## 1. Repository Overview

Kryptos is a Python autonomous trading agent for the Kraken exchange.  
On every 15-minute cycle it:

1. Reads live OHLCV candles from a Kraken WebSocket feed
2. Computes technical indicators (RSI, MACD, EMA, Bollinger Bands, ATR, OBI)
3. Generates a scored BUY / SELL / HOLD signal per pair
4. Passes the top signals to a local LLM (via tool/function calling)
5. Routes every LLM proposal through a deterministic Risk Manager
6. If approved, executes on the broker (Paper or Kraken Live)
7. Writes a full audit trail to SQLite

**Execution modes**

| Command | Mode | Notes |
|---|---|---|
| `python main.py --paper` | Background trading loop | Paper (virtual) money |
| `python main.py --live` | Background trading loop | Real Kraken orders |
| `python kryptos.py` | Interactive CLI | Paper or live |

---

## 2. Technology Stack

| Layer | Library / Tool | Version (requirements.txt) |
|---|---|---|
| Exchange REST | `ccxt` | ≥4.x |
| Exchange WebSocket | `websockets` | ≥12.x |
| LLM (Ollama) | `ollama` | latest |
| LLM (OpenAI-compat) | `openai` | ≥1.x |
| Technical indicators | `ta` | ≥0.11 |
| DataFrame | `pandas` | ≥2.x |
| Config parsing | `PyYAML` | ≥6 |
| Terminal UI | `rich` | ≥13 |
| Persistence | `sqlite3` | stdlib |
| Timezone | `pytz` | ≥2023 |
| Env vars | `python-dotenv` | ≥1 |
| Notifications | `requests` | ≥2.31 |

**Python requirement:** 3.11+

---

## 3. Directory Layout

```
crypto-trader-agent/
├── main.py                     Entry point — background trading loop
├── kryptos.py                  Entry point — interactive CLI
├── config.yaml                 All tunable parameters
├── requirements.txt            Python dependencies
├── README.md                   Project overview and setup guide
│
├── src/
│   ├── agent/
│   │   ├── prompts.py          SYSTEM_PROMPT + build_cycle_prompt()
│   │   ├── tools.py            propose_buy / propose_sell / hold tool handlers
│   │   └── trading_agent.py    LLM call loop, timeout, fallback model
│   │
│   ├── analysis/
│   │   ├── indicators.py       RSI, MACD, EMA 9/21/50, ATR, Bollinger, Volume SMA
│   │   ├── signals.py          10-point confluence BUY / SELL / HOLD scoring
│   │   └── features.py         Regime detection, dynamic SL/TP, ATR sizing
│   │
│   ├── exchange/
│   │   ├── paper_broker.py     Virtual order execution; same interface as KrakenClient
│   │   ├── kraken_client.py    Live Kraken REST (ccxt); Post-Only limits; chase logic
│   │   └── websocket_feed.py   Kraken WS v2; OHLCV candle buffer; OBI
│   │
│   ├── risk/
│   │   └── risk_manager.py     8 buy guards; profit-floor sell gate; circuit breaker
│   │
│   ├── storage/
│   │   ├── database.py         SQLite init, schema DDL, get_connection()
│   │   └── audit_logger.py     Append-only audit trail (cycles, signals, trades, errors)
│   │
│   ├── notifications/
│   │   └── notifier.py         Telegram alerts; healthchecks.io webhook
│   │
│   ├── cli/
│   │   ├── commands.py         CLI command handlers (balance, positions, report, …)
│   │   ├── display.py          Rich terminal tables and formatting
│   │   ├── agent_manager.py    Start / stop the background agent process
│   │   └── nl_parser.py        Natural-language CLI input parser
│   │
│   ├── reports/
│   │   └── trade_report.py     P&L and trade history reports
│   │
│   └── utils/
│       ├── tz.py               Singapore timezone helpers; now_sgt_iso()
│       └── timing.py           @timed decorator; cycle_id propagation
│
├── tests/
│   ├── test_backtest.py        Full strategy backtester using historical candles
│   ├── test_circuit_breaker.py Circuit breaker unit tests
│   ├── test_indicators.py      Indicator computation unit tests
│   ├── test_regime_and_dynamic_tp.py  Dynamic TP and regime unit tests
│   ├── test_risk_manager.py    validate_buy / validate_sell unit tests
│   └── test_trade_converter.py Trade converter unit tests
│
├── scripts/
│   ├── audit_rejections.py     Post-backtest rejection analysis (3 pipeline layers)
│   ├── review.py               14-day P&L performance review script
│   └── daily_report.py         Daily trade summary report
│
├── history/                    Historical OHLCV candle JSON files per pair
├── data/                       Runtime SQLite databases (gitignored)
├── logs/                       Rotating log files (gitignored)
│
└── .claude/
    └── skills/
        ├── commit/SKILL.md     Commit workflow automation
        ├── add-pair/SKILL.md   Add new trading pair workflow
        └── trading-rules/SKILL.md  LLM trading constraints (injected into SYSTEM_PROMPT)
```

---

## 4. Entry Points

### `main.py` — Trading Loop

`python main.py [--paper | --live]`

**Startup sequence:**

```
load_config()
  → setup_logging()
  → validate_config()          # TP values must be in ALLOWED_TAKE_PROFIT_PCTS
  → init_all_databases()       # Creates SQLite tables on first run
  → WebSocketFeed.start()      # Connects to wss://ws.kraken.com/v2
  → wait for candle buffer     # min_candles_to_start (default 220) per pair
  → notifier.send_agent_started()
  → main loop
```

**Main loop (every 15 min by default):**

```
check_stops_and_tp()           # SL/TP price-tick check FIRST, before LLM
 → for each pair with SL/TP hit: close position, notify, update circuit breaker

run_cycle()                    # LLM decision cycle
 → compute_indicators()        # All pairs
 → generate_signal()           # Scored BUY/HOLD/SELL per pair
 → build_cycle_prompt()        # Ranked pair summary → LLM
 → TradingAgent.run_cycle()    # One LLM call for all pairs
 → per tool call:
     → validate_buy/sell()     # Risk manager gate
     → broker.place_order()    # If approved
     → audit_logger.*()        # Write audit trail

kill switch check              # If daily drawdown ≥ 7% → close all + halt
heartbeat (every 8 cycles)     # Telegram summary
PNL report (every 24 cycles)   # Telegram 6-hour report
sleep(cycle_interval_secs)
```

---

### `kryptos.py` — Interactive CLI

`python kryptos.py [command]`

| Command | Description |
|---|---|
| `balance` | Show current portfolio balance |
| `positions` | Show open positions |
| `report` | Show trade history and P&L |
| `start` | Start the background trading agent |
| `stop` | Stop the background trading agent |
| *(natural language)* | Parsed by `nl_parser.py` |

---

## 5. Module Deep-Dives

### `src/analysis/indicators.py`

**`compute_indicators(candles: list, config: dict) -> Optional[dict]`**

Takes a list of `{open, high, low, close, volume}` OHLCV dicts and returns a flat indicator dict for the most recent candle. Returns `None` if fewer than `min_candles_to_start` (220) candles are available.

| Key | Description |
|---|---|
| `rsi_14` | RSI (14-period) |
| `macd_line` | MACD line |
| `macd_signal_line` | MACD signal line |
| `macd_histogram` | MACD histogram (current candle) |
| `macd_histogram_prev` | MACD histogram (prior candle) — used to detect turn |
| `ema_9` | EMA 9-period |
| `ema_21` | EMA 21-period |
| `ema_20` | EMA fast (configurable, default 20) |
| `ema_50` | EMA slow (configurable, default 50) |
| `bb_upper` | Bollinger Band upper (2σ) |
| `bb_mid` | Bollinger Band mid (20-period SMA) |
| `bb_lower` | Bollinger Band lower (2σ) |
| `atr_14` | ATR (14-period) |
| `volume` | Current candle volume |
| `volume_sma_20` | 20-period volume SMA — used for dead zone detection |
| `close` | Latest close price |

---

### `src/analysis/signals.py`

**`generate_signal(pair, indicators, config) -> dict`**

Returns `{"pair", "signal", "strength", "reasons", "price"}`.

**Hard vetoes (block BUY regardless of score):**

| Condition | Reason |
|---|---|
| `rsi_14 >= 70` | Overbought — never enter |
| `ATR-based TP < min_profit_floor_pct` | Trade cannot cover fees |
| `volume < 50% of volume_sma_20` | Volume dead zone |
| `obi < 0` | Order book sells dominate |
| `price < ema_50` | Below medium-term trend |

**BUY score contributors (min score = `buy_min_score`, default 5):**

| Signal | Score |
|---|---|
| RSI < 30 (oversold) | +3 |
| RSI 30–40 (mild oversold) | +1 |
| MACD histogram turned positive (was negative) | +3 |
| MACD histogram > 0 (already positive) | +1 |
| MACD line > signal line | +1 |
| Price ≤ BB lower band | +2 |
| EMA9 > EMA21 (short-term uptrend) | +2 |
| Price > EMA50 (medium trend, bonus) | +1 |
| Fear & Greed ≤ 40 | +1 |
| Fear & Greed ≤ 25 (extreme fear) | +1 |

**SELL score contributors (min score = `sell_min_score`, default 3):**

| Signal | Score |
|---|---|
| RSI > `rsi_overbought` (default 60) | +3 |
| MACD histogram < 0 | +2 |
| Price ≥ BB upper band | +2 |

---

### `src/analysis/features.py`

Higher-level context computations used in the LLM prompt.

| Function | Purpose |
|---|---|
| `detect_regime(candles)` | `LOW` / `STANDARD` / `HIGH` volatility from ATR relative to 20-period SMA |
| `compute_dynamic_tp(candles, config)` | ATR-proportional TP: k=1.5x/2.5x/4.5x for LOW/STANDARD/HIGH regime |
| `compute_dynamic_sl(candles, config)` | SL = min(entry×0.95, entry − ATR×multiplier) |
| `compute_position_size(balance, atr, price, config)` | ATR-proportional Kelly sizing capped at `max_position_pct` |
| `get_sentiment(config)` | Fear & Greed Index from Alternative.me API |
| `detect_pattern(candles)` | Candlestick pattern detection (hammer, engulfing, etc.) |
| `compute_exit_timing(position, indicators)` | Signal strength of holding vs exiting an open position |

---

### `src/risk/risk_manager.py`

**`validate_config(config)`** — Called at startup. Raises `ValueError` if any `take_profit_pct` is not in `[5, 8, 12, 16, 20]`.

**`RiskManager.validate_buy(...) -> (approved, reason, capped_usd)`**

Eight sequential guards — first failure blocks the trade:

| # | Guard | Default |
|---|---|---|
| 0.5 | Time-of-Day (candle timestamp, not system clock) | 16:00–20:00 UTC |
| 0 | Circuit breaker (3 consecutive SLs in 4 h) | configurable |
| 1 | Daily loss limit | 10% |
| 2 | Max open positions | 3 |
| 3 | Min cash reserve | 10% of portfolio |
| 4 | Min order size | $5 |
| 5 | Flash Crash Anomaly | >15% drop from baseline |
| 6 | Fat Finger token volume | 500,000 tokens |
| 7 | 98% safe buffer guard | `proposed > available × 0.98` |
| 8 | Cap at 30% of portfolio | hard cap |

**`RiskManager.validate_sell(pair, open_positions, current_price) -> (approved, reason, _)`**

Blocks if estimated PNL < `min_profit_floor_pct` (default 1.0%) to avoid net losses from exchange fees.

**`RiskManager.is_circuit_open() -> (tripped, resume_in_secs)`**

Queries `paper_trades` / `live_trades` directly. No separate state table — survives restarts.

---

### `src/exchange/websocket_feed.py`

Connects to `wss://ws.kraken.com/v2` (public, no auth).

- Subscribes to `ohlc` (15-min candles) and `book` (L2 depth) channels for all pairs
- Maintains a rolling candle list per pair (FIFO deque)
- Computes OBI: `(bid_volume − ask_volume) / (bid_volume + ask_volume)`

**Key methods:**

| Method | Description |
|---|---|
| `start()` | Opens WS connection, starts subscription tasks |
| `get_candles(pair)` | Returns list of OHLCV dicts for a pair |
| `get_latest_price(pair)` | Returns most recent close price |
| `get_obi(pair)` | Returns current Order Book Imbalance float |
| `is_ready(pair, min_candles)` | True if candle buffer has enough history |

---

### `src/exchange/paper_broker.py`

Virtual broker with identical interface to `KrakenClient`. Uses `paper_trading.db`.

**`place_order(pair, side, usd_amount, current_price, sl_pct, tp_pct, audit) -> dict`**

- Applies 0.05% entry slippage
- Charges 0.16% Maker fee
- Stores position in `paper_positions`
- Returns order result dict

**`close_position(pair, current_price, exit_reason, audit) -> dict`**

- Applies 0.05% exit slippage + 0.16% exit fee (Maker)
- Writes to `paper_trades`
- Returns trade result dict with `pnl_usd`, `pnl_pct`, `exit_reason`

**`check_stops_and_tp(pair, current_price, audit) -> list[dict]`**

Called at the start of every cycle. Compares `current_price` to stored `stop_loss_price` / `take_profit_price`. Returns list of closed trades.

**`get_balance() -> dict`**

Returns `{"total_usd", "cash_usd", "positions_usd", "open_positions_count"}`.

---

### `src/exchange/kraken_client.py`

Live Kraken broker. Same public interface as `PaperBroker`. Uses `live_trading.db`.

**Key differences from PaperBroker:**

- Post-Only Maker limit orders via ccxt (`postOnly=True`)
- 60-second chase: if limit order is unfilled after 60 s, cancel and re-submit at new best bid
- SL/TP placed as exchange orders **after** entry fill confirmed (`status == 'closed'`)
- Fallback: if native SL order submission fails, a market sell is scheduled
- `amount_to_precision()` / `price_to_precision()` prevent "EOrder:Invalid volume" dust errors

---

### `src/agent/prompts.py`

**`SYSTEM_PROMPT`** — Built at module import time. Loads `.claude/skills/trading-rules/SKILL.md` from disk and appends it to the base system prompt.

**`build_cycle_prompt(pairs_data, portfolio, ai_context) -> str`**

Constructs the per-cycle user message sent to the LLM. Includes:
- Portfolio state (balance, cash, open positions, daily P&L)
- Per-pair ranked signal summary (signal, score, key indicators, OBI, regime)
- Explicit action instructions and hard limits

No raw OHLCV candle data is sent to the LLM — only derived indicators.

---

### `src/agent/tools.py`

**`TradingTools`** — Container for all LLM-callable tool handlers.

| Tool | LLM calls when | What happens |
|---|---|---|
| `propose_buy(pair, usd_amount, reasoning)` | Wants to open a long | JIT price re-fetch → `validate_buy()` → `broker.place_order()` |
| `propose_sell(pair, reasoning)` | Wants to close a position | `validate_sell()` → `broker.close_position()` |
| `hold(pair, reasoning)` | Decides to wait | Logged to `audit_llm_decisions`; no order |

Every call writes to the audit trail (`log_llm_decision`, `log_risk_check`, `log_order`, `log_fill`).

---

### `src/agent/trading_agent.py`

**`TradingAgent.run_cycle(pairs_data, portfolio, ai_context) -> dict`**

1. Builds prompt via `build_cycle_prompt()`
2. Makes one LLM call for all pairs (not one call per pair)
3. Dispatches tool calls returned by the LLM
4. Logs every decision (BUY, SELL, HOLD) to audit trail
5. Returns `{"buys": int, "sells": int, "holds": int}`

**Fallback model:** If the primary model times out, retries with `llm.fallback_model` from config.

**Provider support:** `ollama` (local) or `openai_compat` (any OpenAI-compatible endpoint including Google Gemini).

---

### `src/storage/audit_logger.py`

Append-only audit logger. All methods are wrapped in `try/except` — DB write failures never crash the agent.

| Method | Table written |
|---|---|
| `log_cycle(...)` | `audit_cycles` |
| `log_signal(...)` | `audit_signals` |
| `log_llm_decision(...)` | `audit_llm_decisions` |
| `log_risk_check(...)` | `audit_risk_checks` |
| `log_order(...)` | `audit_orders` |
| `log_fill(...)` | `audit_fills` |
| `log_position_event(...)` | `audit_position_events` |
| `log_balance_snapshot(...)` | `audit_balance_snapshots` |
| `log_error(...)` | `audit_errors` |

---

### `src/notifications/notifier.py`

Sends Telegram messages via Bot API and pings healthchecks.io.

| Method | Trigger |
|---|---|
| `send_agent_started(balance, pairs, mode)` | Startup |
| `send_agent_stopped(reason)` | Shutdown |
| `send_trade_executed(trade, mode)` | Every SL/TP/agent close |
| `send_heartbeat(...)` | Every 8 cycles (~2 hours) |
| `send_pnl_report(...)` | Every 24 cycles (~6 hours) |
| `send_circuit_breaker_tripped(...)` | On 3rd consecutive SL |
| `send_error_alert(component, error)` | On caught exceptions |
| `ping_healthcheck()` | Every cycle |

---

## 6. One Full Cycle — End-to-End Data Flow

```
WebSocketFeed (running in background)
  │  Receives 15-min OHLCV candles + L2 book updates
  │  Computes OBI continuously
  ▼
main.py / run_cycle()
  │
  ├─ [1] check_stops_and_tp() — highest priority
  │      For each pair: current_price vs SL/TP thresholds
  │      If hit → broker.close_position() → notifier → circuit breaker update
  │
  ├─ [2] compute_indicators(candles, config)  [per pair]
  │      Returns: RSI, MACD, EMA 9/21/50, Bollinger, ATR, Volume SMA
  │
  ├─ [3] generate_signal(pair, indicators, config)  [per pair]
  │      Confluence scoring → BUY / SELL / HOLD + strength + reasons
  │      Hard vetoes applied before scoring
  │
  ├─ [4] build_cycle_prompt(pairs_data, portfolio, ai_context)
  │      Ranked signal summary → single LLM user message
  │
  ├─ [5] TradingAgent.run_cycle()
  │      One LLM call → 0..N tool calls returned
  │
  ├─ [6] Per tool call:
  │      propose_buy  → validate_buy()  → broker.place_order()
  │      propose_sell → validate_sell() → broker.close_position()
  │      hold         → log only
  │
  ├─ [7] audit_logger.log_*(...)
  │      Writes cycle, signals, decisions, risk checks, orders, fills
  │
  └─ [8] audit_logger.log_balance_snapshot()
         Post-trade portfolio state
```

---

## 7. Database Schema

Three SQLite databases, all stored in `data/`.

### `paper_trading.db` / `live_trading.db`

```sql
-- paper_wallet / daily_pnl
paper_wallet        (id, updated_at, cash_usd)
paper_positions     (id, opened_at, pair, side, entry_price, volume,
                     usd_value, stop_loss_price, take_profit_price,
                     stop_loss_pct, take_profit_pct, status)
paper_trades        (id, opened_at, closed_at, pair, side, entry_price,
                     exit_price, volume, usd_invested, pnl_usd, pnl_pct,
                     exit_reason, hold_duration_secs, fee_usd,
                     stop_loss_pct, take_profit_pct)

-- live adds order IDs
live_positions      (... same + entry_order_id, stop_loss_order_id, take_profit_order_id)
live_trades         (... same + entry_order_id, exit_order_id)
daily_pnl           (id, date, starting_balance, ending_balance, pnl_usd, pnl_pct)

-- shared key-value store (both paper_trading.db and live_trading.db)
agent_state         (key TEXT PRIMARY KEY, value TEXT NOT NULL)
                    -- e.g. key = "start_of_day_balance_2026-04-11" (UTC date)
```

### `audit.db`

```sql
audit_cycles           (id, mode, cycle_at, portfolio_balance_usd,
                        available_cash_usd, open_positions_count,
                        daily_pnl_usd, daily_pnl_pct, cycle_duration_ms)

audit_signals          (id, cycle_id→, pair, price, rsi_14, macd_line,
                        macd_signal_line, macd_histogram, ema_20, ema_50,
                        bb_upper, bb_mid, bb_lower, atr_14,
                        signal_direction, signal_strength, signal_reasons)

audit_llm_decisions    (id, cycle_id→, mode, decided_at, pair, model_name,
                        decision_type, tool_called, tool_args, hold_reason,
                        reasoning_summary, raw_llm_output,
                        prompt_tokens, completion_tokens, latency_ms)

audit_risk_checks      (id, llm_decision_id→, checked_at, proposed_action,
                        proposed_pair, proposed_usd_amount, approved,
                        rejection_reason, adjusted_usd_amount)

audit_orders           (id, risk_check_id→, mode, submitted_at, pair, side,
                        order_type, role, requested_volume, requested_price,
                        exchange_order_id, paper_fill_price, status,
                        error_message, configured_stop_loss_pct,
                        configured_take_profit_pct)

audit_fills            (id, order_id→, mode, filled_at, fill_price,
                        fill_volume, fill_usd_value, fee_usd, slippage_pct)

audit_position_events  (id, mode, event_at, pair, event_type, entry_price,
                        exit_price, pnl_usd, pnl_pct, hold_duration_seconds,
                        exit_order_id→, take_profit_pct_used,
                        stop_loss_pct_used)

audit_balance_snapshots(id, mode, snapshot_at, total_usd, cash_usd,
                        holdings_json, unrealised_pnl_usd)

audit_errors           (id, mode, error_at, component, error_type,
                        error_message, stack_trace, recovered)
```

---

## 8. Configuration Reference

`config.yaml` is the single source of truth for all tunable parameters.

```yaml
llm:
  provider: openai_compat     # 'ollama' | 'openai_compat'
  model: gemini-2.5-flash     # Primary model
  fallback_model: qwen2.5:7b  # On primary timeout
  base_url: https://...       # OpenAI-compat endpoint
  api_key: ...                # Key for compat endpoint
  timeout_seconds: 120
  max_reasoning_chars: 500
  request_delay_seconds: 0

trading:
  cycle_interval_minutes: 15
  max_buys_per_cycle: 2
  max_open_positions: 3
  stop_loss_pct: 5            # Applied to all pairs (non-negotiable)
  min_profit_floor_pct: 1.0   # Minimum PNL% for agent sells
  allowed_trading_hours:
    enabled: true
    start_hour_utc: 16        # 16:00–20:00 UTC default
    end_hour_utc: 20
  pairs:
    - pair: BTC/USD
      take_profit_pct: 8
    - pair: ETH/USD
      take_profit_pct: 12
    # ... (24 pairs total; RAILS/USD configured but disabled)

indicators:
  min_candles_to_start: 220
  rsi_period: 14
  rsi_oversold: 30
  rsi_overbought: 60
  macd_fast: 12
  macd_slow: 26
  macd_signal: 9
  bb_period: 20
  bb_std: 2
  ema_fast: 20
  ema_slow: 50
  atr_period: 14

signals:
  buy_min_score: 5
  sell_min_score: 3
  rsi_oversold_score: 3
  macd_turn_positive_score: 3
  bb_lower_score: 2
  ema_short_uptrend_score: 2
  # ... (all score weights configurable)

risk:
  daily_loss_limit_pct: 10
  min_cash_reserve_pct: 10
  min_order_usd: 5.0
  max_token_volume_per_trade: 500000
  flash_crash_tolerance_pct: 15.0
  circuit_breaker:
    enabled: true
    consecutive_stops: 3
    pause_hours: 4
  kill_switch:
    enabled: true
    daily_drawdown_pct: 7

paper:
  starting_balance: 1000.0
  slippage_pct: 0.05
  maker_fee_pct: 0.16

storage:
  audit_db: audit.db
  paper_db: paper_trading.db
  live_db: live_trading.db
  log_max_bytes: 104857600
  log_backup_count: 4
  llm_debug_logging: false

notifications:
  telegram:
    enabled: true
    bot_token: ${TELEGRAM_BOT_TOKEN}
    chat_id: ${TELEGRAM_CHAT_ID}
  healthcheck:
    enabled: true
    url: https://hc-ping.com/...
```

---

## 9. Key Design Patterns

### 1. Layered Deterministic Swarm
The LLM advises; Python enforces. Every LLM tool call is gated through `RiskManager` before any broker call. The LLM cannot override capital limits, time guards, or circuit breakers.

### 2. Append-Only Audit Trail
`audit_logger.py` only inserts, never updates. All write methods are wrapped in `try/except` — a DB failure degrades gracefully and never crashes the agent.

### 3. Dual-Mode Interface Parity
`PaperBroker` and `KrakenClient` share the same public methods (`place_order`, `close_position`, `check_stops_and_tp`, `get_balance`, `get_open_positions`). Switching between paper and live requires no agent code changes.

### 4. Confluence Signal Scoring
No single indicator triggers a buy. Multiple signals must accumulate to reach `buy_min_score`. Two hard vetoes (RSI ≥ 70 and ATR TP < profit floor) block buys regardless of score.

### 5. Candle-Timestamp Time Gating
The Time-of-Day guard uses the candle timestamp, not `datetime.now()`. This ensures backtesting uses historical hours — not the current system clock.

### 6. Post-Only Limit Order + Chase
In live mode, orders are submitted as Post-Only Maker limits at best bid. After 60 seconds, unfilled orders are cancelled and re-submitted at the new best bid. Falls back to market order if precision errors occur.

### 7. DB-Backed Circuit Breaker
The circuit breaker reads directly from `paper_trades`/`live_trades`. No separate state table means state survives agent restarts automatically.

---

## 10. Test Suite

```bash
# All tests
python -m pytest tests/

# Backtest (uses historical candle JSON from history/)
python tests/test_backtest.py --candles 100

# Specific test files
python -m pytest tests/test_indicators.py
python -m pytest tests/test_risk_manager.py
python -m pytest tests/test_circuit_breaker.py
python -m pytest tests/test_regime_and_dynamic_tp.py
```

**Backtest behaviour:**
- Clears `data/backtest_audit.db`, `data/backtest_paper.db`, and `backtest_run.log` on each run
- Uses `HistoricalFeed` instead of `WebSocketFeed`
- Passes candle timestamps to `validate_buy()` for time-gated backtesting

---

## 11. Scripts

| Script | Usage | Purpose |
|---|---|---|
| `scripts/audit_rejections.py` | `python scripts/audit_rejections.py --db data/backtest_audit.db` | Analyse why trades were blocked (3 pipeline layers) |
| `scripts/review.py` | `python scripts/review.py --mode paper --days 14` | 14-day performance review with READY verdict |
| `scripts/daily_report.py` | `python scripts/daily_report.py` | Today's trade summary |

---

## 12. Skills System

`.claude/skills/` contains SKILL.md files for Claude-assisted development workflows.

| Skill | Trigger | Purpose |
|---|---|---|
| `commit/SKILL.md` | "commit", "push", "save" | Full commit workflow: session notes → CLAUDE.md → README → codebase.md → CHANGELOG → git |
| `add-pair/SKILL.md` | "add pair", "onboard PAIR" | Step-by-step pair config, candle fetch, and validation |
| `trading-rules/SKILL.md` | Injected at runtime | LLM hard constraints (dynamically loaded into `SYSTEM_PROMPT` at startup) |

The `trading-rules/SKILL.md` is the **only** file that is read by the production agent at runtime. All other skills are developer tooling only.

---

## 13. Environment Variables

| Variable | Required | Purpose |
|---|---|---|
| `KRAKEN_API_KEY` | Live mode only | Kraken REST API authentication |
| `KRAKEN_API_SECRET` | Live mode only | Kraken REST API authentication |
| `TELEGRAM_BOT_TOKEN` | Optional | Telegram trade notifications |
| `TELEGRAM_CHAT_ID` | Optional | Telegram chat target |

Set via `.env` file in the project root (loaded by `python-dotenv` at startup) or as shell environment variables.
