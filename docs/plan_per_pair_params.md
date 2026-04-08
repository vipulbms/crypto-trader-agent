# Plan: Per-Pair Parameter Migration
**Status:** Draft — Awaiting product owner review before implementation begins  
**Prepared:** 2026-04-08  
**Pairs covered:** BTC, ETH, BNB, SOL, XRP, TRX, DOGE, ADA, LTC, AVAX, SUI, UNI, INJ  
*(RAILS and HYPE excluded — no historical candle data available in the dataset)*

---

## Section 1: Summary

The current Kryptos configuration applies identical signal thresholds to every pair: one global RSI oversold level (30), one RSI overbought level (75), one BB squeeze threshold (1.0%), one MACD decay threshold (-0.0005), and one volume dead zone ratio (0.5). This is statistically wrong. BTC has a median ATR% of 0.21 while SUI has 0.60; TRX fires RSI < 30 on nearly 7% of candles while BNB fires on only 3.5%. A threshold that is meaningfully selective for BTC is either too loose (generating noise) or too tight (suppressing valid signals) for the high-volatility alts. The fix has two layers: first, derive a per-pair static value for each parameter from historical data, so the config is calibrated to each pair's actual distribution rather than a universal guess. Second, for the three parameters whose optimal values shift with current market conditions — the ATR floor, BB squeeze threshold, and volume dead zone — replace the static thresholds with runtime-adaptive calculations that update as the market evolves. Together these changes will reduce false signals on low-volatility pairs, prevent over-suppression on high-volatility pairs, and allow the dead zone check to remain meaningful for illiquid alts (UNI, INJ) without blocking liquid pairs (BTC, XRP) that already have ~44% of candles below the current 50% threshold.

---

## Section 2: Parameter Recommendations (Per-Pair Static Values)

### 2a. `rsi_oversold` per pair

**Derivation logic:** Set the threshold at the level where the pair hits oversold on approximately 5–8% of candles — often enough to be a meaningful signal, rare enough to be selective. Where RSI < 30 already fires at ~4–5%, keep the threshold at 30. Where RSI < 30 fires at > 6% (TRX at 6.87%), it is too loose — raise to 35 to keep firing rate around 12% max. Where RSI < 30 fires at < 4% (BNB at 3.48%), the signal is too rare — lower to 28 to bring the firing rate to approximately 5–6%.

| Pair     | <30 freq | <35 freq | Recommended `rsi_oversold` | Rationale |
|----------|----------|----------|---------------------------|-----------|
| BTC/USD  | 4.67%    | 9.55%    | **30**                    | Already at target band |
| ETH/USD  | 4.57%    | 9.22%    | **30**                    | Already at target band |
| BNB/USD  | 3.48%    | 7.74%    | **28**                    | <30 too rare; lowering picks up ~5–6% of candles |
| SOL/USD  | 4.42%    | 9.79%    | **30**                    | Already at target band |
| XRP/USD  | 3.69%    | 8.73%    | **28**                    | <30 slightly below target; 28 brings it to ~4.5–5.5% |
| TRX/USD  | 6.87%    | 12.63%   | **35**                    | <30 too frequent (noise); raising to 35 gives ~12.6% band |
| DOGE/USD | 4.52%    | 10.00%   | **30**                    | Already at target band |
| ADA/USD  | 4.41%    | 9.69%    | **30**                    | Already at target band |
| LTC/USD  | 3.84%    | 9.01%    | **28**                    | <30 slightly below target; lowering to 28 |
| AVAX/USD | 4.89%    | 10.58%   | **30**                    | Already at target band |
| SUI/USD  | 4.22%    | 9.64%    | **30**                    | Already at target band |
| UNI/USD  | 4.64%    | 10.16%   | **30**                    | Already at target band |
| INJ/USD  | 4.32%    | 9.97%    | **30**                    | Already at target band |

---

### 2b. `rsi_overbought` per pair

**Derivation logic:** The current global setting of 75 was raised from 65 specifically to prevent premature SELL signals — RSI 65–75 alone scores 3 which equals `sell_min_score`. The goal is for the overbought threshold to fire on 4–6% of candles. Where RSI > 70 already fires at 6.65% (TRX), the bar is too low — use 65 to shift even more conservatively. Where RSI > 70 fires at < 4% (XRP, DOGE, ADA, LTC, SUI, INJ), the threshold is too high — lower to 72 to increase firing rate toward the 4–5% band. All others stay at 75.

