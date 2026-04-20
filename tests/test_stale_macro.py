"""
Tests for #259 — Stale macro data carry-forward for Fear & Greed and BTC dominance.

Tests cover:
  1. fetch_fear_greed() returns stale data on API failure when within TTL
  2. fetch_fear_greed() returns None when cache is cold (no prior data)
  3. fetch_fear_greed() returns None when stale data exceeds TTL
  4. fetch_fear_greed() stale data includes stale_age_hours key
  5. fetch_btc_dominance() returns stale data on API failure when within TTL
  6. fetch_btc_dominance() returns None when cache is cold
  7. fetch_btc_dominance() stale data includes stale_age_hours key
  8. build_sentiment_context() shows 'treat as neutral' when data is None
  9. build_sentiment_context() shows '[stale Xh ago]' label when data is stale
  10. build_cycle_prompt() task instructions include null-macro guidance (rule 6)
"""
import sys, os, time, types, unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# ── stub heavy deps ──────────────────────────────────────────────────────────
timing_mod = types.ModuleType("src.utils.timing")
timing_mod.timed = lambda *a, **kw: (lambda f: f)
timing_mod.set_cycle_id = lambda *a: None
timing_mod.set_request_id = lambda *a: None
timing_mod.current_cycle_id = type("_CV", (), {"get": staticmethod(lambda: 0)})()
sys.modules["src.utils.timing"] = timing_mod

tz_mod = types.ModuleType("src.utils.tz")
from datetime import datetime, timezone as _tz
tz_mod.SGT = _tz.utc
tz_mod.now_sgt = lambda: datetime.now(_tz.utc)
tz_mod.now_sgt_iso = lambda: datetime.now(_tz.utc).isoformat()
tz_mod.to_sgt = lambda dt: dt
sys.modules["src.utils.tz"] = tz_mod
# ─────────────────────────────────────────────────────────────────────────────

import src.analysis.features as features
from src.analysis.features import (
    fetch_fear_greed,
    fetch_btc_dominance,
    build_sentiment_context,
    _sentiment_cache,
    _btc_dom_cache,
)
from src.agent.prompts import build_cycle_prompt

# ─── shared config ────────────────────────────────────────────────────────────

_SENTIMENT_CONFIG = {
    "sentiment": {
        "enabled": True,
        "fear_greed_url": "https://api.alternative.me/fng/?limit=1",
        "fetch_timeout_secs": 5,
        "cache_minutes": 60,
        "stale_ttl_hours": 4,
        "extreme_fear_threshold": 25,
        "extreme_greed_threshold": 75,
    }
}

_DOM_CONFIG = {
    "regime": {
        "enabled": True,
        "bearish_pairs_threshold": 6,
        "bullish_pairs_threshold": 6,
        "volatile_atr_multiplier": 1.5,
        "ranging_macd_threshold": 0.001,
        "bearish_caution_factor": 0.5,
        "volatile_caution_factor": 0.7,
        "btc_dominance": {
            "enabled": True,
            "url": "https://api.coingecko.com/api/v3/global",
            "fetch_timeout_secs": 5,
            "cache_minutes": 120,
            "stale_ttl_hours": 24,
            "trend_min_change_pp": 0.5,
            "trend_lookback_days": 3,
        },
    }
}


def _reset_sentiment_cache():
    _sentiment_cache["data"] = None
    _sentiment_cache["fetched_at"] = 0


def _reset_dom_cache():
    _btc_dom_cache["data"] = None
    _btc_dom_cache["fetched_at"] = 0


# ─────────────────────────────────────────────────────────────────────────────


class TestFearGreedStaleCarryForward(unittest.TestCase):

    def setUp(self):
        _reset_sentiment_cache()

    def test_returns_stale_data_on_api_failure_within_ttl(self):
        """On fetch failure, cached data within TTL is returned instead of None."""
        # Seed cache with fresh-enough data (2 hours old, TTL = 4h)
        _sentiment_cache["data"] = {"value": 21, "label": "Extreme Fear", "timestamp": ""}
        _sentiment_cache["fetched_at"] = time.time() - 7200  # 2 hours ago

        with patch("requests.get", side_effect=Exception("timeout")):
            result = fetch_fear_greed(_SENTIMENT_CONFIG)

        self.assertIsNotNone(result)
        self.assertEqual(result["value"], 21)
        self.assertIn("stale_age_hours", result)
        self.assertAlmostEqual(result["stale_age_hours"], 2.0, delta=0.1)

    def test_returns_none_when_cache_cold_and_fetch_fails(self):
        """On fetch failure with empty cache, None is returned."""
        with patch("requests.get", side_effect=Exception("timeout")):
            result = fetch_fear_greed(_SENTIMENT_CONFIG)
        self.assertIsNone(result)

    def test_returns_none_when_stale_exceeds_ttl(self):
        """Cached data older than stale_ttl_hours is not returned on failure."""
        # Seed cache with 5-hour-old data (TTL = 4h)
        _sentiment_cache["data"] = {"value": 50, "label": "Neutral", "timestamp": ""}
        _sentiment_cache["fetched_at"] = time.time() - 5 * 3600

        with patch("requests.get", side_effect=Exception("timeout")):
            result = fetch_fear_greed(_SENTIMENT_CONFIG)

        self.assertIsNone(result)

    def test_fresh_fetch_does_not_include_stale_key(self):
        """A successful fresh fetch does not add stale_age_hours."""
        mock_resp = unittest.mock.MagicMock()
        mock_resp.json.return_value = {
            "data": [{"value": "42", "value_classification": "Fear", "timestamp": ""}]
        }
        mock_resp.raise_for_status = lambda: None

        with patch("requests.get", return_value=mock_resp):
            result = fetch_fear_greed(_SENTIMENT_CONFIG)

        self.assertIsNotNone(result)
        self.assertNotIn("stale_age_hours", result)


