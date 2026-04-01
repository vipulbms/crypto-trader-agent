"""
Backtest entry point.

Usage:
    python tests/test_backtest.py

Runs the full signal pipeline over historical OHLCV data from history/,
prints a formatted performance report, and lists any bugs encountered.
"""

import logging
import os
import sys
import yaml

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Suppress timing/info noise from indicators/signals in backtest output
logging.basicConfig(level=logging.WARNING)
logging.getLogger("timing").setLevel(logging.WARNING)
logging.getLogger("backtest").setLevel(logging.DEBUG)

from tests.backtest.loader import load_all_pairs, PAIR_FILE_MAP
from tests.backtest.runner import run_backtest
from tests.backtest.report import generate_report


def main():
    with open("config.yaml") as f:
        config = yaml.safe_load(f)

    pairs = [p["pair"] for p in config["trading"]["pairs"]]
    print(f"\nLoading candle data for {len(pairs)} pairs...")

    bugs_found = []

    # ── Load all pairs ───────────────────────────────────────────────
    pair_candles = load_all_pairs(pairs, history_dir="history")

    # Check for missing pairs
    loaded_pairs = set(pair_candles.keys())
    for pair in pairs:
        if pair not in loaded_pairs:
            bugs_found.append(
                f"[DATA] {pair}: history file not found or empty — "
                f"file expected: {PAIR_FILE_MAP.get(pair, ('UNKNOWN',))[0]}"
            )

    if not pair_candles:
        print("ERROR: No candle data loaded. Check history/ folder.")
        sys.exit(1)

    # ── Run backtest ─────────────────────────────────────────────────
    starting_balance = config.get("paper", {}).get("starting_balance_usd", 1000.0)
    print(f"Running backtest on {len(pair_candles)} pairs with ${starting_balance:.0f} starting balance...")
    print("(This may take 30–60 seconds — computing indicators at every candle step)\n")

    results = run_backtest(pair_candles, config, starting_balance=starting_balance)

    # ── Data coverage warning ────────────────────────────────────────
    tradeable_hours = results["tradeable_steps"] * 15 / 60
    if tradeable_hours < 72:
        bugs_found.append(
            f"[DATA] Only {tradeable_hours:.1f} hours of tradeable data available "
            f"(after {results['min_candles']}-candle warmup). "
            f"Kraken OHLC API returns max 720 candles per call — need pagination for 12 months. "
            f"Run `python scripts/download_history.py` to fetch multi-month data."
        )

    # ── Signal quality checks ────────────────────────────────────────
    if results["buy_proposals"] == 0:
        bugs_found.append(
            "[SIGNAL] Zero buy proposals generated across all pairs and candles. "
            "Signal thresholds may be too strict for current market conditions."
        )

    if results["buy_proposals"] > 0 and len(results["trades"]) == 0:
        bugs_found.append(
            "[BROKER] Buys were proposed but no trades recorded — "
            "check place_order() and BacktestBroker state."
        )

    # ── Known bugs discovered while building this pipeline ───────────
    known_bugs = [
        "[BUG-1] AVAX/USD history filename is 'AVAXSD_candle.json' (missing 'U'). "
        "Should be 'AVAXUSD_candle.json'. This is a download-time typo.",

        "[BUG-2] indicators.py returns keys 'ema_20' and 'ema_50' regardless of the "
        "configured ema_fast/ema_slow window values. Config sets ema_slow=200 but the "
        "returned key is 'ema_50'. This is a misleading label (not functional since "
        "signals.py reads the same key 'ema_50'), but will cause confusion if ema_slow "
        "is ever renamed or if someone inspects the indicator output directly.",

        "[BUG-3] Kraken OHLC REST API caps at 720 candles per request. The 'since' "
        "parameter (epoch 1680220800 = April 2023) was provided but the API returned only "
        "the most recent 720 candles (March 24–April 1, 2026). To get 12 months of data "
        "you must paginate: after each request, pass result['last'] as the next 'since' "
        "value and loop until you reach the target start date.",

        "[BUG-4] CLAUDE.md pairs table lists INJ/USD TP as 16%, but config.yaml says 20%. "
        "The config is authoritative — CLAUDE.md is stale.",

        "[BUG-5] SL/TP in the live main loop (main.py) checks price only once per 30-minute "
        "cycle, not on every WebSocket tick. A flash crash could blow through SL between "
        "cycles without triggering it. PaperBroker and BacktestBroker both have the same "
        "limitation — SL price is used as exit_price even if actual low was worse.",
    ]

    # ── Print report ─────────────────────────────────────────────────
    report = generate_report(results, config)
    print(report)

    # ── Print bugs ───────────────────────────────────────────────────
    all_bugs = known_bugs + bugs_found
    print("═" * 70)
    print("  BUGS IDENTIFIED")
    print("═" * 70)
    for i, bug in enumerate(all_bugs, 1):
        print(f"\n  [{i}] {bug}")
    print("\n" + "═" * 70 + "\n")


if __name__ == "__main__":
    main()
