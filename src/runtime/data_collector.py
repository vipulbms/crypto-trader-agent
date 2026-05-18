"""
DataCollector — standalone runtime process that feeds candle data from
Kraken WebSocket into the candle_buffer SQLite table.

Story: S21.1.1 (Sprint S3)
Run as: python -m src.runtime.data_collector [--config config.yaml] [--db paper_trading.db]

Responsibilities:
  1. Connect to Kraken WebSocket and subscribe to OHLCV candles for all active pairs.
  2. On each closed candle, write one row to candle_buffer (deduped by pair+ts).
  3. On each orderbook event, write one snapshot to orderbook_snapshots.
  4. Expose /health HTTP endpoint on 0.0.0.0:8765 (configurable).
  5. Recover from WebSocket disconnections with exponential back-off.

No dependencies on src/agent/ or src/risk/.  Only src/storage.database and
src/exchange.websocket_feed (for KRAKEN_* constants) are used.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
import websockets
import yaml
from aiohttp import web

# Storage helpers — only infrastructure dependencies allowed here
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from src.storage.database import get_connection, COLLECTOR_SCHEMA

logger = logging.getLogger("data_collector")

KRAKEN_WS_URL   = "wss://ws.kraken.com/v2"
KRAKEN_REST_OHLC = "https://api.kraken.com/0/public/OHLC"

# ─────────────────────────────────────────────────────────────
# DB helpers
# ─────────────────────────────────────────────────────────────

def _ensure_schema(db_path: str) -> None:
    """Create candle_buffer and orderbook_snapshots if they don't exist."""
    conn = get_connection(db_path)
    for stmt in COLLECTOR_SCHEMA.split(";"):
        stmt = stmt.strip()
        if stmt:
            conn.execute(stmt)
    conn.commit()
    conn.close()


