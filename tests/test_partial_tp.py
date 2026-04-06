"""
Tests for S12.5.1 — Partial Take-Profit

PaperBroker.check_stops_and_tp() should:
1. Close 50% of position when price reaches 50% of TP target (trigger).
2. NOT fire before the trigger price.
3. NOT fire a second time (partial_exited flag guard).
4. Move SL to entry_price after partial close when move_sl_to_breakeven=True.
5. Credit the correct USD proceeds to the wallet after the partial close.
"""

import sqlite3
import tempfile
import unittest

from src.exchange.paper_broker import PaperBroker
from src.storage.database import init_paper_db


# ──────────────────────────────────────────────
# Test helpers
# ──────────────────────────────────────────────

def _make_broker(
    tmp_db: str,
    trigger_pct: float = 50,
    close_fraction: float = 0.5,
    move_sl_to_breakeven: bool = True,
) -> PaperBroker:
    config = {
        "trailing_stop": {"enabled": False},
        "breakeven_stop": {"enabled": False},
        "partial_take_profit": {
            "enabled": True,
            "trigger_pct_of_tp": trigger_pct,
            "close_fraction": close_fraction,
            "move_sl_to_breakeven": move_sl_to_breakeven,
        },
    }
    return PaperBroker(paper_db=tmp_db, slippage_pct=0.0, maker_fee_pct=0.0, config=config)


