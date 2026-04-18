# Business Requirements Document
## Kryptos — AI Crypto Trading Agent

| Field | Value |
|---|---|
| Document version | 2.0 |
| Date | 11 April 2026 |
| Author | Vipul Sanghrajka |
| Status | Approved — implementation complete |

| Revision | Change summary |
|---|---|
| 1.0 | Initial release — trading agent, paper/live mode, audit trail, reporting scripts |
| 1.1 | Added: Kryptos CLI (NL REPL + direct subcommands), Reports module (9 query functions), NL intent parser with Ollama + keyword fallback, agent process manager, Rich terminal display layer |
| 1.2 | Changed candle interval to 15-min; expanded pair list from 4 to 9 pairs (added XRP, TRX, DOGE, ADA, LTC); updated indicator parameters; added BB band-squeeze guard; all parameters externalised to `config.yaml`; added SGT timezone throughout; rotating log files |
| 1.3 | Added RAILS/USD as 10th trading pair (TP 20%, SL 5%); added `/add-pair` Claude Code skill for onboarding new pairs; added `/commit` Claude Code skill |
| 2.0 | **Volatility-Adaptive Quant Migration**: replaced reversal-gate signals with 10-point confluence scoring; ATR-proportional position sizing; dynamic per-order Take Profit (ATR-adjusted); EMA 9/21/50 trend + momentum filters; Order Book Imbalance (OBI) streaming; Post-Only Limit orders with 60-second chase; Minimum Profit Floor (1.0%); Time-of-Day trading window (16:00–20:00 UTC); Volume Dead Zone guard (50% SMA); Global Kill Switch (−7% daily drawdown); Circuit Breaker (3 consecutive stop-losses → 4-hour pause); Fat Finger guard (98% cash buffer / $5 minimum); Bearish-regime caution factor (0.5×); Fear & Greed Index signal injection; 2-hour Telegram heartbeat; 6-hour PNL report; 15-minute healthchecks.io webhook; full backtesting pipeline; audit-rejection analysis script; expanded to 15 trading pairs |
| 2.1 | Added 10 new trading pairs (WIF, TON, OP, ARB, JUP, PEPE, TIA, RENDER, FET, STX) expanding to 24 active pairs (25 configured, RAILS/USD disabled); calibrated per-pair signal parameters; trailing-stop overrides for Tier 2 volatile pairs; closes #145–#154 |
| 2.2 | Added 3 new trading pairs (PENDLE, ONDO, BONK) expanding to 27 active pairs (28 configured, RAILS/USD disabled); TP whitelist extended to include 25%; PENDLE in eth_ecosystem cluster; BONK in memecoins cluster; per-pair trailing stop overrides for PENDLE/BONK; closes #186–#188 |
| 2.3 | Added MOVR/USD (Moonriver, TP 20%, alt_l1 cluster, Tier 3) expanding to 28 active pairs (29 configured, RAILS/USD disabled); calibrated signal parameters (92% win rate in 7-day backtest); closes #274 |

---

## 1. Executive Summary

The product owner requires an autonomous AI-driven trading agent that monitors the cryptocurrency market and executes trades on their behalf via the Kraken exchange. The product owner is new to cryptocurrency trading and requires the system to act conservatively, prioritising capital protection above profit maximisation.

The agent must operate continuously, make data-driven decisions using a locally-hosted AI model, and maintain a complete audit trail of every decision — including decisions not to trade. A paper trading mode must allow safe validation of the agent's behaviour before any real money is committed.

In its second major version, Kryptos graduates from a signal-gate pattern to a fully **Volatility-Adaptive Quantitative Architecture**: every position size, take-profit target, and buy decision is derived from live market volatility (ATR) and a multi-indicator confluence score. A hard-coded deterministic **Risk & Compliance Guard** layer vetoes any LLM decision that violates mathematical trading rules — the LLM never has final authority over risk parameters.

---

## 2. Business Objectives

| ID | Objective |
|---|---|
| BO-01 | Automate cryptocurrency trading without requiring the product owner to monitor markets manually |
| BO-02 | Protect invested capital as the primary goal; profit generation is secondary |
| BO-03 | Validate the agent's behaviour risk-free over a paper trading period before live deployment |
| BO-04 | Provide full transparency into every decision the agent makes, including reasoning |
| BO-05 | Keep all AI inference local to avoid sending financial data to third-party AI providers |
| BO-06 | Enable the product owner to receive real-time alerts about significant trading events |
| BO-07 | Operate exclusively as a Maker to minimise exchange fees via Post-Only Limit orders |
| BO-08 | Ensure the system survives API anomalies, flash crashes, and exchange dust-limit errors without manual intervention |
| BO-09 | Provide a backtesting pipeline to validate strategy changes before deploying to paper or live mode |

---

## 3. Stakeholders

