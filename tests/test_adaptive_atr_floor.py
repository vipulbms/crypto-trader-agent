"""
Tests for Fix #108: Adaptive ATR floor injection.

The adaptive ATR floor is computed in main.py's run_cycle() and injected
into indicators["adaptive_atr_floor_pct"] before generate_signal() runs.
It takes priority over per-pair static atr_tp_min_pct in signals.py
Hard Blocker 2.

Logic under test (extracted from main.py):
  lookback = pair_entry.get("adaptive_atr_floor_lookback", global_lookback)
  atr_pct_vals = [(c["high"] - c["low"]) / c["close"] * 100 for c in recent_candles]
  p25_atr = sorted(atr_pct_vals)[int(len * 0.25) - 1]
  floor   = max(p25_atr * scaling_factor, min_cap)

All timestamps represent candle time (never system time).
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import unittest


def _compute_adaptive_atr_floor(candles, lookback, scaling_factor, min_cap):
    """
    Mirror of the main.py injection logic — extracted for unit testing.
    Returns the adaptive floor value or None if candles are insufficient.
    """
    recent = candles[-lookback:] if len(candles) >= lookback else candles
    atr_pct_vals = [
        (c["high"] - c["low"]) / c["close"] * 100
        for c in recent
        if c.get("close", 0) > 0
    ]
    if not atr_pct_vals:
        return None
    atr_pct_vals_sorted = sorted(atr_pct_vals)
    p25_idx = max(0, int(len(atr_pct_vals_sorted) * 0.25) - 1)
    p25_atr = atr_pct_vals_sorted[p25_idx]
    return round(max(p25_atr * scaling_factor, min_cap), 4)


def _make_candles(n, high=101.0, low=99.0, close=100.0):
    """Generate synthetic candles with a fixed range."""
    return [
        {"open": close, "high": high, "low": low, "close": close, "volume": 100.0,
         "timestamp": 1700000000 + i * 900}
        for i in range(n)
    ]


class TestAdaptiveAtrFloorComputation(unittest.TestCase):

    def test_uniform_range_floor_computed_correctly(self):
        """
        Given 400 candles where high=101, low=99, close=100 (range=2%)
        When adaptive ATR floor is computed with scaling_factor=0.8, min_cap=0.10
        Then p25 ATR% = 2.0%, floor = 2.0% × 0.8 = 1.6%
        """
        candles = _make_candles(400, high=101.0, low=99.0, close=100.0)
        floor = _compute_adaptive_atr_floor(candles, lookback=400, scaling_factor=0.8, min_cap=0.10)
        self.assertAlmostEqual(floor, 1.6, places=3)

    def test_min_cap_applied_when_p25_is_very_low(self):
        """
        Given candles with very low range (high=100.05, low=99.95, close=100 → 0.1%)
        When scaling_factor=0.8, min_cap=0.10
        Then floor is clamped to min_cap=0.10 (p25=0.1% × 0.8 = 0.08% < 0.10%)
        """
        candles = _make_candles(400, high=100.05, low=99.95, close=100.0)
        floor = _compute_adaptive_atr_floor(candles, lookback=400, scaling_factor=0.8, min_cap=0.10)
        self.assertAlmostEqual(floor, 0.10, places=3)

    def test_lookback_limits_window_correctly(self):
        """
        Given 500 candles — first 100 with 0.1% range, last 400 with 2.0% range
        When lookback=400 (takes last 400 candles only)
        Then floor is based on 2.0% range, not contaminated by first 100 candles
        """
        low_vol = _make_candles(100, high=100.05, low=99.95, close=100.0)
        high_vol = _make_candles(400, high=101.0, low=99.0, close=100.0)
        # Reassign timestamps to be sequential
        all_candles = low_vol + [
            {**c, "timestamp": 1700000000 + (100 + i) * 900}
            for i, c in enumerate(high_vol)
        ]
        floor = _compute_adaptive_atr_floor(all_candles, lookback=400, scaling_factor=0.8, min_cap=0.10)
        self.assertAlmostEqual(floor, 1.6, places=3)

    def test_per_pair_lookback_overrides_global(self):
        """
        Given 500 candles — first 300 with 1.0% range, last 200 with 3.0% range
        When pair has adaptive_atr_floor_lookback=200 and global is 400
        Then floor is based on 3.0% range (last 200 candles only)
        """
        low_vol = _make_candles(300, high=100.5, low=99.5, close=100.0)
        high_vol = _make_candles(200, high=101.5, low=98.5, close=100.0)
        all_candles = low_vol + [
            {**c, "timestamp": 1700000000 + (300 + i) * 900}
            for i, c in enumerate(high_vol)
        ]
        # Per-pair lookback = 200 → only high-vol candles
        floor_200 = _compute_adaptive_atr_floor(all_candles, lookback=200, scaling_factor=0.8, min_cap=0.10)
        # Global lookback = 400 → mixed (includes low-vol candles)
        floor_400 = _compute_adaptive_atr_floor(all_candles, lookback=400, scaling_factor=0.8, min_cap=0.10)
        # Per-pair floor should be higher (3.0% range only)
        self.assertGreater(floor_200, floor_400)

    def test_fewer_candles_than_lookback_uses_all_available(self):
        """
        Given only 100 candles when lookback=400
        When adaptive floor is computed
        Then it uses all 100 candles (does not raise an error)
        """
        candles = _make_candles(100, high=102.0, low=98.0, close=100.0)
        floor = _compute_adaptive_atr_floor(candles, lookback=400, scaling_factor=0.8, min_cap=0.10)
        self.assertIsNotNone(floor)
        # (high-low)/close * 100 = 4.0%; p25=4.0%, scaled=3.2%
        self.assertAlmostEqual(floor, 3.2, places=3)


class TestAdaptiveAtrFloorSignalIntegration(unittest.TestCase):
    """
    Test that signals.py Hard Blocker 2 uses injected adaptive_atr_floor_pct
    over static per-pair atr_tp_min_pct.
    """

    def _make_config(self, pair="BTC/USD", atr_tp_min_pct=0.50):
        return {
            "trading": {
                "pairs": [{
                    "pair": pair,
                    "take_profit_pct": 8,
                    "stop_loss_pct": 5,
                    "atr_tp_min_pct": atr_tp_min_pct,
                    "rsi_oversold": 30,
                    "rsi_overbought": 75,
                    "bb_squeeze_threshold_pct": 1.0,
                    "min_volume_ratio": 0.50,
                }],
                "min_profit_floor_pct": 1.0,
                "allowed_trading_hours": {"enabled": False},
            },
            "dynamic_tp": {"atr_tp_min_pct": 0.30, "enabled": True},
            "signals": {
                "buy_min_score": 5,
                "rsi_weight": 2, "macd_weight": 2, "ema_weight": 1,
                "bb_weight": 1, "volume_weight": 1,
                "fear_greed_weight": 1, "macd_turn_weight": 3,
                "rsi_oversold": 30, "rsi_overbought": 60,
            },
            "indicators": {},
        }

    def test_injected_adaptive_floor_blocks_low_atr_entry(self):
        """
        Given adaptive_atr_floor_pct=1.0% is injected into indicators
        And the computed ATR-TP for this pair is only 0.3% (below injected floor)
        When generate_signal() is called
        Then the signal is HOLD (blocked by Hard Blocker 2)
        """
        from src.analysis.signals import generate_signal
        config = self._make_config(atr_tp_min_pct=0.10)  # static is permissive
        indicators = {
            "rsi_14": 25.0,          # oversold — would score +2
            "macd_histogram": 0.01,
            "macd_histogram_prev": -0.01,  # turn — would score +3
            "ema_9": 101.0,
            "ema_21": 100.0,         # ema9 > ema21 — bullish
            "bb_upper": 105.0,
            "bb_mid": 100.0,
            "bb_lower": 95.0,
            "close": 96.0,           # near lower band
            "atr_14": 0.3,           # 0.3/100 * 100 = 0.3% ATR — below adaptive floor
            "volume": 1000.0,
            "volume_sma_20": 800.0,
            "macd_line": 0.1,
            "macd_signal_line": 0.05,
            # Injected adaptive floor = 1.0% — overrides static 0.10%
            "adaptive_atr_floor_pct": 1.0,
        }
        sig = generate_signal("BTC/USD", indicators, config)
        self.assertEqual(sig["signal"], "HOLD", "Should be blocked by adaptive ATR floor")

    def test_injected_adaptive_floor_allows_high_atr_entry(self):
        """
        Given adaptive_atr_floor_pct=0.20% is injected (very permissive)
        And the computed ATR-TP is 0.30% (above injected floor)
        When generate_signal() runs with strong buy indicators
        Then the signal may pass Hard Blocker 2 (floor not blocking)
        """
        from src.analysis.signals import generate_signal
        config = self._make_config(atr_tp_min_pct=0.50)  # static would block
        indicators = {
            "rsi_14": 25.0,
            "macd_histogram": 0.01,
            "macd_histogram_prev": -0.01,
            "ema_9": 101.0,
            "ema_21": 100.0,
            "bb_upper": 105.0,
            "bb_mid": 100.0,
            "bb_lower": 95.0,
            "close": 96.0,
            "atr_14": 0.3,
            "volume": 1000.0,
            "volume_sma_20": 800.0,
            "macd_line": 0.1,
            "macd_signal_line": 0.05,
            # Injected adaptive floor = 0.20% — permissive
            "adaptive_atr_floor_pct": 0.20,
        }
        sig = generate_signal("BTC/USD", indicators, config)
        # Hard Blocker 2 uses injected 0.20%, not static 0.50%
        # ATR-TP = 0.3% > 0.20% — blocker should NOT fire
        # (Other blockers may still block, but the ATR floor is not the reason)
        atr_blocker_reason = any(
            "ATR" in r and "floor" in r.lower()
            for r in sig.get("reasons", [])
        )
        self.assertFalse(atr_blocker_reason,
                         f"ATR floor should not block; reasons: {sig['reasons']}")


if __name__ == "__main__":
    unittest.main()