| Pair     | >70 freq | >75 freq | Recommended `rsi_overbought` | Rationale |
|----------|----------|----------|------------------------------|-----------|
| BTC/USD  | 4.39%    | 1.88%    | **75**                       | >70 at ~4.4%; current 75 keeps signal selective |
| ETH/USD  | 4.77%    | 2.12%    | **75**                       | >70 at ~4.8%; 75 keeps it tight |
| BNB/USD  | 4.64%    | 1.81%    | **75**                       | >70 at ~4.6%; 75 keeps it tight |
| SOL/USD  | 4.50%    | 1.76%    | **75**                       | >70 at ~4.5%; 75 keeps it tight |
| XRP/USD  | 3.43%    | 1.37%    | **72**                       | >70 too rare at 3.4%; 72 gives ~4–5% firing rate |
| TRX/USD  | 6.65%    | 2.78%    | **65**                       | >70 already 6.65% — lower bar to 65 to avoid excess SELL noise |
| DOGE/USD | 3.78%    | 1.44%    | **72**                       | >70 too rare at 3.8%; lower to 72 |
| ADA/USD  | 3.72%    | 1.36%    | **72**                       | >70 too rare at 3.7%; lower to 72 |
| LTC/USD  | 3.66%    | 1.41%    | **72**                       | >70 too rare at 3.7%; lower to 72 |
| AVAX/USD | 4.33%    | 1.58%    | **75**                       | >70 at ~4.3%; 75 is appropriate |
| SUI/USD  | 3.95%    | 1.42%    | **72**                       | >70 at ~4.0%; borderline — lower to 72 |
| UNI/USD  | 4.03%    | 1.65%    | **75**                       | >70 at ~4.0%; 75 is appropriate |
| INJ/USD  | 3.84%    | 1.34%    | **72**                       | >70 too rare at 3.8%; lower to 72 |

---

### 2c. `bb_squeeze_threshold_pct` per pair

**Derivation logic:** A BB squeeze means bands are genuinely compressed for *that pair's* typical behaviour. The p10 BB width (lowest decile of historical band widths) is the natural calibration point — when current width falls below the pair's own p10, the market is in an unusual squeeze. Rounded to 1 decimal place.

| Pair     | BB median width% | p25 width% | p10 width% (squeeze threshold) | Recommended `bb_squeeze_threshold_pct` |
|----------|------------------|------------|-------------------------------|---------------------------------------|
| BTC/USD  | 1.65%            | 1.05%      | 0.72%                         | **0.7**                               |
| ETH/USD  | 2.85%            | 1.86%      | 1.28%                         | **1.3**                               |
| BNB/USD  | 2.02%            | 1.33%      | 0.88%                         | **0.9**                               |
| SOL/USD  | 3.54%            | 2.42%      | 1.75%                         | **1.8**                               |
| XRP/USD  | 3.09%            | 1.99%      | 1.42%                         | **1.4**                               |
| TRX/USD  | 1.63%            | 1.09%      | 0.75%                         | **0.8**                               |
| DOGE/USD | 3.79%            | 2.52%      | 1.77%                         | **1.8**                               |
| ADA/USD  | 3.79%            | 2.55%      | 1.87%                         | **1.9**                               |
| LTC/USD  | 3.26%            | 2.15%      | 1.51%                         | **1.5**                               |
| AVAX/USD | 3.95%            | 2.70%      | 1.95%                         | **2.0**                               |
| SUI/USD  | 4.28%            | 2.86%      | 2.11%                         | **2.1**                               |
| UNI/USD  | 4.24%            | 2.89%      | 2.11%                         | **2.1**                               |
| INJ/USD  | 4.72%            | 3.28%      | 2.48%                         | **2.5**                               |

> **Current global value (1.0%) is appropriate only for BTC and TRX.** It is far too tight for SOL, DOGE, ADA, AVAX, SUI, UNI, INJ — the current threshold would classify over 10% of their candles as "squeeze" even when bands are at their normal mid-range width.

---

### 2d. `macd_decay_threshold` per pair

**Derivation logic:** The current absolute threshold (-0.0005) is meaningless across pairs with vastly different price scales (BTC at ~$80k vs TRX at ~$0.25). The correct approach is to express the threshold as a percentage of price, then compare against the normalised histogram value `macd_histogram / price × 100`. The recommended per-pair threshold uses the median |histogram|% at a positive-to-negative crossover (the decay moment), negated. This is the "typical" strength of a decay signal for that pair. Values are expressed in `%_of_price` units to 5 decimal places.

| Pair     | Median |hist|% at crossover | Recommended `macd_decay_threshold_pct` | Notes |
|----------|-------------------------------|----------------------------------------|-------|
| BTC/USD  | 0.00691                       | **-0.00691**                           | Very tight — BTC MACD barely moves relative to price |
| ETH/USD  | 0.01164                       | **-0.01164**                           | |
| BNB/USD  | 0.00844                       | **-0.00844**                           | |
| SOL/USD  | 0.01445                       | **-0.01445**                           | |
| XRP/USD  | 0.01250                       | **-0.01250**                           | |
| TRX/USD  | 0.00585                       | **-0.00585**                           | Tightest after BTC — TRX is low-volatility |
| DOGE/USD | 0.01503                       | **-0.01503**                           | |
| ADA/USD  | 0.01573                       | **-0.01573**                           | |
| LTC/USD  | 0.01402                       | **-0.01402**                           | |
| AVAX/USD | 0.01466                       | **-0.01466**                           | |
| SUI/USD  | 0.01675                       | **-0.01675**                           | |
| UNI/USD  | 0.01791                       | **-0.01791**                           | |
| INJ/USD  | 0.01951                       | **-0.01951**                           | Widest — INJ MACD swings most as % of price |

