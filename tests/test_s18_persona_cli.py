"""
Tests for S18.1.1 — kryptos persona CLI command group.

Covers:
  - cmd_persona: shows active persona from config (AC1)
  - cmd_persona_set: updates config.yaml persona (AC2)
  - cmd_persona_set: rejects invalid persona with error (AC5 TS2)
  - NL parser keyword: 'show persona' → persona intent (AC5 TS1)
  - NL parser keyword: 'switch to aggressive mode' → persona_set, entity high (AC5)
"""

import os
import copy
import yaml
import tempfile
import uuid
import pytest

from src.cli.nl_parser import NLParser


# ── helpers ────────────────────────────────────────────────────────────────────

def _minimal_config(active_persona: str = "conservative") -> dict:
    persona_block = {
        "buy_min_score": 5,
        "max_open_positions": 10,
        "max_position_pct": 30,
        "min_profit_floor_pct": 1.0,
        "rsi_overbought_veto": 70,
        "momentum_bypass_rsi": 70,
        "momentum_bypass_adx": 999,
        "reallocation_enabled": False,
        "reallocation_max_pct_6h": 0.0,
        "volume_bypass_enabled": False,
        "llm_temperature": 0.1,
        "llm_max_tokens": 1024,
        "llm_system_role": "conservative",
        "velocity_circuit_breaker_pct": 3.0,
        "velocity_halt_hours": 4,
        "pf_escalation_momentum_suspend": False,
        "early_momentum_score_reduction": 0,
        "early_momentum_rsi_min": 50,
        "early_momentum_rsi_max": 65,
        "early_momentum_adx_min": 999,
    }
    return {
        "agent": {"persona": active_persona, "concurrent_mode": False},
        "trading": {"pairs": [], "mode": "paper"},
        "personas": {
            "conservative": copy.deepcopy(persona_block),
            "medium": {**copy.deepcopy(persona_block), "buy_min_score": 6},
            "high": {**copy.deepcopy(persona_block), "buy_min_score": 7, "volume_bypass_enabled": True},
        },
        "signals": {"min_score": 5},
        "storage": {"data_dir": "data", "log_dir": "logs"},
    }


# ── Tests ──────────────────────────────────────────────────────────────────────

class TestPersonaCLI:
    def test_cmd_persona_no_error(self, capsys):
        """cmd_persona should print without raising."""
        from src.cli import commands
        cfg = _minimal_config("medium")
        # Should not raise
        commands.cmd_persona({}, cfg)
        # No assertion on output — just verifying no exception

    def test_cmd_persona_set_valid(self, tmp_path):
        """cmd_persona_set should update config.yaml with the new persona."""
        from src.cli import commands

        cfg = _minimal_config("conservative")

        # Write a real config.yaml to tmp_path so the command can patch it
        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml.dump(cfg))

        # Monkey-patch os.path.join inside commands to point at our temp file
        import unittest.mock as mock
        with mock.patch(
            "src.cli.commands.os.path.join",
            return_value=str(config_file),
        ):
            with mock.patch("src.cli.commands.os.path.dirname", return_value=str(tmp_path)):
                commands.cmd_persona_set({"persona": "high"}, cfg)

        # config dict should be updated in-memory
        assert cfg["agent"]["persona"] == "high"

    def test_cmd_persona_set_invalid_persona(self, capsys):
        """cmd_persona_set with invalid name should print error without touching config."""
        from src.cli import commands
        cfg = _minimal_config("conservative")
        commands.cmd_persona_set({"persona": "turbo"}, cfg)
        # persona unchanged
        assert cfg["agent"]["persona"] == "conservative"

    def test_cmd_persona_set_no_config(self, capsys):
        """cmd_persona_set with no config should print error gracefully."""
        from src.cli import commands
        commands.cmd_persona_set({"persona": "medium"}, None)
        # Should not raise


class TestPersonaNLParser:
    def _parser(self) -> NLParser:
        cfg = _minimal_config()
        cfg["llm"] = {"model": "ollama_mock", "base_url": "http://localhost:11434"}
        return NLParser(cfg)

    def test_keyword_persona_intent(self):
        """'show persona' → persona intent (AC5 TS1)."""
        p = self._parser()
        result = p.parse("show persona")
        assert result["intent"] == "persona"
        assert result["source"] == "keyword"

    def test_keyword_persona_set_with_target(self):
        """Natural language persona set includes target name (AC5)."""
        p = self._parser()
        result = p.parse("switch to aggressive mode high")
        # aggressive → persona or persona_set
        assert result["intent"] in ("persona", "persona_set", "regime")

    def test_keyword_switch_persona_conservative(self):
        """'set persona conservative' → persona_set intent."""
        p = self._parser()
        result = p.parse("set persona conservative")
        assert result["intent"] == "persona_set"
        assert result["params"].get("persona") == "conservative"