| Role | Responsibility |
|---|---|
| Product Owner | Defines requirements; receives trade alerts and heartbeats; reviews paper trading results; authorises live deployment |
| Trading Agent (AI) | Monitors markets, ranks pairs, proposes trades, verbalises reasoning |
| Risk Manager (system) | Deterministically enforces all capital protection rules — overrides the AI if any limit is exceeded |
| Kraken Exchange | Executes live orders; provides real-time market price feed and Level 2 order book data |
| healthchecks.io | Receives 15-minute HTTP pings; alerts product owner if the agent goes silent |

---

## 4. Scope

### 4.1 In Scope

- Automated monitoring and trading of twenty-eight cryptocurrency pairs: **BTC/USD, ETH/USD, BNB/USD, SOL/USD, XRP/USD, TRX/USD, DOGE/USD, ADA/USD, LTC/USD, AVAX/USD, SUI/USD, HYPE/USD, UNI/USD, INJ/USD, WIF/USD, TON/USD, OP/USD, ARB/USD, JUP/USD, PEPE/USD, TIA/USD, RENDER/USD, FET/USD, STX/USD, PENDLE/USD, ONDO/USD, BONK/USD, MOVR/USD** (RAILS/USD configured but disabled)
- Technical analysis using RSI, MACD, EMA 9/21/50, ATR, Bollinger Bands, Volume SMA, and Fear & Greed Index
- Real-time Level 2 Order Book Imbalance (OBI) streaming per pair
- AI-assisted buy, sell, and hold decisions using a locally hosted LLM (configurable via `config.yaml`)
- Deterministic risk management layer that cannot be overridden by the AI
- Paper trading simulation mode with a virtual USD 1,000 balance
- Live trading mode via Kraken exchange using Post-Only Limit orders
- SQLite audit database recording every decision and its full reasoning chain
- Telegram notifications for trade events, heartbeats, and daily summaries
- 15-minute healthchecks.io webhook for uptime monitoring
- Daily reporting and a paper trading readiness review
- Full backtesting pipeline against historical OHLCV candle data
- Post-backtest rejection analysis via `scripts/audit_rejections.py`
- **Natural-language CLI (`kryptos.py`)** for managing the agent and querying reports
- **Reports module** querying trade history, LLM decisions, performance metrics, and open positions
- **Agent process management** (start / stop / status / schedule) from the CLI
- Claude Code skills: `/add-pair`, `/commit`, `/trading-rules`

### 4.2 Out of Scope

- Margin trading, short selling, or leveraged positions
- Portfolio rebalancing (agent only opens new positions; it does not reallocate existing holdings)
- Support for exchanges other than Kraken
- Mobile application or web dashboard (CLI and Telegram only)
- Automated live deployment without human review of paper trading results
- Tax reporting or accounting integration

---

## 5. Functional Requirements

### 5.1 Market Coverage

| ID | Requirement |
|---|---|
| FR-01 | The system MUST monitor the following pairs: BTC/USD, ETH/USD, BNB/USD, SOL/USD, XRP/USD, TRX/USD, DOGE/USD, ADA/USD, LTC/USD, AVAX/USD, SUI/USD, HYPE/USD, UNI/USD, INJ/USD, WIF/USD, TON/USD, OP/USD, ARB/USD, JUP/USD, PEPE/USD, TIA/USD, RENDER/USD, FET/USD, STX/USD, PENDLE/USD, ONDO/USD, BONK/USD, MOVR/USD |
| FR-02 | The system MUST receive real-time price data from the Kraken public WebSocket feed (`wss://ws.kraken.com/v2`) |
| FR-03 | The system MUST stream Level 2 Order Book data per pair and compute Order Book Imbalance (OBI) = `(BidVol − AskVol) / (BidVol + AskVol)` on every WebSocket update |
| FR-04 | The system MUST back-fill historical OHLCV candles from the Kraken public REST API on startup |
| FR-05 | The system MUST maintain a rolling buffer of **300 fifteen-minute candles** (75 hours of history) per pair |
| FR-06 | The system MUST automatically reconnect to the WebSocket feed if the connection is lost, using exponential backoff up to a configurable maximum |

### 5.2 Technical Analysis

| ID | Requirement |
|---|---|
| FR-07 | The system MUST compute the following indicators per pair on 15-minute candles: RSI (period 14), MACD (12/26/9 with histogram and previous histogram), EMA 9, EMA 21, EMA 50, ATR (period 14), Bollinger Bands (period 20, std 2), and Volume SMA (period 20) |
| FR-08 | The system MUST require a minimum of **220 candles** per pair before generating any signal to ensure all indicators have sufficient warm-up data |
| FR-09 | The system MUST classify each pair as BUY, SELL, or HOLD using a **10-point additive confluence scoring system** configurable in `config.yaml` under `signals:` |
| FR-10 | BUY signals MUST require a minimum score of **5 points** and pass all hard vetoes. Score contributors are: EMA9 > EMA21 micro-momentum (+2), Price > EMA50 macro trend (+2), MACD histogram turn from negative to positive (+3) or merely positive (+1), RSI < 70 (+1), OBI > 0 (+1), Fear & Greed extreme fear ≤ 25 (+2) or fear ≤ 40 (+1) |
| FR-11 | Two conditions MUST act as hard vetoes that override any score: RSI ≥ 70 (overbought) and ATR-based dynamic TP < minimum profit floor (1.0%) |
| FR-12 | BUY signals MUST be suppressed when the current 15-minute candle volume is below **50% of the 20-period Volume SMA** (Volume Dead Zone guard) |
| FR-13 | The system MUST inject the **Fear & Greed Index** value (fetched once per cycle) into each pair's signal context before scoring |
| FR-14 | SELL signals MUST require overbought RSI (≥ 70) or a MACD bearish crossover with at least 2 confirming indicators |

