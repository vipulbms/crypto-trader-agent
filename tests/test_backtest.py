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

    # Run with a specific persona applied (overrides config defaults)
    python tests/test_backtest.py --no-llm --persona high
    python tests/test_backtest.py --persona conservative --start-date 2025-12-01

    # Run all three personas sequentially and compare
    python tests/test_backtest.py --no-llm --all-personas

    # Write closed trade CSV (persona column included)
    python tests/test_backtest.py --no-llm --persona medium --csv
    python tests/test_backtest.py --no-llm --all-personas --csv --output results.csv
"""

import argparse
import asyncio
import csv
import copy
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


VALID_PERSONAS = {"conservative", "medium", "high"}
ALL_PERSONAS_ORDER = ["conservative", "medium", "high"]

# Columns written to the CSV (persona column is appended)
_TRADE_COLUMNS = [
    "id", "opened_at", "closed_at", "pair", "side",
    "entry_price", "exit_price", "volume", "usd_invested",
    "pnl_usd", "pnl_pct", "exit_reason", "hold_duration_secs",
    "fee_usd", "stop_loss_pct", "take_profit_pct", "persona",
]


def apply_persona(config: dict, persona_name: str) -> None:
    """Overlay persona config block onto trading/risk/signal config sections.

    Mutates *config* in place.  Raises ValueError if persona is unknown.
    """
    personas = config.get("personas", {})
    if persona_name not in personas:
        raise ValueError(
            f"Unknown persona '{persona_name}'. "
            f"Available: {sorted(personas.keys())}"
        )
    p = personas[persona_name]
    # Mark active persona so CycleContext / RiskManager see it
    config.setdefault("agent", {})["persona"] = persona_name

    # Signal gate
    if "buy_min_score" in p:
        config.setdefault("signals", {})["buy_min_score"] = p["buy_min_score"]

    # Risk limits
    risk = config.setdefault("risk", {})
    if "max_open_positions" in p:
        risk["max_open_positions"] = p["max_open_positions"]
    if "max_position_pct" in p:
        risk["max_position_pct"] = p["max_position_pct"]
    if "min_profit_floor_pct" in p:
        risk["min_profit_floor_pct"] = p["min_profit_floor_pct"]

    # RSI overbought veto
    if "rsi_overbought_veto" in p:
        config.setdefault("exit_timing", {})["rsi_exit_overbought"] = p["rsi_overbought_veto"]

    # Volume bypass (QSA)
    if "volume_bypass_enabled" in p:
        config.setdefault("qsa", {}).setdefault("volume_floor", {})["bypass_enabled"] = (
            p["volume_bypass_enabled"]
        )


def _read_trades_from_fast_db(persona_label: str) -> list[dict]:
    """Read closed trades from the fast-backtest paper DB and tag with persona_label."""
    db_path = get_db_path("backtest_fast_paper.db")
    if not os.path.exists(db_path):
        return []
    conn = get_connection("backtest_fast_paper.db")
    try:
        rows = conn.execute(
            "SELECT " + ", ".join(c for c in _TRADE_COLUMNS if c != "persona")
            + " FROM paper_trades ORDER BY id"
        ).fetchall()
    finally:
        conn.close()
    cols = [c for c in _TRADE_COLUMNS if c != "persona"]
    result = []
    for row in rows:
        d = dict(zip(cols, row))
        d["persona"] = persona_label
        result.append(d)
    return result


def _write_csv(trades: list[dict], output_path: str) -> None:
    """Write trade rows to CSV at output_path."""
    with open(output_path, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=_TRADE_COLUMNS)
        writer.writeheader()
        writer.writerows(trades)
    print(f"\n[CSV] {len(trades)} trades written to {output_path}")


def _print_persona_comparison(results: list[tuple[str, dict]]) -> None:
    """Print a side-by-side comparison table for multiple persona runs."""
    print("\n" + "═" * 90)
    print("  PERSONA COMPARISON")
    print("═" * 90)
    header = f"  {'Persona':<14} {'Start $':>9} {'End $':>9} {'Net P&L':>10} {'Net%':>8} {'Cycles':>8} {'Buys':>6}"
    print(header)
    print("  " + "-" * 84)
    for persona, res in results:
        start = res["starting_balance"]
        end   = res["final_balance"]
        net   = end - start
        pct   = net / start * 100 if start else 0.0
        cycles = res["cycles"]
        buys  = sum(s.get("buys", 0) for s in res["stats"].values())
        print(f"  {persona.upper():<14} {start:>9,.2f} {end:>9,.2f} {net:>+10,.2f} {pct:>+7.2f}% {cycles:>8} {buys:>6}")
    print()


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
    parser.add_argument(
        "--persona", type=str, default=None,
        choices=sorted(VALID_PERSONAS),
        help="Apply persona config overrides before running (conservative | medium | high)",
    )
    parser.add_argument(
        "--all-personas", action="store_true",
        help="(--no-llm only) Run backtest for all three personas sequentially and compare",
    )
    parser.add_argument(
        "--csv", action="store_true",
        help="Write closed trade records to a CSV file after the run",
    )
    parser.add_argument(
        "--output", type=str, default="backtest_results.csv",
        help="CSV output file path (default: backtest_results.csv)",
    )
    args = parser.parse_args()

    with open("config.yaml") as f:
        config = yaml.safe_load(f)

    if args.persona:
        apply_persona(config, args.persona)
        print(f"\n[PERSONA] Using persona: {args.persona.upper()}")

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

        # ── All-personas comparison mode ──────────────────────────────────────
        if args.all_personas:
            with open("config.yaml") as _f:
                base_config = yaml.safe_load(_f)
            all_results: list[tuple[str, dict]] = []
            all_trades:  list[dict] = []

            for persona in ALL_PERSONAS_ORDER:
                cfg = copy.deepcopy(base_config)
                apply_persona(cfg, persona)
                print(f"\n{'─'*60}")
                print(f"  Running persona: {persona.upper()}")
                print(f"{'─'*60}")
                res = run_backtest(
                    config=cfg,
                    pair_candles=pair_candles,
                    start_date=args.start_date,
                    max_steps=args.candles,
                    pairs_filter=args.pairs,
                )
                print_summary(res)
                all_results.append((persona, res))
                if args.csv:
                    all_trades.extend(_read_trades_from_fast_db(persona))

            _print_persona_comparison(all_results)
            if args.csv:
                _write_csv(all_trades, args.output)
            return

        # ── Single-persona (or no-persona) fast path ──────────────────────────
        result = run_backtest(
            config=config,
            pair_candles=pair_candles,
            start_date=args.start_date,
            max_steps=args.candles,
            pairs_filter=args.pairs,
        )
        print_summary(result)
        if args.csv:
            persona_label = args.persona or ""
            trades = _read_trades_from_fast_db(persona_label)
            _write_csv(trades, args.output)
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
