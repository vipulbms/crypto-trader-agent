"""
WebSocket feed — subscribes to Kraken public OHLCV candles for all configured pairs.
Buffers the last N candles per pair in memory for indicator calculation.
On startup, back-fills history via Kraken public REST (no API key required).
"""

import asyncio
import json
import logging
import time
from collections import deque
from datetime import datetime, timezone
from typing import Dict, Optional

import requests
import websockets

logger = logging.getLogger(__name__)

# Kraken uses XBT internally; map display names to Kraken WS pair names
PAIR_MAP = {
    "BTC/USD": "XBT/USD",
    "ETH/USD": "ETH/USD",
    "BNB/USD": "BNB/USD",
    "SOL/USD": "SOL/USD",
}

# Kraken REST public OHLC pair names (different format from WS)
REST_PAIR_MAP = {
    "BTC/USD": "XBTUSD",
    "ETH/USD": "ETHUSD",
    "BNB/USD": "BNBUSD",
    "SOL/USD": "SOLUSD",
}

KRAKEN_WS_URL = "wss://ws.kraken.com/v2"
KRAKEN_REST_OHLC = "https://api.kraken.com/0/public/OHLC"


class CandleBuffer:
    """Thread-safe deque of OHLCV dicts for one pair."""

    def __init__(self, maxlen: int = 200):
        self._buf: deque = deque(maxlen=maxlen)

    def append(self, candle: dict) -> None:
        self._buf.append(candle)

    def to_list(self) -> list:
        return list(self._buf)

    def __len__(self) -> int:
        return len(self._buf)


class WebSocketFeed:
    """
    Manages a persistent WebSocket connection to Kraken public API.
    Provides get_candles(pair) for the analysis layer.
    """

    def __init__(self, config: dict):
        ind_cfg = config.get("indicators", {})
        self._buffer_size: int = ind_cfg.get("candle_buffer_size", 200)
        self._interval: int = ind_cfg.get("candle_interval", 1)
        pairs_cfg = config.get("trading", {}).get("pairs", [])
        self._pairs: list = [p["pair"] for p in pairs_cfg]
        self._buffers: Dict[str, CandleBuffer] = {
            pair: CandleBuffer(self._buffer_size) for pair in self._pairs
        }
        self._latest_price: Dict[str, float] = {}
        self._running = False
        self._task: Optional[asyncio.Task] = None

    # ──────────────────────────────────────────────
    # Public API
    # ──────────────────────────────────────────────

    def get_candles(self, pair: str) -> list:
        """Return list of OHLCV dicts for the given pair (newest last)."""
        buf = self._buffers.get(pair)
        return buf.to_list() if buf else []

    def get_latest_price(self, pair: str) -> Optional[float]:
        return self._latest_price.get(pair)

    def is_ready(self, pair: str, min_candles: int = 60) -> bool:
        """True once we have enough candles to compute indicators reliably."""
        buf = self._buffers.get(pair)
        return len(buf) >= min_candles if buf else False

    async def start(self) -> None:
        """Back-fill history then start live WebSocket feed."""
        await self._backfill_all()
        self._running = True
        self._task = asyncio.create_task(self._ws_loop())
        logger.info("WebSocket feed started for pairs: %s", self._pairs)

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("WebSocket feed stopped")

    # ──────────────────────────────────────────────
    # Back-fill via public REST
    # ──────────────────────────────────────────────

    async def _backfill_all(self) -> None:
        loop = asyncio.get_event_loop()
        for pair in self._pairs:
            await loop.run_in_executor(None, self._backfill_pair, pair)

    def _backfill_pair(self, pair: str) -> None:
        rest_pair = REST_PAIR_MAP.get(pair)
        if not rest_pair:
            logger.warning("No REST pair mapping for %s — skipping back-fill", pair)
            return
        try:
            resp = requests.get(
                KRAKEN_REST_OHLC,
                params={"pair": rest_pair, "interval": self._interval},
                timeout=10,
            )
            data = resp.json()
            if data.get("error"):
                logger.warning("Kraken REST error for %s: %s", pair, data["error"])
                return
            result = data.get("result", {})
            candles_raw = result.get(rest_pair) or result.get(next(iter(result), ""), [])
            buf = self._buffers[pair]
            # Kraken OHLC format: [time, open, high, low, close, vwap, volume, count]
            for c in candles_raw[-self._buffer_size:]:
                buf.append({
                    "timestamp": int(c[0]),
                    "open":   float(c[1]),
                    "high":   float(c[2]),
                    "low":    float(c[3]),
                    "close":  float(c[4]),
                    "volume": float(c[6]),
                })
            if len(buf) > 0:
                self._latest_price[pair] = buf.to_list()[-1]["close"]
            logger.info("Back-filled %d candles for %s", len(buf), pair)
        except Exception as e:
            logger.error("Back-fill failed for %s: %s", pair, e)

    # ──────────────────────────────────────────────
    # WebSocket loop
    # ──────────────────────────────────────────────

    def _build_subscribe_msg(self) -> dict:
        ws_pairs = [PAIR_MAP.get(p, p) for p in self._pairs]
        return {
            "method": "subscribe",
            "params": {
                "channel": "ohlc",
                "symbol": ws_pairs,
                "interval": self._interval,
            },
        }

    async def _ws_loop(self) -> None:
        backoff = 2
        while self._running:
            try:
                async with websockets.connect(KRAKEN_WS_URL, ping_interval=20) as ws:
                    await ws.send(json.dumps(self._build_subscribe_msg()))
                    logger.info("Subscribed to Kraken OHLC feed")
                    backoff = 2
                    async for raw in ws:
                        if not self._running:
                            break
                        self._handle_message(raw)
            except (websockets.ConnectionClosed, OSError) as e:
                if not self._running:
                    break
                logger.warning("WebSocket disconnected (%s) — reconnecting in %ds", e, backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60)
            except Exception as e:
                logger.error("WebSocket error: %s", e)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60)

    def _handle_message(self, raw: str) -> None:
        try:
            msg = json.loads(raw)
            # Kraken WS v2 OHLC message format
            if msg.get("channel") != "ohlc":
                return
            if msg.get("type") not in ("snapshot", "update"):
                return
            for entry in msg.get("data", []):
                # Map Kraken WS symbol back to our pair name
                ws_symbol = entry.get("symbol", "")
                pair = self._ws_symbol_to_pair(ws_symbol)
                if not pair:
                    continue
                candle = {
                    "timestamp": int(
                        datetime.fromisoformat(
                            entry["timestamp"].replace("Z", "+00:00")
                        ).timestamp()
                    ),
                    "open":   float(entry.get("open", 0)),
                    "high":   float(entry.get("high", 0)),
                    "low":    float(entry.get("low", 0)),
                    "close":  float(entry.get("close", 0)),
                    "volume": float(entry.get("volume", 0)),
                }
                buf = self._buffers.get(pair)
                if buf:
                    # Replace last candle if same timestamp (update), else append
                    existing = buf.to_list()
                    if existing and existing[-1]["timestamp"] == candle["timestamp"]:
                        existing[-1].update(candle)
                    else:
                        buf.append(candle)
                    self._latest_price[pair] = candle["close"]
        except Exception as e:
            logger.debug("Error handling WS message: %s", e)

    def _ws_symbol_to_pair(self, ws_symbol: str) -> Optional[str]:
        reverse = {v: k for k, v in PAIR_MAP.items()}
        return reverse.get(ws_symbol)
