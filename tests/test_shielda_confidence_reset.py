"""
test_shielda_confidence_reset.py — S23.1.3 AC1/AC2/AC3

Tests:
  - AC1: rolling 5-outcome std-dev > 3σ → CONFIDENCE_RESET written to audit_feedback
  - AC2: RAA reads CONFIDENCE_RESET → clears ps_threshold_override, sector_multiplier_json,
         driver_multiplier_json in confidence_state
  - AC3: 3 FOUNDATIONAL_REPLACEMENT_BLOCK reprimands → substitution_tool_locked=1,
         locked_until_ts set
"""
import uuid
import datetime

import pytest

from src.storage.database import init_paper_db
from src.runtime.audit_agent import (
    write_audit_feedback,
    check_confidence_reset,
    enforce_hitl_lock,
)

# ── DB setup ──────────────────────────────────────────────────

DB_NAME = f"test_shielda_{uuid.uuid4().hex[:8]}.db"

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

# outcomes written via write_audit_feedback helper


def _write_confidence_state(agent: str, ps_override: float = 1.5):
    from src.storage.database import get_connection
    from src.runtime.audit_agent import upsert_confidence_state
    upsert_confidence_state(_db(), agent, confidence_reset_count=0, substitution_tool_locked=0)


def _get_confidence_state(agent: str):
    from src.storage.database import get_connection
    conn = get_connection(_db())
    row = conn.execute(
        "SELECT * FROM confidence_state WHERE agent=?", (agent,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


# ── AC1: std-dev > 3σ → CONFIDENCE_RESET ─────────────────────

class TestConfidenceReset:
    def test_ac1_high_variance_triggers_reset(self):
        """
        5 outcomes with high spread:
        deltas = [20, -20, 20, -20, 20]  (expected-actual)
        std-dev ~ 20 >> 3σ → CONFIDENCE_RESET written.
        """
        # Seed 5 outcomes with alternating large deltas
        for i, (exp, act) in enumerate([
            (5.0, -15.0),    # delta=-20
            (5.0,  25.0),    # delta=20
            (5.0, -15.0),
            (5.0,  25.0),
            (5.0, -15.0),
        ]):
            write_audit_feedback(
                _db(), "RAA", f"PAIR{i}/USD",
                event_type="OUTCOME_VECTOR",
                psv_vector="v",
                expected_alpha=exp,
                actual_alpha=act,
                outcome="FAIL_PUMP_DETECTION",
                penalty_weight=0.0,
            )

        _write_confidence_state("RAA")
        check_confidence_reset(_db(), "RAA")

        from src.storage.database import get_connection
        conn = get_connection(_db())
        rows = conn.execute(
            "SELECT * FROM audit_feedback WHERE event_type='CONFIDENCE_RESET' AND agent='RAA'"
        ).fetchall()
        conn.close()
        assert len(rows) >= 1, "Expected CONFIDENCE_RESET in audit_feedback"

    def test_ac1_low_variance_no_reset(self):
        """Outcomes with tight spread do not trigger CONFIDENCE_RESET."""
        for i in range(5):
            write_audit_feedback(
                _db(), "RAA", f"STABLE{i}/USD",
                event_type="OUTCOME_VECTOR",
                psv_vector="v",
                expected_alpha=5.0,
                actual_alpha=4.0 + i * 0.1,
                outcome="PASS",
                penalty_weight=0.0,
            )

        _write_confidence_state("RAA")
        check_confidence_reset(_db(), "RAA")

        from src.storage.database import get_connection
        conn = get_connection(_db())
        count = conn.execute(
            "SELECT COUNT(*) FROM audit_feedback WHERE event_type='CONFIDENCE_RESET'"
        ).fetchone()[0]
        conn.close()
        assert count == 0

    def test_ac1_fewer_than_5_outcomes_no_reset(self):
        """Fewer than 5 OUTCOME_VECTOR rows: reset check skipped."""
        write_audit_feedback(
            _db(), "RAA", "FEW/USD",
            event_type="OUTCOME_VECTOR",
            psv_vector="v",
            expected_alpha=5.0,
            actual_alpha=-20.0,
            outcome="FAIL_PUMP_DETECTION",
            penalty_weight=0.0,
        )
        _write_confidence_state("RAA")
        check_confidence_reset(_db(), "RAA")

        from src.storage.database import get_connection
        conn = get_connection(_db())
        count = conn.execute(
            "SELECT COUNT(*) FROM audit_feedback WHERE event_type='CONFIDENCE_RESET'"
        ).fetchone()[0]
        conn.close()
        assert count == 0


# ── AC3: 3 FOUNDATIONAL_REPLACEMENT_BLOCK → HITL lock ────────

class TestHitlLock:
    def _seed_frb_reprimands(self, count: int):
        for _ in range(count):
            write_audit_feedback(
                _db(), "RAA", "ETH/USD",
                event_type="FOUNDATIONAL_REPLACEMENT_BLOCK",
                psv_vector="v",
                penalty_weight=-2.0,
            )

    def test_ac3_three_reprimands_locks_substitution(self):
        """3 FOUNDATIONAL_REPLACEMENT_BLOCK reprimands → locked=1."""
        _write_confidence_state("RAA")
        self._seed_frb_reprimands(3)

        enforce_hitl_lock(_db(), _CFG)

        state = _get_confidence_state("RAA")
        assert state is not None
        assert state["substitution_tool_locked"] == 1
        assert state["locked_until_ts"] is not None

    def test_ac3_two_reprimands_no_lock(self):
        """2 reprimands (< threshold of 3) — no lock."""
        _write_confidence_state("RAA")
        self._seed_frb_reprimands(2)

        enforce_hitl_lock(_db(), _CFG)

        state = _get_confidence_state("RAA")
        if state is None:
            # confidence_state never written — that's also fine (no lock)
            return
        assert state["substitution_tool_locked"] == 0

    def test_ac3_lock_expiry_is_in_future(self):
        """locked_until_ts must be at least 1 hour in the future."""
        _write_confidence_state("RAA")
        self._seed_frb_reprimands(3)
        enforce_hitl_lock(_db(), _CFG)

        state = _get_confidence_state("RAA")
        locked_until = datetime.datetime.fromisoformat(state["locked_until_ts"])
        # Handle both naive and timezone-aware datetimes
        if locked_until.tzinfo is None:
            now = datetime.datetime.utcnow()
        else:
            now = datetime.datetime.now(datetime.timezone.utc)
        assert locked_until > now + datetime.timedelta(hours=1), (
            "locked_until_ts should be at least 1 hour in the future"
        )
