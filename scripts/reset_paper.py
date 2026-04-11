#!/usr/bin/env python3
"""
reset_paper.py — Reset paper trading state for a fresh test run.

Clears:
  paper_trading.db  — paper_wallet, paper_positions, paper_trades, agent_state
  audit.db          — all rows where mode = 'paper'

Then re-seeds paper_wallet with $1,000 (or --balance <N>).

Usage:
  python scripts/reset_paper.py             # interactive confirmation
  python scripts/reset_paper.py --yes       # skip confirmation prompt
  python scripts/reset_paper.py --balance 500 --yes
"""

import argparse
import os
import sys
import time

# Add project root to path so src.* imports work
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

import yaml
from src.storage.database import get_connection, get_db_path
from src.utils.tz import now_sgt_iso


# ── Config ─────────────────────────────────────────────────────────────────────

def _load_config() -> dict:
    cfg_path = os.path.join(PROJECT_ROOT, "config.yaml")
    with open(cfg_path) as f:
        return yaml.safe_load(f)


# ── Introspect current state ────────────────────────────────────────────────────

def _current_state(paper_db: str, audit_db: str) -> dict:
    state = {}
    try:
        conn = get_connection(paper_db)
        row = conn.execute("SELECT cash_usd FROM paper_wallet ORDER BY id DESC LIMIT 1").fetchone()
        state["cash"] = float(row["cash_usd"]) if row else 0.0
        state["open_positions"] = conn.execute(
            "SELECT COUNT(*) FROM paper_positions WHERE status='open'"
        ).fetchone()[0]
        state["closed_positions"] = conn.execute(
            "SELECT COUNT(*) FROM paper_positions WHERE status='closed'"
        ).fetchone()[0]
        state["trades"] = conn.execute("SELECT COUNT(*) FROM paper_trades").fetchone()[0]
        state["agent_state_rows"] = conn.execute("SELECT COUNT(*) FROM agent_state").fetchone()[0]
        conn.close()
    except Exception as e:
        state["paper_error"] = str(e)

    try:
        conn = get_connection(audit_db)
        state["audit_cycles"] = conn.execute(
            "SELECT COUNT(*) FROM audit_cycles WHERE mode='paper'"
        ).fetchone()[0]
        state["audit_balance_snaps"] = conn.execute(
            "SELECT COUNT(*) FROM audit_balance_snapshots WHERE mode='paper'"
        ).fetchone()[0]
        conn.close()
    except Exception as e:
        state["audit_error"] = str(e)

    return state


# ── Paper trading DB reset ──────────────────────────────────────────────────────

def _reset_paper_db(paper_db: str, balance: float) -> None:
    conn = get_connection(paper_db)

    # Clear all trading data
    conn.execute("DELETE FROM paper_trades")
    conn.execute("DELETE FROM paper_positions")
    conn.execute("DELETE FROM paper_wallet")
    conn.execute("DELETE FROM agent_state")

    # Seed fresh wallet
    conn.execute(
        "INSERT INTO paper_wallet (updated_at, cash_usd) VALUES (?, ?)",
        (now_sgt_iso(), balance),
    )
    conn.commit()
    conn.close()
    print(f"  [OK] paper_trading.db — cleared and seeded with ${balance:,.2f}")


# ── Audit DB reset (paper-mode rows only) ──────────────────────────────────────

def _reset_audit_db_paper(audit_db: str) -> None:
    conn = get_connection(audit_db)

    # Foreign-key safe deletion order: child rows first
    # 1. audit_fills: linked to audit_orders (which have mode column)
    conn.execute("""
        DELETE FROM audit_fills
        WHERE order_id IN (SELECT id FROM audit_orders WHERE mode = 'paper')
    """)

    # 2. audit_position_events: direct mode column
    conn.execute("DELETE FROM audit_position_events WHERE mode = 'paper'")

    # 3. audit_orders: direct mode column
    conn.execute("DELETE FROM audit_orders WHERE mode = 'paper'")

    # 4. audit_risk_checks: linked through audit_llm_decisions (which have mode column)
    conn.execute("""
        DELETE FROM audit_risk_checks
        WHERE llm_decision_id IN (SELECT id FROM audit_llm_decisions WHERE mode = 'paper')
    """)

    # 5. audit_llm_decisions: direct mode column
    conn.execute("DELETE FROM audit_llm_decisions WHERE mode = 'paper'")

    # 6. audit_signals: linked to audit_cycles (which have mode column)
    conn.execute("""
        DELETE FROM audit_signals
        WHERE cycle_id IN (SELECT id FROM audit_cycles WHERE mode = 'paper')
    """)

    # 7. audit_cycles: direct mode column
    conn.execute("DELETE FROM audit_cycles WHERE mode = 'paper'")

    # 8. audit_balance_snapshots: direct mode column
    conn.execute("DELETE FROM audit_balance_snapshots WHERE mode = 'paper'")

    # 9. audit_errors: direct mode column
    conn.execute("DELETE FROM audit_errors WHERE mode = 'paper'")

    conn.commit()
    conn.close()
    print("  [OK] audit.db — all paper-mode rows cleared (live rows untouched)")


