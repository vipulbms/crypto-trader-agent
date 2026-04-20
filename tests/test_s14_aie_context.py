"""
Test suite for Sprint S4 — S14.2.3 (unfilled cluster context) and
S14.2.4 (persona system role injection).

Stories covered:
  S14.2.3  build_cycle_prompt receives unfilled_clusters and emits ## OPEN SECTORS ##
  S14.2.4  build_system_prompt produces a distinct, persona-aware system prompt

pytest: python -m pytest tests/test_s14_aie_context.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.agent.prompts import build_cycle_prompt, build_system_prompt, estimate_tokens


# ──────────────────────────────────────────────────────────────
# Helpers / fixtures
# ──────────────────────────────────────────────────────────────

def _minimal_portfolio(cash: float = 1000.0, open_pos: int = 0) -> dict:
    return {
        "total_usd":           cash,
        "available_cash_usd":  cash,
        "open_positions_count": open_pos,
        "daily_pnl_usd":       0.0,
        "daily_pnl_pct":       0.0,
        "open_positions":      [],
        "max_per_trade":       300.0,
    }


def _buy_signal(pair: str = "BTC/USD", score: int = 6) -> dict:
    return {
        "pair":      pair,
        "signal":    "BUY",
        "buy_score": score,
        "max_score": 28,
        "price":     50000.0,
        "pair_max_usd": 200.0,
        "indicators": {
            "rsi_14":        45.0,
            "adx_14":        28.0,
            "macd_histogram": 0.005,
            "bb_lower":      48000.0,
            "bb_upper":      52000.0,
        },
        "reasons": ["RSI oversold", "MACD turn"],
    }


def _conservative_persona() -> dict:
    return {
        "llm_system_role":       "conservative",
        "max_open_positions":    2,
        "max_position_pct":      0.15,
        "min_profit_floor_pct":  1.5,
        "momentum_bypass_rsi":   70,
        "momentum_bypass_adx":   999,
        "reallocation_enabled":  False,
        "reallocation_max_pct_6h": 0.0,
    }


def _medium_persona() -> dict:
    return {
        "llm_system_role":       "medium",
        "max_open_positions":    5,
        "max_position_pct":      0.25,
        "min_profit_floor_pct":  1.0,
        "momentum_bypass_rsi":   75,
        "momentum_bypass_adx":   25,
        "reallocation_enabled":  True,
        "reallocation_max_pct_6h": 0.20,
    }


def _high_persona() -> dict:
    return {
        "llm_system_role":       "high",
        "max_open_positions":    10,
        "max_position_pct":      0.30,
        "min_profit_floor_pct":  1.0,
        "momentum_bypass_rsi":   80,
        "momentum_bypass_adx":   25,
        "reallocation_enabled":  True,
        "reallocation_max_pct_6h": 0.30,
    }


# ──────────────────────────────────────────────────────────────
# S14.2.4 — build_system_prompt tests
# ──────────────────────────────────────────────────────────────

class TestBuildSystemPrompt:
    """AC1–AC5 for S14.2.4"""

    def test_conservative_contains_preservation_language(self):
        """AC1: conservative prompt mentions capital preservation / drawdown."""
        prompt = build_system_prompt(_conservative_persona())
        lower = prompt.lower()
        assert "capital preservation" in lower or "conservative" in lower or "drawdown" in lower

    def test_medium_contains_balanced_language(self):
        """AC2: medium prompt mentions balanced / momentum."""
        prompt = build_system_prompt(_medium_persona())
        lower = prompt.lower()
        assert "balanced" in lower or "medium" in lower or "sector rotation" in lower

    def test_high_contains_aggressive_language(self):
        """AC3: high prompt mentions alpha / aggressive / breakout."""
        prompt = build_system_prompt(_high_persona())
        lower = prompt.lower()
        assert "alpha" in lower or "aggressive" in lower or "breakout" in lower or "high" in lower

    def test_all_personas_include_shared_rules(self):
        """AC4: every persona prompt includes the hard rules block."""
        for persona in (_conservative_persona(), _medium_persona(), _high_persona()):
            prompt = build_system_prompt(persona)
            assert "HARD RULES" in prompt
            assert "kill_switch" in prompt or "kill switch" in prompt.lower() or "kill_switch=1" in prompt

    def test_all_prompts_within_400_tokens(self):
        """AC5: no persona system prompt exceeds 400 estimated tokens."""
        for persona in (_conservative_persona(), _medium_persona(), _high_persona()):
            prompt = build_system_prompt(persona)
            tokens = estimate_tokens(prompt)
            assert tokens <= 400, (
                f"System prompt for role={persona['llm_system_role']} is {tokens} tokens (limit 400)"
            )

    def test_three_personas_produce_distinct_prompts(self):
        """AC6: all three personas produce different text."""
        p_cons = build_system_prompt(_conservative_persona())
        p_med  = build_system_prompt(_medium_persona())
        p_high = build_system_prompt(_high_persona())
        assert p_cons != p_med
        assert p_med  != p_high
        assert p_cons != p_high

    def test_unknown_role_falls_back_to_medium(self):
        """AC7: unknown llm_system_role key falls back gracefully — doesn't raise."""
        persona = dict(_medium_persona(), llm_system_role="unknown_role")
        prompt = build_system_prompt(persona)
        assert len(prompt) > 50  # non-empty fallback

    def test_empty_persona_config_does_not_raise(self):
        """AC8: empty dict falls back without crashing."""
        prompt = build_system_prompt({})
        assert len(prompt) > 20


