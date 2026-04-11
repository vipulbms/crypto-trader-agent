"""
tests/test_drawdown_recovery.py

Unit tests for drawdown recovery mode (#182).

Scenarios:
  1. daily_pnl = -3.5%, non-major pair BUY → REJECTED
  2. daily_pnl = -3.5%, BTC/USD BUY → APPROVED at recovery-capped size
  3. daily_pnl = -1.0%, recovery mode is NOT active (is_in_drawdown_recovery = False)
  4. daily_pnl = -2.9%, recovery mode NOT triggered (below trigger threshold)
"""

import pytest
from src.risk.risk_manager import RiskManager


def _make_config(enabled: bool = True, trigger: float = 3.0, exit_pct: float = 1.5) -> dict:
    return {
        "trading": {
            "stop_loss_pct": 5,
            "take_profit_pct": 10,
            "min_profit_floor_pct": 1.0,
            "max_position_pct": 20,
            "max_open_positions": 10,
            "allowed_trading_hours": {"enabled": False},
            "pairs": [],
        },
        "risk": {
            "daily_loss_limit_pct": 10,
            "min_cash_reserve_pct": 5,
            "min_order_usd": 20.0,
            "max_token_volume_per_trade": 500_000,
            "flash_crash_tolerance_pct": 15.0,
            "drawdown_recovery": {
                "enabled": enabled,
                "trigger_pct": trigger,
                "exit_pct": exit_pct,
                "allowed_pairs": ["BTC/USD", "ETH/USD", "BNB/USD"],
                "max_position_pct_override": 10,
            },
            "circuit_breaker": {"enabled": False},
        },
    }


def _approve(config: dict, pair: str, proposed: float, pnl_usd: float):
    """Helper: call validate_buy and return (approved, reason, capped)."""
    rm = RiskManager(config)
    return rm.validate_buy(
        pair=pair,
        proposed_usd=proposed,
        portfolio_balance_usd=1000.0,
        available_cash_usd=900.0,
        open_positions_count=0,
        daily_loss_usd=pnl_usd,
        starting_balance_usd=1000.0,
    )


# ─────────────────────────────────────────────────────────────────────────────


def test_non_major_pair_rejected_in_recovery():
    """Given daily_pnl = -3.5%, When WIF/USD BUY proposed, Then REJECTED."""
    config = _make_config()
    approved, reason, _ = _approve(config, "WIF/USD", 50.0, pnl_usd=-35.0)  # -3.5%
    assert not approved
    assert "recovery mode" in reason.lower()
    assert "WIF/USD" not in reason or "BTC/USD" in reason


def test_major_pair_approved_at_half_size():
    """Given daily_pnl = -3.5%, When BTC/USD BUY proposed at $200, Then APPROVED capped at 10%."""
    config = _make_config()
    approved, reason, capped = _approve(config, "BTC/USD", 200.0, pnl_usd=-35.0)  # -3.5%
    assert approved, f"Expected approval, got: {reason}"
    # Recovery cap = available_cash_usd * 10% = 900 * 0.10 = $90
    assert capped <= 90.0 + 0.01, f"Expected cap ≤ $90, got ${capped}"


def test_recovery_mode_not_active_at_minus_one_pct():
    """Given daily_pnl = -1.0%, Then is_in_drawdown_recovery = False."""
    rm = RiskManager(_make_config())
    assert not rm.is_in_drawdown_recovery(-1.0)


def test_recovery_not_triggered_below_threshold():
    """Given daily_pnl = -2.9%, Then recovery mode NOT triggered — non-major pair APPROVED."""
    config = _make_config()
    approved, reason, _ = _approve(config, "WIF/USD", 50.0, pnl_usd=-29.0)  # -2.9%
    assert approved, f"Expected approval at -2.9%, got: {reason}"


def test_recovery_disabled_ignores_threshold():
    """When drawdown_recovery.enabled = false, no restriction even at -5%."""
    config = _make_config(enabled=False)
    approved, reason, _ = _approve(config, "WIF/USD", 50.0, pnl_usd=-50.0)  # -5%
    assert approved, f"Expected approval when recovery disabled, got: {reason}"


def test_is_in_drawdown_recovery_at_boundary():
    """Exactly at -3.0% should trigger recovery."""
    rm = RiskManager(_make_config())
    assert rm.is_in_drawdown_recovery(-3.0)
    assert not rm.is_in_drawdown_recovery(-2.99)


def test_eth_usd_approved_in_recovery():
    """ETH/USD (allowed pair) is approved in recovery mode."""
    config = _make_config()
    approved, reason, capped = _approve(config, "ETH/USD", 200.0, pnl_usd=-35.0)  # -3.5%
    assert approved, f"Expected ETH/USD approved in recovery, got: {reason}"
    # Recovery cap = $90
    assert capped <= 90.01
