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

Design note — timestamp-aligned replay
--------------------------------------
All pairs share the same 15-minute candle grid, but pairs with shorter history
(e.g. BNB/USD starts Apr 2025 while BTC/USD starts 2013) have far fewer candles
in the file.  Using a single global position counter into the *longest* pair's
list would clamp shorter pairs permanently to their last known price, causing
open positions to never hit SL/TP.

Fix: the feed maintains a reference *timestamp* (`_current_ts`) derived from
the longest pair's candle sequence.  For every other pair, `get_candles()` and
`get_latest_price()` do a binary-search on that pair's sorted timestamp list
to find the candle whose time is <= `_current_ts`.  Pairs with no data yet
(newer coins that haven't started yet in the historical window) return [] / None,
and the main loop skips them via `is_ready()`.
"""

import bisect
import logging
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)


class HistoricalFeed:
    """
    Replay candle history for back-testing.

    pair_candles : {pair: [candle_dict, ...]}  full history, sorted oldest-first
    config       : the standard config dict (reads buffer_size, min_candles_to_start)

    The very first tradeable cycle already has min_candles worth of warm-up data
    because the start position is placed min_candles before start_date.
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

        # ── Reference pair: the one with the most candles (widest history) ──
        self._ref_pair = max(pair_candles, key=lambda p: len(pair_candles[p]))
        self._ref_candles = pair_candles[self._ref_pair]
        raw_total = len(self._ref_candles)

        # ── Pre-compute sorted timestamp arrays for O(log n) per-pair lookups ──
        self._pair_times: dict[str, list] = {
            pair: [c["time"] for c in candles]
            for pair, candles in pair_candles.items()
        }

        # ── Determine start position in the reference pair ──
        if start_date:
            ts = datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp()
            start_idx = bisect.bisect_left(self._pair_times[self._ref_pair], int(ts))
            # Warm-up: step back min_candles before the start date
            self._position = max(self._min_candles - 1, start_idx - 1)
        else:
            self._position = self._min_candles - 1

        # ── Cap total steps ──
        if max_steps > 0:
            self._total = min(raw_total, self._position + 1 + max_steps)
        else:
            self._total = raw_total

        self._start_position = self._position

        # ── Track current reference timestamp ──
        self._current_ts: int = self._ref_candles[self._position]["time"]

        actual_date = datetime.utcfromtimestamp(self._current_ts).strftime("%Y-%m-%d")
        logger.info(
            "HistoricalFeed: %d pairs (ref=%s), start=%s position=%d total=%d (%d tradeable steps)",
            len(self._pairs), self._ref_pair, actual_date,
            self._position, self._total,
            max(0, self._total - self._position - 1),
        )

    # ─────────────────────────────────────────────────
    # Internal helper
    # ─────────────────────────────────────────────────

    def _pair_pos(self, pair: str) -> int:
        """
        Return the index of the last candle for *pair* whose timestamp
        is <= the current reference timestamp.  Returns -1 if no such candle.
        """
        times = self._pair_times.get(pair)
        if not times:
            return -1
        idx = bisect.bisect_right(times, self._current_ts) - 1
        return idx

    # ──────────────────────────────────────────────
    # WebSocketFeed-compatible interface
    # ──────────────────────────────────────────────

    def get_candles(self, pair: str) -> list:
        """Return candles up to and including the current timestamp (newest last)."""
        candles = self._pair_candles.get(pair, [])
        if not candles:
            return []
        pos = self._pair_pos(pair)
        if pos < 0:
            return []
        start = max(0, pos + 1 - self._buffer_size)
        return candles[start : pos + 1]

    def get_latest_price(self, pair: str) -> Optional[float]:
        """Return the close price of the candle at or before the current timestamp."""
        candles = self._pair_candles.get(pair, [])
        if not candles:
            return None
        pos = self._pair_pos(pair)
        if pos < 0:
            return None
        return float(candles[pos]["close"])

    def is_ready(self, pair: str, min_candles: int = 60) -> bool:
        return len(self.get_candles(pair)) >= min_candles

    async def start(self) -> None:
        """No-op — candles are already loaded."""
        logger.info("HistoricalFeed.start() — replaying up to %d reference steps", self._total)

    async def stop(self) -> None:
        """No-op."""

    # ──────────────────────────────────────────────
    # Backtest-specific
    # ──────────────────────────────────────────────

    def advance(self) -> bool:
        """
        Step forward one candle in the reference pair's timeline.
        Updates _current_ts so all per-pair lookups stay timestamp-aligned.
        Returns True if the advance succeeded, False when history is exhausted.
        """
        if self._position + 1 >= self._total:
            return False
        self._position += 1
        self._current_ts = self._ref_candles[self._position]["time"]
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
        """Epoch timestamp of the current reference candle."""
        return self._current_ts
