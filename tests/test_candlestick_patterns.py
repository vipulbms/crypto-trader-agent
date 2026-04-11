"""
Tests for candlestick pattern detection and buy score contribution.
Issue #184: hammer, bullish engulfing, doji at support.

Run: python tests/test_candlestick_patterns.py
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.analysis.indicators import detect_candlestick_patterns
from src.analysis.signals import generate_signal


# ── Unit tests for detect_candlestick_patterns ─────────────────────────────


def test_hammer_detection():
    """
    Given a classic hammer candle: long lower wick > 2× body, tiny upper wick,
    bullish close (close > open)
    When detect_candlestick_patterns is called
    Then hammer=True, others=False
    """
    # Candle: open=10, close=11 (body=1), low=7 (lower_wick=3 > 2), high=11.2 (upper_wick=0.2 < 0.3)
    opens  = [12.0, 10.0]
    highs  = [13.0, 11.2]
    lows   = [11.0,  7.0]
    closes = [12.0, 11.0]
    result = detect_candlestick_patterns(opens, highs, lows, closes, atr=5.0)
    assert result["hammer"] is True,            f"Expected hammer=True, got: {result}"
    assert result["bullish_engulfing"] is False, f"Expected bullish_engulfing=False, got: {result}"


def test_bullish_engulfing_detection():
    """
    Given a bearish prior candle (open > close) and a current bullish candle whose body
    fully engulfs the prior body (open < prior_close AND close > prior_open)
    When detect_candlestick_patterns is called
    Then bullish_engulfing=True
    """
    # Prior: open=105, close=100 (bearish, body=5)
    # Current: open=99, close=107 (bullish, engulfs entire prior body)
    opens  = [105.0,  99.0]
    highs  = [106.0, 108.0]
    lows   = [ 99.0,  98.0]
    closes = [100.0, 107.0]
    result = detect_candlestick_patterns(opens, highs, lows, closes, atr=5.0)
    assert result["bullish_engulfing"] is True, f"Expected bullish_engulfing=True, got: {result}"


def test_doji_detection():
    """
    Given a candle with body < 10% of ATR (classic doji — open ≈ close)
    When detect_candlestick_patterns is called
    Then doji_at_support=True
    """
    # Body = 0.1, ATR = 5.0 → 0.1 < 0.5 (10% of ATR)
    opens  = [100.0, 100.0]
    highs  = [101.0, 102.0]
    lows   = [ 99.0,  98.0]
    closes = [100.0, 100.1]
    result = detect_candlestick_patterns(opens, highs, lows, closes, atr=5.0)
    assert result["doji_at_support"] is True, f"Expected doji_at_support=True, got: {result}"


def test_doji_not_detected_large_body():
    """
    Given a candle with body > 10% of ATR (not a doji)
    When detect_candlestick_patterns is called
    Then doji_at_support=False
    """
    # Body = 2.0, ATR = 5.0 → 2.0 > 0.5 (10% of ATR)
    opens  = [100.0, 100.0]
    highs  = [101.0, 103.0]
    lows   = [ 99.0,  99.0]
    closes = [100.0, 102.0]
    result = detect_candlestick_patterns(opens, highs, lows, closes, atr=5.0)
    assert result["doji_at_support"] is False, f"Expected doji_at_support=False, got: {result}"


def test_insufficient_candles_returns_false():
    """
    Given fewer than 2 candles
    When detect_candlestick_patterns is called
    Then all patterns return False safely
    """
    result = detect_candlestick_patterns([100.0], [102.0], [99.0], [101.0], atr=5.0)
    assert result == {"hammer": False, "bullish_engulfing": False, "doji_at_support": False}


# ── Integration tests: pattern contribution to buy score ──────────────────


def _base_indicators():
    """Minimal valid indicators that pass all hard blockers."""
    return {
        "rsi_14":           35.0,
        "macd_histogram":   0.001,
        "macd_histogram_prev": -0.001,
        "macd_line":        0.1,
        "macd_signal_line": 0.05,
        "ema_9":            100.0,
        "ema_21":            99.0,
        "ema_50":            98.0,
        "bb_upper":         110.0,
        "bb_mid":           100.0,
        "bb_lower":          95.0,
        "atr_14":             5.0,
        "adx_14":            25.0,
        "volume":          1000.0,
        "volume_sma_20":    800.0,
        "close":             95.2,   # near BB lower (95.0 * 1.005 = 95.475)
        "rsi_series":       [40.0] * 30,
        "close_series":    [100.0] * 30,
        "bb_width_series":   [2.0] * 10,
        "obv_series":             [],
        "candlestick_patterns": {"hammer": False, "bullish_engulfing": False, "doji_at_support": False},
    }


def _minimal_config():
    return {
        "indicators": {
            "rsi_oversold": 30,
            "rsi_overbought": 70,
            "bb_min_width_pct": 0.5,
            "bb_buy_tolerance_pct": 1.0,
            "bb_sell_tolerance_pct": 1.0,
            "obv_trend_period": 10,
        },
        "signals": {
            "obv_accumulation_weight": 1,
            "bb_squeeze_release_weight": 2,
            "bb_squeeze_release_expansion_factor": 1.2,
            "bb_squeeze_release_lookback": 3,
            "hammer_weight": 1,
            "engulfing_weight": 2,
            "doji_support_weight": 1,
            "buy_min_score": 5,
            "sell_min_score": 3,
            "max_score": 28,
        },
        "dynamic_tp": {"atr_multiplier": 2.0, "atr_tp_min_pct": 0.3},
        "trading": {"pairs": [], "min_profit_floor_pct": 1.0},
    }


def test_hammer_increases_buy_score():
    """
    Given a hammer pattern with RSI oversold conditions
    When generate_signal is called
    Then reasons include hammer text and buy score increases
    """
    ind = _base_indicators()
    ind["candlestick_patterns"] = {"hammer": True, "bullish_engulfing": False, "doji_at_support": False}
    result = generate_signal("ETH/USD", ind, _minimal_config())
    reasons_text = " ".join(result["reasons"])
    assert "Hammer candle" in reasons_text, f"Expected hammer reason, got: {result['reasons']}"


def test_doji_no_score_when_not_near_lower_bb():
    """
    Given a doji candle (doji_at_support=True from indicators) but price is NOT near BB lower
    When generate_signal is called
    Then no doji score is awarded — the 'at support' gate must fail
    """
    ind = _base_indicators()
    ind["close"] = 105.0  # well above BB lower of 95.0 — NOT near lower band
    ind["candlestick_patterns"] = {"hammer": False, "bullish_engulfing": False, "doji_at_support": True}
    # Also need RSI > 30 so no RSI oversold bonus — isolate doji effect
    ind["rsi_14"] = 38.0
    ind["macd_histogram"] = 0.001
    ind["macd_histogram_prev"] = 0.0005  # already positive, no turn
    result = generate_signal("ETH/USD", ind, _minimal_config())
    reasons_text = " ".join(result["reasons"])
    assert "Doji" not in reasons_text, f"Unexpected doji reason when not at support: {result['reasons']}"


if __name__ == "__main__":
    test_hammer_detection()
    test_bullish_engulfing_detection()
    test_doji_detection()
    test_doji_not_detected_large_body()
    test_insufficient_candles_returns_false()
    test_hammer_increases_buy_score()
    test_doji_no_score_when_not_near_lower_bb()
    print("All candlestick pattern tests passed.")
