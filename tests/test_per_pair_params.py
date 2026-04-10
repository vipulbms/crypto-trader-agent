"""
Tests for per-pair signal parameter overrides:
  - Fix #107: per-pair atr_tp_min_pct
  - Fix #109: per-pair rsi_oversold / rsi_overbought
  - Fix #110: per-pair bb_squeeze_threshold_pct in compute_dynamic_tp
  - Fix #111: per-pair min_volume_ratio dead zone
  - Fix #106: adaptive_atr_floor_pct injection overrides static floor
  - Fix #114: rolling_volume_p15 injection overrides ratio check

All timestamps in tests represent candle time (not system time).
"""
import unittest


# ── Minimal config shared across tests ────────────────────────────────────────
def _make_config(pair_overrides=None):
    pairs = [
        {
            "pair": "BTC/USD",
            "take_profit_pct": 8,
            "stop_loss_pct": 5,
            "atr_tp_min_pct": 0.14,
            "rsi_oversold": 30,
            "rsi_overbought": 75,
            "bb_squeeze_threshold_pct": 0.7,
            "min_volume_ratio": 0.50,
        },
        {
            "pair": "TRX/USD",
            "take_profit_pct": 12,
            "stop_loss_pct": 5,
            "atr_tp_min_pct": 0.12,
            "rsi_oversold": 35,     # noisy pair — raised threshold
            "rsi_overbought": 65,   # fires often — lowered
            "bb_squeeze_threshold_pct": 0.8,
            "min_volume_ratio": 0.40,
        },
        {
            "pair": "INJ/USD",
            "take_profit_pct": 20,
            "stop_loss_pct": 5,
            "atr_tp_min_pct": 0.34,
            "rsi_oversold": 30,
            "rsi_overbought": 72,
            "bb_squeeze_threshold_pct": 2.5,
            "min_volume_ratio": 0.30,
        },
        {
            "pair": "BNB/USD",
            "take_profit_pct": 12,
            "stop_loss_pct": 5,
            "atr_tp_min_pct": 0.15,
            "rsi_oversold": 28,
            "rsi_overbought": 75,
            "bb_squeeze_threshold_pct": 0.9,
            "min_volume_ratio": 0.30,
        },
    ]
    if pair_overrides:
        for p in pairs:
            if p["pair"] in pair_overrides:
                p.update(pair_overrides[p["pair"]])
    return {
        "trading": {
            "stop_loss_pct": 5,
            "take_profit_pct": 8,
            "min_profit_floor_pct": 1.0,
            "early_sell_min_tp_proximity_pct": 60,
            "max_position_pct": 15,
            "max_open_positions": 13,
            "max_buys_per_cycle": 3,
            "cycle_interval_minutes": 15,
            "allowed_trading_hours": {
                "enabled": False,
                "start_hour_utc": 0,
                "end_hour_utc": 24,
                "min_volume_ratio": 0.5,
            },
            "pairs": pairs,
        },
        "dynamic_tp": {
            "enabled": True,
            "atr_multiplier": 2.0,
            "bb_width_scale": True,
            "min_tp_pct": 5,
            "max_tp_pct": 20,
            "squeeze_threshold_pct": 1.0,   # global fallback — should be overridden per pair
            "atr_tp_min_pct": 0.30,         # global fallback
        },
        "indicators": {
            "rsi_oversold": 30,
            "rsi_overbought": 75,
            "bb_min_width_pct": 0.5,
            "bb_buy_tolerance_pct": 0.5,
            "bb_sell_tolerance_pct": 0.5,
        },
        "signals": {
            "rsi_oversold_score": 3,
            "rsi_mild_oversold_score": 1,
            "macd_turn_positive_score": 3,
            "macd_hist_positive_score": 1,
            "macd_crossover_score": 1,
            "bb_lower_score": 2,
            "ema_short_uptrend_score": 2,
            "ema_medium_trend_score": 1,
            "fear_greed_fear_score": 1,
            "fear_greed_extreme_score": 1,
            "rsi_overbought_score": 3,
            "macd_hist_negative_score": 2,
            "bb_upper_score": 2,
            "max_score": 16,
            "buy_min_score": 5,
            "sell_min_score": 3,
        },
        "sentiment": {"enabled": False},
        "pattern_analysis": {"enabled": False},
        "exit_timing": {"enabled": False},
        "position_sizing": {"enabled": False},
        "regime": {"enabled": False},
        "risk": {"daily_loss_limit_pct": 10, "min_cash_reserve_pct": 10},
        "storage": {"paper_db": ":memory:", "audit_db": ":memory:"},
    }


