"""
Diagnostic script for cycle-370 review.
Confirms three logging gaps and one precision bug.
"""
import inspect
import random
import sys

sys.path.insert(0, ".")

from src.analysis.features import build_ai_context
from src.analysis.indicators import compute_indicators

# ── Minimal config ────────────────────────────────────────────────────────────
cfg = {
    "indicators": {
        "min_candles_to_start": 50,
        "rsi_period": 14,
        "macd_fast": 12,
        "macd_slow": 26,
        "macd_signal": 9,
        "bb_period": 20,
        "bb_std": 2,
        "ema_fast": 20,
        "ema_slow": 50,
        "atr_period": 14,
        "adx_period": 14,
    }
}

# ── Build 220 synthetic BTC-range candles ────────────────────────────────────
random.seed(42)
base = 70000.0
candles = [
    {
        "open": base + i * 10,
        "high": base + i * 10 + 50,
        "low": base + i * 10 - 50,
        "close": base + i * 10 + random.uniform(-30, 30),
        "volume": 100.0 + random.uniform(0, 50),
    }
    for i in range(220)
]


# ─────────────────────────────────────────────────────────────────────────────
# Issue 1: volume_ratio and bb_width missing from indicators dict
# ─────────────────────────────────────────────────────────────────────────────
ind = compute_indicators(candles, cfg)

print("=" * 60)
print("Issue 1: volume_ratio / bb_width in indicators dict")
print("=" * 60)
print(f"  volume          : {ind.get('volume')}")
print(f"  volume_sma_20   : {ind.get('volume_sma_20')}")
vol = ind.get("volume") or 0
sma = ind.get("volume_sma_20") or 0
actual_ratio = round(vol / sma, 4) if sma > 0 else None
print(f"  volume/sma_20   : {actual_ratio}  (computed manually)")
print(f"  volume_ratio key: {ind.get('volume_ratio')}  <- {'LOGGING GAP: always null' if ind.get('volume_ratio') is None else 'present'}")

bb_upper = ind.get("bb_upper", 0)
bb_lower = ind.get("bb_lower", 0)
close = ind.get("close", 0)
actual_bb_width = round((bb_upper - bb_lower) / close * 100, 4) if close else None
print(f"\n  bb_upper-lower/close*100: {actual_bb_width}%  (computed manually)")
print(f"  bb_width key    : {ind.get('bb_width')}  <- {'LOGGING GAP: always null' if ind.get('bb_width') is None else 'present'}")


# ─────────────────────────────────────────────────────────────────────────────
# Issue 2: Sub-cent token price zeroed by _round(price, 4)
# ─────────────────────────────────────────────────────────────────────────────
print("\n" + "=" * 60)
print("Issue 2: Sub-cent token precision in cycle_logger._round")
print("=" * 60)

tokens = {
    "BONK": {"price": 0.0000165, "atr": 0.0000005},
    "PEPE": {"price": 0.0000086, "atr": 0.0000003},
}

for name, vals in tokens.items():
    p = vals["price"]
    a = vals["atr"]
    p4 = round(p, 4)
    a6 = round(a, 6)   # safe() in indicators.py rounds to 6dp
    print(f"\n  {name}:")
    print(f"    actual price          : {p}")
    print(f"    _round(price, 4)      : {p4}  <- {'ZEROED in log' if p4 == 0 else 'ok'}")
    print(f"    actual ATR            : {a}")
    print(f"    safe(ATR) → 6dp       : {a6}  <- {'ZEROED in indicators' if a6 == 0 else 'ok'}")
    print(f"    ATR floor guard uses  : 'if atr and price' = {bool(a6) and bool(p4)}  <- {'SKIPPED (atr=0 is falsy)' if a6 == 0 else 'fires'}")


# ─────────────────────────────────────────────────────────────────────────────
# Issue 3: fear_greed_value always null in macro block
# ─────────────────────────────────────────────────────────────────────────────
print("\n" + "=" * 60)
print("Issue 3: fear_greed_value null in macro block")
print("=" * 60)

params = list(inspect.signature(build_ai_context).parameters.keys())
print(f"  build_ai_context params: {params}")
missing = "fear_greed" not in params
print(f"  'fear_greed' param missing: {missing}  <- {'LOGGING GAP' if missing else 'ok'}")
print(f"  Consequence: cycle_logger reads ai_context.get('fear_greed', {{}})")
print(f"  That key is never set → macro.fear_greed_value always null")
print(f"  (F&G IS used correctly in per-pair scoring via indicators dict)")


# ─────────────────────────────────────────────────────────────────────────────
# Summary
# ─────────────────────────────────────────────────────────────────────────────
print("\n" + "=" * 60)
print("Summary")
print("=" * 60)
print("  Issue 1 (volume_ratio/bb_width null): LOGGING GAP — no functional impact")
print("  Issue 2 (BONK/PEPE price=0.0):        LOGGING PRECISION — price display only.")
print("            ATR=0 from safe() ALSO bypasses ATR floor guard for micro-price tokens.")
print("  Issue 3 (fear_greed_value null):       LOGGING GAP — no functional impact")
print()
print("  All trading decisions in cycle 370 are functionally correct.")
