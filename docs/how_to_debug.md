# Debugging a Trade — Kryptos

This guide walks through the full diagnostic sequence for investigating why a trade did or did not execute in **paper mode** and **live mode**. Use it whenever you need to explain why the agent bought, sold, didn't buy, or closed at an unexpected price.

---

## Table of Contents

1. [Prerequisites](#1-prerequisites)
2. [Understanding the Three Audit Layers](#2-understanding-the-three-audit-layers)
3. [Debugging: Why Did a BUY Not Execute?](#3-debugging-why-did-a-buy-not-execute)
4. [Debugging: Why Did a SELL / Close Happen?](#4-debugging-why-did-a-sell--close-happen)
5. [Debugging: Wrong Entry or Exit Price](#5-debugging-wrong-entry-or-exit-price)
6. [Debugging: PNL Looks Wrong](#6-debugging-pnl-looks-wrong)
7. [Debugging: Agent Appears Stuck / Silent](#7-debugging-agent-appears-stuck--silent)
8. [Live-Mode–Specific Checks](#8-live-mode-specific-checks)
9. [Useful SQL Snippets](#9-useful-sql-snippets)
10. [Scripts for Automated Analysis](#10-scripts-for-automated-analysis)
11. [Log File Reference](#11-log-file-reference)

---

## 1. Prerequisites

```bash
# SQLite CLI (for DB inspection)
which sqlite3

# All databases live in data/
ls data/
# paper_trading.db  — positions & closed trades (paper)
# live_trading.db   — positions & closed trades (live)
# audit.db          — full audit trail (both modes)

# Log file
tail -f logs/agent.log
```

All timestamps are in **SGT (UTC+8)** inside the DB. Convert to UTC by subtracting 8 hours if comparing to Kraken timestamps.

---

## 2. Understanding the Three Audit Layers

Every cycle writes to three layers in `audit.db`. Debugging always follows the same order:

```
[Layer 1] audit_signals         — did the indicator engine produce a BUY signal?
[Layer 2] audit_llm_decisions   — did the LLM call the propose_buy tool?
[Layer 3] audit_risk_checks     — did the risk manager approve the trade?
           audit_orders         — was the order submitted to the broker?
           audit_fills          — did the order fill?
```

If the answer at any layer is "no", that is where the trade was blocked.

---

## 3. Debugging: Why Did a BUY Not Execute?

### Step 1 — Find the relevant cycle

```sql
-- Open audit.db
sqlite3 data/audit.db

-- List recent cycles (newest first)
SELECT id, cycle_at, portfolio_balance_usd, available_cash_usd, open_positions_count
FROM audit_cycles
ORDER BY id DESC
LIMIT 20;
```

Note the `id` of the cycle you are investigating (e.g. `42`).

---

### Step 2 — Check what signal was generated (Layer 1)

```sql
-- Signals for cycle 42, for a specific pair
SELECT pair, price, signal_direction, signal_strength, signal_reasons
FROM audit_signals
WHERE cycle_id = 42;
```

**What to look for:**

| `signal_direction` | Meaning |
|---|---|
| `HOLD` | Signal engine blocked the pair — reasons explain why |
| `BUY` | Pair passed signals; look at Layer 2 |
| `SELL` | Pair had a sell signal |

If `signal_direction = 'HOLD'`, read `signal_reasons` (stored as JSON array). Common blockers:

- `"BLOCKED: RSI >= 70"` — overbought veto
- `"BLOCKED: Volume below 50% SMA"` — Volume Dead Zone
- `"BLOCKED: OBI < 0"` — order book imbalance
- `"BLOCKED: Price < EMA50"` — below medium-term trend
- `"BLOCKED: ATR TP < profit floor"` — volatility too low to cover fees
- `"BUY score X < min Y"` — confluence score insufficient; individual reasons listed

---

### Step 3 — Check what the LLM decided (Layer 2)

```sql
-- LLM decisions for cycle 42
SELECT pair, decision_type, tool_called, hold_reason, tool_args
FROM audit_llm_decisions
WHERE cycle_id = 42;
```

**What to look for:**

| `tool_called` | Meaning |
|---|---|
| `hold` | LLM chose not to act; `hold_reason` explains |
| `propose_buy` | LLM called buyfor this pair; check Layer 3 |
| `propose_sell` | LLM called sell; check Layer 3 |

If the LLM said `hold` but the signal was `BUY`, the LLM was unimpressed by the signal's context or preferred another pair in the same cycle (max 2 buys per cycle).

To see the full LLM reasoning:

```sql
SELECT raw_llm_output FROM audit_llm_decisions
WHERE cycle_id = 42 AND pair = 'SOL/USD';
```

---

### Step 4 — Check the risk manager decision (Layer 3)

```sql
-- Risk checks linked to LLM decisions in cycle 42
SELECT rc.proposed_pair, rc.proposed_usd_amount, rc.approved,
       rc.rejection_reason, rc.adjusted_usd_amount
FROM audit_risk_checks rc
JOIN audit_llm_decisions ld ON rc.llm_decision_id = ld.id
WHERE ld.cycle_id = 42;
```

**Common rejection reasons:**

| Message | Root cause |
|---|---|
| `Time-of-Day Guard: hour XX outside 16:00-20:00 UTC` | Trade attempted outside allowed hours |
| `Circuit breaker active — 3 consecutive stop-losses` | 3 SLs hit in past 4 hours |
| `Daily loss limit reached: X% >= 10%` | Daily drawdown limit enforced |
| `Max open positions reached (3/3)` | Already at cap |
| `Insufficient cash reserve` | Less than 10% of portfolio in cash |
| `Proposed USD below minimum order size ($5)` | Amount too small |
| `Risk Guard: Proposed USD exceeds 98% safe buffer` | Fat finger guard |

---

### Step 5 — Check the order submission

```sql
-- Orders submitted in cycle 42
SELECT ao.pair, ao.side, ao.role, ao.status, ao.requested_price,
       ao.paper_fill_price, ao.error_message
FROM audit_orders ao
JOIN audit_risk_checks rc ON ao.risk_check_id = rc.id
JOIN audit_llm_decisions ld ON rc.llm_decision_id = ld.id
WHERE ld.cycle_id = 42;
```

**Order status values:**

| `status` | Meaning |
|---|---|
| `simulated` | Paper mode — order processed virtually |
| `submitted` | Live mode — order sent to Kraken |
| `failed` | Order failed; see `error_message` |

---

### Quick "why no buy?" diagnostic query

```sql
-- Show all HOLD signals + risk rejections in the last 5 cycles
SELECT c.id as cycle_id, c.cycle_at, s.pair,
       s.signal_direction, s.signal_strength,
       ld.tool_called, rc.approved, rc.rejection_reason
FROM audit_cycles c
JOIN audit_signals s ON s.cycle_id = c.id
LEFT JOIN audit_llm_decisions ld ON ld.cycle_id = c.id AND ld.pair = s.pair
LEFT JOIN audit_risk_checks rc ON rc.llm_decision_id = ld.id
WHERE c.id IN (SELECT id FROM audit_cycles ORDER BY id DESC LIMIT 5)
ORDER BY c.id DESC, s.pair;
```

---

## 4. Debugging: Why Did a SELL / Close Happen?

### Determine the exit reason

```sql
-- Paper mode
sqlite3 data/paper_trading.db

SELECT pair, opened_at, closed_at, entry_price, exit_price,
       pnl_pct, exit_reason, hold_duration_secs
FROM paper_trades
ORDER BY closed_at DESC
LIMIT 10;
```

**`exit_reason` values:**

| Value | Triggered by |
|---|---|
| `take_profit` | `check_stops_and_tp()` — price reached full TP level |
| `partial_take_profit` | `check_stops_and_tp()` — partial TP triggered (50% of position closed at 50% of TP target) |
| `trailing_stop` | `check_stops_and_tp()` — trailing SL was raised above hard floor and then hit; typically a profitable exit |
| `stop_loss` | `check_stops_and_tp()` — price dropped to the original hard SL floor |
| `agent_sell` | LLM called `propose_sell` and risk manager approved |
| `kill_switch` | Global kill switch fired (daily drawdown ≥ 7%) |
| `fallback_stop_loss` | Live mode: native SL order failed; market sell used |
| `backtest_end` | Backtest finished — position force-closed at final candle price (mark-to-market) |

---

### Verify SL/TP levels that were used

```sql
-- Paper: check the position's configured levels at entry
SELECT pair, entry_price, stop_loss_price, take_profit_price,
       stop_loss_pct, take_profit_pct, opened_at
FROM paper_positions
WHERE status = 'closed'
ORDER BY id DESC
LIMIT 5;
```

Expected relationships:
- `stop_loss_price = entry_price × (1 − stop_loss_pct / 100)` (default: 5%)
- `take_profit_price = entry_price × (1 + take_profit_pct / 100)` (pair-specific)

---

### Trace the position lifecycle event

```sql
-- In audit.db — full event log
sqlite3 data/audit.db

SELECT event_at, pair, event_type, entry_price, exit_price,
       pnl_pct, hold_duration_seconds
FROM audit_position_events
WHERE pair = 'SOL/USD'
ORDER BY event_at DESC
LIMIT 5;
```

Event types: `opened`, `stop_loss_triggered`, `take_profit_triggered`, `manually_closed`.

---

### Check if the LLM initiated the sell (agent_sell)

```sql
-- Find the LLM decision that triggered a sell
SELECT ld.decided_at, ld.pair, ld.decision_type, ld.hold_reason,
       ld.raw_llm_output, rc.approved, rc.rejection_reason
FROM audit_llm_decisions ld
LEFT JOIN audit_risk_checks rc ON rc.llm_decision_id = ld.id
WHERE ld.tool_called = 'propose_sell'
ORDER BY ld.decided_at DESC
LIMIT 10;
```

If `rc.approved = 0`, the profit floor blocked the early sell. The `rejection_reason` will say: `"Minimum Profit Floor Guardrail: Projected PNL is +X.XX%, which is below the 1.0% required"`.

---

## 5. Debugging: Wrong Entry or Exit Price

### Paper mode

Paper broker applies deterministic slippage and fees:

- **Entry:** `fill_price = current_price × (1 + slippage_pct / 100)` (default 0.05%)
- **Exit:** `fill_price = current_price × (1 − slippage_pct / 100)` (default 0.05%)
- **Fee:** 0.16% Maker fee at entry and exit

```sql
-- Check fill details
sqlite3 data/audit.db

SELECT af.fill_price, af.fill_volume, af.fill_usd_value,
       af.fee_usd, af.slippage_pct, ao.role, ao.pair
FROM audit_fills af
JOIN audit_orders ao ON af.order_id = ao.id
WHERE ao.pair = 'ETH/USD'
ORDER BY af.filled_at DESC
LIMIT 10;
```

### Live mode

```sql
-- Live: check exchange order IDs for Kraken reconciliation
sqlite3 data/live_trading.db

SELECT pair, entry_order_id, exit_order_id, entry_price, exit_price, pnl_pct
FROM live_trades
ORDER BY closed_at DESC
LIMIT 5;
```

Use the `entry_order_id` / `exit_order_id` to look up the order in Kraken's history at:  
`https://www.kraken.com/u/history/trades`

---

## 6. Debugging: PNL Looks Wrong

**Expected round-trip cost:** ~0.32% (entry fee 0.16% + exit fee 0.16%) + ~0.10% slippage = ~0.42% total drag.

A trade that hits TP at +8% should net approximately **+7.6%** in paper mode.

```sql
-- Detailed PNL breakdown for closed paper trades
sqlite3 data/paper_trading.db

SELECT pair, entry_price, exit_price, volume, usd_invested,
       fee_usd, pnl_usd, pnl_pct, exit_reason
FROM paper_trades
ORDER BY closed_at DESC
LIMIT 10;
```

Note: `usd_value` in `paper_positions` = entry cost only. Cash actually deducted = entry cost + entry fee. The fee appears in `audit_fills.fee_usd`.

For running unrealised P&L, check balance snapshots:

```sql
sqlite3 data/audit.db

SELECT snapshot_at, total_usd, cash_usd, unrealised_pnl_usd
FROM audit_balance_snapshots
WHERE mode = 'paper'
ORDER BY snapshot_at DESC
LIMIT 10;
```

---

## 7. Debugging: Agent Appears Stuck / Silent

### Check if agent is running

```bash
# Look for the main.py process
ps aux | grep "main.py"
```

### Check last cycle timestamp

```sql
sqlite3 data/audit.db

SELECT id, cycle_at, cycle_duration_ms FROM audit_cycles
ORDER BY id DESC LIMIT 5;
```

If the last cycle is older than the cycle interval (default 15 min), the agent has stalled.

### Check for errors

```sql
SELECT error_at, component, error_type, error_message
FROM audit_errors
ORDER BY error_at DESC
LIMIT 20;
```

### Tail the log file

```bash
tail -100 logs/agent.log | grep -E "ERROR|WARNING|CIRCUIT|KILL"
```

### Circuit breaker status

```sql
-- paper mode: look at last 3 trades
sqlite3 data/paper_trading.db

SELECT pair, exit_reason, closed_at FROM paper_trades
ORDER BY closed_at DESC
LIMIT 3;
```

If all 3 are `stop_loss` and all occurred within the last 4 hours (sgtt), the circuit breaker is active and no buys will be placed.

### Kill switch status

```bash
# Check if kill switch fired today
grep "KILL SWITCH" logs/agent.log | tail -5
```

The kill switch fires when daily drawdown ≥ 7% (configurable in `config.yaml → risk.kill_switch.daily_drawdown_pct`). It closes all positions and halts the agent loop for the rest of the day.

---

## 8. Live-Mode–Specific Checks

### Check open positions on Kraken vs DB

```sql
-- What Kryptos thinks is open
sqlite3 data/live_trading.db

SELECT pair, entry_price, stop_loss_price, take_profit_price,
       entry_order_id, stop_loss_order_id, take_profit_order_id,
       opened_at
FROM live_positions
WHERE status = 'open';
```

Cross-reference `entry_order_id` with Kraken's order history. If the order is missing on Kraken, the fill was not confirmed and the position is stale.

### Verify SL/TP orders on Kraken

The `stop_loss_order_id` and `take_profit_order_id` columns store the Kraken order IDs for active SL/TP orders. Search these in Kraken's Open Orders tab. If they are missing, the deferred SL/TP placement may have failed — check `audit_errors`:

```sql
sqlite3 data/audit.db

SELECT error_at, component, error_type, error_message
FROM audit_errors
WHERE component LIKE '%kraken%' OR component LIKE '%order%'
ORDER BY error_at DESC
LIMIT 10;
```

### Limit order chase diagnostic

In live mode, unfilled limit orders are cancelled and re-submitted after 60 seconds. To see if this happened:

```bash
grep "chase" logs/agent.log | tail -20
```

Or in the audit:

```sql
sqlite3 data/audit.db

SELECT submitted_at, pair, order_type, status, error_message
FROM audit_orders
WHERE mode = 'live'
ORDER BY submitted_at DESC
LIMIT 20;
```

If you see multiple rows for the same `pair` / `role='entry'` close in time, the chase logic fired.

---

## 9. Useful SQL Snippets

### All closed trades (paper) sorted by P&L

```sql
sqlite3 data/paper_trading.db

SELECT pair, pnl_pct, pnl_usd, exit_reason, opened_at, closed_at
FROM paper_trades
ORDER BY pnl_pct DESC;
```

### Win rate and average P&L

```sql
sqlite3 data/paper_trading.db

SELECT
  COUNT(*) AS total_trades,
  SUM(CASE WHEN pnl_usd > 0 THEN 1 ELSE 0 END) AS wins,
  ROUND(100.0 * SUM(CASE WHEN pnl_usd > 0 THEN 1 ELSE 0 END) / COUNT(*), 1) AS win_rate_pct,
  ROUND(AVG(pnl_pct), 2) AS avg_pnl_pct,
  ROUND(SUM(pnl_usd), 2) AS total_pnl_usd
FROM paper_trades;
```

### Indicator values at a specific cycle for a pair

```sql
sqlite3 data/audit.db

SELECT pair, rsi_14, macd_histogram, ema_20, ema_50,
       bb_lower, bb_upper, atr_14, signal_direction, signal_strength
FROM audit_signals
WHERE cycle_id = 42 AND pair = 'SOL/USD';
```

### All rejected buy proposals

```sql
sqlite3 data/audit.db

SELECT rc.checked_at, ld.pair, rc.proposed_usd_amount, rc.rejection_reason
FROM audit_risk_checks rc
JOIN audit_llm_decisions ld ON rc.llm_decision_id = ld.id
WHERE rc.approved = 0 AND ld.decision_type = 'BUY'
ORDER BY rc.checked_at DESC
LIMIT 20;
```

### Daily balance trend

```sql
sqlite3 data/audit.db

SELECT DATE(snapshot_at) AS date, MAX(total_usd) AS eod_balance
FROM audit_balance_snapshots
WHERE mode = 'paper'
GROUP BY DATE(snapshot_at)
ORDER BY date;
```

### Trades by exit reason distribution

```sql
sqlite3 data/paper_trading.db

SELECT exit_reason, COUNT(*) AS count,
       ROUND(AVG(pnl_pct), 2) AS avg_pnl_pct
FROM paper_trades
GROUP BY exit_reason;
```

---

## 10. Scripts for Automated Analysis

### Full rejection audit (3 pipeline layers)

```bash
# After a backtest or trading session
python scripts/audit_rejections.py --db data/audit.db
# or for backtest:
python scripts/audit_rejections.py --db data/backtest_audit.db
```

Output explains how many HOLDs were blocked at the signal layer, what the LLM decided, and which risk guards fired.

### 14-day performance review

```bash
python scripts/review.py --mode paper --days 14
```

Shows balance evolution, win rate, average P&L, drawdown, and a READY/NOT READY verdict.

### Daily trade summary

```bash
python scripts/daily_report.py
```

---

## 11. Log File Reference

Logs are written to `logs/agent.log` (rotating, max 100 MB, 4 backups).

**Log format:**
```
YYYY-MM-DD HH:MM:SS,mmm [LEVEL] module.name: message
```

**Useful search patterns:**

```bash
# All errors
grep "ERROR" logs/agent.log

# Circuit breaker events
grep "\[CIRCUIT\]" logs/agent.log

# Kill switch
grep "KILL SWITCH\|kill_switch" logs/agent.log

# Dynamic TP decisions
grep "\[DYNAMIC_TP\]" logs/agent.log

# All buys
grep "BUY.*filled\|place_order" logs/agent.log

# LLM timeout / fallback model
grep "timeout\|fallback" logs/agent.log -i

# SL/TP fires
grep "stop_loss\|take_profit" logs/agent.log | grep -v "audit"

# Specific pair (e.g. SOL/USD)
grep "SOL/USD" logs/agent.log | tail -50

# Time-of-Day guard firing
grep "Time-of-Day" logs/agent.log
```

**Enable verbose LLM logging** (full prompt + response) by setting in `config.yaml`:

```yaml
storage:
  llm_debug_logging: true
```

This changes the file log level to `DEBUG` and logs the full raw LLM output including reasoning chains. Do **not** enable in production — can produce very large log files.
