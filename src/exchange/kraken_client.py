"""
KrakenClient — thin wrapper around ccxt.kraken for live trading.
Only used in LIVE mode. Never imported in paper mode.

Position tracking mirrors PaperBroker: open/closed positions are persisted
in live_trading.db (live_positions + live_trades tables) so the rest of the
system can use the same interface regardless of mode.
"""

import logging
from datetime import datetime
from typing import Optional

import ccxt

from ..storage.database import get_connection
from ..utils.tz import SGT, now_sgt, now_sgt_iso

logger = logging.getLogger(__name__)


def _now() -> str:
    return now_sgt_iso()


def _build_ccxt_pair_map(config: dict) -> dict:
    return {p["pair"]: p["pair"] for p in config.get("trading", {}).get("pairs", [])}


class KrakenClient:
    """Live trading client. Requires KRAKEN_API_KEY and KRAKEN_API_SECRET."""

    def __init__(self, api_key: str, api_secret: str, config: dict = None, live_db: str = "live_trading.db"):
        self._exchange = ccxt.kraken({
            "apiKey":  api_key,
            "secret":  api_secret,
            "enableRateLimit": True,
        })
        self._pair_map = _build_ccxt_pair_map(config or {})
        self._db = live_db
        logger.info("KrakenClient initialised (live mode) db=%s", live_db)

    # ──────────────────────────────────────────────
    # Account queries
    # ──────────────────────────────────────────────

    def get_balance(self) -> dict:
        """
        Returns total_usd = available_cash + entry cost of open positions.
        Mirrors PaperBroker.get_balance() exactly (uses entry cost, not market value).
        """
        raw = self._exchange.fetch_balance()
        cash = float(raw.get("free", {}).get("USD", 0.0))

        conn = get_connection(self._db)
        positions = conn.execute(
            "SELECT pair, volume, usd_value FROM live_positions WHERE status='open'"
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
            "SELECT * FROM live_positions WHERE status='open'"
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def get_open_positions_count(self) -> int:
        conn = get_connection(self._db)
        count = conn.execute(
            "SELECT COUNT(*) FROM live_positions WHERE status='open'"
        ).fetchone()[0]
        conn.close()
        return count

    # ──────────────────────────────────────────────
    # Order placement
    # ──────────────────────────────────────────────

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
        Place Limit entry order at the bid + linked SL + TP on Kraken.
        Records position in live_trading.db for portfolio tracking.
        """
        if side != "buy":
            raise ValueError("KrakenClient.place_order only supports 'buy' side for entries")

        ccxt_pair = self._pair_map.get(pair, pair)
        # Using a Limit order, volume is exact at current_price
        volume = round(usd_amount / current_price, 8)

        # Entry limit order at the Bid price
        entry = self._exchange.create_limit_buy_order(ccxt_pair, volume, current_price)
        fill_price = float(entry.get("average") or entry.get("price") or current_price)
        fee_usd = float(entry.get("fee", {}).get("cost", 0.0)) if entry.get("fee") else 0.0
        actual_cost = round(fill_price * volume, 4)

        sl_price = round(fill_price * (1 - stop_loss_pct / 100), 8)
        tp_price = round(fill_price * (1 + take_profit_pct / 100), 8)

        # Stop-loss order (Kraken native — survives app restarts)
        sl_order = self._exchange.create_order(
            ccxt_pair, "stop-loss", "sell", volume, sl_price,
            {"stopPrice": sl_price}
        )

        # Take-profit order
        tp_order = self._exchange.create_order(
            ccxt_pair, "take-profit", "sell", volume, tp_price,
            {"stopPrice": tp_price}
        )

        # Record position in DB
        conn = get_connection(self._db)
        conn.execute(
            """INSERT INTO live_positions
               (opened_at, pair, side, entry_price, volume, usd_value,
                stop_loss_price, take_profit_price, stop_loss_pct, take_profit_pct,
                entry_order_id, stop_loss_order_id, take_profit_order_id, status)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (_now(), pair, "buy", fill_price, volume, actual_cost,
             sl_price, tp_price, stop_loss_pct, take_profit_pct,
             entry["id"], sl_order["id"], tp_order["id"], "open"),
        )
        conn.commit()
        position_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.close()

        logger.info(
            "[LIVE] BUY %s: %.8f @ $%.2f | SL: $%.2f | TP: $%.2f | entry=%s sl=%s tp=%s",
            pair, volume, fill_price, sl_price, tp_price,
            entry["id"], sl_order["id"], tp_order["id"],
        )

        return {
            "pair":                  pair,
            "side":                  "buy",
            "volume":                volume,
            "fill_price":            fill_price,
            "usd_invested":          actual_cost,
            "fee_usd":               fee_usd,
            "slippage_pct":          0.0,  # live fill; actual slippage embedded in fill_price
            "stop_loss_price":       sl_price,
            "take_profit_price":     tp_price,
            "stop_loss_pct":         stop_loss_pct,
            "take_profit_pct":       take_profit_pct,
            "entry_order_id":        entry["id"],
            "stop_loss_order_id":    sl_order["id"],
            "take_profit_order_id":  tp_order["id"],
            "position_id":           position_id,
        }

    def close_position(
        self,
        position_id: int,
        exit_price: float,
        exit_reason: str,
    ) -> Optional[dict]:
        """
        Close an open live position.
        - Places a market sell if exit_reason is agent_sell (LLM-initiated).
        - For stop_loss / take_profit: Kraken already executed the native order;
          we only update our DB record and cancel the remaining counter-order.
        Returns trade summary dict matching PaperBroker.close_position().
        """
        conn = get_connection(self._db)
        pos = conn.execute(
            "SELECT * FROM live_positions WHERE id=? AND status='open'",
            (position_id,),
        ).fetchone()
        if not pos:
            conn.close()
            return None

        pos = dict(pos)
        ccxt_pair = self._pair_map.get(pos["pair"], pos["pair"])

        fill_price = exit_price
        exit_order_id = None

        if exit_reason == "agent_sell":
            # LLM wants to exit — place market sell now
            sell = self._exchange.create_market_sell_order(ccxt_pair, pos["volume"])
            fill_price = float(sell.get("average") or sell.get("price") or exit_price)
            exit_order_id = sell["id"]
            # Cancel pending SL and TP orders
            for oid_key in ("stop_loss_order_id", "take_profit_order_id"):
                oid = pos.get(oid_key)
                if oid:
                    try:
                        self._exchange.cancel_order(oid, ccxt_pair)
                    except Exception as e:
                        logger.warning("Could not cancel %s %s: %s", oid_key, oid, e)
        else:
            # stop_loss or take_profit was triggered by Kraken natively.
            # Cancel the counter-order (e.g. if SL fired, cancel TP).
            counter_key = "take_profit_order_id" if exit_reason == "stop_loss" else "stop_loss_order_id"
            counter_oid = pos.get(counter_key)
            if counter_oid:
                try:
                    self._exchange.cancel_order(counter_oid, ccxt_pair)
                except Exception as e:
                    logger.warning("Could not cancel counter order %s: %s", counter_oid, e)

        gross_out = round(fill_price * pos["volume"], 4)
        fee_usd   = round(gross_out * 0.0026, 4)
        net_out   = round(gross_out - fee_usd, 4)
        pnl_usd   = round(net_out - pos["usd_value"], 4)
        pnl_pct   = round(pnl_usd / pos["usd_value"] * 100, 2) if pos["usd_value"] else 0.0

        opened_ts = datetime.fromisoformat(pos["opened_at"])
        hold_secs = int((now_sgt() - opened_ts.replace(tzinfo=opened_ts.tzinfo or SGT)).total_seconds())

        conn.execute(
            "UPDATE live_positions SET status='closed' WHERE id=?",
            (position_id,),
        )
        conn.execute(
            """INSERT INTO live_trades
               (opened_at, closed_at, pair, side, entry_price, exit_price,
                volume, usd_invested, pnl_usd, pnl_pct, exit_reason,
                hold_duration_secs, fee_usd, stop_loss_pct, take_profit_pct,
                entry_order_id, exit_order_id)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                pos["opened_at"], _now(), pos["pair"], pos["side"],
                pos["entry_price"], fill_price, pos["volume"], pos["usd_value"],
                pnl_usd, pnl_pct, exit_reason, hold_secs,
                fee_usd, pos["stop_loss_pct"], pos["take_profit_pct"],
                pos["entry_order_id"], exit_order_id,
            ),
        )
        conn.commit()
        conn.close()

        emoji = "✅" if pnl_usd >= 0 else "🔴"
        logger.info(
            "[LIVE] %s CLOSE %s @ $%.2f | P&L: $%.2f (%.2f%%) | Reason: %s",
            emoji, pos["pair"], fill_price, pnl_usd, pnl_pct, exit_reason,
        )

        return {
            "pair":               pos["pair"],
            "entry_price":        pos["entry_price"],
            "exit_price":         fill_price,
            "volume":             pos["volume"],
            "pnl_usd":            pnl_usd,
            "pnl_pct":            pnl_pct,
            "exit_reason":        exit_reason,
            "hold_duration_secs": hold_secs,
        }

    # ──────────────────────────────────────────────
    # Stop-loss / take-profit monitoring
    # Called on every price tick from the main loop
    # ──────────────────────────────────────────────

    def check_stops_and_tp(
        self,
        pair: str,
        current_price: float,
        audit_logger=None,
    ) -> list:
        """
        Check open positions for this pair.

        First checks whether Kraken's native SL/TP orders have filled (authoritative).
        Falls back to price-based check in case native orders weren't placed or failed.

        Returns list of closed trade summaries (same structure as PaperBroker).
        """
        conn = get_connection(self._db)
        positions = conn.execute(
            "SELECT * FROM live_positions WHERE status='open' AND pair=?",
            (pair,),
        ).fetchall()
        conn.close()

        closed = []
        ccxt_pair = self._pair_map.get(pair, pair)

        for pos in positions:
            pos = dict(pos)
            exit_reason = None
            exit_price  = current_price

            # 1. Check if Kraken already executed SL or TP natively
            for order_id, reason, price_key in [
                (pos.get("stop_loss_order_id"),   "stop_loss",   "stop_loss_price"),
                (pos.get("take_profit_order_id"), "take_profit", "take_profit_price"),
            ]:
                if not order_id:
                    continue
                try:
                    order = self._exchange.fetch_order(order_id, ccxt_pair)
                    if order.get("status") == "closed":
                        exit_reason = reason
                        fill = order.get("average") or order.get("price")
                        exit_price  = float(fill) if fill else pos[price_key]
                        break
                except Exception as e:
                    logger.debug("Could not fetch order %s: %s", order_id, e)

            # 2. Price-based fallback (native order may not have been placed)
            if exit_reason is None:
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

    # ──────────────────────────────────────────────
    # Daily P&L
    # ──────────────────────────────────────────────

    def get_daily_pnl(self, start_of_day_balance: float) -> dict:
        balance = self.get_balance()
        pnl_usd = balance["total_usd"] - start_of_day_balance
        pnl_pct = (pnl_usd / start_of_day_balance * 100) if start_of_day_balance else 0.0
        return {
            "pnl_usd": round(pnl_usd, 2),
            "pnl_pct": round(pnl_pct, 2),
            "current_cash": balance["available_cash_usd"],
        }

    # ──────────────────────────────────────────────
    # Utilities
    # ──────────────────────────────────────────────

    def cancel_order(self, order_id: str, pair: str) -> bool:
        try:
            ccxt_pair = self._pair_map.get(pair, pair)
            self._exchange.cancel_order(order_id, ccxt_pair)
            logger.info("Cancelled order %s for %s", order_id, pair)
            return True
        except Exception as e:
            logger.error("Failed to cancel order %s: %s", order_id, e)
            return False

    def validate_order(self, pair: str, side: str, volume: float, price: float) -> dict:
        ccxt_pair = self._pair_map.get(pair, pair)
        return self._exchange.create_order(
            ccxt_pair, "limit", side, volume, price,
            {"validate": True}
        )
