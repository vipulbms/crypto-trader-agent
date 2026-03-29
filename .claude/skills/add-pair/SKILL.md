---
name: add-pair
description: Add a new trading pair to Kryptos. Use when the user asks to add, onboard, or enable a new crypto pair.
argument-hint: PAIR/USD take_profit_pct
---

# Add New Trading Pair

Add **$ARGUMENTS** to the Kryptos trading agent.

## Current pairs for reference
!`grep "pair:" config.yaml | grep -v "^#"`

## Steps

### 1. Parse arguments
Extract from `$ARGUMENTS`:
- `PAIR` — the base asset symbol (e.g. `SOL`, `PEPE`)
- `take_profit_pct` — desired take-profit % (must be one of: 5, 8, 12, 16, 20)
- Stop-loss is always 5% (fixed)

If take_profit_pct is not provided, recommend one based on volatility:
- Low volatility (BTC-like): 8%
- Moderate volatility: 12%
- High volatility: 16%
- Meme/extreme volatility: 20%

### 2. Determine Kraken pair names
Kraken uses different names in the WebSocket API vs REST API vs ccxt. Common mappings:
- WebSocket: usually `SYMBOL/USD` as-is (except BTC → `XBT/USD`)
- REST OHLC: usually `SYMBOLUSD` (except BTC → `XBTUSD`, DOGE → `XDGUSD`)
- ccxt (live): usually `SYMBOL/USD` as-is

If unsure about the Kraken-specific name, note it and ask the user to verify against https://api.kraken.com/0/public/AssetPairs before proceeding.

### 3. Make all changes

**a) `config.yaml`** — add to the `trading.pairs` list:
```yaml
    - pair: SYMBOL/USD
      take_profit_pct: <value>
      stop_loss_pct: 5
```

**b) `src/exchange/websocket_feed.py`** — add to both `PAIR_MAP` and `REST_PAIR_MAP`:
```python
PAIR_MAP = {
    ...
    "SYMBOL/USD": "WS_SYMBOL/USD",   # Kraken WS name
}
REST_PAIR_MAP = {
    ...
    "SYMBOL/USD": "SYMBOLUSD",       # Kraken REST OHLC name
}
```

**c) `src/exchange/kraken_client.py`** — add to `KRAKEN_PAIR_MAP`:
```python
KRAKEN_PAIR_MAP = {
    ...
    "SYMBOL/USD": "SYMBOL/USD",      # ccxt name
}
```

**d) `src/cli/display.py`** — update the pairs list in `print_welcome()`.

**e) `README.md`** — add a row to the Trading Pairs & Targets table.

**f) `business-requirement.md`** — update FR-01 pair list, Section 8 Per-Pair Configuration table, revision history, and pair count in FR-51 and scope section.

**g) `plan.md`** — update the pairs line in the LLM system prompt section and the pairs table.

### 4. Verify consistency
After making changes, confirm:
- [ ] `config.yaml` has the new pair
- [ ] `PAIR_MAP` and `REST_PAIR_MAP` both updated in `websocket_feed.py`
- [ ] `KRAKEN_PAIR_MAP` updated in `kraken_client.py`
- [ ] `print_welcome()` updated in `display.py`
- [ ] All three docs updated (README, plan, requirement)

### 5. Report
Tell the user:
- What was added and where
- The Kraken WS/REST names used (flag if uncertain)
- The take-profit rationale
- That the agent needs to be restarted to pick up the new pair
