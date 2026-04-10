"""
Tests for correlation cluster guard in RiskManager.validate_buy() (#139).

Verifies:
- ETH + BNB open (same cluster), SOL BUY proposed → size penalised 50%
- ETH + BNB + SOL open, BTC BUY proposed → REJECTED
- ETH open, ADA BUY proposed (different cluster) → no penalty
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.risk.risk_manager import RiskManager
from src.storage.database import get_connection

DB_PATH = "paper_trading.db"

CONFIG = {
    "trading": {
        "stop_loss_pct": 5, "take_profit_pct": 8, "min_profit_floor_pct": 1.0,
        "max_position_pct": 30, "max_open_positions": 13, "pairs": [],
        "early_sell_min_tp_proximity_pct": 60,
    },
    "risk": {
        "daily_loss_limit_pct": 10, "min_cash_reserve_pct": 5,
        "min_order_usd": 20.0, "max_token_volume_per_trade": 500000,
        "flash_crash_tolerance_pct": 15.0,
        "circuit_breaker": {"enabled": False, "consecutive_stops": 3, "pause_hours": 4},
        "correlation_clusters": [
            {"name": "large_cap_l1", "pairs": ["BTC/USD", "ETH/USD", "BNB/USD", "SOL/USD"]},
            {"name": "memecoins",    "pairs": ["DOGE/USD", "HYPE/USD"]},
            {"name": "alt_l1",       "pairs": ["SUI/USD", "AVAX/USD", "INJ/USD"]},
            {"name": "payment_legacy", "pairs": ["XRP/USD", "TRX/USD", "ADA/USD", "LTC/USD"]},
        ],
        "max_cluster_positions": 2,
        "cluster_size_penalty": 0.5,
    },
}


def _seed_positions(pairs: list) -> None:
    """Insert fake open positions for the given pairs."""
    conn = get_connection(DB_PATH)
    conn.execute("DELETE FROM paper_positions WHERE pair LIKE '%/USD'")
    for pair in pairs:
        conn.execute(
            "INSERT INTO paper_positions "
            "(opened_at, pair, side, entry_price, volume, usd_value, "
            " stop_loss_price, take_profit_price, stop_loss_pct, take_profit_pct, status) "
            "VALUES (datetime('now'), ?, 'buy', 100, 1, 100, 95, 108, 5, 8, 'open')",
            (pair,),
        )
    conn.commit()
    conn.close()


def _cleanup():
    conn = get_connection(DB_PATH)
    conn.execute("DELETE FROM paper_positions WHERE pair LIKE '%/USD'")
    conn.commit()
    conn.close()


def test_cluster_penalty_on_second_position():
    """Only ETH open (same cluster), SOL BUY proposed → size penalised 50%."""
    _seed_positions(["ETH/USD"])
    rm = RiskManager(CONFIG, db_path=DB_PATH)
    approved, reason, amount = rm.validate_buy(
        "SOL/USD", 200, 1000, 800, 1, 0, 1000
    )
    assert approved is True, f"Expected approved (penalty), got: {reason}"
    # Expected: cap = min(200, 200) = 200, then × 0.5 = 100
    assert amount <= 100.0 + 0.01, f"Expected penalised amount ≤ $100, got ${amount:.2f}"
    assert amount >= 20.0, f"Expected amount above min_order, got ${amount:.2f}"
    print(f"PASS test_cluster_penalty_on_second_position — amount=${amount:.2f}")
    _cleanup()


def test_cluster_blocked_at_max_positions():
    """ETH + BNB + SOL all open (3 in cluster), BTC BUY proposed → REJECTED (cluster full at 2)."""
    _seed_positions(["ETH/USD", "BNB/USD"])
    rm = RiskManager(CONFIG, db_path=DB_PATH)
    approved, reason, amount = rm.validate_buy(
        "BTC/USD", 200, 1000, 800, 2, 0, 1000
    )
    assert approved is False, f"Expected REJECTED (cluster full), got approved"
    assert "large_cap_l1" in reason, f"Expected cluster name in reason, got: {reason}"
    assert amount == 0.0
    print(f"PASS test_cluster_blocked_at_max_positions — reason: {reason}")
    _cleanup()


def test_different_cluster_no_penalty():
    """ETH open (large_cap_l1), ADA BUY proposed (payment_legacy) → no penalty."""
    _seed_positions(["ETH/USD"])
    rm = RiskManager(CONFIG, db_path=DB_PATH)
    approved, reason, amount = rm.validate_buy(
        "ADA/USD", 200, 1000, 800, 1, 0, 1000
    )
    assert approved is True, f"Expected approved, got: {reason}"
    # Amount should NOT be penalised — ADA is in a different cluster
    assert amount >= 190.0, f"Expected full-size amount (≥$190), got ${amount:.2f}"
    print(f"PASS test_different_cluster_no_penalty — amount=${amount:.2f}")
    _cleanup()


if __name__ == "__main__":
    test_cluster_penalty_on_second_position()
    test_cluster_blocked_at_max_positions()
    test_different_cluster_no_penalty()
    print("\nAll correlation guard tests passed.")
