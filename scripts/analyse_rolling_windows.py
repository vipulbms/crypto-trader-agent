#!/usr/bin/env python3
"""
Rolling-window analysis of candle data for all available pairs from 2025-01-01.

Usage:
    python scripts/analyse_rolling_windows.py --start-date 2025-01-01
"""

import argparse
import datetime
import json
import math
import os
import statistics
from typing import Optional

# ─── constants ────────────────────────────────────────────────────────────────

HISTORY_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "history")

PAIRS = {
    "BTC/USD":  ("XBTUSD_candle.json",  "XBTUSD",  8,  30),
    "ETH/USD":  ("ETHUSD_candle.json",  "ETHUSD",  12, 30),
    "BNB/USD":  ("BNBUSD_candle.json",  "BNBUSD",  12, 28),
    "SOL/USD":  ("SOLUSD_candle.json",  "SOLUSD",  16, 30),
    "XRP/USD":  ("XRPUSD_candle.json",  "XRPUSD",  12, 28),
    "TRX/USD":  ("TRXUSD_candle.json",  "TRXUSD",  12, 35),
    "DOGE/USD": ("XDGUSD_candle.json",  "XDGUSD",  20, 30),
    "ADA/USD":  ("ADAUSD_candle.json",  "ADAUSD",  12, 30),
    "LTC/USD":  ("LTCUSD_candle.json",  "LTCUSD",  8,  28),
    "AVAX/USD": ("AVAXUSD_candle.json", "AVAXUSD", 12, 30),
    "SUI/USD":  ("SUIUSD_candle.json",  "SUIUSD",  16, 30),
    "UNI/USD":  ("UNIUSD_candle.json",  "UNIUSD",  12, 30),
    "INJ/USD":  ("INJUSD_candle.json",  "INJUSD",  16, 30),
}

ATR_PERIOD      = 14
BB_PERIOD       = 50
BB_STD          = 2
VOL_SMA_PERIOD  = 20
RSI_PERIOD      = 14
EMA_FAST        = 12
EMA_SLOW        = 26
EMA_SIGNAL      = 9
EMA9_PERIOD     = 9
EMA21_PERIOD    = 21
EMA50_PERIOD    = 50

BUY_MIN_SCORE   = 5
SELL_MIN_SCORE  = 3
BB_TOLERANCE    = 0.5          # %
FUTURE_CANDLES  = 50
WIN_GAIN_PCT    = 1.5
LOSS_PCT        = 5.0
ATR_FLOOR_CURRENT = 1.0        # current production threshold

WINDOW_SIZES    = [50, 100, 200, 400]
STRIDE          = 10

RSI_OVERBOUGHT  = 70  # sell signal threshold

# ─── helpers ──────────────────────────────────────────────────────────────────

def percentile(data: list[float], p: float) -> float:
    """Compute p-th percentile (0-100) of a sorted or unsorted list."""
    if not data:
        return float("nan")
    s = sorted(data)
    n = len(s)
    idx = (p / 100) * (n - 1)
    lo = int(idx)
    hi = lo + 1
    if hi >= n:
        return s[-1]
    frac = idx - lo
    return s[lo] * (1 - frac) + s[hi] * frac


def safe_stats(data: list[float]) -> dict:
    if len(data) < 2:
        return {k: float("nan") for k in ("mean", "std", "cv", "min", "p5", "p25", "median", "p75", "p95", "max")}
    m = statistics.mean(data)
    sd = statistics.stdev(data)
    return {
        "mean":   m,
        "std":    sd,
        "cv":     sd / m if m != 0 else float("nan"),
        "min":    min(data),
        "p5":     percentile(data, 5),
        "p25":    percentile(data, 25),
        "median": statistics.median(data),
        "p75":    percentile(data, 75),
        "p95":    percentile(data, 95),
        "max":    max(data),
    }


# ─── indicator computation ────────────────────────────────────────────────────

