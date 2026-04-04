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

    # Reversal detector thresholds (from config, with data-backed defaults)
    min_red_before_buy   = sig_cfg.get("reversal_min_red_candles", 8)   # min prior down candles
    min_green_confirm    = sig_cfg.get("reversal_min_green_candles", 4)  # min confirmation candles

    rsi        = indicators.get("rsi_14")
    macd_line  = indicators.get("macd_line")
    macd_sig   = indicators.get("macd_signal_line")
    macd_hist  = indicators.get("macd_histogram")
    ema_9      = indicators.get("ema_9")
    ema_21     = indicators.get("ema_21")
    ema_fast   = indicators.get("ema_20")
    ema_slow   = indicators.get("ema_50")   # EMA200 when ema_slow=200 in config
    bb_upper   = indicators.get("bb_upper")
    bb_lower   = indicators.get("bb_lower")
    price      = indicators.get("close", 0.0)
    cons_red   = indicators.get("consecutive_red", 0)
    cons_green = indicators.get("consecutive_green", 0)
    prev_red   = indicators.get("prev_consecutive_red", 0)

    buy_score  = 0
    sell_score = 0
    reasons    = []

    # BB variables — initialised here so sell path always has them regardless of gate outcomes
    bb_width_pct = ((bb_upper - bb_lower) / price * 100) if (bb_upper and bb_lower and price) else 0
    bb_wide_enough = bb_width_pct >= bb_min_width
    near_lower = bb_wide_enough and bb_lower is not None and price and price <= bb_lower * bb_buy_tol
    near_upper_for_sell = bb_wide_enough and bb_upper is not None and price and price >= bb_upper * bb_sell_tol

    # ── Gate 1: EMA200 trend gate ─────────────────────────────────────────
    # Never buy when price is below EMA200 — long-term downtrend, no entries.
   #ema200_bullish = ema_slow is not None and price and price > ema_slow
   # if not ema200_bullish and ema_slow is not None:
   #     reasons.append(f"BLOCKED: price ${price:.2f} below EMA200 ${ema_slow:.2f} — downtrend")
    # ── Gate 1: Trend and Momentum Filters ───────────────────────────────
    # Reject buys if price is not above EMA50, or if RSI is overbought

    is_bullish_trend = ema_slow is not None and price and price > ema_slow
    if not is_bullish_trend:
        reasons.append(f"BLOCKED: Price ${price:.2f} <= EMA50 ${ema_slow:.2f} — downtrend")
    
    is_momentum_positive = ema_9 is not None and ema_21 is not None and ema_9 > ema_21
    if not is_momentum_positive:
        reasons.append(f"BLOCKED: EMA 9 <= EMA 21 — momentum is not positive")
        
    is_rsi_acceptable = rsi is not None and rsi < 70
    if not is_rsi_acceptable:
        reasons.append(f"BLOCKED: RSI {rsi:.1f} >= 70 — overbought")

    buy_allowed = is_bullish_trend and is_momentum_positive and is_rsi_acceptable

    # ── BUY signals (only scored if gates are passed) ───────────────
    if buy_allowed:
        if rsi is not None and rsi < rsi_oversold:
            buy_score += w_rsi_oversold
            reasons.append(f"RSI oversold ({rsi:.1f} < {rsi_oversold})")

        if macd_hist is not None and macd_hist > 0:
            buy_score += w_macd_hist_pos
            reasons.append("MACD histogram positive (bullish momentum)")

        if macd_line is not None and macd_sig is not None and macd_line > macd_sig:
            buy_score += w_macd_cross
            reasons.append("MACD line above signal (bullish crossover)")

        if near_lower and not near_upper_for_sell:
            buy_score += w_bb_lower
            reasons.append(f"Price at/near lower Bollinger Band (${price:.2f} ≤ ${bb_lower:.2f})")

        if ema_fast is not None and ema_slow is not None and ema_fast >= ema_slow:
            buy_score += w_ema_uptrend
            reasons.append("EMA fast ≥ EMA slow (uptrend)")

        # Adding a default weight for passing the rigorous momentum gates
        buy_score += sig_cfg.get("reversal_confirmed_score", 3)
        reasons.append("Passed Trend (Price > EMA50) and Momentum (EMA 9 > EMA 21) gates")
    else:
        # No buy scoring without passing gates
        pass

    # ── SELL signals ─────────────────────────────────────────────────────
    if rsi is not None and rsi > rsi_overbought:
        sell_score += w_rsi_overbought
        reasons.append(f"RSI overbought ({rsi:.1f} > {rsi_overbought})")

    if macd_hist is not None and macd_hist < 0:
        sell_score += w_macd_hist_neg
        reasons.append("MACD histogram negative (bearish momentum)")

    if near_upper_for_sell and not near_lower:
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
