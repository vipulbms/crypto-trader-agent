# Kryptos — AI Crypto Trading Agent

> An autonomous, conservative AI trading agent for Kraken. Paper-trades with $1,000 virtual balance. Every decision — including every HOLD — is logged with full LLM reasoning. Controlled via a natural-language CLI.

---

## Features

- **AI-powered decisions** — local `qwen2.5:7b` via Ollama; no cloud API calls, no external data sharing
- **Capital-first risk rules** — 5% stop-loss, configurable take-profit (5/8/12/16/20%), max 30% per trade, enforced by deterministic Python (not the LLM)
- **Full audit trail** — every BUY, SELL, and HOLD logged to SQLite with LLM reasoning and risk check results
- **Natural-language CLI** — ask `show last 5 BTC trades with reasoning` or `why did it hold ETH?` in plain English
- **Paper trading mode** — 2-week simulation on real Kraken prices, no API keys needed
- **Telegram alerts** — optional; agent runs fine without them

---

## Trading Pairs & Targets

| Pair | Take-Profit | Stop-Loss |
|---|---|---|
| BTC/USD | 8% | 5% |
| ETH/USD | 12% | 5% |
| BNB/USD | 12% | 5% |
| SOL/USD | 16% | 5% |
| XRP/USD | 12% | 5% |
| TRX/USD | 12% | 5% |
| DOGE/USD | 20% | 5% |
| ADA/USD | 12% | 5% |
| LTC/USD | 12% | 5% |

---

## Prerequisites

### 1. Python environment

```bash
cd /path/to/crypto-trader-agent
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

The `.venv` is already created if you're continuing from a prior session — just `source .venv/bin/activate`.

### 2. Ollama + model

Required for both AI trading decisions and CLI natural-language parsing.

```bash
brew install ollama
ollama serve                  # keep this running in a separate terminal
ollama pull qwen2.5:7b        # ~5 GB, one-time download
```

The CLI falls back to keyword-based intent matching if Ollama is not running, so it is usable even before the model is downloaded.

### 3. Environment variables (optional)

Copy `.env.example` (or create `.env`) and fill in only what you need:

```bash
# Kraken API — live mode only, not needed for paper trading
KRAKEN_API_KEY=your_key_here
KRAKEN_API_SECRET=your_secret_here

# Telegram — optional; agent runs without it
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id

# Ollama — only needed if running on a non-default host
OLLAMA_BASE_URL=http://localhost:11434
```

---

## Quick Start — Paper Trading

```bash
# Terminal 1: Ollama (keep running)
ollama serve

# Terminal 2: Agent
source .venv/bin/activate

# Option A — run directly
python main.py --paper

# Option B — run via CLI (manages the process for you)
python kryptos.py start --paper
```

The agent connects to the Kraken public WebSocket, collects candles, and runs its first decision cycle after ~60 minutes (needs 60 candles per pair). All data is written to `data/paper_trading.db` and `data/audit.db`.

---

## Kryptos CLI

`kryptos.py` is the primary interface. It manages the agent process, answers questions in natural language, and displays trade data from the SQLite databases.

### Mode 1 — Interactive REPL

```bash
python kryptos.py           # paper mode (default)
python kryptos.py --live    # live trading DB
```

Type any natural-language question at the `kryptos>` prompt:

```
kryptos> show me today's report
kryptos> why did it hold ETH this week?
kryptos> what is my win rate over the last 14 days?
kryptos> show last 5 BTC trades with full reasoning
kryptos> when is the next decision cycle?
kryptos> agent status
kryptos> exit
```

Command history is saved across sessions at `data/.kryptos_history`.

### Mode 2 — Single Natural-Language Command

```bash
python kryptos.py "show me my open positions"
python kryptos.py "last 10 trades for ETH with LLM reasoning"
python kryptos.py "show the log"
```

### Mode 3 — Direct Subcommands

No Ollama required; uses argparse directly.

```bash
# Agent lifecycle
python kryptos.py start --paper          # launch agent as background process
python kryptos.py start --live
python kryptos.py stop                   # graceful shutdown (SIGTERM → SIGKILL)
python kryptos.py status                 # uptime, last cycle, running state

# Reports
python kryptos.py report                             # portfolio + trades + metrics
python kryptos.py report --days 7 --pair BTC/USD --detailed
python kryptos.py trades --days 14 --count 20
python kryptos.py decisions --pair ETH/USD --type HOLD --days 7 --detailed
python kryptos.py metrics --days 30
python kryptos.py summary --date 2026-03-28
python kryptos.py positions

# Logs
python kryptos.py log --lines 50
```

---

## Architecture

```
                    kryptos.py  (CLI entry point)
                         │
          ┌──────────────┼──────────────────────┐
          │              │                      │
       NLParser    commands.dispatch()    agent_manager
    (Ollama/keywords)  (12 intents)    (PID-based start/stop)
          │              │
          └──────▶  trade_report.py  ──▶  display.py (Rich)
                   (9 query functions)    (color terminal UI)
                         │
           audit.db  ·  paper_trading.db  ·  agent.log

─────────────────────────────────────────────────────────

                    main.py  (agent process)
                         │
          WebSocket feed (public Kraken, real prices)
                         │
            compute_indicators() — RSI · MACD · BB · EMA · ATR
                         │
            generate_signal()  — BUY / SELL / HOLD + strength 0–1
                         │
           TradingAgent  ──▶  Ollama qwen2.5:7b (tool calling)
                         │
           RiskManager   ──▶  deterministic Python rules
                         │
           PaperBroker / KrakenClient
                         │
      paper_trading.db  ·  live_trading.db  ·  audit.db
