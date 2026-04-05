import unittest
import pandas as pd
from src.analysis.indicators import compute_indicators
from src.analysis.features import compute_dynamic_sl_values

class TestRiskIndicators(unittest.TestCase):
    def setUp(self):
        # We need a list of dicts, length > 220
        self.static_candles = []
        for i in range(250):
            self.static_candles.append({
                "timestamp": i * 900,
                "open": 100.0,
                "high": 105.0,
                "low": 95.0,
                "close": 102.0,
                "volume": 1000.0,
                "count": 10
            })

    def test_indicator_math(self):
        config = {
            "indicators": {
                "rsi_period": 14, 
                "macd_fast": 12, 
                "macd_slow": 26, 
                "macd_signal": 9,
                "bb_period": 20,
                "bb_std_dev": 2,
                "atr_period": 14,
                "min_candles_to_start": 220
            }
        }
        inds = compute_indicators(self.static_candles, config)
        
        self.assertIsNotNone(inds, "Should return an indicator dictionary")
        self.assertIn("macd_histogram", inds)
        self.assertIn("rsi_14", inds)
        self.assertIn("ema_9", inds)
        self.assertIn("ema_21", inds)
        self.assertIn("ema_50", inds)
        self.assertIn("atr_14", inds)

    def test_calculate_targets_dynamic_sl(self):
        config = {"trading": {"stop_loss_pct": 5.0}}
        signals = [
            {
                "pair": "SOL/USD",
                "indicators": {
                    "close": 100.0,
                    "atr_14": 5.0  # high volatility -> multiplier 4.0 -> sl_dist 20 -> capped to 5.0 (5%)
                }
            }
        ]
        
        sl_data = compute_dynamic_sl_values(signals, config)
        self.assertIn("SOL/USD", sl_data)
        # Should be strictly capped at 5.0%
        self.assertEqual(sl_data["SOL/USD"], 5.0)

if __name__ == '__main__':
    unittest.main()