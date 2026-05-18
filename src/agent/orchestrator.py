"""
Orchestrator — regime-to-playbook classifier for the Kryptos agent.

Story: S16.1.1 | Sprint: S5 | Epic: E16 — Orchestrator Agent — Meta-Planner

The Orchestrator selects a playbook each cycle based on current market regime
and portfolio state.  All other agents (QSA, AIE, ROM / RiskManager, TradingAgent)
consume the playbook from CycleContext rather than making independent decisions.

Playbooks
---------
momentum  : ADX median ≥ 25 AND regime trending_up → follow the trend with reduced thresholds
risk_off  : daily_pnl ≤ −3% OR kill_switch active  → conserve capital strictly
ranging   : all other cases (default)

The playbook is persisted to ``agent_state`` key ``current_playbook`` each cycle.
A Telegram alert is sent only when the playbook changes.

Design decision (ADR-008): Orchestrator lives in ``src/agent/`` because it is a thin
pure-Python selector operating on already-computed regime data.  It owns no I/O;
all DB writes and Telegram calls go through the same helpers used by main.py.
"""

from __future__ import annotations

import datetime
import logging
import time
from typing import Optional

logger = logging.getLogger(__name__)

_VALID_PLAYBOOKS = frozenset({"momentum", "ranging", "risk_off"})


class Orchestrator:
    """
    Stateless (between cycles) playbook selector.

    Instantiated once at agent startup; ``select_playbook()`` is called at the
    beginning of every ``run_cycle()`` before any other agent runs.
    """

    # Thresholds can be overridden in config["orchestrator"]
    _RISK_OFF_DAILY_PNL_PCT: float = -3.0
    _MOMENTUM_ADX_MIN: float = 25.0

    def __init__(self, config: dict, db_path: str, notifier=None) -> None:
        self._config   = config
        self._db_path  = db_path
        self._notifier = notifier
        orch_cfg = config.get("orchestrator", {})
        self._risk_off_threshold = float(
            orch_cfg.get("risk_off_daily_pnl_pct", self._RISK_OFF_DAILY_PNL_PCT)
        )
        self._momentum_adx_min = float(
            orch_cfg.get("momentum_adx_min", self._MOMENTUM_ADX_MIN)
        )
        # Last playbook written to DB (in-memory cache to detect transitions)
        self._last_playbook: str = ""

    # ── public API ────────────────────────────────────────────────────────────

    def select_playbook(
        self,
        regime_state: str,
        adx_median: float,
        daily_pnl_pct: float,
        kill_switch: bool = False,
    ) -> str:
        """
        Classify current market conditions into a playbook.

        S16.1.1 AC1-AC4

        Args:
            regime_state:  one of 'trending_up', 'trending_down', 'ranging', 'volatile', 'unknown'
            adx_median:    median ADX across all tracked pairs this cycle
            daily_pnl_pct: portfolio daily P&L % (can be negative)
            kill_switch:   True when global kill-switch is active

        Returns:
            Playbook string: 'momentum' | 'ranging' | 'risk_off'
        """
        # AC2: risk_off when daily loss ≥ threshold OR kill switch
        if kill_switch or daily_pnl_pct <= self._risk_off_threshold:
            playbook = "risk_off"
        # AC3: momentum when ADX ≥ threshold AND regime trending up
        elif adx_median >= self._momentum_adx_min and regime_state == "trending_up":
            playbook = "momentum"
        # AC4: ranging default
        else:
            playbook = "ranging"

        self._persist_playbook(playbook)
        return playbook

    def get_current_playbook(self) -> str:
        """Return the last persisted playbook from agent_state, or 'ranging' as default."""
        if not self._db_path:
            return self._last_playbook or "ranging"
        try:
            from src.storage.database import get_connection
            conn = get_connection(self._db_path)
            row = conn.execute(
                "SELECT value FROM agent_state WHERE key='current_playbook'"
            ).fetchone()
            conn.close()
            return str(row["value"]) if row else (self._last_playbook or "ranging")
        except Exception as exc:
            logger.debug("[ORCH] Could not load current_playbook: %s", exc)
            return self._last_playbook or "ranging"

    # ── private helpers ───────────────────────────────────────────────────────

    def _persist_playbook(self, playbook: str) -> None:
        """
        Write playbook to agent_state.  On transition, emit log + Telegram alert.
        S16.1.1 AC5-AC6.
        """
        old_playbook = self._last_playbook

        if playbook != old_playbook:
            logger.info("[ORCH] Playbook: %s → %s", old_playbook or "<init>", playbook)
            if self._notifier and old_playbook:
                # AC6: alert only on change, not every cycle
                try:
                    self._notifier.send_playbook_changed(old_playbook, playbook)
                except Exception as exc:
                    logger.debug("[ORCH] Telegram playbook alert failed: %s", exc)

        self._last_playbook = playbook

        if not self._db_path:
            return
        try:
            from src.storage.database import get_connection
            conn = get_connection(self._db_path)
            conn.execute(
                "INSERT OR REPLACE INTO agent_state (key, value) VALUES (?, ?)",
                ("current_playbook", playbook),
            )
            conn.commit()
            conn.close()
        except Exception as exc:
            logger.warning("[ORCH] Failed to persist playbook to agent_state: %s", exc)

    # ── S23.2.1 Playbook feedback bias ───────────────────────────────────────

    def get_playbook_bias(self, regime: str) -> dict:
        """
        S23.2.1 AC4 — Return priority multipliers per playbook for ``regime`` based on
        historical performance stored in ``playbook_performance``.

        Returns a dict ``{playbook_name: multiplier}`` where:
          - multiplier=2 when sample_count >= 10 AND profit_factor > 1.2 (strong evidence)
          - multiplier=1 when sample_count >= 10 but profit_factor <= 1.2
          - Playbooks with sample_count < 10 are excluded (insufficient data)
          - Returns ``{}`` when no qualifying rows exist for this regime.

        Callers use the multiplier as a priority hint inside ``select_playbook()``.
        This is read-only — does NOT persist ``current_playbook``.

        Args:
            regime: current regime string (e.g. 'trending_up', 'ranging')

        Returns:
            Dict of {playbook: multiplier} for all qualifying playbooks.
        """
        if not self._db_path:
            return {}
        try:
            from src.storage.database import get_connection
            conn = get_connection(self._db_path)
            rows = conn.execute(
                """SELECT playbook, profit_factor, sample_count
                   FROM playbook_performance
                   WHERE regime=? AND sample_count >= 10
                   ORDER BY profit_factor DESC""",
                (regime,),
            ).fetchall()
            conn.close()
            if not rows:
                return {}
            result = {}
            for row in rows:
                pf = float(row["profit_factor"])
                multiplier = 2 if pf > 1.2 else 1
                result[row["playbook"]] = multiplier
                logger.debug(
                    "[ORCH] Playbook bias regime=%s playbook=%s PF=%.2f n=%d → mult=%d",
                    regime, row["playbook"], pf, row["sample_count"], multiplier,
                )
            return result
        except Exception as exc:
            logger.debug("[ORCH] get_playbook_bias failed: %s", exc)
        return {}

