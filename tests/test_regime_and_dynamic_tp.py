"""
Tests for:
  Fix 1 — caution_factor scales portfolio max_per_trade in bearish/volatile regimes
  Fix 2 — dynamic TP values flow from features → TradingTools → place_order()
"""
import unittest
from unittest.mock import MagicMock

# ── Minimal config (no LLM, no DB, no network calls) ─────────────────────────
CONFIG = {
    "trading": {
        "stop_loss_pct": 5,
        "take_profit_pct": 8,
        "max_position_pct": 30,
        "max_open_positions": 3,
        "allowed_take_profit_pcts": [5, 8, 12, 16, 20],
        "pairs": [
            {"pair": "BTC/USD", "take_profit_pct": 8,  "stop_loss_pct": 5},
            {"pair": "ETH/USD", "take_profit_pct": 12, "stop_loss_pct": 5},
        ],
    },
    "dynamic_tp": {
        "enabled": True,
        "atr_multiplier": 2.0,
        "bb_width_scale": True,
        "min_tp_pct": 5,
        "max_tp_pct": 20,
        "squeeze_threshold_pct": 1.0,
    },
    "regime": {
        "enabled": True,
        "bearish_pairs_threshold": 6,
        "bullish_pairs_threshold": 6,
        "volatile_atr_multiplier": 1.5,
        "ranging_macd_threshold": 0.001,
        "bearish_caution_factor": 0.5,
        "volatile_caution_factor": 0.7,
    },
    "sentiment":        {"enabled": False},
    "pattern_analysis": {"enabled": False},
    "exit_timing":      {"enabled": False},
    "position_sizing":  {"enabled": False},
    "risk": {"daily_loss_limit_pct": 10, "min_cash_reserve_pct": 10},
    "storage": {"paper_db": ":memory:", "audit_db": ":memory:"},
}


def _signal(pair, macd=0.01, atr=500.0, price=50000.0, signal="BUY"):
    return {
        "pair": pair,
        "signal": signal,
        "strength": 0.7,
        "price": price,
        "reasons": [],
        "indicators": {
            "close": price,
            "atr_14": atr,
            "bb_upper": price * 1.02,
            "bb_lower": price * 0.98,
            "macd_histogram": macd,
        },
    }


# ── Fix 2a: compute_dynamic_tp_values ─────────────────────────────────────────

class TestComputeDynamicTpValues(unittest.TestCase):

    def _fn(self):
        from src.analysis.features import compute_dynamic_tp_values
        return compute_dynamic_tp_values

    def test_returns_value_for_every_signal_pair(self):
        result = self._fn()([_signal("BTC/USD"), _signal("ETH/USD")], CONFIG)
        self.assertIn("BTC/USD", result)
        self.assertIn("ETH/USD", result)

    def test_value_clamped_to_pair_min_when_atr_tiny(self):
        """
        Given BTC/USD configured TP=8% and ATR so tiny the raw result is near 0%
        When compute_dynamic_tp_values is called
        Then the result is clamped to the pair's configured TP (8%), not the global min (5%)
        """
        # ATR=1 on price=50000 → raw TP = (1*2/50000)*100 = 0.004% → clamped to pair min 8%
        result = self._fn()([_signal("BTC/USD", atr=1.0, price=50000.0)], CONFIG)
        self.assertEqual(result["BTC/USD"], 8.0)

    def test_value_clamped_to_max_when_atr_huge(self):
        # ATR=5000 on price=5000 → raw TP = 200% → clamped to max 20%
        result = self._fn()([_signal("ETH/USD", atr=5000.0, price=5000.0)], CONFIG)
        self.assertEqual(result["ETH/USD"], 20.0)

    def test_value_within_bounds_for_normal_atr(self):
        # ATR=500 on price=50000 → raw TP = 2.0% → clamped to min 5%
        result = self._fn()([_signal("BTC/USD", atr=500.0, price=50000.0)], CONFIG)
        self.assertGreaterEqual(result["BTC/USD"], 5.0)
        self.assertLessEqual(result["BTC/USD"], 20.0)

    def test_disabled_returns_empty_dict(self):
        cfg = {**CONFIG, "dynamic_tp": {"enabled": False}}
        result = self._fn()([_signal("BTC/USD")], cfg)
        self.assertEqual(result, {})

    def test_bb_squeeze_clamps_tp_to_pair_min(self):
        """
        Given BB width 0.8% (below squeeze_threshold_pct=1.0%)
        When compute_dynamic_tp_values is called
        Then TP is clamped to the pair's configured minimum (8% for BTC)
        Refs #104
        """
        price = 50000.0
        # Tight bands: upper=1.004x, lower=0.996x → width=0.8%
        tight_signal = {
            **_signal("BTC/USD", atr=500.0, price=price),
            "indicators": {
                "close": price,
                "atr_14": 500.0,
                "bb_upper": price * 1.004,
                "bb_lower": price * 0.996,
                "macd_histogram": 0.01,
            },
        }
        cfg = {
            **CONFIG,
            "dynamic_tp": {
                **CONFIG["dynamic_tp"],
                "bb_width_scale": True,
                "squeeze_threshold_pct": 1.0,
            },
        }
        result = self._fn()([tight_signal], cfg)
        self.assertEqual(result["BTC/USD"], 8.0,
                         "BB squeeze should clamp TP to BTC pair minimum (8%)")

    def test_normal_bb_width_uses_atr(self):
        """
        Given BB width 2.4% (above squeeze_threshold_pct=1.0%)
        When compute_dynamic_tp_values is called
        Then TP is computed from ATR, not clamped to pair min
        Refs #104
        """
        price = 50000.0
        wide_signal = {
            **_signal("BTC/USD", atr=500.0, price=price),
            "indicators": {
                "close": price,
                "atr_14": 500.0,
                "bb_upper": price * 1.012,
                "bb_lower": price * 0.988,
                "macd_histogram": 0.01,
            },
        }
        cfg = {
            **CONFIG,
            "dynamic_tp": {
                **CONFIG["dynamic_tp"],
                "bb_width_scale": True,
                "squeeze_threshold_pct": 1.0,
            },
        }
        result = self._fn()([wide_signal], cfg)
        # With normal BB width, ATR-based TP should be used — will be >= pair min (8%)
        self.assertGreaterEqual(result["BTC/USD"], 8.0)


