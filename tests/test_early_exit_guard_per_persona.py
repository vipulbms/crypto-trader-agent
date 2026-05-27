"""
Test that Early Exit Guard is only applied for conservative persona.

Medium and high personas should allow sales below the 60% TP proximity threshold
to support capital reallocation (S15.2.3).

Verify:
  1. Conservative: Early Exit Guard blocks sale at 50% of TP
  2. Medium: Early Exit Guard SKIPPED, sale allowed at 50% of TP
  3. High: Early Exit Guard SKIPPED, sale allowed at 50% of TP
"""

import uuid
import sys
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.risk.risk_manager import RiskManager
from src.storage.database import init_paper_db


def _make_config(persona_name: str, persona_config: dict) -> dict:
    """Create a config with the given persona."""
    return {
        "trading": {
            "stop_loss_pct": 5,
            "take_profit_pct": 12,
            "min_profit_floor_pct": 1.0,
            "early_sell_min_tp_proximity_pct": 60,
            "max_position_pct": 30,
            "max_open_positions": 10,
            "pairs": [],
        },
        "risk": {
            "daily_loss_limit_pct": 10,
            "min_cash_reserve_pct": 5,
            "circuit_breaker": {"enabled": False},
        },
        "personas": {persona_name: persona_config},
        "agent": {"persona": persona_name},
    }


def _make_position(entry_price: float, current_price: float, tp_pct: float) -> dict:
    """Create a mock position."""
    return {
        "entry_price": entry_price,
        "current_price": current_price,
        "take_profit_pct": tp_pct,
    }


# ─────────────────────────────────────────────────────────────────────────────

