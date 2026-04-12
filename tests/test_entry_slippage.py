"""
Tests for #140 — entry slippage applied in PaperBroker.place_order().

1. fill_price = current_price × (1 + slippage_pct/100)
2. SL and TP are anchored to the slipped fill_price, not current_price
3. Zero entry slippage when slippage_pct=0.0
"""
import sys, os, tempfile, sqlite3, types
import pytest
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
timing_mod.set_cycle_id = lambda *a: None
timing_mod.set_request_id = lambda *a: None
timing_mod.current_cycle_id = type("_CV", (), {"get": staticmethod(lambda: 0)})()
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


# ─────────────────────────────────────────────────────────────────────────────
# Per-pair tiered slippage tests (#204)
# ─────────────────────────────────────────────────────────────────────────────

def _make_broker_with_pair_cfg(pair: str, per_pair_slip_pct: float, global_slip: float = 0.05):
    """Create a PaperBroker with a single pair entry in config.trading.pairs."""
    import tempfile
    from src.storage.database import init_paper_db
    f = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    path = f.name
    f.close()
    init_paper_db(path, starting_balance=10_000.0)
    config = {
        "trading": {
            "stop_loss_pct": 5.0,
            "pairs": [{"pair": pair, "slippage_pct": per_pair_slip_pct}],
        },
        "trailing_stop": {"enabled": False},
        "breakeven_stop": {"enabled": False},
        "partial_take_profit": {"enabled": False},
    }
    return PaperBroker(paper_db=path, slippage_pct=global_slip, maker_fee_pct=0.0, config=config), path


class TestPerPairSlippage:
    """Tests for tiered per-pair slippage (#204)."""

    def test_get_pair_slippage_tier1_btc(self):
        """BTC/USD tier-1 config returns 0.05% as fraction 0.0005."""
        broker, _ = _make_broker_with_pair_cfg("BTC/USD", per_pair_slip_pct=0.05, global_slip=0.10)
        assert broker._get_pair_slippage("BTC/USD") == pytest.approx(0.0005)

    def test_get_pair_slippage_tier2_ada(self):
        """ADA/USD tier-2 config returns 0.10% as fraction 0.001."""
        broker, _ = _make_broker_with_pair_cfg("ADA/USD", per_pair_slip_pct=0.10, global_slip=0.05)
        assert broker._get_pair_slippage("ADA/USD") == pytest.approx(0.001)

    def test_get_pair_slippage_tier3_trx(self):
        """TRX/USD tier-3 config returns 0.20% as fraction 0.002."""
        broker, _ = _make_broker_with_pair_cfg("TRX/USD", per_pair_slip_pct=0.20, global_slip=0.05)
        assert broker._get_pair_slippage("TRX/USD") == pytest.approx(0.002)

    def test_get_pair_slippage_tier4_wif(self):
        """WIF/USD tier-4 config returns 0.40% as fraction 0.004."""
        broker, _ = _make_broker_with_pair_cfg("WIF/USD", per_pair_slip_pct=0.40, global_slip=0.05)
        assert broker._get_pair_slippage("WIF/USD") == pytest.approx(0.004)

    def test_get_pair_slippage_fallback_to_global(self):
        """Unknown pair without config entry falls back to global slippage."""
        broker, _ = _make_broker_with_pair_cfg("BTC/USD", per_pair_slip_pct=0.40, global_slip=0.07)
        # AVAX/USD is not in the pairs list → should fall back to global 0.07%
        assert broker._get_pair_slippage("AVAX/USD") == pytest.approx(0.0007)

    def test_place_order_fill_price_uses_per_pair_slippage(self):
        """place_order() fill price reflects per-pair slippage, not global."""
        broker, db = _make_broker_with_pair_cfg("WIF/USD", per_pair_slip_pct=0.40, global_slip=0.05)
        result = broker.place_order(
            pair="WIF/USD", side="buy",
            usd_amount=100.0, current_price=1000.0,
            stop_loss_pct=5.0, take_profit_pct=20.0,
        )
        pos = _get_position(db, result["position_id"])
        # 0.40% slip on top of $1000
        expected_fill = round(1000.0 * (1 + 0.004), 8)
        assert abs(pos["entry_price"] - expected_fill) < 1e-6, (
            f"entry_price should be {expected_fill} (0.40% slip), got {pos['entry_price']}"
        )

    def test_place_order_slippage_pct_in_result_reflects_per_pair(self):
        """Result dict slippage_pct value matches per-pair config, not global."""
        broker, _ = _make_broker_with_pair_cfg("WIF/USD", per_pair_slip_pct=0.40, global_slip=0.05)
        result = broker.place_order(
            pair="WIF/USD", side="buy",
            usd_amount=100.0, current_price=1000.0,
            stop_loss_pct=5.0, take_profit_pct=20.0,
        )
        assert result["slippage_pct"] == pytest.approx(0.40)

    def test_close_position_fill_price_uses_per_pair_slippage(self):
        """close_position() exit fill price reflects per-pair slippage."""
        broker, db = _make_broker_with_pair_cfg("WIF/USD", per_pair_slip_pct=0.40, global_slip=0.05)
        order = broker.place_order(
            pair="WIF/USD", side="buy",
            usd_amount=100.0, current_price=1000.0,
            stop_loss_pct=5.0, take_profit_pct=20.0,
        )
        exit_price = 1200.0
        result = broker.close_position(
            position_id=order["position_id"], exit_price=exit_price, exit_reason="take_profit"
        )
        # 0.40% exit slippage reduces fill below mid-price
        expected_fill = round(exit_price * (1 - 0.004), 8)
        assert abs(result["exit_price"] - expected_fill) < 1e-6, (
            f"exit fill should be {expected_fill} (0.40% slip), got {result['exit_price']}"
        )

    def test_meme_vs_large_cap_round_trip_cost(self):
        """Meme pair (0.40%) has higher round-trip cost than large-cap (0.05%)."""
        price = 1000.0
        amount = 500.0
        # Large-cap
        broker_btc, _ = _make_broker_with_pair_cfg("BTC/USD", per_pair_slip_pct=0.05, global_slip=0.05)
        btc_order = broker_btc.place_order(
            pair="BTC/USD", side="buy", usd_amount=amount,
            current_price=price, stop_loss_pct=5.0, take_profit_pct=8.0,
        )
        btc_exit = broker_btc.close_position(
            position_id=btc_order["position_id"], exit_price=price, exit_reason="agent_sell"
        )
        # Meme
        broker_wif, _ = _make_broker_with_pair_cfg("WIF/USD", per_pair_slip_pct=0.40, global_slip=0.05)
        wif_order = broker_wif.place_order(
            pair="WIF/USD", side="buy", usd_amount=amount,
            current_price=price, stop_loss_pct=5.0, take_profit_pct=20.0,
        )
        wif_exit = broker_wif.close_position(
            position_id=wif_order["position_id"], exit_price=price, exit_reason="agent_sell"
        )
        # Both at same price → WIF should have worse (more negative) P&L due to higher slippage
        assert wif_exit["pnl_usd"] < btc_exit["pnl_usd"], (
            f"Meme PnL {wif_exit['pnl_usd']} should be worse than large-cap {btc_exit['pnl_usd']}"
        )
