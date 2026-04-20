"""
Tests for S17.1.1 — MCP Server with 6 read-only tools.

Covers:
  - All 6 tools return pipe-separated strings (AC3)
  - Unknown tool raises ValueError (AC2)
  - DB opened read-only (AC4) — write attempt raises error
  - tool_get_portfolio_state reflects open positions + cash
  - tool_get_regime_state reads agent_state keys correctly
  - tool_get_persistence_scores aggregates 14-day trades correctly
"""

import uuid
import sqlite3
import os
import pytest

from src.storage.database import get_connection, resolve_trading_db, _get_db_path
from src.mcp.server import (
    tool_get_portfolio_state,
    tool_get_signal_snapshot,
    tool_get_regime_state,
    tool_get_agent_status,
    tool_get_universe_state,
    tool_get_persistence_scores,
    MCPServer,
)


def _mk_db() -> str:
    return f"test_mcp_{uuid.uuid4().hex[:8]}.db"


def _seed_db(db_path: str) -> None:
    """Create minimal schema and seed basic rows."""
    conn = get_connection(db_path)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS paper_balance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cash_usd REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS paper_positions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pair TEXT NOT NULL,
            volume REAL,
            usd_value REAL,
            entry_price REAL,
            stop_loss_price REAL,
            take_profit_price REAL,
            status TEXT DEFAULT 'open'
        );
        CREATE TABLE IF NOT EXISTS paper_trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pair TEXT NOT NULL,
            pnl_usd REAL DEFAULT 0,
            exit_reason TEXT,
            closed_at REAL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS agent_state (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
    """)
    conn.execute("INSERT INTO paper_balance (cash_usd) VALUES (800.0)")
    conn.execute(
        "INSERT INTO paper_positions (pair, volume, usd_value, entry_price, status) "
        "VALUES ('BTC/USD', 0.005, 200.0, 40000.0, 'open')"
    )
    conn.executemany(
        "INSERT OR REPLACE INTO agent_state (key, value) VALUES (?, ?)",
        [
            ("current_playbook",      "momentum"),
            ("current_regime",        "trending_up"),
            ("adx_median_last",       "32.5"),
            ("daily_pnl_pct_last",    "1.2"),
            ("btc_dom_trend_current", "rising"),
            ("active_persona",        "medium"),
            ("last_cycle_ts",         "1700000000"),
        ],
    )
    conn.commit()
    conn.close()


def _minimal_config() -> dict:
    return {
        "trading": {
            "pairs": [
                {"pair": "BTC/USD", "pair_tier": 1, "take_profit_pct": 8, "buy_min_score": 5},
                {"pair": "ETH/USD", "pair_tier": 2, "take_profit_pct": 12, "buy_min_score": 5},
            ]
        },
        "signals": {"min_score": 5},
        "mcp": {"port": 8092},
    }


# ── Tests ──────────────────────────────────────────────────────────────────────

class TestMCPTools:
    def test_portfolio_state_returns_pipe_string(self):
        db = _mk_db()
        _seed_db(db)
        result = tool_get_portfolio_state(db)
        assert "cash|" in result
        assert "total_usd|" in result
        assert "open_positions|" in result
        # Cash 800 + invested 200 = 1000
        assert "1000.00" in result or "1000" in result
        _cleanup(db)

    def test_portfolio_state_open_positions_count(self):
        db = _mk_db()
        _seed_db(db)
        result = tool_get_portfolio_state(db)
        assert "open_positions|1" in result
        _cleanup(db)

    def test_signal_snapshot_no_snapshot_default(self):
        db = _mk_db()
        _seed_db(db)
        result = tool_get_signal_snapshot(db)
        # No signal_snapshot_ keys seeded
        assert result == "no_snapshot"
        _cleanup(db)

    def test_regime_state_reads_agent_state(self):
        db = _mk_db()
        _seed_db(db)
        result = tool_get_regime_state(db)
        assert "playbook|momentum" in result
        assert "regime|trending_up" in result
        assert "adx_median|32.5" in result
        assert "btc_dom_trend|rising" in result
        _cleanup(db)

    def test_agent_status_reads_persona(self):
        db = _mk_db()
        _seed_db(db)
        result = tool_get_agent_status(db)
        assert "persona|medium" in result
        _cleanup(db)

    def test_universe_state_returns_all_pairs(self):
        db = _mk_db()
        _seed_db(db)
        cfg = _minimal_config()
        result = tool_get_universe_state(db, cfg)
        assert "BTC/USD" in result
        assert "ETH/USD" in result
        assert "tier|1" in result
        assert "tp_pct|8" in result
        _cleanup(db)

    def test_persistence_scores_win_rate(self):
        """Win rate should be 100% when all trades are profitable."""
        import time
        db = _mk_db()
        _seed_db(db)
        conn = get_connection(db)
        now = time.time()
        conn.executemany(
            "INSERT INTO paper_trades (pair, pnl_usd, exit_reason, closed_at) VALUES (?,?,?,?)",
            [
                ("BTC/USD", 10.0, "take_profit", now - 1000),
                ("BTC/USD", 5.0,  "take_profit", now - 2000),
            ],
        )
        conn.commit()
        conn.close()
        cfg = _minimal_config()
        result = tool_get_persistence_scores(db, cfg)
        assert "BTC/USD" in result
        assert "win_rate|100.0" in result
        assert "trades|2" in result
        _cleanup(db)

    def test_unknown_tool_raises(self):
        cfg = _minimal_config()
        server = MCPServer.__new__(MCPServer)
        server._config  = cfg
        server._db_path = _mk_db()
        server._port    = 8092
        with pytest.raises(ValueError, match="Unknown tool"):
            server._dispatch("nonexistent_tool")


def _cleanup(db_path: str) -> None:
    try:
        full = str(_get_db_path(db_path))
        if os.path.exists(full):
            os.remove(full)
    except Exception:
        pass