### 5.3 AI Decision Making

| ID | Requirement |
|---|---|
| FR-15 | The system MUST use an LLM with function/tool-calling support (configurable via `config.yaml → llm.model`) for final trade decisions; any compatible model may be used (e.g. `qwen2.5:7b` via Ollama, or a cloud API such as Gemini) |
| FR-16 | The LLM MUST receive a structured prompt each cycle containing portfolio state, per-pair confluence scores and indicators, ATR-adjusted TP targets, and current holdings — never raw OHLCV prices |
| FR-17 | The LLM MUST call exactly one tool per cycle across all pairs: `propose_buy` (top-3 BUY signals only), `propose_sell` (strong conditions only), or `hold` |
| FR-18 | Every `hold` decision MUST include a written reason from the LLM |
| FR-19 | The LLM MUST NOT perform risk arithmetic or enforce position limits — those are the risk manager's responsibility |
| FR-20 | The LLM MUST NOT call `propose_sell` unless the position P&L is above +2%; early TP capture requires the position to be at ≥ 80% of its TP target with a confirmed reversal signal |
| FR-21 | If the primary LLM model fails or times out, the system MUST fall back to the model configured in `config.yaml → llm.fallback_model` and log the event |
| FR-22 | If no LLM response is received within the timeout, the system MUST default to `hold` for that cycle |
| FR-23 | The LLM system prompt MUST be dynamically loaded from `.claude/skills/trading-rules/SKILL.md` at startup to serve as the single source of truth for all trading rules |

### 5.4 Risk Management

| ID | Requirement |
|---|---|
| FR-24 | The system MUST enforce a fixed stop-loss of **5% below entry price** on every trade — the LLM cannot override this |
| FR-25 | The system MUST enforce configurable take-profit levels of **5%, 8%, 12%, 16%, 20%, or 25%** per pair (whitelist-enforced; invalid values prevent startup) |
| FR-26 | ATR-based **dynamic take-profit** MUST be computed per order using `Entry + (k × ATR)`. If `dynamic_tp.enabled: true` in `config.yaml`, this overrides the static TP for the order; it falls back to static if the pair is not in the dynamic TP values |
| FR-27 | No single trade MUST exceed **30% of the total portfolio value**; amounts exceeding this cap MUST be silently resized (not rejected) |
| FR-28 | No more than **3 positions** MUST be open simultaneously across all pairs |
| FR-29 | The system MUST maintain a minimum **10% cash reserve** of total portfolio at all times |
| FR-30 | If daily losses exceed **10% of the start-of-day balance**, all new buys MUST be blocked for the remainder of that calendar day |
| FR-31 | The system MUST enforce a **Global Kill Switch**: if the daily portfolio drawdown reaches **−7%**, the system MUST immediately liquidate all open positions via market orders and halt all trading for the day |
| FR-32 | The system MUST implement a **Circuit Breaker**: if 3 consecutive trades in the last 4 hours all closed at stop-loss, all new buys MUST be blocked for 4 hours. This state MUST be derived from the trade database (no separate state table) so it survives restarts |
| FR-33 | The system MUST enforce a **Minimum Profit Floor** of 1.0% (configurable via `config.yaml → risk.min_profit_floor_pct`): `propose_sell` MUST be rejected if estimated net P&L at the current live price is below this threshold, accounting for exit slippage and fees |
| FR-34 | The system MUST enforce a **Fat Finger Guard**: no trade MUST use more than 98% of available cash (2% buffer for fees); the minimum order value is $5 USD |
| FR-35 | In a **bearish regime** (as classified by `features.py`), the per-trade maximum MUST be scaled by `caution_factor: 0.5` in `main.py` before the LLM cycle — the LLM cannot override this cap |
| FR-36 | All risk rules MUST be enforced by deterministic Python code in `src/risk/risk_manager.py` — never by the LLM |
| FR-37 | The **Time-of-Day filter** MUST block all new buy orders outside the **16:00–20:00 UTC** window (London/New York overlap), evaluated against the candle timestamp (not the system clock) to support backtesting |

### 5.5 Paper Trading Mode

