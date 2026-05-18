"""
Tests for S12.1.1 — Persona config schema in config.yaml.

Story: S12.1.1 | Sprint: S1 | Epic: E12 — Persona Framework

Covers AC1–AC5:
  AC1: config.yaml has agent.persona + personas block with all three profiles
  AC2: Each profile contains all 13 required keys
  AC3: conservative values match current v2 production defaults exactly
  AC4: Missing persona profile keys raise ValueError at startup (validate_config)
  AC5: Unit tests — loads all profiles; asserts key presence; asserts conservative = defaults
"""
import copy
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import yaml

from src.risk.risk_manager import validate_config

# ── v2 production defaults fixture (AC3) ─────────────────────────────────────
# These are the canonical v2 values that conservative persona MUST match.
# Update this fixture if any v2 default changes — the test will then catch
# any conservative profile that has drifted from parity.
_V2_PRODUCTION_DEFAULTS = {
    "buy_min_score": 5,
    "max_open_positions": 10,
    "max_position_pct": 30,
    "min_profit_floor_pct": 1.0,
    "rsi_overbought_veto": 70,
    "momentum_bypass_rsi": 70,
    "momentum_bypass_adx": 999,
    "reallocation_enabled": False,
    "reallocation_max_pct_6h": 0.0,
    "llm_temperature": 0,
    "llm_max_tokens": 1024,
    "llm_system_role": "conservative",
    "velocity_circuit_breaker_pct": 3.0,
    "velocity_halt_hours": 4,
    # S15 keys (added Sprint S5)
    "pf_escalation_momentum_suspend": False,
    "early_momentum_score_reduction": 0,
    "early_momentum_rsi_min": 50,
    "early_momentum_rsi_max": 65,
    "early_momentum_adx_min": 999,
}

_REQUIRED_PERSONA_KEYS = set(_V2_PRODUCTION_DEFAULTS.keys())

_VALID_PERSONAS = ["conservative", "medium", "high"]


# ── minimal valid config factory ─────────────────────────────────────────────

def _minimal_config() -> dict:
    """Return a minimal config dict that passes validate_config()."""
    return {
        "agent": {"persona": "conservative", "concurrent_mode": False},
        "personas": {
            name: dict(_V2_PRODUCTION_DEFAULTS)  # same structure, values may differ
            for name in _VALID_PERSONAS
        },
        "trading": {
            "take_profit_pct": 8,
            "allowed_take_profit_pcts": [5, 8, 12, 16, 20, 25],
            "max_open_positions": 10,
            "max_position_pct": 20,
        },
        "risk": {"min_cash_reserve_pct": 5},
        "trailing_stop": {"enabled": False},
        "breakeven_stop": {"enabled": False},
    }


class TestPersonaConfigSchemaFromFile(unittest.TestCase):
    """AC1 + AC2 + AC3 — load real config.yaml and validate structure."""

    @classmethod
    def setUpClass(cls):
        config_path = os.path.join(os.path.dirname(__file__), "..", "config.yaml")
        with open(config_path) as f:
            cls.config = yaml.safe_load(f)

    def test_agent_persona_key_present(self):
        """AC1: config.yaml has agent.persona."""
        self.assertIn("agent", self.config)
        self.assertIn("persona", self.config["agent"])

    def test_agent_persona_valid_value(self):
        """AC1: agent.persona value is one of conservative | medium | high."""
        persona = self.config["agent"]["persona"]
        self.assertIn(persona, _VALID_PERSONAS, f"Unknown persona: {persona}")

    def test_concurrent_mode_key_present(self):
        """AC1: config.yaml has agent.concurrent_mode."""
        self.assertIn("concurrent_mode", self.config["agent"])

    def test_personas_block_present(self):
        """AC1: config.yaml has personas block."""
        self.assertIn("personas", self.config)

    def test_all_three_profiles_present(self):
        """AC1: All three persona profiles exist."""
        for name in _VALID_PERSONAS:
            self.assertIn(name, self.config["personas"],
                          f"Missing persona profile: {name}")

    def test_all_profiles_have_required_keys(self):
        """AC2: Each profile contains all 13 required keys."""
        for persona in _VALID_PERSONAS:
            profile = self.config["personas"][persona]
            for key in _REQUIRED_PERSONA_KEYS:
                self.assertIn(key, profile,
                              f"Profile '{persona}' missing key: {key}")

    def test_conservative_matches_v2_defaults(self):
        """AC3: conservative persona values match current v2 production configuration exactly."""
        conservative = self.config["personas"]["conservative"]
        for key, expected in _V2_PRODUCTION_DEFAULTS.items():
            self.assertEqual(
                conservative[key], expected,
                f"conservative.{key} = {conservative[key]!r}, "
                f"expected v2 default = {expected!r}"
            )

    def test_validate_config_passes_on_real_config(self):
        """AC4: validate_config() passes without error on the real config.yaml."""
        try:
            validate_config(self.config)
        except (ValueError, Exception) as e:
            self.fail(f"validate_config() raised on valid config.yaml: {e}")


