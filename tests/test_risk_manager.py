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

    def test_trading_hours_guard(self):
        import datetime
        from unittest.mock import patch
        
        # Enable trading hours logic
        self.config["trading"]["allowed_trading_hours"] = {
            "enabled": True,
            "start_hour_utc": 12,
            "end_hour_utc": 20
        }
        self.risk_mgr = RiskManager(self.config)

        # Mock current time to 10:00 UTC (outside window)
        class MockDatetime(datetime.datetime):
            @classmethod
            def now(cls, tz=None):
                return datetime.datetime(2026, 4, 5, 10, 0, 0, tzinfo=datetime.timezone.utc)

        with patch("src.risk.risk_manager.datetime.datetime", MockDatetime):
            approved, reason, amount = self.risk_mgr.validate_buy(
                pair="BTC/USD",
                proposed_usd=100.0,
                portfolio_balance_usd=1000.0,
                available_cash_usd=1000.0,
                open_positions_count=0,
                daily_loss_usd=0.0,
                starting_balance_usd=1000.0,
                current_price=50000.0,
                baseline_price=50000.0
            )

        self.assertFalse(approved)
        self.assertIn("Time-of-Day Guard", reason)

        # Mock current time to 14:00 UTC (inside window)
        class MockDatetimeInside(datetime.datetime):
            @classmethod
            def now(cls, tz=None):
                return datetime.datetime(2026, 4, 5, 14, 0, 0, tzinfo=datetime.timezone.utc)

        with patch("src.risk.risk_manager.datetime.datetime", MockDatetimeInside):
            approved, reason, amount = self.risk_mgr.validate_buy(
                pair="BTC/USD",
                proposed_usd=100.0,
                portfolio_balance_usd=1000.0,
                available_cash_usd=1000.0,
                open_positions_count=0,
                daily_loss_usd=0.0,
                starting_balance_usd=1000.0,
                current_price=50000.0,
                baseline_price=50000.0
            )

        self.assertTrue(approved)
        self.assertIn("Approved", reason)

class TestValidateSellTPProximityGuard(unittest.TestCase):
    """
    Tests for the Early Exit Guard in validate_sell().

    Given a position with a configured take_profit_pct
    When propose_sell is called at various P&L levels
    Then validate_sell() enforces the 60% TP proximity rule (BRD FR-20)
    """

    def setUp(self):
        self.config = {
            "trading": {
                "stop_loss_pct": 5,
                "take_profit_pct": 12,
                "min_profit_floor_pct": 1.0,
                "early_sell_min_tp_proximity_pct": 60,
                "max_position_pct": 30,
            },
            "risk": {
                "min_cash_reserve_pct": 10,
                "circuit_breaker": {"enabled": False},
            },
        }
        self.rm = RiskManager(self.config)

    def _pos(self, entry_price: float, take_profit_pct: float) -> list:
        return [{"entry_price": entry_price, "take_profit_pct": take_profit_pct}]

    def test_sell_blocked_below_60_pct_of_tp(self):
        """
        Given TP=12% and entry=$100
        When current price is $105 (+5% P&L — only 42% of 12% TP)
        Then validate_sell() returns False with Early Exit Guard reason
        """
        approved, reason, _ = self.rm.validate_sell(
            pair="ETH/USD",
            open_positions=self._pos(entry_price=100.0, take_profit_pct=12.0),
            current_price=105.0,
        )
        self.assertFalse(approved)
        self.assertIn("Early Exit Guard", reason)

    def test_sell_allowed_at_65_pct_of_tp(self):
        """
        Given TP=12% and entry=$100
        When current price is $107.80 (+7.8% P&L — 65% of 12% TP, above 60% gate)
        Then validate_sell() returns True
        """
        approved, reason, _ = self.rm.validate_sell(
            pair="ETH/USD",
            open_positions=self._pos(entry_price=100.0, take_profit_pct=12.0),
            current_price=107.80,
        )
        self.assertTrue(approved)
        self.assertIn("Approved", reason)

    def test_sell_always_allowed_above_100_pct_of_tp(self):
        """
        Given TP=12% and entry=$100
        When current price is $113 (+13% P&L — above 100% of TP target)
        Then validate_sell() returns True
        """
        approved, reason, _ = self.rm.validate_sell(
            pair="ETH/USD",
            open_positions=self._pos(entry_price=100.0, take_profit_pct=12.0),
            current_price=113.0,
        )
        self.assertTrue(approved)
        self.assertIn("Approved", reason)

    def test_sell_blocked_by_profit_floor_below_tp_guard(self):
        """
        Given TP=12% and entry=$100
        When current price is $100.50 (+0.5% P&L — below 1% profit floor)
        Then validate_sell() returns False with Minimum Profit Floor reason (floor check fires first)
        """
        approved, reason, _ = self.rm.validate_sell(
            pair="ETH/USD",
            open_positions=self._pos(entry_price=100.0, take_profit_pct=12.0),
            current_price=100.50,
        )
        self.assertFalse(approved)
        self.assertIn("Minimum Profit Floor", reason)

    def test_sell_allowed_when_tp_pct_missing(self):
        """
        Given a position with no take_profit_pct recorded
        When P&L is above the profit floor
        Then validate_sell() approves (no proximity guard without TP info)
        """
        approved, reason, _ = self.rm.validate_sell(
            pair="BTC/USD",
            open_positions=[{"entry_price": 80000.0}],  # no take_profit_pct key
            current_price=81200.0,  # +1.5% — above 1% floor
        )
        self.assertTrue(approved)
        self.assertIn("Approved", reason)


