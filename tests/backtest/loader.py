"""
Backtest data loader.
Reads Kraken OHLCV JSON files from the history/ folder and converts them
into the same candle dict format that compute_indicators() expects.

Candle format returned:
  {"time": int, "open": float, "high": float, "low": float,
   "close": float, "volume": float}

Known file quirks:
  - AVAX/USD uses 'AVAXSD_candle.json' (filename typo — missing 'U')
  - BTC/USD inner key is 'XXBTZUSD' (Kraken legacy naming)
  - ETH/USD inner key is 'XETHZUSD'
  - LTC/USD inner key is 'XLTCZUSD'
  - XRP/USD inner key is 'XXRPZUSD'
  - DOGE/USD file is 'XDGUSD_candle.json' / inner key 'XDGUSD'
"""

import json
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

# Maps display pair → (filename, inner_result_key)
# Built by inspecting every file; inner key is the first non-'last' key in result.
PAIR_FILE_MAP = {
    "BTC/USD":    ("XBTUSD_candle.json",    "XBTUSD"),
    "ETH/USD":    ("ETHUSD_candle.json",    "ETHUSD"),
    "BNB/USD":    ("BNBUSD_candle.json",    "BNBUSD"),
    "SOL/USD":    ("SOLUSD_candle.json",    "SOLUSD"),
    "XRP/USD":    ("XRPUSD_candle.json",    "XRPUSD"),
    "TRX/USD":    ("TRXUSD_candle.json",    "TRXUSD"),
    "DOGE/USD":   ("XDGUSD_candle.json",    "XDGUSD"),
    "ADA/USD":    ("ADAUSD_candle.json",    "ADAUSD"),
    "LTC/USD":    ("LTCUSD_candle.json",    "LTCUSD"),
    "RAILS/USD":  ("RAILSUSD_candle.json",  "RAILSUSD"),
    "AVAX/USD":   ("AVAXUSD_candle.json",   "AVAXUSD"),
    "SUI/USD":    ("SUIUSD_candle.json",    "SUIUSD"),
    "HYPE/USD":   ("HYPEUSD_candle.json",   "HYPEUSD"),
    "UNI/USD":    ("UNIUSD_candle.json",    "UNIUSD"),
    "INJ/USD":    ("INJUSD_candle.json",    "INJUSD"),
    # New pairs added (#145–#154)
    "WIF/USD":    ("WIFUSD_candle.json",    "WIFUSD"),
    "TON/USD":    ("TONUSD_candle.json",    "TONUSD"),
    "OP/USD":     ("OPUSD_candle.json",     "OPUSD"),
    "ARB/USD":    ("ARBUSD_candle.json",    "ARBUSD"),
    "JUP/USD":    ("JUPUSD_candle.json",    "JUPUSD"),
    "PEPE/USD":   ("PEPEUSD_candle.json",   "PEPEUSD"),
    "TIA/USD":    ("TIAUSD_candle.json",    "TIAUSD"),
    "RENDER/USD": ("RENDERUSD_candle.json", "RENDERUSD"),
    "FET/USD":    ("FETUSD_candle.json",    "FETUSD"),
    "STX/USD":    ("STXUSD_candle.json",    "STXUSD"),
    # New pairs added (#186-#188)
    "PENDLE/USD": ("PENDLEUSD_candle.json", "PENDLEUSD"),
    "ONDO/USD":   ("ONDOUSD_candle.json",   "ONDOUSD"),
    "BONK/USD":   ("BONKUSD_candle.json",   "BONKUSD"),
    # New pair added
    "MOVR/USD":   ("MOVRUSD_candle.json",   "MOVRUSD"),
}


def _to_candle(raw: list) -> dict:
    """
    Convert raw Kraken tick array to candle dict.
    Input: [time, open, high, low, close, vwap, volume, count]
    """
    return {
        "time":   int(raw[0]),
        "open":   float(raw[1]),
        "high":   float(raw[2]),
        "low":    float(raw[3]),
        "close":  float(raw[4]),
        "volume": float(raw[6]),   # index 6 = volume (skip vwap at 5)
    }


def load_pair_candles(pair: str, history_dir: str = "history") -> Optional[list]:
    """
    Load all candles for a pair. Returns list of candle dicts sorted by time,
    or None if the file is missing or malformed.
    """
    if pair not in PAIR_FILE_MAP:
        logger.warning("No file mapping for pair %s", pair)
        return None

    filename, inner_key = PAIR_FILE_MAP[pair]
    path = os.path.join(history_dir, filename)

    if not os.path.exists(path):
        logger.warning("History file not found: %s (pair=%s)", path, pair)
        return None

    try:
        with open(path) as f:
            data = json.load(f)
    except Exception as e:
        logger.error("Failed to load %s: %s", path, e)
        return None

    if isinstance(data, list):
        raw_candles = data
    else:
        raw_candles = data.get("result", {}).get(inner_key)
    if not raw_candles:
        logger.error("No candle data at result[%r] in %s", inner_key, path)
        return None

    candles = [_to_candle(row) for row in raw_candles]
    candles.sort(key=lambda c: c["time"])
    logger.debug("Loaded %d candles for %s from %s", len(candles), pair, filename)
    return candles


def load_all_pairs(pairs: list, history_dir: str = "history") -> dict:
    """
    Load candles for all pairs. Returns {pair: [candle, ...]} for successfully
    loaded pairs. Pairs with missing/empty data are excluded and logged.
    """
    result = {}
    for pair in pairs:
        candles = load_pair_candles(pair, history_dir)
        if candles:
            result[pair] = candles
        else:
            logger.warning("Skipping %s — no candle data", pair)
    return result
