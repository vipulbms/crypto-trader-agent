"""
Analyse historical ATR% profile per pair from history/ candle files.

Computes ATR-14 at each candle, then prints median, p25, p75, min, max ATR%
to help calibrate per-pair adaptive_atr_floor settings.

Usage:
    python3 scripts/analyse_atr_profile.py
    python3 scripts/analyse_atr_profile.py --start-date 2025-07-01
"""

import argparse
import json
import os
import statistics
from datetime import datetime, timezone

HISTORY_DIR = os.path.join(os.path.dirname(__file__), "..", "history")
ATR_PERIOD = 14

# Map pair name (config format) to history file
PAIR_FILE_MAP = {
    "BTC/USD":   "XBTUSD_candle.json",
    "ETH/USD":   "ETHUSD_candle.json",
    "BNB/USD":   "BNBUSD_candle.json",
    "SOL/USD":   "SOLUSD_candle.json",
    "XRP/USD":   "XRPUSD_candle.json",
    "TRX/USD":   "TRXUSD_candle.json",
    "DOGE/USD":  "XDGUSD_candle.json",
    "ADA/USD":   "ADAUSD_candle.json",
    "LTC/USD":   "LTCUSD_candle.json",
    "AVAX/USD":  "AVAXUSD_candle.json",
    "SUI/USD":   "SUIUSD_candle.json",
    "UNI/USD":   "UNIUSD_candle.json",
    "INJ/USD":   "INJUSD_candle.json",
}


def load_candles(filepath: str, start_ts: float = 0.0) -> list:
    with open(filepath) as f:
        d = json.load(f)
    result = d.get("result", {})
    pair_key = next((k for k in result if k != "last"), None)
    if not pair_key:
        return []
    candles = result[pair_key]
    # Each candle: [timestamp, open, high, low, close, vwap, volume, count]
    if start_ts > 0:
        candles = [c for c in candles if c[0] >= start_ts]
    return candles


def compute_atr_pct_series(candles: list) -> list:
    """Compute ATR-14 % of close price for each candle."""
    if len(candles) < ATR_PERIOD + 1:
        return []

    # True range for each candle (need previous close)
    tr_values = []
    for i in range(1, len(candles)):
        high  = float(candles[i][2])
        low   = float(candles[i][3])
        prev_close = float(candles[i - 1][4])
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        tr_values.append((tr, float(candles[i][4])))  # (tr, close)

    # Wilder's smoothed ATR-14
    atr = statistics.mean(t for t, _ in tr_values[:ATR_PERIOD])
    atr_pct_series = []

    for i in range(ATR_PERIOD, len(tr_values)):
        tr, close = tr_values[i]
        atr = (atr * (ATR_PERIOD - 1) + tr) / ATR_PERIOD
        if close > 0:
            atr_pct_series.append(atr / close * 100)

    return atr_pct_series


def percentile(data: list, pct: float) -> float:
    if not data:
        return 0.0
    sorted_data = sorted(data)
    k = (len(sorted_data) - 1) * pct / 100
    f = int(k)
    c = f + 1
    if c >= len(sorted_data):
        return sorted_data[f]
    return sorted_data[f] + (k - f) * (sorted_data[c] - sorted_data[f])


def suggest_scaling_factor(median_atr_pct: float) -> float:
    """
    Suggest a scaling_factor so that the adaptive floor = max(min_cap, median × factor)
    blocks entries when ATR drops significantly below its own baseline.

    Target: floor ≈ 60% of the pair's typical ATR (i.e. block if compressed >40%).
    Fixed at 0.6 — user should tune based on backtest results.
    """
    return 0.6


def suggest_lookback(median_atr_pct: float, pair: str) -> int:
    """
    Suggest lookback_candles based on pair volatility.
    High-vol pairs (ATR >2%): 24 candles (6h) — adapt quickly
    Mid-vol pairs (ATR 0.5–2%): 48 candles (12h)
    Low-vol pairs (ATR <0.5%): 96 candles (24h) — need more history to detect compression
    """
    if median_atr_pct >= 2.0:
        return 24
    elif median_atr_pct >= 0.5:
        return 48
    else:
        return 96


def main():
    parser = argparse.ArgumentParser(description="Analyse ATR% profile per pair")
    parser.add_argument("--start-date", type=str, default="",
                        help="Only use candles from this date onward, e.g. 2025-07-01")
    args = parser.parse_args()

    start_ts = 0.0
    if args.start_date:
        start_ts = datetime.strptime(args.start_date, "%Y-%m-%d").replace(
            tzinfo=timezone.utc).timestamp()
        print(f"Filtering candles from {args.start_date} onward\n")

    print(f"{'Pair':<12} {'Candles':>8} {'Min%':>7} {'P25%':>7} {'Median%':>9} {'P75%':>7} {'Max%':>7} {'Suggest scaling':>16} {'Suggest lookback':>17}")
    print("-" * 100)

    suggestions = {}

    for pair, filename in PAIR_FILE_MAP.items():
        filepath = os.path.join(HISTORY_DIR, filename)
        if not os.path.exists(filepath):
            print(f"{pair:<12} {'NO DATA':>8}")
            continue

        candles = load_candles(filepath, start_ts)
        atr_pcts = compute_atr_pct_series(candles)

        if not atr_pcts:
            print(f"{pair:<12} {'INSUFFICIENT':>8}")
            continue

        mn   = min(atr_pcts)
        p25  = percentile(atr_pcts, 25)
        med  = percentile(atr_pcts, 50)
        p75  = percentile(atr_pcts, 75)
        mx   = max(atr_pcts)
        sf   = suggest_scaling_factor(med)
        lb   = suggest_lookback(med, pair)
        floor = max(0.3, med * sf)

        suggestions[pair] = {"scaling_factor": sf, "lookback_candles": lb, "implied_floor": floor}

        print(f"{pair:<12} {len(atr_pcts):>8} {mn:>7.3f} {p25:>7.3f} {med:>9.3f} {p75:>7.3f} {mx:>7.3f} {sf:>16.1f} {lb:>17}  → floor={floor:.3f}%")

    print("\n--- Suggested config.yaml per-pair overrides ---\n")
    for pair, s in suggestions.items():
        safe = pair.replace("/", "")
        print(f"    - pair: {pair}")
        print(f"      adaptive_atr_floor:")
        print(f"        scaling_factor: {s['scaling_factor']}")
        print(f"        lookback_candles: {s['lookback_candles']}  # implied floor ~{s['implied_floor']:.2f}%")
        print()


if __name__ == "__main__":
    main()
