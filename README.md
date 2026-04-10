# Kryptos — AI Crypto Trading Agent

> An autonomous, institutional-grade AI crypto trading agent for Kraken. Paper-trades with a $1,000 virtual balance. Every decision — including every HOLD — is logged with full LLM reasoning. Controlled via a natural-language CLI.

---

## Features

- **AI-powered decisions** — any LLM with tool-calling support (Gemini, Ollama/Qwen, DeepSeek, etc.) decides BUY/SELL/HOLD; signal scores and portfolio context are injected at runtime
- **Quantitative signal scoring** — multi-indicator confluence scoring (RSI, MACD, Bollinger Bands, EMA 9/21/50, ATR, OBI, Fear & Greed); no single indicator triggers a trade
- **Capital-first risk rules** — 5% stop-loss, ATR-adjusted take-profit (5/8/12/16/20%), max 30% per trade; enforced by deterministic Python — the LLM cannot override
- **Minimum profit floor** — 1.0% PNL required to close a position; prevents net losses from Kraken fees
- **Circuit breaker** — 3 consecutive stop-losses within 4 hours pauses all new buys automatically
- **Global kill switch** — 7% portfolio drawdown triggers emergency market-sell of all open positions
- **Liquidity filters** — time-of-day filter (configurable UTC window) and volume dead zone (50% of 20-period SMA) block entries in illiquid conditions
- **Post-Only Maker limit orders** — live mode uses limit chasing (60-second window) to qualify for Kraken maker fees; falls back to market order on timeout
- **Order Book Imbalance (OBI) gate** — live real-time bid/ask pressure blocks entry when selling pressure dominates
- **ATR-proportional position sizing** — position size scales with signal strength and inverse ATR volatility; configured as a percentage of portfolio
- **Dynamic take-profit** — TP levels adjust per trade using ATR and Bollinger Band width instead of fixed percentages
- **Full audit trail** — every cycle, signal, LLM decision, risk verdict, trade, and balance snapshot logged to SQLite
- **Natural-language CLI** — ask `show last 5 BTC trades with reasoning` or `why did it hold ETH?` in plain English
- **Paper and live mode parity** — identical interface and feature set between `PaperBroker` and `KrakenClient`
- **Telegram alerts** — trade fills, errors, daily summary, hourly heartbeat, 6-hour P&L report; optional
- **Healthcheck webhook** — pings a URL (e.g. healthchecks.io) after every successful cycle for uptime monitoring

---

## Trading Pairs & Targets

| Pair | Take-Profit | Stop-Loss | Notes |
|---|---|---|---|
| BTC/USD | 8% | 5% | Slow mover; conservative target |
| ETH/USD | 12% | 5% | Moderate volatility |
| BNB/USD | 12% | 5% | Similar profile to ETH |
| SOL/USD | 16% | 5% | High volatility — larger swings achievable |
| XRP/USD | 12% | 5% | News-driven spikes |
| TRX/USD | 12% | 5% | Mid-tier altcoin |
| DOGE/USD | 20% | 5% | Meme-driven; can swing 20–30% in hours |
| ADA/USD | 12% | 5% | Moderate volatility |
| LTC/USD | 12% | 5% | Follows BTC with 1.5–2× amplification |
| RAILS/USD | 20% | 5% | **Disabled** — 25% win rate, 3/4 stop losses |
| AVAX/USD | 12% | 5% | High volatility L1 |
| SUI/USD | 20% | 5% | High-beta L1, aggressive swings |
| HYPE/USD | 20% | 5% | High volatility DeFi token |
| UNI/USD | 12% | 5% | DeFi blue chip |
| INJ/USD | 20% | 5% | DeFi/L1 hybrid, wide swings |
| WIF/USD | 20% | 5% | Solana meme coin |
| TON/USD | 16% | 5% | Telegram blockchain |
| OP/USD | 16% | 5% | Optimism L2 |
| ARB/USD | 16% | 5% | Arbitrum L2 |
| JUP/USD | 20% | 5% | Jupiter DEX aggregator (Solana) |
| PEPE/USD | 20% | 5% | Extreme meme coin |
| TIA/USD | 20% | 5% | Celestia modular blockchain |
| RENDER/USD | 16% | 5% | AI GPU compute network |
| FET/USD | 16% | 5% | ASI Alliance AI token |
| STX/USD | 16% | 5% | Bitcoin L2 (Stacks) |

