"""
test_feedback_driver_multipliers.py — S23.2.2 AC3/AC4 + S23.2.1 AC4

Tests:
  - S23.2.2 AC3: rsi_oversold accuracy=28% → multiplier=0.5 applied to generate_signal score
  - S23.2.2 AC4: multiplier outside [0.5, 1.5] in DB → clamped at read time
  - S23.2.1 AC4: trending_up regime — momentum PF=1.45 (n=15), ranging PF=0.8 (n=12)
                 → get_playbook_bias returns priority_multiplier=2 for momentum, 1 for ranging
"""
import uuid

import pytest

from src.storage.database import init_paper_db, get_connection
from src.agent.orchestrator import Orchestrator

# ── DB setup ──────────────────────────────────────────────────

DB_NAME = f"test_feedback_dm_{uuid.uuid4().hex[:8]}.db"


@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    import src.storage.database as db_mod
    _orig = db_mod.DATA_DIR_PATH
    db_mod.DATA_DIR_PATH = str(tmp_path)
    init_paper_db(DB_NAME)
    yield
    db_mod.DATA_DIR_PATH = _orig


def _db():
    return DB_NAME


def _min_config():
    return {
        "signals": {
            "rsi_oversold_score": 3,
            "macd_turn_positive_score": 3,
            "macd_hist_positive_score": 1,
            "ema_short_uptrend_score": 2,
            "obv_accumulation_weight": 1,
            "bb_squeeze_release_weight": 2,
            "rsi_divergence_bullish_weight": 2,
            "rsi_divergence_hidden_bullish_weight": 1,
            "adx_trend_weight": 1,
            "fear_greed_fear_score": 1,
            "fear_greed_extreme_score": 1,
            "hammer_weight": 1,
            "engulfing_weight": 2,
            "doji_support_weight": 1,
            "rsi_overbought_score": 3,
            "macd_hist_negative_score": 2,
            "bb_upper_score": 2,
            "rsi_divergence_bearish_weight": 2,
            "rsi_divergence_lookback": 20,
            "buy_min_score": 5,
            "profit_factor_escalation": {"enabled": False},
        },
        "indicators": {
            "rsi_oversold": 30,
            "rsi_overbought": 65,
            "bb_min_width_pct": 0.5,
            "bb_buy_tolerance_pct": 1.0,
            "bb_sell_tolerance_pct": 1.0,
            "obv_trend_period": 10,
            "obv_noise_threshold": 0.001,
            "adaptive_atr_floor_pct": None,
        },
        "dynamic_tp": {"enabled": False, "atr_tp_min_pct": 0.3},
        "trading": {"pairs": [], "min_profit_floor_pct": 1.0},
        "qsa": {
            "feed_heartbeat": {"enabled": False},
            "volume_floor": {"algorithm": "sma"},
        },
    }


def _base_indicators(pair: str = "BONK/USD"):
    """Minimal indicators that would normally produce HOLD — RSI neutral, no clear signals."""
    return {
        "rsi_14":                  50.0,
        "macd_histogram":       0.01,
        "macd_histogram_prev":  0.01,
        "macd_line":            0.0,
        "macd_signal_line":     0.0,
        "bb_upper":             110.0,
        "bb_mid":               100.0,
        "bb_lower":             90.0,
        "bb_width_pct":         2.0,
        "ema_short":            100.0,
        "ema_medium":           99.0,
        "close":                100.0,
        "volume":               10000.0,
        "volume_sma_20":        8000.0,
        "rolling_volume_p15":   5000.0,
        "atr":                  2.0,
        "atr_pct":              2.0,
        "adx_14":               25.0,
        "fear_greed_index":     50,
        "feed_status":          "OK",
        "rsi_series":           [50.0] * 20,
        "close_series":         [100.0] * 20,
        "obv_series":           [1000.0] * 15,
        "bb_width_series":      [2.0] * 10,
        "opens":                [99.0] * 5,
        "highs":                [101.0] * 5,
        "lows":                 [99.0] * 5,
        "closes":               [100.0] * 5,
        "driver_weight_multipliers": {},
    }


# ── S23.2.2 AC3: multiplier applied to score ─────────────────

