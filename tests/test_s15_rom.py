"""
Test suite for Sprint S4 — S15.1.1 (prune candidate), S15.1.2 (reallocation cap),
and S15.2.1 (RSI bypass gate in validate_buy).

pytest: python -m pytest tests/test_s15_rom.py -v
"""
from __future__ import annotations

import sys
import uuid
import os
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.risk.risk_manager import RiskManager
from src.storage.database import get_connection


# ──────────────────────────────────────────────────────────────
# Fixtures / helpers
# ──────────────────────────────────────────────────────────────

def _minimal_config() -> dict:
    """Minimal config satisfying RiskManager.__init__."""
    return {
        "trading": {
            "stop_loss_pct":        5.0,
            "take_profit_pct":      8.0,
            "min_profit_floor_pct": 1.0,
            "max_position_pct":     30.0,
            "max_open_positions":   10,
            "allowed_trading_hours": {"enabled": False},
            "pairs": [],
        },
        "risk": {
            "daily_loss_limit_pct": 10.0,
            "min_cash_reserve_pct": 5.0,
            "min_order_usd":        20.0,
            "circuit_breaker":      {"enabled": True, "consecutive_stops": 3, "pause_hours": 1},
            "max_cluster_positions": 2,
            "correlation_clusters":  [],
        },
        "atr_stop_loss": {"enabled": False},
        "personas": {
            "conservative": _conservative_persona(),
            "medium":        _medium_persona(),
            "high":          _high_persona(),
        },
        "agent": {"persona": "medium", "concurrent_mode": False},
    }


def _conservative_persona() -> dict:
    return {
        "llm_system_role":         "conservative",
        "buy_min_score":           5,
        "max_open_positions":      2,
        "max_position_pct":        0.15,
        "min_profit_floor_pct":    1.5,
        "rsi_overbought_veto":     70,
        "momentum_bypass_rsi":     70,
        "momentum_bypass_adx":     999,
        "reallocation_enabled":    False,
        "reallocation_max_pct_6h": 0.0,
        "llm_temperature":         0.1,
        "llm_max_tokens":          1024,
        "velocity_circuit_breaker_pct": 5.0,
        "velocity_halt_hours":     2,
    }


def _medium_persona() -> dict:
    return {
        "llm_system_role":         "medium",
        "buy_min_score":           5,
        "max_open_positions":      5,
        "max_position_pct":        0.25,
        "min_profit_floor_pct":    1.0,
        "rsi_overbought_veto":     70,
        "momentum_bypass_rsi":     75,
        "momentum_bypass_adx":     25,
        "reallocation_enabled":    True,
        "reallocation_max_pct_6h": 0.20,
        "llm_temperature":         0.3,
        "llm_max_tokens":          2048,
        "velocity_circuit_breaker_pct": 5.0,
        "velocity_halt_hours":     2,
    }


def _high_persona() -> dict:
    return {
        "llm_system_role":         "high",
        "buy_min_score":           5,
        "max_open_positions":      10,
        "max_position_pct":        0.30,
        "min_profit_floor_pct":    1.0,
        "rsi_overbought_veto":     70,
        "momentum_bypass_rsi":     80,
        "momentum_bypass_adx":     25,
        "reallocation_enabled":    True,
        "reallocation_max_pct_6h": 0.30,
        "llm_temperature":         0.5,
        "llm_max_tokens":          4096,
        "velocity_circuit_breaker_pct": 5.0,
        "velocity_halt_hours":     2,
    }


def _make_risk_manager(persona_name: str = "medium", db_path: str = None) -> RiskManager:
    config = _minimal_config()
    rm = RiskManager(config, db_path=db_path)
    persona_map = {
        "conservative": _conservative_persona(),
        "medium":        _medium_persona(),
        "high":          _high_persona(),
    }
    rm.apply_persona_config(persona_map[persona_name])
    return rm


def _make_temp_db() -> str:
    """Create an isolated test DB for reallocation cap tests."""
    db_name = f"test_rom_{uuid.uuid4().hex[:8]}.db"
    # RiskManager uses get_connection which resolves bare names to data/<name>
    # Use an absolute tmp path to isolate
    import tempfile
    tmp = tempfile.mkdtemp()
    db_path = os.path.join(tmp, db_name)
    conn = get_connection(db_path)
    conn.execute(
        """CREATE TABLE IF NOT EXISTS paper_trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pair TEXT,
            usd_value REAL,
            exit_reason TEXT,
            closed_at TEXT
        )"""
    )
    conn.commit()
    conn.close()
    return db_path


