# Kryptos — AI Crypto Trading Agent
## Plan & Design

## 1. Goals

Build a local AI agent that autonomously trades cryptocurrency on Kraken, with the following constraints:

| Constraint | Value |
|---|---|
| Stop-loss (fixed) | 5% below entry |
| Take-profit (configurable) | 5 / 8 / 12 / 16 / 20% per pair |
| Max allocation per trade | 30% of portfolio |
| Max open positions | 3 across all pairs |
| Daily loss limit | 10% of starting balance |
| Minimum cash reserve | 10% of portfolio |
| Pairs | BTC/USD · ETH/USD · BNB/USD · SOL/USD |
| Decision cycle | Every 15 minutes |
| Paper mode balance | $1,000 virtual USD |

Capital preservation is the primary objective. The agent must HOLD more than it trades.

---

## 2. Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                       main.py                               │
│   ┌──────────┐   ┌──────────────┐   ┌──────────────────┐   │
│   │  config  │   │  WebSocket   │   │   Decision Loop  │   │
│   │  .yaml   │──▶│  Feed        │──▶│  (every 15 min)  │   │
│   └──────────┘   │  (public,    │   └────────┬─────────┘   │
│                  │  no auth)    │            │              │
│                  └──────────────┘            ▼              │
│                                    ┌──────────────────┐     │
│                                    │  indicators.py   │     │
│                                    │  RSI · MACD · BB │     │
│                                    │  EMA · ATR       │     │
│                                    └────────┬─────────┘     │
│                                             │               │
│                                    ┌────────▼─────────┐     │
│                                    │  signals.py      │     │
│                                    │  BUY/SELL/HOLD   │     │
│                                    │  + strength 0–1  │     │
│                                    └────────┬─────────┘     │
│                                             │               │
│                                    ┌────────▼─────────┐     │
│                                    │  TradingAgent    │     │
│                                    │  (Ollama LLM)    │     │
│                                    │  qwen2.5:7b      │     │
│                                    └────────┬─────────┘     │
│                                             │               │
│                           ┌────────────────▼────────────┐  │
│                           │      TradingTools           │  │
│                           │  propose_buy / propose_sell │  │
│                           │  hold                       │  │
│                           └────────┬────────────────────┘  │
│                                    │                        │
│                   ┌────────────────▼──────────────┐        │
│                   │       RiskManager             │        │
│                   │  Hard-coded Python rules       │        │
│                   │  LLM never enforces limits     │        │
│                   └────────┬──────────────────────┘        │
│                            │                               │
│          ┌─────────────────▼──────────────┐               │
│          │   PaperBroker / KrakenClient   │               │
│          │   (injected at startup)        │               │
│          └─────────────────┬──────────────┘               │
│                            │                               │
│      ┌─────────────────────▼──────────────────────┐       │
│      │          SQLite databases (data/)           │       │
│      │  paper_trading.db  live_trading.db          │       │
│      │  audit.db                                   │       │
│      └─────────────────────────────────────────────┘       │
└─────────────────────────────────────────────────────────────┘
```

### CLI Layer (`kryptos.py`)

A separate entry point gives the product owner a natural-language interface to the agent, its databases, and its process lifecycle — without touching `main.py`.

```
┌──────────────────────────────────────────────────────────────────────┐
│                  kryptos.py  (CLI / REPL entry point)               │
│  ┌──────────────────────────┐   ┌────────────────────────────────┐  │
│  │  Interactive REPL        │   │  Direct Subcommands            │  │
│  │  python kryptos.py       │   │  start · stop · status         │  │
│  │  > show last 5 BTC trades│   │  report · trades · decisions   │  │
│  │  > why did it hold ETH?  │   │  metrics · summary             │  │
│  └────────────┬─────────────┘   │  positions · log               │  │
│               │                 └─────────────────┬──────────────┘  │
│               ▼                                   │                 │
│  ┌──────────────────────────┐                    │                 │
│  │   NLParser               │◀───────────────────┘                 │
│  │   Ollama → intent JSON   │  temperature=0, 14 intents           │
│  │   keyword fallback       │  (works offline)                     │
│  └────────────┬─────────────┘                                      │
│               │  {intent, params, source}                          │
│               ▼                                                    │
│  ┌──────────────────────────┐   ┌────────────────────────────────┐ │
│  │  commands.dispatch()     │──▶│  agent_manager.py              │ │
│  └────────────┬─────────────┘   │  start / stop / status / log   │ │
│               │                 └────────────────────────────────┘ │
│               ▼                                                    │
│  ┌──────────────────────────┐   ┌────────────────────────────────┐ │
│  │  trade_report.py         │──▶│  display.py  (Rich)            │ │
│  │  9 query functions       │   │  tables · panels · color UI    │ │
│  └──────────────────────────┘   └────────────────────────────────┘ │
│       ↑ reads                                                      │
│  audit.db · paper_trading.db · live_trading.db · agent.log         │
└──────────────────────────────────────────────────────────────────────┘
```

---

## 3. Decision Cycle (every 15 minutes)

```
1. WebSocket feed delivers latest 1-min candles (buffer: 200 per pair)
2. compute_indicators()  — RSI, MACD, Bollinger Bands, EMA, ATR via pandas-ta
3. generate_signal()     — rule-based BUY/SELL/HOLD with strength score
4. build_cycle_prompt()  — inject portfolio state + all 4 pairs into LLM context
5. TradingAgent.run_cycle()
     └─ For each pair → Ollama LLM call with tool definitions
          └─ LLM returns tool call: propose_buy | propose_sell | hold
               └─ RiskManager.validate_buy() — approve / cap / reject
                    └─ PaperBroker / KrakenClient — execute order
