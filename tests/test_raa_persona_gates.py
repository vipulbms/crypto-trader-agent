"""
test_raa_persona_gates.py — S22.3.1 persona filtering for RAA

Tests:
  - Medium gate: rejects RSI out-of-band, rejects ADX too high
  - Medium gate: accepts valid RSI+ADX
  - High gate: rejects oversold RSI without bypass conditions
  - High gate: RSI bypass fires with ADX > 35 + vwma_slope > 0 (AC5)
  - High gate: prune eligibility (ADX < 15 for > 12 cycles)
  - Medium prune eligibility: is_prune_eligible_medium correctly flags long ranging pairs
"""
import uuid

import pytest

from src.storage.database import init_paper_db
from src.runtime.research_analyst import (
    apply_medium_persona_gate,
    apply_high_persona_gate,
    get_high_persona_prune_candidate,
    is_prune_eligible_medium,
)

DB_NAME = f"test_raa_pg_{uuid.uuid4().hex[:8]}.db"


@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    import src.storage.database as db_mod
    _orig = db_mod.DATA_DIR_PATH
    db_mod.DATA_DIR_PATH = str(tmp_path)
    init_paper_db(DB_NAME)
    yield
    db_mod.DATA_DIR_PATH = _orig


# ── default config for gates ─────────────────────────────────

def _medium_raa_cfg():
    return {
        "persona_gates": {
            "medium": {
                "rsi_min": 35,
                "rsi_max": 65,
                "adx_max": 25,
                "prune_adx_threshold": 15,
                "prune_consecutive_cycles": 12,
            }
        }
    }


def _high_raa_cfg():
    return {
        "persona_gates": {
            "high": {
                "rsi_max": 85,
                "rsi_bypass_adx_min": 35,
                "rsi_bypass_requires_vwma_slope": True,
                "aggressive_prune_score_threshold": 8,
                "position_size_pct": 3.0,
            }
        }
    }


# ── Medium persona gate ───────────────────────────────────────

class TestMediumPersonaGate:
    def test_accepts_valid_rsi_and_adx(self):
        reason = apply_medium_persona_gate("SOL/USD", rsi=50, adx=20, raa_cfg=_medium_raa_cfg())
        assert reason is None

    def test_rejects_rsi_too_low(self):
        reason = apply_medium_persona_gate("SOL/USD", rsi=30, adx=20, raa_cfg=_medium_raa_cfg())
        assert reason == "MEDIUM_RSI_GATE"

    def test_rejects_rsi_too_high(self):
        reason = apply_medium_persona_gate("SOL/USD", rsi=70, adx=20, raa_cfg=_medium_raa_cfg())
        assert reason == "MEDIUM_RSI_GATE"

    def test_rejects_adx_too_high(self):
        reason = apply_medium_persona_gate("SOL/USD", rsi=50, adx=30, raa_cfg=_medium_raa_cfg())
        assert reason == "MEDIUM_ADX_GATE"

    def test_boundary_rsi_min_excluded(self):
        reason = apply_medium_persona_gate("SOL/USD", rsi=35, adx=20, raa_cfg=_medium_raa_cfg())
        # rsi=35 is exactly at rsi_min — the gate is rsi_min ≤ rsi ≤ rsi_max, so it should PASS
        assert reason is None

    def test_boundary_adx_max_excluded(self):
        # adx=25 is exactly at adx_max — the gate is adx < adx_max (strict), should REJECT
        reason = apply_medium_persona_gate("SOL/USD", rsi=50, adx=25, raa_cfg=_medium_raa_cfg())
        assert reason == "MEDIUM_ADX_GATE"

    def test_none_adx_passes_adx_gate(self):
        """If ADX not available, gate should not block on ADX alone."""
        reason = apply_medium_persona_gate("SOL/USD", rsi=50, adx=None, raa_cfg=_medium_raa_cfg())
        assert reason is None


# ── High persona gate ─────────────────────────────────────────

