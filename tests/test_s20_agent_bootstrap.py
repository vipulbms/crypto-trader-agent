"""
Test suite for Sprint S4 — S20.3.1 (AgentCard + AgentBootstrap).

Tests:
  - AgentCard fields, UUID auto-generation, to_dict / from_row roundtrip
  - AgentBootstrap.start() → registry row with status=running
  - AgentBootstrap.heartbeat() → updates last_heartbeat
  - AgentBootstrap.stop() → status=stopped
  - AgentBootstrap.get_live_agents() → freshness filter

pytest: python -m pytest tests/test_s20_agent_bootstrap.py -v
"""
from __future__ import annotations

import json
import sqlite3
import tempfile
import os
import time
import uuid
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "mocha-python-libraries" / "packages" / "mocha_python_agent" / "src"))

from mocha_python_agent import AgentCard, AgentBootstrap


# ──────────────────────────────────────────────────────────────
# Test DB helper
# ──────────────────────────────────────────────────────────────

def _tmp_db() -> str:
    """Return path to an isolated temp SQLite DB."""
    tmp = tempfile.mkdtemp()
    return os.path.join(tmp, f"test_agent_{uuid.uuid4().hex[:8]}.db")


# ──────────────────────────────────────────────────────────────
# AgentCard tests
# ──────────────────────────────────────────────────────────────

class TestAgentCard:
    def test_auto_generates_uuid4_agent_id(self):
        card = AgentCard(name="AIE", version="1.0.0")
        assert len(card.agent_id) == 36
        # Verify it's a valid UUID4
        parsed = uuid.UUID(card.agent_id, version=4)
        assert str(parsed) == card.agent_id

    def test_two_cards_get_different_ids(self):
        a = AgentCard(name="AIE", version="1.0.0")
        b = AgentCard(name="AIE", version="1.0.0")
        assert a.agent_id != b.agent_id

    def test_default_status_is_stopped(self):
        card = AgentCard(name="AIE", version="1.0.0")
        assert card.status == "stopped"

    def test_default_host_is_localhost(self):
        card = AgentCard(name="AIE", version="1.0.0")
        assert card.host == "127.0.0.1"

    def test_to_dict_contains_all_fields(self):
        card = AgentCard(name="AIE", version="1.0.0", capabilities=["llm-decision"])
        d = card.to_dict()
        assert d["name"] == "AIE"
        assert d["version"] == "1.0.0"
        assert d["capabilities"] == ["llm-decision"]
        assert "agent_id" in d

    def test_from_row_roundtrip(self):
        card = AgentCard(
            name="QSA", version="2.0.0",
            capabilities=["data-feed"], port=9100, host="127.0.0.1",
        )
        row = {
            "agent_id":    card.agent_id,
            "name":        card.name,
            "version":     card.version,
            "status":      "running",
            "metadata_json": json.dumps({
                "capabilities": card.capabilities,
                "host":          card.host,
                "port":          card.port,
                "started_at":    "2026-01-01T00:00:00+00:00",
            }),
        }
        restored = AgentCard.from_row(row)
        assert restored.name         == card.name
        assert restored.version      == card.version
        assert restored.capabilities == card.capabilities
        assert restored.status       == "running"
        assert restored.agent_id     == card.agent_id

    def test_capabilities_default_to_empty_list(self):
        card = AgentCard(name="ROM", version="1.0.0")
        assert card.capabilities == []


# ──────────────────────────────────────────────────────────────
# AgentBootstrap lifecycle tests
# ──────────────────────────────────────────────────────────────