Take-profit is ATR-adjusted per trade (see Dynamic TP below). The values above are the static fallback.

---

## Prerequisites

### 1. Python environment

```bash
cd /path/to/crypto-trader-agent
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. LLM provider (choose one)

**Option A — Gemini (recommended, no GPU required):**

```bash
# Set your Gemini API key in .env
GEMINI_API_KEY=your_key_here
```

Config in `config.yaml` (already default):
```yaml
llm:
  provider: openai_compat
  model: gemini-2.5-flash
  base_url: https://generativelanguage.googleapis.com/v1beta/openai/
  api_key_env: GEMINI_API_KEY
```

**Option B — Local Ollama (air-gapped, no API cost):**

```bash
brew install ollama
ollama serve                        # keep running in a separate terminal
ollama pull qwen2.5:7b              # or any model with tool-calling support
```

Any model with function/tool-calling support works (Qwen, Gemini, etc.). Set in `config.yaml`:
```yaml
llm:
  provider: ollama
  model: qwen2.5:7b
  base_url: http://localhost:11434
```

### 3. Environment variables

```bash
KRAKEN_API_KEY=your_key_here        # live mode only
KRAKEN_API_SECRET=your_secret_here  # live mode only
GEMINI_API_KEY=your_key_here        # if using Gemini
TELEGRAM_BOT_TOKEN=your_bot_token   # optional
TELEGRAM_CHAT_ID=your_chat_id       # optional
```

---

## Quick Start — Paper Trading

```bash
# Terminal 1: if using Ollama
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

## Claude Code Skills

Kryptos ships with project-level Claude Code skills in `.claude/skills/`. These are invoked directly inside a Claude Code or GitHub Copilot agent session.

### `/add-pair`

Adds a new trading pair end-to-end in one command. Updates all required files automatically.

```
/add-pair PEPE/USD 20
/add-pair LINK/USD 12
```

What it does:
1. Adds the pair and take-profit % to `config.yaml`
2. Adds the Kraken WebSocket and REST name mappings to `websocket_feed.py`
3. Adds the ccxt pair name to `kraken_client.py`
4. Updates the welcome screen in `display.py`
5. Updates README, `plan.md`, `docs/codebase.md`

Take-profit must be one of: `5`, `8`, `12`, `16`, `20`. Stop-loss is always fixed at `5%`.

Restart the agent after adding a pair for it to take effect.

---

### `/trading-rules`

Loaded automatically into the system prompt at agent startup. Defines all hard constraints the LLM must respect:
- Position sizing formula
- SL/TP formula and floor
- Limit order behaviour
- OBI gate
- Max positions and cash reserve
- Daily loss halt and profit floor

Source: `.claude/skills/trading-rules/SKILL.md`

---

### `/commit`

Commits and pushes changes to GitHub. Automatically derives a commit message from the diff, or accepts a custom subject line.

```
/commit
/commit fix daily loss limit bug
```

What it does:
1. Reviews changed files and stages only source files (`.py`, `.yaml`, `.md`, `.txt`, skill files)
2. Never stages `.env`, `data/`, `logs/`, or `__pycache__`
3. Updates `CHANGELOG.md` with a summary of the changes
4. Updates the session memory with any new conventions or decisions
5. Derives a conventional commit message (`fix:`, `feat:`, `docs:`, `refactor:`) from the diff, or uses your message
6. Commits and pushes to `main`

---

## How the Agent Decides

Every 15 minutes:

