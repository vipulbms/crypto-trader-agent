#!/usr/bin/env python3
"""
Create all 60 Kryptos v3 GitHub issues (E12-E24) via gh CLI.
Usage: python3 scripts/create_v3_issues.py
"""
import subprocess
import sys

REPO = "vipulbms/crypto-trader-agent"

TEST_SCENARIOS_FOOTER = """
## Test Scenarios
> To be filled by Tester before sprint start.
- [ ] TS1: Happy path — [describe expected input and output]
- [ ] TS2: Boundary condition — [edge case]
- [ ] TS3: Negative / failure path — [error handling]
- [ ] TS4: Regression — Conservative behaviour unchanged from v2 (if applicable)"""

def ci(title: str, body: str, labels: str, sprint: str) -> bool:
    """Create one GitHub issue."""
    cmd = [
        "gh", "issue", "create",
        "--repo", REPO,
        "--title", title,
        "--body", body,
        "--label", labels,
        "--milestone", f"Sprint {sprint}",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode == 0:
        url = result.stdout.strip()
        print(f"  ✅ {title}\n     {url}")
        return True
    else:
        print(f"  ❌ {title}\n     {result.stderr.strip()}")
        return False


def body(story_meta: str, ac_lines: str, ts_lines: str) -> str:
    return f"{story_meta}\n\n## Acceptance Criteria\n{ac_lines}\n\n## Test Scenarios\n> To be filled by Tester before sprint start.\n{ts_lines}"


ISSUES = [
    # ── E12 ──────────────────────────────────────────────────────────────────
    (
        "[E12] S12.1.1 — Persona config schema in config.yaml",
        """## Story
**As a** system operator,
**I want** each persona's risk parameters defined in `config.yaml` under `personas:`,
**so that** switching persona changes all risk thresholds atomically without code changes.

- **Sprint:** S1
- **Assigned to:** python-dev
- **Story points:** 3
- **BRD reference:** FR-P01
- **Architecture reference:** §2.1
- **Code targets:** `config.yaml`, `src/risk/risk_manager.py`

## Acceptance Criteria
- [ ] AC1: `personas:` block in `config.yaml` with Conservative / Medium / High sub-keys
- [ ] AC2: Each persona contains all required parameters (see BRD §8 Personas Reference Table)
- [ ] AC3: `PersonaLoader.load(persona_name)` raises `ConfigError` if any required field is absent
- [ ] AC4: Unit test: load all three personas from fixture config; assert all fields present

## Test Scenarios
> To be filled by Tester before sprint start.
- [ ] TS1: All three personas load without error
- [ ] TS2: Missing `buy_min_score` field → ConfigError raised
- [ ] TS3: Conservative persona parameters match v2 production values""",
        "sprint:S1,epic:E12,role:python-dev,type:story",
        "S1",
    ),
    (
        "[E12] S12.1.2 — Persona loader and runtime injection",
        """## Story
**As a** trading agent,
**I want** the active persona loaded at startup and injected into all agents via `CycleContext`,
**so that** every agent uses the correct thresholds for the active risk profile.

- **Sprint:** S1
- **Assigned to:** python-dev
- **Story points:** 5
- **BRD reference:** FR-P01, FR-P05
- **Architecture reference:** §2.1
- **Code targets:** `src/risk/risk_manager.py`, `main.py`

## Acceptance Criteria
- [ ] AC1: `PersonaLoader.load(name)` reads `config.yaml` and returns typed `PersonaConfig` dataclass
- [ ] AC2: `main.py` reads `agent.persona` from config at startup; falls back to `conservative` if absent
- [ ] AC3: `CycleContext.persona_config` field populated before any agent runs
- [ ] AC4: Persona switch logged with `actor`, `from_persona`, `to_persona`, `timestamp`
- [ ] AC5: Unit test: load conservative; verify `buy_min_score`, `max_position_pct`, `velocity_circuit_breaker_pct` match expected values

## Test Scenarios
> To be filled by Tester before sprint start.
- [ ] TS1: Persona loaded and injected into CycleContext
- [ ] TS2: `agent.persona: unknown` → ConfigError
- [ ] TS3: Conservative values match v2 defaults""",
        "sprint:S1,epic:E12,role:python-dev,type:story",
        "S1",
    ),
    (
        "[E12] S12.1.3 — Persona-aware signal gating",
        """## Story
**As a** risk manager,
**I want** `validate_buy()` to read thresholds from the active persona config,
**so that** Conservative trades more cautiously and High trades more aggressively.

- **Sprint:** S2
- **Assigned to:** python-dev
- **Story points:** 3
- **BRD reference:** FR-P02
- **Architecture reference:** §2.1
- **Code targets:** `src/risk/risk_manager.py`

## Acceptance Criteria
- [ ] AC1: `validate_buy()` reads `persona_config.buy_min_score`, `max_position_pct`, `min_profit_floor_pct`
- [ ] AC2: Conservative: `buy_min_score=5`, `max_position_pct=20%`; High: `buy_min_score=3`, `max_position_pct=30%`
- [ ] AC3: Unit test (3): Conservative blocks buy at score=4; High allows buy at score=3; Medium allows at score=4

## Test Scenarios
> To be filled by Tester before sprint start.
- [ ] TS1: Conservative score=4 → BLOCK
- [ ] TS2: High score=3 → ALLOW
- [ ] TS3: Regression — Conservative = v2 behaviour""",
        "sprint:S2,epic:E12,role:python-dev,type:story",
        "S2",
    ),
    # ── E13 ──────────────────────────────────────────────────────────────────
    (
        "[E13] S13.1.1 — Winsorized EMA-14 volume floor",
        """## Story
**As a** risk manager,
**I want** the volume floor computed as a Winsorized EMA-14 rather than rolling p15,
**so that** single-candle volume spikes do not distort the floor and cause false volume dead-zone blocks.

- **Sprint:** S2
- **Assigned to:** python-dev
- **Story points:** 3
- **BRD reference:** FR-Q01
- **Architecture reference:** §2.2
- **Code targets:** `src/analysis/indicators.py`, `src/analysis/signals.py`

## Acceptance Criteria
- [ ] AC1: `compute_winsorized_ema(series, period=14, clip_pct=0.05)` replaces `rolling_volume_p15`
- [ ] AC2: Outliers clipped at p5/p95 before EMA; underlying data unchanged
- [ ] AC3: Volume dead-zone check uses `winsorized_ema_volume` instead of `rolling_volume_p15`
- [ ] AC4: Unit test: 14-candle series with one 10× spike — Winsorized EMA within 5% of non-spiked mean

## Test Scenarios
> To be filled by Tester before sprint start.
- [ ] TS1: Single volume spike does not trigger false dead-zone block
- [ ] TS2: Normal volume series → EMA matches manual calculation
- [ ] TS3: Performance — adds < 5ms per pair (NFR-04)""",
        "sprint:S2,epic:E13,role:python-dev,type:story",
        "S2",
    ),
    (
        "[E13] S13.1.2 — Variance heartbeat per pair",
        """## Story
**As a** risk manager,
**I want** per-pair OHLCV variance checked each cycle, with zero-variance pairs flagged as frozen,
**so that** stale WebSocket data is detected and affected pairs removed from the LLM cycle.

- **Sprint:** S2
- **Assigned to:** python-dev
- **Story points:** 3
- **BRD reference:** FR-Q02
- **Architecture reference:** §2.2
- **Code targets:** `src/analysis/signals.py`, `main.py`

## Acceptance Criteria
- [ ] AC1: `compute_ohlcv_variance(candles, n=5)` returns float variance over last N candles
- [ ] AC2: Variance == 0.0 → pair marked `frozen`; excluded from LLM prompt that cycle; logged at WARN
- [ ] AC3: Frozen count included in heartbeat Telegram message
- [ ] AC4: Unit test: 5 identical close prices → pair frozen; 5 varying → not frozen

## Test Scenarios
> To be filled by Tester before sprint start.
- [ ] TS1: Frozen pair → excluded from prompt
- [ ] TS2: Recovered pair → included again next cycle
- [ ] TS3: All pairs frozen → cycle skips LLM, logs warning""",
        "sprint:S2,epic:E13,role:python-dev,type:story",
        "S2",
    ),
    (
        "[E13] S13.2.1 — Pipe-format QSA signal block",
        """## Story
**As a** developer,
**I want** QSA signals emitted in pipe-separated format,
**so that** AIE can parse structured data efficiently within tight token budgets.

- **Sprint:** S2
- **Assigned to:** ai-engineer
- **Story points:** 2
- **BRD reference:** FR-Q03, FR-T01
- **Architecture reference:** §2.2, §5
- **Code targets:** `src/analysis/signals.py`, `src/agent/prompts.py`

## Acceptance Criteria
- [ ] AC1: `format_signal_psv(signal: dict) -> str` produces `Pair|RSI|ADX|Score|Action|...` string
- [ ] AC2: Boolean fields encoded as `1`/`0`; no quotes; separator is `|`
- [ ] AC3: PSV string for 15 pairs ≤ 600 tokens (tiktoken `cl100k_base`)
- [ ] AC4: Unit test: known signal dict → expected PSV string matches exactly

## Test Scenarios
> To be filled by Tester before sprint start.
- [ ] TS1: 15-pair PSV ≤ 600 tokens
- [ ] TS2: Boolean field encoding verified
- [ ] TS3: Regression — existing signal fields preserved""",
        "sprint:S2,epic:E13,role:ai-engineer,type:story",
        "S2",
    ),
    (
        "[E13] S13.2.2 — PSV field schema and token budget",
        """## Story
**As a** developer,
**I want** the PSV field schema defined and enforced with a per-pair token budget,
**so that** signal blocks are consistent and never exceed AIE's total token limit.

- **Sprint:** S3
- **Assigned to:** ai-engineer
- **Story points:** 2
- **BRD reference:** FR-Q04, FR-T02
- **Architecture reference:** §5
- **Code targets:** `src/analysis/signals.py`

## Acceptance Criteria
- [ ] AC1: Canonical PSV field order documented in Architecture-Design-v3.md §5
- [ ] AC2: Per-pair PSV ≤ 40 tokens; total 15 pairs ≤ 600 tokens
- [ ] AC3: `validate_psv_budget(pairs)` raises `TokenBudgetError` if total exceeds budget
- [ ] AC4: Unit test: 16-pair input → budget error raised

## Test Scenarios
> To be filled by Tester before sprint start.
- [ ] TS1: 15 pairs → passes budget check
- [ ] TS2: 16 pairs → TokenBudgetError
- [ ] TS3: Empty pair list → no error""",
        "sprint:S3,epic:E13,role:ai-engineer,type:story",
        "S3",
    ),
    (
        "[E13] S13.2.3 — Per-pair volume ratio in pipe format",
        """## Story
**As a** developer,
**I want** the per-pair volume ratio included in the PSV signal block,
**so that** AIE has volume context when evaluating signal quality.

- **Sprint:** S3
- **Assigned to:** ai-engineer
- **Story points:** 2
- **BRD reference:** FR-Q05
- **Architecture reference:** §2.2
- **Code targets:** `src/analysis/signals.py`

## Acceptance Criteria
- [ ] AC1: `volume_ratio` field (current_volume / winsorized_ema, 2 d.p.) included in PSV
- [ ] AC2: Field position defined in canonical schema; existing fields unaffected
- [ ] AC3: Unit test: volume_ratio=1.23 → PSV contains `1.23` in correct position

## Test Scenarios
> To be filled by Tester before sprint start.
- [ ] TS1: Normal volume → ratio appears in PSV
- [ ] TS2: Zero EMA volume → ratio=0.0, no division error""",
        "sprint:S3,epic:E13,role:ai-engineer,type:story",
        "S3",
    ),
    (
        "[E13] S13.3.1 — Trade context injection into QSA",
        """## Story
**As a** trading agent,
**I want** the last closed trade per pair (exit reason, PnL%, days ago) injected as context before signal generation,
**so that** the signal score accounts for recent performance history on each pair.

- **Sprint:** S3
- **Assigned to:** python-dev
- **Story points:** 3
- **BRD reference:** FR-Q06
- **Architecture reference:** §2.2
- **Code targets:** `src/analysis/signals.py`, `main.py`

## Acceptance Criteria
- [ ] AC1: `get_last_trade_context(pair, db_path)` returns `{exit_reason, pnl_pct, days_ago}` or None
- [ ] AC2: Context injected into `indicators` dict before `generate_signal()` runs
- [ ] AC3: Recent stop-loss (< 3 days ago) adds `recent_sl_warning` flag to signal reasons
- [ ] AC4: Unit test: pair with stop_loss yesterday → `recent_sl_warning` in reasons

## Test Scenarios
> To be filled by Tester before sprint start.
- [ ] TS1: No prior trade → no warning
- [ ] TS2: Stop-loss yesterday → warning flag present
- [ ] TS3: Take-profit → no warning; positive context injected""",
        "sprint:S3,epic:E13,role:python-dev,type:story",
        "S3",
    ),
    # ── E14 ──────────────────────────────────────────────────────────────────
    (
        "[E14] S14.1.1 — Pipe-format AIE prompt builder",
        """## Story
**As a** developer,
**I want** the AIE prompt assembled from pipe-format signal blocks with a 15-pair cap,
**so that** token usage is minimised and the LLM receives structured, parseable input.

- **Sprint:** S3
- **Assigned to:** ai-engineer
- **Story points:** 3
- **BRD reference:** FR-A01, FR-T03, FR-T04
- **Architecture reference:** §2.3, §5
- **Code targets:** `src/agent/prompts.py`

## Acceptance Criteria
- [ ] AC1: `build_cycle_prompt(signals, context)` assembles PSV signal blocks
- [ ] AC2: Only BUY + SELL action pairs included; HOLD pairs filtered (max 15 BUY/SELL)
- [ ] AC3: Excess pairs filtered to HOLD with log `[AIE] Pair count limited to 15`
- [ ] AC4: Total prompt ≤ 2200 tokens verified by pre-call estimator
- [ ] AC5: Unit test: 20 BUY pairs → only top 15 by score included; 5 filtered to HOLD

## Test Scenarios
> To be filled by Tester before sprint start.
- [ ] TS1: 15 BUY/SELL pairs → prompt ≤ 2200 tokens
- [ ] TS2: 20 BUY pairs → 5 filtered to HOLD
- [ ] TS3: All HOLD pairs → empty prompt signal section (cycle skipped)""",
        "sprint:S3,epic:E14,role:ai-engineer,type:story",
        "S3",
    ),
    (
        "[E14] S14.1.2 — Pre-call token estimator",
        """## Story
**As a** developer,
**I want** prompt tokens counted before every LLM call using tiktoken,
**so that** the agent never exceeds the LLM's context window and fails silently.

- **Sprint:** S3
- **Assigned to:** ai-engineer
- **Story points:** 3
- **BRD reference:** FR-A02, FR-T02
- **Architecture reference:** §2.3
- **Code targets:** `src/agent/prompts.py`, `src/agent/trading_agent.py`

## Acceptance Criteria
- [ ] AC1: `estimate_tokens(text) -> int` uses `tiktoken cl100k_base`
- [ ] AC2: Called after `build_cycle_prompt()`; if > 2200 → HOLD-filter applied and prompt rebuilt
- [ ] AC3: Final token count logged at DEBUG
- [ ] AC4: Unit test: prompt with 2300 tokens → HOLD filter applied; rebuilt prompt ≤ 2200

## Test Scenarios
> To be filled by Tester before sprint start.
- [ ] TS1: 2100 token prompt → no filtering
- [ ] TS2: 2300 token prompt → filter applied → ≤ 2200
- [ ] TS3: After filtering still > 2200 → cycle skipped with log""",
        "sprint:S3,epic:E14,role:ai-engineer,type:story",
        "S3",
    ),
    (
        "[E14] S14.2.1 — Portfolio state block in prompt",
        """## Story
**As a** trading agent,
**I want** the current portfolio state (holdings, unrealised PnL, SL/TP distances) included in every LLM prompt,
**so that** the LLM does not propose duplicate entries or miss exit opportunities.

- **Sprint:** S3
- **Assigned to:** ai-engineer
- **Story points:** 3
- **BRD reference:** FR-A03
- **Architecture reference:** §2.3
- **Code targets:** `src/agent/prompts.py`, `main.py`

## Acceptance Criteria
- [ ] AC1: `build_portfolio_block(positions)` produces pipe-format block: `Pair|EntryPrice|CurrentPrice|UnrealisedPnL%|SLDist%|TPDist%`
- [ ] AC2: Block injected under `## PORTFOLIO_STATE` header
- [ ] AC3: LLM correctly avoids proposing entry for an already-held pair
- [ ] AC4: Unit test: ETH held at +5% → prompt contains ETH in portfolio block

## Test Scenarios
> To be filled by Tester before sprint start.
- [ ] TS1: Empty portfolio → block empty, no error
- [ ] TS2: ETH held → ETH in portfolio block; no re-entry proposed
- [ ] TS3: 3 positions → all three visible""",
        "sprint:S3,epic:E14,role:ai-engineer,type:story",
        "S3",
    ),
    (
        "[E14] S14.2.2 — Regime state block in prompt",
        """## Story
**As a** trading agent,
**I want** the active regime summary (playbook, BTC dominance, ADX median) in the LLM prompt,
**so that** the LLM's reasoning aligns with current macro conditions.

- **Sprint:** S3
- **Assigned to:** ai-engineer
- **Story points:** 2
- **BRD reference:** FR-A04
- **Architecture reference:** §2.3
- **Code targets:** `src/agent/prompts.py`

## Acceptance Criteria
- [ ] AC1: `build_regime_block(regime_state)` produces `MODE:{playbook}|REGIME:{regime}|ADX_MED:{val}|BTC_DOM:{pct}%|BTC_DOM_TREND:{rising/falling/flat}`
- [ ] AC2: Block injected under `## REGIME_STATE` header
- [ ] AC3: Unit test: risk_off playbook → block contains `MODE:risk_off`

## Test Scenarios
> To be filled by Tester before sprint start.
- [ ] TS1: All three playbooks → correct MODE string
- [ ] TS2: Null BTC dominance → `BTC_DOM:null|BTC_DOM_TREND:neutral`""",
        "sprint:S3,epic:E14,role:ai-engineer,type:story",
        "S3",
    ),
    (
        "[E14] S14.2.3 — Unfilled cluster context in prompt",
        """## Story
**As a** trading agent,
**I want** the prompt to list which sector clusters still have open slots under the Correlation Guard,
**so that** the LLM prioritises signals from diversified sectors.

- **Sprint:** S4
- **Assigned to:** ai-engineer
- **Story points:** 2
- **BRD reference:** FR-A05
- **Architecture reference:** §2.3
- **Code targets:** `src/agent/prompts.py`, `main.py`

## Acceptance Criteria
- [ ] AC1: `build_cycle_prompt()` receives `unfilled_clusters: list[str]` — sectors with capacity remaining
- [ ] AC2: Encoded as `open_sectors|{sector1},{sector2},...`; empty if all clusters full
- [ ] AC3: When all clusters full: prompt adds `"All sector clusters at capacity — reallocation only"`
- [ ] AC4: Unit test: 2 of 4 clusters available → correct clusters listed in prompt

## Test Scenarios
> To be filled by Tester before sprint start.
- [ ] TS1: 2 open clusters → both listed
- [ ] TS2: All full → capacity message shown""",
        "sprint:S4,epic:E14,role:ai-engineer,type:story",
        "S4",
    ),
    (
        "[E14] S14.2.4 — Persona system role injection",
        """## Story
**As a** trading agent,
**I want** the LLM system prompt to use the active persona's role and condensed rules,
**so that** LLM reasoning aligns with the risk appetite the operator has selected.

- **Sprint:** S4
- **Assigned to:** ai-engineer
- **Story points:** 3
- **BRD reference:** FR-A06, FR-T05
- **Architecture reference:** §2.3
- **Code targets:** `src/agent/prompts.py`

## Acceptance Criteria
- [ ] AC1: `SYSTEM_PROMPT` replaced with `build_system_prompt(persona_config: dict) -> str`
- [ ] AC2: System prompt includes persona_role + condensed trading rules (≤ 400 tokens total)
- [ ] AC3: Conservative: "protect capital"; Medium: "balance momentum"; High: "capture breakouts"
- [ ] AC4: Unit test: generate system prompt for all 3 personas; assert correct role string; assert ≤ 400 tokens each

## Test Scenarios
> To be filled by Tester before sprint start.
- [ ] TS1: All 3 personas → correct role string
- [ ] TS2: Each system prompt ≤ 400 tokens
- [ ] TS3: Regression — Conservative prompt does not change existing decision behaviour""",
        "sprint:S4,epic:E14,role:ai-engineer,type:story",
        "S4",
    ),
    # ── E15 ──────────────────────────────────────────────────────────────────
    (
        "[E15] S15.1.1 — Prune candidate identification",
        """## Story
**As a** risk manager,
**I want** to identify the weakest open position when the portfolio is gridlocked,
**so that** capital can be freed for higher-conviction signals.

- **Sprint:** S4
- **Assigned to:** python-dev
- **Story points:** 3
- **BRD reference:** FR-R01, FR-R02, FR-R05
- **Architecture reference:** §2.4
- **Code targets:** `src/risk/risk_manager.py`

## Acceptance Criteria
- [ ] AC1: `RiskManager.get_prune_candidate(open_positions, min_gain_pct, incoming_score) -> Optional[str]`
- [ ] AC2: Eligibility: `adx < 25` AND `pnl_pct < persona.min_profit_floor_pct * 1.5` AND not in deep loss
- [ ] AC3: Rank eligible by `adx ASC, pnl_pct ASC`; return first
- [ ] AC4: `reallocation_enabled == false` → always return None
- [ ] AC5: Unit test (3): no candidates → None; one eligible → correct pair; deep-loss excluded

## Test Scenarios
> To be filled by Tester before sprint start.
- [ ] TS1: No eligible positions → None
- [ ] TS2: One eligible → returned
- [ ] TS3: Deep-loss position → excluded""",
        "sprint:S4,epic:E15,role:python-dev,type:story",
        "S4",
    ),
    (
        "[E15] S15.1.2 — Capital reallocation execution flow",
        """## Story
**As a** trading agent,
**I want** the system to automatically close the prune candidate and execute the new buy,
**so that** high-conviction signals are captured even when the portfolio is at capacity.

- **Sprint:** S4
- **Assigned to:** python-dev
- **Story points:** 5
- **BRD reference:** FR-R01, FR-R05
- **Architecture reference:** §2.4
- **Code targets:** `src/risk/risk_manager.py`, `main.py`

## Acceptance Criteria
- [ ] AC1: Trigger: `positions_open >= max_open_positions` AND `incoming_score >= 8` AND `adx_incoming > 25` AND prune candidate exists
- [ ] AC2: `close_position(prune, exit_reason='reallocation')` called before `place_order(incoming)`
- [ ] AC3: No Telegram message sent (silent execution for Medium/High)
- [ ] AC4: Medium 6h cap enforced; Conservative always disabled
- [ ] AC5: If prune close fails → new buy blocked; error logged
- [ ] AC6: Unit test (5): full flow; conservative disabled; score < 8 skips; deep-loss protection; medium cap blocks

## Test Scenarios
> To be filled by Tester before sprint start.
- [ ] TS1: Full happy path — prune + new buy
- [ ] TS2: Conservative persona → reallocation disabled
- [ ] TS3: Medium 6h cap reached → reallocation blocked""",
        "sprint:S4,epic:E15,role:python-dev,type:story",
        "S4",
    ),
    (
        "[E15] S15.2.1 — Persona-scoped RSI bypass in validate_buy",
        """## Story
**As a** risk manager,
**I want** the RSI overbought veto to relax when ADX indicates strong trend conditions for Medium and High personas,
**so that** the agent participates in sustained institutional rallies.

- **Sprint:** S4
- **Assigned to:** python-dev
- **Story points:** 3
- **BRD reference:** FR-R03
- **Architecture reference:** §2.4
- **Code targets:** `src/risk/risk_manager.py`

## Acceptance Criteria
- [ ] AC1: `validate_buy()` reads `momentum_bypass_rsi` and `momentum_bypass_adx` from persona config
- [ ] AC2: Bypass only when `playbook == 'momentum'`
- [ ] AC3: Conservative: RSI 70 veto unchanged; Medium: RSI 75 when ADX > 25; High: RSI 80 when ADX > 25
- [ ] AC4: ADX below threshold → standard RSI 70 veto applies regardless of persona
- [ ] AC5: Unit test (6 cases): all persona × bypass active/inactive

## Test Scenarios
> To be filled by Tester before sprint start.
- [ ] TS1: Conservative + RSI 72 → blocked
- [ ] TS2: Medium + RSI 72 + ADX 28 + momentum playbook → allowed
- [ ] TS3: High + RSI 76 + ADX 20 → blocked (ADX below threshold)""",
        "sprint:S4,epic:E15,role:python-dev,type:story",
        "S4",
    ),
    (
        "[E15] S15.2.2 — PF escalation suspended in momentum playbook (Medium/High)",
        """## Story
**As a** risk manager,
**I want** Profit Factor auto-escalation suppressed in momentum playbook for Medium/High personas,
**so that** recovering altcoins are not doubly penalised at the start of their recovery.

- **Sprint:** S5
- **Assigned to:** python-dev
- **Story points:** 2
- **BRD reference:** FR-R06
- **Architecture reference:** §2.4
- **Code targets:** `src/risk/risk_manager.py`, `src/analysis/signals.py`

## Acceptance Criteria
- [ ] AC1: `get_effective_min_score(pair, playbook)` applies PF delta = 0 when `playbook == 'momentum'` AND `pf_escalation_momentum_suspend == true`
- [ ] AC2: Conservative: suspension never applies
- [ ] AC3: Log when suppression fires
- [ ] AC4: Unit test (4 cases): medium + momentum + low PF → no escalation; medium + ranging + low PF → +2 escalation

## Test Scenarios
> To be filled by Tester before sprint start.
- [ ] TS1: Medium + momentum + PF=0.5 → no escalation
- [ ] TS2: Medium + ranging + PF=0.5 → +2 escalation
- [ ] TS3: Conservative + momentum + PF=0.5 → +2 escalation (not suspended)""",
        "sprint:S5,epic:E15,role:python-dev,type:story",
        "S5",
    ),
    (
        "[E15] S15.2.3 — Early Momentum Accumulation score reduction (Medium/High)",
        """## Story
**As a** risk manager,
**I want** buy_min_score reduced by 1 when RSI is in the accumulation range [50,65] AND ADX > 25,
**so that** pairs showing early institutional accumulation can be entered before retail participation.

- **Sprint:** S5
- **Assigned to:** python-dev
- **Story points:** 3
- **BRD reference:** FR-R07
- **Architecture reference:** §2.4
- **Code targets:** `src/risk/risk_manager.py`

## Acceptance Criteria
- [ ] AC1: `get_effective_min_score()` applies −1 delta when `50 <= rsi <= 65` AND `adx > early_momentum_adx_min` AND `early_momentum_score_reduction > 0`
- [ ] AC2: Floor: `max(1, effective_min_score - early_momentum_score_reduction)`
- [ ] AC3: Conservative: `early_momentum_score_reduction = 0`; no delta
- [ ] AC4: Unit test (5): medium + RSI=55 + ADX=28 → −1; RSI=48 → no; ADX=22 → no; conservative → no; stacks with PF suspension

## Test Scenarios
> To be filled by Tester before sprint start.
- [ ] TS1: Medium + RSI=55 + ADX=28 → score reduced
- [ ] TS2: RSI=48 → no reduction
- [ ] TS3: Both PF suspension + early momentum active simultaneously""",
        "sprint:S5,epic:E15,role:python-dev,type:story",
        "S5",
    ),
    (
        "[E15] S15.3.1 — Loss velocity calculation and halt",
        """## Story
**As a** risk manager,
**I want** trading to halt when hourly loss rate exceeds the persona's velocity threshold,
**so that** the system stops absorbing losses during rapid adverse moves.

- **Sprint:** S5
- **Assigned to:** python-dev
- **Story points:** 5
- **BRD reference:** FR-R04
- **Architecture reference:** §2.4
- **Code targets:** `src/risk/risk_manager.py`, `main.py`, `src/notifications/notifier.py`

## Acceptance Criteria
- [ ] AC1: `check_velocity_circuit(trades_last_hour, portfolio_value) -> bool`
- [ ] AC2: `loss_rate_pct = abs(losses_last_hour) / portfolio_value * 100`
- [ ] AC3: Threshold from persona config; halt persisted to `agent_state` as `velocity_circuit_open_until`
- [ ] AC4: Telegram alert on open and on clear
- [ ] AC5: Independent of stop-loss circuit breaker
- [ ] AC6: Unit test (3): threshold exceeded → open; not exceeded → normal; expiry → clears

## Test Scenarios
> To be filled by Tester before sprint start.
- [ ] TS1: Loss rate exceeds threshold → circuit opens
- [ ] TS2: Rate below threshold → no halt
- [ ] TS3: Halt expires → trading resumes""",
        "sprint:S5,epic:E15,role:python-dev,type:story",
        "S5",
    ),
    # ── E16 ──────────────────────────────────────────────────────────────────
    (
        "[E16] S16.1.1 — Regime-to-playbook classifier",
        """## Story
**As a** trading agent,
**I want** the Orchestrator to select a playbook each cycle based on regime and portfolio state,
**so that** all agents apply the correct rule set for current market conditions.

- **Sprint:** S5
- **Assigned to:** python-dev
- **Story points:** 5
- **BRD reference:** FR-O01, FR-O05
- **Architecture reference:** §2.5
- **Code targets:** `main.py` (or new `src/agent/orchestrator.py`)

## Acceptance Criteria
- [ ] AC1: `Orchestrator.select_playbook(regime_state, adx_median, daily_pnl_pct, kill_switch) -> str`
- [ ] AC2: `risk_off` when `daily_pnl_pct <= -3` OR kill_switch active
- [ ] AC3: `momentum` when `adx_median >= 25` AND `regime_state == 'trending_up'`
- [ ] AC4: `ranging` default
- [ ] AC5: Playbook persisted to `agent_state`; transition logged + Telegram alert (on change only)
- [ ] AC6: Unit test (6): all three playbook transitions; no double-alert on stable cycle

## Test Scenarios
> To be filled by Tester before sprint start.
- [ ] TS1: risk_off triggered by daily PnL
- [ ] TS2: momentum triggered by ADX + regime
- [ ] TS3: Stable cycle → no Telegram alert""",
        "sprint:S5,epic:E16,role:python-dev,type:story",
        "S5",
    ),
    (
        "[E16] S16.1.2 — Playbook injected into RiskManager and prompts",
        """## Story
**As a** trading agent,
**I want** the active playbook propagated to both the RiskManager and the LLM prompt,
**so that** all layers apply the same regime-specific logic uniformly.

- **Sprint:** S5
- **Assigned to:** python-dev
- **Story points:** 3
- **BRD reference:** FR-O02
- **Architecture reference:** §2.5
- **Code targets:** `src/risk/risk_manager.py`, `src/agent/prompts.py`

## Acceptance Criteria
- [ ] AC1: `CycleContext.playbook` set by Orchestrator before all agents run
- [ ] AC2: `validate_buy()` applies playbook-based score delta (Ranging +1, Risk-Off +2, Momentum 0)
- [ ] AC3: `validate_buy()` applies playbook-based profit floor delta (Momentum ×0.8, Risk-Off ×1.5)
- [ ] AC4: LLM prompt includes playbook in risk constraints block
- [ ] AC5: Unit test: risk_off → buy_min_score += 2 + profit floor ×1.5

## Test Scenarios
> To be filled by Tester before sprint start.
- [ ] TS1: risk_off → stricter thresholds
- [ ] TS2: momentum → relaxed floor
- [ ] TS3: ranging → +1 score delta""",
        "sprint:S5,epic:E16,role:python-dev,type:story",
        "S5",
    ),
    (
        "[E16] S16.2.1 — Agent timeout detection and recovery",
        """## Story
**As a** system operator,
**I want** the Orchestrator to detect and recover from any agent taking > 30 seconds,
**so that** a stuck LLM call does not freeze the entire trading loop.

- **Sprint:** S5
- **Assigned to:** python-dev
- **Story points:** 3
- **BRD reference:** FR-O03
- **Architecture reference:** §2.5
- **Code targets:** `main.py`, `src/agent/trading_agent.py`

## Acceptance Criteria
- [ ] AC1: Each agent coroutine wrapped with `asyncio.wait_for(..., timeout=30.0)`
- [ ] AC2: On timeout: log `[ORCH] {agent_name} timed out after 30s — skipping cycle`
- [ ] AC3: 2+ consecutive timeouts → force risk_off + Telegram alert
- [ ] AC4: Counter resets on successful completion
- [ ] AC5: Unit test: mock AIE timeout → cycle skipped; risk_off on second timeout

## Test Scenarios
> To be filled by Tester before sprint start.
- [ ] TS1: Single timeout → cycle skipped, no playbook change
- [ ] TS2: Two consecutive → risk_off + Telegram
- [ ] TS3: Recovery → counter resets""",
        "sprint:S5,epic:E16,role:python-dev,type:story",
        "S5",
    ),
    # ── E17 ──────────────────────────────────────────────────────────────────
    (
        "[E17] S17.1.1 — MCP server with six read-only tools",
        """## Story
**As a** developer or agent,
**I want** to query Kryptos portfolio state, signals, universe, and persistence scores via MCP HTTP tools,
**so that** agents can query current state concurrently without interfering with the trading loop.

- **Sprint:** S6
- **Assigned to:** python-dev
- **Story points:** 8
- **BRD reference:** FR-M01, FR-M02, FR-M03, FR-M04
- **Architecture reference:** §2.6
- **Code targets:** `src/mcp/server.py`

## Acceptance Criteria
- [ ] AC1: HTTP-based MCP on `127.0.0.1:8092`
- [ ] AC2: Six tools: `get_portfolio_state`, `get_signal_snapshot`, `get_regime_state`, `get_agent_status`, `get_universe_state`, `get_persistence_scores`
- [ ] AC3: All tools return pipe-separated strings
- [ ] AC4: DB connection read-only (`?mode=ro`)
- [ ] AC5: Binds exclusively to `127.0.0.1`
- [ ] AC6: Responds within 500ms (S6 gate condition)

## Test Scenarios
> To be filled by Tester before sprint start.
- [ ] TS1: All 6 tools respond correctly
- [ ] TS2: Non-localhost connection rejected
- [ ] TS3: Response latency ≤ 500ms under normal load""",
        "sprint:S6,epic:E17,role:python-dev,type:story",
        "S6",
    ),
    # ── E18 ──────────────────────────────────────────────────────────────────
    (
        "[E18] S18.1.1 — kryptos persona CLI command group",
        """## Story
**As a** system operator,
**I want** CLI commands to view and switch the active persona,
**so that** I can change risk profile without editing config files.

- **Sprint:** S6
- **Assigned to:** python-dev
- **Story points:** 3
- **BRD reference:** FR-P02
- **Architecture reference:** §2.1
- **Code targets:** `src/cli/commands.py`, `kryptos.py`

## Acceptance Criteria
- [ ] AC1: `kryptos persona` shows active persona + all persona parameter summaries
- [ ] AC2: `kryptos persona set conservative|medium|high` updates `config.yaml`
- [ ] AC3: Switch takes effect next cycle; prompt warns about active cycle
- [ ] AC4: Switch logged to `kryptos-cli.log` with `actor=cli`
- [ ] AC5: Unit test: "switch to aggressive mode" → intent `persona_set`, entity `high`

## Test Scenarios
> To be filled by Tester before sprint start.
- [ ] TS1: Valid persona set → config updated
- [ ] TS2: Invalid persona → error message
- [ ] TS3: Switch logged to CLI audit log""",
        "sprint:S6,epic:E18,role:python-dev,type:story",
        "S6",
    ),
    (
        "[E18] S18.1.2 — kryptos regime CLI command",
        """## Story
**As a** system operator,
**I want** a CLI command showing current detected regime and active playbook,
**so that** I can understand why the agent is in conservative or aggressive mode.

- **Sprint:** S6
- **Assigned to:** python-dev
- **Story points:** 2
- **BRD reference:** FR-P02
- **Architecture reference:** §2.5
- **Code targets:** `src/cli/commands.py`, `src/cli/display.py`

## Acceptance Criteria
- [ ] AC1: `kryptos regime` shows: persona, playbook, regime, ADX median, BTC dominance trend, daily PnL, velocity circuit state
- [ ] AC2: Data from `agent_state` table
- [ ] AC3: Colour-coded: ranging=yellow, momentum=green, risk_off=red

## Test Scenarios
> To be filled by Tester before sprint start.
- [ ] TS1: All fields populated from agent_state
- [ ] TS2: Correct colour coding per playbook""",
        "sprint:S6,epic:E18,role:python-dev,type:story",
        "S6",
    ),
    (
        "[E18] S18.1.3 — Kryptos API persona endpoints",
        """## Story
**As a** UI developer,
**I want** GET/PUT /api/v2/persona endpoints,
**so that** the dashboard can display and update the active persona.

- **Sprint:** S6
- **Assigned to:** java-dev
- **Story points:** 3
- **BRD reference:** FR-P03
- **Architecture reference:** §2.1, §8
- **Code targets:** `kryptos-api/src/main/java/.../PersonaController.java`

## Acceptance Criteria
- [ ] AC1: `GET /api/v2/persona` returns active + available personas with config
- [ ] AC2: `PUT /api/v2/persona` with `{"persona": "medium"}` updates `agent_state`
- [ ] AC3: `main.py` checks `active_persona_override` each cycle
- [ ] AC4: Override cleared by `DELETE /api/v2/persona/override`
- [ ] AC5: Invalid value returns 400

## Test Scenarios
> To be filled by Tester before sprint start.
- [ ] TS1: GET returns all three personas
- [ ] TS2: PUT valid persona → 200
- [ ] TS3: PUT invalid persona → 400""",
        "sprint:S6,epic:E18,role:java-dev,type:story",
        "S6",
    ),
    (
        "[E18] S18.1.4 — Kryptos UI — Persona Panel",
        """## Story
**As a** user,
**I want** a persona selector panel on the dashboard,
**so that** I can see and change my active risk profile without the CLI.

- **Sprint:** S7
- **Assigned to:** ui-dev
- **Story points:** 3
- **BRD reference:** FR-P04
- **Architecture reference:** §9
- **Code targets:** `kryptos-ui/src/screens/Dashboard/`

## Acceptance Criteria
- [ ] AC1: Dashboard shows persona as labelled card (Conservative / Medium / High) with risk descriptor
- [ ] AC2: Clicking a card calls `PUT /api/v2/persona`; UI shows confirmation toast
- [ ] AC3: Header shows active playbook (`MODE: MOMENTUM`) with colour coding
- [ ] AC4: Agent status panel shows last cycle time, frozen pairs, velocity circuit state

## Test Scenarios
> To be filled by Tester before sprint start.
- [ ] TS1: Active persona highlighted correctly
- [ ] TS2: Switch → toast displayed
- [ ] TS3: Playbook mode label colour matches playbook""",
        "sprint:S7,epic:E18,role:ui-dev,type:story",
        "S7",
    ),
    # ── E19 ──────────────────────────────────────────────────────────────────
    (
        "[E19] S19.1.1 — Per-persona fast backtest",
        """## Story
**As a** developer,
**I want** `test_backtest.py --persona medium --no-llm` to run under Medium persona rules,
**so that** I can compare win rates across all three personas.

- **Sprint:** S8
- **Assigned to:** tester
- **Story points:** 3
- **BRD reference:** FR-P01
- **Architecture reference:** §13
- **Code targets:** `tests/test_backtest.py`

## Acceptance Criteria
- [ ] AC1: `--persona` flag accepted; loads persona config before backtest
- [ ] AC2: Output CSV includes `persona` column
- [ ] AC3: Summary shows persona name prominently
- [ ] AC4: `--all-personas` runs all three and shows comparative summary

## Test Scenarios
> To be filled by Tester before sprint start.
- [ ] TS1: medium persona → Medium rules applied
- [ ] TS2: --all-personas → 3 summary rows
- [ ] TS3: Conservative results identical to plain no-flag run""",
        "sprint:S8,epic:E19,role:tester,type:story",
        "S8",
    ),
    (
        "[E19] S19.1.2 — Regression test: conservative persona = v2 baseline",
        """## Story
**As a** developer,
**I want** a regression test confirming Conservative persona = v2 baseline behaviour,
**so that** the persona framework did not accidentally change existing trading decisions.

- **Sprint:** S8
- **Assigned to:** tester
- **Story points:** 3
- **BRD reference:** FR-P01
- **Architecture reference:** §13
- **Code targets:** `tests/test_persona_regression.py`

## Acceptance Criteria
- [ ] AC1: Run fast backtest: (a) Conservative persona, (b) v2 config
- [ ] AC2: Trade count, win rate, PnL differ by < 0.1%
- [ ] AC3: Test documented in `tests/test_persona_regression.py`

## Test Scenarios
> To be filled by Tester before sprint start.
- [ ] TS1: Conservative = v2 (trade count match)
- [ ] TS2: Conservative = v2 (PnL ± 0.1%)
- [ ] TS3: Medium differs from v2 (confirms persona differentiation)""",
        "sprint:S8,epic:E19,role:tester,type:story",
        "S8",
    ),
    # ── E20 ──────────────────────────────────────────────────────────────────
    (
        "[E20] S20.0.1 — Library Repositories Scaffold",
        """## Story
**As a** developer,
**I want** each shared library in its own git repository with standard packaging,
**so that** libraries can be installed and versioned independently.

- **Sprint:** S1
- **Assigned to:** python-dev
- **Story points:** 5
- **BRD reference:** FR-L01
- **Architecture reference:** §2.7
- **Code targets:** `mocha-python-audit`, `mocha-python-logging`, `mocha-python-ai`, `mocha-python-agent` (new repos)

## Acceptance Criteria
- [ ] AC1: Four repos created: `mocha-python-audit`, `mocha-python-logging`, `mocha-python-ai`, `mocha-python-agent`
- [ ] AC2: Each has `pyproject.toml`, `src/mocha_python_{name}/__init__.py`, `tests/`, `CHANGELOG.md`, `README.md`
- [ ] AC3: Each installable via `pip install git+https://...@v1.0.0`
- [ ] AC4: GitHub Actions CI: ruff + mypy + pytest on push/PR
- [ ] AC5: Initial semver tag `v1.0.0` after first passing CI
- [ ] AC6: Added to Kryptos `requirements.txt` with pinned `git+https@vX.Y.Z`

## Test Scenarios
> To be filled by Tester before sprint start.
- [ ] TS1: pip install in clean venv → no errors
- [ ] TS2: CI passes on each repo
- [ ] TS3: requirements.txt pinned entries""",
        "sprint:S1,epic:E20,role:python-dev,type:story",
        "S1",
    ),
    (
        "[E20] S20.1.1 — Audit Library",
        """## Story
**As a** developer,
**I want** a single AuditLogger class used by every agent,
**so that** audit records are consistent and no component writes raw SQL for audit purposes.

- **Sprint:** S2
- **Assigned to:** python-dev
- **Story points:** 5
- **BRD reference:** FR-L02, FR-L07
- **Architecture reference:** §2.7
- **Code targets:** `mocha-python-audit/src/mocha_python_audit/audit_logger.py`

## Acceptance Criteria
- [ ] AC1: `AuditLogger` with 8 interface methods; installable from git+https
- [ ] AC2: All agents use AuditLogger; no direct INSERT outside this class
- [ ] AC3: `audit_events` table with all required columns
- [ ] AC4: Concurrent write test: 5 threads → no corruption
- [ ] AC5: 500ms write timeout respected

## Test Scenarios
> To be filled by Tester before sprint start.
- [ ] TS1: 5-thread concurrent writes → all 5 rows present
- [ ] TS2: DB lock → timeout exception propagated
- [ ] TS3: component field present on every record""",
        "sprint:S2,epic:E20,role:python-dev,type:story",
        "S2",
    ),
    (
        "[E20] S20.1.2 — Integration Logging Library",
        """## Story
**As a** developer,
**I want** every outbound network call automatically logged with latency and status,
**so that** I can diagnose slow integrations without adding instrumentation per call site.

- **Sprint:** S2
- **Assigned to:** python-dev
- **Story points:** 5
- **BRD reference:** FR-L03
- **Architecture reference:** §2.7
- **Code targets:** `mocha-python-logging/src/mocha_python_logging/integration_logger.py`

## Acceptance Criteria
- [ ] AC1: `IntegrationLogger` + `@log_integration` decorator; installable
- [ ] AC2: All Groq, Kraken, CoinGecko, CoinGlass, Telegram calls wrapped
- [ ] AC3: Written to `/logs/integration.log`; 100MB × 5 rotation
- [ ] AC4: API keys / Authorization headers redacted to `[REDACTED]`
- [ ] AC5: `duration_ms` captured for sync and async functions

## Test Scenarios
> To be filled by Tester before sprint start.
- [ ] TS1: API key redacted in log
- [ ] TS2: duration_ms measured correctly for async function
- [ ] TS3: All required fields present in log record""",
        "sprint:S2,epic:E20,role:python-dev,type:story",
        "S2",
    ),
    (
        "[E20] S20.2.1 — AI Client Library",
        """## Story
**As an** agent implementer,
**I want** a single AIClient class that abstracts all LLM provider details,
**so that** retry/fallback logic is centralised and no agent imports groq/openai directly.

- **Sprint:** S3
- **Assigned to:** python-dev
- **Story points:** 5
- **BRD reference:** FR-L04, FR-L08
- **Architecture reference:** §2.7
- **Code targets:** `mocha-python-ai/src/mocha_python_ai/ai_client.py`

## Acceptance Criteria
- [ ] AC1: `AIClient.chat_with_tools(messages, tools, persona_params)` is the only public method
- [ ] AC2: 3 retry attempts, exponential backoff; attempt 3 uses fallback model
- [ ] AC3: qwen3 models receive `reasoning_effort: none` + `reasoning_format: hidden`
- [ ] AC4: `<think>…</think>` blocks stripped before returning to caller
- [ ] AC5: Every call logged via IntegrationLogger with latency + token counts
- [ ] AC6: Unit test: primary times out → fallback model used

## Test Scenarios
> To be filled by Tester before sprint start.
- [ ] TS1: Primary timeout → fallback used → fallback=True in response
- [ ] TS2: qwen3 model → correct extra_body keys sent
- [ ] TS3: No agent imports groq/openai directly after migration""",
        "sprint:S3,epic:E20,role:python-dev,type:story",
        "S3",
    ),
    (
        "[E20] S20.3.1 — Agent Bootstrap Library",
        """## Story
**As a** developer deploying the agent mesh,
**I want** each agent to self-register its Agent Card on startup,
**so that** the Orchestrator can discover live agents without hardcoded process lists.

- **Sprint:** S4
- **Assigned to:** python-dev
- **Story points:** 5
- **BRD reference:** FR-L05
- **Architecture reference:** §2.7
- **Code targets:** `mocha-python-agent/src/mocha_python_agent/agent_bootstrap.py`

## Acceptance Criteria
- [ ] AC1: `AgentCard` dataclass + `AgentBootstrap` class; installable
- [ ] AC2: `agent_registry` table in DB
- [ ] AC3: `start()` writes card; `stop()` sets status=stopped; `heartbeat()` updates timestamp
- [ ] AC4: `get_live_agents()` returns agents with heartbeat within 5 minutes
- [ ] AC5: Orchestrator aborts if any required agent absent at session start

## Test Scenarios
> To be filled by Tester before sprint start.
- [ ] TS1: Agent starts → card in registry
- [ ] TS2: Heartbeat > 5 min → not returned in get_live_agents
- [ ] TS3: Orchestrator aborts if required agent missing""",
        "sprint:S4,epic:E20,role:python-dev,type:story",
        "S4",
    ),
    (
        "[E20] S20.4.1 — Library integration into consuming projects",
        """## Story
**As a** developer,
**I want** all agents importing from installed library packages,
**so that** the codebase has no embedded copies of shared library code.

- **Sprint:** S4
- **Assigned to:** python-dev
- **Story points:** 3
- **BRD reference:** FR-L06
- **Architecture reference:** §2.7
- **Code targets:** `requirements.txt`, all `src/` agent modules

## Acceptance Criteria
- [ ] AC1: All four libraries in `requirements.txt` with pinned `git+https@vX.Y.Z`
- [ ] AC2: `grep -r "from src\\.lib" src/` returns zero matches
- [ ] AC3: All agents use fully qualified package imports
- [ ] AC4: `pip install -r requirements.txt` in clean venv completes without errors
- [ ] AC5: Full test suite passes with libraries from git+https pins

## Test Scenarios
> To be filled by Tester before sprint start.
- [ ] TS1: Clean venv install → no errors
- [ ] TS2: No direct src.lib imports remain
- [ ] TS3: Full test suite passes""",
        "sprint:S4,epic:E20,role:python-dev,type:story",
        "S4",
    ),
    # ── E21 ──────────────────────────────────────────────────────────────────
    (
        "[E21] S21.1.1 — DataCollector Runtime — WebSocket and Candle Buffer",
        """## Story
**As a** developer,
**I want** the Kraken WebSocket feed to run in an independent process writing to candle_buffer,
**so that** candle history is preserved across agent restarts and the trading loop is decoupled from network I/O.

- **Sprint:** S3
- **Assigned to:** python-dev
- **Story points:** 8
- **BRD reference:** FR-L09, FR-RT01, FR-RT02
- **Architecture reference:** §2.8
- **Code targets:** `src/runtime/data_collector.py`

## Acceptance Criteria
- [ ] AC1: `src/runtime/data_collector.py` launches as standalone process
- [ ] AC2: `candle_buffer` and `orderbook_snapshots` tables created
- [ ] AC3: Complete candle written within 5s of candle close for all active pairs
- [ ] AC4: `/health` endpoint responds within 200ms with `pairs_active` count
- [ ] AC5: QSA reads from `candle_buffer`; no in-process WebSocketFeed instance
- [ ] AC6: Integration test: kill/restart DataCollector → candle history intact; QSA resumes without gap

## Test Scenarios
> To be filled by Tester before sprint start.
- [ ] TS1: Candle written within 5s of close
- [ ] TS2: Kill + restart → no data gap
- [ ] TS3: /health responds ≤ 200ms""",
        "sprint:S3,epic:E21,role:python-dev,type:story",
        "S3",
    ),
    (
        "[E21] S21.1.2 — DataCollector Runtime — Feed Freeze Detection",
        """## Story
**As a** risk manager,
**I want** DataCollector to detect per-pair feed freezes,
**so that** the Orchestrator can exclude frozen pairs without waiting for QSA variance checks.

- **Sprint:** S4
- **Assigned to:** python-dev
- **Story points:** 3
- **BRD reference:** FR-Q02, FR-RT03
- **Architecture reference:** §2.8
- **Code targets:** `src/runtime/data_collector.py`

## Acceptance Criteria
- [ ] AC1: Freeze detection checks OHLCV variance over last N candles (default N=5)
- [ ] AC2: `/feed_status` REST endpoint: ok / frozen / stale per pair
- [ ] AC3: Freeze logged via AuditLogger
- [ ] AC4: Orchestrator skips frozen pairs (reads `/feed_status` once per cycle)
- [ ] AC5: Unit test: 5 identical close prices → pair classified as `frozen`

## Test Scenarios
> To be filled by Tester before sprint start.
- [ ] TS1: 5 identical candles → frozen
- [ ] TS2: Orchestrator skips frozen pair in cycle
- [ ] TS3: Other pairs unaffected by single frozen pair""",
        "sprint:S4,epic:E21,role:python-dev,type:story",
        "S4",
    ),
    (
        "[E21] S21.2.1 — FulfillmentService Runtime — Core REST API",
        """## Story
**As a** ROM Agent,
**I want** to submit buy and sell orders via a local REST API,
**so that** order execution is decoupled from the trading agent and fully audited independently.

- **Sprint:** S4
- **Assigned to:** python-dev
- **Story points:** 8
- **BRD reference:** FR-L10, FR-RT04
- **Architecture reference:** §2.8, §11
- **Code targets:** `src/runtime/fulfillment_service.py`

## Acceptance Criteria
- [ ] AC1: Launches with `--mode paper|live` flag
- [ ] AC2: `POST /fill` accepts FillRequest; returns FillResponse
- [ ] AC3: `GET /positions`, `GET /balance`, `GET /health` implemented
- [ ] AC4: All endpoints bound to `127.0.0.1` only; non-localhost → 403
- [ ] AC5: Bearer token auth on all except `/health`; missing token → 401

## Test Scenarios
> To be filled by Tester before sprint start.
- [ ] TS1: All endpoints respond correctly
- [ ] TS2: Non-localhost request → 403
- [ ] TS3: Missing Bearer token → 401""",
        "sprint:S4,epic:E21,role:python-dev,type:story",
        "S4",
    ),
    (
        "[E21] S21.2.2 — FulfillmentService Runtime — Fulfillment Audit",
        """## Story
**As a** compliance reviewer,
**I want** every order attempt written to fulfillment_audit before the response is returned,
**so that** there is a tamper-evident record of every execution decision.

- **Sprint:** S5
- **Assigned to:** python-dev
- **Story points:** 3
- **BRD reference:** FR-RT06
- **Architecture reference:** §2.8, §12.4
- **Code targets:** `src/runtime/fulfillment_service.py`

## Acceptance Criteria
- [ ] AC1: `fulfillment_audit` table created with all required columns
- [ ] AC2: Every `POST /fill` — regardless of outcome — produces one row before HTTP response
- [ ] AC3: `fulfillment_id` is UUID4; in both DB and HTTP response
- [ ] AC4: `duration_ms` accurate to ±5ms
- [ ] AC5: Unit test: Kraken REST times out → `execution_status=timeout` row written; caller receives 504

## Test Scenarios
> To be filled by Tester before sprint start.
- [ ] TS1: Successful fill → audit row written
- [ ] TS2: Rejection → audit row with execution_status=rejected
- [ ] TS3: Timeout → execution_status=timeout + 504 response""",
        "sprint:S5,epic:E21,role:python-dev,type:story",
        "S5",
    ),
    (
        "[E21] S21.2.3 — FulfillmentService Runtime — SL/TP Monitoring",
        """## Story
**As a** risk manager,
**I want** stop-loss and take-profit monitoring to run inside the FulfillmentService,
**so that** position protection is active even when the trading agent cycle is paused.

- **Sprint:** S5
- **Assigned to:** python-dev
- **Story points:** 5
- **BRD reference:** FR-RT05
- **Architecture reference:** §2.8
- **Code targets:** `src/runtime/fulfillment_service.py`

## Acceptance Criteria
- [ ] AC1: SL/TP loop runs every 60 seconds independent of agent cycle
- [ ] AC2: SL/TP trigger → close position → write fulfillment_audit + AuditLogger.log_trade()
- [ ] AC3: Trailing stop raise logic preserved
- [ ] AC4: Partial TP (50% at 50% of TP) preserved with partial_exited guard
- [ ] AC5: Integration test: paper position at $100; price hits $95 → closed within 60s; exit_reason=stop_loss

## Test Scenarios
> To be filled by Tester before sprint start.
- [ ] TS1: Stop-loss → position closed within 60s
- [ ] TS2: Trailing stop raised → labelled correctly
- [ ] TS3: Partial TP fires once; guarded from double-fire""",
        "sprint:S5,epic:E21,role:python-dev,type:story",
        "S5",
    ),
    # ── E22 ──────────────────────────────────────────────────────────────────
    (
        "[E22] S22.1.1 — Trend Persistence Engine — Database and Process",
        """## Story
**As a** developer,
**I want** a trend_persistence SQLite table and a RAA process that polls every 30 minutes,
**so that** candidate pairs accumulate Persistence Score data before any proposal is submitted.

- **Sprint:** S9
- **Assigned to:** ai-engineer
- **Story points:** 5
- **BRD reference:** FR-RAA01
- **Architecture reference:** §2.9
- **Code targets:** `src/runtime/research_analyst.py`

## Acceptance Criteria
- [ ] AC1: `trend_persistence`, `universe`, `universe_events` tables created
- [ ] AC2: RAA polls Kraken Ticker + CoinGecko every 30 min as independent process
- [ ] AC3: Ps computed and persisted; consecutive cycle counter resets when Ps < 1.5
- [ ] AC4: Unit test: 4 consecutive cycles Ps=1.8 → cycles_sustained=4; Ps drops to 1.2 → resets to 0

## Test Scenarios
> To be filled by Tester before sprint start.
- [ ] TS1: 4 consecutive passing cycles → cycles_sustained=4
- [ ] TS2: Ps drop → counter reset
- [ ] TS3: Process restarts → existing persistence data preserved""",
        "sprint:S9,epic:E22,role:ai-engineer,type:story",
        "S9",
    ),
    (
        "[E22] S22.1.2 — Universe Proposal API",
        """## Story
**As a** developer,
**I want** the RAA to submit PROPOSE(pair, replace_target?) to the Risk Manager when all gates pass,
**so that** the universe extends only with sufficient statistical evidence.

- **Sprint:** S9
- **Assigned to:** ai-engineer
- **Story points:** 5
- **BRD reference:** FR-RAA02
- **Architecture reference:** §2.9
- **Code targets:** `src/runtime/research_analyst.py`, `src/risk/risk_manager.py`

## Acceptance Criteria
- [ ] AC1: Proposal submitted only when Ps > 1.5 for ≥ 4 consecutive cycles
- [ ] AC2: Alpha spread gate: projected alpha > +2.0% over replacement target's 30-day return
- [ ] AC3: N < 35: replace_target optional; N = 35: replace_target required
- [ ] AC4: RM validates all gates; RAA never writes to universe directly
- [ ] AC5: Unit test: N=35, no replace_target → rejected with UNIVERSE_AT_CAP

## Test Scenarios
> To be filled by Tester before sprint start.
- [ ] TS1: All gates pass → ADD_PAIR universe_events row
- [ ] TS2: N=35 + no replace_target → UNIVERSE_AT_CAP rejection
- [ ] TS3: Alpha spread insufficient → proposal blocked""",
        "sprint:S9,epic:E22,role:ai-engineer,type:story",
        "S9",
    ),
    (
        "[E22] S22.2.1 — RAA Meme-Block Guardrail",
        """## Story
**As a** risk manager,
**I want** a hard-coded rule preventing MEME pairs from displacing FOUNDATIONAL pairs,
**so that** core anchors (BTC, ETH, SOL) can never be liquidated for speculative tokens.

- **Sprint:** S9
- **Assigned to:** python-dev
- **Story points:** 3
- **BRD reference:** FR-RAA03, FR-RAA06
- **Architecture reference:** §2.9
- **Code targets:** `src/risk/risk_manager.py`

## Acceptance Criteria
- [ ] AC1: MEME + replace_target=FOUNDATIONAL → immediate reject before reaching RM
- [ ] AC2: Rejection logged as MEME_BLOCK_REJECT in audit_events
- [ ] AC3: Rule enforced in Python code; no config or LLM override
- [ ] AC4: Unit test: BONK + replace=BTC → REJECT; BONK + replace=PEPE → allowed through to persistence gate

## Test Scenarios
> To be filled by Tester before sprint start.
- [ ] TS1: MEME displacing FOUNDATIONAL → rejected
- [ ] TS2: MEME displacing MEME → allowed
- [ ] TS3: No universe_events row on reject""",
        "sprint:S9,epic:E22,role:python-dev,type:story",
        "S9",
    ),
    (
        "[E22] S22.2.2 — SHIELDA Exception Management",
        """## Story
**As a** developer,
**I want** the RAA to self-correct on 422 errors and halt on stale feed,
**so that** bad data never silently corrupts the universe.

- **Sprint:** S9
- **Assigned to:** python-dev
- **Story points:** 3
- **BRD reference:** FR-RAA04, FR-RAA07
- **Architecture reference:** §2.9
- **Code targets:** `src/runtime/research_analyst.py`

## Acceptance Criteria
- [ ] AC1: 422 → self-correction prompt; reformat PSV and resubmit
- [ ] AC2: 3 consecutive 422s → SELF_CORRECT_FAILED logged; no retry until next cycle
- [ ] AC3: Kraken variance == 0 → all proposals for that pair halted; STALE_FEED_HALT logged
- [ ] AC4: Unit test: 3 simulated 422s → SELF_CORRECT_FAILED; 0 universe_events rows

## Test Scenarios
> To be filled by Tester before sprint start.
- [ ] TS1: 3 consecutive 422 → drop proposal
- [ ] TS2: Stale feed → pair halted; others unaffected
- [ ] TS3: Self-correction succeeds on 2nd attempt""",
        "sprint:S9,epic:E22,role:python-dev,type:story",
        "S9",
    ),
    (
        "[E22] S22.3.1 — Medium Persona RAA Integration",
        """## Story
**As a** trader using the Medium persona,
**I want** RAA to apply conservative conviction gates before proposing a new pair,
**so that** the universe only expands when a pair shows clear, sustained strength.

- **Sprint:** S9
- **Assigned to:** ai-engineer
- **Story points:** 3
- **BRD reference:** FR-RAA05
- **Architecture reference:** §2.9
- **Code targets:** `src/runtime/research_analyst.py`

## Acceptance Criteria
- [ ] AC1: RAA reads active persona; applies Medium-specific guardrails
- [ ] AC2: Medium RSI gate: 35–65; outside range → blocked
- [ ] AC3: Medium ADX gate: < 25; above → blocked
- [ ] AC4: Prune eligibility: held pair ADX < 15 for > 12 consecutive cycles
- [ ] AC5: Unit test: RSI=68 → RSI_OUT_OF_RANGE; RSI=52 + ADX=22 → passes

## Test Scenarios
> To be filled by Tester before sprint start.
- [ ] TS1: RSI=68 → blocked
- [ ] TS2: RSI=52 + ADX=22 → passes gates
- [ ] TS3: ADX < 15 for 10 cycles → NOT prunable; at 13 → prunable""",
        "sprint:S9,epic:E22,role:ai-engineer,type:story",
        "S9",
    ),
    (
        "[E22] S22.3.2 — High Persona RAA Integration",
        """## Story
**As a** trader using the High persona,
**I want** RAA to apply aggressive conviction gates and momentum-driven pruning,
**so that** the universe rapidly rotates towards highest-alpha opportunities.

- **Sprint:** S9
- **Assigned to:** ai-engineer
- **Story points:** 3
- **BRD reference:** FR-RAA08
- **Architecture reference:** §2.9
- **Code targets:** `src/runtime/research_analyst.py`

## Acceptance Criteria
- [ ] AC1: High RSI bypass: up to RSI 85 IFF ADX > 35 AND VWMA_Slope > 0
- [ ] AC2: Aggressive pruning: score > 8/28 → auto-include lowest-ADX holding as replace_target
- [ ] AC3: PSV format includes VWMA_Slope; MUST be non-null for all High proposals
- [ ] AC4: Position size: 3.0% with ATR-based multiplier
- [ ] AC5: Unit test: RSI=82 + ADX=38 + VWMA_Slope=+0.004 → authorised; RSI=82 + ADX=28 → blocked

## Test Scenarios
> To be filled by Tester before sprint start.
- [ ] TS1: RSI 82+ADX 38+positive slope → entry authorised
- [ ] TS2: RSI 82+ADX 28 → blocked (ADX too low)
- [ ] TS3: Score > 8 → lowest-ADX pair auto-added as replace_target""",
        "sprint:S9,epic:E22,role:ai-engineer,type:story",
        "S9",
    ),
    # ── E23 ──────────────────────────────────────────────────────────────────
    (
        "[E23] S23.1.1 — Audit Agent process container and outcome tracking",
        """## Story
**As a** developer,
**I want** an independent Audit Agent that evaluates all trading outcomes post-hoc,
**so that** all trading agents receive continuous performance feedback without consuming cycle budget.

- **Sprint:** S10
- **Assigned to:** python-dev
- **Story points:** 8
- **BRD reference:** FR-CLO01, FR-CLO02, FR-CLO03
- **Architecture reference:** §2.10
- **Code targets:** `src/runtime/audit_agent.py`

## Acceptance Criteria
- [ ] AC1: Process launches; REST health on port 8094; returns `{"status": "ok"}`
- [ ] AC2: 24h Validation Window per RAA proposal; PSV outcome vector written to audit_feedback on close
- [ ] AC3: Reprimand Vector written immediately on every RM 422/MEME_BLOCK
- [ ] AC4: 24h rollup populates playbook_performance and risk_decision_outcomes
- [ ] AC5: 6h rollup populates signal_accuracy
- [ ] AC6: Unit test: expected alpha +8%, actual −12% → FAIL_PUMP_DETECTION row
- [ ] AC7: Unit test: MEME_BLOCK → reprimand row within same sync cycle

## Test Scenarios
> To be filled by Tester before sprint start.
- [ ] TS1: Health endpoint responds
- [ ] TS2: PSV outcome vector written after 24h window
- [ ] TS3: MEME_BLOCK → immediate reprimand""",
        "sprint:S10,epic:E23,role:python-dev,type:story",
        "S10",
    ),
    (
        "[E23] S23.1.2 — RAA Self-Reflection Loop",
        """## Story
**As a** developer,
**I want** the RAA to read its last 50 outcome vectors and execute a four-phase reflection loop,
**so that** the RAA adjusts persistence thresholds based on historical accuracy.

- **Sprint:** S10
- **Assigned to:** ai-engineer
- **Story points:** 5
- **BRD reference:** FR-CLO04
- **Architecture reference:** §2.10
- **Code targets:** `src/runtime/research_analyst.py`

## Acceptance Criteria
- [ ] AC1: RAA reads last 50 audit_feedback rows (agent='RAA') at each poll cycle start
- [ ] AC2: LLM SELF_CRITIQUE call writes (agent, pair, lesson) to llm_reflection_log
- [ ] AC3: ps_threshold_override and sector_multiplier_json updated in confidence_state (DB_UPSERT phase)
- [ ] AC4: Updated ps_threshold_override used in next classify_pair call (META_PROMPT phase)
- [ ] AC5: Unit test: 5 consecutive FAIL_PUMP_DETECTION → ps_threshold_override raised 1.5→2.0

## Test Scenarios
> To be filled by Tester before sprint start.
- [ ] TS1: 5 pump failures → threshold raised
- [ ] TS2: No feedback rows → reflection skipped; no error
- [ ] TS3: Updated threshold used in next classify call""",
        "sprint:S10,epic:E23,role:ai-engineer,type:story",
        "S10",
    ),
    (
        "[E23] S23.1.3 — SHIELDA Confidence Reset and HITL Lock",
        """## Story
**As a** risk manager,
**I want** automatic confidence reset when RAA predictions are statistically inaccurate and HITL lock after repeated violations,
**so that** a miscalibrated RAA cannot continuously degrade universe quality.

- **Sprint:** S10
- **Assigned to:** python-dev
- **Story points:** 5
- **BRD reference:** FR-CLO05, FR-CLO06
- **Architecture reference:** §2.10
- **Code targets:** `src/runtime/audit_agent.py`, `src/risk/risk_manager.py`

## Acceptance Criteria
- [ ] AC1: Rolling 5-outcome std-dev > 3σ → CONFIDENCE_RESET event + confidence_reset_count++
- [ ] AC2: RAA reads CONFIDENCE_RESET → clears ps_threshold_override etc. to NULL
- [ ] AC3: 3 FOUNDATIONAL_REPLACEMENT_BLOCKs in 24h → substitution_tool_locked=1; locked_until_ts = now+24h; Telegram alert
- [ ] AC4: While locked: every PROPOSE_REPLACE → hitl_queue row PENDING; no universe_events row
- [ ] AC5: kryptos-api HITL endpoints: GET/POST approve/reject
- [ ] AC6: Unit test: 3 MEME_BLOCKs → locked; next proposal → hitl_queue PENDING; no universe change

## Test Scenarios
> To be filled by Tester before sprint start.
- [ ] TS1: 3σ deviation → confidence reset applied
- [ ] TS2: 3 MEME_BLOCKs → lock activated
- [ ] TS3: Locked + proposal → hitl_queue, not universe_events""",
        "sprint:S10,epic:E23,role:python-dev,type:story",
        "S10",
    ),
    (
        "[E23] S23.2.1 — Orchestrator playbook bias from performance history",
        """## Story
**As a** trader,
**I want** the Orchestrator to prefer historically profitable playbooks in the current regime,
**so that** playbook selection improves over time without human intervention.

- **Sprint:** S10
- **Assigned to:** python-dev
- **Story points:** 3
- **BRD reference:** FR-CLO07, FR-O04
- **Architecture reference:** §2.10, §2.5
- **Code targets:** `src/agent/orchestrator.py`, `main.py`

## Acceptance Criteria
- [ ] AC1: Orchestrator reads playbook_performance WHERE regime = current at cycle start
- [ ] AC2: ≥ 10 samples → +1 priority multiplier for playbooks with PF > 1.2
- [ ] AC3: No rows for current regime → default config playbook (no change)
- [ ] AC4: Playbook NEVER changes mid-cycle
- [ ] AC5: Unit test: trending_up — momentum PF=1.45 (n=15) → Orchestrator selects momentum

## Test Scenarios
> To be filled by Tester before sprint start.
- [ ] TS1: Sufficient history → higher-PF playbook selected
- [ ] TS2: No history → default playbook
- [ ] TS3: Mid-cycle change attempt → blocked""",
        "sprint:S10,epic:E23,role:python-dev,type:story",
        "S10",
    ),
    (
        "[E23] S23.2.2 — QSA signal driver accuracy multipliers",
        """## Story
**As a** developer,
**I want** QSA to apply per-driver accuracy multipliers based on historical predictive quality,
**so that** drivers with poor track records are de-weighted automatically.

- **Sprint:** S10
- **Assigned to:** python-dev
- **Story points:** 3
- **BRD reference:** FR-CLO08
- **Architecture reference:** §2.10
- **Code targets:** `src/analysis/signals.py`

## Acceptance Criteria
- [ ] AC1: QSA reads signal_accuracy at cycle start; merges weight_multiplier into driver scores
- [ ] AC2: Multiplier bounded [0.5, 1.5]; hard vetoes (RSI ≥ 70, volume floor) never affected
- [ ] AC3: Unit test: rsi_oversold accuracy 28% for BONK → weight_multiplier=0.5 applied
- [ ] AC4: Unit test: multiplier outside [0.5,1.5] in DB → clamped at read time

## Test Scenarios
> To be filled by Tester before sprint start.
- [ ] TS1: Low accuracy driver → 0.5 multiplier applied
- [ ] TS2: High accuracy driver → up to 1.5 multiplier
- [ ] TS3: Out-of-range value in DB → clamped, no exception""",
        "sprint:S10,epic:E23,role:python-dev,type:story",
        "S10",
    ),
    (
        "[E23] S23.2.3 — AIE negative few-shot injection",
        """## Story
**As a** developer,
**I want** AIE to include up to 3 recent loss-pattern examples from its reflection log in its system prompt,
**so that** the LLM avoids documented failure patterns without manual prompt engineering.

- **Sprint:** S10
- **Assigned to:** ai-engineer
- **Story points:** 3
- **BRD reference:** FR-CLO09, FR-A08
- **Architecture reference:** §2.10
- **Code targets:** `src/agent/prompts.py`

## Acceptance Criteria
- [ ] AC1: Fetches last 3 llm_reflection_log rows with injected=1 for agent='AIE'
- [ ] AC2: Injected as `PATTERNS TO AVOID` block at end of system prompt; ≤ 200 additional tokens
- [ ] AC3: If budget exceeded → oldest injected=1 record set to injected=0 first
- [ ] AC4: No active lessons → system prompt unchanged
- [ ] AC5: Unit test: 4 active lessons → oldest set to injected=0; only 3 remain

## Test Scenarios
> To be filled by Tester before sprint start.
- [ ] TS1: 3 active lessons → injected correctly
- [ ] TS2: 0 lessons → prompt unchanged
- [ ] TS3: Budget enforcement: 4 lessons → oldest deactivated""",
        "sprint:S10,epic:E23,role:ai-engineer,type:story",
        "S10",
    ),
    (
        "[E23] S23.2.4 — ROM advisory feedback display",
        """## Story
**As a** trader,
**I want** the UI Risk Management panel to show per-pair SL/TP calibration health,
**so that** I can make informed manual adjustments to SL/TP parameters.

- **Sprint:** S10
- **Assigned to:** java-dev
- **Story points:** 3
- **BRD reference:** FR-CLO10
- **Architecture reference:** §2.10
- **Code targets:** `kryptos-api/src/main/java/.../FeedbackController.java`

## Acceptance Criteria
- [ ] AC1: risk_decision_outcomes populated by Audit Agent daily rollup for pairs with ≥ 10 closed trades
- [ ] AC2: sl_hit_rate > 0.60 AND sample_count ≥ 20 → Telegram advisory with recommendation string
- [ ] AC3: ROM does NOT auto-adjust parameters — advisory only
- [ ] AC4: kryptos-api GET /feedback/risk returns risk_decision_outcomes sorted by sl_hit_rate DESC

## Test Scenarios
> To be filled by Tester before sprint start.
- [ ] TS1: sl_hit_rate > 60% → Telegram advisory sent
- [ ] TS2: < 20 samples → no advisory
- [ ] TS3: GET /feedback/risk → sorted by sl_hit_rate DESC""",
        "sprint:S10,epic:E23,role:java-dev,type:story",
        "S10",
    ),
    # ── E24 ──────────────────────────────────────────────────────────────────
    (
        "[E24] S24.1.1 — Full audit trail per trade",
        """## Story
**As a** trader,
**I want** to click any trade and see its complete four-block decision chain,
**so that** I can understand exactly why the bot entered or exited a position.

- **Sprint:** S11
- **Assigned to:** java-dev
- **Story points:** 5
- **BRD reference:** FR-CLO01
- **Architecture reference:** §9
- **Code targets:** `kryptos-api/src/main/java/.../TradeController.java`, `kryptos-ui/src/screens/TradeHistory/`

## Acceptance Criteria
- [ ] AC1: Trade list: pair, entry/exit price, PnL%, fees, duration, exit reason
- [ ] AC2: Detail panel: QSA signal block, AIE LLM reasoning, ROM guard outcomes, FulfillmentService fill block
- [ ] AC3: Each block links to raw audit_events row via cycle_id
- [ ] AC4: PnL includes round-trip friction ≈ 0.62% for Tier-1
- [ ] AC5: GET /trades/{id}/detail responds in < 500ms
- [ ] AC6: Unit test: known cycle_id → response includes all four blocks

## Test Scenarios
> To be filled by Tester before sprint start.
- [ ] TS1: All four blocks populated
- [ ] TS2: cycle_id links are correct
- [ ] TS3: Response < 500ms under load""",
        "sprint:S11,epic:E24,role:java-dev,type:story",
        "S11",
    ),
    (
        "[E24] S24.1.2 — Copilot Q&A: natural language trade explanation",
        """## Story
**As a** trader,
**I want** to type "Why was SOL/USD bought?" and receive a plain-English explanation,
**so that** I learn from the bot's decisions without reading raw audit logs.

- **Sprint:** S11
- **Assigned to:** java-dev
- **Story points:** 5
- **BRD reference:** FR-CLO01
- **Architecture reference:** §9
- **Code targets:** `kryptos-api/src/main/java/.../ExplainController.java`

## Acceptance Criteria
- [ ] AC1: GET /trades/{id}/explain fetches audit context → LLM prompt → 2–4 sentence narrative
- [ ] AC2: Explanation includes: signal drivers, LLM reasoning, exit reason + outcome assessment
- [ ] AC3: Chat input on Trade Detail panel; response rendered within 5 seconds
- [ ] AC4: CopilotQA LLM call logged to audit_events; MUST NOT influence trading
- [ ] AC5: Unit test: mocked audit context → /explain response contains entry reason, exit reason, outcome

## Test Scenarios
> To be filled by Tester before sprint start.
- [ ] TS1: Valid trade_id → narrative returned within 5s
- [ ] TS2: Explanation references correct signal drivers
- [ ] TS3: CopilotQA does not affect CycleContext or trading state""",
        "sprint:S11,epic:E24,role:java-dev,type:story",
        "S11",
    ),
    (
        "[E24] S24.2.1 — Real-time agent heartbeat and last-cycle summary",
        """## Story
**As an** operations engineer,
**I want** a dashboard panel showing all 5 agents' status and last cycle timestamps,
**so that** I immediately detect if any agent is stalled.

- **Sprint:** S11
- **Assigned to:** ui-dev
- **Story points:** 3
- **BRD reference:** FR-CLO01
- **Architecture reference:** §9
- **Code targets:** `kryptos-ui/src/screens/Dashboard/`

## Acceptance Criteria
- [ ] AC1: 5 agents shown with status badge (READY / DEGRADED / STALE), last heartbeat, last cycle
- [ ] AC2: STALE = heartbeat > 5 min ago; DEGRADED = no cycle event in > 35 min
- [ ] AC3: GET /agents/status polled every 30s via usePolling hook
- [ ] AC4: Unit test: Orchestrator HEARTBEAT > 5 min → GET /agents/status returns STALE

## Test Scenarios
> To be filled by Tester before sprint start.
- [ ] TS1: All agents READY → green badges
- [ ] TS2: Orchestrator heartbeat > 5 min → STALE badge
- [ ] TS3: Poll interval 30s verified""",
        "sprint:S11,epic:E24,role:ui-dev,type:story",
        "S11",
    ),
    (
        "[E24] S24.3.1 — Per-pair signal score history and driver breakdown",
        """## Story
**As a** trader,
**I want** to view a pair's signal score time-series over the last 48 hours with driver-level breakdowns,
**so that** I can validate the bot's signal logic and identify recurring entry patterns.

- **Sprint:** S11
- **Assigned to:** ui-dev
- **Story points:** 5
- **BRD reference:** FR-CLO01
- **Architecture reference:** §9
- **Code targets:** `kryptos-ui/src/screens/PairDetail/`

## Acceptance Criteria
- [ ] AC1: Signal Intelligence page: pair selector + 96-cycle time-series chart (48h)
- [ ] AC2: Click on chart point → driver breakdown panel (RSI, ADX, OBI, MACD, OBV, BB squeeze, candlestick patterns)
- [ ] AC3: GET /signals?pair=ETH%2FUSD&limit=96 → 96 records in ascending time order
- [ ] AC4: Unit test: 96 SIGNAL audit events → array of 96 with composite_score and driver_scores

## Test Scenarios
> To be filled by Tester before sprint start.
- [ ] TS1: 96 data points rendered
- [ ] TS2: Click → driver breakdown shows correct values
- [ ] TS3: All drivers shown even when score=0""",
        "sprint:S11,epic:E24,role:ui-dev,type:story",
        "S11",
    ),
    (
        "[E24] S24.4.1 — Active universe, RAA pipeline and recent proposals",
        """## Story
**As a** trader,
**I want** to see all active pairs with RAA metadata and the top persistence pipeline candidates,
**so that** I understand what the RAA is considering for addition or removal.

- **Sprint:** S11
- **Assigned to:** ui-dev
- **Story points:** 5
- **BRD reference:** FR-RAA01
- **Architecture reference:** §9
- **Code targets:** `kryptos-ui/src/screens/` (new Universe screen)

## Acceptance Criteria
- [ ] AC1: Universe panel: active pairs with classification, date added, current Ps
- [ ] AC2: Pipeline: top 10 candidates by Ps with cycles_sustained, estimated_cycles_to_gate
- [ ] AC3: Recent activity: last 5 ACCEPTED + last 5 REJECTED proposals with rejection reasons
- [ ] AC4: GET /universe returns all three sections in one JSON response
- [ ] AC5: HITL lock banner when substitution_tool_locked=1 with countdown

## Test Scenarios
> To be filled by Tester before sprint start.
- [ ] TS1: Active pairs listed correctly
- [ ] TS2: HITL lock banner visible when locked
- [ ] TS3: GET /universe < 1s response""",
        "sprint:S11,epic:E24,role:ui-dev,type:story",
        "S11",
    ),
    (
        "[E24] S24.5.1 — Audit Agent outcome visibility across all agents",
        """## Story
**As a** trader,
**I want** a Feedback dashboard showing per-agent performance metrics and active learning state,
**so that** I can see whether the closed-loop feedback system is improving decisions over time.

- **Sprint:** S11
- **Assigned to:** ui-dev
- **Story points:** 5
- **BRD reference:** FR-CLO02, FR-CLO03, FR-CLO07, FR-CLO08, FR-CLO09, FR-CLO10
- **Architecture reference:** §2.10, §9
- **Code targets:** `kryptos-ui/src/screens/` (new Feedback screen)

## Acceptance Criteria
- [ ] AC1: RAA section: last 10 outcome vectors, ps_threshold_override, HITL lock status, confidence_reset_count
- [ ] AC2: Orchestrator section: playbook_performance table sorted by PF DESC
- [ ] AC3: QSA section: top/bottom 10 drivers by accuracy_pct with current weight_multiplier
- [ ] AC4: AIE section: active PATTERNS TO AVOID lessons (≤ 3)
- [ ] AC5: ROM section: risk_decision_outcomes per pair; sl_hit_rate > 60% highlighted red
- [ ] AC6: GET /feedback/raa and GET /feedback/agents respond < 1s for 30 days history

## Test Scenarios
> To be filled by Tester before sprint start.
- [ ] TS1: All 5 sections rendered
- [ ] TS2: sl_hit_rate > 60% pair highlighted red
- [ ] TS3: GET /feedback/agents < 1s response""",
        "sprint:S11,epic:E24,role:ui-dev,type:story",
        "S11",
    ),
    (
        "[E24] S24.6.1 — Human-in-the-loop universe proposal approval UI",
        """## Story
**As a** trader,
**I want** a HITL queue page listing all pending RAA proposals requiring approval,
**so that** I can review and approve or reject proposals during a HITL lock period.

- **Sprint:** S11
- **Assigned to:** ui-dev
- **Story points:** 3
- **BRD reference:** FR-CLO06
- **Architecture reference:** §2.10, §9
- **Code targets:** `kryptos-ui/src/screens/` (new HITLQueue screen)

## Acceptance Criteria
- [ ] AC1: Queue page renders when hitl_queue has ≥ 1 PENDING row; shows pair, replace_target, Ps, alpha spread, rationale, reprimand history count
- [ ] AC2: Approve → POST /hitl-queue/{id}/approve → ADD_PAIR universe_events; status → APPROVED
- [ ] AC3: Reject → POST /hitl-queue/{id}/reject → PROPOSE_REJECTED universe_events; status → REJECTED
- [ ] AC4: HITL lock banner on ALL Kryptos UI pages when lock active — shows expiry + link to queue
- [ ] AC5: Unit test: approve 2, reject 1 → correct universe_events rows; all 3 hitl_queue rows updated

## Test Scenarios
> To be filled by Tester before sprint start.
- [ ] TS1: Approve → proposal executed
- [ ] TS2: Reject → proposal rejected with correct universe_events
- [ ] TS3: Banner visible on all pages while lock active""",
        "sprint:S11,epic:E24,role:ui-dev,type:story",
        "S11",
    ),
]


def main():
    ok = 0
    fail = 0
    for title, body_text, labels, sprint in ISSUES:
        if ci(title, body_text, labels, sprint):
            ok += 1
        else:
            fail += 1

    print(f"\n{'='*60}")
    print(f"Created: {ok}  |  Failed: {fail}  |  Total: {ok+fail}")
    if fail > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
