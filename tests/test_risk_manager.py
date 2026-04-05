import unittest
from src.risk.risk_manager import RiskManager

class TestRiskManager(unittest.TestCase):
    def setUp(self):
        self.config = {
            "trading": {
                "stop_loss_pct": 5,
                "take_profit_pct": 10,
                "max_position_pct": 30,
            },
            "risk": {
                "min_cash_reserve_pct": 10,
            }
        }
        self.risk_mgr = RiskManager(self.config)

    def test_fat_finger_guard_max_buffer(self):
        # available_cash_usd = 1000
        # max_safe_allocation = 980
        # proposed = 990 -> rejected
        approved, reason, amount = self.risk_mgr.validate_buy(
            pair="BTC/USD",
            proposed_usd=990.0,
            portfolio_balance_usd=1000.0,
            available_cash_usd=1000.0,
            open_positions_count=0,
            daily_loss_usd=0.0,
            starting_balance_usd=1000.0,
            current_price=50000.0,
            baseline_price=50000.0
        )
        self.assertFalse(approved)
        self.assertIn("exceeds the 98% safe available balance buffer", reason)
        self.assertEqual(amount, 0.0)

    def test_minimum_order_size(self):
        # less than 5.0 -> rejected
        approved, _, amount = self.risk_mgr.validate_buy(
            pair="BTC/USD",
            proposed_usd=4.5,
            portfolio_balance_usd=100.0,
            available_cash_usd=100.0,
            open_positions_count=0,
            daily_loss_usd=0.0,
            starting_balance_usd=100.0,
            current_price=50000.0,
            baseline_price=50000.0
        )
        self.assertFalse(approved)
        self.assertEqual(amount, 0.0)

    def test_flash_crash_guard(self):
        # dropped 20%
        # baseline = 100, current = 80
        approved, reason, amount = self.risk_mgr.validate_buy(
            pair="SOL/USD",
            proposed_usd=50.0,
            portfolio_balance_usd=1000.0,
            available_cash_usd=1000.0,
            open_positions_count=0,
            daily_loss_usd=0.0,
            starting_balance_usd=1000.0,
            current_price=80.0,
            baseline_price=100.0
        )
        self.assertFalse(approved)
        self.assertIn("Flash Crash Guard triggered", reason)

    def test_fat_finger_token_quantity(self):
        # buying a token that crashed to essentially 0, proposed quantity > 500_000
        approved, reason, amount = self.risk_mgr.validate_buy(
            pair="SHIB/USD",
            proposed_usd=100.0,
            portfolio_balance_usd=1000.0,
            available_cash_usd=1000.0,
            open_positions_count=0,
            daily_loss_usd=0.0,
            starting_balance_usd=1000.0,
            current_price=0.0001,
            baseline_price=0.000101
        )
        self.assertFalse(approved)
        self.assertIn("Fat Finger Guard: Token quantity", reason)

if __name__ == "__main__":
    unittest.main()
