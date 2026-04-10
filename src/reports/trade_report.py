"""
trade_report.py — Comprehensive report queries over audit.db and trading databases.

All public functions return plain Python dicts / lists — no display logic here.
The CLI display layer (src/cli/display.py) is responsible for formatting.
"""

import json
import logging
import os
import sqlite3
from datetime import datetime, timedelta
from typing import Optional

from src.utils.tz import now_sgt, to_sgt

from src.storage.database import get_connection

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────

def _days_ago_iso(days: int) -> str:
    return (now_sgt() - timedelta(days=days)).isoformat()


def _audit_conn(config: dict) -> sqlite3.Connection:
    return get_connection(config["storage"]["audit_db"])


def _trade_conn(config: dict, mode: str) -> sqlite3.Connection:
    key = "paper_db" if mode == "paper" else "live_db"
    return get_connection(config["storage"][key])


def _safe(fn):
    """Decorator: wrap a report function so it never raises — returns empty on error."""
    import functools
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:
            logger.error("Report query failed [%s]: %s", fn.__name__, exc)
            return {} if "summary" in fn.__name__ or "metrics" in fn.__name__ else []
    return wrapper


# ──────────────────────────────────────────────────────────────
# Portfolio summary
# ──────────────────────────────────────────────────────────────

@_safe
def get_portfolio_summary(mode: str, config: dict) -> dict:
    """
    Return current portfolio state from the trading DB and the latest
    audit balance snapshot.
    """
    tc = _trade_conn(config, mode)
    ac = _audit_conn(config)

    if mode == "paper":
        wallet = tc.execute("SELECT cash_usd FROM paper_wallet WHERE id=1").fetchone()
        cash = wallet["cash_usd"] if wallet else 0.0
        positions = tc.execute(
            "SELECT * FROM paper_positions WHERE status='open' ORDER BY opened_at DESC"
        ).fetchall()
    else:
        cash = 0.0  # live balance comes from Kraken; use last snapshot
        positions = tc.execute(
            "SELECT * FROM live_positions WHERE status='open' ORDER BY opened_at DESC"
        ).fetchall()

    # Latest balance snapshot
    snap = ac.execute(
        "SELECT * FROM audit_balance_snapshots WHERE mode=? ORDER BY snapshot_at DESC LIMIT 1",
        (mode,),
    ).fetchone()

    # Today's closed trades for daily P&L
    today = now_sgt().strftime("%Y-%m-%d")
    if mode == "paper":
        daily_trades = tc.execute(
            "SELECT pnl_usd FROM paper_trades WHERE DATE(closed_at)=?", (today,)
        ).fetchall()
    else:
        daily_trades = tc.execute(
            "SELECT pnl_usd FROM live_trades WHERE DATE(closed_at)=?", (today,)
        ).fetchall()

    daily_pnl = sum(r["pnl_usd"] for r in daily_trades)
    # Paper: compute live from wallet + open positions (snapshot is stale between cycles)
    # Live: cash comes from Kraken so fall back to last snapshot
    if mode == "paper":
        open_pos_value = sum(float(p["usd_value"]) for p in positions)
        total_usd = round(cash + open_pos_value, 4)
    else:
        total_usd = snap["total_usd"] if snap else cash

    tc.close()
    ac.close()

    return {
        "mode": mode,
        "total_usd": total_usd,
        "cash_usd": cash,
        "open_positions": [dict(p) for p in positions],
        "open_positions_count": len(positions),
        "daily_pnl_usd": daily_pnl,
        "snapshot_at": snap["snapshot_at"] if snap else None,
        "unrealised_pnl_usd": snap["unrealised_pnl_usd"] if snap else 0.0,
    }


# ──────────────────────────────────────────────────────────────
# Trade history with LLM decisions
# ──────────────────────────────────────────────────────────────