def compute_ema(values: list[float], period: int) -> list[Optional[float]]:
    result: list[Optional[float]] = [None] * len(values)
    k = 2.0 / (period + 1)
    # seed with SMA
    if len(values) < period:
        return result
    sma = sum(values[:period]) / period
    result[period - 1] = sma
    for i in range(period, len(values)):
        result[i] = values[i] * k + result[i - 1] * (1 - k)
    return result


def compute_wilder_atr(highs, lows, closes, period=14) -> list[Optional[float]]:
    n = len(closes)
    tr: list[float] = []
    for i in range(n):
        if i == 0:
            tr.append(highs[i] - lows[i])
        else:
            tr.append(max(
                highs[i] - lows[i],
                abs(highs[i] - closes[i - 1]),
                abs(lows[i] - closes[i - 1]),
            ))
    result: list[Optional[float]] = [None] * n
    if n < period:
        return result
    # seed
    atr = sum(tr[:period]) / period
    result[period - 1] = atr
    for i in range(period, n):
        atr = (atr * (period - 1) + tr[i]) / period
        result[i] = atr
    return result


def compute_rsi(closes: list[float], period=14) -> list[Optional[float]]:
    n = len(closes)
    result: list[Optional[float]] = [None] * n
    if n < period + 1:
        return result
    gains, losses = [], []
    for i in range(1, period + 1):
        diff = closes[i] - closes[i - 1]
        gains.append(max(diff, 0.0))
        losses.append(max(-diff, 0.0))
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        result[period] = 100.0
    else:
        rs = avg_gain / avg_loss
        result[period] = 100 - 100 / (1 + rs)
    for i in range(period + 1, n):
        diff = closes[i] - closes[i - 1]
        g = max(diff, 0.0)
        l = max(-diff, 0.0)
        avg_gain = (avg_gain * (period - 1) + g) / period
        avg_loss = (avg_loss * (period - 1) + l) / period
        if avg_loss == 0:
            result[i] = 100.0
        else:
            rs = avg_gain / avg_loss
            result[i] = 100 - 100 / (1 + rs)
    return result


def compute_bb(closes: list[float], period=50, std_mult=2) -> tuple[list, list, list]:
    n = len(closes)
    upper = [None] * n
    mid   = [None] * n
    lower = [None] * n
    for i in range(period - 1, n):
        window = closes[i - period + 1: i + 1]
        m = sum(window) / period
        variance = sum((x - m) ** 2 for x in window) / period
        sd = math.sqrt(variance)
        mid[i]   = m
        upper[i] = m + std_mult * sd
        lower[i] = m - std_mult * sd
    return upper, mid, lower


def compute_macd(closes: list[float]) -> tuple[list, list, list]:
    """Returns (macd_line, signal_line, histogram) — all may contain None."""
    ema12 = compute_ema(closes, EMA_FAST)
    ema26 = compute_ema(closes, EMA_SLOW)
    n = len(closes)
    macd_line = [None] * n
    for i in range(n):
        if ema12[i] is not None and ema26[i] is not None:
            macd_line[i] = ema12[i] - ema26[i]
    # signal = EMA9 of macd_line
    macd_vals = [v if v is not None else float("nan") for v in macd_line]
    # find first valid index
    first_valid = next((i for i, v in enumerate(macd_line) if v is not None), None)
    signal_line = [None] * n
    histogram   = [None] * n
    if first_valid is None:
        return macd_line, signal_line, histogram
    valid_macd = [v for v in macd_line if v is not None]
    ema_sig = compute_ema(valid_macd, EMA_SIGNAL)
    vi = 0
    sig_arr: list[Optional[float]] = []
    for i in range(n):
        if macd_line[i] is None:
            sig_arr.append(None)
        else:
            sig_arr.append(ema_sig[vi])
            vi += 1
    for i in range(n):
        if macd_line[i] is not None and sig_arr[i] is not None:
            signal_line[i] = sig_arr[i]
            histogram[i]   = macd_line[i] - sig_arr[i]
    return macd_line, signal_line, histogram


def compute_vol_sma(volumes: list[float], period=20) -> list[Optional[float]]:
    n = len(volumes)
    result: list[Optional[float]] = [None] * n
    for i in range(period - 1, n):
        result[i] = sum(volumes[i - period + 1: i + 1]) / period
    return result


