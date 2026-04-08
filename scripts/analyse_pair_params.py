#!/usr/bin/env python3
"""
Pair parameter analysis script for Kryptos.
Reads candle history files and computes ATR, RSI, MACD, BB, and Volume statistics.
Usage: python3 scripts/analyse_pair_params.py --start-date 2025-01-01
"""

import json
import os
import sys
import argparse
import math
from datetime import datetime, timezone
from statistics import median, mean, stdev

HISTORY_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "history")

PAIR_FILE_MAP = {
    "BTC/USD":  "XBTUSD_candle.json",
    "ETH/USD":  "ETHUSD_candle.json",
    "BNB/USD":  "BNBUSD_candle.json",
    "SOL/USD":  "SOLUSD_candle.json",
    "XRP/USD":  "XRPUSD_candle.json",
    "TRX/USD":  "TRXUSD_candle.json",
    "DOGE/USD": "XDGUSD_candle.json",
    "ADA/USD":  "ADAUSD_candle.json",
    "LTC/USD":  "LTCUSD_candle.json",
    "AVAX/USD": "AVAXUSD_candle.json",
    "SUI/USD":  "SUIUSD_candle.json",
    "UNI/USD":  "UNIUSD_candle.json",
    "INJ/USD":  "INJUSD_candle.json",
}


def percentile(data, pct):
    """Compute p-th percentile from sorted list."""
    if not data:
        return float("nan")
    s = sorted(data)
    idx = (len(s) - 1) * pct / 100.0
    lo = int(idx)
    hi = lo + 1
    frac = idx - lo
    if hi >= len(s):
        return s[lo]
    return s[lo] * (1 - frac) + s[hi] * frac


def load_candles(pair, start_ts):
    """Load candles for a pair from history file, filtered by start_ts."""
    fname = PAIR_FILE_MAP[pair]
    fpath = os.path.join(HISTORY_DIR, fname)
    if not os.path.exists(fpath):
        return None

    with open(fpath) as f:
        raw = json.load(f)

    result = raw.get("result", {})
    # The key inside result is the pair name (e.g. XBTUSD)
    key = next((k for k in result if k != "last"), None)
    if key is None:
        return None

    candles_raw = result[key]
    # Each candle: [timestamp, open, high, low, close, vwap, volume, count]
    candles = []
    for c in candles_raw:
        ts = int(c[0])
        if ts < start_ts:
            continue
        candles.append({
            "ts":     ts,
            "open":   float(c[1]),
            "high":   float(c[2]),
            "low":    float(c[3]),
            "close":  float(c[4]),
            "vwap":   float(c[5]),
            "volume": float(c[6]),
            "count":  int(c[7]),
        })
    return candles


# ── Indicators ────────────────────────────────────────────────────────────────

def compute_atr14(candles):
    """Wilder's smoothed ATR-14. Returns list of (atr_pct, close) per candle (after warmup)."""
    if len(candles) < 15:
        return []
    trs = []
    for i in range(1, len(candles)):
        h = candles[i]["high"]
        l = candles[i]["low"]
        pc = candles[i - 1]["close"]
        tr = max(h - l, abs(h - pc), abs(l - pc))
        trs.append((tr, candles[i]["close"]))

    # Seed with simple average of first 14
    atr = mean(t[0] for t in trs[:14])
    results = []
    for i in range(14, len(trs)):
        tr, close = trs[i]
        atr = (atr * 13 + tr) / 14
        results.append(atr / close * 100.0)
    return results


def compute_rsi14(candles):
    """RSI-14 using Wilder's smoothing. Returns list of RSI values."""
    closes = [c["close"] for c in candles]
    if len(closes) < 15:
        return []

    gains = []
    losses = []
    for i in range(1, len(closes)):
        delta = closes[i] - closes[i - 1]
        gains.append(max(delta, 0))
        losses.append(max(-delta, 0))

    avg_gain = mean(gains[:14])
    avg_loss = mean(losses[:14])
    results = []

    for i in range(14, len(gains)):
        avg_gain = (avg_gain * 13 + gains[i]) / 14
        avg_loss = (avg_loss * 13 + losses[i]) / 14
        if avg_loss == 0:
            results.append(100.0)
        else:
            rs = avg_gain / avg_loss
            results.append(100.0 - 100.0 / (1 + rs))
    return results


def compute_ema(values, period):
    """Exponential moving average."""
    if not values:
        return []
    k = 2.0 / (period + 1)
    ema = [values[0]]
    for v in values[1:]:
        ema.append(v * k + ema[-1] * (1 - k))
    return ema


