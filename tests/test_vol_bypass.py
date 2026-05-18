"""
Tests for S13.3.1 — Volume bypass on confirmed momentum geometry.

Story: S13.3.1 | Sprint: S3 | Epic: E13 — QSA Data Resilience

Covers:
  AC1: Vol bypass fires when medium persona + price > BB upper + MACD crossover
  AC2: Vol bypass does NOT fire for conservative persona (volume_bypass_enabled=False)
  AC3: Vol bypass does NOT fire when price ≤ BB upper
  AC4: Vol bypass does NOT fire when MACD crossover condition is absent
  AC5: 'vol_bypass_momentum_geometry' appears in signal reasons when bypass fires
"""

from src.analysis.signals import generate_signal


# ── Helpers ───────────────────────────────────────────────────────────────────

def _base_config(buy_min_score: int = 5) -> dict:
    return {
        "trading": {
            "candle_interval": 15,
            "pairs": [],
        },
        "indicators": {
            "min_candles_to_start": 30,
            "rsi_oversold": 30,
            "rsi_overbought": 65,
        },
        "signals": {
            "buy_min_score": buy_min_score,
            "sell_min_score": 3,
            "max_score": 28,
            "profit_factor_escalation": {"enabled": False},
        },
        "dynamic_tp": {
            "atr_tp_min_pct": 0.3,
            "atr_multiplier": 2.0,
        },
        "risk": {
            "min_profit_floor_pct": 1.0,
        },
    }


def _blocked_indicators(
    volume_bypass_enabled: bool = True,
    price: float = 106.0,   # intentionally above bb_upper=105
    macd_hist: float = 0.01,       # just flipped positive
    macd_hist_prev: float = -0.01,  # was negative → crossover
) -> dict:
    """
    Indicators where the volume check would block, but momentum geometry
    conditions are set according to parameters.
    """
    return {
        "rsi_14": 45.0,
        "macd_histogram": macd_hist,
        "macd_histogram_prev": macd_hist_prev,
        "macd_line": 0.01,
        "macd_signal_line": 0.005,
        "ema_9": 105.0,
        "ema_21": 104.0,
        "ema_50": 103.0,
        "bb_upper": 105.0,
        "bb_lower": 95.0,
        "bb_mid": 100.0,
        "atr_14": 2.0,
        "adx_14": 30.0,
        "close": price,            # signals.py reads price from indicators["close"]
        "volume": 10.0,            # very low → triggers vol blocker
        "volume_sma_20": 100.0,    # average 100 — ratio 0.1 << min_volume_ratio
        "rolling_volume_p15": None,
        "winsorized_vol_ema": None,
        "bb_width_pct": 5.0,
        "obv_series": [],
        "rsi_series": [],
        "close_series": [],
        "bb_width_series": [],
        "feed_status": "OK",
        "volume_bypass_enabled": volume_bypass_enabled,
        # candle arrays omitted — signals.py guards None
    }


# ── Test class ────────────────────────────────────────────────────────────────

class TestVolumeBypass:

    def test_bypass_fires_for_medium_persona(self):
        """
        AC1: medium persona (volume_bypass_enabled=True) + price > bb_upper +
        MACD crossover → vol_blocked overridden, signal proceeds past volume gate.
        """
        cfg = _base_config()
        inds = _blocked_indicators(volume_bypass_enabled=True)
        sig = generate_signal("ETH/USD", inds, cfg)
        # Signal must NOT be blocked by vol gate (would return HOLD with vol reason)
        # If bypass fires, signal proceeds to scoring (may still HOLD on score)
        assert "BLOCKED: Volume" not in " ".join(sig.get("reasons", []))

    def test_bypass_reason_appended(self):
        """
        AC5: 'vol_bypass_momentum_geometry' appears in reasons when bypass fires.
        """
        cfg = _base_config()
        inds = _blocked_indicators(volume_bypass_enabled=True)
        sig = generate_signal("ETH/USD", inds, cfg)
        assert "vol_bypass_momentum_geometry" in sig.get("reasons", [])

    def test_bypass_blocked_for_conservative_persona(self):
        """
        AC2: volume_bypass_enabled=False → vol blocker is NOT suspended;
        signal is HOLD with volume reason.
        """
        cfg = _base_config()
        inds = _blocked_indicators(volume_bypass_enabled=False)
        sig = generate_signal("ETH/USD", inds, cfg)
        assert sig["signal"] == "HOLD"
        reasons_str = " ".join(sig.get("reasons", []))
        assert "BLOCKED: Volume" in reasons_str

    def test_bypass_blocked_when_price_not_above_bb_upper(self):
        """
        AC3: price ≤ BB upper → bypass does NOT fire even if persona allows it.
        """
        cfg = _base_config()
        # Set price equal to bb_upper (not above)
        inds = _blocked_indicators(volume_bypass_enabled=True, price=105.0)
        sig = generate_signal("ETH/USD", inds, cfg)
        assert sig["signal"] == "HOLD"
        assert "vol_bypass_momentum_geometry" not in sig.get("reasons", [])

    def test_bypass_blocked_when_no_macd_crossover(self):
        """
        AC4: MACD histogram was already positive in previous candle → no crossover;
        bypass does NOT fire.
        """
        cfg = _base_config()
        # macd_hist_prev >= 0 → not a fresh crossover
        inds = _blocked_indicators(
            volume_bypass_enabled=True,
            price=106.0,
            macd_hist=0.05,
            macd_hist_prev=0.02,  # was already positive, no crossover
        )
        sig = generate_signal("ETH/USD", inds, cfg)
        assert sig["signal"] == "HOLD"
        assert "vol_bypass_momentum_geometry" not in sig.get("reasons", [])

    def test_bypass_blocked_when_macd_now_negative(self):
        """
        AC4 variant: current MACD histogram is negative → bypass condition
        (macd_hist >= 0) fails — bypass does NOT override the vol block.
        """
        cfg = _base_config()
        inds = _blocked_indicators(
            volume_bypass_enabled=True,
            price=106.0,
            macd_hist=-0.01,    # negative now → condition fails
            macd_hist_prev=-0.05,
        )
        sig = generate_signal("ETH/USD", inds, cfg)
        # Bypass didn't fire — signal should NOT be a bypass-driven BUY
        assert sig["signal"] != "BUY"
        assert "vol_bypass_momentum_geometry" not in sig.get("reasons", [])
