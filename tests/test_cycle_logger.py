"""
tests/test_cycle_logger.py — Unit tests for src/utils/cycle_logger.py

Tests:
  1. Signal dict from _build_result() exposes score fields
  2. format_cycle_report() runs without error on a minimal input
  3. format_cycle_report() correctly labels a hard-vetoed HOLD pair
  4. format_cycle_report() correctly labels a low-score HOLD pair
  5. format_cycle_report() shows LLM result for a BUY pair
  6. format_cycle_report() shows LLM result for a SELL pair
  7. format_cycle_report() handles missing/optional indicator fields gracefully
  8. MACD bullish turn annotation appears when prev <= 0 < current
  9. MACD bearish turn annotation appears when prev >= 0 > current
 10. init_cycle_logger() is idempotent (no handler duplication)
"""

import json
import logging
import os
import sys
from datetime import datetime, timezone

import pytest

# Add project root to path so imports work when run from repo root
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from src.utils.cycle_logger import format_cycle_report, init_cycle_logger, _cycle_log
from src.analysis.signals import _build_result


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

def _make_signal(
    pair="ETH/USD",
    buy_score=7,
    sell_score=0,
    buy_min_score=5,
    sell_min_score=3,
    max_score=28,
    reasons=None,
    price=3000.0,
    extra_indicators=None,
):
    """Build a minimal signal dict as _build_result() would produce it."""
    base = _build_result(
        pair=pair,
        buy_score=buy_score,
        sell_score=sell_score,
        buy_min_score=buy_min_score,
        sell_min_score=sell_min_score,
        max_score=max_score,
        reasons=reasons or ["RSI oversold (28.4 < 30)", "MACD histogram turned positive"],
        price=price,
    )
    # attach a minimal indicators dict (as main.py does)
    base["indicators"] = {
        "rsi_14":               28.4,
        "macd_histogram":       0.000120,
        "macd_histogram_prev": -0.000080,
        "adx_14":               35.2,
        "ema_9":                2990.0,
        "ema_21":               2970.0,
        "ema_50":               2980.0,
        "close":                price,
        "bb_lower":             2800.0,
        "bb_upper":             3200.0,
        "atr_14":               45.2,
        "volume_ratio":         1.12,
        **(extra_indicators or {}),
    }
    return base


def _make_portfolio():
    return {
        "total_usd":            1234.56,
        "available_cash_usd":   456.78,
        "open_positions_count": 2,
        "daily_pnl_usd":        12.34,
        "daily_pnl_pct":        1.02,
    }


def _make_ai_context(regime="neutral"):
    return {
        "regime_data": {"regime": regime, "caution_factor": 1.0},
        "fear_greed":  {"value": 38, "label": "fear"},
        "btc_dominance": {"btc_dominance_pct": 52.3, "btc_dominance_trend": "rising"},
        "cycle_top_data": {"cycle_top_active": False, "mvrv_z_score": 1.2, "nupl": 0.45},
    }


# ─────────────────────────────────────────────────────────────────────────────
# Tests — score fields in signal dict
# ─────────────────────────────────────────────────────────────────────────────

class TestBuildResultScoreFields:
    """_build_result() must expose raw scores for cycle_logger consumption."""

    def test_buy_signal_exposes_scores(self):
        sig = _build_result("ETH/USD", 7, 0, 5, 3, 28, ["RSI oversold"], 3000.0)
        assert sig["signal"] == "BUY"
        assert sig["buy_score"] == 7
        assert sig["sell_score"] == 0
        assert sig["buy_min_score"] == 5
        assert sig["sell_min_score"] == 3
        assert sig["max_score"] == 28

    def test_sell_signal_exposes_scores(self):
        sig = _build_result("DOGE/USD", 1, 5, 5, 3, 28, ["RSI overbought"], 0.14)
        assert sig["signal"] == "SELL"
        assert sig["buy_score"] == 1
        assert sig["sell_score"] == 5
        assert sig["buy_min_score"] == 5
        assert sig["sell_min_score"] == 3
        assert sig["max_score"] == 28

    def test_hold_signal_exposes_scores(self):
        sig = _build_result("BTC/USD", 3, 0, 5, 3, 28, ["EMA9 > EMA21"], 65000.0)
        assert sig["signal"] == "HOLD"
        assert sig["buy_score"] == 3
        assert sig["max_score"] == 28

    def test_hold_boundary_below_min(self):
        """Score exactly one below min → HOLD, not BUY."""
        sig = _build_result("SOL/USD", 4, 0, 5, 3, 28, [], 140.0)
        assert sig["signal"] == "HOLD"
        assert sig["buy_score"] == 4
        assert sig["buy_min_score"] == 5


