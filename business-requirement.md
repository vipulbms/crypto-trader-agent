# Business Requirements Document
## Kryptos — AI Crypto Trading Agent

| Field | Value |
|---|---|
| Document version | 1.2 |
| Date | 28 March 2026 |
| Author | Vipul Sanghrajka |
| Status | Approved — implementation complete |

| Revision | Change summary |
|---|---|
| 1.0 | Initial release — trading agent, paper/live mode, audit trail, reporting scripts |
| 1.1 | Added: Kryptos CLI (NL REPL + direct subcommands), Reports module (9 query functions), NL intent parser with Ollama + keyword fallback, agent process manager, Rich terminal display layer |
| 1.2 | Changed candle interval from 1-min to 15-min; expanded pair list from 4 to 9 pairs (added XRP, TRX, DOGE, ADA, LTC); updated indicator parameters (BB period 50, EMA slow 200, RSI thresholds 30/60); added BB band-squeeze guard; all parameters externalised to config.yaml; added SGT timezone throughout; added rotating log files (100 MB, 4 backups); added per-method performance timing; expanded config.yaml with `signals:`, `exchange:`, and new `indicators:` keys |
| 1.3 | Added RAILS/USD as 10th trading pair (TP 20%, SL 5%); added RAILS to WebSocket PAIR_MAP and REST_PAIR_MAP; added `/add-pair` Claude Code skill for onboarding new pairs |

---

## 1. Executive Summary

The product owner requires an autonomous AI-driven trading agent that monitors the cryptocurrency market and executes trades on their behalf via the Kraken exchange. The product owner is new to cryptocurrency trading and requires the system to act conservatively, prioritising capital protection above profit maximisation.

The agent must operate continuously, make data-driven decisions using a locally-hosted AI model, and maintain a complete audit trail of every decision — including decisions not to trade. A paper trading mode must allow safe validation of the agent's behaviour over a two-week period before any real money is committed.

---

## 2. Business Objectives

| ID | Objective |
|---|---|
| BO-01 | Automate cryptocurrency trading without requiring the product owner to monitor markets manually |
| BO-02 | Protect invested capital as the primary goal; profit generation is secondary |
| BO-03 | Validate the agent's behaviour risk-free over a two-week paper trading period before live deployment |
| BO-04 | Provide full transparency into every decision the agent makes, including reasoning |
| BO-05 | Keep all AI inference local to avoid sending financial data to third-party AI providers |
| BO-06 | Enable the product owner to receive real-time alerts about significant trading events |

---

## 3. Stakeholders

| Role | Responsibility |
|---|---|
| Product Owner | Defines requirements; receives trade alerts; reviews paper trading results; authorises live deployment |
| Trading Agent (AI) | Monitors markets, proposes trades, holds positions |
| Risk Manager (system) | Deterministically enforces all capital protection rules — overrides the AI if limits are exceeded |
| Kraken Exchange | Executes live orders; provides real-time market price feed |

---

## 4. Scope

### 4.1 In Scope

- Automated monitoring and trading of ten cryptocurrency pairs: **BTC/USD, ETH/USD, BNB/USD, SOL/USD, XRP/USD, TRX/USD, DOGE/USD, ADA/USD, LTC/USD, RAILS/USD**
- Technical analysis of market data (RSI, MACD, Bollinger Bands, EMA, ATR)
- AI-assisted buy, sell, and hold decisions using a locally hosted LLM
- Deterministic risk management layer that cannot be overridden by the AI
- Paper trading simulation mode with a virtual USD 1,000 balance
- Live trading mode via Kraken exchange
- SQLite audit database recording every decision and its full reasoning chain
- Telegram notifications for trade events and daily summaries
- Daily reporting and a two-week paper trading review with a readiness verdict
- **Natural-language CLI (`kryptos.py`)** for managing the agent and querying reports
- **Reports module** querying trade history, LLM decisions, performance metrics, and open positions
- **Agent process management** (start / stop / status / schedule) from the CLI

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
| FR-01 | The system MUST monitor the following pairs: BTC/USD, ETH/USD, BNB/USD, SOL/USD, XRP/USD, TRX/USD, DOGE/USD, ADA/USD, LTC/USD, RAILS/USD |
| FR-02 | The system MUST receive real-time price data from the Kraken public WebSocket feed (`wss://ws.kraken.com/v2`) |
| FR-03 | The system MUST back-fill historical OHLCV candles from the Kraken public REST API on startup |
| FR-04 | The system MUST maintain a rolling buffer of **300 fifteen-minute candles** (75 hours of history) per pair |
| FR-05 | The system MUST automatically reconnect to the WebSocket feed if the connection is lost, using exponential backoff up to a configurable maximum |

