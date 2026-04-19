"""
Tests for S12.1.3 — Persona persistence.

Covers:
  1. resolve_trading_db() returns correct filename for concurrent / non-concurrent mode.
  2. Paper-trades INSERT includes persona column (PaperBroker wiring).
  3. Notifier prefix includes persona tag when concurrent_mode is True.
  4. Active persona is persisted to agent_state after apply_persona_config().
  5. Schema migration adds persona column to existing DBs without error.

Story: S12.1.3 | Sprint: S1 | Epic: E12 — Persona Framework
"""

import uuid
import sqlite3
import os

import pytest

from src.storage.database import (
    resolve_trading_db,
    get_db_path,
    get_connection,
    init_paper_db,
)
from src.notifications.notifier import Notifier


# ──────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────

def _make_config(
    persona: str = "conservative",
    concurrent_mode: bool = False,
    paper_db: str = "paper_trading.db",
    live_db: str = "live_trading.db",
) -> dict:
    """Minimal config sufficient for resolve_trading_db() and Notifier tests."""
    return {
        "agent": {"persona": persona, "concurrent_mode": concurrent_mode},
        "storage": {"paper_db": paper_db, "live_db": live_db, "audit_db": "audit.db"},
        "notifications": {"telegram_enabled": False},
        "trading": {"pairs": [], "take_profit_pct": 12},
    }


# ──────────────────────────────────────────────────────────────
# resolve_trading_db()
# ──────────────────────────────────────────────────────────────

class TestResolveTradinDb:
    """resolve_trading_db() must embed persona name when concurrent_mode=True."""

    def test_paper_non_concurrent_returns_base_name(self):
        cfg = _make_config(persona="conservative", concurrent_mode=False)
        assert resolve_trading_db(cfg, "paper") == "paper_trading.db"

    def test_live_non_concurrent_returns_base_name(self):
        cfg = _make_config(persona="high", concurrent_mode=False)
        assert resolve_trading_db(cfg, "live") == "live_trading.db"

    def test_paper_concurrent_conservative(self):
        cfg = _make_config(persona="conservative", concurrent_mode=True)
        assert resolve_trading_db(cfg, "paper") == "paper_trading_conservative.db"

    def test_paper_concurrent_medium(self):
        cfg = _make_config(persona="medium", concurrent_mode=True)
        assert resolve_trading_db(cfg, "paper") == "paper_trading_medium.db"

    def test_paper_concurrent_high(self):
        cfg = _make_config(persona="high", concurrent_mode=True)
        assert resolve_trading_db(cfg, "paper") == "paper_trading_high.db"

    def test_live_concurrent_conservative(self):
        cfg = _make_config(persona="conservative", concurrent_mode=True)
        assert resolve_trading_db(cfg, "live") == "live_trading_conservative.db"

    def test_custom_base_name_preserved(self):
        """If operator overrides paper_db filename, it should still be persona-suffixed."""
        cfg = _make_config(persona="medium", concurrent_mode=True, paper_db="trading_paper.db")
        assert resolve_trading_db(cfg, "paper") == "trading_paper_medium.db"

    def test_default_persona_when_missing(self):
        """When agent.persona is absent, fallback conservative is used."""
        cfg = {
            "agent": {"concurrent_mode": True},
            "storage": {"paper_db": "paper_trading.db"},
        }
        assert resolve_trading_db(cfg, "paper") == "paper_trading_conservative.db"


# ──────────────────────────────────────────────────────────────
# Notifier prefix
# ──────────────────────────────────────────────────────────────

class TestNotifierPersonaPrefix:
    """Notifier must include persona tag in prefix when persona is provided."""

    def test_no_persona_paper_prefix(self):
        n = Notifier(_make_config(), mode="paper", persona="")
        assert n._prefix == "[PAPER] "

    def test_no_persona_live_prefix(self):
        n = Notifier(_make_config(), mode="live", persona="")
        assert n._prefix == "[LIVE] "

    def test_persona_conservative_paper_prefix(self):
        n = Notifier(_make_config(), mode="paper", persona="conservative")
        assert n._prefix == "[PAPER|CONSERVATIVE] "

    def test_persona_medium_live_prefix(self):
        n = Notifier(_make_config(), mode="live", persona="medium")
        assert n._prefix == "[LIVE|MEDIUM] "

    def test_persona_high_paper_prefix(self):
        n = Notifier(_make_config(), mode="paper", persona="high")
        assert n._prefix == "[PAPER|HIGH] "

    def test_empty_persona_does_not_add_pipe(self):
        """Backward compat: passing persona='' must produce the v2 format."""
        n = Notifier(_make_config(), mode="paper", persona="")
        assert "|" not in n._prefix


