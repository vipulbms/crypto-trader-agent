"""
Tests for S12.3.1 — Breakeven Stop

PaperBroker.check_stops_and_tp() should:
1. Move SL to entry_price when price reaches trigger_pct above entry.
2. NOT move SL before the trigger threshold is reached.
3. NOT re-fire after SL has already been moved to entry (guard: sl_price < entry_price).
"""

import sqlite3
import tempfile
import unittest

from src.exchange.paper_broker import PaperBroker
from src.storage.database import init_paper_db


def _make_broker(tmp_db: str, trigger_pct: float = 2.0) -> PaperBroker:
    config = {
        "trailing_stop": {"enabled": False},
        "breakeven_stop": {
            "enabled": True,
            "trigger_pct": trigger_pct,
        },
        "partial_take_profit": {"enabled": False},
    }
    return PaperBroker(paper_db=tmp_db, slippage_pct=0.0, maker_fee_pct=0.0, config=config)


def _seed_position(db: str, entry_price: float, sl_price: float, tp_price: float,
                   initial_highest: float = None) -> int:
    """Insert a synthetic open position directly into paper_positions."""
    from src.utils.tz import now_sgt_iso
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    for col in [
        "ALTER TABLE paper_positions ADD COLUMN highest_price_seen REAL",
        "ALTER TABLE paper_positions ADD COLUMN partial_exited INTEGER DEFAULT 0",
    ]:
        try:
            conn.execute(col)
        except sqlite3.OperationalError:
            pass
    conn.execute(
        """INSERT INTO paper_positions
           (opened_at, pair, side, entry_price, volume, usd_value,
            stop_loss_price, take_profit_price, stop_loss_pct, take_profit_pct,
            status, highest_price_seen, partial_exited)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (now_sgt_iso(), "ETH/USD", "buy", entry_price, 0.1, entry_price * 0.1,
         sl_price, tp_price, 5.0, 12.0, "open",
         initial_highest if initial_highest is not None else entry_price, 0),
    )
    conn.commit()
    pos_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.close()
    return pos_id


def _get_sl_price(db: str, pos_id: int) -> float:
    conn = sqlite3.connect(db)
    row = conn.execute(
        "SELECT stop_loss_price FROM paper_positions WHERE id=?", (pos_id,)
    ).fetchone()
    conn.close()
    return float(row[0])


class TestBreakevenStop(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.db = self.tmp.name
        init_paper_db(self.db, starting_balance=10000.0)

    def test_sl_moves_to_entry_when_trigger_reached(self):
        """
        When price rises to >= entry * (1 + trigger_pct/100), SL should be moved
        to entry_price so the trade cannot close at a loss.
        """
        entry = 2000.0
        original_sl = 1900.0  # 5% below entry
        # trigger_pct = 2.0, so need price >= 2040.0
        broker = _make_broker(self.db, trigger_pct=2.0)
        pos_id = _seed_position(
            self.db, entry_price=entry, sl_price=original_sl, tp_price=2240.0
        )

        broker.check_stops_and_tp("ETH/USD", current_price=2050.0)

        sl_after = _get_sl_price(self.db, pos_id)
        self.assertAlmostEqual(
            sl_after, entry, places=4,
            msg="SL should equal entry_price after breakeven trigger fires"
        )

    def test_sl_does_not_move_before_trigger(self):
        """
        When price is below trigger threshold, SL must NOT change.
        """
        entry = 2000.0
        original_sl = 1900.0
        # trigger_pct = 2.0 → needs $2040; we feed $2030 (only +1.5%)
        broker = _make_broker(self.db, trigger_pct=2.0)
        pos_id = _seed_position(
            self.db, entry_price=entry, sl_price=original_sl, tp_price=2240.0
        )

        broker.check_stops_and_tp("ETH/USD", current_price=2030.0)

        sl_after = _get_sl_price(self.db, pos_id)
        self.assertAlmostEqual(
            sl_after, original_sl, places=4,
            msg="SL should remain unchanged before trigger threshold is reached"
        )

    def test_sl_does_not_re_fire_once_at_entry(self):
        """
        Once SL is already at entry_price (sl_price == entry_price), subsequent
        price ticks above the trigger threshold must NOT fire again.
        This guards against redundant DB writes and any unintended state change.
        """
        entry = 2000.0
        # Simulate position already at breakeven: sl_price == entry_price
        broker = _make_broker(self.db, trigger_pct=2.0)
        pos_id = _seed_position(
            self.db,
            entry_price=entry,
            sl_price=entry,          # already at breakeven
            tp_price=2240.0,
        )

        # Price is well above trigger — but guard should prevent re-fire
        broker.check_stops_and_tp("ETH/USD", current_price=2100.0)

        sl_after = _get_sl_price(self.db, pos_id)
        self.assertAlmostEqual(
            sl_after, entry, places=4,
            msg="SL should remain at entry_price; guard prevents re-fire"
        )


if __name__ == "__main__":
    unittest.main()