@_safe
def get_trades_with_decisions(
    mode: str,
    config: dict,
    days: int = 30,
    pair: Optional[str] = None,
    limit: int = 50,
) -> list:
    """
    Return closed trades from the trading DB enriched with the LLM
    decision that initiated each entry (joined via audit tables).

    Returns a list of dicts, newest first.
    """
    tc = _trade_conn(config, mode)
    table = "paper_trades" if mode == "paper" else "live_trades"
    since = _days_ago_iso(days)

    query = f"""
        SELECT * FROM {table}
        WHERE opened_at >= ?
        {" AND pair=? " if pair else ""}
        ORDER BY opened_at DESC
        LIMIT ?
    """
    params = [since] + ([pair] if pair else []) + [limit]
    trades = tc.execute(query, params).fetchall()
    tc.close()

    ac = _audit_conn(config)
    result = []
    for trade in trades:
        t = dict(trade)

        # Find the LLM BUY decision closest to entry time
        decision = ac.execute(
            """SELECT d.*, r.approved, r.rejection_reason, r.adjusted_usd_amount
               FROM audit_llm_decisions d
               LEFT JOIN audit_risk_checks r ON r.llm_decision_id = d.id
               WHERE d.mode=? AND d.pair=? AND d.decision_type='BUY'
                 AND d.decided_at >= ? AND d.decided_at <= ?
               ORDER BY d.decided_at ASC LIMIT 1""",
            (mode, t["pair"],
             # search window: up to 5 min before and 5 min after entry
             _offset_iso(t["opened_at"], -300),
             _offset_iso(t["opened_at"], 300)),
        ).fetchone()

        t["llm_decision"] = dict(decision) if decision else None

        # Duration in human-readable form
        if t.get("hold_duration_secs"):
            t["hold_duration_human"] = _fmt_duration(t["hold_duration_secs"])

        result.append(t)

    ac.close()
    return result


def _offset_iso(iso_str: str, offset_secs: int) -> str:
    """Shift an ISO timestamp by offset_secs seconds."""
    try:
        dt = to_sgt(datetime.fromisoformat(iso_str.replace("Z", "+00:00")))
        return (dt + timedelta(seconds=offset_secs)).isoformat()
    except Exception:
        return iso_str


def _fmt_duration(secs: int) -> str:
    h = secs // 3600
    m = (secs % 3600) // 60
    s = secs % 60
    if h > 0:
        return f"{h}h {m}m"
    if m > 0:
        return f"{m}m {s}s"
    return f"{s}s"


# ──────────────────────────────────────────────────────────────
# Cycle detail (full decision trace for one cycle)
# ──────────────────────────────────────────────────────────────

@_safe
def get_cycle_detail(cycle_id: int, config: dict) -> dict:
    """Return the full decision chain for a single cycle ID."""
    ac = _audit_conn(config)

    cycle = ac.execute(
        "SELECT * FROM audit_cycles WHERE id=?", (cycle_id,)
    ).fetchone()
    if not cycle:
        ac.close()
        return {}

    signals = ac.execute(
        "SELECT * FROM audit_signals WHERE cycle_id=?", (cycle_id,)
    ).fetchall()

    decisions = ac.execute(
        "SELECT * FROM audit_llm_decisions WHERE cycle_id=?", (cycle_id,)
    ).fetchall()

    full_decisions = []
    for d in decisions:
        d_dict = dict(d)
        risk = ac.execute(
            "SELECT * FROM audit_risk_checks WHERE llm_decision_id=?", (d["id"],)
        ).fetchone()
        d_dict["risk_check"] = dict(risk) if risk else None

        orders = []
        if risk:
            raw_orders = ac.execute(
                "SELECT * FROM audit_orders WHERE risk_check_id=?", (risk["id"],)
            ).fetchall()
            for o in raw_orders:
                o_dict = dict(o)
                fill = ac.execute(
                    "SELECT * FROM audit_fills WHERE order_id=?", (o["id"],)
                ).fetchone()
                o_dict["fill"] = dict(fill) if fill else None
                orders.append(o_dict)
        d_dict["orders"] = orders
        full_decisions.append(d_dict)

    ac.close()
    return {
        "cycle": dict(cycle),
        "signals": [dict(s) for s in signals],
        "decisions": full_decisions,
    }


# ──────────────────────────────────────────────────────────────
# Recent cycles summary
# ──────────────────────────────────────────────────────────────