1. **WebSocket** delivers latest 15-min candles (300-candle rolling buffer per pair) + real-time OBI (Order Book Imbalance)
2. **`compute_indicators()`** — RSI(14), MACD(12/26/9), Bollinger Bands(50,2), EMA-9/21/50, ATR(14), Volume SMA(20), MACD histogram turn detection
3. **Fear & Greed Index** fetched once per cycle and injected into each pair's indicator dict
4. **`generate_signal()`** — confluence scoring (0–16 pts per pair); hard vetoes: RSI ≥ 70, OBI < 0, price < EMA50, volume < 50% SMA, ATR-derived TP below profit floor; `buy_min_score: 5` required
5. **`build_cycle_prompt()`** — injects portfolio state, SKILL.md trading rules, and all pair scores into a single LLM context (~1,200 tokens for 24 pairs)
6. **LLM** (Gemini/Ollama) called once per cycle; must call `propose_buy`, `propose_sell`, or `hold` tool; top-3 buy signals only
7. **`RiskManager.validate_buy()`** — deterministic Python veto layer: circuit breaker, kill switch, time-of-day window, volume dead zone, fat finger guard ($5 min, 98% cash buffer), portfolio cap (30%), max open positions (5), cash reserve (10%)
8. **`RiskManager.validate_sell()`** — blocks early exits below 1.0% profit floor
9. **`PaperBroker`** or **`KrakenClient`** executes: limit order with 60-second chase (live), simulated fill (paper)
10. **`AuditLogger`** records everything — cycle, signal, LLM reasoning, risk verdict, fill, balance snapshot

**The LLM proposes; Python decides. The risk manager cannot be overridden by prompt.**

---

## Database Storage

The agent uses three local SQLite databases (defaulting to the `data/` directory) to maintain state, history, and a complete audit trail.

### 1. `audit.db` (The Audit Trail)
This database logs every action, signal, and decision the system makes, regardless of whether it results in a trade.
- **`audit_cycles`**: Records every agent loop iteration (cycle ID, start/end times).
- **`audit_signals`**: Stores the raw technical indicators (RSI, MACD, etc.) and generated signal scores for each pair per cycle.
- **`audit_llm_decisions`**: Logs the exact outputs from the LLM, including its chosen action (BUY/SELL/HOLD) and the full text of its reasoning.
- **`audit_risk_checks`**: Records the Risk Manager's verdict for proposed trades (approved, reduced, or rejected) and the reason why.
- **`audit_orders`**: Logs all orders that are actually sent to the broker/exchange.
- **`audit_fills`**: Records the execution details of those orders, including filled price, fees, and slippage.
- **`audit_position_events`**: Tracks lifecycle events for open positions, such as automatically hitting a Stop-Loss (SL) or Take-Profit (TP).
- **`audit_balance_snapshots`**: Captures regular snapshots of the account's total USD value and cash balance to track portfolio growth.
- **`audit_errors`**: Logs system errors or exceptions for debugging.

### 2. `paper_trading.db` (Virtual Trading State)
This database acts as the virtual exchange when running `main.py --paper`.
- **`paper_wallet`**: Tracks the current virtual cash balance (e.g., USD available to trade).
- **`paper_positions`**: Stores currently open positions, tracking entry price, quantity, and the specific SL/TP levels.
- **`paper_trades`**: The historical ledger of all completed (closed) paper trades.
- **`daily_pnl`**: Tracks the realized Daily Profit and Loss. The system uses this to enforce the daily maximum loss risk rule.

### 3. `live_trading.db` (Live Trading State)
When running in live mode, this database tracks the system's actual real-money exposure to ensure it stays synchronized with Kraken.
- **`live_positions`**: Stores currently active trades executing on Kraken.
- **`live_trades`**: The historical ledger of closed live trades.
- **`daily_pnl`**: Tracks the realized Daily Profit and Loss for the live portfolio.

---

## Technical Indicators Explained

All indicators are computed on **15-minute candles**.

### RSI — "Is the price tired?"

Measures how fast the price moved recently (0–100 scale).
- **RSI < 30** — oversold — BUY hint (+3 pts)
- **RSI 30–40** — mild dip — BUY hint (+1 pt)
- **RSI ≥ 70** — hard veto: BUY blocked entirely
- **RSI > 60** — overbought — SELL hint (+3 pts)

### MACD — "Which way is momentum heading?"

- **Histogram turned positive this candle** — fresh momentum crossover — BUY hint (+3 pts)
- **Histogram > 0** (continuation) — momentum remains bullish — BUY hint (+1 pt)
- **MACD line crossed above signal** — BUY hint (+1 pt)
- **Histogram < 0** — bearish momentum — SELL hint (+2 pts)

