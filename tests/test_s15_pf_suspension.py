"""
Tests for S15.2.2 — Profit factor escalation suspended in momentum playbook.

Verifies:
  1. Standard playbook: PF < pf_severe raises buy_min_score by 2
  2. Standard playbook: PF < pf_warn raises buy_min_score by 1
  3. Momentum playbook + pf_escalation_momentum_suspend=True: no PF escalation
  4. Momentum playbook + pf_escalation_momentum_suspend=False: PF still escalates
"""

import sys
import os
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.risk.risk_manager import RiskManager
from src.storage.database import init_paper_db

DB_PATH = f"test_paper_{uuid.uuid4().hex[:8]}.db"

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
    "signals": {
        "buy_min_score": 5,
        "profit_factor_escalation": {
            "enabled": True,
            "lookback_days": 30,
            "min_trades": 1,
            "pf_warn_threshold": 1.0,
            "pf_severe_threshold": 0.7,
        },
    },
    "personas": {
        "medium": {
            "max_open_positions": 3, "max_position_pct": 30, "min_profit_floor_pct": 1.0,
            "velocity_circuit_breaker_pct": 5.0, "velocity_halt_hours": 2,
            "pf_escalation_momentum_suspend": True,
            "early_momentum_score_reduction": 1, "early_momentum_rsi_min": 50,
            "early_momentum_rsi_max": 65, "early_momentum_adx_min": 25,
            "volume_bypass_enabled": True,
        },
    },
    "agent": {"persona": "medium"},
}


def _make_risk(extra_persona=None):
    init_paper_db(DB_PATH)
    cfg = {**BASE_CONFIG}
    if extra_persona:
        cfg = {**cfg, "personas": {**cfg["personas"], "medium": {**cfg["personas"]["medium"], **extra_persona}}}
    r = RiskManager(cfg, db_path=DB_PATH)
    r.apply_persona_config(cfg["personas"]["medium"])
    if extra_persona:
        r.apply_persona_config({**cfg["personas"]["medium"], **extra_persona})
    return r


def test_standard_playbook_severe_pf_raises_min_score():
    """PF < 0.7 in standard playbook raises buy_min_score +2."""
    risk = _make_risk()
    pair_cfg = {"pair": "BTC/USD"}
    indicators = {"profit_factor": 0.5, "pf_trade_count": 5}
    sig_cfg = BASE_CONFIG["signals"]
    score = risk.get_effective_min_score("BTC/USD", "standard", pair_cfg, indicators, sig_cfg)
    assert score == 7, f"Expected 7 (5+2) for PF=0.5, got {score}"


def test_standard_playbook_warn_pf_raises_min_score():
    """PF < 1.0 (but >= 0.7) in standard playbook raises buy_min_score +1."""
    risk = _make_risk()
    pair_cfg = {"pair": "BTC/USD"}
    indicators = {"profit_factor": 0.8, "pf_trade_count": 5}
    sig_cfg = BASE_CONFIG["signals"]
    score = risk.get_effective_min_score("BTC/USD", "standard", pair_cfg, indicators, sig_cfg)
    assert score == 6, f"Expected 6 (5+1) for PF=0.8, got {score}"


def test_momentum_playbook_pf_suspended():
    """PF < 0.7 in momentum playbook with pf_escalation_momentum_suspend=True → no escalation."""
    risk = _make_risk()
    pair_cfg = {"pair": "BTC/USD"}
    indicators = {"profit_factor": 0.5, "pf_trade_count": 5}
    sig_cfg = BASE_CONFIG["signals"]
    score = risk.get_effective_min_score("BTC/USD", "momentum", pair_cfg, indicators, sig_cfg)
    # In momentum playbook, PF escalation is suspended (=0 delta from PF)
    # playbook delta for momentum = 0, so score stays at base 5
    assert score == 5, f"Expected 5 (no PF escalation in momentum), got {score}"


def test_momentum_playbook_pf_not_suspended_when_flag_false():
    """pf_escalation_momentum_suspend=False (conservative) → PF escalation still applies in momentum."""
    init_paper_db(DB_PATH)
    cfg = {**BASE_CONFIG, "personas": {
        "medium": {**BASE_CONFIG["personas"]["medium"], "pf_escalation_momentum_suspend": False}
    }}
    risk = RiskManager(cfg, db_path=DB_PATH)
    risk.apply_persona_config(cfg["personas"]["medium"])
    pair_cfg = {"pair": "BTC/USD"}
    indicators = {"profit_factor": 0.5, "pf_trade_count": 5}
    sig_cfg = BASE_CONFIG["signals"]
    score = risk.get_effective_min_score("BTC/USD", "momentum", pair_cfg, indicators, sig_cfg)
    # PF escalation fires (+2), playbook delta for momentum = 0
    assert score == 7, f"Expected 7 when pf suspend=False + momentum, got {score}"