@_safe
def get_recent_cycles(mode: str, config: dict, limit: int = 10) -> list:
    """Return the N most recent cycles with a brief per-pair decision summary."""
    ac = _audit_conn(config)

    cycles = ac.execute(
        "SELECT * FROM audit_cycles WHERE mode=? ORDER BY cycle_at DESC LIMIT ?",
        (mode, limit),
    ).fetchall()

    result = []
    for c in cycles:
        decisions = ac.execute(
            "SELECT pair, decision_type, tool_called FROM audit_llm_decisions WHERE cycle_id=?",
            (c["id"],),
        ).fetchall()
        result.append({
            **dict(c),
            "decisions_summary": [dict(d) for d in decisions],
        })

    ac.close()
    return result


# ──────────────────────────────────────────────────────────────
# LLM decision patterns
# ──────────────────────────────────────────────────────────────

@_safe
def get_llm_decision_patterns(mode: str, config: dict, days: int = 14) -> dict:
    """
    Analyse LLM decision history: BUY/SELL/HOLD counts per pair,
    risk rejection rate, top hold reasons, model used distribution.
    """
    ac = _audit_conn(config)
    since = _days_ago_iso(days)

    # Decision counts by type and pair
    by_pair = ac.execute(
        """SELECT pair, decision_type, COUNT(*) as cnt
           FROM audit_llm_decisions
           WHERE mode=? AND decided_at >= ?
           GROUP BY pair, decision_type
           ORDER BY pair, decision_type""",
        (mode, since),
    ).fetchall()

    # Risk rejections
    rejections = ac.execute(
        """SELECT r.rejection_reason, COUNT(*) as cnt
           FROM audit_risk_checks r
           JOIN audit_llm_decisions d ON r.llm_decision_id = d.id
           WHERE d.mode=? AND r.approved=0 AND d.decided_at >= ?
           GROUP BY r.rejection_reason
           ORDER BY cnt DESC LIMIT 5""",
        (mode, since),
    ).fetchall()

    # Top hold reasons
    hold_reasons = ac.execute(
        """SELECT hold_reason, COUNT(*) as cnt
           FROM audit_llm_decisions
           WHERE mode=? AND decision_type='HOLD' AND hold_reason IS NOT NULL
             AND decided_at >= ?
           GROUP BY hold_reason
           ORDER BY cnt DESC LIMIT 10""",
        (mode, since),
    ).fetchall()

    # Model usage
    models = ac.execute(
        """SELECT model_name, COUNT(*) as cnt
           FROM audit_llm_decisions
           WHERE mode=? AND decided_at >= ?
           GROUP BY model_name ORDER BY cnt DESC""",
        (mode, since),
    ).fetchall()

    # Average latency per model
    latencies = ac.execute(
        """SELECT model_name, ROUND(AVG(latency_ms),0) as avg_ms
           FROM audit_llm_decisions
           WHERE mode=? AND decided_at >= ? AND latency_ms IS NOT NULL
           GROUP BY model_name""",
        (mode, since),
    ).fetchall()

    total_decisions = ac.execute(
        "SELECT COUNT(*) FROM audit_llm_decisions WHERE mode=? AND decided_at >= ?",
        (mode, since),
    ).fetchone()[0]

    total_risk_checks = ac.execute(
        """SELECT COUNT(*) FROM audit_risk_checks r
           JOIN audit_llm_decisions d ON r.llm_decision_id = d.id
           WHERE d.mode=? AND d.decided_at >= ?""",
        (mode, since),
    ).fetchone()[0]

    total_rejections = ac.execute(
        """SELECT COUNT(*) FROM audit_risk_checks r
           JOIN audit_llm_decisions d ON r.llm_decision_id = d.id
           WHERE d.mode=? AND r.approved=0 AND d.decided_at >= ?""",
        (mode, since),
    ).fetchone()[0]

    # Risk approvals / rejections per pair per decision type
    risk_by_pair = ac.execute(
        """SELECT d.pair, d.decision_type, r.approved, COUNT(*) as cnt
           FROM audit_risk_checks r
           JOIN audit_llm_decisions d ON r.llm_decision_id = d.id
           WHERE d.mode=? AND d.decided_at >= ?
           GROUP BY d.pair, d.decision_type, r.approved""",
        (mode, since),
    ).fetchall()

    ac.close()

    # Build per-pair matrix: LLM proposed, risk approved, risk rejected, final outcome
    pair_matrix: dict = {}
    for row in by_pair:
        p = row["pair"]
        if p not in pair_matrix:
            pair_matrix[p] = {
                "LLM_BUY": 0, "LLM_SELL": 0, "LLM_HOLD": 0,
                "RISK_APPROVED": 0, "RISK_REJECTED": 0,
                "FINAL_EXECUTED": 0, "FINAL_HOLD": 0,
            }
        pair_matrix[p][f"LLM_{row['decision_type']}"] = row["cnt"]
        if row["decision_type"] == "HOLD":
            pair_matrix[p]["FINAL_HOLD"] += row["cnt"]

    for row in risk_by_pair:
        p = row["pair"]
        if p not in pair_matrix:
            continue
        if row["approved"]:
            pair_matrix[p]["RISK_APPROVED"] += row["cnt"]
            pair_matrix[p]["FINAL_EXECUTED"] += row["cnt"]
        else:
            pair_matrix[p]["RISK_REJECTED"] += row["cnt"]
            pair_matrix[p]["FINAL_HOLD"] += row["cnt"]

    return {
        "days": days,
        "total_decisions": total_decisions,
        "pair_matrix": pair_matrix,
        "top_hold_reasons": [dict(r) for r in hold_reasons],
        "risk_rejections": [dict(r) for r in rejections],
        "rejection_rate_pct": round(total_rejections / total_risk_checks * 100, 1)
        if total_risk_checks > 0 else 0.0,
        "models_used": {r["model_name"]: r["cnt"] for r in models},
        "avg_latency_ms": {r["model_name"]: r["avg_ms"] for r in latencies},
    }