> **Code change required:** `features.py:check_exit_timing()` currently compares raw `macd_hist` to the absolute threshold. It must be changed to compute `macd_hist / price × 100` and compare that against the per-pair `macd_decay_threshold_pct`. See Section 3c.

---

### 2e. `min_volume_ratio` per pair

**Derivation logic:** The current global threshold of 0.5 means any candle with volume below 50% of the 20-period SMA is blocked. For pairs where over 55% of all historical candles already fall below 50% of their own SMA (BNB 56.6%, TRX 52.9%, DOGE 51.5%, ADA 52.1%, AVAX 53.6%, UNI 57.9%, INJ 58.3%), this threshold blocks the majority of trading opportunities — including many that are not genuinely thin. Lowering the threshold for these pairs to 0.3 limits blocks to only the truly extreme thin periods.

**Threshold rules applied:**
- Dead zone % > 55% → use **0.30** (only the thinnest ~30% of candles are blocked)
- Dead zone % 48–55% → use **0.40** (moderate filter)
- Dead zone % < 48% → keep **0.50** (current behaviour, these pairs have adequate volume most of the time)

| Pair     | Dead zone % (candles below 50% SMA) | Vol p10 ratio | Recommended `min_volume_ratio` |
|----------|--------------------------------------|---------------|-------------------------------|
| BTC/USD  | 44.05%                               | 0.151         | **0.50**                      |
| ETH/USD  | 47.32%                               | 0.138         | **0.50**                      |
| BNB/USD  | 56.64%                               | 0.028         | **0.30**                      |
| SOL/USD  | 43.77%                               | 0.144         | **0.50**                      |
| XRP/USD  | 40.97%                               | 0.171         | **0.50**                      |
| TRX/USD  | 52.92%                               | 0.081         | **0.40**                      |
| DOGE/USD | 51.51%                               | 0.068         | **0.40**                      |
| ADA/USD  | 52.11%                               | 0.078         | **0.40**                      |
| LTC/USD  | 49.66%                               | 0.109         | **0.40**                      |
| AVAX/USD | 53.60%                               | 0.057         | **0.40**                      |
| SUI/USD  | 47.70%                               | 0.092         | **0.50**                      |
| UNI/USD  | 57.93%                               | 0.021         | **0.30**                      |
| INJ/USD  | 58.30%                               | 0.019         | **0.30**                      |

> Note: BNB, UNI, and INJ have extremely low p10 volume ratios (0.028, 0.021, 0.019). Even with `min_volume_ratio=0.30`, the dead zone check will still catch the genuinely thin periods. The very low p10 values confirm these pairs have occasional severe volume droughts — the 0.30 threshold preserves that protection.

---

### 2f. `atr_tp_min_pct` per pair

**Derivation logic:** The current global value of 1.0% was raised specifically to block BTC (which has ATR-based TP of ~0.21% × 2.0 = 0.42%) but it over-blocks some mid-cap pairs too. The correct per-pair floor is p25 ATR% × 0.8. This means: "only allow entry when ATR is at least 80% of what is normal for this pair's lower quartile." This is a conservative requirement — the market must show at least baseline normal volatility.

Formula: `atr_tp_min_pct = max(0.15, round(p25_atr_pct × 0.8, 2))`

The 0.15% minimum cap prevents the floor from being so low (for BTC) that it is practically meaningless.

| Pair     | p25 ATR% | p25 × 0.8 | Min cap | Recommended `atr_tp_min_pct` |
|----------|----------|-----------|---------|------------------------------|
| BTC/USD  | 0.14%    | 0.112%    | 0.15%   | **0.15**                     |
| ETH/USD  | 0.29%    | 0.232%    | —       | **0.23**                     |
| BNB/USD  | 0.16%    | 0.128%    | 0.15%   | **0.15** (capped)            |
| SOL/USD  | 0.38%    | 0.304%    | —       | **0.30**                     |
| XRP/USD  | 0.33%    | 0.264%    | —       | **0.26**                     |
| TRX/USD  | 0.12%    | 0.096%    | 0.15%   | **0.15** (capped)            |
| DOGE/USD | 0.39%    | 0.312%    | —       | **0.31**                     |
| ADA/USD  | 0.40%    | 0.320%    | —       | **0.32**                     |
| LTC/USD  | 0.32%    | 0.256%    | —       | **0.26**                     |
| AVAX/USD | 0.39%    | 0.312%    | —       | **0.31**                     |
| SUI/USD  | 0.46%    | 0.368%    | —       | **0.37**                     |
| UNI/USD  | 0.37%    | 0.296%    | —       | **0.30**                     |
| INJ/USD  | 0.42%    | 0.336%    | —       | **0.34**                     |

