#!/usr/bin/env python3
"""
H4 gate analysis script — #180.

Tests the hypothesis: blocking BUY entries during a confirmed 4h downtrend
(EMA9 < EMA21 AND MACD histogram < 0) improves win rate and P&L.

Runs two fast-backtest passes (no LLM) over historical candles:
  Pass 1 (Baseline): no gate — every BUY signal fires; each trade tagged with
                     the H4 state that was active at the time of entry.
  Pass 2 (Gated):    BUY entries blocked when H4 state == confirmed_down.

P&L comes directly from paper_trades.pnl_usd (IEEE 754 double stored by the
paper broker) — no custom calculation that could introduce overflow.

Usage:
    python scripts/analyse_h4_gate.py --start-date 2025-10-01
    python scripts/analyse_h4_gate.py --start-date 2025-10-01 --summary-only
    python scripts/analyse_h4_gate.py --start-date 2025-10-01 --baseline-only
    python scripts/analyse_h4_gate.py --start-date 2025-10-01 --block-partial
"""

import argparse
import copy
import math
import os
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone

import pandas as pd
import ta.momentum
import ta.trend
import ta.volatility
import yaml

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from tests.backtest.loader import load_all_pairs
from src.exchange.historical_feed import HistoricalFeed
from src.exchange.paper_broker import PaperBroker
from src.storage.database import get_connection, get_db_path, init_paper_db, init_audit_db
from src.analysis.indicators import detect_candlestick_patterns, detect_rsi_divergence, detect_bb_squeeze_release
from src.analysis.signals import generate_signal
from src.analysis.features import detect_market_regime, fetch_fear_greed

