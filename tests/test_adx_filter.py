"""
Tests for ADX trend strength filter in signal scoring (GH #134).

Run:
    ~/.pyenv/versions/3.11.15/bin/python3 tests/test_adx_filter.py
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


def _base_indicators(adx: float) -> dict:
    """Return a minimal valid indicators dict with the given ADX value."""
    return {
        "rsi_14":              35.0,    # mild oversold — gives buy_score=1 baseline
        "macd_line":           0.01,
        "macd_signal_line":    0.005,
        "macd_histogram":      0.005,   # positive, not a turn
        "macd_histogram_prev": 0.002,
        "ema_9":               100.0,
        "ema_21":              99.0,    # EMA9 > EMA21 → +2
        "ema_50":              98.0,
        "bb_upper":            110.0,
        "bb_lower":            90.0,
        "atr_14":              2.0,
        "adx_14":              adx,
        "volume":              1000.0,
        "volume_sma_20":       800.0,
        "close":               100.0,
        "rsi_series":          [],
        "close_series":        [],
    }


def _config(buy_min_score: int = 4) -> dict:
    return {
        "indicators": {
            "rsi_oversold": 30,
            "rsi_overbought": 75,
            "bb_min_width_pct": 0.5,
            "bb_buy_tolerance_pct": 0.5,
            "bb_sell_tolerance_pct": 0.5,
            "atr_period": 14,
            "adx_period": 14,
        },
        "signals": {
            "rsi_oversold_score": 3,
            "rsi_mild_oversold_score": 1,
            "macd_turn_positive_score": 3,
            "macd_hist_positive_score": 1,
            "macd_crossover_score": 1,
            "bb_lower_score": 2,
            "ema_short_uptrend_score": 2,
            "ema_medium_trend_score": 1,
            "fear_greed_fear_score": 1,
            "fear_greed_extreme_score": 1,
            "adx_trend_weight": 1,
            "rsi_divergence_bullish_weight": 2,
            "rsi_divergence_hidden_bullish_weight": 1,
            "rsi_divergence_bearish_weight": 2,
            "rsi_divergence_lookback": 20,
            "rsi_overbought_score": 3,
            "macd_hist_negative_score": 2,
            "bb_upper_score": 2,
            "buy_min_score": buy_min_score,
            "sell_min_score": 3,
            "max_score": 22,
        },
        "trading": {
            "pairs": [{"pair": "BTC/USD", "atr_tp_min_pct": 0.1, "stop_loss_pct": 5, "take_profit_pct": 8}],
            "min_profit_floor_pct": 1.0,
        },
        "dynamic_tp": {"atr_tp_min_pct": 0.10, "atr_multiplier": 2.0},
    }


def test_adx_below_20_reduces_buy_score():
    """
    Given ADX < 20 (ranging/choppy market)
    When a BUY signal is evaluated
    Then the buy score is reduced by adx_trend_weight (soft penalty, not a hard veto)
    """
    from src.analysis.signals import generate_signal

    # Baseline score without ADX penalty:
    # RSI mild oversold (+1) + MACD hist pos (+1) + MACD cross (+1)
    # + EMA9>EMA21 (+2) + price>EMA50 (+1) = 6
    # With ADX < 20: -1 → score = 5
    # buy_min_score = 6 → should HOLD (penalty pushes below threshold)
    ind = _base_indicators(adx=15.0)
    cfg = _config(buy_min_score=6)
    result = generate_signal("BTC/USD", ind, cfg)

    assert result["signal"] == "HOLD", (
        f"Expected HOLD (ADX=15 penalty reduces score below threshold), got {result['signal']}. "
        f"Reasons: {result['reasons']}"
    )
    assert any("ADX" in r and "< 20" in r for r in result["reasons"]), (
        f"Expected ADX ranging penalty in reasons. Got: {result['reasons']}"
    )
    print("PASS: test_adx_below_20_reduces_buy_score")


def test_adx_above_40_increases_buy_score():
    """
    Given ADX > 40 (strong directional trend)
    When a BUY signal is evaluated
    Then the buy score is increased by adx_trend_weight (+1 bonus)
    """
    from src.analysis.signals import generate_signal

    # Score without ADX: RSI mild (+1) + MACD hist (+1) + MACD cross (+1)
    # + EMA9>EMA21 (+2) + price>EMA50 (+1) = 6
    # buy_min_score = 7 → would HOLD without ADX boost
    # With ADX > 40: +1 → score = 7 → BUY fires, ADX boost reason is present
    ind = _base_indicators(adx=45.0)
    cfg = _config(buy_min_score=7)
    result = generate_signal("BTC/USD", ind, cfg)

    assert result["signal"] == "BUY", (
        f"Expected BUY (ADX=45 boosts score), got {result['signal']}. "
        f"Reasons: {result['reasons']}"
    )
    assert any("ADX" in r and "> 40" in r for r in result["reasons"]), (
        f"Expected ADX strong trend boost in reasons. Got: {result['reasons']}"
    )
    print("PASS: test_adx_above_40_increases_buy_score")


def test_adx_neutral_range_no_modification():
    """
    Given ADX between 20-40 (moderate trend — neutral zone)
    When a BUY signal is evaluated
    Then no ADX score modification is applied
    """
    from src.analysis.signals import generate_signal

    ind = _base_indicators(adx=28.0)
    cfg = _config(buy_min_score=6)
    result = generate_signal("BTC/USD", ind, cfg)

    # No ADX reason should appear
    assert not any("ADX" in r for r in result["reasons"]), (
        f"Expected no ADX reason for ADX=28 (neutral zone). Got: {result['reasons']}"
    )
    # Score unchanged: 6 → BUY
    assert result["signal"] == "BUY", (
        f"Expected BUY (ADX=28 neutral, score unchanged), got {result['signal']}"
    )
    print("PASS: test_adx_neutral_range_no_modification")


def test_adx_below_20_is_soft_penalty_not_hard_veto():
    """
    Given ADX < 20 (ranging market) BUT very strong confluence otherwise
    When a BUY signal is evaluated
    Then the signal can still be BUY — ADX < 20 is a soft penalty, not a hard veto
    """
    from src.analysis.signals import generate_signal

    # Give a very strong confluence that survives a -1 penalty
    ind = _base_indicators(adx=10.0)
    ind["rsi_14"] = 25.0    # deep oversold → +3
    ind["macd_histogram_prev"] = -0.005  # histogram turned positive → +3 (not +1)
    # Score: RSI oversold (+3) + MACD turn (+3) + MACD cross (+1) + EMA9>EMA21 (+2) - ADX penalty (-1) = 8
    cfg = _config(buy_min_score=5)
    result = generate_signal("BTC/USD", ind, cfg)

    assert result["signal"] == "BUY", (
        f"Expected BUY (strong confluence overrides ADX<20 soft penalty), got {result['signal']}. "
        f"Reasons: {result['reasons']}"
    )
    print("PASS: test_adx_below_20_is_soft_penalty_not_hard_veto")


if __name__ == "__main__":
    test_adx_below_20_reduces_buy_score()
    test_adx_above_40_increases_buy_score()
    test_adx_neutral_range_no_modification()
    test_adx_below_20_is_soft_penalty_not_hard_veto()
    print("\nAll ADX filter tests passed.")
