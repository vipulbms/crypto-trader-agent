"""
Tests for #206 — BTC dominance trend as macro altcoin regime input.

Tests cover:
  1. fetch_btc_dominance() returns correct structure and caches correctly
  2. Trend calculation: rising / falling / flat
  3. detect_market_regime() includes btc_dominance_trend in return dict
  4. Regime summary appended when dominance is rising/falling
  5. build_ai_context() propagates btc_dominance_trend / btc_dominance_pct
"""
import sys, os, tempfile, sqlite3, time, types, unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# ── stub heavy deps ──────────────────────────────────────────────────────────
timing_mod = types.ModuleType("src.utils.timing")
timing_mod.timed = lambda *a, **kw: (lambda f: f)
sys.modules["src.utils.timing"] = timing_mod

tz_mod = types.ModuleType("src.utils.tz")
from datetime import datetime, timezone as _tz
tz_mod.SGT = _tz.utc
tz_mod.now_sgt = lambda: datetime.now(_tz.utc)
tz_mod.now_sgt_iso = lambda: datetime.now(_tz.utc).isoformat()
sys.modules["src.utils.tz"] = tz_mod
# ─────────────────────────────────────────────────────────────────────────────

from src.analysis.features import (
    fetch_btc_dominance,
    detect_market_regime,
    build_ai_context,
    _btc_dom_cache,
)

# ─── helpers ─────────────────────────────────────────────────────────────────

_BASE_CONFIG = {
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
            "cache_minutes": 60,
            "trend_min_change_pp": 0.5,
            "trend_lookback_days": 3,
        },
    },
}

def _coingecko_mock(btc_pct: float):
    """Returns a mock requests.Response-like object for /api/v3/global."""
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {
        "data": {"market_cap_percentage": {"btc": btc_pct, "eth": 15.0}}
    }
    return mock_resp


def _make_db_with_past_entry(past_dom_pct: float, days_ago: int = 3) -> str:
    """Create a temp DB with a historical BTC dominance entry."""
    from datetime import timedelta
    f = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    path = f.name
    f.close()
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE agent_state (key TEXT PRIMARY KEY, value TEXT)")
    past_date = (datetime.now(_tz.utc) - timedelta(days=days_ago)).strftime("%Y-%m-%d")
    conn.execute("INSERT INTO agent_state VALUES (?, ?)", (f"btc_dom_{past_date}", str(past_dom_pct)))
    conn.commit()
    conn.close()
    return path


# ─── Test class ──────────────────────────────────────────────────────────────

class TestFetchBtcDominance:

    def setup_method(self):
        """Clear in-process cache before each test."""
        _btc_dom_cache["data"] = None
        _btc_dom_cache["fetched_at"] = 0

    def test_returns_correct_structure(self):
        """fetch_btc_dominance() returns dict with required keys."""
        with patch("requests.get", return_value=_coingecko_mock(52.5)):
            result = fetch_btc_dominance(_BASE_CONFIG)
        assert result is not None
        assert "btc_dominance_pct" in result
        assert "btc_dominance_trend" in result
        assert "trend_change_pp" in result
        assert result["btc_dominance_pct"] == 52.5

    def test_trend_flat_without_history(self):
        """Without historical DB entry, trend defaults to 'flat' (no prior)."""
        with patch("requests.get", return_value=_coingecko_mock(52.0)):
            result = fetch_btc_dominance(_BASE_CONFIG, db_path=None)
        assert result["btc_dominance_trend"] == "flat"
        assert result["trend_change_pp"] == 0.0

    def test_trend_rising_when_dominance_increased(self):
        """Rising trend when dominance increased > trend_min_change_pp."""
        db = _make_db_with_past_entry(past_dom_pct=50.0, days_ago=3)
        with patch("requests.get", return_value=_coingecko_mock(51.0)):  # +1.0pp
            result = fetch_btc_dominance(_BASE_CONFIG, db_path=db)
        assert result["btc_dominance_trend"] == "rising"
        assert result["trend_change_pp"] == pytest.approx(1.0, abs=0.01)

    def test_trend_falling_when_dominance_decreased(self):
        """Falling trend when dominance decreased > trend_min_change_pp."""
        db = _make_db_with_past_entry(past_dom_pct=55.0, days_ago=3)
        with patch("requests.get", return_value=_coingecko_mock(54.0)):  # -1.0pp
            result = fetch_btc_dominance(_BASE_CONFIG, db_path=db)
        assert result["btc_dominance_trend"] == "falling"
        assert result["trend_change_pp"] == pytest.approx(-1.0, abs=0.01)

    def test_trend_flat_within_threshold(self):
        """Flat trend when change <= trend_min_change_pp (0.5)."""
        db = _make_db_with_past_entry(past_dom_pct=52.0, days_ago=3)
        with patch("requests.get", return_value=_coingecko_mock(52.3)):  # +0.3pp < 0.5
            result = fetch_btc_dominance(_BASE_CONFIG, db_path=db)
        assert result["btc_dominance_trend"] == "flat"

    def test_memcache_prevents_refetch(self):
        """Second call within cache window reuses in-memory data."""
        with patch("requests.get", return_value=_coingecko_mock(53.0)) as mock_get:
            fetch_btc_dominance(_BASE_CONFIG)
            fetch_btc_dominance(_BASE_CONFIG)
        assert mock_get.call_count == 1  # only one HTTP call

    def test_returns_none_when_disabled(self):
        """Returns None when btc_dominance.enabled is False."""
        cfg = {
            "regime": {"btc_dominance": {"enabled": False}}
        }
        result = fetch_btc_dominance(cfg)
        assert result is None

    def test_returns_none_on_network_error(self):
        """Returns None (and does not raise) when CoinGecko is unreachable."""
        with patch("requests.get", side_effect=Exception("network error")):
            result = fetch_btc_dominance(_BASE_CONFIG)
        assert result is None


