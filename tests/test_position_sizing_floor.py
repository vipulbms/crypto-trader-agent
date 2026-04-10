"""
Tests for position sizing floor guard and config sanity warning (issue #159).

Ensures:
  1. compute_position_size() never returns below min_order_usd, even when the
     ATR-math produces a tiny value (e.g. high-price / low-ATR assets).
  2. validate_config() emits a WARNING when max_open_positions × base_position_pct
     exceeds the deployable capital band.
"""

import logging

import pytest

from src.analysis.features import compute_position_size
from src.risk.risk_manager import validate_config


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _base_config(
    min_order_usd: float = 20.0,
    risk_per_trade_pct: float = 1.5,
) -> dict:
    return {
        "risk": {
            "min_order_usd": min_order_usd,
            "risk_per_trade_pct": risk_per_trade_pct,
        }
    }


def _full_config(
    max_open_positions: int = 5,
    base_position_pct: int = 16,
    min_cash_reserve_pct: float = 5.0,
) -> dict:
    return {
        "trading": {
            "max_open_positions": max_open_positions,
            "take_profit_pct": 12,
        },
        "position_sizing": {
            "base_position_pct": base_position_pct,
        },
        "risk": {
            "min_cash_reserve_pct": min_cash_reserve_pct,
            "min_order_usd": 20.0,
        },
    }


# ---------------------------------------------------------------------------
# compute_position_size — floor tests
# ---------------------------------------------------------------------------

class TestComputePositionSizeFloor:
    """compute_position_size must never return below min_order_usd."""

    def test_tiny_atr_gives_floor(self):
        """
        BTC at $90,000 with ATR $50 → risk_amount=$15. sl_dist=~$75.
        coins_to_buy = 15/75 = 0.2; usd_size = 0.2 × 90000 = $18 000.
        Wait — actually with a high-price asset the usd_size is large.
        Let's construct a case where it's genuinely tiny:
        tiny portfolio ($100), normal ATR ratio → should still floor at $20.
        """
        config = _base_config(min_order_usd=20.0)
        # portfolio = $100, ATR = $5, price = $100
        # risk_amount = 100 × 0.015 = $1.50
        # sl_dist = max(1×5, capped 5) = $5
        # coins = 1.50/5 = 0.3; usd_size = 0.3 × 100 = $30 → above floor, fine
        # Reduce risk_per_trade_pct to force a tiny result
        config["risk"]["risk_per_trade_pct"] = 0.01  # 0.01% → risk_amount = $0.01
        result = compute_position_size(
            signal_strength=5.0,
            atr=5.0,
            price=100.0,
            portfolio_total_usd=100.0,
            config=config,
        )
        assert result >= 20.0, f"Expected ≥ $20, got ${result}"

    def test_floor_not_applied_when_size_is_already_above(self):
        """Normal sizing well above $20 must not be clamped up to $20 (it's already fine)."""
        config = _base_config(min_order_usd=20.0)
        result = compute_position_size(
            signal_strength=5.0,
            atr=50.0,
            price=50_000.0,
            portfolio_total_usd=1_000.0,
            config=config,
        )
        assert result >= 20.0
        # Should be in a reasonable range (not exactly $20 — the ATR math wins here)
        assert result > 20.0

    def test_floor_respects_custom_min_order_usd(self):
        """Floor uses min_order_usd from config, not a hardcoded $20."""
        config = _base_config(min_order_usd=50.0)
        config["risk"]["risk_per_trade_pct"] = 0.001  # force trivially small result
        result = compute_position_size(
            signal_strength=5.0,
            atr=5.0,
            price=100.0,
            portfolio_total_usd=100.0,
            config=config,
        )
        assert result >= 50.0, f"Expected ≥ $50, got ${result}"

    def test_floor_default_when_min_order_usd_missing(self):
        """When min_order_usd is absent from config, default floor of $20 applies."""
        config = {"risk": {"risk_per_trade_pct": 0.001}}  # no min_order_usd key
        result = compute_position_size(
            signal_strength=5.0,
            atr=5.0,
            price=100.0,
            portfolio_total_usd=100.0,
            config=config,
        )
        assert result >= 20.0


# ---------------------------------------------------------------------------
# validate_config — sanity warning tests
# ---------------------------------------------------------------------------

class TestValidateConfigSanityWarning:
    """validate_config must warn when max_open_positions × base_position_pct > deployable."""

    def test_warns_when_overshoot(self, caplog):
        """13 × 16% = 208% > 95% deployable → warning logged."""
        config = _full_config(
            max_open_positions=13,
            base_position_pct=16,
            min_cash_reserve_pct=5.0,
        )
        with caplog.at_level(logging.WARNING, logger="src.risk.risk_manager"):
            validate_config(config)
        assert any("[CONFIG]" in m for m in caplog.messages), (
            "Expected a [CONFIG] warning about position sizing overshoot"
        )

    def test_no_warning_when_valid(self, caplog):
        """5 × 16% = 80% ≤ 95% deployable → no warning."""
        config = _full_config(
            max_open_positions=5,
            base_position_pct=16,
            min_cash_reserve_pct=5.0,
        )
        with caplog.at_level(logging.WARNING, logger="src.risk.risk_manager"):
            validate_config(config)
        assert not any("[CONFIG]" in m for m in caplog.messages), (
            "Unexpected [CONFIG] warning for valid config"
        )

    def test_warning_message_contains_suggested_reduction(self, caplog):
        """Warning should tell the operator the correct reduced value."""
        config = _full_config(
            max_open_positions=13,
            base_position_pct=16,
            min_cash_reserve_pct=5.0,
        )
        with caplog.at_level(logging.WARNING, logger="src.risk.risk_manager"):
            validate_config(config)
        warning_msgs = [m for m in caplog.messages if "[CONFIG]" in m]
        assert warning_msgs, "Expected [CONFIG] warning"
        # floor(95/16) = 5
        assert "5" in warning_msgs[0], (
            f"Expected suggested value 5 in warning, got: {warning_msgs[0]}"
        )

    def test_boundary_exactly_at_deployable_no_warning(self, caplog):
        """Exactly at limit: 5 × 19% = 95% ≤ 95% → no warning."""
        config = _full_config(
            max_open_positions=5,
            base_position_pct=19,
            min_cash_reserve_pct=5.0,
        )
        with caplog.at_level(logging.WARNING, logger="src.risk.risk_manager"):
            validate_config(config)
        assert not any("[CONFIG]" in m for m in caplog.messages)
