"""
Tests for trailing_stop vs stop_loss exit_reason labelling (GH#123).
"""
import sys, os, sqlite3, tempfile, types
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# ── stub notifier so paper_broker imports cleanly ──────────────────────────
notifier_mod = types.ModuleType("src.notifications.notifier")
class _Notifier:
    def send_trade_executed(self, *a, **kw): pass
notifier_mod.Notifier = _Notifier
sys.modules.setdefault("src.notifications.notifier", notifier_mod)
sys.modules.setdefault("src.notifications", types.ModuleType("src.notifications"))

timing_mod = types.ModuleType("src.utils.timing")
def _timed(*a, **kw):
    def _dec(fn): return fn
    return _dec
timing_mod.timed = _timed
sys.modules.setdefault("src.utils.timing", timing_mod)

from src.exchange.paper_broker import PaperBroker
from src.storage.database import init_paper_db


# ── helpers ────────────────────────────────────────────────────────────────

def _make_broker(trail_pct=5.0, activate_pct=3.0, trailing_enabled=True) -> tuple:
    """Return (broker, db_path) with a fresh paper DB."""
    f = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    db_path = f.name
    f.close()
    init_paper_db(db_path, starting_balance=10000.0)
    config = {
        "trading": {"stop_loss_pct": 5.0},
        "paper": {"slippage_pct": 0.0, "fee_pct": 0.0},
        "trailing_stop": {
            "enabled": trailing_enabled,
            "trail_pct": trail_pct,
            "activate_after_pct": activate_pct,
            "per_pair_overrides": {},
        },
        "breakeven_stop": {"enabled": False},
        "partial_take_profit": {"enabled": False},
    }
    return PaperBroker(paper_db=db_path, config=config), db_path


def _buy(broker: PaperBroker, pair="TEST/USD", price=100.0, tp_pct=20.0):
    broker.place_order(
        pair=pair,
        side="buy",
        usd_amount=1000.0,
        current_price=price,
        stop_loss_pct=5.0,
        take_profit_pct=tp_pct,
    )


# ── tests ──────────────────────────────────────────────────────────────────

def test_hard_stop_loss_when_trailing_not_activated():
    """
    Given trailing stop is enabled but price never rose enough to activate it
    When price drops to the original hard SL
    Then exit_reason is 'stop_loss' (not 'trailing_stop')
    """
    broker, _ = _make_broker()
    _buy(broker, price=100.0)

    # price drops straight to hard SL (never rose >= 3% activate threshold)
    closed = broker.check_stops_and_tp("TEST/USD", current_price=94.0)
    assert len(closed) == 1
    assert closed[0]["exit_reason"] == "stop_loss"


def test_trailing_stop_label_when_sl_was_raised():
    """
    Given trailing stop is enabled and price rose enough to raise the SL
    When the raised trailing SL is hit on a pullback
    Then exit_reason is 'trailing_stop' (not 'stop_loss')
    """
    broker, _ = _make_broker(trail_pct=5.0, activate_pct=3.0)
    _buy(broker, price=100.0, tp_pct=30.0)

    # First tick: price rises to 115 → trailing activates, SL raised to ~109.25
    broker.check_stops_and_tp("TEST/USD", current_price=115.0)
    # Second tick: price drops to 109 → hits raised trailing SL
    closed = broker.check_stops_and_tp("TEST/USD", current_price=109.0)
    assert len(closed) == 1
    assert closed[0]["exit_reason"] == "trailing_stop"


def test_trailing_stop_is_profitable():
    """
    Given trailing stop fires after SL was raised above entry
    When the trade closes
    Then pnl_pct is positive (trade was a gain)
    """
    broker, _ = _make_broker(trail_pct=5.0, activate_pct=3.0)
    _buy(broker, price=100.0, tp_pct=30.0)

    broker.check_stops_and_tp("TEST/USD", current_price=115.0)  # raises SL
    closed = broker.check_stops_and_tp("TEST/USD", current_price=109.0)
    assert len(closed) == 1
    assert closed[0]["exit_reason"] == "trailing_stop"
    assert closed[0]["pnl_pct"] > 0


def test_no_trailing_stop_label_when_trailing_disabled():
    """
    Given trailing stop is disabled
    When the SL price is hit
    Then exit_reason is 'stop_loss'
    """
    broker, _ = _make_broker(trailing_enabled=False)
    _buy(broker, price=100.0)

    closed = broker.check_stops_and_tp("TEST/USD", current_price=94.0)
    assert len(closed) == 1
    assert closed[0]["exit_reason"] == "stop_loss"


