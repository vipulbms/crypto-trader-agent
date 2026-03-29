# Kryptos — AI Crypto Trading Agent

> An autonomous, conservative AI trading agent for Kraken. Paper-trades with $1,000 virtual balance. Every decision — including every HOLD — is logged with full LLM reasoning. Controlled via a natural-language CLI.

---

## Features

- **AI-powered decisions** — local `qwen2.5:14b` via Ollama; no cloud API calls, no external data sharing
- **Capital-first risk rules** — 5% stop-loss, configurable take-profit (5/8/12/16/20%), max 30% per trade, enforced by deterministic Python (not the LLM)
- **Full audit trail** — every BUY, SELL, and HOLD logged to SQLite with LLM reasoning and risk check results
- **Natural-language CLI** — ask `show last 5 BTC trades with reasoning` or `why did it hold ETH?` in plain English
- **Paper trading mode** — simulation on real Kraken prices, no API keys needed
- **Telegram alerts** — optional; agent runs fine without them
- **Performance timing** — every method in the decision flow is timed and logged for profiling

---

## Trading Pairs & Targets

| Pair | Take-Profit | Stop-Loss | Rationale |
|---|---|---|---|
| BTC/USD | 8% | 5% | Most mature asset; conservative target |
| ETH/USD | 12% | 5% | Moderate volatility |
| BNB/USD | 12% | 5% | Similar profile to ETH |
| SOL/USD | 16% | 5% | High volatility — larger swings achievable |
| XRP/USD | 12% | 5% | News-driven spikes; data shows RSI rarely < 30 |
| TRX/USD | 12% | 5% | Mid-tier altcoin |
| DOGE/USD | 20% | 5% | Meme-driven; can swing 20–30% in hours |
| ADA/USD | 12% | 5% | Moderate volatility, similar to ETH |
| LTC/USD | 12% | 5% | Follows BTC with 1.5–2× amplification |

---

## Prerequisites

### 1. Python environment

```bash
cd /path/to/crypto-trader-agent
~/.pyenv/versions/3.11.15/bin/python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Ollama + model

```bash
brew install ollama
ollama serve                   # keep running in a separate terminal
ollama pull qwen2.5:14b        # ~9 GB, one-time download
```

### 3. Environment variables

Copy `.env.example` and fill in what you need:

```bash
KRAKEN_API_KEY=your_key_here       # live mode only
KRAKEN_API_SECRET=your_secret_here # live mode only
TELEGRAM_BOT_TOKEN=your_bot_token  # optional
TELEGRAM_CHAT_ID=your_chat_id      # optional
OLLAMA_BASE_URL=http://localhost:11434
```

---

## Quick Start — Paper Trading

```bash
# Terminal 1: Ollama (keep running)
ollama serve

