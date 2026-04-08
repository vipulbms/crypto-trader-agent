"""
Backtest entry point.

Runs the full production trading pipeline (signals → LLM → PaperBroker)
over historical OHLCV candles loaded from history/.

The only difference from live/paper mode is that candles come from files
via HistoricalFeed instead of a live WebSocket connection.

Usage:
    python tests/test_backtest.py
"""

import argparse
import asyncio
import logging
import os
import sys

import yaml
from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

from tests.backtest.loader import load_all_pairs
from src.exchange.historical_feed import HistoricalFeed
from main import run_agent


def main():
    parser = argparse.ArgumentParser(description="Run Kryptos backtest over historical candles")
    parser.add_argument(
        "--candles", type=int, default=0,
        help="Max number of candle steps to replay (0 = all available)",
    )
    parser.add_argument(
        "--start-date", type=str, default="",
        help="Start trading from this date, e.g. 2025-07-01 (uses prior candles for warmup)",
    )
    args = parser.parse_args()

    with open("config.yaml") as f:
        config = yaml.safe_load(f)

    pairs = [p["pair"] for p in config["trading"]["pairs"]]
    print(f"\nLoading candle data for {len(pairs)} pairs from history/...")
    pair_candles = load_all_pairs(pairs, history_dir="history")

    if not pair_candles:
        print("ERROR: No candle data loaded. Check history/ folder.")
        sys.exit(1)

    loaded = list(pair_candles.keys())
    skipped = [p for p in pairs if p not in pair_candles]
    print(f"Loaded: {len(loaded)} pairs  |  Skipped (no data): {len(skipped)}")
    if skipped:
        print(f"  Skipped: {', '.join(skipped)}")

    # Use isolated databases so the backtest does not touch paper_trading.db / audit.db
    config["storage"]["paper_db"] = "backtest_paper.db"
    config["storage"]["audit_db"] = "backtest_audit.db"

    # Disable trading hours filter — backtest must evaluate all candles regardless of time-of-day
    config["trading"]["allowed_trading_hours"]["enabled"] = False

    # Clean up old backtest databases and logs before starting
    print("Cleaning up previous backtest databases and logs...")
    data_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
    for db_file in [config["storage"]["paper_db"], config["storage"]["audit_db"]]:
        db_path = os.path.join(data_dir, db_file)
        if os.path.exists(db_path):
            os.remove(db_path)
            print(f"  Removed {db_file}")

    log_file = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backtest_run.log")
    if os.path.exists(log_file):
        try:
            open(log_file, "w").close()
            print(f"  Cleared backtest_run.log")
        except Exception as e:
            print(f"  Warning: failed to clear backtest_run.log - {e}")

    feed = HistoricalFeed(pair_candles, config, max_steps=args.candles, start_date=args.start_date)
    print(f"Starting backtest — {feed.total_tradeable} tradeable candle steps...\n")

    asyncio.run(run_agent(config, mode="paper", feed=feed))

    print("\nBacktest complete. Results are in backtest_paper.db and backtest_audit.db.")
    print("Run:  python kryptos.py report  (after pointing config to backtest DBs)")


if __name__ == "__main__":
    main()