# ──────────────────────────────────────────────────────────────
# S14.2.3 — build_cycle_prompt + unfilled_clusters tests
# ──────────────────────────────────────────────────────────────

class TestBuildCyclePromptUnfilledClusters:
    """AC1–AC5 for S14.2.3"""

    def test_open_sectors_block_present_when_clusters_have_slots(self):
        """AC1: unfilled_clusters list → ## OPEN SECTORS ## emitted."""
        prompt = build_cycle_prompt(
            cycle_time="2026-01-01 12:00:00",
            portfolio=_minimal_portfolio(),
            signals=[_buy_signal()],
            unfilled_clusters=["L1_alts", "meme"],
        )
        assert "## OPEN SECTORS ##" in prompt

    def test_cluster_names_appear_in_prompt(self):
        """AC2: each cluster name appears in the open sectors block."""
        clusters = ["L1_alts", "solana_meme", "eth_l2"]
        prompt = build_cycle_prompt(
            cycle_time="2026-01-01 12:00:00",
            portfolio=_minimal_portfolio(),
            signals=[_buy_signal()],
            unfilled_clusters=clusters,
        )
        for c in clusters:
            assert c in prompt, f"Cluster '{c}' not found in prompt"

    def test_capacity_message_when_clusters_none(self):
        """AC3: None → 'all sector clusters at capacity' message (case-insensitive)."""
        prompt = build_cycle_prompt(
            cycle_time="2026-01-01 12:00:00",
            portfolio=_minimal_portfolio(),
            signals=[_buy_signal()],
            unfilled_clusters=None,
        )
        assert "## OPEN SECTORS ##" in prompt
        assert "capacity" in prompt.lower()

    def test_capacity_message_when_clusters_empty_list(self):
        """AC4: empty list → same capacity message."""
        prompt = build_cycle_prompt(
            cycle_time="2026-01-01 12:00:00",
            portfolio=_minimal_portfolio(),
            signals=[_buy_signal()],
            unfilled_clusters=[],
        )
        assert "capacity" in prompt.lower()

    def test_risk_constraints_block_present(self):
        """AC5: ## RISK CONSTRAINTS ## block present in every prompt."""
        prompt = build_cycle_prompt(
            cycle_time="2026-01-01 12:00:00",
            portfolio=_minimal_portfolio(),
            signals=[_buy_signal()],
        )
        assert "## RISK CONSTRAINTS ##" in prompt

    def test_current_portfolio_block_present(self):
        """AC6: ## CURRENT PORTFOLIO ## block always present."""
        prompt = build_cycle_prompt(
            cycle_time="2026-01-01 12:00:00",
            portfolio=_minimal_portfolio(),
            signals=[],
        )
        assert "## CURRENT PORTFOLIO ##" in prompt

    def test_hold_signals_omitted_from_prompt(self):
        """AC7: HOLD-signal pairs are not emitted in the ## SIGNALS ## block."""
        signals = [
            _buy_signal("BTC/USD"),
            {"pair": "ETH/USD", "signal": "HOLD", "buy_score": 3, "max_score": 28, "price": 3000.0, "indicators": {}},
        ]
        prompt = build_cycle_prompt(
            cycle_time="2026-01-01 12:00:00",
            portfolio=_minimal_portfolio(),
            signals=signals,
        )
        # BTC should appear (BUY signal)
        assert "BTC/USD" in prompt
        # If ETH/USD appears in ## SIGNALS ##, it must only be in the PORTFOLIO block
        # The SIGNALS block must not contain a HOLD pair's signal line
        if "## SIGNALS ##" in prompt:
            signals_section = prompt.split("## SIGNALS ##")[1]
            # ETH should not have a score line in signals section (it's HOLD)
            assert f"pair|ETH/USD" not in signals_section

    def test_prompt_token_estimate_well_under_limit(self):
        """AC8: simple prompt for single BUY fits under 2,000 tokens."""
        prompt = build_cycle_prompt(
            cycle_time="2026-01-01 12:00:00",
            portfolio=_minimal_portfolio(),
            signals=[_buy_signal()],
        )
        assert estimate_tokens(prompt) < 2000