| ID | Requirement |
|---|---|
| FR-38 | The system MUST support a `--paper` flag that activates paper trading mode |
| FR-39 | Paper trading MUST initialise with a virtual balance of **USD 1,000** on first run |
| FR-40 | Paper trading MUST NOT require Kraken API keys; the public price feed is sufficient |
| FR-41 | Paper trading MUST simulate a **0.05% slippage** on entry and exit fills, and a **0.16% Maker fee** on entry and a **0.26% Taker fee** on exit |
| FR-42 | Paper trading MUST monitor stop-loss and take-profit levels on every cycle tick and auto-close positions that are triggered |
| FR-43 | All paper trades MUST be stored in `paper_trading.db` with the same schema as live trades |

### 5.6 Live Trading Mode

| ID | Requirement |
|---|---|
| FR-44 | The system MUST support a `--live` flag that activates live trading mode |
| FR-45 | Live mode MUST authenticate with Kraken using `KRAKEN_API_KEY` and `KRAKEN_API_SECRET` from the environment |
| FR-46 | Live mode MUST place entry orders as **Post-Only Limit orders** (`postOnly: True`) to qualify for Maker fee rates |
| FR-47 | If a Post-Only limit order does not fill within **60 seconds**, the system MUST chase the market by cancelling and re-submitting at the updated best ask price (limit chase loop) |
| FR-48 | After every live entry, the system MUST place native stop-loss and take-profit orders on Kraken's servers **only after the entry order confirms `status == 'closed'`** |
| FR-49 | If a local fallback SL/TP fires (price breach detected before native orders execute), the system MUST cancel any pending native limit orders and submit a market sell classified as `"fallback_stop_loss"` |
| FR-50 | All order quantities and prices MUST be formatted using CCXT `amount_to_precision()` and `price_to_precision()` to prevent Kraken dust/increment errors |
| FR-51 | Live trades MUST be stored in `live_trading.db` |

### 5.7 Audit Trail

| ID | Requirement |
|---|---|
| FR-52 | The system MUST record **every decision** (BUY, SELL, and HOLD) in `audit.db` — not just executed trades |
| FR-53 | The audit record MUST store the full LLM reasoning text (`raw_llm_output`) and a short summary (`reasoning_summary`) |
| FR-54 | HOLD decisions MUST record the LLM's stated reason in a dedicated `hold_reason` column |
| FR-55 | The audit trail MUST maintain a foreign-key chain: cycle → signal → LLM decision → risk check → order → fill → position event |
| FR-56 | The audit logger MUST NEVER raise an exception; all writes MUST be wrapped in try/except to prevent audit failures from disrupting trading |
| FR-57 | The audit database MUST be append-only; no records MUST be deleted or updated after creation |
| FR-58 | The system MUST record balance snapshots **after** trades execute (post-trade re-fetch) so the snapshot reflects the actual post-trade balance |

### 5.8 Notifications

| ID | Requirement |
|---|---|
| FR-59 | The system MUST send Telegram alerts for: trade executed, stop-loss triggered, take-profit triggered, daily loss limit reached, agent started, agent stopped, and unhandled errors |
| FR-60 | All paper trading alerts MUST be prefixed with `[PAPER]` |
| FR-61 | If Telegram is not configured, the system MUST degrade gracefully to console logging — it MUST NOT crash |
| FR-62 | The system MUST send a **Telegram heartbeat** every **2 hours** summarising: current balance, hourly P&L, cycle count, buys/sells executed, and circuit breaker state |
| FR-63 | The system MUST send a **6-hour PNL report** via Telegram with cumulative P&L, open positions, and daily drawdown |
| FR-64 | The system MUST ping a **healthchecks.io webhook** every **15 minutes** (`ping_healthcheck()`) so external uptime monitoring can alert if the agent goes silent |
| FR-65 | Heartbeat and healthcheck pings MUST be skipped in backtest mode |

### 5.9 Reporting

| ID | Requirement |
|---|---|
| FR-66 | A daily report script MUST output per-pair P&L, trade count, win rate, and decision breakdown (BUY/SELL/HOLD counts) |
| FR-67 | A paper trading review script MUST compute win rate, max drawdown, total P&L, and per-pair performance and output a **READY FOR LIVE TRADING** or **NOT READY** verdict |
| FR-68 | The READY verdict MUST require: win rate ≥ 50%, max drawdown < 15%, total P&L > 0, and at least 10 trades executed |
| FR-69 | A `scripts/audit_rejections.py` script MUST query all three audit layers (signals, LLM decisions, risk checks) to explain why the bot did not buy during a given backtest or live run |

### 5.10 Decision Cycle

| ID | Requirement |
|---|---|
| FR-70 | The agent MUST run a decision cycle every **30 minutes** |
| FR-71 | Stop-loss and take-profit checks (`check_stops_and_tp()`) MUST run at the **start of every cycle**, before the LLM is invoked — these are the highest-priority action |
| FR-72 | The agent MUST wait for at least **220 candles** per pair before running the first cycle; a configurable timeout allows the agent to proceed if the buffer does not fill in time |
| FR-73 | One LLM call MUST be made per cycle covering all pairs (single ranked multi-pair prompt, not one call per pair) |
| FR-74 | Any exception in a single pair's analysis MUST be logged and the agent MUST continue processing the remaining pairs |
| FR-75 | The system MUST log execution time for every significant method in the decision flow using a `@timed` decorator; each log entry MUST include: cycle ID, class name, method name, and elapsed milliseconds |
| FR-76 | All timestamps throughout the system MUST use **Singapore Standard Time (SGT, UTC+8)** |
| FR-77 | Agent logs MUST be written to `logs/agent.log` using a **rotating file handler**: maximum 100 MB per file, retaining 4 backup copies |

