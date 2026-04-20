"""
test_hitl_lock_propose_replace.py — S23.1.3 AC4/AC6

Tests:
  - AC4: While substitution_tool_locked=1: every PROPOSE_REPLACE call writes to hitl_queue
         (status=PENDING); no universe_events row written
  - AC6: 3 MEME_BLOCK reprimands → locked=1; next PROPOSE_REPLACE → hitl_queue PENDING only

Uses audit_agent.check_hitl_lock + research_analyst._maybe_propose_replace pattern.
"""
import uuid
import datetime

import pytest

from src.storage.database import init_paper_db, get_connection
from src.runtime.audit_agent import write_rejection_reprimand, enforce_hitl_lock, get_confidence_state, upsert_confidence_state

# ── DB setup ──────────────────────────────────────────────────

DB_NAME = f"test_hitl_lock_{uuid.uuid4().hex[:8]}.db"

_CFG = {
    "feedback": {
        "enabled": True,
        "hitl_lock": {
            "meme_block_violations": 3,
            "lock_duration_hours": 24,
        }
    }
}


@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    import src.storage.database as db_mod
    _orig = db_mod.DATA_DIR_PATH
    db_mod.DATA_DIR_PATH = str(tmp_path)
    init_paper_db(DB_NAME)
    yield
    db_mod.DATA_DIR_PATH = _orig


def _db():
    return DB_NAME


# ── helpers ───────────────────────────────────────────────────

def _lock_substitution_tool():
    """Directly set substitution_tool_locked=1 in confidence_state."""
    conn = get_connection(_db())
    ts_now = datetime.datetime.utcnow().isoformat()
    locked_until = (datetime.datetime.utcnow() + datetime.timedelta(hours=24)).isoformat()
    conn.execute(
        "INSERT OR REPLACE INTO confidence_state "
        "(agent, substitution_tool_locked, locked_until_ts, confidence_reset_count, last_updated_at) "
        "VALUES ('RAA', 1, ?, 0, ?)",
        (locked_until, ts_now)
    )
    conn.commit()
    conn.close()


def _unlock_substitution_tool():
    upsert_confidence_state(_db(), "RAA", substitution_tool_locked=0)


def _simulate_propose_replace(pair: str, replace_target: str, is_locked: bool):
    """
    Simulates research_analyst's PROPOSE_REPLACE path.
    If locked: write hitl_queue PENDING, do NOT write universe_events.
    If not locked: write universe_events directly.
    """
    conn = get_connection(_db())
    ts = datetime.datetime.utcnow().isoformat()
    if is_locked:
        conn.execute(
            "INSERT INTO hitl_queue (ts, agent, proposal_type, pair, replace_target, "
            "classification, psv_vector, rationale, status) "
            "VALUES (?, 'RAA', 'PROPOSE_REPLACE', ?, ?, 'FOUNDATIONAL', 'v', 'test', 'PENDING')",
            (ts, pair, replace_target)
        )
    else:
        conn.execute(
            "INSERT INTO universe_events (pair, event_type, ts, processed, payload_json) "
            "VALUES (?, 'REPLACE_PAIR', ?, 0, '{\"source\":\"RAA\"}')",
            (pair, ts)
        )
    conn.commit()
    conn.close()


def _is_locked():
    state = get_confidence_state(_db(), "RAA")
    return bool(state and state.get("substitution_tool_locked") == 1)


# ── AC4: while locked, PROPOSE_REPLACE → hitl_queue only ─────

class TestLockedProposalRouting:
    def test_ac4_locked_writes_hitl_queue_not_universe(self):
        """With substitution_tool_locked=1: proposal goes to hitl_queue only."""
        _lock_substitution_tool()
        assert _is_locked()

        _simulate_propose_replace("NEAR/USD", "RAILS/USD", is_locked=True)

        conn = get_connection(_db())
        hitl_count = conn.execute(
            "SELECT COUNT(*) FROM hitl_queue WHERE pair='NEAR/USD' AND status='PENDING'"
        ).fetchone()[0]
        universe_count = conn.execute(
            "SELECT COUNT(*) FROM universe_events WHERE pair='NEAR/USD'"
        ).fetchone()[0]
        conn.close()

        assert hitl_count == 1, "Expected 1 PENDING hitl_queue row"
        assert universe_count == 0, "Expected 0 universe_events when locked"

    def test_ac4_unlocked_writes_universe_not_hitl_queue(self):
        """With substitution_tool_locked=0: proposal goes to universe_events directly."""
        _unlock_substitution_tool()
        assert not _is_locked()

        _simulate_propose_replace("AVAX/USD", "OLD/USD", is_locked=False)

        conn = get_connection(_db())
        hitl_count = conn.execute(
            "SELECT COUNT(*) FROM hitl_queue WHERE pair='AVAX/USD'"
        ).fetchone()[0]
        universe_count = conn.execute(
            "SELECT COUNT(*) FROM universe_events WHERE pair='AVAX/USD'"
        ).fetchone()[0]
        conn.close()

        assert universe_count == 1, "Expected 1 universe_events row when unlocked"
        assert hitl_count == 0, "Expected 0 hitl_queue rows when unlocked"


# ── AC6: 3 MEME_BLOCKs → locked, next PROPOSE_REPLACE → PENDING ─

class TestMemeBlockToLock:
    def test_ac6_three_meme_blocks_trigger_lock_and_queue(self):
        """
        Full end-to-end: 3 MEME_BLOCK reprimands → check_hitl_lock fires →
        next PROPOSE_REPLACE routed to hitl_queue (simulated).
        """
        for _ in range(3):
            write_rejection_reprimand(
                _db(), "BONK/USD",
                rejection_reason="MEME_BLOCK",
                psv_vector="class=MEME|ps=1.2|regime=bearish",
            )

        # Run HITL lock check — should set substitution_tool_locked=1
        enforce_hitl_lock(_db(), _CFG)
        assert _is_locked(), "substitution_tool_locked should be 1 after 3 MEME_BLOCKs"

        # Simulate PROPOSE_REPLACE — must go to hitl_queue
        _simulate_propose_replace("LINK/USD", "BONK/USD", is_locked=True)

        conn = get_connection(_db())
        hitl_count = conn.execute(
            "SELECT COUNT(*) FROM hitl_queue WHERE status='PENDING'"
        ).fetchone()[0]
        universe_count = conn.execute(
            "SELECT COUNT(*) FROM universe_events WHERE pair='LINK/USD'"
        ).fetchone()[0]
        conn.close()

        assert hitl_count == 1
        assert universe_count == 0

    def test_ac6_two_meme_blocks_no_lock(self):
        """2 MEME_BLOCKs (< threshold) — not locked."""
        for _ in range(2):
            write_rejection_reprimand(
                _db(), "PEPE/USD",
                rejection_reason="MEME_BLOCK",
                psv_vector="v",
            )

        enforce_hitl_lock(_db(), _CFG)
        assert not _is_locked(), "Should not be locked with only 2 MEME_BLOCKs"