class TestEarlyExitGuardPerPersona:
    """Early Exit Guard should only apply to conservative persona."""

    CONSERVATIVE = {
        "buy_min_score": 5,
        "max_open_positions": 10,
        "max_position_pct": 30,
        "min_profit_floor_pct": 1.0,
        "rsi_overbought_veto": 70,
        "momentum_bypass_rsi": 70,
        "momentum_bypass_adx": 999,
        "volume_bypass_enabled": False,
        "reallocation_enabled": False,
        "reallocation_max_pct_6h": 0.0,
        "llm_temperature": 0.0,
        "llm_max_tokens": 1024,
        "llm_system_role": "conservative",
        "velocity_circuit_breaker_pct": 3.0,
        "velocity_halt_hours": 4,
        "pf_escalation_momentum_suspend": False,
        "early_momentum_score_reduction": 0,
        "early_momentum_rsi_min": 50,
        "early_momentum_rsi_max": 65,
        "early_momentum_adx_min": 999,
    }

    MEDIUM = {
        "buy_min_score": 6,
        "max_open_positions": 10,
        "max_position_pct": 30,
        "min_profit_floor_pct": 1.0,
        "rsi_overbought_veto": 72,
        "momentum_bypass_rsi": 60,
        "momentum_bypass_adx": 25,
        "volume_bypass_enabled": True,
        "reallocation_enabled": True,
        "reallocation_max_pct_6h": 0.2,
        "llm_temperature": 0.1,
        "llm_max_tokens": 2048,
        "llm_system_role": "medium",
        "velocity_circuit_breaker_pct": 5.0,
        "velocity_halt_hours": 2,
        "pf_escalation_momentum_suspend": False,
        "early_momentum_score_reduction": 0,
        "early_momentum_rsi_min": 50,
        "early_momentum_rsi_max": 65,
        "early_momentum_adx_min": 20,
    }

    HIGH = {
        "buy_min_score": 5,
        "max_open_positions": 10,
        "max_position_pct": 30,
        "min_profit_floor_pct": 0.5,
        "rsi_overbought_veto": 75,
        "momentum_bypass_rsi": 55,
        "momentum_bypass_adx": 30,
        "volume_bypass_enabled": True,
        "reallocation_enabled": True,
        "reallocation_max_pct_6h": 0.3,
        "llm_temperature": 0.2,
        "llm_max_tokens": 2048,
        "llm_system_role": "high",
        "velocity_circuit_breaker_pct": 7.0,
        "velocity_halt_hours": 1,
        "pf_escalation_momentum_suspend": False,
        "early_momentum_score_reduction": 0,
        "early_momentum_rsi_min": 50,
        "early_momentum_rsi_max": 65,
        "early_momentum_adx_min": 15,
    }

    def test_conservative_blocks_early_exit_at_50_percent_tp(self):
        """
        Conservative persona: TP=12%, current P&L=6% (50% of TP).
        Expected: REJECTED by Early Exit Guard (needs 60% of TP = 7.2%).
        """
        db_path = f"test_paper_{uuid.uuid4().hex[:8]}.db"
        init_paper_db(db_path)

        cfg = _make_config("conservative", self.CONSERVATIVE)
        risk = RiskManager(cfg, db_path=db_path)
        risk.apply_persona_config(self.CONSERVATIVE, persona_name="conservative")

        # Entry: $100, Current: $106 (6% gain = 50% of 12% TP)
        open_positions = [_make_position(entry_price=100, current_price=106, tp_pct=12)]

        is_valid, reason, _ = risk.validate_sell("BTC/USD", open_positions, 106)

        assert not is_valid, "Conservative should BLOCK early exit at 50% of TP"
        assert "Early Exit Guard" in reason, f"Expected 'Early Exit Guard' in reason, got: {reason}"

    def test_medium_allows_early_exit_at_50_percent_tp(self):
        """
        Medium persona: TP=12%, current P&L=6% (50% of TP).
        Expected: ALLOWED (Early Exit Guard disabled for medium).
        """
        db_path = f"test_paper_{uuid.uuid4().hex[:8]}.db"
        init_paper_db(db_path)

        cfg = _make_config("medium", self.MEDIUM)
        risk = RiskManager(cfg, db_path=db_path)
        risk.apply_persona_config(self.MEDIUM, persona_name="medium")

        # Entry: $100, Current: $106 (6% gain = 50% of 12% TP)
        open_positions = [_make_position(entry_price=100, current_price=106, tp_pct=12)]

        is_valid, reason, _ = risk.validate_sell("BTC/USD", open_positions, 106)

        assert is_valid, f"Medium should ALLOW early exit at 50% of TP. Reason: {reason}"

    def test_high_allows_early_exit_at_50_percent_tp(self):
        """
        High persona: TP=12%, current P&L=6% (50% of TP).
        Expected: ALLOWED (Early Exit Guard disabled for high).
        """
        db_path = f"test_paper_{uuid.uuid4().hex[:8]}.db"
        init_paper_db(db_path)

        cfg = _make_config("high", self.HIGH)
        risk = RiskManager(cfg, db_path=db_path)
        risk.apply_persona_config(self.HIGH, persona_name="high")

        # Entry: $100, Current: $106 (6% gain = 50% of 12% TP)
        open_positions = [_make_position(entry_price=100, current_price=106, tp_pct=12)]

        is_valid, reason, _ = risk.validate_sell("BTC/USD", open_positions, 106)

        assert is_valid, f"High should ALLOW early exit at 50% of TP. Reason: {reason}"

    def test_conservative_allows_exit_at_60_percent_tp(self):
        """
        Conservative persona: TP=12%, current P&L=7.2% (60% of TP).
        Expected: ALLOWED (meets the 60% threshold).
        """
        db_path = f"test_paper_{uuid.uuid4().hex[:8]}.db"
        init_paper_db(db_path)

        cfg = _make_config("conservative", self.CONSERVATIVE)
        risk = RiskManager(cfg, db_path=db_path)
        risk.apply_persona_config(self.CONSERVATIVE, persona_name="conservative")

        # Entry: $100, Current: $107.2 (7.2% gain = 60% of 12% TP)
        open_positions = [_make_position(entry_price=100, current_price=107.2, tp_pct=12)]

        is_valid, reason, _ = risk.validate_sell("BTC/USD", open_positions, 107.2)

        assert is_valid, f"Conservative should ALLOW exit at 60% of TP. Reason: {reason}"
