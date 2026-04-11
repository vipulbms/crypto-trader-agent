"""
tests/test_profit_factor.py

Unit tests for profit factor auto-escalation (#183).

Scenarios:
  1. 15 closed trades, PF = 0.65 (< 0.7 severe threshold) → buy_min_score raised by 2
  2. 15 closed trades, PF = 0.85 (< 1.0 warn threshold)  → buy_min_score raised by 1
  3. 15 closed trades, PF = 1.5  (≥ 1.0 — healthy)       → no change
  4. 8 closed trades  (< min_trades=10)                   → no escalation (PF not injected)
"""

import pytest
from src.analysis.features import compute_profit_factor
from src.analysis.signals import generate_signal


# ──────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────

def _base_config(pf_enabled: bool = True) -> dict:
    return {
        "trading": {
            "stop_loss_pct": 5,
            "take_profit_pct": 10,
            "min_profit_floor_pct": 1.0,
            "pairs": [],
        },
        "dynamic_tp": {"enabled": False},
        "signals": {
            "buy_min_score": 5,
            "sell_min_score": 3,
            "max_score": 28,
            "profit_factor_escalation": {
                "enabled": pf_enabled,
                "lookback_days": 30,
                "min_trades": 10,
                "pf_warn_threshold": 1.0,
                "pf_severe_threshold": 0.7,
            },
        },
        "indicators": {
            "rsi_period": 14,
            "ema_short": 9,
            "ema_long": 21,
            "atr_period": 14,
            "obv_trend_period": 10,
            "obv_noise_threshold": 0.001,
            "adx_period": 14,
        },
    }


def _base_indicators(profit_factor=None) -> dict:
    """Minimal indicators for a neutral (HOLD) signal with optional PF injection."""
    ind = {
        "rsi_14": 50.0,
        "macd_line": 0.0,
        "macd_signal_line": 0.0,
        "macd_histogram": 0.0,
        "macd_histogram_prev": 0.0,
        "ema_9": 100.0,
        "ema_21": 100.0,
        "upper_band": 110.0,
        "lower_band": 90.0,
        "bb_mid": 100.0,
        "bb_width_pct": 5.0,
        "atr_14": 2.0,
        "close": 100.0,
        "volume": 1_000_000,
        "rolling_volume_p15": 500_000,
        "adx_14": 25.0,
        "rsi_series": [50.0] * 30,
        "close_series": [100.0] * 30,
        "obv_series": [1_000_000] * 30,
        "bb_width_series": [5.0] * 10,
        "open_series": [99.0] * 30,
        "high_series": [101.0] * 30,
        "low_series": [99.0] * 30,
        "fear_greed_index": 50,
    }
    if profit_factor is not None:
        ind["profit_factor"] = profit_factor
    return ind


def _get_escalation_reasons(reasons: list) -> list:
    return [r for r in reasons if "Profit factor" in r]


# ──────────────────────────────────────────────────────────────
# compute_profit_factor unit tests
# ──────────────────────────────────────────────────────────────

def _make_trades(pf_target: float, n: int = 15) -> list:
    """
    Construct a trade list of `n` trades whose gross-win / gross-loss ratio ≈ pf_target.
    Strategy: half wins of size win_usd, half losses of $1 each.
    win_usd = pf_target * (n//2) / (n//2) = pf_target
    """
    half = n // 2
    trades = [{"pnl_usd": pf_target} for _ in range(half)]
    trades += [{"pnl_usd": -1.0} for _ in range(n - half)]
    return trades


class TestComputeProfitFactor:
    def test_severe_threshold(self):
        # 7 wins of $0.65, 8 losses of $1 → PF = 0.65*7 / 8 ≈ 0.57 (< 0.7)
        trades = [{"pnl_usd": 0.65}] * 7 + [{"pnl_usd": -1.0}] * 8
        pf = compute_profit_factor("TEST/USD", trades)
        assert pf is not None
        assert pf < 0.7, f"Expected PF < 0.7, got {pf}"

    def test_warn_threshold(self):
        # 7 wins of $0.85, 8 losses of $1 → PF ≈ 0.74
        trades = [{"pnl_usd": 0.85}] * 7 + [{"pnl_usd": -1.0}] * 8
        pf = compute_profit_factor("TEST/USD", trades)
        assert pf is not None
        assert 0.7 <= pf < 1.0, f"Expected 0.7 ≤ PF < 1.0, got {pf}"

    def test_healthy(self):
        trades = [{"pnl_usd": 3.0}] * 10 + [{"pnl_usd": -1.0}] * 5
        pf = compute_profit_factor("TEST/USD", trades)
        assert pf is not None and pf >= 1.0

    def test_insufficient_trades_returns_none(self):
        trades = [{"pnl_usd": 1.0}] * 8
        assert compute_profit_factor("TEST/USD", trades) is None

    def test_no_losses_returns_inf(self):
        trades = [{"pnl_usd": 2.0}] * 12
        pf = compute_profit_factor("TEST/USD", trades)
        assert pf == float("inf")


# ──────────────────────────────────────────────────────────────
# generate_signal escalation integration tests
# ──────────────────────────────────────────────────────────────

class TestProfitFactorEscalation:
    def test_severe_pf_raises_min_score_by_2(self):
        """PF=0.65 (< 0.7) → buy_min_score raised by 2, reason appended."""
        cfg = _base_config()
        ind = _base_indicators(profit_factor=0.65)
        result = generate_signal("BTC/USD", ind, cfg)
        esc = _get_escalation_reasons(result["reasons"])
        assert len(esc) == 1
        assert "severe underperformance" in esc[0]
        assert "+2" in esc[0] or "raised +2" in esc[0]

    def test_warn_pf_raises_min_score_by_1(self):
        """PF=0.85 (< 1.0 but ≥ 0.7) → buy_min_score raised by 1, reason appended."""
        cfg = _base_config()
        ind = _base_indicators(profit_factor=0.85)
        result = generate_signal("BTC/USD", ind, cfg)
        esc = _get_escalation_reasons(result["reasons"])
        assert len(esc) == 1
        assert "underperforming" in esc[0]
        assert "+1" in esc[0] or "raised +1" in esc[0]

    def test_healthy_pf_no_escalation(self):
        """PF=1.5 → no escalation reason appended."""
        cfg = _base_config()
        ind = _base_indicators(profit_factor=1.5)
        result = generate_signal("BTC/USD", ind, cfg)
        esc = _get_escalation_reasons(result["reasons"])
        assert len(esc) == 0

    def test_no_pf_injected_no_escalation(self):
        """When profit_factor key absent (< min_trades), no escalation runs."""
        cfg = _base_config()
        ind = _base_indicators()  # no profit_factor key
        result = generate_signal("BTC/USD", ind, cfg)
        esc = _get_escalation_reasons(result["reasons"])
        assert len(esc) == 0

    def test_disabled_config_no_escalation(self):
        """When profit_factor_escalation.enabled=False, PF < 0.7 does NOT escalate."""
        cfg = _base_config(pf_enabled=False)
        ind = _base_indicators(profit_factor=0.50)
        result = generate_signal("BTC/USD", ind, cfg)
        esc = _get_escalation_reasons(result["reasons"])
        assert len(esc) == 0
