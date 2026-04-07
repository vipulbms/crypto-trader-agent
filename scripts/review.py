"""
2-week review script — run after your paper trading period to evaluate agent performance.

Usage:
    python scripts/review.py --mode paper
    python scripts/review.py --mode paper --days 14
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.reports.review_report import run_review  # noqa: E402

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="2-week trading agent review")
    parser.add_argument("--mode", choices=["paper", "live"], default="paper")
    parser.add_argument("--days", type=int, default=14, help="Number of days to review")
    args = parser.parse_args()
    run_review(args.mode, args.days)
