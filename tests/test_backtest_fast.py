"""
Fast backtest — signal-only, no LLM.

Replaces the LLM with a deterministic rule engine:
  - Signal=BUY + no open position for pair + cash available → place_order
  - Signal=SELL + open position for pair → close_position

Purpose:
  - Validate signal parameter changes (ADX, RSI divergence, thresholds) in seconds
  - Calibrate per-pair buy_min_score, atr_tp_min_pct, rsi_oversold etc. without LLM cost
  - Used by /add-pair skill to assess a new pair's signal quality before onboarding

Usage:
    ~/.pyenv/versions/3.11.15/bin/python3 tests/test_backtest_fast.py
    ~/.pyenv/versions/3.11.15/bin/python3 tests/test_backtest_fast.py --start-date 2025-12-25
    ~/.pyenv/versions/3.11.15/bin/python3 tests/test_backtest_fast.py --start-date 2025-12-25 --pairs BTC/USD ETH/USD
    ~/.pyenv/versions/3.11.15/bin/python3 tests/test_backtest_fast.py --start-date 2025-12-25 --summary-only
"""

import argparse
import asyncio
import logging
import os
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone

import yaml

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

logging.basicConfig(
    level=logging.WARNING,  # suppress INFO noise — only warnings/errors shown
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

from tests.backtest.loader import load_all_pairs
from src.exchange.historical_feed import HistoricalFeed
from src.exchange.paper_broker import PaperBroker
from src.storage.database import get_connection, get_db_path, init_paper_db, init_audit_db
from src.analysis.indicators import compute_indicators
from src.analysis.signals import generate_signal
from src.analysis.features import build_ai_context, fetch_fear_greed


# ── Deterministic rule engine (replaces LLM) ──────────────────────────────────

def decide(signals: list, open_positions: list, portfolio: dict, config: dict) -> list:
    """
    Simple rule-based trading decisions — no LLM.

    Rules:
      BUY:  Signal=BUY, no open position for this pair, cash available, max positions not reached
      SELL: Signal=SELL, open position exists for this pair
      HOLD: everything else

    Returns list of {pair, action, usd_amount} dicts.
    """
    trading_cfg   = config.get("trading", {})
    risk_cfg      = config.get("risk", {})
    max_positions = trading_cfg.get("max_open_positions", 13)
    min_order_usd = risk_cfg.get("min_order_usd", 20.0)
    base_pct      = config.get("position_sizing", {}).get("base_position_pct", 16.0)
    max_pct       = trading_cfg.get("max_position_pct", 20.0)
    reserve_pct   = risk_cfg.get("min_cash_reserve_pct", 5.0)

    open_pairs   = {p["pair"] for p in open_positions if p.get("status") == "open"}
    n_open       = len(open_pairs)
    total_usd    = portfolio["total_usd"]
    cash_usd     = portfolio["available_cash_usd"]
    min_reserve  = total_usd * reserve_pct / 100

    decisions = []

    # SELL pass first — free up slots before buying
    for sig in signals:
        if sig["signal"] == "SELL" and sig["pair"] in open_pairs:
            pos = next((p for p in open_positions
                        if p["pair"] == sig["pair"] and p.get("status") == "open"), None)
            if pos:
                decisions.append({"pair": sig["pair"], "action": "sell", "position_id": pos["id"],
                                   "exit_price": sig["price"]})

    sells_this_cycle = {d["pair"] for d in decisions if d["action"] == "sell"}
    n_open_after_sells = n_open - len(sells_this_cycle)

    # BUY pass — rank by strength descending
    buy_signals = sorted(
        [s for s in signals if s["signal"] == "BUY" and s["pair"] not in open_pairs
         and s["pair"] not in sells_this_cycle],
        key=lambda s: s.get("strength", 0),
        reverse=True,
    )
    max_buys = trading_cfg.get("max_buys_per_cycle", 7)
    buys_this_cycle = 0

    for sig in buy_signals:
        if n_open_after_sells + buys_this_cycle >= max_positions:
            break
        if buys_this_cycle >= max_buys:
            break

        deployable = cash_usd - min_reserve
        usd_amount = min(
            total_usd * base_pct / 100,
            total_usd * max_pct / 100,
            deployable,
        )
        # Apply per-pair caution_factor_bearish if injected
        if "pair_max_usd" in sig:
            usd_amount = min(usd_amount, sig["pair_max_usd"])

        if usd_amount < min_order_usd:
            continue

        decisions.append({"pair": sig["pair"], "action": "buy", "usd_amount": round(usd_amount, 2),
                           "current_price": sig["price"]})
        cash_usd -= usd_amount  # track depletion within this cycle
        buys_this_cycle += 1

    return decisions


# ── Main backtest loop ─────────────────────────────────────────────────────────

def run_backtest(config: dict, pair_candles: dict, start_date: str, max_steps: int,
                 pairs_filter: list) -> dict:
    """Run the full signal+broker loop without LLM. Returns summary stats dict."""

    # Isolated DBs
    config["storage"]["paper_db"]  = "backtest_fast_paper.db"
    config["storage"]["audit_db"]  = "backtest_fast_audit.db"
    config["trading"]["allowed_trading_hours"]["enabled"] = False

    # Clean slate
    for db_file in [config["storage"]["paper_db"], config["storage"]["audit_db"]]:
        db_path = get_db_path(db_file)
        if os.path.exists(db_path):
            os.remove(db_path)

    starting_balance = config.get("paper", {}).get("starting_balance_usd", 1000.0)
    init_paper_db(config["storage"]["paper_db"], starting_balance)
    init_audit_db(config["storage"]["audit_db"])

    # Filter to requested pairs only
    if pairs_filter:
        pair_candles = {p: c for p, c in pair_candles.items() if p in pairs_filter}
        config["trading"]["pairs"] = [
            pc for pc in config["trading"]["pairs"] if pc["pair"] in pairs_filter
        ]

    pairs = [p["pair"] for p in config["trading"]["pairs"] if p["pair"] in pair_candles]

    paper_cfg = config.get("paper", {})
    broker = PaperBroker(
        paper_db=config["storage"]["paper_db"],
        slippage_pct=paper_cfg.get("slippage_pct", 0.05),
        maker_fee_pct=paper_cfg.get("maker_fee_pct", 0.16),
        config=config,
    )

    feed = HistoricalFeed(pair_candles, config, max_steps=max_steps, start_date=start_date)
    total_steps = feed.total_tradeable
    print(f"\nFast backtest — {total_steps} candle steps, {len(pairs)} pairs, NO LLM\n")

    # Stats tracking
    stats = defaultdict(lambda: {"buys": 0, "sells_tp": 0, "sells_sl": 0, "sells_agent": 0,
                                  "trailing_stop": 0, "pnl_usd": 0.0})
    cycle_count = 0
    start_time  = time.time()

    # Fear & greed: fetch once (static for backtest — avoids live API calls per cycle)
    fear_greed_index = None
    try:
        fg = fetch_fear_greed(config)
        fear_greed_index = fg["value"] if fg else None
    except Exception:
        pass

    candle_ts = 0

    while True:
        cycle_count += 1
        candle_ts = feed.current_candle_time

        # ── SL/TP checks ──────────────────────────────────────────
        for pair in pairs:
            price = feed.get_latest_price(pair)
            if not price:
                continue
            closed = broker.check_stops_and_tp(pair, price, None, candle_ts=candle_ts)
            for t in closed:
                reason = t.get("exit_reason", "unknown")
                if reason == "take_profit":
                    stats[pair]["sells_tp"] += 1
                elif reason == "stop_loss":
                    stats[pair]["sells_sl"] += 1
                elif reason == "trailing_stop":
                    stats[pair]["trailing_stop"] += 1
                stats[pair]["pnl_usd"] += t.get("pnl_usd", 0.0)

        # ── Compute indicators + signals ───────────────────────────
        signals    = []
        ind_cfg    = config.get("indicators", {})
        atr_cfg    = config.get("adaptive_atr_floor", {})
        bb_cfg     = config.get("adaptive_bb_squeeze", {})
        vol_cfg    = config.get("adaptive_volume_floor", {})
        trading_pairs_cfg = config.get("trading", {}).get("pairs", [])

        for pair in pairs:
            candles = feed.get_candles(pair)
            if not candles:
                continue
            indicators = compute_indicators(candles, config)
            if not indicators:
                continue

            if fear_greed_index is not None:
                indicators["fear_greed_index"] = fear_greed_index

            # Adaptive ATR floor injection
            if atr_cfg.get("enabled", False):
                pair_entry = next((p for p in trading_pairs_cfg if p.get("pair") == pair), {})
                lookback   = pair_entry.get("adaptive_atr_floor_lookback",
                                            atr_cfg.get("lookback_candles", 400))
                scale      = atr_cfg.get("scaling_factor", 0.8)
                min_cap    = atr_cfg.get("min_cap_pct", 0.10)
                recent     = candles[-lookback:]
                vals       = [((c["high"] - c["low"]) / c["close"] * 100)
                              for c in recent if c.get("close", 0) > 0]
                if vals:
                    vals.sort()
                    p25 = vals[max(0, int(len(vals) * 0.25) - 1)]
                    indicators["adaptive_atr_floor_pct"] = round(max(p25 * scale, min_cap), 4)

            # Adaptive BB squeeze injection
            if bb_cfg.get("enabled", False):
                lb  = bb_cfg.get("lookback_candles", 400)
                pct = bb_cfg.get("percentile", 10)
                rec = candles[-lb:]
                bv  = [((c["high"] - c["low"]) / ((c["high"] + c["low"]) / 2) * 100)
                       for c in rec if c.get("high", 0) > 0 and c.get("low", 0) > 0]
                if bv:
                    bv.sort()
                    indicators["_rolling_bb_p10_pct"] = round(bv[max(0, int(len(bv) * pct / 100) - 1)], 4)

            # Adaptive volume floor injection
            if vol_cfg.get("enabled", False):
                lb  = vol_cfg.get("lookback_candles", 400)
                pct = vol_cfg.get("percentile", 15)
                rec = candles[-lb:]
                vv  = [c["volume"] for c in rec if c.get("volume", 0) > 0]
                if vv:
                    vv.sort()
                    indicators["rolling_volume_p15"] = vv[max(0, int(len(vv) * pct / 100) - 1)]

            sig = generate_signal(pair, indicators, config)
            sig["indicators"] = indicators
            signals.append(sig)

        if not signals:
            if not feed.advance():
                break
            continue

        # ── Build context + apply regime caution (mirrors main.py) ─
        balance_data   = broker.get_balance()
        open_positions = broker.get_open_positions()
        n_open         = len([p for p in open_positions if p.get("status") == "open"])

        portfolio = {
            "total_usd":            balance_data["total_usd"],
            "available_cash_usd":   balance_data["available_cash_usd"],
            "open_positions_count": n_open,
            "daily_pnl_usd":        0.0,
            "daily_pnl_pct":        0.0,
            "open_positions":       open_positions,
            "max_per_trade":        balance_data["total_usd"] * config.get("trading", {}).get("max_position_pct", 20) / 100,
        }

        ai_context   = build_ai_context(signals=signals, portfolio=portfolio,
                                        open_positions=open_positions, config=config)
        regime_data  = ai_context.get("regime_data", {})
        regime       = regime_data.get("regime", "unknown")
        global_caution = regime_data.get("caution_factor", 1.0)

        if regime == "bearish":
            base_max = portfolio["max_per_trade"]
            for sig in signals:
                pair_cfg     = next((p for p in trading_pairs_cfg if p.get("pair") == sig["pair"]), {})
                pair_caution = pair_cfg.get("caution_factor_bearish", global_caution)
                sig["pair_max_usd"] = round(base_max * pair_caution, 2)

        # ── Deterministic decisions ────────────────────────────────
        decisions = decide(signals, open_positions, portfolio, config)

        for dec in decisions:
            pair = dec["pair"]
            if dec["action"] == "buy":
                price = dec["current_price"]
                if not price:
                    continue
                pair_cfg    = next((p for p in trading_pairs_cfg if p.get("pair") == pair), {})
                sl_pct      = pair_cfg.get("stop_loss_pct", 5.0)
                tp_pct      = pair_cfg.get("take_profit_pct", 12.0)
                # Use dynamic TP if available
                dyn_tp      = ai_context.get("dynamic_tp_values", {}).get(pair)
                if dyn_tp and config.get("dynamic_tp", {}).get("enabled", False):
                    tp_pct = dyn_tp
                ts_iso      = datetime.fromtimestamp(candle_ts, tz=timezone.utc).isoformat() if candle_ts else None
                try:
                    broker.place_order(
                        pair=pair, side="buy",
                        usd_amount=dec["usd_amount"],
                        current_price=price,
                        stop_loss_pct=sl_pct,
                        take_profit_pct=tp_pct,
                        timestamp_override=ts_iso,
                    )
                    stats[pair]["buys"] += 1
                except ValueError as e:
                    pass  # overdraw guard — skip silently

            elif dec["action"] == "sell":
                ts_iso = datetime.fromtimestamp(candle_ts, tz=timezone.utc).isoformat() if candle_ts else None
                result = broker.close_position(
                    position_id=dec["position_id"],
                    exit_price=dec["exit_price"],
                    exit_reason="agent_sell",
                    timestamp_override=ts_iso,
                )
                if result:
                    stats[pair]["sells_agent"] += 1
                    stats[pair]["pnl_usd"] += result.get("pnl_usd", 0.0)

        # Progress every 100 cycles
        if cycle_count % 100 == 0:
            elapsed = time.time() - start_time
            pct = cycle_count / total_steps * 100 if total_steps else 0
            print(f"  {cycle_count}/{total_steps} cycles ({pct:.0f}%) — {elapsed:.0f}s elapsed", flush=True)

        if not feed.advance():
            break

    # ── Force mark-to-market close remaining positions ──────────────
    last_prices = {pair: feed.get_latest_price(pair) for pair in pairs
                   if feed.get_latest_price(pair)}
    force_closed = broker.force_close_all(last_prices)
    for t in force_closed:
        pair   = t.get("pair", "?")
        stats[pair]["pnl_usd"] += t.get("pnl_usd", 0.0)

    final_balance = broker.get_balance()
    elapsed_total = time.time() - start_time

    return {
        "pairs":            pairs,
        "stats":            dict(stats),
        "starting_balance": starting_balance,
        "final_balance":    final_balance["total_usd"],
        "cycles":           cycle_count,
        "force_closed":     len(force_closed),
        "elapsed_secs":     elapsed_total,
    }


# ── Pretty summary ─────────────────────────────────────────────────────────────

def print_summary(result: dict) -> None:
    stats     = result["stats"]
    pairs     = result["pairs"]
    start_bal = result["starting_balance"]
    end_bal   = result["final_balance"]
    net_pnl   = end_bal - start_bal
    net_pct   = net_pnl / start_bal * 100 if start_bal else 0

    print("\n" + "═" * 80)
    print("  FAST BACKTEST RESULTS (signal-only, no LLM)")
    print("═" * 80)
    print(f"  Cycles:          {result['cycles']}")
    print(f"  Elapsed:         {result['elapsed_secs']:.1f}s")
    print(f"  Starting balance: ${start_bal:,.2f}")
    print(f"  Final balance:    ${end_bal:,.2f}")
    print(f"  Net P&L:          ${net_pnl:+,.2f}  ({net_pct:+.2f}%)")
    if result["force_closed"]:
        print(f"  Force-closed:     {result['force_closed']} positions (mark-to-market at last candle)")
    print()

    # Per-pair table
    header = f"  {'Pair':<12} {'Buys':>6} {'TP':>5} {'SL':>5} {'Trail':>6} {'AgentSell':>10} {'P&L USD':>10} {'Win%':>7}"
    print(header)
    print("  " + "-" * 76)

    total_buys = total_tp = total_sl = total_trail = total_agent = 0
    for pair in sorted(pairs):
        s = stats.get(pair, {})
        buys    = s.get("buys", 0)
        tp      = s.get("sells_tp", 0)
        sl      = s.get("sells_sl", 0)
        trail   = s.get("trailing_stop", 0)
        agent   = s.get("sells_agent", 0)
        pnl     = s.get("pnl_usd", 0.0)
        exits   = tp + sl + trail + agent
        win_pct = (tp + trail + agent) / exits * 100 if exits > 0 else 0.0
        total_buys  += buys
        total_tp    += tp
        total_sl    += sl
        total_trail += trail
        total_agent += agent
        pnl_str = f"${pnl:+,.2f}"
        win_str = f"{win_pct:.0f}%" if exits > 0 else "—"
        print(f"  {pair:<12} {buys:>6} {tp:>5} {sl:>5} {trail:>6} {agent:>10} {pnl_str:>10} {win_str:>7}")

    print("  " + "-" * 76)
    total_exits = total_tp + total_sl + total_trail + total_agent
    overall_win = (total_tp + total_trail + total_agent) / total_exits * 100 if total_exits > 0 else 0
    print(f"  {'TOTAL':<12} {total_buys:>6} {total_tp:>5} {total_sl:>5} {total_trail:>6} {total_agent:>10} {'':>10} {overall_win:.0f}%")
    print()

    # Signal quality notes
    if total_buys == 0:
        print("  ⚠  No BUY signals fired — check min_volume_ratio or atr_tp_min_pct thresholds")
    elif total_sl / max(total_exits, 1) > 0.5:
        print(f"  ⚠  High stop-loss rate ({total_sl/max(total_exits,1)*100:.0f}%) — consider raising buy_min_score or atr_tp_min_pct")
    elif overall_win >= 60:
        print(f"  ✓  Win rate {overall_win:.0f}% — signal parameters look solid")
    elif overall_win >= 45:
        print(f"  ~  Win rate {overall_win:.0f}% — acceptable; consider raising buy_min_score by 1 for underperforming pairs")
    else:
        print(f"  ✗  Win rate {overall_win:.0f}% — raise buy_min_score by 2 AND review atr_tp_min_pct")

    print("═" * 80)
    print()


# ── Entry point ────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Fast backtest — signal-only, no LLM. Runs in seconds."
    )
    parser.add_argument(
        "--start-date", type=str, default="",
        help="Start date e.g. 2025-12-25 (uses prior candles for warmup)",
    )
    parser.add_argument(
        "--candles", type=int, default=0,
        help="Max candle steps to replay (0 = all)",
    )
    parser.add_argument(
        "--pairs", nargs="+", default=[],
        help="Filter to specific pairs e.g. --pairs BTC/USD ETH/USD",
    )
    parser.add_argument(
        "--summary-only", action="store_true",
        help="Suppress per-cycle progress output",
    )
    args = parser.parse_args()

    if args.summary_only:
        logging.getLogger().setLevel(logging.ERROR)

    with open("config.yaml") as f:
        config = yaml.safe_load(f)

    all_pairs = [p["pair"] for p in config["trading"]["pairs"]]
    pairs_filter = args.pairs if args.pairs else []

    display_pairs = pairs_filter if pairs_filter else all_pairs
    print(f"\nLoading candle data for {len(display_pairs)} pairs from history/...")
    pair_candles = load_all_pairs(all_pairs, history_dir="history")

    if not pair_candles:
        print("ERROR: No candle data found in history/")
        sys.exit(1)

    loaded  = list(pair_candles.keys())
    skipped = [p for p in all_pairs if p not in pair_candles]
    print(f"Loaded: {len(loaded)} pairs  |  Skipped (no data): {len(skipped)}")
    if skipped:
        print(f"  Skipped: {', '.join(skipped)}")

    result = run_backtest(
        config=config,
        pair_candles=pair_candles,
        start_date=args.start_date,
        max_steps=args.candles,
        pairs_filter=pairs_filter,
    )

    print_summary(result)


if __name__ == "__main__":
    main()
