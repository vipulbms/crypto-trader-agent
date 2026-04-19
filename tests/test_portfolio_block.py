"""
Tests for S14.2.1 — CURRENT PORTFOLIO pipe-format block in cycle prompt.

Story: S14.2.1 | Sprint: S3 | Epic: E14 — LLM Prompt Engineering

Covers:
  AC1: ## CURRENT PORTFOLIO ## section header present
  AC2: Open position appears as pipe-format row starting with 'pos|'
  AC3: Position row contains pair, entry, pnl_pct, pnl_usd, tp_dist_pct,
       sl_dist_pct fields
  AC4: SYSTEM_PROMPT contains the CURRENT PORTFOLIO rule
  AC5: When no open positions, positions section still rendered (empty list ok)
"""

from src.agent.prompts import SYSTEM_PROMPT, build_cycle_prompt


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_position(
    pair: str = "ETH/USD",
    entry: float = 3000.0,
    sl: float = 2850.0,
    tp: float = 3360.0,
    usd_value: float = 500.0,
    current_price: float = 3100.0,
) -> dict:
    return {
        "pair":             pair,
        "entry_price":      entry,
        "stop_loss_price":  sl,
        "take_profit_price": tp,
        "usd_value":        usd_value,
        "current_price":    current_price,
        "cluster":          "L1",
    }


def _portfolio(positions: list = None) -> dict:
    positions = positions or []
    return {
        "total_usd":            10000.0,
        "available_cash_usd":   8000.0,
        "open_positions_count": len(positions),
        "daily_pnl_usd":        50.0,
        "daily_pnl_pct":        0.5,
        "open_positions":       positions,
        "max_per_trade":        2400.0,
    }


def _build(positions=None):
    return build_cycle_prompt(
        cycle_time="2026-04-19 12:00",
        portfolio=_portfolio(positions),
        signals=[],
        pair_tp_config={"ETH/USD": 12},
    )


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestPortfolioBlock:

    def test_portfolio_header_present(self):
        """AC1: ## CURRENT PORTFOLIO ## section appears in prompt."""
        prompt = _build()
        assert "## CURRENT PORTFOLIO ##" in prompt

    def test_position_pipe_row_for_open_position(self):
        """AC2: Open position generates a row starting with 'pos|'."""
        pos = _make_position("ETH/USD")
        prompt = _build(positions=[pos])
        assert "pos|ETH/USD" in prompt

    def test_position_row_contains_required_fields(self):
        """AC3: Pipe row has entry, pnl_pct, pnl_usd, tp_dist_pct, sl_dist_pct."""
        pos = _make_position("BTC/USD", entry=90000.0, sl=85500.0, tp=97200.0,
                              usd_value=2000.0, current_price=92000.0)
        prompt = _build(positions=[pos])
        for field in ("entry|", "pnl_pct|", "pnl_usd|", "tp_dist_pct|", "sl_dist_pct|"):
            assert field in prompt, f"Field '{field}' missing from position row"

    def test_system_prompt_contains_portfolio_rule(self):
        """AC4: SYSTEM_PROMPT tells LLM not to propose_buy for open positions."""
        assert "CURRENT PORTFOLIO" in SYSTEM_PROMPT
        assert "propose_buy" in SYSTEM_PROMPT.lower() or "Do NOT propose_buy" in SYSTEM_PROMPT

    def test_empty_portfolio_still_renders_section(self):
        """AC5: Even with no open positions the section header is present."""
        prompt = _build(positions=[])
        assert "## CURRENT PORTFOLIO ##" in prompt

    def test_pnl_computed_from_current_price(self):
        """AC3: When current_price provided, pnl_pct is numeric (not 'N/A')."""
        pos = _make_position(entry=3000.0, current_price=3150.0)  # +5%
        prompt = _build(positions=[pos])
        # Should have a non-N/A pnl_pct value
        assert "pnl_pct|N/A" not in prompt

    def test_missing_current_price_shows_na(self):
        """AC3: When current_price absent, pnl_pct falls back to 'N/A'."""
        pos = _make_position()
        pos.pop("current_price", None)
        prompt = _build(positions=[pos])
        assert "pnl_pct|N/A" in prompt

    def test_multiple_positions_all_appear(self):
        """AC2: Two open positions → two separate 'pos|' rows."""
        positions = [_make_position("ETH/USD"), _make_position("SOL/USD", entry=150.0)]
        prompt = _build(positions=positions)
        assert "pos|ETH/USD" in prompt
        assert "pos|SOL/USD" in prompt
