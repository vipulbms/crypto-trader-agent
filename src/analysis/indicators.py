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

        # Add volume moving average to detect dry volume (dead zones)
        volume_sma_20 = df["volume"].rolling(window=20).mean()

    except Exception as e:
        logger.error("Indicator calculation error: %s", e)
        return None

    # macd_histogram_prev: second-to-last histogram value — used to detect a turn
    # (negative → positive crossover is a stronger signal than just being positive)
    hist_vals = macd_histogram.dropna()
    macd_histogram_prev = safe(hist_vals.iloc[-2]) if len(hist_vals) >= 2 else None

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
        "volume":               safe(df["volume"].iloc[-1]),
        "volume_sma_20":        safe(volume_sma_20.iloc[-1]),
        "close":                safe(df["close"].iloc[-1]),
    }
