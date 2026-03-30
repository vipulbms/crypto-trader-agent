---
name: add-pair
description: Add a new trading pair to Kryptos. Use when the user asks to add, onboard, or enable a new crypto pair.
argument-hint: PAIR/USD KRAKENRESTNAME
---

# Add New Trading Pair

Add **$ARGUMENTS** to the Kryptos trading agent.

## Current pairs for reference
!`grep -E "pair:|ws_name:|rest_name:" config.yaml | grep -v "^#"`

## Steps

### 1. Parse arguments
Extract from `$ARGUMENTS`:
- `PAIR/USD` — the display pair name (e.g. `AVAX/USD`)
- `KRAKENRESTNAME` — the Kraken REST OHLC name (e.g. `AVAXUSD`) — provided by the user

### 2. Verify the pair exists on Kraken and get its WS name
Run this to confirm the pair is valid and get the official WS name:
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
    print(f'Price: ', end='')
    r2 = requests.get('https://api.kraken.com/0/public/OHLC', params={'pair': rest, 'interval': 60}, timeout=10)
    d2 = r2.json()
    rk = [k for k in d2['result'] if k != 'last'][0]
    print(d2['result'][rk][-1][4])
"
```

### 3. Determine take_profit_pct
If not provided by the user, recommend based on volatility:
- Low volatility (BTC-like): 8%
- Moderate volatility (ETH-like): 12%
- High volatility (SOL/AVAX-like): 15-16%
- Meme/extreme volatility: 20%
- Must be one of: 5, 8, 12, 15, 16, 20

### 4. Make all changes

**a) `config.yaml`** — add to the `trading.pairs` list (this is now the SINGLE source of truth for all pair maps):
```yaml
    - pair: PAIR/USD
      ws_name: WS_NAME        # from step 2 (e.g. AVAX/USD; BTC is XBT/USD)
      rest_name: KRAKENRESTNAME  # e.g. AVAXUSD, XBTUSD, XDGUSD
      take_profit_pct: <value>
      stop_loss_pct: 5
```

**b) `src/agent/prompts.py`** — update the pair count and list in `SYSTEM_PROMPT`:
```python
- You monitor N pairs: ..., PAIR/USD
```

**c) `src/agent/tools.py`** — add `'PAIR/USD'` to the `propose_buy` docstring pair list.

**d) `src/cli/display.py`** — update the pairs list in `print_welcome()`.

**e) `src/cli/nl_parser.py`** — add `'PAIR/USD'` and `'SYMBOL'` to the `PAIRS` list, and add to the LLM system prompt pair hint.

**f) `rsi_verifier.py`** — no change needed (reads pairs from config.yaml automatically).

**g) `src/exchange/websocket_feed.py`** — no change needed (builds maps from config.yaml automatically).

**h) `src/exchange/kraken_client.py`** — no change needed (builds maps from config.yaml automatically).

**i) `random_execution_kraken.py`** — add to `PAIRS` dict:
```python
'PAIR/USD': 'KRAKENRESTNAME',
```

### 5. Verify consistency
After making changes, confirm:
- [ ] `config.yaml` has `pair`, `ws_name`, `rest_name`, `take_profit_pct`, `stop_loss_pct`
- [ ] `src/agent/prompts.py` pair count and list updated
- [ ] `src/agent/tools.py` docstring updated
- [ ] `src/cli/display.py` welcome banner updated
- [ ] `src/cli/nl_parser.py` PAIRS list and LLM prompt updated
- [ ] `random_execution_kraken.py` PAIRS dict updated

### 6. Report
Tell the user:
- Pair added, WS name, REST name, take-profit rationale
- Agent needs a restart to pick up the new pair
- No code changes needed in websocket_feed.py or kraken_client.py (config-driven)
