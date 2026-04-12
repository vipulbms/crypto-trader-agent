#!/usr/bin/env python3
"""
Generate a representative SYSTEM + CYCLE prompt and write it to docs/sample_prompt.md.

Usage:
    python scripts/generate_prompt_sample.py          # synthetic 27-pair sample
    python scripts/generate_prompt_sample.py --live   # real data from paper_trading.db

Output:
    docs/sample_prompt.md — SYSTEM + CYCLE prompt with token count estimate
"""

import argparse
import os
import sqlite3
import sys
from datetime import datetime, timezone

import yaml

# Allow imports from project root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.agent.prompts import build_cycle_prompt


def _load_config(path: str = "config.yaml") -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def _estimate_tokens(text: str) -> int:
    """Rough token count: words × 1.33 (GPT-style). Install tiktoken for precision."""
    try:
        import tiktoken
        enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(text))
    except ImportError:
        return int(len(text.split()) * 1.33)


def _build_synthetic_signals(config: dict) -> list:
    """Build realistic synthetic signals for all configured pairs."""
    trading = config.get("trading", {})
    pairs_cfg = trading.get("pairs", [])
    global_tp = trading.get("take_profit_pct", 10)
    signals = []

    # Cycle through BUY / HOLD / SELL in roughly realistic proportions
    signal_rotation = ["BUY", "HOLD", "HOLD", "BUY", "HOLD", "SELL", "HOLD",
                       "BUY", "HOLD", "HOLD", "HOLD", "BUY", "HOLD", "HOLD",
                       "HOLD", "BUY", "HOLD", "HOLD", "HOLD", "HOLD", "BUY",
                       "HOLD", "HOLD", "HOLD", "HOLD", "HOLD", "HOLD"]

    # Representative price seeds per pair
    price_map = {
        "BTC/USD": 83500.0, "ETH/USD": 1820.0, "BNB/USD": 580.0,
        "SOL/USD": 142.0,   "XRP/USD": 2.15,   "TRX/USD": 0.245,
        "DOGE/USD": 0.168,  "ADA/USD": 0.72,   "LTC/USD": 88.5,
        "AVAX/USD": 21.5,   "SUI/USD": 2.68,   "HYPE/USD": 14.2,
        "UNI/USD": 6.12,    "INJ/USD": 10.8,   "WIF/USD": 0.92,
        "TON/USD": 2.94,    "OP/USD": 0.71,    "ARB/USD": 0.38,
        "JUP/USD": 0.42,    "PEPE/USD": 0.0000088, "TIA/USD": 2.31,
        "RENDER/USD": 3.45, "FET/USD": 0.61,   "STX/USD": 0.78,
        "PENDLE/USD": 2.85, "ONDO/USD": 0.87,  "BONK/USD": 0.0000148,
    }

    tier_map = {
        "BTC/USD": 1, "ETH/USD": 2, "BNB/USD": 2, "SOL/USD": 2,
        "XRP/USD": 2, "TRX/USD": 2, "LTC/USD": 2, "AVAX/USD": 2,
        "ADA/USD": 3, "UNI/USD": 3, "INJ/USD": 3, "SUI/USD": 3,
        "OP/USD": 3,  "ARB/USD": 3, "TON/USD": 3, "TIA/USD": 3,
        "RENDER/USD": 3, "FET/USD": 3, "STX/USD": 3, "PENDLE/USD": 3,
        "ONDO/USD": 3, "WIF/USD": 4, "DOGE/USD": 4, "HYPE/USD": 4,
        "JUP/USD": 4, "PEPE/USD": 4, "BONK/USD": 4,
    }

    for i, pair_cfg in enumerate(pairs_cfg):
        pair = pair_cfg["pair"]
        sig_type = signal_rotation[i % len(signal_rotation)]
        price = price_map.get(pair, 10.0)
        bb_lower = price * 0.975
        tier = tier_map.get(pair, 3)
        tp_pct = pair_cfg.get("take_profit_pct", global_tp)
        caution = pair_cfg.get("caution_factor_bearish", 0.5)
        pair_max_usd = round(200 * caution * (1 if tier <= 2 else 0.7 if tier == 3 else 0.4), 2)

        if sig_type == "BUY":
            reasons = [
                f"Price at/near lower Bollinger Band (${price:.4f} <= ${bb_lower:.4f})",
                "MACD histogram turned positive (strong momentum)",
                "RSI oversold (30.2)",
                "OBV accumulation trend (7-candle)",
            ]
            strength = 0.72
        elif sig_type == "SELL":
            reasons = [
                "Price at/near upper Bollinger Band",
                "MACD histogram crossed negative",
                "RSI overbought (73.1)",
            ]
            strength = 0.68
        else:
            reasons = ["Insufficient confluence — waiting for setup"]
            strength = 0.22

        signals.append({
            "pair":        pair,
            "signal":      sig_type,
            "strength":    strength,
            "price":       price,
            "pair_max_usd": pair_max_usd,
            "pair_tier":   tier,
            "indicators": {
                "rsi_14":          30.2 if sig_type == "BUY" else (73.1 if sig_type == "SELL" else 52.0),
                "macd_histogram":  0.0023 if sig_type == "BUY" else (-0.0018 if sig_type == "SELL" else 0.0001),
                "atr_14":          price * 0.006,
                "bb_lower":        bb_lower,
                "bb_upper":        price * 1.025,
            },
            "reasons": reasons,
        })

    return signals


