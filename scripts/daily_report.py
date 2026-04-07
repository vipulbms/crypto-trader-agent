"""
Daily report — run manually or schedule via cron/launchd.

Usage:
    python scripts/daily_report.py --mode paper
    python scripts/daily_report.py --mode paper --days-ago 1
    python scripts/daily_report.py --mode live
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.reports.daily_report import run_daily_report  # noqa: E402

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Daily trading report")
    parser.add_argument("--mode", choices=["paper", "live"], default="paper")
    parser.add_argument("--days-ago", type=int, default=0, help="0=today, 1=yesterday, etc.")
    args = parser.parse_args()
    run_daily_report(args.mode, args.days_ago)
