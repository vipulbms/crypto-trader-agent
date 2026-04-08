"""
Tests for #98 — Backtest Timestamp Fix

Verifies that:
1. PaperBroker.place_order() stores the candle timestamp (timestamp_override) as
   opened_at, not the wall-clock time.
2. PaperBroker.close_position() stores the candle timestamp as closed_at.
3. timestamp_override=None falls back to the current wall-clock time (ISO string).
4. check_stops_and_tp() passes the candle_ts through to close_position when
   a stop-loss is triggered.
"""

import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone

from src.exchange.paper_broker import PaperBroker
from src.storage.database import init_paper_db


CANDLE_TS_ISO = "2025-12-15T08:00:00+00:00"
ENTRY_PRICE   = 100.0
SL_PCT        = 5.0
TP_PCT        = 12.0


def _make_broker(tmp_db: str) -> PaperBroker:
    config = {
        "trailing_stop":        {"enabled": False},
        "breakeven_stop":       {"enabled": False},
        "partial_take_profit":  {"enabled": False},
    }
    return PaperBroker(paper_db=tmp_db, slippage_pct=0.0, maker_fee_pct=0.0, config=config)


def _seed_cash(db: str, amount: float = 10_000.0) -> None:
    conn = sqlite3.connect(db)
    conn.execute("UPDATE paper_wallet SET cash_usd=?", (amount,))
    conn.commit()
    conn.close()


def _get_position(db: str, pos_id: int) -> dict:
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM paper_positions WHERE id=?", (pos_id,)).fetchone()
    conn.close()
    return dict(row) if row else {}


def _get_trade(db: str, pos_id: int) -> dict:
    """Get the most recently inserted trade (paper_trades has no position_id FK)."""
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT * FROM paper_trades ORDER BY id DESC LIMIT 1"
    ).fetchone()
    conn.close()
    return dict(row) if row else {}


