"""
Backtest runner — replays historical candles through the live signal pipeline.

Decision logic (deterministic, no LLM):
  BUY:  signal == BUY, strength >= 0.5, no existing position in pair,
        open positions < max_open_positions, cash > min reserve
  SELL: signal == SELL, existing position P&L > +2%
  SL/TP: checked first each step using candle high/low (intra-candle)

Position sizing: base_position_pct (20%) of current total balance per trade.
"""

import logging
import sys
import os

# Ensure project root is on path so src.* imports resolve
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from src.analysis.indicators import compute_indicators
from src.analysis.signals import generate_signal
from tests.backtest.broker import BacktestBroker

logger = logging.getLogger(__name__)


def run_backtest(
    pair_candles: dict,     # {pair: [candle_dict, ...]}
    config: dict,
    starting_balance: float = 1000.0,
) -> dict:
    """
    Slide through all candle steps across all pairs simultaneously.
    Returns a results dict with per-pair and aggregate statistics.
    """
    trading_cfg   = config.get("trading", {})
    risk_cfg      = config.get("risk", {})
    ind_cfg       = config.get("indicators", {})
    sizing_cfg    = config.get("position_sizing", {})

    max_open      = trading_cfg.get("max_open_positions", 3)
    min_cash_pct  = risk_cfg.get("min_cash_reserve_pct", 10) / 100
    min_candles   = ind_cfg.get("min_candles_to_start", 220)
    base_pct      = sizing_cfg.get("base_position_pct", 20) / 100
    buy_strength_min = 0.5   # only buy if signal strength >= this

    # Build per-pair TP/SL from config
    pair_tp_map = {}
    pair_sl_map = {}
    for p in trading_cfg.get("pairs", []):
        pair_tp_map[p["pair"]] = p.get("take_profit_pct", trading_cfg.get("take_profit_pct", 8))
        pair_sl_map[p["pair"]] = p.get("stop_loss_pct", trading_cfg.get("stop_loss_pct", 5))

    broker = BacktestBroker(starting_balance=starting_balance)

    # Align pairs to the same candle count (use the minimum across all pairs)
    n_candles = min(len(c) for c in pair_candles.values())
    pairs = list(pair_candles.keys())

    # Tracking
    cycle_count   = 0
    buy_proposals = 0
    sell_proposals= 0
    rejected_buys = 0
    balance_history = []   # (step, total_usd) snapshots

    for i in range(min_candles, n_candles):
        cycle_count += 1
        current_candle_time = pair_candles[pairs[0]][i]["time"]

        # ── Step 1: SL/TP check FIRST for all pairs ──────────────────
        for pair in pairs:
            candle = pair_candles[pair][i]
            broker.check_stops_and_tp(
                pair=pair,
                current_price=candle["close"],
                candle=candle,
            )

        # ── Step 2: Compute signals for all pairs ────────────────────
        signals = []
        for pair in pairs:
            candles = pair_candles[pair][:i + 1]
            indicators = compute_indicators(candles, config)
            if not indicators:
                continue
            sig = generate_signal(pair, indicators, config)
            sig["indicators"] = indicators
            signals.append(sig)

        if not signals:
            continue

        # ── Step 3: Apply buy decisions ───────────────────────────────
        balance_data     = broker.get_balance()
        total_usd        = balance_data["total_usd"]
        cash_usd         = balance_data["available_cash_usd"]
        min_cash_reserve = total_usd * min_cash_pct
        open_count       = broker.get_open_positions_count()
        open_pairs       = {p["pair"] for p in broker.get_open_positions()}

        # Sort BUY signals by strength (descending) to prioritise strongest
        buy_signals  = sorted(
            [s for s in signals if s["signal"] == "BUY"],
            key=lambda s: s["strength"],
            reverse=True,
        )

        buys_this_cycle = 0
        max_buys = trading_cfg.get("max_buys_per_cycle", 3)

        for sig in buy_signals:
            pair = sig["pair"]
            if buys_this_cycle >= max_buys:
                break
            if sig["strength"] < buy_strength_min:
                continue
            if pair in open_pairs:
                rejected_buys += 1
                continue
            if open_count >= max_open:
                rejected_buys += 1
                continue
            if cash_usd <= min_cash_reserve:
                rejected_buys += 1
                continue

            proposed_usd = round(total_usd * base_pct, 2)
            tradable     = cash_usd - min_cash_reserve
            if tradable <= 0:
                rejected_buys += 1
                continue
            actual_usd = min(proposed_usd, tradable)
            if actual_usd < 1.0:
                rejected_buys += 1
                continue

            tp_pct = pair_tp_map.get(pair, 8)
            sl_pct = pair_sl_map.get(pair, 5)
            current_price = pair_candles[pair][i]["close"]

            broker.place_order(
                pair=pair,
                side="buy",
                usd_amount=actual_usd,
                current_price=current_price,
                stop_loss_pct=sl_pct,
                take_profit_pct=tp_pct,
                candle_time=current_candle_time,
            )
            buy_proposals += 1
            buys_this_cycle += 1
            open_count += 1
            open_pairs.add(pair)

            # Refresh cash after buy
            balance_data = broker.get_balance()
            cash_usd     = balance_data["available_cash_usd"]

        # ── Step 4: Apply sell decisions ─────────────────────────────
        sell_signals = [s for s in signals if s["signal"] == "SELL"]
        sell_pair_set = {s["pair"] for s in sell_signals}

        for pos in broker.get_open_positions():
            pair = pos["pair"]
            if pair not in sell_pair_set:
                continue
            current_price = pair_candles[pair][i]["close"]
            pnl_pct = ((current_price - pos["entry_price"]) / pos["entry_price"] * 100)
            if pnl_pct > 2.0:   # only sell if meaningful profit (matches agent guardrail)
                broker.close_position(
                    pos["id"], current_price, "agent_sell",
                    candle_time=current_candle_time,
                )
                sell_proposals += 1

        # ── Balance snapshot every 48 steps (12 hours) ───────────────
        if cycle_count % 48 == 0:
            balance_history.append((current_candle_time, broker.get_balance()["total_usd"]))

    # Force-close all open positions at last candle close (mark-to-market)
    last_idx = n_candles - 1
    last_candle_time = pair_candles[pairs[0]][last_idx]["time"]
    for pos in list(broker.get_open_positions()):
        last_price = pair_candles[pos["pair"]][last_idx]["close"]
        broker.close_position(pos["id"], last_price, "end_of_backtest",
                              candle_time=last_candle_time)

    final_balance = broker.get_balance()["total_usd"]

    return {
        "starting_balance":  starting_balance,
        "final_balance":     round(final_balance, 2),
        "total_pnl_usd":     round(final_balance - starting_balance, 2),
        "total_pnl_pct":     round((final_balance - starting_balance) / starting_balance * 100, 2),
        "cycles":            cycle_count,
        "buy_proposals":     buy_proposals,
        "sell_proposals":    sell_proposals,
        "rejected_buys":     rejected_buys,
        "trades":            broker.trades,
        "balance_history":   balance_history,
        "n_candles":         n_candles,
        "min_candles":       min_candles,
        "tradeable_steps":   n_candles - min_candles,
    }