6. AuditLogger records EVERY decision (including HOLD) to audit.db
7. Notifier sends Telegram alert
```

---

## 4. Source Files

```
crypto-trader-agent/
├── kryptos.py                       CLI entry point (REPL + NL + subcommands)
├── main.py                          Agent runner (background process)
├── config.yaml                      All tunable parameters
├── requirements.txt                 Python dependencies
├── .env                             API keys (never committed)
├── src/
│   ├── agent/
│   │   ├── prompts.py               SYSTEM_PROMPT + build_cycle_prompt()
│   │   ├── tools.py                 LLM-callable tools (propose_buy, propose_sell, hold)
│   │   └── trading_agent.py         TradingAgent — Ollama function calling per pair
│   ├── analysis/
│   │   ├── indicators.py            compute_indicators() — pandas-ta
│   │   └── signals.py               generate_signal() — BUY/SELL/HOLD scorer
│   ├── cli/
│   │   ├── agent_manager.py         PID-based start / stop / status / schedule / log
│   │   ├── commands.py              dispatch() — routes 12 intents to cmd_* functions
│   │   ├── display.py               Rich terminal output — 15+ print_* functions
│   │   └── nl_parser.py             Ollama NL→intent JSON + keyword fallback
│   ├── exchange/
│   │   ├── websocket_feed.py        Public Kraken WebSocket (no auth)
│   │   ├── kraken_client.py         Live order execution via ccxt
│   │   └── paper_broker.py          Paper order simulation with SL/TP monitoring
│   ├── notifications/
│   │   └── notifier.py              Telegram alerts ([PAPER] prefix in paper mode)
│   ├── reports/
│   │   └── trade_report.py          9 data query functions across all 3 databases
│   ├── risk/
│   │   └── risk_manager.py          RiskManager — deterministic Python, not LLM
│   └── storage/
│       ├── database.py              SQLite schema + init functions
│       └── audit_logger.py          Append-only audit trail
└── scripts/
    ├── daily_report.py              Daily P&L report per pair
    └── review.py                    2-week readiness review + READY verdict
```

---

## 5. LLM Setup

### Model

| Setting | Value |
|---|---|
| Primary | `qwen2.5:7b` — best tool/function calling in the 7B class |
| Fallback | `llama3.1:8b` — used if primary fails |
| Runtime | Ollama at `http://localhost:11434` |
| Temperature | `0.1` — conservative / deterministic |
| Framework | Ollama Python client with native function calling (`tools=` parameter) |

### Installation

```bash
brew install ollama
ollama serve                   # start the local server
ollama pull qwen2.5:7b        # ~5 GB download
```

---

## 6. LLM Prompts

### 6.1 System Prompt

Injected once when the agent is created. Static.