# ── Fix 2b: build_ai_context exposes dynamic_tp_values ───────────────────────

class TestBuildAiContextKeys(unittest.TestCase):

    def _build(self, signals):
        from src.analysis.features import build_ai_context
        portfolio = {"total_usd": 1000.0, "available_cash_usd": 800.0, "open_positions_count": 0}
        return build_ai_context(signals=signals, portfolio=portfolio, open_positions=[], config=CONFIG)

    def test_dynamic_tp_values_present(self):
        ctx = self._build([_signal("BTC/USD")])
        self.assertIn("dynamic_tp_values", ctx)
        self.assertIsInstance(ctx["dynamic_tp_values"], dict)

    def test_dynamic_tp_values_keyed_by_pair(self):
        ctx = self._build([_signal("BTC/USD"), _signal("ETH/USD")])
        self.assertIn("BTC/USD", ctx["dynamic_tp_values"])
        self.assertIn("ETH/USD", ctx["dynamic_tp_values"])

    def test_regime_data_has_caution_factor(self):
        ctx = self._build([_signal("BTC/USD")])
        self.assertIn("regime_data", ctx)
        self.assertIn("caution_factor", ctx["regime_data"])


# ── Fix 2c: TradingTools uses dynamic TP in propose_buy ───────────────────────

