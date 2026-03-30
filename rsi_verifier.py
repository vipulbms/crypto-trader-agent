"""
rsi_verifier.py — Fetch live RSI from Kraken public API for monitored pairs.

Usage:
    python3.11 rsi_verifier.py
    python3.11 rsi_verifier.py --interval 60    # 1h candles (default)
    python3.11 rsi_verifier.py --interval 15    # 15m candles
    python3.11 rsi_verifier.py --threshold 70   # flag RSI >= 70 (default)
"""

import argparse
import os
import yaml
import requests
import pandas as pd
import ta.momentum


def load_pairs_from_config(config_path: str = "config.yaml") -> list:
    """Load (rest_name, display_name) pairs from config.yaml."""
    with open(config_path) as f:
        cfg = yaml.safe_load(f)
    pairs = []
    for p in cfg.get("trading", {}).get("pairs", []):
        rest_name = p.get("rest_name", p["pair"].replace("/", ""))
        pairs.append((rest_name, p["pair"]))
    return pairs


_CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.yaml")
PAIRS = load_pairs_from_config(_CONFIG_PATH)


def fetch_rsi(kraken_pair: str, interval: int = 60, window: int = 14):
    """Fetch OHLC from Kraken and return (latest_rsi, latest_price)."""
    resp = requests.get(
        "https://api.kraken.com/0/public/OHLC",
        params={"pair": kraken_pair, "interval": interval},
        timeout=10,
    )
    data = resp.json()
    if data.get("error"):
        raise ValueError(f"Kraken API error: {data['error']}")
    result_key = [k for k in data["result"] if k != "last"][0]
    candles = data["result"][result_key]
    df = pd.DataFrame(
        candles,
        columns=["time", "open", "high", "low", "close", "vwap", "volume", "count"],
    )
    df["close"] = df["close"].astype(float)
    rsi_series = ta.momentum.RSIIndicator(close=df["close"], window=window).rsi()
    return rsi_series.iloc[-1], df["close"].iloc[-1]


def main():
    parser = argparse.ArgumentParser(description="Live RSI checker via Kraken public API")
    parser.add_argument("--interval",  type=int, default=60,  help="Candle interval in minutes (default: 60)")
    parser.add_argument("--window",    type=int, default=14,  help="RSI window (default: 14)")
    parser.add_argument("--threshold", type=float, default=70.0, help="Overbought threshold (default: 70)")
    args = parser.parse_args()

    results = []
    for kraken_pair, display_pair in PAIRS:
        try:
            rsi, price = fetch_rsi(kraken_pair, args.interval, args.window)
            results.append((display_pair, rsi, price))
        except Exception as e:
            print(f"  {display_pair}: error — {e}")

    results.sort(key=lambda x: x[1], reverse=True)

    print(f"\nLive RSI ({args.window}-period, {args.interval}m candles) — Kraken")
    print(f"{'Pair':<12} {'RSI':>8} {'Price (USD)':>14}  Status")
    print("-" * 58)
    for pair, rsi, price in results:
        if rsi >= args.threshold:
            status = f"OVERBOUGHT  *** RSI >= {args.threshold:.0f}"
        elif rsi >= 60:
            status = "Elevated    (60-69)"
        else:
            status = "Normal      (< 60)"
        print(f"{pair:<12} {rsi:>8.1f} {price:>14.4f}  {status}")

    over_threshold = [(p, r, pr) for p, r, pr in results if r >= args.threshold]
    print(f"\n--- Pairs with RSI >= {args.threshold:.0f} ---")
    if over_threshold:
        for i, (pair, rsi, price) in enumerate(over_threshold, 1):
            print(f"  {i}. {pair}: RSI={rsi:.1f} @ ${price:.4f}")
    else:
        print(f"  None currently above RSI {args.threshold:.0f}")


if __name__ == "__main__":
    main()
