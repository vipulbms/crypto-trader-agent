"""
Signal generator — converts indicator values into structured trading signals.
Produces BUY / SELL / HOLD with a confidence strength and human-readable reasons.
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)


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
    rsi_oversold   = ind_cfg.get("rsi_oversold", 35)
    rsi_overbought = ind_cfg.get("rsi_overbought", 65)

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
        buy_score += 3
        reasons.append(f"RSI oversold ({rsi:.1f} < {rsi_oversold})")

    if macd_hist is not None and macd_hist > 0:
        buy_score += 2
        reasons.append("MACD histogram positive (bullish momentum)")

    if macd_line is not None and macd_sig is not None and macd_line > macd_sig:
        buy_score += 1
        reasons.append("MACD line above signal (bullish crossover)")

    if bb_lower is not None and price and price <= bb_lower * 1.01:
        buy_score += 3
        reasons.append(f"Price at/near lower Bollinger Band (${price:.2f} ≤ ${bb_lower:.2f})")

    if ema_fast is not None and ema_slow is not None and ema_fast >= ema_slow:
        buy_score += 1
        reasons.append("EMA20 ≥ EMA50 (uptrend)")

    # ── SELL signals ─────────────────────────────────────
    if rsi is not None and rsi > rsi_overbought:
        sell_score += 3
        reasons.append(f"RSI overbought ({rsi:.1f} > {rsi_overbought})")

    if macd_hist is not None and macd_hist < 0:
        sell_score += 2
        reasons.append("MACD histogram negative (bearish momentum)")

    if bb_upper is not None and price and price >= bb_upper * 0.99:
        sell_score += 2
        reasons.append(f"Price at/near upper Bollinger Band (${price:.2f} ≥ ${bb_upper:.2f})")

    max_score = 10.0

    if buy_score > sell_score and buy_score >= 4:
        strength = min(buy_score / max_score, 1.0)
        return {
            "pair":     pair,
            "signal":   "BUY",
            "strength": round(strength, 2),
            "reasons":  reasons,
            "price":    price,
        }
    elif sell_score > buy_score and sell_score >= 3:
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