# ── Main ───────────────────────────────────────────────────────────────────────

def _check_agent_running(paper_path: str) -> bool:
    """Return True if paper_trading.db was modified within the last 120 seconds."""
    try:
        mtime = os.path.getmtime(paper_path)
        return (time.time() - mtime) < 120
    except OSError:
        return False


def main() -> None:
    parser = argparse.ArgumentParser(description="Reset paper trading databases")
    parser.add_argument("--balance", type=float, default=1000.0,
                        help="Starting cash balance in USD (default: 1000)")
    parser.add_argument("--yes", action="store_true",
                        help="Skip confirmation prompt")
    parser.add_argument("--force", action="store_true",
                        help="Force reset even if the trading agent appears to be running")
    args = parser.parse_args()

    config = _load_config()
    paper_db = config["storage"]["paper_db"]
    audit_db  = config["storage"]["audit_db"]

    paper_path = get_db_path(paper_db)
    audit_path = get_db_path(audit_db)

    print("\n=== Paper Trading Reset ===\n")
    print(f"  paper_trading.db : {paper_path}")
    print(f"  audit.db         : {audit_path}")
    print(f"  New balance      : ${args.balance:,.2f}\n")

    # ── Running-agent guard (#171) ─────────────────────────────────────────────
    if _check_agent_running(paper_path) and not args.force:
        print("  ⚠️  WARNING: paper_trading.db was modified in the last 120 seconds.")
        print("  The trading agent may still be running. Resetting while the agent is")
        print("  alive will cause a stale start-of-day balance and trigger a false")
        print("  daily loss notification.\n")
        print("  Stop the agent first (Ctrl+C in its terminal), then re-run.")
        print("  If you are certain the agent is stopped, re-run with --force.\n")
        sys.exit(1)

    state = _current_state(paper_db, audit_db)
    print("State before reset:")
    if "paper_error" in state:
        print(f"  paper_trading.db  ERROR: {state['paper_error']}")
    else:
        print(f"  Cash balance      : ${state.get('cash', 0):.2f}")
        print(f"  Open positions    : {state.get('open_positions', 0)}")
        print(f"  Closed positions  : {state.get('closed_positions', 0)}")
        print(f"  Completed trades  : {state.get('trades', 0)}")
        print(f"  Agent state rows  : {state.get('agent_state_rows', 0)}")
    if "audit_error" in state:
        print(f"  audit.db          ERROR: {state['audit_error']}")
    else:
        print(f"  Audit cycles (paper)  : {state.get('audit_cycles', 0)}")
        print(f"  Balance snapshots (paper): {state.get('audit_balance_snaps', 0)}")

    print()

    if not args.yes:
        answer = input("This will DELETE all paper trading data. Continue? [y/N] ").strip().lower()
        if answer != "y":
            print("Aborted.")
            sys.exit(0)

    print("\nResetting...")
    _reset_paper_db(paper_db, args.balance)
    _reset_audit_db_paper(audit_db)

    print("\nVerifying...")
    state = _current_state(paper_db, audit_db)
    assert state.get("cash") == args.balance,      f"Cash mismatch: {state.get('cash')} != {args.balance}"
    assert state.get("open_positions") == 0,        "Open positions remain after reset"
    assert state.get("trades") == 0,               "Trades remain after reset"
    assert state.get("audit_cycles") == 0,         "Audit cycles remain after reset"
    assert state.get("audit_balance_snaps") == 0,  "Balance snapshots remain after reset"

    print(f"\n  Verified: ${state['cash']:,.2f} cash, 0 positions, 0 trades, 0 audit rows")
    print("\n=== Reset complete. Ready for fresh paper trading. ===\n")


if __name__ == "__main__":
    main()
