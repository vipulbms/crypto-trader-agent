"""
Telegram notifier for trade alerts, daily summaries, and stop-loss notifications.
In paper mode, all messages are prefixed with [PAPER] and no approval is needed.
In live mode, hybrid approval flow waits for user confirmation.
"""

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

try:
    import telegram
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    TELEGRAM_AVAILABLE = True
except ImportError:
    TELEGRAM_AVAILABLE = False
    logger.warning("python-telegram-bot not installed. Notifications disabled.")


class Notifier:
    """
    Sends Telegram notifications for all trade events.
    Can be used without Telegram (logs to console only).
    """

    def __init__(self, config: dict, mode: str):
        notif_cfg = config.get("notifications", {})
        self._enabled = notif_cfg.get("telegram_enabled", True) and TELEGRAM_AVAILABLE
        self._mode    = mode
        self._prefix  = "[PAPER] " if mode == "paper" else "[LIVE] "
        self._bot: Optional[object] = None
        self._chat_id: Optional[str] = None
        self._healthcheck_url = notif_cfg.get("healthcheck_url", "")

        if self._enabled:
            token    = os.getenv("TELEGRAM_BOT_TOKEN")
            chat_id  = os.getenv("TELEGRAM_CHAT_ID")
            if token and chat_id:
                try:
                    self._bot     = telegram.Bot(token=token)
                    self._chat_id = chat_id
                    logger.info("Telegram notifier initialised")
                except Exception as e:
                    logger.warning("Telegram init failed: %s — notifications will log only", e)
                    self._enabled = False
            else:
                logger.info("TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set — logging only")
                self._enabled = False

    async def _send_coro(self, text: str) -> None:
        """Coroutine that actually sends the Telegram message."""
        try:
            await self._bot.send_message(
                chat_id=self._chat_id,
                text=text,
                parse_mode="HTML",
            )
        except Exception as e:
            logger.warning("Telegram send failed: %s", e)

    def _send(self, text: str) -> None:
        """Send a Telegram message, falling back to console log."""
        logger.info("NOTIFICATION: %s", text)
        if self._enabled and self._bot and self._chat_id:
            import asyncio
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self._send_coro(text))
            except RuntimeError:
                # No running loop — run synchronously
                asyncio.run(self._send_coro(text))

    # ──────────────────────────────────────────────
    # Notification types
    # ──────────────────────────────────────────────

    def send_trade_executed(self, trade: dict, mode: str) -> None:
        """Sent after every executed trade (paper or live)."""
        pair       = trade.get("pair", "?")
        side       = trade.get("side", "?").upper()
        price      = trade.get("fill_price") or trade.get("exit_price", 0)
        pnl_usd    = trade.get("pnl_usd")
        volume     = trade.get("volume", 0)
        sl         = trade.get("stop_loss_price")
        tp         = trade.get("take_profit_price")
        reason     = trade.get("exit_reason", "")
        usd_invested = trade.get("usd_invested")
        fee_usd      = trade.get("fee_usd")

        if pnl_usd is not None:
            # Closing trade
            emoji = "✅" if pnl_usd >= 0 else "🔴"
            msg = (
                f"{self._prefix}{emoji} <b>{side} CLOSED</b>: {pair}\n"
                f"Exit: ${price:.2f} | Vol: {volume:.6f}\n"
                f"P&L: ${pnl_usd:+.2f} | Reason: {reason}"
            )
        else:
            # Opening trade
            if usd_invested is not None:
                fee_str = f" fee: ${fee_usd:.2f}" if fee_usd else ""
                invested_str = f" | Invested: ${usd_invested:.2f}{fee_str}"
            else:
                invested_str = ""
            msg = (
                f"{self._prefix}🟡 <b>{side}</b>: {pair}\n"
                f"Fill: ${price:.2f} | Vol: {volume:.6f}{invested_str}\n"
                f"SL: ${sl:.2f} | TP: ${tp:.2f}"
            )
        self._send(msg)

    def send_stop_triggered(self, pair: str, pnl_usd: float, exit_price: float) -> None:
        """Alert when stop-loss fires."""
        msg = (
            f"{self._prefix}🔴 <b>STOP-LOSS HIT</b>: {pair}\n"
            f"Exit: ${exit_price:.2f} | Loss: ${pnl_usd:.2f}"
        )
        self._send(msg)

    def send_take_profit_triggered(self, pair: str, pnl_usd: float, exit_price: float) -> None:
        """Alert when take-profit fires."""
        msg = (
            f"{self._prefix}✅ <b>TAKE-PROFIT HIT</b>: {pair}\n"
            f"Exit: ${exit_price:.2f} | Gain: +${pnl_usd:.2f}"
        )
        self._send(msg)

    def send_daily_summary(self, summary: dict) -> None:
        """Send end-of-day P&L summary."""
        mode_label = "📄 PAPER" if self._mode == "paper" else "💰 LIVE"
        msg = (
            f"{self._prefix}{mode_label} <b>Daily Summary</b>\n"
            f"Balance: ${summary.get('balance', 0):.2f}\n"
            f"Daily P&L: ${summary.get('pnl_usd', 0):+.2f} ({summary.get('pnl_pct', 0):+.2f}%)\n"
            f"Trades today: {summary.get('trades_today', 0)}\n"
            f"Win rate: {summary.get('win_rate_pct', 0):.1f}%"
        )
        self._send(msg)

    def send_agent_started(self, balance: float, pairs: list, mode: str) -> None:
        """Notify when agent starts."""
        mode_label = "PAPER TRADING" if mode == "paper" else "LIVE TRADING"
        msg = (
            f"{self._prefix}🚀 <b>Agent Started — {mode_label}</b>\n"
            f"Balance: ${balance:.2f}\n"
            f"Pairs: {', '.join(pairs)}"
        )
        self._send(msg)

    def send_agent_stopped(self, mode: str) -> None:
        """Notify when agent stops."""
        mode_label = "PAPER TRADING" if mode == "paper" else "LIVE TRADING"
        msg = f"{self._prefix}🛑 <b>Agent Stopped — {mode_label}</b>"
        self._send(msg)

    def send_pnl_report(self, balance: float, pnl_usd: float, pnl_pct: float) -> None:
        """Send mid-day P&L report."""
        msg = (
            f"{self._prefix}📊 <b>6-Hour PnL Report</b>\n"
            f"Balance: ${balance:.2f}\n"
            f"Net P&L: ${pnl_usd:+.2f} ({pnl_pct:+.2f}%)"
        )
        self._send(msg)

    def send_error_alert(self, component: str, error: str) -> None:
        """Alert on critical errors."""
        msg = f"{self._prefix}⚠️ <b>Error in {component}</b>: {error}"
        self._send(msg)

    def send_daily_loss_limit_reached(self, loss_pct: float) -> None:
        """Alert when daily loss limit halts trading."""
        msg = (
            f"{self._prefix}🛑 <b>Daily Loss Limit Reached</b>\n"
            f"Loss: {loss_pct:.1f}% — trading halted for today"
        )
        self._send(msg)

    def send_circuit_breaker_tripped(self, consecutive_stops: int, pause_hours: float) -> None:
        """Alert when circuit breaker pauses all buys after consecutive stop-losses."""
        msg = (
            f"{self._prefix}⚡ <b>Circuit Breaker Tripped</b>\n"
            f"{consecutive_stops} consecutive stop-losses hit.\n"
            f"All new buys paused for {pause_hours:.0f} hours."
        )
        self._send(msg)

    def send_heartbeat(self, summary: dict) -> None:
        """Hourly 'still alive' message with last-hour activity summary."""
        balance    = summary.get("balance_usd", 0)
        pnl_usd    = summary.get("hourly_pnl_usd", 0)
        pnl_pct    = summary.get("hourly_pnl_pct", 0)
        cycles     = summary.get("cycles_completed", 0)
        open_pos   = summary.get("open_positions", 0)
        buys       = summary.get("buys_last_hour", 0)
        sells      = summary.get("sells_last_hour", 0)
        circuit    = summary.get("circuit_breaker_active", False)
        cb_note    = " | ⚡ Circuit breaker ACTIVE" if circuit else ""
        msg = (
            f"{self._prefix}💓 <b>Heartbeat</b>{cb_note}\n"
            f"Balance: ${balance:.2f} ({pnl_usd:+.2f} / {pnl_pct:+.2f}% last hour)\n"
            f"Cycles: {cycles} | Open: {open_pos} | Buys: {buys} | Sells: {sells}"
        )
        self._send(msg)

    def ping_healthcheck(self) -> None:
        """Pings an external webhook (e.g. healthchecks.io) to signal the bot is alive."""
        if not self._healthcheck_url:
            return
        logger.debug("Pinging healthcheck URL: %s", self._healthcheck_url)
        try:
            import urllib.request
            req = urllib.request.Request(self._healthcheck_url, method="GET")
            with urllib.request.urlopen(req, timeout=5) as response:
                if response.status not in (200, 202):
                    logger.warning("Healthcheck ping returned status %s", response.status)
        except Exception as e:
            logger.warning("Failed to ping healthcheck URL: %s", e)
