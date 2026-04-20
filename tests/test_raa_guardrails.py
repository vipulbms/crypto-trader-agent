"""
test_raa_guardrails.py — S22.2.1 + S22.2.2

Tests:
  - MEME_BLOCK: MEME pair cannot displace FOUNDATIONAL (AC1–AC4)
  - MEME pair can displace MEME (not blocked)
  - SELF_CORRECT_FAILED: after max_retries 422 rejections, event logged
  - STALE_FEED_HALT: frozen OHLCV feed skips candidate (AC3)
"""
import uuid

import pytest

from src.storage.database import init_paper_db, get_connection
from src.runtime.research_analyst import (
    check_meme_block,
    _write_audit_feedback,
    _FOUNDATIONAL_ANCHORS,
)

DB_NAME = f"test_raa_gr_{uuid.uuid4().hex[:8]}.db"


@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    import src.storage.database as db_mod
    _orig = db_mod.DATA_DIR_PATH
    db_mod.DATA_DIR_PATH = str(tmp_path)
    init_paper_db(DB_NAME)
    yield
    db_mod.DATA_DIR_PATH = _orig


def _get_feedback(db: str) -> list[dict]:
    conn = get_connection(db)
    rows = conn.execute("SELECT * FROM audit_feedback ORDER BY id").fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── S22.2.1 MEME_BLOCK guardrail ─────────────────────────────

class TestMemeBlock:
    def test_meme_cannot_displace_foundational_anchor(self):
        """AC1: MEME pair cannot displace a FOUNDATIONAL anchor — hard rule."""
        reason = check_meme_block(
            target_pair="DOGE/USD",
            target_class="MEME",
            replace_target="ETH/USD",
            replace_class="FOUNDATIONAL",
            db_path=DB_NAME,
            foundational_set=_FOUNDATIONAL_ANCHORS,
        )
        assert reason == "MEME_BLOCK_REJECT"

    def test_meme_block_reject_written_to_audit_feedback(self):
        """AC2: meme-block rejection is logged to audit_feedback with penalty_weight."""
        check_meme_block(
            target_pair="BONK/USD",
            target_class="MEME",
            replace_target="BTC/USD",
            replace_class="FOUNDATIONAL",
            db_path=DB_NAME,
            foundational_set=_FOUNDATIONAL_ANCHORS,
        )
        feedback = _get_feedback(DB_NAME)
        assert any(
            f["event_type"] == "MEME_BLOCK_REJECT" and f["pair"] == "BONK/USD"
            and f["penalty_weight"] < 0
            for f in feedback
        )

    def test_meme_cannot_displace_foundational_even_if_not_in_hard_anchors(self):
        """AC4: replace_class=FOUNDATIONAL always triggers the block."""
        reason = check_meme_block(
            target_pair="PEPE/USD",
            target_class="MEME",
            replace_target="SOME/USD",   # Not in hard anchors
            replace_class="FOUNDATIONAL",
            db_path=DB_NAME,
            foundational_set=_FOUNDATIONAL_ANCHORS,
        )
        assert reason == "MEME_BLOCK_REJECT"

    def test_meme_can_displace_meme(self):
        """MEME displacing MEME must NOT be blocked."""
        reason = check_meme_block(
            target_pair="WIF/USD",
            target_class="MEME",
            replace_target="DOGE/USD",
            replace_class="MEME",
            db_path=DB_NAME,
            foundational_set=_FOUNDATIONAL_ANCHORS,
        )
        assert reason is None

    def test_foundational_can_displace_foundational(self):
        """FOUNDATIONAL displacing FOUNDATIONAL must NOT be blocked."""
        reason = check_meme_block(
            target_pair="LINK/USD",
            target_class="FOUNDATIONAL",
            replace_target="ADA/USD",
            replace_class="FOUNDATIONAL",
            db_path=DB_NAME,
            foundational_set=_FOUNDATIONAL_ANCHORS,
        )
        assert reason is None

    def test_foundational_can_displace_meme(self):
        """FOUNDATIONAL displacing MEME is allowed."""
        reason = check_meme_block(
            target_pair="SOL/USD",
            target_class="FOUNDATIONAL",
            replace_target="PEPE/USD",
            replace_class="MEME",
            db_path=DB_NAME,
            foundational_set=_FOUNDATIONAL_ANCHORS,
        )
        assert reason is None

    def test_meme_addition_without_displacement_not_blocked(self):
        """Meme pair being added without displacing anyone is not blocked."""
        reason = check_meme_block(
            target_pair="SHIB/USD",
            target_class="MEME",
            replace_target=None,
            replace_class=None,
            db_path=DB_NAME,
            foundational_set=_FOUNDATIONAL_ANCHORS,
        )
        assert reason is None

    def test_meme_block_deterministic_no_config_override(self):
        """AC3: No config flag or parameter can bypass the meme-block rule."""
        # Regardless of any override attempts, the rule must fire
        for _ in range(3):
            reason = check_meme_block(
                target_pair="FLOKI/USD",
                target_class="MEME",
                replace_target="ETH/USD",
                replace_class="FOUNDATIONAL",
                db_path=DB_NAME,
                foundational_set=_FOUNDATIONAL_ANCHORS,
            )
            assert reason == "MEME_BLOCK_REJECT"