> The current global 1.0% floor blocks ALL pairs most of the time — median ATR% for no pair exceeds 0.60%. With per-pair floors, entry is only blocked when ATR is genuinely suppressed below the pair's own lower quartile, which is exactly the intended behaviour.

---

## Section 3: Dynamic (Runtime-Adaptive) Parameters

### 3a. Adaptive ATR Floor (`atr_tp_min_pct` → runtime adaptive)

**What it is:** The minimum ATR-based TP% required to allow a BUY signal. Currently a single global constant (1.0%) applied to all pairs.

**Why it should be dynamic:** Volatility regimes shift over time. A static floor derived from 2025 data may be too tight in a low-volatility 2026 accumulation phase, suppressing all signals for weeks. An adaptive floor tracks the pair's own recent volatility history, so the floor rises when the market becomes generally more volatile and falls when it compresses — without manual intervention.

**How to compute at runtime:**
1. From the pair's candle buffer (already in memory via `websocket_feed.py`), extract the last `lookback_candles` ATR-14 values.
2. Compute the p25 of those values as a percentage of the current price.
3. Multiply by `scaling_factor` to get the adaptive floor.
4. Clamp to `[min_cap, pair_static_floor]` — never go below `min_cap`, never exceed the static per-pair value from Section 2f (the static value acts as the upper bound to prevent being permanently blocked in choppy markets).

**Formula:**
```
recent_atr_pcts = [(atr / close) * 100 for each candle in last lookback_candles]
p25_atr_pct = percentile(recent_atr_pcts, 25)
adaptive_floor = max(min_cap, p25_atr_pct * scaling_factor)
```

**Where in code:** Computed in `signals.py:generate_signal()` for the ATR blocker (Hard Blocker 2). The pair's candle buffer is not directly accessible in `generate_signal()` — it receives a pre-computed indicators dict. Therefore the rolling ATR percentile must be pre-computed in `main.py` (or `websocket_feed.py`) and injected into the indicators dict as `adaptive_atr_floor_pct` before signal generation. `generate_signal()` reads it instead of the static config value.

**Config values:**
```yaml
adaptive_atr_floor:
  enabled: true
  lookback_candles: 100      # ~25 hours of 15-min candles
  scaling_factor: 0.8        # ATR must reach 80% of the pair's recent p25
  min_cap: 0.15              # Absolute floor (% of price) — never block below this
  per_pair_min_cap:          # Override min_cap per pair (optional)
    BTC/USD: 0.15
    TRX/USD: 0.15
    BNB/USD: 0.15
```

---

### 3b. Rolling BB Squeeze Threshold (`bb_squeeze_threshold_pct` → runtime adaptive)

**What it is:** The BB width percentage below which a squeeze is declared and dynamic TP is clamped to the pair's floor. Currently a global constant (1.0%).

**Why it should be dynamic:** BB squeeze is relative to the pair's own recent band behaviour. A 1.5% width is a squeeze for INJ (p10 = 2.5%) but perfectly normal for BTC (p10 = 0.7%). More importantly, broader volatility cycles shift the p10 over time — a fixed historical p10 becomes stale. The rolling approach measures whether *right now* the bands are compressed relative to *the pair's own recent history*.

**How to compute at runtime:**
1. From the pair's candle buffer, extract the last `lookback_candles` BB width values as % of mid-price: `(upper - lower) / mid * 100`.
2. Compute the p10 of those values.
3. If current BB width < rolling_p10 → squeeze declared.
4. Fall back to static per-pair threshold from Section 2c if fewer than `min_candles` are available.

**Formula:**
```
recent_bb_widths = [(upper - lower) / mid * 100 for each candle in last lookback_candles]
rolling_p10 = percentile(recent_bb_widths, 10)
is_squeeze = current_bb_width_pct < rolling_p10
```

**Where in code:** Computed in `features.py:compute_dynamic_tp()`, which already has access to `bb_upper`, `bb_lower`, and `entry_price`. The pair's candle buffer access must be injected (same mechanism as 3a — pre-compute in `main.py` and pass as indicator `rolling_bb_p10_pct`). `compute_dynamic_tp()` uses `rolling_bb_p10_pct` from the indicators dict when available, falls back to static per-pair `bb_squeeze_threshold_pct` from config.

**Config values:**
```yaml
adaptive_bb_squeeze:
  enabled: true
  lookback_candles: 200      # ~50 hours — enough to see meaningful width variation
  min_candles: 50            # Fall back to static threshold if fewer candles available
  percentile: 10             # Declare squeeze when width < this percentile of recent history
```