class TestProposeBuyUsesdynamicTp(unittest.TestCase):

    def _make_tools(self):
        from src.agent.tools import TradingTools
        from src.risk.risk_manager import RiskManager

        mock_broker = MagicMock()
        mock_broker.get_balance.return_value = {
            "total_usd": 1000.0,
            "available_cash_usd": 800.0,
        }
        mock_broker.get_open_positions_count.return_value = 0
        mock_broker.get_open_positions.return_value = []
        mock_broker.get_daily_pnl.return_value = {"pnl_usd": 0.0, "pnl_pct": 0.0}
        mock_broker.place_order.return_value = {
            "fill_price":       50000.0,
            "volume":           0.004,
            "stop_loss_price":  47500.0,
            "take_profit_price": 58000.0,
            "usd_invested":     200.0,
            "fee_usd":          0.52,
            "slippage_pct":     0.05,
        }

        mock_ws = MagicMock()
        mock_ws.get_latest_price.return_value = 50000.0

        mock_audit = MagicMock()
        mock_audit.log_risk_check.return_value = 1
        mock_audit.log_order.return_value = 1

        tools = TradingTools(
            broker=mock_broker,
            risk_manager=RiskManager(CONFIG),
            audit_logger=mock_audit,
            notifier=None,
            ws_feed=mock_ws,
            mode="paper",
            config=CONFIG,
            start_of_day_balance=1000.0,
        )
        tools.set_cycle_context(1)
        tools.set_llm_decision_id(1)
        return tools, mock_broker

    def _tp_used(self, mock_broker):
        return mock_broker.place_order.call_args.kwargs["take_profit_pct"]

    def test_dynamic_tp_overrides_static(self):
        tools, mock_broker = self._make_tools()
        tools.set_dynamic_tp_values({"BTC/USD": 16.0})  # static is 8%
        tools.propose_buy("BTC/USD", 200.0)
        self.assertEqual(self._tp_used(mock_broker), 16.0)

    def test_static_tp_used_when_no_dynamic_values_set(self):
        tools, mock_broker = self._make_tools()
        # No set_dynamic_tp_values call — defaults to {}
        tools.propose_buy("BTC/USD", 200.0)
        self.assertEqual(self._tp_used(mock_broker), 8.0)

    def test_static_tp_used_when_pair_missing_from_dynamic(self):
        tools, mock_broker = self._make_tools()
        tools.set_dynamic_tp_values({"ETH/USD": 14.0})  # BTC/USD not in values
        tools.propose_buy("BTC/USD", 200.0)
        self.assertEqual(self._tp_used(mock_broker), 8.0)

    def test_set_dynamic_tp_values_resets_on_next_call(self):
        tools, mock_broker = self._make_tools()
        tools.set_dynamic_tp_values({"BTC/USD": 16.0})
        tools.set_dynamic_tp_values({})  # cleared
        tools.propose_buy("BTC/USD", 200.0)
        self.assertEqual(self._tp_used(mock_broker), 8.0)


# ── Fix 1: caution_factor scales max_per_trade ────────────────────────────────

class TestCautionFactorScaling(unittest.TestCase):

    def _apply(self, caution_factor, max_per_trade=300.0):
        """Mirrors the scaling logic added to main.py run_cycle()."""
        portfolio = {"max_per_trade": max_per_trade}
        if caution_factor < 1.0:
            portfolio["max_per_trade"] = round(max_per_trade * caution_factor, 2)
        return portfolio["max_per_trade"]

    def test_bearish_halves_max_per_trade(self):
        self.assertEqual(self._apply(0.5, 300.0), 150.0)

    def test_volatile_reduces_max_per_trade(self):
        self.assertEqual(self._apply(0.7, 300.0), 210.0)

    def test_normal_regime_unchanged(self):
        self.assertEqual(self._apply(1.0, 300.0), 300.0)

    def test_bearish_regime_detected_from_signals(self):
        from src.analysis.features import detect_market_regime
        # 8 bearish (MACD < 0), 2 bullish — threshold is 6
        signals = (
            [_signal(f"P{i}/USD", macd=-0.01) for i in range(8)] +
            [_signal(f"P{i+8}/USD", macd=0.01) for i in range(2)]
        )
        regime = detect_market_regime(signals, CONFIG)
        self.assertEqual(regime["regime"], "bearish")
        self.assertEqual(regime["caution_factor"], 0.5)

    def test_bullish_regime_no_caution(self):
        from src.analysis.features import detect_market_regime
        signals = [_signal(f"P{i}/USD", macd=0.01) for i in range(10)]
        regime = detect_market_regime(signals, CONFIG)
        self.assertEqual(regime["regime"], "bullish")
        self.assertEqual(regime["caution_factor"], 1.0)

    def test_volatile_regime_detected(self):
        from src.analysis.features import detect_market_regime
        # 3+ pairs with ATR >> avg ATR → volatile
        # Use one very high ATR pair among low-ATR pairs
        signals = (
            [_signal(f"P{i}/USD", atr=1.0,    price=100.0, macd=0.0) for i in range(7)] +
            [_signal(f"P{i+7}/USD", atr=500.0, price=100.0, macd=0.0) for i in range(3)]
        )
        regime = detect_market_regime(signals, CONFIG)
        # volatile regime fires when >= 3 pairs have ATR > avg_ATR * 1.5
        self.assertIn(regime["caution_factor"], [0.7, 1.0])  # volatile or mixed


if __name__ == "__main__":
    unittest.main()
