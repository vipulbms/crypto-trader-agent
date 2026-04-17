# Kryptos — Session Changelog

---

## Session: 2026-04-17 (Part A) — Fix display.py PF tuple, CI simplified, README additions, UI design docs

### Bug Fixes
- **[#252] display.py `print_portfolio_summary()` crashes — `pf_by_pair` returns `(float, int)` tuple, not `float`**: `get_signal_driver_report()` passes `(profit_factor, n_trades)` tuples in `profit_factors` dict. `display.py` compared the value directly against float thresholds causing `TypeError`. Fix: unpack safely — `pf_entry[0] if isinstance(pf_entry, tuple) else pf_entry`. **Files:** `src/cli/display.py`

### Chores
- **[#181] CI pipeline simplified — remove Copilot review gate**: Removed `copilot-review` and `create-backlog-issues` jobs from `.github/workflows/ci.yml`. `test` job now runs unconditionally on every push/PR. Tests gate merges without Copilot review blocking them. **Files:** `.github/workflows/ci.yml`

### Documentation
- **[#253] README: Telegram Setup (§3) + Market Sentiment in Practice (§9) added**: Step-by-step Telegram bot creation guide (BotFather → chat ID → env config) and a live decision walkthrough showing how Fear & Greed, RSI, MACD, ATR, and OBV combine into a BUY score. **Files:** `README.md`
- **[#253] `.gitignore` excludes `.claude/settings.json`** (Claude Code auto-generated tool state)
- **[#251] UI design blueprint and mockups committed**: `docs/ui-designer.md` (1,297 lines, full SPA architecture + data contracts) and `docs/user-interface/` (HTML mockups, CSS, screenshots) — the design specification that drove the kryptos-ui + kryptos-api implementation. **Files:** `docs/ui-designer.md` (new), `docs/user-interface/` (new, 9 files)

---

## Session: 2026-04-13 (Part B) — Docs: comprehensive README rewrite + SETUP.md + setup.sh (#240)

### Documentation
- **README.md completely rewritten** — 19 sections (was ~8), 1,474 lines / 68 KB. Major additions:
  - §4 Technical Indicators: all 11 subsections (RSI, MACD, BB, BB Squeeze Release, EMA, ATR, ADX, OBV, RSI Divergence, Candlestick Patterns, Fear & Greed)
  - §5 BUY Signal — Complete Reference: 19-contributor scoring table (max_score=28), 5 hard vetoes, per-tier min scores, profit factor escalation logic, 3 worked examples (BTC/SOL/PEPE)
  - §6 SELL Signal — Complete Reference: `propose_sell` pre-flight (3 conditions), `validate_sell` gates, triple-condition rule, automatic exits, `close_position` P&L math, exit reason taxonomy (6 codes)
  - §7 HOLD Logic: 3 paths (hard-veto, score-miss, LLM HOLD)
  - §8 Sequence Diagrams: 4 Mermaid diagrams (BUY, SELL, HOLD, automatic SL/TP)
  - §9 Defence Mechanisms: dynamic TP, partial TP, trailing stop, hard SL + circuit breaker + kill switch, meme coin protections, correlation guard, macro overlays (BTC dominance + MVRV/NUPL cycle-top guard)
  - §10 Trading Pairs — Full Reference: 4 tier tables, all 27 pairs with TP%, min score, caution factor, slippage, trailing config
- **SETUP.md** (new) — 10-section first-time installation guide covering system requirements, LLM provider configuration (Groq/Gemini/Ollama), Telegram setup, healthcheck webhook, and paper trading reset
- **setup.sh** (new, executable) — automated setup script with Python 3.11 check, venv creation, interactive LLM provider selection, `.env` template generation

---

## Session: 2026-04-12 (Part E) — Fix qwen3-32b tool_use_failed: add reasoning_format=hidden (#228)

### Bug Fixes
- **[#228] qwen3-32b `tool_use_failed` — missing `reasoning_format`**: `qwen/qwen3-32b` continued failing with HTTP 400 `tool_use_failed` (empty `failed_generation`) on every LLM cycle despite the `reasoning_effort=none` fix from #223. Root cause: Groq docs require `reasoning_format` to be explicitly set to `parsed` or `hidden` when tool calling is enabled — the default `raw` is incompatible with function calling. Fix: added `reasoning_format: "hidden"` to the `extra_body` dict alongside `reasoning_effort: "none"` in `TradingAgent._call_openai_compat()`. `hidden` returns only the final answer with no reasoning tokens.

---

## Session: 2026-04-12 (Part D) — Fix duplicate log lines (#226)

### Bug Fixes
- **[#226] Duplicate log lines**: `setup_logging()` attached a `console_handler` (`StreamHandler(sys.stdout)`) and a `file_handler` (`RotatingFileHandler`) to the root logger. When started as a background subprocess by `agent_manager.start()`, `sys.stdout` is already redirected to `agent.log`, so every log record was written to the file twice. Fix: wrap `console_handler` attachment with `if sys.stdout.isatty()` — interactive runs get both handlers; background subprocess gets only the file handler.

---

## Session: 2026-04-12 (Part C) — Fix qwen3-32b tool_use_failed (#223)

### Bug Fixes
- **[#223] qwen3-32b `tool_use_failed` on Groq**: `qwen/qwen3-32b` was failing every LLM cycle with a 400 error (`failed_generation: ''`), always falling back to llama. Root cause: qwen3's thinking mode generates `<think>` content before the tool call JSON, breaking Groq's function-call parser. Fix: pass `extra_body={"reasoning_effort": "none"}` (correct Groq parameter) in `_call_openai_compat()` when `disable_thinking=True` and model contains `qwen3`. The llama fallback is unaffected. Previous Anthropic-style `extra_body={"thinking": ...}` (#177) was not tried again as it caused 400 for all models (#216).

### Chores
- Deleted temp diagnostic scripts `scripts/_diag_log.py` and `scripts/_trace_handlers.py` (created during session_2026_04_12b investigation).

### Tests
- Updated `tests/test_trading_agent.py`: replaced stale "no extra_body" assertion with new tests `test_disable_thinking_true_qwen3_passes_reasoning_effort` and `test_disable_thinking_true_llama_no_extra_body`. 8/8 tests pass.

---

## Session: 2026-04-12 (Part B) — Token reduction + LLM logging + observability fixes (#217, #219)

### Features
- **[#219] Structured LLM interaction logging**: every LLM call written as JSON to `/logs/agent-llm-prompts.log` (100 MB × 5 files). Fields: request_id, session_id, timestamp, model, prompts, raw_output, tool_calls, token counts, estimated_cost_usd, latency_ms. `src/utils/llm_logger.py` (new).
- **[#219] Session + request ID tracing**: `session_id` UUID4 generated at agent startup; `request_id` UUID4 per LLM call. Both injected into every `agent.log` line as `[S:xxxxxxxx]` via `_TraceFilter`. `src/utils/timing.py` extended with ContextVars.
- **[#219] kryptos-cli.log CLI audit**: every `kryptos.py` command logged to `/logs/kryptos-cli.log` (100 MB × 5 files) with timestamp, command text, intent, and source.
- **[#219] `storage.log_dir` config key**: log directory now configurable via `config.yaml → storage.log_dir` (default `/logs`). Both agent.log and LLM log read from config.
- **[#219] `agent_manager.init_from_config()`**: fixes pre-existing `_LOG_FILE = None` crash in `start()` and `tail_log()`.
- **scripts/generate_prompt_sample.py** (new): generates `docs/sample_prompt.md` with SYSTEM + CYCLE prompt and token estimates. `--live` reads real DB data; default uses synthetic fixtures.

### Fixes
- **[#217 Step 3] Cycle prompt token reduction (~1,015 tokens)**:
  - HOLD-signal pairs filtered out of per-pair blocks — only BUY + SELL sent to LLM (~18 pairs eliminated per typical cycle)
  - `BB Lower/Upper` and `ATR(14)` lines removed — covered by `reasons` list
  - Tier + Max buy consolidated from 2 lines → 1
  - `--- TAKE-PROFIT TARGETS ---` table removed (28 lines)
  - `patterns`, `position_sizing`, `dynamic_tp` ai_context blocks removed (redundant)
  - Task instructions condensed from 7 to 5 lines
- **Duplicate log lines**: `setup_logging()` now clears existing root logger handlers before adding new ones, preventing double-emit when `logging.basicConfig` had already run
- **CoinGlass 1h failure back-off**: `fetch_cycle_top_indicators` records `failed_at` on 5xx errors; skips retry for 1 hour to suppress repeated `[CYCLE_TOP] Fetch failed` warnings
- **`@timed("config")` noise**: `compute_indicators` changed to `@timed()` — stops logging entire config dict in timing lines

### Files changed
`src/agent/prompts.py`, `src/agent/trading_agent.py`, `src/analysis/features.py`, `src/analysis/indicators.py`, `src/cli/agent_manager.py`, `src/utils/llm_logger.py` (new), `src/utils/timing.py`, `main.py`, `kryptos.py`, `config.yaml`, `tests/test_btc_dominance.py`, `tests/test_cycle_top_guard.py`, `tests/test_entry_slippage.py`, `tests/test_sector_tiers.py`, `tests/test_trading_agent.py`, `tests/test_trailing_stop_label.py`, `scripts/generate_prompt_sample.py` (new)

---

## Session: 2026-04-12 (Part A) — H4 gate analysis: hypothesis disproven (#180)

### Analysis
- **[#180] H4 trend gate hypothesis test**: ran two-pass fast backtest (no LLM) over 2025-10-01 → 2026-04-12 (1,110 baseline trades, 26 pairs). `confirmed_down` entries (EMA9 < EMA21 + MACD histogram < 0) achieved **43.9% win rate** vs **41.4% overall** — 2.5pp above baseline. Applying the gate worsened P&L by −$45.79 and dropped win rate by −2.1pp. Hypothesis NOT supported; issue closed as won't implement.

### Features
- **`scripts/analyse_h4_gate.py`** (new): vectorised two-pass analysis script. Key optimisations: `_precompute_indicators_all()` runs `ta` library once per pair on trimmed candle window (~6 min for 16-month window vs ~147 min per-step); date-based candle trimming; O(n) incremental EMA for H4 state precomputation; `detect_market_regime()` replaces `build_ai_context()` per cycle.

### Documentation
- `README.md`: added H4 gate analysis section with usage examples and last-run verdict.

### Files Changed
- `scripts/analyse_h4_gate.py` (new)
- `README.md`

---

## Session: 2026-04-11 (Part AC) — Cycle-top guard via MVRV Z-Score and NUPL (#205)

### Features
- **[#205] CoinGlass cycle-top guard**: added `fetch_cycle_top_indicators()` in `src/analysis/features.py` to fetch BTC `MVRV Z-Score` and `NUPL`, cache them in-memory, and persist a 24-hour snapshot in `agent_state`.
- **Prompt warning block**: `build_ai_context()` now emits a `[CYCLE TOP WARNING]` block and `src/agent/prompts.py` shows it near the regime section when both thresholds are breached.
- **Tier 3/4 BUY suppression**: `main.py` now converts Tier 3 and Tier 4 raw BUY signals to HOLD before the LLM acts when the macro cycle-top guard is active.
- **Risk-manager enforcement**: `RiskManager.validate_buy()` now hard-blocks Tier 3 / Tier 4 buys during active cycle-top conditions, even if the LLM still attempts one.
- **Telegram alerts**: `Notifier` now sends activation/deactivation alerts for the cycle-top guard.
- **Skill update**: `trading-rules` now documents the hard-blocked cycle-top behavior.

### Tests
- Added `tests/test_cycle_top_guard.py` covering CoinGlass parsing/cache, prompt warning output, signal suppression, and risk-manager enforcement.
- Re-ran `tests/test_btc_dominance.py`, `tests/test_sector_tiers.py`, and `tests/test_regime_and_dynamic_tp.py` to validate adjacent regime logic.

### Files Changed
- `src/analysis/features.py`
- `src/risk/risk_manager.py`
- `src/agent/prompts.py`
- `src/notifications/notifier.py`
- `main.py`
- `.claude/skills/trading-rules/SKILL.md`
- `tests/test_cycle_top_guard.py`

---

## Session: 2026-04-11 (Part AA) — Sector rotation tier caps in rising BTC dominance (#203)

### Features
- **[#203] Runtime pair-tier sizing**: added `compute_pair_regime_caps()` in `src/analysis/features.py` to turn configured `pair_tier` values into per-pair regime caps.
- **Bearish + rising BTC dominance overlay**: `main.py` now applies additional multipliers on top of `caution_factor_bearish`:
  - Tier 3 speculative alts → `0.5×`
  - Tier 4 meme pairs → `0.3×`
  - non-core Tier 2 alts → `0.7×`
  - BTC / ETH / BNB unaffected
- **Prompt visibility**: `src/agent/prompts.py` now shows `Tier: N (label)` in each pair block.
- **Tool-side enforcement**: `src/agent/tools.py` + `src/agent/trading_agent.py` now enforce `pair_max_usd` before `validate_buy()` so the cap is not prompt-only.
- **Skill updates**: `add-pair` now includes `pair_tier`; `trading-rules` documents the concrete tiered dominance overlay.

### Tests
- Added `tests/test_sector_tiers.py` — cap math, prompt tier display, and tool cap enforcement.
- Re-ran `tests/test_regime_and_dynamic_tp.py` to confirm no regression in related regime/prompt flow.

### Files Changed
- `src/analysis/features.py`
- `main.py`
- `src/agent/prompts.py`
- `src/agent/tools.py`
- `src/agent/trading_agent.py`
- `.claude/skills/add-pair/SKILL.md`
- `.claude/skills/trading-rules/SKILL.md`
- `tests/test_sector_tiers.py`

---

## Session: 2026-04-11 (Part AB) — Resolve PR #214 merge conflicts

### Chore
- Merged `origin/main` into `feature/203` and resolved documentation/session-note conflicts caused by overlapping same-day entries from #203 and the already-merged #206/#212 work.
- Preserved the existing `main` branch history for Parts `X`, `Y`, and `Z`, and moved the #203 session note to `session_2026_04_11aa.md` to avoid a duplicate `Part Y`.
- Re-ran targeted regression coverage for BTC-dominance context and sector-tier sizing after the merge.

### Files Changed
- `CHANGELOG.md`
- `CLAUDE.md`
- `docs/sessions/session_2026_04_11aa.md`
- `docs/sessions/session_2026_04_11ab.md`
- `docs/sessions/session_2026_04_11y.md`

---

## Session: 2026-04-11 (Part Z) — Resolve PR #210 merge conflicts

### Chore
- Merged `origin/main` into `feature/206` and resolved conflicts caused by overlapping #204, #206, and #212 documentation/config changes.
- Renamed the BTC-dominance session note from Part `X` to Part `Y` because `main` had already taken Part `X` for the later docs-only skill sync.
- Aligned `fetch_btc_dominance()` with the merged nested `regime.btc_dominance.fetch_timeout_secs` config.

### Files Changed
- `config.yaml`
- `src/analysis/features.py`
- `CLAUDE.md`
- `CHANGELOG.md`
- `docs/sessions/session_2026_04_11x.md`
- `docs/sessions/session_2026_04_11y.md`
- `docs/sessions/session_2026_04_11z.md`

---

## Session: 2026-04-11 (Part Y) — BTC dominance trend macro input (#206)

### Features
- **[#206] BTC dominance trend fetch**: Added `fetch_btc_dominance(config, db_path=None)` in `src/analysis/features.py` using CoinGecko `/api/v3/global` with in-memory TTL caching.
- **DB-backed trend calculation**: Daily dominance values are persisted in `agent_state` as `btc_dom_YYYY-MM-DD`; trend compares current value vs `trend_lookback_days` ago and classifies `rising/falling/flat` using `trend_min_change_pp`.
- **Regime context enrichment**: `detect_market_regime(..., btc_dominance=...)` now appends dominance interpretation to regime summary and returns `btc_dominance_trend` + `btc_dominance_pct`.
- **AI context propagation**: `build_ai_context(..., btc_dominance=...)` forwards dominance fields to the cycle prompt context.
- **Main loop integration**: `main.py` fetches BTC dominance once per cycle (skipped in backtest) and passes it into AI context.

### Tests
- Added `tests/test_btc_dominance.py` with **15 test cases**:
  - fetch structure + failure handling
  - trend classification (rising/falling/flat)
  - cache behavior
  - regime payload and summary augmentation
  - AI context propagation
- Result: **15/15 passing**.

### Files Changed
- `config.yaml` — new `regime.btc_dominance` block (`enabled`, `url`, `cache_minutes`, `trend_min_change_pp`, `trend_lookback_days`)
- `src/analysis/features.py` — `fetch_btc_dominance` + regime/context integration
- `main.py` — per-cycle dominance fetch and `build_ai_context` wiring
- `tests/test_btc_dominance.py` — new test suite
- `CLAUDE.md` — session and gotchas updated

---

## Session: 2026-04-11 (Part X) — Skill docs synced with #204 and #206 (#212)

### Docs
- Updated `.claude/skills/add-pair/SKILL.md` to include `slippage_pct` in the new-pair template and added tier-based guidance for selecting the value after #204.
- Updated `.claude/skills/trading-rules/SKILL.md` to document the BTC dominance macro overlay introduced by #206 and its effect on altcoin risk appetite.
- Corrected the touched field-count/checklist text in `add-pair` so the onboarding workflow stays internally consistent.

### Files Changed
- `.claude/skills/add-pair/SKILL.md`
- `.claude/skills/trading-rules/SKILL.md`
- `docs/sessions/session_2026_04_11x.md`
- `CLAUDE.md`

---

## Session: 2026-04-11 (Part W) — Tiered per-pair slippage in paper broker (#204)

### Features
- **[#204] Per-pair tiered slippage**: `PaperBroker._get_pair_slippage(pair)` resolves slippage from `trading.pairs[].slippage_pct` config field, falling back to global `slippage_pct`. Applied on both entry (`place_order`) and exit (`close_position`).
- **Tier structure**: Tier 1 (BTC) 0.05% · Tier 2 (ETH/BNB/SOL/XRP/ADA/LTC/AVAX) 0.05–0.10% · Tier 3 (speculative alts) 0.20% · Tier 4 (meme/micro) 0.40%. BONK/WIF round-trip friction (0.8%) is 8× that of BTC (0.1%).
- **`pair_tier` field**: added to all 27 pairs in config — also pre-wires sector rotation logic for #203.
- **Config additions**: `regime.btc_dominance` sub-block (for #206), `regime.*_dominance_rising_multiplier` keys (for #203), `risk.cycle_top_guard` block (for #205).
- **9 new tests** in `tests/test_entry_slippage.py` — `TestPerPairSlippage` class covering all 4 tiers, global fallback, fill price accuracy on entry/exit, and round-trip cost comparison.

### Files Changed
- `config.yaml` — `slippage_pct` + `pair_tier` added to all 27 pairs; `regime.btc_dominance` sub-block; `regime.*_dominance_rising_multiplier` keys; `risk.cycle_top_guard` block
- `src/exchange/paper_broker.py` — `_get_pair_slippage()` helper; `place_order()` + `close_position()` use per-pair slippage
- `tests/test_entry_slippage.py` — `_make_broker_with_pair_cfg()` helper + `TestPerPairSlippage` (9 tests)

---

## Session: 2026-04-11 (Part S) — Add PENDLE/USD, ONDO/USD, BONK/USD (#186–#188)

### Features
- **[#186] Add PENDLE/USD** (TP 20%, `buy_min_score=7`, `caution_factor_bearish=0.40`): DeFi yield protocol with expiry-driven BB squeeze breakouts. Added to `eth_ecosystem` correlation cluster. Trailing stop 7%/5%.
- **[#187] Add ONDO/USD** (TP 16%, `buy_min_score=6`, `caution_factor_bearish=0.50`): RWA tokenisation; TradFi institutional narrative; steady trending profile. Unclustered. Standard trailing 5%/3%.
- **[#188] Add BONK/USD** (TP 25%, `buy_min_score=9`, `caution_factor_bearish=0.20`): Extreme Solana meme; maximum-gate entry; BB squeeze release expected to fire reliably before breakouts. Added to `memecoins` cluster. Trailing stop 7%/5%.
- **TP whitelist extended**: `ALLOWED_TAKE_PROFIT_PCTS` now includes 25% (required for BONK).
- **27 active pairs**: up from 24 (28 configured including disabled RAILS/USD).

### Files Changed
- `config.yaml` — 3 new pair blocks; `allowed_take_profit_pcts` includes 25; `memecoins` cluster + BONK; `eth_ecosystem` cluster + PENDLE; trailing stop overrides for PENDLE/BONK
- `src/risk/risk_manager.py` — `ALLOWED_TAKE_PROFIT_PCTS` includes 25
- `tests/backtest/loader.py` — `PAIR_FILE_MAP` entries for PENDLE/ONDO/BONK
- `src/agent/tools.py` — `propose_buy` docstring pair list updated
- `src/cli/display.py` — welcome banner updated
- `src/cli/nl_parser.py` — `PAIRS` list and `_SYSTEM_PROMPT` updated
- `.claude/skills/trading-rules/SKILL.md` — pair count 24→27; caution/score summaries updated
- `docs/business_requirements.md` — v2.2 entry; scope; FR-01; FR-25 (TP levels); pair table
- `docs/epics_stories_ac.md` — 24 pairs → 27 pairs (3 occurrences)
- `CLAUDE.md` — pairs table rows; session entry
- `history/PENDLEUSD_candle.json`, `ONDOUSD_candle.json`, `BONKUSD_candle.json` — 721 candles each

---

## Session: 2026-04-11 (Part R) — Candlestick pattern signals (#184)

### Feature
- **[#184] Candlestick pattern signals — hammer +1, bullish engulfing +2, doji at BB lower +1**:
  - `detect_candlestick_patterns(opens, highs, lows, closes, atr)` added to `src/analysis/indicators.py`. Returns `{"hammer", "bullish_engulfing", "doji_at_support"}`.
  - Hammer: lower_wick > 2×body AND upper_wick < 0.3×body AND bullish close.
  - Bullish engulfing: current body engulfs prior bearish body.
  - Doji: body < 10% of ATR (scale-agnostic). Scores only when `near_lower` is True in signals.py.
  - Called in `compute_indicators()`; result returned as `"candlestick_patterns"` in indicators dict.
  - `signals.py` reads weights from config and adds score/reason for each detected pattern.
  - `config.yaml`: `hammer_weight: 1`, `engulfing_weight: 2`, `doji_support_weight: 1`. `max_score: 25 → 28`.

### Files Changed
- `src/analysis/indicators.py` — `detect_candlestick_patterns()` function; wired into `compute_indicators()`
- `src/analysis/signals.py` — weights, BUY scoring block, score table comment updated; unused import removed
- `config.yaml` — 3 pattern weights added; `max_score` updated to 28
- `tests/test_candlestick_patterns.py` — 7 new tests (5 unit + 2 integration)

### Tests
- 209 tests, all passing (was 202 before this session).

---


### Fix
- **[#178] `_get_or_set_sod_balance` generalised to paper + live mode**: Previously only called for `mode == "paper"`. Live mode relied on a stale in-memory SOD balance set once at startup, ignoring midnight UTC rollovers and `reset_paper.py` invocations.
- **`agent_state` table codified in schemas**: Added `CREATE TABLE IF NOT EXISTS agent_state` DDL to both `PAPER_SCHEMA` and `LIVE_SCHEMA` in `src/storage/database.py`. Added idempotent migrations to `init_paper_db()` and `init_live_db()`. Previously the table only existed in the production paper DB from a prior ad-hoc migration.
- **SOD block condition** in `main.py` changed from `if mode == "paper" and not is_backtest:` → `if not is_backtest:` with inner `if/else` selecting `paper_trading.db` vs `live_trading.db`.
- **9 new tests** in `tests/test_sod_balance.py`: schema creation, idempotency, live-mode first-write, same-day stability, midnight UTC rollover, DB fallback, paper-mode regression.

### Files Changed
- `src/storage/database.py` — `agent_state` DDL added to `PAPER_SCHEMA`, `LIVE_SCHEMA`, and both migration lists
- `main.py` — `_get_or_set_sod_balance(paper_db, ...)` → `db_path`, docstring updated, SOD block extended to live mode
- `tests/test_sod_balance.py` — 9 new tests

### Tests
- 199 tests, all passing (was 190 before this session).

---

## Session: 2026-04-11 (Part N) — Clarify reset_paper.py output label (#175)

### Chore
- **[#175] rename `Current state:` → `State before reset:` in `scripts/reset_paper.py`**: The pre-reset row-count snapshot was labelled `Current state:`, causing confusion — readers thought non-zero counts were post-reset residuals. Rename makes it clear the block shows what *will* be wiped, not what remains.

---

## Session: 2026-04-11 (Part K) — Commit skill: branch + PR workflow (#168)

### Chore
- **[#168] commit skill enforces feature/defect branch + pull request**:
  - New Step 1: always create `feature/<N>` or `defect/<N>` branch from up-to-date `main` before any commit work. Never commit directly to `main`.
  - Step 10: push uses `git push -u origin feature/<N>` (branch, not main).
  - New Step 11: `gh pr create --base main --head feature/<N> --body "Closes #<N>"` to open PR.
  - Step 12: confirm reports commit hash, branch name, and PR URL.
  - All existing steps renumbered 2–12 accordingly.

---

## Session: 2026-04-11 (Part J) — Cash guards as primary gate, count ceiling raised to 10 (#167)

### Bug Fix
- **[#167] `max_open_positions` count gate replaced with cash-first architecture**:
  The #165 soft-gate was correct in direction but wrong in architecture. The count gate was
  still primary; cash guards were secondary. With `caution_factor_bearish` reducing positions
  to $35–$70 each, 5 slots exhausted at ~$376 leaving $624 stranded.

  **`config.yaml`**: `max_open_positions: 5` → `10`. At $20 min-order, 10 slots on a $1,000
  portfolio equates to $200 total investment — cash depletes before count ceiling is reached.
  Comment updated to explain it is a safety net only.

  **`src/risk/risk_manager.py` `validate_buy()` guard reorder**: moved "min cash reserve" and
  "Guard 0.5 deployable < min_order_usd" to run **before** the count ceiling. Removed the #165
  dual-condition soft peek; count gate is now a simple hard block at 10. New guard order:
  cash reserve → deployable → count ceiling (10) → cluster guard → size checks.

  **`src/risk/risk_manager.py` `validate_config()` sanity warning**: formula updated from
  `base_position_pct` (in `position_sizing`) to `max_position_pct` (in `trading`), consistent
  with the sizing parameter used in `main.py`.

  **Tests**: 3 tests updated/added — blocked-when-no-cash now asserts Guard 0.5 reason;
  allowed-when-cash uses `max_open_positions=10`; new `test_max_open_positions_ceiling_hard_blocks_at_10`.

  **All 183 tests pass.**

---

## Session: 2026-04-11 (Part I) — Fix position gate to use remaining cash (#165)

### Bug Fix
- **[#165] `max_open_positions` count cap now cash-aware**: When caution_factor shrinks individual
  positions (e.g. SUI at $35, JUP at $70), 5 slots could be exhausted with only ~$400 deployed,
  leaving $594 idle and all further buys blocked by a pure count check.

  **`main.py`**: `max_per_trade` now computed as `cash_usd × max_position_pct` (was `total_usd × ...`).
  LLM prompt shows ceiling proportional to remaining cash.

  **`src/risk/risk_manager.py` `validate_buy()` step 2**: count gate only fires when
  `count >= max_open_positions` **AND** `deployable_cash < min_order_usd`. When cash is
  available, execution falls through to existing cash guards (min reserve check, guard 0.5,
  step 5 tradable cap), which are the correct gatekeepers.

  **`tests/test_risk_manager.py`**: 2 new tests — blocked-when-no-cash, allowed-when-cash-available.
  182 tests pass.

---

## Session: 2026-04-11 (Part H) — Add reset_paper.py utility script (#163)

### New Script
- **[#163] `scripts/reset_paper.py`**: Resets `paper_trading.db` (wallet, positions, trades, agent_state) and `audit.db` (all `mode='paper'` rows, FK-safe deletion order) to a clean slate. Re-seeds wallet with configurable `--balance` (default $1,000). Prints current state before acting, shows interactive `[y/N]` confirmation unless `--yes` passed, verifies clean state with assertions after reset.

---

## Session: 2026-04-11 (Part G) — add-pair skill: trailing_stop + correlation_clusters steps (#162)

### Chore / Docs
- **[#162] add-pair skill updated**: Added two missing step-5 sub-items to `.claude/skills/add-pair/SKILL.md`:
  - **5(i) `trailing_stop.per_pair_overrides`**: volatility-tier table (standard / high-vol L1 / meme / extreme meme) with trail_pct / activate_after_pct values. Standard pairs (BTC/ETH/XRP/ADA) need no override entry; high-vol L1 = 6%/4%; meme = 7%/5%; extreme meme = 8%/6%.
  - **5(j) `risk.correlation_clusters`**: current cluster table (6 clusters), decision rules (add-to-existing / create-new / leave-unclustered), YAML snippets for both cases.
  - Checklist: two new items added.
- **[#160] Closed**: `correlation_clusters` config fix was already committed in b8dbf4c (session_2026_04_11f). Issue closed retroactively with cross-reference to skill update.

---

## Session: 2026-04-11 (Part D) — Entry slippage, dynamic prompt max_buys (#140, #144)

### Bugs Fixed
- **[#140] Entry slippage added to place_order()**: `fill_price = round(current_price * (1 + self._slippage), 8)`. Reuses existing exit slippage field (0.05%). Round-trip friction model is now symmetric: entry slippage (0.05%) + entry fee (0.26%) + exit slippage (0.05%) + exit fee (0.26%) ≈ 0.62% per trade. SL/TP are anchored to the slipped fill_price.
- **[#144] LLM prompt "TOP 3" → dynamic `max_buys_per_cycle`**: `build_cycle_prompt()` now accepts `max_buys_per_cycle: int` param (default 7); `TradingAgent.run_cycle()` passes `self._max_buys`. Prompt reads `f"top {max_buys_per_cycle} picks"` — stays in sync with config automatically. Fixed stale module docstring "default: 2" → "default: 7".

### Tests
- `tests/test_entry_slippage.py` — 3 new tests: fill_price slippage, SL/TP anchoring, zero-slippage case

### Files
- `src/exchange/paper_broker.py` — `place_order()` entry slippage
- `src/agent/prompts.py` — `build_cycle_prompt()` new param, dynamic text
- `src/agent/trading_agent.py` — pass `max_buys_per_cycle=self._max_buys`
- `config.yaml` — updated `slippage_pct` comment
- `tests/test_entry_slippage.py` — new file

---

## Session: 2026-04-11 (Part C) — Adaptive lookback, partial TP, correlation guard, graduated CB (#139, #141, #142, #143)

### Features Added
- **[#139] Correlation cluster guard**: `validate_buy()` Guard 2a — if pair belongs to a cluster (large_cap_l1/memecoins/alt_l1/payment_legacy) and ≥ 2 positions in that cluster are already open, BUY rejected. If 1 open in cluster, position size penalised 50% (`cluster_size_penalty`). Config: `risk.correlation_clusters`, `max_cluster_positions: 2`, `cluster_size_penalty: 0.5`.
- **[#143] Graduated circuit breaker**: Replaces flat 4h pause with exponential backoff — 1st fire → 1h, 2nd → 2h, 3rd+ → 4h. Fire count derived from 24h trade history via `_count_circuit_fires_in_window()`. Backward compat: `pause_hours` still accepted as flat override. Config: `pause_tiers_hours: [1, 2, 4]`, `tier_reset_hours: 24`.

### Config Changes
- **[#141]** `adaptive_atr_floor_lookback: 400 → 200` for all 14 pairs and 3 global defaults (`adaptive_atr_floor`, `adaptive_bb_squeeze`, `adaptive_volume_floor`). 200 candles = 50h — responsive to regime shifts within 2 trading days.
- **[#142]** `partial_take_profit.enabled: false → true` — now active in production.

### Bugs Fixed
- **[#143]** `is_circuit_open()` used `self._cb_pause_secs` (max tier = 4h) for `resume_in` instead of the tier-appropriate `pause_secs`. This caused all tiers to always report 4h pause duration regardless of tier.

### Files
- `config.yaml`
- `src/risk/risk_manager.py` — new helpers `_count_circuit_fires_in_window`, `_get_correlation_cluster`, `_get_open_pairs`; `is_circuit_open()` graduated logic; `validate_buy()` Guard 2a
- `tests/test_circuit_breaker.py` — 3 new graduated tests
- `tests/test_correlation_guard.py` — new file, 3 tests

---



### Bugs Fixed
- **[#138] Asymmetric early-sell trap**: On a TP=12% pair, the 80% guard prevented the LLM from selling until +9.6% while SL fires at -5% — a 14.6% swing from peak. Reduced to 60%: early sell now allowed at ≥7.2% on a 12% TP pair, ≥12% on a 20% TP pair.

### Config
- `trading.early_sell_min_tp_proximity_pct`: `80` → `60`

### Files
- `config.yaml`
- `.claude/skills/trading-rules/SKILL.md` — updated guard examples
- `tests/test_risk_manager.py` — renamed tests, updated boundary price
- `tests/test_per_pair_params.py` — fixture updated

---

## Session: 2026-04-10 (Part C) — Fix stale total value in balance report (#133)

### Bugs Fixed
- **[#133] Total value showed stale audit snapshot**: `get_portfolio_summary()` read `total_usd` from `audit_balance_snapshots` (only updated during trading cycles). After a DB reset, this returned the old value while `Available` correctly showed the live wallet. Fixed: paper mode now computes `total_usd = cash + sum(open position usd_values)` live. Live mode still uses the snapshot (Kraken cash is external).

### Files
- `src/reports/trade_report.py` — live paper total_usd computation

---

## Session: 2026-04-10 (Part B) — Disable RAILS/USD + clean slate reset (#132)

### Changed
- **[#132] RAILS/USD disabled**: Commented out pair block and trailing stop override in `config.yaml`. 25% live win rate, 3/4 stop losses, net -$10.25 over 4 trades. Re-enable by uncommenting config block.
- **Paper trading reset**: Cleared all positions, trades, and wallet; fresh $1,000 cash balance inserted.

### Files
- `config.yaml` — RAILS pair block and trailing stop override commented out

---

## Session: 2026-04-10 (Part A) — RAILS over-trading fix + unambiguous propose_sell gate (#131)

### Bugs Fixed
- **[#131] RAILS buy_min_score raised to 7**: Was defaulting to global 5 despite 3/4 stop-loss rate in production (~40% price decline since entries). `config.yaml` now explicitly sets `buy_min_score: 7` for RAILS — same bar as INJ.
- **[#131] RAILS caution_factor_bearish 0.40 → 0.25**: Halves max position size in bearish regime (~$49 vs $78 on $1,000 portfolio). RAILS contributed -$21.18 in 3 stop losses overnight.
- **[#131] propose_sell prompt ambiguity**: `SKILL.md` conditions (a) and (b) were disjunctive — LLM could infer a sell at 1% P&L when Signal=SELL fired. Replaced with a single unified gate requiring ALL three conditions: 80% TP proximity (code-enforced), confirmed SELL signal, P&L above floor.
- **SKILL.md missing frontmatter**: Added `name: trading-rules` YAML frontmatter block to fix IDE diagnostic error.

### Changed
- `config.yaml` — RAILS `caution_factor_bearish: 0.25`, `buy_min_score: 7`
- `.claude/skills/trading-rules/SKILL.md` — unified propose_sell gate, updated per-pair threshold docs, added frontmatter

---

## Session: 2026-04-09 (Part G) — trailing_stop reporting, min_order_usd $20, force_close_all, overdraw guard

### Features / Fixes
- **[#125] trailing_stop in Exit Reasons panel**: `print_performance_metrics()` now shows count **and** total P&L (green/red) per exit reason. `trade_report.py` adds `exit_reason_pnl` dict alongside `exit_reason_counts`. `docs/how_to_debug.md` updated with `trailing_stop`, `partial_take_profit`, and `backtest_end` in the exit reason table.
- **[#126] min_order_usd raised to $20**: `config.yaml` updated. Guard 0.5 added to `validate_buy()` in `risk_manager.py` — if deployable cash < $20, rejects immediately with `[RISK] Skipping BUY {pair} — deployable cash $X below min_order_usd $Y`. Hardcoded `capped < 5.0` replaced by `capped < self._min_order_usd`. 3 new tests.
- **[#127] Force mark-to-market close at backtest end**: `PaperBroker.force_close_all(prices)` added. Called by `tests/test_backtest.py` after `run_agent()` completes — closes all remaining open positions with `exit_reason='backtest_end'` at the last candle price and prints forced-close count + P&L.
- **[#129] Overdraw guard in place_order()**: `PaperBroker.place_order()` now checks `new_cash >= 0` before writing to DB. Raises `ValueError("Insufficient funds: ...")` and logs `[PAPER] OVERDRAW BLOCKED`. 2 new tests.

### Changed
- `config.yaml` — `min_order_usd: 5.0` → `20.0`
- `src/exchange/paper_broker.py` — overdraw guard + `force_close_all()`
- `src/risk/risk_manager.py` — Guard 0.5 (deployable cash check) + `capped < self._min_order_usd`
- `src/reports/trade_report.py` — `_sum_pnl_by_field()` helper + `exit_reason_pnl` in summary
- `src/cli/display.py` — Exit Reasons panel shows P&L per reason
- `tests/test_backtest.py` — `force_close_all` call + summary print
- `tests/test_risk_manager.py` — 5 new tests (135 → 140 total)
- `docs/how_to_debug.md` — exit_reason table expanded

---

## Session: 2026-04-09 (Part E) — Trailing Stop Label Fix (#123)

### Bug Fixed
- **[#123] Trailing stop exits mislabelled as `stop_loss`**: `check_stops_and_tp()` always emitted `exit_reason = "stop_loss"` when price hit the SL level, even when the trailing stop had raised the SL above the hard floor (i.e., the exit was profitable). This inflated the apparent loss rate and could incorrectly trip the circuit breaker.

### Changed
- **`src/exchange/paper_broker.py`**: When trailing stop is enabled and `stop_loss_price > entry_price × (1 - sl_pct/100) + ε`, emit `exit_reason = "trailing_stop"`. Hard floor hits remain `"stop_loss"`. Updated `audit_logger.log_position_event()` to emit `"trailing_stop_triggered"` event type.
- **`src/exchange/kraken_client.py`**: Same logic applied to both native Kraken order detection and price-based fallback paths.
- **`src/risk/risk_manager.py`**: `is_circuit_open()` and `record_stop_loss()` now exclude `"trailing_stop"` from consecutive-stop counts — only `"stop_loss"` and `"fallback_stop_loss"` count as hard losses.
- **`tests/test_trailing_stop_label.py`**: 6 new tests (94 total passing).

---

## Session: 2026-04-09 (Part D) — Backtest Clean-Slate Teardown Fix (#122)

### Bug Fixed
- **[#122] Stale DB contamination in backtest**: `test_backtest.py` teardown used a manually constructed `data_dir` path that could diverge from `database.py`'s `get_connection()` path. Also had no post-teardown validation — contaminated state could silently proceed.

### Changed
- **`src/storage/database.py`**: Added `get_db_path()` public alias for `_get_db_path()`.
- **`tests/test_backtest.py`**:
  - Teardown now uses `get_db_path()` — same resolution as `get_connection()`.
  - After deletion, explicitly re-inits paper and audit DBs.
  - Asserts 0 open positions and `cash == starting_balance` before feed starts; aborts on contamination.
  - Logs `Validated: 0 open positions, wallet=$X.XX` at startup.

---

## Session: 2026-04-09 (Part C) — Disable Time-of-Day Guard

### Changed
- **[#121] `config.yaml`**: `allowed_trading_hours.enabled: false` — time-of-day guard disabled; agent now trades at any hour.
- **[#121] `.claude/skills/trading-rules/SKILL.md`**: Updated Volume & Time-of-Day Guard rule to reflect disabled state.
- **[#121] `.claude/memory/project_kryptos.md`**: Trading Hours section updated.

Note: Volume dead zone check (`min_volume_ratio` / `rolling_volume_p15`) remains always-on in `signals.py` Hard Blocker 3.

---

## Session: 2026-04-09 (Part B) — Adaptive Injections, MACD Normalisation, 90% Capital, Signal Drivers

### Fixed
- **[#108] `main.py` + `config.yaml`**: Adaptive ATR floor — rolling p25 ATR% × 0.8 injected as `adaptive_atr_floor_pct` per cycle. Config: `adaptive_atr_floor.{enabled, scaling_factor: 0.8, min_cap_pct: 0.10, lookback_candles: 400}`.
- **[#112] `src/analysis/features.py` + `config.yaml`**: MACD decay threshold normalised — `macd_decay_threshold_pct: -0.005` (% of price) replaces absolute `-0.0005`. Fires consistently regardless of pair price scale.
- **[#115] `src/exchange/paper_broker.py`**: `hold_secs` in backtest computed from candle `timestamp_override`, not wall clock `now_sgt()`.

### Added
- **[#113] `main.py` + `config.yaml`**: Adaptive BB squeeze — rolling p10 BB width% injected as `_rolling_bb_p10_pct` per cycle. Config: `adaptive_bb_squeeze.{enabled, lookback_candles: 400, percentile: 10}`.
- **[#114] `main.py` + `config.yaml`**: Adaptive volume floor — rolling p15 raw volume injected as `rolling_volume_p15` per cycle. Config: `adaptive_volume_floor.{enabled, lookback_candles: 400, percentile: 15}`.
- **[#116] `config.yaml`**: Position cap removed — `max_open_positions: 13`, `max_position_pct: 15%`, `max_buys_per_cycle: 5`. Up to 90% capital deployment with 10% cash floor.
- **[#117] `src/reports/trade_report.py` + `src/cli/commands.py` + `src/cli/display.py` + `kryptos.py`**: Signal driver report. `kryptos.py drivers [--days 30] [--top 10]` shows top blockers/drivers per pair.
- **[#118] `scripts/calibrate_params.py`**: Parameter calibration utility. Analyses historical candles and outputs recommended config YAML changes for all 5 per-pair signal parameters.

### Tests
- `tests/test_adaptive_atr_floor.py`: 7 tests for adaptive ATR floor computation and signal integration.
- `tests/test_candle_timestamps.py`: 3 tests verifying candle timestamps in opened_at, closed_at, hold_secs.

---

## Session: 2026-04-09 (Part A) — Per-Pair Signal Parameters, Backtest Hours Fix, Analysis Scripts

### Fixed
- **[#106] `tests/test_backtest.py`**: Backtest now forces `allowed_trading_hours.enabled=False` — previously the 1-hour trading window caused only ~84 LLM calls per 2,016-candle backtest (96% suppression).
- **[#107] `config.yaml` + `src/analysis/signals.py`**: Per-pair `atr_tp_min_pct` replaces broken global 1.0% floor. Global floor was blocking 93–99.8% of all signals with zero selectivity. Per-pair values (BTC=0.14%, TRX=0.12%, INJ=0.34%) derived from p25 ATR% × 0.8 with min cap.
- **[#109] `config.yaml` + `src/analysis/signals.py`**: Per-pair `rsi_oversold` (BNB/XRP/LTC→28, TRX→35) and `rsi_overbought` (TRX→65, XRP/DOGE/ADA/LTC/SUI/INJ→72) — calibrated so each pair fires oversold/overbought ~5–8% of candles.
- **[#110] `config.yaml` + `src/analysis/features.py`**: Per-pair `bb_squeeze_threshold_pct` (BTC=0.7%, INJ=2.5%) — global 1.0% was incorrectly declaring SOL/SUI/UNI/INJ in squeeze most of the time, clamping dynamic TP to minimum.
- **[#111] `config.yaml` + `src/analysis/signals.py`**: Per-pair `min_volume_ratio` — BNB/UNI/INJ→0.30 (dead zone was blocking 57–58% of candles at global 0.50).

### Added
- **`scripts/analyse_atr_profile.py`**: ATR% distribution per pair from historical candles.
- **`scripts/analyse_pair_params.py`**: Full statistical analysis of RSI, MACD, BB, volume per pair.
- **`scripts/analyse_rolling_windows.py`**: Rolling-window stability (CV) + buy/sell signal win rate analysis.
- **`docs/plan_per_pair_params.md`**: Full plan for all 12 parameter changes with data-derived recommendations.
- **`tests/test_per_pair_params.py`**: 20 new tests covering per-pair ATR floor, RSI, BB squeeze, volume ratio, and adaptive injection overrides.
- **GitHub issues #107–#118**: All 12 planned changes documented with What/Why/How.

### Infra
- `adaptive_atr_floor_lookback: 400` added per-pair in config — placeholder for future adaptive floor injection from `main.py` (Fix #108, pending).
- ATR floor priority chain documented: injected adaptive → per-pair static → global fallback → min_profit_floor.

---

## Session: 2026-04-08 (Part C) — Trailing Stop Tuning, ATR Floor, BB Squeeze TP, Trading Hours

### Fixed
- **[#102] `config.yaml` + `paper_broker.py` + `kraken_client.py`**: Trailing stop `trail_pct` 3→5%, `activate_after_pct` 1.5→3.0%. Per-pair overrides now support dict `{trail_pct, activate_after_pct}`: DOGE/RAILS/HYPE 7%/5.0%, SUI 6%/4.0%. Prevents SOL/AVAX-style near-breakeven exits from 2% consolidations.
- **[#103] `config.yaml`**: `atr_tp_min_pct` 0.3→1.0% — blocks entries in compressed markets where ATR% is too small to justify 5% SL risk (root cause of DOGE/UNI/INJ full -5.29% SL hits).
- **[#104] `src/analysis/features.py:compute_dynamic_tp()`**: Implemented BB squeeze guard — when BB width < `squeeze_threshold_pct` (1.0%), TP clamps to pair floor. `bb_width_scale: true` config was previously a no-op.
- **[#95] `src/analysis/features.py:compute_dynamic_tp()`**: Dynamic TP now uses `max(global_min, pair_static_tp)` as floor — DOGE/RAILS/HYPE no longer get 5% TP in low-ATR conditions.
- **[#105] `config.yaml`**: Trading window narrowed to 03:00–04:00 SGT (19:00–19:59 UTC, 1 hour) for focused testing.
- **59 tests pass** (1 pre-existing import error unrelated to these changes)

---

## Session: 2026-04-08 (Part B) — Backtest Timestamps, Chart Legend, Charts in Reports

### Fixed
- **`src/exchange/paper_broker.py`** — `place_order()` / `close_position()` accept `timestamp_override: Optional[str]`; new `_ts(override)` helper uses candle timestamp in backtest, wall clock in live — closes #98
- **`src/exchange/historical_feed.py`** — `current_candle_time: int` property exposes the last-advanced candle epoch so `main.py` can pass it into the broker
- **`src/agent/tools.py`** — `propose_buy()` / `propose_sell()` pass candle ISO timestamp to broker as `timestamp_override`
- **`main.py`** — passes `candle_ts=feed.current_candle_time` to `broker.check_stops_and_tp()`

### Added
- **`src/reports/chart_generator.py`** — core charting engine (extracted from `scripts/chart_trades.py`); public API: `generate_charts()`, `render_trade_chart()`; full proxy-artists legend (BUY ▲, TP ▼, SL ▼, SELL ▼, PARTIAL TP ▼, entry/exit price dashes) — closes #99 / #100
- **`scripts/chart_trades.py`** — reduced to thin 54-line wrapper
- **`src/cli/commands.py`** — `cmd_charts()` added; `cmd_daily_report()` / `cmd_review()` accept `charts: bool` flag — closes #100
- **`kryptos.py`** — `charts` subcommand; `--charts` flag on `daily` and `review`; `--pair`, `--out`, `--window` args on `charts`
- **`tests/test_backtest_timestamps.py`** — 6 new tests for timestamp fix
- **`tests/test_chart_generator.py`** — 23 new tests for chart engine
- **Full test suite: 80 tests pass**

---

## Session: 2026-04-07 (Part C) — HistoricalFeed Timestamp-Based Lookup Fix

### Fixed
- **`src/exchange/historical_feed.py`** — complete rewrite to use timestamp-based candle lookup instead of position-based indexing
  - **Root cause:** single global `_position` counter clamped via `min(pos, len-1)` always returned the last candle for shorter pairs (BNB/USD: 24k candles vs BTC/USD: 429k candles). Prices were frozen at the entry value forever — positions never hit SL or TP.
  - **Fix:** `_ref_pair` tracks the pair with the most candles. `_current_ts` is the timestamp of the current reference candle. Each pair uses `bisect.bisect_right` on its sorted timestamp list to find the correct candle for the current cycle.
  - Shorter pairs with no data at `_current_ts` return `None` / `[]` (guarded by `is_ready()` in main loop), so pairs like HYPE/USD with limited history are safely skipped before their data begins.
- All 51 tests pass.

---

## Session: 2026-04-07 (Part B) — Migrate Claude Memory to Project Scope

### Added
- **`.claude/memory/`** directory with 4 files committed to git: `project_kryptos.md`, `feedback_coding_style.md`, `feedback_testing.md`, `feedback_github_traceability.md`
- **`CLAUDE.md`**: added `@.claude/memory/*.md` import directives so all contributors and Claude sessions auto-load the shared context — closes #91

---

## Session: 2026-04-07 (Part A) — Trading Hours Window Fix (SGT)

### Fixed
- **`config.yaml`** `allowed_trading_hours`: corrected to `start_hour_utc: 22` / `end_hour_utc: 20` (06:00–04:00 SGT, cross-midnight UTC window). Previous values (`start: 06`, `end: 23/24`) were left-over from UTC-centric tuning and blocked the 23:00 UTC (07:00 SGT) hour due to exclusive `<` comparison.
- **`.claude/skills/trading-rules/SKILL.md`**: updated Time-of-Day Guard description to show `06:00–04:00 SGT / 22:00–20:00 UTC, cross-midnight`.
- No code changes — the cross-midnight logic (`current_hour >= start OR current_hour < end`) was already in `risk_manager.py`.

---

## Session: 2026-04-06 (Part E) — Partial Take-Profit

### Added
- **`partial_take_profit` config block** (`config.yaml`): enabled flag, trigger_pct_of_tp (50%), close_fraction (0.5), move_sl_to_breakeven
- **`close_position(volume_override)` parameter** (`paper_broker.py`, `kraken_client.py`): partial close reduces volume/usd_value in DB; position stays open; `partial_exited=1` set
- **Step 3 partial TP in `check_stops_and_tp()`** (`paper_broker.py`, `kraken_client.py`): fires when price ≥ entry×(1+tp_pct×trigger_ratio/100); guarded by `partial_exited` flag; optionally moves SL to entry after close
- **`tests/test_partial_tp.py`** (5 tests): fires at trigger, silent before trigger, no double-fire, SL-to-entry after partial, wallet credit check
- Full test suite: **51 tests pass** — closes #87

---

## Session: 2026-04-06 (Part D) — Breakeven Stop Tests

### Added
- **`tests/test_breakeven_stop.py`** (3 tests): SL moves to entry at trigger, no-move before threshold, no re-fire guard — closes #85

---

## Session: 2026-04-06 (Part C) — Signal Coverage & Profit Margin Fixes

### Fixed
- **ATR floor decoupled** (`signals.py`, `config.yaml`): `dynamic_tp.atr_tp_min_pct: 0.3` — BTC/ETH/SOL now pass ATR gate (was blocked by 1% floor)
- **RSI overbought 60→65** (`config.yaml`): Reduces premature SELL signals before TP targets are reached
- **validate_sell() TP proximity guard** (`risk_manager.py`, `config.yaml`): Code-enforces BRD FR-20 — LLM blocked until P&L ≥ 80% of TP target; closes #83
- **5 unit tests** (`tests/test_risk_manager.py`): All proximity guard scenarios covered

---

## Session: 2026-04-06 (Part A) — Backtest Analysis & GitHub Issues Shell Script

### Analysis
- Diagnosed early-sell bug from 3,931-cycle backtest: `validate_sell()` has no upper-side proximity guard → LLM exits at 2–4% despite TP targets of 5–20%
- Root cause: BRD FR-20 (80% TP proximity before early exit) is prompt-only, not code-enforced

### Added
- `scripts/create_github_issues.sh` — comprehensive script creating all 12 epics (E1–E12) and 28 stories as GitHub issues with full AC and traceability to BRD FR-XX, DSD §X.X, NFR-XX, code file::function
- Stories are registered as GitHub sub-issues under their parent epic via `gh api POST /repos/{owner}/{repo}/issues/{num}/sub_issues`
- E12 (new epic) covers: propose_sell proximity guard (bug), trailing stop, breakeven stop, ATR-based SL, partial take-profit

---

## Session: 2026-04-05 (Part F) — Documentation: BRD, Detailed Design, Epics/Stories

### Added

| Artifact | File | Summary |
|---|---|---|
| Business Requirements Document | `docs/business_requirements.md` | 8 FRs, 6 NFRs, bug resolution table, setup guide |
| Detailed Solution Design | `docs/detailed_solution_design.md` | 10 sections, 9 Mermaid diagrams, 7 ADRs, LLM architecture deep-dive, Skills system docs |
| Epics, Stories & AC | `docs/epics_stories_ac.md` | 11 Epics, 40+ Stories with Gherkin AC, traceability matrix |

### Removed
- Deleted `random_execution_kraken.py` — stale exploration prototype
- Deleted `test_ws.py` — stale WebSocket exploration script

---

## Session: 2026-04-05 (Part E) — Global Kill Switch & Backtest Telemetry

### Features Added

| Feature | Files | Notes |
|---|---|---|
| Global Max Daily Loss (Kill Switch) | `config.yaml`, `main.py`, `kraken_client.py` | Protects the portfolio at 7% drawdown; executes a mass limit-cancellation and market-sell out of crypto. |
| Backtesting Lifecycle Refinement | `test_backtest.py` | Native flush of `backtest_paper.db` and log rotations allowing sterile execution runs. |
| Audit Rejection Utility | `scripts/audit_rejections.py` | Extracts telemetry indicating why algorithmic blocks triggered. |

---

## Session: 2026-04-05 (Part B) — Confluence scoring, circuit breaker, heartbeat

### Features Added

| Feature | Files | Notes |
|---|---|---|
| Multi-indicator confluence BUY scoring | `signals.py`, `indicators.py`, `config.yaml` | 10 contributors, min score 5; removed all hard EMA gates |
| MACD histogram turn detection | `indicators.py` | `macd_histogram_prev` added; turn = +3, continuation = +1 |
| Fear & Greed injected into signal scoring | `main.py`, `signals.py` | Fetched once/cycle; +1 fear ≤40, +2 extreme fear ≤25 |
| ATR profit floor veto | `signals.py` | Blocks entry if ATR-based TP < `min_profit_floor_pct` |
| Circuit breaker (DB-backed) | `risk_manager.py`, `config.yaml` | Reads last 3 trades within 4h window; no extra table needed |
| Heartbeat notification | `notifier.py`, `main.py`, `config.yaml` | Hourly Telegram summary in live mode |
| Circuit breaker tests | `tests/test_circuit_breaker.py` | 4 Gherkin-annotated test cases |

### Files Changed

| File | Change |
|---|---|
| `src/analysis/signals.py` | Full rewrite — confluence scoring, two vetoes, helper functions |
| `src/analysis/indicators.py` | Added `macd_histogram_prev`; removed candle-counting reversal detector |
| `src/risk/risk_manager.py` | Circuit breaker reads trade history via SQL time window; `db_path` param |
| `src/notifications/notifier.py` | Added `send_heartbeat()` and `send_circuit_breaker_tripped()` |
| `main.py` | Fear & Greed injection; heartbeat loop; circuit breaker wiring; `run_cycle` returns buy/sell counts |
| `config.yaml` | New signal score weights; circuit breaker block; heartbeat interval |
| `.claude/skills/trading-rules/SKILL.md` | Aligned with confluence scoring and circuit breaker rules |

---

## Session: 2026-04-01 (Part C) — Backtesting pipeline

### Features Added

| Feature | Files | Notes |
|---|---|---|
| Candle data loader | `tests/backtest/loader.py` | Maps 15 pairs to history JSON files; normalises Kraken tick arrays |
| In-memory BacktestBroker | `tests/backtest/broker.py` | PaperBroker equivalent; intra-candle SL/TP using high/low |
| Backtest runner | `tests/backtest/runner.py` | Slides candle window; deterministic signal-following agent |
| Report generator | `tests/backtest/report.py` | P&L, per-pair stats, trade log, Sharpe ratio, balance history |
| Backtest entry point | `tests/test_backtest.py` | `python tests/test_backtest.py`; prints report + bug list |

### Bugs Fixed (in backtest code)

| Bug | Fix |
|---|---|
| `hold_candles` was epoch-seconds delta not candle count | Divide by `15 * 60` to convert to candle count |

### Bugs Identified (production + data)

| # | Bug | Severity |
|---|---|---|
| BUG-1 | `AVAXSD_candle.json` filename missing 'U' | Low |
| BUG-2 | `indicators.py` returns `ema_50` key even when `ema_slow=200` | Low |
| BUG-3 | Kraken OHLC API 720-candle cap — only 7.5 days returned, not 12 months | High |
| BUG-4 | CLAUDE.md INJ/USD TP listed as 16%, config says 20% | Low |
| BUG-5 | SL/TP checked once per 30-min cycle — flash crash risk | Medium |

### Backtest Results (7.5-day window, March 24–April 1, 2026)

| Metric | Value |
|---|---|
| P&L | -$18.33 (-1.83%) |
| Win rate | 63.6% |
| Win/Loss ratio | 0.67x |
| TP hits / SL hits | 0 / 4 |

---

## Session: 2026-04-01 (Part B) — LLM model switch + live broker parity

### Bugs Fixed

| Bug | Root Cause | Fix |
|---|---|---|
| LLM timeout every cycle since midnight | `qwen2.5:14b` runs on CPU (no GPU) — 700–900 s per inference, consuming full 900 s timeout. Fallback `llama3.1:8b` was never installed, producing 404 with no recovery | Switched to `deepseek-r1:7b` (half size, ~2× faster); fallback to `deepseek-r1:7b`; timeout reduced to 600 s |
| Prompts.py said "every 15 minutes" | Stale copy from before cycle interval was doubled to 30 min | Updated SYSTEM_PROMPT to say "every 30 minutes" |
| Live mode non-functional | `KrakenClient.get_balance()` used market value; `get_open_positions()` called `fetch_open_orders()` (wrong); `close_position()` and `check_stops_and_tp()` missing | Complete `KrakenClient` rewrite — all methods now mirror `PaperBroker` interface, positions tracked in `live_trading.db` |
| SL/TP loop only ran in paper mode | `if mode == "paper":` guard in `main.py` prevented live SL/TP checks | Removed guard — SL/TP loop now runs for both paper and live |

### Files Changed

| File | Change |
|---|---|
| `config.yaml` | `model` → `deepseek-r1:7b`; `fallback_model` → `deepseek-r1:7b`; `timeout_seconds` 900 → 600 |
| `src/agent/prompts.py` | Cycle interval doc fix: 15 min → 30 min |
| `src/exchange/kraken_client.py` | Full rewrite — `live_db` param; `get_balance()` mirrors PaperBroker; `get_open_positions()` from DB; `close_position()` new; `check_stops_and_tp()` new |
| `main.py` | Wire `live_db` to `KrakenClient`; remove `if mode == "paper":` guard from SL/TP loop |

---

## Session: 2026-04-01 (Part A) — Regime caution factor + dynamic TP code-enforced; tests added

### Bugs Fixed

| Bug | Root Cause | Fix |
|---|---|---|
| `caution_factor` computed but never applied | `detect_market_regime()` returned `caution_factor` (0.5/0.7) in `ai_context["regime_data"]` but nothing in `main.py` consumed it — position size was never actually reduced in bearish/volatile markets | After `build_ai_context()`, `portfolio["max_per_trade"]` is now scaled by `caution_factor` before the LLM cycle |
| Dynamic TP advisory only — not used at order placement | `compute_dynamic_tp()` computed ATR/BB-adjusted TP and injected text into LLM prompt, but `propose_buy()` always called `self._risk.get_take_profit_pct(pair)` (static config) — actual TP stored in `paper_positions` was always the static value | Added `compute_dynamic_tp_values()` to `features.py`; wired through `build_ai_context()` → `trading_agent.run_cycle()` → `TradingTools.set_dynamic_tp_values()` → `propose_buy()` |

### Features Added

| Feature | Files | Notes |
|---|---|---|
| `compute_dynamic_tp_values()` | `src/analysis/features.py` | Returns `{pair: tp_pct}` for all pairs; included in `build_ai_context()` output as `"dynamic_tp_values"` |
| `set_dynamic_tp_values()` on `TradingTools` | `src/agent/tools.py` | Called once per cycle by `TradingAgent`; values used in `propose_buy()` |
| Regime caution scaling | `main.py` | Logs `[REGIME]` when caution applied |
| 18 unit tests | `tests/test_regime_and_dynamic_tp.py` | Covers dynamic TP clamping, `build_ai_context` keys, `propose_buy` TP override, caution factor scaling and regime detection |

### Docs Updated

- `CLAUDE.md` — session notes table updated; two new gotchas added
- `README.md` — pairs table updated to 15 pairs
- `plan.md` — pairs list updated (10→15); cycle interval corrected (15→30 min); decision cycle step updated for single-LLM-call architecture and AI context
- `business-requirement.md` — FR-01 and scope updated to 15 pairs
- `.claude/skills/commit/SKILL.md` — steps 2–4 added (session notes, CLAUDE.md, docs review)

### Files Changed

| File | Change |
|---|---|
| `main.py` | Apply `caution_factor` to `portfolio["max_per_trade"]` after `build_ai_context()` |
| `src/analysis/features.py` | `compute_dynamic_tp_values()` added; `build_ai_context()` returns `"dynamic_tp_values"` |
| `src/agent/tools.py` | `_dynamic_tp_values` field; `set_dynamic_tp_values()`; `propose_buy()` uses dynamic TP |
| `src/agent/trading_agent.py` | `set_dynamic_tp_values()` called in `run_cycle()` |
| `tests/test_regime_and_dynamic_tp.py` | NEW — 18 unit tests |
| `.claude/skills/commit/SKILL.md` | Extended pre-commit steps |

---

## Session: 2026-03-30 (Part B) — AI Features, New Pairs, Config Refactor

### AI Features Added (src/analysis/features.py)

All 7 features are config-driven — no literals hardcoded in Python. All controlled via `config.yaml`.

| # | Feature | Description | Config Key |
|---|---|---|---|
| 1 | **Position Sizing** | Scale trade size by signal strength × ATR volatility. Weak signals get smaller size; high ATR reduces size to control risk | `position_sizing` |
| 2 | **Dynamic Take-Profit** | ATR-based TP: `ATR × multiplier / entry_price × 100`. Reduced to `min_tp_pct` when Bollinger Bands squeeze (low volatility) | `dynamic_tp` |
| 3 | **Market Regime Detection** | Count pairs with negative/positive MACD histogram. Classify as bearish/bullish/volatile/ranging. Inject `caution_factor` into LLM context | `regime` |
| 4 | **Fear & Greed Sentiment** | Fetch Alternative.me Fear & Greed Index (0–100). Cached for `cache_minutes`. Extreme Fear → LLM warned to be conservative | `sentiment` |
| 5 | **Pattern Analysis** | Query closed paper trades for per-pair win rate, avg P&L, most common exit reason. Injected as LLM advisory context | `pattern_analysis` |
| 6 | **Exit Timing** | Detect open position momentum decay: MACD histogram decay, RSI overbought, price stalled vs ATR. Returns advisory reason string | `exit_timing` |
| 7 | **Post-Trade LLM Analysis** | After each closed trade (agent sell, SL, or TP), LLM writes 2–3 sentences on why the trade succeeded or failed | `post_trade` |

### AI Feature Wiring

| File | Change |
|---|---|
| `src/analysis/features.py` | New file — all 7 features implemented |
| `main.py` | `build_ai_context()` called before each LLM cycle; `llm_client` passed to `TradingTools`; post-trade analysis triggered on SL/TP close |
| `src/agent/trading_agent.py` | `run_cycle()` accepts `ai_context` param; passed to `build_cycle_prompt()` |
| `src/agent/tools.py` | `llm_client` stored; `_run_post_trade_analysis()` added; called from `propose_sell` and SL/TP loop |
| `src/agent/prompts.py` | `build_cycle_prompt()` injects all 6 AI context blocks (regime, sentiment, patterns, exit_timing, position_sizing, dynamic_tp) |
| `config.yaml` | 7 new sections added with full literal configuration |

### Exit Timing Prompt Fix

- **Bug**: LLM treated Feature 6 exit timing alerts as commands — sold BNB at -0.14% when SL was at -5% and TP was +12%
- **Fix**: Added `EXIT MANAGEMENT` section to `SYSTEM_PROMPT`:
  - SL/TP owns all exits — LLM must not call `propose_sell` on stalled positions
  - Exit timing alerts are INFORMATIONAL only
  - `propose_sell` on open position only if Signal=SELL AND clear momentum reversal confirmed

### New Trading Pairs (15 total)

| Pair | WS Name | REST Name | TP% | Rationale |
|---|---|---|---|---|
| AVAX/USD | AVAX/USD | AVAXUSD | 15% | High volatility L1 |
| SUI/USD | SUI/USD | SUIUSD | 20% | High-beta L1 |
| HYPE/USD | HYPE/USD | HYPEUSD | 20% | High volatility DeFi |
| UNI/USD | UNI/USD | UNIUSD | 15% | DeFi blue chip |
| INJ/USD | INJ/USD | INJUSD | 20% | DeFi/L1 hybrid |

### Config-Driven Pair Maps (Architecture Refactor)

**Before**: `PAIR_MAP`, `REST_PAIR_MAP`, `KRAKEN_PAIR_MAP` hardcoded in Python files — adding a pair required editing 7+ files.

**After**: `config.yaml` is the single source of truth:
```yaml
- pair: BTC/USD
  ws_name: XBT/USD      # Kraken WebSocket v2 symbol
  rest_name: XBTUSD     # Kraken public REST OHLC symbol
  take_profit_pct: 8
  stop_loss_pct: 5
```
Adding a new pair now only requires editing `config.yaml` (plus prompts/display for the pair list text).

### Backfill Key Bug Fix

- **Bug**: `_backfill_pair()` called `result.get(rest_pair)` but Kraken REST returns data under its internal key (`XXBTZUSD` for BTC, `XDGZUSD` for DOGE) — not the name we sent
- **Fix** (`websocket_feed.py`):
  ```python
  result_key = next((k for k in result if k != "last"), None)
  candles_raw = result.get(result_key, []) if result_key else []
  ```

### Daily Loss Limit Notification Spam Fix

- **Bug**: `send_daily_loss_limit_reached()` called every 15-minute cycle after limit hit — hundreds of alerts per day
- **Fix** (`main.py`): `loop_state = {"daily_loss_notified_date": None}` shared across cycles; notification sent only once per calendar date; resets at midnight

### LLM Debug Logging

- **New**: Full LLM prompt + HTTP response logged at DEBUG level in `logs/agent.log`
- **Config**: `storage.llm_debug_logging: false` — set `true` to enable
- Console stays at INFO; file log receives DEBUG (prompts, requests, responses, token counts)
- Log tags: `[LLM PROMPT]`, `[LLM REQUEST]`, `[LLM RESPONSE]`

### New Tool: rsi_verifier.py

- Fetches live RSI from Kraken public REST API for all monitored pairs
- Reads pairs from `config.yaml` — no hardcoded list
- Args: `--interval` (candle minutes), `--window` (RSI period), `--threshold` (overbought level)

### Updated: add-pair Skill

- Old skill referenced now-removed `PAIR_MAP`/`REST_PAIR_MAP`/`KRAKEN_PAIR_MAP`
- New skill: only update `config.yaml` (with `ws_name`+`rest_name`) + prompts/display/nl_parser/random_execution_kraken
- Includes live Kraken API verification step

### Bugs Fixed This Session

| Bug | Root Cause | Fix |
|---|---|---|
| LLM closes open positions on stall signal | Feature 6 exit timing alert injected into prompt; LLM treated it as action command | Added EXIT MANAGEMENT rules to SYSTEM_PROMPT |
| Daily loss limit notification spam | No deduplication — fired every cycle after limit hit | `loop_state` date tracking; notify once per day |
| REST backfill fetching wrong candles | Kraken response key differs from request name (e.g. `XXBTZUSD` ≠ `XBTUSD`) | Use `next(k for k in result if k != "last")` |

### Files Changed This Session

| File | Change |
|---|---|
| `src/analysis/features.py` | NEW — all 7 AI features |
| `config.yaml` | `ws_name`/`rest_name` on all pairs; 5 new pairs; 7 AI feature sections; `llm_debug_logging` |
| `src/agent/prompts.py` | EXIT MANAGEMENT section; AI context blocks injected |
| `src/agent/trading_agent.py` | `ai_context` param; LLM prompt/response debug logging |
| `src/agent/tools.py` | `llm_client`; `_run_post_trade_analysis()`; all 15 pairs in docstring |
| `src/exchange/websocket_feed.py` | Config-driven pair maps; backfill key bug fix |
| `src/exchange/kraken_client.py` | Config-driven pair map; `config` param in `__init__` |
| `src/cli/display.py` | Welcome banner updated to 15 pairs |
| `src/cli/nl_parser.py` | PAIRS list and LLM prompt updated for 15 pairs |
| `main.py` | Daily loss spam fix; `build_ai_context` wired; `config` to KrakenClient; DEBUG logging |
| `rsi_verifier.py` | NEW — live RSI verifier |
| `random_execution_kraken.py` | PAIRS updated to 14 pairs |
| `.claude/skills/add-pair/SKILL.md` | Updated to config-driven architecture |
| `docs/sessions/session_2026_03_30b.md` | Session notes |

### Commit
| Hash | Message |
|---|---|
| `4b08e80` | feat: 5 new pairs, config-driven pair maps, AI features 1-7, LLM debug logging |

---

## Session: 2026-03-30

### Bugs Fixed

| Bug | Root Cause | Fix |
|---|---|---|
| Daily loss limit fires immediately after every BUY (30.1% false loss) | `PaperBroker.get_balance()` returned `total_usd = cash` only, not including open position entry values. `get_daily_pnl()` used `available_cash_usd` instead of `total_usd`. After buying BNB for $209.77, cash dropped from $699.22 to $488.90, which looked like a 30.1% loss | `get_balance()` now queries `usd_value` from open positions and adds to cash for `total_usd`. `get_daily_pnl()` now uses `total_usd` |
| `close_position()` would crash on first real stop-loss or take-profit | `datetime.fromisoformat()` used inside `close_position()` but `datetime` was never imported | Added `from datetime import datetime` |
| LLM overrides valid BUY signals with HOLD (e.g. XRP BUY 0.60 → HOLD) | System prompt said "when signals are not strongly aligned, hold() is correct" — gave LLM discretion to re-evaluate raw indicators (RSI, MACD) and override the scorer. LLM saw RSI=77.1 on adjacent TRX pair and applied it to XRP reasoning | Replaced vague guidance with explicit decision rule: Signal=BUY → propose_buy, with exhaustive list of only 4 valid override conditions |

### Key Insight (prompts.py)
The LLM must not be given discretion to re-evaluate individual raw indicators after the scorer has already produced a BUY signal. The scorer weighs all indicators together — a high RSI on one pair does not cancel a BUY score that was built from MACD + BB confluence. The prompt must be a decision tree, not guidance.

### Key Insight (paper_broker.py)
This `get_balance()` / `get_daily_pnl()` bug has regressed twice. The correct invariant: `total_usd = cash + sum(usd_value of open positions)`. Buying converts cash into a position of equal entry value — `total_usd` stays flat. Only price movement or realised losses should change it.

### Critical Conventions (reinforced)
- `PaperBroker.get_balance()` must return `total_usd = cash + open_position_entry_values` — never cash-only
- `get_daily_pnl()` must use `total_usd`, never `available_cash_usd`
- `from datetime import datetime` must be present in `paper_broker.py`
- LLM prompt must give an explicit decision tree for BUY/SELL/HOLD — never vague "when in doubt, hold" language

### Files Changed

| File | Change |
|---|---|
| `src/exchange/paper_broker.py` | `get_balance()` includes open position `usd_value`; `get_daily_pnl()` uses `total_usd`; added `from datetime import datetime` |
| `src/agent/prompts.py` | Explicit decision rule: Signal=BUY → propose_buy; 4 valid override conditions listed; removed "when in doubt hold" instruction |

---

## Session: 2026-03-29 (continued — night)

### Bugs Fixed

| Bug | Root Cause | Fix |
|---|---|---|
| All pairs returning HOLD strength=0 after BB config change | `bb_min_width_pct=1.5%` was suppressing BB signals on pairs with band widths of 0.7–1.4% (most pairs) | Reverted `bb_min_width_pct` to 0.5%; fixed the real problem in `signals.py` instead |
| Simultaneous upper+lower BB signals on narrow bands | BB buy and sell checks were independent — both could fire when price was between tight bands | `near_lower` and `near_upper_for_sell` now computed once and are mutually exclusive; if both fire, neither is awarded |

### Files Changed

| File | Change |
|---|---|
| `src/analysis/signals.py` | BB upper/lower checks now mutually exclusive — simultaneous touch awards neither |
| `config.yaml` | `bb_min_width_pct` reverted to 0.5%; `bb_buy_tolerance_pct` and `bb_sell_tolerance_pct` kept at 0.5% |

### Key Insight
The BB squeeze fix belongs in the **signal logic** (mutual exclusion), not in the config threshold. Raising `bb_min_width_pct` to catch squeeze suppresses too many valid signals. The correct fix is: if price is simultaneously near both bands, award neither — the bands are too tight to be meaningful regardless of the width threshold.

### Current market state (2026-03-29 23:xx SGT)
MACD histogram is negative across all 10 pairs — genuine bearish momentum phase. No BUY signals expected until MACD turns positive or RSI drops below 30 on at least one pair. Agent correctly HOLDing.

---

## Session: 2026-03-29 (continued — evening)

### Bugs Fixed

| Bug | Root Cause | Fix |
|---|---|---|
| `Cannot operate on a closed database` in Decision Breakdown report | `risk_by_pair` query placed after `ac.close()` in `get_llm_decision_patterns()` | Moved `ac.close()` to after all queries; also removed duplicate `ac.close()` |
| BB tolerance overlap — most pairs showing both upper and lower BB signals simultaneously | `bb_buy_tolerance_pct` and `bb_sell_tolerance_pct` both 1.0% caused overlap when band width was only ~0.88%; `bb_min_width_pct` of 0.5% was too low to catch it | Raised `bb_min_width_pct` to 1.5%, reduced tolerances to 0.5% |
| LLM overriding valid BUY signals (e.g. XRP score 6/10) with HOLD | System prompt hardcoded `RSI < 35` as mandatory BUY condition; LLM ignored MACD+BB confluence when RSI was neutral | Updated `prompts.py` to tell LLM to trust the signal scorer; RSI < 30 is a bonus not a requirement |
| No BUY executions despite XRP generating BUY signal every cycle | Combination of above two bugs — BB false signals on other pairs + LLM RSI fixation | Both fixed above |

### Files Changed

| File | Change |
|---|---|
| `src/reports/trade_report.py` | Moved `ac.close()` after `risk_by_pair` query; removed duplicate close |
| `src/agent/prompts.py` | Removed hardcoded `RSI < 35` mandatory BUY rule; LLM now trusts signal scorer |
| `config.yaml` | `bb_min_width_pct` 0.5→1.5; `bb_buy_tolerance_pct` and `bb_sell_tolerance_pct` 1.0→0.5 |

### Key Insight
The signal scorer and the LLM prompt were misaligned. The scorer awards points for MACD+BB confluence without requiring RSI oversold — but the prompt told the LLM RSI < 35 was mandatory. Always keep the prompt aligned with the scoring system.

---

## Session: 2026-03-29

### Bugs Fixed

| Bug | Root Cause | Fix |
|---|---|---|
| Daily loss limit trips after first trade | `PaperBroker.get_balance()` returned cash-only as `total_usd`; buying $300 of ADA looked like a $300 loss | `total_usd` now includes open position entry cost; `get_daily_pnl()` uses `total_usd` not `available_cash_usd` |
| `AttributeError` in live mode | `KrakenClient` was missing `get_daily_pnl()` and `get_open_positions_count()` | Both methods added to `KrakenClient` |
| Decision Breakdown shows BUY=0 | `decision_type` stored as `TRADE_BUY`/`TRADE_SELL`; report expected `BUY`/`SELL` | Changed to `BUY`/`SELL` in `trading_agent.py`; migrated 3 existing DB rows |
| LLM hallucinated pair names (`SLAY/USD`, `SPICE/USD`) | Tool execution used `tool_args.get("pair")` — trusted the LLM's pair argument | Always use the signal's known `pair` variable; 38 hallucinated DB rows deleted |
| `generate_signal` logging `cycle=0` | `set_cycle_id()` called inside `TradingAgent` but signals computed before that in `main.py` | `set_cycle_id()` now called immediately after `audit.log_cycle()` in `main.py` |
| `config.yaml` `pair: 3` crash | `BTC/USD` accidentally edited to `3` in config | Restored to `BTC/USD` |
| RAILS/USD WebSocket updates dropped | `RAILS/USD` was in `REST_PAIR_MAP` but missing from `PAIR_MAP` | Added to `PAIR_MAP` in `websocket_feed.py` |

### Features Added

- **Decision Breakdown by Pair** report now shows 8 columns: LLM Buy, LLM Sell, LLM Hold, Risk ✓, Risk ✗, Executed, Final Hold
- **RAILS/USD** added as 10th trading pair (TP 20%, SL 5%) across all config and source files
- **`/add-pair` Claude Code skill** — onboards a new pair across all 7 required files in one command
- **`/commit` Claude Code skill** — stages safe files, derives conventional commit message, pushes to GitHub

### Files Changed

| File | Change |
|---|---|
| `src/exchange/paper_broker.py` | `get_balance()` includes open position value; `get_daily_pnl()` uses `total_usd` |
| `src/exchange/kraken_client.py` | Added `get_daily_pnl()`, `get_open_positions_count()`, `RAILS/USD` to pair map |
| `src/exchange/websocket_feed.py` | Added `RAILS/USD` to `PAIR_MAP` |
| `src/agent/trading_agent.py` | `TRADE_BUY`→`BUY`, `TRADE_SELL`→`SELL`; tool execution uses signal pair not LLM pair |
| `src/storage/audit_logger.py` | Updated `decision_type` comment |
| `src/reports/trade_report.py` | Decision patterns query now fetches risk approval/rejection per pair |
| `src/cli/display.py` | Decision Breakdown table expanded to 8 columns; RAILS/USD in welcome screen |
| `main.py` | `set_cycle_id()` called immediately after `audit.log_cycle()` |
| `config.yaml` | `BTC/USD` restored; `RAILS/USD` added |
| `data/audit.db` | Migrated `TRADE_BUY`→`BUY`, `TRADE_SELL`→`SELL`; deleted 38 hallucinated pair rows |
| `.claude/skills/add-pair/SKILL.md` | New skill created |
| `.claude/skills/commit/SKILL.md` | New skill created |
| `README.md` | Claude Code Skills section added; file tree updated; docs table updated |
| `business-requirement.md` | Revision 1.3; FR-76, FR-77 added; RAILS/USD in all tables; 10 pairs throughout |
| `plan.md` | Updated pair count to 10 in LLM system prompt section |

### Key Architectural Decisions

- **Broker interface contract**: Both `PaperBroker` and `KrakenClient` must implement the same methods. An abstract base class (`BaseBroker`) was recommended to enforce this — not yet implemented.
- **LLM output validation**: Never trust pair names from LLM tool arguments. Always use the known pair from the signal loop.
- **Cycle ID propagation**: `set_cycle_id()` must be called at the top of `run_cycle()` in `main.py`, before any `@timed` decorated functions run.
- **Decision type constants**: `BUY`/`SELL`/`HOLD` are used throughout. A shared constants file was recommended to prevent future mismatches.

### Commits

| Hash | Message |
|---|---|
| `34e2d6a` | fix: daily loss limit trips after first trade in paper mode |
| `9517c6b` | fix: multiple bugs + add RAILS/USD as 10th trading pair |
| `68ba58e` | docs: add /add-pair Claude Code skill usage to README and requirements |
| `28412c9` | feat: add /commit Claude Code skill and update docs |

---

## Session: 2026-04-04 (Part A) — Volatility-Adaptive Quant Migration

### Features Added

| Feature                 | Files                                                      | Notes                                                              |
|-------------------------|------------------------------------------------------------|--------------------------------------------------------------------|
| Trend & Momentum        | `src/analysis/indicators.py`, `src/analysis/signals.py`    | Overhauled EMA 9/21/50 usage, removed strict 8-red/4-green block.  |
| Adaptive Risk Mgmt      | `src/analysis/features.py`, `src/risk/risk_manager.py`     | Position sizing/TP/SL naturally scales dynamically by ATR.         |
| Order Book Imbalance    | `src/exchange/websocket_feed.py`                           | Added real-time L2 order book streaming for Imbalance constraints. |
| Limit Orders            | `src/exchange/paper_broker.py`, `KrakenClient`             | Maker limit orders implemented over taker market orders.          |
| Unified Backtesting     | `tests/test_backtest.py`                                   | Full production backtest rig overriding legacy determinism script. |

---

## Session: 2026-04-05 (Part A) — Minimum Profit Floor and Trading Rules SKILL

### Features Added
- **Minimum Profit Floor**: Added a 1.0% minimum profit floor to prevent the agent from closing trades for micro-profits that would map to net losses after Kraken Maker/Taker fees.
- **Configurable Profit Floor**: Added `min_profit_floor_pct` to `config.yaml`.
- **Trading Rules SKILL**: Moved hardcoded trading rules from the agent prompt into `.claude/skills/trading-rules/SKILL.md` to be dynamically loaded, deduplicating logic.
- **Strict PNL Validation**: Updated `src/risk/risk_manager.py` to strictly reject sell requests that do not meet the minimum profit floor. The live execution price from the WebSocket is now used to calculate the estimated PNL during `propose_sell`.

## Session: 2026-04-05 (Part C) — Live API Execution Fixes

### Bugs Fixed
- **Kraken Client Limits**: Fixed a critical execution sequence bugs where Stop-Loss/Take-Profit orders were placed instantly right after a Limit Buy Order in `kraken_client.py`, triggering 'Insufficient Funds'. Orders are now gracefully queued until the initial Limit executes.
- **Kraken Client Fallbacks**: Fixed a fallback exit bug where missed native SL/TP triggers incorrectly just canceled orders instead of issuing a market sell.

### Features Added
- **VPS Telemetry**: Built 2-Hour Heartbeats, 6-Hour PnL reports, and explicit start/stop telemetry events.
- **Dependency Locking**: Generated a strict `requirements.txt` pinned version file.
- **Defensive Unit Testing**: Constructed `tests/test_indicators.py` explicitly verifying indicators and ATR stop loss dynamic ranges.

## Session: 2026-04-05 (Part C) — Live API Execution Fixes

### Bugs Fixed
- **Kraken Client Limits**: Fixed a critical execution sequence bugs where Stop-Loss/Take-Profit orders were placed instantly right after a Limit Buy Order in `kraken_client.py`, triggering 'Insufficient Funds'. Orders are now gracefully queued until the initial Limit executes.
- **Kraken Client Fallbacks**: Fixed a fallback exit bug where missed native SL/TP triggers incorrectly just canceled orders instead of issuing a market sell.

### Features Added
- **VPS Telemetry**: Built 2-Hour Heartbeats, 6-Hour PnL reports, and explicit start/stop telemetry events.
- **Dependency Locking**: Generated a strict `requirements.txt` pinned version file.
- **Defensive Unit Testing**: Constructed `tests/test_indicators.py` explicitly verifying indicators and ATR stop loss dynamic ranges.

## Session: 2026-04-05 (Part B) — Fat Finger and Balance Guards

### Features Added
- **Fat Finger Guard**: Dynamic Balance Validation. Added `max_safe_allocation = available_cash_usd * 0.98` to buffer 2% cash and protect from failed execution. Added strict checks to prevent enormous token quantity purchases caused by floating point limits or order fat fingers.
- **Flash Crash Anomaly Detection**: Rejected orders when current asset price plummets below macroscopic baseline pricing limits.

## [Unreleased]
### Added
- Execution: Post-Only limit orders with 60-second replacement chase logic to mitigate taker fees.
- Strategy: Time-of-Day filter (16:00-20:00 UTC) and Volume guards (>50% 20-SMA).
- Architectural: Healthcheck webhook ping on agent loop completion to monitor for deadlocks.

## Session: 2026-04-05 (Part G) — Documentation Suite

### Documentation Added / Updated
- **README.md rewrite**: Full rewrite reflecting quantitative migration — confluence scoring, ATR sizing, dynamic TP, OBI, limit orders, profit floor, kill switch, heartbeat, healthchecks.io. All 15 pairs listed with correct TP%. Configuration reference table and architecture section added.
- **docs/business_requirements.md (BRD v2.0)**: Formal rewrite from scratch — 13 sections, 99+ numbered FRs, 15 Business Rules, 23-term glossary, revision history table, pair configuration table.
- **docs/codebase.md** (new): Developer reference covering all 13 modules with function signatures, DB schema, config.yaml parameter reference, data-flow section, and 6 Design Patterns (744 lines).
- **docs/how_to_debug.md** (new): Operational runbook — 5-step debug workflow, SQL snippets, log grep patterns, paper vs live differences, common failure scenarios (616 lines).
- **commit SKILL.md expanded**: Step 4 now includes per-file update guidance for all 6 docs with complexity guide. Step 8 stage list updated to include all 6 docs.
- **business-requirement.md deleted**: Stale root-level file removed; `docs/business_requirements.md` is now the single source of truth.
- **CLAUDE.md**: Model `<think>` block note generalised to cover any reasoning model (not just deepseek-r1).
- **plan.md**: Architecture diagram LLM label updated to `(tool-capable)`.

## Session: 2026-04-06 (Part B) — GitHub Sub-Issues API Fix

### Bug Fixed
- **`create_story()` sub-issue linking**: Fixed broken `gh api` call in `scripts/create_github_issues.sh` — added required `Accept: application/vnd.github+json` and `X-GitHub-Api-Version: 2026-03-10` headers; changed `--field` to `-F` for the POST body parameter.

### Scripts Added
- **`scripts/link_epics.sh`**: Retroactive sub-issue linker — discovers existing Epic and Story issues by label and links each Story as a GitHub Sub-Issue of its parent Epic. Idempotent (safe to re-run).

## Session: 2026-04-09 (Part F) — Per-pair caution_factor, buy_min_score, aggressive sizing

### Features Added
- **Per-pair caution_factor_bearish (#124)**: In bearish regime, `main.py` now injects `sig["pair_max_usd"]` per signal using `pair_cfg.get("caution_factor_bearish", global_caution)`. Winners (ETH/BNB/DOGE)=1.0, stable pairs (BTC/LTC/TRX/XRP)=0.8, mid-vol (ADA/AVAX/SOL)=0.6, underperformers (SUI/INJ)=0.35, RAILS/HYPE=0.40. Values calibrated from 200-SMA bearish window drawdown analysis on `/history/` candle data. LLM prompt shows per-pair "Max buy size" in bearish regime.
- **Per-pair buy_min_score (#128)**: `signals.py` reads `pair_cfg.get("buy_min_score", global)`. INJ=7, SOL/UNI=6 (30–50% win rates in backtest). ETH/BNB/DOGE=5 (explicit). Global default=5.
- **Aggressive position sizing (#130)**: `max_position_pct` 15→20%, `base_position_pct` 12→16%, `min_cash_reserve_pct` 10→5%, `max_buys_per_cycle` 5→7. Max per trade $150→$200 on $1k portfolio.

### Skills Updated
- `trading-rules/SKILL.md`: reserve 5%, max_buys 7, growth-oriented role, per-pair bearish/score rules documented.
- `add-pair/SKILL.md`: 13-field pair block, guidance tables for `caution_factor_bearish` and `buy_min_score`.

### Tests
- 9 new tests in `tests/test_per_pair_params.py` (`TestPerPairBuyMinScore`, `TestPerPairCautionFactor`). 98 total pass.

## Session: 2026-04-11b

### Features
- **OBV accumulation signal (#136)**: `indicators.py` computes OBV series (last 30 values). `signals.py` computes trend via `_compute_obv_trend()` — OBV rising +1 BUY; OBV falling adds distribution warning to reasons. Per-pair `obv_trend_period` override (global default 10).
- **BB squeeze release (#137)**: `indicators.py` computes `bb_width_series` (last 10 values, % of price) and adds `detect_bb_squeeze_release()`. `signals.py` awards +2 BUY on upward squeeze breakout (prior candles in squeeze → current expands to threshold × 1.2 with price > midband). `max_score` updated 22 → 25.

### Skills
- `trading-rules/SKILL.md`: OBV and BB squeeze release rules added.
- `add-pair/SKILL.md`: `obv_trend_period` added to pair block template, estimation table, checklist, and backtest interpretation guide. Field count now 15.

### Tests
- `tests/test_obv_signal.py`: 8 new tests.
- `tests/test_bb_squeeze_breakout.py`: 8 new tests.
- 96 tests total, all passing.

## Session: 2026-04-11 (Part F) — Add 10 new trading pairs (#145–#154)

### Features Added
- **10 new tradeable pairs**: WIF/USD (Solana meme), TON/USD (Telegram chain), OP/USD (Optimism L2), ARB/USD (Arbitrum L2), JUP/USD (Jupiter DEX), PEPE/USD (extreme meme), TIA/USD (Celestia modular), RENDER/USD (AI GPU compute), FET/USD (ASI Alliance AI), STX/USD (Bitcoin L2 / Stacks). Total active pairs: 24 (was 14; RAILS/USD disabled).
- **config.yaml**: 10 new 15-field pair blocks (TP%, SL%, atr_tp_min_pct, RSI thresholds, BB squeeze, volume ratio, ATR lookback, caution_factor_bearish, buy_min_score, rsi_divergence_lookback, obv_trend_period). Trailing-stop per_pair_overrides added for WIF, JUP, PEPE, TIA, RENDER, FET, STX.
- **Backtest validated**: overall 55% win rate (threshold ≥45%). Post-backtest tuning: WIF/USD buy_min_score 6→7 (33% win); OP/USD buy_min_score 6→7 (47% marginal); TIA/USD buy_min_score 7→8 + atr_tp_min_pct 0.45→0.50 (39% win).
- **RENDER rest_name confirmed**: `RENDERUSD` (not `RNDR` as tentatively noted in issue #152).

### Files Changed
- `config.yaml` — 10 new pair blocks + trailing-stop overrides
- `tests/backtest/loader.py` — 10 new PAIR_FILE_MAP entries
- `src/agent/tools.py` — propose_buy docstring pair list extended
- `src/cli/display.py` — welcome banner updated (RAILS removed, 10 new pairs)
- `src/cli/nl_parser.py` — PAIRS list + _SYSTEM_PROMPT extended
- `docs/business_requirements.md` — v2.1, pair count 15→24, FR-01 list, pair table
- `docs/epics_stories_ac.md` — "15 pairs" → "24 pairs" (3 occurrences)
- `CLAUDE.md` — pairs table and session notes extended
- `history/` — 10 new candle JSON files (721 candles each, 15-min interval)

### Tests
- 174 tests, all passing (no regressions).

### Fix (follow-up)
- `.claude/skills/trading-rules/SKILL.md`: pair list updated 15→24 active pairs; RAILS/USD marked disabled; `Per-pair Max Buy Size`, `Per-pair Signal Threshold`, and `DECISION STYLE` bearish regime rule updated to reflect new caution tiers and buy_min_score thresholds for 10 new pairs.