`indicators.py` returns both `macd_histogram` (current) and `macd_histogram_prev` (previous candle) to detect a fresh turn.

### Bollinger Bands — "Is the price on sale or overpriced?"

Dynamic price channel; expands in volatility, contracts in calm markets.
- **Price at/near lower band** — BUY hint (+2 pts)
- **Price at/near upper band** — SELL hint (+2 pts)
- **Band width < 0.5% of price** — squeezed bands = noise; BB signals ignored

Period: BB(50) = 12.5 hours. Widened from BB(20) to prevent false signals during band-squeeze.

### EMA Trend Filters

Exponential Moving Averages computed at 9, 21, and 50 candle periods.
- **EMA9 > EMA21** — short-term momentum turning up — BUY hint (+2 pts)
- **Price > EMA50** — medium-term trend support — BUY bonus (+1 pt); **Price < EMA50** is a hard buy veto
- **Price < EMA50** — hard BUY veto (trend is against entry)

### ATR — "How bumpy is the road?"

Average True Range measures typical price swings per candle.
- Used to size positions (smaller in volatile conditions)
- Used for dynamic SL (`min(entry × 0.95, entry − ATR × multiplier)`)
- Used for dynamic TP (`entry + k × ATR` where k = 1.5–4.5×)
- **ATR-based TP < 1.0%** — hard BUY veto (reward too small to cover fees)

### Order Book Imbalance (OBI)

Computed from the live Kraken WebSocket ticker:
$\text{OBI} = \frac{\text{BidVol} - \text{AskVol}}{\text{BidVol} + \text{AskVol}}$

- **OBI < 0** — sell-side pressure dominates — hard BUY veto

### Fear & Greed Index

Fetched once per cycle from alternative.me; injected into all pair signal calculations.
- **Index ≤ 40** (Fear) — BUY hint (+1 pt)
- **Index ≤ 25** (Extreme Fear) — additional BUY hint (+1 pt, stacks)

---

## Signal Scoring

`generate_signal()` awards points across up to 10 contributors. All weights are in `config.yaml → signals:`.

**BUY requires score ≥ 5** (two or more signals must align):

| Condition | Points |
|---|---|
| RSI < 30 (oversold) | +3 |
| RSI 30–40 (mild dip) | +1 |
| MACD histogram turned positive | +3 |
| MACD histogram > 0 (continuation) | +1 |
| MACD line crossed above signal | +1 |
| Price at/near lower Bollinger Band | +2 |
| EMA9 > EMA21 (short-term uptrend) | +2 |
| Price > EMA50 (medium-term support) | +1 |
| Fear & Greed ≤ 40 | +1 |
| Fear & Greed ≤ 25 | +1 |

**Hard BUY vetoes (score ignored entirely):**

| Condition | Reason |
|---|---|
| RSI ≥ 70 | Severely overbought |
| OBI < 0 | Sell-side pressure dominates |
| Price < EMA50 | Below medium-term trend |
| Volume < 50% of SMA(20) | Volume dead zone |
| ATR-based TP < profit floor | Reward too small to cover fees |

**SELL requires score ≥ 3** AND sell score > buy score:

| Condition | Points |
|---|---|
| RSI > 60 (overbought) | +3 |
| MACD histogram < 0 | +2 |
| Price at/near upper Bollinger Band | +2 |

The signal layer only recommends. The LLM makes the final call and can override any BUY with HOLD.

---

## Risk Rules

All enforced by deterministic Python (`RiskManager`) — the LLM never does arithmetic on these values.

| Rule | Value | Notes |
|---|---|---|
| Stop-loss | 5% below entry | Fixed; non-negotiable |
| Take-profit | 5–20% per pair | ATR-adjusted per trade |
| Min profit floor | 1.0% | Covers fees; LLM cannot exit below this |
| Max position size | 30% of portfolio | Hard cap |
| Max open positions | 5 simultaneously | |
| Cash reserve | 10% always liquid | Blocks entry if breached |
| Daily loss limit | −10% of start-of-day balance | Blocks all new buys |
| Global kill switch | −7% portfolio drawdown | Emergency market-sell all positions |
| Circuit breaker | 3 consecutive SLs in 4 hours | Pauses all buys for 4 hours |
| Time-of-day filter | Configurable UTC window | Default: 06:00–23:00 UTC |
| Volume filter | Current vol ≥ 50% of 20-period SMA | Dead zone guard |
| Fat finger | Min order $5; max 98% of available cash | Prevents dust orders and insufficient-funds errors |
| Flash crash | Ignores SL trigger if price moved > 15% | Avoids SL on flash crashes |

