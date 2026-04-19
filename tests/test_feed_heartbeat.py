"""
Tests for S13.2.1 — Per-cycle OHLCV variance heartbeat (frozen feed detection).

Story: S13.2.1 | Sprint: S2 | Epic: E13 — QSA Data Resilience

Covers:
  AC1: compute_indicators() returns feed_status key
  AC2: feed_status == 'FROZEN' when all OHLCV columns have zero variance across last 3 candles
  AC3: feed_status == 'OK' for normal candles
  AC4: signals.py forces HOLD when feed_status == 'FROZEN'; reason = 'feed_frozen'
  AC5: signals.py returns normal BUY/SELL/HOLD for feed_status == 'OK'
"""
import time

import pytest

from src.analysis.indicators import compute_indicators
from src.analysis.signals import generate_signal


# ── Config helpers ────────────────────────────────────────────────────────────

def _base_config() -> dict:
    return {
        "trading": {
            "candle_interval": 15,
            "pairs": [],
        },
        "indicators": {
            "min_candles_to_start": 30,
            "rsi_oversold": 30,
            "rsi_overbought": 65,
            "min_candles_to_start": 30,
        },
        "signals": {
            "buy_min_score": 5,
            "sell_min_score": 3,
            "max_score": 28,
            "profit_factor_escalation": {"enabled": False},
        },
        "qsa": {
            "volume_floor": {
                "algorithm": "winsorized_ema",
                "period": 14,
                "winsorize_percentile": 95,
                "winsorize_lookback": 100,
            },
            "feed_heartbeat": {
                "enabled": True,
                "variance_lookback": 3,
                "freeze_alert_cycles": 3,
            },
        },
        "dynamic_tp": {
            "atr_tp_min_pct": 0.3,
            "atr_multiplier": 2.0,
        },
    }


def _make_candles(n: int, freeze_last: int = 0, volume: float = 1000.0) -> list:
    """
    Generate n OHLCV candles.  When freeze_last > 0, the last `freeze_last`
    candles are identical (all values the same) to simulate a frozen feed.
    """
    t_now = int(time.time())
    candles = []
    for i in range(n):
        ts = t_now - (n - i) * 900
        close = 50000.0 + i * 10  # strictly incrementing to avoid accidental freeze
        candles.append({
            "timestamp": ts,
            "open": close - 5, "high": close + 10, "low": close - 10,
            "close": close, "volume": volume + i,
        })

    # Overwrite the last `freeze_last` candles with identical values
    if freeze_last > 0:
        ref = candles[-freeze_last]
        for j in range(freeze_last):
            candles[-(freeze_last - j)] = dict(ref)

    # Ensure last candle timestamp is in the past so _vol_idx = -1
    candles[-1]["timestamp"] = t_now - 1800
    return candles


# ── AC1 + AC3: feed_status key present and 'OK' for normal candles ────────────

class TestFeedStatusOK:
    def test_feed_status_key_present(self):
        candles = _make_candles(60)
        result = compute_indicators(candles, _base_config())
        assert result is not None
        assert "feed_status" in result

    def test_normal_candles_are_ok(self):
        candles = _make_candles(60)
        result = compute_indicators(candles, _base_config())
        assert result is not None
        assert result["feed_status"] == "OK"


# ── AC2: FROZEN detection ─────────────────────────────────────────────────────

class TestFeedStatusFrozen:
    def test_three_identical_candles_returns_frozen(self):
        """Last 3 candles all identical → feed_status == 'FROZEN'."""
        candles = _make_candles(60, freeze_last=3)
        result = compute_indicators(candles, _base_config())
        assert result is not None
        assert result["feed_status"] == "FROZEN"

    def test_two_identical_is_not_frozen(self):
        """Only 2 last candles identical (and 3rd differs) → feed_status == 'OK'."""
        candles = _make_candles(60, freeze_last=2)
        result = compute_indicators(candles, _base_config())
        assert result is not None
        # Two identical candles have zero variance for those two rows,
        # but the third differs — the overall 3-candle var is > 0
        assert result["feed_status"] == "OK"

    def test_feed_heartbeat_disabled_skips_check(self):
        """When feed_heartbeat.enabled=false, feed_status is always 'OK'."""
        cfg = _base_config()
        cfg["qsa"]["feed_heartbeat"]["enabled"] = False
        candles = _make_candles(60, freeze_last=3)
        result = compute_indicators(candles, cfg)
        assert result is not None
        assert result["feed_status"] == "OK"


# ── AC3 (signals): FROZEN forces HOLD ─────────────────────────────────────────

class TestFrozenSignalForced:
    def _minimal_indicators(self, feed_status: str = "FROZEN") -> dict:
        """Minimal indicators dict with a strong BUY setup, but frozen feed."""
        return {
            "rsi_14": 28.0,           # oversold → would normally fire BUY
            "macd_histogram": 0.5,
            "macd_histogram_prev": -0.1,  # crossover
            "macd_line": 0.2,
            "macd_signal_line": 0.1,
            "ema_9": 100.1,
            "ema_21": 99.9,
            "ema_50": 99.0,
            "bb_upper": 105.0,
            "bb_lower": 95.0,
            "bb_mid": 100.0,
            "atr_14": 5.0,
            "adx_14": 35.0,
            "volume": 2000.0,
            "volume_sma_20": 1000.0,
            "close": 97.0,
            "rsi_series": [],
            "close_series": [],
            "obv_series": [],
            "bb_width_series": [],
            "candlestick_patterns": {},
            "feed_status": feed_status,
        }

    def test_frozen_feed_forces_hold(self):
        ind = self._minimal_indicators("FROZEN")
        result = generate_signal("BTC/USD", ind, _base_config())
        assert result["signal"] == "HOLD"
        assert "feed_frozen" in result["reasons"]

    def test_frozen_feed_hold_strength_zero(self):
        ind = self._minimal_indicators("FROZEN")
        result = generate_signal("BTC/USD", ind, _base_config())
        assert result["strength"] == 0.0

    def test_ok_feed_allows_normal_signal(self):
        """With feed_status=OK and a strong BUY setup, signal should not be forced HOLD."""
        ind = self._minimal_indicators("OK")
        result = generate_signal("BTC/USD", ind, _base_config())
        # With RSI 28 + MACD crossover the signal should be BUY (not HOLD due to freeze)
        assert result["signal"] != "HOLD" or "feed_frozen" not in result["reasons"]
