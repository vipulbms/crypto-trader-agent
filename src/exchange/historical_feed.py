"""
HistoricalFeed — drop-in replacement for WebSocketFeed that replays candle
history from pre-loaded files instead of a live WebSocket connection.

Implements the same public interface as WebSocketFeed:
    get_candles(pair)
    get_latest_price(pair)
    is_ready(pair, min_candles)
    start()   — async no-op
    stop()    — async no-op

Extra method:
    advance() → bool   step forward one candle; returns False when history is exhausted
"""

import logging
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)


class HistoricalFeed:
    """
    Replay candle history for back-testing.

    pair_candles : {pair: [candle_dict, ...]}  full history, sorted oldest-first
    config       : the standard config dict (reads buffer_size, min_candles_to_start)

    Position starts at min_candles - 1 so the very first cycle already has
    enough data to compute indicators without any warmup wait.
    """

    def __init__(
        self,
        pair_candles: dict,
        config: dict,
        max_steps: int = 0,
        start_date: str = "",   # "YYYY-MM-DD" — start trading from this date
    ):
        ind_cfg = config.get("indicators", {})
        self._pair_candles = pair_candles
        self._pairs = list(pair_candles.keys())
        self._buffer_size = ind_cfg.get("candle_buffer_size", 750)
        self._min_candles = ind_cfg.get("min_candles_to_start", 220)

        # Use the longest pair as the time reference — shorter pairs return [] when out of range
        raw_total = max(len(c) for c in pair_candles.values()) if pair_candles else 0

        # Find the candle index for start_date using the longest pair as reference
        if start_date:
            ts = datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp()
            ref = max(pair_candles.values(), key=len)
            start_idx = next(
                (i for i, c in enumerate(ref) if c.get("time", c.get("timestamp", 0)) >= ts),
                0,
            )
            # Position starts min_candles before start_date so indicators are warm
            self._position = max(self._min_candles - 1, start_idx - 1)
        else:
            self._position = self._min_candles - 1

        # Cap end based on max_steps from the starting position
        if max_steps > 0:
            self._total = min(raw_total, self._position + 1 + max_steps)
        else:
            self._total = raw_total

        self._start_position = self._position

        actual_date = datetime.utcfromtimestamp(
            next(iter(pair_candles.values()), [{}])[self._position].get("time",
            next(iter(pair_candles.values()), [{}])[self._position].get("timestamp", 0))
        ).strftime("%Y-%m-%d") if pair_candles else "unknown"

        logger.info(
            "HistoricalFeed: %d pairs, start=%s position=%d total=%d (%d tradeable steps)",
            len(self._pairs), actual_date, self._position, self._total,
            max(0, self._total - self._position - 1),
        )

    # ──────────────────────────────────────────────
    # WebSocketFeed-compatible interface
    # ──────────────────────────────────────────────

    def get_candles(self, pair: str) -> list:
        """Return candles up to and including the current position (newest last)."""
        candles = self._pair_candles.get(pair, [])
        if not candles:
            return []
        pos = min(self._position, len(candles) - 1)
        start = max(0, pos + 1 - self._buffer_size)
        return candles[start : pos + 1]

    def get_latest_price(self, pair: str) -> Optional[float]:
        """Return the close price of the current candle."""
        candles = self._pair_candles.get(pair, [])
        if not candles:
            return None
        pos = min(self._position, len(candles) - 1)
        return float(candles[pos]["close"])

    def is_ready(self, pair: str, min_candles: int = 60) -> bool:
        return len(self.get_candles(pair)) >= min_candles

    async def start(self) -> None:
        """No-op — candles are already loaded."""
        logger.info("HistoricalFeed.start() — replaying %d candles per pair", self._total)

    async def stop(self) -> None:
        """No-op."""

    # ──────────────────────────────────────────────
    # Backtest-specific
    # ──────────────────────────────────────────────

    def advance(self) -> bool:
        """
        Step forward one candle.
        Returns True if the advance succeeded, False when history is exhausted.
        """
        if self._position + 1 >= self._total:
            return False
        self._position += 1
        return True

    @property
    def total_tradeable(self) -> int:
        return max(0, self._total - self._start_position - 1)

    @property
    def progress(self) -> str:
        tradeable = max(1, self._total - self._start_position - 1)
        done = self._position - self._start_position
        return f"{done}/{tradeable} ({done / tradeable * 100:.1f}%)"

    @property
    def current_candle_time(self) -> int:
        """Epoch timestamp of the current candle (uses first pair as reference)."""
        candles = next(iter(self._pair_candles.values()), [])
        if not candles or self._position >= len(candles):
            return 0
        c = candles[self._position]
        return int(c.get("time", c.get("timestamp", 0)))
