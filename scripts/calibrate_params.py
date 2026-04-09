#!/usr/bin/env python3
"""
calibrate_params.py — Parameter calibration utility (Fix #118).

Analyses historical candle data from the exchange's SQLite cache (or Kraken REST API)
for the requested pairs and date range, and outputs recommended config YAML changes.

Usage:
    python scripts/calibrate_params.py \
        --start-date 2025-01-01 \
        --end-date   2025-04-01 \
        --pairs BTC/USD ETH/USD SOL/USD \
        --output recommended_params.yaml

    # Analyse all configured pairs for last 90 days
    python scripts/calibrate_params.py --days 90

Output is a YAML snippet that can be compared against the current config.yaml.
Each parameter value is derived from statistical analysis of the candle data.

Parameters calibrated (per pair):
  - atr_tp_min_pct        (p25 ATR% × 0.8, capped at 0.10%)
  - rsi_oversold          (RSI percentile 5 + 2, rounded to nearest 2)
  - rsi_overbought        (RSI percentile 95 - 2, rounded to nearest 2)
  - bb_squeeze_threshold_pct (p10 BB width%)
  - min_volume_ratio      (volume dead zone fraction → 1 - p20_vol_ratio)
"""

import argparse
import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from typing import Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

try:
    import yaml
except ImportError:
    print("ERROR: pyyaml not installed. Run: pip install pyyaml")
    sys.exit(1)


# ─────────────────────────────────────────────────────────────
# Candle data loading
# ─────────────────────────────────────────────────────────────

def _load_candles_from_db(pair: str, db_path: str, start_dt: datetime, end_dt: datetime) -> list:
    """Load candles from SQLite candle cache (tests/backtest*.db or similar)."""
    if not os.path.exists(db_path):
        return []
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """SELECT timestamp, open, high, low, close, volume
               FROM candles
               WHERE pair=? AND timestamp >= ? AND timestamp <= ?
               ORDER BY timestamp ASC""",
            (pair, int(start_dt.timestamp()), int(end_dt.timestamp())),
        ).fetchall()
        return [dict(r) for r in rows]
    except Exception as e:
        print(f"  [WARN] DB query failed for {pair}: {e}")
        return []
    finally:
        conn.close()


def _load_candles_from_kraken(pair: str, start_dt: datetime, end_dt: datetime) -> list:
    """Fetch candles from Kraken public REST API (15-min intervals)."""
    try:
        import requests
    except ImportError:
        print("  [WARN] requests not installed — cannot fetch from Kraken")
        return []

    import yaml as _yaml
    with open("config.yaml") as f:
        cfg = _yaml.safe_load(f)

    pair_cfg = next(
        (p for p in cfg.get("trading", {}).get("pairs", []) if p.get("pair") == pair),
        {}
    )
    rest_name = pair_cfg.get("rest_name", pair.replace("/", ""))

    all_candles = []
    since = int(start_dt.timestamp())
    end_ts = int(end_dt.timestamp())

    while since < end_ts:
        url = f"https://api.kraken.com/0/public/OHLC?pair={rest_name}&interval=15&since={since}"
        try:
            resp = requests.get(url, timeout=15)
            data = resp.json()
            if data.get("error"):
                print(f"  [WARN] Kraken API error for {pair}: {data['error']}")
                break
            result = data.get("result", {})
            candle_key = next(iter(k for k in result if k != "last"), None)
            if not candle_key:
                break
            raw = result[candle_key]
            if not raw:
                break
            for c in raw:
                ts = int(c[0])
                if ts > end_ts:
                    break
                all_candles.append({
                    "timestamp": ts,
                    "open":  float(c[1]),
                    "high":  float(c[2]),
                    "low":   float(c[3]),
                    "close": float(c[4]),
                    "volume": float(c[6]),
                })
            last_ts = int(raw[-1][0])
            if last_ts <= since:
                break
            since = last_ts
        except Exception as e:
            print(f"  [WARN] Kraken fetch failed: {e}")
            break

    return all_candles


# ─────────────────────────────────────────────────────────────
# Statistical analysis
# ─────────────────────────────────────────────────────────────