# ──────────────────────────────────────────────────────────────
# S15.1.1 — get_prune_candidate tests
# ──────────────────────────────────────────────────────────────

class TestGetPruneCandidate:
    """AC1–AC5 for S15.1.1"""

    def test_returns_none_when_reallocation_disabled(self):
        """AC1: conservative persona (reallocation_enabled=False) → always None."""
        rm = _make_risk_manager("conservative")
        positions = [
            {"pair": "SOL/USD", "adx": 18.0, "pnl_pct": 0.5},
        ]
        result = rm.get_prune_candidate(positions)
        assert result is None

    def test_returns_none_when_no_eligible_positions(self):
        """AC2: no position meets all three criteria simultaneously."""
        rm = _make_risk_manager("medium")
        positions = [
            # ADX >= 25 → not eligible
            {"pair": "BTC/USD", "adx": 30.0, "pnl_pct": 0.5},
            # P&L% deep loss (below -(5/2) = -2.5%)
            {"pair": "ETH/USD", "adx": 18.0, "pnl_pct": -3.0},
        ]
        result = rm.get_prune_candidate(positions)
        assert result is None

    def test_returns_weakest_eligible_position(self):
        """AC3: lowest ADX eligible position is returned."""
        rm = _make_risk_manager("medium")
        positions = [
            {"pair": "SOL/USD", "adx": 20.0, "pnl_pct": 0.4},  # eligible, ADX=20
            {"pair": "INJ/USD", "adx": 15.0, "pnl_pct": 0.3},  # eligible, ADX=15 (weakest)
            {"pair": "BTC/USD", "adx": 35.0, "pnl_pct": 0.8},  # ADX too high → not eligible
        ]
        result = rm.get_prune_candidate(positions)
        assert result == "INJ/USD"  # lowest ADX

    def test_pnl_pct_tiebreaker_selects_lowest(self):
        """AC4: when ADX is equal, lowest P&L% wins."""
        rm = _make_risk_manager("medium")
        positions = [
            {"pair": "SOL/USD", "adx": 18.0, "pnl_pct": 1.2},
            {"pair": "INJ/USD", "adx": 18.0, "pnl_pct": 0.2},  # lower P&L
        ]
        result = rm.get_prune_candidate(positions)
        assert result == "INJ/USD"

    def test_returns_none_on_empty_positions(self):
        """AC5: empty positions list → None, no crash."""
        rm = _make_risk_manager("medium")
        result = rm.get_prune_candidate([])
        assert result is None

    def test_high_pnl_position_not_eligible(self):
        """AC6: P&L% >= floor * 1.5 → not eligible for prune."""
        rm = _make_risk_manager("medium")
        # _min_profit_floor_pct = 1.0 for medium; floor_threshold = 1.5
        positions = [
            {"pair": "BTC/USD", "adx": 18.0, "pnl_pct": 2.0},  # 2.0 >= 1.5 → not eligible
        ]
        result = rm.get_prune_candidate(positions)
        assert result is None


# ──────────────────────────────────────────────────────────────
# S15.1.2 — check_reallocation_cap tests
# ──────────────────────────────────────────────────────────────

class TestCheckReallocationCap:
    """AC1–AC4 for S15.1.2"""

    def test_conservative_always_blocked(self):
        """AC1: conservative persona (reallocation_max_pct_6h=0.0) → always blocked."""
        rm = _make_risk_manager("conservative")
        blocked = rm.check_reallocation_cap(prune_usd=50.0, portfolio_value=1000.0)
        assert blocked is True

    def test_medium_within_cap_not_blocked(self):
        """AC2: medium persona, 6h total=0, prune $100 < $200 cap → not blocked."""
        db_path = _make_temp_db()
        rm = _make_risk_manager("medium", db_path=db_path)
        blocked = rm.check_reallocation_cap(prune_usd=100.0, portfolio_value=1000.0)
        assert blocked is False  # 100 < 20% of 1000 = 200

    def test_medium_over_cap_is_blocked(self):
        """AC3: medium persona prune $250 > $200 cap → blocked."""
        db_path = _make_temp_db()
        rm = _make_risk_manager("medium", db_path=db_path)
        blocked = rm.check_reallocation_cap(prune_usd=250.0, portfolio_value=1000.0)
        assert blocked is True  # 250 > 20% of 1000 = 200

    def test_high_within_cap_not_blocked(self):
        """AC4: high persona (30% cap), prune $250 < $300 cap → not blocked."""
        db_path = _make_temp_db()
        rm = _make_risk_manager("high", db_path=db_path)
        blocked = rm.check_reallocation_cap(prune_usd=250.0, portfolio_value=1000.0)
        assert blocked is False  # 250 < 30% of 1000 = 300


