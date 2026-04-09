"""
Tests for Fix #115: Backtest must use candle timestamps exclusively.

Verifies that opened_at, closed_at in paper_trading.db records use the
candle timestamp (passed as timestamp_override) and never the system clock.
Also verifies hold_secs is computed from candle timestamps, not wall clock.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone


CANDLE_TS_ISO = "2025-07-01T10:00:00+00:00"   # representative historical timestamp
CANDLE_TS_CLOSE = "2025-07-01T10:15:00+00:00"  # 15 min later (one candle forward)


def _make_broker(db_path: str):
    from src.exchange.paper_broker import PaperBroker
    from src.storage.database import init_all_databases

    config = {
        "storage": {"paper_db": db_path},
        "paper": {"slippage_pct": 0.0, "maker_fee_pct": 0.0},
        "trading": {"stop_loss_pct": 5, "min_profit_floor_pct": 1.0, "pairs": []},
        "dynamic_tp": {"enabled": False},
        "trailing_stop": {"enabled": False},
        "breakeven_stop": {"enabled": False},
        "partial_take_profit": {"enabled": False},
    }
    init_all_databases(config, "paper")
    return PaperBroker(paper_db=db_path, slippage_pct=0.0, maker_fee_pct=0.0, config=config)


class TestBacktestCandleTimestamps(unittest.TestCase):

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self._db = os.path.join(self._tmpdir, "test_paper.db")
        self._broker = _make_broker(self._db)
        # Seed wallet with $1000
        conn = sqlite3.connect(self._db)
        conn.execute("UPDATE paper_wallet SET cash_usd=1000.0")
        conn.commit()
        conn.close()

    def test_opened_at_uses_candle_timestamp_not_system_clock(self):
        """
        Given a buy is placed with timestamp_override = CANDLE_TS_ISO
        When the position is recorded in paper_positions
        Then opened_at equals CANDLE_TS_ISO (not system time)
        """
        result = self._broker.place_order(
            pair="BTC/USD",
            side="buy",
            usd_amount=100.0,
            current_price=50000.0,
            stop_loss_pct=5.0,
            take_profit_pct=8.0,
            timestamp_override=CANDLE_TS_ISO,
        )
        conn = sqlite3.connect(self._db)
        row = conn.execute(
            "SELECT opened_at FROM paper_positions WHERE id=?",
            (result["position_id"],)
        ).fetchone()
        conn.close()
        self.assertIsNotNone(row)
        self.assertEqual(row[0], CANDLE_TS_ISO,
                         f"opened_at should be candle time; got: {row[0]}")

    def test_closed_at_uses_candle_timestamp_not_system_clock(self):
        """
        Given a position is opened at CANDLE_TS_ISO
        And the position is closed with timestamp_override = CANDLE_TS_CLOSE
        When the trade is recorded in paper_trades
        Then closed_at equals CANDLE_TS_CLOSE (not system time)
        """
        result = self._broker.place_order(
            pair="BTC/USD",
            side="buy",
            usd_amount=100.0,
            current_price=50000.0,
            stop_loss_pct=5.0,
            take_profit_pct=8.0,
            timestamp_override=CANDLE_TS_ISO,
        )
        self._broker.close_position(
            position_id=result["position_id"],
            exit_price=51000.0,
            exit_reason="test_exit",
            timestamp_override=CANDLE_TS_CLOSE,
        )
        conn = sqlite3.connect(self._db)
        row = conn.execute(
            "SELECT opened_at, closed_at FROM paper_trades WHERE pair='BTC/USD'"
        ).fetchone()
        conn.close()
        self.assertIsNotNone(row)
        self.assertEqual(row[0], CANDLE_TS_ISO,
                         f"opened_at in trade should be candle time; got: {row[0]}")
        self.assertEqual(row[1], CANDLE_TS_CLOSE,
                         f"closed_at in trade should be candle time; got: {row[1]}")

    def test_hold_secs_computed_from_candle_time_not_wall_clock(self):
        """
        Given a position opened at CANDLE_TS_ISO (2025-07-01 10:00)
        And closed at CANDLE_TS_CLOSE (2025-07-01 10:15)
        When hold_secs is computed
        Then it equals 900 seconds (15 minutes), not wall-clock elapsed time
        """
        result = self._broker.place_order(
            pair="ETH/USD",
            side="buy",
            usd_amount=100.0,
            current_price=2000.0,
            stop_loss_pct=5.0,
            take_profit_pct=12.0,
            timestamp_override=CANDLE_TS_ISO,
        )
        self._broker.close_position(
            position_id=result["position_id"],
            exit_price=2100.0,
            exit_reason="take_profit",
            timestamp_override=CANDLE_TS_CLOSE,
        )
        conn = sqlite3.connect(self._db)
        row = conn.execute(
            "SELECT hold_duration_secs FROM paper_trades WHERE pair='ETH/USD'"
        ).fetchone()
        conn.close()
        self.assertIsNotNone(row)
        self.assertEqual(row[0], 900,
                         f"hold_secs should be 900 (15 min candle gap); got: {row[0]}")


if __name__ == "__main__":
    unittest.main()
