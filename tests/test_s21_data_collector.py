"""
Test suite for Sprint S4 — S21.1.2 (DataCollector feed freeze detection).

Tests:
  - Five identical closes → _detect_feed_status = "frozen"
  - Stale timestamp (> 5 intervals) → "stale"
  - Normal variance and fresh timestamp → "ok"
  - Fewer than N candles → "ok" (not enough data)
  - /feed_status JSON response structure

pytest: python -m pytest tests/test_s21_data_collector.py -v
"""
from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
import time
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.runtime.data_collector import DataCollector
from src.storage.database import get_connection


# ──────────────────────────────────────────────────────────────
# Helpers / fixtures
# ──────────────────────────────────────────────────────────────

def _minimal_config(candle_interval: int = 30) -> dict:
    return {
        "trading": {
            "pairs": [
                {"pair": "BTC/USD", "ws_name": "BTC/USD"},
            ],
        },
        "indicators": {
            "candle_interval": candle_interval,
        },
        "qsa": {
            "feed_heartbeat": {
                "enabled": True,
                "variance_lookback": 5,
            },
        },
    }


def _make_collector_with_db(config: dict | None = None) -> tuple[DataCollector, str]:
    """Create a DataCollector backed by an isolated temp DB."""
    tmp = tempfile.mkdtemp()
    db_path = os.path.join(tmp, f"test_dc_{uuid.uuid4().hex[:8]}.db")
    cfg = config or _minimal_config()
    # Ensure candle_buffer table exists
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS candle_buffer (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pair TEXT NOT NULL,
            ts INTEGER NOT NULL,
            open_price REAL,
            high REAL,
            low REAL,
            close REAL,
            volume REAL,
            is_closed INTEGER DEFAULT 1,
            inserted_at TEXT,
            UNIQUE(pair, ts)
        )
        """
    )
    conn.commit()
    conn.close()
    dc = DataCollector(cfg, db_path=db_path)
    return dc, db_path


def _insert_candles(db_path: str, pair: str, closes: list[float], base_ts: int = None) -> None:
    """Insert closed candles with specified close prices, spaced 30 min apart."""
    if base_ts is None:
        base_ts = int(time.time()) - len(closes) * 1800
    conn = sqlite3.connect(db_path)
    for i, close in enumerate(closes):
        ts = base_ts + i * 1800
        conn.execute(
            "INSERT OR REPLACE INTO candle_buffer (pair, ts, open_price, high, low, close, volume, is_closed, inserted_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 1, datetime('now'))",
            (pair, ts, close, close * 1.001, close * 0.999, close, 100.0),
        )
    conn.commit()
    conn.close()


# ──────────────────────────────────────────────────────────────
# _detect_feed_status tests
# ──────────────────────────────────────────────────────────────

class TestDetectFeedStatus:
    """AC1–AC5 for S21.1.2"""

    def test_five_identical_closes_returns_frozen(self):
        """AC1: five identical close prices → 'frozen'."""
        dc, db = _make_collector_with_db()
        _insert_candles(db, "BTC/USD", [50000.0, 50000.0, 50000.0, 50000.0, 50000.0])
        status = dc._detect_feed_status("BTC/USD")
        assert status == "frozen"

    def test_normal_variance_returns_ok(self):
        """AC2: varying closes → 'ok'."""
        dc, db = _make_collector_with_db()
        _insert_candles(db, "BTC/USD", [50000.0, 50100.0, 49900.0, 50050.0, 49950.0])
        # Timestamp is recent (base_ts = now - 5*1800), last candle within the stale threshold
        status = dc._detect_feed_status("BTC/USD")
        assert status == "ok"

    def test_stale_timestamp_returns_stale(self):
        """AC3: last candle timestamp older than 5 × interval → 'stale'."""
        cfg = _minimal_config(candle_interval=30)  # 30-min candles
        dc, db = _make_collector_with_db(cfg)
        # Place 5 unique closes but all timestamps far in the past
        stale_base_ts = int(time.time()) - 20 * 1800  # 20 intervals ago (latest candle ~16 intervals old)
        _insert_candles(db, "BTC/USD",
                        [50000.0, 50100.0, 49900.0, 50050.0, 49950.0],
                        base_ts=stale_base_ts)
        status = dc._detect_feed_status("BTC/USD")
        assert status == "stale"

    def test_fewer_than_n_candles_returns_ok(self):
        """AC4: fewer than variance_lookback candles → not enough data → 'ok'."""
        dc, db = _make_collector_with_db()
        _insert_candles(db, "BTC/USD", [50000.0, 50100.0])  # only 2 candles
        status = dc._detect_feed_status("BTC/USD")
        assert status == "ok"  # not frozen; insufficient history

    def test_unknown_pair_returns_ok(self):
        """AC5: pair not in DB → 'ok' (no crash)."""
        dc, db = _make_collector_with_db()
        status = dc._detect_feed_status("UNKNOWN/USD")
        assert status == "ok"

    def test_four_identical_one_different_not_frozen(self):
        """AC6: four identical + one different → variance > 0 → not 'frozen'."""
        dc, db = _make_collector_with_db()
        _insert_candles(db, "BTC/USD", [50000.0, 50000.0, 50000.0, 50000.0, 50001.0])
        status = dc._detect_feed_status("BTC/USD")
        assert status != "frozen"

    def test_frozen_takes_priority_over_stale(self):
        """AC7: all identical AND stale → reported as 'frozen' (zero variance check first)."""
        dc, db = _make_collector_with_db()
        stale_base_ts = int(time.time()) - 8 * 1800
        _insert_candles(db, "BTC/USD",
                        [50000.0, 50000.0, 50000.0, 50000.0, 50000.0],
                        base_ts=stale_base_ts)
        status = dc._detect_feed_status("BTC/USD")
        assert status == "frozen"


# ──────────────────────────────────────────────────────────────
# _refresh_feed_statuses tests
# ──────────────────────────────────────────────────────────────

class TestRefreshFeedStatuses:
    def test_refresh_returns_dict_keyed_by_pair(self):
        """AC8: _refresh_feed_statuses returns {pair: status} for all tracked pairs."""
        dc, db = _make_collector_with_db()
        _insert_candles(db, "BTC/USD", [50000.0, 50100.0, 49900.0, 50050.0, 49950.0])
        statuses = dc._refresh_feed_statuses()
        assert "BTC/USD" in statuses
        assert statuses["BTC/USD"] in ("ok", "stale", "frozen")

    def test_refresh_updates_cache(self):
        """AC9: after _refresh_feed_statuses, _feed_status_cache is populated."""
        dc, db = _make_collector_with_db()
        _insert_candles(db, "BTC/USD", [50000.0, 50000.0, 50000.0, 50000.0, 50000.0])
        dc._refresh_feed_statuses()
        assert dc._feed_status_cache.get("BTC/USD") == "frozen"