def _seed_position(
    db: str,
    entry_price: float = 1000.0,
    sl_price: float = 950.0,
    tp_price: float = 1120.0,    # +12% TP
    take_profit_pct: float = 12.0,
    volume: float = 1.0,
    partial_exited: int = 0,
) -> int:
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
    usd_value = entry_price * volume
    conn.execute(
        """INSERT INTO paper_positions
           (opened_at, pair, side, entry_price, volume, usd_value,
            stop_loss_price, take_profit_price, stop_loss_pct, take_profit_pct,
            status, highest_price_seen, partial_exited)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (now_sgt_iso(), "SOL/USD", "buy", entry_price, volume, usd_value,
         sl_price, tp_price, 5.0, take_profit_pct, "open", entry_price, partial_exited),
    )
    conn.commit()
    pos_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.close()
    return pos_id


def _get_position(db: str, pos_id: int) -> dict:
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT * FROM paper_positions WHERE id=?", (pos_id,)
    ).fetchone()
    conn.close()
    return dict(row) if row else {}


def _get_cash(db: str) -> float:
    conn = sqlite3.connect(db)
    row = conn.execute("SELECT cash_usd FROM paper_wallet ORDER BY id DESC LIMIT 1").fetchone()
    conn.close()
    return float(row[0]) if row else 0.0


def _count_trades(db: str, exit_reason: str) -> int:
    conn = sqlite3.connect(db)
    n = conn.execute(
        "SELECT COUNT(*) FROM paper_trades WHERE exit_reason=?", (exit_reason,)
    ).fetchone()[0]
    conn.close()
    return n


# ──────────────────────────────────────────────
# Test cases
# ──────────────────────────────────────────────

class TestPartialTakeProfit(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.db = self.tmp.name
        init_paper_db(self.db, starting_balance=10000.0)

    # (a) Partial close fires at the trigger price
    def test_partial_close_fires_at_trigger(self):
        """
        At 50% of TP target, 50% of position should be closed with reason
        'partial_take_profit' and position remains open with half the volume.
        """
        entry      = 1000.0
        tp_pct     = 12.0
        # 50% of the way to TP → +6% → $1060
        trigger    = entry * (1 + tp_pct * 0.5 / 100)   # 1060.0
        broker     = _make_broker(self.db)
        pos_id     = _seed_position(self.db, entry_price=entry, tp_price=1120.0,
                                    take_profit_pct=tp_pct, volume=1.0)

        result = broker.check_stops_and_tp("SOL/USD", current_price=trigger)

        # One partial trade should have been appended to closed list
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["exit_reason"], "partial_take_profit")
        self.assertAlmostEqual(result[0]["volume"], 0.5, places=6)

        # Position still open with 50% volume
        pos = _get_position(self.db, pos_id)
        self.assertEqual(pos["status"], "open")
        self.assertAlmostEqual(pos["volume"], 0.5, places=6)
        self.assertEqual(pos["partial_exited"], 1)

    # (b) No partial close before trigger
    def test_no_partial_close_before_trigger(self):
        """
        Price below trigger threshold → position unchanged, no trades recorded.
        """
        entry   = 1000.0
        tp_pct  = 12.0
        # Below 50% of TP → only +3% (+$30) — trigger is +6%
        below_trigger = entry * (1 + tp_pct * 0.5 / 100) - 1  # $1059
        broker  = _make_broker(self.db)
        pos_id  = _seed_position(self.db, entry_price=entry, tp_price=1120.0,
                                 take_profit_pct=tp_pct, volume=1.0)

        result = broker.check_stops_and_tp("SOL/USD", current_price=below_trigger)

        self.assertEqual(result, [], "No trades before trigger")
        pos = _get_position(self.db, pos_id)
        self.assertEqual(pos["partial_exited"], 0)
        self.assertAlmostEqual(pos["volume"], 1.0, places=6)

    # (c) partial_exited flag prevents second fire
    def test_no_double_fire(self):
        """
        If partial_exited is already 1, a second price tick above the trigger
        must NOT close another portion.
        """
        entry   = 1000.0
        trigger = 1060.0
        broker  = _make_broker(self.db)
        # Seed with partial_exited=1 (already fired once)
        pos_id  = _seed_position(self.db, entry_price=entry, tp_price=1120.0,
                                 take_profit_pct=12.0, volume=0.5, partial_exited=1)

        result = broker.check_stops_and_tp("SOL/USD", current_price=trigger)

        self.assertEqual(result, [], "Second partial fire must be prevented")
        pos = _get_position(self.db, pos_id)
        self.assertAlmostEqual(pos["volume"], 0.5, places=6,
                               msg="Volume must not change on second tick")

    # (d) SL moves to entry after partial close (move_sl_to_breakeven=True)
    def test_sl_moves_to_entry_after_partial(self):
        """
        With move_sl_to_breakeven=True, the remaining position's SL should be
        set to entry_price after the partial TP fires.
        """
        entry  = 1000.0
        sl     = 950.0
        broker = _make_broker(self.db, move_sl_to_breakeven=True)
        pos_id = _seed_position(self.db, entry_price=entry, sl_price=sl,
                                tp_price=1120.0, take_profit_pct=12.0, volume=1.0)

        broker.check_stops_and_tp("SOL/USD", current_price=1060.0)

        pos = _get_position(self.db, pos_id)
        self.assertAlmostEqual(
            pos["stop_loss_price"], entry, places=4,
            msg="SL should equal entry_price after partial TP fires"
        )

    # (e) Wallet is credited correctly after partial close
    def test_wallet_credited_after_partial(self):
        """
        After partial TP close, cash should increase by:
          gross = exit_price × partial_volume
          fee   = gross × 0.26%   (hardcoded taker fee in close_position)
          net   = gross - fee
        """
        entry   = 1000.0
        volume  = 1.0
        exit_px = 1060.0
        starting_cash = _get_cash(self.db)

        broker  = _make_broker(self.db)
        _seed_position(self.db, entry_price=entry, tp_price=1120.0,
                       take_profit_pct=12.0, volume=volume)

        broker.check_stops_and_tp("SOL/USD", current_price=exit_px)

        new_cash = _get_cash(self.db)
        partial_vol   = volume * 0.5            # 0.5
        gross         = exit_px * partial_vol   # 530.0
        fee           = gross * 0.0026          # 1.378
        expected_net  = gross - fee             # 528.622

        self.assertGreater(new_cash, starting_cash,
                           "Cash should increase after partial close")
        self.assertAlmostEqual(
            new_cash - starting_cash, expected_net, delta=0.01,
            msg="Wallet credit should match net proceeds after exit fee"
        )


if __name__ == "__main__":
    unittest.main()