```

---

## How the Agent Decides

Every 15 minutes:

1. WebSocket delivers latest 1-min candles (200-candle rolling buffer per pair)
2. `compute_indicators()` — RSI, MACD, Bollinger Bands, EMA-20/50, ATR
3. `generate_signal()` — rule-based BUY/SELL/HOLD with 0–1 strength score
4. `build_cycle_prompt()` — injects portfolio state + all 4 pair signals into LLM context
5. Ollama LLM (`qwen2.5:7b`) is called once per pair; must call `propose_buy`, `propose_sell`, or `hold`
6. `RiskManager.validate_buy()` — caps/rejects the LLM's proposal using hard Python rules
7. `PaperBroker` (or `KrakenClient` in live) executes the order
8. `AuditLogger` records everything — cycle, signal, LLM reasoning, risk verdict, fill

The LLM proposes; Python decides. The risk manager cannot be overridden by prompt.

### Signal Scoring (BUY threshold ≥ 4 / 10)

| Condition | Points |
|---|---|
| RSI < 35 (oversold) | +3 |
| MACD histogram positive | +2 |
| MACD crossover (neg → pos) | +1 |
| Price at or below lower Bollinger Band | +3 |
| EMA-20 ≥ EMA-50 (uptrend) | +1 |

---

## Risk Rules

All enforced by deterministic Python — the LLM never does arithmetic on these values.

| Rule | Value |
|---|---|
| Stop-loss | 5% below entry (fixed) |
| Take-profit | 8–16% per pair (configurable whitelist: 5, 8, 12, 16, 20) |
| Max position size | 30% of portfolio |
| Max open positions | 3 simultaneously |
| Cash reserve | 10% of portfolio always kept liquid |
| Daily loss limit | Buys blocked if daily P&L < −10% of start-of-day balance |

---

## Paper vs Live Mode

| Aspect | Paper (`--paper`) | Live (`--live`) |
|---|---|---|
| Kraken private API | Not required | Required |
| Order execution | `PaperBroker` (SQLite simulation) | `KrakenClient` (ccxt) |
| Price feed | Public Kraken WebSocket (real prices) | Same |
| Starting balance | $1,000 virtual | Actual Kraken balance |
| Stop/TP enforcement | Polled each cycle | Native Kraken server-side orders |
| Slippage | 0.05% simulated | Real fills |
| Fee | 0.26% simulated | Real Kraken fees |
| Telegram alerts | `[PAPER]` prefix | `[LIVE]` prefix |

---

## After 2 Weeks — Readiness Review

```bash
# Check the verdict
python scripts/review.py --mode paper --days 14

# Or via the CLI
python kryptos.py metrics --days 14
```

**READY FOR LIVE TRADING** requires ALL of:

| Criterion | Threshold |
|---|---|
| Win rate | ≥ 50% |
| Max drawdown | < 15% |
| Total P&L over 14 days | > 0 |
| Closed trades | ≥ 10 |

If any criterion is not met, extend the paper trading period and review the `decisions` report.

---

## File Structure

```
crypto-trader-agent/
├── kryptos.py                   CLI entry point (REPL + NL + subcommands)
├── main.py                      Agent runner (background process)
├── config.yaml                  All tunable parameters
├── requirements.txt
├── .env                         API keys — never committed
├── data/                        Created at runtime
│   ├── paper_trading.db
│   ├── live_trading.db
│   ├── audit.db
│   ├── kryptos.pid              Agent process ID (when running)
│   └── agent.log
├── src/
│   ├── agent/                   LLM prompts, tool definitions, TradingAgent
│   ├── analysis/                Indicators (pandas-ta) + signal scorer
│   ├── cli/                     NLParser · commands · display · agent_manager
│   ├── exchange/                WebSocket feed · KrakenClient · PaperBroker
│   ├── notifications/           Telegram notifier
│   ├── reports/                 trade_report.py — 9 query functions
│   ├── risk/                    RiskManager — deterministic Python rules
│   └── storage/                 SQLite schema + append-only audit logger
└── scripts/
    ├── daily_report.py          Daily P&L report
    └── review.py                2-week readiness verdict
```

---

## Configuration (`config.yaml`)

Key parameters — all tunable without code changes:

```yaml
trading:
  stop_loss_pct: 5                         # Fixed — do not change
  take_profit_pct: 8                       # Global fallback (must be in allowed list)
  allowed_take_profit_pcts: [5, 8, 12, 16, 20]
  max_position_pct: 30
  max_open_positions: 3
  cycle_interval_minutes: 15

  pairs:
    - pair: BTC/USD;  take_profit_pct: 8
    - pair: ETH/USD;  take_profit_pct: 12
    - pair: BNB/USD;  take_profit_pct: 12
    - pair: SOL/USD;  take_profit_pct: 16
    - pair: XRP/USD;  take_profit_pct: 12
    - pair: TRX/USD;  take_profit_pct: 12
    - pair: DOGE/USD;  take_profit_pct: 20
    - pair: ADA/USD;  take_profit_pct: 12
    - pair: LTC/USD;  take_profit_pct: 12

paper:
  starting_balance_usd: 1000

llm:
  model: qwen2.5:14b
  fallback_model: llama3.1:8b
  base_url: http://localhost:11434
  timeout_seconds: 60

risk:
  daily_loss_limit_pct: 10
  min_cash_reserve_pct: 10
```

---

## Documentation

| File | Contents |
|---|---|
| [plan.md](plan.md) | Architecture diagrams, decision cycle, all LLM prompts verbatim, indicator scoring, CLI architecture, database design, configuration reference |
| [business-requirement.md](business-requirement.md) | Full BRD — 72 functional requirements, 11 NFRs, 8 business rules, acceptance criteria, risks, glossary |