# ─────────────────────────────────────────────────────────────────────────────
# Tests — format_cycle_report()
# ─────────────────────────────────────────────────────────────────────────────

class TestFormatCycleReport:

    def test_returns_non_empty_string(self):
        sig = _make_signal()
        report = format_cycle_report(
            cycle_id=1,
            timestamp=datetime(2026, 4, 12, 14, 30, 0, tzinfo=timezone.utc),
            portfolio=_make_portfolio(),
            signals=[sig],
            ai_context=_make_ai_context(),
            results=[{"pair": "ETH/USD", "result": "BUY executed $180.00"}],
            duration_ms=4200,
        )
        assert isinstance(report, str)
        assert len(report) > 100
        data = json.loads(report)  # must be valid JSON
        assert data["cycle_id"] == 1

    def test_header_contains_cycle_id(self):
        sig = _make_signal()
        report = format_cycle_report(
            cycle_id=42,
            timestamp=datetime(2026, 4, 12, tzinfo=timezone.utc),
            portfolio=_make_portfolio(),
            signals=[sig],
            ai_context=_make_ai_context(),
            results=[],
        )
        data = json.loads(report)
        assert data["cycle_id"] == 42

    def test_buy_pair_shows_llm_result(self):
        sig = _make_signal(pair="ETH/USD", buy_score=7, sell_score=0)
        report = format_cycle_report(
            cycle_id=1,
            timestamp=datetime(2026, 4, 12, tzinfo=timezone.utc),
            portfolio=_make_portfolio(),
            signals=[sig],
            ai_context=_make_ai_context(),
            results=[{"pair": "ETH/USD", "result": "BUY executed $180.00"}],
        )
        data = json.loads(report)
        pair_entry = next(p for p in data["pairs"] if p["pair"] == "ETH/USD")
        assert pair_entry["llm_result"] == "BUY executed $180.00"
        assert pair_entry["verdict"] == "BUY candidate"

    def test_sell_pair_shows_llm_result(self):
        sig = _make_signal(
            pair="DOGE/USD",
            buy_score=0,
            sell_score=5,
            reasons=["RSI overbought (73.1 > 65)"],
            price=0.14,
        )
        report = format_cycle_report(
            cycle_id=1,
            timestamp=datetime(2026, 4, 12, tzinfo=timezone.utc),
            portfolio=_make_portfolio(),
            signals=[sig],
            ai_context=_make_ai_context(),
            results=[{"pair": "DOGE/USD", "result": "SELL executed — position closed"}],
        )
        data = json.loads(report)
        pair_entry = next(p for p in data["pairs"] if p["pair"] == "DOGE/USD")
        assert pair_entry["verdict"] == "SELL candidate"
        assert "SELL executed" in pair_entry["llm_result"]

    def test_hard_vetoed_hold_labelled_correctly(self):
        veto_reasons = ["BLOCKED: RSI 72.1 >= 70 — overbought, no entry"]
        sig = _make_signal(
            pair="SOL/USD",
            buy_score=2,
            sell_score=0,
            reasons=veto_reasons,
            price=140.52,
        )
        # Force signal to HOLD manually (veto fires before score check in signals.py)
        sig["signal"] = "HOLD"
        report = format_cycle_report(
            cycle_id=1,
            timestamp=datetime(2026, 4, 12, tzinfo=timezone.utc),
            portfolio=_make_portfolio(),
            signals=[sig],
            ai_context=_make_ai_context(),
            results=[],
        )
        data = json.loads(report)
        pair_entry = next(p for p in data["pairs"] if p["pair"] == "SOL/USD")
        assert pair_entry["is_vetoed"] is True
        assert pair_entry["verdict"] == "HOLD (hard veto)"
        assert pair_entry["sent_to_llm"] is False

    def test_low_score_hold_shows_gap(self):
        sig = _make_signal(
            pair="BTC/USD",
            buy_score=4,
            sell_score=0,
            buy_min_score=5,
            reasons=["ADX 45.0 > 40 — strong trend confirmed"],
            price=65000.0,
        )
        sig["signal"] = "HOLD"
        sig["strength"] = 0.0
        report = format_cycle_report(
            cycle_id=1,
            timestamp=datetime(2026, 4, 12, tzinfo=timezone.utc),
            portfolio=_make_portfolio(),
            signals=[sig],
            ai_context=_make_ai_context(),
            results=[],
        )
        data = json.loads(report)
        pair_entry = next(p for p in data["pairs"] if p["pair"] == "BTC/USD")
        assert pair_entry["buy_score"] == 4
        assert pair_entry["buy_min_score"] == 5
        assert "score 4 < min 5" in pair_entry["verdict"]
        assert "gap 1" in pair_entry["verdict"]

    def test_macd_bullish_turn_annotation(self):
        sig = _make_signal(
            extra_indicators={
                "macd_histogram":       0.000120,
                "macd_histogram_prev": -0.000080,
            }
        )
        report = format_cycle_report(
            cycle_id=1,
            timestamp=datetime(2026, 4, 12, tzinfo=timezone.utc),
            portfolio=_make_portfolio(),
            signals=[sig],
            ai_context=_make_ai_context(),
            results=[],
        )
        data = json.loads(report)
        pair_entry = data["pairs"][0]
        assert pair_entry["indicators"]["macd_turn"] == "bullish"

    def test_macd_bearish_turn_annotation(self):
        sig = _make_signal(
            buy_score=0,
            sell_score=4,
            reasons=["MACD histogram turned negative"],
            extra_indicators={
                "macd_histogram":       -0.000080,
                "macd_histogram_prev":   0.000120,
            }
        )
        sig["signal"] = "SELL"
        report = format_cycle_report(
            cycle_id=1,
            timestamp=datetime(2026, 4, 12, tzinfo=timezone.utc),
            portfolio=_make_portfolio(),
            signals=[sig],
            ai_context=_make_ai_context(),
            results=[],
        )
        data = json.loads(report)
        pair_entry = data["pairs"][0]
        assert pair_entry["indicators"]["macd_turn"] == "bearish"

    def test_missing_indicators_graceful(self):
        """Report must not crash when indicators dict is empty."""
        sig = _make_signal()
        sig["indicators"] = {}  # wipe all indicators
        report = format_cycle_report(
            cycle_id=1,
            timestamp=datetime(2026, 4, 12, tzinfo=timezone.utc),
            portfolio=_make_portfolio(),
            signals=[sig],
            ai_context=_make_ai_context(),
            results=[],
        )
        data = json.loads(report)  # must not crash, must be valid JSON
        assert data["cycle_id"] == 1

    def test_summary_counts_correct(self):
        buy_sig  = _make_signal(pair="ETH/USD", buy_score=7, sell_score=0)
        hold_sig = _make_signal(pair="BTC/USD", buy_score=3, sell_score=0, price=65000.0)
        hold_sig["signal"] = "HOLD"
        hold_sig["strength"] = 0.0
        sell_sig = _make_signal(
            pair="DOGE/USD", buy_score=0, sell_score=5,
            reasons=["RSI overbought"], price=0.14,
        )
        sell_sig["signal"] = "SELL"
        report = format_cycle_report(
            cycle_id=1,
            timestamp=datetime(2026, 4, 12, tzinfo=timezone.utc),
            portfolio=_make_portfolio(),
            signals=[buy_sig, hold_sig, sell_sig],
            ai_context=_make_ai_context(),
            results=[
                {"pair": "ETH/USD",  "result": "BUY executed $180.00"},
                {"pair": "DOGE/USD", "result": "SELL executed"},
            ],
        )
        data = json.loads(report)
        summary = data["summary"]
        assert summary["n_buy"] == 1
        assert summary["n_sell"] == 1
        assert summary["n_hold"] == 1
        assert summary["n_sent_to_llm"] == 2


# ─────────────────────────────────────────────────────────────────────────────
# Tests — init_cycle_logger()
# ─────────────────────────────────────────────────────────────────────────────

class TestInitCycleLogger:

    def test_idempotent_no_duplicate_handlers(self, tmp_path):
        config = {}
        init_cycle_logger(log_dir=str(tmp_path), config=config)
        init_cycle_logger(log_dir=str(tmp_path), config=config)  # second call
        assert len(_cycle_log.handlers) == 1

    def test_creates_log_file(self, tmp_path):
        config = {}
        init_cycle_logger(log_dir=str(tmp_path), config=config)
        log_path = tmp_path / "cycle_decisions.log"
        # Write a line to trigger file creation
        _cycle_log.info("test line")
        assert log_path.exists()