def _build_live_signals(config: dict, db_path: str) -> tuple[dict, list]:
    """Load latest portfolio + signals from audit DB."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    # Portfolio from paper_broker
    broker_conn = sqlite3.connect(db_path)
    broker_conn.row_factory = sqlite3.Row

    try:
        cash_row = broker_conn.execute(
            "SELECT balance_usd FROM paper_wallet ORDER BY id DESC LIMIT 1"
        ).fetchone()
        cash_usd = cash_row["balance_usd"] if cash_row else 1000.0

        pos_rows = broker_conn.execute(
            "SELECT pair, volume, usd_value, entry_price, stop_loss_price, take_profit_price "
            "FROM paper_positions WHERE status='open'"
        ).fetchall()
        open_positions = [dict(r) for r in pos_rows]
        total_usd = cash_usd + sum(p["usd_value"] for p in open_positions)

        portfolio = {
            "total_usd":           total_usd,
            "available_cash_usd":  cash_usd,
            "open_positions_count": len(open_positions),
            "daily_pnl_usd":       0.0,
            "daily_pnl_pct":       0.0,
            "open_positions":      open_positions,
            "max_per_trade":       round(cash_usd * 0.20, 2),
        }

        # Latest signals from audit_signals
        signal_rows = conn.execute("""
            SELECT pair, signal, strength, price, indicators_json, reasons_json
            FROM audit_signals
            WHERE cycle_id = (SELECT MAX(cycle_id) FROM audit_signals)
            ORDER BY pair
        """).fetchall()

        import json
        signals = []
        for row in signal_rows:
            indicators = json.loads(row["indicators_json"] or "{}")
            reasons    = json.loads(row["reasons_json"] or "[]")
            signals.append({
                "pair":     row["pair"],
                "signal":   row["signal"],
                "strength": row["strength"],
                "price":    row["price"],
                "indicators": indicators,
                "reasons":    reasons,
            })

        return portfolio, signals
    finally:
        conn.close()
        broker_conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate SYSTEM + CYCLE prompt sample")
    parser.add_argument("--live",   action="store_true", help="Load real data from paper_trading.db")
    parser.add_argument("--config", default="config.yaml", help="Config file path")
    parser.add_argument("--db",     default="paper_trading.db", help="DB path (--live only)")
    parser.add_argument("--output", default="docs/sample_prompt.md", help="Output file path")
    args = parser.parse_args()

    config = _load_config(args.config)
    system_prompt = config.get("llm", {}).get("system_prompt", "")
    trading = config.get("trading", {})
    global_tp = trading.get("take_profit_pct", 10)
    pair_tp = {
        p["pair"]: p.get("take_profit_pct", global_tp)
        for p in trading.get("pairs", [])
    }
    max_buys    = trading.get("max_buys_per_cycle", 7)
    min_order   = config.get("risk", {}).get("min_order_usd", 20.0)

    if args.live:
        print(f"Loading real data from {args.db}...")
        try:
            portfolio, signals = _build_live_signals(config, args.db)
            source_label = f"Live data from `{args.db}`"
        except Exception as e:
            print(f"ERROR: Could not load live data — {e}")
            print("Falling back to synthetic data.")
            signals = _build_synthetic_signals(config)
            portfolio = {
                "total_usd": 1000.0, "available_cash_usd": 850.0,
                "open_positions_count": 1, "daily_pnl_usd": 12.5,
                "daily_pnl_pct": 1.25,
                "open_positions": [{"pair": "ETH/USD", "volume": 0.045,
                                    "usd_value": 150.0, "entry_price": 1800.0,
                                    "stop_loss_price": 1710.0, "take_profit_price": 2016.0}],
                "max_per_trade": 170.0,
            }
            source_label = "Synthetic (fallback — live DB load failed)"
    else:
        signals = _build_synthetic_signals(config)
        portfolio = {
            "total_usd": 1000.0, "available_cash_usd": 850.0,
            "open_positions_count": 1, "daily_pnl_usd": 12.5,
            "daily_pnl_pct": 1.25,
            "open_positions": [{"pair": "ETH/USD", "volume": 0.045,
                                "usd_value": 150.0, "entry_price": 1800.0,
                                "stop_loss_price": 1710.0, "take_profit_price": 2016.0}],
            "max_per_trade": 170.0,
        }
        source_label = "Synthetic fixtures (27-pair sample)"

    cycle_prompt = build_cycle_prompt(
        cycle_time=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        portfolio=portfolio,
        signals=signals,
        mode="paper",
        pair_tp_config=pair_tp,
        ai_context=None,
        max_buys_per_cycle=max_buys,
        min_order_usd=min_order,
    )

    sys_tokens   = _estimate_tokens(system_prompt)
    cycle_tokens = _estimate_tokens(cycle_prompt)
    total_tokens = sys_tokens + cycle_tokens

    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    output = f"""# Kryptos LLM Prompt Sample

**Generated:** {generated_at}
**Source:** {source_label}
**Pairs:** {len(signals)}

## Token Estimates

| Section | Tokens (est.) |
|---|---|
| System prompt | {sys_tokens:,} |
| Cycle prompt | {cycle_tokens:,} |
| **Total** | **{total_tokens:,}** |

> Token counts use `tiktoken cl100k_base` if installed, else word-count × 1.33 heuristic.
> Groq free-tier limit: 6,000 tokens/min. Groq paid: 100,000+ tokens/min.

---

## System Prompt

```
{system_prompt}
```

---

## Cycle Prompt

```
{cycle_prompt}
```
"""

    os.makedirs(os.path.dirname(args.output) if os.path.dirname(args.output) else ".", exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        f.write(output)

    print(f"Written to {args.output}")
    print(f"  System prompt: {sys_tokens:,} tokens")
    print(f"  Cycle prompt:  {cycle_tokens:,} tokens")
    print(f"  Total:         {total_tokens:,} tokens")


if __name__ == "__main__":
    main()
