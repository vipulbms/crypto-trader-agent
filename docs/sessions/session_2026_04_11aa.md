# Session Notes — 2026-04-11 (Part AA)

## Changes

### 1. Feat: sector rotation via pair tiers in rising BTC dominance (#203)

**Bug report / Feature request:** Kryptos already stored `pair_tier` in `config.yaml`, but runtime sizing logic still treated all pairs the same in bearish conditions even when BTC dominance was rising.

**Root cause / Motivation:**
- `main.py` only applied `caution_factor_bearish`; it never used `pair_tier` or the new dominance multipliers.
- The per-pair signal block shown to the LLM did not expose the tier.
- `propose_buy()` had no tool-side enforcement for the per-pair regime-adjusted cap, so the limit was guidance only.
- `add-pair` and `trading-rules` skills did not yet describe the tiered sizing workflow introduced by #203.

**Fix / Implementation:**
- Added `compute_pair_regime_caps()` in `src/analysis/features.py` to compute `pair_tier`, `pair_max_usd`, and the dominance multiplier used for each pair.
- Updated `main.py` to inject `pair_tier` into every signal and to apply additional dominance multipliers when regime is bearish and `btc_dominance_trend == rising`:
  - Tier 3 → `0.5×`
  - Tier 4 → `0.3×`
  - secondary non-core Tier 2 alts → `0.7×`
  - BTC / ETH / BNB unaffected
- Updated `src/agent/prompts.py` to display `Tier: N (label)` in each per-pair signal block.
- Updated `src/agent/tools.py` and `src/agent/trading_agent.py` so `propose_buy()` receives per-pair `pair_max_usd` caps and enforces them before calling `validate_buy()`.
- Updated `.claude/skills/add-pair/SKILL.md` to include `pair_tier` in the pair template and guidance table.
- Updated `.claude/skills/trading-rules/SKILL.md` to document the concrete tiered BTC-dominance sizing overlay.
- Added `tests/test_sector_tiers.py` with focused coverage for cap math, prompt visibility, and tool-side cap enforcement.

**Validation:**
- `python -m pytest tests/test_sector_tiers.py -q` → 4 passed
- `python -m pytest tests/test_regime_and_dynamic_tp.py -q` → 20 passed

**Closes:** #203