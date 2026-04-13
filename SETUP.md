# Kryptos — Setup Guide

> New to Kryptos? This guide gets you from zero to a running paper-trading agent in under 15 minutes.

---

## Table of Contents

1. [System Requirements](#1-system-requirements)
2. [Install](#2-install)
3. [Choose Your LLM Provider](#3-choose-your-llm-provider)
4. [Configure Environment Variables](#4-configure-environment-variables)
5. [First Run — Paper Mode](#5-first-run--paper-mode)
6. [Verify the Agent is Working](#6-verify-the-agent-is-working)
7. [Key Parameters to Tune](#7-key-parameters-to-tune)
8. [Set Up Telegram Notifications (Optional)](#8-set-up-telegram-notifications-optional)
9. [Healthcheck Webhook (Optional)](#9-healthcheck-webhook-optional)
10. [Reset Paper Trading](#10-reset-paper-trading)

---

## 1. System Requirements

| Requirement | Minimum | Recommended |
|---|---|---|
| OS | macOS 12+ / Ubuntu 22.04+ | Ubuntu 22.04 LTS |
| Python | 3.11 | 3.11.x |
| RAM | 1 GB | 2 GB |
| Disk | 500 MB | 1 GB (for candle history + logs) |
| Internet | Required | Stable broadband |

For local LLM (Ollama): additional 4–8 GB RAM and 10–30 GB disk for model weights.

---

## 2. Install

### Option A: Automated (recommended)

```bash
git clone https://github.com/vipulbms/crypto-trader-agent.git
cd crypto-trader-agent
chmod +x setup.sh
./setup.sh
```

The script will:
- Check Python 3.11+
- Create a virtual environment at `.venv/`
- Install all dependencies from `requirements.txt`
- Create the `data/` and `logs/` directories
- Prompt you for your LLM choice and write a `.env` template

### Option B: Manual

```bash
git clone https://github.com/vipulbms/crypto-trader-agent.git
cd crypto-trader-agent

# Create virtual environment
python3.11 -m venv .venv
source .venv/bin/activate          # macOS/Linux
# .venv\Scripts\activate           # Windows

# Install dependencies
pip install -r requirements.txt

# Create required directories
mkdir -p data logs

# Copy environment template
cp .env.example .env
```

---

## 3. Choose Your LLM Provider

Kryptos supports three LLM backends. Choose one:

### Option A: Groq (Recommended — Free, Fast)

Groq provides free API access to powerful models with very low latency. Sign up at [console.groq.com](https://console.groq.com).

1. Create an account and generate an API key
2. Set `GROQ_API_KEY` in your `.env` file (see §4)
3. The default model `qwen/qwen3-32b` with `llama-3.3-70b-versatile` fallback is pre-configured in `config.yaml`

Config in `config.yaml` (already set as default):
```yaml
llm:
  provider: openai_compat
  model: qwen/qwen3-32b
  base_url: https://api.groq.com/openai/v1
  fallback_model: llama-3.3-70b-versatile
  timeout_seconds: 60
  disable_thinking: true        # Required for qwen3 tool calling on Groq
```

### Option B: Google Gemini

Sign up at [aistudio.google.com](https://aistudio.google.com) and create an API key. Free tier available.

1. Set `GEMINI_API_KEY` in your `.env` file (see §4)
2. Update `config.yaml`:

```yaml
llm:
  provider: openai_compat
  model: gemini-2.5-flash
  base_url: https://generativelanguage.googleapis.com/v1beta/openai/
  api_key_env: GEMINI_API_KEY
  fallback_model: gemini-2.0-flash
  timeout_seconds: 90
  disable_thinking: false
```

### Option C: Ollama (Local, Private, No API Key)

Run LLMs entirely on your own machine. No internet required for inference. Requires a reasonably powerful machine (see requirements above).

1. Install Ollama: [ollama.ai/download](https://ollama.ai/download)
2. Pull a model (recommended minimum for trading: 7B parameter instruction model):

```bash
ollama pull llama3.2:3b          # Fastest; less accurate (3B)
ollama pull llama3.1:8b          # Good balance (8B)
ollama pull qwen2.5:14b          # Best quality for local (14B)
```

3. Update `config.yaml`:

```yaml
llm:
  provider: ollama
  model: qwen2.5:14b             # or whichever you pulled
  base_url: http://localhost:11434
  fallback_model: llama3.1:8b
  timeout_seconds: 120           # Local models are slower
  disable_thinking: false
```

4. Make sure Ollama is running:
```bash
ollama serve
```

---

## 4. Configure Environment Variables

Create a file named `.env` in the project root (never commit this file):

```bash
# ============================================================
# REQUIRED: Choose ONE LLM provider (see Section 3)
# ============================================================

# Groq (recommended)
GROQ_API_KEY=gsk_your_key_here

# OR Google Gemini
# GEMINI_API_KEY=AIza_your_key_here

# ============================================================
# OPTIONAL: Live trading on Kraken (paper mode does NOT need these)
# ============================================================
KRAKEN_API_KEY=
KRAKEN_API_SECRET=

# ============================================================
# OPTIONAL: Telegram notifications (highly recommended)
# ============================================================
# See Section 8 for how to get these values
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
```

**Paper trading never requires Kraken keys.** The agent uses the public Kraken WebSocket for real-time prices but executes all trades virtually in SQLite.

---

## 5. First Run — Paper Mode

```bash
# Activate virtual environment (if not already active)
source .venv/bin/activate

# Start the paper trading agent in the background
python main.py --paper
```

Expected output in `logs/agent.log` (first 2–3 minutes):

```
2026-04-13 10:00:00 INFO  [main] === Kryptos starting (paper mode) ===
2026-04-13 10:00:01 INFO  [ws] Connecting to Kraken WebSocket...
2026-04-13 10:00:02 INFO  [ws] Subscribed to 27 pairs
2026-04-13 10:00:02 INFO  [main] Warming up candle buffers (need 220 candles)...
2026-04-13 10:07:31 INFO  [main] Candle warm-up complete. Starting decision cycles.
2026-04-13 10:07:31 INFO  [cycle] === Cycle 1 started ===
2026-04-13 10:07:32 INFO  [signals] BTC/USD: score=3/28, HOLD (score 3 < min 5)
2026-04-13 10:07:32 INFO  [signals] ETH/USD: score=7/28, BUY candidate
...
2026-04-13 10:07:45 INFO  [agent] LLM response received (1.2s)
2026-04-13 10:07:45 INFO  [trade] BUY ETH/USD: $150 @ $2,450.00 (score=7)
```

The **warmup period** (220 candles × 1 minute each ≈ 3.5 hours of market data) must accumulate before the first trade. In practice, the WebSocket delivers candles quickly and warmup completes in 5–10 minutes.

### Watching the Agent Live

Open a second terminal:

```bash
source .venv/bin/activate

# Monitor the agent logs in real time
tail -f logs/agent.log

# Check open positions
python kryptos.py positions

# Check today's P&L
python kryptos.py summary

# Full balance report
python kryptos.py balance
```

---

## 6. Verify the Agent is Working

Run the interactive CLI to confirm everything is healthy:

```bash
python kryptos.py
```

Type these commands at the `kryptos>` prompt:

```
kryptos> agent status
```

Expected output:
```
Agent Status: RUNNING (PID 12345)
Uptime: 00:15:22
Cycle: 3 completed
Last cycle: 2026-04-13 10:22:45 SGT
Next cycle: in 14m 33s
```

```
kryptos> balance
```

Expected output:
```
Portfolio Value: $1,000.00
  Cash:          $1,000.00
  Open Positions: 0
  Realized P&L:   $0.00 (0.0%)
```

If you see errors, check:
1. `logs/agent.log` for the full error message
2. That your API key is set correctly in `.env`
3. That the Kraken WebSocket connection succeeded (look for "Subscribed to 27 pairs")

---

## 7. Key Parameters to Tune

All parameters are in `config.yaml`. Start with paper trading for at least 2 weeks before changing anything.

### Parameters Most People Adjust

```yaml
trading:
  cycle_interval_minutes: 30       # How often the LLM runs (default 30 min)
                                   # Reduce to 15 for more aggressive trading
                                   # Raise to 60 for fewer API calls

  max_position_pct: 20             # Max % of cash per trade
                                   # Start at 10% while learning the system

  max_open_positions: 10           # Safety ceiling on concurrent positions
                                   # Cash guards are the real limit in practice

risk:
  min_cash_reserve_pct: 5          # Minimum cash to keep uninvested
                                   # Raise to 20% for more conservative operation

  daily_loss_limit_pct: 10         # % daily loss before halting new buys
                                   # Reduce to 5% for tighter risk control

  circuit_breaker:
    consecutive_stops: 3           # Number of SLs before pause
                                   # Reduce to 2 for more cautious operation

signals:
  buy_min_score: 5                 # Global minimum signal score to consider BUY
                                   # Raise to 7 during testing to reduce trade frequency
```

### Parameters NOT to Touch Initially

- `stop_loss_pct: 5` — keep at 5%; it's the core risk anchor
- `min_profit_floor_pct: 1.0` — never reduce; it covers exchange fees
- `global_max_daily_loss_pct: 7.0` — kill switch; only raise if you're confident
- Per-pair `buy_min_score` values — these are calibrated from backtests; don't override without running a new backtest

---

## 8. Set Up Telegram Notifications (Optional but Highly Recommended)

Telegram sends you real-time alerts for every trade, daily P&L, and system health.

### Step 1: Create a Telegram Bot

1. Open Telegram and search for `@BotFather`
2. Send `/newbot`
3. Choose a name and username for your bot
4. BotFather gives you a token like: `7123456789:AAFsomestring`
5. Copy this token — this is your `TELEGRAM_BOT_TOKEN`

### Step 2: Get Your Chat ID

1. Message your new bot in Telegram (send "hello")
2. Visit this URL in your browser (replace `YOUR_TOKEN`):
   ```
   https://api.telegram.org/botYOUR_TOKEN/getUpdates
   ```
3. Look for `"chat":{"id":` in the response — this number is your `TELEGRAM_CHAT_ID`

### Step 3: Add to `.env`

```bash
TELEGRAM_BOT_TOKEN=7123456789:AAFsomestring
TELEGRAM_CHAT_ID=123456789
```

### What You'll Receive

- 🟢 **BUY executed**: pair, entry price, amount, score
- 🔴 **SELL/SL/TP hit**: pair, exit reason, P&L%
- ⚠️ **Circuit breaker activated / drawdown recovery entered**
- 📊 **Daily P&L summary** (automatically at 00:00 UTC)
- 💓 **Hourly heartbeat** (in live mode): balance, hourly P&L, buys/sells

---

## 9. Healthcheck Webhook (Optional)

Monitor that the agent is alive using a dead-man's switch service like [healthchecks.io](https://healthchecks.io) (free tier available).

1. Create a check on healthchecks.io, set period to 65 minutes (the heartbeat fires every 60 minutes)
2. Copy the ping URL (e.g. `https://hc-ping.com/your-uuid-here`)
3. Add to `config.yaml`:

```yaml
notifications:
  healthcheck_url: "https://hc-ping.com/your-uuid-here"
```

The agent pings this URL every heartbeat cycle. If it misses 2+ pings, healthchecks.io alerts you.

---

## 10. Reset Paper Trading

To start fresh (clear all virtual trades and reset balance to $1,000):

```bash
# Ensure the agent is stopped first
python kryptos.py stop

# Reset with confirmation prompt
python scripts/reset_paper.py --yes
```

If the agent is still running (modified DB in last 120 seconds), the script will warn you. Use `--force` to bypass:

```bash
python scripts/reset_paper.py --yes --force
```

**What reset does:**
1. Deletes all rows from `paper_positions`, `paper_trades`, `daily_pnl` in `paper_trading.db`
2. Resets `paper_wallet` to starting balance ($1,000)
3. Clears `agent_state` entries (start-of-day balance, BTC dominance cache)
4. Deletes paper-trading rows from `audit.db` (audit_signals, audit_cycles, etc.)
5. **Does NOT delete live trading data** — only paper data is touched

After reset, restart the agent:
```bash
python main.py --paper
```