def _percentile(values: list, p: float) -> float:
    """Simple percentile without numpy."""
    if not values:
        return 0.0
    s = sorted(values)
    idx = max(0, min(len(s) - 1, int(len(s) * p / 100) - 1))
    return s[idx]


def _analyse_pair(candles: list) -> Optional[dict]:
    """
    Compute calibration statistics for a pair from its candle list.
    Returns a dict of recommended parameter values, or None if insufficient data.
    """
    if len(candles) < 100:
        return None

    import math

    closes  = [c["close"] for c in candles if c.get("close", 0) > 0]
    highs   = [c["high"]  for c in candles if c.get("high",  0) > 0]
    lows    = [c["low"]   for c in candles if c.get("low",   0) > 0]
    volumes = [c["volume"] for c in candles if c.get("volume", 0) > 0]

    if not closes or not volumes:
        return None

    # ATR% (high-low range / close * 100)
    atr_pcts = [
        (highs[i] - lows[i]) / closes[i] * 100
        for i in range(len(closes))
        if closes[i] > 0
    ]
    p25_atr = _percentile(atr_pcts, 25)
    atr_tp_min = round(max(p25_atr * 0.8, 0.10), 2)

    # BB width% (high-low / mid * 100 as proxy)
    bb_width_pcts = [
        (highs[i] - lows[i]) / ((highs[i] + lows[i]) / 2) * 100
        for i in range(len(closes))
    ]
    p10_bb = round(_percentile(bb_width_pcts, 10), 1)

    # RSI (simplified — use price momentum proxy as RSI distribution)
    # Since we don't compute RSI here, use change% as proxy for distribution shape
    changes = [
        abs(closes[i] - closes[i - 1]) / closes[i - 1] * 100
        for i in range(1, len(closes))
        if closes[i - 1] > 0
    ]
    # Map to [0,100] RSI-like values: 50 ± (change_rank / max_change * 50)
    # This is an approximation — full RSI needs ema of gains/losses over 14 periods
    # For calibration purposes, RSI p5/p95 from actual RSI requires ta library
    try:
        import ta
        import pandas as pd
        df = pd.DataFrame(candles).astype({"close": float})
        rsi_series = ta.momentum.RSIIndicator(close=df["close"], window=14).rsi().dropna()
        rsi_p5  = float(rsi_series.quantile(0.05))
        rsi_p95 = float(rsi_series.quantile(0.95))
        rsi_oversold   = max(25, int((rsi_p5  + 2) / 2) * 2)   # round to nearest 2, min 25
        rsi_overbought = min(80, int((rsi_p95 - 2) / 2) * 2)   # round to nearest 2, max 80
    except ImportError:
        rsi_oversold   = 30
        rsi_overbought = 70

    # Volume dead zone — fraction of candles below 30% of SMA(20)
    sma_window = 20
    if len(volumes) >= sma_window:
        dead_zone_count = 0
        for i in range(sma_window, len(volumes)):
            sma = sum(volumes[i - sma_window:i]) / sma_window
            if sma > 0 and volumes[i] < sma * 0.30:
                dead_zone_count += 1
        dead_zone_frac = dead_zone_count / (len(volumes) - sma_window)
        # If >50% is dead zone at 0.30, raise threshold to 0.40; if <30%, lower to 0.30
        if dead_zone_frac > 0.50:
            min_volume_ratio = 0.30
        elif dead_zone_frac > 0.35:
            min_volume_ratio = 0.40
        else:
            min_volume_ratio = 0.50
    else:
        min_volume_ratio = 0.50

    return {
        "atr_tp_min_pct":           atr_tp_min,
        "bb_squeeze_threshold_pct": p10_bb,
        "rsi_oversold":             rsi_oversold,
        "rsi_overbought":           rsi_overbought,
        "min_volume_ratio":         min_volume_ratio,
        "_stats": {
            "candles":        len(candles),
            "p25_atr_pct":    round(p25_atr, 4),
            "p10_bb_pct":     round(p10_bb, 4),
            "rsi_p5":         round(rsi_p5, 1) if 'rsi_p5' in dir() else None,
            "rsi_p95":        round(rsi_p95, 1) if 'rsi_p95' in dir() else None,
        },
    }