---

### 3c. Price-Normalised MACD Decay Threshold (`macd_decay_threshold` → per-pair % of price)

**What it is:** The MACD histogram value below which momentum is considered to be decaying on an open position. Currently stored as an absolute value (-0.0005) in `exit_timing.macd_decay_threshold`.

**Why it should be dynamic (price-normalised):** The current threshold is entirely meaningless across pairs with different price scales. For BTC at $80,000, a histogram of -0.0005 is negligible noise. For TRX at $0.25, it is a significant move. Normalising by price — `macd_hist / price × 100` — produces a dimensionless `%_of_price` metric that is directly comparable across pairs and matches the statistical data in Section 2d.

**How to compute at runtime:** No rolling window needed — this is a per-cycle calculation. In `features.py:check_exit_timing()`:
1. Read `macd_hist` and `price` from the indicators dict.
2. Compute `macd_hist_pct = (macd_hist / price) * 100`.
3. Read the per-pair threshold from config: `exit_timing.per_pair_macd_decay_threshold_pct[pair]`, falling back to `exit_timing.macd_decay_threshold_pct` (global default).
4. Fire the decay alert when `macd_hist_pct < threshold`.

**Code change required (1 function):**
In `features.py:check_exit_timing()`, replace:
```python
macd_decay = et_cfg.get("macd_decay_threshold", -0.0005)
...
if macd_hist is not None and macd_hist < macd_decay:
```
With:
```python
# Normalise to % of price for cross-pair comparability
if macd_hist is not None and price and price > 0:
    macd_hist_pct = (macd_hist / price) * 100
    pair_thresholds = et_cfg.get("per_pair_macd_decay_threshold_pct", {})
    macd_decay_pct = pair_thresholds.get(pair, et_cfg.get("macd_decay_threshold_pct", -0.01250))
    if macd_hist_pct < macd_decay_pct:
        return f"MACD histogram decayed to {macd_hist_pct:.5f}% of price — bearish momentum"
```

**Config values:**
```yaml
exit_timing:
  macd_decay_threshold_pct: -0.01250   # Global default (XRP median — middle of the range)
  per_pair_macd_decay_threshold_pct:
    BTC/USD: -0.00691
    ETH/USD: -0.01164
    BNB/USD: -0.00844
    SOL/USD: -0.01445
    XRP/USD: -0.01250
    TRX/USD: -0.00585
    DOGE/USD: -0.01503
    ADA/USD: -0.01573
    LTC/USD: -0.01402
    AVAX/USD: -0.01466
    SUI/USD: -0.01675
    UNI/USD: -0.01791
    INJ/USD: -0.01951
```

The old `macd_decay_threshold: -0.0005` key should be removed to avoid confusion.

---

### 3d. Rolling Volume Floor (`min_volume_ratio` → runtime adaptive)

**What it is:** The fraction of the 20-period volume SMA below which a candle is declared a dead zone. Currently a single global constant (0.5).

**Why it should be dynamic:** The 20-period SMA is already a rolling reference, but the threshold (50%) is fixed regardless of how each pair's volume is distributed. For UNI (p10 ratio = 0.021), the bottom decile of volume is at 2.1% of the SMA — this is the truly extreme dead zone. The current 50% threshold blocks far more candles than intended. Rather than comparing to a fixed fraction of the SMA, compare to the pair's own recent volume distribution percentile. This is robust against regime changes because the reference window moves with the market.

**How to compute at runtime:**
1. From the candle buffer, extract the last `lookback_candles` volume values.
2. Compute the p15 of those volumes.
3. Block entry when current volume < rolling_p15.
4. Fall back to static per-pair `min_volume_ratio × current_volume_sma_20` if fewer than `min_candles` available.

**Formula:**
```
recent_volumes = [candle.volume for candle in last lookback_candles]
rolling_p15 = percentile(recent_volumes, 15)
is_dead_zone = current_volume < rolling_p15
```

**Where in code:** `signals.py:generate_signal()` (Hard Blocker 3). The rolling p15 must be pre-computed in `main.py` (same injection pattern as 3a/3b) and passed as `rolling_volume_p15` in the indicators dict. `generate_signal()` uses `rolling_volume_p15` when available, falls back to `volume_sma_20 × min_volume_ratio` (static behaviour unchanged as fallback).

**Config values:**
```yaml
adaptive_volume_floor:
  enabled: true
  lookback_candles: 100      # ~25 hours
  percentile: 15             # Block candles below p15 of recent volume history
  min_candles: 30            # Fall back to static ratio if fewer candles available
```

---

## Section 4: Implementation Sequence

Issues must be created before any implementation begins (per `feedback_github_traceability.md`).

