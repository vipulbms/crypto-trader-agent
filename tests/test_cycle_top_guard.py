"""
Tests for #205 — MVRV Z-Score / NUPL cycle-top guard.
"""

import os
import sqlite3
import sys
import tempfile
import time
import types
import unittest
from datetime import datetime, timezone as _tz
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

timing_mod = types.ModuleType("src.utils.timing")
timing_mod.timed = lambda *a, **kw: (lambda f: f)
sys.modules["src.utils.timing"] = timing_mod

tz_mod = types.ModuleType("src.utils.tz")
tz_mod.SGT = _tz.utc
tz_mod.now_sgt = lambda: datetime.now(_tz.utc)
tz_mod.now_sgt_iso = lambda: datetime.now(_tz.utc).isoformat()
sys.modules["src.utils.tz"] = tz_mod

from src.agent.prompts import build_cycle_prompt
from src.analysis.features import (
    _cycle_top_cache,
    apply_cycle_top_guard,
    build_cycle_top_context,
    fetch_cycle_top_indicators,
)
from src.risk.risk_manager import RiskManager


CONFIG = {
    "risk": {
        "daily_loss_limit_pct": 10,
        "min_cash_reserve_pct": 5,
        "min_order_usd": 20,
        "cycle_top_guard": {
            "enabled": True,
            "mvrv_z_danger": 7.0,
            "nupl_danger": 0.70,
            "mvrv_url": "https://example.com/mvrv",
            "nupl_url": "https://example.com/nupl",
            "fetch_timeout_secs": 8,
            "cache_hours": 24,
        },
    },
    "trading": {
        "stop_loss_pct": 5,
        "take_profit_pct": 8,
        "max_position_pct": 20,
        "max_open_positions": 10,
        "pairs": [
            {"pair": "BTC/USD", "pair_tier": 1, "take_profit_pct": 8},
            {"pair": "ETH/USD", "pair_tier": 2, "take_profit_pct": 12},
            {"pair": "INJ/USD", "pair_tier": 3, "take_profit_pct": 16},
            {"pair": "PEPE/USD", "pair_tier": 4, "take_profit_pct": 20},
        ],
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
    "sentiment": {"enabled": False},
    "pattern_analysis": {"enabled": False},
    "exit_timing": {"enabled": False},
    "position_sizing": {"enabled": False},
}


def _mock_indicator_response(value, key="value"):
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {
        "success": True,
        "data": {
            "list": [
                {"time": 1, key: value - 0.1},
                {"time": 2, key: value},
            ]
        },
    }
    return mock_resp


def _signal(pair, tier, signal="BUY"):
    return {
        "pair": pair,
        "signal": signal,
        "strength": 0.8,
        "price": 100.0,
        "pair_tier": tier,
        "reasons": ["test"],
        "indicators": {
            "close": 100.0,
            "atr_14": 2.0,
            "rsi_14": 30.0,
            "macd_histogram": 0.1,
            "bb_lower": 95.0,
            "bb_upper": 105.0,
        },
    }


class TestFetchCycleTopIndicators(unittest.TestCase):

    def setUp(self):
        _cycle_top_cache["data"] = None
        _cycle_top_cache["fetched_at"] = 0

    @patch.dict(os.environ, {"COINGLASS_API_KEY": "test-key"}, clear=False)
    def test_fetch_returns_active_payload(self):
        with patch(
            "requests.get",
            side_effect=[
                _mock_indicator_response(7.4, key="mvrvZScore"),
                _mock_indicator_response(0.73, key="nupl"),
            ],
        ):
            result = fetch_cycle_top_indicators(CONFIG)

        self.assertIsNotNone(result)
        self.assertEqual(result["mvrv_z_score"], 7.4)
        self.assertEqual(result["nupl"], 0.73)
        self.assertTrue(result["cycle_top_active"])

    @patch.dict(os.environ, {"COINGLASS_API_KEY": "test-key"}, clear=False)
    def test_db_cache_prevents_refetch(self):
        handle = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        path = handle.name
        handle.close()
        conn = sqlite3.connect(path)
        conn.execute("CREATE TABLE agent_state (key TEXT PRIMARY KEY, value TEXT)")
        conn.execute(
            "INSERT INTO agent_state VALUES (?, ?)",
            ("cycle_top_guard_payload", '{"mvrv_z_score": 7.2, "nupl": 0.71, "cycle_top_active": true}'),
        )
        conn.execute(
            "INSERT INTO agent_state VALUES (?, ?)",
            ("cycle_top_guard_fetched_at", str(time.time())),
        )
        conn.commit()
        conn.close()

        with patch("requests.get") as mock_get:
            result = fetch_cycle_top_indicators(CONFIG, db_path=path)

        self.assertTrue(result["cycle_top_active"])
        self.assertEqual(mock_get.call_count, 0)

    def test_missing_api_key_returns_none(self):
        with patch.dict(os.environ, {}, clear=True):
            result = fetch_cycle_top_indicators(CONFIG)
        self.assertIsNone(result)


class TestCycleTopPromptAndSuppression(unittest.TestCase):

    def test_apply_cycle_top_guard_suppresses_only_tier3_and_tier4_buys(self):
        signals = [
            _signal("ETH/USD", 2),
            _signal("INJ/USD", 3),
            _signal("PEPE/USD", 4),
        ]

        suppressed = apply_cycle_top_guard(
            signals,
            CONFIG,
            {"mvrv_z_score": 7.3, "nupl": 0.72, "cycle_top_active": True},
        )

        self.assertEqual(suppressed, 2)
        self.assertEqual(signals[0]["signal"], "BUY")
        self.assertEqual(signals[1]["signal"], "HOLD")
        self.assertEqual(signals[2]["signal"], "HOLD")
        self.assertIn("Cycle top guard active", signals[1]["reasons"])

    def test_prompt_includes_cycle_top_warning_block(self):
        prompt = build_cycle_prompt(
            cycle_time="2026-04-11 12:00:00",
            portfolio={
                "total_usd": 1000.0,
                "available_cash_usd": 900.0,
                "open_positions_count": 0,
                "daily_pnl_usd": 0.0,
                "daily_pnl_pct": 0.0,
                "open_positions": [],
                "max_per_trade": 200.0,
            },
            signals=[_signal("BTC/USD", 1)],
            mode="paper",
            pair_tp_config={"BTC/USD": 8},
            ai_context={
                "cycle_top": build_cycle_top_context(
                    {"mvrv_z_score": 7.5, "nupl": 0.74, "cycle_top_active": True},
                    CONFIG,
                )
            },
            max_buys_per_cycle=7,
            min_order_usd=20.0,
        )

        self.assertIn("[CYCLE TOP WARNING]", prompt)
        self.assertIn("Block new Tier 3 / Tier 4 BUYs", prompt)


class TestRiskManagerCycleTopGuard(unittest.TestCase):

    def test_validate_buy_rejects_tier3_when_cycle_top_active(self):
        risk = RiskManager(CONFIG)
        risk.set_cycle_top_state(True, {"mvrv_z_score": 7.4, "nupl": 0.73})

        approved, reason, capped = risk.validate_buy(
            pair="INJ/USD",
            proposed_usd=50.0,
            portfolio_balance_usd=1000.0,
            available_cash_usd=900.0,
            open_positions_count=0,
            daily_loss_usd=0.0,
            starting_balance_usd=1000.0,
            current_price=100.0,
            baseline_price=100.0,
            candle_timestamp_sec=0.0,
        )

        self.assertFalse(approved)
        self.assertEqual(capped, 0.0)
        self.assertIn("Cycle top guard active", reason)

    def test_validate_buy_allows_tier1_when_cycle_top_active(self):
        risk = RiskManager(CONFIG)
        risk.set_cycle_top_state(True, {"mvrv_z_score": 7.4, "nupl": 0.73})

        approved, reason, capped = risk.validate_buy(
            pair="BTC/USD",
            proposed_usd=50.0,
            portfolio_balance_usd=1000.0,
            available_cash_usd=900.0,
            open_positions_count=0,
            daily_loss_usd=0.0,
            starting_balance_usd=1000.0,
            current_price=100.0,
            baseline_price=100.0,
            candle_timestamp_sec=0.0,
        )

        self.assertTrue(approved)
        self.assertGreater(capped, 0.0)


if __name__ == "__main__":
    unittest.main()