---

## Paper vs Live Mode

| Aspect | Paper (`--paper`) | Live (`--live`) |
|---|---|---|
| Kraken private API | Not required | Required |
| Order execution | `PaperBroker` (SQLite simulation) | `KrakenClient` (ccxt) |
| Price feed | Public Kraken WebSocket (real prices) | Same |
| Starting balance | $1,000 virtual | Actual Kraken balance |
| Order type | Market simulation | Post-Only Maker limit, 60s chase, market fallback |
| SL/TP enforcement | Polled each cycle (price-tick based) | Deferred until limit fill confirmed |
| Slippage | 0.05% simulated (entry + exit) | Real fills |
| Fee | 0.16% simulated (Kraken maker) | Real Kraken fees |
| Telegram alerts | `[PAPER]` prefix | `[LIVE]` prefix |
| Live positions DB | `data/paper_trading.db` | `data/live_trading.db` |

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

Run the backtest first:

```bash
python tests/test_backtest.py           # full 12-month candle history
python scripts/audit_rejections.py      # why trades were blocked (layer breakdown)
```

---

## File Structure

```
crypto-trader-agent/
├── kryptos.py                        CLI entry point (REPL + NL + subcommands)
├── main.py                           Agent runner (background process)
├── config.yaml                       ALL tunable parameters — no hardcoded values in code
├── requirements.txt
├── .env                              API keys — never committed
├── .claude/
│   └── skills/
│       ├── add-pair/
│       │   └── SKILL.md             /add-pair skill — onboards new pairs across all files
│       ├── commit/
│       │   └── SKILL.md             /commit skill — stages, commits, pushes to GitHub
│       └── trading-rules/
│           └── SKILL.md             LLM trading constraints — loaded into SYSTEM_PROMPT at runtime
├── docs/
│   ├── business_requirements.md     Formal BRD — 8 FRs, 6 NFRs, bug table, setup guide
│   ├── codebase.md                  Developer reference — all modules, schema, config, patterns
│   ├── how_to_debug.md              Debug guide — trace any trade through 3 audit layers
│   ├── detailed_solution_design.md  Architecture — 10 sections, 9 Mermaid diagrams, 7 ADRs
│   ├── epics_stories_ac.md          11 Epics, 40+ Stories, Gherkin ACs, traceability matrix
│   └── sessions/                    Per-session change notes
├── history/                          12-month OHLCV candle JSON files (for backtesting)
├── logs/                             Created at runtime
│   └── agent.log                    Rotating log (100 MB max, 4 backups)
├── data/                             Created at runtime
│   ├── paper_trading.db
│   ├── live_trading.db
│   └── audit.db
├── scripts/
│   ├── audit_rejections.py          Post-backtest diagnostic — why trades were blocked
│   ├── daily_report.py              Print daily P&L summary
│   └── review.py                    Candle and signal review tool
├── tests/
│   ├── test_backtest.py             Full strategy backtest against 12-month candle history
│   ├── test_circuit_breaker.py      Circuit breaker unit tests
│   ├── test_indicators.py           Indicator computation unit tests
│   ├── test_regime_and_dynamic_tp.py  Regime + dynamic TP unit tests
│   ├── test_risk_manager.py         Risk manager unit tests
│   └── trades_to_candle_converter.py  Convert Kraken trade CSVs to OHLCV candle JSON
└── src/
    ├── agent/                        LLM prompts, tool definitions, TradingAgent
    ├── analysis/                     Indicators (ta library) + signal scorer + features
    ├── cli/                          NLParser · commands · display · agent_manager
    ├── exchange/                     WebSocket feed · KrakenClient · PaperBroker
    ├── notifications/                Telegram notifier + healthcheck webhook
    ├── reports/                      trade_report.py — P&L and trade history queries
    ├── risk/                         RiskManager — deterministic Python rules
    ├── storage/                      SQLite schema + append-only audit logger
    └── utils/                        tz.py (SGT timezone) · timing.py (@timed decorator)
```

