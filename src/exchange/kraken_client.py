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
        self._exchange.load_markets()
        self._pair_map = _build_ccxt_pair_map(config or {})
        self._db = live_db
        self._config = config or {}
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
        timestamp_override: Optional[str] = None,  # ignored in live mode
    ) -> dict:
        """
        Place Limit entry order at the bid + linked SL + TP on Kraken.
        Records position in live_trading.db for portfolio tracking.
        """
        if side != "buy":
            raise ValueError("KrakenClient.place_order only supports 'buy' side for entries")

        ccxt_pair = self._pair_map.get(pair, pair)
        
        # Calculate raw volume, then strictly apply Kraken's specific precision filters
        raw_volume = usd_amount / current_price
        volume = float(self._exchange.amount_to_precision(ccxt_pair, raw_volume))
        
        # Format the entry price tick increments
        safe_price = float(self._exchange.price_to_precision(ccxt_pair, current_price))

        # Entry limit order at the Bid price (Post-Only to guarantee Maker fee)
        entry = self._exchange.create_limit_buy_order(ccxt_pair, volume, safe_price, params={"postOnly": True})
        fill_price = float(entry.get("average") or entry.get("price") or current_price)
        fee_usd = float(entry.get("fee", {}).get("cost", 0.0)) if entry.get("fee") else 0.0
        actual_cost = round(fill_price * volume, 4)

        sl_price = round(fill_price * (1 - stop_loss_pct / 100), 8)
        tp_price = round(fill_price * (1 + take_profit_pct / 100), 8)

        # We no longer place SL/TP here natively before the Limit order fills.
        # Instead, check_stops_and_tp will poll the entry order and place SL/TP natively
        # once the entry order status flips to 'closed' (filled).
        sl_order_id = "pending_fill"
        tp_order_id = "pending_fill"

        # Record position in DB
        conn = get_connection(self._db)
        conn.execute(
            """INSERT INTO live_positions
               (opened_at, pair, side, entry_price, volume, usd_value,
                stop_loss_price, take_profit_price, stop_loss_pct, take_profit_pct,
                highest_price_seen, partial_exited,
                entry_order_id, stop_loss_order_id, take_profit_order_id, status)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (_now(), pair, "buy", fill_price, volume, actual_cost,
             sl_price, tp_price, stop_loss_pct, take_profit_pct,
             fill_price, 0,
             entry["id"], sl_order_id, tp_order_id, "open"),
        )
        conn.commit()
        position_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.close()

        logger.info(
            "[LIVE] BUY LIMIT %s: %.8f @ $%.2f | SL: $%.2f | TP: $%.2f | entry=%s",
            pair, volume, fill_price, sl_price, tp_price,
            entry["id"]
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
            "stop_loss_order_id":    sl_order_id,
            "take_profit_order_id":  tp_order_id,
            "position_id":           position_id,
        }

    def close_position(
        self,
        position_id: int,
        exit_price: float,
        exit_reason: str,
        volume_override: Optional[float] = None,
        timestamp_override: Optional[str] = None,  # ignored in live mode
    ) -> Optional[dict]:
        """
        Close an open live position (fully or partially).

        Args:
            volume_override: if provided, execute a partial market sell for this
                             volume only. Position stays open; volume/usd_value
                             are reduced and partial_exited=1 is set.

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

        close_volume = volume_override if volume_override is not None else pos["volume"]
        is_partial   = volume_override is not None

        fill_price = exit_price
        exit_order_id = None

        if exit_reason in ("agent_sell", "fallback_stop_loss", "fallback_take_profit",
                           "global_kill_switch", "partial_take_profit"):
            # LLM wants to exit, fallback triggered, or partial TP — place market sell now
            sell = self._exchange.create_market_sell_order(ccxt_pair, close_volume)
            fill_price = float(sell.get("average") or sell.get("price") or exit_price)
            exit_order_id = sell["id"]
            if not is_partial:
                # Cancel pending SL and TP orders if any exist natively
                for oid_key in ("stop_loss_order_id", "take_profit_order_id"):
                    oid = pos.get(oid_key)
                    if oid and oid != "pending_fill":
                        try:
                            self._exchange.cancel_order(oid, ccxt_pair)
                        except Exception as e:
                            logger.warning("Could not cancel %s %s: %s", oid_key, oid, e)
        else:
            # stop_loss or take_profit was triggered by Kraken natively.
            # Cancel the counter-order (e.g. if SL fired, cancel TP).
            counter_key = "take_profit_order_id" if exit_reason == "stop_loss" else "stop_loss_order_id"
            counter_oid = pos.get(counter_key)
            if counter_oid and counter_oid != "pending_fill":
                try:
                    self._exchange.cancel_order(counter_oid, ccxt_pair)
                except Exception as e:
                    logger.warning("Could not cancel counter order %s: %s", counter_oid, e)

        fraction    = close_volume / pos["volume"] if pos["volume"] else 1.0
        cost_basis  = round(pos["usd_value"] * fraction, 4)
        gross_out   = round(fill_price * close_volume, 4)
        fee_usd     = round(gross_out * 0.0026, 4)
        net_out     = round(gross_out - fee_usd, 4)
        pnl_usd     = round(net_out - cost_basis, 4)
        pnl_pct     = round(pnl_usd / cost_basis * 100, 2) if cost_basis else 0.0

        opened_ts = datetime.fromisoformat(pos["opened_at"])
        hold_secs = int((now_sgt() - opened_ts.replace(tzinfo=opened_ts.tzinfo or SGT)).total_seconds())

        if is_partial:
            remaining_volume    = round(pos["volume"] - close_volume, 8)
            remaining_usd_value = round(pos["usd_value"] - cost_basis, 4)
            conn.execute(
                "UPDATE live_positions SET volume=?, usd_value=?, partial_exited=1 WHERE id=?",
                (remaining_volume, remaining_usd_value, position_id),
            )
        else:
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
                pos["entry_price"], fill_price, close_volume, cost_basis,
                pnl_usd, pnl_pct, exit_reason, hold_secs,
                fee_usd, pos["stop_loss_pct"], pos["take_profit_pct"],
                pos["entry_order_id"], exit_order_id,
            ),
        )
        conn.commit()
        conn.close()

        emoji = "✅" if pnl_usd >= 0 else "🔴"
        partial_tag = "[PARTIAL] " if is_partial else ""
        logger.info(
            "[LIVE] %s %sCLOSE %s @ $%.2f | P&L: $%.2f (%.2f%%) | Reason: %s",
            emoji, partial_tag, pos["pair"], fill_price, pnl_usd, pnl_pct, exit_reason,
        )

        return {
            "pair":               pos["pair"],
            "entry_price":        pos["entry_price"],
            "exit_price":         fill_price,
            "volume":             close_volume,
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

            # 0. If the limit entry hasn't been confirmed filled, poll it.
            if pos.get("stop_loss_order_id") == "pending_fill" or pos.get("take_profit_order_id") == "pending_fill":
                try:
                    entry_order = self._exchange.fetch_order(pos["entry_order_id"], ccxt_pair)
                    status = entry_order.get("status")
                    if status == "closed":
                        # Entry filled! Place native SL/TP
                        sl_order = self._exchange.create_order(
                            ccxt_pair, "stop-loss", "sell", pos["volume"], pos["stop_loss_price"],
                            {"stopPrice": pos["stop_loss_price"]}
                        )
                        tp_order = self._exchange.create_order(
                            ccxt_pair, "take-profit", "sell", pos["volume"], pos["take_profit_price"],
                            {"stopPrice": pos["take_profit_price"]}
                        )
                        
                        up_conn = get_connection(self._db)
                        up_conn.execute(
                            "UPDATE live_positions SET stop_loss_order_id=?, take_profit_order_id=? WHERE id=?",
                            (sl_order["id"], tp_order["id"], pos["id"])
                        )
                        up_conn.commit()
                        up_conn.close()
                        
                        pos["stop_loss_order_id"] = sl_order["id"]
                        pos["take_profit_order_id"] = tp_order["id"]
                        logger.info("Placed SL/TP for filled position %s. SL: %s, TP: %s", pos["id"], sl_order["id"], tp_order["id"])
                    
                    elif status in ("canceled", "expired", "rejected"):
                        # Entry limit order failed. Clean up tracker DB.
                        up_conn = get_connection(self._db)
                        up_conn.execute("UPDATE live_positions SET status='closed' WHERE id=?", (pos["id"],))
                        up_conn.commit()
                        up_conn.close()
                        logger.warning("Entry order %s was %s natively. Closed tracker.", pos["entry_order_id"], status)
                        continue
                    else:
                        # Entry still open, check if we need to chase the bid (Post-Only / Maker Fee Mitigation)
                        opened_ts = datetime.fromisoformat(pos["opened_at"])
                        elapsed_secs = (now_sgt() - opened_ts.replace(tzinfo=opened_ts.tzinfo or SGT)).total_seconds()
                        if elapsed_secs >= 60:
                            logger.info("Chasing bid for %s. Elapsed: %.1fs", pos["pair"], elapsed_secs)
                            try:
                                self._exchange.cancel_order(pos["entry_order_id"], ccxt_pair)
                                
                                # Replace with new limit order at the precise new Best Bid (Post-Only)
                                raw_new_vol = pos["usd_value"] / current_price
                                new_volume = float(self._exchange.amount_to_precision(ccxt_pair, raw_new_vol))
                                safe_price = float(self._exchange.price_to_precision(ccxt_pair, current_price))
                                
                                new_entry = self._exchange.create_limit_buy_order(
                                    ccxt_pair, new_volume, safe_price, params={"postOnly": True}
                                )
                                
                                new_fill_price = float(new_entry.get("average") or new_entry.get("price") or current_price)
                                new_sl_price = round(new_fill_price * (1 - pos["stop_loss_pct"] / 100), 8)
                                new_tp_price = round(new_fill_price * (1 + pos["take_profit_pct"] / 100), 8)
                                
                                up_conn = get_connection(self._db)
                                up_conn.execute(
                                    """UPDATE live_positions 
                                       SET entry_order_id=?, entry_price=?, volume=?, stop_loss_price=?, take_profit_price=?, opened_at=? 
                                       WHERE id=?""",
                                    (new_entry["id"], new_fill_price, new_volume, new_sl_price, new_tp_price, _now(), pos["id"])
                                )
                                up_conn.commit()
                                up_conn.close()
                                
                                pos["entry_order_id"] = new_entry["id"]
                                pos["opened_at"] = _now()
                            except Exception as e:
                                logger.warning("Could not chase limit order %s: %s", pos["entry_order_id"], e)
                        
                        # Skip SL/TP checks this cycle since entry isn't filled yet
                        continue
                except Exception as e:
                    logger.debug("Could not verify entry fill %s: %s", pos["entry_order_id"], e)
                    continue

            # 1a. Update highest_price_seen (S12.2.1)
            highest = pos.get("highest_price_seen") or pos["entry_price"]
            if current_price > highest:
                highest = current_price
                upd = get_connection(self._db)
                upd.execute(
                    "UPDATE live_positions SET highest_price_seen=? WHERE id=?",
                    (highest, pos["id"])
                )
                upd.commit()
                upd.close()
                pos["highest_price_seen"] = highest

            trailing_cfg  = self._config.get("trailing_stop", {})
            breakeven_cfg = self._config.get("breakeven_stop", {})

            # 1b. Trailing SL update (S12.2.1)
            if trailing_cfg.get("enabled", False):
                pair_override = trailing_cfg.get("per_pair_overrides", {}).get(pair)
                if isinstance(pair_override, dict):
                    trail_pct    = pair_override.get("trail_pct",         trailing_cfg.get("trail_pct", 5.0))
                    activate_pct = pair_override.get("activate_after_pct", trailing_cfg.get("activate_after_pct", 3.0))
                else:
                    trail_pct    = pair_override if pair_override is not None else trailing_cfg.get("trail_pct", 5.0)
                    activate_pct = trailing_cfg.get("activate_after_pct", 3.0)
                gain_pct = (current_price - pos["entry_price"]) / pos["entry_price"] * 100
                if gain_pct >= activate_pct:
                    trailing_sl = round(highest * (1 - trail_pct / 100), 8)
                    if trailing_sl > pos["stop_loss_price"]:
                        upd2 = get_connection(self._db)
                        upd2.execute(
                            "UPDATE live_positions SET stop_loss_price=? WHERE id=?",
                            (trailing_sl, pos["id"])
                        )
                        upd2.commit()
                        upd2.close()
                        # Also update native SL order on Kraken if placed
                        sl_oid = pos.get("stop_loss_order_id")
                        if sl_oid and sl_oid != "pending_fill":
                            try:
                                self._exchange.cancel_order(sl_oid, ccxt_pair)
                                safe_sl = float(self._exchange.price_to_precision(ccxt_pair, trailing_sl))
                                new_sl = self._exchange.create_order(
                                    ccxt_pair, "stop-loss", "sell", pos["volume"], safe_sl,
                                    {"stopPrice": safe_sl}
                                )
                                upd3 = get_connection(self._db)
                                upd3.execute(
                                    "UPDATE live_positions SET stop_loss_order_id=? WHERE id=?",
                                    (new_sl["id"], pos["id"])
                                )
                                upd3.commit()
                                upd3.close()
                                pos["stop_loss_order_id"] = new_sl["id"]
                            except Exception as e:
                                logger.warning("[TRAILING_SL] Could not update Kraken native SL: %s", e)
                        logger.debug(
                            "[TRAILING_SL] %s SL raised to $%.4f (%.1f%% below $%.4f)",
                            pair, trailing_sl, trail_pct, highest
                        )
                        pos["stop_loss_price"] = trailing_sl

            # 1c. Breakeven SL (mutually exclusive with trailing — S12.3.1)
            elif breakeven_cfg.get("enabled", False):
                trigger_pct = breakeven_cfg.get("trigger_pct", 2.0)
                if (
                    current_price >= pos["entry_price"] * (1 + trigger_pct / 100)
                    and pos["stop_loss_price"] < pos["entry_price"]
                ):
                    upd4 = get_connection(self._db)
                    upd4.execute(
                        "UPDATE live_positions SET stop_loss_price=? WHERE id=?",
                        (pos["entry_price"], pos["id"])
                    )
                    upd4.commit()
                    upd4.close()
                    logger.info(
                        "[BREAKEVEN_SL] %s SL moved to entry $%.4f", pair, pos["entry_price"]
                    )
                    pos["stop_loss_price"] = pos["entry_price"]

            # 1d. Partial Take-Profit (S12.5.1) — fires once per position
            partial_cfg = self._config.get("partial_take_profit", {})
            if (
                partial_cfg.get("enabled", False)
                and not pos.get("partial_exited", 0)
            ):
                trigger_ratio = partial_cfg.get("trigger_pct_of_tp", 50) / 100
                partial_trigger_price = pos["entry_price"] * (
                    1 + pos["take_profit_pct"] * trigger_ratio / 100
                )
                if current_price >= partial_trigger_price:
                    close_fraction = partial_cfg.get("close_fraction", 0.5)
                    partial_volume = round(pos["volume"] * close_fraction, 8)
                    ptrade = self.close_position(
                        pos["id"], current_price, "partial_take_profit",
                        volume_override=partial_volume
                    )
                    if ptrade:
                        closed.append(ptrade)
                        logger.info(
                            "[PARTIAL_TP] %s closed %.8f @ $%.4f (%.1f%% of position)",
                            pair, partial_volume, current_price, close_fraction * 100,
                        )
                    # Re-fetch position after partial close
                    upd_p = get_connection(self._db)
                    pos = dict(upd_p.execute(
                        "SELECT * FROM live_positions WHERE id=?", (pos["id"],)
                    ).fetchone() or {})
                    upd_p.close()
                    if not pos or pos.get("status") == "closed":
                        continue
                    # Optionally move SL to entry (breakeven)
                    if partial_cfg.get("move_sl_to_breakeven", True) and pos["stop_loss_price"] < pos["entry_price"]:
                        upd_sl = get_connection(self._db)
                        upd_sl.execute(
                            "UPDATE live_positions SET stop_loss_price=? WHERE id=?",
                            (pos["entry_price"], pos["id"])
                        )
                        upd_sl.commit()
                        upd_sl.close()
                        pos["stop_loss_price"] = pos["entry_price"]
                        logger.info("[PARTIAL_TP] %s SL moved to entry $%.4f", pair, pos["entry_price"])

            # 2. Check if Kraken already executed SL or TP natively
            hard_sl = pos["entry_price"] * (1 - pos["stop_loss_pct"] / 100)
            trailing_enabled = trailing_cfg.get("enabled", False)
            for order_id, reason, price_key in [
                (pos.get("stop_loss_order_id"),   "stop_loss",   "stop_loss_price"),
                (pos.get("take_profit_order_id"), "take_profit", "take_profit_price"),
            ]:
                if not order_id or order_id == "pending_fill":
                    continue
                try:
                    order = self._exchange.fetch_order(order_id, ccxt_pair)
                    if order.get("status") == "closed":
                        if reason == "stop_loss" and trailing_enabled and pos["stop_loss_price"] > hard_sl + 0.000001:
                            exit_reason = "trailing_stop"
                        else:
                            exit_reason = reason
                        fill = order.get("average") or order.get("price")
                        exit_price  = float(fill) if fill else pos[price_key]
                        break
                except Exception as e:
                    logger.debug("Could not fetch order %s: %s", order_id, e)

            # 2. Price-based fallback (native order may not have been placed)
            if exit_reason is None:
                if current_price <= pos["stop_loss_price"]:
                    if trailing_enabled and pos["stop_loss_price"] > hard_sl + 0.000001:
                        exit_reason = "trailing_stop"
                    else:
                        exit_reason = "fallback_stop_loss"
                    exit_price  = pos["stop_loss_price"]
                elif current_price >= pos["take_profit_price"]:
                    exit_reason = "fallback_take_profit"
                    exit_price  = pos["take_profit_price"]

            if exit_reason:
                trade = self.close_position(pos["id"], exit_price, exit_reason)
                if trade and audit_logger:
                    audit_logger.log_position_event(
                        pair=pair,
                        event_type=(
                            "stop_loss_triggered"
                            if "stop_loss" in exit_reason
                            else "trailing_stop_triggered"
                            if exit_reason == "trailing_stop"
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
