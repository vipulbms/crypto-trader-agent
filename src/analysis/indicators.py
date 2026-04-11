"""
Technical indicator computation using the `ta` library.
Accepts a list of OHLCV dicts and returns a dict of latest indicator values.
"""

import logging
import math
from typing import Optional

import pandas as pd
import ta.momentum
import ta.trend
import ta.volatility

from src.utils.timing import timed

logger = logging.getLogger(__name__)


@timed("config")
def compute_indicators(candles: list, config: dict) -> Optional[dict]:
    """
    Compute technical indicators from a list of OHLCV candle dicts.

    Returns a flat dict of indicator values for the most recent candle,
    or None if there are insufficient candles.
    """
    min_candles = config.get("indicators", {}).get("min_candles_to_start", 220)
    if not candles or len(candles) < min_candles:
        return None

    ind_cfg = config.get("indicators", {})
    rsi_period    = ind_cfg.get("rsi_period", 14)
    macd_fast     = ind_cfg.get("macd_fast", 12)
    macd_slow     = ind_cfg.get("macd_slow", 26)
    macd_signal   = ind_cfg.get("macd_signal", 9)
    bb_period     = ind_cfg.get("bb_period", 20)
    bb_std        = ind_cfg.get("bb_std", 2)
    ema_fast      = ind_cfg.get("ema_fast", 20)
    ema_slow      = ind_cfg.get("ema_slow", 50)
    atr_period    = ind_cfg.get("atr_period", 14)
    adx_period    = ind_cfg.get("adx_period", 14)

    df = pd.DataFrame(candles)
    df = df.astype({
        "open": float, "high": float, "low": float,
        "close": float, "volume": float
    })

    def safe(val):
        """Return float or None for missing/NaN values."""
        try:
            v = float(val)
            return None if math.isnan(v) else round(v, 6)
        except Exception:
            return None

    try:
        rsi = ta.momentum.RSIIndicator(close=df["close"], window=rsi_period).rsi()

        macd_obj = ta.trend.MACD(
            close=df["close"],
            window_fast=macd_fast,
            window_slow=macd_slow,
            window_sign=macd_signal,
        )
        macd_line = macd_obj.macd()
        macd_signal_line = macd_obj.macd_signal()
        macd_histogram = macd_obj.macd_diff()

        bb_obj = ta.volatility.BollingerBands(
            close=df["close"], window=bb_period, window_dev=bb_std
        )
        bb_upper = bb_obj.bollinger_hband()
        bb_mid   = bb_obj.bollinger_mavg()
        bb_lower = bb_obj.bollinger_lband()

        ema_9_series = ta.trend.EMAIndicator(
            close=df["close"], window=9
        ).ema_indicator()
        ema_21_series = ta.trend.EMAIndicator(
            close=df["close"], window=21
        ).ema_indicator()
        ema_fast_series = ta.trend.EMAIndicator(
            close=df["close"], window=ema_fast
        ).ema_indicator()
        ema_slow_series = ta.trend.EMAIndicator(
            close=df["close"], window=ema_slow
        ).ema_indicator()

        atr = ta.volatility.AverageTrueRange(
            high=df["high"], low=df["low"], close=df["close"], window=atr_period
        ).average_true_range()

        # ADX — trend strength indicator (Wilder, period=14 by default)
        # Returns 0-100: <20 = ranging/choppy, 20-40 = moderate trend, >40 = strong trend
        adx_obj = ta.trend.ADXIndicator(
            high=df["high"], low=df["low"], close=df["close"], window=adx_period
        )
        adx_series = adx_obj.adx()

        # Add volume moving average to detect dry volume (dead zones)
        volume_sma_20 = df["volume"].rolling(window=20).mean()

        # OBV — On-Balance Volume: cumulative directional volume
        # Rising OBV = accumulation (smart money buying); falling = distribution
        direction = df["close"].diff().apply(lambda d: 1 if d > 0 else (-1 if d < 0 else 0))
        obv_series_full = (direction * df["volume"]).cumsum()

        # BB width series — needed by signals.py for squeeze release detection
        # Expressed as % of price so it is price-scale agnostic
        bb_width_series_full = ((bb_upper - bb_lower) / df["close"] * 100).fillna(0)

        # Candlestick patterns — computed from raw OHLC arrays (#184)
        candlestick_patterns = detect_candlestick_patterns(
            opens=df["open"].tolist(),
            highs=df["high"].tolist(),
            lows=df["low"].tolist(),
            closes=df["close"].tolist(),
            atr=safe(atr.iloc[-1]),
        )

    except Exception as e:
        logger.error("Indicator calculation error: %s", e)
        return None

    # macd_histogram_prev: second-to-last histogram value — used to detect a turn
    # (negative → positive crossover is a stronger signal than just being positive)
    hist_vals = macd_histogram.dropna()
    macd_histogram_prev = safe(hist_vals.iloc[-2]) if len(hist_vals) >= 2 else None

    # RSI and close series (last 30 values) — used by signals.py for divergence detection
    # 30 covers the maximum rsi_divergence_lookback (25) with a small buffer
    rsi_clean   = rsi.dropna()
    close_clean = df["close"].iloc[len(df) - len(rsi_clean):]
    _series_len = min(30, len(rsi_clean))
    rsi_series   = [safe(v) for v in rsi_clean.iloc[-_series_len:]]
    close_series = [safe(v) for v in close_clean.iloc[-_series_len:]]

    # OBV series — last 30 values for trend computation in signals.py (per-pair period)
    obv_clean = obv_series_full.dropna()
    _obv_len = min(30, len(obv_clean))
    obv_series = [safe(v) for v in obv_clean.iloc[-_obv_len:]]

    # BB width series — last 10 values for squeeze release detection in signals.py
    _bb_len = min(10, len(bb_width_series_full))
    bb_width_series = [safe(v) for v in bb_width_series_full.iloc[-_bb_len:]]

    return {
        "rsi_14":               safe(rsi.iloc[-1]),
        "macd_line":            safe(macd_line.iloc[-1]),
        "macd_signal_line":     safe(macd_signal_line.iloc[-1]),
        "macd_histogram":       safe(macd_histogram.iloc[-1]),
        "macd_histogram_prev":  macd_histogram_prev,
        "ema_9":                safe(ema_9_series.iloc[-1]),
        "ema_21":               safe(ema_21_series.iloc[-1]),
        "ema_20":               safe(ema_fast_series.iloc[-1]),
        "ema_50":               safe(ema_slow_series.iloc[-1]),
        "bb_upper":             safe(bb_upper.iloc[-1]),
        "bb_mid":               safe(bb_mid.iloc[-1]),
        "bb_lower":             safe(bb_lower.iloc[-1]),
        "atr_14":               safe(atr.iloc[-1]),
        "adx_14":               safe(adx_series.iloc[-1]),
        "volume":               safe(df["volume"].iloc[-1]),
        "volume_sma_20":        safe(volume_sma_20.iloc[-1]),
        "close":                safe(df["close"].iloc[-1]),
        # Series for divergence detection (signals.py) — last 30 candles
        "rsi_series":           rsi_series,
        "close_series":         close_series,
        # OBV series — last 30 values; trend computed per-pair in signals.py (#136)
        "obv_series":           obv_series,
        # BB width series (% of price) — last 10 values; squeeze release in signals.py (#137)
        "bb_width_series":      bb_width_series,
        # Candlestick reversal patterns — hammer, bullish_engulfing, doji_at_support (#184)
        "candlestick_patterns": candlestick_patterns,
    }