# Terminal 2: Agent
source .venv/bin/activate
python main.py --paper
# or via CLI:
python kryptos.py start --paper
```

The agent connects to the Kraken public WebSocket, back-fills 300 candles (75 hours of 15-min data) per pair, waits for 220 candles to warm up all indicators, then runs its first decision cycle. All data is written to `data/paper_trading.db` and `data/audit.db`.

---

## Kryptos CLI

`kryptos.py` is the primary interface. It manages the agent process, answers questions in natural language, and displays trade data from the SQLite databases.

### Interactive REPL

```bash
python kryptos.py           # paper mode (default)
python kryptos.py --live    # live trading DB
```

```
kryptos> show me today's report
kryptos> why did it hold ETH this week?
kryptos> what is my win rate over the last 14 days?
kryptos> show last 5 BTC trades with full reasoning
kryptos> when is the next decision cycle?
kryptos> agent status
kryptos> exit
```

### Direct Subcommands

```bash
python kryptos.py start --paper
python kryptos.py stop
python kryptos.py status
python kryptos.py report --days 7 --pair BTC/USD --detailed
python kryptos.py trades --days 14 --count 20
python kryptos.py decisions --pair ETH/USD --type HOLD --days 7 --detailed
python kryptos.py metrics --days 30
python kryptos.py summary --date 2026-03-29
python kryptos.py positions
python kryptos.py log --lines 50
```

---

## How the Agent Decides

Every 15 minutes:

1. WebSocket delivers latest 15-min candles (300-candle rolling buffer per pair)
2. `compute_indicators()` — RSI(14), MACD(12/26/9), Bollinger Bands(50,2), EMA-20/200, ATR(14)
3. `generate_signal()` — rule-based BUY/SELL/HOLD with 0–1 strength score
4. `build_cycle_prompt()` — injects portfolio state + all pair signals into LLM context
5. Ollama LLM (`qwen2.5:14b`) is called once per pair; must call `propose_buy`, `propose_sell`, or `hold`
6. `RiskManager.validate_buy()` — caps/rejects using hard Python rules
7. `PaperBroker` (or `KrakenClient`) executes the order
8. `AuditLogger` records everything — cycle, signal, LLM reasoning, risk verdict, fill

**The LLM proposes; Python decides. The risk manager cannot be overridden by prompt.**

---

## Technical Indicators Explained

All indicators are computed on **15-minute candles**. This aligns with the 15-minute decision cycle — each candle represents exactly one cycle's worth of price action.

### RSI — "Is the price tired?"

Measures how fast the price moved recently (0–100 scale).
- **RSI < 30** = price dropped too fast = possibly oversold = BUY hint (+3 pts)
- **RSI > 60** = price rose too fast = possibly overbought = SELL hint (+3 pts)
- **30–60** = neutral, no signal

*At 15-min candles: RSI(14) looks back 3.5 hours. RSI < 30 fires on only 7–11% of candles (data-backed threshold from 30 days of Kraken history).*

### MACD — "Which way is momentum heading?"

Two moving averages chase the price. The histogram shows how fast they're diverging.
- **Histogram > 0** = accelerating upward = BUY hint (+2 pts)
- **Line crossed above signal** = momentum just turned bullish = BUY hint (+1 pt)
- **Histogram < 0** = decelerating/reversing = SELL hint (+2 pts)

*At 15-min candles: MACD(12,26,9) fast line = 3 hours, slow line = 6.5 hours.*

### Bollinger Bands — "Is the price on sale or overpriced?"

A dynamic price channel that expands during volatile periods and contracts during calm ones.
- **Price at or below lower band** = on sale = BUY hint (+3 pts)
- **Price at or above upper band** = overpriced = SELL hint (+2 pts)
- **Band width < 0.5% of price** = bands are squeezed = signals ignored (noise, not real levels)

*At 15-min candles: BB(50,2) looks back 12.5 hours. Widened from BB(20) to prevent the "band squeeze" problem where both upper and lower bands simultaneously register as touched during calm markets.*

### EMA Fast / Slow — "Short-term vs long-term mood"

Exponential Moving Averages weight recent prices more heavily.
- **EMA(20) ≥ EMA(200)** = short-term trend above long-term = uptrend = BUY hint (+1 pt)

*At 15-min candles: EMA(20) = 5 hours (short-term), EMA(200) = 50 hours / ~2 days (genuine long-term trend). Using EMA(50) as the slow line was too short at 12.5 hours — both EMAs reacted to the same timeframe.*

### ATR — "How bumpy is the road?"

Average True Range measures typical price swings. Used internally to understand volatility context but not directly in signal scoring.

---

## Signal Scoring

`generate_signal()` awards points out of 10. All weights and thresholds are configurable in `config.yaml` under `signals:`.

**BUY requires score ≥ 4 AND buy score > sell score:**

| Condition | Points (default) |
|---|---|
| RSI < 30 (oversold) | +3 |
| MACD histogram > 0 | +2 |
| MACD line crossed above signal | +1 |
| Price at/near lower Bollinger Band | +3 |
| EMA(20) ≥ EMA(200) (uptrend) | +1 |

**SELL requires score ≥ 3 AND sell score > buy score:**

| Condition | Points (default) |
|---|---|
| RSI > 60 (overbought) | +3 |
| MACD histogram < 0 | +2 |
| Price at/near upper Bollinger Band | +2 |

**Important:** The signal layer only *recommends*. The LLM makes the final call and can override any BUY with HOLD if it judges the confluence insufficient.

---

## Risk Rules

All enforced by deterministic Python — the LLM never does arithmetic on these values.

| Rule | Value |
|---|---|
| Stop-loss | 5% below entry (fixed) |
| Take-profit | 8–20% per pair (configurable whitelist: 5, 8, 12, 16, 20) |
| Max position size | 30% of portfolio |
| Max open positions | 3 simultaneously |
| Cash reserve | 10% always kept liquid |
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
| Fee | 0.26% simulated (Kraken maker) | Real Kraken fees |
| Telegram alerts | `[PAPER]` prefix | `[LIVE]` prefix |

---

## Readiness Review

```bash
python kryptos.py metrics --days 14
```

**READY FOR LIVE TRADING** requires ALL of:

| Criterion | Threshold |
|---|---|
| Win rate | ≥ 50% |
| Max drawdown | < 15% |
| Total P&L over 14 days | > 0 |
| Closed trades | ≥ 10 |

---

## File Structure

```
crypto-trader-agent/
├── kryptos.py                   CLI entry point (REPL + NL + subcommands)
├── main.py                      Agent runner (background process)
├── config.yaml                  ALL tunable parameters — no hardcoded values in code
├── requirements.txt
├── .env                         API keys — never committed
├── logs/                        Created at runtime
│   └── agent.log                Rotating log (100 MB max, 4 backups)
├── data/                        Created at runtime
│   ├── paper_trading.db
│   ├── live_trading.db
│   ├── audit.db
│   └── kryptos.pid
├── src/
│   ├── agent/                   LLM prompts, tool definitions, TradingAgent
│   ├── analysis/                Indicators (ta library) + signal scorer
│   ├── cli/                     NLParser · commands · display · agent_manager
│   ├── exchange/                WebSocket feed · KrakenClient · PaperBroker
│   ├── notifications/           Telegram notifier (async, non-blocking)
│   ├── reports/                 trade_report.py — 9 query functions
│   ├── risk/                    RiskManager — deterministic Python rules
│   ├── storage/                 SQLite schema + append-only audit logger
│   └── utils/                   tz.py (SGT timezone) · timing.py (@timed decorator)
└── scripts/
    ├── daily_report.py
    └── review.py
