"""
Tests for #237 — CoinGlass v4 API: correct domain, endpoint paths, and response parsing.

Tests cover:
  1. Config URLs point to open-api-v4.coinglass.com
  2. _extract_mvrv_from_bull_market_indicators() parses the v4 list correctly
  3. fetch_cycle_top_indicators() sends requests to the v4 URLs from config
  4. NUPL is parsed from 'net_unpnl' field (v4 response schema)
  5. Missing MVRV entry in bull-market list returns None gracefully
  6. Connectivity smoke test: v4 endpoints return non-connection-error HTTP status
"""
import sys
import os
import types
import unittest
from unittest.mock import patch, MagicMock

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
sys.modules["src.utils.tz"] = tz_mod
# ─────────────────────────────────────────────────────────────────────────────

from src.analysis.features import (
    _extract_mvrv_from_bull_market_indicators,
    _extract_latest_indicator_value,
    fetch_cycle_top_indicators,
    _cycle_top_cache,
)

# ── sample v4 API responses ───────────────────────────────────────────────────

_MVRV_RESPONSE = {
    "code": "0",
    "msg": "success",
    "data": [
        {
            "indicator_name": "Bitcoin Ahr999 Index",
            "current_value": "0.78",
            "target_value": "4",
            "hit_status": False,
        },
        {
            "indicator_name": "Pi Cycle Top Indicator",
            "current_value": "85073.0",
            "target_value": "154582",
            "hit_status": False,
        },
        {
            "indicator_name": "Bitcoin MVRV Z-Score",
            "current_value": "2.45",
            "target_value": "7",
            "hit_status": False,
        },
        {
            "indicator_name": "200-Week Moving Average Heatmap",
            "current_value": "3.1",
            "target_value": "5",
            "hit_status": False,
        },
    ],
}

_NUPL_RESPONSE = {
    "code": "0",
    "data": [
        {"price": 30000, "net_unpnl": 0.35, "timestamp": 1690000000000},
        {"price": 82000, "net_unpnl": 0.58, "timestamp": 1744000000000},
    ],
}

_BASE_CONFIG = {
    "risk": {
        "cycle_top_guard": {
            "enabled": True,
            "mvrv_z_danger": 7.0,
            "nupl_danger": 0.70,
            "mvrv_url": "https://open-api-v4.coinglass.com/api/bull-market-peak-indicator",
            "nupl_url": "https://open-api-v4.coinglass.com/api/index/bitcoin-net-unrealized-profit-loss",
            "fetch_timeout_secs": 8,
            "cache_hours": 24,
        }
    }
}


class TestConfigUrls(unittest.TestCase):
    """Verify that config.yaml URLs are updated to the v4 domain."""

    def _load_config(self):
        import yaml
        config_path = os.path.join(os.path.dirname(__file__), "..", "config.yaml")
        with open(config_path) as f:
            return yaml.safe_load(f)

    def test_mvrv_url_uses_v4_domain(self):
        cfg = self._load_config()
        mvrv_url = cfg["risk"]["cycle_top_guard"]["mvrv_url"]
        self.assertIn("open-api-v4.coinglass.com", mvrv_url,
                      f"mvrv_url should use v4 domain, got: {mvrv_url}")
        self.assertNotIn("open-api.coinglass.com", mvrv_url)

    def test_nupl_url_uses_v4_domain(self):
        cfg = self._load_config()
        nupl_url = cfg["risk"]["cycle_top_guard"]["nupl_url"]
        self.assertIn("open-api-v4.coinglass.com", nupl_url,
                      f"nupl_url should use v4 domain, got: {nupl_url}")
        self.assertNotIn("open-api.coinglass.com", nupl_url)

    def test_mvrv_url_path(self):
        cfg = self._load_config()
        mvrv_url = cfg["risk"]["cycle_top_guard"]["mvrv_url"]
        self.assertIn("/api/bull-market-peak-indicator", mvrv_url)

    def test_nupl_url_path(self):
        cfg = self._load_config()
        nupl_url = cfg["risk"]["cycle_top_guard"]["nupl_url"]
        self.assertIn("/api/index/bitcoin-net-unrealized-profit-loss", nupl_url)


