#!/usr/bin/env python3
"""
chart_trades.py — CLI wrapper for the Kryptos chart generator.

Delegates all rendering to src/reports/chart_generator.py.

Usage:
    python scripts/chart_trades.py                  # uses data/paper_trading.db
    python scripts/chart_trades.py --db data/backtest_paper.db
    python scripts/chart_trades.py --pair ETH/USD   # single pair only
    python scripts/chart_trades.py --window 200     # candles before/after trade
    python scripts/chart_trades.py --out charts/    # output directory

Charts are saved to charts/<PAIR>_<index>.png
"""

import argparse
import sys
from pathlib import Path

# Allow running from the project root with: python scripts/chart_trades.py
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.reports.chart_generator import generate_charts


def main() -> None:
    parser = argparse.ArgumentParser(description="Chart every closed trade with candles.")
    parser.add_argument("--db",     default="data/paper_trading.db",
                        help="SQLite DB to read trades from (default: data/paper_trading.db)")
    parser.add_argument("--pair",   default=None, help="Filter to one pair, e.g. ETH/USD")
    parser.add_argument("--window", type=int, default=80,
                        help="Candles of context before/after each trade (default: 80)")
    parser.add_argument("--history", default="history",
                        help="Directory with *_candle.json files (default: history/)")
    parser.add_argument("--out",    default="charts",
                        help="Output directory for charts (default: charts/)")
    args = parser.parse_args()

    if not Path(args.db).exists():
        sys.exit(f"ERROR: DB not found: {args.db}")

    generate_charts(
        db_path=args.db,
        out_dir=args.out,
        history_dir=args.history,
        pair_filter=args.pair,
        window=args.window,
    )


if __name__ == "__main__":
    main()