class TestAtrBasedStopLoss(unittest.TestCase):
    """
    Tests for S12.4.1 — ATR-based stop-loss at entry.
    get_stop_loss_pct(pair, atr, price) should compute sl_pct = (multiplier × ATR / price) × 100
    clamped to [min_stop_loss_pct, max_stop_loss_pct].
    """

    def _make_rm(self, enabled: bool, multiplier: float = 1.5, min_pct: float = 1.0, max_pct: float = 5.0):
        config = {
            "trading": {"stop_loss_pct": 5},
            "risk": {},
            "atr_stop_loss": {
                "enabled": enabled,
                "atr_multiplier": multiplier,
                "min_stop_loss_pct": min_pct,
                "max_stop_loss_pct": max_pct,
            },
        }
        return RiskManager(config)

    def test_atr_sl_basic_computation(self):
        """
        Given atr_multiplier=1.5, ATR=100, price=10000
        sl_pct = (1.5 × 100 / 10000) × 100 = 1.5%
        Expected: 1.5 (within [1.0, 5.0])
        """
        rm = self._make_rm(enabled=True)
        sl = rm.get_stop_loss_pct("BTC/USD", atr=100.0, price=10000.0)
        self.assertAlmostEqual(sl, 1.5, places=2)

    def test_atr_sl_clamped_to_max(self):
        """
        Given atr_multiplier=1.5, ATR=500, price=10000
        sl_pct = (1.5 × 500 / 10000) × 100 = 7.5% → clamped to max 5.0%
        """
        rm = self._make_rm(enabled=True)
        sl = rm.get_stop_loss_pct("SOL/USD", atr=500.0, price=10000.0)
        self.assertEqual(sl, 5.0)

    def test_atr_sl_disabled_falls_back_to_fixed(self):
        """
        When atr_stop_loss.enabled=False, get_stop_loss_pct returns trading.stop_loss_pct (5%).
        """
        rm = self._make_rm(enabled=False)
        sl = rm.get_stop_loss_pct("ETH/USD", atr=100.0, price=3000.0)
        self.assertEqual(sl, 5)


