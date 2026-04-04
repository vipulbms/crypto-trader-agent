# Kryptos — AI Crypto Trading Agent

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
- **Early sell guardrails (critical):** agent cannot call `propose_sell` unless P&L > +2%; for early TP capture, position must be at ≥80% of TP target with confirmed reversal
- Fallback model configured in `config.yaml → llm.fallback_model` if primary times out

### Paper Broker
- `place_order()`: applies entry slippage (0.05%), deducts `actual_cost + fee_usd` from cash
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
| RAILS/USD | 20% | High volatility |
| AVAX/USD | 12% | |
| SUI/USD | 16% | |
| HYPE/USD | 20% | |
| UNI/USD | 12% | |
| INJ/USD | 16% | |

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

---

## Known Behaviours / Gotchas

- **Realized P&L at TP is slightly below configured %**: exit slippage (0.05%) + exit fee (0.26%) reduce net proceeds by ~0.31%. This is intentional simulation of real trading costs.
- **`usd_value` ≠ cash deducted**: `usd_value` in DB = entry cost only; actual cash deducted = entry cost + entry fee. The fee is shown in Telegram notifications but not in `paper_positions.usd_value`.
- **`agent_sell` vs `take_profit`**: `exit_reason` in DB distinguishes LLM-initiated sells from automatic TP hits. If you see small-gain exits, check if `exit_reason = agent_sell` — means the LLM sold early.
- **Cycle interval**: 30 minutes. SL/TP checks happen every cycle start, not on every price tick. Price can blow past SL between cycles without firing.
- **caution_factor is code-enforced**: In bearish regime, `portfolio["max_per_trade"]` is scaled by 0.5 in `main.py` before the LLM cycle. The LLM cannot exceed this cap even if it ignores the prompt warning.
- **Dynamic TP is now order-level**: `TradingTools.propose_buy()` uses ATR/BB-adjusted TP from `ai_context["dynamic_tp_values"]` instead of static config. Falls back to static if `dynamic_tp.enabled: false` or pair not in values. Logged as `[DYNAMIC_TP]`.
- **deepseek-r1 `<think>` blocks**: deepseek-r1 emits chain-of-thought `<think>…</think>` before its response. Ollama strips these before populating `msg.tool_calls`, so tool dispatch is unaffected. If you see verbose `content` in debug logs, that's the reasoning block.
- **Live broker parity**: `KrakenClient` now has the same interface as `PaperBroker` — `get_balance()`, `get_open_positions()`, `close_position()`, `check_stops_and_tp()` all implemented. Positions are tracked in `live_trading.db` (same SQLite pattern as paper mode).
- **Volatility-Adaptive Limits**: The system no longer uses naive market orders. `KrakenClient` and `PaperBroker` now execute `Limit` orders on the bid to save on spread. These limit entries are gated by positive **Order Book Imbalance (OBI)** monitored in real-time.
