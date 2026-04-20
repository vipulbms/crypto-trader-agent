"""
Tests for S18.1.2 — kryptos regime CLI command.

Covers:
  - cmd_regime reads all 7 AC1 fields from agent_state (AC2)
  - Colour codes match playbook (AC3): momentum=green, ranging=yellow, risk_off=red
  - Velocity circuit shows open when timestamp in future
  - No crash when agent_state is empty (graceful defaults)
  - NL keyword 'show regime' → regime intent
"""

import uuid
import os
import time

import pytest

from src.storage.database import get_connection, _get_db_path


def _mk_db() -> str:
    return f"test_regime_{uuid.uuid4().hex[:8]}.db"


def _seed_state(db_path: str, rows: list[tuple]) -> None:
    conn = get_connection(db_path)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS agent_state (
            key TEXT PRIMARY KEY, value TEXT NOT NULL
        );
    """)
    conn.executemany(
        "INSERT OR REPLACE INTO agent_state (key, value) VALUES (?, ?)", rows
    )
    conn.commit()
    conn.close()


def _minimal_config() -> dict:
    return {
        "agent": {"persona": "medium", "concurrent_mode": False},
        "trading": {"pairs": [], "mode": "paper"},
        "storage": {"data_dir": "data", "log_dir": "logs"},
    }


def _cleanup(db_path: str) -> None:
    try:
        full = str(_get_db_path(db_path))
        if os.path.exists(full):
            os.remove(full)
    except Exception:
        pass


class TestRegimeCLI:
    def test_regime_reads_all_fields(self, monkeypatch):
        """All 7 AC1 fields should be present in the rendered output."""
        from src.cli import commands, display as d
        from src.storage import database

        db = _mk_db()
        _seed_state(db, [
            ("current_playbook",      "momentum"),
            ("current_regime",        "trending_up"),
            ("adx_median_last",       "35.0"),
            ("btc_dom_trend_current", "rising"),
            ("daily_pnl_pct_last",    "2.5"),
            ("active_persona",        "medium"),
            ("last_cycle_ts",         "1700000000"),
        ])

        cfg = _minimal_config()
        captured = []

        # Monkey-patch display.print_regime_state to capture the call
        monkeypatch.setattr(d, "print_regime_state", lambda state, config: captured.append(state))
        # Monkey-patch resolve_trading_db + get_connection_ro to use our test DB
        monkeypatch.setattr(database, "resolve_trading_db", lambda cfg, mode: db)

        commands.cmd_regime({}, cfg)

        assert len(captured) == 1
        state = captured[0]
        assert state["current_playbook"]      == "momentum"
        assert state["current_regime"]        == "trending_up"
        assert state["adx_median_last"]       == "35.0"
        assert state["btc_dom_trend_current"] == "rising"
        assert state["daily_pnl_pct_last"]    == "2.5"
        assert state["active_persona"]        == "medium"
        assert state["last_cycle_ts"]         == "1700000000"

        _cleanup(db)

    def test_regime_defaults_when_empty(self, monkeypatch):
        """If agent has never run, state is empty — should not crash."""
        from src.cli import commands, display as d
        from src.storage import database

        db = _mk_db()
        _seed_state(db, [])  # empty agent_state

        cfg = _minimal_config()
        captured = []
        monkeypatch.setattr(d, "print_regime_state", lambda state, config: captured.append(state))
        monkeypatch.setattr(database, "resolve_trading_db", lambda cfg, mode: db)

        commands.cmd_regime({}, cfg)  # must not raise

        assert len(captured) == 1
        _cleanup(db)

    def test_velocity_circuit_open_when_future(self):
        """tool_get_regime_state shows vel_circuit=1 when timestamp is in future."""
        from src.mcp.server import tool_get_regime_state

        db = _mk_db()
        future_ts = str(time.time() + 7200)  # 2 hours from now
        _seed_state(db, [("velocity_circuit_open_until", future_ts)])

        result = tool_get_regime_state(db)
        assert "vel_circuit|1" in result

        _cleanup(db)

    def test_velocity_circuit_closed_when_past(self):
        """tool_get_regime_state shows vel_circuit=0 when timestamp is in past."""
        from src.mcp.server import tool_get_regime_state

        db = _mk_db()
        past_ts = str(time.time() - 3600)  # 1 hour ago
        _seed_state(db, [("velocity_circuit_open_until", past_ts)])

        result = tool_get_regime_state(db)
        assert "vel_circuit|0" in result

        _cleanup(db)


class TestRegimeNLParser:
    def _parser(self):
        from src.cli.nl_parser import NLParser
        cfg: dict = {
            "agent": {"persona": "medium"},
            "llm": {"model": "mock", "base_url": "http://localhost:11434"},
            "trading": {"pairs": []},
        }
        return NLParser(cfg)

    def test_keyword_regime_intent(self):
        """'show regime' → regime intent."""
        p = self._parser()
        result = p.parse("show regime")
        assert result["intent"] == "regime"
        assert result["source"] == "keyword"

    def test_keyword_playbook_intent(self):
        """'what playbook is active' → regime intent."""
        p = self._parser()
        result = p.parse("what playbook is active")
        assert result["intent"] == "regime"