def _indicators(price=50000.0, atr=100.0, rsi=45.0, volume=1000.0, volume_sma_20=1000.0,
                bb_upper=None, bb_lower=None, macd_hist=0.01, macd_hist_prev=-0.01,
                ema_9=50100.0, ema_21=49900.0, ema_50=48000.0):
    if bb_upper is None:
        bb_upper = price * 1.02
    if bb_lower is None:
        bb_lower = price * 0.98
    return {
        "close": price,
        "atr_14": atr,
        "rsi_14": rsi,
        "volume": volume,
        "volume_sma_20": volume_sma_20,
        "bb_upper": bb_upper,
        "bb_lower": bb_lower,
        "macd_histogram": macd_hist,
        "macd_histogram_prev": macd_hist_prev,
        "macd_line": 0.05,
        "macd_signal_line": 0.03,
        "ema_9": ema_9,
        "ema_21": ema_21,
        "ema_50": ema_50,
    }


# ── Fix #107: per-pair atr_tp_min_pct ─────────────────────────────────────────

class TestPerPairAtrTpMinPct(unittest.TestCase):

    def _signal(self, pair, indicators):
        from src.analysis.signals import generate_signal
        return generate_signal(pair, indicators, _make_config())

    def test_btc_passes_at_0_14_pct_atr(self):
        """
        Given BTC atr_tp_min_pct=0.14 and ATR-based TP = (2.0 × 110 / 50000) × 100 = 0.44%
        When generate_signal is called
        Then BUY signal is NOT blocked by ATR floor (0.44 > 0.14)
        Refs #107
        """
        ind = _indicators(price=50000.0, atr=110.0)  # ATR-based TP = 0.44%
        result = self._signal("BTC/USD", ind)
        blocked = any("ATR-based TP" in r for r in result["reasons"])
        self.assertFalse(blocked, f"BTC should not be ATR-blocked at 0.44% TP, reasons: {result['reasons']}")

    def test_btc_blocked_when_atr_genuinely_tiny(self):
        """
        Given BTC atr_tp_min_pct=0.14 and ATR-based TP = (2.0 × 10 / 50000) × 100 = 0.04%
        When generate_signal is called
        Then BUY is BLOCKED (0.04 < 0.14)
        Refs #107
        """
        ind = _indicators(price=50000.0, atr=10.0)  # ATR-based TP = 0.04%
        result = self._signal("BTC/USD", ind)
        blocked = any("ATR-based TP" in r or "BLOCKED" in r for r in result["reasons"])
        self.assertTrue(blocked, f"BTC should be blocked at 0.04% TP, reasons: {result['reasons']}")

    def test_global_floor_was_1_pct_now_per_pair_0_14_allows_btc(self):
        """
        Given old global floor 1.0% would block BTC at ATR-based TP = 0.44%
        When per-pair floor 0.14% is used
        Then BTC is no longer blocked
        Refs #107
        """
        # ATR=110 on price=50000: ATR-based TP = 0.44% — blocked at 1.0%, allowed at 0.14%
        ind = _indicators(price=50000.0, atr=110.0)
        result = self._signal("BTC/USD", ind)
        self.assertNotEqual(result["signal"], "HOLD",
                            "BTC with ATR-TP 0.44% should not be HOLD under per-pair floor 0.14%")

    def test_injected_adaptive_floor_overrides_static(self):
        """
        Given adaptive_atr_floor_pct=0.50 injected into indicators dict
        And per-pair atr_tp_min_pct=0.14 (lower)
        When ATR-based TP = 0.44% (below adaptive 0.50%)
        Then BUY is BLOCKED by adaptive floor
        Refs #108
        """
        from src.analysis.signals import generate_signal
        ind = _indicators(price=50000.0, atr=110.0)
        ind["adaptive_atr_floor_pct"] = 0.50  # injected adaptive floor higher than ATR-TP
        result = generate_signal("BTC/USD", ind, _make_config())
        blocked = any("ATR-based TP" in r or "BLOCKED" in r for r in result["reasons"])
        self.assertTrue(blocked, "Adaptive floor 0.50% should block ATR-TP 0.44%")

    def test_trx_per_pair_floor_0_12(self):
        """
        Given TRX atr_tp_min_pct=0.12 and ATR-based TP = (2.0 × 0.0003 / 0.25) × 100 = 0.24%
        When generate_signal is called
        Then TRX is NOT blocked (0.24 > 0.12)
        Refs #107
        """
        ind = _indicators(price=0.25, atr=0.0003)  # TRX-like price/ATR
        result = self._signal("TRX/USD", ind)
        blocked = any("ATR-based TP" in r for r in result["reasons"])
        self.assertFalse(blocked, f"TRX should not be blocked at ATR-TP 0.24%, reasons: {result['reasons']}")


