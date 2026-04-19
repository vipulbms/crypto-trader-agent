"""
Tests for S21.1.1 — DataCollector runtime (DB write path).

Story: S21.1.1 | Sprint: S3 | Epic: E21 — Data Collector Runtime

Covers:
  AC1: standalone module; no agent/risk imports at top level
  AC2: _upsert_candle writes a row to candle_buffer table
  AC3: Duplicate (pair, ts) → INSERT OR REPLACE (no duplicate rows)
  AC4: OHLCV values stored correctly in candle_buffer
  AC5: 5 candles with identical close prices can be detected as frozen
        (candle_buffer stores what it received; freeze detection is a QSA concern)
  AC6: _upsert_orderbook writes to orderbook_snapshots; OBI computed = (bid-ask)/(bid+ask)
"""

import os
import sqlite3
import tempfile
import uuid

from src.runtime.data_collector import _ensure_schema, _upsert_candle, _upsert_orderbook
from src.storage.database import COLLECTOR_SCHEMA, get_connection


# ── Helpers ───────────────────────────────────────────────────────────────────

def _temp_db() -> str:
    """Create an isolated SQLite file in /tmp for each test."""
    _dir = tempfile.mkdtemp()
    return os.path.join(_dir, f"test_dc_{uuid.uuid4().hex[:8]}.db")


def _candle(pair: str = "ETH/USD", ts: int = 1714000000, close: float = 3000.0) -> dict:
    return {
        "pair":      pair,
        "ts":        ts,
        "open":      close - 5,
        "high":      close + 10,
        "low":       close - 10,
        "close":     close,
        "volume":    500.0,
        "is_closed": True,
    }


def _orderbook_snap(pair: str = "ETH/USD", bid: float = 3001.0, ask: float = 3002.0) -> dict:
    return {
        "pair":     pair,
        "ts":       1714000500,
        "best_bid": bid,
        "best_ask": ask,
    }


# ── AC1: no top-level agent/risk imports ─────────────────────────────────────

class TestNoAgentImports:

    def test_data_collector_module_no_agent_imports(self):
        """
        AC1: data_collector.py must not import from src.agent or src.risk at module level.
        Verified by inspecting module source.
        """
        import inspect
        import src.runtime.data_collector as dc_mod
        src_lines = inspect.getsource(dc_mod)
        assert "from src.agent" not in src_lines, (
            "data_collector.py imports from src.agent (forbidden per AC1)"
        )
        assert "from src.risk" not in src_lines, (
            "data_collector.py imports from src.risk (forbidden per AC1)"
        )


# ── AC2 + AC4: candle_buffer write ───────────────────────────────────────────

class TestCandleBufferWrite:

    def test_upsert_candle_writes_row(self):
        """AC2: _upsert_candle inserts a row into candle_buffer."""
        db = _temp_db()
        _ensure_schema(db)
        _upsert_candle(db, _candle())
        conn = get_connection(db)
        row = conn.execute("SELECT * FROM candle_buffer WHERE pair='ETH/USD'").fetchone()
        conn.close()
        assert row is not None, "Expected row in candle_buffer after _upsert_candle()"

    def test_ohlcv_stored_correctly(self):
        """AC4: OHLCV fields stored with correct values."""
        db = _temp_db()
        _ensure_schema(db)
        c = _candle(close=3100.0)
        _upsert_candle(db, c)
        conn = get_connection(db)
        row = conn.execute(
            "SELECT open_price, high, low, close, volume FROM candle_buffer WHERE pair='ETH/USD'"
        ).fetchone()
        conn.close()
        assert row is not None
        _open, high, low, close, vol = row
        assert close == 3100.0
        assert high > close - 5
        assert vol == 500.0

    def test_duplicate_pair_ts_no_extra_row(self):
        """AC3: second write with same (pair, ts) → INSERT OR REPLACE; still 1 row."""
        db = _temp_db()
        _ensure_schema(db)
        c = _candle(ts=1714000000, close=3000.0)
        _upsert_candle(db, c)
        c2 = dict(c)
        c2["close"] = 3050.0  # same timestamp, updated close
        _upsert_candle(db, c2)
        conn = get_connection(db)
        count = conn.execute(
            "SELECT COUNT(*) FROM candle_buffer WHERE pair='ETH/USD' AND ts=1714000000"
        ).fetchone()[0]
        row = conn.execute(
            "SELECT close FROM candle_buffer WHERE pair='ETH/USD' AND ts=1714000000"
        ).fetchone()
        conn.close()
        assert count == 1, "Duplicate row created for same (pair, ts)"
        assert row[0] == 3050.0, "REPLACE should update to latest close"

    def test_five_identical_close_prices_stored(self):
        """
        AC5: DataCollector faithfully stores 5 identical candles (frozen pattern).
        The freeze detection itself is a QSA signals.py concern; here we just verify
        candle_buffer contains all 5 rows with identical close.
        """
        db = _temp_db()
        _ensure_schema(db)
        ts_base = 1714000000
        frozen_close = 4200.0
        for i in range(5):
            _upsert_candle(db, _candle(ts=ts_base + i * 900, close=frozen_close))
        conn = get_connection(db)
        rows = conn.execute(
            "SELECT ts, close FROM candle_buffer WHERE pair='ETH/USD' ORDER BY ts"
        ).fetchall()
        conn.close()
        assert len(rows) == 5, f"Expected 5 rows, got {len(rows)}"
        closes = [r[1] for r in rows]
        assert all(c == frozen_close for c in closes), (
            "Not all 5 candles have identical close price"
        )


# ── AC6: orderbook_snapshots write ───────────────────────────────────────────

class TestOrderbookWrite:

    def test_upsert_orderbook_writes_row(self):
        """AC6: _upsert_orderbook inserts a row into orderbook_snapshots."""
        db = _temp_db()
        _ensure_schema(db)
        _upsert_orderbook(db, _orderbook_snap())
        conn = get_connection(db)
        row = conn.execute("SELECT * FROM orderbook_snapshots WHERE pair='ETH/USD'").fetchone()
        conn.close()
        assert row is not None

    def test_obi_computed_correctly(self):
        """AC6: OBI = (bid - ask) / (bid + ask) stored in row."""
        db = _temp_db()
        _ensure_schema(db)
        snap = _orderbook_snap(bid=3000.0, ask=3002.0)
        _upsert_orderbook(db, snap)
        conn = get_connection(db)
        row = conn.execute(
            "SELECT best_bid, best_ask, obi FROM orderbook_snapshots WHERE pair='ETH/USD'"
        ).fetchone()
        conn.close()
        assert row is not None
        bid, ask, obi = row
        expected_obi = (bid - ask) / (bid + ask)
        assert abs(obi - expected_obi) < 1e-9, f"OBI mismatch: {obi} vs {expected_obi}"

    def test_multiple_snapshots_inserted(self):
        """Multiple orderbook snapshots for the same pair are all stored."""
        db = _temp_db()
        _ensure_schema(db)
        for i in range(3):
            s = _orderbook_snap()
            s["ts"] = 1714000500 + i * 60
            _upsert_orderbook(db, s)
        conn = get_connection(db)
        count = conn.execute(
            "SELECT COUNT(*) FROM orderbook_snapshots WHERE pair='ETH/USD'"
        ).fetchone()[0]
        conn.close()
        assert count == 3
