"""
PaperBroker — simulates order execution using the paper_trading.db virtual wallet.
Same interface as KrakenClient so the rest of the system is unaware of the switch.
Stop-loss and take-profit are monitored on every price tick.
No Kraken API keys required.
"""

import logging
from datetime import datetime
from typing import Optional

from ..storage.database import get_connection
from ..utils.tz import SGT, now_sgt, now_sgt_iso
from ..utils.timing import timed

logger = logging.getLogger(__name__)


def _now() -> str:
    return now_sgt_iso()


def _ts_now() -> int:
    return int(now_sgt().timestamp())


class PaperBroker:
    """
    Virtual trading broker for paper mode.
    Reads/writes paper_trading.db exclusively.
    """

    def __init__(self, paper_db: str, slippage_pct: float = 0.05, maker_fee_pct: float = 0.26):
        self._db = paper_db
        self._slippage  = slippage_pct / 100
        self._maker_fee = maker_fee_pct / 100

    # ──────────────────────────────────────────────
    # Account queries (same interface as KrakenClient)
    # ──────────────────────────────────────────────

    def get_balance(self) -> dict:
        """
        Returns:
            {
                "total_usd": float,
                "available_cash_usd": float,
                "holdings": {"BTC": float, "ETH": float, ...}
            }
        """
        conn = get_connection(self._db)
        row = conn.execute("SELECT cash_usd FROM paper_wallet ORDER BY id DESC LIMIT 1").fetchone()
        cash = float(row["cash_usd"]) if row else 0.0

        positions = conn.execute(
            "SELECT pair, volume, usd_value FROM paper_positions WHERE status='open'"
        ).fetchall()
        conn.close()

        holdings = {}
        open_pos_value = 0.0
        for pos in positions:
            coin = pos["pair"].split("/")[0]
            holdings[coin] = holdings.get(coin, 0.0) + float(pos["volume"])
            open_pos_value += float(pos["usd_value"])

        return {
            "total_usd":          round(cash + open_pos_value, 4),
            "available_cash_usd": cash,
            "holdings":           holdings,
        }

    def get_open_positions(self) -> list:
        conn = get_connection(self._db)
        rows = conn.execute(
            "SELECT * FROM paper_positions WHERE status='open'"
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def get_open_positions_count(self) -> int:
        conn = get_connection(self._db)
        count = conn.execute(
            "SELECT COUNT(*) FROM paper_positions WHERE status='open'"
        ).fetchone()[0]
        conn.close()
        return count

    # ──────────────────────────────────────────────
    # Order simulation
    # ──────────────────────────────────────────────

    @timed("pair", "side", "usd_amount", "current_price")
    def place_order(
        self,
        pair: str,
        side: str,
        usd_amount: float,
        current_price: float,
        stop_loss_pct: float,
        take_profit_pct: float,
    ) -> dict:
        """
        Simulate a buy order with slippage.
        Deducts USD from wallet and records position + stop/TP levels.
        """
        if side != "buy":
            raise ValueError("PaperBroker.place_order only supports 'buy' side for entries")

        # Apply slippage (buy at slightly higher price)
        fill_price  = round(current_price * (1 + self._slippage), 8)
        volume      = round(usd_amount / fill_price, 8)
        actual_cost = round(fill_price * volume, 4)
        fee_usd     = round(actual_cost * self._maker_fee, 4)

        sl_price = round(fill_price * (1 - stop_loss_pct / 100), 8)
        tp_price = round(fill_price * (1 + take_profit_pct / 100), 8)

        conn = get_connection(self._db)

        # Deduct cost + fee from wallet
        row = conn.execute("SELECT cash_usd FROM paper_wallet ORDER BY id DESC LIMIT 1").fetchone()
        current_cash = float(row["cash_usd"]) if row else 0.0
        new_cash = current_cash - actual_cost - fee_usd
        conn.execute(
            "UPDATE paper_wallet SET cash_usd=?, updated_at=?",
            (round(new_cash, 4), _now()),
        )

        # Record position
        conn.execute(
            """INSERT INTO paper_positions
               (opened_at, pair, side, entry_price, volume, usd_value,
                stop_loss_price, take_profit_price, stop_loss_pct, take_profit_pct, status)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (_now(), pair, "buy", fill_price, volume, actual_cost,
             sl_price, tp_price, stop_loss_pct, take_profit_pct, "open"),
        )
        conn.commit()
        position_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.close()

        logger.info(
            "[PAPER] BUY %s: %.8f @ $%.2f | SL: $%.2f | TP: $%.2f | Cash: $%.2f",
            pair, volume, fill_price, sl_price, tp_price, new_cash,
        )

        return {
            "pair":               pair,
            "side":               "buy",
            "volume":             volume,
            "fill_price":         fill_price,
            "usd_invested":       actual_cost,
            "fee_usd":            fee_usd,
            "slippage_pct":       self._slippage * 100,
            "stop_loss_price":    sl_price,
            "take_profit_price":  tp_price,
            "stop_loss_pct":      stop_loss_pct,
            "take_profit_pct":    take_profit_pct,
            "entry_order_id":     f"PAPER-{position_id}",
            "stop_loss_order_id": f"PAPER-SL-{position_id}",
            "take_profit_order_id": f"PAPER-TP-{position_id}",
            "position_id":        position_id,
        }

    @timed("position_id", "exit_price", "exit_reason")
    def close_position(
        self,
        position_id: int,
        exit_price: float,
        exit_reason: str,
    ) -> Optional[dict]:
        """
        Close an open paper position. Simulates slippage on exit.
        Returns trade summary or None if position not found.
        """
        conn = get_connection(self._db)
        pos = conn.execute(
            "SELECT * FROM paper_positions WHERE id=? AND status='open'",
            (position_id,),
        ).fetchone()
        if not pos:
            conn.close()
            return None

        pos = dict(pos)
        # Sell at slight slippage below current price
        fill_price  = round(exit_price * (1 - self._slippage), 8)
        gross_out   = round(fill_price * pos["volume"], 4)
        fee_usd     = round(gross_out * 0.0026, 4)
        net_out     = round(gross_out - fee_usd, 4)
        pnl_usd     = round(net_out - pos["usd_value"], 4)
        pnl_pct     = round(pnl_usd / pos["usd_value"] * 100, 2) if pos["usd_value"] else 0.0

        opened_ts   = datetime.fromisoformat(pos["opened_at"])
        hold_secs   = int((now_sgt() - opened_ts.replace(tzinfo=opened_ts.tzinfo or SGT)).total_seconds())

        # Update position status
        conn.execute(
            "UPDATE paper_positions SET status='closed' WHERE id=?",
            (position_id,),
        )

        # Log closed trade
        conn.execute(
            """INSERT INTO paper_trades
               (opened_at, closed_at, pair, side, entry_price, exit_price,
                volume, usd_invested, pnl_usd, pnl_pct, exit_reason,
                hold_duration_secs, fee_usd, stop_loss_pct, take_profit_pct)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                pos["opened_at"], _now(), pos["pair"], pos["side"],
                pos["entry_price"], fill_price, pos["volume"], pos["usd_value"],
                pnl_usd, pnl_pct, exit_reason, hold_secs,
                fee_usd, pos["stop_loss_pct"], pos["take_profit_pct"],
            ),
        )

        # Credit proceeds to wallet
        row = conn.execute("SELECT cash_usd FROM paper_wallet ORDER BY id DESC LIMIT 1").fetchone()
        current_cash = float(row["cash_usd"]) if row else 0.0
        conn.execute(
            "UPDATE paper_wallet SET cash_usd=?, updated_at=?",
            (round(current_cash + net_out, 4), _now()),
        )
        conn.commit()
        conn.close()

        emoji = "✅" if pnl_usd >= 0 else "🔴"
        logger.info(
            "[PAPER] %s CLOSE %s @ $%.2f | P&L: $%.2f (%.2f%%) | Reason: %s",
            emoji, pos["pair"], fill_price, pnl_usd, pnl_pct, exit_reason,
        )

        return {
            "pair":            pos["pair"],
            "entry_price":     pos["entry_price"],
            "exit_price":      fill_price,
            "volume":          pos["volume"],
            "pnl_usd":         pnl_usd,
            "pnl_pct":         pnl_pct,
            "exit_reason":     exit_reason,
            "hold_duration_secs": hold_secs,
        }

    # ──────────────────────────────────────────────
    # Stop-loss / take-profit monitoring
    # Called on every price tick from the main loop
    # ──────────────────────────────────────────────

    @timed("pair", "current_price")
    def check_stops_and_tp(
        self,
        pair: str,
        current_price: float,
        audit_logger=None,
    ) -> list:
        """
        Check all open positions for the given pair.
        Auto-closes any that hit stop-loss or take-profit.
        Returns list of closed trade summaries.
        """
        conn = get_connection(self._db)
        positions = conn.execute(
            "SELECT * FROM paper_positions WHERE status='open' AND pair=?",
            (pair,),
        ).fetchall()
        conn.close()

        closed = []
        for pos in positions:
            pos = dict(pos)
            exit_reason = None
            exit_price  = current_price

            if current_price <= pos["stop_loss_price"]:
                exit_reason = "stop_loss"
                exit_price  = pos["stop_loss_price"]
            elif current_price >= pos["take_profit_price"]:
                exit_reason = "take_profit"
                exit_price  = pos["take_profit_price"]

            if exit_reason:
                trade = self.close_position(pos["id"], exit_price, exit_reason)
                if trade and audit_logger:
                    audit_logger.log_position_event(
                        pair=pair,
                        event_type=(
                            "stop_loss_triggered"
                            if exit_reason == "stop_loss"
                            else "take_profit_triggered"
                        ),
                        entry_price=pos["entry_price"],
                        exit_price=exit_price,
                        pnl_usd=trade["pnl_usd"],
                        pnl_pct=trade["pnl_pct"],
                        hold_duration_seconds=trade["hold_duration_secs"],
                        take_profit_pct_used=pos["take_profit_pct"],
                        stop_loss_pct_used=pos["stop_loss_pct"],
                    )
                if trade:
                    closed.append(trade)
        return closed

    def get_daily_pnl(self, start_of_day_balance: float) -> dict:
        """Calculate P&L for today vs a starting balance snapshot."""
        balance = self.get_balance()
        pnl_usd = balance["total_usd"] - start_of_day_balance
        pnl_pct = (pnl_usd / start_of_day_balance * 100) if start_of_day_balance else 0.0
        return {
            "pnl_usd": round(pnl_usd, 2),
            "pnl_pct": round(pnl_pct, 2),
            "current_cash": balance["available_cash_usd"],
        }