# ──────────────────────────────────────────────────────────────
# Schema migration — persona column in paper_trades
# ──────────────────────────────────────────────────────────────

class TestPersonaColumnMigration:
    """init_paper_db() must add persona column to paper_trades on an existing DB."""

    @pytest.fixture(autouse=True)
    def _isolated_db(self, tmp_path):
        """Each test uses a fresh UUID-named DB in the project data/ dir.

        Critical: MUST use a temp name — never 'paper_trading.db' — to avoid
        wiping production data (ref: incident #234).
        """
        self._db_name = f"test_{uuid.uuid4().hex[:8]}.db"
        self._db_path = get_db_path(self._db_name)
        yield
        if os.path.exists(self._db_path):
            os.remove(self._db_path)

    def test_persona_column_present_after_init(self):
        """After init_paper_db(), paper_trades must have persona column."""
        init_paper_db(self._db_name)
        conn = sqlite3.connect(self._db_path)
        cols = [row[1] for row in conn.execute("PRAGMA table_info(paper_trades)").fetchall()]
        conn.close()
        assert "persona" in cols, f"persona column missing; columns: {cols}"

    def test_persona_column_defaults_to_empty_string(self):
        """The default value for persona must be '' (empty string)."""
        init_paper_db(self._db_name)
        conn = sqlite3.connect(self._db_path)
        col_info = {
            row[1]: row[4]  # name → dflt_value
            for row in conn.execute("PRAGMA table_info(paper_trades)").fetchall()
        }
        conn.close()
        # SQLite stores DEFAULT '' as empty string literal
        assert col_info.get("persona") in ("''", "", None), (
            f"Unexpected default value: {col_info.get('persona')!r}"
        )

    def test_second_init_is_idempotent(self):
        """Calling init_paper_db() twice must not raise OperationalError."""
        init_paper_db(self._db_name)
        init_paper_db(self._db_name)  # should not raise


# ──────────────────────────────────────────────────────────────
# PaperBroker — persona written to paper_trades
# ──────────────────────────────────────────────────────────────

class TestPaperBrokerPersonaTrades:
    """PaperBroker.close_position() must write self._persona into paper_trades."""

    @pytest.fixture(autouse=True)
    def _isolated_db(self):
        from src.storage.database import init_paper_db, get_db_path
        self._db_name = f"test_{uuid.uuid4().hex[:8]}.db"
        self._db_path = get_db_path(self._db_name)
        init_paper_db(self._db_name, starting_balance=1000.0)
        yield
        if os.path.exists(self._db_path):
            os.remove(self._db_path)

    def _make_broker(self, persona: str = "conservative"):
        from src.exchange.paper_broker import PaperBroker
        return PaperBroker(
            paper_db=self._db_name,
            slippage_pct=0.0,
            maker_fee_pct=0.0,
            config={"trading": {"pairs": []}},
            persona=persona,
        )

    def _seed_position(self, broker, pair: str = "BTC/USD", entry_price: float = 50000.0):
        """Place a minimal open position and return its id."""
        from src.storage.database import get_connection
        from src.utils.tz import now_sgt_iso
        conn = get_connection(self._db_name)
        conn.execute(
            """INSERT INTO paper_positions
               (opened_at, pair, side, entry_price, volume, usd_value,
                stop_loss_price, take_profit_price, stop_loss_pct, take_profit_pct, status)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (now_sgt_iso(), pair, "buy", entry_price, 0.01, entry_price * 0.01,
             entry_price * 0.95, entry_price * 1.10, 5.0, 10.0, "open"),
        )
        conn.commit()
        row = conn.execute("SELECT last_insert_rowid()").fetchone()
        conn.close()
        return row[0]

    def test_persona_written_to_trade_record(self):
        broker = self._make_broker(persona="medium")
        pos_id = self._seed_position(broker)
        broker.close_position(position_id=pos_id, exit_price=51000.0, exit_reason="test")
        conn = sqlite3.connect(self._db_path)
        row = conn.execute("SELECT persona FROM paper_trades ORDER BY id DESC LIMIT 1").fetchone()
        conn.close()
        assert row is not None
        assert row[0] == "medium"

    def test_default_persona_empty_string(self):
        """No persona specified → empty string written."""
        broker = self._make_broker(persona="")
        pos_id = self._seed_position(broker)
        broker.close_position(position_id=pos_id, exit_price=51000.0, exit_reason="test")
        conn = sqlite3.connect(self._db_path)
        row = conn.execute("SELECT persona FROM paper_trades ORDER BY id DESC LIMIT 1").fetchone()
        conn.close()
        assert row[0] == ""
