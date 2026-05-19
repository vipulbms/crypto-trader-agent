"""
Tests for per-cycle persona injection into CycleContext and RiskManager.

Story: S12.1.2 — Persona runtime injection into CycleContext (AC5)
Sprint: S1 | Epic: E12 — Persona Framework

Verifies:
  1. CycleContext.from_config() correctly picks up the active persona from config.
  2. RiskManager.apply_persona_config() updates the three persona-driven thresholds.
  3. Switching personas mid-run produces the correct thresholds each time.
  4. buy_min_score, max_open_positions, max_position_pct, min_profit_floor_pct
     resolve correctly for each of the three canonical personas.
  5. Conservative baseline matches v2 production defaults (sprint gate criterion).
"""

import uuid

import pytest

from src.core.cycle_context import CycleContext
from src.risk.risk_manager import RiskManager


# ---------------------------------------------------------------------------
# Shared test fixtures
# ---------------------------------------------------------------------------

_CONSERVATIVE_PROFILE = {
    "buy_min_score": 5,
    "max_open_positions": 10,
    "max_position_pct": 30,
    "min_profit_floor_pct": 1.0,
    "rsi_overbought_veto": 70,
    "momentum_bypass_rsi": 65,
    "momentum_bypass_adx": 0,
    "reallocation_enabled": False,
    "llm_temperature": 0.0,
    "llm_max_tokens": 1024,
    "llm_system_role": "standard",
    "velocity_circuit_breaker_pct": 3.0,
    "velocity_halt_hours": 4,
}

_MEDIUM_PROFILE = {
    "buy_min_score": 6,
    "max_open_positions": 10,
    "max_position_pct": 30,
    "min_profit_floor_pct": 1.0,
    "rsi_overbought_veto": 72,
    "momentum_bypass_rsi": 60,
    "momentum_bypass_adx": 25,
    "reallocation_enabled": True,
    "llm_temperature": 0.1,
    "llm_max_tokens": 2048,
    "llm_system_role": "standard",
    "velocity_circuit_breaker_pct": 5.0,
    "velocity_halt_hours": 2,
}

_HIGH_PROFILE = {
    "buy_min_score": 5,
    "max_open_positions": 10,
    "max_position_pct": 30,
    "min_profit_floor_pct": 0.5,
    "rsi_overbought_veto": 75,
    "momentum_bypass_rsi": 55,
    "momentum_bypass_adx": 30,
    "reallocation_enabled": True,
    "llm_temperature": 0.2,
    "llm_max_tokens": 2048,
    "llm_system_role": "aggressive",
    "velocity_circuit_breaker_pct": 7.0,
    "velocity_halt_hours": 1,
}


def _make_config(active_persona: str) -> dict:
    """Build a minimal config with the given active persona."""
    return {
        "agent": {"persona": active_persona, "concurrent_mode": False},
        "personas": {
            "conservative": _CONSERVATIVE_PROFILE,
            "medium": _MEDIUM_PROFILE,
            "high": _HIGH_PROFILE,
        },
        "trading": {
            "pairs": [],
            "take_profit_pct": 12,
            "max_open_positions": 10,
            "max_position_pct": 30,
            "min_profit_floor_pct": 1.0,
        },
        "risk": {"min_cash_reserve_pct": 5.0, "min_order_usd": 20.0},
    }


def _make_risk_manager(config: dict) -> RiskManager:
    return RiskManager(config)


def _new_cycle_id() -> str:
    return uuid.uuid4().hex[:8]


# ---------------------------------------------------------------------------
# CycleContext.from_config() — persona resolution
# ---------------------------------------------------------------------------

class TestCycleContextFromConfig:
    """CycleContext.from_config() must read agent.persona and expose the profile."""

    def test_conservative_persona_resolved(self):
        ctx = CycleContext.from_config(_make_config("conservative"), _new_cycle_id())
        assert ctx.persona == "conservative"

    def test_medium_persona_resolved(self):
        ctx = CycleContext.from_config(_make_config("medium"), _new_cycle_id())
        assert ctx.persona == "medium"

    def test_high_persona_resolved(self):
        ctx = CycleContext.from_config(_make_config("high"), _new_cycle_id())
        assert ctx.persona == "high"

    def test_persona_config_populated(self):
        ctx = CycleContext.from_config(_make_config("conservative"), _new_cycle_id())
        assert isinstance(ctx.persona_config, dict)
        assert len(ctx.persona_config) >= 13

    def test_persona_config_matches_profile(self):
        ctx = CycleContext.from_config(_make_config("medium"), _new_cycle_id())
        assert ctx.persona_config["buy_min_score"] == _MEDIUM_PROFILE["buy_min_score"]
        assert ctx.persona_config["llm_temperature"] == _MEDIUM_PROFILE["llm_temperature"]


# ---------------------------------------------------------------------------
# Convenience property access
# ---------------------------------------------------------------------------

