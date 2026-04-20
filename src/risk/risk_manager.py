"""
Risk Manager — hard-coded validation gate.
Every proposed trade must pass through here before execution.
The 5% stop-loss, configurable take-profit, 30% position cap, and daily
loss limit are enforced deterministically — NOT by the LLM.
"""

import logging
import time
import datetime
from typing import Optional

from src.utils.timing import timed

logger = logging.getLogger(__name__)

ALLOWED_TAKE_PROFIT_PCTS = [5, 8, 12, 16, 20, 25]


def validate_config(config: dict) -> None:
    """
    Called once at startup. Raises ValueError if any take-profit value
    is not in the allowed set. Prevents misconfigured agents from starting.
    Also validates mutually exclusive features (trailing_stop / breakeven_stop)
    and the persona config schema (S12.1.1 — AC4).
    """
    allowed = config.get("trading", {}).get(
        "allowed_take_profit_pcts", ALLOWED_TAKE_PROFIT_PCTS
    )
    global_tp = config.get("trading", {}).get("take_profit_pct")
    if global_tp is not None and global_tp not in allowed:
        raise ValueError(
            f"Invalid global take_profit_pct: {global_tp}. "
            f"Allowed: {allowed}"
        )
    for pair_cfg in config.get("trading", {}).get("pairs", []):
        pair_tp = pair_cfg.get("take_profit_pct")
        if pair_tp is not None and pair_tp not in allowed:
            raise ValueError(
                f"Invalid take_profit_pct for {pair_cfg['pair']}: {pair_tp}. "
                f"Allowed: {allowed}"
            )
    # Trailing stop and breakeven stop are mutually exclusive (S12.3.1)
    trailing_enabled = config.get("trailing_stop", {}).get("enabled", False)
    breakeven_enabled = config.get("breakeven_stop", {}).get("enabled", False)
    if trailing_enabled and breakeven_enabled:
        raise ValueError(
            "trailing_stop and breakeven_stop cannot both be enabled simultaneously. "
            "Disable one in config.yaml."
        )
    # Persona config schema validation (S12.1.1 — AC4)
    _REQUIRED_PERSONA_KEYS = {
        "buy_min_score", "max_open_positions", "max_position_pct",
        "min_profit_floor_pct", "rsi_overbought_veto",
        "momentum_bypass_rsi", "momentum_bypass_adx",
        "reallocation_enabled", "reallocation_max_pct_6h",
        "llm_temperature", "llm_max_tokens",
        "llm_system_role", "velocity_circuit_breaker_pct", "velocity_halt_hours",
        # S15.2.2 — PF escalation suspension
        "pf_escalation_momentum_suspend",
        # S15.2.3 — Early Momentum score reduction
        "early_momentum_score_reduction", "early_momentum_rsi_min",
        "early_momentum_rsi_max", "early_momentum_adx_min",
    }
    _VALID_PERSONAS = {"conservative", "medium", "high"}
    agent_cfg = config.get("agent", {})
    active_persona = agent_cfg.get("persona")
    if active_persona is not None and active_persona not in _VALID_PERSONAS:
        raise ValueError(
            f"Invalid agent.persona: '{active_persona}'. "
            f"Must be one of: {sorted(_VALID_PERSONAS)}"
        )
    personas_cfg = config.get("personas", {})
    if not personas_cfg:
        raise ValueError(
            "Missing 'personas:' block in config.yaml. "
            "All three profiles (conservative, medium, high) are required."
        )
    for persona_name in _VALID_PERSONAS:
        if persona_name not in personas_cfg:
            raise ValueError(
                f"Missing persona profile '{persona_name}' in config.yaml personas block."
            )
        profile = personas_cfg[persona_name]
        missing = _REQUIRED_PERSONA_KEYS - set(profile.keys())
        if missing:
            raise ValueError(
                f"Persona '{persona_name}' is missing required keys: {sorted(missing)}. "
                f"Add the missing keys to config.yaml under personas.{persona_name}."
            )
    # Sanity check: max_open_positions × max_position_pct must not exceed deployable capital
    trading = config.get("trading", {})
    max_pos = trading.get("max_open_positions", 3)
    base_pct = trading.get("max_position_pct", 20)
    reserve_pct = config.get("risk", {}).get("min_cash_reserve_pct", 5)
    max_deployable_pct = 100 - reserve_pct
    if max_pos * base_pct > max_deployable_pct:
        logger.warning(
            "[CONFIG] max_open_positions (%d) × max_position_pct (%d%%) = %d%% exceeds "
            "max_deployable (%d%% after %.0f%% reserve). "
            "Suggest reducing max_open_positions to %d.",
            max_pos, base_pct, max_pos * base_pct, max_deployable_pct, reserve_pct,
            int(max_deployable_pct // base_pct),
        )
    logger.info("Config validation passed — all take-profit values and persona profiles are valid")


class RiskManager:
    """
    Risk validation with DB-persisted circuit breaker.
    State survives agent restarts — consecutive stop count and triggered timestamp
    are read from and written to the trading DB (agent_state table).
    """

    def __init__(self, config: dict, db_path: Optional[str] = None):
        trading = config.get("trading", {})
        risk    = config.get("risk", {})
        self._stop_loss_pct       = trading.get("stop_loss_pct", 5)
        self._global_tp_pct       = trading.get("take_profit_pct", 10)
        self._min_profit_floor_pct= trading.get("min_profit_floor_pct", 1.0)
        self._early_sell_min_tp_proximity_pct = trading.get("early_sell_min_tp_proximity_pct", 80)
        self._max_position_pct    = trading.get("max_position_pct", 30)
        self._max_open_positions  = trading.get("max_open_positions", 3)
        self._daily_loss_limit_pct= risk.get("daily_loss_limit_pct", 10)
        self._min_cash_reserve_pct= risk.get("min_cash_reserve_pct", 10)

        # ATR-based stop-loss at entry (S12.4.1 — #86)
        atr_sl_cfg = config.get("atr_stop_loss", {})
        self._atr_sl_enabled    = atr_sl_cfg.get("enabled", False)
        self._atr_sl_multiplier = atr_sl_cfg.get("atr_multiplier", 1.5)
        self._atr_sl_max_pct    = atr_sl_cfg.get("max_stop_loss_pct", 5.0)
        self._atr_sl_min_pct    = atr_sl_cfg.get("min_stop_loss_pct", 1.0)

        # Fat finger guards
        self._min_order_usd = risk.get("min_order_usd", 5.0)
        self._max_token_volume_per_trade = risk.get("max_token_volume_per_trade", 500_000)
        self._flash_crash_tolerance_pct = risk.get("flash_crash_tolerance_pct", 15.0)

        # Time-of-Day filter
        trading_hours = trading.get("allowed_trading_hours", {})
        self._trading_hours_enabled = trading_hours.get("enabled", False)
        self._trading_start_hour = trading_hours.get("start_hour_utc", 12)
        self._trading_end_hour = trading_hours.get("end_hour_utc", 20)

        # Circuit breaker config — thresholds from config.yaml
        cb_cfg = risk.get("circuit_breaker", {})
        self._cb_enabled          = cb_cfg.get("enabled", True)
        self._cb_max_consec_stops = cb_cfg.get("consecutive_stops", 3)
        # Graduated backoff (#143): pause_tiers_hours takes priority over flat pause_hours
        if "pause_tiers_hours" in cb_cfg:
            self._cb_pause_tiers  = [h * 3600 for h in cb_cfg["pause_tiers_hours"]]
        else:
            flat = cb_cfg.get("pause_hours", 4) * 3600
            self._cb_pause_tiers  = [flat, flat, flat]
        self._cb_tier_reset_hours = cb_cfg.get("tier_reset_hours", 24)
        # Keep _cb_pause_secs for record_stop_loss logging (max tier)
        self._cb_pause_secs       = max(self._cb_pause_tiers)

        # Correlation guard (#139)
        self._correlation_clusters   = risk.get("correlation_clusters", [])
        self._max_cluster_positions  = risk.get("max_cluster_positions", 2)
        self._cluster_size_penalty   = risk.get("cluster_size_penalty", 0.5)

        # Drawdown recovery mode (#182)
        recovery_cfg = risk.get("drawdown_recovery", {})
        self._recovery_enabled       = recovery_cfg.get("enabled", False)
        self._recovery_trigger_pct   = recovery_cfg.get("trigger_pct", 3.0)
        self._recovery_exit_pct      = recovery_cfg.get("exit_pct", 1.5)
        self._recovery_allowed_pairs = recovery_cfg.get("allowed_pairs", ["BTC/USD", "ETH/USD", "BNB/USD"])
        self._recovery_max_pos_pct   = recovery_cfg.get("max_position_pct_override", 10)

        # Cycle-top guard (#205)
        cycle_top_cfg = risk.get("cycle_top_guard", {})
        self._cycle_top_guard_enabled = cycle_top_cfg.get("enabled", False)
        self._cycle_top_active = False
        self._cycle_top_data: dict = {}
        self._pair_tiers = {
            pair_cfg["pair"]: int(pair_cfg.get("pair_tier", 0) or 0)
            for pair_cfg in trading.get("pairs", [])
        }

        # DB path — used to query trade history for circuit breaker
        self._db_path = db_path

        # S15.1.1, S15.2.1 — full persona config (set by apply_persona_config each cycle)
        self._persona_config: dict = {}

        # Build per-pair TP map
        self._pair_tp: dict = {}
        for p in trading.get("pairs", []):
            self._pair_tp[p["pair"]] = p.get("take_profit_pct", self._global_tp_pct)

    def set_cycle_top_state(self, active: bool, data: Optional[dict] = None) -> None:
        """Update the current cycle-top guard state for validate_buy()."""
        self._cycle_top_active = bool(active and self._cycle_top_guard_enabled)
        self._cycle_top_data = data or {}

    def apply_persona_config(self, persona_config: dict) -> None:
        """
        Update persona-driven thresholds from the active CycleContext.

        Called once per cycle in main.py after CycleContext is constructed.
        Overrides the three risk fields that vary by persona so validate_buy()
        and validate_sell() operate under the correct persona thresholds.
        Full config stored as _persona_config for S15.1.1 + S15.2.1 access.

        Args:
            persona_config: The dict at config["personas"][active_persona].

        Story: S12.1.2 — Persona runtime injection into CycleContext (AC3)
        """
        self._persona_config: dict = dict(persona_config)  # S15.1.1, S15.2.1
        if "max_open_positions" in persona_config:
            self._max_open_positions = int(persona_config["max_open_positions"])
        if "max_position_pct" in persona_config:
            self._max_position_pct = float(persona_config["max_position_pct"])
        if "min_profit_floor_pct" in persona_config:
            self._min_profit_floor_pct = float(persona_config["min_profit_floor_pct"])
        logger.debug(
            "[PERSONA] RiskManager thresholds applied — persona=%s "
            "max_open=%d max_pos=%.0f%% min_floor=%.2f%%",
            persona_config.get("_persona_name", "?"),
            self._max_open_positions,
            self._max_position_pct,
            self._min_profit_floor_pct,
        )

    # ── Circuit breaker — derived from trade history ──────────────────────────
    # Queries the last N trades that closed within the pause window.
    # If all N are stop_loss AND the most recent happened within pause_hours → tripped.
    # An old streak (all stops but >4 hours ago) does not block new trades.

    def _query_recent_exits(self, since_epoch: float) -> list:
        """
        Return the most recent `consecutive_stops` closed trades that occurred
        after `since_epoch`, newest-first: [{"exit_reason": str, "closed_at": str}, ...]
        Returns [] if DB unavailable.
        """
        if not self._db_path:
            return []
        try:
            from src.storage.database import get_connection
            from datetime import datetime, timezone
            conn = get_connection(self._db_path)
            trades_table = "paper_trades" if "paper" in self._db_path else "live_trades"
            since_iso = datetime.fromtimestamp(since_epoch, tz=timezone.utc).isoformat()
            rows = conn.execute(
                f"SELECT exit_reason, closed_at FROM {trades_table} "
                f"WHERE closed_at >= ? "
                f"ORDER BY closed_at DESC LIMIT ?",
                (since_iso, self._cb_max_consec_stops),
            ).fetchall()
            conn.close()
            return [{"exit_reason": r["exit_reason"], "closed_at": r["closed_at"]} for r in rows]
        except Exception as e:
            logger.warning("[CIRCUIT] Failed to query trade history: %s", e)
            return []

    def _count_circuit_fires_in_window(self, window_hours: float) -> int:
        """
        Count how many times the circuit breaker has fired (completed N consecutive stop-losses)
        within the last window_hours. Used to determine graduated pause tier (#143).
        """
        if not self._db_path:
            return 0
        try:
            from src.storage.database import get_connection
            from datetime import datetime, timezone
            conn = get_connection(self._db_path)
            trades_table = "paper_trades" if "paper" in self._db_path else "live_trades"
            since_iso = datetime.fromtimestamp(
                time.time() - window_hours * 3600, tz=timezone.utc
            ).isoformat()
            rows = conn.execute(
                f"SELECT exit_reason FROM {trades_table} "
                f"WHERE closed_at >= ? ORDER BY closed_at ASC",
                (since_iso,),
            ).fetchall()
            conn.close()
            # Walk through exits: count complete streaks of N consecutive stop-losses
            fires = 0
            streak = 0
            for row in rows:
                if row["exit_reason"] in ("stop_loss", "fallback_stop_loss"):
                    streak += 1
                    if streak >= self._cb_max_consec_stops:
                        fires += 1
                        streak = 0  # reset after each complete fire
                else:
                    streak = 0
            return fires
        except Exception as e:
            logger.warning("[CIRCUIT] Failed to count fires: %s", e)
            return 0

    def _get_correlation_cluster(self, pair: str) -> Optional[dict]:
        """Return cluster info {name, pairs} if pair belongs to a configured cluster, else None."""
        for cluster in self._correlation_clusters:
            if pair in cluster.get("pairs", []):
                return cluster
        return None

    def _get_open_pairs(self) -> list:
        """Return list of currently open pair names from DB. Returns [] if DB unavailable."""
        if not self._db_path:
            return []
        try:
            from src.storage.database import get_connection
            conn = get_connection(self._db_path)
            positions_table = "paper_positions" if "paper" in self._db_path else "live_positions"
            rows = conn.execute(
                f"SELECT pair FROM {positions_table} WHERE status='open'"
            ).fetchall()
            conn.close()
            return [r["pair"] for r in rows]
        except Exception as e:
            logger.warning("[RISK] Failed to query open positions: %s", e)
            return []

    def is_circuit_open(self) -> tuple:
        """
        Returns (tripped: bool, resume_in_secs: float).

        Tripped when: the last N trades within the current tier's pause window are ALL stop_loss.
        Pause duration is graduated (#143): 1st fire→1h, 2nd→2h, 3rd+→4h (within tier_reset_hours).
        """
        if not self._cb_enabled:
            return False, 0.0

        # --- #143: Determine pause duration based on fires in last tier_reset_hours ---
        fires = self._count_circuit_fires_in_window(self._cb_tier_reset_hours)
        tier_idx = min(max(fires - 1, 0), len(self._cb_pause_tiers) - 1)
        pause_secs = self._cb_pause_tiers[tier_idx]

        window_start = time.time() - pause_secs
        recent = self._query_recent_exits(since_epoch=window_start)

        if len(recent) < self._cb_max_consec_stops:
            return False, 0.0

        all_stops = all(r["exit_reason"] in ("stop_loss", "fallback_stop_loss") for r in recent)
        if not all_stops:
            return False, 0.0

        # All N consecutive stop-losses happened within the pause window.
        # resume_in = time remaining until the oldest of the N stops falls outside the window.
        try:
            from datetime import datetime, timezone
            most_recent_ts = datetime.fromisoformat(recent[0]["closed_at"]).timestamp()
        except Exception:
            most_recent_ts = time.time()

        resume_in = (most_recent_ts + pause_secs) - time.time()
        if resume_in <= 0:
            return False, 0.0

        logger.debug(
            "[CIRCUIT] Active (tier %d, pause %.0fh) — %d consecutive stop-losses, resumes in %.0f min",
            tier_idx + 1, pause_secs / 3600, self._cb_max_consec_stops, resume_in / 60,
        )
        return True, resume_in

    def record_stop_loss(self, pair: str) -> bool:
        """
        Call after every stop-loss exit to log and check if circuit just tripped.
        No DB write needed — the trade record already exists in paper_trades/live_trades.
        Returns True if circuit breaker just tripped.
        """
        if not self._cb_enabled:
            return False
        tripped, _ = self.is_circuit_open()
        if tripped:
            logger.warning(
                "[CIRCUIT] Circuit breaker TRIPPED — %d consecutive stop-losses (last: %s). "
                "All buys paused for %.0f hours.",
                self._cb_max_consec_stops, pair, self._cb_pause_secs / 3600,
            )
            return True
        window_start = time.time() - self._cb_pause_secs
        recent = self._query_recent_exits(since_epoch=window_start)
        stop_streak = sum(1 for r in recent if r["exit_reason"] in ("stop_loss", "fallback_stop_loss"))
        logger.info(
            "[CIRCUIT] Stop-loss recorded for %s — consecutive stops: %d/%d",
            pair, stop_streak, self._cb_max_consec_stops,
        )
        return False

    def record_profitable_exit(self) -> None:
        """No-op — a profitable exit breaks the streak automatically via trade history."""
        pass

    def is_in_drawdown_recovery(self, daily_pnl_pct: float) -> bool:
        """
        Returns True when the daily P&L has fallen below the recovery trigger threshold.
        Used to restrict new buys to major liquid pairs at reduced size (#182).

        daily_pnl_pct: signed percentage, e.g. -3.5 means a 3.5% loss today.
        """
        if not self._recovery_enabled:
            return False
        return daily_pnl_pct <= -self._recovery_trigger_pct

    def get_stop_loss_pct(self, pair: str, atr: float = None, price: float = None) -> float:
        """Return SL % for this pair. Uses ATR-based formula when enabled (S12.4.1)."""
        if self._atr_sl_enabled and atr and price and price > 0:
            atr_sl_pct = (self._atr_sl_multiplier * atr / price) * 100
            return float(max(self._atr_sl_min_pct, min(self._atr_sl_max_pct, round(atr_sl_pct, 2))))
        return self._stop_loss_pct

    def get_take_profit_pct(self, pair: str) -> float:
        return self._pair_tp.get(pair, self._global_tp_pct)

    def calculate_stop_loss_price(self, entry_price: float, pair: str, override_pct: Optional[float] = None) -> float:
        sl_pct = override_pct if override_pct is not None else self._stop_loss_pct
        return round(entry_price * (1 - sl_pct / 100), 8)

    def calculate_take_profit_price(self, entry_price: float, pair: str, override_pct: Optional[float] = None) -> float:
        tp_pct = override_pct if override_pct is not None else self.get_take_profit_pct(pair)
        return round(entry_price * (1 + tp_pct / 100), 8)

    def get_prune_candidate(
        self,
        open_positions: list,
        incoming_score: int = 0,
    ) -> Optional[str]:
        """
        S15.1.1 — Identify the weakest open position eligible for reallocation.

        A position is eligible when ALL apply:
          - ADX < 25 (trend has faded — momentum stalled)
          - P&L% < _min_profit_floor_pct * 1.5 (not worth holding as-is)
          - P&L% > -(stop_loss_pct / 2) (not a deep loss — closing would not realise a large hit)

        Returns the pair name of the weakest eligible position (lowest ADX, then lowest P&L%),
        or None when reallocation is disabled or no eligible position exists.

        Args:
            open_positions: list of dicts with keys: pair, adx, pnl_pct
            incoming_score: buy score of the incoming signal (unused for now, reserved for AC4)

        Story: S15.1.1
        """
        persona_cfg = getattr(self, "_persona_config", {})
        if not persona_cfg.get("reallocation_enabled", False):
            return None

        floor_threshold = self._min_profit_floor_pct * 1.5
        deep_loss_guard = -(self._stop_loss_pct / 2)

        eligible = [
            pos for pos in open_positions
            if (
                float(pos.get("adx") or 999) < 25
                and float(pos.get("pnl_pct") or 0) < floor_threshold
                and float(pos.get("pnl_pct") or 0) > deep_loss_guard
            )
        ]
        if not eligible:
            return None

        # Weakest: lowest ADX first (most range-bound); then lowest P&L% as tiebreaker
        eligible.sort(key=lambda p: (float(p.get("adx") or 999), float(p.get("pnl_pct") or 0)))
        prune_pair = eligible[0].get("pair")
        logger.info(
            "[ROM] Prune candidate identified: %s (adx=%.1f, pnl_pct=%.2f%%)",
            prune_pair,
            float(eligible[0].get("adx") or 999),
            float(eligible[0].get("pnl_pct") or 0),
        )
        return prune_pair

    def get_effective_min_score(
        self,
        pair: str,
        playbook: str,
        pair_cfg: dict,
        indicators: dict,
        sig_cfg: dict,
    ) -> int:
        """
        S15.2.2 / S15.2.3 — Compute the effective buy_min_score for a pair, incorporating:
          1. Per-pair override from config (existing #128 behaviour).
          2. Profit Factor escalation — suspended when playbook='momentum' AND
             pf_escalation_momentum_suspend=true in persona config (S15.2.2).
          3. Early Momentum score reduction — when RSI ∈ [rsi_min, rsi_max] AND
             ADX > early_momentum_adx_min (S15.2.3).  Floor: 1.

        Args:
            pair:       pair name (e.g. 'BTC/USD')
            playbook:   current playbook ('momentum' | 'ranging' | 'risk_off' | 'standard')
            pair_cfg:   the per-pair config dict from trading.pairs[]
            indicators: current indicators dict for this pair (contains profit_factor, rsi_14, adx_14)
            sig_cfg:    signals config section (for global buy_min_score, PF thresholds)

        Returns:
            Effective buy_min_score (int ≥ 1)

        Stories: S15.2.2, S15.2.3
        """
        persona_cfg = getattr(self, "_persona_config", {})

        # Base score: per-pair override → global default
        base_score = int(pair_cfg.get("buy_min_score", sig_cfg.get("buy_min_score", 5)))

        # ── Step 1: Profit Factor escalation (S15.2.2) ──────────────────────────
        pf_cfg = sig_cfg.get("profit_factor_escalation", {})
        pf_escalation_enabled = bool(pf_cfg.get("enabled", False))
        pf_suspend = bool(persona_cfg.get("pf_escalation_momentum_suspend", False))
        pf_delta = 0

        if pf_escalation_enabled and not (pf_suspend and playbook == "momentum"):
            pf = indicators.get("profit_factor")
            if pf is not None:
                pf_warn   = float(pf_cfg.get("pf_warn_threshold", 1.0))
                pf_severe = float(pf_cfg.get("pf_severe_threshold", 0.7))
                min_trades = int(pf_cfg.get("min_trades", 10))
                n_trades = int(indicators.get("pf_trade_count", 0))
                if n_trades >= min_trades:
                    if pf < pf_severe:
                        pf_delta = 2
                    elif pf < pf_warn:
                        pf_delta = 1
        elif pf_escalation_enabled and pf_suspend and playbook == "momentum":
            pf = indicators.get("profit_factor")
            if pf is not None and float(pf) < float(pf_cfg.get("pf_warn_threshold", 1.0)):
                logger.info(
                    "[ROM] PF_ESCALATION SUSPENDED — playbook=momentum; %s using persona "
                    "default score %d (PF=%.2f)",
                    pair, base_score, float(pf),
                )

        effective = base_score + pf_delta

        # ── Step 2: Early Momentum score reduction (S15.2.3) ────────────────────
        em_reduction = int(persona_cfg.get("early_momentum_score_reduction", 0))
        if em_reduction > 0:
            rsi = indicators.get("rsi_14")
            adx = indicators.get("adx_14")
            em_rsi_min = float(persona_cfg.get("early_momentum_rsi_min", 50))
            em_rsi_max = float(persona_cfg.get("early_momentum_rsi_max", 65))
            em_adx_min = float(persona_cfg.get("early_momentum_adx_min", 999))
            if (
                rsi is not None and adx is not None
                and em_rsi_min <= float(rsi) <= em_rsi_max
                and float(adx) > em_adx_min
            ):
                effective = max(1, effective - em_reduction)
                logger.info(
                    "[ROM] EARLY_MOMENTUM %s RSI=%.0f ADX=%.0f — "
                    "min_score reduced to %d",
                    pair, float(rsi), float(adx), effective,
                )

        # ── Step 3: Playbook score delta (S16.1.2 AC2) ──────────────────────────
        # ranging  → +1 (filter noise in choppy markets)
        # risk_off → +2 (block casual buys in adverse conditions)
        # momentum → 0  (no extra bar — trend is confirmed)
        _playbook_score_delta = {"ranging": 1, "risk_off": 2, "momentum": 0, "standard": 0}
        effective += _playbook_score_delta.get(playbook, 0)
        if playbook in ("ranging", "risk_off"):
            logger.debug(
                "[ROM] Playbook score delta applied — %s playbook=%s +%d → effective=%d",
                pair, playbook, _playbook_score_delta[playbook], effective,
            )

        return effective

    def check_velocity_circuit(
        self,
        portfolio_value: float,
        db_path: str,
    ) -> tuple:
        """
        S15.3.1 — Return (tripped: bool, resume_until_epoch: float).

        Velocity circuit trips when the hourly loss rate exceeds the persona's
        velocity_circuit_breaker_pct.  Halt duration = velocity_halt_hours, persisted
        to agent_state as 'velocity_circuit_open_until'.

        Args:
            portfolio_value:  current total portfolio USD value
            db_path:          path to the SQLite trading DB

        Returns:
            (tripped: bool, resume_until_epoch: float)
            When tripped=True, resume_until_epoch is a Unix timestamp.
            When tripped=False, resume_until_epoch is 0.0.

        Story: S15.3.1
        """
        persona_cfg = getattr(self, "_persona_config", {})
        threshold_pct = float(persona_cfg.get("velocity_circuit_breaker_pct", 3.0))
        halt_hours    = float(persona_cfg.get("velocity_halt_hours", 4.0))

        if not db_path:
            return False, 0.0

        try:
            from src.storage.database import get_connection
            conn = get_connection(db_path)

            # Check if already tripped (persisted halt still active)
            row = conn.execute(
                "SELECT value FROM agent_state WHERE key='velocity_circuit_open_until'"
            ).fetchone()
            if row:
                resume_until = float(row["value"])
                if resume_until > time.time():
                    conn.close()
                    logger.debug(
                        "[ROM] VELOCITY CIRCUIT still open — resumes at %s",
                        datetime.datetime.fromtimestamp(resume_until).isoformat(),
                    )
                    return True, resume_until
                # Halt expired — clear it
                conn.execute(
                    "DELETE FROM agent_state WHERE key='velocity_circuit_open_until'"
                )
                conn.commit()

            # Compute losses in the last 60 minutes
            since_iso = datetime.datetime.fromtimestamp(
                time.time() - 3600, tz=datetime.timezone.utc
            ).isoformat()
            trades_table = "paper_trades" if "paper" in db_path else "live_trades"
            rows = conn.execute(
                f"SELECT pnl_usd FROM {trades_table} "
                f"WHERE closed_at >= ? AND pnl_usd < 0",
                (since_iso,),
            ).fetchall()
            conn.close()

            losses_last_hour = sum(float(r["pnl_usd"] or 0) for r in rows)
            if portfolio_value <= 0:
                return False, 0.0

            loss_rate_pct = abs(losses_last_hour) / portfolio_value * 100
            if loss_rate_pct >= threshold_pct:
                resume_until = time.time() + halt_hours * 3600
                # Persist halt
                conn2 = get_connection(db_path)
                conn2.execute(
                    "INSERT OR REPLACE INTO agent_state(key, value) VALUES(?,?)",
                    ("velocity_circuit_open_until", str(resume_until)),
                )
                conn2.commit()
                conn2.close()
                logger.warning(
                    "[ROM] VELOCITY CIRCUIT OPEN — loss_rate=%.2f%% >= %.2f%% threshold; "
                    "halting buys for %.1fh",
                    loss_rate_pct, threshold_pct, halt_hours,
                )
                return True, resume_until

            return False, 0.0

        except Exception as exc:
            logger.warning("[ROM] velocity_circuit check failed: %s", exc)
            return False, 0.0
    def validate_buy(
        self,
        pair: str,
        proposed_usd: float,
        portfolio_balance_usd: float,
        available_cash_usd: float,
        open_positions_count: int,
        daily_loss_usd: float,
        starting_balance_usd: float,
        current_price: float = 0.0,
        baseline_price: float = 0.0,
        candle_timestamp_sec: float = 0.0,
        rsi: Optional[float] = None,
        adx: Optional[float] = None,
        playbook: str = "standard",
    ) -> tuple:
        """
        Returns (approved: bool, reason: str, capped_amount: float)
        The capped_amount is the actual amount to trade after applying the 30% cap.

        S15.2.1 — Persona RSI veto with optional momentum bypass:
          - Standard playbook: RSI >= 70 is always blocked.
          - Momentum playbook: RSI veto threshold is raised to persona's
            momentum_bypass_rsi (e.g. 75 for medium, 80 for high) when
            ADX > persona's momentum_bypass_adx.
          - Conservative persona: momentum_bypass_adx=999 → bypass never fires.
        """
        # S15.2.1 — RSI persona veto (before all other guards)
        if rsi is not None and rsi > 0:
            persona_cfg = getattr(self, "_persona_config", {})
            _rsi_hard_veto = 70.0
            _rsi_threshold = _rsi_hard_veto
            if playbook == "momentum" and adx is not None:
                bypass_rsi = float(persona_cfg.get("momentum_bypass_rsi", 70))
                bypass_adx = float(persona_cfg.get("momentum_bypass_adx", 999))
                if adx > bypass_adx:
                    _rsi_threshold = bypass_rsi
            if rsi >= _rsi_threshold:
                return (
                    False,
                    f"RSI veto: RSI {rsi:.0f} >= {_rsi_threshold:.0f} (playbook={playbook})",
                    0.0,
                )

        # S16.1.2 AC3 — Playbook-based profit floor multiplier
        # momentum: lower floor (×0.8) — trend already confirmed, fees easier to cover
        # risk_off: raise floor (×1.5) — only accept high-confidence reward setups
        # ranging / standard: unchanged (×1.0)
        _floor_mult = {"momentum": 0.8, "risk_off": 1.5}
        _effective_profit_floor = self._min_profit_floor_pct * _floor_mult.get(playbook, 1.0)
        # Guard: reject if the pair's TP is below the effective floor.
        # pair_tp_pct passed via take_profit_pct kwarg (added below in signature)
        # We derive it here if not passed as a param
        _pair_tp = self.get_take_profit_pct(pair)
        if _effective_profit_floor > 0 and _pair_tp > 0 and _pair_tp < _effective_profit_floor:
            return (
                False,
                f"Profit floor guard: pair TP {_pair_tp:.1f}% < effective floor "
                f"{_effective_profit_floor:.2f}% (playbook={playbook})",
                0.0,
            )

        # 0.5. Time-of-Day Guard — explicitly block outside of allowed volume overlap
        if self._trading_hours_enabled:
            if candle_timestamp_sec > 0:
                current_hour = datetime.datetime.fromtimestamp(candle_timestamp_sec, datetime.timezone.utc).hour
            else:
                current_hour = datetime.datetime.now(datetime.timezone.utc).hour
                
            if self._trading_start_hour <= self._trading_end_hour:
                allowed = self._trading_start_hour <= current_hour < self._trading_end_hour
            else:
                allowed = current_hour >= self._trading_start_hour or current_hour < self._trading_end_hour
            
            if not allowed:
                return (
                    False,
                    f"Time-of-Day Guard: Current hour ({current_hour:02d}:00 UTC) outside allowed window ({self._trading_start_hour:02d}:00 - {self._trading_end_hour:02d}:00 UTC).",
                    0.0,
                )

        # -1. Duplicate position guard — one open position per pair at a time (#230)
        open_pairs = self._get_open_pairs()
        if pair in open_pairs:
            return (
                False,
                f"Position already open for {pair}",
                0.0,
            )

        # 0. Circuit breaker — pause all buys after consecutive stop-losses
        tripped, resume_in = self.is_circuit_open()
        if tripped:
            resume_mins = int(resume_in / 60)
            return (
                False,
                f"Circuit breaker active — {self._cb_max_consec_stops} consecutive stop-losses."
                f" Resumes in {resume_mins} min.",
                0.0,
            )

        # 1. Daily loss limit check
        if starting_balance_usd > 0:
            daily_loss_pct = abs(daily_loss_usd) / starting_balance_usd * 100
            if daily_loss_pct >= self._daily_loss_limit_pct and daily_loss_usd < 0:
                return (
                    False,
                    f"Daily loss limit reached: {daily_loss_pct:.1f}% >= {self._daily_loss_limit_pct}%",
                    0.0,
                )
        # Guard 1.1 — Macro cycle-top guard: block new Tier 3 / 4 BUYs (#205)
        if self._cycle_top_active and self._pair_tiers.get(pair, 0) in (3, 4):
            mvrv = self._cycle_top_data.get("mvrv_z_score")
            nupl = self._cycle_top_data.get("nupl")
            return (
                False,
                f"Cycle top guard active — Tier {self._pair_tiers.get(pair, 0)} BUYs blocked "
                f"(MVRV {mvrv:.2f}, NUPL {nupl:.2f})",
                0.0,
            )
        # Guard 1.2 — Drawdown recovery mode: restrict to major pairs at reduced size (#182)
        if starting_balance_usd > 0:
            daily_pnl_pct = daily_loss_usd / starting_balance_usd * 100
            if self.is_in_drawdown_recovery(daily_pnl_pct):
                if pair not in self._recovery_allowed_pairs:
                    return (
                        False,
                        f"Drawdown recovery mode ({daily_pnl_pct:.1f}% daily P&L) — "
                        f"only {', '.join(self._recovery_allowed_pairs)} permitted",
                        0.0,
                    )
                # Cap position size at the recovery override (half of normal)
                recovery_cap = available_cash_usd * self._recovery_max_pos_pct / 100
                if proposed_usd > recovery_cap:
                    proposed_usd = recovery_cap
                    logger.info(
                        "[RECOVERY] %s: position capped at $%.2f (recovery max %d%%)",
                        pair, proposed_usd, self._recovery_max_pos_pct,
                    )
        # 3. Min cash reserve — PRIMARY gate: runs before count ceiling (#167)
        min_cash = portfolio_balance_usd * (self._min_cash_reserve_pct / 100)
        if available_cash_usd <= min_cash:
            return (
                False,
                f"Insufficient cash reserve (${available_cash_usd:.2f} <= min ${min_cash:.2f})",
                0.0,
            )

        # Guard 0.5: Deployable cash below min_order_usd — primary gate, before count ceiling (#167)
        deployable = available_cash_usd - min_cash
        if deployable < self._min_order_usd:
            logger.info(
                "[RISK] Skipping BUY %s — deployable cash $%.2f below min_order_usd $%.2f",
                pair, deployable, self._min_order_usd,
            )
            return (False, f"Deployable cash ${deployable:.2f} below min_order_usd ${self._min_order_usd:.2f}", 0.0)

        # 2. Max open positions — hard safety ceiling (#167)
        # Cash guards above are the primary gate. This ceiling only fires when caution-factor
        # positions have consumed all slots before cash is exhausted. At max_open_positions=10
        # with min_order_usd=$20, this is a safety net — not the routine blocker.
        if open_positions_count >= self._max_open_positions:
            return (
                False,
                f"Max open positions reached ({open_positions_count}/{self._max_open_positions})",
                0.0,
            )

        # 2a. Correlation cluster guard (#139)
        cluster_penalty_factor = 1.0
        cluster = self._get_correlation_cluster(pair)
        if cluster and self._correlation_clusters:
            cluster_open = [p for p in open_pairs if p in cluster["pairs"] and p != pair]
            if len(cluster_open) >= self._max_cluster_positions:
                return (
                    False,
                    f"Cluster '{cluster['name']}' already has {len(cluster_open)} open "
                    f"({', '.join(cluster_open)}) — max {self._max_cluster_positions}.",
                    0.0,
                )
            if len(cluster_open) == 1:
                cluster_penalty_factor = self._cluster_size_penalty
                logger.info(
                    "[RISK] Cluster '%s' has 1 open (%s) — sizing penalised %.0f%%",
                    cluster["name"], cluster_open[0], self._cluster_size_penalty * 100,
                )

        # -- DYNAMIC BALANCE & CRASH VALIDATION --

        # Guard 1: Minimum Order Size
        if proposed_usd < self._min_order_usd:
            return (
                False, 
                f"Proposed USD (${proposed_usd:.2f}) is below minimum order size (${self._min_order_usd:.2f}).", 
                0.0
            )
            
        # Guard 2: Flash Crash Anomaly Detection
        if current_price > 0 and baseline_price > 0:
            price_drop_pct = ((baseline_price - current_price) / baseline_price) * 100
            
            # If price fell off a cliff, assume broken order book
            if price_drop_pct > self._flash_crash_tolerance_pct: 
                return (
                    False, 
                    f"Flash Crash Guard triggered: Price (${current_price}) dropped {price_drop_pct:.1f}% below baseline.", 
                    0.0
                )
                
            # Guard 3: Fat Finger Token Volume Overflow
            token_est_quantity = proposed_usd / current_price
            if token_est_quantity > self._max_token_volume_per_trade:
                return (
                    False, 
                    f"Fat Finger Guard: Token quantity ({token_est_quantity:,.0f}) exceeds reasonable max limits.", 
                    0.0
                )

        # --- NEW: Dynamic Balance & Fat Finger Guard ---
        
        # 1. Ensure proposed amount doesn't eat into the 2% fee/buffer of available cash
        max_safe_allocation = available_cash_usd * 0.98
        
        if proposed_usd > max_safe_allocation:
            # Fat-finger or over-leverage protection triggered
            return (
                False,
                f"Risk Guard triggered: Proposed USD (${proposed_usd:.2f}) exceeds "
                f"the 98% safe available balance buffer (${max_safe_allocation:.2f}).",
                0.0,
            )
        # --- END NEW Guard ---

        # 4. Cap at 30% of portfolio
        max_trade_usd = portfolio_balance_usd * (self._max_position_pct / 100)
        capped = min(proposed_usd, max_trade_usd)

        # 5. Cannot trade more than available cash (minus reserve)
        tradable_cash = available_cash_usd - min_cash
        capped = min(capped, tradable_cash)

        if capped < self._min_order_usd:
            return (False, "No tradable cash after min reserve deduction", 0.0)

        # Apply cluster size penalty if applicable (#139)
        if cluster_penalty_factor < 1.0:
            capped = round(capped * cluster_penalty_factor, 2)
            if capped < self._min_order_usd:
                return (False, f"Post-cluster-penalty size ${capped:.2f} below min_order_usd ${self._min_order_usd:.2f}", 0.0)

        reason = "Approved"
        if capped < proposed_usd:
            reason = f"Approved (capped ${proposed_usd:.2f} → ${capped:.2f} by 30% rule)"

        return (True, reason, round(capped, 2))

    def check_reallocation_cap(self, prune_usd: float, portfolio_value: float) -> bool:
        """
        S15.1.2 — Guard against excessive reallocation within a 6-hour window.

        Returns True (BLOCKED) when the persona's 6-hour reallocation cap would be
        breached by the proposed close/reopen.

        Logic:
          - Conservative: reallocation_max_pct_6h = 0.0 → always blocked.
          - Medium: 20% of portfolio per 6h window.
          - High: 30% of portfolio per 6h window.
          - Sum of USD value of positions closed with exit_reason='reallocation' in
            the past 6 hours + prune_usd must NOT exceed the cap.

        Returns:
            True  → reallocation is BLOCKED (cap reached or persona disallows)
            False → reallocation is PERMITTED
        """
        persona_cfg = getattr(self, "_persona_config", {})
        max_pct = float(persona_cfg.get("reallocation_max_pct_6h", 0.0))
        if max_pct <= 0:
            return True  # conservative persona or cap exhausted

        cap_usd = portfolio_value * max_pct
        if cap_usd <= 0:
            return True

        # Query total USD reallocated in the last 6 hours
        reallocated_usd = 0.0
        if self._db_path:
            try:
                from src.storage.database import get_connection
                conn = get_connection(self._db_path)
                trades_table = "paper_trades" if "paper" in self._db_path else "live_trades"
                since_iso = datetime.datetime(
                    *datetime.datetime.utcnow().timetuple()[:6],
                    tzinfo=datetime.timezone.utc,
                ) - datetime.timedelta(hours=6)
                rows = conn.execute(
                    f"SELECT usd_value FROM {trades_table} "
                    f"WHERE exit_reason='reallocation' AND closed_at >= ?",
                    (since_iso.isoformat(),),
                ).fetchall()
                conn.close()
                reallocated_usd = sum(float(r["usd_value"] or 0) for r in rows)
            except Exception as e:
                logger.warning("[ROM] Failed to query reallocation history: %s", e)

        if reallocated_usd + prune_usd > cap_usd:
            logger.info(
                "[ROM] Reallocation blocked — 6h cap exhausted: "
                "already_reallocated=$%.2f + this=$%.2f > cap=$%.2f (%.0f%% of $%.2f)",
                reallocated_usd, prune_usd, cap_usd, max_pct * 100, portfolio_value,
            )
            return True

        return False

    @timed("pair", "open_positions_count")
    def validate_sell(
        self,
        pair: str,
        open_positions: list[dict],
        current_price: float,
    ) -> tuple:
        """Validate a proposed sell/close of an open position against the profit floor."""
        if not open_positions:
            return (False, "No open positions to sell", 0.0)

        for pos in open_positions:
            entry_price = pos.get("entry_price")
            if not entry_price:
                continue

            est_pnl_pct = ((current_price - entry_price) / entry_price) * 100
            
            # BLOCK trades that don't satisfy the minimum floor
            if est_pnl_pct < self._min_profit_floor_pct:
                return (
                    False,
                    f"Minimum Profit Floor Guardrail: Projected PNL is {est_pnl_pct:+.2f}%, "
                    f"which is below the {self._min_profit_floor_pct}% required to cover exchange fees.",
                    0.0
                )

            # BLOCK early exits below 80% of the TP target (BRD FR-20 — code-enforced)
            take_profit_pct = pos.get("take_profit_pct")
            if take_profit_pct and take_profit_pct > 0:
                proximity_threshold_pct = take_profit_pct * (self._early_sell_min_tp_proximity_pct / 100)
                if est_pnl_pct < proximity_threshold_pct:
                    return (
                        False,
                        f"Early Exit Guard: P&L {est_pnl_pct:+.2f}% is below "
                        f"{proximity_threshold_pct:.1f}% ({self._early_sell_min_tp_proximity_pct}% of "
                        f"{take_profit_pct}% TP target). Let the trade run.",
                        0.0,
                    )

        return (True, "Approved", 0.0)