def test_circuit_breaker_excludes_trailing_stop():
    """
    Given the last N trades are all 'trailing_stop' exits (profitable trailing stops)
    When is_circuit_open() is called
    Then the circuit breaker does NOT trip
    """
    import time, datetime
    from src.risk.risk_manager import RiskManager

    f = tempfile.NamedTemporaryFile(suffix="_paper_trading.db", delete=False)
    db_path = f.name
    f.close()
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE paper_trades (
            id INTEGER PRIMARY KEY, exit_reason TEXT,
            closed_at TEXT, opened_at TEXT, side TEXT,
            pair TEXT, entry_price REAL, exit_price REAL, volume REAL,
            usd_invested REAL, pnl_usd REAL, pnl_pct REAL,
            hold_duration_secs REAL, fee_usd REAL,
            stop_loss_pct REAL, take_profit_pct REAL
        )
    """)
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    conn.executemany(
        "INSERT INTO paper_trades (exit_reason, closed_at) VALUES (?,?)",
        [("trailing_stop", now), ("trailing_stop", now), ("trailing_stop", now)]
    )
    conn.commit()
    conn.close()

    config = {
        "trading": {"stop_loss_pct": 5.0},
        "risk": {
            "max_position_pct": 30,
            "max_open_positions": 5,
            "min_cash_reserve_pct": 10,
            "daily_loss_limit_pct": 10,
            "circuit_breaker": {"enabled": True, "consecutive_stops": 3, "pause_hours": 4},
        },
        "position_sizing": {"base_position_pct": 20, "max_position_pct": 30},
    }
    rm = RiskManager(config=config, db_path=db_path)
    tripped, _ = rm.is_circuit_open()
    assert not tripped, "Circuit breaker must not trip on trailing_stop exits"


def test_circuit_breaker_trips_on_hard_stop_losses():
    """
    Given the last 3 trades are all 'stop_loss' exits
    When is_circuit_open() is called
    Then the circuit breaker DOES trip
    """
    import datetime
    from src.risk.risk_manager import RiskManager

    f = tempfile.NamedTemporaryFile(suffix="_paper_trading.db", delete=False)
    db_path = f.name
    f.close()
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE paper_trades (
            id INTEGER PRIMARY KEY, exit_reason TEXT, closed_at TEXT,
            opened_at TEXT, side TEXT, pair TEXT, entry_price REAL,
            exit_price REAL, volume REAL, usd_invested REAL, pnl_usd REAL,
            pnl_pct REAL, hold_duration_secs REAL, fee_usd REAL,
            stop_loss_pct REAL, take_profit_pct REAL
        )
    """)
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    conn.executemany(
        "INSERT INTO paper_trades (exit_reason, closed_at) VALUES (?,?)",
        [("stop_loss", now), ("stop_loss", now), ("stop_loss", now)]
    )
    conn.commit()
    conn.close()

    config = {
        "trading": {"stop_loss_pct": 5.0},
        "risk": {
            "max_position_pct": 30,
            "max_open_positions": 5,
            "min_cash_reserve_pct": 10,
            "daily_loss_limit_pct": 10,
            "circuit_breaker": {"enabled": True, "consecutive_stops": 3, "pause_hours": 4},
        },
        "position_sizing": {"base_position_pct": 20, "max_position_pct": 30},
    }
    rm = RiskManager(config=config, db_path=db_path)
    tripped, _ = rm.is_circuit_open()
    assert tripped, "Circuit breaker must trip on 3 consecutive stop_loss exits"


if __name__ == "__main__":
    test_hard_stop_loss_when_trailing_not_activated()
    print("PASS: hard_stop_loss_when_trailing_not_activated")
    test_trailing_stop_label_when_sl_was_raised()
    print("PASS: trailing_stop_label_when_sl_was_raised")
    test_trailing_stop_is_profitable()
    print("PASS: trailing_stop_is_profitable")
    test_no_trailing_stop_label_when_trailing_disabled()
    print("PASS: no_trailing_stop_label_when_trailing_disabled")
    test_circuit_breaker_excludes_trailing_stop()
    print("PASS: circuit_breaker_excludes_trailing_stop")
    test_circuit_breaker_trips_on_hard_stop_losses()
    print("PASS: circuit_breaker_trips_on_hard_stop_losses")
    print("\nAll 6 tests passed.")