# ─── data loading ─────────────────────────────────────────────────────────────

def load_candles(pair: str, start_ts: float) -> list[dict]:
    fname, key, tp_pct, rsi_oversold = PAIRS[pair]
    fpath = os.path.join(HISTORY_DIR, fname)
    if not os.path.exists(fpath):
        return []
    with open(fpath) as f:
        data = json.load(f)
    raw = data["result"].get(key, [])
    candles = []
    for c in raw:
        ts = float(c[0])
        if ts < start_ts:
            continue
        candles.append({
            "ts":     ts,
            "open":   float(c[1]),
            "high":   float(c[2]),
            "low":    float(c[3]),
            "close":  float(c[4]),
            "volume": float(c[6]),
        })
    return candles


# ─── per-candle series ────────────────────────────────────────────────────────

def build_series(candles: list[dict]) -> dict:
    n = len(candles)
    closes  = [c["close"]  for c in candles]
    highs   = [c["high"]   for c in candles]
    lows    = [c["low"]    for c in candles]
    volumes = [c["volume"] for c in candles]

    atr_raw = compute_wilder_atr(highs, lows, closes, ATR_PERIOD)
    atr_pct = [
        (atr_raw[i] / closes[i] * 100) if (atr_raw[i] is not None and closes[i] > 0) else None
        for i in range(n)
    ]

    bb_upper, bb_mid, bb_lower = compute_bb(closes, BB_PERIOD, BB_STD)
    bb_width_pct = [
        ((bb_upper[i] - bb_lower[i]) / bb_mid[i] * 100)
        if (bb_upper[i] is not None and bb_mid[i] and bb_mid[i] > 0) else None
        for i in range(n)
    ]

    vol_sma   = compute_vol_sma(volumes, VOL_SMA_PERIOD)
    vol_ratio = [
        (volumes[i] / vol_sma[i]) if (vol_sma[i] is not None and vol_sma[i] > 0) else None
        for i in range(n)
    ]

    rsi = compute_rsi(closes, RSI_PERIOD)

    macd_line, signal_line, macd_hist = compute_macd(closes)
    macd_hist_norm = [
        (macd_hist[i] / closes[i] * 100) if (macd_hist[i] is not None and closes[i] > 0) else None
        for i in range(n)
    ]

    ema9  = compute_ema(closes, EMA9_PERIOD)
    ema21 = compute_ema(closes, EMA21_PERIOD)
    ema50 = compute_ema(closes, EMA50_PERIOD)

    return {
        "closes":        closes,
        "highs":         highs,
        "lows":          lows,
        "volumes":       volumes,
        "atr_pct":       atr_pct,
        "bb_width_pct":  bb_width_pct,
        "bb_upper":      bb_upper,
        "bb_lower":      bb_lower,
        "vol_ratio":     vol_ratio,
        "rsi":           rsi,
        "macd_line":     macd_line,
        "signal_line":   signal_line,
        "macd_hist":     macd_hist,
        "macd_hist_norm": macd_hist_norm,
        "ema9":          ema9,
        "ema21":         ema21,
        "ema50":         ema50,
        "timestamps":    [c["ts"] for c in candles],
    }


# ─── rolling window analysis ──────────────────────────────────────────────────

def rolling_window_analysis(series: dict, window_sizes: list[int], stride: int = 10) -> dict:
    """
    For each (window_size), slide across the series and compute adaptive stats.
    Returns {window_size: {param: [list of per-window adaptive values]}}
    """
    atr_pct      = series["atr_pct"]
    bb_width_pct = series["bb_width_pct"]
    vol_ratio    = series["vol_ratio"]
    n = len(atr_pct)

    results = {}
    for w in window_sizes:
        atr_floors, bb_squeezes, vol_floors = [], [], []
        for start in range(0, n - w + 1, stride):
            end = start + w
            atr_window = [v for v in atr_pct[start:end]      if v is not None]
            bb_window  = [v for v in bb_width_pct[start:end] if v is not None]
            vol_window = [v for v in vol_ratio[start:end]    if v is not None]
            if atr_window:
                atr_floors.append(percentile(atr_window, 25))
            if bb_window:
                bb_squeezes.append(percentile(bb_window, 10))
            if vol_window:
                vol_floors.append(percentile(vol_window, 15))
        results[w] = {
            "atr_floor":   atr_floors,
            "bb_squeeze":  bb_squeezes,
            "vol_floor":   vol_floors,
        }
    return results