class TestExtractMvrvFromBullMarketIndicators(unittest.TestCase):
    """Unit tests for the new MVRV extractor."""

    def test_extracts_mvrv_from_list(self):
        result = _extract_mvrv_from_bull_market_indicators(_MVRV_RESPONSE)
        self.assertAlmostEqual(result, 2.45)

    def test_returns_none_when_mvrv_not_in_list(self):
        payload = {
            "code": "0",
            "data": [
                {"indicator_name": "Bitcoin Ahr999 Index", "current_value": "0.78"},
                {"indicator_name": "Pi Cycle Top Indicator", "current_value": "85073.0"},
            ],
        }
        result = _extract_mvrv_from_bull_market_indicators(payload)
        self.assertIsNone(result)

    def test_returns_none_on_empty_data(self):
        result = _extract_mvrv_from_bull_market_indicators({"code": "0", "data": []})
        self.assertIsNone(result)

    def test_returns_none_on_missing_data_key(self):
        result = _extract_mvrv_from_bull_market_indicators({"code": "401", "msg": "API key missing."})
        self.assertIsNone(result)

    def test_case_insensitive_mvrv_match(self):
        payload = {
            "code": "0",
            "data": [
                {"indicator_name": "Bitcoin mvrv z-score", "current_value": "3.1"},
            ],
        }
        result = _extract_mvrv_from_bull_market_indicators(payload)
        self.assertAlmostEqual(result, 3.1)


class TestNuplV4Parsing(unittest.TestCase):
    """NUPL is now parsed from 'net_unpnl' field in the v4 time-series response."""

    def test_extracts_net_unpnl_from_latest_entry(self):
        # The function should pick the last entry's net_unpnl value
        result = _extract_latest_indicator_value(_NUPL_RESPONSE, ["net_unpnl", "nupl", "value"])
        self.assertAlmostEqual(result, 0.58)

    def test_handles_single_entry(self):
        payload = {
            "code": "0",
            "data": [{"price": 50000, "net_unpnl": 0.42, "timestamp": 1700000000000}],
        }
        result = _extract_latest_indicator_value(payload, ["net_unpnl", "nupl", "value"])
        self.assertAlmostEqual(result, 0.42)