# ──────────────────────────────────────────────────────────────
# Performance metrics
# ──────────────────────────────────────────────────────────────

@_safe
def get_performance_metrics(mode: str, config: dict, days: int = 14) -> dict:
    """
    Compute win rate, total P&L, max drawdown, per-pair breakdown,
    best/worst trades, and average hold duration.
    """
    tc = _trade_conn(config, mode)
    table = "paper_trades" if mode == "paper" else "live_trades"
    since = _days_ago_iso(days)

    trades = tc.execute(
        f"SELECT * FROM {table} WHERE opened_at >= ? ORDER BY opened_at ASC",
        (since,),
    ).fetchall()
    tc.close()

    ac = _audit_conn(config)
    # Balance series for drawdown
    balance_series = ac.execute(
        """SELECT snapshot_at, total_usd FROM audit_balance_snapshots
           WHERE mode=? AND snapshot_at >= ?
           ORDER BY snapshot_at ASC""",
        (mode, since),
    ).fetchall()
    ac.close()

    trades_list = [dict(t) for t in trades]
    total = len(trades_list)
    if total == 0:
        return {
            "days": days, "total_trades": 0, "wins": 0, "losses": 0,
            "win_rate_pct": 0.0, "total_pnl_usd": 0.0,
            "max_drawdown_pct": 0.0, "by_pair": {},
            "best_trade": None, "worst_trade": None, "avg_hold_secs": 0,
        }

    wins   = [t for t in trades_list if t["pnl_usd"] > 0]
    losses = [t for t in trades_list if t["pnl_usd"] <= 0]
    total_pnl = sum(t["pnl_usd"] for t in trades_list)

    # Per-pair breakdown
    by_pair: dict = {}
    for t in trades_list:
        p = t["pair"]
        if p not in by_pair:
            by_pair[p] = {"total": 0, "wins": 0, "losses": 0, "pnl_usd": 0.0}
        by_pair[p]["total"] += 1
        by_pair[p]["pnl_usd"] += t["pnl_usd"]
        if t["pnl_usd"] > 0:
            by_pair[p]["wins"] += 1
        else:
            by_pair[p]["losses"] += 1
    for p in by_pair:
        n = by_pair[p]["total"]
        by_pair[p]["win_rate_pct"] = round(by_pair[p]["wins"] / n * 100, 1) if n else 0.0
        by_pair[p]["pnl_usd"] = round(by_pair[p]["pnl_usd"], 2)

    best  = max(trades_list, key=lambda t: t["pnl_usd"])
    worst = min(trades_list, key=lambda t: t["pnl_usd"])
    avg_hold = int(sum(t.get("hold_duration_secs", 0) for t in trades_list) / total)

    # Max drawdown from balance series
    max_dd = _compute_max_drawdown([r["total_usd"] for r in balance_series])

    return {
        "days": days,
        "total_trades": total,
        "wins": len(wins),
        "losses": len(losses),
        "win_rate_pct": round(len(wins) / total * 100, 1),
        "total_pnl_usd": round(total_pnl, 2),
        "max_drawdown_pct": max_dd,
        "by_pair": by_pair,
        "best_trade": best,
        "worst_trade": worst,
        "avg_hold_secs": avg_hold,
        "avg_hold_human": _fmt_duration(avg_hold),
        "exit_reason_counts": _count_field(trades_list, "exit_reason"),
        "exit_reason_pnl": _sum_pnl_by_field(trades_list, "exit_reason"),
    }