# ─── buy signal analysis ──────────────────────────────────────────────────────

def scan_buy_signals(pair: str, series: dict, candles: list[dict]) -> list[dict]:
    _, _, tp_pct, rsi_oversold = PAIRS[pair]
    n = len(candles)
    closes     = series["closes"]
    rsi        = series["rsi"]
    macd_hist  = series["macd_hist"]
    macd_line  = series["macd_line"]
    signal_line= series["signal_line"]
    bb_upper   = series["bb_upper"]
    bb_lower   = series["bb_lower"]
    ema9       = series["ema9"]
    ema21      = series["ema21"]
    ema50      = series["ema50"]
    atr_pct    = series["atr_pct"]
    bb_width_pct = series["bb_width_pct"]
    vol_ratio  = series["vol_ratio"]
    timestamps = series["timestamps"]

    signals = []
    for i in range(1, n):
        if rsi[i] is None or macd_hist[i] is None:
            continue

        score = 0

        # RSI oversold
        if rsi[i] < rsi_oversold:
            score += 3

        # MACD histogram
        prev_hist = macd_hist[i - 1]
        curr_hist = macd_hist[i]
        if prev_hist is not None and prev_hist < 0 and curr_hist > 0:
            score += 3  # turn positive
        elif curr_hist > 0:
            score += 1  # staying positive

        # MACD line > signal
        if macd_line[i] is not None and signal_line[i] is not None:
            if macd_line[i] > signal_line[i]:
                score += 1

        # BB lower touch (within 0.5%)
        if bb_lower[i] is not None and closes[i] > 0:
            diff_pct = (closes[i] - bb_lower[i]) / closes[i] * 100
            if diff_pct <= BB_TOLERANCE:
                score += 2

        # EMA9 > EMA21
        if ema9[i] is not None and ema21[i] is not None:
            if ema9[i] > ema21[i]:
                score += 2

        # Price > EMA50
        if ema50[i] is not None:
            if closes[i] > ema50[i]:
                score += 1

        if score < BUY_MIN_SCORE:
            continue

        # record indicator state
        atr_v  = atr_pct[i]
        bb_v   = bb_width_pct[i]
        vol_v  = vol_ratio[i]
        blocked_by_atr_floor = (atr_v is not None and atr_v < ATR_FLOOR_CURRENT)

        # future path
        future_closes = closes[i + 1: i + 1 + FUTURE_CANDLES]
        if not future_closes:
            continue
        if closes[i] <= 0:
            continue
        max_gain = max((fc / closes[i] - 1) * 100 for fc in future_closes)
        max_loss = min((fc / closes[i] - 1) * 100 for fc in future_closes)

        ts_str = datetime.datetime.utcfromtimestamp(timestamps[i]).strftime("%Y-%m-%d %H:%M")

        signals.append({
            "ts":                  ts_str,
            "score":               score,
            "atr_pct":             atr_v,
            "bb_width_pct":        bb_v,
            "vol_ratio":           vol_v,
            "max_gain":            max_gain,
            "max_loss":            abs(max_loss),
            "profitable":          max_gain > WIN_GAIN_PCT and abs(max_loss) < LOSS_PCT,
            "blocked_by_atr_floor": blocked_by_atr_floor,
        })

    return signals


# ─── sell signal analysis ─────────────────────────────────────────────────────

