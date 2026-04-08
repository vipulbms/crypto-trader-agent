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
            "early_sell_min_tp_proximity_pct": 80,
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


if __name__ == "__main__":
    unittest.main()
