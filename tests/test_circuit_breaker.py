"""
Tests for the circuit breaker in RiskManager.

Verifies:
- 3 recent stop-losses (within pause window) → circuit trips
- 3 old stop-losses (outside pause window) → circuit does NOT trip
- Streak broken by a profitable exit → circuit does NOT trip
- validate_buy is blocked when circuit is open
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from datetime import datetime, timezone, timedelta
from src.risk.risk_manager import RiskManager
from src.storage.database import get_connection

DB_PATH = "paper_trading.db"

CONFIG = {
    "trading": {
        "stop_loss_pct": 5, "take_profit_pct": 8, "min_profit_floor_pct": 1.0,
        "max_position_pct": 30, "max_open_positions": 3, "pairs": [],
    },
    "risk": {
        "daily_loss_limit_pct": 10, "min_cash_reserve_pct": 10,
        "circuit_breaker": {"enabled": True, "consecutive_stops": 3, "pause_hours": 4},
    },
}


def _seed_trades(rows: list) -> None:
    """Insert test trades. rows = list of (closed_at_iso, exit_reason)."""
    conn = get_connection(DB_PATH)
    conn.execute("DELETE FROM paper_trades WHERE pair='TEST/USD'")
    for closed_at, exit_reason in rows:
        conn.execute(
            "INSERT INTO paper_trades "
            "(opened_at, closed_at, pair, side, entry_price, exit_price, volume, "
            " usd_invested, pnl_usd, pnl_pct, exit_reason, hold_duration_secs, "
            " fee_usd, stop_loss_pct, take_profit_pct) "
            "VALUES (?, ?, 'TEST/USD', 'buy', 100, 95, 1, 100, -5, -5, ?, 3600, 0.26, 5, 8)",
            (closed_at, closed_at, exit_reason),
        )
    conn.commit()
    conn.close()


def _cleanup():
    conn = get_connection(DB_PATH)
    conn.execute("DELETE FROM paper_trades WHERE pair='TEST/USD'")
    conn.commit()
    conn.close()


def test_recent_stops_trip_circuit():
    """3 stop-losses within last 4 hours → circuit open."""
    now = datetime.now(timezone.utc)
    _seed_trades([
        ((now - timedelta(minutes=90)).isoformat(), "stop_loss"),
        ((now - timedelta(minutes=60)).isoformat(), "stop_loss"),
        ((now - timedelta(minutes=30)).isoformat(), "stop_loss"),
    ])
    rm = RiskManager(CONFIG, db_path=DB_PATH)
    open_, resume = rm.is_circuit_open()
    assert open_ is True, f"Expected circuit open, got {open_}"
    assert resume > 0, f"Expected resume > 0, got {resume}"
    print(f"PASS test_recent_stops_trip_circuit — resume in {resume/60:.0f} min")
    _cleanup()


def test_old_stops_do_not_trip():
    """3 stop-losses that are 6 hours old (outside 4h window) → circuit closed."""
    now = datetime.now(timezone.utc)
    _seed_trades([
        ((now - timedelta(hours=8)).isoformat(), "stop_loss"),
        ((now - timedelta(hours=7)).isoformat(), "stop_loss"),
        ((now - timedelta(hours=6)).isoformat(), "stop_loss"),
    ])
    rm = RiskManager(CONFIG, db_path=DB_PATH)
    open_, _ = rm.is_circuit_open()
    assert open_ is False, f"Expected circuit closed (old streak), got {open_}"
    print("PASS test_old_stops_do_not_trip")
    _cleanup()


def test_profit_breaks_streak():
    """2 stops then a profit then 1 stop → only 1 consecutive stop → circuit closed."""
    now = datetime.now(timezone.utc)
    _seed_trades([
        ((now - timedelta(minutes=90)).isoformat(), "stop_loss"),
        ((now - timedelta(minutes=60)).isoformat(), "stop_loss"),
        ((now - timedelta(minutes=45)).isoformat(), "take_profit"),   # breaks streak
        ((now - timedelta(minutes=30)).isoformat(), "stop_loss"),
    ])
    rm = RiskManager(CONFIG, db_path=DB_PATH)
    open_, _ = rm.is_circuit_open()
    assert open_ is False, f"Expected circuit closed (streak broken), got {open_}"
    print("PASS test_profit_breaks_streak")
    _cleanup()


def test_validate_buy_blocked():
    """validate_buy returns rejected when circuit is open."""
    now = datetime.now(timezone.utc)
    _seed_trades([
        ((now - timedelta(minutes=90)).isoformat(), "stop_loss"),
        ((now - timedelta(minutes=60)).isoformat(), "stop_loss"),
        ((now - timedelta(minutes=30)).isoformat(), "stop_loss"),
    ])
    rm = RiskManager(CONFIG, db_path=DB_PATH)
    approved, reason, amount = rm.validate_buy("BTC/USD", 100, 1000, 800, 0, 0, 1000)
    assert approved is False, f"Expected rejected, got approved"
    assert "Circuit breaker" in reason, f"Expected circuit breaker reason, got: {reason}"
    assert amount == 0.0
    print(f"PASS test_validate_buy_blocked — reason: {reason}")
    _cleanup()


if __name__ == "__main__":
    test_recent_stops_trip_circuit()
    test_old_stops_do_not_trip()
    test_profit_breaks_streak()
    test_validate_buy_blocked()
    print("\nAll circuit breaker tests passed.")
