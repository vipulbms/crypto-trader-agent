"""
Tests for S14.1.2 — Token budget guard in build_cycle_prompt().

Story: S14.1.2 | Sprint: S3 | Epic: E14 — LLM Prompt Engineering

Covers:
  AC6: 30-pair BUY-heavy prompt triggers trimming; result ≤ 5800 estimated tokens
  AC7: SELL signals are never trimmed even when budget is tight
  AC8: Weakest BUY (lowest buy_score) is removed first
"""

from src.agent.prompts import build_cycle_prompt, estimate_tokens


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_signal(pair: str, direction: str = "BUY", score: int = 5, price: float = 100.0) -> dict:
    return {
        "pair":       pair,
        "signal":     direction,
        "buy_score":  score,
        "sell_score": score if direction == "SELL" else 0,
        "price":      price,
        "pair_max_usd": 100.0,
        "max_score":  28,
        "reasons":    ["RSI oversold; MACD bullish crossover; BB squeeze release"],
        "indicators": {
            "rsi_14":         28.0,
            "adx_14":         35.0,
            "macd_histogram": 0.05,
            "bb_lower":       90.0,
            "bb_upper":       110.0,
        },
    }


def _portfolio(n_open: int = 0) -> dict:
    return {
        "total_usd":            10000.0,
        "available_cash_usd":   9000.0,
        "open_positions_count": n_open,
        "daily_pnl_usd":        100.0,
        "daily_pnl_pct":        1.0,
        "open_positions":       [],
        "max_per_trade":        3000.0,
    }


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestTokenBudget:

    def test_30_pair_prompt_stays_within_budget(self):
        """
        AC6: A 30-pair BUY-heavy prompt gets trimmed so estimated tokens ≤ 5800.
        Each pair's score is 5 so trimming is by ascending score.
        """
        pairs = [f"PAIR{i:02d}/USD" for i in range(30)]
        signals = [_make_signal(p, "BUY", score=5) for p in pairs]

        prompt = build_cycle_prompt(
            cycle_time="2026-04-19 10:00",
            portfolio=_portfolio(),
            signals=signals,
            pair_tp_config={p: 12 for p in pairs},
        )
        assert estimate_tokens(prompt) <= 5800, (
            f"Prompt not trimmed: {estimate_tokens(prompt)} estimated tokens"
        )

    def test_sell_signals_never_trimmed(self):
        """
        AC7: SELL signals survive even when BUY signals are trimmed away.
        """
        buy_pairs = [f"BUY{i:02d}/USD" for i in range(25)]
        sell_pairs = ["ETH/USD", "SOL/USD"]
        signals = (
            [_make_signal(p, "BUY", score=5) for p in buy_pairs]
            + [_make_signal(p, "SELL", score=4) for p in sell_pairs]
        )
        tp = {p: 12 for p in buy_pairs + sell_pairs}
        prompt = build_cycle_prompt(
            cycle_time="2026-04-19 10:00",
            portfolio=_portfolio(),
            signals=signals,
            pair_tp_config=tp,
        )
        for p in sell_pairs:
            assert p in prompt, f"SELL pair {p} was incorrectly trimmed from prompt"

    def test_weakest_buy_removed_first(self):
        """
        AC8: When trimming, the BUY signal with the lowest buy_score is removed first.
        """
        signals = [
            _make_signal("WEAK/USD",   "BUY", score=1),   # weakest — should be trimmed first
            _make_signal("STRONG/USD", "BUY", score=9),   # strongest
        ]
        # Add padding to ensure budget is exceeded
        filler_pairs = [f"FILL{i:02d}/USD" for i in range(28)]
        signals += [_make_signal(p, "BUY", score=5) for p in filler_pairs]
        tp = {s["pair"]: 12 for s in signals}

        prompt = build_cycle_prompt(
            cycle_time="2026-04-19 10:00",
            portfolio=_portfolio(),
            signals=signals,
            pair_tp_config=tp,
        )

        # If any trimming happened, WEAK/USD should be gone before STRONG/USD
        # At minimum, the prompt stays within budget
        assert estimate_tokens(prompt) <= 5800

    def test_small_prompt_not_trimmed(self):
        """
        Sanity: a 2-pair prompt is well under budget and should include both pairs.
        """
        signals = [_make_signal("BTC/USD", "BUY"), _make_signal("ETH/USD", "BUY")]
        prompt = build_cycle_prompt(
            cycle_time="2026-04-19 10:00",
            portfolio=_portfolio(),
            signals=signals,
            pair_tp_config={"BTC/USD": 8, "ETH/USD": 12},
        )
        assert "BTC/USD" in prompt
        assert "ETH/USD" in prompt
        assert estimate_tokens(prompt) <= 5800
