# Session Notes — 2026-04-11 (Part AC)

## Changes

### 1. Feat: macro cycle-top guard via MVRV Z-Score and NUPL (#205)

**Bug report / Feature request:** Kryptos had no on-chain cycle-position awareness and could keep opening aggressive Tier 3 / Tier 4 altcoin BUYs even when Bitcoin was historically overvalued at a macro cycle top.

**Root cause / Motivation:**
- `risk.cycle_top_guard` was present in `config.yaml`, but nothing in the runtime fetched CoinGlass indicators or enforced the guard.
- The prompt had no macro-peak warning block, so the LLM could not distinguish a normal bearish dip from a late-cycle distribution regime.
- `validate_buy()` had no code-enforced block on speculative tiers during cycle-top conditions.

**Fix / Implementation:**
- Added `fetch_cycle_top_indicators()` to `src/analysis/features.py` with in-memory caching, `agent_state` persistence, and defensive parsing for CoinGlass MVRV/NUPL payloads.
- Added `build_cycle_top_context()` and `apply_cycle_top_guard()` so the prompt can render a `[CYCLE TOP WARNING]` block and Tier 3 / Tier 4 raw BUY signals can be suppressed to HOLD before the LLM ranks candidates.
- Updated `main.py` to fetch the cycle-top metrics once per cycle, propagate the warning into AI context, suppress speculative BUYs, and send Telegram activation/deactivation alerts.
- Updated `src/risk/risk_manager.py` with a code-enforced cycle-top state gate so Tier 3 / Tier 4 `propose_buy()` calls are rejected even if the LLM still tries them.
- Updated `.claude/skills/trading-rules/SKILL.md` so prompt guidance reflects the new hard guardrail.
- Added `tests/test_cycle_top_guard.py` covering fetch/cache parsing, prompt warning rendering, suppression logic, and buy validation.

**Validation:**
- `python -m pytest tests/test_cycle_top_guard.py tests/test_btc_dominance.py tests/test_sector_tiers.py tests/test_regime_and_dynamic_tp.py` → 46 passed

**Closes:** #205