# ─────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Calibrate config.yaml parameters from historical candle data"
    )
    parser.add_argument("--start-date", type=str, default=None,
                        help="Start date YYYY-MM-DD (default: --days ago)")
    parser.add_argument("--end-date", type=str, default=None,
                        help="End date YYYY-MM-DD (default: today)")
    parser.add_argument("--days", type=int, default=90,
                        help="Look-back in days if --start-date not given (default: 90)")
    parser.add_argument("--pairs", nargs="*", default=None,
                        help="Pairs to calibrate (default: all in config.yaml)")
    parser.add_argument("--db", type=str, default=None,
                        help="Path to candle SQLite DB (default: use Kraken REST API)")
    parser.add_argument("--output", type=str, default=None,
                        help="Write YAML snippet to this file (default: stdout)")
    args = parser.parse_args()

    end_dt = (
        datetime.strptime(args.end_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        if args.end_date
        else datetime.now(timezone.utc)
    )
    start_dt = (
        datetime.strptime(args.start_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        if args.start_date
        else end_dt - timedelta(days=args.days)
    )

    with open("config.yaml") as f:
        config = yaml.safe_load(f)

    all_pairs_cfg = config.get("trading", {}).get("pairs", [])
    pairs_to_run  = args.pairs if args.pairs else [p["pair"] for p in all_pairs_cfg]

    print(f"\nCalibrating {len(pairs_to_run)} pairs from {start_dt.date()} to {end_dt.date()}")
    print("─" * 60)

    recommendations = []
    for pair in pairs_to_run:
        print(f"  {pair}: loading candles...", end=" ", flush=True)
        if args.db:
            candles = _load_candles_from_db(pair, args.db, start_dt, end_dt)
        else:
            candles = _load_candles_from_kraken(pair, start_dt, end_dt)

        if not candles:
            print("no data — skipped")
            continue

        print(f"{len(candles)} candles", end=" ")
        result = _analyse_pair(candles)
        if not result:
            print("— insufficient data")
            continue

        stats = result.pop("_stats", {})
        print(f"→ atr_tp_min={result['atr_tp_min_pct']}% bb_squeeze={result['bb_squeeze_threshold_pct']}%"
              f" rsi={result['rsi_oversold']}/{result['rsi_overbought']} vol_ratio={result['min_volume_ratio']}")

        recommendations.append({
            "pair": pair,
            **result,
            "_stats": stats,
        })

    if not recommendations:
        print("\nNo recommendations generated.")
        return

    # Build YAML output — only the fields that differ from current config
    print("\n" + "─" * 60)
    yaml_pairs = []
    for rec in recommendations:
        pair = rec["pair"]
        existing = next((p for p in all_pairs_cfg if p.get("pair") == pair), {})
        changes = {}
        for key in ["atr_tp_min_pct", "bb_squeeze_threshold_pct", "rsi_oversold",
                    "rsi_overbought", "min_volume_ratio"]:
            new_val = rec.get(key)
            old_val = existing.get(key)
            if new_val is not None and new_val != old_val:
                changes[key] = {"was": old_val, "recommended": new_val}

        if changes:
            yaml_pairs.append({"pair": pair, "changes": changes,
                                "stats": rec.get("_stats", {})})
            for k, v in changes.items():
                print(f"  {pair}.{k}: {v['was']} → {v['recommended']}")
        else:
            print(f"  {pair}: no changes recommended")

    # Write YAML snippet
    output_yaml = yaml.dump(
        {"recommended_changes": yaml_pairs},
        default_flow_style=False,
        sort_keys=False,
    )

    if args.output:
        with open(args.output, "w") as f:
            f.write(f"# Generated by calibrate_params.py — {datetime.now().isoformat()[:16]}\n")
            f.write(f"# Period: {start_dt.date()} to {end_dt.date()}\n\n")
            f.write(output_yaml)
        print(f"\nRecommendations written to: {args.output}")
    else:
        print("\n--- YAML snippet ---")
        print(output_yaml)


if __name__ == "__main__":
    main()
