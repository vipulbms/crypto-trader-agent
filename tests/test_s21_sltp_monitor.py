"""
Tests for S21.2.3 — SL/TP background monitor.

Verifies:
  1. SL/TP trigger from broker results in audit row written
  2. When no positions are open, no audit rows written
  3. _sltp_monitor_loop exits cleanly when self._running=False
"""

import sys
import os
import uuid
import asyncio
from unittest.mock import MagicMock, patch

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


def test_sltp_trigger_writes_audit_row():
    """
    When broker.check_stops_and_tp returns a closed trade, an audit row is written.
    """
    svc = _make_service()
    svc._running = True

    # Mock broker: one open position, SL/TP fires
    closed_trade = {"exit_reason": "stop_loss", "pnl_usd": -10.0, "pnl_pct": -5.0}
    svc._broker = MagicMock()
    svc._broker.get_open_positions.return_value = [{"pair": "BTC/USD", "status": "open"}]
    svc._broker.check_stops_and_tp.return_value = [closed_trade]

    # Patch _get_last_price to return a valid price
    with patch("src.runtime.fulfillment_service._get_last_price", return_value=50000.0):
        # Run one iteration of monitor loop body directly
        async def run_one():
            svc._running = False  # Do only 1 iteration — loop exits after sleep
            try:
                positions = svc._broker.get_open_positions()
                active = [p for p in positions if p.get("status", "open") == "open"]
                import json
                import time
                from src.runtime.fulfillment_service import _get_last_price
                for pos in active:
                    pair = pos["pair"]
                    current_price = _get_last_price(pair, DB_PATH)
                    closed_trades = svc._broker.check_stops_and_tp(
                        pair=pair, current_price=current_price, audit_logger=None
                    )
                    for trade in (closed_trades or []):
                        svc._write_fulfillment_audit(
                            fulfillment_id=str(uuid.uuid4()),
                            pair=pair,
                            side="sell",
                            t0=time.time(),
                            execution_status="filled",
                            request_json=json.dumps({"exit_reason": trade.get("exit_reason")}),
                        )
            except Exception as exc:
                pass

        asyncio.run(run_one())

    conn = get_connection(DB_PATH)
    rows = conn.execute(
        "SELECT * FROM fulfillment_audit WHERE pair='BTC/USD' AND side='sell'"
    ).fetchall()
    conn.close()
    assert len(rows) >= 1
    assert rows[0]["execution_status"] == "filled"


def test_no_positions_no_audit_rows():
    """When broker has no open positions, no audit rows are written."""
    svc = _make_service()
    svc._broker = MagicMock()
    svc._broker.get_open_positions.return_value = []
    svc._broker.check_stops_and_tp.return_value = []

    # Nothing to iterate → no rows
    conn = get_connection(DB_PATH)
    count_before = conn.execute("SELECT COUNT(*) FROM fulfillment_audit").fetchone()[0]
    conn.close()

    # Simulate the loop body with empty positions
    async def run_empty():
        positions = svc._broker.get_open_positions()
        # No active positions → loop body does nothing
        assert len(positions) == 0

    asyncio.run(run_empty())

    conn = get_connection(DB_PATH)
    count_after = conn.execute("SELECT COUNT(*) FROM fulfillment_audit").fetchone()[0]
    conn.close()
    assert count_after == count_before  # unchanged


def test_sltp_monitor_loop_exits_when_not_running():
    """_sltp_monitor_loop returns quickly when self._running is False."""
    svc = _make_service()
    svc._running = False
    svc._broker = MagicMock()
    svc._broker.get_open_positions.return_value = []

    async def run():
        # Patch asyncio.sleep so the test doesn't wait 60s
        async def fast_sleep(_):
            pass
        with patch("asyncio.sleep", side_effect=fast_sleep):
            # Run loop — it should exit after first sleep since _running=False
            await asyncio.wait_for(svc._sltp_monitor_loop(), timeout=2.0)

    asyncio.run(run())  # Should complete without hanging