def compute_macd(candles, fast=12, slow=26, signal_period=9):
    """
    Returns list of dicts: {histogram, close, prev_histogram}
    Starts after slow+signal warmup period.
    """
    closes = [c["close"] for c in candles]
    if len(closes) < slow + signal_period:
        return []

    ema_fast = compute_ema(closes, fast)
    ema_slow = compute_ema(closes, slow)
    macd_line = [f - s for f, s in zip(ema_fast, ema_slow)]
    signal_line = compute_ema(macd_line, signal_period)

    offset = 0  # signal_line aligns with macd_line (both start at index 0)
    results = []
    for i in range(1, len(signal_line)):
        hist = macd_line[i] - signal_line[i]
        prev_hist = macd_line[i - 1] - signal_line[i - 1]
        close = closes[i]
        results.append({
            "histogram":      hist,
            "prev_histogram": prev_hist,
            "close":          close,
        })
    return results


def compute_bb(candles, period=50, num_std=2):
    """
    Bollinger Bands. Returns list of dicts per candle (after warmup):
    {upper, lower, mid, width_pct, close, near_lower, near_upper, in_squeeze}
    """
    closes = [c["close"] for c in candles]
    if len(closes) < period:
        return []

    TOLERANCE = 0.005   # 0.5%
    SQUEEZE_THRESHOLD = 0.005  # 0.5%

    results = []
    for i in range(period - 1, len(closes)):
        window = closes[i - period + 1: i + 1]
        mid = mean(window)
        sd = stdev(window) if len(window) > 1 else 0.0
        upper = mid + num_std * sd
        lower = mid - num_std * sd
        close = closes[i]
        width_pct = (upper - lower) / mid * 100.0 if mid > 0 else 0.0
        near_lower = abs(close - lower) / close <= TOLERANCE
        near_upper = abs(close - upper) / close <= TOLERANCE
        in_squeeze = width_pct < SQUEEZE_THRESHOLD * 100

        results.append({
            "upper":      upper,
            "lower":      lower,
            "mid":        mid,
            "width_pct":  width_pct,
            "close":      close,
            "near_lower": near_lower,
            "near_upper": near_upper,
            "in_squeeze": in_squeeze,
        })
    return results


def compute_volume_stats(candles, sma_period=20):
    """
    Returns list of dicts: {volume, ratio_to_sma, dead_zone}
    dead_zone = ratio < 0.5
    """
    volumes = [c["volume"] for c in candles]
    if len(volumes) < sma_period:
        return []

    results = []
    for i in range(sma_period - 1, len(volumes)):
        window = volumes[i - sma_period + 1: i + 1]
        sma = mean(window)
        ratio = volumes[i] / sma if sma > 0 else 0.0
        results.append({
            "volume":       volumes[i],
            "ratio_to_sma": ratio,
            "dead_zone":    ratio < 0.5,
        })
    return results


# ── Formatting helpers ─────────────────────────────────────────────────────────

def fmt(v, decimals=3):
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "N/A"
    return f"{v:.{decimals}f}"

def fmt_pct(v, decimals=2):
    return fmt(v, decimals) + "%"

def sep(char="─", width=80):
    print(char * width)

def header(title):
    sep("═")
    print(f"  {title}")
    sep("═")

def subheader(title):
    sep("─")
    print(f"  {title}")
    sep("─")


# ── Per-pair analysis ──────────────────────────────────────────────────────────

