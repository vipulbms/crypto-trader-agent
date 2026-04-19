"""
Tests for S13.1.1 — Winsorized EMA-14 volume floor.

Story: S13.1.1 + S13.1.2 | Sprint: S2 | Epic: E13 — QSA Data Resilience

Covers:
  AC1: compute_indicators() returns winsorized_vol_ema
  AC2: Spike neutralisation — one outlier does not lift the floor above p75
  AC3: Backward compat — algorithm=sma returns None for winsorized_vol_ema (v2 unchanged)
  AC4: Edge case — fewer than 14 candles still returns a value (EMA gracefully handles)
  AC5: Invalid algorithm raises ValueError (S13.1.2 AC3)
"""
import math
import time

import pytest

from src.analysis.indicators import compute_indicators


# ── Helpers ──────────────────────────────────────────────────────────────────

def _base_config(algorithm: str = "winsorized_ema") -> dict:
    return {
        "trading": {"candle_interval": 15},
        "indicators": {"min_candles_to_start": 30},
        "qsa": {
            "volume_floor": {
                "algorithm": algorithm,
                "period": 14,
                "winsorize_percentile": 95,
                "winsorize_lookback": 100,
            },
            "feed_heartbeat": {"enabled": False},
        },
    }


def _make_candles(n: int, volume: float = 100.0, close: float = 100.0,
                  spike_idx: int = -1, spike_vol: float = 1_000_000.0) -> list:
    """Generate n OHLCV candles with uniform values (and an optional volume spike)."""
    t_now = int(time.time())
    candles = []
    for i in range(n):
        vol = spike_vol if i == spike_idx else volume
        ts = t_now - (n - i) * 900  # 15-min bars
        candles.append({
            "timestamp": ts,
            "open": close, "high": close + 1, "low": close - 1,
            "close": close, "volume": vol,
        })
    # Close the last candle so _vol_idx = -1
    candles[-1]["timestamp"] = t_now - 1800
    return candles


# ── AC1: winsorized_vol_ema is present in return dict ────────────────────────

class TestWinsorizedEmaPresent:
    def test_key_exists_in_output(self):
        candles = _make_candles(60)
        result = compute_indicators(candles, _base_config("winsorized_ema"))
        assert result is not None
        assert "winsorized_vol_ema" in result

    def test_value_is_float_not_none(self):
        candles = _make_candles(60)
        result = compute_indicators(candles, _base_config("winsorized_ema"))
        assert result["winsorized_vol_ema"] is not None
        assert isinstance(result["winsorized_vol_ema"], float)


# ── AC2: Spike neutralisation ─────────────────────────────────────────────────

class TestSpikeNeutralisation:
    def test_spike_does_not_dominate_floor(self):
        """
        One extreme spike should not push winsorized_vol_ema above the p75 of normal volume.
        Normal volumes are all 100.0; spike is 1,000,000.
        Without Winsorizing, EMA would be dominated by the spike.
        After Winsorizing (p95 cap), the floor should stay close to 100.
        """
        n = 60
        spike_idx = n // 2  # spike in the middle of the series
        candles = _make_candles(n, volume=100.0, spike_idx=spike_idx, spike_vol=1_000_000.0)
        result = compute_indicators(candles, _base_config("winsorized_ema"))
        assert result is not None
        # p75 of [100, 100, ..., 100] = 100; floor should stay well below 200
        assert result["winsorized_vol_ema"] < 200.0, (
            f"Winsorized EMA too high ({result['winsorized_vol_ema']:.2f}) — "
            "spike not neutralized"
        )


# ── AC3: Backward compat — algorithm=sma ─────────────────────────────────────

class TestBackwardCompat:
    def test_sma_algo_returns_none_for_winsorized_ema(self):
        """When algorithm=sma, winsorized_vol_ema must be None (v2 unchanged)."""
        candles = _make_candles(60)
        result = compute_indicators(candles, _base_config("sma"))
        assert result is not None
        assert result["winsorized_vol_ema"] is None

    def test_sma_algo_volume_sma_20_still_present(self):
        """When algorithm=sma, volume_sma_20 must still be returned for v2 compatibility."""
        candles = _make_candles(60)
        result = compute_indicators(candles, _base_config("sma"))
        assert result is not None
        assert result["volume_sma_20"] is not None


# ── AC4: Edge case — small candle count still returns a value ─────────────────

class TestSmallCandleCount:
    def test_fewer_than_winsorize_lookback_returns_value(self):
        """
        When len(candles) < winsorize_lookback (100), the code falls back to using
        the full df["volume"] series for the quantile cap.  The result must still be
        a valid float, not None or NaN.  Use 50 candles (below lookback=100 but
        above min_candles_to_start so all indicators can initialise).
        """
        cfg = _base_config("winsorized_ema")
        cfg["qsa"]["volume_floor"]["winsorize_lookback"] = 100  # default
        candles = _make_candles(50)
        result = compute_indicators(candles, cfg)
        assert result is not None
        val = result["winsorized_vol_ema"]
        assert val is not None
        assert not math.isnan(val)


# ── AC5: Invalid algorithm raises ValueError (S13.1.2) ───────────────────────

class TestInvalidAlgorithm:
    def test_invalid_algorithm_raises_value_error(self):
        candles = _make_candles(60)
        cfg = _base_config("invalid_algo")
        with pytest.raises(ValueError, match="Invalid qsa.volume_floor.algorithm"):
            compute_indicators(candles, cfg)
