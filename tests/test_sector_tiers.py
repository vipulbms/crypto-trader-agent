"""
Tests for #203 — sector rotation via pair tiers and BTC dominance rising caps.
"""
import unittest
from unittest.mock import MagicMock


CONFIG = {
    "regime": {
        "enabled": True,
        "bearish_pairs_threshold": 6,
        "bullish_pairs_threshold": 6,
        "volatile_atr_multiplier": 1.5,
        "ranging_macd_threshold": 0.001,
        "bearish_caution_factor": 0.5,
        "volatile_caution_factor": 0.7,
        "btc_dominance_rising_caution_multiplier": 0.7,
        "tier3_dominance_rising_multiplier": 0.5,
        "tier4_dominance_rising_multiplier": 0.3,
    },
    "trading": {
        "stop_loss_pct": 5,
        "take_profit_pct": 8,
        "max_position_pct": 20,
        "max_open_positions": 10,
        "max_buys_per_cycle": 7,
        "pairs": [
            {"pair": "BTC/USD", "pair_tier": 1, "caution_factor_bearish": 1.0, "take_profit_pct": 8},
            {"pair": "SOL/USD", "pair_tier": 2, "caution_factor_bearish": 0.6, "take_profit_pct": 16},
            {"pair": "INJ/USD", "pair_tier": 3, "caution_factor_bearish": 0.35, "take_profit_pct": 16},
            {"pair": "PEPE/USD", "pair_tier": 4, "caution_factor_bearish": 0.25, "take_profit_pct": 20},
        ],
    },
    "sentiment": {"enabled": False},
    "pattern_analysis": {"enabled": False},
    "exit_timing": {"enabled": False},
    "position_sizing": {"enabled": False},
    "risk": {"min_order_usd": 20},
}


def _signal(pair, signal="BUY"):
    return {
        "pair": pair,
        "signal": signal,
        "strength": 0.7,
        "price": 100.0,
        "reasons": ["test"],
        "indicators": {
            "close": 100.0,
            "atr_14": 2.5,
            "rsi_14": 28.0,
            "macd_histogram": 0.12,
            "bb_lower": 95.0,
            "bb_upper": 105.0,
        },
    }


class TestComputePairRegimeCaps(unittest.TestCase):

    def test_bearish_rising_btc_dominance_applies_tier_multipliers(self):
        from src.analysis.features import compute_pair_regime_caps

        regime_data = {
            "regime": "bearish",
            "caution_factor": 0.5,
            "btc_dominance_trend": "rising",
        }
        signals = [_signal("BTC/USD"), _signal("SOL/USD"), _signal("INJ/USD"), _signal("PEPE/USD")]

        caps = compute_pair_regime_caps(signals, 100.0, regime_data, CONFIG)

        self.assertEqual(caps["BTC/USD"]["pair_tier"], 1)
        self.assertEqual(caps["BTC/USD"]["pair_max_usd"], 100.0)
        self.assertEqual(caps["SOL/USD"]["pair_max_usd"], 42.0)   # 100 * 0.6 * 0.7
        self.assertEqual(caps["INJ/USD"]["pair_max_usd"], 17.5)   # 100 * 0.35 * 0.5
        self.assertEqual(caps["PEPE/USD"]["pair_max_usd"], 7.5)   # 100 * 0.25 * 0.3

    def test_flat_btc_dominance_uses_plain_bearish_caution(self):
        from src.analysis.features import compute_pair_regime_caps

        regime_data = {
            "regime": "bearish",
            "caution_factor": 0.5,
            "btc_dominance_trend": "flat",
        }
        signals = [_signal("INJ/USD"), _signal("PEPE/USD")]

        caps = compute_pair_regime_caps(signals, 100.0, regime_data, CONFIG)

        self.assertEqual(caps["INJ/USD"]["pair_max_usd"], 35.0)
        self.assertEqual(caps["PEPE/USD"]["pair_max_usd"], 25.0)


class TestPromptShowsTier(unittest.TestCase):

    def test_prompt_includes_tier_label(self):
        from src.agent.prompts import build_cycle_prompt

        signals = [_signal("INJ/USD")]
        signals[0]["pair_tier"] = 3
        signals[0]["pair_max_usd"] = 17.5
        portfolio = {
            "total_usd": 1000.0,
            "available_cash_usd": 900.0,
            "open_positions_count": 0,
            "daily_pnl_usd": 0.0,
            "daily_pnl_pct": 0.0,
            "open_positions": [],
            "max_per_trade": 200.0,
        }
        prompt = build_cycle_prompt(
            cycle_time="2026-04-11 12:00:00",
            portfolio=portfolio,
            signals=signals,
            mode="paper",
            pair_tp_config={"INJ/USD": 16},
            ai_context={},
            max_buys_per_cycle=7,
            min_order_usd=20.0,
        )

        # New pipe format: max_buy_usd is embedded as a pipe field (rounds to nearest int)
        self.assertIn("pair|INJ/USD", prompt)
        self.assertIn("max_buy_usd|18", prompt)  # 17.5 rounds to 18 with :.0f


class TestTradingToolsPairCap(unittest.TestCase):

    def _make_tools(self):
        from src.agent.tools import TradingTools

        mock_broker = MagicMock()
        mock_broker.get_balance.return_value = {
            "total_usd": 1000.0,
            "available_cash_usd": 900.0,
        }
        mock_broker.get_open_positions_count.return_value = 0
        mock_broker.get_open_positions.return_value = []
        mock_broker.get_daily_pnl.return_value = {"pnl_usd": 0.0, "pnl_pct": 0.0}
        mock_broker.place_order.return_value = {
            "fill_price": 100.0,
            "volume": 0.5,
            "stop_loss_price": 95.0,
            "take_profit_price": 116.0,
            "usd_invested": 50.0,
            "fee_usd": 0.0,
            "slippage_pct": 0.05,
        }

        mock_risk = MagicMock()
        mock_risk.validate_buy.return_value = (True, "", 50.0)
        mock_risk.get_stop_loss_pct.return_value = 5.0
        mock_risk.get_take_profit_pct.return_value = 16.0
        mock_risk.calculate_stop_loss_price.return_value = 95.0
        mock_risk.calculate_take_profit_price.return_value = 116.0

        mock_ws = MagicMock()
        mock_ws.get_latest_price.return_value = 100.0
        mock_ws.get_candles.return_value = []
        mock_ws.current_candle_time = None

        mock_audit = MagicMock()
        mock_audit.log_risk_check.return_value = 1
        mock_audit.log_order.return_value = 2

        tools = TradingTools(
            broker=mock_broker,
            risk_manager=mock_risk,
            audit_logger=mock_audit,
            notifier=None,
            ws_feed=mock_ws,
            mode="paper",
            config=CONFIG,
            start_of_day_balance=1000.0,
        )
        return tools, mock_risk, mock_broker

    def test_propose_buy_caps_requested_amount_to_pair_max(self):
        tools, mock_risk, mock_broker = self._make_tools()
        tools.set_pair_max_usd({"INJ/USD": 50.0})

        result = tools.propose_buy("INJ/USD", 100.0)

        self.assertIn("BUY EXECUTED", result)
        self.assertEqual(mock_risk.validate_buy.call_args.kwargs["proposed_usd"], 50.0)
        self.assertEqual(mock_broker.place_order.call_args.kwargs["usd_amount"], 50.0)


if __name__ == "__main__":
    unittest.main()