def analyse_pair(pair, candles):
    n = len(candles)
    print(f"\n{'━'*80}")
    print(f"  PAIR: {pair}   ({n} candles from filter date)")
    print(f"{'━'*80}")

    if n < 100:
        print("  Insufficient candles — skipping.")
        return

    # ── ATR-14 ────────────────────────────────────────────────────────────────
    atr_pcts = compute_atr14(candles)
    if atr_pcts:
        print(f"\n  ATR-14 (% of close price)  [n={len(atr_pcts)}]")
        print(f"    min={fmt_pct(min(atr_pcts))}  "
              f"p10={fmt_pct(percentile(atr_pcts,10))}  "
              f"p25={fmt_pct(percentile(atr_pcts,25))}  "
              f"median={fmt_pct(median(atr_pcts))}  "
              f"p75={fmt_pct(percentile(atr_pcts,75))}  "
              f"p90={fmt_pct(percentile(atr_pcts,90))}  "
              f"max={fmt_pct(max(atr_pcts))}")

    # ── RSI-14 ────────────────────────────────────────────────────────────────
    rsi_vals = compute_rsi14(candles)
    if rsi_vals:
        n_rsi = len(rsi_vals)
        def rsi_below(thresh):
            return sum(1 for r in rsi_vals if r < thresh) / n_rsi * 100
        def rsi_above(thresh):
            return sum(1 for r in rsi_vals if r > thresh) / n_rsi * 100

        print(f"\n  RSI-14  [n={n_rsi}]")
        print(f"    median RSI = {fmt(median(rsi_vals), 2)}")
        print(f"    Oversold  → <25: {fmt_pct(rsi_below(25))}  "
              f"<30: {fmt_pct(rsi_below(30))}  "
              f"<35: {fmt_pct(rsi_below(35))}  "
              f"<40: {fmt_pct(rsi_below(40))}")
        print(f"    Overbought→ >65: {fmt_pct(rsi_above(65))}  "
              f">70: {fmt_pct(rsi_above(70))}  "
              f">75: {fmt_pct(rsi_above(75))}  "
              f">80: {fmt_pct(rsi_above(80))}")

    # ── MACD ──────────────────────────────────────────────────────────────────
    macd_data = compute_macd(candles)
    if macd_data:
        n_macd = len(macd_data)
        hist_abs_pcts = [abs(d["histogram"]) / d["close"] * 100 for d in macd_data if d["close"] > 0]
        pct_positive = sum(1 for d in macd_data if d["histogram"] > 0) / n_macd * 100
        crossovers = [d for d in macd_data if d["prev_histogram"] < 0 and d["histogram"] > 0]
        crossover_pct = len(crossovers) / n_macd * 100

        # MACD decay: candles where histogram turned negative (pos→neg)
        neg_turns = [d for d in macd_data if d["prev_histogram"] > 0 and d["histogram"] < 0]
        neg_turn_hist_pcts = [abs(d["histogram"]) / d["close"] * 100 for d in neg_turns if d["close"] > 0]

        print(f"\n  MACD (fast=12, slow=26, signal=9)  [n={n_macd}]")
        print(f"    median |histogram| % of price = {fmt_pct(median(hist_abs_pcts), 4)}")
        print(f"    % candles histogram positive   = {fmt_pct(pct_positive)}")
        print(f"    % candles crossover (neg→pos)  = {fmt_pct(crossover_pct)}")
        if neg_turn_hist_pcts:
            print(f"    MACD decay (pos→neg turn):")
            print(f"      n={len(neg_turn_hist_pcts)}  "
                  f"median |hist|% at turn = {fmt_pct(median(neg_turn_hist_pcts), 5)}  "
                  f"p25={fmt_pct(percentile(neg_turn_hist_pcts, 25), 5)}  "
                  f"p75={fmt_pct(percentile(neg_turn_hist_pcts, 75), 5)}")
        else:
            print("    MACD decay: no pos→neg turns found")

    # ── Bollinger Bands ───────────────────────────────────────────────────────
    bb_data = compute_bb(candles)
    if bb_data:
        n_bb = len(bb_data)
        widths = [d["width_pct"] for d in bb_data]
        pct_lower = sum(1 for d in bb_data if d["near_lower"]) / n_bb * 100
        pct_upper = sum(1 for d in bb_data if d["near_upper"]) / n_bb * 100
        pct_squeeze = sum(1 for d in bb_data if d["in_squeeze"]) / n_bb * 100

        print(f"\n  Bollinger Bands (period=50, std=2)  [n={n_bb}]")
        print(f"    median width %  = {fmt_pct(median(widths))}")
        print(f"    p25 width %     = {fmt_pct(percentile(widths, 25))}  (squeeze level)")
        print(f"    p10 width %     = {fmt_pct(percentile(widths, 10))}")
        print(f"    % near lower    = {fmt_pct(pct_lower)}")
        print(f"    % near upper    = {fmt_pct(pct_upper)}")
        print(f"    % in squeeze (<0.5% width) = {fmt_pct(pct_squeeze)}")

    # ── Volume ────────────────────────────────────────────────────────────────
    vol_data = compute_volume_stats(candles)
    if vol_data:
        n_vol = len(vol_data)
        vols = [d["volume"] for d in vol_data]
        ratios = [d["ratio_to_sma"] for d in vol_data]
        dead_pct = sum(1 for d in vol_data if d["dead_zone"]) / n_vol * 100

        print(f"\n  Volume (20-period SMA)  [n={n_vol}]")
        print(f"    median volume  = {median(vols):.4f}  p25={percentile(vols,25):.4f}")
        print(f"    ratio to SMA:  p10={fmt(percentile(ratios,10))}  p25={fmt(percentile(ratios,25))}  "
              f"median={fmt(median(ratios))}  p75={fmt(percentile(ratios,75))}")
        print(f"    % dead zone (ratio < 0.50) = {fmt_pct(dead_pct)}")


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Analyse candle data for all pairs.")
    parser.add_argument("--start-date", default="2025-01-01",
                        help="Filter candles from this date (YYYY-MM-DD, UTC)")
    args = parser.parse_args()

    start_dt = datetime.strptime(args.start_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    start_ts = int(start_dt.timestamp())

    header(f"Kryptos — Pair Parameter Analysis  (start={args.start_date})")
    print(f"  History dir: {HISTORY_DIR}")
    print(f"  Start timestamp: {start_ts}  ({start_dt.isoformat()})")

    for pair in PAIR_FILE_MAP:
        candles = load_candles(pair, start_ts)
        if candles is None:
            print(f"\n  {pair}: file not found — skipping")
            continue
        analyse_pair(pair, candles)

    sep("═")
    print("  Analysis complete.")
    sep("═")


if __name__ == "__main__":
    main()