def scan_sell_signals(series: dict, candles: list[dict]) -> list[dict]:
    n = len(candles)
    closes     = series["closes"]
    rsi        = series["rsi"]
    macd_hist  = series["macd_hist"]
    bb_upper   = series["bb_upper"]
    bb_lower   = series["bb_lower"]
    timestamps = series["timestamps"]

    signals = []
    for i in range(n):
        if rsi[i] is None:
            continue

        score = 0

        # RSI overbought
        if rsi[i] > RSI_OVERBOUGHT:
            score += 3

        # MACD histogram negative
        if macd_hist[i] is not None and macd_hist[i] < 0:
            score += 2

        # BB upper touch (within 0.5%)
        if bb_upper[i] is not None and closes[i] > 0:
            diff_pct = (bb_upper[i] - closes[i]) / closes[i] * 100
            if diff_pct <= BB_TOLERANCE:
                score += 2

        if score < SELL_MIN_SCORE:
            continue

        # What happened next?
        future_closes = closes[i + 1: i + 1 + FUTURE_CANDLES]
        if not future_closes or closes[i] <= 0:
            continue

        max_drop  = min((fc / closes[i] - 1) * 100 for fc in future_closes)  # negative = drop
        max_rally = max((fc / closes[i] - 1) * 100 for fc in future_closes)  # positive = rally

        correct     = max_drop < -2.0    # price dropped >2%
        premature   = max_rally > 2.0    # price rallied >2% after signal

        # normalised MACD decay threshold check
        macd_hist_norm = series["macd_hist_norm"]
        norm_val = macd_hist_norm[i] if macd_hist_norm[i] is not None else None
        abs_val  = macd_hist[i] if macd_hist[i] is not None else None
        would_fire_norm = norm_val is not None and norm_val < -0.001  # -0.1% of price
        would_fire_abs  = abs_val  is not None and abs_val  < -0.0005

        ts_str = datetime.datetime.utcfromtimestamp(timestamps[i]).strftime("%Y-%m-%d %H:%M")
        signals.append({
            "ts":                ts_str,
            "score":             score,
            "correct":           correct,
            "premature":         premature,
            "norm_would_fire":   would_fire_norm,
            "abs_would_fire":    would_fire_abs,
        })

    return signals


# ─── display helpers ──────────────────────────────────────────────────────────

def fmt(v, decimals=3) -> str:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "  N/A  "
    return f"{v:.{decimals}f}"


def hdr(title: str, width: int = 90) -> None:
    print()
    print("═" * width)
    print(f"  {title}")
    print("═" * width)