def _precompute_indicators_all(
    pair_candles: dict, pairs: list, config: dict, start_date: str | None = None
) -> dict:
    """
    Compute all technical indicators for every pair ONCE using vectorised pandas/ta
    operations. Returns pair → {candle_timestamp: indicator_dict}.

    Candles are trimmed to (start_date - WARMUP_CANDLES) so the ta library runs on a
    small window (< 10,500 rows) rather than the full 26,000-candle history.
    Indicator accuracy is preserved because WARMUP_CANDLES (750) >> max EMA period (50).

    This replaces the per-step compute_indicators() calls (17–20ms each) with a
    single O(n) pass per pair (~150ms per pair), reducing the main loop to ~0ms/pair.
    """
    WARMUP_CANDLES = 750          # candles before start_date kept for accurate warm-up
    CANDLE_SECONDS = 1800         # 30-minute candles

    # Compute earliest required timestamp
    first_needed_ts: int | None = None
    if start_date:
        try:
            sd = datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            first_needed_ts = int(sd.timestamp()) - WARMUP_CANDLES * CANDLE_SECONDS
        except ValueError:
            pass

    ind_cfg    = config.get("indicators", {})
    atr_cfg    = config.get("adaptive_atr_floor", {})
    bb_cfg     = config.get("adaptive_bb_squeeze", {})
    vol_cfg    = config.get("adaptive_volume_floor", {})
    min_candles = ind_cfg.get("min_candles_to_start", 220)

    rsi_period   = ind_cfg.get("rsi_period", 14)
    macd_fast    = ind_cfg.get("macd_fast", 12)
    macd_slow    = ind_cfg.get("macd_slow", 26)
    macd_sig_p   = ind_cfg.get("macd_signal", 9)
    bb_period    = ind_cfg.get("bb_period", 20)
    bb_std       = ind_cfg.get("bb_std", 2)
    ema_fast_p   = ind_cfg.get("ema_fast", 20)
    ema_slow_p   = ind_cfg.get("ema_slow", 50)
    atr_period   = ind_cfg.get("atr_period", 14)
    adx_period   = ind_cfg.get("adx_period", 14)
    trading_pairs_cfg = config.get("trading", {}).get("pairs", [])

    def _safe(v):
        try:
            f = float(v)
            return None if math.isnan(f) else round(f, 6)
        except Exception:
            return None

    result: dict = {}

    for pair in pairs:
        all_candles = pair_candles.get(pair) or []
        # Trim to the window we actually need (warmup + simulation), preserving
        # indicator accuracy while keeping the DataFrame small and fast.
        if first_needed_ts is not None and all_candles:
            candles = [c for c in all_candles if c["time"] >= first_needed_ts]
            if len(candles) < min_candles:
                candles = all_candles[-min_candles:]  # fallback: use last min_candles
        else:
            candles = all_candles

        if not candles or len(candles) < min_candles:
            result[pair] = {}
            continue

        df = pd.DataFrame(candles).astype(
            {"open": float, "high": float, "low": float, "close": float, "volume": float}
        )
        n = len(df)

        # ── Core indicator Series (all vectorised) ─────────────────────────
        rsi_s   = ta.momentum.RSIIndicator(close=df["close"], window=rsi_period).rsi()
        macd_o  = ta.trend.MACD(close=df["close"], window_fast=macd_fast,
                                 window_slow=macd_slow, window_sign=macd_sig_p)
        ml_s    = macd_o.macd()
        msl_s   = macd_o.macd_signal()
        mh_s    = macd_o.macd_diff()
        bb_o    = ta.volatility.BollingerBands(close=df["close"],
                                               window=bb_period, window_dev=bb_std)
        bbu_s   = bb_o.bollinger_hband()
        bbm_s   = bb_o.bollinger_mavg()
        bbl_s   = bb_o.bollinger_lband()
        ema9_s  = ta.trend.EMAIndicator(close=df["close"], window=9).ema_indicator()
        ema21_s = ta.trend.EMAIndicator(close=df["close"], window=21).ema_indicator()
        emaf_s  = ta.trend.EMAIndicator(close=df["close"], window=ema_fast_p).ema_indicator()
        emas_s  = ta.trend.EMAIndicator(close=df["close"], window=ema_slow_p).ema_indicator()
        atr_s   = ta.volatility.AverageTrueRange(
            high=df["high"], low=df["low"], close=df["close"], window=atr_period
        ).average_true_range()
        adx_s   = ta.trend.ADXIndicator(
            high=df["high"], low=df["low"], close=df["close"], window=adx_period
        ).adx()
        vsma20_s = df["volume"].rolling(window=20).mean()
        direction_s = df["close"].diff().apply(lambda d: 1 if d > 0 else (-1 if d < 0 else 0))
        obv_s    = (direction_s * df["volume"]).cumsum()
        bbw_s    = ((bbu_s - bbl_s) / df["close"] * 100).fillna(0)

        # ── Adaptive floors (vectorised rolling quantiles) ─────────────────
        atr_floor_s = None
        if atr_cfg.get("enabled", False):
            pair_entry = next((p for p in trading_pairs_cfg if p.get("pair") == pair), {})
            lb    = pair_entry.get("adaptive_atr_floor_lookback",
                                   atr_cfg.get("lookback_candles", 400))
            scale = atr_cfg.get("scaling_factor", 0.8)
            cap   = atr_cfg.get("min_cap_pct", 0.10)
            atr_pct_s = ((df["high"] - df["low"]) / df["close"] * 100)
            raw_floor = atr_pct_s.rolling(window=lb, min_periods=1).quantile(0.25) * scale
            atr_floor_s = raw_floor.clip(lower=cap)

        bb_p10_s = None
        if bb_cfg.get("enabled", False):
            lb  = bb_cfg.get("lookback_candles", 400)
            pct = bb_cfg.get("percentile", 10) / 100
            bw2 = ((df["high"] - df["low"]) / ((df["high"] + df["low"]) / 2) * 100)
            bb_p10_s = bw2.rolling(window=lb, min_periods=1).quantile(pct)

        vol_p15_s = None
        if vol_cfg.get("enabled", False):
            lb  = vol_cfg.get("lookback_candles", 400)
            pct = vol_cfg.get("percentile", 15) / 100
            vol_p15_s = df["volume"].rolling(window=lb, min_periods=1).quantile(pct)

        # ── Convert to numpy for fast per-step slicing ────────────────────
        opens_np   = df["open"].to_numpy()
        highs_np   = df["high"].to_numpy()
        lows_np    = df["low"].to_numpy()
        closes_np  = df["close"].to_numpy()
        vols_np    = df["volume"].to_numpy()
        rsi_np     = rsi_s.to_numpy()
        ml_np      = ml_s.to_numpy()
        msl_np     = msl_s.to_numpy()
        mh_np      = mh_s.to_numpy()
        bbu_np     = bbu_s.to_numpy()
        bbm_np     = bbm_s.to_numpy()
        bbl_np     = bbl_s.to_numpy()
        ema9_np    = ema9_s.to_numpy()
        ema21_np   = ema21_s.to_numpy()
        emaf_np    = emaf_s.to_numpy()
        emas_np    = emas_s.to_numpy()
        atr_np     = atr_s.to_numpy()
        adx_np     = adx_s.to_numpy()
        vsma20_np  = vsma20_s.to_numpy()
        obv_np     = obv_s.to_numpy()
        bbw_np     = bbw_s.to_numpy()

        lookup: dict = {}

        for i in range(min_candles - 1, n):
            ts = candles[i]["time"]

            # Series slices (last 30 and last 10) -------------------------
            s30 = slice(max(0, i - 29), i + 1)
            s10 = slice(max(0, i - 9),  i + 1)

            rsi_series   = [_safe(v) for v in rsi_np[s30]]
            close_series = [float(v)  for v in closes_np[s30]]
            obv_series   = [_safe(v) for v in obv_np[s30]]
            bbw_series   = [_safe(v) for v in bbw_np[s10]]

            # Candlestick patterns (last 10 candles) ----------------------
            patterns = detect_candlestick_patterns(
                opens=list(opens_np[s10]),
                highs=list(highs_np[s10]),
                lows=list(lows_np[s10]),
                closes=list(closes_np[s10]),
                atr=_safe(atr_np[i]),
            )

            ind: dict = {
                "rsi_14":              _safe(rsi_np[i]),
                "macd_line":           _safe(ml_np[i]),
                "macd_signal_line":    _safe(msl_np[i]),
                "macd_histogram":      _safe(mh_np[i]),
                "macd_histogram_prev": _safe(mh_np[i - 1]) if i > 0 else None,
                "ema_9":               _safe(ema9_np[i]),
                "ema_21":              _safe(ema21_np[i]),
                "ema_20":              _safe(emaf_np[i]),
                "ema_50":              _safe(emas_np[i]),
                "bb_upper":            _safe(bbu_np[i]),
                "bb_mid":              _safe(bbm_np[i]),
                "bb_lower":            _safe(bbl_np[i]),
                "atr_14":              _safe(atr_np[i]),
                "adx_14":              _safe(adx_np[i]),
                "volume":              float(vols_np[i]),
                "volume_sma_20":       _safe(vsma20_np[i]),
                "close":               float(closes_np[i]),
                "rsi_series":          rsi_series,
                "close_series":        close_series,
                "obv_series":          obv_series,
                "bb_width_series":     bbw_series,
                "candlestick_patterns": patterns,
            }

            # Adaptive injections
            if atr_floor_s is not None:
                v = _safe(atr_floor_s.iloc[i])
                if v is not None:
                    ind["adaptive_atr_floor_pct"] = v
            if bb_p10_s is not None:
                v = _safe(bb_p10_s.iloc[i])
                if v is not None:
                    ind["_rolling_bb_p10_pct"] = v
            if vol_p15_s is not None:
                v = _safe(vol_p15_s.iloc[i])
                if v is not None:
                    ind["rolling_volume_p15"] = v

            lookup[ts] = ind

        result[pair] = lookup

    return result


