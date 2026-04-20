"""
Tests for S21.2.2 — Fulfillment audit trail.

Verifies:
  1. _write_fulfillment_audit inserts a row with correct status and duration
  2. Duplicate fulfillment_id is silently ignored (INSERT OR IGNORE)
  3. Error case writes audit row with execution_status="error"
"""

import sys
import os
import uuid
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.storage.database import init_paper_db, get_connection

DB_PATH = f"test_paper_{uuid.uuid4().hex[:8]}.db"

BASE_CONFIG = {
    "trading": {
        "stop_loss_pct": 5, "take_profit_pct": 8, "min_profit_floor_pct": 1.0,
        "max_position_pct": 30, "max_open_positions": 3, "pairs": [],
        "candle_interval": 30,
    },
    "risk": {
        "daily_loss_limit_pct": 10, "min_cash_reserve_pct": 5,
        "circuit_breaker": {"enabled": False, "consecutive_stops": 3, "pause_hours": 4},
    },
    "signals": {"buy_min_score": 5, "profit_factor_escalation": {"enabled": False}},
    "fulfillment": {"api_key": "test-key"},
}


def _make_service():
    init_paper_db(DB_PATH)
    from src.runtime.fulfillment_service import FulfillmentService
    return FulfillmentService(BASE_CONFIG, DB_PATH, mode="paper", api_key="test-key")


def test_audit_row_written_for_fill():
    """_write_fulfillment_audit creates a row with correct status and positive duration_ms."""
    svc = _make_service()
    fid = str(uuid.uuid4())
    t0 = time.time() - 0.05  # 50ms earlier
    svc._write_fulfillment_audit(
        fulfillment_id=fid,
        pair="BTC/USD",
        side="buy",
        t0=t0,
        execution_status="filled",
        request_json='{"amount_usd": 100}',
        response_json='{"order_id": "abc"}',
    )
    conn = get_connection(DB_PATH)
    row = conn.execute(
        "SELECT * FROM fulfillment_audit WHERE fulfillment_id=?", (fid,)
    ).fetchone()
    conn.close()
    assert row is not None
    assert row["execution_status"] == "filled"
    assert row["pair"] == "BTC/USD"
    assert row["side"] == "buy"
    assert int(row["duration_ms"]) >= 0


def test_duplicate_fulfillment_id_ignored():
    """Second write with same fulfillment_id is silently ignored (INSERT OR IGNORE)."""
    svc = _make_service()
    fid = str(uuid.uuid4())
    t0 = time.time()
    svc._write_fulfillment_audit(fid, "ETH/USD", "buy", t0, "filled", '{}')
    svc._write_fulfillment_audit(fid, "ETH/USD", "buy", t0, "error", '{}')  # duplicate
    conn = get_connection(DB_PATH)
    rows = conn.execute(
        "SELECT * FROM fulfillment_audit WHERE fulfillment_id=?", (fid,)
    ).fetchall()
    conn.close()
    assert len(rows) == 1
    assert rows[0]["execution_status"] == "filled"  # first write wins


def test_error_status_written():
    """Error path writes audit row with execution_status='error' and error_message."""
    svc = _make_service()
    fid = str(uuid.uuid4())
    t0 = time.time()
    svc._write_fulfillment_audit(
        fid, "SOL/USD", "buy", t0, "error", '{}', error_message="Broker timeout"
    )
    conn = get_connection(DB_PATH)
    row = conn.execute(
        "SELECT * FROM fulfillment_audit WHERE fulfillment_id=?", (fid,)
    ).fetchone()
    conn.close()
    assert row is not None
    assert row["execution_status"] == "error"
    assert "Broker timeout" in (row["error_message"] or "")
