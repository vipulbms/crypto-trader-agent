"""
Tests for S13.2.3 — BTC/USD spot-price failover via CoinGecko.

Story: S13.2.3 | Sprint: S3 | Epic: E13 — QSA Data Resilience

Covers:
  AC1: fetch_btc_spot_price() returns None when failover.enabled=False
  AC2: Returns float on successful CoinGecko fetch
  AC3: Cache hit returns cached value without new HTTP call
  AC4: Stale cached value returned on network error
  AC5: Cache TTL honoured (no re-fetch until expired)
"""

import time
from unittest.mock import MagicMock, patch

from src.analysis import features as feat_module
from src.analysis.features import fetch_btc_spot_price


def _enabled_config(cache_seconds: int = 60) -> dict:
    return {
        "qsa": {
            "failover": {
                "enabled": True,
                "cache_seconds": cache_seconds,
            }
        },
        "regime": {
            "fetch_timeout_secs": 8,
        },
    }


def _disabled_config() -> dict:
    return {
        "qsa": {
            "failover": {
                "enabled": False,
            }
        },
        "regime": {
            "fetch_timeout_secs": 8,
        },
    }


class TestBtcSpotFailover:

    def setup_method(self):
        """Reset module-level cache before each test."""
        feat_module._btc_spot_cache["price"] = None
        feat_module._btc_spot_cache["fetched_at"] = 0

    def test_returns_none_when_disabled(self):
        """AC1: failover.enabled=False → function returns None immediately."""
        result = fetch_btc_spot_price(_disabled_config())
        assert result is None

    def test_returns_price_on_success(self):
        """AC2: successful CoinGecko fetch → returns float price."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"bitcoin": {"usd": 95000.0}}
        mock_response.raise_for_status = MagicMock()

        with patch("requests.get", return_value=mock_response):
            result = fetch_btc_spot_price(_enabled_config())

        assert isinstance(result, float)
        assert result == 95000.0

    def test_cache_hit_skips_http(self):
        """AC3: second call within TTL returns cached value without new request."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"bitcoin": {"usd": 95000.0}}
        mock_response.raise_for_status = MagicMock()

        with patch("requests.get", return_value=mock_response) as mock_get:
            _ = fetch_btc_spot_price(_enabled_config(cache_seconds=300))
            result2 = fetch_btc_spot_price(_enabled_config(cache_seconds=300))

        assert mock_get.call_count == 1, "HTTP called more than once; cache not working"
        assert result2 == 95000.0

    def test_stale_cache_returned_on_network_error(self):
        """AC4: when HTTP fails, returns last cached price (stale carry-forward)."""
        # Pre-seed cache
        feat_module._btc_spot_cache["price"] = 88000.0
        feat_module._btc_spot_cache["fetched_at"] = 0  # expired

        with patch("requests.get", side_effect=Exception("CoinGecko down")):
            result = fetch_btc_spot_price(_enabled_config(cache_seconds=60))

        assert result == 88000.0, "Should return stale cached price on error"

    def test_returns_none_no_cache_on_error(self):
        """AC4 variant: no cache available + network error → returns None."""
        feat_module._btc_spot_cache["price"] = None
        feat_module._btc_spot_cache["fetched_at"] = 0

        with patch("requests.get", side_effect=Exception("CoinGecko down")):
            result = fetch_btc_spot_price(_enabled_config(cache_seconds=60))

        assert result is None

    def test_cache_expires_after_ttl(self):
        """AC5: after TTL expires, a new HTTP call is made."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"bitcoin": {"usd": 97000.0}}
        mock_response.raise_for_status = MagicMock()

        # Seed a stale cache entry (fetched 120 seconds ago; TTL = 60 s)
        feat_module._btc_spot_cache["price"] = 80000.0
        feat_module._btc_spot_cache["fetched_at"] = time.time() - 120

        with patch("requests.get", return_value=mock_response) as mock_get:
            result = fetch_btc_spot_price(_enabled_config(cache_seconds=60))

        assert mock_get.call_count == 1, "Should re-fetch after TTL expiry"
        assert result == 97000.0