class TestAgentBootstrapLifecycle:
    def _get_registry_row(self, db_path: str, agent_id: str) -> dict | None:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM agent_registry WHERE agent_id = ?", (agent_id,)
        ).fetchone()
        conn.close()
        return dict(row) if row else None

    def test_start_creates_registry_row_with_running_status(self):
        """AC1: start() writes a row to agent_registry with status=running."""
        db = _tmp_db()
        card = AgentCard(name="AIE", version="3.0.0")
        boot = AgentBootstrap(db_path=db, card=card)
        boot.start()
        row = self._get_registry_row(db, card.agent_id)
        assert row is not None
        assert row["status"] == "running"

    def test_start_records_started_at_in_metadata(self):
        """AC2: metadata_json contains started_at ISO timestamp."""
        db = _tmp_db()
        card = AgentCard(name="AIE", version="3.0.0")
        boot = AgentBootstrap(db_path=db, card=card)
        boot.start()
        row = self._get_registry_row(db, card.agent_id)
        meta = json.loads(row["metadata_json"])
        assert "started_at" in meta
        assert len(meta["started_at"]) > 10  # non-empty ISO string

    def test_start_persists_capabilities(self):
        """AC3: capabilities list persisted in metadata_json."""
        db = _tmp_db()
        card = AgentCard(name="ROM", version="1.0.0", capabilities=["reallocation", "prune-gate"])
        boot = AgentBootstrap(db_path=db, card=card)
        boot.start()
        row = self._get_registry_row(db, card.agent_id)
        meta = json.loads(row["metadata_json"])
        assert meta["capabilities"] == ["reallocation", "prune-gate"]

    def test_heartbeat_updates_last_heartbeat(self):
        """AC4: heartbeat() updates last_heartbeat to a more recent timestamp."""
        db = _tmp_db()
        card = AgentCard(name="AIE", version="3.0.0")
        boot = AgentBootstrap(db_path=db, card=card)
        boot.start()
        row_before = self._get_registry_row(db, card.agent_id)
        ts_before  = row_before["last_heartbeat"]
        time.sleep(0.05)
        boot.heartbeat()
        row_after = self._get_registry_row(db, card.agent_id)
        ts_after  = row_after["last_heartbeat"]
        assert ts_after >= ts_before  # monotonically non-decreasing

    def test_stop_sets_status_to_stopped(self):
        """AC5: stop() changes status to 'stopped' in the registry."""
        db = _tmp_db()
        card = AgentCard(name="AIE", version="3.0.0")
        boot = AgentBootstrap(db_path=db, card=card)
        boot.start()
        boot.stop()
        row = self._get_registry_row(db, card.agent_id)
        assert row["status"] == "stopped"

    def test_second_start_upserts_existing_row(self):
        """AC6: calling start() twice does not create a second row."""
        db = _tmp_db()
        card = AgentCard(name="AIE", version="3.0.0")
        boot = AgentBootstrap(db_path=db, card=card)
        boot.start()
        boot.stop()
        boot.start()
        conn = sqlite3.connect(db)
        count = conn.execute(
            "SELECT COUNT(*) FROM agent_registry WHERE agent_id = ?",
            (card.agent_id,),
        ).fetchone()[0]
        conn.close()
        assert count == 1


# ──────────────────────────────────────────────────────────────
# AgentBootstrap.get_live_agents tests
# ──────────────────────────────────────────────────────────────

class TestGetLiveAgents:
    def _insert_agent(
        self,
        db: str,
        agent_id: str,
        name: str,
        status: str,
        last_heartbeat_offset_secs: float = 0,
    ) -> None:
        """Insert a row directly, offset heartbeat from now by N seconds."""
        from datetime import datetime, timezone, timedelta
        now = datetime.now(timezone.utc)
        ts = (now - timedelta(seconds=abs(last_heartbeat_offset_secs))).isoformat()
        conn = sqlite3.connect(db)
        conn.execute(
            """CREATE TABLE IF NOT EXISTS agent_registry (
                agent_id TEXT PRIMARY KEY,
                name TEXT, version TEXT,
                status TEXT DEFAULT 'stopped',
                last_heartbeat TEXT,
                registered_at TEXT,
                metadata_json TEXT
            )"""
        )
        conn.execute(
            "INSERT OR REPLACE INTO agent_registry VALUES (?,?,?,?,?,?,?)",
            (agent_id, name, "1.0.0", status, ts, ts, json.dumps({})),
        )
        conn.commit()
        conn.close()

    def test_fresh_running_agent_is_returned(self):
        """AC7: running agent with recent heartbeat appears in get_live_agents."""
        db = _tmp_db()
        aid = str(uuid.uuid4())
        self._insert_agent(db, aid, "AIE", "running", last_heartbeat_offset_secs=10)
        live = AgentBootstrap.get_live_agents(db, stale_secs=120)
        ids = [a.agent_id for a in live]
        assert aid in ids

    def test_stale_agent_excluded(self):
        """AC8: running agent with heartbeat > stale_secs ago is excluded."""
        db = _tmp_db()
        aid = str(uuid.uuid4())
        self._insert_agent(db, aid, "QSA", "running", last_heartbeat_offset_secs=200)
        live = AgentBootstrap.get_live_agents(db, stale_secs=120)
        ids = [a.agent_id for a in live]
        assert aid not in ids

    def test_stopped_agent_excluded_even_if_fresh(self):
        """AC9: stopped agent is never returned even if heartbeat is recent."""
        db = _tmp_db()
        aid = str(uuid.uuid4())
        self._insert_agent(db, aid, "ROM", "stopped", last_heartbeat_offset_secs=5)
        live = AgentBootstrap.get_live_agents(db, stale_secs=120)
        ids = [a.agent_id for a in live]
        assert aid not in ids

    def test_empty_registry_returns_empty_list(self):
        """AC10: empty registry → empty list, no crash."""
        db = _tmp_db()
        # Create empty table
        conn = sqlite3.connect(db)
        conn.execute(
            """CREATE TABLE IF NOT EXISTS agent_registry (
                agent_id TEXT PRIMARY KEY,
                name TEXT, version TEXT,
                status TEXT DEFAULT 'stopped',
                last_heartbeat TEXT,
                registered_at TEXT,
                metadata_json TEXT
            )"""
        )
        conn.commit()
        conn.close()
        live = AgentBootstrap.get_live_agents(db, stale_secs=120)
        assert live == []