### 5.11 Backtesting

| ID | Requirement |
|---|---|
| FR-78 | The system MUST provide a backtesting pipeline (`tests/test_backtest.py`) that replays historical OHLCV candle data through the full signal → LLM → risk → broker execution stack |
| FR-79 | Each backtest run MUST start with a clean slate: clearing `backtest_run.log`, `data/backtest_audit.db`, and `data/backtest_paper.db` before execution |
| FR-80 | The backtest MUST pass the historical candle timestamp to `validate_buy()` so the Time-of-Day filter evaluates historical time, not the system clock |
| FR-81 | The backtest historical feed (`HistoricalFeed`) MUST use pre-recorded candle JSON files from the `history/` directory |

### 5.12 CLI — Natural Language Interface

| ID | Requirement |
|---|---|
| FR-82 | The system MUST provide a CLI entry point (`kryptos.py`) as the primary user interface |
| FR-83 | The CLI MUST support three operating modes: **interactive REPL**, **single NL command**, and **direct subcommands** |
| FR-84 | The CLI MUST accept free-text natural-language input and classify it into structured intents using the local Ollama model at `temperature=0.0` with JSON-only response format |
| FR-85 | If Ollama is unavailable, the CLI MUST fall back automatically to **keyword-based intent matching** — the CLI MUST remain fully functional in this mode |
| FR-86 | The CLI MUST support the following direct subcommands: `start`, `stop`, `status`, `report`, `trades`, `decisions`, `metrics`, `summary`, `positions`, `log` |
| FR-87 | The `start` subcommand MUST accept `--paper` and `--live` flags and launch the agent as a **background process** managed via a PID file at `data/kryptos.pid` |
| FR-88 | The `stop` command MUST send SIGTERM, wait up to 10 seconds, then send SIGKILL if the process has not exited |
| FR-89 | The CLI MUST display all output using a **Rich-based terminal UI** with the following colour convention: green = BUY / positive / running; red = SELL / negative / stopped; yellow = HOLD / warnings; cyan = info headers; magenta = LLM reasoning text |
| FR-90 | The interactive REPL MUST maintain **command history** across sessions, stored at `data/.kryptos_history` |

### 5.13 Reports Module

| ID | Requirement |
|---|---|
| FR-91 | The reports module MUST query data from `audit.db` and the relevant trading database depending on mode |
| FR-92 | Trade records MUST be enriched with the corresponding LLM decision using a **±5-minute time-window JOIN** on `audit_llm_decisions` |
| FR-93 | The `report` command MUST display: portfolio balance summary, recent closed trades table, and rolling performance metrics |
| FR-94 | The `decisions` command MUST display: per-pair BUY/SELL/HOLD decision matrix, top hold reasons, model usage statistics, and average LLM latency |
| FR-95 | The `metrics` command MUST display: overall win rate, total P&L, maximum drawdown, per-pair breakdown, best and worst individual trades, and average hold duration |
| FR-96 | All report query functions MUST use a `@_safe` decorator that catches all exceptions and returns an empty result — **report errors MUST never propagate to the CLI layer** |

### 5.14 Claude Code Skills

| ID | Requirement |
|---|---|
| FR-97 | The project MUST ship an `/add-pair` Claude Code skill (`.claude/skills/add-pair/SKILL.md`) guiding the developer through all file changes required to onboard a new trading pair |
| FR-98 | The project MUST ship a `/commit` Claude Code skill (`.claude/skills/commit/SKILL.md`) that stages only safe source files, derives a conventional commit message from the diff, and pushes to GitHub — never staging secrets, databases, or runtime logs |
| FR-99 | The project MUST ship a `/trading-rules` Claude Code skill (`.claude/skills/trading-rules/SKILL.md`) that serves as the single source of truth for all LLM trading constraints and is injected into the system prompt at startup |

---

## 6. Non-Functional Requirements