# ──────────────────────────────────────────────────────────────
# S15.2.1 — validate_buy RSI veto tests
# ──────────────────────────────────────────────────────────────

class TestValidateBuyRSIVeto:
    """AC1–AC6 for S15.2.1"""

    def _common_kwargs(self, proposed_usd=100.0) -> dict:
        return dict(
            pair="SOL/USD",
            proposed_usd=proposed_usd,
            portfolio_balance_usd=1000.0,
            available_cash_usd=500.0,
            open_positions_count=0,
            daily_loss_usd=0.0,
            starting_balance_usd=1000.0,
        )

    def test_standard_playbook_rsi_below_70_approved(self):
        """AC1: RSI=60 in standard mode → not blocked."""
        rm = _make_risk_manager("medium")
        ok, reason, _ = rm.validate_buy(rsi=60.0, playbook="standard", **self._common_kwargs())
        assert ok or "RSI veto" not in reason

    def test_standard_playbook_rsi_at_70_blocked(self):
        """AC2: RSI=70 in standard mode → blocked."""
        rm = _make_risk_manager("medium")
        ok, reason, _ = rm.validate_buy(rsi=70.0, playbook="standard", **self._common_kwargs())
        assert not ok
        assert "RSI veto" in reason

    def test_standard_playbook_rsi_above_70_blocked(self):
        """AC3: RSI=75 in standard mode → blocked (even for medium persona)."""
        rm = _make_risk_manager("medium")
        ok, reason, _ = rm.validate_buy(rsi=75.0, playbook="standard", **self._common_kwargs())
        assert not ok
        assert "RSI veto" in reason

    def test_momentum_playbook_high_adx_allows_higher_rsi(self):
        """AC4: medium persona, momentum playbook, ADX=30 > 25 → RSI<75 allowed."""
        rm = _make_risk_manager("medium")
        # ADX=30 > momentum_bypass_adx=25, so threshold raised to momentum_bypass_rsi=75
        ok, reason, _ = rm.validate_buy(rsi=73.0, adx=30.0, playbook="momentum",
                                        **self._common_kwargs())
        # RSI=73 < 75 threshold → not blocked by RSI veto
        if not ok:
            assert "RSI veto" not in reason

    def test_momentum_playbook_rsi_above_bypass_still_blocked(self):
        """AC5: medium momentum, ADX=30, RSI=76 >= 75 → still blocked."""
        rm = _make_risk_manager("medium")
        ok, reason, _ = rm.validate_buy(rsi=76.0, adx=30.0, playbook="momentum",
                                        **self._common_kwargs())
        assert not ok
        assert "RSI veto" in reason

    def test_conservative_momentum_bypass_never_fires(self):
        """AC6: conservative persona has momentum_bypass_adx=999 → bypass never reachable."""
        rm = _make_risk_manager("conservative")
        # Even with extremely high ADX, conservative threshold stays at 70
        ok, reason, _ = rm.validate_buy(rsi=72.0, adx=50.0, playbook="momentum",
                                        **self._common_kwargs())
        assert not ok
        assert "RSI veto" in reason

    def test_rsi_none_skips_veto(self):
        """AC7: rsi=None → RSI veto block is skipped, other guards apply normally."""
        rm = _make_risk_manager("medium")
        ok, reason, _ = rm.validate_buy(rsi=None, playbook="standard", **self._common_kwargs())
        # Should not be blocked for RSI reason
        assert "RSI veto" not in reason

    def test_rsi_zero_treated_as_unavailable(self):
        """AC8: rsi=0 treated as unavailable (converted to None via 'or None')."""
        rm = _make_risk_manager("medium")
        ok, reason, _ = rm.validate_buy(rsi=0.0, playbook="standard", **self._common_kwargs())
        assert "RSI veto" not in reason

    def test_veto_reason_includes_playbook_label(self):
        """AC9: rejection reason string includes playbook context."""
        rm = _make_risk_manager("medium")
        ok, reason, _ = rm.validate_buy(rsi=75.0, playbook="standard", **self._common_kwargs())
        assert not ok
        assert "standard" in reason
