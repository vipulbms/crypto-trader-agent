"""
Tests for S16.1.2 — Playbook injection into validate_buy and get_effective_min_score.

Verifies:
  1. risk_off playbook adds +2 to effective min score
  2. ranging playbook adds +1 to effective min score
  3. risk_off playbook raises profit floor × 1.5; pair TP below floor is rejected
"""

import sys
import os
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.risk.risk_manager import RiskManager
from src.storage.database import init_paper_db

DB_PATH = f"test_paper_{uuid.uuid4().hex[:8]}.db"

PERSONA = {
    "max_open_positions": 3, "max_position_pct": 30, "min_profit_floor_pct": 1.0,
    "velocity_circuit_breaker_pct": 5.0, "velocity_halt_hours": 1,
    "pf_escalation_momentum_suspend": True,
    "early_momentum_score_reduction": 1, "early_momentum_rsi_min": 50,
    "early_momentum_rsi_max": 65, "early_momentum_adx_min": 25,
    "volume_bypass_enabled": True,
    "momentum_bypass_rsi": 75, "momentum_bypass_adx": 30,
}

BASE_CONFIG = {
    "trading": {
        "stop_loss_pct": 5, "take_profit_pct": 8, "min_profit_floor_pct": 1.0,
        "max_position_pct": 30, "max_open_positions": 3,
        "pairs": [
            {"pair": "BTC/USD", "take_profit_pct": 8},
            {"pair": "XRP/USD", "take_profit_pct": 1.2},
        ],
    },
    "risk": {
        "daily_loss_limit_pct": 10, "min_cash_reserve_pct": 5,
        "circuit_breaker": {"enabled": False, "consecutive_stops": 3, "pause_hours": 4},
    },
    "signals": {
        "buy_min_score": 5,
        "profit_factor_escalation": {"enabled": False},
        "playbook_score_deltas": {"ranging": 1, "risk_off": 2, "momentum": 0, "standard": 0},
    },
    "personas": {"medium": PERSONA},
    "agent": {"persona": "medium"},
}


def _make_risk():
    init_paper_db(DB_PATH)
    r = RiskManager(BASE_CONFIG, db_path=DB_PATH)
    r.apply_persona_config(PERSONA, persona_name="medium")
    return r


def test_risk_off_playbook_raises_score_delta():
    """risk_off playbook adds +2 to base buy_min_score via get_effective_min_score."""
    risk = _make_risk()
    sig_cfg = BASE_CONFIG["signals"]
    base_score = int(sig_cfg.get("buy_min_score", 5))
    effective = risk.get_effective_min_score(
        "BTC/USD", "risk_off",
        {"pair": "BTC/USD", "take_profit_pct": 8},
        {"profit_factor": None},
        sig_cfg,
    )
    # risk_off delta = +2 → should be at least base + 2
    assert effective >= base_score + 2


def test_ranging_playbook_raises_score_delta():
    """ranging playbook adds +1 to base buy_min_score."""
    risk = _make_risk()
    sig_cfg = BASE_CONFIG["signals"]
    base_score = int(sig_cfg.get("buy_min_score", 5))
    effective = risk.get_effective_min_score(
        "BTC/USD", "ranging",
        {"pair": "BTC/USD", "take_profit_pct": 8},
        {"profit_factor": None},
        sig_cfg,
    )
    assert effective >= base_score + 1


def test_risk_off_profit_floor_rejects_low_tp_pair():
    """
    risk_off floor = min_profit_floor × 1.5 = 1.5%.
    XRP has TP 1.2%, which is below 1.5% → validate_buy should reject.
    """
    risk = _make_risk()
    approved, reason, _ = risk.validate_buy(
        pair="XRP/USD",
        proposed_usd=100.0,
        portfolio_balance_usd=1000.0,
        available_cash_usd=800.0,
        open_positions_count=0,
        daily_loss_usd=0.0,
        starting_balance_usd=1000.0,
        current_price=0.5,
        playbook="risk_off",
    )
    assert approved is False
    assert "floor" in reason.lower() or "profit" in reason.lower()
