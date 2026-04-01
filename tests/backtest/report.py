"""
Backtest report generator.
Takes the results dict from runner.run_backtest() and produces a formatted text report.
"""

import datetime
import math
from collections import defaultdict


def _dt(ts: int) -> str:
    return datetime.datetime.utcfromtimestamp(ts).strftime("%Y-%m-%d %H:%M")


def _pnl_bar(pnl_pct: float, width: int = 20) -> str:
    """ASCII bar chart for P&L percentage."""
    filled = min(abs(int(pnl_pct / 2)), width)
    bar = "█" * filled + "░" * (width - filled)
    sign = "+" if pnl_pct >= 0 else "-"
    return f"[{bar}] {sign}{abs(pnl_pct):.2f}%"


def generate_report(results: dict, config: dict) -> str:
    trades          = results["trades"]
    n_candles       = results["n_candles"]
    min_candles     = results["min_candles"]
    tradeable       = results["tradeable_steps"]
    start_bal       = results["starting_balance"]
    final_bal       = results["final_balance"]
    total_pnl_usd   = results["total_pnl_usd"]
    total_pnl_pct   = results["total_pnl_pct"]
    cycles          = results["cycles"]
    buy_proposals   = results["buy_proposals"]
    sell_proposals  = results["sell_proposals"]
    rejected_buys   = results["rejected_buys"]
    balance_hist    = results.get("balance_history", [])

    # ── Split trades by exit reason ──────────────────────────────────
    closed_trades   = [t for t in trades if t["exit_reason"] != "end_of_backtest"]
    eob_trades      = [t for t in trades if t["exit_reason"] == "end_of_backtest"]
    wins            = [t for t in closed_trades if t["pnl_usd"] >= 0]
    losses          = [t for t in closed_trades if t["pnl_usd"] < 0]
    tp_trades       = [t for t in closed_trades if t["exit_reason"] == "take_profit"]
    sl_trades       = [t for t in closed_trades if t["exit_reason"] == "stop_loss"]
    agent_sells     = [t for t in closed_trades if t["exit_reason"] == "agent_sell"]
    win_rate        = len(wins) / len(closed_trades) * 100 if closed_trades else 0

    # ── Per-pair breakdown ──────────────────────────────────────────
    pair_stats = defaultdict(lambda: {"trades": 0, "pnl_usd": 0.0, "wins": 0, "losses": 0,
                                       "tp": 0, "sl": 0})
    for t in closed_trades:
        ps = pair_stats[t["pair"]]
        ps["trades"] += 1
        ps["pnl_usd"] += t["pnl_usd"]
        if t["pnl_usd"] >= 0:
            ps["wins"] += 1
        else:
            ps["losses"] += 1
        if t["exit_reason"] == "take_profit":
            ps["tp"] += 1
        elif t["exit_reason"] == "stop_loss":
            ps["sl"] += 1

    # ── Average hold duration ────────────────────────────────────────
    avg_hold_candles = (
        sum(t["hold_candles"] for t in closed_trades) / len(closed_trades)
        if closed_trades else 0
    )
    avg_hold_hrs = avg_hold_candles * 15 / 60

    # ── Sharpe-like ratio (rough: mean return / std of returns) ──────
    if len(closed_trades) >= 2:
        pnl_pcts = [t["pnl_pct"] for t in closed_trades]
        mean_r   = sum(pnl_pcts) / len(pnl_pcts)
        variance = sum((r - mean_r) ** 2 for r in pnl_pcts) / len(pnl_pcts)
        std_r    = math.sqrt(variance) if variance > 0 else 0
        sharpe   = round(mean_r / std_r, 3) if std_r > 0 else 0.0
    else:
        sharpe = 0.0
        mean_r = 0.0

    avg_win  = sum(t["pnl_usd"] for t in wins)  / len(wins)  if wins   else 0
    avg_loss = sum(t["pnl_usd"] for t in losses) / len(losses) if losses else 0
    rr_ratio = abs(avg_win / avg_loss) if avg_loss != 0 else float("inf")

    lines = []
    sep  = "═" * 70
    sep2 = "─" * 70

    lines += [
        "",
        sep,
        "  KRYPTOS — BACKTEST REPORT",
        sep,
        "",
        "  DATA WINDOW",
        f"  {'Total candles:':<30} {n_candles} × 15 min",
        f"  {'Warmup candles (EMA200):':<30} {min_candles}",
        f"  {'Tradeable steps:':<30} {tradeable} ({tradeable * 15 / 60:.1f} hours)",
        f"  {'Decision cycles run:':<30} {cycles}",
        "",
        sep2,
        "  PORTFOLIO SUMMARY",
        sep2,
        f"  {'Starting balance:':<30} ${start_bal:,.2f}",
        f"  {'Final balance:':<30} ${final_bal:,.2f}",
        f"  {'Total P&L:':<30} ${total_pnl_usd:+,.2f}  ({total_pnl_pct:+.2f}%)",
        f"  {'P&L bar:':<30} {_pnl_bar(total_pnl_pct)}",
        "",
        sep2,
        "  TRADING ACTIVITY",
        sep2,
        f"  {'Buy orders placed:':<30} {buy_proposals}",
        f"  {'Sell orders placed:':<30} {sell_proposals}",
        f"  {'Buys rejected (risk rules):':<30} {rejected_buys}",
        f"  {'Total closed trades:':<30} {len(closed_trades)}",
        f"  {'  — Take-profit hits:':<30} {len(tp_trades)}",
        f"  {'  — Stop-loss hits:':<30} {len(sl_trades)}",
        f"  {'  — Agent early sells:':<30} {len(agent_sells)}",
        f"  {'  — Force-closed (end):':<30} {len(eob_trades)}",
        "",
        sep2,
        "  PERFORMANCE METRICS",
        sep2,
        f"  {'Win rate:':<30} {win_rate:.1f}%  ({len(wins)}W / {len(losses)}L)",
        f"  {'Avg win:':<30} ${avg_win:+.2f}",
        f"  {'Avg loss:':<30} ${avg_loss:+.2f}",
        f"  {'Win/Loss ratio:':<30} {rr_ratio:.2f}x",
        f"  {'Avg return per trade:':<30} {mean_r:+.2f}%",
        f"  {'Sharpe ratio (approx):':<30} {sharpe}",
        f"  {'Avg hold duration:':<30} {avg_hold_hrs:.1f}h ({avg_hold_candles:.0f} candles)",
        "",
    ]

    # ── Balance history ──────────────────────────────────────────────
    if balance_hist:
        lines += [sep2, "  BALANCE HISTORY (every 12h)", sep2]
        for ts, bal in balance_hist:
            pnl = bal - start_bal
            sign = "+" if pnl >= 0 else ""
            lines.append(f"  {_dt(ts)}  ${bal:>8.2f}  ({sign}{pnl:.2f})")
        lines.append("")

    # ── Per-pair breakdown ───────────────────────────────────────────
    lines += [sep2, "  PER-PAIR BREAKDOWN", sep2,
              f"  {'Pair':<12} {'Trades':>6} {'W':>4} {'L':>4} {'TP':>4} {'SL':>4} {'P&L USD':>10}",
              f"  {'-'*12} {'-'*6} {'-'*4} {'-'*4} {'-'*4} {'-'*4} {'-'*10}"]
    for pair in sorted(pair_stats):
        ps = pair_stats[pair]
        lines.append(
            f"  {pair:<12} {ps['trades']:>6} {ps['wins']:>4} {ps['losses']:>4} "
            f"{ps['tp']:>4} {ps['sl']:>4} ${ps['pnl_usd']:>+9.2f}"
        )
    lines.append("")

    # ── Individual trade log ─────────────────────────────────────────
    if closed_trades:
        lines += [sep2, "  TRADE LOG (closed trades, excluding end-of-backtest)", sep2,
                  f"  {'#':<4} {'Pair':<12} {'Entry':>10} {'Exit':>10} "
                  f"{'P&L%':>7} {'P&L$':>8} {'Hold':>6} {'Reason':<15}",
                  f"  {'-'*4} {'-'*12} {'-'*10} {'-'*10} {'-'*7} {'-'*8} {'-'*6} {'-'*15}"]
        for i, t in enumerate(closed_trades, 1):
            hold_h = t["hold_candles"] * 15 / 60
            lines.append(
                f"  {i:<4} {t['pair']:<12} ${t['entry_price']:>9.4f} ${t['exit_price']:>9.4f} "
                f"{t['pnl_pct']:>+6.2f}% ${t['pnl_usd']:>+7.2f} "
                f"{hold_h:>5.1f}h {t['exit_reason']:<15}"
            )
        lines.append("")

    # ── End-of-backtest open positions ───────────────────────────────
    if eob_trades:
        lines += [sep2, "  OPEN POSITIONS AT END (mark-to-market close)", sep2]
        for t in eob_trades:
            lines.append(
                f"  {t['pair']:<12} entry=${t['entry_price']:.4f} "
                f"mark=${t['exit_price']:.4f} P&L={t['pnl_pct']:+.2f}%"
            )
        lines.append("")

    lines += [sep, "  END OF REPORT", sep, ""]
    return "\n".join(lines)
