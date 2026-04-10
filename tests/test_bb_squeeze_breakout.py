"""
Tests for BB squeeze release detection and buy score contribution.
Issue #137.

Run: ~/.pyenv/versions/3.11.15/bin/python3 tests/test_bb_squeeze_breakout.py
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.analysis.indicators import detect_bb_squeeze_release
from src.analysis.signals import generate_signal


# ── Unit tests for detect_bb_squeeze_release ───────────────────────────────


def test_squeeze_release_detected():
    """
    Given 3 prior candles in squeeze (width < threshold)
    And current candle expands to threshold × 1.3 (above expansion_factor=1.2)
    And price is above BB midband
    When detect_bb_squeeze_release is called
    Then it returns True
    """
    threshold = 1.0
    # 3 squeeze candles + 1 release candle
    bb_width_series = [0.8, 0.7, 0.9, 0.8, 0.9, 0.85, 0.7, 1.3]
    result = detect_bb_squeeze_release(
        bb_width_series, threshold=threshold, lookback=3,
        expansion_factor=1.2, bb_mid=99.0, price=101.0
    )
    assert result is True, "Expected squeeze release to be detected"


def test_no_prior_squeeze():
    """
    Given all prior candles had BB width above threshold (no squeeze)
    When detect_bb_squeeze_release is called
    Then it returns False
    """
    threshold = 1.0
    bb_width_series = [1.5, 1.6, 1.7, 1.8, 1.9, 1.8, 1.7, 2.0]
    result = detect_bb_squeeze_release(
        bb_width_series, threshold=threshold, lookback=3,
        expansion_factor=1.2, bb_mid=99.0, price=101.0
    )
    assert result is False, "No prior squeeze — should not detect release"


def test_current_candle_not_expanded_enough():
    """
    Given 3 prior candles in squeeze
    But current candle width only reaches threshold exactly (not threshold × 1.2)
    When detect_bb_squeeze_release is called
    Then it returns False (insufficient expansion)
    """
    threshold = 1.0
    bb_width_series = [0.8, 0.7, 0.9, 0.8, 0.9, 0.85, 0.7, 1.05]  # 1.05 < 1.0 × 1.2 = 1.2
    result = detect_bb_squeeze_release(
        bb_width_series, threshold=threshold, lookback=3,
        expansion_factor=1.2, bb_mid=99.0, price=101.0
    )
    assert result is False, "Expansion not sufficient — should not detect release"


def test_downward_breakout_rejected():
    """
    Given 3 prior candles in squeeze and BB expanded
    But price is below BB midband (downward breakout)
    When detect_bb_squeeze_release is called
    Then it returns False (only upward breakouts rewarded)
    """
    threshold = 1.0
    bb_width_series = [0.8, 0.7, 0.9, 0.8, 0.9, 0.85, 0.7, 1.3]
    result = detect_bb_squeeze_release(
        bb_width_series, threshold=threshold, lookback=3,
        expansion_factor=1.2, bb_mid=101.0, price=99.0   # price < midband
    )
    assert result is False, "Downward breakout should not be rewarded"


def test_insufficient_series_length():
    """
    Given a BB width series shorter than lookback + 1
    When detect_bb_squeeze_release is called
    Then it returns False (not enough data)
    """
    result = detect_bb_squeeze_release([0.8, 1.3], threshold=1.0, lookback=3)
    assert result is False, "Insufficient data should return False"


def test_no_midband_price_check_when_not_provided():
    """
    Given squeeze release conditions met but no bb_mid/price provided
    When detect_bb_squeeze_release is called
    Then it returns True (price check skipped gracefully)
    """
    threshold = 1.0
    bb_width_series = [0.8, 0.7, 0.9, 0.8, 0.9, 0.85, 0.7, 1.3]
    result = detect_bb_squeeze_release(
        bb_width_series, threshold=threshold, lookback=3, expansion_factor=1.2
        # bb_mid and price omitted
    )
    assert result is True, "Without price/mid check, valid squeeze release should be detected"


# ── Integration test: BB squeeze release adds +2 to buy score ──────────────


def _base_indicators(bb_width_series=None):
    """Minimal valid indicators — all hard blockers pass."""
    return {
        "rsi_14":          35.0,
        "macd_histogram":  0.001,
        "macd_histogram_prev": -0.001,
        "macd_line":       0.1,
        "macd_signal_line": 0.05,
        "ema_9":           100.0,
        "ema_21":          99.0,
        "ema_50":          98.0,
        "bb_upper":        105.0,
        "bb_mid":          99.0,
        "bb_lower":        95.0,
        "atr_14":          2.0,
        "adx_14":          25.0,
        "volume":          1000.0,
        "volume_sma_20":   800.0,
        "close":           101.0,   # price > bb_mid (99.0) → upward breakout
        "rsi_series":      [40.0] * 30,
        "close_series":    [100.0] * 30,
        "obv_series":      [],
        "bb_width_series": bb_width_series or [],
    }


def _minimal_config(bb_squeeze_threshold=1.0):
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
            "buy_min_score": 5,
            "sell_min_score": 3,
            "max_score": 25,
        },
        "dynamic_tp": {
            "atr_multiplier": 2.0,
            "atr_tp_min_pct": 0.3,
            "squeeze_threshold_pct": bb_squeeze_threshold,
        },
        "trading": {
            "pairs": [
                {"pair": "ETH/USD", "bb_squeeze_threshold_pct": bb_squeeze_threshold}
            ],
            "min_profit_floor_pct": 1.0,
        },
    }


def test_squeeze_release_adds_to_buy_score():
    """
    Given a BB squeeze release pattern (3 squeeze candles then expansion above midband)
    When generate_signal is called
    Then reasons include BB squeeze release text
    """
    # 3 squeeze candles (0.7-0.9%) then release (1.3%)  — threshold = 1.0%
    bb_width = [2.0, 2.0, 2.0, 2.0, 0.8, 0.7, 0.9, 1.3]
    ind = _base_indicators(bb_width_series=bb_width)
    result = generate_signal("ETH/USD", ind, _minimal_config(bb_squeeze_threshold=1.0))
    reasons_text = " ".join(result["reasons"])
    assert "BB squeeze release" in reasons_text, (
        f"Expected BB squeeze release reason, got: {result['reasons']}"
    )


def test_no_squeeze_release_no_bonus():
    """
    Given BB widths are all above threshold (never in squeeze)
    When generate_signal is called
    Then reasons do NOT include BB squeeze release text
    """
    bb_width = [2.0] * 8  # always wide, no squeeze
    ind = _base_indicators(bb_width_series=bb_width)
    result = generate_signal("ETH/USD", ind, _minimal_config(bb_squeeze_threshold=1.0))
    reasons_text = " ".join(result["reasons"])
    assert "BB squeeze release" not in reasons_text, (
        f"Unexpected BB squeeze release: {result['reasons']}"
    )


if __name__ == "__main__":
    test_squeeze_release_detected()
    test_no_prior_squeeze()
    test_current_candle_not_expanded_enough()
    test_downward_breakout_rejected()
    test_insufficient_series_length()
    test_no_midband_price_check_when_not_provided()
    test_squeeze_release_adds_to_buy_score()
    test_no_squeeze_release_no_bonus()
    print("All BB squeeze breakout tests passed.")
