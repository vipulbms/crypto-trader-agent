"""
KrakenClient — thin wrapper around ccxt.kraken for live trading.
Only used in LIVE mode. Never imported in paper mode.
"""

import logging
from typing import Optional

import ccxt

logger = logging.getLogger(__name__)

# ccxt uses BTC/USD; Kraken internally uses XBT but ccxt handles the mapping
KRAKEN_PAIR_MAP = {
    "BTC/USD": "BTC/USD",
    "ETH/USD": "ETH/USD",
    "BNB/USD": "BNB/USD",
    "SOL/USD": "SOL/USD",
}


class KrakenClient:
    """Live trading client. Requires KRAKEN_API_KEY and KRAKEN_API_SECRET."""

    def __init__(self, api_key: str, api_secret: str):
        self._exchange = ccxt.kraken({
            "apiKey":  api_key,
            "secret":  api_secret,
            "enableRateLimit": True,
        })
        logger.info("KrakenClient initialised (live mode)")

    # ──────────────────────────────────────────────
    # Account queries
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
        raw = self._exchange.fetch_balance()
        usd_total = raw.get("total", {}).get("USD", 0.0)
        usd_free  = raw.get("free", {}).get("USD", 0.0)
        holdings  = {
            coin: raw["total"].get(coin, 0.0)
            for coin in ["BTC", "ETH", "BNB", "SOL"]
        }
        return {
            "total_usd":          float(usd_total),
            "available_cash_usd": float(usd_free),
            "holdings":           holdings,
        }

    def get_open_positions(self) -> list:
        """
        Returns list of open orders placed by this agent.
        Each item: {"pair", "side", "volume", "price", "order_id", "role"}
        """
        orders = self._exchange.fetch_open_orders()
        result = []
        for o in orders:
            result.append({
                "pair":     o["symbol"],
                "side":     o["side"],
                "volume":   o["amount"],
                "price":    o["price"],
                "order_id": o["id"],
                "status":   o["status"],
            })
        return result

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
        Place an entry market order + linked stop-loss + take-profit.
        All three orders are placed immediately after the entry fills.

        Returns dict with order IDs and calculated prices.
        """
        ccxt_pair = KRAKEN_PAIR_MAP.get(pair, pair)
        volume = round(usd_amount / current_price, 8)

        # Entry order
        entry = self._exchange.create_market_buy_order(ccxt_pair, volume)
        fill_price = float(entry.get("average") or entry.get("price") or current_price)
        logger.info("LIVE BUY %s: %.8f @ $%.2f (order %s)", pair, volume, fill_price, entry["id"])

        sl_price = round(fill_price * (1 - stop_loss_pct / 100), 8)
        tp_price = round(fill_price * (1 + take_profit_pct / 100), 8)

        # Stop-loss order (Kraken native — survives app restarts)
        sl_order = self._exchange.create_order(
            ccxt_pair, "stop-loss", "sell", volume, sl_price,
            {"stopPrice": sl_price}
        )
        logger.info("LIVE STOP-LOSS set at $%.2f (order %s)", sl_price, sl_order["id"])

        # Take-profit order
        tp_order = self._exchange.create_order(
            ccxt_pair, "take-profit", "sell", volume, tp_price,
            {"stopPrice": tp_price}
        )
        logger.info("LIVE TAKE-PROFIT set at $%.2f (order %s)", tp_price, tp_order["id"])

        return {
            "pair":               pair,
            "side":               "buy",
            "volume":             volume,
            "fill_price":         fill_price,
            "usd_invested":       usd_amount,
            "stop_loss_price":    sl_price,
            "take_profit_price":  tp_price,
            "stop_loss_pct":      stop_loss_pct,
            "take_profit_pct":    take_profit_pct,
            "entry_order_id":     entry["id"],
            "stop_loss_order_id": sl_order["id"],
            "take_profit_order_id": tp_order["id"],
        }

    def cancel_order(self, order_id: str, pair: str) -> bool:
        """Cancel an open order. Returns True if successful."""
        try:
            ccxt_pair = KRAKEN_PAIR_MAP.get(pair, pair)
            self._exchange.cancel_order(order_id, ccxt_pair)
            logger.info("Cancelled order %s for %s", order_id, pair)
            return True
        except Exception as e:
            logger.error("Failed to cancel order %s: %s", order_id, e)
            return False

    def validate_order(self, pair: str, side: str, volume: float, price: float) -> dict:
        """
        Validate an order without placing it (Kraken validate flag).
        Useful for testing order construction.
        """
        ccxt_pair = KRAKEN_PAIR_MAP.get(pair, pair)
        return self._exchange.create_order(
            ccxt_pair, "limit", side, volume, price,
            {"validate": True}
        )