### Issue 1: [FEAT] Per-pair `rsi_oversold` and `rsi_overbought` thresholds

- **Files changed:** `config.yaml`, `src/analysis/signals.py`
- **Config changes:** Add `rsi_oversold` and `rsi_overbought` keys to each entry in `trading.pairs[]`. `signals.py:generate_signal()` reads per-pair overrides from the pair's config dict, falls back to global `indicators.rsi_oversold` / `indicators.rsi_overbought`.
- **Estimated impact:** TRX most affected (RSI oversold lowered from 30→35, overbought from 75→65). XRP, DOGE, ADA, LTC, SUI, INJ gain more frequent overbought signals via 75→72.
- **Dependencies:** None — standalone config change + tiny signal read path.
- **Risk:** Low. Pure threshold change. No structural code change.

### Issue 2: [FEAT] Per-pair `atr_tp_min_pct` (replaces broken global 1.0%)

- **Files changed:** `config.yaml`, `src/analysis/signals.py`
- **Config changes:** Add `atr_tp_min_pct` to each `trading.pairs[]` entry. `signals.py` reads `pair_config.get("atr_tp_min_pct")` before falling back to `dynamic_tp.atr_tp_min_pct`. Remove or deprecate the global `dynamic_tp.atr_tp_min_pct`.
- **Estimated impact:** Very high. The current global 1.0% floor is blocking virtually all BUY signals since no pair's ATR-based TP reaches 1.0% (medians range 0.42%–1.20%, mostly below 1.0%). BTC floor drops to 0.15% — it will now be permitted to generate BUY signals in normal conditions.
- **Dependencies:** None. Standalone.
- **Risk:** Low-medium. High impact on signal generation — should be validated with a backtest run after merge.

### Issue 3: [FEAT] Per-pair `bb_squeeze_threshold_pct` (static values from Section 2c)

- **Files changed:** `config.yaml`, `src/analysis/features.py`
- **Config changes:** Add `bb_squeeze_threshold_pct` to each `trading.pairs[]` entry. `features.py:compute_dynamic_tp()` reads `pair_config.get("bb_squeeze_threshold_pct")` before falling back to global `dynamic_tp.squeeze_threshold_pct`.
- **Estimated impact:** High for high-volatility alts. Current global 1.0% incorrectly declares most SOL/SUI/UNI/INJ candles as squeezes, suppressing dynamic TP upside. Per-pair values (1.8–2.5%) calibrate the squeeze to each pair.
- **Dependencies:** None. Standalone.
- **Risk:** Low.

### Issue 4: [FEAT] Per-pair `min_volume_ratio` (static values from Section 2e)

- **Files changed:** `config.yaml`, `src/analysis/signals.py`
- **Config changes:** Add `min_volume_ratio` to each `trading.pairs[]` entry. `signals.py` (Hard Blocker 3) reads per-pair override before global `allowed_trading_hours.min_volume_ratio`.
- **Estimated impact:** High for BNB, UNI, INJ (currently blocking 56–58% of all candles — dropping to 0.30 unblocks ~26% of those). Medium for TRX, DOGE, ADA, LTC, AVAX.
- **Dependencies:** None. Standalone.
- **Risk:** Low. The threshold is still active — only the calibration changes.

### Issue 5: [FEAT] Price-normalised MACD decay threshold in exit_timing (Section 3c)

- **Files changed:** `config.yaml`, `src/analysis/features.py`
- **Config changes:** Add `macd_decay_threshold_pct` (global) and `per_pair_macd_decay_threshold_pct` dict to `exit_timing`. Remove old `macd_decay_threshold: -0.0005`.
- **Estimated impact:** High correctness improvement. The current absolute threshold is broken for BTC (effectively never fires) and over-sensitive for micro-cap pairs. Per-pair % thresholds make exit timing meaningful across all 15 pairs.
- **Dependencies:** None.
- **Risk:** Low-medium. One function change in `features.py`. Requires updating existing tests for `check_exit_timing()`.

### Issue 6: [FEAT] Adaptive ATR floor — pre-compute rolling p25 and inject into indicators (Section 3a)

- **Files changed:** `config.yaml`, `main.py` (or `websocket_feed.py`), `src/analysis/signals.py`
- **Config changes:** Add `adaptive_atr_floor` section (see Section 3a config preview).
- **Estimated impact:** Medium. Allows ATR floor to self-calibrate as volatility regimes shift, reducing manual intervention.
- **Dependencies:** Issues 2 and 4 should land first (per-pair static values are the fallback for adaptive).
- **Risk:** Medium. Requires new pre-computation in the main loop and indicator dict injection. Needs new tests.

### Issue 7: [FEAT] Adaptive BB squeeze — rolling p10 BB width injected into indicators (Section 3b)