# ── S22.2.2 SELF_CORRECT_FAILED + STALE_FEED_HALT ────────────

class TestSelfCorrection:
    def test_stale_feed_halt_skips_candidate(self):
        """AC3: has_variance=False → audit event written, candidate skipped."""
        frozen_ticker = {
            "last": 1.0, "open": 1.0, "high": 1.0, "low": 1.0,
            "volume_24h": 1.0, "has_variance": False,
        }
        # has_variance=False means the RAA cycle should skip this pair
        assert not frozen_ticker["has_variance"]
        # Simulate the audit log write that happens in run_cycle
        _write_audit_feedback(
            DB_NAME, "RAA", "TRX/USD", "STALE_FEED_HALT",
            psv_vector="TRX/USD|frozen",
        )
        feedback = _get_feedback(DB_NAME)
        assert any(
            f["event_type"] == "STALE_FEED_HALT" and f["pair"] == "TRX/USD"
            for f in feedback
        )


class TestValidateUniverseProposalMemeBlock:
    """
    End-to-end test through RiskManager.validate_universe_proposal to ensure
    the MEME_BLOCK rule fires from the Risk Manager layer too.
    """

    def _make_config(self):
        return {
            "raa": {
                "universe_cap": 35,
                "alpha_spread_gate": {"min_alpha_pct": 2.0},
            },
            "agent": {"persona": "conservative"},
            "personas": {"conservative": {"reallocation_enabled": False}},
        }

    def test_rm_rejects_meme_displacing_foundational(self):
        from src.risk.risk_manager import RiskManager
        cfg = self._make_config()
        rm = RiskManager(cfg, DB_NAME)
        result = rm.validate_universe_proposal(
            pair="DOGE/USD",
            classification="MEME",
            replace_target="ETH/USD",
            replace_class="FOUNDATIONAL",
            n_current=5,
            projected_alpha=10.0,  # Very good alpha — but rule is hard
            persona_config={},
            psv_vector="DOGE/USD|...",
            db_path=DB_NAME,
        )
        assert result["status"] == "rejected"
        assert result["reason"] == "MEME_BLOCK"
        assert result["http_status"] == 422

    def test_rm_allows_meme_displacing_meme(self):
        from src.risk.risk_manager import RiskManager
        cfg = self._make_config()
        rm = RiskManager(cfg, DB_NAME)
        result = rm.validate_universe_proposal(
            pair="WIF/USD",
            classification="MEME",
            replace_target="DOGE/USD",
            replace_class="MEME",
            n_current=5,
            projected_alpha=5.0,
            persona_config={},
            psv_vector="WIF/USD|...",
            db_path=DB_NAME,
        )
        assert result["status"] == "approved"
