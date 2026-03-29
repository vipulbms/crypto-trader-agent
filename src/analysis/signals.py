"""
Signal generator — converts indicator values into structured trading signals.
Produces BUY / SELL / HOLD with a confidence strength and human-readable reasons.
"""

import logging
from typing import Optional

from src.utils.timing import timed

logger = logging.getLogger(__name__)


@timed("pair")
def generate_signal(pair: str, indicators: dict, config: dict) -> dict:
    """
    Evaluate indicator values and produce a signal dict:
    {
        "pair":      "BTC/USD",
        "signal":    "BUY" | "SELL" | "HOLD",
        "strength":  float 0.0-1.0,
        "reasons":   [str, ...]
        "price":     float
    }

    BUY conditions (all must align for high-strength signal):
        - RSI < rsi_oversold threshold (oversold)
        - MACD histogram > 0 (bullish momentum) or MACD line crossing above signal
        - Price near or below lower Bollinger Band
        - EMA20 >= EMA50 (uptrend confirmation, optional weight)

    SELL conditions (any one sufficient):
        - RSI > rsi_overbought threshold (overbought)
        - MACD histogram turning negative (bearish crossover)
        - Price above upper Bollinger Band
    """
    ind_cfg = config.get("indicators", {})
    sig_cfg = config.get("signals", {})

    rsi_oversold   = ind_cfg.get("rsi_oversold", 30)
    rsi_overbought = ind_cfg.get("rsi_overbought", 60)
    bb_min_width   = ind_cfg.get("bb_min_width_pct", 0.5)
    bb_buy_tol     = 1 + ind_cfg.get("bb_buy_tolerance_pct", 1.0) / 100
    bb_sell_tol    = 1 - ind_cfg.get("bb_sell_tolerance_pct", 1.0) / 100

    w_rsi_oversold  = sig_cfg.get("rsi_oversold_score", 3)
    w_macd_hist_pos = sig_cfg.get("macd_hist_positive_score", 2)
    w_macd_cross    = sig_cfg.get("macd_crossover_score", 1)
    w_bb_lower      = sig_cfg.get("bb_lower_score", 3)
    w_ema_uptrend   = sig_cfg.get("ema_uptrend_score", 1)
    w_rsi_overbought= sig_cfg.get("rsi_overbought_score", 3)
    w_macd_hist_neg = sig_cfg.get("macd_hist_negative_score", 2)
    w_bb_upper      = sig_cfg.get("bb_upper_score", 2)
    max_score       = sig_cfg.get("max_score", 10)
    buy_min_score   = sig_cfg.get("buy_min_score", 4)
    sell_min_score  = sig_cfg.get("sell_min_score", 3)

    rsi        = indicators.get("rsi_14")
    macd_line  = indicators.get("macd_line")
    macd_sig   = indicators.get("macd_signal_line")
    macd_hist  = indicators.get("macd_histogram")
    ema_fast   = indicators.get("ema_20")
    ema_slow   = indicators.get("ema_50")
    bb_upper   = indicators.get("bb_upper")
    bb_lower   = indicators.get("bb_lower")
    price      = indicators.get("close", 0.0)

    buy_score  = 0
    sell_score = 0
    reasons    = []

    # ── BUY signals ──────────────────────────────────────
    if rsi is not None and rsi < rsi_oversold:
        buy_score += w_rsi_oversold
        reasons.append(f"RSI oversold ({rsi:.1f} < {rsi_oversold})")

    if macd_hist is not None and macd_hist > 0:
        buy_score += w_macd_hist_pos
        reasons.append("MACD histogram positive (bullish momentum)")

    if macd_line is not None and macd_sig is not None and macd_line > macd_sig:
        buy_score += w_macd_cross
        reasons.append("MACD line above signal (bullish crossover)")

    # Only use BB signals when bands have meaningful width.
    # Squeezed bands mean upper ≈ lower ≈ price — both touch simultaneously, which is noise.
    bb_width_pct = ((bb_upper - bb_lower) / price * 100) if (bb_upper and bb_lower and price) else 0
    bb_wide_enough = bb_width_pct >= bb_min_width

    if bb_wide_enough and bb_lower is not None and price and price <= bb_lower * bb_buy_tol:
        buy_score += w_bb_lower
        reasons.append(f"Price at/near lower Bollinger Band (${price:.2f} ≤ ${bb_lower:.2f})")

    if ema_fast is not None and ema_slow is not None and ema_fast >= ema_slow:
        buy_score += w_ema_uptrend
        reasons.append("EMA fast ≥ EMA slow (uptrend)")

    # ── SELL signals ─────────────────────────────────────
    if rsi is not None and rsi > rsi_overbought:
        sell_score += w_rsi_overbought
        reasons.append(f"RSI overbought ({rsi:.1f} > {rsi_overbought})")

    if macd_hist is not None and macd_hist < 0:
        sell_score += w_macd_hist_neg
        reasons.append("MACD histogram negative (bearish momentum)")

    if bb_wide_enough and bb_upper is not None and price and price >= bb_upper * bb_sell_tol:
        sell_score += w_bb_upper
        reasons.append(f"Price at/near upper Bollinger Band (${price:.2f} ≥ ${bb_upper:.2f})")

    if buy_score > sell_score and buy_score >= buy_min_score:
        strength = min(buy_score / max_score, 1.0)
        return {
            "pair":     pair,
            "signal":   "BUY",
            "strength": round(strength, 2),
            "reasons":  reasons,
            "price":    price,
        }
    elif sell_score > buy_score and sell_score >= sell_min_score:
        strength = min(sell_score / max_score, 1.0)
        return {
            "pair":     pair,
            "signal":   "SELL",
            "strength": round(strength, 2),
            "reasons":  reasons,
            "price":    price,
        }
    else:
        hold_reasons = reasons if reasons else ["No clear confluence of signals"]
        return {
            "pair":     pair,
            "signal":   "HOLD",
            "strength": 0.0,
            "reasons":  hold_reasons,
            "price":    price,
        }
