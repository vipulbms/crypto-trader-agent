"""
test_audit_agent_outcome_tracking.py — S23.1.1 AC6/AC7

Tests:
  - AC6: RAA proposal with expected_alpha +8%, actual_alpha -12% → FAIL_PUMP_DETECTION outcome
  - AC7: MEME_BLOCK reprimand → audit_feedback row with penalty_weight=-2.0
"""
import uuid

import pytest

from src.storage.database import init_paper_db
from src.runtime.audit_agent import (
    write_reprimand,
    run_24h_validation_window,
)

# ── DB setup ──────────────────────────────────────────────────

DB_NAME = f"test_audit_outcome_{uuid.uuid4().hex[:8]}.db"

_MIN_CONFIG = {
    "feedback": {
        "enabled": True,
        "validation_window_h": 0,   # 0 = immediate for test (window already elapsed)
        "expected_alpha_success_pct": 5.0,
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

def _seed_add_pair_event(pair: str, expected_alpha: float, hours_ago: int = 25):
    """Insert a universe_events ADD_PAIR row with ts = now - hours_ago."""
    import json
    from src.storage.database import get_connection
    conn = get_connection(_db())
    import datetime
    ts = (datetime.datetime.utcnow() - datetime.timedelta(hours=hours_ago)).isoformat()
    payload = json.dumps({
        "pair": pair,
        "expected_alpha": expected_alpha,
        "classification": "MEME",
        "psv_vector": "ps1|ps2|ps3",
    })
    conn.execute(
        "INSERT INTO universe_events (pair, event_type, ts, processed, payload_json) "
        "VALUES (?, 'ADD_PAIR', ?, 0, ?)",
        (pair, ts, payload)
    )
    conn.commit()
    conn.close()


def _seed_actual_trade(pair: str, pnl_pct: float):
    """Insert a paper_trades row so actual_alpha can be computed."""
    from src.storage.database import get_connection
    import datetime
    conn = get_connection(_db())
    ts = datetime.datetime.utcnow().isoformat()
    conn.execute(
        "INSERT INTO paper_trades "
        "(pair, pnl_pct, pnl_usd, opened_at, closed_at, exit_reason, "
        "side, entry_price, exit_price, volume, usd_invested, "
        "hold_duration_secs, stop_loss_pct, take_profit_pct) "
        "VALUES (?, ?, ?, ?, ?, 'stop_loss', 'buy', 1.0, 1.0, 1.0, 100.0, 3600, 5.0, 10.0)",
        (pair, pnl_pct, round(pnl_pct, 4), ts, ts)
    )
    conn.commit()
    conn.close()


# ── AC6: expected +8%, actual -12% → FAIL_PUMP_DETECTION ─────

class TestOutcomeTracking:
    def test_ac6_fail_pump_detection_written(self):
        """
        Seed ADD_PAIR event 25h ago (validation window elapsed) with expected_alpha=+8%.
        Seed closed trade with pnl_pct=-12%.
        run_24h_validation_window should write FAIL_PUMP_DETECTION to audit_feedback.
        """
        _seed_add_pair_event("PUMP/USD", expected_alpha=8.0, hours_ago=25)
        _seed_actual_trade("PUMP/USD", pnl_pct=-12.0)

        run_24h_validation_window(_db(), _MIN_CONFIG)

        from src.storage.database import get_connection
        conn = get_connection(_db())
        rows = conn.execute(
            "SELECT * FROM audit_feedback WHERE pair='PUMP/USD' AND event_type='OUTCOME_VECTOR'"
        ).fetchall()
        conn.close()

        assert len(rows) >= 1, "Expected at least one OUTCOME_VECTOR row for PUMP/USD"
        row = rows[0]
        assert row["outcome"] == "FAIL_PUMP_DETECTION", (
            f"Expected FAIL_PUMP_DETECTION, got {row['outcome']}"
        )
        assert float(row["actual_alpha"]) < 0.0
        assert float(row["expected_alpha"]) > 0.0

    def test_ac6_event_marked_processed(self):
        """After window runs, the universe_events row must have processed=1."""
        _seed_add_pair_event("PUMP/USD", expected_alpha=8.0, hours_ago=25)
        _seed_actual_trade("PUMP/USD", pnl_pct=-12.0)

        run_24h_validation_window(_db(), _MIN_CONFIG)

        from src.storage.database import get_connection
        conn = get_connection(_db())
        rows = conn.execute(
            "SELECT processed FROM universe_events WHERE pair='PUMP/USD'"
        ).fetchall()
        conn.close()
        assert all(r["processed"] == 1 for r in rows), "Expected processed=1 after window"

    def test_ac6_no_action_within_window(self):
        """Event only 1h old — validation window not elapsed; no audit_feedback row."""
        _seed_add_pair_event("NEW/USD", expected_alpha=8.0, hours_ago=1)
        _seed_actual_trade("NEW/USD", pnl_pct=-12.0)

        # Use a 24h window config (not overridden to 0)
        config = dict(_MIN_CONFIG)
        config["feedback"] = {**config["feedback"], "validation_window_h": 24}
        run_24h_validation_window(_db(), config)

        from src.storage.database import get_connection
        conn = get_connection(_db())
        count = conn.execute(
            "SELECT COUNT(*) FROM audit_feedback WHERE pair='NEW/USD'"
        ).fetchone()[0]
        conn.close()
        assert count == 0, "Should not have processed event within window"


# ── AC7: MEME_BLOCK reprimand ─────────────────────────────────

class TestReprimand:
    def test_ac7_meme_block_reprimand_written(self):
        """
        write_reprimand with event_type='MEME_BLOCK' and penalty_weight=-2.0
        must write an audit_feedback row with those exact values.
        """
        write_reprimand(
            db_path=_db(),
            agent="RAA",
            pair="BONK/USD",
            event_type="MEME_BLOCK",
            psv_vector="class=MEME|ps=1.2|regime=bearish",
            penalty_weight=-2.0,
        )

        from src.storage.database import get_connection
        conn = get_connection(_db())
        rows = conn.execute(
            "SELECT * FROM audit_feedback WHERE pair='BONK/USD' AND event_type='MEME_BLOCK'"
        ).fetchall()
        conn.close()

        assert len(rows) == 1
        row = rows[0]
        assert row["agent"] == "RAA"
        assert float(row["penalty_weight"]) == -2.0

    def test_ac7_422_rejection_reprimand(self):
        """Risk Manager 422 rejection also writes a reprimand."""
        write_reprimand(
            db_path=_db(),
            agent="RAA",
            pair="WIF/USD",
            event_type="422_REJECTION",
            psv_vector="class=MEME|ps=0.9|regime=neutral",
            penalty_weight=-2.0,
        )

        from src.storage.database import get_connection
        conn = get_connection(_db())
        count = conn.execute(
            "SELECT COUNT(*) FROM audit_feedback WHERE event_type='422_REJECTION'"
        ).fetchone()[0]
        conn.close()
        assert count == 1

    def test_ac7_multiple_reprimands_accumulate(self):
        """Each call to write_reprimand creates a new row."""
        for _ in range(3):
            write_reprimand(
                db_path=_db(),
                agent="RAA",
                pair="PEPE/USD",
                event_type="MEME_BLOCK",
                psv_vector="v",
                penalty_weight=-2.0,
            )

        from src.storage.database import get_connection
        conn = get_connection(_db())
        count = conn.execute(
            "SELECT COUNT(*) FROM audit_feedback WHERE pair='PEPE/USD'"
        ).fetchone()[0]
        conn.close()
        assert count == 3
