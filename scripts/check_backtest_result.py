#!/usr/bin/env python3
"""
Parse fast backtest stdout and exit non-zero if overall win rate is below threshold.

Usage:
  python scripts/check_backtest_result.py --input backtest_output.txt --min-win-rate 45
  python tests/test_backtest.py --no-llm | python scripts/check_backtest_result.py --min-win-rate 45
"""

import argparse
import re
import sys


def parse_win_rate(text: str) -> int | None:
    """Extract overall win rate from the TOTAL summary line of fast backtest output.

    The fast backtest print_summary() emits a line like:
        TOTAL              128    72   41      9           6              56%
    Win rate is always the last token on the TOTAL line.
    """
    for line in text.splitlines():
        if "TOTAL" in line:
            m = re.search(r"(\d+)%\s*$", line)
            if m:
                return int(m.group(1))
    return None


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Check fast backtest win rate against a minimum threshold."
    )
    parser.add_argument(
        "--input", "-i",
        metavar="FILE",
        help="File containing backtest output (default: read from stdin)",
    )
    parser.add_argument(
        "--min-win-rate", "-m",
        type=int,
        default=45,
        metavar="PCT",
        help="Minimum acceptable overall win rate %% (default: 45)",
    )
    args = parser.parse_args()

    if args.input:
        try:
            with open(args.input) as f:
                text = f.read()
        except OSError as e:
            print(f"ERROR: Cannot read input file: {e}", file=sys.stderr)
            sys.exit(2)
    else:
        text = sys.stdin.read()

    win_rate = parse_win_rate(text)

    if win_rate is None:
        print(
            "ERROR: Could not find overall win rate in backtest output.\n"
            "Expected a line containing 'TOTAL' ending with 'XX%'.",
            file=sys.stderr,
        )
        sys.exit(2)

    threshold = args.min_win_rate
    if win_rate >= threshold:
        print(f"✓  Win rate {win_rate}% ≥ {threshold}% threshold — backtest PASSED")
        sys.exit(0)
    else:
        print(f"✗  Win rate {win_rate}% < {threshold}% threshold — backtest FAILED")
        sys.exit(1)


if __name__ == "__main__":
    main()