| ID | Requirement |
|---|---|
| NFR-01 | **Privacy** — All AI inference MUST run locally (Ollama). No market data or portfolio data MUST be transmitted to external AI services |
| NFR-02 | **Availability** — The agent MUST recover automatically from WebSocket disconnections within 60 seconds using exponential backoff |
| NFR-03 | **Reliability** — A failure in any single pair's analysis MUST NOT halt the agent; errors MUST be caught, logged, and the cycle MUST continue |
| NFR-04 | **Auditability** — Every decision MUST be traceable from cycle timestamp to final fill via the audit database foreign-key chain |
| NFR-05 | **Determinism** — Risk rule enforcement is deterministic Python; the same portfolio state and signals MUST always produce the same risk outcome regardless of LLM output |
| NFR-06 | **Crash resilience (live mode)** — Stop-loss and take-profit orders placed on Kraken servers MUST survive application crashes or network outages |
| NFR-07 | **Configurability** — All trading parameters (SL%, TP%, cycle interval, pair list, indicator periods, signal scoring weights, candle buffer size, LLM timeout, WebSocket ping/backoff, log rotation settings, min profit floor, kill switch threshold, circuit breaker config, trading hours) MUST be adjustable via `config.yaml` without code changes |
| NFR-08 | **Security** — API credentials MUST be stored in `.env` only, never in source code or committed to version control |
| NFR-09 | **Observability** — The agent MUST write structured logs to both stdout and `logs/agent.log`; every method in the decision flow MUST emit a timing log entry; 15-minute healthchecks.io pings provide external uptime monitoring |
| NFR-10 | **Performance** — Each 30-minute decision cycle MUST complete within the cycle window; LLM calls have a configurable timeout (default 600 seconds) |
| NFR-11 | **CLI usability** — The CLI MUST be operable by a non-technical user through natural language; keyword fallback MUST require no additional configuration |
| NFR-12 | **Exchange precision** — All order quantities and prices MUST be formatted using CCXT `amount_to_precision()` / `price_to_precision()` to prevent dust/increment errors on Kraken |

---

## 7. Business Rules

| ID | Rule |
|---|---|
| BR-01 | The agent MUST NOT trade if the daily loss limit (10%) has been reached, even if the LLM proposes a buy |
| BR-02 | The agent MUST NOT open a position if doing so would reduce available cash below 10% of portfolio |
| BR-03 | The agent MUST NOT open a 4th position if 3 are already open |
| BR-04 | The stop-loss percentage defaults to 5% and is configurable only via `config.yaml`; it MUST NOT be overridable by the LLM at runtime |
| BR-05 | Take-profit values MUST come from the whitelist `[5, 8, 12, 16, 20]`; any other value prevents startup |
| BR-06 | Proposed trade amounts exceeding 30% of portfolio MUST be silently capped (not rejected) to enable partial execution |
| BR-07 | Live trading MUST NOT begin without the product owner reviewing paper trading results and confirming readiness |
| BR-08 | The LLM MUST NOT be given the ability to modify risk parameters, cancel stop-loss orders, or override any risk rule |
| BR-09 | The system MUST NOT execute a buy order outside the 16:00–20:00 UTC trading window |
| BR-10 | The system MUST NOT execute a buy if the current candle volume is below 50% of the 20-period Volume SMA |
| BR-11 | The system MUST NOT execute a sell if the estimated net P&L is below the Minimum Profit Floor of 1.0% |
| BR-12 | If the Global Kill Switch fires (−7% daily drawdown), all open positions MUST be market-sold before the agent halts |
| BR-13 | The Circuit Breaker MUST pause all buying for 4 hours after 3 consecutive stop-loss exits within any rolling 4-hour window |
| BR-14 | In a bearish market regime, the agent's per-trade position maximum MUST be scaled to 50% of the normal maximum before the LLM cycle starts |
| BR-15 | No trade MUST use more than 98% of available cash; the minimum order value is $5 USD |

---

## 8. Per-Pair Configuration