class TestDetectMarketRegimeBtcDominance:

    def _base_signals(self, n=8, make_bearish=False):
        """Generate minimal signal list for regime tests."""
        hist = -0.01 if make_bearish else 0.01
        return [
            {
                "pair": f"PAIR{i}/USD",
                "indicators": {
                    "macd_histogram": hist,
                    "atr_14": 10.0,
                    "close": 1000.0,
                },
            }
            for i in range(n)
        ]

    def test_regime_includes_btc_dominance_trend_key(self):
        """detect_market_regime() returns btc_dominance_trend in its dict."""
        dom = {"btc_dominance_pct": 52.0, "btc_dominance_trend": "rising", "trend_change_pp": 1.0}
        result = detect_market_regime(self._base_signals(), _BASE_CONFIG, btc_dominance=dom)
        assert "btc_dominance_trend" in result
        assert result["btc_dominance_trend"] == "rising"

    def test_regime_includes_btc_dominance_pct_key(self):
        """detect_market_regime() returns btc_dominance_pct in its dict."""
        dom = {"btc_dominance_pct": 54.75, "btc_dominance_trend": "flat", "trend_change_pp": 0.1}
        result = detect_market_regime(self._base_signals(), _BASE_CONFIG, btc_dominance=dom)
        assert result["btc_dominance_pct"] == 54.75

    def test_summary_appended_when_rising(self):
        """'RISING' note appended to regime summary when dominance is rising."""
        dom = {"btc_dominance_pct": 52.0, "btc_dominance_trend": "rising", "trend_change_pp": 1.2}
        sigs = self._base_signals(n=8, make_bearish=True)   # force bearish
        result = detect_market_regime(sigs, _BASE_CONFIG, btc_dominance=dom)
        assert "RISING" in result["summary"]
        assert "altcoin" in result["summary"].lower()

    def test_summary_appended_when_falling(self):
        """'FALLING' note appended to regime summary when dominance is falling."""
        dom = {"btc_dominance_pct": 49.0, "btc_dominance_trend": "falling", "trend_change_pp": -1.5}
        result = detect_market_regime(self._base_signals(), _BASE_CONFIG, btc_dominance=dom)
        assert "FALLING" in result["summary"]

    def test_no_btc_dominance_defaults_to_unknown(self):
        """When btc_dominance is None, btc_dominance_trend = 'unknown'."""
        result = detect_market_regime(self._base_signals(), _BASE_CONFIG, btc_dominance=None)
        assert result["btc_dominance_trend"] == "unknown"


class TestBuildAiContextBtcDominance:

    def test_btc_dominance_trend_propagated(self):
        """build_ai_context() includes btc_dominance_trend from regime."""
        dom = {"btc_dominance_pct": 52.5, "btc_dominance_trend": "rising", "trend_change_pp": 0.8}
        signals = [
            {
                "pair": "BTC/USD",
                "signal": "BUY", "strength": 0.7,
                "indicators": {"macd_histogram": 0.01, "atr_14": 100.0, "close": 50000.0,
                               "rsi_14": 45.0, "bb_upper": 52000, "bb_lower": 48000,
                               "bb_mid": 50000, "macd_histogram_prev": -0.01},
                "reasons": [],
            }
        ]
        portfolio = {"total_usd": 1000, "available_cash_usd": 800, "max_per_trade": 200}
        open_positions = []
        ctx = build_ai_context(signals, portfolio, open_positions, _BASE_CONFIG, btc_dominance=dom)
        assert ctx["btc_dominance_trend"] == "rising"
        assert ctx["btc_dominance_pct"] == 52.5

    def test_btc_dominance_defaults_when_not_provided(self):
        """build_ai_context() defaults btc_dominance_trend to 'unknown' when not passed."""
        signals = [
            {
                "pair": "ETH/USD",
                "signal": "HOLD", "strength": 0.3,
                "indicators": {"macd_histogram": 0.02, "atr_14": 50.0, "close": 3000.0,
                               "rsi_14": 50.0, "bb_upper": 3100, "bb_lower": 2900,
                               "bb_mid": 3000, "macd_histogram_prev": 0.01},
                "reasons": [],
            }
        ]
        portfolio = {"total_usd": 1000, "available_cash_usd": 900, "max_per_trade": 200}
        ctx = build_ai_context(signals, portfolio, [], _BASE_CONFIG)
        assert ctx["btc_dominance_trend"] == "unknown"


import pytest