class TestHighPersonaGate:
    def test_accepts_valid_rsi(self):
        reason = apply_high_persona_gate(
            "BTC/USD", rsi=60, adx=20, vwma_slope=0.1, raa_cfg=_high_raa_cfg()
        )
        assert reason is None

    def test_rejects_rsi_above_max(self):
        reason = apply_high_persona_gate(
            "BTC/USD", rsi=90, adx=20, vwma_slope=0.1, raa_cfg=_high_raa_cfg()
        )
        assert reason == "HIGH_RSI_GATE"

    def test_rsi_bypass_fires_with_adx_and_positive_slope(self):
        """AC5: rsi > rsi_max BUT adx > 35 AND vwma_slope > 0 → bypass, no rejection."""
        reason = apply_high_persona_gate(
            "ETH/USD", rsi=88, adx=40, vwma_slope=0.05, raa_cfg=_high_raa_cfg()
        )
        assert reason is None

    def test_rsi_bypass_fails_without_positive_vwma_slope(self):
        """AC5: adx > 35 but vwma_slope <= 0 → bypass does NOT fire."""
        reason = apply_high_persona_gate(
            "ETH/USD", rsi=88, adx=40, vwma_slope=-0.01, raa_cfg=_high_raa_cfg()
        )
        assert reason == "HIGH_RSI_GATE"

    def test_rsi_bypass_fails_with_low_adx(self):
        """AC5: adx < 35 → bypass does NOT fire."""
        reason = apply_high_persona_gate(
            "ETH/USD", rsi=88, adx=30, vwma_slope=0.1, raa_cfg=_high_raa_cfg()
        )
        assert reason == "HIGH_RSI_GATE"

    def test_rsi_bypass_disabled_by_config(self):
        """When rsi_bypass_requires_vwma_slope=False, bypass triggers on ADX only."""
        cfg = {
            "persona_gates": {
                "high": {
                    "rsi_max": 85,
                    "rsi_bypass_adx_min": 35,
                    "rsi_bypass_requires_vwma_slope": False,
                    "aggressive_prune_score_threshold": 8,
                    "position_size_pct": 3.0,
                }
            }
        }
        reason = apply_high_persona_gate(
            "ETH/USD", rsi=88, adx=40, vwma_slope=None, raa_cfg=cfg
        )
        assert reason is None  # ADX alone is enough when flag=False


# ── Prune eligibility ─────────────────────────────────────────

class TestPruneEligibility:
    def test_is_prune_eligible_medium_true(self):
        """ADX below threshold for > min_cycles → eligible."""
        history = [12.0] * 15  # 15 cycles all below 15
        assert is_prune_eligible_medium("SOL/USD", history, _medium_raa_cfg()) is True

    def test_is_prune_eligible_medium_false_recent_high(self):
        """Recent ADX spike above threshold → not eligible."""
        history = [12.0] * 10 + [20.0, 25.0, 30.0]
        assert is_prune_eligible_medium("SOL/USD", history, _medium_raa_cfg()) is False

    def test_is_prune_eligible_medium_not_enough_cycles(self):
        """Fewer than prune_consecutive_cycles of low ADX → not eligible."""
        history = [10.0] * 8  # only 8 consecutive
        assert is_prune_eligible_medium("SOL/USD", history, _medium_raa_cfg()) is False

    def test_get_high_persona_prune_candidate_returns_weakest(self):
        """Returns pair with lowest score below aggressive_prune_score_threshold."""
        universe = [
            {"pair": "SOL/USD", "latest_score": 10},
            {"pair": "LINK/USD", "latest_score": 5},
            {"pair": "BTC/USD", "latest_score": 3},
        ]
        candidate = get_high_persona_prune_candidate(universe, incoming_score=9, raa_cfg=_high_raa_cfg())
        # BTC/USD has the lowest score < 8 threshold
        assert candidate == "BTC/USD"

    def test_get_high_persona_prune_candidate_no_weak_pair(self):
        """All pairs have score >= threshold → no prune candidate."""
        universe = [
            {"pair": "SOL/USD", "latest_score": 12},
            {"pair": "ETH/USD", "latest_score": 9},
        ]
        candidate = get_high_persona_prune_candidate(universe, incoming_score=10, raa_cfg=_high_raa_cfg())
        assert candidate is None

    def test_prune_candidate_not_returned_if_incoming_score_low(self):
        """If incoming_score <= threshold, no prune (not worth displacing)."""
        universe = [
            {"pair": "SOL/USD", "latest_score": 4},
        ]
        # incoming=7 is below threshold=8 — RAA should not prune
        candidate = get_high_persona_prune_candidate(universe, incoming_score=7, raa_cfg=_high_raa_cfg())
        assert candidate is None
