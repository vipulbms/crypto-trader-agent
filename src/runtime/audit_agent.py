"""
src/runtime/audit_agent.py — S23.1.1 / S23.1.3

Audit Agent: standalone post-hoc outcome evaluation process.

Responsibilities:
  1. 24h validation window: evaluate every RAA proposal outcome after 24h.
  2. Reprimand vectors: write penalty feedback on 422/MEME_BLOCK rejections.
  3. HITL lock: lock substitution tool after 3 FOUNDATIONAL_REPLACEMENT_BLOCKs in 24h.
  4. 24h rollup: populate playbook_performance + risk_decision_outcomes.
  5. 6h rollup: populate signal_accuracy (driver accuracy per pair from last 30d).
  6. Confidence reset detection: rolling 5-outcome std-dev > 3σ.

Entry point:
    python -m src.runtime.audit_agent --config config.yaml --db paper_trading.db [--port 8094]
"""

import argparse
import asyncio
import json
import logging
import math
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

# ── Path setup ────────────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import yaml

logger = logging.getLogger("audit_agent")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

# ── Optional aiohttp ──────────────────────────────────────────
try:
    from aiohttp import web as _aio_web
    _AIOHTTP_AVAILABLE = True
except ImportError:
    _AIOHTTP_AVAILABLE = False
    logger.warning("[AUDIT] aiohttp not available — health endpoint disabled")

# ── Optional Telegram notifier ────────────────────────────────
try:
    from src.notifications.notifier import Notifier as _Notifier
    _NOTIFIER_AVAILABLE = True
except ImportError:
    _NOTIFIER_AVAILABLE = False

# ─────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────

_AGENT_NAME = "AUDIT"
_RAA_AGENT  = "RAA"

# Reprimand codes
_REPRIMAND_MEME_BLOCK    = "MEME_BLOCK_REPRIMAND"
_REPRIMAND_UNIVERSE_CAP  = "UNIVERSE_CAP_REPRIMAND"
_REPRIMAND_ALPHA_INSUF   = "ALPHA_SPREAD_REPRIMAND"
_REPRIMAND_DB_ERROR      = "DB_ERROR_REPRIMAND"
_FOUNDATIONAL_BLOCK      = "FOUNDATIONAL_REPLACEMENT_BLOCK"

# Outcome codes
_OUTCOME_PASS  = "PASS"
_OUTCOME_FAIL  = "FAIL_PUMP_DETECTION"
_OUTCOME_FLAT  = "FLAT"

# ─────────────────────────────────────────────────────────────
# DB helpers
# ─────────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get_conn(db_path: str):
    from src.storage.database import get_connection
    return get_connection(db_path)


def _ensure_schema(db_path: str) -> None:
    """Ensure all feedback tables exist (idempotent)."""
    from src.storage.database import init_paper_db
    init_paper_db(db_path)


# ── audit_feedback ────────────────────────────────────────────