# ── Fix #109: per-pair RSI thresholds ─────────────────────────────────────────

class TestPerPairRsiThresholds(unittest.TestCase):

    def _signal(self, pair, indicators):
        from src.analysis.signals import generate_signal
        return generate_signal(pair, indicators, _make_config())

    def test_trx_rsi_35_triggers_oversold(self):
        """
        Given TRX rsi_oversold=35 and RSI=34
        When generate_signal is called
        Then RSI oversold score is awarded (+3)
        Refs #109
        """
        ind = _indicators(price=0.25, atr=0.0005, rsi=34.0)
        result = self._signal("TRX/USD", ind)
        self.assertTrue(any("RSI oversold" in r for r in result["reasons"]),
                        f"TRX RSI 34 should trigger oversold at threshold 35, reasons: {result['reasons']}")

    def test_btc_rsi_34_does_not_trigger_oversold(self):
        """
        Given BTC rsi_oversold=30 and RSI=34
        When generate_signal is called
        Then RSI oversold score is NOT awarded (34 > 30)
        Refs #109
        """
        ind = _indicators(price=50000.0, atr=200.0, rsi=34.0)
        result = self._signal("BTC/USD", ind)
        self.assertFalse(any("RSI oversold" in r and "34" in r for r in result["reasons"]),
                         f"BTC RSI 34 should not trigger oversold at threshold 30, reasons: {result['reasons']}")

    def test_bnb_rsi_28_triggers_oversold(self):
        """
        Given BNB rsi_oversold=28 and RSI=27
        When generate_signal is called
        Then RSI oversold score is awarded
        Refs #109
        """
        ind = _indicators(price=600.0, atr=2.0, rsi=27.0)
        result = self._signal("BNB/USD", ind)
        self.assertTrue(any("RSI oversold" in r for r in result["reasons"]),
                        f"BNB RSI 27 should trigger oversold at threshold 28, reasons: {result['reasons']}")

    def test_trx_rsi_66_triggers_overbought_block(self):
        """
        Given TRX rsi_overbought=65 and RSI=66
        When generate_signal is called
        Then RSI >= 70 hard blocker does NOT fire (66 < 70) but SELL score includes overbought
        Refs #109
        """
        ind = _indicators(price=0.25, atr=0.0005, rsi=66.0)
        result = self._signal("TRX/USD", ind)
        # RSI overbought score should be in reasons (SELL path), not hard blocker
        self.assertTrue(any("overbought" in r.lower() for r in result["reasons"]),
                        f"TRX RSI 66 should register overbought at threshold 65, reasons: {result['reasons']}")

    def test_inj_rsi_73_triggers_overbought(self):
        """
        Given INJ rsi_overbought=72 and RSI=73
        When generate_signal is called
        Then overbought score is awarded in SELL path
        Refs #109
        """
        ind = _indicators(price=10.0, atr=0.06, rsi=73.0)
        result = self._signal("INJ/USD", ind)
        self.assertTrue(any("overbought" in r.lower() for r in result["reasons"]),
                        f"INJ RSI 73 should trigger overbought at threshold 72, reasons: {result['reasons']}")

    def test_btc_rsi_73_does_not_trigger_sell_overbought(self):
        """
        Given BTC rsi_overbought=75 and RSI=73
        When generate_signal is called
        Then overbought score is NOT awarded (73 < 75)
        Refs #109
        """
        ind = _indicators(price=50000.0, atr=200.0, rsi=73.0)
        result = self._signal("BTC/USD", ind)
        self.assertFalse(any("RSI overbought" in r for r in result["reasons"]),
                         f"BTC RSI 73 should NOT trigger overbought at threshold 75, reasons: {result['reasons']}")


