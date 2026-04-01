"""
BacktestBroker — pure in-memory broker for historical simulation.

Same interface as PaperBroker / KrakenClient:
  get_balance(), get_open_positions(), get_open_positions_count(),
  place_order(), close_position(), check_stops_and_tp(), get_daily_pnl()

Key differences from PaperBroker:
  - No SQLite — all state is in-memory dicts/lists
  - check_stops_and_tp() uses candle high/low instead of close price only
    (more realistic: checks if price blew through SL/TP intra-candle)
  - SL takes priority over TP if both triggered in the same candle
  - No @timed decorator (no timing infrastructure needed in backtest)
"""

import logging

logger = logging.getLogger(__name__)

SLIPPAGE = 0.0005   # 0.05% — matches PaperBroker default
FEE      = 0.0026   # 0.26% maker fee — matches PaperBroker default


class BacktestBroker:
    def __init__(self, starting_balance: float = 1000.0):
        self._cash = starting_balance
        self._start_balance = starting_balance
        self._positions: dict[int, dict] = {}   # position_id → position dict
        self._next_id = 1
        self.trades: list[dict] = []            # all closed trade records

    # ──────────────────────────────────────────────
    # Account queries
    # ──────────────────────────────────────────────

    def get_balance(self) -> dict:
        open_pos_value = sum(p["usd_value"] for p in self._positions.values())
        total = round(self._cash + open_pos_value, 4)
        holdings = {}
        for p in self._positions.values():
            coin = p["pair"].split("/")[0]
            holdings[coin] = holdings.get(coin, 0.0) + p["volume"]
        return {
            "total_usd":          total,
            "available_cash_usd": round(self._cash, 4),
            "holdings":           holdings,
        }

    def get_open_positions(self) -> list:
        return list(self._positions.values())

    def get_open_positions_count(self) -> int:
        return len(self._positions)

    def get_daily_pnl(self, start_of_day_balance: float) -> dict:
        balance = self.get_balance()
        pnl_usd = balance["total_usd"] - start_of_day_balance
        pnl_pct = (pnl_usd / start_of_day_balance * 100) if start_of_day_balance else 0.0
        return {
            "pnl_usd":      round(pnl_usd, 2),
            "pnl_pct":      round(pnl_pct, 2),
            "current_cash": balance["available_cash_usd"],
        }

    # ──────────────────────────────────────────────
    # Order simulation
    # ──────────────────────────────────────────────

    def place_order(
        self,
        pair: str,
        side: str,
        usd_amount: float,
        current_price: float,
        stop_loss_pct: float,
        take_profit_pct: float,
        candle_time: int = 0,
    ) -> dict:
        if side != "buy":
            raise ValueError("BacktestBroker.place_order only supports 'buy'")

        fill_price  = round(current_price * (1 + SLIPPAGE), 8)
        volume      = round(usd_amount / fill_price, 8)
        actual_cost = round(fill_price * volume, 4)
        fee_usd     = round(actual_cost * FEE, 4)

        sl_price = round(fill_price * (1 - stop_loss_pct / 100), 8)
        tp_price = round(fill_price * (1 + take_profit_pct / 100), 8)

        self._cash -= (actual_cost + fee_usd)
        pos_id = self._next_id
        self._next_id += 1

        self._positions[pos_id] = {
            "id":               pos_id,
            "pair":             pair,
            "side":             "buy",
            "entry_price":      fill_price,
            "volume":           volume,
            "usd_value":        actual_cost,
            "stop_loss_price":  sl_price,
            "take_profit_price":tp_price,
            "stop_loss_pct":    stop_loss_pct,
            "take_profit_pct":  take_profit_pct,
            "opened_at_time":   candle_time,
            "status":           "open",
        }

        logger.debug(
            "[BT] BUY %s %.8f @ $%.4f | SL:$%.4f TP:$%.4f cash=$%.2f",
            pair, volume, fill_price, sl_price, tp_price, self._cash,
        )

        return {
            "pair":               pair,
            "side":               "buy",
            "volume":             volume,
            "fill_price":         fill_price,
            "usd_invested":       actual_cost,
            "fee_usd":            fee_usd,
            "stop_loss_price":    sl_price,
            "take_profit_price":  tp_price,
            "stop_loss_pct":      stop_loss_pct,
            "take_profit_pct":    take_profit_pct,
            "position_id":        pos_id,
        }

    def close_position(
        self,
        position_id: int,
        exit_price: float,
        exit_reason: str,
        candle_time: int = 0,
    ):
        pos = self._positions.pop(position_id, None)
        if not pos:
            return None

        fill_price = round(exit_price * (1 - SLIPPAGE), 8)
        gross_out  = round(fill_price * pos["volume"], 4)
        fee_usd    = round(gross_out * FEE, 4)
        net_out    = round(gross_out - fee_usd, 4)
        pnl_usd    = round(net_out - pos["usd_value"], 4)
        pnl_pct    = round(pnl_usd / pos["usd_value"] * 100, 2) if pos["usd_value"] else 0.0
        hold_secs    = candle_time - pos["opened_at_time"]
        hold_candles = hold_secs // (15 * 60)   # convert epoch-seconds delta to candle count

        self._cash += net_out

        trade = {
            "pair":             pos["pair"],
            "entry_price":      pos["entry_price"],
            "exit_price":       fill_price,
            "volume":           pos["volume"],
            "usd_invested":     pos["usd_value"],
            "pnl_usd":          pnl_usd,
            "pnl_pct":          pnl_pct,
            "exit_reason":      exit_reason,
            "hold_candles":     hold_candles,
            "hold_duration_secs": hold_secs,
            "opened_at_time":   pos["opened_at_time"],
            "closed_at_time":   candle_time,
            "stop_loss_pct":    pos["stop_loss_pct"],
            "take_profit_pct":  pos["take_profit_pct"],
        }
        self.trades.append(trade)

        emoji = "✅" if pnl_usd >= 0 else "🔴"
        logger.debug(
            "[BT] %s CLOSE %s @ $%.4f | P&L: $%.2f (%.2f%%) | %s",
            emoji, pos["pair"], fill_price, pnl_usd, pnl_pct, exit_reason,
        )
        return trade

    # ──────────────────────────────────────────────
    # SL/TP monitoring — uses intra-candle high/low
    # ──────────────────────────────────────────────

    def check_stops_and_tp(
        self,
        pair: str,
        current_price: float,   # candle close (used as fallback)
        audit_logger=None,
        candle: dict = None,    # full candle dict with high/low for intra-candle check
    ) -> list:
        """
        Uses candle high/low when available for realistic intra-candle SL/TP detection.
        SL has priority over TP (conservative).
        """
        candle_high  = candle["high"]  if candle else current_price
        candle_low   = candle["low"]   if candle else current_price
        candle_time  = candle["time"]  if candle else 0

        closed = []
        for pos_id, pos in list(self._positions.items()):
            if pos["pair"] != pair:
                continue

            exit_reason = None
            exit_price  = current_price

            # SL takes priority — check low first
            if candle_low <= pos["stop_loss_price"]:
                exit_reason = "stop_loss"
                exit_price  = pos["stop_loss_price"]
            elif candle_high >= pos["take_profit_price"]:
                exit_reason = "take_profit"
                exit_price  = pos["take_profit_price"]

            if exit_reason:
                trade = self.close_position(pos_id, exit_price, exit_reason, candle_time)
                if trade:
                    closed.append(trade)
        return closed
