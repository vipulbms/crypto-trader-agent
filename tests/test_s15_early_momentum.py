"""
Tests for S15.2.3 — Early momentum score reduction.

Verifies:
  1. RSI in early-momentum range + ADX enough → buy_min_score reduced by 1 (floor=1)
  2. RSI too high (>rsi_max) → no reduction
  3. RSI too low (<rsi_min) → no reduction
  4. ADX below adx_min → no reduction
  5. Reduction floored at 1 (cannot go below 1)
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
    "velocity_circuit_breaker_pct": 5.0, "velocity_halt_hours": 2,
    "pf_escalation_momentum_suspend": True,
    "early_momentum_score_reduction": 1, "early_momentum_rsi_min": 50,
    "early_momentum_rsi_max": 65, "early_momentum_adx_min": 25,
    "volume_bypass_enabled": True,
}

BASE_CONFIG = {
    "trading": {
        "stop_loss_pct": 5, "take_profit_pct": 8, "min_profit_floor_pct": 1.0,
        "max_position_pct": 30, "max_open_positions": 3,
        "pairs": [{"pair": "BTC/USD", "take_profit_pct": 8}],
    },
    "risk": {
        "daily_loss_limit_pct": 10, "min_cash_reserve_pct": 5,
        "circuit_breaker": {"enabled": False, "consecutive_stops": 3, "pause_hours": 4},
    },
    "signals": {"buy_min_score": 5, "profit_factor_escalation": {"enabled": False}},
    "personas": {"medium": PERSONA},
    "agent": {"persona": "medium"},
}


def _make_risk():
    init_paper_db(DB_PATH)
    r = RiskManager(BASE_CONFIG, db_path=DB_PATH)
    r.apply_persona_config(PERSONA, persona_name="medium")
    return r


def test_early_momentum_reduces_score():
    """RSI=55 (in [50,65]) ADX=30 (>25) in momentum → score 5−1=4."""
    risk = _make_risk()
    indicators = {"rsi_14": 55, "adx_14": 30}
    sig_cfg = BASE_CONFIG["signals"]
    score = risk.get_effective_min_score("BTC/USD", "momentum", {}, indicators, sig_cfg)
    assert score == 4, f"Expected 4 (5−1), got {score}"


def test_early_momentum_rsi_too_high_no_reduction():
    """RSI=70 (>rsi_max=65) → no early-momentum reduction."""
    risk = _make_risk()
    indicators = {"rsi_14": 70, "adx_14": 30}
    sig_cfg = BASE_CONFIG["signals"]
    score = risk.get_effective_min_score("BTC/USD", "momentum", {}, indicators, sig_cfg)
    assert score == 5, f"Expected 5 (no reduction, RSI too high), got {score}"


def test_early_momentum_rsi_too_low_no_reduction():
    """RSI=45 (<rsi_min=50) → no early-momentum reduction."""
    risk = _make_risk()
    indicators = {"rsi_14": 45, "adx_14": 30}
    sig_cfg = BASE_CONFIG["signals"]
    score = risk.get_effective_min_score("BTC/USD", "momentum", {}, indicators, sig_cfg)
    assert score == 5, f"Expected 5 (no reduction, RSI too low), got {score}"


def test_early_momentum_adx_too_low_no_reduction():
    """ADX=15 (<adx_min=25) → no early-momentum reduction."""
    risk = _make_risk()
    indicators = {"rsi_14": 55, "adx_14": 15}
    sig_cfg = BASE_CONFIG["signals"]
    score = risk.get_effective_min_score("BTC/USD", "momentum", {}, indicators, sig_cfg)
    assert score == 5, f"Expected 5 (no reduction, ADX too low), got {score}"


def test_early_momentum_floor_at_one():
    """Score cannot drop below 1 even with big reduction + playbook delta is 0 (momentum)."""
    persona_big_reduction = {**PERSONA, "early_momentum_score_reduction": 10}
    r = RiskManager({**BASE_CONFIG, "personas": {"medium": persona_big_reduction}}, db_path=DB_PATH)
    r.apply_persona_config(persona_big_reduction, persona_name="medium")
    indicators = {"rsi_14": 55, "adx_14": 30}
    sig_cfg = BASE_CONFIG["signals"]
    score = r.get_effective_min_score("BTC/USD", "momentum", {}, indicators, sig_cfg)
    assert score >= 1, f"Score should be >= 1, got {score}"