class TestPersonaValidationErrors(unittest.TestCase):
    """AC4 — validate_config() raises ValueError on missing/invalid persona data."""

    def test_missing_personas_block_raises(self):
        """AC4: Missing personas block raises ValueError."""
        cfg = _minimal_config()
        del cfg["personas"]
        with self.assertRaises(ValueError, msg="Should raise when personas block absent"):
            validate_config(cfg)

    def test_missing_single_profile_raises(self):
        """AC4: Missing one persona profile raises ValueError."""
        cfg = _minimal_config()
        del cfg["personas"]["medium"]
        with self.assertRaises(ValueError):
            validate_config(cfg)

    def test_missing_profile_key_raises(self):
        """AC4: Profile missing a required key raises ValueError."""
        for key in _REQUIRED_PERSONA_KEYS:
            with self.subTest(missing_key=key):
                cfg = _minimal_config()
                del cfg["personas"]["conservative"][key]
                with self.assertRaises(ValueError):
                    validate_config(cfg)

    def test_invalid_agent_persona_value_raises(self):
        """AC4: Invalid agent.persona value raises ValueError."""
        cfg = _minimal_config()
        cfg["agent"]["persona"] = "god_mode"
        with self.assertRaises(ValueError):
            validate_config(cfg)

    def test_valid_personas_pass(self):
        """AC4: Valid configs with each persona name pass without error."""
        for persona in _VALID_PERSONAS:
            with self.subTest(persona=persona):
                cfg = _minimal_config()
                cfg["agent"]["persona"] = persona
                try:
                    validate_config(cfg)
                except ValueError as e:
                    self.fail(f"validate_config() raised for valid persona '{persona}': {e}")


class TestPersonaProfileValues(unittest.TestCase):
    """AC2 spot-check — verify sensible value types/ranges across all profiles."""

    @classmethod
    def setUpClass(cls):
        config_path = os.path.join(os.path.dirname(__file__), "..", "config.yaml")
        with open(config_path) as f:
            cls.config = yaml.safe_load(f)

    def test_buy_min_score_is_positive_int(self):
        for name in _VALID_PERSONAS:
            v = self.config["personas"][name]["buy_min_score"]
            self.assertIsInstance(v, int)
            self.assertGreater(v, 0, f"{name}.buy_min_score must be > 0")

    def test_max_position_pct_in_range(self):
        for name in _VALID_PERSONAS:
            v = self.config["personas"][name]["max_position_pct"]
            self.assertGreater(v, 0)
            self.assertLessEqual(v, 100)

    def test_reallocation_enabled_is_bool(self):
        for name in _VALID_PERSONAS:
            v = self.config["personas"][name]["reallocation_enabled"]
            self.assertIsInstance(v, bool,
                                  f"{name}.reallocation_enabled must be bool, got {type(v)}")

    def test_conservative_reallocation_disabled(self):
        self.assertFalse(
            self.config["personas"]["conservative"]["reallocation_enabled"],
            "Conservative persona must never reallocate capital"
        )

    def test_llm_system_role_valid(self):
        # S4 (S14.2.4): llm_system_role is a free-form string matching the persona name or a descriptor.
        valid_roles = {"conservative", "medium", "high", "standard", "aggressive"}
        for name in _VALID_PERSONAS:
            role = self.config["personas"][name]["llm_system_role"]
            self.assertIn(role, valid_roles,
                          f"{name}.llm_system_role '{role}' not in {valid_roles}")

    def test_velocity_halt_positive(self):
        for name in _VALID_PERSONAS:
            v = self.config["personas"][name]["velocity_halt_hours"]
            self.assertGreater(v, 0, f"{name}.velocity_halt_hours must be > 0")

    def test_conservative_halt_gte_high(self):
        """Conservative persona must halt at least as long as high (risk-aversion ordering)."""
        conservative_halt = self.config["personas"]["conservative"]["velocity_halt_hours"]
        high_halt = self.config["personas"]["high"]["velocity_halt_hours"]
        self.assertGreaterEqual(conservative_halt, high_halt,
                                "Conservative must halt >= high persona (more cautious)")


if __name__ == "__main__":
    unittest.main()