# ── H4 helpers ────────────────────────────────────────────────────────────────

H4_SECONDS = 4 * 60 * 60  # 14 400 s per 4-hour candle
_EMA_WARMUP_MIN = 21       # need ≥ 21 completed H4 candles for EMA9/EMA21
_MACD_WARMUP_MIN = 35      # need ≥ 35 completed H4 candles for MACD (26 + 9)


def _ema(values: list, period: int) -> list:
    """Standard EMA, seeded with SMA of first `period` values."""
    if len(values) < period:
        return []
    k = 2.0 / (period + 1)
    sma = sum(values[:period]) / period
    result = [sma]
    for v in values[period:]:
        result.append(v * k + result[-1] * (1 - k))
    return result


def aggregate_to_h4(candles: list) -> list:
    """
    Aggregate 30-min candles into 4-hour OHLCV buckets.
    Each bucket's `time` is the start of its 4-hour window (UTC floor).
    """
    buckets: dict = {}
    for c in candles:
        ts = (c["time"] // H4_SECONDS) * H4_SECONDS
        if ts not in buckets:
            buckets[ts] = {
                "time": ts, "open": c["open"], "high": c["high"],
                "low": c["low"], "close": c["close"], "volume": c["volume"],
            }
        else:
            b = buckets[ts]
            b["high"]   = max(b["high"], c["high"])
            b["low"]    = min(b["low"],  c["low"])
            b["close"]  = c["close"]
            b["volume"] += c["volume"]
    return sorted(buckets.values(), key=lambda x: x["time"])


def compute_h4_state(h4_candles: list) -> str:
    """
    Determine the H4 trend state from completed 4-hour candles.

    Returns one of:
      'uptrend'        — EMA9 ≥ EMA21
      'partial_down'   — EMA9 < EMA21, MACD histogram ≥ 0 (compression)
      'confirmed_down' — EMA9 < EMA21, MACD histogram < 0 (confirmed downtrend)
      'unknown'        — insufficient history for EMA21 warmup
    """
    if len(h4_candles) < _EMA_WARMUP_MIN:
        return "unknown"

    closes = [c["close"] for c in h4_candles]

    ema9  = _ema(closes, 9)
    ema21 = _ema(closes, 21)
    if not ema9 or not ema21:
        return "unknown"

    if ema9[-1] >= ema21[-1]:
        return "uptrend"

    # EMA9 < EMA21 — check MACD for confirmation
    if len(h4_candles) < _MACD_WARMUP_MIN:
        return "partial_down"

    ema12 = _ema(closes, 12)
    ema26 = _ema(closes, 26)
    if not ema12 or not ema26:
        return "partial_down"

    # Build MACD line from aligned tail lengths
    n = min(len(ema12), len(ema26))
    macd_line = [a - b for a, b in zip(ema12[-n:], ema26[-n:])]

    signal_line = _ema(macd_line, 9)
    if not signal_line:
        return "partial_down"

    histogram = macd_line[-1] - signal_line[-1]
    return "confirmed_down" if histogram < 0 else "partial_down"


def _precompute_h4_states_fast(h4_candles: list) -> dict:
    """
    O(n) incremental computation of H4 state for each bucket.

    For bucket[i], the state records the trend using only h4_candles[:i]
    (candles completed BEFORE that bucket arrives).  Running EMAs are
    maintained so we never recompute from scratch.
    """
    lookup: dict = {}

    k9   = 2.0 / (9  + 1)
    k21  = 2.0 / (21 + 1)
    k12  = 2.0 / (12 + 1)
    k26  = 2.0 / (26 + 1)
    k_sg = 2.0 / (9  + 1)

    n = 0
    ema9 = ema21 = ema12 = ema26 = macd_sig = None
    seed_buf: list = []   # stores first 26 closes for SMA seeding
    macd_buf: list = []   # accumulates MACD line values to seed signal EMA

    for bucket in h4_candles:
        # ── Record state BEFORE incorporating this bucket ─────────────
        if n < _EMA_WARMUP_MIN:
            state = "unknown"
        elif ema9 >= ema21:   # type: ignore[operator]  (both set when n >= 21)
            state = "uptrend"
        elif n < _MACD_WARMUP_MIN:
            state = "partial_down"
        elif macd_sig is None:
            state = "partial_down"
        else:
            hist = (ema12 - ema26) - macd_sig   # type: ignore[operator]
            state = "confirmed_down" if hist < 0 else "partial_down"

        lookup[bucket["time"]] = state

        # ── Update running EMAs with this bucket's close ───────────────
        close = bucket["close"]
        n += 1
        if n <= 26:
            seed_buf.append(close)

        if n == 9:
            ema9 = sum(seed_buf[:9]) / 9
        elif n > 9:
            ema9 = close * k9 + ema9 * (1 - k9)   # type: ignore[operator]

        if n == 21:
            ema21 = sum(seed_buf[:21]) / 21
        elif n > 21:
            ema21 = close * k21 + ema21 * (1 - k21)  # type: ignore[operator]

        if n == 12:
            ema12 = sum(seed_buf[:12]) / 12
        elif n > 12:
            ema12 = close * k12 + ema12 * (1 - k12)  # type: ignore[operator]

        if n == 26:
            ema26 = sum(seed_buf[:26]) / 26
        elif n > 26:
            ema26 = close * k26 + ema26 * (1 - k26)  # type: ignore[operator]

        # MACD line and signal EMA
        if ema12 is not None and ema26 is not None:
            macd_val = ema12 - ema26
            macd_buf.append(macd_val)
            if len(macd_buf) == 9:
                macd_sig = sum(macd_buf) / 9
            elif len(macd_buf) > 9:
                macd_sig = macd_val * k_sg + macd_sig * (1 - k_sg)  # type: ignore

    return lookup


# ── Deterministic buy/sell decision engine ────────────────────────────────────

def _decide(signals: list, open_positions: list, portfolio: dict, config: dict) -> list:
    """
    Rule-based decisions (no LLM): BUY on BUY signal, SELL on SELL signal.
    Mirrors the logic in tests/test_backtest_fast.py.
    """
    trading_cfg   = config.get("trading", {})
    risk_cfg      = config.get("risk", {})
    max_positions = trading_cfg.get("max_open_positions", 10)
    min_order_usd = risk_cfg.get("min_order_usd", 20.0)
    base_pct      = config.get("position_sizing", {}).get("base_position_pct", 16.0)
    max_pct       = trading_cfg.get("max_position_pct", 20.0)
    reserve_pct   = risk_cfg.get("min_cash_reserve_pct", 5.0)

    open_pairs  = {p["pair"] for p in open_positions if p.get("status") == "open"}
    n_open      = len(open_pairs)
    total_usd   = float(portfolio["total_usd"])
    cash_usd    = float(portfolio["available_cash_usd"])
    min_reserve = total_usd * reserve_pct / 100

    decisions = []

    # Sells first
    for sig in signals:
        if sig["signal"] == "SELL" and sig["pair"] in open_pairs:
            pos = next((p for p in open_positions
                        if p["pair"] == sig["pair"] and p.get("status") == "open"), None)
            if pos:
                decisions.append({
                    "pair": sig["pair"], "action": "sell",
                    "position_id": pos["id"], "exit_price": sig["price"],
                })

    sells_this_cycle  = {d["pair"] for d in decisions if d["action"] == "sell"}
    n_open_after_sell = n_open - len(sells_this_cycle)

    buy_signals = sorted(
        [s for s in signals if s["signal"] == "BUY" and s["pair"] not in open_pairs
         and s["pair"] not in sells_this_cycle],
        key=lambda s: s.get("strength", 0), reverse=True,
    )
    max_buys = trading_cfg.get("max_buys_per_cycle", 7)
    buys_this_cycle = 0

    for sig in buy_signals:
        if n_open_after_sell + buys_this_cycle >= max_positions:
            break
        if buys_this_cycle >= max_buys:
            break

        deployable = cash_usd - min_reserve
        usd_amount = min(total_usd * base_pct / 100, total_usd * max_pct / 100, deployable)
        if "pair_max_usd" in sig:
            usd_amount = min(usd_amount, float(sig["pair_max_usd"]))
        if usd_amount < min_order_usd:
            continue

        decisions.append({
            "pair": sig["pair"], "action": "buy",
            "usd_amount": round(usd_amount, 2), "current_price": sig["price"],
        })
        cash_usd -= usd_amount
        buys_this_cycle += 1

    return decisions


# ── Single backtest pass ───────────────────────────────────────────────────────

_H4_STATES = ("uptrend", "partial_down", "confirmed_down", "unknown")

_BLOCKED_STATES = {
    "confirmed":      {"confirmed_down"},
    "confirmed+partial": {"confirmed_down", "partial_down"},
}


def run_pass(
    config: dict,
    pair_candles: dict,
    start_date: str,
    gate_mode: str,   # "none" | "confirmed" | "confirmed+partial"
    db_suffix: str,
    verbose: bool = True,
) -> dict:
    """
    Run one fast-backtest pass without LLM.

    P&L is read from paper_trades.pnl_usd (SQLite REAL → Python float).
    H4 state at entry time is tracked via (pair, opened_at) key.

    Returns a stats dict — see return statement below.
    """
    cfg = copy.deepcopy(config)
    paper_db = f"h4_{db_suffix}_paper.db"
    audit_db = f"h4_{db_suffix}_audit.db"
    cfg["storage"]["paper_db"] = paper_db
    cfg["storage"]["audit_db"] = audit_db
    cfg["trading"]["allowed_trading_hours"]["enabled"] = False

    # Clean slate
    for db_name in (paper_db, audit_db):
        p = get_db_path(db_name)
        if os.path.exists(p):
            os.remove(p)
    starting_balance = float(cfg.get("paper", {}).get("starting_balance_usd", 1000.0))
    init_paper_db(paper_db, starting_balance)
    init_audit_db(audit_db)

    trading_pairs_cfg = cfg.get("trading", {}).get("pairs", [])
    pairs = [pc["pair"] for pc in trading_pairs_cfg if pc["pair"] in pair_candles]

    paper_cfg = cfg.get("paper", {})
    broker = PaperBroker(
        paper_db=paper_db,
        slippage_pct=paper_cfg.get("slippage_pct", 0.05),
        maker_fee_pct=paper_cfg.get("maker_fee_pct", 0.16),
        config=cfg,
    )

    label = {"none": "Baseline", "confirmed": "H4 Gate ON", "confirmed+partial": "H4 Gate (both states)"}[gate_mode]

    # Pre-aggregate to H4 and pre-compute state for every completed bucket.
    # O(n) incremental approach: maintain running EMAs instead of recomputing
    # from scratch for each bucket (avoids the previous O(n²) list-slicing).
    h4_state_lookup: dict = {}   # pair → {bucket_ts: state_string}
    for pair in pairs:
        h4_candles = aggregate_to_h4(pair_candles[pair])
        h4_state_lookup[pair] = _precompute_h4_states_fast(h4_candles)

    # Vectorised indicator precomputation: runs ta library ONCE per pair.
    # Replaces 17-20ms per-step compute_indicators() calls with a lookup.
    print(f"  [{label}] Precomputing indicators for {len(pairs)} pairs...", flush=True)
    ind_lookup = _precompute_indicators_all(pair_candles, pairs, cfg, start_date=start_date)
    print(f"  [{label}] Precomputation done. Starting simulation...", flush=True)

    feed        = HistoricalFeed(pair_candles, cfg, max_steps=0, start_date=start_date)
    total_steps = feed.total_tradeable

    # State tracking
    # Key: (pair, opened_at_iso) → h4_state string
    entry_h4_state: dict = {}
    h4_blocked = defaultdict(int)
    atr_cfg = cfg.get("adaptive_atr_floor", {})
    bb_cfg  = cfg.get("adaptive_bb_squeeze", {})
    vol_cfg = cfg.get("adaptive_volume_floor", {})
    blocked_states = _BLOCKED_STATES.get(gate_mode, set())

    fear_greed_index = None
    try:
        fg = fetch_fear_greed(cfg)
        fear_greed_index = fg["value"] if fg else None
    except Exception:
        pass

    start_time   = time.time()
    cycle_count  = 0
    peak_balance = starting_balance
    max_drawdown = 0.0

    while True:
        cycle_count += 1
        if verbose and cycle_count % 500 == 0:
            elapsed = time.time() - start_time
            pct = cycle_count / total_steps * 100 if total_steps else 0
            print(f"  [{label}] {cycle_count}/{total_steps} ({pct:.0f}%) — {elapsed:.0f}s", flush=True)

        candle_ts = feed.current_candle_time

        # SL / TP checks
        for pair in pairs:
            price = feed.get_latest_price(pair)
            if price:
                broker.check_stops_and_tp(pair, price, None, candle_ts=candle_ts)

        # Signals — use precomputed indicator lookup (O(1) per pair per step)
        signals = []
        for pair in pairs:
            indicators = ind_lookup.get(pair, {}).get(candle_ts)
            if not indicators:
                continue

            # inject mutable copy so generate_signal() additions don't corrupt the cache
            indicators = dict(indicators)

            if fear_greed_index is not None:
                indicators["fear_greed_index"] = fear_greed_index

            # H4 state: look up pre-computed state for the current 4h bucket
            current_bucket = (candle_ts // H4_SECONDS) * H4_SECONDS
            pair_lookup    = h4_state_lookup.get(pair, {})
            h4_state       = pair_lookup.get(current_bucket, "unknown")

            sig = generate_signal(pair, indicators, cfg)
            sig["h4_state"] = h4_state
            signals.append(sig)

        if not signals:
            if not feed.advance():
                break
            continue

        # Drawdown tracking
        bal       = broker.get_balance()
        total_usd = float(bal["total_usd"])
        if total_usd > peak_balance:
            peak_balance = total_usd
        if peak_balance > 0:
            dd = (peak_balance - total_usd) / peak_balance * 100
            if dd > max_drawdown:
                max_drawdown = dd

        open_positions = broker.get_open_positions()
        n_open = len([p for p in open_positions if p.get("status") == "open"])

        portfolio = {
            "total_usd":            total_usd,
            "available_cash_usd":   float(bal["available_cash_usd"]),
            "open_positions_count": n_open,
            "daily_pnl_usd":        0.0,
            "daily_pnl_pct":        0.0,
            "open_positions":       open_positions,
            "max_per_trade":        total_usd * cfg.get("trading", {}).get("max_position_pct", 20) / 100,
        }

        # Regime detection — fast pure-Python call (no HTTP, no string builders)
        regime_data    = detect_market_regime(signals, cfg)
        regime         = regime_data.get("regime", "unknown")
        global_caution = regime_data.get("caution_factor", 1.0)

        if regime == "bearish":
            base_max = portfolio["max_per_trade"]
            for sig in signals:
                pair_cfg     = next((p for p in trading_pairs_cfg if p.get("pair") == sig["pair"]), {})
                pair_caution = pair_cfg.get("caution_factor_bearish", global_caution)
                sig["pair_max_usd"] = round(base_max * float(pair_caution), 2)

        # Apply H4 gate: downgrade blocked BUY signals to HOLD before decide()
        if blocked_states:
            for sig in signals:
                if sig["signal"] == "BUY" and sig.get("h4_state") in blocked_states:
                    h4_blocked[sig["h4_state"]] += 1
                    sig["signal"] = "HOLD"

        decisions = _decide(signals, open_positions, portfolio, cfg)

        for dec in decisions:
            pair = dec["pair"]
            if dec["action"] == "buy":
                price = dec.get("current_price") or feed.get_latest_price(pair)
                if not price:
                    continue
                pair_cfg = next((p for p in trading_pairs_cfg if p.get("pair") == pair), {})
                sl_pct   = float(pair_cfg.get("stop_loss_pct", 5.0))
                tp_pct   = float(pair_cfg.get("take_profit_pct", 12.0))
                # Dynamic TP: not used in analysis script — static config values are fine for hypothesis testing

                ts_iso   = datetime.fromtimestamp(candle_ts, tz=timezone.utc).isoformat() if candle_ts else None
                h4_state_at_entry = next(
                    (s.get("h4_state", "unknown") for s in signals if s["pair"] == pair),
                    "unknown",
                )
                try:
                    broker.place_order(
                        pair=pair, side="buy", usd_amount=dec["usd_amount"],
                        current_price=float(price), stop_loss_pct=sl_pct,
                        take_profit_pct=tp_pct, timestamp_override=ts_iso,
                    )
                    if ts_iso:
                        entry_h4_state[(pair, ts_iso)] = h4_state_at_entry
                except ValueError:
                    pass  # overdraw guard

            elif dec["action"] == "sell":
                ts_iso = datetime.fromtimestamp(candle_ts, tz=timezone.utc).isoformat() if candle_ts else None
                broker.close_position(
                    position_id=dec["position_id"], exit_price=float(dec["exit_price"]),
                    exit_reason="agent_sell", timestamp_override=ts_iso,
                )

        if not feed.advance():
            break

    # Mark-to-market
    last_prices = {pair: feed.get_latest_price(pair) for pair in pairs if feed.get_latest_price(pair)}
    broker.force_close_all(last_prices)
    elapsed = time.time() - start_time

    # Read all trades from DB — pnl_usd is stored as IEEE 754 REAL (Python float)
    conn   = get_connection(paper_db)
    trades = conn.execute(
        "SELECT pair, opened_at, pnl_usd, exit_reason FROM paper_trades"
    ).fetchall()
    conn.close()

    # Per-H4-state buckets
    state_stats = {s: {"trades": 0, "wins": 0, "losses": 0, "pnl": 0.0} for s in _H4_STATES}
    total_pnl   = 0.0
    wins        = 0
    stop_losses = 0
    take_profits = 0

    for t in trades:
        pnl         = float(t["pnl_usd"])
        exit_reason = t["exit_reason"]
        is_win      = pnl > 0

        # Look up H4 state at entry
        key   = (t["pair"], t["opened_at"])
        state = entry_h4_state.get(key, "unknown")
        if state not in state_stats:
            state = "unknown"

        total_pnl += pnl
        if is_win:
            wins += 1
        if exit_reason == "take_profit":
            take_profits += 1
        elif exit_reason in ("stop_loss", "fallback_stop_loss"):
            stop_losses += 1

        bucket = state_stats[state]
        bucket["trades"] += 1
        bucket["pnl"]    += pnl
        if is_win:
            bucket["wins"]   += 1
        else:
            bucket["losses"] += 1

    total_trades = len(trades)
    win_rate     = (wins / total_trades * 100) if total_trades else 0.0

    return {
        "net_pnl":          total_pnl,
        "win_rate":         win_rate,
        "total_trades":     total_trades,
        "take_profits":     take_profits,
        "stop_losses":      stop_losses,
        "max_drawdown":     max_drawdown,
        "elapsed_secs":     elapsed,
        "starting_balance": starting_balance,
        "state_stats":      state_stats,
        "h4_blocked":       dict(h4_blocked),
    }


# ── Reporting ──────────────────────────────────────────────────────────────────

_STATE_LABELS = {
    "uptrend":        "4h Uptrend     (EMA9 ≥ EMA21)",
    "partial_down":   "4h Partial Down(EMA9 < EMA21, MACD≥0)",
    "confirmed_down": "4h Confirmed Down(EMA9 < EMA21 + MACD<0) ← hard block",
    "unknown":        "4h Unknown     (insufficient history)",
}


def print_state_table(result: dict, label: str) -> None:
    w = 71
    print(f"┌{'─'*w}┐")
    print(f"│  H4 State Breakdown — {label:<48}│")
    print(f"├{'─'*w}┤")
    print(f"  {'State':<48}{'Trades':>6}   {'Wins':>4}  {'Losses':>6}   {'Win%':>4}         {'P&L':>9}")
    print(f"  {'─'*w}")
    for state in _H4_STATES:
        s     = result["state_stats"][state]
        t, w_, l = s["trades"], s["wins"], s["losses"]
        wr    = f"{w_/t*100:.0f}%" if t else "  0%"
        pnl   = s["pnl"]
        print(f"  {_STATE_LABELS[state]:<48}{t:>6}    {w_:>4}  {l:>6}   {wr:>4}  ${pnl:>+10.2f}")
    print(f"  {'─'*w}")
    t_all = result["total_trades"]
    print(f"  {'TOTAL':<48}{t_all:>6}")
    print(f"└{'─'*w}┘")


def print_comparison(baseline: dict, gated: dict, blocked_states: set) -> None:
    w = 71
    print(f"\n╔{'═'*w}╗")
    print(f"║  BEFORE / AFTER COMPARISON{'':42}║")
    print(f"╠{'═'*w}╣")

    b_pnl = baseline["net_pnl"]
    g_pnl = gated["net_pnl"]
    b_bal = baseline["starting_balance"]

    b_pnl_pct = b_pnl / b_bal * 100
    g_pnl_pct = g_pnl / b_bal * 100

    rows = [
        ("Net P&L",
         f"${b_pnl:+.2f} ({b_pnl_pct:+.1f}%)",
         f"${g_pnl:+.2f} ({g_pnl_pct:+.1f}%)"),
        ("Win Rate",
         f"{baseline['win_rate']:.1f}%",
         f"{gated['win_rate']:.1f}%"),
        ("Total Trades",
         str(baseline["total_trades"]),
         str(gated["total_trades"])),
        ("Take Profits",
         str(baseline["take_profits"]),
         str(gated["take_profits"])),
        ("Stop Losses",
         str(baseline["stop_losses"]),
         str(gated["stop_losses"])),
        ("Max Drawdown",
         f"{baseline['max_drawdown']:.1f}%",
         f"{gated['max_drawdown']:.1f}%"),
        ("Run Time",
         f"{baseline['elapsed_secs']:.0f}s",
         f"{gated['elapsed_secs']:.0f}s"),
    ]

    header = f"  {'Metric':<30} {'Baseline (no gate)':>24}           {'H4 Gate ON':>10}"
    sep    = f"  {'─'*w}"
    print(header)
    print(sep)
    for label, bval, gval in rows:
        print(f"  {label:<30} {bval:>24}  {gval:>20}")
    print(sep)

    total_blocked = sum(gated["h4_blocked"].values())
    print(f"\n  Trades blocked by h4 gate: {total_blocked}")
    for state in ("confirmed_down", "partial_down"):
        n = gated["h4_blocked"].get(state, 0)
        if n or state in blocked_states:
            print(f"    {_STATE_LABELS[state]}: {n}")

    # ── Hypothesis verdict ──────────────────────────────────────────────────
    print(f"\n  {'── VERDICT ':─<{w-2}}")
    pnl_delta = g_pnl - b_pnl
    wr_delta  = gated["win_rate"] - baseline["win_rate"]
    trade_delta = gated["total_trades"] - baseline["total_trades"]
    print(f"  P&L change:   ${pnl_delta:+.2f}")
    print(f"  Win rate Δ:   {wr_delta:+.1f}%")
    print(f"  Trade count Δ:{trade_delta:+d} (gate blocks {total_blocked} entries)")

    # Win rate of confirmed_down entries in baseline
    cd = baseline["state_stats"]["confirmed_down"]
    cd_trades = cd["trades"]
    cd_wr     = (cd["wins"] / cd_trades * 100) if cd_trades else None
    overall_wr = baseline["win_rate"]

    if cd_trades >= 20 and cd_wr is not None:
        gap = overall_wr - cd_wr
        print(f"\n  Hypothesis:  confirmed-downtrend entries have lower win rate")
        print(f"  Overall win rate:            {overall_wr:.1f}%")
        print(f"  h4_confirmed_downtrend wr:   {cd_wr:.1f}%  ({cd_trades} trades)")
        print(f"  Gap:                         {gap:+.1f}pp")
        if gap >= 10:
            verdict = "✓  STRONG SIGNAL — implement as Hard Blocker 4"
        elif gap >= 6:
            verdict = "~  MODERATE SIGNAL — consider soft penalty (-2 score)"
        elif gap >= 2:
            verdict = "~  WEAK SIGNAL — gap < 6pp; soft penalty only if P&L also improves"
        else:
            verdict = "✗  NO SIGNAL — confirmed_down entries perform similarly to overall"
        print(f"  {verdict}")
    else:
        print(f"\n  Insufficient confirmed_down trades ({cd_trades}) to compute win rate gap.")

    print(f"╚{'═'*w}╝\n")


# ── Entry point ────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="H4 gate backtest analysis (#180)")
    parser.add_argument("--start-date",  type=str, default="2025-10-01",
                        help="Start date for backtest candles (YYYY-MM-DD)")
    parser.add_argument("--summary-only", action="store_true",
                        help="Suppress per-cycle progress output")
    parser.add_argument("--baseline-only", action="store_true",
                        help="Run Pass 1 (baseline) only — skip gated pass")
    parser.add_argument("--block-partial", action="store_true",
                        help="Also block 4h partial_down (EMA9<EMA21, MACD≥0) in gated pass")
    args = parser.parse_args()

    with open("config.yaml") as f:
        config = yaml.safe_load(f)

    all_pairs = [p["pair"] for p in config["trading"]["pairs"]]
    print(f"\nLoading candle data for {len(all_pairs)} pairs from history/ …")
    pair_candles = load_all_pairs(all_pairs, history_dir="history")
    if not pair_candles:
        print("ERROR: No candle data loaded.")
        sys.exit(1)

    skipped = [p for p in all_pairs if p not in pair_candles]
    print(f"Loaded {len(pair_candles)} pairs  |  Skipped (no data): {len(skipped)}")
    if skipped:
        print(f"  {', '.join(skipped)}")

    verbose = not args.summary_only

    # ── Pass 1: Baseline ──────────────────────────────────────────────────────
    print(f"\n── PASS 1: Baseline (no gate) ──  start-date={args.start_date}")
    baseline = run_pass(
        config=config, pair_candles=pair_candles, start_date=args.start_date,
        gate_mode="none", db_suffix="baseline", verbose=verbose,
    )
    print_state_table(baseline, "PASS 1 — Baseline")

    if args.baseline_only:
        print("\n(--baseline-only: skipping gated pass)")
        return

    # ── Pass 2: Gated ─────────────────────────────────────────────────────────
    gate_mode = "confirmed+partial" if args.block_partial else "confirmed"
    pass_label = "PASS 2 — H4 Gate ON" + (" (both states)" if args.block_partial else "")
    print(f"\n── PASS 2: {gate_mode} gate ──  start-date={args.start_date}")
    gated = run_pass(
        config=config, pair_candles=pair_candles, start_date=args.start_date,
        gate_mode=gate_mode, db_suffix="gated", verbose=verbose,
    )
    print_state_table(gated, pass_label)
    blocked_states = _BLOCKED_STATES.get(gate_mode, set())
    print_comparison(baseline, gated, blocked_states)


if __name__ == "__main__":
    main()
