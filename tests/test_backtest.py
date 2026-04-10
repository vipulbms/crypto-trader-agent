"""
Backtest entry point.

Runs the full production trading pipeline (signals → LLM → PaperBroker)
over historical OHLCV candles loaded from history/.

The only difference from live/paper mode is that candles come from files
via HistoricalFeed instead of a live WebSocket connection.

Usage:
    # Full pipeline (LLM required — ~2h for 7-day run)
    python tests/test_backtest.py

    # Fast signal-only — no LLM, runs in seconds
    python tests/test_backtest.py --no-llm
    python tests/test_backtest.py --no-llm --start-date 2025-12-25
    python tests/test_backtest.py --no-llm --start-date 2025-12-25 --pairs BTC/USD ETH/USD
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
from src.exchange.paper_broker import PaperBroker
from src.storage.database import get_connection, get_db_path, init_paper_db, init_audit_db
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
    parser.add_argument(
        "--no-llm", action="store_true",
        help="Skip LLM — use deterministic signal-only rule engine. Runs in seconds.",
    )
    parser.add_argument(
        "--pairs", nargs="+", default=[],
        help="(--no-llm only) Filter to specific pairs e.g. --pairs BTC/USD ETH/USD",
    )
    args = parser.parse_args()

    with open("config.yaml") as f:
        config = yaml.safe_load(f)

    # ── Fast path: signal-only, no LLM ────────────────────────────────────────
    if args.no_llm:
        from tests.test_backtest_fast import run_backtest, print_summary
        all_pairs = [p["pair"] for p in config["trading"]["pairs"]]
        print(f"\nLoading candle data for {len(all_pairs)} pairs from history/...")
        pair_candles = load_all_pairs(all_pairs, history_dir="history")
        if not pair_candles:
            print("ERROR: No candle data loaded. Check history/ folder.")
            sys.exit(1)
        loaded  = list(pair_candles.keys())
        skipped = [p for p in all_pairs if p not in pair_candles]
        print(f"Loaded: {len(loaded)} pairs  |  Skipped (no data): {len(skipped)}")
        if skipped:
            print(f"  Skipped: {', '.join(skipped)}")
        result = run_backtest(
            config=config,
            pair_candles=pair_candles,
            start_date=args.start_date,
            max_steps=args.candles,
            pairs_filter=args.pairs,
        )
        print_summary(result)
        return

    # ── Full path: LLM pipeline ────────────────────────────────────────────────
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
    for db_file in [config["storage"]["paper_db"], config["storage"]["audit_db"]]:
        db_path = get_db_path(db_file)
        if os.path.exists(db_path):
            os.remove(db_path)
            print(f"  Removed {db_file}")
        else:
            print(f"  {db_file} not found — skipping")

    log_file = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backtest_run.log")
    if os.path.exists(log_file):
        try:
            open(log_file, "w").close()
            print(f"  Cleared backtest_run.log")
        except Exception as e:
            print(f"  Warning: failed to clear backtest_run.log - {e}")

    # Validate clean state: re-init DB and assert no stale positions or wrong cash
    starting_balance = config.get("paper", {}).get("starting_balance_usd", 1000.0)
    init_paper_db(config["storage"]["paper_db"], starting_balance)
    init_audit_db(config["storage"]["audit_db"])
    conn = get_connection(config["storage"]["paper_db"])
    open_count = conn.execute("SELECT COUNT(*) FROM paper_positions WHERE status='open'").fetchone()[0]
    cash_usd = conn.execute("SELECT cash_usd FROM paper_wallet ORDER BY id DESC LIMIT 1").fetchone()[0]
    conn.close()
    if open_count != 0:
        print(f"ERROR: Backtest DB has {open_count} open positions after teardown — aborting.")
        sys.exit(1)
    if abs(cash_usd - starting_balance) > 0.01:
        print(f"ERROR: Backtest wallet cash ${cash_usd:.2f} != starting balance ${starting_balance:.2f} — aborting.")
        sys.exit(1)
    print(f"  Validated: 0 open positions, wallet=${cash_usd:.2f}")

    feed = HistoricalFeed(pair_candles, config, max_steps=args.candles, start_date=args.start_date)
    print(f"Starting backtest — {feed.total_tradeable} tradeable candle steps...\n")

    asyncio.run(run_agent(config, mode="paper", feed=feed))

    # Force mark-to-market close of all remaining open positions at last candle price (#127)
    paper_cfg = config.get("paper", {})
    broker = PaperBroker(
        paper_db=config["storage"]["paper_db"],
        slippage_pct=paper_cfg.get("slippage_pct", 0.05),
        maker_fee_pct=paper_cfg.get("maker_fee_pct", 0.16),
        config=config,
    )
    last_prices = {
        pair: feed.get_latest_price(pair)
        for pair in loaded
        if feed.get_latest_price(pair) is not None
    }
    force_closed = broker.force_close_all(last_prices)
    if force_closed:
        force_pnl = sum(t.get("pnl_usd", 0) for t in force_closed)
        print(
            f"\nForced closed {len(force_closed)} positions at backtest end (mark-to-market)"
            f"  |  P&L: ${force_pnl:+,.2f}"
        )

    print("\nBacktest complete. Results are in backtest_paper.db and backtest_audit.db.")
    print("Run:  python kryptos.py report  (after pointing config to backtest DBs)")


if __name__ == "__main__":
    main()
