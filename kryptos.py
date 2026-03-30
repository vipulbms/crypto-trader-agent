#!/usr/bin/env python3
"""
kryptos.py — Command-line interface for the Kryptos AI crypto trading agent.

Usage:
    Interactive REPL (natural language):
        python kryptos.py
        python kryptos.py --paper
        python kryptos.py --live

    Single command (non-interactive):
        python kryptos.py "show me today's report"
        python kryptos.py "start paper trading"
        python kryptos.py "what's my win rate over the last 7 days?"

    Direct subcommands (bypass NL parsing):
        python kryptos.py start [--paper|--live]
        python kryptos.py stop
        python kryptos.py status
        python kryptos.py report [--days N] [--pair BTC/USD] [--mode paper|live]
        python kryptos.py decisions [--days N] [--pair BTC/USD]
        python kryptos.py metrics [--days N]
        python kryptos.py log [--lines N]
"""

import argparse
import logging
import os
import sys

import yaml

# Silence noisy loggers so the REPL stays clean
logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logging.getLogger("httpx").setLevel(logging.ERROR)
logging.getLogger("ollama").setLevel(logging.ERROR)

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))


# ──────────────────────────────────────────────────────────────
# Config loader
# ──────────────────────────────────────────────────────────────

def _load_config() -> dict:
    cfg_path = os.path.join(_BASE_DIR, "config.yaml")
    if not os.path.exists(cfg_path):
        return {}
    with open(cfg_path, "r") as f:
        return yaml.safe_load(f)


# ──────────────────────────────────────────────────────────────
# Readline history (REPL)
# ──────────────────────────────────────────────────────────────

def _setup_readline() -> None:
    try:
        import readline
        history_path = os.path.join(_BASE_DIR, "data", ".kryptos_history")
        os.makedirs(os.path.dirname(history_path), exist_ok=True)
        try:
            readline.read_history_file(history_path)
        except FileNotFoundError:
            pass
        import atexit
        atexit.register(readline.write_history_file, history_path)
        readline.set_history_length(500)
    except ImportError:
        pass


# ──────────────────────────────────────────────────────────────
# Parser factory
# ──────────────────────────────────────────────────────────────

def _make_nl_parser(config: dict):
    from src.cli.nl_parser import NLParser
    llm_cfg   = config.get("llm", {})
    model     = llm_cfg.get("model", "qwen2.5:14b")
    base_url  = llm_cfg.get("base_url", "http://localhost:11434")
    return NLParser(model=model, base_url=base_url)


# ──────────────────────────────────────────────────────────────
# REPL
# ──────────────────────────────────────────────────────────────

def run_repl(config: dict, default_mode: str = "paper") -> None:
    from src.cli import commands, display as d
    from src.cli.nl_parser import NLParser

    _setup_readline()
    parser = _make_nl_parser(config)

    d.print_welcome(default_mode)

    # Inject default mode into every intent if not specified
    def _with_mode(intent_obj: dict) -> dict:
        p = intent_obj.get("params", {})
        if not p.get("mode"):
            p["mode"] = default_mode
        intent_obj["params"] = p
        return intent_obj

    while True:
        try:
            text = input("\n[Kryptos] ").strip()
        except (EOFError, KeyboardInterrupt):
            d.print_info("\nGoodbye from Kryptos.")
            break

        if not text:
            continue

        intent_obj = _with_mode(parser.parse(text))

        # Show which intent was detected (dim, only when NL was used & not a direct command)
        if intent_obj.get("source") == "keyword" and len(text.split()) > 1:
            d.console.print(
                f"  [dim]→ intent: {intent_obj['intent']}[/dim]",
                highlight=False,
            )

        keep_running = commands.dispatch(intent_obj, config)
        if not keep_running:
            break


# ──────────────────────────────────────────────────────────────
# Single natural-language command (non-interactive)
# ──────────────────────────────────────────────────────────────

def run_single_command(text: str, config: dict, default_mode: str = "paper") -> None:
    from src.cli import commands
    from src.cli.nl_parser import NLParser

    parser     = _make_nl_parser(config)
    intent_obj = parser.parse(text)
    p = intent_obj.get("params", {})
    if not p.get("mode"):
        p["mode"] = default_mode
    intent_obj["params"] = p
    commands.dispatch(intent_obj, config)


# ──────────────────────────────────────────────────────────────
# Direct subcommand handlers (bypass NL parsing)
# ──────────────────────────────────────────────────────────────

def run_direct(subcommand: str, args: argparse.Namespace, config: dict) -> None:
    from src.cli import commands, display as d

    mode = "live" if getattr(args, "live", False) else getattr(args, "mode", "paper")
    params = {
        "mode": mode,
        "pair": getattr(args, "pair", None),
        "days": getattr(args, "days", None),
        "count": getattr(args, "count", None),
        "lines": getattr(args, "lines", 30),
        "detail": "detailed" if getattr(args, "detailed", False) else "summary",
    }

    mapping = {
        "start":     commands.cmd_start,
        "stop":      lambda p: commands.cmd_stop(p),
        "status":    lambda p: commands.cmd_status(p, config),
        "schedule":  lambda p: commands.cmd_next_schedule(p, config),
        "report":    lambda p: commands.cmd_view_report(p, config),
        "trades":    lambda p: commands.cmd_trade_details(p, config),
        "decisions": lambda p: commands.cmd_llm_decisions(p, config),
        "metrics":   lambda p: commands.cmd_win_rate(p, config),
        "summary":   lambda p: commands.cmd_daily_summary(p, config),
        "positions": lambda p: commands.cmd_open_positions(p, config),
        "log":       lambda p: commands.cmd_tail_log(p),
        "help":      lambda p: commands.cmd_help(p),
    }

    fn = mapping.get(subcommand)
    if fn:
        fn(params)
    else:
        d.print_error(f"Unknown subcommand: '{subcommand}'")
        d.print_help()