def write_audit_feedback(
    db_path: str,
    agent: str,
    pair: Optional[str],
    event_type: str,
    psv_vector: str = "",
    expected_alpha: Optional[float] = None,
    actual_alpha: Optional[float] = None,
    outcome: Optional[str] = None,
    penalty_weight: float = 0.0,
) -> None:
    conn = _get_conn(db_path)
    conn.execute(
        """INSERT INTO audit_feedback
           (agent, pair, event_type, ts, psv_vector, expected_alpha, actual_alpha, outcome, penalty_weight)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (agent, pair, event_type, _now_iso(),
         psv_vector, expected_alpha, actual_alpha, outcome, penalty_weight),
    )
    conn.commit()
    conn.close()


def get_recent_feedback(
    db_path: str,
    agent: str,
    since_iso: Optional[str] = None,
    limit: int = 200,
) -> list:
    conn = _get_conn(db_path)
    if since_iso:
        rows = conn.execute(
            """SELECT * FROM audit_feedback
               WHERE agent=? AND ts>=? ORDER BY ts DESC LIMIT ?""",
            (agent, since_iso, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM audit_feedback WHERE agent=? ORDER BY ts DESC LIMIT ?",
            (agent, limit),
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── confidence_state ──────────────────────────────────────────

def get_confidence_state(db_path: str, agent: str) -> Optional[dict]:
    conn = _get_conn(db_path)
    row = conn.execute(
        "SELECT * FROM confidence_state WHERE agent=?", (agent,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def upsert_confidence_state(db_path: str, agent: str, **kwargs) -> None:
    now = _now_iso()
    conn = _get_conn(db_path)
    existing = conn.execute(
        "SELECT id FROM confidence_state WHERE agent=?", (agent,)
    ).fetchone()
    if existing:
        sets = ", ".join(f"{k}=?" for k in kwargs)
        vals = list(kwargs.values()) + [now, agent]
        conn.execute(
            f"UPDATE confidence_state SET {sets}, last_updated_at=? WHERE agent=?", vals
        )
    else:
        fields = ["agent", "last_updated_at"] + list(kwargs.keys())
        placeholders = ", ".join("?" for _ in fields)
        vals = [agent, now] + list(kwargs.values())
        conn.execute(
            f"INSERT INTO confidence_state ({', '.join(fields)}) VALUES ({placeholders})", vals
        )
    conn.commit()
    conn.close()


# ── hitl_queue ────────────────────────────────────────────────

def write_hitl_queue(
    db_path: str,
    agent: str,
    proposal_type: str,
    pair: str,
    replace_target: Optional[str],
    classification: str,
    psv_vector: str,
    rationale: str,
) -> int:
    conn = _get_conn(db_path)
    cursor = conn.execute(
        """INSERT INTO hitl_queue
           (ts, agent, proposal_type, pair, replace_target, classification,
            psv_vector, rationale, status)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'PENDING')""",
        (_now_iso(), agent, proposal_type, pair, replace_target,
         classification, psv_vector, rationale),
    )
    row_id = cursor.lastrowid
    conn.commit()
    conn.close()
    logger.info("[AUDIT] HITL queue entry created: id=%d pair=%s", row_id, pair)
    return row_id


def count_reprimands_in_window(
    db_path: str,
    agent: str,
    event_type: str,
    hours: int = 24,
) -> int:
    since_iso = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    conn = _get_conn(db_path)
    row = conn.execute(
        """SELECT COUNT(*) FROM audit_feedback
           WHERE agent=? AND event_type=? AND ts>=?""",
        (agent, event_type, since_iso),
    ).fetchone()
    conn.close()
    return row[0] if row else 0


def is_substitution_locked(db_path: str) -> bool:
    state = get_confidence_state(db_path, _RAA_AGENT)
    if not state:
        return False
    if not state.get("substitution_tool_locked"):
        return False
    locked_until = state.get("locked_until_ts")
    if not locked_until:
        return True
    now_ts = time.time()
    try:
        exp_ts = datetime.fromisoformat(locked_until).timestamp()
    except ValueError:
        return True
    if now_ts >= exp_ts:
        # Lock expired — clear it
        upsert_confidence_state(
            db_path, _RAA_AGENT,
            substitution_tool_locked=0,
            locked_until_ts=None,
        )
        logger.info("[AUDIT] Substitution lock expired, cleared automatically")
        return False
    return True


# ── playbook_performance ──────────────────────────────────────

def upsert_playbook_performance(
    db_path: str,
    regime: str,
    playbook: str,
    sample_count: int,
    win_rate: float,
    profit_factor: float,
    max_drawdown: float,
) -> None:
    conn = _get_conn(db_path)
    conn.execute(
        """INSERT INTO playbook_performance
           (regime, playbook, sample_count, win_rate, profit_factor, max_drawdown, last_updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(regime, playbook) DO UPDATE SET
             sample_count=excluded.sample_count,
             win_rate=excluded.win_rate,
             profit_factor=excluded.profit_factor,
             max_drawdown=excluded.max_drawdown,
             last_updated_at=excluded.last_updated_at""",
        (regime, playbook, sample_count, win_rate, profit_factor, max_drawdown, _now_iso()),
    )
    conn.commit()
    conn.close()


# ── signal_accuracy ───────────────────────────────────────────

def upsert_signal_accuracy(
    db_path: str,
    pair: str,
    driver: str,
    accuracy_pct: float,
    weight_multiplier: float,
    sample_count: int,
) -> None:
    # Clamp multiplier to [0.5, 1.5] on write (AC4 boundary guard)
    clamped = max(0.5, min(1.5, weight_multiplier))
    conn = _get_conn(db_path)
    conn.execute(
        """INSERT INTO signal_accuracy
           (pair, driver, accuracy_pct, weight_multiplier, sample_count, last_updated_at)
           VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT(pair, driver) DO UPDATE SET
             accuracy_pct=excluded.accuracy_pct,
             weight_multiplier=excluded.weight_multiplier,
             sample_count=excluded.sample_count,
             last_updated_at=excluded.last_updated_at""",
        (pair, driver, accuracy_pct, clamped, sample_count, _now_iso()),
    )
    conn.commit()
    conn.close()


def get_signal_accuracy(db_path: str, pair: str) -> dict:
    """Returns {driver: weight_multiplier} for this pair. Multipliers clamped [0.5, 1.5]."""
    conn = _get_conn(db_path)
    rows = conn.execute(
        "SELECT driver, weight_multiplier FROM signal_accuracy WHERE pair=?", (pair,)
    ).fetchall()
    conn.close()
    return {r[0]: max(0.5, min(1.5, float(r[1]))) for r in rows}


# ── risk_decision_outcomes ────────────────────────────────────

def upsert_risk_decision_outcomes(
    db_path: str,
    pair: str,
    sample_count: int,
    sl_hit_rate: float,
    tp_hit_rate: float,
    avg_hold_secs: Optional[float],
) -> None:
    conn = _get_conn(db_path)
    conn.execute(
        """INSERT INTO risk_decision_outcomes
           (pair, sample_count, sl_hit_rate, tp_hit_rate, avg_hold_secs, last_updated_at)
           VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT(pair) DO UPDATE SET
             sample_count=excluded.sample_count,
             sl_hit_rate=excluded.sl_hit_rate,
             tp_hit_rate=excluded.tp_hit_rate,
             avg_hold_secs=excluded.avg_hold_secs,
             last_updated_at=excluded.last_updated_at""",
        (pair, sample_count, sl_hit_rate, tp_hit_rate, avg_hold_secs, _now_iso()),
    )
    conn.commit()
    conn.close()


# ─────────────────────────────────────────────────────────────
# Core audit logic
# ─────────────────────────────────────────────────────────────

def _compute_accuracy_pct(hits: int, total: int) -> float:
    return round((hits / total) * 100, 1) if total > 0 else 0.0


def _accuracy_to_multiplier(accuracy_pct: float) -> float:
    """
    Maps accuracy percentage to a weight multiplier clamped to [0.5, 1.5].
    50% → 1.0 (baseline). Linear interpolation:
      0%  → 0.5
      50% → 1.0
      100% → 1.5
    """
    return max(0.5, min(1.5, (accuracy_pct / 100.0) * 1.0 + 0.5))


# ── SHIELDA Confidence Reset (S23.1.3 AC1) ───────────────────

def check_confidence_reset(db_path: str, agent: str, sigma_threshold: float = 3.0) -> bool:
    """
    Compute rolling 5-outcome std-dev of (actual_alpha - expected_alpha).
    If > sigma_threshold: increment confidence_reset_count + write CONFIDENCE_RESET event.

    Returns True if reset was triggered.
    """
    rows = get_recent_feedback(db_path, agent, limit=5)
    outcomes = [
        r for r in rows
        if r.get("actual_alpha") is not None and r.get("expected_alpha") is not None
    ]
    if len(outcomes) < 5:
        return False

    errors = [float(r["actual_alpha"]) - float(r["expected_alpha"]) for r in outcomes]
    mean = sum(errors) / len(errors)
    variance = sum((e - mean) ** 2 for e in errors) / len(errors)
    std_dev = math.sqrt(variance)

    if std_dev > sigma_threshold:
        logger.warning(
            "[AUDIT] Confidence reset triggered for %s: std_dev=%.3f > σ_threshold=%.3f",
            agent, std_dev, sigma_threshold,
        )
        state = get_confidence_state(db_path, agent)
        current_count = state.get("confidence_reset_count", 0) if state else 0
        upsert_confidence_state(
            db_path, agent,
            confidence_reset_count=current_count + 1,
        )
        write_audit_feedback(
            db_path, agent, None,
            event_type="CONFIDENCE_RESET",
            psv_vector=f"std_dev={std_dev:.3f}",
            penalty_weight=-1.0,
        )
        return True
    return False


# ── HITL lock enforcement (S23.1.3 AC3) ─────────────────────

def enforce_hitl_lock(db_path: str, config: dict, notifier=None) -> None:
    """
    Check if RAA has accumulated ≥ 3 FOUNDATIONAL_REPLACEMENT_BLOCK reprimands in 24h.
    If so: lock substitution tool.
    """
    hitl_cfg = config.get("feedback", {}).get("hitl_lock", {})
    meme_limit = int(hitl_cfg.get("meme_block_violations", 3))
    lock_hours = int(hitl_cfg.get("lock_duration_hours", 24))

    n_violations = count_reprimands_in_window(db_path, _RAA_AGENT, _FOUNDATIONAL_BLOCK, hours=24)
    if n_violations < meme_limit:
        return

    state = get_confidence_state(db_path, _RAA_AGENT)
    if state and state.get("substitution_tool_locked"):
        return  # Already locked

    locked_until = (datetime.now(timezone.utc) + timedelta(hours=lock_hours)).isoformat()
    upsert_confidence_state(
        db_path, _RAA_AGENT,
        substitution_tool_locked=1,
        locked_until_ts=locked_until,
    )
    write_audit_feedback(
        db_path, _RAA_AGENT, None,
        event_type="SUBSTITUTION_TOOL_LOCKED",
        psv_vector=f"violations={n_violations}|locked_until={locked_until}",
        penalty_weight=-3.0,
    )
    logger.warning(
        "[AUDIT] RAA substitution tool LOCKED for %dh after %d FOUNDATIONAL_REPLACEMENT_BLOCK violations",
        lock_hours, n_violations,
    )
    if notifier and _NOTIFIER_AVAILABLE:
        try:
            notifier.send_message(
                f"⛔ <b>HITL Lock Active</b>\n"
                f"RAA substitution tool locked for {lock_hours}h\n"
                f"Violations: {n_violations} in 24h\n"
                f"Expires: {locked_until[:16]} UTC\n"
                f"All PROPOSE_REPLACE calls now require manual HITL approval."
            )
        except Exception as exc:
            logger.warning("[AUDIT] Telegram alert failed: %s", exc)


# ── 24h Validation Window (S23.1.1 AC2) ─────────────────────

def evaluate_proposal_outcome(
    db_path: str,
    pair: str,
    expected_alpha: float,
    entry_price: float,
    psv_vector: str,
    config: dict,
) -> str:
    """
    Evaluate if a RAA universe proposal met its expected_alpha target 24h after entry.
    Returns outcome code: PASS / FAIL_PUMP_DETECTION / FLAT.
    """
    validation_window_h = int(
        config.get("feedback", {}).get("validation_window_h", 24)
    )
    conn = _get_conn(db_path)
    # Find latest trade for this pair as proxy for current price
    row = conn.execute(
        """SELECT exit_price FROM paper_trades
           WHERE pair=? AND exit_price IS NOT NULL
           ORDER BY exit_time DESC LIMIT 1""",
        (pair,),
    ).fetchone()
    conn.close()

    if not row or not entry_price:
        actual_alpha = 0.0
        outcome = _OUTCOME_FLAT
    else:
        exit_price = float(row[0])
        actual_alpha = ((exit_price - entry_price) / entry_price) * 100.0
        if actual_alpha >= expected_alpha * 0.5:
            outcome = _OUTCOME_PASS
        elif actual_alpha < 0:
            outcome = _OUTCOME_FAIL
        else:
            outcome = _OUTCOME_FLAT

    write_audit_feedback(
        db_path, _RAA_AGENT, pair,
        event_type="OUTCOME_VECTOR",
        psv_vector=psv_vector,
        expected_alpha=expected_alpha,
        actual_alpha=actual_alpha,
        outcome=outcome,
        penalty_weight=-2.0 if outcome == _OUTCOME_FAIL else 0.0,
    )
    logger.info(
        "[AUDIT] Proposal outcome for %s: expected=%.2f%% actual=%.2f%% → %s",
        pair, expected_alpha, actual_alpha, outcome,
    )
    return outcome


# ── Reprimand on 422 rejection (S23.1.1 AC3) ─────────────────

def write_rejection_reprimand(
    db_path: str,
    pair: str,
    rejection_reason: str,
    psv_vector: str = "",
    replace_class: Optional[str] = None,
) -> None:
    """Write a reprimand vector immediately on Risk Manager 422 / MEME_BLOCK rejection."""
    # Map rejection reason to event_type
    event_map = {
        "MEME_BLOCK": _FOUNDATIONAL_BLOCK,
        "UNIVERSE_AT_CAP": _REPRIMAND_UNIVERSE_CAP,
        "ALPHA_SPREAD_INSUFFICIENT": _REPRIMAND_ALPHA_INSUF,
        "DB_ERROR": _REPRIMAND_DB_ERROR,
    }
    event_type = event_map.get(rejection_reason, f"{rejection_reason}_REPRIMAND")
    penalty = -2.0 if rejection_reason == "MEME_BLOCK" else -0.5

    write_audit_feedback(
        db_path, _RAA_AGENT, pair,
        event_type=event_type,
        psv_vector=psv_vector,
        penalty_weight=penalty,
    )
    logger.info(
        "[AUDIT] Reprimand written: pair=%s reason=%s penalty=%.1f",
        pair, rejection_reason, penalty,
    )


# ── 24h Rollup (S23.1.1 AC4) ─────────────────────────────────

def run_24h_rollup(db_path: str, config: dict) -> None:
    """
    Compute and persist:
      - playbook_performance per (regime, playbook)
      - risk_decision_outcomes per pair
    From closed trades in the last 30 days.
    """
    since_iso = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    conn = _get_conn(db_path)

    # playbook_performance
    try:
        playbook_rows = conn.execute(
            """SELECT regime, playbook,
                      COUNT(*) as n,
                      SUM(CASE WHEN pnl_usd > 0 THEN 1 ELSE 0 END) as wins,
                      SUM(CASE WHEN pnl_usd > 0 THEN pnl_usd ELSE 0 END) as gross_profit,
                      SUM(CASE WHEN pnl_usd < 0 THEN ABS(pnl_usd) ELSE 0 END) as gross_loss,
                      MIN(pnl_pct) as worst_pct
               FROM paper_trades
               WHERE exit_time >= ? AND regime IS NOT NULL AND playbook IS NOT NULL
               GROUP BY regime, playbook""",
            (since_iso,),
        ).fetchall()

        for row in playbook_rows:
            regime, playbook, n, wins, gross_profit, gross_loss, worst_pct = row
            win_rate = (wins / n) if n > 0 else 0.0
            pf = (gross_profit / gross_loss) if gross_loss and gross_loss > 0 else (
                float("inf") if gross_profit > 0 else 0.0
            )
            upsert_playbook_performance(
                db_path, regime, playbook, n,
                win_rate=round(win_rate, 4),
                profit_factor=round(min(pf, 99.0), 4),
                max_drawdown=abs(float(worst_pct)) if worst_pct else 0.0,
            )
        logger.info("[AUDIT] 24h rollup: %d playbook_performance rows updated", len(playbook_rows))
    except Exception as exc:
        logger.warning("[AUDIT] playbook_performance rollup failed: %s", exc)

    # risk_decision_outcomes
    try:
        pair_rows = conn.execute(
            """SELECT pair,
                      COUNT(*) as n,
                      SUM(CASE WHEN exit_reason IN ('stop_loss','trailing_stop') THEN 1 ELSE 0 END) as sl_hits,
                      SUM(CASE WHEN exit_reason='take_profit' THEN 1 ELSE 0 END) as tp_hits,
                      AVG(CAST(
                        (julianday(exit_time) - julianday(entry_time)) * 86400 AS REAL
                      )) as avg_hold
               FROM paper_trades
               WHERE exit_time >= ?
               GROUP BY pair
               HAVING n >= 10""",
            (since_iso,),
        ).fetchall()

        for row in pair_rows:
            pair, n, sl_hits, tp_hits, avg_hold = row
            upsert_risk_decision_outcomes(
                db_path, pair, n,
                sl_hit_rate=round((sl_hits or 0) / n, 4),
                tp_hit_rate=round((tp_hits or 0) / n, 4),
                avg_hold_secs=float(avg_hold) if avg_hold else None,
            )
        logger.info("[AUDIT] 24h rollup: %d risk_decision_outcomes rows updated", len(pair_rows))
    except Exception as exc:
        logger.warning("[AUDIT] risk_decision_outcomes rollup failed: %s", exc)

    conn.close()

    # Telegram advisory for high SL-hit-rate pairs (S23.2.4 AC2)
    _send_sl_advisory(db_path, config)


def _send_sl_advisory(db_path: str, config: dict, notifier=None) -> None:
    advisory_cfg = config.get("feedback", {}).get("advisory", {})
    sl_alert_threshold = float(advisory_cfg.get("sl_hit_rate_alert", 0.60))
    min_samples = int(advisory_cfg.get("min_sample_count", 20))

    conn = _get_conn(db_path)
    rows = conn.execute(
        """SELECT pair, sl_hit_rate, sample_count FROM risk_decision_outcomes
           WHERE sl_hit_rate > ? AND sample_count >= ?
           ORDER BY sl_hit_rate DESC""",
        (sl_alert_threshold, min_samples),
    ).fetchall()
    conn.close()

    for pair, sl_rate, n in rows:
        msg = (
            f"⚠️ <b>ROM Advisory: High SL Rate</b>\n"
            f"Pair: {pair}\n"
            f"SL hit rate: {sl_rate:.1%} (n={n})\n"
            f"Recommendation: TIGHTEN_SL or RAISE_MIN_SCORE\n"
            f"Action: Edit config.yaml manually."
        )
        logger.warning("[AUDIT] SL advisory for %s: sl_hit_rate=%.1%% n=%d", pair, sl_rate, n)
        if notifier and _NOTIFIER_AVAILABLE:
            try:
                notifier.send_message(msg)
            except Exception as exc:
                logger.warning("[AUDIT] Telegram SL advisory failed: %s", exc)


# ── 6h Rollup — signal accuracy (S23.1.1 AC5) ────────────────

_SIGNAL_DRIVERS = [
    "rsi_oversold", "macd_histogram_turn", "macd_histogram_positive",
    "bb_lower_bounce", "fear_greed_fear", "fear_greed_extreme_fear",
    "adx_strong", "adx_ranging", "volume_ok", "rsi_divergence_bullish",
    "rsi_divergence_hidden", "obv_trend_up", "bb_squeeze_release",
    "hammer", "bullish_engulfing", "doji_at_support",
]


def run_6h_rollup(db_path: str) -> None:
    """
    For each (pair, driver), compute accuracy_pct from the last 30 days:
    accuracy = % of BUY signals where the trade was profitable.
    """
    since_iso = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    conn = _get_conn(db_path)

    # Get all pairs that have trades
    pair_rows = conn.execute(
        "SELECT DISTINCT pair FROM paper_trades WHERE exit_time >= ?", (since_iso,)
    ).fetchall()
    pairs = [r[0] for r in pair_rows]
    conn.close()

    # For each pair, attempt to correlate audit_events signal logs with trade outcomes
    # This is a best-effort approximation: accuracy_pct derived from trade outcomes per pair
    updated = 0
    for pair in pairs:
        conn = _get_conn(db_path)
        trades = conn.execute(
            """SELECT entry_time, exit_time, pnl_usd
               FROM paper_trades WHERE pair=? AND exit_time >= ?""",
            (pair, since_iso),
        ).fetchall()
        conn.close()

        if not trades:
            continue

        n_total = len(trades)
        n_profit = sum(1 for t in trades if float(t[2] or 0) > 0)
        base_accuracy = _compute_accuracy_pct(n_profit, n_total)

        for driver in _SIGNAL_DRIVERS:
            # Without per-driver signal history, use base win rate as a proxy.
            # In a future sprint this will be linked to audit_events signal records.
            multiplier = _accuracy_to_multiplier(base_accuracy)
            upsert_signal_accuracy(db_path, pair, driver, base_accuracy, multiplier, n_total)
            updated += 1

    logger.info("[AUDIT] 6h rollup: %d signal_accuracy records updated across %d pairs", updated, len(pairs))


# ─────────────────────────────────────────────────────────────
# AuditAgent class
# ─────────────────────────────────────────────────────────────


def write_reprimand(
    db_path: str,
    agent: str,
    pair: str,
    event_type: str,
    psv_vector: str = "",
    penalty_weight: float = -0.5,
) -> None:
    """General helper to write a negative reprimand to audit_feedback."""
    write_audit_feedback(
        db_path, agent, pair,
        event_type=event_type,
        psv_vector=psv_vector,
        penalty_weight=penalty_weight,
    )


def run_24h_validation_window(db_path: str, config: dict) -> None:
    """
    S23.1.1 AC6: Check universe_events ADD_PAIR against actual pnl_pct.
    If (expected_alpha > 5%) and (actual_alpha < 0), it is a FAIL_PUMP_DETECTION.
    """
    fb_conf = config.get("feedback", {})
    if not fb_conf.get("enabled", False):
        return

    window_h = fb_conf.get("validation_window_h", 24)
    threshold = fb_conf.get("expected_alpha_success_pct", 5.0)

    since_ts = (datetime.now(timezone.utc) - timedelta(hours=window_h)).isoformat()
    conn = _get_conn(db_path)

    # Find unprocessed ADD_PAIR events older than window_h
    rows = conn.execute(
        "SELECT id, pair, payload_json FROM universe_events "
        "WHERE event_type = 'ADD_PAIR' AND processed = 0 AND ts < ?",
        (since_ts,)
    ).fetchall()

    for row in rows:
        event_id, pair, payload_json = row["id"], row["pair"], row["payload_json"]
        payload = json.loads(payload_json)
        expected_alpha = payload.get("expected_alpha", 0.0)
        psv = payload.get("psv_vector", "")

        # Get actual pnl_pct from paper_trades if any
        trade = conn.execute(
            "SELECT pnl_pct FROM paper_trades WHERE pair = ? ORDER BY closed_at DESC LIMIT 1",
            (pair,)
        ).fetchone()

        if trade:
            actual_alpha = trade["pnl_pct"]
            outcome = _OUTCOME_PASS
            if expected_alpha >= threshold and actual_alpha < 0:
                outcome = _OUTCOME_FAIL

            # Write outcome to audit_feedback
            write_audit_feedback(
                db_path, _RAA_AGENT, pair,
                event_type='OUTCOME_VECTOR',
                psv_vector=psv,
                expected_alpha=expected_alpha,
                actual_alpha=actual_alpha,
                outcome=outcome,
            )

        # Mark as processed
        conn.execute("UPDATE universe_events SET processed = 1 WHERE id = ?", (event_id,))

    conn.commit()
    conn.close()

class AuditAgent:
    """
    Standalone audit process — runs independent review cycles.
    Cycle interval is derived from config.feedback validation_window_h.
    """

    def __init__(self, config: dict, db_path: str, port: int = 8094):
        self._config    = config
        self._db_path   = db_path
        self._port      = port
        self._running   = False
        self._last_24h  = 0.0
        self._last_6h   = 0.0

        poll_minutes = int(
            config.get("feedback", {}).get("validation_window_h", 24) * 60 / 2
        )
        self._poll_interval_secs = max(60, min(poll_minutes * 60, 3600))

        self._notifier = None
        if _NOTIFIER_AVAILABLE:
            try:
                self._notifier = _Notifier(config)
            except Exception:
                pass

        logger.info(
            "[AUDIT] AuditAgent initialised — db=%s port=%d poll_interval=%ds",
            db_path, port, self._poll_interval_secs,
        )

    async def run_cycle(self) -> None:
        now = time.time()
        logger.info("[AUDIT] === Cycle start ===")

        # Confidence reset check for RAA
        sigma = float(
            self._config.get("feedback", {}).get("confidence_reset", {}).get("sigma_threshold", 3.0)
        )
        check_confidence_reset(self._db_path, _RAA_AGENT, sigma_threshold=sigma)

        # HITL lock enforcement
        enforce_hitl_lock(self._db_path, self._config, notifier=self._notifier)

        # 6h rollup
        if now - self._last_6h >= 6 * 3600:
            run_6h_rollup(self._db_path)
            self._last_6h = now

        # 24h rollup
        if now - self._last_24h >= 24 * 3600:
            run_24h_rollup(self._db_path, self._config)
            self._last_24h = now

        logger.info("[AUDIT] === Cycle complete ===")

    async def run_loop(self) -> None:
        self._running = True
        _ensure_schema(self._db_path)

        # Start aiohttp health server
        if _AIOHTTP_AVAILABLE:
            asyncio.create_task(self._start_health_server())

        while self._running:
            try:
                await self.run_cycle()
            except Exception as exc:
                logger.error("[AUDIT] Cycle error: %s", exc, exc_info=True)
            await asyncio.sleep(self._poll_interval_secs)

    def stop(self) -> None:
        self._running = False
        logger.info("[AUDIT] Stop requested")

    # ── Health server ─────────────────────────────────────────

    async def _start_health_server(self) -> None:
        if not _AIOHTTP_AVAILABLE:
            return

        async def _health(_req):
            return _aio_web.Response(
                text=json.dumps({"status": "ok", "agent": "audit_agent"}),
                content_type="application/json",
            )

        app = _aio_web.Application()
        app.router.add_get("/health", _health)
        runner = _aio_web.AppRunner(app)
        await runner.setup()
        site = _aio_web.TCPSite(runner, "127.0.0.1", self._port)
        try:
            await site.start()
            logger.info("[AUDIT] Health endpoint: http://127.0.0.1:%d/health", self._port)
        except Exception as exc:
            logger.warning("[AUDIT] Health server failed to start: %s", exc)


# ─────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────

async def _main(config_path: str, db_path: str, port: int) -> None:
    with open(config_path) as f:
        config = yaml.safe_load(f)

    resolved_port = config.get("services", {}).get("audit_agent", {}).get("port", port)
    agent = AuditAgent(config, db_path, port=resolved_port)

    loop = asyncio.get_event_loop()
    import signal as _signal
    for sig in (_signal.SIGINT, _signal.SIGTERM):
        loop.add_signal_handler(sig, agent.stop)

    await agent.run_loop()


def main() -> None:  # pragma: no cover
    parser = argparse.ArgumentParser(description="Kryptos Audit Agent (S23)")
    parser.add_argument("--config", default="config.yaml", help="Path to config.yaml")
    parser.add_argument("--db", default="paper_trading.db", help="SQLite DB filename")
    parser.add_argument("--port", type=int, default=8094, help="Health endpoint port")
    args = parser.parse_args()
    asyncio.run(_main(args.config, args.db, args.port))


if __name__ == "__main__":
    main()
