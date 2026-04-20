"""
test_raa_universe_proposal.py — S22.1.2 AC3/AC4/AC8

Tests:
  - N < universe_cap: proposal accepted without replace_target
  - N == universe_cap: proposal with replace_target accepted; without → UNIVERSE_AT_CAP
  - Alpha spread below threshold → ALPHA_SPREAD_INSUFFICIENT
  - Approved: universe row written + universe_events ADD_PAIR and REMOVE_PAIR
"""
import json
import uuid

import pytest

from src.storage.database import init_paper_db, get_connection

DB_NAME = f"test_raa_up_{uuid.uuid4().hex[:8]}.db"


@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    import src.storage.database as db_mod
    _orig = db_mod.DATA_DIR_PATH
    db_mod.DATA_DIR_PATH = str(tmp_path)
    init_paper_db(DB_NAME)
    yield
    db_mod.DATA_DIR_PATH = _orig


def _make_config(universe_cap=35, min_alpha=2.0):
    return {
        "raa": {
            "universe_cap": universe_cap,
            "alpha_spread_gate": {"min_alpha_pct": min_alpha},
        },
        "agent": {"persona": "conservative"},
        "personas": {
            "conservative": {"reallocation_enabled": False},
        },
    }


def _make_rm(cfg):
    from src.risk.risk_manager import RiskManager
    return RiskManager(cfg, DB_NAME)


def _seed_universe(db: str, pairs: list[str], classification="FOUNDATIONAL"):
    from datetime import datetime, timezone
    conn = get_connection(db)
    for p in pairs:
        conn.execute(
            "INSERT OR REPLACE INTO universe (pair, classification, added_at, added_by) VALUES (?,?,?,?)",
            (p, classification, datetime.now(timezone.utc).isoformat(), "test"),
        )
    conn.commit()
    conn.close()


def _get_universe(db: str) -> list[str]:
    conn = get_connection(db)
    rows = conn.execute("SELECT pair FROM universe").fetchall()
    conn.close()
    return [r[0] for r in rows]


def _get_events(db: str) -> list[dict]:
    conn = get_connection(db)
    rows = conn.execute("SELECT * FROM universe_events ORDER BY id").fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── AC3: N < cap, no replace_target ──────────────────────────

class TestProposalNBelowCap:
    def test_accepted_without_replace_target(self):
        cfg = _make_config(universe_cap=35)
        rm = _make_rm(cfg)
        _seed_universe(DB_NAME, ["BTC/USD", "ETH/USD"])  # n=2
        result = rm.validate_universe_proposal(
            pair="SOL/USD",
            classification="FOUNDATIONAL",
            replace_target=None,
            replace_class=None,
            n_current=2,
            projected_alpha=5.0,
            persona_config={},
            psv_vector="SOL/USD|100|55|22|0.5|crypto|CANDIDATE",
            db_path=DB_NAME,
        )
        assert result["status"] == "approved"
        assert result["http_status"] == 200
        assert "SOL/USD" in _get_universe(DB_NAME)

    def test_add_pair_event_written(self):
        cfg = _make_config()
        rm = _make_rm(cfg)
        result = rm.validate_universe_proposal(
            pair="AVAX/USD", classification="FOUNDATIONAL",
            replace_target=None, replace_class=None,
            n_current=5, projected_alpha=3.0,
            persona_config={}, psv_vector="AVAX/USD|...",
            db_path=DB_NAME,
        )
        events = _get_events(DB_NAME)
        assert any(e["event_type"] == "ADD_PAIR" and e["pair"] == "AVAX/USD" for e in events)


# ── AC4: N == cap, with/without replace_target ────────────────

