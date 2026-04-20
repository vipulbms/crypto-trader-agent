"""
FulfillmentService — standalone HTTP service that wraps the broker (paper or live)
and exposes a simple REST API for order placement and portfolio inspection.

Story: S21.2.1 (Sprint S4)
Run as: python -m src.runtime.fulfillment_service [--mode paper|live] [--port 8090]

Endpoints:
  POST  /fill        — Place a buy or close a position (Bearer token required)
  GET   /positions   — List open positions (Bearer token required)
  GET   /balance     — Cash + total portfolio value (Bearer token required)
  GET   /health      — Liveness probe (no auth)

Security:
  - 127.0.0.1 (localhost) requests only — 403 for all other remote IPs.
  - Bearer token from env var FULFILLMENT_API_KEY or config.fulfillment.api_key.
  - 401 on missing/invalid token for all authenticated endpoints.

No dependencies on src/agent/ or src/risk/.  Uses the broker abstraction only.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import signal
import sys
import uuid
from pathlib import Path
from typing import Optional

import yaml
from aiohttp import web

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from src.storage.database import get_connection

logger = logging.getLogger("fulfillment_service")

_ALLOWED_HOSTS = {"127.0.0.1", "::1"}


# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────

def _get_last_price(pair: str, db_path: str) -> Optional[float]:
    """Return the last closed candle price for *pair* from candle_buffer."""
    try:
        conn = get_connection(db_path)
        row = conn.execute(
            "SELECT close FROM candle_buffer WHERE pair=? AND is_closed=1 ORDER BY ts DESC LIMIT 1",
            (pair,),
        ).fetchone()
        conn.close()
        return float(row[0]) if row else None
    except Exception:
        return None


def _pair_config(config: dict, pair: str) -> dict:
    """Return the trading config block for *pair*, or empty dict."""
    for p in config.get("trading", {}).get("pairs", []):
        if p.get("pair") == pair:
            return p
    return {}


# ─────────────────────────────────────────────────────────────
# Middleware
# ─────────────────────────────────────────────────────────────

def _make_security_middleware(api_key: str):
    """Return aiohttp middleware that enforces localhost + Bearer token auth."""

    @web.middleware
    async def middleware(request: web.Request, handler):
        # Allow /health without auth — check first
        if request.path == "/health":
            return await handler(request)

        # Localhost-only guard
        remote = request.remote or ""
        if remote.split(":")[0] not in _ALLOWED_HOSTS and remote not in _ALLOWED_HOSTS:
            logger.warning("[FS] Rejected request from non-localhost IP: %s", remote)
            raise web.HTTPForbidden(reason="Access restricted to localhost")

        # Bearer token check
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            raise web.HTTPUnauthorized(
                reason="Missing Bearer token",
                headers={"WWW-Authenticate": 'Bearer realm="fulfillment"'},
            )
        token = auth_header[7:]
        if token != api_key:
            raise web.HTTPUnauthorized(
                reason="Invalid Bearer token",
                headers={"WWW-Authenticate": 'Bearer realm="fulfillment"'},
            )

        return await handler(request)

    return middleware


# ─────────────────────────────────────────────────────────────
# FulfillmentService
# ─────────────────────────────────────────────────────────────

class FulfillmentService:
    """
    HTTP service wrapping the broker.  Supports paper mode (PaperBroker) and
    live mode (KrakenClient with the same interface).

    AC: binds 127.0.0.1 only; Bearer token required; /health unauthenticated.
    """

    def __init__(
        self,
        config: dict,
        db_path: str,
        mode: str = "paper",
        host: str = "127.0.0.1",
        port: int = 8090,
        api_key: str = "",
    ) -> None:
        self._config  = config
        self._db_path = db_path
        self._mode    = mode
        self._host    = host
        self._port    = port
        self._api_key = api_key
        self._running = False

        # Lazy-import broker based on mode to avoid circular dependency scans
        if mode == "live":
            from src.exchange.kraken_client import KrakenClient
            self._broker = KrakenClient(config)
        else:
            from src.exchange.paper_broker import PaperBroker
            self._broker = PaperBroker(db_path, config=config)

    # ── request handlers ─────────────────────────────────────

    async def _health_handler(self, request: web.Request) -> web.Response:
        return web.json_response({"status": "ok", "mode": self._mode})

    async def _balance_handler(self, request: web.Request) -> web.Response:
        try:
            bal = self._broker.get_balance()
        except Exception as exc:
            logger.error("[FS] get_balance failed: %s", exc)
            raise web.HTTPInternalServerError(reason=str(exc))

        positions = self._broker.get_open_positions()
        return web.json_response(
            {
                "cash_usd":            bal.get("available_cash_usd", 0.0),
                "total_usd":           bal.get("total_usd", 0.0),
                "open_positions_count": len(positions),
            }
        )

    async def _positions_handler(self, request: web.Request) -> web.Response:
        try:
            positions = self._broker.get_open_positions()
        except Exception as exc:
            logger.error("[FS] get_open_positions failed: %s", exc)
            raise web.HTTPInternalServerError(reason=str(exc))
        return web.json_response({"positions": positions})

    async def _fill_handler(self, request: web.Request) -> web.Response:
        """
        POST /fill
        Body (JSON):
          {
            "pair":             "BTC/USD",   # required
            "side":             "buy",       # required: "buy" | "sell"
            "usd_amount":       100.0,       # required for buy; ignored for sell
            "stop_loss_pct":    5.0,         # optional; falls back to pair config
            "take_profit_pct":  8.0,         # optional; falls back to pair config
            "exit_reason":      "agent_sell" # optional; used when side=sell
          }
        """
        try:
            body = await request.json()
        except Exception:
            raise web.HTTPBadRequest(reason="Invalid JSON body")

        pair = body.get("pair", "").strip()
        side = body.get("side", "").lower().strip()
        if not pair or side not in ("buy", "sell"):
            raise web.HTTPBadRequest(reason="'pair' and 'side' (buy|sell) are required")

        fulfillment_id = str(uuid.uuid4())

        if side == "buy":
            usd_amount = float(body.get("usd_amount", 0))
            if usd_amount <= 0:
                raise web.HTTPBadRequest(reason="'usd_amount' must be > 0 for buy")

            # Resolve SL/TP: request body → pair config → global default
            pair_cfg = _pair_config(self._config, pair)
            global_risk = self._config.get("risk", {})
            stop_loss_pct = float(
                body.get("stop_loss_pct")
                or pair_cfg.get("stop_loss_pct")
                or global_risk.get("stop_loss_pct", 5.0)
            )
            take_profit_pct = float(
                body.get("take_profit_pct")
                or pair_cfg.get("take_profit_pct", 8.0)
            )

            current_price = _get_last_price(pair, self._db_path)
            if current_price is None:
                raise web.HTTPServiceUnavailable(reason=f"No price data for {pair} in candle_buffer")

            try:
                result = self._broker.place_order(
                    pair=pair,
                    side="buy",
                    usd_amount=usd_amount,
                    current_price=current_price,
                    stop_loss_pct=stop_loss_pct,
                    take_profit_pct=take_profit_pct,
                )
            except ValueError as exc:
                raise web.HTTPUnprocessableEntity(reason=str(exc))
            except Exception as exc:
                logger.error("[FS] place_order %s failed: %s", pair, exc)
                raise web.HTTPInternalServerError(reason=str(exc))

            return web.json_response(
                {
                    "fulfillment_id":  fulfillment_id,
                    "status":          "filled",
                    "pair":            result["pair"],
                    "side":            "buy",
                    "filled_price":    result["fill_price"],
                    "filled_usd":      result["usd_invested"],
                    "volume":          result["volume"],
                    "entry_order_id":  result.get("entry_order_id", ""),
                    "position_id":     result.get("position_id"),
                },
                status=201,
            )

        else:  # side == "sell"
            exit_reason = str(body.get("exit_reason", "agent_sell"))
            current_price = _get_last_price(pair, self._db_path)
            if current_price is None:
                raise web.HTTPServiceUnavailable(reason=f"No price data for {pair} in candle_buffer")

            try:
                result = self._broker.close_position(pair, current_price, exit_reason=exit_reason)
            except ValueError as exc:
                raise web.HTTPUnprocessableEntity(reason=str(exc))
            except Exception as exc:
                logger.error("[FS] close_position %s failed: %s", pair, exc)
                raise web.HTTPInternalServerError(reason=str(exc))

            return web.json_response(
                {
                    "fulfillment_id": fulfillment_id,
                    "status":         "closed",
                    "pair":           pair,
                    "side":           "sell",
                    "exit_reason":    exit_reason,
                    "pnl_usd":        result.get("pnl_usd"),
                    "pnl_pct":        result.get("pnl_pct"),
                }
            )

    # ── lifecycle ─────────────────────────────────────────────

    async def start(self) -> None:
        self._running = True
        middleware = _make_security_middleware(self._api_key)
        app = web.Application(middlewares=[middleware])
        app.router.add_get("/health",    self._health_handler)
        app.router.add_get("/balance",   self._balance_handler)
        app.router.add_get("/positions", self._positions_handler)
        app.router.add_post("/fill",     self._fill_handler)

        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, self._host, self._port)
        await site.start()
        logger.info("[FS] FulfillmentService (%s) listening on %s:%d", self._mode, self._host, self._port)

        while self._running:
            await asyncio.sleep(1)

        await runner.cleanup()

    async def stop(self) -> None:
        self._running = False


# ─────────────────────────────────────────────────────────────
# Entrypoint
# ─────────────────────────────────────────────────────────────

def _load_config(config_path: str) -> dict:
    with open(config_path, "r") as f:
        return yaml.safe_load(f)


async def _main(args) -> None:
    config  = _load_config(args.config)
    db_path = args.db or config.get("storage", {}).get("paper_db", "paper_trading.db")
    api_key = (
        os.environ.get("FULFILLMENT_API_KEY")
        or config.get("fulfillment", {}).get("api_key", "")
    )
    if not api_key:
        logger.warning(
            "[FS] No FULFILLMENT_API_KEY set — all authenticated endpoints will reject requests"
        )

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    service = FulfillmentService(
        config=config,
        db_path=db_path,
        mode=args.mode,
        host="127.0.0.1",
        port=args.port,
        api_key=api_key,
    )

    loop = asyncio.get_running_loop()

    def _shutdown(_sig, _frame):
        logger.info("[FS] Shutdown signal received")
        loop.create_task(service.stop())

    signal.signal(signal.SIGINT,  _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    await service.start()


def main() -> None:
    parser = argparse.ArgumentParser(description="Kryptos FulfillmentService")
    parser.add_argument("--config", default="config.yaml",  help="Path to config.yaml")
    parser.add_argument("--db",     default=None,           help="SQLite DB path")
    parser.add_argument("--mode",   default="paper",        choices=["paper", "live"], help="Broker mode")
    parser.add_argument("--port",   type=int, default=8090, help="HTTP port (default 8090)")
    args = parser.parse_args()
    asyncio.run(_main(args))


if __name__ == "__main__":
    main()
