"""
Signal generator — converts indicator values into structured trading signals.
Produces BUY / SELL / HOLD with a confidence strength and human-readable reasons.

BUY logic: confluence scoring — no single indicator triggers a buy.
Multiple signals must align to reach the minimum score threshold.

Hard blockers (veto regardless of score):
  1. RSI >= 70 — overbought, never enter
  2. ATR-based TP < min_profit_floor_pct — trade cannot cover fees in low-volatility grind

BUY score contributors (need >= buy_min_score to emit BUY):
  RSI < 30 (oversold)                  +3
  RSI 30-40 (mild oversold)            +1
  MACD histogram turned positive        +3   (was negative, now positive — momentum crossover)
  MACD histogram > 0 (not a turn)      +1   (already positive, weaker signal)
  MACD line > signal line              +1
  Price <= BB lower band               +2
  EMA9 > EMA21 (short-term up)         +2
  Price > EMA50 (medium trend)         +1   (bonus, not a blocker)
  Fear & Greed <= 40 (fear)            +1
  Fear & Greed <= 25 (extreme fear)    +1   (stacks with above)
  ADX > 40 (strong trend)              +1   (confirms directional momentum)
  ADX < 20 (ranging market)            -1   (soft penalty — no clear trend)
  RSI regular bullish divergence       +2   (price LL + RSI HL → reversal likely)
  RSI hidden bullish divergence        +1   (price HL + RSI LL → trend continuation)
  OBV rising (accumulation)            +1   (smart money buying on volume) (#136)
  BB squeeze release (upward break)    +2   (high-probability breakout setup) (#137)

SELL score contributors (need >= sell_min_score to emit SELL):
  RSI > rsi_overbought                 +3
  MACD histogram < 0                   +2
  Price >= BB upper band               +2
  RSI regular bearish divergence       +2   (price HH + RSI LH → reversal likely)
"""

import logging
from typing import Optional