### 5.2 Technical Analysis

| ID | Requirement |
|---|---|
| FR-06 | The system MUST compute RSI (period 14), MACD (12/26/9), Bollinger Bands (period 50, std 2), EMA-20, EMA-200, and ATR (period 14) per pair on 15-minute candles |
| FR-06a | Bollinger Band signals MUST be suppressed when band width is less than 0.5% of the current price (band-squeeze guard) to prevent contradictory simultaneous buy/sell signals |
| FR-07 | The system MUST require a minimum of **220 candles** per pair before generating any signal, to ensure all indicators (especially EMA-200) have sufficient warm-up data |
| FR-08 | The system MUST classify each pair as BUY, SELL, or HOLD using a **weighted point scoring system** configurable in `config.yaml` under `signals:` |
| FR-09 | BUY signals MUST require a configurable minimum score (default 4 pts) from: oversold RSI (< 30, +3 pts), bullish MACD histogram (+2 pts), MACD crossover (+1 pt), price near lower Bollinger Band (+3 pts), EMA uptrend (+1 pt) |
| FR-10 | SELL signals MUST require a configurable minimum score (default 3 pts) from: overbought RSI (> 60, +3 pts), bearish MACD histogram (+2 pts), price near upper Bollinger Band (+2 pts) |

### 5.3 AI Decision Making

| ID | Requirement |
|---|---|
| FR-11 | The system MUST use a locally hosted LLM (Ollama `qwen2.5:14b`) for final trade decisions |
| FR-12 | The LLM MUST receive a structured prompt each cycle containing portfolio state, per-pair indicators, signal direction, take-profit targets, and current holdings |
| FR-13 | The LLM MUST call exactly one tool per pair per cycle: `propose_buy`, `propose_sell`, or `hold` |
| FR-14 | Every `hold` decision MUST include a written reason from the LLM |
| FR-15 | The LLM MUST NOT perform risk arithmetic or enforce position limits — those are the risk manager's responsibility |
| FR-16 | If the primary LLM model fails, the system MUST fall back to `llama3.1:8b` and log the event |
| FR-17 | If no LLM response is received within the timeout, the system MUST default to `hold` for that pair |

### 5.4 Risk Management

| ID | Requirement |
|---|---|
| FR-18 | The system MUST enforce a fixed stop-loss of **5% below entry price** on every trade |
| FR-19 | The system MUST enforce configurable take-profit levels of **5%, 8%, 12%, or 16%, or 20%** per pair |
| FR-20 | Take-profit values not in the whitelist `[5, 8, 12, 16, 20]` MUST be rejected at startup with a clear error |
| FR-21 | No single trade MUST exceed **30% of the total portfolio value** |
| FR-22 | No more than **3 positions** MUST be open simultaneously across all pairs |
| FR-23 | The system MUST maintain a minimum **10% cash reserve** of total portfolio at all times |
| FR-24 | If daily losses exceed **10% of the start-of-day balance**, all new buys MUST be blocked for the remainder of that day |
| FR-25 | All risk rules MUST be enforced by deterministic Python code — never by the LLM |