def _compute_max_drawdown(values: list) -> float:
    if len(values) < 2:
        return 0.0
    peak = values[0]
    max_dd = 0.0
    for v in values:
        if v > peak:
            peak = v
        dd = (peak - v) / peak * 100 if peak > 0 else 0.0
        if dd > max_dd:
            max_dd = dd
    return round(max_dd, 2)


def _count_field(rows: list, field: str) -> dict:
    result: dict = {}
    for r in rows:
        k = r.get(field, "unknown")
        result[k] = result.get(k, 0) + 1
    return result


def _sum_pnl_by_field(rows: list, field: str) -> dict:
    """Sum pnl_usd per distinct value of field (e.g. per exit_reason)."""
    result: dict = {}
    for r in rows:
        k = r.get(field, "unknown")
        result[k] = result.get(k, 0.0) + r.get("pnl_usd", 0.0)
    return {k: round(v, 2) for k, v in result.items()}


# ──────────────────────────────────────────────────────────────
# Specific LLM decision detail
# ──────────────────────────────────────────────────────────────

@_safe
def get_llm_decision_detail(
    mode: str,
    config: dict,
    pair: Optional[str] = None,
    decision_type: Optional[str] = None,
    days: int = 7,
    limit: int = 20,
) -> list:
    """Return LLM decisions with full reasoning text, optionally filtered."""
    ac = _audit_conn(config)
    since = _days_ago_iso(days)

    query = """SELECT d.*, r.approved, r.rejection_reason, r.adjusted_usd_amount
               FROM audit_llm_decisions d
               LEFT JOIN audit_risk_checks r ON r.llm_decision_id = d.id
               WHERE d.mode=? AND d.decided_at >= ?"""
    params: list = [mode, since]

    if pair:
        query += " AND d.pair=?"
        params.append(pair)
    if decision_type:
        query += " AND d.decision_type=?"
        params.append(decision_type.upper())

    query += " ORDER BY d.decided_at DESC LIMIT ?"
    params.append(limit)

    rows = ac.execute(query, params).fetchall()
    ac.close()
    return [dict(r) for r in rows]


# ──────────────────────────────────────────────────────────────
# Daily P&L summary
# ──────────────────────────────────────────────────────────────

@_safe
def get_daily_summary(mode: str, config: dict, date_str: Optional[str] = None) -> dict:
    """Return trade activity and P&L for a specific date (default: today)."""
    if not date_str:
        date_str = now_sgt().strftime("%Y-%m-%d")

    tc = _trade_conn(config, mode)
    table = "paper_trades" if mode == "paper" else "live_trades"

    trades = tc.execute(
        f"SELECT * FROM {table} WHERE DATE(closed_at)=? ORDER BY closed_at ASC",
        (date_str,),
    ).fetchall()
    tc.close()

    ac = _audit_conn(config)
    cycle_count = ac.execute(
        "SELECT COUNT(*) FROM audit_cycles WHERE mode=? AND DATE(cycle_at)=?",
        (mode, date_str),
    ).fetchone()[0]

    decisions = ac.execute(
        """SELECT decision_type, COUNT(*) as cnt
           FROM audit_llm_decisions
           WHERE mode=? AND DATE(decided_at)=?
           GROUP BY decision_type""",
        (mode, date_str),
    ).fetchall()

    snapshot = ac.execute(
        """SELECT total_usd FROM audit_balance_snapshots
           WHERE mode=? AND DATE(snapshot_at)=?
           ORDER BY snapshot_at DESC LIMIT 1""",
        (mode, date_str),
    ).fetchone()

    errors = ac.execute(
        "SELECT COUNT(*) FROM audit_errors WHERE mode=? AND DATE(error_at)=?",
        (mode, date_str),
    ).fetchone()[0]

    ac.close()

    trades_list = [dict(t) for t in trades]
    total_pnl = sum(t["pnl_usd"] for t in trades_list)

    return {
        "date": date_str,
        "mode": mode,
        "cycles_run": cycle_count,
        "trades_closed": len(trades_list),
        "total_pnl_usd": round(total_pnl, 2),
        "wins": sum(1 for t in trades_list if t["pnl_usd"] > 0),
        "losses": sum(1 for t in trades_list if t["pnl_usd"] <= 0),
        "decision_counts": {d["decision_type"]: d["cnt"] for d in decisions},
        "closing_balance": snapshot["total_usd"] if snapshot else None,
        "errors": errors,
        "trades": trades_list,
    }