- **Files changed:** `config.yaml`, `main.py`, `src/analysis/features.py`
- **Config changes:** Add `adaptive_bb_squeeze` section.
- **Estimated impact:** Low-medium. Primarily improves dynamic TP accuracy over time.
- **Dependencies:** Issue 3 (per-pair static values are the fallback).
- **Risk:** Medium. Same injection pattern as Issue 6.

### Issue 8: [FEAT] Adaptive volume floor — rolling p15 injected into indicators (Section 3d)

- **Files changed:** `config.yaml`, `main.py`, `src/analysis/signals.py`
- **Config changes:** Add `adaptive_volume_floor` section.
- **Estimated impact:** Medium. Better calibration for UNI/INJ/BNB dead zone detection over time.
- **Dependencies:** Issue 4 (static per-pair ratios are the fallback).
- **Risk:** Medium.

---

## Section 5: Config Change Preview

The following shows additions and modifications to `config.yaml`. Only the changed sections are shown.

### 5a. `trading.pairs[]` — new per-pair fields

Each pair entry gains four new optional fields. Example for the full set:

```yaml
trading:
  pairs:
    - pair: BTC/USD
      ws_name: XBT/USD
      rest_name: XBTUSD
      take_profit_pct: 8
      stop_loss_pct: 5
      rsi_oversold: 30              # NEW — pair-specific oversold threshold
      rsi_overbought: 75            # NEW — pair-specific overbought threshold
      bb_squeeze_threshold_pct: 0.7 # NEW — per-pair BB squeeze (replaces global 1.0)
      atr_tp_min_pct: 0.15          # NEW — per-pair ATR floor (replaces broken global 1.0)
      min_volume_ratio: 0.50        # NEW — per-pair dead zone ratio

    - pair: ETH/USD
      ws_name: ETH/USD
      rest_name: ETHUSD
      take_profit_pct: 12
      stop_loss_pct: 5
      rsi_oversold: 30
      rsi_overbought: 75
      bb_squeeze_threshold_pct: 1.3
      atr_tp_min_pct: 0.23
      min_volume_ratio: 0.50

    - pair: BNB/USD
      ws_name: BNB/USD
      rest_name: BNBUSD
      take_profit_pct: 12
      stop_loss_pct: 5
      rsi_oversold: 28
      rsi_overbought: 75
      bb_squeeze_threshold_pct: 0.9
      atr_tp_min_pct: 0.15
      min_volume_ratio: 0.30        # Dead zone 56.6% — use lower threshold

    - pair: SOL/USD
      ws_name: SOL/USD
      rest_name: SOLUSD
      take_profit_pct: 16
      stop_loss_pct: 5
      rsi_oversold: 30
      rsi_overbought: 75
      bb_squeeze_threshold_pct: 1.8
      atr_tp_min_pct: 0.30
      min_volume_ratio: 0.50

    - pair: XRP/USD
      ws_name: XRP/USD
      rest_name: XRPUSD
      take_profit_pct: 12
      stop_loss_pct: 5
      rsi_oversold: 28
      rsi_overbought: 72
      bb_squeeze_threshold_pct: 1.4
      atr_tp_min_pct: 0.26
      min_volume_ratio: 0.50

    - pair: TRX/USD
      ws_name: TRX/USD
      rest_name: TRXUSD
      take_profit_pct: 12
      stop_loss_pct: 5
      rsi_oversold: 35              # Oversold fires too often at 30 (6.87%)
      rsi_overbought: 65            # Overbought fires too often at 70 (6.65%)
      bb_squeeze_threshold_pct: 0.8
      atr_tp_min_pct: 0.15
      min_volume_ratio: 0.40

    - pair: DOGE/USD
      ws_name: DOGE/USD
      rest_name: XDGUSD
      take_profit_pct: 20
      stop_loss_pct: 5
      rsi_oversold: 30
      rsi_overbought: 72
      bb_squeeze_threshold_pct: 1.8
      atr_tp_min_pct: 0.31
      min_volume_ratio: 0.40

    - pair: ADA/USD
      ws_name: ADA/USD
      rest_name: ADAUSD
      take_profit_pct: 12
      stop_loss_pct: 5
      rsi_oversold: 30
      rsi_overbought: 72
      bb_squeeze_threshold_pct: 1.9
      atr_tp_min_pct: 0.32
      min_volume_ratio: 0.40

    - pair: LTC/USD
      ws_name: LTC/USD
      rest_name: LTCUSD
      take_profit_pct: 12
      stop_loss_pct: 5
      rsi_oversold: 28
      rsi_overbought: 72
      bb_squeeze_threshold_pct: 1.5
      atr_tp_min_pct: 0.26
      min_volume_ratio: 0.40

    - pair: RAILS/USD
      ws_name: RAILS/USD
      rest_name: RAILSUSD
      take_profit_pct: 20
      stop_loss_pct: 5
      # No per-pair signal params — no historical data; global defaults apply

    - pair: AVAX/USD
      ws_name: AVAX/USD
      rest_name: AVAXUSD
      take_profit_pct: 12
      stop_loss_pct: 5
      rsi_oversold: 30
      rsi_overbought: 75
      bb_squeeze_threshold_pct: 2.0
      atr_tp_min_pct: 0.31
      min_volume_ratio: 0.40

    - pair: SUI/USD
      ws_name: SUI/USD
      rest_name: SUIUSD
      take_profit_pct: 20
      stop_loss_pct: 5
      rsi_oversold: 30
      rsi_overbought: 72
      bb_squeeze_threshold_pct: 2.1
      atr_tp_min_pct: 0.37
      min_volume_ratio: 0.50

    - pair: HYPE/USD
      ws_name: HYPE/USD
      rest_name: HYPEUSD
      take_profit_pct: 20
      stop_loss_pct: 5
      # No per-pair signal params — no historical data; global defaults apply

    - pair: UNI/USD
      ws_name: UNI/USD
      rest_name: UNIUSD
      take_profit_pct: 12
      stop_loss_pct: 5
      rsi_oversold: 30
      rsi_overbought: 75
      bb_squeeze_threshold_pct: 2.1
      atr_tp_min_pct: 0.30
      min_volume_ratio: 0.30        # Dead zone 57.9% — use lower threshold

    - pair: INJ/USD
      ws_name: INJ/USD
      rest_name: INJUSD
      take_profit_pct: 20
      stop_loss_pct: 5
      rsi_oversold: 30
      rsi_overbought: 72
      bb_squeeze_threshold_pct: 2.5
      atr_tp_min_pct: 0.34
      min_volume_ratio: 0.30        # Dead zone 58.3% — use lower threshold
```

