"""
Tests for S12.2.1 — Trailing Stop

PaperBroker.check_stops_and_tp() should:
1. Track highest_price_seen per position.
2. Activate trailing SL only after gain >= activate_after_pct.
3. Raise trailing SL as highest price increases.
4. Respect per_pair_overrides for trail_pct.
"""

import sqlite3
import tempfile
import unittest

from src.exchange.paper_broker import PaperBroker
from src.storage.database import init_paper_db


def _make_broker(tmp_db: str, trail_pct: float = 3.0, activate_pct: float = 1.5,
                 pair_overrides: dict = None) -> PaperBroker:
    config = {
        "trailing_stop": {
            "enabled": True,
            "trail_pct": trail_pct,
            "activate_after_pct": activate_pct,
            "per_pair_overrides": pair_overrides or {},
        },
        "breakeven_stop": {"enabled": False},
        "partial_take_profit": {"enabled": False},
    }
    return PaperBroker(paper_db=tmp_db, slippage_pct=0.0, maker_fee_pct=0.0, config=config)


def _seed_position(db: str, entry_price: float, sl_price: float, tp_price: float,
                   initial_highest: float = None) -> int:
    """Insert a synthetic open position directly into paper_positions."""
    from src.utils.tz import now_sgt_iso
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    # Ensure columns exist
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
        (now_sgt_iso(), "BTC/USD", "buy", entry_price, 0.01, entry_price * 0.01,
         sl_price, tp_price, 5.0, 8.0, "open",
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


def _get_highest(db: str, pos_id: int) -> float:
    conn = sqlite3.connect(db)
    row = conn.execute(
        "SELECT highest_price_seen FROM paper_positions WHERE id=?", (pos_id,)
    ).fetchone()
    conn.close()
    return float(row[0]) if row[0] is not None else None


class TestTrailingStop(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.db = self.tmp.name
        init_paper_db(self.db, starting_balance=10000.0)

    def test_highest_price_seen_updated(self):
        """
        When price rises above entry, highest_price_seen should be updated.
        """
        entry = 100.0
        broker = _make_broker(self.db)
        pos_id = _seed_position(self.db, entry_price=entry, sl_price=95.0, tp_price=108.0)

        # Price jumps to $103 — not yet activating trailing (only 3% = above activate_pct=1.5)
        broker.check_stops_and_tp("BTC/USD", current_price=103.0)
        self.assertAlmostEqual(_get_highest(self.db, pos_id), 103.0, places=4)

    def test_trailing_sl_not_activated_below_threshold(self):
        """
        If gain < activate_after_pct (1.5%), trailing SL should NOT be raised.
        """
        entry = 100.0
        original_sl = 95.0
        broker = _make_broker(self.db, activate_pct=1.5)
        pos_id = _seed_position(self.db, entry_price=entry, sl_price=original_sl, tp_price=108.0)

        # Price is $101 (+1%) — below 1.5% activation threshold
        broker.check_stops_and_tp("BTC/USD", current_price=101.0)
        sl_after = _get_sl_price(self.db, pos_id)
        self.assertAlmostEqual(sl_after, original_sl, places=4,
                               msg="Trailing SL should not move below activation threshold")

    def test_trailing_sl_activated_and_raised(self):
        """
        Once gain >= activate_after_pct, trailing SL = highest × (1 - trail_pct/100)
        and must be greater than the original SL to update.
        """
        entry = 100.0
        original_sl = 95.0  # 5% below entry
        trail_pct = 3.0
        broker = _make_broker(self.db, trail_pct=trail_pct, activate_pct=1.5)
        pos_id = _seed_position(self.db, entry_price=entry, sl_price=original_sl, tp_price=115.0)

        # Price rises to $104 (+4%) — above 1.5% activation
        # Trailing SL = 104 × (1 - 0.03) = $100.88 > $95 (original) → should update
        broker.check_stops_and_tp("BTC/USD", current_price=104.0)
        expected_sl = round(104.0 * (1 - trail_pct / 100), 8)
        self.assertAlmostEqual(_get_sl_price(self.db, pos_id), expected_sl, places=4)

    def test_per_pair_override_trail_pct(self):
        """
        DOGE/USD with override trail_pct=5.0 should use that, not the global 3.0.
        """
        entry = 1.0
        broker = _make_broker(
            self.db, trail_pct=3.0, activate_pct=0.5,
            pair_overrides={"DOGE/USD": 5.0}
        )
        # Seed a DOGE/USD position
        from src.utils.tz import now_sgt_iso
        conn = sqlite3.connect(self.db)
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
            (now_sgt_iso(), "DOGE/USD", "buy", entry, 100.0, 100.0,
             0.95, 1.2, 5.0, 20.0, "open", entry, 0),
        )
        conn.commit()
        pos_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.close()

        # Price = $1.02 (+2%) — above 0.5% activation
        # Trailing SL with DOGE override = 1.02 × (1 - 0.05) = $0.969
        broker.check_stops_and_tp("DOGE/USD", current_price=1.02)
        expected_sl = round(1.02 * (1 - 5.0 / 100), 8)
        self.assertAlmostEqual(_get_sl_price(self.db, pos_id), expected_sl, places=4)


if __name__ == "__main__":
    unittest.main()