```
You are a conservative crypto trading agent managing a real investment portfolio
on Kraken exchange.

RULES (non-negotiable — enforced by the risk manager, not you):
- Never allocate more than 30% of the total portfolio to a single trade
- Stop-loss is always set at 5% below entry price — it is non-negotiable
- Take-profit targets are configured per pair (shown in each cycle prompt)
- Never open more than 3 positions at the same time across all pairs
- Always keep at least 10% of portfolio as cash reserve
- If daily losses exceed 10% of starting balance, do NOT trade — call hold()

YOUR ROLE:
- You receive a market summary and portfolio state every 15 minutes
- You monitor 4 pairs: BTC/USD, ETH/USD, BNB/USD, SOL/USD
- You have 3 tools: propose_buy, propose_sell, hold
- Your goal is capital PRESERVATION first, gains second
- You are a CONSERVATIVE agent — only trade on strong, clear signal confluence

SIGNAL INTERPRETATION:
- BUY only when ALL of: RSI < 35 (oversold) AND MACD bullish AND price near
  lower Bollinger Band
- SELL (close long) when: RSI > 65 OR MACD turning bearish OR you judge the
  trade is at risk
- When in doubt, call hold() — doing nothing is always valid and often correct

MANDATORY TOOL CALLING:
- You MUST call exactly one tool per pair per cycle: propose_buy, propose_sell,
  or hold
- Calling hold() requires a reason string — e.g. hold("RSI neutral at 52,
  signals mixed")
- Never skip calling a tool — every decision is audited
- Explain your reasoning in 2-3 sentences BEFORE calling the tool
```

**Source:** [src/agent/prompts.py](src/agent/prompts.py)

---

### 6.2 Cycle Prompt

Built dynamically every 15 minutes by `build_cycle_prompt()`. Injected as the user message. One LLM call is made per pair.

```
=== CYCLE: 2026-03-28T14:00:00 UTC [PAPER TRADING — virtual money] ===

--- PORTFOLIO STATE ---
Total Balance:        $1000.00
Available Cash:       $1000.00
Open Positions:       0
Daily P&L:            $+0.00 (+0.00%)
Max per new trade:    $300.00  (30% of $1000.00)

--- TAKE-PROFIT TARGETS ---
  BTC/USD: +8% above entry | Stop-loss: -5%
  ETH/USD: +12% above entry | Stop-loss: -5%
  BNB/USD: +12% above entry | Stop-loss: -5%
  SOL/USD: +16% above entry | Stop-loss: -5%

--- BTC/USD ---
Price:         $82345.1200
RSI(14):       32.4
MACD Hist:     -12.3400
BB Lower/Upper: $80100.00 / $86000.00
ATR(14):       420.1200
Signal:        BUY  (strength: 0.72)
Reasons:       RSI oversold, price near lower BB, MACD histogram negative but
               flattening

--- ETH/USD ---
Price:         $1950.2200
RSI(14):       55.1
MACD Hist:     3.1100
BB Lower/Upper: $1820.00 / $2100.00
ATR(14):       45.2200
Signal:        HOLD  (strength: 0.31)
Reasons:       RSI neutral, price mid-range

--- BNB/USD ---
...

--- SOL/USD ---
...

--- INSTRUCTIONS ---
Review the signals above for each pair.
For EACH pair, call ONE tool: propose_buy, propose_sell, or hold.
Always explain your reasoning briefly before calling each tool.
Remember: when signals are not strongly aligned, hold() is the correct choice.
```

**Source:** `build_cycle_prompt()` in [src/agent/prompts.py](src/agent/prompts.py)

---

### 6.3 Tool Definitions (Function Calling Schema)

The LLM receives these JSON schemas via the `tools=` parameter on every call:

```json
[
  {
    "type": "function",
    "function": {
      "name": "propose_buy",
      "description": "Propose buying a crypto pair. Risk manager may cap or reject the amount.",
      "parameters": {
        "type": "object",
        "properties": {
          "pair":       { "type": "string", "description": "Trading pair e.g. 'BTC/USD'" },
          "usd_amount": { "type": "number", "description": "USD amount to invest" }
        },
        "required": ["pair", "usd_amount"]
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "propose_sell",
      "description": "Close an existing open position for a pair.",
      "parameters": {
        "type": "object",
        "properties": {
          "pair":   { "type": "string", "description": "Trading pair to sell" },
          "reason": { "type": "string", "description": "Reason for selling" }
        },
        "required": ["pair", "reason"]
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "hold",
      "description": "Take no action for a pair this cycle.",
      "parameters": {
        "type": "object",
        "properties": {
          "pair":   { "type": "string", "description": "Trading pair" },
          "reason": { "type": "string", "description": "Reason for holding" }
        },
        "required": ["pair", "reason"]
      }
    }
  }
]
```