def _upsert_candle(db_path: str, candle: dict) -> None:
    """Insert or replace a candle row (deduplicated on pair + ts)."""
    now = datetime.now(timezone.utc).isoformat()
    conn = get_connection(db_path)
    conn.execute(
        """
        INSERT OR REPLACE INTO candle_buffer
            (pair, ts, open_price, high, low, close, volume, is_closed, inserted_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            candle["pair"],
            int(candle["ts"]),
            float(candle["open"]),
            float(candle["high"]),
            float(candle["low"]),
            float(candle["close"]),
            float(candle["volume"]),
            1 if candle.get("is_closed", True) else 0,
            now,
        ),
    )
    conn.commit()
    conn.close()


def _upsert_orderbook(db_path: str, snap: dict) -> None:
    """Insert orderbook snapshot row."""
    now = datetime.now(timezone.utc).isoformat()
    best_bid = float(snap["best_bid"])
    best_ask = float(snap["best_ask"])
    denom = best_bid + best_ask
    obi = (best_bid - best_ask) / denom if denom > 0 else 0.0
    conn = get_connection(db_path)
    conn.execute(
        """
        INSERT INTO orderbook_snapshots (pair, ts, best_bid, best_ask, obi, inserted_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (snap["pair"], int(snap["ts"]), best_bid, best_ask, obi, now),
    )
    conn.commit()
    conn.close()


# ─────────────────────────────────────────────────────────────
# Backfill via Kraken REST
# ─────────────────────────────────────────────────────────────

def _backfill_pair(pair: str, rest_name: str, interval_min: int, db_path: str) -> int:
    """Fetch last 720 candles for one pair via REST and write to candle_buffer."""
    url = f"{KRAKEN_REST_OHLC}?pair={rest_name}&interval={interval_min}"
    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        if data.get("error"):
            logger.warning("[DC] Backfill %s REST error: %s", pair, data["error"])
            return 0
        rows = None
        for key, val in data.get("result", {}).items():
            if key != "last":
                rows = val
                break
        if not rows:
            return 0
        written = 0
        conn = get_connection(db_path)
        for row in rows:
            ts, o, h, l, c, _vwap, vol, _cnt = row[:8]
            conn.execute(
                """
                INSERT OR IGNORE INTO candle_buffer
                    (pair, ts, open_price, high, low, close, volume, is_closed, inserted_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?)
                """,
                (pair, int(ts), float(o), float(h), float(l), float(c), float(vol),
                 datetime.now(timezone.utc).isoformat()),
            )
            written += 1
        conn.commit()
        conn.close()
        return written
    except Exception as exc:
        logger.warning("[DC] Backfill %s failed: %s", pair, exc)
        return 0


# ─────────────────────────────────────────────────────────────
# DataCollector
# ─────────────────────────────────────────────────────────────

class DataCollector:
    """
    Connects to Kraken WebSocket, writes closed candles and orderbook snapshots
    to SQLite.  Exposes /health HTTP endpoint.

    AC1:  Standalone; no agent/risk imports.
    AC4:  Closed candles written within ~5s of candle close (WS push).
    AC5:  /health responds with pairs_active + last_write_ts.
    """

    def __init__(self, config: dict, db_path: str, http_host: str = "0.0.0.0", http_port: int = 8765) -> None:
        self._config    = config
        self._db_path   = db_path
        self._http_host = http_host
        self._http_port = http_port

        pairs_cfg = config.get("trading", {}).get("pairs", [])
        self._pairs: list[str] = [p["pair"] for p in pairs_cfg if not p.get("disabled")]
        self._pair_map: dict[str, str] = {
            p["pair"]: p.get("ws_name", p["pair"]) for p in pairs_cfg
        }
        self._rest_map: dict[str, str] = {
            p["pair"]: p.get("rest_name", p["pair"].replace("/", "")) for p in pairs_cfg
        }
        self._interval: int  = config.get("indicators", {}).get("candle_interval", 1)
        self._running         = False
        self._last_write_ts: float | None = None
        self._pairs_active    = 0
        # S21.1.2 — feed freeze tracking
        self._feed_status_cache: dict[str, str] = {}  # pair → 'ok' | 'frozen' | 'stale'
        _qsa_cfg = config.get("qsa", {})
        self._freeze_variance_lookback: int = (
            _qsa_cfg.get("feed_heartbeat", {}).get("variance_lookback", 5)
        )

    # ── lifecycle ────────────────────────────────────────────

    async def start(self) -> None:
        _ensure_schema(self._db_path)
        logger.info("[DC] DataCollector starting — %d pairs, db=%s", len(self._pairs), self._db_path)
        # Backfill from REST before connecting WS
        for pair in self._pairs:
            rest_name = self._rest_map.get(pair, pair.replace("/", ""))
            n = _backfill_pair(pair, rest_name, self._interval, self._db_path)
            logger.info("[DC] Backfilled %d candles for %s", n, pair)

        self._running = True
        self._pairs_active = len(self._pairs)
        await asyncio.gather(
            self._ws_loop(),
            self._http_server(),
        )

    async def stop(self) -> None:
        self._running = False

    # ── WebSocket loop ────────────────────────────────────────

    async def _ws_loop(self) -> None:
        backoff = 2
        while self._running:
            try:
                async with websockets.connect(
                    KRAKEN_WS_URL,
                    ping_interval=20,
                    ping_timeout=10,
                ) as ws:
                    await self._subscribe(ws)
                    backoff = 2  # reset on success
                    async for raw in ws:
                        if not self._running:
                            break
                        await self._handle_message(raw)
            except Exception as exc:
                if not self._running:
                    break
                logger.warning("[DC] WS error: %s — reconnecting in %ds", exc, backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60)

    async def _subscribe(self, ws) -> None:
        ws_pairs = [self._pair_map.get(p, p) for p in self._pairs]
        msg = json.dumps({
            "method": "subscribe",
            "params": {
                "channel": "ohlc",
                "symbol": ws_pairs,
                "interval": self._interval,
            },
        })
        await ws.send(msg)
        logger.info("[DC] Subscribed to OHLC for %d pairs", len(ws_pairs))

    async def _handle_message(self, raw: str) -> None:
        try:
            msg = json.loads(raw)
        except Exception:
            return
        channel = msg.get("channel", "")
        if channel == "ohlc":
            data_list = msg.get("data", [])
            for item in data_list:
                is_closed = bool(item.get("confirm", False))
                if not is_closed:
                    continue  # skip in-progress candles
                ws_symbol = item.get("symbol", "")
                # Reverse-lookup display name
                pair = next(
                    (p for p, w in self._pair_map.items() if w == ws_symbol),
                    ws_symbol,
                )
                candle = {
                    "pair":      pair,
                    "ts":        item.get("timestamp_open", item.get("timestamp", 0)),
                    "open":      item.get("open", 0),
                    "high":      item.get("high", 0),
                    "low":       item.get("low", 0),
                    "close":     item.get("close", 0),
                    "volume":    item.get("volume", 0),
                    "is_closed": True,
                }
                _upsert_candle(self._db_path, candle)
                self._last_write_ts = time.time()
                logger.debug("[DC] Candle written: %s ts=%s close=%.4f",
                             pair, candle["ts"], candle["close"])

        elif channel == "book":
            asks = msg.get("data", {}).get("asks", [])
            bids = msg.get("data", {}).get("bids", [])
            ws_symbol = msg.get("symbol", "")
            pair = next(
                (p for p, w in self._pair_map.items() if w == ws_symbol), ws_symbol
            )
            if asks and bids:
                snap = {
                    "pair":     pair,
                    "ts":       int(time.time()),
                    "best_bid": bids[0][0] if isinstance(bids[0], list) else bids[0],
                    "best_ask": asks[0][0] if isinstance(asks[0], list) else asks[0],
                }
                _upsert_orderbook(self._db_path, snap)

    # ── Feed freeze detection (S21.1.2) ──────────────────────

    def _detect_feed_status(self, pair: str) -> str:
        """
        Returns 'ok' | 'frozen' | 'stale'.

        frozen: last N closed candles all have identical close price (zero-variance).
        stale:  most recent candle timestamp is > 5 × candle_interval minutes old.
        """
        n = self._freeze_variance_lookback
        try:
            conn = get_connection(self._db_path)
            rows = conn.execute(
                """
                SELECT close, ts FROM candle_buffer
                WHERE pair = ? AND is_closed = 1
                ORDER BY ts DESC LIMIT ?
                """,
                (pair, n),
            ).fetchall()
            conn.close()
        except Exception:
            return "ok"  # DB unavailable — assume live

        if len(rows) < n:
            return "ok"  # not enough history yet

        closes = [float(r[0]) for r in rows]
        mean = sum(closes) / len(closes)
        variance = sum((x - mean) ** 2 for x in closes) / len(closes)
        if variance == 0.0:
            prev = self._feed_status_cache.get(pair, "ok")
            if prev != "frozen":
                logger.warning("[DC] Feed FROZEN detected: %s — last %d closes identical (%.4f)",
                               pair, n, closes[0])
            return "frozen"

        stale_secs = self._interval * 60 * 5  # 5 missed intervals
        latest_ts = max(int(r[1]) for r in rows)
        if (time.time() - latest_ts) > stale_secs:
            return "stale"

        return "ok"

    def _refresh_feed_statuses(self) -> dict[str, str]:
        """Check all tracked pairs and update _feed_status_cache."""
        for pair in self._pairs:
            status = self._detect_feed_status(pair)
            self._feed_status_cache[pair] = status
        return dict(self._feed_status_cache)

    # ── HTTP /health endpoint ─────────────────────────────────

    async def _health_handler(self, request: web.Request) -> web.Response:
        payload = {
            "status":        "ok",
            "pairs_active":  self._pairs_active,
            "last_write_ts": self._last_write_ts,
        }
        return web.json_response(payload)

    async def _feed_status_handler(self, request: web.Request) -> web.Response:
        """S21.1.2 — per-pair feed freeze status endpoint."""
        statuses = self._refresh_feed_statuses()
        payload = {
            "feed_status": statuses,
            "frozen_pairs": [p for p, s in statuses.items() if s == "frozen"],
            "stale_pairs":  [p for p, s in statuses.items() if s == "stale"],
            "ts":           time.time(),
        }
        return web.json_response(payload)

    async def _http_server(self) -> None:
        app = web.Application()
        app.router.add_get("/health", self._health_handler)
        app.router.add_get("/feed_status", self._feed_status_handler)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, self._http_host, self._http_port)
        await site.start()
        logger.info("[DC] /health listening on %s:%d", self._http_host, self._http_port)
        while self._running:
            await asyncio.sleep(1)
        await runner.cleanup()


# ─────────────────────────────────────────────────────────────
# Entrypoint
# ─────────────────────────────────────────────────────────────

def _load_config(config_path: str) -> dict:
    with open(config_path, "r") as f:
        return yaml.safe_load(f)


async def _main(args) -> None:
    config   = _load_config(args.config)
    db_path  = args.db or config.get("storage", {}).get("paper_db", "paper_trading.db")
    port     = args.port

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    collector = DataCollector(config, db_path, http_port=port)

    loop = asyncio.get_running_loop()

    def _shutdown(_sig, _frame):
        logger.info("[DC] Shutdown signal received")
        loop.create_task(collector.stop())

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    await collector.start()


def main() -> None:
    parser = argparse.ArgumentParser(description="Kryptos DataCollector")
    parser.add_argument("--config", default="config.yaml",     help="Path to config.yaml")
    parser.add_argument("--db",     default=None,              help="SQLite DB path (overrides config)")
    parser.add_argument("--port",   type=int, default=8765,    help="HTTP health port")
    args = parser.parse_args()
    asyncio.run(_main(args))


if __name__ == "__main__":
    main()