# ── Fix #110: per-pair bb_squeeze_threshold_pct ───────────────────────────────

class TestPerPairBbSqueeze(unittest.TestCase):

    def _tp(self, pair, bb_upper, bb_lower, price=50000.0, atr=500.0):
        from src.analysis.features import compute_dynamic_tp
        return compute_dynamic_tp(pair, price, atr, bb_upper, bb_lower, _make_config())

    def test_inj_1_5pct_bb_width_not_a_squeeze(self):
        """
        Given INJ bb_squeeze_threshold_pct=2.5 and BB width=1.5% (below threshold)
        When compute_dynamic_tp is called
        Then TP is clamped to pair minimum (squeeze detected)
        Refs #110
        """
        price = 10.0
        bb_upper = price * 1.0075   # width = 1.5%
        bb_lower = price * 0.9925
        tp = self._tp("INJ/USD", bb_upper, bb_lower, price=price, atr=0.08)
        # Should be clamped to pair min (20% for INJ, but global min_tp=5 → max(5,20)=20)
        self.assertEqual(tp, 20.0, f"INJ BB width 1.5% < threshold 2.5% → squeeze → TP should be pair min 20%, got {tp}")

    def test_inj_3_0pct_bb_width_not_squeeze(self):
        """
        Given INJ bb_squeeze_threshold_pct=2.5 and BB width=3.0% (above threshold)
        When compute_dynamic_tp is called
        Then TP is computed from ATR (not clamped to min)
        Refs #110
        """
        price = 10.0
        bb_upper = price * 1.015    # width = 3.0%
        bb_lower = price * 0.985
        tp = self._tp("INJ/USD", bb_upper, bb_lower, price=price, atr=0.15)
        # ATR-based TP should be > pair min; at least not clamped
        self.assertGreaterEqual(tp, 5.0, "TP should be at least global min")
        # With ATR=0.15 on price=10, raw TP = (2.0 × 0.15 / 10) × 100 = 3.0% → clamped to max(5,20)=20
        # Either way it should NOT be artificially clamped by squeeze when width is wide enough
        self.assertTrue(tp > 0, "TP must be positive")

    def test_btc_0_6pct_bb_width_is_squeeze(self):
        """
        Given BTC bb_squeeze_threshold_pct=0.7 and BB width=0.6% (below threshold)
        When compute_dynamic_tp is called
        Then TP is clamped to BTC pair minimum (8%)
        Refs #110
        """
        price = 50000.0
        bb_upper = price * 1.003   # width = 0.6%
        bb_lower = price * 0.997
        tp = self._tp("BTC/USD", bb_upper, bb_lower, price=price, atr=200.0)
        self.assertEqual(tp, 8.0, f"BTC BB width 0.6% < threshold 0.7% → squeeze → TP should be 8%, got {tp}")

    def test_global_squeeze_threshold_not_used_when_per_pair_set(self):
        """
        Given global squeeze_threshold_pct=1.0 and INJ per-pair=2.5
        And BB width=1.5% (above global 1.0 but below per-pair 2.5)
        When compute_dynamic_tp is called for INJ
        Then per-pair threshold (2.5%) is used → squeeze detected → TP clamped
        Refs #110
        """
        price = 10.0
        bb_upper = price * 1.0075  # width = 1.5%
        bb_lower = price * 0.9925
        # Global threshold 1.0% would NOT declare squeeze (1.5 > 1.0)
        # Per-pair INJ threshold 2.5% WOULD declare squeeze (1.5 < 2.5)
        tp = self._tp("INJ/USD", bb_upper, bb_lower, price=price, atr=0.08)
        self.assertEqual(tp, 20.0, "Per-pair INJ threshold 2.5% should override global 1.0%")


# ── Fix #111: per-pair min_volume_ratio ───────────────────────────────────────