**Source:** `_TOOL_DEFS` in [src/agent/trading_agent.py](src/agent/trading_agent.py)

---

### 6.4 CLI NL Parser System Prompt

Used by `NLParser` in `kryptos.py` to convert free-text input into a structured `{intent, params}` JSON object. Injected once; every user message is passed as the human turn with `temperature=0.0`.

```
You are an intent classifier for a crypto trading CLI called Kryptos.
Given a natural language command, return a single JSON object with:
  intent   — one of the 14 intents listed below
  params   — a dict of extracted parameters (use null for missing values)

INTENTS:
  start_agent     — start the trading agent (params: mode="paper"|"live")
  stop_agent      — stop the trading agent
  agent_status    — show running state, uptime, last cycle
  next_schedule   — when is the next decision cycle
  view_report     — portfolio summary + recent trades + performance
  trade_details   — detailed view of individual trades with LLM reasoning
                    (params: pair, days, count, detail="summary"|"detailed")
  llm_decisions   — why did the agent BUY/SELL/HOLD a pair
                    (params: pair, days, decision_type="BUY"|"SELL"|"HOLD")
  daily_summary   — summary of a specific day (params: date="YYYY-MM-DD")
  win_rate        — performance metrics and win rate (params: days)
  open_positions  — currently open positions
  tail_log        — last N lines of agent.log (params: lines=30)
  help            — list available commands
  exit            — quit the CLI

PARAMETER DEFAULTS (use null if not mentioned):
  mode: "paper", pair: null, days: null, count: null,
  date: null, decision_type: null, detail: "summary", lines: 30

RESPOND WITH VALID JSON ONLY — no prose, no markdown fences.
Example: {"intent": "trade_details", "params": {"pair": "BTC/USD", "days": 7}}
```

**Keyword fallback** activates automatically when Ollama is unavailable. It uses `any(kw in lower for kw in ...)` pattern matching across all 14 intents and regex extraction for pair, days, count, and decision_type. The CLI is fully functional without Ollama in keyword mode.

**Source:** `_SYSTEM_PROMPT` in [src/cli/nl_parser.py](src/cli/nl_parser.py)

---

## 7. Technical Indicators

Computed by `compute_indicators()` in [src/analysis/indicators.py](src/analysis/indicators.py) using `pandas-ta`. Requires at least 60 candles in the buffer.

| Indicator | Parameters | Used for |
|---|---|---|
| RSI | period=14 | Oversold/overbought detection |
| MACD | 12 / 26 / 9 | Momentum direction and histogram crossovers |
| Bollinger Bands | period=20, std=2 | Price range extremes |
| EMA fast | period=20 | Short-term trend |
| EMA slow | period=50 | Long-term trend |
| ATR | period=14 | Volatility; informs position sizing |

### Signal Scoring (BUY)

`generate_signal()` awards points out of 10:

| Condition | Points |
|---|---|
| RSI < 35 (oversold) | +3 |
| MACD histogram > 0 | +2 |
| MACD histogram crossover (neg→pos) | +1 |
| Price at or below lower Bollinger Band | +3 |
| EMA20 ≥ EMA50 (uptrend) | +1 |

- **BUY** requires score ≥ 4 AND buy score > sell score
- **SELL** requires sell score ≥ 3
- Otherwise: **HOLD**

**Source:** [src/analysis/signals.py](src/analysis/signals.py)

---

## 8. Risk Rules

All enforced by deterministic Python in [src/risk/risk_manager.py](src/risk/risk_manager.py). The LLM never does risk arithmetic.

| Rule | Value | Where enforced |
|---|---|---|
| Stop-loss | 5% below entry (fixed) | `validate_config()` startup check |
| Take-profit whitelist | 5, 8, 12, 16, 20% only | `validate_config()` startup check |
| Max position size | 30% of portfolio | `validate_buy()` — caps amount |
| Max open positions | 3 across all pairs | `validate_buy()` — rejects if full |
| Daily loss limit | 10% of start-of-day balance | `validate_buy()` — blocks all buys |
| Minimum cash reserve | 10% always available | `validate_buy()` — rejects if breached |