---

## Configuration (`config.yaml`)

**Every parameter is in `config.yaml`. No hardcoded values exist in any source file.**

Key sections:

```yaml
trading:
  stop_loss_pct: 5
  min_profit_floor_pct: 1.0       # Min PNL to allow a close (covers fees/slippage)
  take_profit_pct: 8              # Global default; overridden per pair
  allowed_take_profit_pcts: [5, 8, 12, 16, 20]
  max_position_pct: 30
  max_open_positions: 5
  cycle_interval_minutes: 15
  allowed_trading_hours:
    enabled: true
    start_hour_utc: 06
    end_hour_utc: 23
    min_volume_ratio: 0.5         # Block if vol < 50% of SMA(20)

paper:
  starting_balance_usd: 1000
  slippage_pct: 0.05
  maker_fee_pct: 0.16             # Kraken maker fee simulation

indicators:
  rsi_period: 14
  rsi_oversold: 30
  rsi_overbought: 60
  macd_fast: 12 / macd_slow: 26 / macd_signal: 9
  bb_period: 50 / bb_std: 2 / bb_min_width_pct: 0.5
  ema_fast: 9 / ema_medium: 21 / ema_slow: 50
  atr_period: 14
  candle_buffer_size: 300
  min_candles_to_start: 220

signals:
  buy_min_score: 5                # Two or more signals must align
  sell_min_score: 3

llm:
  provider: openai_compat         # or ollama
  model: gemini-2.5-flash
  base_url: https://generativelanguage.googleapis.com/v1beta/openai/
  timeout_seconds: 60

risk:
  daily_loss_limit_pct: 10        # Blocks all new buys
  global_max_daily_loss_pct: 7.0  # Kill switch — emergency sell-all
  min_cash_reserve_pct: 10
  min_order_usd: 5.0
  flash_crash_tolerance_pct: 15.0
  circuit_breaker:
    enabled: true
    consecutive_stops: 3
    pause_hours: 4

position_sizing:
  enabled: true
  base_position_pct: 20
  min_position_pct: 5
  max_position_pct: 30

dynamic_tp:
  enabled: true
  atr_multiplier: 2.0
  min_tp_pct: 5 / max_tp_pct: 20

notifications:
  telegram_enabled: true
  heartbeat_interval_minutes: 60
  healthcheck_url: ""             # e.g. https://hc-ping.com/your-uuid
```

---
## Documentation

| Document | File | Contents |
|---|---|---|
| Business Requirements | [docs/business_requirements.md](docs/business_requirements.md) | Formal BRD — 8 FRs, 6 NFRs, bug resolution table, setup guide |
| Codebase Reference | [docs/codebase.md](docs/codebase.md) | Developer guide — all modules, schema, config reference, design patterns |
| Debugging Guide | [docs/how_to_debug.md](docs/how_to_debug.md) | Trace any trade through 3 audit layers; SQL snippets; live vs paper |
| Detailed Solution Design | [docs/detailed_solution_design.md](docs/detailed_solution_design.md) | Architecture — 10 sections, 9 Mermaid diagrams, LLM architecture deep-dive, 7 ADRs |
| Epics, Stories & AC | [docs/epics_stories_ac.md](docs/epics_stories_ac.md) | 11 Epics, 40+ User Stories with Gherkin Acceptance Criteria, traceability matrix |
| Trading Rules SKILL | [.claude/skills/trading-rules/SKILL.md](.claude/skills/trading-rules/SKILL.md) | LLM hard constraints loaded into SYSTEM_PROMPT at agent startup |
| Add Pair SKILL | [.claude/skills/add-pair/SKILL.md](.claude/skills/add-pair/SKILL.md) | `/add-pair` skill — onboards a new trading pair across all required files |
| Commit SKILL | [.claude/skills/commit/SKILL.md](.claude/skills/commit/SKILL.md) | `/commit` skill — stages, commits, and pushes changes safely |
| Changelog | [CHANGELOG.md](CHANGELOG.md) | Per-session feature log |

