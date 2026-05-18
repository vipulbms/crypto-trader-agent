"""
Tests for S14.2.2 — Risk constraints pipe row in cycle prompt.

Story: S14.2.2 | Sprint: S3 | Epic: E14 — LLM Prompt Engineering

Covers:
  AC1: ## RISK CONSTRAINTS ## section header present in prompt
  AC2: Constraints row is pipe-format with cash_usd, positions_open,
       positions_max, kill_switch, circuit_open, playbook, persona fields
  AC3: positions_open >= positions_max → capacity instruction injected
  AC4: kill_switch=1 in row when kill switch is active
  AC5: risk_state=None does not raise (backward compatibility)
"""

from src.agent.prompts import build_cycle_prompt


# ── Helpers ───────────────────────────────────────────────────────────────────

def _portfolio(n_open: int = 0) -> dict:
    return {
        "total_usd":            10000.0,
        "available_cash_usd":   5000.0,
        "open_positions_count": n_open,
        "daily_pnl_usd":        0.0,
        "daily_pnl_pct":        0.0,
        "open_positions":       [],
        "max_per_trade":        1500.0,
    }


def _build(risk_state=None, n_open: int = 0):
    return build_cycle_prompt(
        cycle_time="2026-04-19 14:00",
        portfolio=_portfolio(n_open),
        signals=[],
        risk_state=risk_state,
        unfilled_clusters=["Layer1", "DeFi"],  # prevent S14.2.3 "at capacity" branch
    )


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestRiskConstraintsBlock:

    def test_risk_constraints_header_present(self):
        """AC1: Section header appears in prompt."""
        prompt = _build()
        assert "## RISK CONSTRAINTS ##" in prompt

    def test_required_fields_in_row(self):
        """AC2: All 7 constraint fields present in pipe row."""
        prompt = _build(risk_state={
            "kill_switch": False,
            "circuit_open": False,
            "playbook": "standard",
            "persona": "medium",
            "positions_max": 10,
        })
        for field in ("cash_usd|", "positions_open|", "positions_max|",
                      "kill_switch|", "circuit_open|", "playbook|", "persona|"):
            assert field in prompt, f"Field '{field}' missing from risk constraints row"

    def test_capacity_warning_when_at_limit(self):
        """AC3: positions_open >= positions_max → capacity warning injected."""
        prompt = _build(
            risk_state={"positions_max": 3},
            n_open=3,
        )
        assert "capacity" in prompt.lower(), (
            "Expected capacity warning when positions_open >= positions_max"
        )

    def test_no_capacity_warning_below_limit(self):
        """AC3 inverse: below limit → no capacity warning."""
        prompt = _build(
            risk_state={"positions_max": 10},
            n_open=2,
        )
        assert "capacity" not in prompt.lower()

    def test_kill_switch_active_reflected_in_row(self):
        """AC4: kill_switch=True → row shows kill_switch|1."""
        prompt = _build(risk_state={"kill_switch": True})
        assert "kill_switch|1" in prompt

    def test_kill_switch_inactive_shows_zero(self):
        """AC4 inverse: kill_switch=False → row shows kill_switch|0."""
        prompt = _build(risk_state={"kill_switch": False})
        assert "kill_switch|0" in prompt

    def test_none_risk_state_no_error(self):
        """AC5: risk_state=None is backward-compatible; uses defaults."""
        try:
            prompt = _build(risk_state=None)
        except Exception as exc:
            raise AssertionError(f"risk_state=None raised an exception: {exc}") from exc
        assert "## RISK CONSTRAINTS ##" in prompt

    def test_circuit_open_reflected(self):
        """circuit_open=True → circuit_open|1 in row."""
        prompt = _build(risk_state={"circuit_open": True})
        assert "circuit_open|1" in prompt

    def test_persona_label_in_row(self):
        """persona value appears in the constraints row."""
        prompt = _build(risk_state={"persona": "conservative"})
        assert "persona|conservative" in prompt

    def test_playbook_label_in_row(self):
        """playbook value appears in the constraints row."""
        prompt = _build(risk_state={"playbook": "recovery"})
        assert "playbook|recovery" in prompt