```

---

## Configuration (`config.yaml`)

**Every parameter is in `config.yaml`. No hardcoded values exist in any source file.**

```yaml
trading:
  stop_loss_pct: 5
  take_profit_pct: 8
  allowed_take_profit_pcts: [5, 8, 12, 16, 20]
  max_position_pct: 30
  max_open_positions: 3
  cycle_interval_minutes: 15

paper:
  starting_balance_usd: 1000
  slippage_pct: 0.05
  maker_fee_pct: 0.26

indicators:
  rsi_period: 14
  rsi_oversold: 30          # fires 7-11% of candles on 30-day Kraken data
  rsi_overbought: 60
  macd_fast: 12
  macd_slow: 26
  macd_signal: 9
  bb_period: 50             # 50×15-min = 12.5 hrs; prevents band-squeeze false signals
  bb_std: 2
  bb_min_width_pct: 0.5     # ignore BB signals when band gap < 0.5% of price
  bb_buy_tolerance_pct: 1.0
  bb_sell_tolerance_pct: 1.0
  ema_fast: 20              # 20×15-min = 5 hrs short-term trend
  ema_slow: 200             # 200×15-min = 50 hrs long-term trend
  atr_period: 14
  candle_buffer_size: 300
  candle_interval: 15
  min_candles_to_start: 220
  buffer_fill_timeout_secs: 300
  buffer_check_interval_secs: 5

signals:
  rsi_oversold_score: 3
  macd_hist_positive_score: 2
  macd_crossover_score: 1
  bb_lower_score: 3
  ema_uptrend_score: 1
  max_score: 10
  rsi_overbought_score: 3
  macd_hist_negative_score: 2
  bb_upper_score: 2
  buy_min_score: 4
  sell_min_score: 3

llm:
  model: qwen2.5:14b
  fallback_model: llama3.1:8b
  base_url: http://localhost:11434
  timeout_seconds: 600
  max_reasoning_chars: 1000

risk:
  daily_loss_limit_pct: 10
  min_cash_reserve_pct: 10

exchange:
  ws_ping_interval_secs: 20
  ws_max_backoff_secs: 60

storage:
  paper_db: paper_trading.db
  live_db: live_trading.db
  audit_db: audit.db
  log_max_bytes: 104857600    # 100 MB
  log_backup_count: 4
```

---

## Documentation

| File | Contents |
|---|---|
| [plan.md](plan.md) | Architecture, decision cycle, LLM prompts, indicator scoring, CLI architecture, database design, full config reference |
| [business-requirement.md](business-requirement.md) | Full BRD — functional requirements, NFRs, business rules, acceptance criteria, risks, glossary |
