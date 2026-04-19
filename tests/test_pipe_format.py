"""
Tests for S14.1.1 / S14.1.2 — Pipe-format signal block and token estimator.

Story: S14.1.1 | S14.1.2 | Sprint: S3 | Epic: E14 — LLM Prompt Engineering

Covers (S14.1.1):
  AC1: build_pipe_signal_block() returns pipe-separated key|value string
  AC2: All expected fields present: pair, score, direction, rsi, adx,
       macd_hist, bb_pos, regime, price, tp_pct, sl_pct, max_buy_usd
  AC3: BUY signal uses buy_score; SELL signal uses sell_score
  AC4: Single pair block below 200 chars (compact enough for token budget)

Covers (S14.1.2):
  AC1: estimate_tokens("") == 0; estimate_tokens("abcd") == 1 (len//4)
  AC5: 5-pair prompt has estimate_tokens result < 600 (each pair ~100 chars)
"""

from src.agent.prompts import build_pipe_signal_block, estimate_tokens


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_signal(
    pair: str = "ETH/USD",
    direction: str = "BUY",
    buy_score: int = 8,
    sell_score: int = 2,
    price: float = 3000.0,
    pair_max_usd: float = 150.0,
    rsi: float = 28.0,
    adx: float = 35.0,
    macd_hist: float = 0.125,
    bb_lower: float = 2800.0,
    bb_upper: float = 3200.0,
    max_score: int = 28,
) -> dict:
    return {
        "pair":       pair,
        "signal":     direction,
        "buy_score":  buy_score,
        "sell_score": sell_score,
        "price":      price,
        "pair_max_usd": pair_max_usd,
        "max_score":  max_score,
        "reasons":    ["RSI oversold"],
        "indicators": {
            "rsi_14":         rsi,
            "adx_14":         adx,
            "macd_histogram": macd_hist,
            "bb_lower":       bb_lower,
            "bb_upper":       bb_upper,
        },
    }


# ── estimate_tokens tests ─────────────────────────────────────────────────────

class TestEstimateTokens:

    def test_empty_string(self):
        """AC1: empty string → 0 tokens."""
        assert estimate_tokens("") == 0

    def test_four_chars_one_token(self):
        """AC1: 4 characters → 1 token (integer division)."""
        assert estimate_tokens("abcd") == 1

    def test_zero_length_check(self):
        assert estimate_tokens("   ") == 0  # 3 chars → 0

    def test_longer_string(self):
        text = "x" * 400
        assert estimate_tokens(text) == 100

    def test_proportional(self):
        text = "a" * 4000
        assert estimate_tokens(text) == 1000


# ── build_pipe_signal_block tests ─────────────────────────────────────────────

class TestBuildPipeSignalBlock:

    def test_returns_string(self):
        """AC1: function returns a string."""
        block = build_pipe_signal_block(_make_signal())
        assert isinstance(block, str)

    def test_pipe_separated_format(self):
        """AC1: block contains pipe characters separating fields."""
        block = build_pipe_signal_block(_make_signal())
        assert "|" in block

    def test_all_expected_keys_present(self):
        """AC2: all 12 expected field keys appear in the block."""
        block = build_pipe_signal_block(_make_signal())
        for key in ("pair", "score", "direction", "rsi", "adx", "macd_hist",
                    "bb_pos", "regime", "price", "tp_pct", "sl_pct", "max_buy_usd"):
            assert key in block, f"Expected key '{key}' missing from pipe block: {block!r}"

    def test_buy_uses_buy_score(self):
        """AC3: BUY direction → buy_score appears in block."""
        sig = _make_signal(direction="BUY", buy_score=9, sell_score=2)
        block = build_pipe_signal_block(sig)
        assert "9/28" in block

    def test_sell_uses_sell_score(self):
        """AC3: SELL direction → sell_score appears in block."""
        sig = _make_signal(direction="SELL", buy_score=2, sell_score=5)
        block = build_pipe_signal_block(sig)
        assert "5/28" in block

    def test_block_under_200_chars(self):
        """AC4: single block stays compact for token budget."""
        block = build_pipe_signal_block(_make_signal())
        assert len(block) < 200, f"Block is too long ({len(block)} chars): {block!r}"

    def test_pair_name_in_block(self):
        block = build_pipe_signal_block(_make_signal(pair="BTC/USD"))
        assert "BTC/USD" in block

    def test_custom_regime_label(self):
        block = build_pipe_signal_block(_make_signal(), regime="BEAR")
        assert "BEAR" in block

    def test_sl_pct_always_five(self):
        """SL is always 5% (non-negotiable)."""
        block = build_pipe_signal_block(_make_signal())
        assert "sl_pct|5" in block

    def test_five_pairs_tokens_under_600(self):
        """
        AC5 (S14.1.2): 5-pair batch pipe blocks combined should be under 600 estimated tokens.
        """
        pairs = ["BTC/USD", "ETH/USD", "SOL/USD", "BNB/USD", "DOGE/USD"]
        combined = "\n".join(
            build_pipe_signal_block(_make_signal(pair=p)) for p in pairs
        )
        assert estimate_tokens(combined) < 600, (
            f"5 pairs consume {estimate_tokens(combined)} tokens (expected < 600)"
        )

    def test_bb_pos_none_when_no_bb_bands(self):
        """When bb_lower/bb_upper missing, bb_pos should be 'N/A'."""
        sig = _make_signal()
        sig["indicators"].pop("bb_lower", None)
        sig["indicators"].pop("bb_upper", None)
        block = build_pipe_signal_block(sig)
        assert "bb_pos|N/A" in block