### 5.5 Paper Trading Mode

| ID | Requirement |
|---|---|
| FR-26 | The system MUST support a `--paper` flag that activates paper trading mode |
| FR-27 | Paper trading MUST initialise with a virtual balance of **USD 1,000** on first run |
| FR-28 | Paper trading MUST NOT require Kraken API keys; the public price feed is sufficient |
| FR-29 | Paper trading MUST simulate a **0.05% slippage** on fills and a **0.26% fee** (Kraken maker rate) |
| FR-30 | Paper trading MUST monitor stop-loss and take-profit levels on every cycle tick and auto-close positions that are triggered |
| FR-31 | All paper trades MUST be stored in `paper_trading.db` with the same schema as live trades |

### 5.6 Live Trading Mode

| ID | Requirement |
|---|---|
| FR-32 | The system MUST support a `--live` flag that activates live trading mode |
| FR-33 | Live mode MUST authenticate with Kraken using `KRAKEN_API_KEY` and `KRAKEN_API_SECRET` from the environment |
| FR-34 | After every live entry, the system MUST immediately place **native stop-loss and take-profit orders on Kraken's servers** so they persist if the application crashes |
| FR-35 | Live trades MUST be stored in `live_trading.db` |

### 5.7 Audit Trail

| ID | Requirement |
|---|---|
| FR-36 | The system MUST record **every decision** (BUY, SELL, and HOLD) in `audit.db` — not just executed trades |
| FR-37 | The audit record MUST store the full LLM reasoning text (`raw_llm_output`) and a short summary (`reasoning_summary`) |
| FR-38 | HOLD decisions MUST record the LLM's stated reason in a dedicated `hold_reason` column |
| FR-39 | The audit trail MUST maintain a foreign-key chain: cycle → signal → LLM decision → risk check → order → fill → position event |
| FR-40 | The audit logger MUST NEVER raise an exception; all writes MUST be wrapped in try/except to prevent audit failures from disrupting trading |
| FR-41 | The audit database MUST be append-only; no records MUST be deleted or updated after creation |

### 5.8 Notifications

| ID | Requirement |
|---|---|
| FR-42 | The system MUST send Telegram alerts for: trade executed, stop-loss triggered, take-profit triggered, daily loss limit reached, agent started, and unhandled errors |
| FR-43 | All paper trading alerts MUST be prefixed with `[PAPER]` |
| FR-44 | If Telegram is not configured, the system MUST degrade gracefully to console logging — it MUST NOT crash |

### 5.9 Reporting

| ID | Requirement |
|---|---|
| FR-45 | A daily report script MUST output per-pair P&L, trade count, win rate, and decision breakdown (BUY/SELL/HOLD counts) |
| FR-46 | A two-week review script MUST compute win rate, max drawdown, total P&L, and per-pair performance |
| FR-47 | The two-week review MUST output a clear **READY FOR LIVE TRADING** or **NOT READY** verdict |
| FR-48 | The READY verdict MUST require: win rate ≥ 50%, max drawdown < 15%, total P&L > 0, and at least 10 trades executed |

### 5.10 Decision Cycle