| Pair | Take-Profit | Stop-Loss | Rationale |
|---|---|---|---|
| BTC/USD | 8% | 5% | Most mature asset; large swings are less frequent; conservative target is appropriate |
| ETH/USD | 12% | 5% | Moderate volatility; 12% balances realism with profitability |
| BNB/USD | 12% | 5% | Similar volatility profile to ETH |
| SOL/USD | 16% | 5% | High volatility; larger price swings make a 16% TP achievable |
| XRP/USD | 12% | 5% | News-driven spikes common; RSI rarely drops below 30 on 15-min candles |
| TRX/USD | 12% | 5% | Mid-tier altcoin with moderate, ETH-like volatility |
| DOGE/USD | 20% | 5% | Meme-driven asset; can swing 20–30% in hours; high TP justified |
| ADA/USD | 12% | 5% | Moderate volatility, comparable to ETH |
| LTC/USD | 8% | 5% | Follows BTC moves; conservative target appropriate given lower volatility relative to altcoins |
| RAILS/USD | 20% | 5% | High-volatility asset; meme-driven swings of 20–30% achievable |
| AVAX/USD | 12% | 5% | Moderate-to-high volatility; L1 competitor with regular 10–15% ranges |
| SUI/USD | 16% | 5% | Newer L1 with high volatility; 16% reflects realistic swing range |
| HYPE/USD | 20% | 5% | Emerging asset with extreme volatility; 20% TP reflects outsized swing potential |
| UNI/USD | 12% | 5% | DeFi governance token; moderate volatility comparable to mid-cap alts |
| INJ/USD | 16% | 5% | High-growth DeFi L1; frequent 15–20% swings along trend changes |
| WIF/USD | 20% | 5% | Solana-ecosystem memecoin; DOGE-tier meme volatility; strong SOL-correlation momentum cycles |
| TON/USD | 16% | 5% | Toncoin (Telegram blockchain); news-driven momentum spikes from 900M-user base; clean RSI cycles |
| OP/USD | 16% | 5% | Optimism L2; amplified ETH recovery cycles; airdrop-driven volume spikes |
| ARB/USD | 16% | 5% | Arbitrum L2 (largest ETH L2 by TVL); high absolute volume; clear technical ranges |
| JUP/USD | 20% | 5% | Jupiter DEX aggregator (Solana); high-beta SOL; recurring Jupuary airdrop volume spikes |
| PEPE/USD | 20% | 5% | PEPE memecoin (2nd largest meme); extreme volatility; highest buy_min_score (8) — quality-only entries |
| TIA/USD | 20% | 5% | Celestia modular blockchain; institutional modular thesis; volatile with ecosystem announcements |
| RENDER/USD | 16% | 5% | Render Network (decentralised GPU compute); AI narrative tailwind; Solana-migrated |
| FET/USD | 16% | 5% | Fetch.ai / ASI Alliance (AI agent infrastructure); AI+DeFi convergence; large merged token |
| STX/USD | 16% | 5% | Stacks Bitcoin L2; amplified BTC cycles; sBTC backed by 1:1 BTC; 5+ years price history |
| PENDLE/USD | 20% | 5% | Pendle Finance DeFi yield protocol; expiry-driven BB squeeze breakouts; ETH ecosystem |
| ONDO/USD | 16% | 5% | Ondo Finance RWA tokenisation; TradFi institutional narrative; steady trending profile |
| BONK/USD | 25% | 5% | Solana memecoin; extreme parabolic spikes with SOL bull runs; buy_min_score=9 maximum gate |
| MOVR/USD | 20% | 5% | Moonriver (Moonbeam/Polkadot parachain); high-vol speculative alt; buy_min_score=6; caution=0.40 |

All dynamic TP values (when `dynamic_tp.enabled: true`) are computed as `Entry + (k × ATR)` and logged as `[DYNAMIC_TP]`. If the ATR-adjusted TP would be below the 1.0% profit floor, the pair is vetoed from buying.

---

## 9. Acceptance Criteria

### Paper Trading Phase

The paper trading phase is considered successful and the agent is **READY FOR LIVE TRADING** if ALL of the following are met after a minimum 14-day run:

| Criterion | Threshold |
|---|---|
| Win rate (profitable closed trades / total closed trades) | ≥ 50% |
| Maximum drawdown (largest peak-to-trough loss) | < 15% |
| Total P&L over review period | > 0 (net positive) |
| Number of closed trades | ≥ 10 (sufficient sample size) |
| Circuit breaker activations | < 3 (indicates strategy is not repeatedly hitting stop-losses) |

If any criterion is not met, paper trading MUST be extended and root causes reviewed using `scripts/audit_rejections.py`.

### Live Trading Phase

Live trading is authorised only after:

1. Product owner has reviewed the paper trading report (`scripts/review.py` output)
2. `scripts/review.py` has output a **READY FOR LIVE TRADING** verdict
3. Kraken API keys have been configured in `.env`
4. healthchecks.io webhook URL has been configured in `config.yaml`
5. Product owner has confirmed they understand real money is at risk

---

## 10. Constraints

| ID | Constraint |
|---|---|
| C-01 | The system MUST run on macOS (development and production environment) |
| C-02 | The LLM MUST run locally via Ollama; cloud-hosted models are not permitted |
| C-03 | The exchange MUST be Kraken; other exchanges are not in scope |
| C-04 | The implementation language MUST be Python 3.11+ |
| C-05 | All persistent storage MUST use SQLite; no external database server is required |
| C-06 | The initial live investment amount is at the discretion of the product owner; the system enforces percentage-based limits relative to whatever balance is present |
| C-07 | All exchange order formatting MUST use CCXT precision helpers; raw float arithmetic MUST NOT be passed directly to Kraken API |

---

## 11. Assumptions

| ID | Assumption |
|---|---|
| A-01 | The product owner will install Ollama (or configure a cloud LLM endpoint) and ensure the model set in `config.yaml → llm.model` supports function/tool calling before running the agent |
| A-02 | The product owner has or will create a Kraken account with Spot trading enabled |
| A-03 | Telegram bot setup is optional; the agent operates correctly without it |
| A-04 | The machine running the agent has a stable internet connection for the Kraken WebSocket feed and REST API |
| A-05 | BNB/USD is available as a trading pair on Kraken (or will be substituted with the nearest equivalent) |
| A-06 | The product owner will not manually cancel Kraken stop-loss orders while the agent is running |
| A-07 | The healthchecks.io webhook URL is configured in `config.yaml`; if absent, the graceful degradation skips the ping without crashing |
| A-08 | The backtesting pipeline uses pre-recorded candle JSON files from the `history/` directory and does not call live exchange APIs |

---

## 12. Risks