# ─── main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--start-date", default="2025-01-01")
    args = parser.parse_args()

    start_dt = datetime.datetime.strptime(args.start_date, "%Y-%m-%d")
    start_ts = start_dt.timestamp()

    print(f"\nKryptos — Rolling Window Analysis  (from {args.start_date})")
    print(f"Pairs: {len(PAIRS)}   Windows: {WINDOW_SIZES}   Stride: {STRIDE}")

    # ── collect all results ──────────────────────────────────────────────────

    all_series   : dict[str, dict]       = {}
    all_rw       : dict[str, dict]       = {}
    all_buy_sigs : dict[str, list[dict]] = {}
    all_sell_sigs: dict[str, list[dict]] = {}
    all_candles  : dict[str, list[dict]] = {}

    for pair in PAIRS:
        print(f"  Processing {pair} ...", end=" ", flush=True)
        candles = load_candles(pair, start_ts)
        if not candles:
            print(f"NO DATA")
            continue
        series = build_series(candles)
        rw     = rolling_window_analysis(series, WINDOW_SIZES, STRIDE)
        buy_s  = scan_buy_signals(pair, series, candles)
        sell_s = scan_sell_signals(series, candles)

        all_candles[pair]   = candles
        all_series[pair]    = series
        all_rw[pair]        = rw
        all_buy_sigs[pair]  = buy_s
        all_sell_sigs[pair] = sell_s
        print(f"✓  {len(candles):,} candles  {len(buy_s)} buy signals  {len(sell_s)} sell signals")

    # ─────────────────────────────────────────────────────────────────────────
    # SECTION 1: ROLLING WINDOW STABILITY
    # ─────────────────────────────────────────────────────────────────────────
    hdr("ROLLING WINDOW STABILITY")

    params = [
        ("ATR Adaptive Floor (p25 ATR%)",     "atr_floor"),
        ("BB Adaptive Squeeze (p10 BB width%)", "bb_squeeze"),
        ("Volume Adaptive Floor (p15 vol ratio)", "vol_floor"),
    ]

    for pair in all_rw:
        print(f"\n  ── {pair} ──")
        rw = all_rw[pair]
        for param_label, param_key in params:
            print(f"\n    {param_label}")
            print(f"    {'Window':>8}  {'mean':>7}  {'std':>7}  {'CV':>6}  {'p5':>7}  {'median':>7}  {'p95':>7}  {'stable?':>8}")
            for w in WINDOW_SIZES:
                data = rw[w][param_key]
                if not data:
                    print(f"    {w:>8}  {'(no data)':>50}")
                    continue
                s = safe_stats(data)
                stable = "YES" if (not math.isnan(s["cv"]) and s["cv"] < 0.20) else "no"
                print(
                    f"    {w:>8}  {fmt(s['mean']):>7}  {fmt(s['std']):>7}  {fmt(s['cv']):>6}  "
                    f"{fmt(s['p5']):>7}  {fmt(s['median']):>7}  {fmt(s['p95']):>7}  {stable:>8}"
                )

    # ─────────────────────────────────────────────────────────────────────────
    # SECTION 2: RECOMMENDED LOOKBACK PER PAIR
    # ─────────────────────────────────────────────────────────────────────────
    hdr("RECOMMENDED LOOKBACK PER PAIR")

    print(f"\n  {'Pair':<12}  {'ATR lb':>7}  {'BB lb':>6}  {'Vol lb':>7}  "
          f"{'ATR min_cap%':>12}  {'BB fallback%':>13}  {'Vol fallback':>12}")
    print(f"  {'-'*12}  {'-'*7}  {'-'*6}  {'-'*7}  {'-'*12}  {'-'*13}  {'-'*12}")

    recommendations: dict[str, dict] = {}

    for pair in all_rw:
        rw = all_rw[pair]
        series = all_series[pair]

        # pick the smallest window where CV < 0.20 for each param
        def best_window(param_key: str) -> tuple[int, float, float]:
            for w in WINDOW_SIZES:
                data = rw[w][param_key]
                if not data:
                    continue
                s = safe_stats(data)
                if not math.isnan(s["cv"]) and s["cv"] < 0.20:
                    return w, s["median"], s["p25"]
            # fallback: largest window
            w = WINDOW_SIZES[-1]
            data = rw[w][param_key]
            s = safe_stats(data) if data else {"median": float("nan"), "p25": float("nan")}
            return w, s["median"], s["p25"]

        atr_lb, atr_median, atr_p25   = best_window("atr_floor")
        bb_lb,  bb_median,  bb_p25    = best_window("bb_squeeze")
        vol_lb, vol_median, vol_p25   = best_window("vol_floor")

        # static fallbacks: overall p25/p10/p15 of full series
        full_atr  = [v for v in series["atr_pct"]      if v is not None]
        full_bb   = [v for v in series["bb_width_pct"] if v is not None]
        full_vol  = [v for v in series["vol_ratio"]    if v is not None]
        atr_static_cap  = percentile(full_atr, 25)  if full_atr  else float("nan")
        bb_static_fall  = percentile(full_bb,  10)  if full_bb   else float("nan")
        vol_static_fall = percentile(full_vol, 15)  if full_vol  else float("nan")

        recommendations[pair] = {
            "atr_lb": atr_lb, "bb_lb": bb_lb, "vol_lb": vol_lb,
            "atr_min_cap": atr_static_cap,
            "bb_fallback": bb_static_fall,
            "vol_fallback": vol_static_fall,
        }

        print(
            f"  {pair:<12}  {atr_lb:>7}  {bb_lb:>6}  {vol_lb:>7}  "
            f"{fmt(atr_static_cap, 3):>12}  {fmt(bb_static_fall, 3):>13}  {fmt(vol_static_fall, 3):>12}"
        )

    # ─────────────────────────────────────────────────────────────────────────
    # SECTION 3: BUY SIGNAL ANALYSIS
    # ─────────────────────────────────────────────────────────────────────────
    hdr("BUY SIGNAL ANALYSIS")

    print(f"\n  Current ATR floor in production: {ATR_FLOOR_CURRENT}%")
    print(f"  Win condition: max_gain > {WIN_GAIN_PCT}% AND max_loss < {LOSS_PCT}% over next {FUTURE_CANDLES} candles\n")

    summary_buy: dict[str, dict] = {}

    for pair in all_buy_sigs:
        sigs = all_buy_sigs[pair]
        series = all_series[pair]
        if not sigs:
            print(f"\n  ── {pair} ── No BUY signals found")
            continue

        total         = len(sigs)
        profitable    = [s for s in sigs if s["profitable"]]
        win_pct       = len(profitable) / total * 100 if total else 0.0

        atr_vals_sig  = [s["atr_pct"]      for s in sigs if s["atr_pct"]      is not None]
        bb_vals_sig   = [s["bb_width_pct"] for s in sigs if s["bb_width_pct"] is not None]
        max_gains     = [s["max_gain"] for s in sigs]
        max_losses    = [s["max_loss"] for s in sigs]

        full_atr      = [v for v in series["atr_pct"]      if v is not None]
        full_bb       = [v for v in series["bb_width_pct"] if v is not None]
        overall_med_atr = statistics.median(full_atr) if full_atr else float("nan")
        overall_med_bb  = statistics.median(full_bb)  if full_bb  else float("nan")
        sig_med_atr     = statistics.median(atr_vals_sig) if atr_vals_sig else float("nan")
        sig_med_bb      = statistics.median(bb_vals_sig)  if bb_vals_sig  else float("nan")

        avg_gain = statistics.mean(max_gains) if max_gains else float("nan")
        avg_loss = statistics.mean(max_losses) if max_losses else float("nan")

        # blocked by current ATR floor
        blocked = [s for s in sigs if s["blocked_by_atr_floor"]]
        blocked_profitable = [s for s in blocked if s["profitable"]]
        blocked_win_pct = len(blocked_profitable) / len(blocked) * 100 if blocked else 0.0

        # score distribution
        score_dist: dict[int, int] = {}
        for s in sigs:
            k = s["score"] if s["score"] <= 8 else 8
            score_dist[k] = score_dist.get(k, 0) + 1

        summary_buy[pair] = {
            "total": total, "win_pct": win_pct,
            "sig_med_atr": sig_med_atr, "overall_med_atr": overall_med_atr,
            "sig_med_bb": sig_med_bb, "overall_med_bb": overall_med_bb,
            "avg_gain": avg_gain, "avg_loss": avg_loss,
            "blocked": len(blocked), "blocked_win_pct": blocked_win_pct,
            "score_dist": score_dist,
        }

        print(f"  ── {pair} ──")
        print(f"    Total signals       : {total}")
        print(f"    Win %               : {win_pct:.1f}%")
        print(f"    Median ATR% at signal: {fmt(sig_med_atr, 3)}  (overall median: {fmt(overall_med_atr, 3)})")
        print(f"    Median BB width%    : {fmt(sig_med_bb, 3)}  (overall median: {fmt(overall_med_bb, 3)})")
        print(f"    Avg max_gain        : {fmt(avg_gain, 2)}%")
        print(f"    Avg max_loss        : {fmt(avg_loss, 2)}%")
        print(f"    Blocked by ATR ≥1.0%: {len(blocked)} signals  ({blocked_win_pct:.1f}% would have been profitable)")
        dist_str = "  ".join(
            f"≥{k}={score_dist[k]}" if k == 8 else f"{k}={score_dist.get(k, 0)}"
            for k in sorted(score_dist)
        )
        print(f"    Score distribution  : {dist_str}")
        print()

    # ─────────────────────────────────────────────────────────────────────────
    # SECTION 4: SELL SIGNAL ANALYSIS
    # ─────────────────────────────────────────────────────────────────────────
    hdr("SELL SIGNAL ANALYSIS")

    print(f"\n  Sell signal threshold: RSI>{RSI_OVERBOUGHT} (+3)  MACD hist<0 (+2)  BB upper touch (+2)  min_score={SELL_MIN_SCORE}")
    print(f"  'Correct' = price dropped >2% within next {FUTURE_CANDLES} candles")
    print(f"  'Premature' = price rallied >2% within next {FUTURE_CANDLES} candles\n")

    for pair in all_sell_sigs:
        sigs = all_sell_sigs[pair]
        if not sigs:
            print(f"  ── {pair} ── No SELL signals found")
            continue

        total    = len(sigs)
        correct  = sum(1 for s in sigs if s["correct"])
        premature = sum(1 for s in sigs if s["premature"])
        pct_correct   = correct   / total * 100 if total else 0.0
        pct_premature = premature / total * 100 if total else 0.0

        norm_fires = sum(1 for s in sigs if s["norm_would_fire"])
        abs_fires  = sum(1 for s in sigs if s["abs_would_fire"])
        norm_pct   = norm_fires / total * 100 if total else 0.0
        abs_pct    = abs_fires  / total * 100 if total else 0.0

        print(f"  ── {pair} ──")
        print(f"    Total signals        : {total}")
        print(f"    Correct drop >2%     : {correct}  ({pct_correct:.1f}%)")
        print(f"    Premature rally >2%  : {premature}  ({pct_premature:.1f}%)")
        print(f"    MACD normalised fire (<-0.1% of price): {norm_fires} ({norm_pct:.1f}% of signals)")
        print(f"    MACD absolute fire   (<-0.0005)       : {abs_fires}  ({abs_pct:.1f}% of signals)")
        print()

    # ─────────────────────────────────────────────────────────────────────────
    # SECTION 5: SUMMARY RECOMMENDATIONS
    # ─────────────────────────────────────────────────────────────────────────
    hdr("SUMMARY RECOMMENDATIONS")

    print(f"""
  Interpretation guide:
    ATR min_cap  = recommended minimum atr_tp_min_pct (p25 of full-series ATR%)
    BB fallback  = recommended static bb_min_width_pct when rolling window unavailable
    Vol fallback = recommended static min_volume_ratio floor
    ATR lb / BB lb / Vol lb = recommended lookback candle count (smallest window with CV<0.20)
""")
    print(
        f"  {'Pair':<12}  "
        f"{'ATR lb':>7}  {'BB lb':>6}  {'Vol lb':>7}  "
        f"{'ATR min_cap%':>12}  {'BB fallback%':>13}  {'Vol fallback':>12}  "
        f"{'BuyWin%':>8}  {'BlockedWin%':>11}"
    )
    print(
        f"  {'-'*12}  {'-'*7}  {'-'*6}  {'-'*7}  "
        f"{'-'*12}  {'-'*13}  {'-'*12}  "
        f"{'-'*8}  {'-'*11}"
    )

    for pair in PAIRS:
        rec = recommendations.get(pair)
        bsig = summary_buy.get(pair)
        if rec is None:
            print(f"  {pair:<12}  (no data)")
            continue
        bwin   = fmt(bsig["win_pct"],          1) if bsig else "  N/A  "
        blkwin = fmt(bsig["blocked_win_pct"],   1) if bsig else "  N/A  "
        print(
            f"  {pair:<12}  "
            f"{rec['atr_lb']:>7}  {rec['bb_lb']:>6}  {rec['vol_lb']:>7}  "
            f"{fmt(rec['atr_min_cap'], 3):>12}  {fmt(rec['bb_fallback'], 3):>13}  {fmt(rec['vol_fallback'], 3):>12}  "
            f"{bwin:>8}  {blkwin:>11}"
        )

    print()
    print("  Notes:")
    print("  * ATR min_cap < current 1.0% floor indicates the floor is blocking low-ATR entries.")
    print("  * BlockedWin% = % of ATR-blocked signals that would have been profitable anyway.")
    print("  * High BlockedWin% + ATR min_cap << 1.0% → consider lowering atr_tp_min_pct per pair.")
    print("  * Stable (CV<0.20) at smallest window = fast adaptation; larger = slow/stable markets.")
    print()

    hdr("END OF REPORT")
    print()


if __name__ == "__main__":
    main()
