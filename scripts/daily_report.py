"""
Daily report — run manually or schedule via cron/launchd.
Queries audit.db and paper_trading.db to print a daily P&L summary.

Usage:
    python scripts/daily_report.py --mode paper
    python scripts/daily_report.py --mode live
"""

import argparse
import os
import sqlite3
import sys
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import yaml
from src.storage.database import get_connection
from src.storage.audit_logger import AuditLogger


def load_config() -> dict:
    cfg_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.yaml")
    with open(cfg_path) as f:
        return yaml.safe_load(f)


def print_divider(char="─", width=60):
    print(char * width)


def run_daily_report(mode: str, day_offset: int = 0) -> None:
    config = load_config()
    storage = config.get("storage", {})
    audit_db = storage.get("audit_db", "audit.db")

    audit = AuditLogger(audit_db=audit_db, mode=mode)

    target_date = (datetime.now(timezone.utc) - timedelta(days=day_offset)).date()
    date_str = str(target_date)

    print("\n" + "═" * 60)
    mode_label = "📄 PAPER TRADING" if mode == "paper" else "💰 LIVE TRADING"
    print(f"  {mode_label} — Daily Report: {date_str}")
    print("═" * 60)

    # ── Balance snapshots for the day ─────────────────────────
    conn = get_connection(audit_db)
    snapshots = conn.execute(
        """SELECT total_usd, snapshot_at FROM audit_balance_snapshots
           WHERE mode=? AND DATE(snapshot_at)=?
           ORDER BY snapshot_at ASC""",
        (mode, date_str),
    ).fetchall()

    if snapshots:
        start_bal = float(snapshots[0]["total_usd"])
        end_bal   = float(snapshots[-1]["total_usd"])
        day_pnl   = end_bal - start_bal
        day_pnl_pct = (day_pnl / start_bal * 100) if start_bal else 0
    else:
        start_bal = end_bal = day_pnl = day_pnl_pct = 0

    print(f"\nStarting balance:    ${start_bal:,.2f}")
    print(f"Ending balance:      ${end_bal:,.2f}")
    pnl_arrow = "▲" if day_pnl >= 0 else "▼"
    print(f"Daily P&L:           {pnl_arrow} ${day_pnl:+,.2f} ({day_pnl_pct:+.2f}%)")

    # ── Trades for the day ────────────────────────────────────
    trades = conn.execute(
        """SELECT pair, event_type, pnl_usd, pnl_pct, hold_duration_seconds,
                  entry_price, exit_price, take_profit_pct_used, stop_loss_pct_used
           FROM audit_position_events
           WHERE mode=? AND DATE(event_at)=?
           AND event_type IN ('stop_loss_triggered','take_profit_triggered','manually_closed')
           ORDER BY event_at ASC""",
        (mode, date_str),
    ).fetchall()

    print(f"\nTrades today:        {len(trades)}")
    if trades:
        print_divider()
        for t in trades:
            pnl = float(t["pnl_usd"] or 0)
            emoji = "✅" if pnl >= 0 else "🔴"
            reason_map = {
                "take_profit_triggered": f"TP hit (+{t['take_profit_pct_used']}%)",
                "stop_loss_triggered":   f"SL hit (-{t['stop_loss_pct_used']}%)",
                "manually_closed":       "Agent sell",
            }
            reason = reason_map.get(t["event_type"], t["event_type"])
            hold_min = int((t["hold_duration_seconds"] or 0) / 60)
            print(
                f"  {emoji} {t['pair']:10s} | {reason:20s} | "
                f"P&L: ${pnl:+7.2f} ({float(t['pnl_pct'] or 0):+.1f}%) | "
                f"Held: {hold_min}m"
            )

    # ── Agent decisions for the day ───────────────────────────
    decisions = conn.execute(
        """SELECT decision_type, COUNT(*) as cnt
           FROM audit_llm_decisions
           WHERE mode=? AND DATE(decided_at)=?
           GROUP BY decision_type""",
        (mode, date_str),
    ).fetchall()

    cycles = conn.execute(
        "SELECT COUNT(*) FROM audit_cycles WHERE mode=? AND DATE(cycle_at)=?",
        (mode, date_str),
    ).fetchone()[0]

    print(f"\nDecision cycles:     {cycles}")
    if decisions:
        print_divider()
        for d in decisions:
            print(f"  {d['decision_type']:12s}: {d['cnt']} decisions")

    # ── Per-pair performance (all-time) ───────────────────────
    print("\nPer-pair performance (all-time):")
    print_divider()
    pairs = [p["pair"] for p in config.get("trading", {}).get("pairs", [])]
    for pair in pairs:
        pair_trades = conn.execute(
            """SELECT pnl_usd, take_profit_pct_used, event_type, stop_loss_pct_used
               FROM audit_position_events
               WHERE mode=? AND pair=?
               AND event_type IN ('stop_loss_triggered','take_profit_triggered','manually_closed')""",
            (mode, pair),
        ).fetchall()
        total  = len(pair_trades)
        wins   = sum(1 for t in pair_trades if (t["pnl_usd"] or 0) > 0)
        net    = sum(float(t["pnl_usd"] or 0) for t in pair_trades)
        wr     = (wins / total * 100) if total else 0

        # Get configured TP for this pair
        pair_cfg = next(
            (p for p in config["trading"]["pairs"] if p["pair"] == pair), {}
        )
        tp_pct = pair_cfg.get("take_profit_pct", config["trading"].get("take_profit_pct", "?"))
        sl_pct = pair_cfg.get("stop_loss_pct", config["trading"].get("stop_loss_pct", 5))

        print(
            f"  {pair:10s} | TP:{tp_pct:3}% SL:{sl_pct}% | "
            f"{total:2d} trades | Win: {wr:4.0f}% | Net: ${net:+7.2f}"
        )

    # ── Errors ──────────────────────────────────────────────
    errors = conn.execute(
        "SELECT COUNT(*) FROM audit_errors WHERE mode=? AND DATE(error_at)=?",
        (mode, date_str),
    ).fetchone()[0]
    if errors:
        print(f"\n⚠  Errors logged today: {errors} (check audit.db audit_errors table)")

    conn.close()
    print("\n" + "═" * 60 + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Daily trading report")
    parser.add_argument("--mode", choices=["paper", "live"], default="paper")
    parser.add_argument("--days-ago", type=int, default=0, help="0=today, 1=yesterday, etc.")
    args = parser.parse_args()
    run_daily_report(args.mode, args.days_ago)