class TestProposalNAtCap:
    def test_rejected_at_cap_without_replace(self):
        """S22.1.2 AC4: N==cap without replace_target → UNIVERSE_AT_CAP."""
        cfg = _make_config(universe_cap=5)
        rm = _make_rm(cfg)
        _seed_universe(DB_NAME, ["A/USD", "B/USD", "C/USD", "D/USD", "E/USD"])
        result = rm.validate_universe_proposal(
            pair="F/USD", classification="FOUNDATIONAL",
            replace_target=None, replace_class=None,
            n_current=5, projected_alpha=5.0,
            persona_config={}, psv_vector="F/USD|...",
            db_path=DB_NAME,
        )
        assert result["status"] == "rejected"
        assert result["reason"] == "UNIVERSE_AT_CAP"
        assert result["http_status"] == 422

    def test_accepted_at_cap_with_replace_target(self):
        """S22.1.2 AC4: N==cap WITH replace_target → accepted, old pair displaced."""
        cfg = _make_config(universe_cap=3)
        rm = _make_rm(cfg)
        _seed_universe(DB_NAME, ["A/USD", "B/USD", "C/USD"])
        result = rm.validate_universe_proposal(
            pair="D/USD", classification="FOUNDATIONAL",
            replace_target="C/USD", replace_class="FOUNDATIONAL",
            n_current=3, projected_alpha=4.0,
            persona_config={}, psv_vector="D/USD|...",
            db_path=DB_NAME,
        )
        assert result["status"] == "approved"
        universe = _get_universe(DB_NAME)
        assert "D/USD" in universe
        assert "C/USD" not in universe

    def test_remove_pair_event_written_on_displacement(self):
        cfg = _make_config(universe_cap=3)
        rm = _make_rm(cfg)
        _seed_universe(DB_NAME, ["A/USD", "B/USD", "C/USD"])
        rm.validate_universe_proposal(
            pair="D/USD", classification="FOUNDATIONAL",
            replace_target="C/USD", replace_class="FOUNDATIONAL",
            n_current=3, projected_alpha=4.0,
            persona_config={}, psv_vector="D/USD|...",
            db_path=DB_NAME,
        )
        events = _get_events(DB_NAME)
        event_types = [e["event_type"] for e in events]
        assert "ADD_PAIR" in event_types
        assert "REMOVE_PAIR" in event_types
        remove_event = next(e for e in events if e["event_type"] == "REMOVE_PAIR")
        assert remove_event["pair"] == "C/USD"


# ── AC8: Alpha spread gate ────────────────────────────────────

class TestAlphaSpreadGate:
    def test_rejected_below_min_alpha(self):
        """S22.1.2 AC8: projected_alpha < min_alpha_pct → ALPHA_SPREAD_INSUFFICIENT."""
        cfg = _make_config(min_alpha=2.0)
        rm = _make_rm(cfg)
        result = rm.validate_universe_proposal(
            pair="XYZ/USD", classification="FOUNDATIONAL",
            replace_target=None, replace_class=None,
            n_current=5, projected_alpha=1.5,
            persona_config={}, psv_vector="XYZ/USD|...",
            db_path=DB_NAME,
        )
        assert result["status"] == "rejected"
        assert result["reason"] == "ALPHA_SPREAD_INSUFFICIENT"
        assert result["http_status"] == 422

    def test_accepted_above_min_alpha(self):
        cfg = _make_config(min_alpha=2.0)
        rm = _make_rm(cfg)
        result = rm.validate_universe_proposal(
            pair="XYZ/USD", classification="FOUNDATIONAL",
            replace_target=None, replace_class=None,
            n_current=5, projected_alpha=2.5,
            persona_config={}, psv_vector="XYZ/USD|...",
            db_path=DB_NAME,
        )
        assert result["status"] == "approved"

    def test_exact_min_alpha_rejected(self):
        """Border case: exactly equal to min_alpha is below (strict >)."""
        cfg = _make_config(min_alpha=2.0)
        rm = _make_rm(cfg)
        result = rm.validate_universe_proposal(
            pair="XYZ/USD", classification="FOUNDATIONAL",
            replace_target=None, replace_class=None,
            n_current=5, projected_alpha=2.0,
            persona_config={}, psv_vector="XYZ/USD|...",
            db_path=DB_NAME,
        )
        # 2.0 is NOT > 2.0 — should be rejected
        assert result["status"] == "rejected"
        assert result["reason"] == "ALPHA_SPREAD_INSUFFICIENT"