For live trading, stop-loss and take-profit orders are placed on Kraken's servers immediately after entry — they persist even if the app crashes.

---

## 9. Database Design

All databases stored in `data/` in the project root.

### `paper_trading.db` / `live_trading.db`

| Table | Purpose |
|---|---|
| `paper_wallet` | Current virtual cash balance |
| `paper_positions` | Open positions (entry price, SL, TP, volume) |
| `paper_trades` | Closed trades with full P&L |

### `audit.db` — Append-Only Audit Trail

Every HOLD, BUY, and SELL decision is recorded. The chain of foreign keys links cycle → signal → LLM decision → risk check → order → fill → position event.

| Table | Purpose |
|---|---|
| `audit_cycles` | One row per 15-min cycle (timestamp, mode, pairs active) |
| `audit_signals` | Technical signal per pair per cycle (RSI, MACD, BB values + direction) |
| `audit_llm_decisions` | LLM decision per pair: BUY/SELL/HOLD + `reasoning_summary` + `raw_llm_output` + `hold_reason` |
| `audit_risk_checks` | RiskManager verdict: approved/rejected + reason + capped amount |
| `audit_orders` | Order submitted to broker (pair, side, amount, price) |
| `audit_fills` | Actual fill (price, volume, fee, slippage) |
| `audit_position_events` | Position lifecycle events (OPENED, CLOSED, SL_HIT, TP_HIT) |
| `audit_balance_snapshots` | Portfolio snapshot at end of each cycle |
| `audit_errors` | Any exceptions caught during cycles |

**Source:** [src/storage/database.py](src/storage/database.py) · [src/storage/audit_logger.py](src/storage/audit_logger.py)

---

## 10. Paper vs Live Mode

| Aspect | Paper (`--paper`) | Live (`--live`) |
|---|---|---|
| Kraken private API | Not required | Required (API key + secret) |
| Order execution | `PaperBroker` (SQLite simulation) | `KrakenClient` (ccxt) |
| Price feed | Public Kraken WebSocket (real prices) | Same public WebSocket |
| Starting balance | $1,000 virtual | Actual Kraken balance |
| Stop/TP enforcement | `check_stops_and_tp()` called each cycle | Native Kraken stop/TP orders placed on server at entry |
| Slippage | 0.05% simulated | Real fills |
| Fee | 0.26% simulated (Kraken maker) | Real Kraken fees |
| Telegram alerts | `[PAPER]` prefix, FYI only | `[LIVE]` prefix |

---

## 11. Running the Agent

### Prerequisites

```bash
# 1. Install Ollama
brew install ollama
ollama serve                   # terminal 1 — keep running
ollama pull qwen2.5:7b        # ~5 GB

# 2. Activate virtual environment
cd /path/to/crypto-trader-agent
source .venv/bin/activate
```

### Paper trading (2-week simulation, no API keys needed)

```bash
python main.py --paper
```

Starts with $1,000 virtual balance. Connects to Kraken public WebSocket for real prices. Waits for 60 candles (~60 min) before the first decision cycle.

### Daily report

```bash
python scripts/daily_report.py --mode paper
```

### 2-week readiness review

```bash
python scripts/review.py --mode paper --days 14
```

Outputs a `READY FOR LIVE TRADING` verdict if:
- Win rate ≥ 50%
- Max drawdown < 15%
- Total P&L > 0
- At least 10 trades executed

### Live trading

```bash
# Fill in .env first:
# KRAKEN_API_KEY=...
# KRAKEN_API_SECRET=...
python main.py --live
```

### Kryptos CLI

The CLI wraps all of the above into a single entry point. It also manages the agent process lifecycle.