| ID | Requirement |
|---|---|
| FR-49 | The agent MUST run a decision cycle every **15 minutes** |
| FR-50 | The agent MUST wait for at least **220 candles** per pair before running the first cycle (configurable via `indicators.min_candles_to_start`); a timeout (default 300 s) allows the agent to proceed if the buffer does not fill in time |
| FR-51 | One LLM call MUST be made per pair per cycle (10 calls per cycle total across all pairs) |
| FR-52 | Any exception in a single pair's cycle MUST be logged and the agent MUST continue processing the remaining pairs |
| FR-73 | The system MUST log execution time for every significant method in the decision flow using a `@timed` decorator; each log entry MUST include: cycle ID, class name, method name, key parameters, and elapsed milliseconds |
| FR-74 | All timestamps throughout the system (database writes, log entries, cycle prompts) MUST use **Singapore Standard Time (SGT, UTC+8)** |
| FR-75 | Agent logs MUST be written to `logs/agent.log` using a **rotating file handler**: maximum 100 MB per file, retaining 4 backup copies |
| FR-76 | The project MUST ship a **`/add-pair` Claude Code skill** (`.claude/skills/add-pair/SKILL.md`) that guides the developer through all file changes required to onboard a new trading pair: `config.yaml`, `websocket_feed.py` (PAIR_MAP + REST_PAIR_MAP), `kraken_client.py`, `display.py`, and all three documentation files |
| FR-77 | The project MUST ship a **`/commit` Claude Code skill** (`.claude/skills/commit/SKILL.md`) that stages only safe source files, derives a conventional commit message from the diff, and pushes to GitHub — never staging secrets, databases, or runtime logs |

### 5.11 CLI — Natural Language Interface

| ID | Requirement |
|---|---|
| FR-53 | The system MUST provide a CLI entry point (`kryptos.py`) as the primary user interface |
| FR-54 | The CLI MUST support three operating modes: **interactive REPL**, **single NL command**, and **direct subcommands** |
| FR-55 | The CLI MUST accept free-text natural-language input and classify it into one of **14 structured intents** |
| FR-56 | Intent classification MUST use the local Ollama model with `temperature=0.0` and a JSON-only response format |
| FR-57 | If Ollama is unavailable, the CLI MUST fall back automatically to **keyword-based intent matching** — the CLI MUST remain fully functional in this mode |
| FR-58 | The CLI MUST support the following direct subcommands: `start`, `stop`, `status`, `report`, `trades`, `decisions`, `metrics`, `summary`, `positions`, `log` |
| FR-59 | The `start` subcommand MUST accept `--paper` and `--live` flags and launch the agent as a **background process** |
| FR-60 | Agent process lifecycle MUST be managed using a **PID file** at `data/kryptos.pid` containing `{pid, mode, started_at}` |
| FR-61 | The `stop` command MUST send SIGTERM, wait up to 10 seconds, then send SIGKILL if the process has not exited |
| FR-62 | The CLI MUST display all output using a **Rich-based terminal UI** with the following color convention: green = BUY / positive / running; red = SELL / negative / stopped; yellow = HOLD / warnings; cyan = info headers; magenta = LLM reasoning text |
| FR-63 | The interactive REPL MUST maintain **command history** across sessions, stored at `data/.kryptos_history` |
| FR-64 | The CLI MUST inject the `--paper` / `--live` flag as the `default_mode` parameter into every intent object |

### 5.12 Reports Module

| ID | Requirement |
|---|---|
| FR-65 | The reports module MUST query data from `audit.db` and the relevant trading database (`paper_trading.db` or `live_trading.db`) depending on mode |
| FR-66 | Trade records MUST be enriched with the corresponding LLM decision using a **±5-minute time-window JOIN** on `audit_llm_decisions` |
| FR-67 | The `report` command MUST display: portfolio balance summary, recent closed trades table, and rolling performance metrics |
| FR-68 | The `decisions` command MUST display: per-pair BUY/SELL/HOLD decision matrix, top hold reasons, model usage statistics, and average LLM latency |
| FR-69 | The `metrics` command MUST display: overall win rate, total P&L, maximum drawdown, per-pair breakdown, best and worst individual trades, and average hold duration |
| FR-70 | The `trades` command MUST support an optional `--detailed` flag that prints the full LLM reasoning text alongside each trade |
| FR-71 | All report query functions MUST use a `@_safe` decorator that catches all exceptions and returns an empty result — **report errors MUST never propagate to the CLI layer** |
| FR-72 | The reports module MUST provide a `get_cycle_detail(cycle_id)` function that returns the full foreign-key chain: cycle → signals → LLM decisions → risk checks → orders → fills |

