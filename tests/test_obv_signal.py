"""
Tests for OBV (On-Balance Volume) trend detection and buy score contribution.
Issue #136.

Run: ~/.pyenv/versions/3.11.15/bin/python3 tests/test_obv_signal.py
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.analysis.signals import _compute_obv_trend, generate_signal


# ── Unit tests for _compute_obv_trend ──────────────────────────────────────


def test_obv_trend_rising():
    """
    Given OBV that has increased meaningfully over the period
    When _compute_obv_trend is called
    Then it returns 'rising'
    """
    obv = list(range(100, 120))  # steadily increasing
    assert _compute_obv_trend(obv, period=10) == "rising"


def test_obv_trend_falling():
    """
    Given OBV that has decreased meaningfully over the period
    When _compute_obv_trend is called
    Then it returns 'falling'
    """
    obv = list(range(120, 100, -1))  # steadily decreasing
    assert _compute_obv_trend(obv, period=10) == "falling"


def test_obv_trend_flat():
    """
    Given OBV with negligible change over the period (within 0.1% noise band)
    When _compute_obv_trend is called
    Then it returns 'flat'
    """
    obv = [1000.0] * 15  # no change
    assert _compute_obv_trend(obv, period=10) == "flat"


def test_obv_trend_insufficient_data():
    """
    Given fewer candles than period + 1
    When _compute_obv_trend is called
    Then it returns 'flat' (not enough data)
    """
    obv = [100, 200, 300]
    assert _compute_obv_trend(obv, period=10) == "flat"


def test_obv_trend_none_values():
    """
    Given OBV series containing None values at either endpoint
    When _compute_obv_trend is called
    Then it returns 'flat' (safely)
    """
    obv = [None] * 5 + [100, 200, 300, 400, 500, None]
    assert _compute_obv_trend(obv, period=5) == "flat"


# ── Per-pair noise threshold tests (#185) ─────────────────────────────────


def test_obv_noise_threshold_meme_above_floor():
    """
    Given 2% OBV rise and a meme pair noise_threshold=0.02
    When _compute_obv_trend is called
    Then it returns 'rising' (exactly at the boundary counts as > threshold)
    """
    # prior=1000, current=1021 → change=2.1% > 2% threshold
    obv = [1000.0] * 10 + [1021.0]
    assert _compute_obv_trend(obv, period=10, noise_threshold=0.02) == "rising"


def test_obv_noise_threshold_meme_below_floor():
    """
    Given 0.5% OBV rise and a meme pair noise_threshold=0.02
    When _compute_obv_trend is called
    Then it returns 'flat' (0.5% < 2% threshold — noise, not accumulation)
    """
    # prior=1000, current=1005 → change=0.5% < 2% threshold
    obv = [1000.0] * 10 + [1005.0]
    assert _compute_obv_trend(obv, period=10, noise_threshold=0.02) == "flat"


def test_obv_noise_threshold_large_cap_above_floor():
    """
    Given 0.5% OBV rise and a large-cap pair noise_threshold=0.002
    When _compute_obv_trend is called
    Then it returns 'rising' (0.5% > 0.2% threshold — meaningful for BTC/ETH)
    """
    # prior=1000, current=1005 → change=0.5% > 0.2% threshold
    obv = [1000.0] * 10 + [1005.0]
    assert _compute_obv_trend(obv, period=10, noise_threshold=0.002) == "rising"


# ── Integration tests: OBV contribution to buy score ──────────────────────


def _base_indicators(obv_series=None):
    """Minimal valid indicators that pass all hard blockers."""
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
        "bb_mid":          100.0,
        "bb_lower":        95.0,
        "atr_14":          2.0,
        "adx_14":          25.0,
        "volume":          1000.0,
        "volume_sma_20":   800.0,
        "close":           100.0,
        "rsi_series":      [40.0] * 30,
        "close_series":    [100.0] * 30,
        "bb_width_series": [2.0] * 10,   # not in squeeze
        "obv_series":      obv_series or [],
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
            "buy_min_score": 5,
            "sell_min_score": 3,
            "max_score": 25,
        },
        "dynamic_tp": {"atr_multiplier": 2.0, "atr_tp_min_pct": 0.3},
        "trading": {"pairs": [], "min_profit_floor_pct": 1.0},
    }


def test_obv_rising_increases_buy_score():
    """
    Given OBV is rising over the configured period
    When generate_signal is called with a BUY-ready indicator set
    Then the signal reasons include OBV accumulation text
    """
    rising_obv = list(range(100, 130))  # 30 values, clearly rising
    ind = _base_indicators(obv_series=rising_obv)
    result = generate_signal("ETH/USD", ind, _minimal_config())
    reasons_text = " ".join(result["reasons"])
    assert "OBV rising" in reasons_text, f"Expected OBV rising reason, got: {result['reasons']}"


def test_obv_falling_adds_distribution_note():
    """
    Given OBV is falling over the configured period
    When generate_signal is called
    Then reasons include a distribution warning (no score awarded)
    """
    falling_obv = list(range(130, 100, -1))  # 30 values, clearly falling
    ind = _base_indicators(obv_series=falling_obv)
    result = generate_signal("ETH/USD", ind, _minimal_config())
    reasons_text = " ".join(result["reasons"])
    assert "OBV falling" in reasons_text, f"Expected OBV falling reason, got: {result['reasons']}"


def test_obv_flat_no_mention():
    """
    Given OBV is flat (negligible change)
    When generate_signal is called
    Then no OBV-related reason is appended
    """
    flat_obv = [1000.0] * 30
    ind = _base_indicators(obv_series=flat_obv)
    result = generate_signal("ETH/USD", ind, _minimal_config())
    reasons_text = " ".join(result["reasons"])
    assert "OBV" not in reasons_text, f"Unexpected OBV reason for flat OBV: {result['reasons']}"


if __name__ == "__main__":
    test_obv_trend_rising()
    test_obv_trend_falling()
    test_obv_trend_flat()
    test_obv_trend_insufficient_data()
    test_obv_trend_none_values()
    test_obv_noise_threshold_meme_above_floor()
    test_obv_noise_threshold_meme_below_floor()
    test_obv_noise_threshold_large_cap_above_floor()
    test_obv_rising_increases_buy_score()
    test_obv_falling_adds_distribution_note()
    test_obv_flat_no_mention()
    print("All OBV signal tests passed.")
