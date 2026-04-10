---
name: add-pair
description: Add a new trading pair to Kryptos. Use when the user asks to add, onboard, or enable a new crypto pair.
argument-hint: PAIR/USD KRAKENRESTNAME [tp_pct]
---

# Add New Trading Pair

Add **$ARGUMENTS** to the Kryptos trading agent.

## Current pairs for reference
!`grep -E "^\s+- pair:|ws_name:|rest_name:|take_profit_pct:|atr_tp_min_pct:|rsi_oversold:|bb_squeeze" config.yaml | grep -v "^#" | head -80`

## Steps

### 1. Parse arguments
Extract from `$ARGUMENTS`:
- `PAIR/USD` — the display pair name (e.g. `HYPE/USD`)
- `KRAKENRESTNAME` — the Kraken REST OHLC symbol (e.g. `HYPEUSD`) — provided by the user
- `tp_pct` — take-profit % (optional; if omitted, derived in step 3)

### 2. Verify the pair exists on Kraken and get its WS name
```bash
python3.11 -c "
import requests
rest = 'KRAKENRESTNAME'
resp = requests.get('https://api.kraken.com/0/public/AssetPairs', params={'pair': rest}, timeout=10)
data = resp.json()
if data.get('error'):
    print('ERROR:', data['error'])
else:
    key = list(data['result'].keys())[0]
    info = data['result'][key]
    print(f'WS name: {info.get(\"wsname\")}')
    r2 = requests.get('https://api.kraken.com/0/public/OHLC', params={'pair': rest, 'interval': 15}, timeout=10)
    d2 = r2.json()
    rk = [k for k in d2['result'] if k != 'last'][0]
    candles = d2['result'][rk]
    price = candles[-1][4]
    print(f'Latest price: {price}')
    print(f'Candles returned: {len(candles)}')
"
```

### 3. Determine take_profit_pct
If not provided by the user, recommend based on volatility profile:
- Low volatility (BTC-like, slow mover): **8%**
- Moderate volatility (ETH/BNB/XRP-like): **12%**
- High volatility (SOL/AVAX-like): **16%**
- Meme/extreme volatility (DOGE/RAILS/HYPE-like): **20%**
- Must be one of: `5 | 8 | 12 | 16 | 20`

### 4. Calibrate per-pair signal parameters

Every pair requires 6 calibrated signal parameters. These cannot be left at global defaults — global values are statistically wrong for most pairs (the global `bb_squeeze_threshold_pct: 1.0%` over-squeezes high-volatility pairs; the global `min_volume_ratio: 0.5` blocks >50% of candles for some pairs).

**Run the calibration utility first:**
```bash
~/.pyenv/versions/3.11.15/bin/python3 scripts/calibrate_params.py \
    --start-date 2025-01-01 \
    --pairs PAIR/USD \
    --output /tmp/new_pair_params.yaml
```

Read `/tmp/new_pair_params.yaml` for the recommended values.

**If calibration fails** (no historical data yet — common for brand-new pairs), use these estimation rules derived from the pair's volatility tier:

| Parameter | Low-vol (BTC-like) | Mid-vol (ETH-like) | High-vol (SOL-like) | Meme (DOGE-like) |
|---|---|---|---|---|
| `atr_tp_min_pct` | 0.12–0.18 | 0.20–0.30 | 0.28–0.36 | 0.30–0.40 |
| `rsi_oversold` | 30 | 30 | 30 | 30 |
| `rsi_overbought` | 75 | 72–75 | 72 | 72 |
| `bb_squeeze_threshold_pct` | 0.7–1.0 | 1.2–1.5 | 1.6–2.0 | 1.8–2.5 |
| `min_volume_ratio` | 0.50 | 0.40–0.50 | 0.40 | 0.40 |
| `adaptive_atr_floor_lookback` | 400 | 400 | 400 | 400 |
| `rsi_divergence_lookback` | 25 | 20 | 20 | 15 |
| `obv_trend_period` | 14 | 10 | 10 | 7 |

`adx_period` is always 14 (Wilder standard) — no per-pair override needed at launch unless the pair is unusually noisy.

**How to interpret calibration output:**
- `atr_tp_min_pct` = p25 ATR% × 0.8, rounded to 2dp. Min cap: 0.10%. This is the minimum expected move needed to justify entry.
- `rsi_oversold` = RSI p5, adjusted to nearest 2, so oversold fires ~5-8% of candles. Min 25, max 35.
- `rsi_overbought` = RSI p95, adjusted to nearest 2. Min 65, max 80.
- `bb_squeeze_threshold_pct` = p10 BB width%. Below this = pair is in squeeze; TP clamps to pair floor.
- `min_volume_ratio` = if >50% of candles were dead zone at 0.30 threshold → use 0.30. If >35% → 0.40. Otherwise 0.50.
- `adaptive_atr_floor_lookback` = always 400 unless pair has unusual volatility spikes (then 200).