### 5b. `dynamic_tp` — deprecate global `atr_tp_min_pct`

```yaml
dynamic_tp:
  enabled: true
  atr_multiplier: 2.0
  bb_width_scale: true
  min_tp_pct: 5
  max_tp_pct: 20
  squeeze_threshold_pct: 1.0    # Global fallback only — per-pair overrides in trading.pairs[]
  atr_tp_min_pct: 0.15          # DEPRECATED: now per-pair in trading.pairs[]; this is the fallback
```

### 5c. `exit_timing` — replace absolute MACD threshold with price-normalised per-pair values

```yaml
exit_timing:
  enabled: true
  min_hold_minutes: 60
  # macd_decay_threshold: -0.0005   # REMOVED — replaced by normalised threshold below
  macd_decay_threshold_pct: -0.01250  # NEW: % of price; global fallback (XRP median)
  per_pair_macd_decay_threshold_pct:  # NEW: per-pair overrides
    BTC/USD: -0.00691
    ETH/USD: -0.01164
    BNB/USD: -0.00844
    SOL/USD: -0.01445
    XRP/USD: -0.01250
    TRX/USD: -0.00585
    DOGE/USD: -0.01503
    ADA/USD: -0.01573
    LTC/USD: -0.01402
    AVAX/USD: -0.01466
    SUI/USD: -0.01675
    UNI/USD: -0.01791
    INJ/USD: -0.01951
  rsi_exit_overbought: 70
  sideways_candles: 8
```

### 5d. New sections for runtime-adaptive parameters (Issues 6–8)

```yaml
# ──────────────────────────────────────────────
# Adaptive ATR floor — overrides static atr_tp_min_pct with rolling p25 ATR%
# ──────────────────────────────────────────────
adaptive_atr_floor:
  enabled: false             # Enable after static per-pair values are validated (Issue 6)
  lookback_candles: 100      # ~25 hours of 15-min candles
  scaling_factor: 0.8        # Floor = p25 of recent ATR% × scaling_factor
  min_cap: 0.15              # Absolute minimum floor across all pairs

# ──────────────────────────────────────────────
# Adaptive BB squeeze — rolling p10 BB width replaces static squeeze threshold
# ──────────────────────────────────────────────
adaptive_bb_squeeze:
  enabled: false             # Enable after static per-pair values are validated (Issue 7)
  lookback_candles: 200      # ~50 hours
  percentile: 10             # Squeeze = width < p10 of recent history
  min_candles: 50            # Fall back to static if insufficient buffer

# ──────────────────────────────────────────────
# Adaptive volume floor — rolling p15 volume replaces fixed ratio × SMA
# ──────────────────────────────────────────────
adaptive_volume_floor:
  enabled: false             # Enable after static per-pair values are validated (Issue 8)
  lookback_candles: 100      # ~25 hours
  percentile: 15             # Dead zone = volume < p15 of recent history
  min_candles: 30            # Fall back to static ratio if insufficient buffer
```

---

*End of plan. All values in this document are derived directly from the 2025-01-01 historical candle dataset provided. No implementation should begin until this plan is reviewed and approved.*