# ──────────────────────────────────────────────────────────────
# Open positions
# ──────────────────────────────────────────────────────────────

@_safe
def get_open_positions(mode: str, config: dict) -> list:
    """Return all currently open positions."""
    tc = _trade_conn(config, mode)
    table = "paper_positions" if mode == "paper" else "live_positions"
    rows = tc.execute(
        f"SELECT * FROM {table} WHERE status='open' ORDER BY opened_at ASC"
    ).fetchall()
    tc.close()
    return [dict(r) for r in rows]


def get_signal_driver_report(config: dict, days: int = 30, top_n: int = 10) -> dict:
    """
    Analyse audit_signals to show which parameters are driving BUY/HOLD decisions.
    Returns:
        {
            "by_pair": {
                "BTC/USD": {
                    "buy_count": int,
                    "hold_count": int,
                    "top_blockers": [{"reason": str, "count": int}, ...],   # top HOLD reasons
                    "top_drivers": [{"reason": str, "count": int}, ...],    # top BUY reasons
                }
            },
            "global_top_blockers": [{"reason": str, "count": int}, ...],
            "global_top_drivers": [{"reason": str, "count": int}, ...],
            "period_days": int,
        }
    """
    from collections import Counter

    ac = _audit_conn(config)
    cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
    rows = ac.execute(
        """SELECT pair, signal_direction, signal_reasons
           FROM audit_signals
           WHERE created_at >= ?
           ORDER BY created_at ASC""",
        (cutoff,),
    ).fetchall()
    ac.close()

    by_pair: dict = {}
    global_blocker_counts: Counter = Counter()
    global_driver_counts: Counter  = Counter()

    for row in rows:
        pair      = row[0]
        direction = row[1]
        try:
            reasons = json.loads(row[2]) if row[2] else []
        except Exception:
            reasons = []

        if pair not in by_pair:
            by_pair[pair] = {
                "buy_count":   0,
                "hold_count":  0,
                "_blockers":   Counter(),
                "_drivers":    Counter(),
            }

        entry = by_pair[pair]
        if direction == "BUY":
            entry["buy_count"] += 1
            for r in reasons:
                entry["_drivers"][r] += 1
                global_driver_counts[r] += 1
        else:
            entry["hold_count"] += 1
            for r in reasons:
                if "BLOCKED" in r or "blocked" in r.lower() or "insufficient" in r.lower():
                    entry["_blockers"][r] += 1
                    global_blocker_counts[r] += 1

    # Convert Counter objects to sorted lists
    result_by_pair = {}
    for pair, entry in by_pair.items():
        result_by_pair[pair] = {
            "buy_count":    entry["buy_count"],
            "hold_count":   entry["hold_count"],
            "top_blockers": [{"reason": r, "count": c}
                             for r, c in entry["_blockers"].most_common(top_n)],
            "top_drivers":  [{"reason": r, "count": c}
                             for r, c in entry["_drivers"].most_common(top_n)],
        }

    return {
        "by_pair":             result_by_pair,
        "global_top_blockers": [{"reason": r, "count": c}
                                 for r, c in global_blocker_counts.most_common(top_n)],
        "global_top_drivers":  [{"reason": r, "count": c}
                                 for r, c in global_driver_counts.most_common(top_n)],
        "period_days":         days,
    }
