"""
Tests for #140 — entry slippage applied in PaperBroker.place_order().

1. fill_price = current_price × (1 + slippage_pct/100)
2. SL and TP are anchored to the slipped fill_price, not current_price
3. Zero entry slippage when slippage_pct=0.0
"""
import sys, os, tempfile, sqlite3, types
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# ── stub heavy dependencies ─────────────────────────────────────────────────
notifier_mod = types.ModuleType("src.notifications.notifier")
class _N:
    def send_trade_executed(self, *a, **kw): pass
notifier_mod.Notifier = _N
sys.modules.setdefault("src.notifications.notifier", notifier_mod)
sys.modules.setdefault("src.notifications", types.ModuleType("src.notifications"))

timing_mod = types.ModuleType("src.utils.timing")
timing_mod.timed = lambda *a, **kw: (lambda fn: fn)
sys.modules.setdefault("src.utils.timing", timing_mod)

from src.exchange.paper_broker import PaperBroker
from src.storage.database import init_paper_db


def _make_broker(slippage_pct: float = 0.05, starting_cash: float = 10_000.0):
    """Return PaperBroker backed by a fresh temp DB."""
    f = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    path = f.name
    f.close()
    init_paper_db(path, starting_balance=starting_cash)
    config = {
        "trading": {"stop_loss_pct": 5.0},
        "trailing_stop": {"enabled": False},
        "breakeven_stop": {"enabled": False},
        "partial_take_profit": {"enabled": False},
    }
    return PaperBroker(paper_db=path, slippage_pct=slippage_pct, maker_fee_pct=0.0, config=config), path


def _get_position(db_path: str, pos_id: int) -> dict:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM paper_positions WHERE id=?", (pos_id,)).fetchone()
    conn.close()
    return dict(row) if row else {}


class TestEntrySlippage:

    def test_fill_price_includes_entry_slippage(self):
        """
        Given slippage_pct=0.05 and current_price=2000.0
        When place_order() is called
        Then entry_price stored in DB = 2000 × 1.0005 = 2001.0
        """
        broker, db = _make_broker(slippage_pct=0.05)
        result = broker.place_order(
            pair="ETH/USD", side="buy",
            usd_amount=100.0, current_price=2000.0,
            stop_loss_pct=5.0, take_profit_pct=12.0,
        )
        pos = _get_position(db, result["position_id"])
        expected_fill = round(2000.0 * 1.0005, 8)
        assert abs(pos["entry_price"] - expected_fill) < 1e-6, (
            f"entry_price should be {expected_fill}, got {pos['entry_price']}"
        )

    def test_sl_tp_anchored_to_slipped_fill_price(self):
        """
        Given slippage_pct=0.05, current_price=1000.0, SL=5%, TP=10%
        When place_order() is called
        Then stop_loss_price = fill_price × 0.95  (not current_price × 0.95)
        And  take_profit_price = fill_price × 1.10 (not current_price × 1.10)
        """
        broker, db = _make_broker(slippage_pct=0.05)
        result = broker.place_order(
            pair="BTC/USD", side="buy",
            usd_amount=200.0, current_price=1000.0,
            stop_loss_pct=5.0, take_profit_pct=10.0,
        )
        pos = _get_position(db, result["position_id"])
        fill = pos["entry_price"]
        expected_sl = round(fill * 0.95, 8)
        expected_tp = round(fill * 1.10, 8)
        assert abs(pos["stop_loss_price"] - expected_sl) < 1e-4, (
            f"SL should be {expected_sl}, got {pos['stop_loss_price']}"
        )
        assert abs(pos["take_profit_price"] - expected_tp) < 1e-4, (
            f"TP should be {expected_tp}, got {pos['take_profit_price']}"
        )

    def test_zero_entry_slippage_when_slippage_pct_is_zero(self):
        """
        Given slippage_pct=0.0
        When place_order() is called with current_price=500.0
        Then entry_price stored in DB equals 500.0 exactly (no rounding drift)
        """
        broker, db = _make_broker(slippage_pct=0.0)
        result = broker.place_order(
            pair="SOL/USD", side="buy",
            usd_amount=50.0, current_price=500.0,
            stop_loss_pct=5.0, take_profit_pct=16.0,
        )
        pos = _get_position(db, result["position_id"])
        assert pos["entry_price"] == 500.0, (
            f"With zero slippage, entry_price should be 500.0, got {pos['entry_price']}"
        )