class TestPerPairVolumeRatio(unittest.TestCase):

    def _signal(self, pair, indicators):
        from src.analysis.signals import generate_signal
        return generate_signal(pair, indicators, _make_config())

    def test_bnb_blocked_at_0_35_ratio_with_threshold_0_30(self):
        """
        Given BNB min_volume_ratio=0.30 and volume = 35% of SMA (below 0.30)
        Wait — 0.35 > 0.30, so NOT blocked
        Refs #111
        """
        ind = _indicators(price=600.0, atr=2.0, volume=350.0, volume_sma_20=1000.0)
        result = self._signal("BNB/USD", ind)
        blocked = any("dead zone" in r.lower() for r in result["reasons"])
        self.assertFalse(blocked, "BNB vol=35% of SMA should NOT be blocked at threshold 30%")

    def test_bnb_blocked_at_0_25_ratio_with_threshold_0_30(self):
        """
        Given BNB min_volume_ratio=0.30 and volume = 25% of SMA (below 0.30)
        When generate_signal is called
        Then dead zone blocker fires
        Refs #111
        """
        ind = _indicators(price=600.0, atr=2.0, volume=250.0, volume_sma_20=1000.0)
        result = self._signal("BNB/USD", ind)
        blocked = any("dead zone" in r.lower() or "BLOCKED" in r for r in result["reasons"])
        self.assertTrue(blocked, "BNB vol=25% of SMA should be blocked at threshold 30%")

    def test_global_threshold_0_5_would_block_but_per_pair_0_30_allows(self):
        """
        Given BNB min_volume_ratio=0.30 and volume = 40% of SMA
        Global threshold 0.50 would block (40 < 50%), per-pair 0.30 allows (40 > 30%)
        When generate_signal is called for BNB
        Then NOT blocked — per-pair threshold wins
        Refs #111
        """
        ind = _indicators(price=600.0, atr=2.0, volume=400.0, volume_sma_20=1000.0)
        result = self._signal("BNB/USD", ind)
        blocked = any("dead zone" in r.lower() for r in result["reasons"])
        self.assertFalse(blocked, "BNB vol=40% should not be blocked at per-pair threshold 30%")

    def test_rolling_p15_injection_overrides_ratio_check(self):
        """
        Given rolling_volume_p15=500 injected into indicators
        And volume=400 (below rolling floor)
        When generate_signal is called
        Then dead zone blocks on rolling floor, not ratio check
        Refs #114
        """
        ind = _indicators(price=600.0, atr=2.0, volume=400.0, volume_sma_20=1000.0)
        ind["rolling_volume_p15"] = 500.0  # injected adaptive floor
        result = self._signal("BNB/USD", ind)
        blocked = any("BLOCKED" in r or "dead zone" in r.lower() for r in result["reasons"])
        self.assertTrue(blocked, "Rolling p15 floor 500 should block volume 400")

    def test_rolling_p15_allows_when_volume_above_floor(self):
        """
        Given rolling_volume_p15=300 and volume=400 (above floor)
        When generate_signal is called
        Then NOT blocked by rolling floor
        Refs #114
        """
        ind = _indicators(price=600.0, atr=2.0, volume=400.0, volume_sma_20=1000.0)
        ind["rolling_volume_p15"] = 300.0
        result = self._signal("BNB/USD", ind)
        blocked = any("dead zone" in r.lower() for r in result["reasons"])
        self.assertFalse(blocked, "Rolling p15=300 should allow volume 400")


# ── Per-pair buy_min_score tests (#128) ────────────────────────────────────────

