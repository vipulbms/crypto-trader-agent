"""
Tests for #178 — SOD balance DB-persisted in live mode; midnight rollover.

1. agent_state table is created by init_live_db (LIVE_SCHEMA + migration)
2. _get_or_set_sod_balance() writes SOD balance with live_trading.db
3. _get_or_set_sod_balance() returns stored value on subsequent calls (stable)
4. _get_or_set_sod_balance() detects midnight rollover and writes new SOD key
5. _get_or_set_sod_balance() falls back gracefully when DB unavailable
"""
import os
import sys
import tempfile
import sqlite3
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.storage.database import init_live_db, init_paper_db, get_connection


# ── helpers ──────────────────────────────────────────────────────────────────

def _fresh_live_db() -> str:
    """Return path to a freshly initialised live_trading DB (in-memory via temp file)."""
    f = tempfile.NamedTemporaryFile(suffix=".db", delete=False, prefix="live_trading_")
    path = os.path.basename(f.name)
    f.close()
    # init_live_db writes to data/<filename> — we need a name without path separators
    # Use a short random name that resolves under data/
    import uuid
    name = f"test_live_{uuid.uuid4().hex[:8]}.db"
    init_live_db(name)
    return name


def _fresh_paper_db() -> str:
    """Return path to a freshly initialised paper_trading DB."""
    import uuid
    name = f"test_paper_{uuid.uuid4().hex[:8]}.db"
    init_paper_db(name, starting_balance=1000.0)
    return name


def _get_sod_balance(db_path: str, current_balance: float, utc_date_str: str) -> float:
    """
    Invoke _get_or_set_sod_balance as if it is the given UTC date (mocked).
    Returns only the float portion (strips the is_new_day bool).
    """
    import main as main_module

    fake_now = datetime.strptime(utc_date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)

    class _FakeDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return fake_now

    with patch("main.datetime", _FakeDatetime):
        balance, _ = main_module._get_or_set_sod_balance(db_path, current_balance)
        return balance


def _read_agent_state(db_path: str, key: str):
    """Read a single value from agent_state directly."""
    conn = get_connection(db_path)
    row = conn.execute("SELECT value FROM agent_state WHERE key=?", (key,)).fetchone()
    conn.close()
    return row["value"] if row else None


# ── tests ─────────────────────────────────────────────────────────────────────


class TestAgentStateTableExists:

    def test_agent_state_in_live_db_schema(self):
        """init_live_db creates agent_state table in live_trading.db."""
        db = _fresh_live_db()
        conn = get_connection(db)
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()]
        conn.close()
        assert "agent_state" in tables, f"agent_state missing from live DB; tables={tables}"

    def test_agent_state_in_paper_db_schema(self):
        """init_paper_db creates agent_state table in paper_trading.db."""
        db = _fresh_paper_db()
        conn = get_connection(db)
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()]
        conn.close()
        assert "agent_state" in tables, f"agent_state missing from paper DB; tables={tables}"

    def test_agent_state_migration_idempotent(self):
        """Calling init_live_db twice does not raise an error (CREATE IF NOT EXISTS)."""
        db = _fresh_live_db()
        init_live_db(db)  # second call — must not raise
        conn = get_connection(db)
        count = conn.execute("SELECT COUNT(*) FROM agent_state").fetchone()[0]
        conn.close()
        assert count == 0  # empty table, no crash


class TestSodBalanceLiveMode:

    def test_live_mode_writes_sod_on_first_call(self):
        """
        First call for a given UTC date writes current_balance to agent_state
        and returns it.
        """
        db = _fresh_live_db()
        result = _get_sod_balance(db, 5000.0, "2026-04-11")
        assert result == 5000.0
        stored = _read_agent_state(db, "start_of_day_balance_2026-04-11")
        assert stored == "5000.0"

    def test_live_mode_returns_stored_value_on_second_call(self):
        """
        Subsequent calls within the same UTC day return the original stored value,
        ignoring the current_balance argument (stable SOD baseline).
        """
        db = _fresh_live_db()
        _get_sod_balance(db, 5000.0, "2026-04-11")
        # Balance changed during the day
        result = _get_sod_balance(db, 4800.0, "2026-04-11")
        assert result == 5000.0, "SOD should remain pinned to first call's value"

    def test_live_mode_midnight_rollover_writes_new_key(self):
        """
        After UTC midnight, a new key is written for the new day and the
        current balance (= yesterday's close) becomes the new SOD baseline.
        """
        db = _fresh_live_db()
        # Day 1: write SOD
        day1 = _get_sod_balance(db, 5000.0, "2026-04-11")
        assert day1 == 5000.0
        # Day 2: new key written with new balance
        day2 = _get_sod_balance(db, 5200.0, "2026-04-12")
        assert day2 == 5200.0
        # Both keys exist independently
        assert _read_agent_state(db, "start_of_day_balance_2026-04-11") == "5000.0"
        assert _read_agent_state(db, "start_of_day_balance_2026-04-12") == "5200.0"

    def test_live_mode_fallback_when_db_unavailable(self):
        """
        If the DB call fails (e.g. DB missing or corrupt) the function falls
        back to returning current_balance — no exception propagated.
        """
        import main as main_module
        balance, is_new_day = main_module._get_or_set_sod_balance("nonexistent_live.db", 9999.99)
        assert balance == 9999.99
        assert is_new_day is False


class TestSodBalancePaperMode:

    def test_paper_mode_stable_across_cycles(self):
        """Paper mode behaves identically — SOD stays pinned within a UTC day."""
        db = _fresh_paper_db()
        _get_sod_balance(db, 1000.0, "2026-04-11")
        result = _get_sod_balance(db, 1100.0, "2026-04-11")
        assert result == 1000.0

    def test_paper_mode_midnight_rollover(self):
        """Paper mode midnight rollover writes next-day key."""
        db = _fresh_paper_db()
        _get_sod_balance(db, 1000.0, "2026-04-11")
        result = _get_sod_balance(db, 1050.0, "2026-04-12")
        assert result == 1050.0
        assert _read_agent_state(db, "start_of_day_balance_2026-04-12") == "1050.0"