### Session Notes

Development history is documented in `docs/sessions/`. Each file covers one session's changes:

| File | Summary |
|---|---|
| [session_2026_03_30b–d](docs/sessions/session_2026_03_30b.md) | Early architecture, WebSocket feed, paper broker |
| [session_2026_03_31a](docs/sessions/session_2026_03_31a.md) | LLM INFO logging; TP tuning |
| [session_2026_03_31b](docs/sessions/session_2026_03_31b.md) | Multi-pair ranked prompt; signal confluence |
| [session_2026_03_31c](docs/sessions/session_2026_03_31c.md) | Position sizing; regime detection |
| [session_2026_03_31d](docs/sessions/session_2026_03_31d.md) | Dynamic TP; sentiment; pattern analysis |
| [session_2026_03_31e](docs/sessions/session_2026_03_31e.md) | Exit timing; post-trade analysis |
| [session_2026_03_31f](docs/sessions/session_2026_03_31f.md) | Timeout handling across LLM/DB/WebSocket |
| [session_2026_03_31g](docs/sessions/session_2026_03_31g.md) | Telegram: add invested USD amount |
| [session_2026_03_31h](docs/sessions/session_2026_03_31h.md) | Balance mismatch fix; SL priority; early-sell guardrails |
| [session_2026_04_01a](docs/sessions/session_2026_04_01a.md) | caution_factor code-enforced; dynamic TP wired; 18 tests added |
| [session_2026_04_01b](docs/sessions/session_2026_04_01b.md) | LLM switched to deepseek-r1:7b; KrakenClient live broker parity rewrite |
| [session_2026_04_01c](docs/sessions/session_2026_04_01c.md) | Backtesting pipeline added; 7.5-day backtest run and reported |
| [session_2026_04_04a](docs/sessions/session_2026_04_04a.md) | Volatility-Adaptive Quant Migration; OBI; Limit orders |
| [session_2026_04_05a](docs/sessions/session_2026_04_05a.md) | Minimum Profit Floor; extracted trading rules to SKILL.md |
| [session_2026_04_05b](docs/sessions/session_2026_04_05b.md) | Multi-indicator confluence scoring; circuit breaker; heartbeat |
| [session_2026_04_05c](docs/sessions/session_2026_04_05c.md) | Live API limit orders / fallbacks; 2-hour heartbeat; 6-hour P&L report |
| [session_2026_04_05d](docs/sessions/session_2026_04_05d.md) | Post-only limit chase; volume/time-of-day filters; healthcheck webhook |
| [session_2026_04_05e](docs/sessions/session_2026_04_05e.md) | Global kill switch (−7% drawdown); backtest clean-slate; audit_rejections.py |
| [session_2026_04_05f](docs/sessions/session_2026_04_05f.md) | Documentation: BRD, Detailed Design, Epics/Stories/AC |

---

## Known Behaviours

- **Realized P&L at TP is slightly below configured %** — exit slippage (0.05%) + exit fee (~0.16%) reduce net proceeds. This is intentional simulation of real trading costs.
- **`usd_value` ≠ cash deducted** — `usd_value` in DB = entry cost only; actual cash deducted = entry cost + entry fee.
- **`agent_sell` vs `take_profit`** — `exit_reason` in the DB distinguishes LLM-initiated sells from automatic TP hits.
- **SL/TP polled, not streamed** — in paper mode, SL/TP fire when `current_price` crosses the stored level at cycle start. Price can gap past SL between cycles.
- **Cycle interval: 15 minutes** — by default; set in `config.yaml → trading.cycle_interval_minutes`.
- **Reasoning model `<think>` blocks** — some models (e.g. DeepSeek-R1, QwQ) emit chain-of-thought blocks before their response. Ollama strips these before populating `msg.tool_calls`, so tool dispatch is unaffected.
- **Heartbeat (live mode only)** — sends a Telegram summary every 60 minutes: balance, hourly P&L, cycles, buys/sells, circuit breaker state.