class TestCycleContextProperties:
    """Convenience properties must return values from the embedded persona_config."""

    def test_buy_min_score_conservative(self):
        ctx = CycleContext.from_config(_make_config("conservative"), _new_cycle_id())
        assert ctx.buy_min_score == 5

    def test_buy_min_score_medium(self):
        ctx = CycleContext.from_config(_make_config("medium"), _new_cycle_id())
        assert ctx.buy_min_score == 6

    def test_min_profit_floor_high(self):
        """High persona has a lower profit floor (0.5%)."""
        ctx = CycleContext.from_config(_make_config("high"), _new_cycle_id())
        assert ctx.min_profit_floor_pct == pytest.approx(0.5)

    def test_min_profit_floor_conservative(self):
        ctx = CycleContext.from_config(_make_config("conservative"), _new_cycle_id())
        assert ctx.min_profit_floor_pct == pytest.approx(1.0)

    def test_llm_temperature_conservative_is_zero(self):
        """Conservative uses deterministic temperature 0 for reproducibility."""
        ctx = CycleContext.from_config(_make_config("conservative"), _new_cycle_id())
        assert ctx.llm_temperature == pytest.approx(0.0)

    def test_llm_max_tokens_high(self):
        ctx = CycleContext.from_config(_make_config("high"), _new_cycle_id())
        assert ctx.llm_max_tokens == 2048

    def test_reallocation_enabled_conservative_false(self):
        ctx = CycleContext.from_config(_make_config("conservative"), _new_cycle_id())
        assert ctx.reallocation_enabled is False

    def test_reallocation_enabled_medium_true(self):
        ctx = CycleContext.from_config(_make_config("medium"), _new_cycle_id())
        assert ctx.reallocation_enabled is True


# ---------------------------------------------------------------------------
# RiskManager.apply_persona_config() — threshold injection
# ---------------------------------------------------------------------------

class TestApplyPersonaConfig:
    """apply_persona_config() must update RiskManager internal thresholds each cycle."""

    def test_apply_conservative_max_open(self):
        risk = _make_risk_manager(_make_config("conservative"))
        risk.apply_persona_config(_CONSERVATIVE_PROFILE, persona_name="conservative")
        assert risk._max_open_positions == 10

    def test_apply_medium_buy_score_not_in_risk_manager(self):
        """buy_min_score lives in signals.py; apply_persona_config ignores unknown keys."""
        risk = _make_risk_manager(_make_config("medium"))
        # Should not raise even though buy_min_score is not a RiskManager field
        risk.apply_persona_config(_MEDIUM_PROFILE, persona_name="medium")

    def test_apply_high_min_profit_floor(self):
        """High persona relaxes the profit floor to 0.5%."""
        risk = _make_risk_manager(_make_config("high"))
        risk.apply_persona_config(_HIGH_PROFILE, persona_name="high")
        assert risk._min_profit_floor_pct == pytest.approx(0.5)

    def test_apply_conservative_min_profit_floor(self):
        risk = _make_risk_manager(_make_config("conservative"))
        risk.apply_persona_config(_CONSERVATIVE_PROFILE, persona_name="conservative")
        assert risk._min_profit_floor_pct == pytest.approx(1.0)

    def test_apply_max_position_pct_updated(self):
        risk = _make_risk_manager(_make_config("conservative"))
        custom = {**_CONSERVATIVE_PROFILE, "max_position_pct": 20}
        risk.apply_persona_config(custom, persona_name="conservative")
        assert risk._max_position_pct == pytest.approx(20.0)

    def test_apply_converts_strings_to_numeric_types(self):
        """apply_persona_config must coerce string values (e.g. from YAML env override)."""
        risk = _make_risk_manager(_make_config("conservative"))
        risk.apply_persona_config({
            "max_open_positions": "7",
            "max_position_pct": "25.0",
            "min_profit_floor_pct": "0.8",
        }, persona_name="conservative")
        assert risk._max_open_positions == 7
        assert risk._max_position_pct == pytest.approx(25.0)
        assert risk._min_profit_floor_pct == pytest.approx(0.8)


# ---------------------------------------------------------------------------
# Persona switch mid-run (sprint gate criterion)
# ---------------------------------------------------------------------------

class TestPersonaMidRunSwitch:
    """
    Sprint S1 gate: switching persona mid-run applies correct thresholds each cycle.
    Conservative baseline must equal v2 production defaults.
    """

    def test_conservative_then_high_switches_floor(self):
        """Simulates two consecutive cycles with different personas."""
        risk = _make_risk_manager(_make_config("conservative"))

        # Cycle 1 — conservative
        ctx1 = CycleContext.from_config(_make_config("conservative"), _new_cycle_id())
        risk.apply_persona_config(ctx1.persona_config, persona_name="conservative")
        assert risk._min_profit_floor_pct == pytest.approx(1.0)

        # Cycle 2 — high
        ctx2 = CycleContext.from_config(_make_config("high"), _new_cycle_id())
        risk.apply_persona_config(ctx2.persona_config, persona_name="high")
        assert risk._min_profit_floor_pct == pytest.approx(0.5)

    def test_high_then_conservative_restores_floor(self):
        """Switching back to conservative resets to v2 production baseline."""
        risk = _make_risk_manager(_make_config("high"))
        risk.apply_persona_config(_HIGH_PROFILE, persona_name="high")
        assert risk._min_profit_floor_pct == pytest.approx(0.5)

        risk.apply_persona_config(_CONSERVATIVE_PROFILE, persona_name="conservative")
        assert risk._min_profit_floor_pct == pytest.approx(1.0)

    def test_conservative_matches_v2_production_defaults(self):
        """
        Sprint gate: conservative persona MUST be behaviourally identical to v2.

        v2 production values (from _V2_PRODUCTION_DEFAULTS in test_persona_config_loading.py):
          min_profit_floor_pct = 1.0
          max_open_positions   = 10
          max_position_pct     = 30
          buy_min_score        = 5
          llm_temperature      = 0 (deterministic)
        """
        ctx = CycleContext.from_config(_make_config("conservative"), _new_cycle_id())

        assert ctx.buy_min_score == 5,           "buy_min_score must match v2 default"
        assert ctx.max_open_positions == 10,     "max_open_positions must match v2 default"
        assert ctx.max_position_pct == 30,       "max_position_pct must match v2 default"
        assert ctx.min_profit_floor_pct == pytest.approx(1.0), "min_profit_floor_pct must match v2 default"
        assert ctx.llm_temperature == pytest.approx(0.0),      "llm_temperature must be 0 (deterministic)"