def detect_bb_squeeze_release(
    bb_width_series: list,
    threshold: float,
    lookback: int = 3,
    expansion_factor: float = 1.2,
    bb_mid: float = None,
    price: float = None,
) -> bool:
    """
    Detect Bollinger Band squeeze release — the candle where BB width expands sharply
    after a period of compression, with price breaking above the midband (upward only).

    Conditions (all must be true):
      1. The previous `lookback` candles all had BB width < threshold (squeeze)
      2. Current candle BB width > threshold × expansion_factor (20% above threshold)
      3. If price and bb_mid provided: price > bb_mid (upward breakout, not downward)

    Returns True if all conditions are met, False otherwise.
    """
    if not bb_width_series or len(bb_width_series) < lookback + 1:
        return False

    prior = bb_width_series[-(lookback + 1):-1]  # `lookback` candles before current
    current_width = bb_width_series[-1]

    if any(v is None for v in prior) or current_width is None:
        return False

    # All prior candles must be in squeeze
    if not all(w < threshold for w in prior):
        return False

    # Current candle must expand sharply above the threshold
    if current_width <= threshold * expansion_factor:
        return False

    # Only reward upward breakouts (price above midband)
    if price is not None and bb_mid is not None and price <= bb_mid:
        return False

    return True


def detect_rsi_divergence(prices: list, rsi_values: list, lookback: int = 20) -> dict:
    """
    Detect RSI divergence over the last `lookback` candles using a split-half approach.

    Split the lookback window into two halves:
      - First half  = earlier swing (index 0 .. mid-1)
      - Second half = recent swing  (index mid .. lookback-1)

    Find the local extremum (min for bullish, max for bearish) in each half, then
    compare price direction vs RSI direction at those two pivot points.

    Returns:
        {
            "bullish_regular":  bool,  # price LL + RSI HL → +2 BUY
            "bearish_regular":  bool,  # price HH + RSI LH → +2 SELL
            "hidden_bullish":   bool,  # price HL + RSI LL → +1 BUY (trend continuation)
        }

    All False if insufficient data or series contain None values.
    """
    result = {"bullish_regular": False, "bearish_regular": False, "hidden_bullish": False}

    if not prices or not rsi_values:
        return result

    n = min(lookback, len(prices), len(rsi_values))
    if n < 4:
        return result

    p   = prices[-n:]
    rsi = rsi_values[-n:]

    # Drop any None values — if any present, abort (incomplete series)
    if any(v is None for v in p) or any(v is None for v in rsi):
        return result

    mid = n // 2

    # ── Bullish divergence: compare price lows ──────────────────────────────
    first_half_prices = p[:mid]
    second_half_prices = p[mid:]
    first_half_rsi    = rsi[:mid]
    second_half_rsi   = rsi[mid:]

    idx1_low = first_half_prices.index(min(first_half_prices))
    idx2_low = second_half_prices.index(min(second_half_prices))

    price_low1 = first_half_prices[idx1_low]
    price_low2 = second_half_prices[idx2_low]
    rsi_low1   = first_half_rsi[idx1_low]
    rsi_low2   = second_half_rsi[idx2_low]

    # Regular bullish: price made lower low, RSI made higher low
    if price_low2 < price_low1 and rsi_low2 > rsi_low1:
        result["bullish_regular"] = True

    # Hidden bullish: price made higher low, RSI made lower low (trend continuation)
    if price_low2 > price_low1 and rsi_low2 < rsi_low1:
        result["hidden_bullish"] = True

    # ── Bearish divergence: compare price highs ─────────────────────────────
    idx1_high = first_half_prices.index(max(first_half_prices))
    idx2_high = second_half_prices.index(max(second_half_prices))

    price_high1 = first_half_prices[idx1_high]
    price_high2 = second_half_prices[idx2_high]
    rsi_high1   = first_half_rsi[idx1_high]
    rsi_high2   = second_half_rsi[idx2_high]

    # Regular bearish: price made higher high, RSI made lower high
    if price_high2 > price_high1 and rsi_high2 < rsi_high1:
        result["bearish_regular"] = True

    return result