---

## 6. Non-Functional Requirements

| ID | Requirement |
|---|---|
| NFR-01 | **Privacy** — All AI inference MUST run locally (Ollama). No market data or portfolio data MUST be transmitted to external AI services |
| NFR-02 | **Availability** — The agent MUST recover automatically from WebSocket disconnections and restart within 60 seconds |
| NFR-03 | **Reliability** — A failure in any single pair's analysis MUST NOT halt the agent; errors MUST be caught, logged, and the cycle MUST continue |
| NFR-04 | **Auditability** — Every decision MUST be traceable from cycle timestamp to final fill via the audit database foreign-key chain |
| NFR-05 | **Determinism** — Risk rule enforcement is deterministic Python; the same portfolio state and signals MUST always produce the same risk outcome regardless of LLM output |
| NFR-06 | **Crash resilience (live mode)** — Stop-loss and take-profit orders placed on Kraken servers MUST survive application crashes or network outages |
| NFR-07 | **Configurability** — All trading parameters (SL%, TP%, cycle interval, pair list, indicator periods, signal scoring weights, BB squeeze threshold, candle buffer size, LLM timeout, WebSocket ping/backoff, log rotation settings) MUST be adjustable via `config.yaml` without code changes; the config is organised into sections: `trading`, `paper`, `indicators`, `signals`, `llm`, `risk`, `exchange`, `storage` |
| NFR-08 | **Security** — API credentials MUST be stored in `.env` only, never in source code or committed to version control |
| NFR-09 | **Observability** — The agent MUST write structured logs to both stdout and `logs/agent.log`; the log file MUST rotate at 100 MB with 4 backup copies; every method in the decision flow MUST emit a timing log entry |
| NFR-10 | **Performance** — Each decision cycle MUST complete within the 15-minute window; LLM calls have a 600-second timeout (configurable) |
| NFR-11 | **CLI usability** — The CLI MUST be operable by a non-technical user through natural language; it MUST work without any knowledge of subcommand syntax; keyword fallback MUST require no additional configuration |

---

## 7. Business Rules

| ID | Rule |
|---|---|
| BR-01 | The agent MUST NOT trade if the daily loss limit has been reached, even if the LLM proposes a buy |
| BR-02 | The agent MUST NOT open a position if doing so would reduce available cash below 10% of portfolio |
| BR-03 | The agent MUST NOT open a 4th position if 3 are already open |
| BR-04 | The stop-loss percentage defaults to 5% and is configurable only via `config.yaml`; it MUST NOT be overridable by the LLM at runtime |
| BR-05 | Take-profit values MUST come from the whitelist `[5, 8, 12, 16, 20]`; any other value prevents startup |
| BR-06 | Proposed trade amounts exceeding 30% of portfolio MUST be silently capped (not rejected) to enable partial execution |
| BR-07 | Live trading MUST NOT begin without a completed and reviewed two-week paper trading run |
| BR-08 | The LLM MUST NOT be given the ability to modify risk parameters, cancel stop-loss orders, or override any risk rule |

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
| LTC/USD | 12% | 5% | Follows BTC moves with roughly 1.5–2× amplification |
| RAILS/USD | 20% | 5% | High-volatility asset; meme-driven swings of 20–30% achievable |

---

## 9. Acceptance Criteria

### Paper Trading Phase (2 weeks)

The paper trading phase is considered successful and the agent is **READY FOR LIVE TRADING** if ALL of the following are met after 14 days:

| Criterion | Threshold |
|---|---|
| Win rate (profitable closed trades / total closed trades) | ≥ 50% |
| Maximum drawdown (largest peak-to-trough loss) | < 15% |
| Total P&L over 14 days | > 0 (net positive) |
| Number of closed trades | ≥ 10 (sufficient sample size) |

If any criterion is not met, paper trading MUST be extended and root causes reviewed.