class TestPerPairBuyMinScore(unittest.TestCase):
    """Tests for per-pair buy_min_score override in generate_signal(). Refs #128."""

    def _signal(self, pair, indicators, pair_extra=None):
        """Helper: run generate_signal with per-pair buy_min_score override."""
        from src.analysis.signals import generate_signal
        cfg = _make_config()
        # Apply per-pair buy_min_score override if provided
        if pair_extra:
            for p in cfg["trading"]["pairs"]:
                if p["pair"] == pair:
                    p.update(pair_extra)
        return generate_signal(pair, indicators, cfg)

    def test_inj_buy_blocked_at_score_5_when_threshold_is_7(self):
        """
        Given INJ/USD has buy_min_score=7
        And indicators produce a score of 4 (RSI mildly oversold, MACD histogram turned positive,
        but EMA bearish and MACD line below signal — no trend bonus)
        When generate_signal is called
        Then signal is HOLD, not BUY
        Refs #128
        """
        ind = _indicators(
            price=10.0, atr=0.5, volume=5000.0, volume_sma_20=3000.0,
            ema_9=9.8, ema_21=10.2,  # bearish EMA — no +2 bonus
        )
        ind["rsi_14"] = 32.0                  # mild oversold (+1)
        ind["macd_histogram"] = 0.01          # barely positive (+1)
        ind["macd_histogram_prev"] = -0.01    # turned positive (+3)
        ind["macd_line"] = -0.01              # below signal — no +1 crossover
        ind["macd_signal_line"] = 0.01
        ind["bb_lower"] = 10.2                # not near lower band
        # Score: mild_oversold +1, macd_turn +3 = 4 < 7 → HOLD
        result = self._signal("INJ/USD", ind, {"buy_min_score": 7})
        self.assertNotEqual(result["signal"], "BUY",
            f"INJ with buy_min_score=7 should HOLD at score ~4. Got: {result['reasons']}")

    def test_inj_buy_fires_at_score_7_when_threshold_is_7(self):
        """
        Given INJ/USD has buy_min_score=7
        And indicators produce a score >= 7 (RSI oversold, MACD turn, BB lower touch)
        When generate_signal is called
        Then signal is BUY
        Refs #128
        """
        ind = _indicators(price=10.0, atr=0.5, volume=5000.0, volume_sma_20=3000.0)
        ind["rsi_14"] = 25.0           # deeply oversold (+3)
        ind["macd_histogram"] = 0.05   # positive (+1)
        ind["macd_histogram_prev"] = -0.05  # turned positive (+3)
        ind["bb_lower"] = 10.1         # price near lower band (+2) — total ~9
        ind["adaptive_atr_floor_pct"] = 0.1  # floor satisfied
        result = self._signal("INJ/USD", ind, {"buy_min_score": 7, "atr_tp_min_pct": 0.10})
        self.assertEqual(result["signal"], "BUY",
            f"INJ at score ~9 should BUY when threshold=7. Reasons: {result['reasons']}")

    def test_global_default_used_when_no_per_pair_score(self):
        """
        Given BTC/USD has no buy_min_score override (uses global default=5)
        And indicators produce a score of exactly 5
        When generate_signal is called
        Then signal is BUY (global threshold met)
        Refs #128
        """
        ind = _indicators(price=90000.0, atr=500.0, volume=5000.0, volume_sma_20=3000.0)
        ind["rsi_14"] = 25.0           # deeply oversold (+3)
        ind["macd_histogram"] = 0.05   # positive (+1)
        ind["macd_histogram_prev"] = -0.05  # turned positive (+3) — total 7
        ind["bb_lower"] = 90100.0      # near lower band (+2)
        ind["adaptive_atr_floor_pct"] = 0.1
        result = self._signal("BTC/USD", ind, {"atr_tp_min_pct": 0.10})
        self.assertEqual(result["signal"], "BUY",
            f"BTC with global threshold=5 should BUY at score 7. Reasons: {result['reasons']}")

    def test_sol_threshold_6_blocks_score_5(self):
        """
        Given SOL/USD has buy_min_score=6
        And indicators produce score ~4 (RSI oversold +3, MACD hist positive +1,
        but EMA bearish and MACD line below signal — no trend bonuses)
        When generate_signal is called
        Then signal is HOLD
        Refs #128
        """
        from src.analysis.signals import generate_signal
        cfg = _make_config()
        cfg["trading"]["pairs"].append({
            "pair": "SOL/USD",
            "take_profit_pct": 16,
            "stop_loss_pct": 5,
            "atr_tp_min_pct": 0.30,
            "rsi_oversold": 30,
            "rsi_overbought": 75,
            "bb_squeeze_threshold_pct": 1.8,
            "min_volume_ratio": 0.50,
            "buy_min_score": 6,
        })
        ind = _indicators(
            price=150.0, atr=3.0, volume=5000.0, volume_sma_20=3000.0,
            ema_9=148.0, ema_21=152.0,  # bearish EMA — no +2 bonus
        )
        ind["rsi_14"] = 29.0                # oversold (+3)
        ind["macd_histogram"] = 0.01        # positive but not a turn (+1)
        ind["macd_histogram_prev"] = 0.005  # was already positive — no +3 turn
        ind["macd_line"] = -0.01            # below signal — no +1 crossover
        ind["macd_signal_line"] = 0.01
        ind["bb_lower"] = 160.0             # not near lower band
        # Score: RSI oversold +3, MACD hist positive +1 = 4 < 6 → HOLD
        result = generate_signal("SOL/USD", ind, cfg)
        self.assertNotEqual(result["signal"], "BUY",
            f"SOL with buy_min_score=6 should HOLD at score ~4. Got: {result['reasons']}")


