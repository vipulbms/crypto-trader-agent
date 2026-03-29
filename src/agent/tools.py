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
    ):
        self._broker       = broker
        self._risk         = risk_manager
        self._audit        = audit_logger
        self._notifier     = notifier
        self._ws            = ws_feed
        self._mode          = mode
        self._config        = config
        self._sod_balance   = start_of_day_balance

        # Current cycle context — set before each cycle by the agent
        self._current_cycle_id: Optional[int] = None
        self._current_llm_decision_id: Optional[int] = None

    def set_cycle_context(self, cycle_id: int) -> None:
        self._current_cycle_id = cycle_id

    def set_llm_decision_id(self, decision_id: int) -> None:
        self._current_llm_decision_id = decision_id

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
            pair: Trading pair e.g. 'BTC/USD', 'ETH/USD', 'BNB/USD', 'SOL/USD', 'XRP/USD', 'TRX/USD', 'DOGE/USD', 'ADA/USD', LTC/USD, 'RAILS/USD'
            usd_amount: Amount in USD to invest (will be capped at 30% of portfolio)

        Returns:
            String describing the outcome.
        """
        logger.info("[TOOL] propose_buy(%s, $%.2f)", pair, usd_amount)

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
            return f"REJECTED: {reason}"

        current_price = self._ws.get_latest_price(pair)
        if not current_price:
            msg = f"No price data available for {pair}"
            logger.error(msg)
            return f"FAILED: {msg}"

        sl_pct = self._risk.get_stop_loss_pct(pair)
        tp_pct = self._risk.get_take_profit_pct(pair)

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
            result = self._broker.place_order(
                pair=pair,
                side="buy",
                usd_amount=capped_amount,
                current_price=current_price,
                stop_loss_pct=sl_pct,
                take_profit_pct=tp_pct,
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
            requested_price=self._risk.calculate_stop_loss_price(result["fill_price"], pair),
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
            requested_price=self._risk.calculate_take_profit_price(result["fill_price"], pair),
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

        approved, check_reason, _ = self._risk.validate_sell(
            pair=pair,
            open_positions_count=len(pair_positions),
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

        current_price = self._ws.get_latest_price(pair)
        if not current_price:
            return f"FAILED: No price data for {pair}"

        results = []
        for pos in pair_positions:
            pos_id = pos.get("id") or pos.get("position_id")
            if not pos_id:
                continue
            trade = self._broker.close_position(
                position_id=pos_id,
                exit_price=current_price,
                exit_reason="agent_sell",
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
