"""
AuditLogger — append-only audit trail for all agent decisions and executions.
Writes to audit.db. All methods are wrapped in try/except so a DB write
failure NEVER crashes the agent.
"""

import json
import logging
import traceback
from typing import Optional

from .database import get_connection
from ..utils.tz import now_sgt_iso

logger = logging.getLogger(__name__)


def _now() -> str:
    return now_sgt_iso()


class AuditLogger:
    def __init__(self, audit_db: str, mode: str):
        """
        audit_db : filename of the audit SQLite DB (e.g. 'audit.db')
        mode     : 'paper' or 'live'
        """
        self._db = audit_db
        self._mode = mode

    def _conn(self):
        return get_connection(self._db)

    # ──────────────────────────────────────────────
    # Cycle
    # ──────────────────────────────────────────────

    def log_cycle(
        self,
        portfolio_balance_usd: float,
        available_cash_usd: float,
        open_positions_count: int,
        daily_pnl_usd: float = 0.0,
        daily_pnl_pct: float = 0.0,
    ) -> Optional[int]:
        """Log the start of a decision cycle. Returns the cycle_id."""
        try:
            conn = self._conn()
            cur = conn.execute(
                """INSERT INTO audit_cycles
                   (mode, cycle_at, portfolio_balance_usd, available_cash_usd,
                    open_positions_count, daily_pnl_usd, daily_pnl_pct)
                   VALUES (?,?,?,?,?,?,?)""",
                (self._mode, _now(), portfolio_balance_usd, available_cash_usd,
                 open_positions_count, daily_pnl_usd, daily_pnl_pct),
            )
            conn.commit()
            cycle_id = cur.lastrowid
            conn.close()
            return cycle_id
        except Exception:
            logger.warning("AuditLogger.log_cycle failed:\n%s", traceback.format_exc())
            return None

    def update_cycle_duration(self, cycle_id: int, duration_ms: int) -> None:
        """Patch the cycle row with the total duration once the cycle finishes."""
        try:
            conn = self._conn()
            conn.execute(
                "UPDATE audit_cycles SET cycle_duration_ms=? WHERE id=?",
                (duration_ms, cycle_id),
            )
            conn.commit()
            conn.close()
        except Exception:
            logger.warning("AuditLogger.update_cycle_duration failed:\n%s", traceback.format_exc())

    # ──────────────────────────────────────────────
    # Signals
    # ──────────────────────────────────────────────

    def log_signal(
        self,
        cycle_id: int,
        pair: str,
        price: float,
        indicators: dict,
        signal_direction: str,
        signal_strength: float,
        signal_reasons: list,
    ) -> Optional[int]:
        """Log technical indicator values and the resulting signal for one pair."""
        try:
            conn = self._conn()
            cur = conn.execute(
                """INSERT INTO audit_signals
                   (cycle_id, pair, price,
                    rsi_14, macd_line, macd_signal_line, macd_histogram,
                    ema_20, ema_50, bb_upper, bb_mid, bb_lower, atr_14,
                    signal_direction, signal_strength, signal_reasons)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    cycle_id, pair, price,
                    indicators.get("rsi_14"),
                    indicators.get("macd_line"),
                    indicators.get("macd_signal_line"),
                    indicators.get("macd_histogram"),
                    indicators.get("ema_20"),
                    indicators.get("ema_50"),
                    indicators.get("bb_upper"),
                    indicators.get("bb_mid"),
                    indicators.get("bb_lower"),
                    indicators.get("atr_14"),
                    signal_direction,
                    signal_strength,
                    json.dumps(signal_reasons),
                ),
            )
            conn.commit()
            row_id = cur.lastrowid
            conn.close()
            return row_id
        except Exception:
            logger.warning("AuditLogger.log_signal failed:\n%s", traceback.format_exc())
            return None

    # ──────────────────────────────────────────────
    # LLM decisions — logged for EVERY cycle per pair (BUY, SELL, and HOLD)
    # ──────────────────────────────────────────────

    def log_llm_decision(
        self,
        cycle_id: int,
        pair: str,
        model_name: str,
        decision_type: str,       # 'BUY' | 'SELL' | 'HOLD'
        tool_called: str,          # 'propose_buy' | 'propose_sell' | 'hold'
        raw_llm_output: str,
        tool_args: Optional[dict] = None,
        hold_reason: Optional[str] = None,
        prompt_tokens: Optional[int] = None,
        completion_tokens: Optional[int] = None,
        latency_ms: Optional[int] = None,
        max_reasoning_chars: int = 500,
    ) -> Optional[int]:
        """
        Log every LLM decision — buy, sell, OR hold.
        A hold decision is just as important as a trade for retrospective analysis.
        """
        try:
            reasoning_summary = raw_llm_output[:max_reasoning_chars] if raw_llm_output else ""
            conn = self._conn()
            cur = conn.execute(
                """INSERT INTO audit_llm_decisions
                   (cycle_id, mode, decided_at, pair, model_name,
                    decision_type, tool_called, tool_args, hold_reason,
                    reasoning_summary, raw_llm_output,
                    prompt_tokens, completion_tokens, latency_ms)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    cycle_id, self._mode, _now(), pair, model_name,
                    decision_type, tool_called,
                    json.dumps(tool_args) if tool_args else None,
                    hold_reason,
                    reasoning_summary,
                    raw_llm_output,
                    prompt_tokens, completion_tokens, latency_ms,
                ),
            )
            conn.commit()
            row_id = cur.lastrowid
            conn.close()
            return row_id
        except Exception:
            logger.warning("AuditLogger.log_llm_decision failed:\n%s", traceback.format_exc())
            return None

    # ──────────────────────────────────────────────
    # Risk checks
    # ──────────────────────────────────────────────

    def log_risk_check(
        self,
        llm_decision_id: int,
        proposed_action: str,
        proposed_pair: str,
        approved: bool,
        proposed_usd_amount: Optional[float] = None,
        rejection_reason: Optional[str] = None,
        adjusted_usd_amount: Optional[float] = None,
    ) -> Optional[int]:
        """Log the risk manager's approval or rejection of a proposed action."""
        try:
            conn = self._conn()
            cur = conn.execute(
                """INSERT INTO audit_risk_checks
                   (llm_decision_id, checked_at, proposed_action, proposed_pair,
                    proposed_usd_amount, approved, rejection_reason, adjusted_usd_amount)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (
                    llm_decision_id, _now(), proposed_action, proposed_pair,
                    proposed_usd_amount, int(approved), rejection_reason, adjusted_usd_amount,
                ),
            )
            conn.commit()
            row_id = cur.lastrowid
            conn.close()
            return row_id
        except Exception:
            logger.warning("AuditLogger.log_risk_check failed:\n%s", traceback.format_exc())
            return None

    # ──────────────────────────────────────────────
    # Orders
    # ──────────────────────────────────────────────

    def log_order(
        self,
        risk_check_id: Optional[int],
        pair: str,
        side: str,
        order_type: str,
        role: str,                          # 'entry' | 'stop_loss' | 'take_profit'
        status: str,                        # 'submitted' | 'simulated' | 'failed'
        requested_volume: Optional[float] = None,
        requested_price: Optional[float] = None,
        exchange_order_id: Optional[str] = None,
        paper_fill_price: Optional[float] = None,
        error_message: Optional[str] = None,
        configured_stop_loss_pct: Optional[float] = None,
        configured_take_profit_pct: Optional[float] = None,
    ) -> Optional[int]:
        """Log every order submission attempt (real or simulated)."""
        try:
            conn = self._conn()
            cur = conn.execute(
                """INSERT INTO audit_orders
                   (risk_check_id, mode, submitted_at, pair, side, order_type, role,
                    requested_volume, requested_price, exchange_order_id,
                    paper_fill_price, status, error_message,
                    configured_stop_loss_pct, configured_take_profit_pct)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    risk_check_id, self._mode, _now(), pair, side, order_type, role,
                    requested_volume, requested_price, exchange_order_id,
                    paper_fill_price, status, error_message,
                    configured_stop_loss_pct, configured_take_profit_pct,
                ),
            )
            conn.commit()
            row_id = cur.lastrowid
            conn.close()
            return row_id
        except Exception:
            logger.warning("AuditLogger.log_order failed:\n%s", traceback.format_exc())
            return None

    # ──────────────────────────────────────────────
    # Fills
    # ──────────────────────────────────────────────

    def log_fill(
        self,
        order_id: int,
        fill_price: float,
        fill_volume: float,
        fill_usd_value: float,
        fee_usd: float = 0.0,
        slippage_pct: float = 0.0,
    ) -> Optional[int]:
        """Log the execution fill for an order."""
        try:
            conn = self._conn()
            cur = conn.execute(
                """INSERT INTO audit_fills
                   (order_id, mode, filled_at, fill_price, fill_volume,
                    fill_usd_value, fee_usd, slippage_pct)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (order_id, self._mode, _now(), fill_price, fill_volume,
                 fill_usd_value, fee_usd, slippage_pct),
            )
            conn.commit()
            row_id = cur.lastrowid
            conn.close()
            return row_id
        except Exception:
            logger.warning("AuditLogger.log_fill failed:\n%s", traceback.format_exc())
            return None

    # ──────────────────────────────────────────────
    # Position events
    # ──────────────────────────────────────────────

    def log_position_event(
        self,
        pair: str,
        event_type: str,       # 'opened' | 'stop_loss_triggered' | 'take_profit_triggered' | 'manually_closed'
        entry_price: float,
        take_profit_pct_used: Optional[float] = None,
        stop_loss_pct_used: Optional[float] = None,
        exit_price: Optional[float] = None,
        pnl_usd: Optional[float] = None,
        pnl_pct: Optional[float] = None,
        hold_duration_seconds: Optional[int] = None,
        exit_order_id: Optional[int] = None,
    ) -> Optional[int]:
        """Log a position lifecycle event (open, stop-loss hit, take-profit hit, close)."""
        try:
            conn = self._conn()
            cur = conn.execute(
                """INSERT INTO audit_position_events
                   (mode, event_at, pair, event_type, entry_price, exit_price,
                    pnl_usd, pnl_pct, hold_duration_seconds, exit_order_id,
                    take_profit_pct_used, stop_loss_pct_used)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    self._mode, _now(), pair, event_type, entry_price,
                    exit_price, pnl_usd, pnl_pct, hold_duration_seconds,
                    exit_order_id, take_profit_pct_used, stop_loss_pct_used,
                ),
            )
            conn.commit()
            row_id = cur.lastrowid
            conn.close()
            return row_id
        except Exception:
            logger.warning("AuditLogger.log_position_event failed:\n%s", traceback.format_exc())
            return None

    # ──────────────────────────────────────────────
    # Balance snapshot
    # ──────────────────────────────────────────────

    def log_balance_snapshot(
        self,
        total_usd: float,
        cash_usd: float,
        holdings: dict,
        unrealised_pnl_usd: float = 0.0,
    ) -> Optional[int]:
        """Snapshot portfolio balances at end of each cycle."""
        try:
            conn = self._conn()
            cur = conn.execute(
                """INSERT INTO audit_balance_snapshots
                   (mode, snapshot_at, total_usd, cash_usd, holdings_json, unrealised_pnl_usd)
                   VALUES (?,?,?,?,?,?)""",
                (self._mode, _now(), total_usd, cash_usd,
                 json.dumps(holdings), unrealised_pnl_usd),
            )
            conn.commit()
            row_id = cur.lastrowid
            conn.close()
            return row_id
        except Exception:
            logger.warning("AuditLogger.log_balance_snapshot failed:\n%s", traceback.format_exc())
            return None

    # ──────────────────────────────────────────────
    # Errors
    # ──────────────────────────────────────────────

    def log_error(
        self,
        component: str,
        error_type: str,
        error_message: str,
        stack_trace: Optional[str] = None,
        recovered: bool = True,
    ) -> Optional[int]:
        """Log any runtime error. Never raises."""
        try:
            conn = self._conn()
            cur = conn.execute(
                """INSERT INTO audit_errors
                   (mode, error_at, component, error_type, error_message, stack_trace, recovered)
                   VALUES (?,?,?,?,?,?,?)""",
                (self._mode, _now(), component, error_type, error_message,
                 stack_trace, int(recovered)),
            )
            conn.commit()
            row_id = cur.lastrowid
            conn.close()
            return row_id
        except Exception:
            # Last resort — at minimum print to stderr
            logger.error("AuditLogger.log_error itself failed: %s", traceback.format_exc())
            return None

    # ──────────────────────────────────────────────
    # Query helpers (used by report scripts)
    # ──────────────────────────────────────────────

    def get_decision_trace(self, cycle_id: int) -> dict:
        """Return full chain for one cycle: signals → LLM decisions → risk checks → orders."""
        try:
            conn = self._conn()
            signals = conn.execute(
                "SELECT * FROM audit_signals WHERE cycle_id=?", (cycle_id,)
            ).fetchall()
            decisions = conn.execute(
                "SELECT * FROM audit_llm_decisions WHERE cycle_id=?", (cycle_id,)
            ).fetchall()
            result = {
                "cycle": conn.execute(
                    "SELECT * FROM audit_cycles WHERE id=?", (cycle_id,)
                ).fetchone(),
                "signals": [dict(r) for r in signals],
                "decisions": [],
            }
            for d in decisions:
                d_dict = dict(d)
                risk = conn.execute(
                    "SELECT * FROM audit_risk_checks WHERE llm_decision_id=?", (d["id"],)
                ).fetchone()
                d_dict["risk_check"] = dict(risk) if risk else None
                if risk:
                    orders = conn.execute(
                        "SELECT * FROM audit_orders WHERE risk_check_id=?", (risk["id"],)
                    ).fetchall()
                    d_dict["orders"] = [dict(o) for o in orders]
                result["decisions"].append(d_dict)
            conn.close()
            return result
        except Exception:
            logger.warning("AuditLogger.get_decision_trace failed:\n%s", traceback.format_exc())
            return {}

    def get_all_trades(self, start_date: str = None, end_date: str = None) -> list:
        """Return all closed position events with full P&L, filtered by date if given."""
        try:
            conn = self._conn()
            query = """SELECT * FROM audit_position_events
                       WHERE mode=? AND event_type IN
                       ('stop_loss_triggered','take_profit_triggered','manually_closed')"""
            params = [self._mode]
            if start_date:
                query += " AND event_at >= ?"
                params.append(start_date)
            if end_date:
                query += " AND event_at <= ?"
                params.append(end_date)
            query += " ORDER BY event_at ASC"
            rows = conn.execute(query, params).fetchall()
            conn.close()
            return [dict(r) for r in rows]
        except Exception:
            logger.warning("AuditLogger.get_all_trades failed:\n%s", traceback.format_exc())
            return []

    def get_win_rate(self) -> dict:
        """Return win/loss counts and win rate percentage."""
        try:
            conn = self._conn()
            rows = conn.execute(
                """SELECT pnl_usd FROM audit_position_events
                   WHERE mode=? AND event_type IN
                   ('stop_loss_triggered','take_profit_triggered','manually_closed')""",
                (self._mode,),
            ).fetchall()
            conn.close()
            total = len(rows)
            if total == 0:
                return {"total": 0, "wins": 0, "losses": 0, "win_rate_pct": 0.0}
            wins = sum(1 for r in rows if r["pnl_usd"] and r["pnl_usd"] > 0)
            losses = total - wins
            return {
                "total": total,
                "wins": wins,
                "losses": losses,
                "win_rate_pct": round(wins / total * 100, 1),
            }
        except Exception:
            logger.warning("AuditLogger.get_win_rate failed:\n%s", traceback.format_exc())
            return {}

    def get_daily_pnl_series(self) -> list:
        """Return list of {date, total_usd} from balance snapshots for drawdown calculation."""
        try:
            conn = self._conn()
            rows = conn.execute(
                """SELECT DATE(snapshot_at) as date, total_usd
                   FROM audit_balance_snapshots
                   WHERE mode=?
                   ORDER BY snapshot_at ASC""",
                (self._mode,),
            ).fetchall()
            conn.close()
            return [dict(r) for r in rows]
        except Exception:
            logger.warning("AuditLogger.get_daily_pnl_series failed:\n%s", traceback.format_exc())
            return []

    def get_llm_behaviour_summary(self) -> dict:
        """Return counts of BUY/SELL/HOLD decisions and risk manager rejection rate."""
        try:
            conn = self._conn()
            decisions = conn.execute(
                """SELECT decision_type, COUNT(*) as cnt
                   FROM audit_llm_decisions WHERE mode=?
                   GROUP BY decision_type""",
                (self._mode,),
            ).fetchall()
            rejections = conn.execute(
                """SELECT COUNT(*) FROM audit_risk_checks r
                   JOIN audit_llm_decisions d ON r.llm_decision_id=d.id
                   WHERE d.mode=? AND r.approved=0""",
                (self._mode,),
            ).fetchone()[0]
            total_checks = conn.execute(
                """SELECT COUNT(*) FROM audit_risk_checks r
                   JOIN audit_llm_decisions d ON r.llm_decision_id=d.id
                   WHERE d.mode=?""",
                (self._mode,),
            ).fetchone()[0]
            conn.close()
            summary = {d["decision_type"]: d["cnt"] for d in decisions}
            summary["risk_rejections"] = rejections
            summary["risk_rejection_rate_pct"] = (
                round(rejections / total_checks * 100, 1) if total_checks > 0 else 0.0
            )
            return summary
        except Exception:
            logger.warning("AuditLogger.get_llm_behaviour_summary failed:\n%s", traceback.format_exc())
            return {}
