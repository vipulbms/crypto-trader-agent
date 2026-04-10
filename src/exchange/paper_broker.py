"""
PaperBroker — simulates order execution using the paper_trading.db virtual wallet.
Same interface as KrakenClient so the rest of the system is unaware of the switch.
Stop-loss and take-profit are monitored on every price tick.
No Kraken API keys required.
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from ..storage.database import get_connection
from ..utils.tz import SGT, now_sgt, now_sgt_iso
from ..utils.timing import timed

logger = logging.getLogger(__name__)


def _now() -> str:
    return now_sgt_iso()


def _ts_now() -> int:
    return int(now_sgt().timestamp())


def _epoch_to_iso(ts: int) -> str:
    """Convert Unix epoch (seconds, UTC) to ISO-8601 string."""
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


class PaperBroker:
    """
    Virtual trading broker for paper mode.
    Reads/writes paper_trading.db exclusively.
    """

    def __init__(self, paper_db: str, slippage_pct: float = 0.05, maker_fee_pct: float = 0.16, config: dict = None):
        self._db = paper_db
        self._slippage  = slippage_pct / 100
        self._maker_fee = maker_fee_pct / 100
        self._config = config or {}

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
        timestamp_override: Optional[str] = None,
    ) -> dict:
        """
        Simulate a Limit buy order at the current Bid.
        Deducts USD from wallet and records position + stop/TP levels.
        """
        if side != "buy":
            raise ValueError("PaperBroker.place_order only supports 'buy' side for entries")

        # In a high-frequency quant strategy, we execute Limit Orders at the Bid.
        # Even limit orders incur queue position risk and small adverse selection
        # on a 30-minute cycle. Apply entry slippage symmetrically with exit. (#140)
        fill_price  = round(current_price * (1 + self._slippage), 8)
        volume      = round(usd_amount / fill_price, 8)
        actual_cost = round(fill_price * volume, 4)
        fee_usd     = round(actual_cost * self._maker_fee, 4)

        sl_price = round(fill_price * (1 - stop_loss_pct / 100), 8)
        tp_price = round(fill_price * (1 + take_profit_pct / 100), 8)

        conn = get_connection(self._db)

        # Deduct cost + fee from wallet — guard against overdraw (#129)
        row = conn.execute("SELECT cash_usd FROM paper_wallet ORDER BY id DESC LIMIT 1").fetchone()
        current_cash = float(row["cash_usd"]) if row else 0.0
        new_cash = current_cash - actual_cost - fee_usd
        if new_cash < 0:
            conn.close()
            logger.error(
                "[PAPER] OVERDRAW BLOCKED — would set cash to $%.4f for %s order $%.2f",
                new_cash, pair, actual_cost,
            )
            raise ValueError(
                f"Insufficient funds: need ${actual_cost + fee_usd:.2f}, have ${current_cash:.2f}"
            )
        conn.execute(
            "UPDATE paper_wallet SET cash_usd=?, updated_at=?",
            (round(new_cash, 4), _now()),
        )

        # Record position
        opened_at = timestamp_override or _now()
        conn.execute(
            """INSERT INTO paper_positions
               (opened_at, pair, side, entry_price, volume, usd_value,
                stop_loss_price, take_profit_price, stop_loss_pct, take_profit_pct,
                status, highest_price_seen, partial_exited)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (opened_at, pair, "buy", fill_price, volume, actual_cost,
             sl_price, tp_price, stop_loss_pct, take_profit_pct, "open",
             fill_price, 0),
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
        volume_override: Optional[float] = None,
        timestamp_override: Optional[str] = None,
    ) -> Optional[dict]:
        """
        Close an open paper position (fully or partially).

        Args:
            volume_override: if provided, close only this volume instead of the
                             full position volume (used for partial take-profit).
                             The position remains open with the remaining volume.
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
        close_volume = volume_override if volume_override is not None else pos["volume"]
        is_partial   = volume_override is not None

        # Sell at slight slippage below current price
        fill_price  = round(exit_price * (1 - self._slippage), 8)
        gross_out   = round(fill_price * close_volume, 4)
        fee_usd     = round(gross_out * 0.0026, 4)
        net_out     = round(gross_out - fee_usd, 4)
        # P&L proportional to the fraction of usd_value being closed
        fraction    = close_volume / pos["volume"] if pos["volume"] else 1.0
        cost_basis  = round(pos["usd_value"] * fraction, 4)
        pnl_usd     = round(net_out - cost_basis, 4)
        pnl_pct     = round(pnl_usd / cost_basis * 100, 2) if cost_basis else 0.0

        opened_ts   = datetime.fromisoformat(pos["opened_at"])
        # Use timestamp_override as "now" in backtest to avoid mixing candle/wall-clock time (#115)
        reference_ts = (
            datetime.fromisoformat(timestamp_override)
            if timestamp_override
            else now_sgt()
        )
        hold_secs   = int((reference_ts.replace(tzinfo=reference_ts.tzinfo or SGT) - opened_ts.replace(tzinfo=opened_ts.tzinfo or SGT)).total_seconds())

        if is_partial:
            # Keep position open; reduce volume and usd_value
            remaining_volume   = round(pos["volume"] - close_volume, 8)
            remaining_usd_value = round(pos["usd_value"] - cost_basis, 4)
            conn.execute(
                "UPDATE paper_positions SET volume=?, usd_value=?, partial_exited=1 WHERE id=?",
                (remaining_volume, remaining_usd_value, position_id),
            )
        else:
            conn.execute(
                "UPDATE paper_positions SET status='closed' WHERE id=?",
                (position_id,),
            )

        # Log closed/partial trade
        closed_at = timestamp_override or _now()
        conn.execute(
            """INSERT INTO paper_trades
               (opened_at, closed_at, pair, side, entry_price, exit_price,
                volume, usd_invested, pnl_usd, pnl_pct, exit_reason,
                hold_duration_secs, fee_usd, stop_loss_pct, take_profit_pct)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                pos["opened_at"], closed_at, pos["pair"], pos["side"],
                pos["entry_price"], fill_price, close_volume, cost_basis,
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
        partial_tag = "[PARTIAL] " if is_partial else ""
        logger.info(
            "[PAPER] %s %sCLOSE %s @ $%.2f | P&L: $%.2f (%.2f%%) | Reason: %s",
            emoji, partial_tag, pos["pair"], fill_price, pnl_usd, pnl_pct, exit_reason,
        )

        return {
            "pair":            pos["pair"],
            "entry_price":     pos["entry_price"],
            "exit_price":      fill_price,
            "volume":          close_volume,
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
        candle_ts: int = 0,
    ) -> list:
        """
        Check all open positions for the given pair.
        Execution order:
          1. Update highest_price_seen
          2. Trailing SL update (S12.2.1) — or breakeven (S12.3.1); mutually exclusive
          3. Full SL check
          4. Full TP check
        Returns list of closed trade summaries.
        """
        conn = get_connection(self._db)
        positions = conn.execute(
            "SELECT * FROM paper_positions WHERE status='open' AND pair=?",
            (pair,),
        ).fetchall()
        conn.close()

        trailing_cfg  = self._config.get("trailing_stop", {})
        breakeven_cfg = self._config.get("breakeven_stop", {})
        ts_override   = _epoch_to_iso(candle_ts) if candle_ts else None

        closed = []
        for pos in positions:
            pos = dict(pos)

            # 1. Update highest_price_seen
            highest = pos.get("highest_price_seen") or pos["entry_price"]
            if current_price > highest:
                highest = current_price
                upd = get_connection(self._db)
                upd.execute(
                    "UPDATE paper_positions SET highest_price_seen=? WHERE id=?",
                    (highest, pos["id"])
                )
                upd.commit()
                upd.close()
                pos["highest_price_seen"] = highest

            # 2a. Trailing SL update
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
                            "UPDATE paper_positions SET stop_loss_price=? WHERE id=?",
                            (trailing_sl, pos["id"])
                        )
                        upd2.commit()
                        upd2.close()
                        logger.debug(
                            "[TRAILING_SL] %s SL raised to $%.4f (%.1f%% below $%.4f)",
                            pair, trailing_sl, trail_pct, highest
                        )
                        pos["stop_loss_price"] = trailing_sl

            # 2b. Breakeven SL (mutually exclusive with trailing)
            elif breakeven_cfg.get("enabled", False):
                trigger_pct = breakeven_cfg.get("trigger_pct", 2.0)
                if (
                    current_price >= pos["entry_price"] * (1 + trigger_pct / 100)
                    and pos["stop_loss_price"] < pos["entry_price"]
                ):
                    upd3 = get_connection(self._db)
                    upd3.execute(
                        "UPDATE paper_positions SET stop_loss_price=? WHERE id=?",
                        (pos["entry_price"], pos["id"])
                    )
                    upd3.commit()
                    upd3.close()
                    logger.info(
                        "[BREAKEVEN_SL] %s SL moved to entry $%.4f", pair, pos["entry_price"]
                    )
                    pos["stop_loss_price"] = pos["entry_price"]

            # 3. Partial Take-Profit (S12.5.1) — fires once per position
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
                        volume_override=partial_volume,
                        timestamp_override=ts_override,
                    )
                    if ptrade:
                        closed.append(ptrade)
                        logger.info(
                            "[PARTIAL_TP] %s closed %.8f @ $%.4f (%.1f%% of position)",
                            pair, partial_volume, current_price, close_fraction * 100,
                        )
                    # Re-fetch position after partial close (volume + partial_exited updated)
                    upd_p = get_connection(self._db)
                    pos = dict(upd_p.execute(
                        "SELECT * FROM paper_positions WHERE id=?", (pos["id"],)
                    ).fetchone() or {})
                    upd_p.close()
                    if not pos or pos.get("status") == "closed":
                        continue
                    # Optionally move SL to entry (breakeven)
                    if partial_cfg.get("move_sl_to_breakeven", True) and pos["stop_loss_price"] < pos["entry_price"]:
                        upd_sl = get_connection(self._db)
                        upd_sl.execute(
                            "UPDATE paper_positions SET stop_loss_price=? WHERE id=?",
                            (pos["entry_price"], pos["id"])
                        )
                        upd_sl.commit()
                        upd_sl.close()
                        pos["stop_loss_price"] = pos["entry_price"]
                        logger.info("[PARTIAL_TP] %s SL moved to entry $%.4f", pair, pos["entry_price"])

            # 4. Full SL / TP check
            exit_reason = None
            exit_price  = current_price

            if current_price <= pos["stop_loss_price"]:
                hard_sl = pos["entry_price"] * (1 - pos["stop_loss_pct"] / 100)
                if trailing_cfg.get("enabled", False) and pos["stop_loss_price"] > hard_sl + 0.000001:
                    exit_reason = "trailing_stop"
                else:
                    exit_reason = "stop_loss"
                exit_price  = pos["stop_loss_price"]
            elif current_price >= pos["take_profit_price"]:
                exit_reason = "take_profit"
                exit_price  = pos["take_profit_price"]

            if exit_reason:
                trade = self.close_position(pos["id"], exit_price, exit_reason,
                                            timestamp_override=ts_override)
                if trade and audit_logger:
                    audit_logger.log_position_event(
                        pair=pair,
                        event_type=(
                            "stop_loss_triggered"
                            if exit_reason == "stop_loss"
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

    def force_close_all(self, prices: dict) -> list:
        """
        Mark-to-market close all open positions at the supplied end-of-backtest prices.
        Called after the last candle is processed to realise final P&L (backtest_end).

        Args:
            prices: {pair: close_price} — typically the last candle price per pair.

        Returns list of closed trade summaries.
        """
        conn = get_connection(self._db)
        positions = conn.execute(
            "SELECT * FROM paper_positions WHERE status='open'"
        ).fetchall()
        conn.close()

        closed = []
        for pos in positions:
            pos = dict(pos)
            price = prices.get(pos["pair"])
            if price is None:
                logger.warning("[PAPER] force_close_all: no price for %s — skipping", pos["pair"])
                continue
            trade = self.close_position(pos["id"], price, "backtest_end")
            if trade:
                closed.append(trade)

        if closed:
            logger.info("[PAPER] force_close_all: closed %d positions at backtest end", len(closed))
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
