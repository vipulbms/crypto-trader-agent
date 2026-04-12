#!/usr/bin/env python3
"""Quick profiler to find the per-cycle bottleneck in the H4 backtest."""
import sys, time
sys.path.insert(0, '.')

import yaml
from tests.backtest.loader import load_all_pairs
from src.analysis.indicators import compute_indicators
from src.analysis.signals import generate_signal
from src.analysis.features import build_ai_context

with open('config.yaml') as f:
    config = yaml.safe_load(f)

all_pairs = [p['pair'] for p in config['trading']['pairs']]
pair_candles = load_all_pairs(all_pairs, history_dir='history')
print(f"Loaded {len(pair_candles)} pairs")

candles = pair_candles['BTC/USD'][-500:]
N = 50

# 1. compute_indicators
t0 = time.time()
for _ in range(N):
    compute_indicators(candles, config)
print(f"compute_indicators(BTC, 500 candles):  {(time.time()-t0)/N*1000:.1f}ms  [{N} samples]")

# 2. generate_signal
ind = compute_indicators(candles, config)
t0 = time.time()
for _ in range(N):
    generate_signal('BTC/USD', ind, config)
print(f"generate_signal:                        {(time.time()-t0)/N*1000:.1f}ms  [{N} samples]")

# 3. Full per-cycle: indicators + signal for all 26 pairs
pairs = list(pair_candles.keys())
t0 = time.time()
for _ in range(10):
    signals = []
    for pair in pairs:
        c = pair_candles[pair][-500:]
        i = compute_indicators(c, config)
        if i:
            s = generate_signal(pair, i, config)
            s['indicators'] = i
            signals.append(s)
elapsed_10 = time.time() - t0
print(f"indicators+signals all {len(pairs)} pairs:         {elapsed_10/10*1000:.0f}ms per cycle  [10 samples]")

# 4. build_ai_context
portfolio = {
    'total_usd': 1000.0, 'available_cash_usd': 900.0,
    'open_positions_count': 0, 'daily_pnl_usd': 0.0,
    'daily_pnl_pct': 0.0, 'open_positions': [], 'max_per_trade': 200.0,
}
t0 = time.time()
for _ in range(N):
    build_ai_context(signals=signals, portfolio=portfolio, open_positions=[], config=config)
print(f"build_ai_context (26 signals):          {(time.time()-t0)/N*1000:.1f}ms  [{N} samples]")

# 5. Projection
per_cycle_ms = elapsed_10 / 10 * 1000  # ms
bac_ms = (time.time() - t0) / N * 1000
total_ms = per_cycle_ms + bac_ms
n_steps = 193 * 48  # Oct 2025 to Apr 2026, one step per 30min
print(f"\nProjection for 2025-10-01 start ({n_steps} steps, 2 passes):")
print(f"  Per cycle (indicators+signals+bac):  {total_ms:.0f}ms")
print(f"  Pass 1 total:                        {n_steps * total_ms / 1000:.0f}s")
print(f"  Both passes:                         {2 * n_steps * total_ms / 1000:.0f}s ({2 * n_steps * total_ms / 60000:.1f} min)")