### Live Trading Phase

Live trading is authorised only after:

1. Product owner has reviewed the two-week paper trading report
2. `scripts/review.py` has output a `READY FOR LIVE TRADING` verdict
3. Kraken API keys have been configured in `.env`
4. Product owner has confirmed they understand real money is at risk

---

## 10. Constraints

| ID | Constraint |
|---|---|
| C-01 | The system MUST run on macOS (development and production environment) |
| C-02 | The LLM MUST run locally via Ollama; cloud-hosted models are not permitted |
| C-03 | The exchange MUST be Kraken; other exchanges are not in scope |
| C-04 | The implementation language MUST be Python 3 |
| C-05 | All persistent storage MUST use SQLite; no external database server is required |
| C-06 | The initial live investment amount is at the discretion of the product owner; the system enforces percentage-based limits relative to whatever balance is present |

---

## 11. Assumptions

| ID | Assumption |
|---|---|
| A-01 | The product owner will install Ollama and pull `qwen2.5:14b` before running the agent |
| A-02 | The product owner has or will create a Kraken account with Spot trading enabled |
| A-03 | Telegram bot setup is optional; the agent operates correctly without it |
| A-04 | The machine running the agent has a stable internet connection for the Kraken price feed |
| A-05 | BNB/USD is available as a trading pair on Kraken (or will be substituted with the nearest equivalent, e.g. BNB/USDT) |
| A-06 | The product owner will not manually cancel Kraken stop-loss orders while the agent is running |

---

## 12. Risks

| ID | Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| R-01 | LLM hallucinates an invalid trade amount | Medium | High | Risk manager caps all amounts to 30%; LLM cannot bypass this |
| R-02 | Stop-loss fires repeatedly before TP is reached | High | Medium | Conservative per-pair TP levels (8–16%) aligned with realistic daily ranges |
| R-03 | Kraken connection drops during a live trade | Low | High | Native server-side SL/TP orders persist independently of the Python process |
| R-04 | Ollama model is unavailable or slow | Low | Medium | 60-second timeout; automatic fallback to `llama3.1:8b`; defaults to HOLD |
| R-05 | Paper trading results do not reflect live performance due to slippage differences | Medium | Medium | Slippage (0.05%) and fees (0.26%) are simulated; review threshold requires ≥10 trades |
| R-06 | BNB/USD may have low liquidity on Kraken | Low | Low | Isolated to one pair; other pairs continue trading unaffected |

---

## 13. Glossary

| Term | Definition |
|---|---|
| ATR | Average True Range — a measure of market volatility |
| Bollinger Bands | A volatility indicator showing upper and lower price bands around a moving average |
| CLI | Command-Line Interface — the `kryptos.py` entry point providing REPL and subcommand modes |
| EMA | Exponential Moving Average — a trend-following indicator that weights recent prices more heavily |
| Hold | A decision by the agent to take no action on a pair for the current cycle |
| Intent | A classified user action (e.g. `view_report`, `start_agent`) extracted from a natural-language command by `NLParser` |
| LLM | Large Language Model — the AI model (`qwen2.5:14b`) that makes trading judgements and powers the CLI NL parser |
| MACD | Moving Average Convergence Divergence — a momentum indicator |
| NL / NLParser | Natural Language / the `NLParser` class that converts free-text input to a structured intent + params object |
| Paper trading | Simulated trading using virtual money to validate strategy without financial risk |
| PID file | Process ID file at `data/kryptos.pid` used by the CLI to track the running agent process |
| REPL | Read-Eval-Print Loop — the interactive CLI mode activated by running `python kryptos.py` with no arguments |
| RSI | Relative Strength Index — measures whether an asset is overbought or oversold |
| SL | Stop-loss — an automatic order to close a position at a fixed loss threshold |
| TP | Take-profit — an automatic order to close a position at a fixed gain threshold |
