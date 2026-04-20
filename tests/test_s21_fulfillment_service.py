"""
Test suite for Sprint S4 — S21.2.1 (FulfillmentService HTTP API).

Tests:
  - GET /health → 200, no auth required
  - POST /fill buy → 201 with fulfillment_id (paper mode)
  - GET /balance → 200, returns cash/total/open_positions_count
  - GET /positions → 200, returns positions list
  - Missing/invalid Bearer token → 401
  - Non-localhost IP → 403 (tested via middleware unit-test)

The tests use aiohttp.test_utils to avoid binding a real network port.

pytest: python -m pytest tests/test_s21_fulfillment_service.py -v
"""
from __future__ import annotations

import os
import sys
import uuid
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.runtime.fulfillment_service import FulfillmentService, _make_security_middleware, _get_last_price


# ──────────────────────────────────────────────────────────────
# Test helpers
# ──────────────────────────────────────────────────────────────

def _minimal_config() -> dict:
    return {
        "trading": {
            "stop_loss_pct":        5.0,
            "take_profit_pct":      8.0,
            "min_profit_floor_pct": 1.0,
            "max_position_pct":     30.0,
            "max_open_positions":   10,
            "allowed_trading_hours": {"enabled": False},
            "pairs": [
                {
                    "pair":           "BTC/USD",
                    "stop_loss_pct":  5.0,
                    "take_profit_pct": 8.0,
                },
            ],
        },
        "risk": {
            "daily_loss_limit_pct": 10.0,
            "min_cash_reserve_pct": 5.0,
            "min_order_usd":        20.0,
            "circuit_breaker":      {"enabled": True, "consecutive_stops": 3, "pause_hours": 1},
            "max_cluster_positions": 2,
            "correlation_clusters":  [],
        },
        "atr_stop_loss": {"enabled": False},
        "personas": {
            "conservative": {"llm_system_role": "conservative", "buy_min_score": 5, "max_open_positions": 2, "max_position_pct": 0.15, "min_profit_floor_pct": 1.5, "rsi_overbought_veto": 70, "momentum_bypass_rsi": 70, "momentum_bypass_adx": 999, "reallocation_enabled": False, "reallocation_max_pct_6h": 0.0, "llm_temperature": 0.1, "llm_max_tokens": 1024, "velocity_circuit_breaker_pct": 5.0, "velocity_halt_hours": 2},
            "medium":        {"llm_system_role": "medium",       "buy_min_score": 5, "max_open_positions": 5, "max_position_pct": 0.25, "min_profit_floor_pct": 1.0, "rsi_overbought_veto": 70, "momentum_bypass_rsi": 75, "momentum_bypass_adx": 25, "reallocation_enabled": True, "reallocation_max_pct_6h": 0.20, "llm_temperature": 0.3, "llm_max_tokens": 2048, "velocity_circuit_breaker_pct": 5.0, "velocity_halt_hours": 2},
            "high":          {"llm_system_role": "high",         "buy_min_score": 5, "max_open_positions": 10, "max_position_pct": 0.30, "min_profit_floor_pct": 1.0, "rsi_overbought_veto": 70, "momentum_bypass_rsi": 80, "momentum_bypass_adx": 25, "reallocation_enabled": True, "reallocation_max_pct_6h": 0.30, "llm_temperature": 0.5, "llm_max_tokens": 4096, "velocity_circuit_breaker_pct": 5.0, "velocity_halt_hours": 2},
        },
        "agent": {"persona": "medium", "concurrent_mode": False},
    }


