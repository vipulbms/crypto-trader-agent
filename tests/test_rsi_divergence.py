"""
Tests for RSI divergence detection (GH #135).

Tests cover:
  - detect_rsi_divergence() directly (unit tests)
  - Integration via generate_signal() (scoring tests)

Run:
    ~/.pyenv/versions/3.11.15/bin/python3 tests/test_rsi_divergence.py
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.analysis.indicators import detect_rsi_divergence


# ── Unit tests for detect_rsi_divergence() ────────────────────────────────────

def test_regular_bullish_divergence_detected():
    """
    Given price makes a lower low in the second half of the lookback window
    And RSI makes a higher low at the same region
    When detect_rsi_divergence() is called
    Then bullish_regular is True
    """
    # First half: price low = 100, RSI low = 30
    # Second half: price low = 95 (lower), RSI low = 35 (higher) → regular bullish divergence
    prices = [105, 100, 103, 106, 102,  # first half — low at index 1 (price=100)
              104, 101, 98,  95,  97]   # second half — low at index 3 (price=95)
    rsi    = [45,  30,  38,  42,  36,   # first half — low at index 1 (rsi=30)
              40,  37,  36,  35,  38]   # second half — low at index 3 (rsi=35)

    result = detect_rsi_divergence(prices, rsi, lookback=10)

    assert result["bullish_regular"] is True, (
        f"Expected bullish_regular=True. Got: {result}"
    )
    assert result["bearish_regular"] is False
    print("PASS: test_regular_bullish_divergence_detected")


def test_regular_bearish_divergence_detected():
    """
    Given price makes a higher high in the second half of the lookback window
    And RSI makes a lower high at the same region
    When detect_rsi_divergence() is called
    Then bearish_regular is True
    """
    # First half: price high = 110, RSI high = 70
    # Second half: price high = 115 (higher), RSI high = 65 (lower) → regular bearish divergence
    prices = [105, 110, 107, 104, 106,  # first half — high at index 1 (price=110)
              108, 112, 115, 111, 109]  # second half — high at index 2 (price=115)
    rsi    = [55,  70,  65,  60,  63,   # first half — high at index 1 (rsi=70)
              60,  66,  65,  62,  60]   # second half — high at index 2 (rsi=65)

    result = detect_rsi_divergence(prices, rsi, lookback=10)

    assert result["bearish_regular"] is True, (
        f"Expected bearish_regular=True. Got: {result}"
    )
    assert result["bullish_regular"] is False
    print("PASS: test_regular_bearish_divergence_detected")


def test_hidden_bullish_divergence_detected():
    """
    Given price makes a higher low in the second half (trend continuation up)
    And RSI makes a lower low
    When detect_rsi_divergence() is called
    Then hidden_bullish is True
    """
    # First half: price low = 95, RSI low = 28
    # Second half: price low = 98 (higher), RSI low = 25 (lower) → hidden bullish
    prices = [100, 95,  98,  102, 99,   # first half — low at index 1 (price=95)
              101, 103, 98,  100, 104]  # second half — low at index 2 (price=98)
    rsi    = [40,  28,  33,  38,  35,   # first half — low at index 1 (rsi=28)
              36,  39,  25,  30,  38]   # second half — low at index 2 (rsi=25)

    result = detect_rsi_divergence(prices, rsi, lookback=10)

    assert result["hidden_bullish"] is True, (
        f"Expected hidden_bullish=True. Got: {result}"
    )
    print("PASS: test_hidden_bullish_divergence_detected")


def test_no_divergence_when_price_and_rsi_move_together():
    """
    Given price and RSI both make lower lows (no divergence)
    When detect_rsi_divergence() is called
    Then all divergence flags are False
    """
    # Price and RSI both trending down — no divergence
    prices = [110, 105, 108, 106, 104,
              103, 100, 98,  96,  95]
    rsi    = [55,  50,  52,  48,  46,
              44,  40,  37,  33,  30]

    result = detect_rsi_divergence(prices, rsi, lookback=10)

    assert result["bullish_regular"] is False
    assert result["bearish_regular"] is False
    assert result["hidden_bullish"]  is False, (
        f"Expected no divergence. Got: {result}"
    )
    print("PASS: test_no_divergence_when_price_and_rsi_move_together")


def test_insufficient_data_returns_all_false():
    """
    Given fewer than 4 data points
    When detect_rsi_divergence() is called
    Then all flags are False (no crash)
    """
    result = detect_rsi_divergence([100, 98], [30, 28], lookback=20)
    assert result == {"bullish_regular": False, "bearish_regular": False, "hidden_bullish": False}
    print("PASS: test_insufficient_data_returns_all_false")


def test_none_values_in_series_returns_all_false():
    """
    Given a series containing None values (incomplete indicators)
    When detect_rsi_divergence() is called
    Then all flags are False (graceful handling)
    """
    prices = [100, None, 98, 95, 97, 96, 94, 92, 90, 91]
    rsi    = [40,  35,   38, 30, 32, 33, 31, 29, 35, 36]
    result = detect_rsi_divergence(prices, rsi, lookback=10)
    assert result == {"bullish_regular": False, "bearish_regular": False, "hidden_bullish": False}
    print("PASS: test_none_values_in_series_returns_all_false")


# ── Integration tests via generate_signal() ───────────────────────────────────

def _config() -> dict:
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
            "rsi_divergence_lookback": 10,
            "rsi_overbought_score": 3,
            "macd_hist_negative_score": 2,
            "bb_upper_score": 2,
            "buy_min_score": 5,
            "sell_min_score": 3,
            "max_score": 22,
        },
        "trading": {
            "pairs": [{"pair": "ETH/USD", "atr_tp_min_pct": 0.1, "stop_loss_pct": 5, "take_profit_pct": 12}],
            "min_profit_floor_pct": 1.0,
        },
        "dynamic_tp": {"atr_tp_min_pct": 0.10, "atr_multiplier": 2.0},
    }


def test_bullish_divergence_adds_to_buy_score():
    """
    Given indicators with regular bullish RSI divergence
    When generate_signal() is called
    Then the reasons list includes the bullish divergence reason
    And the signal is BUY (divergence contributes +2 to score)
    """
    from src.analysis.signals import generate_signal

    # Construct close_series and rsi_series that produce regular bullish divergence
    # (lookback=10): first half low price=95/rsi=30, second half low price=90/rsi=35
    close_series = [105, 95,  103, 106, 102,   # first half — low at idx 1 (price=95)
                    104, 101, 90,  92,  97]     # second half — low at idx 2 (price=90)
    rsi_series   = [45,  30,  38,  42,  36,    # first half — low at idx 1 (rsi=30)
                    40,  37,  35,  36,  38]    # second half — low at idx 2 (rsi=35, higher)

    indicators = {
        "rsi_14": 36.0,           # mild oversold +1
        "macd_line": 0.01,
        "macd_signal_line": 0.005,
        "macd_histogram": 0.005,  # positive +1
        "macd_histogram_prev": 0.002,
        "ema_9": 100.0,
        "ema_21": 99.0,           # EMA9 > EMA21 +2
        "ema_50": 98.0,
        "bb_upper": 110.0,
        "bb_lower": 90.0,
        "atr_14": 2.0,
        "adx_14": 25.0,           # neutral ADX — no modifier
        "volume": 1000.0,
        "volume_sma_20": 800.0,
        "close": 97.0,
        "rsi_series": rsi_series,
        "close_series": close_series,
    }

    result = generate_signal("ETH/USD", indicators, _config())

    assert result["signal"] == "BUY", (
        f"Expected BUY with bullish divergence. Got {result['signal']}. Reasons: {result['reasons']}"
    )
    assert any("bullish divergence" in r.lower() for r in result["reasons"]), (
        f"Expected bullish divergence reason. Got: {result['reasons']}"
    )
    print("PASS: test_bullish_divergence_adds_to_buy_score")


def test_bearish_divergence_adds_to_sell_score():
    """
    Given indicators with regular bearish RSI divergence
    When generate_signal() is called
    Then the reasons list includes the bearish divergence reason
    And the signal reflects increased SELL score
    """
    from src.analysis.signals import generate_signal

    # Regular bearish: first half high price=110/rsi=68, second half high price=115/rsi=63
    close_series = [105, 110, 107, 104, 106,
                    108, 112, 115, 111, 109]
    rsi_series   = [58,  68,  62,  57,  60,
                    63,  66,  63,  60,  58]

    indicators = {
        "rsi_14": 64.0,           # moderately overbought — but below 75 veto
        "macd_line": -0.01,
        "macd_signal_line": 0.005,
        "macd_histogram": -0.005,  # negative — sell signal
        "macd_histogram_prev": 0.002,
        "ema_9": 115.0,
        "ema_21": 116.0,
        "ema_50": 108.0,
        "bb_upper": 116.0,
        "bb_lower": 95.0,
        "atr_14": 2.0,
        "adx_14": 30.0,
        "volume": 1000.0,
        "volume_sma_20": 800.0,
        "close": 114.0,
        "rsi_series": rsi_series,
        "close_series": close_series,
    }

    result = generate_signal("ETH/USD", indicators, _config())

    assert any("bearish divergence" in r.lower() for r in result["reasons"]), (
        f"Expected bearish divergence reason. Got: {result['reasons']}"
    )
    print("PASS: test_bearish_divergence_adds_to_sell_score")


if __name__ == "__main__":
    # Unit tests
    test_regular_bullish_divergence_detected()
    test_regular_bearish_divergence_detected()
    test_hidden_bullish_divergence_detected()
    test_no_divergence_when_price_and_rsi_move_together()
    test_insufficient_data_returns_all_false()
    test_none_values_in_series_returns_all_false()
    # Integration tests
    test_bullish_divergence_adds_to_buy_score()
    test_bearish_divergence_adds_to_sell_score()
    print("\nAll RSI divergence tests passed.")