```bash
# Interactive REPL (recommended for daily use)
python kryptos.py              # defaults to --paper
python kryptos.py --live       # connects to live trading DB

# Single natural-language command
python kryptos.py "show last 5 BTC trades with reasoning"
python kryptos.py "why did it hold ETH this week?"
python kryptos.py "what is my win rate over the last 14 days?"

# Direct subcommands (no Ollama needed)
python kryptos.py start --paper          # launch agent as background process
python kryptos.py stop                   # SIGTERM → SIGKILL with 10s grace
python kryptos.py status                 # uptime, last cycle, running state
python kryptos.py report --days 7 --pair BTC/USD --detailed
python kryptos.py trades --days 14 --count 20
python kryptos.py decisions --pair ETH/USD --type HOLD --days 7
python kryptos.py metrics --days 30
python kryptos.py summary --date 2026-03-28
python kryptos.py positions
python kryptos.py log --lines 50
```

When started with `python kryptos.py start`, the agent runs as a separate process; output appends to `agent.log`. A PID file at `data/kryptos.pid` tracks the process.

---

## 12. Configuration Reference (`config.yaml`)

```yaml
trading:
  stop_loss_pct: 5                         # Fixed — do not change
  take_profit_pct: 8                       # Global fallback (must be in allowed list)
  allowed_take_profit_pcts: [5, 8, 12, 16, 20]
  max_position_pct: 30                     # Max % of portfolio per trade
  max_open_positions: 3                    # Across all pairs
  cycle_interval_minutes: 15

  pairs:
    - pair: BTC/USD;  take_profit_pct: 8   # Conservative — BTC moves slowly
    - pair: ETH/USD;  take_profit_pct: 12
    - pair: BNB/USD;  take_profit_pct: 12
    - pair: SOL/USD;  take_profit_pct: 16  # Volatile — can reach larger moves

paper:
  starting_balance_usd: 1000
  slippage_pct: 0.05
  require_kraken_private_api: false

indicators:
  rsi_period: 14;  rsi_oversold: 35;  rsi_overbought: 65
  macd_fast: 12;   macd_slow: 26;     macd_signal: 9
  bb_period: 20;   bb_std: 2
  ema_fast: 20;    ema_slow: 50;      atr_period: 14
  candle_buffer_size: 200             # 1-min candles kept per pair

llm:
  model: qwen2.5:7b
  fallback_model: llama3.1:8b
  base_url: http://localhost:11434
  timeout_seconds: 60

risk:
  daily_loss_limit_pct: 10            # Halt all buys if exceeded
  min_cash_reserve_pct: 10            # Always keep 10% as cash

storage:
  paper_db: paper_trading.db
  live_db: live_trading.db
  audit_db: audit.db
```

---

## 13. Environment Variables (`.env`)

```bash
# Kraken (live mode only — not needed for paper)
KRAKEN_API_KEY=your_key_here
KRAKEN_API_SECRET=your_secret_here

# Telegram (optional — agent runs fine without it)
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id

# Ollama (default shown — change if running on a different host)
OLLAMA_BASE_URL=http://localhost:11434
```

---

## 14. Key Design Decisions

**LLM is the judgment layer, not the enforcement layer.** The risk manager is pure deterministic Python. The LLM proposes; the rules decide. This prevents prompt injection or hallucinated amounts from bypassing limits.

**HOLD is a first-class decision.** Every HOLD is logged with a reason in `audit_llm_decisions.hold_reason`. The audit trail is complete regardless of whether the agent trades.

**Stop/TP in paper mode is polled, in live mode is server-side.** In paper mode `check_stops_and_tp()` is called each cycle. In live mode, Kraken holds the stop and take-profit orders server-side — they fire even if the Python process crashes.

**Public WebSocket always connects; private API only in live mode.** Paper mode uses real Kraken prices via `wss://ws.kraken.com/v2` with no authentication. Only order placement requires API keys.

**All TP values are whitelisted.** `validate_config()` runs at startup and raises `ValueError` if any configured TP is not in `[5, 8, 12, 16, 20]`. This prevents misconfiguration from silently running with an unvalidated target.

---

## 15. CLI Architecture (`kryptos.py`)

### Operating Modes

| Mode | Invocation | Description |
|---|---|---|
| Interactive REPL | `python kryptos.py` | readline loop; Ctrl+C exits; history saved to `data/.kryptos_history` |
| Single NL command | `python kryptos.py "..."` | parses one sentence and exits |
| Direct subcommand | `python kryptos.py <cmd> [flags]` | argparse; 10 subcommands |

### Intent Catalogue (14 intents)