# ──────────────────────────────────────────────────────────────
# Argument parser
# ──────────────────────────────────────────────────────────────

def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="kryptos",
        description="Kryptos — AI crypto trading agent CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python kryptos.py                          # Interactive REPL
  python kryptos.py --live                   # REPL defaulting to live mode
  python kryptos.py "show last 5 BTC trades" # One-shot NL query
  python kryptos.py start --paper            # Direct: start agent in paper mode
  python kryptos.py stop                     # Direct: stop the agent
  python kryptos.py status                   # Direct: check agent status
  python kryptos.py report --days 7 --pair BTC/USD
  python kryptos.py decisions --days 14 --detailed
  python kryptos.py metrics --days 30
  python kryptos.py log --lines 50
        """,
    )

    # Global mode flags
    mode_grp = p.add_mutually_exclusive_group()
    mode_grp.add_argument("--paper", action="store_true", default=False, help="Default to paper mode")
    mode_grp.add_argument("--live",  action="store_true", default=False, help="Default to live mode")

    # Subcommands (positional — optional)
    subparsers = p.add_subparsers(dest="subcommand", metavar="SUBCOMMAND")

    # start
    sp_start = subparsers.add_parser("start", help="Start the trading agent")
    sg = sp_start.add_mutually_exclusive_group()
    sg.add_argument("--paper", dest="paper_flag", action="store_true", help="Paper mode")
    sg.add_argument("--live",  dest="live_flag",  action="store_true", help="Live mode")

    # stop
    subparsers.add_parser("stop", help="Stop the running agent")

    # status
    subparsers.add_parser("status", help="Show agent status")

    # schedule
    subparsers.add_parser("schedule", help="Show next cycle schedule")

    # report
    sp_rep = subparsers.add_parser("report", help="View trade history report")
    sp_rep.add_argument("--days",     type=int, default=30,    help="Number of days to look back (default: 30)")
    sp_rep.add_argument("--pair",     type=str, default=None,  help="Filter by pair e.g. BTC/USD")
    sp_rep.add_argument("--count",    type=int, default=50,    help="Max records to show (default: 50)")
    sp_rep.add_argument("--mode",     type=str, default="paper", choices=["paper", "live"])
    sp_rep.add_argument("--detailed", action="store_true",     help="Include LLM reasoning column")

    # trades
    sp_tr = subparsers.add_parser("trades", help="Show trade details with LLM reasoning")
    sp_tr.add_argument("--days",  type=int, default=7)
    sp_tr.add_argument("--pair",  type=str, default=None)
    sp_tr.add_argument("--count", type=int, default=5)
    sp_tr.add_argument("--mode",  type=str, default="paper", choices=["paper", "live"])

    # decisions
    sp_dec = subparsers.add_parser("decisions", help="Review LLM decisions and reasoning")
    sp_dec.add_argument("--days",     type=int, default=7)
    sp_dec.add_argument("--pair",     type=str, default=None)
    sp_dec.add_argument("--type",     dest="decision_type", type=str, default=None,
                        choices=["BUY", "SELL", "HOLD"])
    sp_dec.add_argument("--count",    type=int, default=20)
    sp_dec.add_argument("--mode",     type=str, default="paper", choices=["paper", "live"])
    sp_dec.add_argument("--detailed", action="store_true", help="Show full LLM output for each decision")

    # metrics
    sp_met = subparsers.add_parser("metrics", help="Performance metrics and win rate")
    sp_met.add_argument("--days", type=int, default=14)
    sp_met.add_argument("--mode", type=str, default="paper", choices=["paper", "live"])

    # summary
    sp_sum = subparsers.add_parser("summary", help="Daily P&L summary")
    sp_sum.add_argument("--date", type=str, default=None, help="Date YYYY-MM-DD (default: today)")
    sp_sum.add_argument("--mode", type=str, default="paper", choices=["paper", "live"])

    # positions
    sp_pos = subparsers.add_parser("positions", help="Show open positions")
    sp_pos.add_argument("--mode", type=str, default="paper", choices=["paper", "live"])

    # log
    sp_log = subparsers.add_parser("log", help="Show recent agent log")
    sp_log.add_argument("--lines", type=int, default=30, help="Number of log lines to show (default: 30)")

    # help is built-in
    subparsers.add_parser("help", help="Show available commands")

    # Free-text positional (natural language query, single-shot mode)
    p.add_argument("query", nargs="?", default=None, help="Natural language query (non-interactive)")

    return p


# ──────────────────────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────────────────────

def main() -> None:
    arg_parser = build_arg_parser()
    args       = arg_parser.parse_args()
    config     = _load_config()

    # Resolve default mode
    default_mode = "live" if getattr(args, "live", False) else "paper"

    # If a direct subcommand was given (start/stop/status etc.)
    if args.subcommand:
        # The 'start' subcommand has its own --paper/--live flags
        if args.subcommand == "start":
            if getattr(args, "live_flag", False):
                args.mode = "live"
            else:
                args.mode = "paper"
        run_direct(args.subcommand, args, config)
        return

    # If a free-text query was passed as a positional argument
    if args.query:
        run_single_command(args.query, config, default_mode)
        return

    # Otherwise: interactive REPL
    run_repl(config, default_mode)


if __name__ == "__main__":
    main()