from src.analysis.indicators import detect_bb_squeeze_release, detect_rsi_divergence
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
    """
    ind_cfg = config.get("indicators", {})
    sig_cfg = config.get("signals", {})

    # Per-pair config overrides — fall back to global indicators config
    pair_cfg = next(
        (p for p in config.get("trading", {}).get("pairs", []) if p.get("pair") == pair),
        {}
    )
    rsi_oversold   = pair_cfg.get("rsi_oversold",   ind_cfg.get("rsi_oversold", 30))
    rsi_overbought = pair_cfg.get("rsi_overbought",  ind_cfg.get("rsi_overbought", 60))
    bb_min_width   = ind_cfg.get("bb_min_width_pct", 0.5)
    bb_buy_tol     = 1 + ind_cfg.get("bb_buy_tolerance_pct", 1.0) / 100
    bb_sell_tol    = 1 - ind_cfg.get("bb_sell_tolerance_pct", 1.0) / 100

    # BUY score weights
    w_rsi_oversold        = sig_cfg.get("rsi_oversold_score", 3)
    w_rsi_mild_oversold   = sig_cfg.get("rsi_mild_oversold_score", 1)
    w_macd_turn_positive  = sig_cfg.get("macd_turn_positive_score", 3)
    w_macd_hist_pos       = sig_cfg.get("macd_hist_positive_score", 1)
    w_macd_cross          = sig_cfg.get("macd_crossover_score", 1)
    w_bb_lower            = sig_cfg.get("bb_lower_score", 2)
    w_ema_short           = sig_cfg.get("ema_short_uptrend_score", 2)
    w_ema_medium          = sig_cfg.get("ema_medium_trend_score", 1)
    w_fear_greed_fear     = sig_cfg.get("fear_greed_fear_score", 1)
    w_fear_greed_extreme  = sig_cfg.get("fear_greed_extreme_score", 1)
    w_adx_strong          = sig_cfg.get("adx_trend_weight", 1)
    w_div_bull_regular    = sig_cfg.get("rsi_divergence_bullish_weight", 2)
    w_div_bull_hidden     = sig_cfg.get("rsi_divergence_hidden_bullish_weight", 1)
    w_obv_accumulation    = sig_cfg.get("obv_accumulation_weight", 1)       # OBV rising (#136)
    w_bb_squeeze_release  = sig_cfg.get("bb_squeeze_release_weight", 2)     # BB breakout (#137)

    # SELL score weights
    w_rsi_overbought  = sig_cfg.get("rsi_overbought_score", 3)
    w_macd_hist_neg   = sig_cfg.get("macd_hist_negative_score", 2)
    w_bb_upper        = sig_cfg.get("bb_upper_score", 2)
    w_div_bear_regular = sig_cfg.get("rsi_divergence_bearish_weight", 2)

    # Per-pair divergence lookback — shorter for fast/meme pairs, longer for slow movers
    div_lookback = pair_cfg.get("rsi_divergence_lookback", sig_cfg.get("rsi_divergence_lookback", 20))

    # Per-pair OBV trend period — how many candles back to compare OBV for trend (#136)
    obv_trend_period = pair_cfg.get("obv_trend_period", ind_cfg.get("obv_trend_period", 10))

    max_score      = sig_cfg.get("max_score", 16)
    # Per-pair buy_min_score overrides global — tighten for underperformers (#128)
    buy_min_score  = pair_cfg.get("buy_min_score", sig_cfg.get("buy_min_score", 5))
    sell_min_score = sig_cfg.get("sell_min_score", 3)

    # Extract indicator values
    rsi           = indicators.get("rsi_14")
    macd_line     = indicators.get("macd_line")
    macd_sig      = indicators.get("macd_signal_line")
    macd_hist     = indicators.get("macd_histogram")
    macd_hist_prev= indicators.get("macd_histogram_prev")
    ema_9         = indicators.get("ema_9")
    ema_21        = indicators.get("ema_21")
    ema_50        = indicators.get("ema_50")
    bb_upper      = indicators.get("bb_upper")
    bb_lower      = indicators.get("bb_lower")
    atr           = indicators.get("atr_14")
    adx           = indicators.get("adx_14")
    volume        = indicators.get("volume")
    volume_sma_20 = indicators.get("volume_sma_20")
    price         = indicators.get("close", 0.0)
    fear_greed    = indicators.get("fear_greed_index")  # injected by run_cycle

    # RSI divergence — computed from series stored by indicators.py
    rsi_series   = indicators.get("rsi_series", [])
    close_series = indicators.get("close_series", [])
    divergence   = detect_rsi_divergence(close_series, rsi_series, lookback=div_lookback)

    # OBV trend — rising = accumulation (+1 BUY), falling = distribution (#136)
    obv_series    = indicators.get("obv_series", [])
    obv_trend     = _compute_obv_trend(obv_series, obv_trend_period)

    # BB squeeze release — high-probability breakout setup (+2 BUY) (#137)
    bb_width_series = indicators.get("bb_width_series", [])
    bb_squeeze_threshold = (
        pair_cfg.get("bb_squeeze_threshold_pct")
        or config.get("dynamic_tp", {}).get("squeeze_threshold_pct", 1.0)
    )
    bb_squeeze_release_expansion = sig_cfg.get("bb_squeeze_release_expansion_factor", 1.2)
    bb_squeeze_release_lookback  = sig_cfg.get("bb_squeeze_release_lookback", 3)
    bb_mid = indicators.get("bb_mid")
    squeeze_released = detect_bb_squeeze_release(
        bb_width_series,
        threshold=bb_squeeze_threshold,
        lookback=bb_squeeze_release_lookback,
        expansion_factor=bb_squeeze_release_expansion,
        bb_mid=bb_mid,
        price=price,
    )

    buy_score  = 0
    sell_score = 0
    reasons    = []

    # BB pre-computation — needed by both buy and sell paths
    bb_width_pct = ((bb_upper - bb_lower) / price * 100) if (bb_upper and bb_lower and price) else 0
    bb_wide_enough = bb_width_pct >= bb_min_width
    near_lower = bb_wide_enough and bb_lower is not None and price and price <= bb_lower * bb_buy_tol
    near_upper_for_sell = bb_wide_enough and bb_upper is not None and price and price >= bb_upper * bb_sell_tol

    # ── Hard blocker 1: RSI overbought ───────────────────────────────────────
    if rsi is not None and rsi >= 70:
        reasons.append(f"BLOCKED: RSI {rsi:.1f} >= 70 — overbought, no entry")
        # Still evaluate SELL path below
        sell_score = _score_sell(
            rsi, rsi_overbought, macd_hist, near_upper_for_sell, near_lower,
            w_rsi_overbought, w_macd_hist_neg, w_bb_upper, reasons
        )
        return _build_result(pair, 0, sell_score, buy_min_score, sell_min_score, max_score, reasons, price)

    # ── Hard blocker 2: ATR too small to cover fees ───────────────────────────
    # Priority: adaptive floor injected by main.py > per-pair static > global dynamic_tp > min_profit_floor
    min_floor = (
        indicators.get("adaptive_atr_floor_pct")             # injected by main.py when adaptive enabled
        or pair_cfg.get("atr_tp_min_pct")                    # per-pair static (Fix #107)
        or config.get("dynamic_tp", {}).get("atr_tp_min_pct")
        or config.get("trading", {}).get("min_profit_floor_pct", 1.0)
    )
    atr_multiplier = config.get("dynamic_tp", {}).get("atr_multiplier", 2.0)
    if atr and price and price > 0:
        atr_tp_pct = (atr_multiplier * atr / price) * 100
        if atr_tp_pct < min_floor:
            reasons.append(
                f"BLOCKED: ATR-based TP {atr_tp_pct:.2f}% < {min_floor}% floor"
                f" — market too flat to cover fees"
            )
            sell_score = _score_sell(
                rsi, rsi_overbought, macd_hist, near_upper_for_sell, near_lower,
                w_rsi_overbought, w_macd_hist_neg, w_bb_upper, reasons
            )
            return _build_result(pair, 0, sell_score, buy_min_score, sell_min_score, max_score, reasons, price)

    # ── Hard blocker 3: Volume drop-off (Dead Zones) ──────────────────────────
    # Priority: adaptive rolling floor injected by main.py > per-pair static > global
    rolling_vol_p15 = indicators.get("rolling_volume_p15")   # injected by main.py when adaptive enabled
    min_vol_ratio = (
        pair_cfg.get("min_volume_ratio")                      # per-pair static (Fix #111)
        or config.get("trading", {}).get("allowed_trading_hours", {}).get("min_volume_ratio", 0.5)
    )
    if volume is not None:
        # Adaptive floor (rolling p15) takes priority over ratio-based check when injected
        if rolling_vol_p15 is not None:
            vol_blocked = volume < rolling_vol_p15
            vol_reason = (
                f"BLOCKED: Volume ({volume:.2f}) below rolling p15 floor ({rolling_vol_p15:.2f})"
                f" — dead zone detected"
            )
        elif volume_sma_20 is not None and volume_sma_20 > 0:
            vol_blocked = volume < (volume_sma_20 * min_vol_ratio)
            vol_reason = (
                f"BLOCKED: Volume ({volume:.2f}) dropped below {min_vol_ratio * 100:.0f}% "
                f"of average ({volume_sma_20:.2f}) — dead zone detected"
            )
        else:
            vol_blocked = False
            vol_reason = ""
        if vol_blocked:
            reasons.append(vol_reason)
            sell_score = _score_sell(
                rsi, rsi_overbought, macd_hist, near_upper_for_sell, near_lower,
                w_rsi_overbought, w_macd_hist_neg, w_bb_upper, reasons
            )
            return _build_result(pair, 0, sell_score, buy_min_score, sell_min_score, max_score, reasons, price)

    # ── BUY scoring ──────────────────────────────────────────────────────────

    # RSI oversold
    if rsi is not None:
        if rsi < rsi_oversold:
            buy_score += w_rsi_oversold
            reasons.append(f"RSI oversold ({rsi:.1f} < {rsi_oversold})")
        elif rsi < 40:
            buy_score += w_rsi_mild_oversold
            reasons.append(f"RSI mildly oversold ({rsi:.1f} < 40)")

    # MACD histogram — turn is stronger than just being positive
    if macd_hist is not None and macd_hist > 0:
        if macd_hist_prev is not None and macd_hist_prev < 0:
            buy_score += w_macd_turn_positive
            reasons.append(
                f"MACD histogram turned positive ({macd_hist_prev:.5f} → {macd_hist:.5f})"
                f" — momentum crossover"
            )
        else:
            buy_score += w_macd_hist_pos
            reasons.append(f"MACD histogram positive ({macd_hist:.5f})")

    # MACD line vs signal line
    if macd_line is not None and macd_sig is not None and macd_line > macd_sig:
        buy_score += w_macd_cross
        reasons.append("MACD line above signal (bullish crossover)")

    # Bollinger Band lower touch
    if near_lower and not near_upper_for_sell:
        buy_score += w_bb_lower
        reasons.append(f"Price at/near lower Bollinger Band (${price:.4f} <= ${bb_lower:.4f})")

    # EMA short-term: EMA9 > EMA21
    if ema_9 is not None and ema_21 is not None and ema_9 > ema_21:
        buy_score += w_ema_short
        reasons.append(f"EMA9 > EMA21 — short-term momentum positive")

    # EMA medium trend: price > EMA50 (bonus, not a blocker)
    if ema_50 is not None and price and price > ema_50:
        buy_score += w_ema_medium
        reasons.append(f"Price above EMA50 (${price:.4f} > ${ema_50:.4f}) — medium trend support")

    # Fear & Greed sentiment
    if fear_greed is not None:
        if fear_greed <= 25:
            buy_score += w_fear_greed_fear + w_fear_greed_extreme
            reasons.append(f"Fear & Greed: {fear_greed} — extreme fear (buy zone)")
        elif fear_greed <= 40:
            buy_score += w_fear_greed_fear
            reasons.append(f"Fear & Greed: {fear_greed} — fear (supportive for buys)")

    # ADX trend strength — soft modifier (not a hard veto)
    if adx is not None:
        if adx > 40:
            buy_score += w_adx_strong
            reasons.append(f"ADX {adx:.1f} > 40 — strong trend confirmed")
        elif adx < 20:
            buy_score -= w_adx_strong
            reasons.append(f"ADX {adx:.1f} < 20 — ranging market, soft penalty")

    # RSI divergence — bullish signals add to BUY score
    if divergence["bullish_regular"]:
        buy_score += w_div_bull_regular
        reasons.append(f"RSI regular bullish divergence (price LL + RSI HL) — reversal likely")
    if divergence["hidden_bullish"]:
        buy_score += w_div_bull_hidden
        reasons.append(f"RSI hidden bullish divergence (price HL + RSI LL) — trend continuation")

    # OBV trend — accumulation adds to BUY score (#136)
    if obv_trend == "rising":
        buy_score += w_obv_accumulation
        reasons.append(f"OBV rising — volume accumulation detected (smart money buying)")
    elif obv_trend == "falling":
        reasons.append(f"OBV falling — volume distribution detected (smart money selling)")

    # BB squeeze release — high-probability breakout after compression (#137)
    if squeeze_released:
        buy_score += w_bb_squeeze_release
        reasons.append(
            f"BB squeeze release — BB width expanded from squeeze, price broke above midband"
        )

    # ── SELL scoring ─────────────────────────────────────────────────────────
    sell_score = _score_sell(
        rsi, rsi_overbought, macd_hist, near_upper_for_sell, near_lower,
        w_rsi_overbought, w_macd_hist_neg, w_bb_upper,
        w_div_bear_regular, divergence, reasons
    )

    return _build_result(pair, buy_score, sell_score, buy_min_score, sell_min_score, max_score, reasons, price)


def _compute_obv_trend(obv_series: list, period: int = 10) -> str:
    """
    Compare OBV now vs `period` candles ago to determine trend direction.

    Returns "rising", "falling", or "flat".
    A small noise threshold (0.1%) avoids labelling micro-fluctuations as trends.
    """
    if not obv_series or len(obv_series) < period + 1:
        return "flat"
    current = obv_series[-1]
    prior   = obv_series[-(period + 1)]
    if current is None or prior is None or prior == 0:
        return "flat"
    change_pct = (current - prior) / abs(prior)
    if change_pct > 0.001:
        return "rising"
    elif change_pct < -0.001:
        return "falling"
    return "flat"


def _score_sell(
    rsi, rsi_overbought, macd_hist, near_upper_for_sell, near_lower,
    w_rsi_overbought, w_macd_hist_neg, w_bb_upper,
    w_div_bear_regular=0, divergence=None, reasons=None
) -> int:
    if reasons is None:
        reasons = []
    sell_score = 0
    if rsi is not None and rsi > rsi_overbought:
        sell_score += w_rsi_overbought
        reasons.append(f"RSI overbought ({rsi:.1f} > {rsi_overbought})")
    if macd_hist is not None and macd_hist < 0:
        sell_score += w_macd_hist_neg
        reasons.append(f"MACD histogram negative ({macd_hist:.5f}) — bearish momentum")
    if near_upper_for_sell and not near_lower:
        sell_score += w_bb_upper
        reasons.append("Price at/near upper Bollinger Band")
    if divergence and divergence.get("bearish_regular"):
        sell_score += w_div_bear_regular
        reasons.append("RSI regular bearish divergence (price HH + RSI LH) — reversal likely")
    return sell_score


def _build_result(pair, buy_score, sell_score, buy_min_score, sell_min_score, max_score, reasons, price) -> dict:
    if buy_score > sell_score and buy_score >= buy_min_score:
        return {
            "pair":     pair,
            "signal":   "BUY",
            "strength": round(min(buy_score / max_score, 1.0), 2),
            "reasons":  reasons,
            "price":    price,
        }
    elif sell_score > buy_score and sell_score >= sell_min_score:
        return {
            "pair":     pair,
            "signal":   "SELL",
            "strength": round(min(sell_score / max_score, 1.0), 2),
            "reasons":  reasons,
            "price":    price,
        }
    else:
        return {
            "pair":     pair,
            "signal":   "HOLD",
            "strength": 0.0,
            "reasons":  reasons if reasons else ["No clear confluence of signals"],
            "price":    price,
        }