### 5. Make all changes

**a) `config.yaml`** — add to `trading.pairs[]` (full 15-field block required):
```yaml
    - pair: PAIR/USD
      ws_name: WS_NAME                   # from step 2 (e.g. AVAX/USD; BTC is XBT/USD)
      rest_name: KRAKENRESTNAME          # e.g. HYPEUSD, AVAXUSD, XBTUSD
      take_profit_pct: <value>           # from step 3
      stop_loss_pct: 5                   # fixed — never change
      atr_tp_min_pct: <value>            # from calibration (step 4)
      rsi_oversold: <value>              # from calibration (step 4)
      rsi_overbought: <value>            # from calibration (step 4)
      bb_squeeze_threshold_pct: <value>  # from calibration (step 4)
      min_volume_ratio: <value>          # from calibration (step 4)
      adaptive_atr_floor_lookback: 400   # 100h window — change only if volatility spikes are extreme
      caution_factor_bearish: <value>    # bearish regime position multiplier (#124); see table below
      buy_min_score: <value>             # min confluence score for BUY (#128); see table below
      rsi_divergence_lookback: <value>   # from calibration table (step 4): 25=slow, 20=mid, 15=fast/meme (#135)
      obv_trend_period: <value>          # candles back to compare OBV for trend (#136); see table below
```

**caution_factor_bearish** — how aggressively to cut position size in bearish regime (1.0 = no cut, buy the dip; 0.30 = cut to 30%):
| Volatility tier | Suggested value | Reasoning |
|---|---|---|
| Proven winner (ETH/BNB/DOGE-like) | **1.0** | Buy the dip — these outperform even in bearish |
| Stable large-cap (BTC/LTC/TRX/XRP-like) | **0.8** | Low bearish drawdown (~1%) — slight caution only |
| Mid-volatility (ADA/AVAX-like) | **0.6** | Moderate bearish drawdown (~1.8–1.9%) |
| Underperformer (SOL-like) | **0.5** | Global default — mixed track record |
| High-volatility meme (RAILS/HYPE-like) | **0.4** | Unpredictable — cut harder |
| Highest drawdown (SUI/INJ-like) | **0.35** | Worst bearish behaviour — protect capital |

**buy_min_score** — minimum confluence score to emit a BUY signal (global default = 5):
| Win rate at score 5 | Suggested value |
|---|---|
| ≥ 80% | 5 (global default — don't override) |
| 50–79% | **6** |
| < 50% | **7** |

**b) `src/agent/prompts.py`** — check if `SYSTEM_PROMPT` has a hardcoded pair count or list:
```bash
grep -n "pairs\|monitor\|PAIR" src/agent/prompts.py | head -20
```
If a hardcoded list or count is found, update it to include `PAIR/USD` and increment the count.

**c) `src/agent/tools.py`** — add `'PAIR/USD'` to the `propose_buy` docstring pair list:
```bash
grep -n "pair.*BTC/USD\|BTC/USD.*pair" src/agent/tools.py | head -5
```
Update the docstring line to include the new pair.

**d) `src/cli/display.py`** — update the pairs list in `print_welcome()`:
```bash
grep -n "BTC.*ETH.*BNB\|Pairs:" src/cli/display.py | head -5
```
Append the new symbol (without /USD) to the welcome banner string.

**e) `src/cli/nl_parser.py`** — add to **both** the PAIRS list and the LLM system prompt:
```bash
grep -n "PAIRS\s*=\|BTC/USD.*ETH/USD" src/cli/nl_parser.py | head -5
```
- Add `'PAIR/USD'` to the full-name list
- Add `'SYMBOL'` to the short-name list  
- Add `PAIR/USD` to the comma-separated list in `_SYSTEM_PROMPT`

**f) `docs/business_requirements.md`** — surgical updates:
- Update pair count in scope statement (e.g. "fifteen" → "sixteen")
- Add `PAIR/USD` to FR-01 pair list
- Add row to the Pair Parameters table: `| PAIR/USD | TP% | 5% | rationale |`
- Add a version history entry

**g) `docs/epics_stories_ac.md`** — update pair count references:
```bash
grep -n "15 pairs\|fifteen pairs" docs/epics_stories_ac.md
```
Update each occurrence of the count.

**h) `CLAUDE.md`** — update the pairs table in "Pairs and Take-Profit Targets":
Add a row for the new pair.

### 6. Run 7-day fast backtest to validate signal parameters

Before committing, validate that the new pair's signal parameters produce acceptable win rates.

**Fetch historical candles if not already in `history/`:**
```bash
python3.11 -c "
import requests, json
rest = 'KRAKENRESTNAME'
resp = requests.get('https://api.kraken.com/0/public/OHLC',
    params={'pair': rest, 'interval': 15}, timeout=30)
data = resp.json()
key = [k for k in data['result'] if k != 'last'][0]
with open(f'history/{rest}_candle.json', 'w') as f:
    json.dump(data, f)
print(f'Saved {len(data[\"result\"][key])} candles')
"
```