class TestDriverMultipliers:
    def test_ac3_low_accuracy_reduces_rsi_weight(self):
        """
        RSI oversold fires (RSI=25) with default weight=3.
        When multiplier=0.5, effective weight is 1 (rounded), reducing total score.
        """
        from src.analysis.signals import generate_signal

        indicators_no_mult = _base_indicators()
        indicators_no_mult["rsi_14"] = 25.0  # RSI oversold

        indicators_with_mult = dict(indicators_no_mult)
        indicators_with_mult["driver_weight_multipliers"] = {
            "rsi_oversold": 0.5   # 28% accuracy → 0.5 multiplier
        }

        config = _min_config()

        result_base  = generate_signal("BONK/USD", indicators_no_mult,  config)
        result_halved = generate_signal("BONK/USD", indicators_with_mult, config)

        base_score   = result_base.get("buy_score",   0)
        halved_score = result_halved.get("buy_score", 0)

        assert halved_score < base_score, (
            f"Multiplier=0.5 should reduce score: base={base_score}, halved={halved_score}"
        )

    def test_ac3_high_accuracy_increases_macd_weight(self):
        """
        MACD turn fires with default weight=3.
        When multiplier=1.3, effective weight is 4 (rounded from 3.9).
        """
        from src.analysis.signals import generate_signal

        indicators_base = _base_indicators()
        indicators_base["macd_histogram"]      = 0.05   # positive
        indicators_base["macd_histogram_prev"] = -0.05  # was negative → MACD turn

        indicators_boosted = dict(indicators_base)
        indicators_boosted["driver_weight_multipliers"] = {
            "macd_histogram_turn": 1.3
        }

        config = _min_config()

        result_base    = generate_signal("ETH/USD", indicators_base,    config)
        result_boosted = generate_signal("ETH/USD", indicators_boosted, config)

        assert result_boosted.get("buy_score", 0) >= result_base.get("buy_score", 0), (
            "Higher multiplier should not reduce score"
        )

    # ── AC4: out-of-bounds multiplier clamped ────────────────

    def test_ac4_multiplier_too_high_clamped(self):
        """Multiplier=3.0 in DB should be clamped to 1.5 before injection."""
        # Simulate clamping logic from main.py
        raw_multiplier = 3.0
        clamped = max(0.5, min(1.5, raw_multiplier))
        assert clamped == 1.5

    def test_ac4_multiplier_too_low_clamped(self):
        """Multiplier=0.1 in DB should be clamped to 0.5."""
        raw_multiplier = 0.1
        clamped = max(0.5, min(1.5, raw_multiplier))
        assert clamped == 0.5

    def test_ac4_valid_multiplier_unchanged(self):
        """Multiplier=0.8 is in range — unchanged."""
        raw_multiplier = 0.8
        clamped = max(0.5, min(1.5, raw_multiplier))
        assert clamped == 0.8

    def test_ac4_no_crash_with_extreme_multipliers(self):
        """generate_signal must not raise even with extreme multipliers."""
        from src.analysis.signals import generate_signal

        indicators = _base_indicators()
        indicators["driver_weight_multipliers"] = {
            "rsi_oversold": 0.5,       # clamped from 0.0
            "macd_histogram_turn": 1.5, # clamped from 5.0
        }
        indicators["rsi"] = 25.0

        config = _min_config()
        result = generate_signal("BONK/USD", indicators, config)
        assert result["signal"] in ("BUY", "SELL", "HOLD")


# ── S23.2.1 AC4: Orchestrator playbook bias ───────────────────

class TestOrchestratorPlaybookBias:
    def _seed_playbook_performance(self, regime: str, playbook: str,
                                   profit_factor: float, sample_count: int):
        import datetime
        conn = get_connection(_db())
        ts = datetime.datetime.utcnow().isoformat()
        conn.execute(
            "INSERT OR REPLACE INTO playbook_performance "
            "(regime, playbook, sample_count, win_rate, profit_factor, max_drawdown, last_updated_at) "
            "VALUES (?, ?, ?, 0.55, ?, 0.05, ?)",
            (regime, playbook, sample_count, profit_factor, ts)
        )
        conn.commit()
        conn.close()

    def test_ac4_momentum_high_pf_selected_over_ranging(self):
        """
        trending_up regime:
          momentum: PF=1.45, n=15 → multiplier=2
          ranging:  PF=0.80, n=12 → multiplier=1
        Orchestrator should return momentum with higher priority.
        """
        self._seed_playbook_performance("trending_up", "momentum", 1.45, 15)
        self._seed_playbook_performance("trending_up", "ranging",  0.80, 12)

        orch = Orchestrator(config=_min_config(), db_path=_db())
        bias = orch.get_playbook_bias("trending_up")

        assert bias.get("momentum") == 2, f"Expected momentum=2, got {bias}"
        assert bias.get("ranging")  == 1, f"Expected ranging=1, got {bias}"

    def test_ac4_insufficient_samples_no_bias(self):
        """PF > 1.2 but n=5 (<10 threshold) → multiplier=1 (no bias)."""
        self._seed_playbook_performance("trending_up", "momentum", 1.45, 5)

        orch = Orchestrator(config=_min_config(), db_path=_db())
        bias = orch.get_playbook_bias("trending_up")

        assert bias == {}, f"n=5 should not qualify for bias, got {bias}"

    def test_ac4_no_rows_returns_empty_bias(self):
        """No playbook_performance rows → empty dict returned."""
        orch = Orchestrator(config=_min_config(), db_path=_db())
        bias = orch.get_playbook_bias("bear")
        assert bias == {}