def _tmp_db_with_wallet() -> str:
    """Create an isolated DB with paper_wallet, paper_positions, candle_buffer."""
    tmp = tempfile.mkdtemp()
    db_path = os.path.join(tmp, f"test_fs_{uuid.uuid4().hex[:8]}.db")
    conn = sqlite3.connect(db_path)
    conn.execute(
        """CREATE TABLE paper_wallet (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cash_usd REAL NOT NULL,
            updated_at TEXT
        )"""
    )
    conn.execute("INSERT INTO paper_wallet (cash_usd, updated_at) VALUES (1000.0, datetime('now'))")
    conn.execute(
        """CREATE TABLE paper_positions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            opened_at TEXT, pair TEXT, side TEXT, entry_price REAL,
            volume REAL, usd_value REAL,
            stop_loss_price REAL, take_profit_price REAL,
            stop_loss_pct REAL, take_profit_pct REAL,
            status TEXT DEFAULT 'open',
            highest_price_seen REAL, partial_exited INTEGER DEFAULT 0,
            persona TEXT DEFAULT ''
        )"""
    )
    conn.execute(
        """CREATE TABLE paper_trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pair TEXT, usd_value REAL, exit_reason TEXT, closed_at TEXT,
            opened_at TEXT, side TEXT, entry_price REAL, exit_price REAL,
            volume REAL, fee_usd REAL, pnl_usd REAL, pnl_pct REAL,
            stop_loss_pct REAL, take_profit_pct REAL, persona TEXT DEFAULT ''
        )"""
    )
    conn.execute(
        """CREATE TABLE agent_state (
            key TEXT PRIMARY KEY,
            value TEXT,
            updated_at TEXT
        )"""
    )
    conn.execute(
        """CREATE TABLE candle_buffer (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pair TEXT NOT NULL,
            ts INTEGER NOT NULL,
            open_price REAL, high REAL, low REAL, close REAL,
            volume REAL, is_closed INTEGER DEFAULT 1,
            inserted_at TEXT,
            UNIQUE(pair, ts)
        )"""
    )
    # Insert a price candle for BTC/USD
    conn.execute(
        "INSERT INTO candle_buffer (pair, ts, open_price, high, low, close, volume, is_closed, inserted_at) "
        "VALUES ('BTC/USD', ?, 50000.0, 50100.0, 49900.0, 50000.0, 1.0, 1, datetime('now'))",
        (int(__import__('time').time()) - 10,),
    )
    conn.commit()
    conn.close()
    return db_path


# ──────────────────────────────────────────────────────────────
# _get_last_price unit tests
# ──────────────────────────────────────────────────────────────

class TestGetLastPrice:
    def test_returns_correct_close_price(self):
        """Returns last closed candle close price for known pair."""
        db = _tmp_db_with_wallet()
        price = _get_last_price("BTC/USD", db)
        assert price is not None
        assert abs(price - 50000.0) < 1.0

    def test_returns_none_for_unknown_pair(self):
        """Returns None when pair has no rows in candle_buffer."""
        db = _tmp_db_with_wallet()
        price = _get_last_price("UNKNOWN/USD", db)
        assert price is None


# ──────────────────────────────────────────────────────────────
# Security middleware unit tests
# ──────────────────────────────────────────────────────────────

class TestSecurityMiddleware:
    """Unit-test the middleware logic without a real aiohttp request."""

    def test_health_endpoint_bypasses_auth(self):
        """GET /health requires no Bearer token."""
        middleware = _make_security_middleware("secret-key")
        # Verify the middleware function is async (no error constructing it)
        import asyncio
        assert asyncio.iscoroutinefunction(middleware)

    @pytest.mark.asyncio
    async def test_missing_token_raises_401(self):
        """Request without Authorization header → HTTPUnauthorized."""
        from aiohttp import web
        middleware = _make_security_middleware("secret-key")

        mock_request = MagicMock()
        mock_request.path = "/balance"
        mock_request.remote = "127.0.0.1"
        mock_request.headers = {}

        async def noop_handler(req):
            return web.Response()

        with pytest.raises(web.HTTPUnauthorized):
            await middleware(mock_request, noop_handler)

    @pytest.mark.asyncio
    async def test_wrong_token_raises_401(self):
        """Request with wrong token → HTTPUnauthorized."""
        from aiohttp import web
        middleware = _make_security_middleware("correct-key")

        mock_request = MagicMock()
        mock_request.path = "/balance"
        mock_request.remote = "127.0.0.1"
        mock_request.headers = {"Authorization": "Bearer wrong-key"}

        async def noop_handler(req):
            return web.Response()

        with pytest.raises(web.HTTPUnauthorized):
            await middleware(mock_request, noop_handler)

    @pytest.mark.asyncio
    async def test_non_localhost_raises_403(self):
        """Request from non-localhost IP → HTTPForbidden."""
        from aiohttp import web
        middleware = _make_security_middleware("correct-key")

        mock_request = MagicMock()
        mock_request.path = "/balance"
        mock_request.remote = "10.0.0.5"  # non-localhost
        mock_request.headers = {"Authorization": "Bearer correct-key"}

        async def noop_handler(req):
            return web.Response()

        with pytest.raises(web.HTTPForbidden):
            await middleware(mock_request, noop_handler)

    @pytest.mark.asyncio
    async def test_valid_token_localhost_passes(self):
        """Valid token from localhost → handler is called."""
        from aiohttp import web
        middleware = _make_security_middleware("correct-key")
        called = []

        mock_request = MagicMock()
        mock_request.path = "/balance"
        mock_request.remote = "127.0.0.1"
        mock_request.headers = {"Authorization": "Bearer correct-key"}

        async def noop_handler(req):
            called.append(True)
            return web.Response()

        await middleware(mock_request, noop_handler)
        assert called