class TestPlaceOrderTimestamp(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        init_paper_db(self.tmp.name)
        _seed_cash(self.tmp.name)
        self.broker = _make_broker(self.tmp.name)

    def test_timestamp_override_stored_as_opened_at(self):
        """place_order with timestamp_override stores candle time as opened_at."""
        result = self.broker.place_order(
            pair="ETH/USD", side="buy",
            usd_amount=500.0, current_price=ENTRY_PRICE,
            stop_loss_pct=SL_PCT, take_profit_pct=TP_PCT,
            timestamp_override=CANDLE_TS_ISO,
        )
        pos = _get_position(self.tmp.name, result["position_id"])
        self.assertEqual(pos["opened_at"], CANDLE_TS_ISO,
                         "opened_at should equal the candle timestamp override")

    def test_no_override_uses_wall_clock(self):
        """place_order without timestamp_override sets opened_at to a recent wall-clock time."""
        before = datetime.now(timezone.utc)
        result = self.broker.place_order(
            pair="ETH/USD", side="buy",
            usd_amount=500.0, current_price=ENTRY_PRICE,
            stop_loss_pct=SL_PCT, take_profit_pct=TP_PCT,
        )
        after = datetime.now(timezone.utc)
        pos = _get_position(self.tmp.name, result["position_id"])
        opened_at = datetime.fromisoformat(pos["opened_at"]).astimezone(timezone.utc)
        self.assertGreaterEqual(opened_at, before.replace(microsecond=0))
        self.assertLessEqual(opened_at, after)

    def test_two_orders_with_different_candle_timestamps(self):
        """Two orders can have different candle timestamps stored independently."""
        ts1 = "2025-12-01T00:00:00+00:00"
        ts2 = "2025-12-10T12:00:00+00:00"
        r1 = self.broker.place_order(
            pair="ETH/USD", side="buy", usd_amount=200.0, current_price=100.0,
            stop_loss_pct=5.0, take_profit_pct=12.0, timestamp_override=ts1,
        )
        r2 = self.broker.place_order(
            pair="BTC/USD", side="buy", usd_amount=200.0, current_price=100.0,
            stop_loss_pct=5.0, take_profit_pct=8.0, timestamp_override=ts2,
        )
        p1 = _get_position(self.tmp.name, r1["position_id"])
        p2 = _get_position(self.tmp.name, r2["position_id"])
        self.assertEqual(p1["opened_at"], ts1)
        self.assertEqual(p2["opened_at"], ts2)


class TestClosePositionTimestamp(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        init_paper_db(self.tmp.name)
        _seed_cash(self.tmp.name)
        self.broker = _make_broker(self.tmp.name)

    def _open_position(self, ts=None):
        return self.broker.place_order(
            pair="ETH/USD", side="buy", usd_amount=500.0,
            current_price=ENTRY_PRICE,
            stop_loss_pct=SL_PCT, take_profit_pct=TP_PCT,
            timestamp_override=ts,
        )

    def test_close_with_timestamp_override_stores_closed_at(self):
        """close_position with timestamp_override stores candle time as closed_at."""
        open_result = self._open_position()
        close_ts = "2025-12-20T16:00:00+00:00"
        self.broker.close_position(
            position_id=open_result["position_id"],
            exit_price=ENTRY_PRICE * 1.10,
            exit_reason="take_profit",
            timestamp_override=close_ts,
        )
        trade = _get_trade(self.tmp.name, open_result["position_id"])
        self.assertEqual(trade["closed_at"], close_ts,
                         "closed_at should equal the exit candle timestamp override")

    def test_close_without_override_uses_wall_clock(self):
        """close_position without timestamp_override sets closed_at to wall-clock time."""
        open_result = self._open_position()
        before = datetime.now(timezone.utc)
        self.broker.close_position(
            position_id=open_result["position_id"],
            exit_price=ENTRY_PRICE * 1.10,
            exit_reason="take_profit",
        )
        after = datetime.now(timezone.utc)
        trade = _get_trade(self.tmp.name, open_result["position_id"])
        closed_at = datetime.fromisoformat(trade["closed_at"]).astimezone(timezone.utc)
        self.assertGreaterEqual(closed_at, before.replace(microsecond=0))
        self.assertLessEqual(closed_at, after)


class TestCheckStopsTimestampPropagation(unittest.TestCase):
    """candle_ts passed to check_stops_and_tp() should be forwarded to close_position."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        init_paper_db(self.tmp.name)
        _seed_cash(self.tmp.name)
        self.broker = _make_broker(self.tmp.name)

    def test_sl_triggered_uses_candle_ts_as_closed_at(self):
        """When SL fires inside check_stops_and_tp, the candle_ts becomes closed_at."""
        open_ts  = "2025-12-15T08:00:00+00:00"
        close_ts_epoch = 1734346800   # 2025-12-16T09:00:00 UTC as unix int
        r = self.broker.place_order(
            pair="ETH/USD", side="buy", usd_amount=500.0,
            current_price=ENTRY_PRICE,
            stop_loss_pct=SL_PCT, take_profit_pct=TP_PCT,
            timestamp_override=open_ts,
        )
        # Price well below stop-loss — SL should fire
        sl_price = ENTRY_PRICE * (1 - SL_PCT / 100)
        self.broker.check_stops_and_tp(
            pair="ETH/USD",
            current_price=sl_price - 1.0,
            candle_ts=close_ts_epoch,
        )
        trade = _get_trade(self.tmp.name, r["position_id"])
        self.assertIsNotNone(trade, "Trade should have been recorded after SL")
        self.assertEqual(trade["exit_reason"], "stop_loss",
                         "Exit reason should be stop_loss")
        # closed_at should be the ISO representation of close_ts_epoch
        closed_at = datetime.fromisoformat(trade["closed_at"]).astimezone(timezone.utc)
        expected_utc = datetime.fromtimestamp(close_ts_epoch, tz=timezone.utc)
        self.assertEqual(closed_at, expected_utc,
                         "closed_at should match the candle timestamp passed to check_stops_and_tp")


if __name__ == "__main__":
    unittest.main()