**Run the fast backtest (no LLM, ~30 seconds):**
```bash
~/.pyenv/versions/3.11.15/bin/python3 tests/test_backtest.py \
    --no-llm \
    --start-date $(date -v-7d +%Y-%m-%d) \
    --pairs PAIR/USD
```

**Interpret results and adjust parameters:**

| Metric | Action |
|--------|--------|
| Win rate ≥ 60% | Parameters are good — proceed |
| Win rate 45–59% | Raise `buy_min_score` by 1 |
| Win rate < 45% | Raise `buy_min_score` by 2 AND raise `atr_tp_min_pct` by +0.05 |
| Zero BUY signals | `min_volume_ratio` or `atr_tp_min_pct` too aggressive — lower slightly |
| SL rate > 60% of exits | Entry quality poor — raise `buy_min_score` or `rsi_oversold` threshold |
| ADX < 20 in majority of signals | Pair is a chop pair — set `caution_factor_bearish` ≤ 0.4 |
| RSI divergence fires > 20% of BUYs | Shorten `rsi_divergence_lookback` by 5 |
| RSI divergence fires < 5% of BUYs | Lengthen `rsi_divergence_lookback` by 5 |
| OBV trend rarely rising (< 10% of candles) | Shorten `obv_trend_period` by 3 (captures shorter cycles) |
| OBV trend always rising (> 60% of candles) | Lengthen `obv_trend_period` by 3 (requires more conviction) |

Re-run the backtest after any parameter adjustment before committing.

### 7. Verify consistency

After making all changes, run these checks:

```bash
# Confirm config has all 11 fields for the new pair
grep -A 12 "pair: PAIR/USD" config.yaml

# Confirm nl_parser has both the full name and short name
grep "PAIR/USD\|SYMBOL" src/cli/nl_parser.py

# Confirm tools.py docstring updated
grep "PAIR/USD" src/agent/tools.py

# Run tests — all must pass before committing
~/.pyenv/versions/3.11.15/bin/python3 -c "
import sys; sys.path.insert(0, '.')
exec(open('tests/test_per_pair_params.py').read())
"
~/.pyenv/versions/3.11.15/bin/python3 tests/test_adaptive_atr_floor.py
```

**Checklist:**
- [ ] `config.yaml`: 15-field pair block present (pair, ws_name, rest_name, take_profit_pct, stop_loss_pct, atr_tp_min_pct, rsi_oversold, rsi_overbought, bb_squeeze_threshold_pct, min_volume_ratio, adaptive_atr_floor_lookback, caution_factor_bearish, buy_min_score, rsi_divergence_lookback, obv_trend_period)
- [ ] Fast backtest run and win rate acceptable (step 6)
- [ ] `src/agent/tools.py`: propose_buy docstring updated
- [ ] `src/cli/display.py`: welcome banner updated
- [ ] `src/cli/nl_parser.py`: PAIRS list (both full and short) updated; _SYSTEM_PROMPT updated
- [ ] `docs/business_requirements.md`: scope count, FR-01 list, pair table row, version history
- [ ] `docs/epics_stories_ac.md`: pair count references updated
- [ ] `CLAUDE.md`: pairs table updated
- [ ] All existing tests pass

### 8. Create a GitHub issue before committing
```bash
gh issue create --repo vipulbms/crypto-trader-agent \
  --title "[FEAT] Add PAIR/USD trading pair" \
  --body "## What\nAdd PAIR/USD (KRAKENRESTNAME) to the agent.\n\n## Why\n<user-provided rationale>\n\n## How to fix\n- config.yaml: 11-field pair block (tp=TP%, sl=5%)\n- atr_tp_min_pct=X, rsi_oversold=X, rsi_overbought=X, bb_squeeze=X, min_volume_ratio=X\n- nl_parser, tools.py, display.py updated\n- docs updated"
```

### 9. Commit
Use the `/commit` skill after all changes are verified and tests pass.

Commit message format:
```
feat: add PAIR/USD trading pair (tp=TP%, sl=5%)

- config.yaml: 11-field pair block with calibrated signal parameters
- atr_tp_min_pct=X% (calibrated/estimated), rsi_oversold=X, rsi_overbought=X
- bb_squeeze_threshold_pct=X%, min_volume_ratio=X
- nl_parser, tools.py, display.py, BRD, epics/stories updated

Closes #N
```

### 10. Report to user
Tell the user:
- Pair added with WS name, REST name, TP rationale
- Calibration source (calibrate_params.py result OR estimation fallback with reason)
- Per-pair signal thresholds set and why
- Agent needs a restart to pick up the new pair
- `websocket_feed.py`, `kraken_client.py`, `signals.py`, `features.py` require no changes (config-driven)