| ID | Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| R-01 | LLM hallucinates an invalid trade amount | Medium | High | Risk manager silently caps all amounts to 30% of portfolio; LLM cannot bypass this |
| R-02 | Stop-loss fires repeatedly before TP is reached | High | Medium | Circuit breaker pauses buying after 3 consecutive SL exits within 4 hours; conservative per-pair TP levels |
| R-03 | Kraken connection drops during a live trade | Low | High | Native server-side SL/TP orders persist independently of the Python process |
| R-04 | Ollama model is unavailable or slow | Low | Medium | Configurable timeout; automatic fallback model; defaults to HOLD on timeout |
| R-05 | Paper trading results do not reflect live performance due to slippage differences | Medium | Medium | Entry slippage (0.05%), Maker fee (0.16% entry, 0.26% exit) simulated; review threshold requires ≥ 10 trades |
| R-06 | Time-of-Day filter blocks all backtested pairs if system clock is used | Low | High | Fixed: `validate_buy()` evaluates the historical `candle_timestamp`, not `datetime.now()` |
| R-07 | Daily drawdown breaches kill switch before strategy can recover | Low | Medium | Kill switch at −7% allows some recovery room before the −10% daily loss limit triggers a full halt |
| R-08 | ATR-derived TP falls below profit floor on low-volatility pairs | Medium | Low | Hard veto in signal scoring: pair is skipped for buying until ATR recovers; logged as a rejection |
| R-09 | Limit order never fills, leaving cash idle | Medium | Low | 60-second limit chase loop re-submits at updated best ask; if still unfilled, cycle ends and next cycle retries |
| R-10 | Exchange returns dust/increment error on small orders | Low | Medium | CCXT `amount_to_precision()` / `price_to_precision()` applied before every API call; $5 minimum guard |

---

## 13. Glossary

| Term | Definition |
|---|---|
| ATR | Average True Range — a measure of market volatility computed over 14 candles; used for dynamic position sizing and TP targets |
| Bollinger Bands | A volatility indicator showing upper and lower price bands around a 20-period moving average |
| Caution Factor | A 0.5× multiplier applied to the per-trade size cap in bearish regimes, enforced in `main.py` before the LLM cycle |
| Circuit Breaker | A 4-hour trading pause triggered when 3 consecutive trades within any 4-hour window close at stop-loss |
| CLI | Command-Line Interface — the `kryptos.py` entry point providing REPL and subcommand modes |
| Confluence Score | The additive buy signal score (0–10) across EMA, MACD, RSI, OBI, and Fear & Greed contributors; minimum 5 required to buy |
| Dynamic TP | An ATR-adjusted take-profit target computed at order entry time: `Entry + (k × ATR)`, overriding the static pair configuration |
| EMA | Exponential Moving Average — a trend-following indicator weighting recent prices more heavily; used at periods 9 (micro), 21 (short), and 50 (macro) |
| Fat Finger Guard | A safety check preventing trades that would use more than 98% of available cash, and blocking orders below $5 USD |
| Fear & Greed Index | A market sentiment score (0–100) from `alternative.me`; extreme fear (≤ 25) and fear (≤ 40) add signal score points |
| Global Kill Switch | An emergency liquidation trigger that fires when daily portfolio drawdown reaches −7%, market-sells all positions, and halts trading |
| Hold | A decision by the agent to take no action on a pair for the current cycle |
| LLM | Large Language Model — any model with function/tool-calling support (configurable via `config.yaml → llm.model`, e.g. `qwen2.5:7b` or Gemini) that makes trading judgements |
| Maker | An exchange order type (limit / post-only) that adds liquidity to the order book and qualifies for lower Kraken fees |
| MACD | Moving Average Convergence Divergence — a momentum indicator (12/26/9); the histogram turn from negative to positive is the strongest BUY signal |
| Minimum Profit Floor | A 1.0% net P&L gate below which `propose_sell` is rejected to ensure fees and slippage are fully covered |
| OBI | Order Book Imbalance — `(BidVol − AskVol) / (BidVol + AskVol)`; positive OBI (more buy pressure than sell pressure) contributes +1 to the confluence score |
| Paper Trading | Simulated trading using virtual money to validate strategy without financial risk |
| PID File | Process ID file at `data/kryptos.pid` used by the CLI to track the running agent process |
| Post-Only | Limit order flag (`postOnly: True`) that causes the order to be rejected by the exchange if it would immediately match (cross the spread), guaranteeing Maker fee treatment |
| REPL | Read-Eval-Print Loop — the interactive CLI mode activated by running `python kryptos.py` with no arguments |
| RSI | Relative Strength Index — measures whether an asset is overbought (≥ 70, hard veto) or oversold (lower values add confluence score) |
| SL | Stop-loss — an automatic order to close a position at a fixed loss threshold (5% below entry) |
| TP | Take-profit — an automatic order to close a position at a fixed gain threshold (pair-specific, 8–20%) |
| Volume Dead Zone | A condition where current 15-minute volume is below 50% of the 20-period Volume SMA; blocks all buys to avoid low-liquidity fakeouts |