def detect_candlestick_patterns(
    opens: list, highs: list, lows: list, closes: list, atr: Optional[float]
) -> dict:
    """
    Detect three high-probability candlestick reversal patterns on the most recent candle.

    Patterns:
      - hammer:           Lower wick > 2× body, upper wick < 30% of body,
                          bullish close (close > open), non-zero body.
                          Signals potential reversal after a downtrend.
      - bullish_engulfing: Current bullish candle body fully engulfs the prior bearish
                          candle body (current open < prior close AND current close > prior open).
                          Strong reversal signal requiring two candles.
      - doji_at_support:  Body (|close - open|) is less than 10% of ATR — extreme indecision.
                          The "at support" gate (price near BB lower band) is applied in
                          signals.py to award the score.

    All three are additive bonus signals — never enough alone to trigger a BUY.

    Returns dict with bool values; all False if fewer than 2 candles supplied.
    """
    empty = {"hammer": False, "bullish_engulfing": False, "doji_at_support": False}
    if len(closes) < 2:
        return empty

    c, o, h, l = closes[-1], opens[-1], highs[-1], lows[-1]
    pc, po = closes[-2], opens[-2]  # previous candle

    body       = abs(c - o)
    lower_wick = min(c, o) - l
    upper_wick = h - max(c, o)

    hammer = (
        body > 0
        and lower_wick > 2 * body
        and upper_wick < 0.3 * body
        and c > o  # bullish close
    )

    # Up candle fully engulfs prior down candle body
    bullish_engulfing = (
        c > o           # current candle is bullish
        and pc < po     # previous candle was bearish
        and o < pc      # current open below prior close (engulfs from below)
        and c > po      # current close above prior open (engulfs to above)
    )

    doji_at_support = (body < 0.1 * atr) if atr else False

    return {
        "hammer":            hammer,
        "bullish_engulfing": bullish_engulfing,
        "doji_at_support":   doji_at_support,
    }