class TestFetchCycleTopIndicators(unittest.TestCase):
    """fetch_cycle_top_indicators() uses the v4 URLs and parses both values."""

    def setUp(self):
        # Clear the in-memory cache before each test
        _cycle_top_cache["data"] = None
        _cycle_top_cache["fetched_at"] = 0
        _cycle_top_cache["failed_at"] = None

    def _make_response(self, json_data, status=200):
        mock_resp = MagicMock()
        mock_resp.status_code = status
        mock_resp.json.return_value = json_data
        mock_resp.raise_for_status = MagicMock()
        return mock_resp

    @patch("src.analysis.features.requests.get")
    @patch.dict(os.environ, {"COINGLASS_API_KEY": "test-api-key-123"})
    def test_requests_use_v4_urls(self, mock_get):
        mock_get.side_effect = [
            self._make_response(_MVRV_RESPONSE),
            self._make_response(_NUPL_RESPONSE),
        ]
        fetch_cycle_top_indicators(_BASE_CONFIG)

        calls = mock_get.call_args_list
        self.assertEqual(len(calls), 2)
        mvrv_url = calls[0][0][0]
        nupl_url = calls[1][0][0]
        self.assertIn("open-api-v4.coinglass.com", mvrv_url)
        self.assertIn("open-api-v4.coinglass.com", nupl_url)
        self.assertIn("bull-market-peak-indicator", mvrv_url)
        self.assertIn("bitcoin-net-unrealized-profit-loss", nupl_url)

    @patch("src.analysis.features.requests.get")
    @patch.dict(os.environ, {"COINGLASS_API_KEY": "test-api-key-123"})
    def test_returns_correct_mvrv_and_nupl(self, mock_get):
        mock_get.side_effect = [
            self._make_response(_MVRV_RESPONSE),
            self._make_response(_NUPL_RESPONSE),
        ]
        result = fetch_cycle_top_indicators(_BASE_CONFIG)

        self.assertIsNotNone(result)
        self.assertAlmostEqual(result["mvrv_z_score"], 2.45)
        self.assertAlmostEqual(result["nupl"], 0.58)
        self.assertFalse(result["cycle_top_active"])  # 2.45 < 7.0 and 0.58 < 0.70

    @patch("src.analysis.features.requests.get")
    @patch.dict(os.environ, {"COINGLASS_API_KEY": "test-api-key-123"})
    def test_cycle_top_active_when_both_thresholds_breached(self, mock_get):
        danger_mvrv = {
            "code": "0",
            "data": [
                {"indicator_name": "Bitcoin MVRV Z-Score", "current_value": "7.5", "hit_status": True},
            ],
        }
        danger_nupl = {
            "code": "0",
            "data": [{"price": 200000, "net_unpnl": 0.75, "timestamp": 1750000000000}],
        }
        mock_get.side_effect = [
            self._make_response(danger_mvrv),
            self._make_response(danger_nupl),
        ]
        result = fetch_cycle_top_indicators(_BASE_CONFIG)

        self.assertIsNotNone(result)
        self.assertTrue(result["cycle_top_active"])

    @patch("src.analysis.features.requests.get")
    @patch.dict(os.environ, {"COINGLASS_API_KEY": "test-api-key-123"})
    def test_returns_none_when_mvrv_not_parseable(self, mock_get):
        mock_get.side_effect = [
            self._make_response({"code": "0", "data": []}),  # empty — no MVRV entry
            self._make_response(_NUPL_RESPONSE),
        ]
        result = fetch_cycle_top_indicators(_BASE_CONFIG)
        self.assertIsNone(result)

    def test_returns_none_when_api_key_missing(self):
        env_without_key = {k: v for k, v in os.environ.items() if k != "COINGLASS_API_KEY"}
        with patch.dict(os.environ, env_without_key, clear=True):
            result = fetch_cycle_top_indicators(_BASE_CONFIG)
        self.assertIsNone(result)


class TestV4Connectivity(unittest.TestCase):
    """
    Smoke tests: confirm v4 endpoints are reachable (no DNS/connectivity errors).
    These tests require network access and pass even without an API key — the
    expected non-error response is {"code":"401","msg":"API key missing."}.
    Skip by setting env var SKIP_NETWORK_TESTS=1.
    """

    @unittest.skipIf(os.getenv("SKIP_NETWORK_TESTS"), "network tests disabled")
    def test_mvrv_endpoint_reachable(self):
        import requests
        url = "https://open-api-v4.coinglass.com/api/bull-market-peak-indicator"
        try:
            r = requests.get(url, headers={"Accept": "application/json"}, timeout=10)
            # 200 with code="401" (API key missing) or 200 with real data — both mean reachable
            self.assertEqual(r.status_code, 200,
                             f"Expected 200 from v4 MVRV endpoint, got {r.status_code}")
        except Exception as e:
            self.fail(f"Could not connect to v4 MVRV endpoint: {e}")

    @unittest.skipIf(os.getenv("SKIP_NETWORK_TESTS"), "network tests disabled")
    def test_nupl_endpoint_reachable(self):
        import requests
        url = "https://open-api-v4.coinglass.com/api/index/bitcoin-net-unrealized-profit-loss"
        try:
            r = requests.get(url, headers={"Accept": "application/json"}, timeout=10)
            self.assertEqual(r.status_code, 200,
                             f"Expected 200 from v4 NUPL endpoint, got {r.status_code}")
        except Exception as e:
            self.fail(f"Could not connect to v4 NUPL endpoint: {e}")


if __name__ == "__main__":
    unittest.main()