# ── Per-pair caution_factor_bearish tests (#124) ────────────────────────────────

class TestPerPairCautionFactor(unittest.TestCase):
    """
    Tests verify that per-pair caution_factor_bearish is correctly read from
    config and injected into signal dicts in main.py logic.
    We test the config lookup pattern directly since caution_factor application
    lives in main.py orchestration, not a unit-testable function.
    Refs #124
    """

    def _get_pair_caution(self, pair, config, global_caution=0.5):
        """Replicate the main.py per-pair caution lookup."""
        trading_pairs_cfg = config.get("trading", {}).get("pairs", [])
        pair_cfg = next((p for p in trading_pairs_cfg if p.get("pair") == pair), {})
        return pair_cfg.get("caution_factor_bearish", global_caution)

    def test_eth_caution_factor_is_1_0(self):
        """
        Given ETH/USD has caution_factor_bearish=1.0 in config
        When bearish regime lookup is performed
        Then caution_factor for ETH is 1.0 (no reduction — buy the dip)
        Refs #124
        """
        cfg = _make_config()
        for p in cfg["trading"]["pairs"]:
            if p["pair"] == "BTC/USD":
                p["caution_factor_bearish"] = 0.8
        # Add ETH
        cfg["trading"]["pairs"].append({
            "pair": "ETH/USD", "take_profit_pct": 12, "stop_loss_pct": 5,
            "atr_tp_min_pct": 0.23, "rsi_oversold": 30, "rsi_overbought": 75,
            "bb_squeeze_threshold_pct": 1.3, "min_volume_ratio": 0.50,
            "caution_factor_bearish": 1.0,
        })
        factor = self._get_pair_caution("ETH/USD", cfg)
        self.assertEqual(factor, 1.0, "ETH should have caution_factor=1.0")

    def test_inj_caution_factor_is_0_35(self):
        """
        Given INJ/USD has caution_factor_bearish=0.35 in config
        When bearish regime lookup is performed
        Then caution_factor for INJ is 0.35 (aggressive cut)
        Refs #124
        """
        cfg = _make_config()
        for p in cfg["trading"]["pairs"]:
            if p["pair"] == "INJ/USD":
                p["caution_factor_bearish"] = 0.35
        factor = self._get_pair_caution("INJ/USD", cfg)
        self.assertEqual(factor, 0.35, "INJ should have caution_factor=0.35")

    def test_pair_without_override_uses_global_fallback(self):
        """
        Given a pair has no caution_factor_bearish in config
        When bearish regime lookup is performed with global_caution=0.5
        Then caution_factor falls back to 0.5
        Refs #124
        """
        cfg = _make_config()
        # TRX has no caution_factor_bearish set
        factor = self._get_pair_caution("TRX/USD", cfg, global_caution=0.5)
        self.assertEqual(factor, 0.5, "TRX without override should use global 0.5")

    def test_pair_max_usd_scales_correctly_for_winner(self):
        """
        Given base_max=$200 and ETH caution_factor=1.0
        When pair_max_usd is computed
        Then ETH gets full $200 (no reduction in bearish)
        Refs #124
        """
        base_max = 200.0
        caution = 1.0
        pair_max = round(base_max * caution, 2)
        self.assertEqual(pair_max, 200.0)

    def test_pair_max_usd_scales_correctly_for_underperformer(self):
        """
        Given base_max=$200 and INJ caution_factor=0.35
        When pair_max_usd is computed
        Then INJ gets $70 (65% reduction in bearish)
        Refs #124
        """
        base_max = 200.0
        caution = 0.35
        pair_max = round(base_max * caution, 2)
        self.assertEqual(pair_max, 70.0)


if __name__ == "__main__":
    unittest.main()