| Intent | Example phrases | Action |
|---|---|---|
| `start_agent` | "start trading", "run paper" | `agent_manager.start(mode)` |
| `stop_agent` | "stop", "shut it down" | `agent_manager.stop()` |
| `agent_status` | "status", "is it running?" | `agent_manager.status(config)` |
| `next_schedule` | "next cycle", "when does it run next" | `agent_manager.get_next_schedule(config)` |
| `view_report` | "report", "show my portfolio" | portfolio + trades + metrics |
| `trade_details` | "last 5 trades", "show BTC trades" | `get_trades_with_decisions()` |
| `llm_decisions` | "why did it hold ETH", "BUY reasons" | `get_llm_decision_detail()` |
| `daily_summary` | "today summary", "what happened yesterday" | `get_daily_summary()` |
| `win_rate` | "win rate", "how am I doing" | `get_performance_metrics()` |
| `open_positions` | "positions", "what do I own" | `get_open_positions()` |
| `tail_log` | "show the log", "last 50 lines" | `agent_manager.tail_log(n)` |
| `help` | "help", "what can you do" | print intent catalogue |
| `exit` | "exit", "quit", "bye" | return `False` from dispatch |

### NL Parser Strategy

```
NLParser.parse(text)
  │
  ├─ if _ollama_ok:
  │    client.chat(model, messages=[system_prompt + user_text], temperature=0.0)
  │    strip markdown code fences
  │    json.loads(response)
  │
  └─ else (or on any error):
       _keyword_parse(text)
       regex for: pair=[A-Z]+/USD, days=\d+, count=\d+, decision_type=BUY|SELL|HOLD
       _normalise_params()
```

Return value: `{intent, params, source: "llm"|"keyword", raw_text}`

### Report Query Functions (`src/reports/trade_report.py`)

All functions are decorated with `@_safe` — they catch all exceptions and return `{}` / `[]`. Queries span `audit.db` and the appropriate trading DB depending on `mode`.

| Function | Returns | Joins |
|---|---|---|
| `get_portfolio_summary(mode, config)` | cash, positions, daily P&L, unrealised P&L | trading DB + audit snapshot |
| `get_trades_with_decisions(mode, config, days, pair, limit)` | closed trades enriched with LLM BUY decision | trades JOIN audit_llm_decisions via ±5-min window |
| `get_cycle_detail(cycle_id, config)` | full FK chain for one cycle | cycle→signals→decisions→risk_checks→orders→fills |
| `get_recent_cycles(mode, config, limit)` | last N cycles with per-pair summaries | audit_cycles + audit_llm_decisions |
| `get_llm_decision_patterns(mode, config, days)` | BUY/SELL/HOLD matrix, top hold reasons, model stats | audit_llm_decisions GROUP BY pair |
| `get_performance_metrics(mode, config, days)` | win rate, total P&L, max drawdown, per-pair | paper_trades / live_trades |
| `get_llm_decision_detail(mode, config, pair, decision_type, days, limit)` | individual decisions + raw LLM output | audit_llm_decisions JOIN audit_risk_checks |
| `get_daily_summary(mode, config, date_str)` | day cycles, decisions, trade list | audit_cycles + audit_llm_decisions + trades |
| `get_open_positions(mode, config)` | open positions | paper_positions / live_positions |

### Display Color Scheme (Rich terminal)

| Color | Meaning |
|---|---|
| Green | Positive P&L / BUY decision / agent running |
| Red | Negative P&L / SELL decision / agent stopped |
| Yellow | HOLD decision / warnings |
| Cyan | Info headers / neutral data |
| Magenta | LLM reasoning text / raw LLM output |

### Agent Process Management (`src/cli/agent_manager.py`)

- **PID file:** `data/kryptos.pid` — JSON `{pid, mode, started_at}`
- **Start:** `subprocess.Popen([python, main.py, --flag], start_new_session=True)` → waits 1 s to verify alive
- **Stop:** SIGTERM → poll 1 s intervals up to 10 s → SIGKILL if still alive → clear PID file
- **Status:** `os.kill(pid, 0)` liveness check + uptime + last audit cycle timestamp
- **Schedule:** reads `max(timestamp)` from `audit_cycles` → adds `cycle_interval_minutes` → returns `{next_cycle_at, wait_human, is_overdue}`