class TestBtcDominanceStaleCarryForward(unittest.TestCase):

    def setUp(self):
        _reset_dom_cache()

    def test_returns_stale_data_on_fetch_failure_within_ttl(self):
        """On fetch failure, cached BTC dominance within 24h TTL is returned."""
        _btc_dom_cache["data"] = {
            "btc_dominance_pct": 52.5,
            "btc_dominance_trend": "flat",
            "trend_change_pp": 0.1,
        }
        _btc_dom_cache["fetched_at"] = time.time() - 6 * 3600  # 6 hours ago

        with patch("requests.get", side_effect=Exception("timeout")):
            result = fetch_btc_dominance(_DOM_CONFIG)

        self.assertIsNotNone(result)
        self.assertEqual(result["btc_dominance_pct"], 52.5)
        self.assertIn("stale_age_hours", result)
        self.assertAlmostEqual(result["stale_age_hours"], 6.0, delta=0.1)

    def test_returns_none_when_cache_cold_and_fetch_fails(self):
        """On fetch failure with empty BTC dom cache, None is returned."""
        with patch("requests.get", side_effect=Exception("timeout")):
            result = fetch_btc_dominance(_DOM_CONFIG)
        self.assertIsNone(result)

    def test_returns_none_when_stale_exceeds_ttl(self):
        """BTC dominance data older than 24h is not returned on failure."""
        _btc_dom_cache["data"] = {
            "btc_dominance_pct": 51.0,
            "btc_dominance_trend": "rising",
            "trend_change_pp": 0.8,
        }
        _btc_dom_cache["fetched_at"] = time.time() - 25 * 3600  # 25 hours ago

        with patch("requests.get", side_effect=Exception("timeout")):
            result = fetch_btc_dominance(_DOM_CONFIG)

        self.assertIsNone(result)


class TestBuildSentimentContext(unittest.TestCase):

    def setUp(self):
        _reset_sentiment_cache()

    def test_shows_neutral_unavailable_message_when_data_is_none(self):
        """When fetch fails and cache is cold, prompt shows 'treat as neutral' text."""
        with patch("requests.get", side_effect=Exception("timeout")):
            result = build_sentiment_context(_SENTIMENT_CONFIG)

        self.assertIn("unavailable", result.lower())
        self.assertIn("neutral", result.lower())
        # Message must say "not bearish" — not imply bearish sentiment
        self.assertIn("not bearish", result.lower())

    def test_shows_stale_label_when_data_is_stale(self):
        """Stale data includes '[stale Xh ago]' label in the context string."""
        _sentiment_cache["data"] = {"value": 21, "label": "Extreme Fear", "timestamp": ""}
        _sentiment_cache["fetched_at"] = time.time() - 2 * 3600  # 2 hours ago

        with patch("requests.get", side_effect=Exception("timeout")):
            result = build_sentiment_context(_SENTIMENT_CONFIG)

        self.assertIn("stale", result.lower())
        self.assertIn("21", result)
        self.assertIn("Extreme Fear", result)

    def test_no_stale_label_on_fresh_data(self):
        """Fresh data has no stale label in the context string."""
        mock_resp = unittest.mock.MagicMock()
        mock_resp.json.return_value = {
            "data": [{"value": "42", "value_classification": "Fear", "timestamp": ""}]
        }
        mock_resp.raise_for_status = lambda: None

        with patch("requests.get", return_value=mock_resp):
            result = build_sentiment_context(_SENTIMENT_CONFIG)

        self.assertNotIn("stale", result.lower())
        self.assertIn("42", result)


class TestBuildCyclePromptNullMacroRule(unittest.TestCase):

    def _minimal_portfolio(self):
        return {
            "total_usd": 1000.0,
            "available_cash_usd": 800.0,
            "open_positions_count": 0,
            "daily_pnl_usd": 0.0,
            "daily_pnl_pct": 0.0,
            "open_positions": [],
            "max_per_trade": 200.0,
        }

    def test_task_instructions_include_null_macro_guidance(self):
        """Rule 6 in task instructions tells LLM not to hold due to unavailable macro data."""
        prompt = build_cycle_prompt(
            cycle_time="12:00", portfolio=self._minimal_portfolio(), signals=[]
        )
        self.assertIn("unavailable", prompt.lower())
        self.assertIn("not a reason to hold", prompt.lower())


if __name__ == "__main__":
    unittest.main()
