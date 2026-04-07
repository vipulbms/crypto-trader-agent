"""
review_report.py — N-day performance review with live-trading readiness verdict.

Core logic extracted from scripts/review.py so it can be called
from the Kryptos CLI as well as the standalone script.

Usage (from CLI):
    python kryptos.py review [--days N] [--mode paper|live]

Usage (standalone):
    python scripts/review.py [--mode paper] [--days 14]
"""

import os
from datetime import datetime, timezone, timedelta
from typing import Optional

import yaml

from src.storage.database import get_connection
from src.storage.audit_logger import AuditLogger


def _load_config() -> dict:
    cfg_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "config.yaml")
    with open(cfg_path) as f:
        return yaml.safe_load(f)


def _divider(char: str = "─", width: int = 64) -> None:
    print(char * width)


def run_review(mode: str, days: int = 14, config: Optional[dict] = None) -> None:
    """Print a comprehensive N-day performance review with a readiness verdict.

    Args:
        mode:   "paper" or "live"
        days:   look-back window in days (default 14)
        config: pre-loaded config dict; loaded from disk if None
    """
    if config is None:
        config = _load_config()

    storage  = config.get("storage", {})
    audit_db = storage.get("audit_db", "audit.db")
    audit    = AuditLogger(audit_db=audit_db, mode=mode)
    conn     = get_connection(audit_db)

    end_date   = datetime.now(timezone.utc).date()
    start_date = end_date - timedelta(days=days)
    start_str  = str(start_date)
    end_str    = str(end_date)

    print("\n" + "═" * 64)
    mode_label = "📄 PAPER TRADING" if mode == "paper" else "💰 LIVE TRADING"
    print(f"  {mode_label} — {days}-Day Review")
    print(f"  Period: {start_str} → {end_str}")
    print("═" * 64)

    # ── Starting vs Ending balance ────────────────────────────
    first_snap = conn.execute(
        """SELECT total_usd FROM audit_balance_snapshots
           WHERE mode=? AND DATE(snapshot_at)>=? ORDER BY snapshot_at ASC LIMIT 1""",
        (mode, start_str),
    ).fetchone()
    last_snap = conn.execute(
        """SELECT total_usd FROM audit_balance_snapshots
           WHERE mode=? AND DATE(snapshot_at)<=? ORDER BY snapshot_at DESC LIMIT 1""",
        (mode, end_str),
    ).fetchone()

    start_bal = float(first_snap["total_usd"]) if first_snap else 0
    end_bal   = float(last_snap["total_usd"])  if last_snap  else 0
    total_pnl = end_bal - start_bal
    total_pnl_pct = (total_pnl / start_bal * 100) if start_bal else 0

    print(f"\nStarting balance:    ${start_bal:,.2f}")
    print(f"Ending balance:      ${end_bal:,.2f}")
    arrow = "▲" if total_pnl >= 0 else "▼"
    print(f"Total return:        {arrow} ${total_pnl:+,.2f} ({total_pnl_pct:+.2f}%)")

    # ── Trade statistics ──────────────────────────────────────
    trades = conn.execute(
        """SELECT pair, event_type, pnl_usd, pnl_pct, hold_duration_seconds,
                  entry_price, exit_price, event_at,
                  take_profit_pct_used, stop_loss_pct_used
           FROM audit_position_events
           WHERE mode=? AND DATE(event_at) BETWEEN ? AND ?
           AND event_type IN ('stop_loss_triggered','take_profit_triggered','manually_closed')
           ORDER BY event_at ASC""",
        (mode, start_str, end_str),
    ).fetchall()
    trades = [dict(t) for t in trades]

    total_trades = len(trades)
    wins         = [t for t in trades if (t["pnl_usd"] or 0) > 0]
    losses       = [t for t in trades if (t["pnl_usd"] or 0) <= 0]
    win_rate     = (len(wins) / total_trades * 100) if total_trades else 0
    avg_win      = sum(float(t["pnl_usd"]) for t in wins) / len(wins) if wins else 0
    avg_loss     = sum(float(t["pnl_usd"]) for t in losses) / len(losses) if losses else 0
    best_trade   = max(trades, key=lambda t: float(t["pnl_usd"] or 0)) if trades else None
    worst_trade  = min(trades, key=lambda t: float(t["pnl_usd"] or 0)) if trades else None

    sl_hits     = [t for t in trades if t["event_type"] == "stop_loss_triggered"]
    tp_hits     = [t for t in trades if t["event_type"] == "take_profit_triggered"]
    agent_sells = [t for t in trades if t["event_type"] == "manually_closed"]

    print(f"\nTotal trades:        {total_trades}")
    _divider()
    print(f"  Wins:              {len(wins)} ({win_rate:.1f}%)")
    print(f"  Losses:            {len(losses)} ({100-win_rate:.1f}%)")
    print(f"  Stop-loss hits:    {len(sl_hits)}")
    print(f"  Take-profit hits:  {len(tp_hits)}")
    print(f"  Agent sells:       {len(agent_sells)}")
    print(f"  Avg win:           ${avg_win:+.2f}")
    print(f"  Avg loss:          ${avg_loss:+.2f}")
    if best_trade:
        print(f"  Best trade:        {best_trade['pair']} | ${float(best_trade['pnl_usd']):+.2f}")
    if worst_trade:
        print(f"  Worst trade:       {worst_trade['pair']} | ${float(worst_trade['pnl_usd']):+.2f}")

    # ── Max drawdown ──────────────────────────────────────────
    daily_series = audit.get_daily_pnl_series()
    max_dd = 0.0
    if daily_series:
        balances = [float(s["total_usd"]) for s in daily_series]
        peak     = balances[0]
        for b in balances:
            if b > peak:
                peak = b
            dd = (peak - b) / peak * 100 if peak else 0
            max_dd = max(max_dd, dd)
        print(f"\nMax drawdown:        {max_dd:.2f}%")

    # ── Per-pair breakdown ────────────────────────────────────
    print("\nPer-pair performance:")
    _divider()
    pairs = [p["pair"] for p in config.get("trading", {}).get("pairs", [])]
    for pair in pairs:
        pt = [t for t in trades if t["pair"] == pair]
        if not pt:
            print(f"  {pair:10s} | No trades in period")
            continue
        pw   = [t for t in pt if (t["pnl_usd"] or 0) > 0]
        pnet = sum(float(t["pnl_usd"] or 0) for t in pt)
        pwr  = (len(pw) / len(pt) * 100)
        pair_cfg = next(
            (p for p in config["trading"]["pairs"] if p["pair"] == pair), {}
        )
        tp_pct = pair_cfg.get("take_profit_pct", "?")
        avg_hold = sum(int(t["hold_duration_seconds"] or 0) for t in pt) / len(pt) / 60
        print(
            f"  {pair:10s} | TP:{tp_pct:3}% | "
            f"{len(pt):2d} trades | Win:{pwr:4.0f}% | "
            f"Net: ${pnet:+7.2f} | Avg hold: {avg_hold:.0f}m"
        )

    # ── LLM behaviour ─────────────────────────────────────────
    print("\nLLM decision summary:")
    _divider()
    behaviour     = audit.get_llm_behaviour_summary()
    total_decs    = sum(v for k, v in behaviour.items() if k in ("TRADE_BUY", "TRADE_SELL", "HOLD"))
    for key in ["TRADE_BUY", "TRADE_SELL", "HOLD"]:
        count = behaviour.get(key, 0)
        pct   = (count / total_decs * 100) if total_decs else 0
        print(f"  {key:12s}: {count:4d} ({pct:.1f}%)")
    print(
        f"  Risk rejections: {behaviour.get('risk_rejections', 0)} "
        f"({behaviour.get('risk_rejection_rate_pct', 0)}% rejection rate)"
    )

    # ── Top hold reasons ──────────────────────────────────────
    hold_reasons = conn.execute(
        """SELECT hold_reason, COUNT(*) as cnt
           FROM audit_llm_decisions
           WHERE mode=? AND decision_type='HOLD'
           AND DATE(decided_at) BETWEEN ? AND ?
           AND hold_reason IS NOT NULL
           GROUP BY hold_reason ORDER BY cnt DESC LIMIT 5""",
        (mode, start_str, end_str),
    ).fetchall()
    if hold_reasons:
        print("\nTop hold reasons:")
        _divider()
        for r in hold_reasons:
            print(f"  ({r['cnt']:3d}×) {r['hold_reason'][:60]}")

    # ── Full trade log ────────────────────────────────────────
    print(f"\nFull trade log ({len(trades)} trades):")
    _divider()
    for t in trades:
        pnl   = float(t["pnl_usd"] or 0)
        emoji = "✅" if pnl >= 0 else "🔴"
        reason_map = {
            "take_profit_triggered": "TP  ",
            "stop_loss_triggered":   "SL  ",
            "manually_closed":       "SELL",
        }
        reason = reason_map.get(t["event_type"], "?   ")
        ts     = t["event_at"][:16].replace("T", " ")
        hold_m = int((t["hold_duration_seconds"] or 0) / 60)
        print(
            f"  {emoji} {ts} | {t['pair']:10s} | {reason} | "
            f"${float(t['entry_price'] or 0):>9.2f} → ${float(t['exit_price'] or 0):>9.2f} | "
            f"P&L: ${pnl:+7.2f} | {hold_m}m"
        )

    # ── READY FOR LIVE TRADING? ───────────────────────────────
    print("\n" + "═" * 64)
    print("  READY FOR LIVE TRADING? VERDICT")
    _divider()

    checks = []

    # 1. Win rate > 50%
    wr_pass = win_rate >= 50
    checks.append((wr_pass, f"Win rate {win_rate:.1f}% {'≥' if wr_pass else '<'} 50%"))

    # 2. Max drawdown < 15%
    dd_pass = max_dd < 15 if daily_series else False
    checks.append((dd_pass, f"Max drawdown {max_dd:.1f}% {'<' if dd_pass else '≥'} 15%"))

    # 3. Total return > 0
    pnl_pass = total_pnl > 0
    checks.append((pnl_pass, f"Total return ${total_pnl:+.2f} ({'positive ✓' if pnl_pass else 'negative ✗'})"))

    # 4. At least 10 trades (enough to judge)
    trades_pass = total_trades >= 10
    checks.append((trades_pass, f"Trade sample: {total_trades} trades ({'sufficient' if trades_pass else 'too few — run longer'})"))

    all_pass = all(c[0] for c in checks)
    for passed, desc in checks:
        icon = "✅" if passed else "❌"
        print(f"  {icon} {desc}")

    print()
    if all_pass:
        print("  🟢 VERDICT: Agent looks ready for live trading with small real capital.")
        print("     Start live with minimal amounts and monitor closely.")
    else:
        fails = [desc for passed, desc in checks if not passed]
        print("  🔴 VERDICT: NOT YET READY. Address these issues first:")
        for f in fails:
            print(f"     • {f}")

    print("═" * 64 + "\n")
    conn.close()