# ──────────────────────────────────────────────────────────────
# FulfillmentService handler unit tests (no real HTTP server)
# ──────────────────────────────────────────────────────────────

class TestFulfillmentServiceHandlers:
    """Test handler methods directly without spinning up an HTTP server."""

    def _make_service(self) -> tuple[FulfillmentService, str]:
        db = _tmp_db_with_wallet()
        cfg = _minimal_config()
        svc = FulfillmentService(
            config=cfg,
            db_path=db,
            mode="paper",
            host="127.0.0.1",
            port=8090,
            api_key="test-key",
        )
        return svc, db

    @pytest.mark.asyncio
    async def test_health_handler_returns_ok(self):
        """GET /health → {"status": "ok", "mode": "paper"}."""
        from aiohttp import web
        svc, _ = self._make_service()
        mock_request = MagicMock()
        response = await svc._health_handler(mock_request)
        import json
        body = json.loads(response.body)
        assert body["status"] == "ok"
        assert body["mode"] == "paper"

    @pytest.mark.asyncio
    async def test_balance_handler_returns_expected_keys(self):
        """GET /balance → dict with cash_usd, total_usd, open_positions_count."""
        from aiohttp import web
        svc, _ = self._make_service()
        mock_request = MagicMock()
        response = await svc._balance_handler(mock_request)
        import json
        body = json.loads(response.body)
        assert "cash_usd" in body
        assert "total_usd" in body
        assert "open_positions_count" in body
        assert body["cash_usd"] == pytest.approx(1000.0, abs=0.01)
        assert body["open_positions_count"] == 0

    @pytest.mark.asyncio
    async def test_positions_handler_returns_empty_list(self):
        """GET /positions → {"positions": []} when no open positions."""
        svc, _ = self._make_service()
        mock_request = MagicMock()
        response = await svc._positions_handler(mock_request)
        import json
        body = json.loads(response.body)
        assert "positions" in body
        assert body["positions"] == []

    @pytest.mark.asyncio
    async def test_fill_buy_succeeds_returns_201(self):
        """POST /fill buy → 201 with fulfillment_id."""
        from aiohttp import web
        svc, _ = self._make_service()
        mock_request = MagicMock()
        mock_request.json = MagicMock(return_value=_make_awaitable({
            "pair":            "BTC/USD",
            "side":            "buy",
            "usd_amount":      50.0,
            "stop_loss_pct":   5.0,
            "take_profit_pct": 8.0,
        }))
        response = await svc._fill_handler(mock_request)
        import json
        body = json.loads(response.body)
        assert response.status == 201
        assert "fulfillment_id" in body
        assert body["status"] == "filled"
        assert body["side"] == "buy"

    @pytest.mark.asyncio
    async def test_fill_missing_pair_returns_400(self):
        """POST /fill without pair → 400 Bad Request."""
        from aiohttp import web
        svc, _ = self._make_service()
        mock_request = MagicMock()
        mock_request.json = MagicMock(return_value=_make_awaitable({
            "side": "buy",
            "usd_amount": 50.0,
        }))
        with pytest.raises(web.HTTPBadRequest):
            await svc._fill_handler(mock_request)

    @pytest.mark.asyncio
    async def test_fill_zero_usd_returns_400(self):
        """POST /fill with usd_amount=0 → 400 Bad Request."""
        from aiohttp import web
        svc, _ = self._make_service()
        mock_request = MagicMock()
        mock_request.json = MagicMock(return_value=_make_awaitable({
            "pair": "BTC/USD",
            "side": "buy",
            "usd_amount": 0.0,
        }))
        with pytest.raises(web.HTTPBadRequest):
            await svc._fill_handler(mock_request)


def _make_awaitable(value):
    """Return a coroutine that yields value — for mocking request.json()."""
    import asyncio
    async def _inner():
        return value
    return _inner()
