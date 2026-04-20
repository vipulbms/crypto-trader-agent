"""
Tests for S15.3.1 — Velocity circuit breaker.

Verifies:
  1. High hourly loss rate → circuit trips, returns (True, resume_epoch)
  2. Normal P&L → circuit does NOT trip
  3. Halted circuit resumes after halt window expires
"""

import sys
import os
import uuid
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.risk.risk_manager import RiskManager
from src.storage.database import init_paper_db, get_connection

DB_PATH = f"test_paper_{uuid.uuid4().hex[:8]}.db"

PERSONA = {
    "max_open_positions": 3, "max_position_pct": 30, "min_profit_floor_pct": 1.0,
    "velocity_circuit_breaker_pct": 5.0, "velocity_halt_hours": 1,
    "pf_escalation_momentum_suspend": True,
    "early_momentum_score_reduction": 1, "early_momentum_rsi_min": 50,
    "early_momentum_rsi_max": 65, "early_momentum_adx_min": 25,
    "volume_bypass_enabled": True,
}

BASE_CONFIG = {
    "trading": {
        "stop_loss_pct": 5, "take_profit_pct": 8, "min_profit_floor_pct": 1.0,
        "max_position_pct": 30, "max_open_positions": 3,
        "pairs": [],
    },
    "risk": {
        "daily_loss_limit_pct": 10, "min_cash_reserve_pct": 5,
        "circuit_breaker": {"enabled": False, "consecutive_stops": 3, "pause_hours": 4},
    },
    "signals": {"buy_min_score": 5, "profit_factor_escalation": {"enabled": False}},
    "personas": {"medium": PERSONA},
    "agent": {"persona": "medium"},
}


def _mk_db():
    return f"test_paper_{uuid.uuid4().hex[:8]}.db"


def _make_risk(db_path: str):
    init_paper_db(db_path)
    r = RiskManager(BASE_CONFIG, db_path=db_path)
    r.apply_persona_config(PERSONA)
    return r


def _seed_losses(pnl_values: list, db_path: str):
    """Seed paper_trades rows with recent losses to trip the velocity circuit."""
    import datetime as _dt
    init_paper_db(db_path)
    conn = get_connection(db_path)
    now = _dt.datetime.now(_dt.timezone.utc)
    for pnl in pnl_values:
        closed_at = (now - _dt.timedelta(minutes=30)).isoformat()
        conn.execute(
            """INSERT INTO paper_trades
               (pair, side, entry_price, exit_price, volume, usd_invested,
                pnl_usd, pnl_pct, exit_reason, opened_at, closed_at, persona,
                hold_duration_secs, fee_usd, stop_loss_pct, take_profit_pct)
               VALUES (?, 'buy', 100, 95, 1, 100, ?, ?, 'stop_loss', ?, ?, '', 0, 0, 5, 8)""",
            ("BTC/USD", float(pnl), float(pnl) / 100, closed_at, closed_at),
        )
    conn.commit()
    conn.close()


def test_high_loss_rate_trips_circuit():
    """Losses > 5% within an hour → circuit trips."""
    db = _mk_db()
    risk = _make_risk(db)
    _seed_losses([-30, -30], db)
    tripped, resume_until = risk.check_velocity_circuit(1000.0, db)
    assert tripped is True
    assert resume_until > time.time()


def test_normal_pnl_no_trip():
    """Losses below threshold → circuit does NOT trip."""
    db = _mk_db()
    risk = _make_risk(db)
    _seed_losses([-5, -5], db)
    tripped, _ = risk.check_velocity_circuit(1000.0, db)
    assert tripped is False


def test_circuit_clears_after_halt_window():
    """Once halt window expires, circuit no longer reports tripped."""
    db = _mk_db()
    risk = _make_risk(db)
    conn = get_connection(db)
    conn.execute(
        "INSERT OR REPLACE INTO agent_state (key, value) VALUES (?, ?)",
        ("velocity_circuit_open_until", str(time.time() - 1)),
    )
    conn.commit()
    conn.close()
    # No recent trade losses → velocity check won't re-trip on trade data
    tripped, _ = risk.check_velocity_circuit(1000.0, db)
    assert tripped is False
