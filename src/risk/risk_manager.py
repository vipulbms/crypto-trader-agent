"""
Risk Manager — hard-coded validation gate.
Every proposed trade must pass through here before execution.
The 5% stop-loss, configurable take-profit, 30% position cap, and daily
loss limit are enforced deterministically — NOT by the LLM.
"""

import logging
from typing import Optional

from src.utils.timing import timed

logger = logging.getLogger(__name__)

ALLOWED_TAKE_PROFIT_PCTS = [5, 8, 12, 16, 20]


def validate_config(config: dict) -> None:
    """
    Called once at startup. Raises ValueError if any take-profit value
    is not in the allowed set. Prevents misconfigured agents from starting.
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
    logger.info("Config validation passed — all take-profit values are valid")


class RiskManager:
    """
    Stateless risk validation. Receives current portfolio state and a proposed
    action, returns (approved: bool, reason: str, adjusted_amount: float|None).
    """

    def __init__(self, config: dict):
        trading = config.get("trading", {})
        risk    = config.get("risk", {})
        self._stop_loss_pct       = trading.get("stop_loss_pct", 5)
        self._global_tp_pct       = trading.get("take_profit_pct", 10)
        self._max_position_pct    = trading.get("max_position_pct", 30)
        self._max_open_positions  = trading.get("max_open_positions", 3)
        self._daily_loss_limit_pct= risk.get("daily_loss_limit_pct", 10)
        self._min_cash_reserve_pct= risk.get("min_cash_reserve_pct", 10)

        # Build per-pair TP map
        self._pair_tp: dict = {}
        for p in trading.get("pairs", []):
            self._pair_tp[p["pair"]] = p.get("take_profit_pct", self._global_tp_pct)

    def get_stop_loss_pct(self, pair: str) -> float:
        return self._stop_loss_pct

    def get_take_profit_pct(self, pair: str) -> float:
        return self._pair_tp.get(pair, self._global_tp_pct)

    def calculate_stop_loss_price(self, entry_price: float, pair: str, override_pct: Optional[float] = None) -> float:
        sl_pct = override_pct if override_pct is not None else self._stop_loss_pct
        return round(entry_price * (1 - sl_pct / 100), 8)

    def calculate_take_profit_price(self, entry_price: float, pair: str, override_pct: Optional[float] = None) -> float:
        tp_pct = override_pct if override_pct is not None else self.get_take_profit_pct(pair)
        return round(entry_price * (1 + tp_pct / 100), 8)

    @timed("pair", "proposed_usd", "open_positions_count")
    def validate_buy(
        self,
        pair: str,
        proposed_usd: float,
        portfolio_balance_usd: float,
        available_cash_usd: float,
        open_positions_count: int,
        daily_loss_usd: float,
        starting_balance_usd: float,
    ) -> tuple:
        """
        Returns (approved: bool, reason: str, capped_amount: float)
        The capped_amount is the actual amount to trade after applying the 30% cap.
        """
        # 1. Daily loss limit check
        if starting_balance_usd > 0:
            daily_loss_pct = abs(daily_loss_usd) / starting_balance_usd * 100
            if daily_loss_pct >= self._daily_loss_limit_pct and daily_loss_usd < 0:
                return (
                    False,
                    f"Daily loss limit reached: {daily_loss_pct:.1f}% >= {self._daily_loss_limit_pct}%",
                    0.0,
                )

        # 2. Max open positions
        if open_positions_count >= self._max_open_positions:
            return (
                False,
                f"Max open positions reached ({open_positions_count}/{self._max_open_positions})",
                0.0,
            )

        # 3. Min cash reserve
        min_cash = portfolio_balance_usd * (self._min_cash_reserve_pct / 100)
        if available_cash_usd <= min_cash:
            return (
                False,
                f"Insufficient cash reserve (${available_cash_usd:.2f} <= min ${min_cash:.2f})",
                0.0,
            )

        # 4. Cap at 30% of portfolio
        max_trade_usd = portfolio_balance_usd * (self._max_position_pct / 100)
        capped = min(proposed_usd, max_trade_usd)

        # 5. Cannot trade more than available cash (minus reserve)
        tradable_cash = available_cash_usd - min_cash
        capped = min(capped, tradable_cash)

        if capped <= 0:
            return (False, "No tradable cash after min reserve deduction", 0.0)

        reason = "Approved"
        if capped < proposed_usd:
            reason = f"Approved (capped ${proposed_usd:.2f} → ${capped:.2f} by 30% rule)"

        return (True, reason, round(capped, 2))

    @timed("pair", "open_positions_count")
    def validate_sell(
        self,
        pair: str,
        open_positions_count: int,
    ) -> tuple:
        """Validate a proposed sell/close of an open position."""
        if open_positions_count == 0:
            return (False, "No open positions to sell", 0.0)
        return (True, "Approved", 0.0)
