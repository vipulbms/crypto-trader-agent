"""
Trading tools exposed to the LLM agent.
Each function is a tool the LLM can call.
All actions are passed through the risk manager before any order is placed.
"""

import logging
from typing import Optional

from ..utils.timing import timed

logger = logging.getLogger(__name__)


class TradingTools:
    """
    Container for all LLM-callable trading tools.
    Holds references to the broker, risk manager, and audit logger.
    """

    def __init__(
        self,
        broker,
        risk_manager,
        audit_logger,
        notifier,
        ws_feed,
        mode: str,
        config: dict,
        start_of_day_balance: float,
        llm_client=None,
    ):
        self._broker       = broker
        self._risk         = risk_manager
        self._audit        = audit_logger
        self._notifier     = notifier
        self._ws            = ws_feed
        self._mode          = mode
        self._config        = config
        self._sod_balance   = start_of_day_balance
        self._llm_client    = llm_client  # for post-trade analysis (Feature 7)

        # Current cycle context — set before each cycle by the agent
        self._current_cycle_id: Optional[int] = None
        self._current_llm_decision_id: Optional[int] = None
        self._dynamic_tp_values: dict = {}
        self._dynamic_sl_values: dict = {}
        self._pair_max_usd: dict = {}
        self._signal_scores: dict = {}  # pair → score for missed-signal alerting (#268)

    def set_cycle_context(self, cycle_id: int) -> None:
        self._current_cycle_id = cycle_id

    def set_llm_decision_id(self, decision_id: int) -> None:
        self._current_llm_decision_id = decision_id

    def set_dynamic_tp_values(self, values: dict) -> None:
        self._dynamic_tp_values = values or {}

    def set_dynamic_sl_values(self, values: dict) -> None:
        self._dynamic_sl_values = values or {}

    def set_pair_max_usd(self, values: dict) -> None:
        self._pair_max_usd = values or {}

    def set_signal_scores(self, scores: dict) -> None:
        """Inject per-pair signal scores so missed-signal alerts can include the score."""
        self._signal_scores = scores or {}

    def set_pair_max_usd(self, values: dict) -> None:
        self._pair_max_usd = values or {}

    # ──────────────────────────────────────────────
    # Tool: propose_buy
    # ──────────────────────────────────────────────

    @timed("pair", "usd_amount")
    def propose_buy(self, pair: str, usd_amount: float) -> str:
        """
        Propose buying a crypto pair with a given USD amount.
        The risk manager may cap the amount or reject the trade.
        Stop-loss and take-profit are set automatically.

        Args:
            pair: Trading pair e.g. 'BTC/USD', 'ETH/USD', 'BNB/USD', 'SOL/USD', 'XRP/USD', 'TRX/USD', 'DOGE/USD', 'ADA/USD', 'LTC/USD', 'RAILS/USD', 'AVAX/USD', 'SUI/USD', 'HYPE/USD', 'UNI/USD', 'INJ/USD', 'WIF/USD', 'TON/USD', 'OP/USD', 'ARB/USD', 'JUP/USD', 'PEPE/USD', 'TIA/USD', 'RENDER/USD', 'FET/USD', 'STX/USD', 'PENDLE/USD', 'ONDO/USD', 'BONK/USD', 'MOVR/USD', 'RAVE/USD'
            usd_amount: Amount in USD to invest (will be capped at 30% of portfolio)

        Returns:
            String describing the outcome.
        """
        logger.info("[TOOL] propose_buy(%s, $%.2f)", pair, usd_amount)

        pair_cap = self._pair_max_usd.get(pair)
        if pair_cap is not None and usd_amount > pair_cap:
            logger.info(
                "[TIER_CAP] %s requested $%.2f capped to pair_max_usd $%.2f",
                pair, usd_amount, pair_cap,
            )
            usd_amount = pair_cap

        current_price = self._ws.get_latest_price(pair)
        if not current_price:
            msg = f"No price data available for {pair}"
            logger.error(msg)
            return f"FAILED: {msg}"
            
        ema_200 = current_price # Default baseline
        
        # Get current candle timestamp if available (useful for backtesting limits)
        candles = self._ws.get_candles(pair) if hasattr(self._ws, "get_candles") else []
        current_time = float(candles[-1].get("time", candles[-1].get("timestamp", 0.0))) if candles else 0.0

        balance    = self._broker.get_balance()
        total_usd  = balance["total_usd"]
        cash_usd   = balance["available_cash_usd"]
        n_positions= self._broker.get_open_positions_count() if hasattr(self._broker, "get_open_positions_count") else len(self._broker.get_open_positions())

        daily_pnl  = self._broker.get_daily_pnl(self._sod_balance)

        approved, reason, capped_amount = self._risk.validate_buy(
            pair=pair,
            proposed_usd=usd_amount,
            portfolio_balance_usd=total_usd,
            available_cash_usd=cash_usd,
            open_positions_count=n_positions,
            daily_loss_usd=daily_pnl["pnl_usd"],
            starting_balance_usd=self._sod_balance,
            current_price=current_price,
            baseline_price=ema_200,
            candle_timestamp_sec=current_time
        )

        # Audit risk check
        risk_check_id = self._audit.log_risk_check(
            llm_decision_id=self._current_llm_decision_id,
            proposed_action="BUY",
            proposed_pair=pair,
            approved=approved,
            proposed_usd_amount=usd_amount,
            rejection_reason=None if approved else reason,
            adjusted_usd_amount=capped_amount if approved else None,
        )

        if not approved:
            logger.warning("[RISK] BUY rejected for %s: %s", pair, reason)
            # Fire Telegram alert for high-conviction rejections (#268)
            missed_threshold = self._config.get("signals", {}).get("missed_signal_min_score", 8)
            score = self._signal_scores.get(pair, 0)
            if score >= missed_threshold and self._notifier:
                max_score = self._config.get("signals", {}).get("max_score", 28)
                self._notifier.send_missed_signal(pair, score, max_score, reason)
            return f"REJECTED: {reason}"

        sl_pct = self._dynamic_sl_values.get(pair) or self._risk.get_stop_loss_pct(pair)
        tp_pct = self._dynamic_tp_values.get(pair) or self._risk.get_take_profit_pct(pair)
        
        if pair in self._dynamic_sl_values:
            logger.info("[DYNAMIC_SL] %s using dynamic SL=%.1f%%", pair, sl_pct)
        if pair in self._dynamic_tp_values:
            logger.info("[DYNAMIC_TP] %s using dynamic TP=%.1f%%", pair, tp_pct)

        # Audit entry order
        entry_order_id = self._audit.log_order(
            risk_check_id=risk_check_id,
            pair=pair,
            side="buy",
            order_type="market",
            role="entry",
            status="simulated" if self._mode == "paper" else "submitted",
            requested_volume=round(capped_amount / current_price, 8),
            requested_price=current_price,
            configured_stop_loss_pct=sl_pct,
            configured_take_profit_pct=tp_pct,
        )

        try:
            # Derive candle timestamp for backtest accuracy (wall-clock in live mode)
            candle_ts_iso = None
            if hasattr(self._ws, "current_candle_time") and self._ws.current_candle_time:
                from datetime import datetime, timezone as _tz
                candle_ts_iso = datetime.fromtimestamp(
                    self._ws.current_candle_time, tz=_tz.utc
                ).isoformat()
            result = self._broker.place_order(
                pair=pair,
                side="buy",
                usd_amount=capped_amount,
                current_price=current_price,
                stop_loss_pct=sl_pct,
                take_profit_pct=tp_pct,
                timestamp_override=candle_ts_iso,
            )
        except Exception as e:
            self._audit.log_error("exchange", type(e).__name__, str(e))
            return f"FAILED: Order error — {e}"

        # Audit fill
        self._audit.log_fill(
            order_id=entry_order_id,
            fill_price=result["fill_price"],
            fill_volume=result["volume"],
            fill_usd_value=result.get("usd_invested", capped_amount),
            fee_usd=result.get("fee_usd", 0.0),
            slippage_pct=result.get("slippage_pct", 0.0),
        )

        # Audit SL order
        sl_order_id = self._audit.log_order(
            risk_check_id=risk_check_id,
            pair=pair,
            side="sell",
            order_type="stop-loss",
            role="stop_loss",
            status="simulated" if self._mode == "paper" else "submitted",
            requested_price=self._risk.calculate_stop_loss_price(result["fill_price"], pair, sl_pct),
            exchange_order_id=result.get("stop_loss_order_id"),
            configured_stop_loss_pct=sl_pct,
            configured_take_profit_pct=tp_pct,
        )

        # Audit TP order
        self._audit.log_order(
            risk_check_id=risk_check_id,
            pair=pair,
            side="sell",
            order_type="take-profit",
            role="take_profit",
            status="simulated" if self._mode == "paper" else "submitted",
            requested_price=self._risk.calculate_take_profit_price(result["fill_price"], pair, tp_pct),
            exchange_order_id=result.get("take_profit_order_id"),
            configured_stop_loss_pct=sl_pct,
            configured_take_profit_pct=tp_pct,
        )

        # Audit position opened
        self._audit.log_position_event(
            pair=pair,
            event_type="opened",
            entry_price=result["fill_price"],
            take_profit_pct_used=tp_pct,
            stop_loss_pct_used=sl_pct,
        )

        # Notify
        if self._notifier:
            self._notifier.send_trade_executed(result, self._mode)

        return (
            f"BUY EXECUTED: {pair} | "
            f"{result['volume']:.6f} units @ ${result['fill_price']:.2f} | "
            f"SL: ${result['stop_loss_price']:.2f} | "
            f"TP: ${result['take_profit_price']:.2f} | "
            f"Invested: ${result.get('usd_invested', capped_amount):.2f}"
        )

    # ──────────────────────────────────────────────
    # Tool: propose_sell
    # ──────────────────────────────────────────────

    @timed("pair", "reason")
    def propose_sell(self, pair: str, reason: str = "Agent decision") -> str:
        """
        Propose closing (selling) an open position for the given pair.

        Args:
            pair: Trading pair to close e.g. 'BTC/USD'
            reason: Why you are closing this position

        Returns:
            String describing the outcome.
        """
        logger.info("[TOOL] propose_sell(%s) — reason: %s", pair, reason)

        positions = self._broker.get_open_positions()
        pair_positions = [p for p in positions if p.get("pair") == pair]

        current_price = self._ws.get_latest_price(pair)
        if not current_price:
            return f"FAILED: No price data for {pair}"

        # Feed actual position details and live price to the risk manager
        approved, check_reason, _ = self._risk.validate_sell(
            pair=pair,
            open_positions=pair_positions,
            current_price=current_price
        )

        risk_check_id = self._audit.log_risk_check(
            llm_decision_id=self._current_llm_decision_id,
            proposed_action="SELL",
            proposed_pair=pair,
            approved=approved,
            rejection_reason=None if approved else check_reason,
        )

        if not approved:
            return f"REJECTED: {check_reason}"

        results = []
        # Derive candle timestamp for backtest accuracy (wall-clock in live mode)
        candle_ts_iso = None
        if hasattr(self._ws, "current_candle_time") and self._ws.current_candle_time:
            from datetime import datetime, timezone as _tz
            candle_ts_iso = datetime.fromtimestamp(
                self._ws.current_candle_time, tz=_tz.utc
            ).isoformat()
        for pos in pair_positions:
            pos_id = pos.get("id") or pos.get("position_id")
            if not pos_id:
                continue
            trade = self._broker.close_position(
                position_id=pos_id,
                exit_price=current_price,
                exit_reason="agent_sell",
                timestamp_override=candle_ts_iso,
            )
            if trade:
                self._audit.log_position_event(
                    pair=pair,
                    event_type="manually_closed",
                    entry_price=trade["entry_price"],
                    exit_price=trade["exit_price"],
                    pnl_usd=trade["pnl_usd"],
                    pnl_pct=trade["pnl_pct"],
                    hold_duration_seconds=trade["hold_duration_secs"],
                    take_profit_pct_used=pos.get("take_profit_pct"),
                    stop_loss_pct_used=pos.get("stop_loss_pct"),
                )
                if self._notifier:
                    self._notifier.send_trade_executed(trade, self._mode)
                results.append(
                    f"${trade['pnl_usd']:+.2f} ({trade['pnl_pct']:+.2f}%)"
                )
                # Feature 7: Post-trade analysis
                self._run_post_trade_analysis(trade)

        return f"SELL EXECUTED: {pair} | P&L: {', '.join(results)}"

    # ──────────────────────────────────────────────
    # Tool: hold
    # ──────────────────────────────────────────────

    @timed("pair", "reason")
    def hold(self, pair: str, reason: str) -> str:
        """
        Explicitly hold (do nothing) for the given pair this cycle.
        A reason is REQUIRED — every hold decision is audited.

        Args:
            pair: Trading pair e.g. 'BTC/USD'
            reason: Why you are holding e.g. 'RSI neutral at 52, signals mixed'

        Returns:
            Confirmation string.
        """
        logger.info("[TOOL] hold(%s) — %s", pair, reason)

        # Audit risk check for hold (always approved)
        self._audit.log_risk_check(
            llm_decision_id=self._current_llm_decision_id,
            proposed_action="HOLD",
            proposed_pair=pair,
            approved=True,
            rejection_reason=None,
        )

        return f"HOLD: {pair} — {reason}"

    # ──────────────────────────────────────────────
    # Internal: post-trade analysis (Feature 7)
    # ──────────────────────────────────────────────

    def _run_post_trade_analysis(self, trade: dict) -> None:
        """Fire-and-forget post-trade LLM analysis. Logs result; never raises."""
        try:
            from src.analysis.features import generate_post_trade_analysis
            llm_cfg = self._config.get("llm", {})
            model   = llm_cfg.get("model", "qwen2.5:14b")
            analysis = generate_post_trade_analysis(
                trade=trade,
                signals_at_entry=None,
                config=self._config,
                llm_client=self._llm_client,
                model=model,
            )
            if analysis:
                logger.info(
                    "[POST-TRADE] %s %s P&L %.2f%% — %s",
                    trade.get("pair"), trade.get("exit_reason"),
                    trade.get("pnl_pct", 0), analysis,
                )
        except Exception as e:
            logger.warning("Post-trade analysis error: %s", e)