class TestMinOrderUsdFloor(unittest.TestCase):
    """#126 — $5 position must be rejected when min_order_usd is $20."""

    def setUp(self):
        self.config = {
            "trading": {
                "stop_loss_pct": 5,
                "take_profit_pct": 10,
                "max_position_pct": 30,
            },
            "risk": {
                "min_cash_reserve_pct": 5,
                "min_order_usd": 20.0,
            },
        }
        self.risk_mgr = RiskManager(self.config)

    def test_micro_position_rejected_at_20_floor(self):
        """A $5 proposed trade must be rejected when min_order_usd=20."""
        approved, reason, amount = self.risk_mgr.validate_buy(
            pair="DOGE/USD",
            proposed_usd=5.0,
            portfolio_balance_usd=1000.0,
            available_cash_usd=100.0,
            open_positions_count=0,
            daily_loss_usd=0.0,
            starting_balance_usd=1000.0,
            current_price=0.10,
            baseline_price=0.10,
        )
        self.assertFalse(approved)
        self.assertEqual(amount, 0.0)

    def test_deployable_cash_below_floor_rejected(self):
        """If deployable cash (available - reserve) < min_order_usd, reject immediately."""
        # portfolio=$1000, reserve=5% → $50. available=$60 → deployable=$10 < $20
        approved, reason, amount = self.risk_mgr.validate_buy(
            pair="ADA/USD",
            proposed_usd=10.0,
            portfolio_balance_usd=1000.0,
            available_cash_usd=60.0,
            open_positions_count=0,
            daily_loss_usd=0.0,
            starting_balance_usd=1000.0,
            current_price=0.50,
            baseline_price=0.50,
        )
        self.assertFalse(approved)
        self.assertIn("min_order_usd", reason)
        self.assertEqual(amount, 0.0)

    def test_valid_position_above_floor_approved(self):
        """A $25 proposed trade must pass the $20 floor."""
        approved, _, amount = self.risk_mgr.validate_buy(
            pair="DOGE/USD",
            proposed_usd=25.0,
            portfolio_balance_usd=1000.0,
            available_cash_usd=500.0,
            open_positions_count=0,
            daily_loss_usd=0.0,
            starting_balance_usd=1000.0,
            current_price=0.10,
            baseline_price=0.10,
        )
        self.assertTrue(approved)
        self.assertGreater(amount, 0.0)

    def test_max_open_positions_blocked_when_no_cash(self):
        """Count cap fires when count >= max AND deployable cash < min_order_usd (#165).
        portfolio=$1000, reserve=5%→$50, available=$65 → deployable=$15 < $20."""
        approved, reason, _ = self.risk_mgr.validate_buy(
            pair="SOL/USD",
            proposed_usd=25.0,
            portfolio_balance_usd=1000.0,
            available_cash_usd=65.0,    # deployable=65-50=$15 < min_order_usd=$20
            open_positions_count=3,
            daily_loss_usd=0.0,
            starting_balance_usd=1000.0,
        )
        self.assertFalse(approved)
        self.assertIn("Max open positions reached", reason)

    def test_max_open_positions_allowed_when_cash_available(self):
        """Count cap must NOT fire when cash is available — fall through to cash guards (#165)."""
        # Live scenario: 5 positions open but $594 cash available.
        # max_open_positions defaults to 3 in this config; override via a fresh manager.
        cfg = {
            "trading": {
                "stop_loss_pct": 5,
                "take_profit_pct": 10,
                "max_position_pct": 30,
                "max_open_positions": 5,
            },
            "risk": {
                "min_cash_reserve_pct": 5,
                "min_order_usd": 20,
            },
        }
        risk = RiskManager(cfg)
        approved, reason, amount = risk.validate_buy(
            pair="BTC/USD",
            proposed_usd=100.0,
            portfolio_balance_usd=1000.0,
            available_cash_usd=594.0,   # deployable=$544 >> $20 — should pass count gate
            open_positions_count=5,
            daily_loss_usd=0.0,
            starting_balance_usd=1000.0,
        )
        self.assertTrue(approved, f"Expected approved but got: {reason}")
        self.assertGreater(amount, 0.0)


class TestPaperBrokerOverdrawGuard(unittest.TestCase):
    """#129 — place_order() must raise ValueError if wallet would go negative."""

    def _make_broker(self, starting_cash: float):
        import tempfile
        from src.storage.database import init_paper_db
        from src.exchange.paper_broker import PaperBroker

        tmp = tempfile.mktemp(suffix=".db")
        init_paper_db(tmp, starting_cash)
        return PaperBroker(paper_db=tmp, slippage_pct=0.0, maker_fee_pct=0.0, config={})

    def test_place_order_raises_on_insufficient_cash(self):
        """Wallet has $10; trying to buy $50 worth must raise ValueError."""
        broker = self._make_broker(10.0)
        with self.assertRaises(ValueError) as ctx:
            broker.place_order(
                pair="BTC/USD",
                side="buy",
                usd_amount=50.0,
                current_price=50000.0,
                stop_loss_pct=5.0,
                take_profit_pct=8.0,
            )
        self.assertIn("Insufficient funds", str(ctx.exception))

    def test_place_order_succeeds_within_balance(self):
        """Wallet has $1000; buying $50 must succeed without raising."""
        broker = self._make_broker(1000.0)
        result = broker.place_order(
            pair="ETH/USD",
            side="buy",
            usd_amount=50.0,
            current_price=3000.0,
            stop_loss_pct=5.0,
            take_profit_pct=12.0,
        )
        self.assertIn("position_id", result)
        balance = broker.get_balance()
        self.assertGreater(balance["available_cash_usd"], 0.0)


if __name__ == "__main__":
    unittest.main()
