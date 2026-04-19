# Kryptos v3 — User Stories, Acceptance Criteria & Sprint Plan

**Document Type:** Product Backlog + Sprint Plan  
**Version:** 3.0  
**Date:** 19 April 2026  
**Reference:** docs/v2-agentic/BRD-v3.md, docs/v2-agentic/Architecture-Design-v3.md  
**Status:** Draft

---

## Epic Index

| Epic ID | Name | Priority | Sprint |
|---|---|---|---|
| E12 | Persona Framework | P0 | S1–S2 |
| E13 | QSA Agent — Data Resilience | P0 | S2–S3 |
| E14 | AIE Agent — Context Engineering | P0 | S3–S4 |
| E15 | ROM Agent — Capital Reallocation & Momentum Bypass | P0 | S4–S5 |
| E16 | Orchestrator Agent — Meta-Planner | P0 | S5 |
| E17 | MCP Server | P1 | S6 |
| E18 | CLI / UI / API — Persona + Agent Observability | P1 | S6–S7 |
| E19 | Testing & Backtest Validation | P0 | S7–S8 |
| E20 | Shared Libraries | P0 | S1–S4 |
| E21 | Separate Runtime Components (DataCollector + FulfillmentService) | P0 | S3–S5 |
| E22 | Research Analyst Agent (RAA) | P1 | S9 |
| E23 | Closed-Loop Optimization: Audit Agent + Feedback Loops | P1 | S10 |
| E24 | Kryptos UI: Decision Intelligence + Copilot Q&A | P2 | S11 |

---

## Sprint Plan Summary

| Sprint | Duration | Focus | Key Deliverables |
|---|---|---|---|
| S1 | 1 week | Foundation — Persona Config + Library Scaffold | Persona config schema, loader, runtime injection; `mocha-python-*` repo scaffolding |
| S2 | 1 week | QSA — Data Resilience + Audit/Logging Libraries | Winsorized EMA, variance heartbeat, `AuditLogger`, `IntegrationLogger` |
| S3 | 1 week | AIE — Pipe Format + Context + AI Client + DataCollector | Pipe-format builder, token estimator, `AIClient` library, DataCollector runtime |
| S4 | 1 week | AIE State-Aware LLM + ROM Reallocation + AgentBootstrap + FulfillmentService | State-aware prompt, ROM reallocation, `AgentBootstrap`, FulfillmentService core |
| S5 | 1 week | ROM — Momentum Bypass + Velocity CB + Orchestrator + FulfillmentService | Orchestrator, playbook selection, velocity circuit breaker, fulfillment audit, SL/TP monitor |
| S6 | 1 week | MCP Server + CLI/API/UI — Persona Endpoints | MCP server, CLI persona commands, API endpoints |
| S7 | 1 week | UI Enhancements | Persona panel, agent status, regime overlay |
| S8 | 1 week | Full Backtest Validation + Bug Fix | Per-persona backtest, signal calibration, regression suite |
| S9 | 1 week | Research Analyst Agent (RAA) | Trend persistence engine, universe proposal API, guardrails, persona integration |
| S10 | 1 week | Closed-Loop Optimization — Audit Agent + Feedback | Audit Agent process, self-reflection loop, SHIELDA reset, per-agent feedback integration |
| S11 | 1 week | UI Decision Intelligence + Copilot Q&A | Trade Explorer, agent dashboard, signal intelligence, universe manager, HITL queue UI |

---

## E12 — Persona Framework

**Goal:** Define and load three risk personas so every agent in the system operates
under the active persona's thresholds rather than a single global config.

---

### F12.1 — Persona Config and Loader

#### S12.1.1 — Persona config schema in config.yaml

**As a** system operator,  
**I want** each persona's risk parameters defined in `config.yaml` under `personas:`,  
**so that** switching persona changes all risk thresholds atomically without code changes.

**Acceptance Criteria:**
- [ ] AC1: `config.yaml` contains `agent.persona` (one of `conservative | medium | high`) and a `personas:` block with all three profiles
- [ ] AC2: Each persona profile contains: `buy_min_score`, `max_open_positions`, `max_position_pct`, `min_profit_floor_pct`, `rsi_overbought_veto`, `momentum_bypass_rsi`, `momentum_bypass_adx`, `reallocation_enabled`, `llm_temperature`, `llm_max_tokens`, `llm_system_role`, `velocity_circuit_breaker_pct`, `velocity_halt_hours`
- [ ] AC3: `conservative` persona values match current v2 production configuration exactly (no behaviour change at startup)
- [ ] AC4: Missing persona profile keys raise `ConfigError` at startup
- [ ] AC5: Unit test: `test_persona_config_loading.py` — loads all three profiles; asserts key presence; asserts conservative = current defaults

**Code targets:** `config.yaml`, `src/risk/risk_manager.py::_validate_config()`

---

#### S12.1.2 — Persona runtime injection into CycleContext

**As a** trading agent,  
**I want** the active persona's parameters injected into `CycleContext` at the start of every cycle,  
**so that** all agents (AIE, ROM) read persona-overridden values rather than global config.

**Acceptance Criteria:**
- [ ] AC1: `CycleContext` dataclass has a `persona_config: dict` field populated from `config["personas"][active_persona]`
- [ ] AC2: `main.py` reads `config["agent"]["persona"]` once per cycle (re-reads to support live switching)
- [ ] AC3: `RiskManager` initialises all thresholds from `CycleContext.persona_config` (not directly from global config)
- [ ] AC4: `TradingAgent` reads `temperature`, `max_tokens`, `system_role` from `CycleContext.persona_config`
- [ ] AC5: Unit test: `test_persona_injection.py` — cycles with three different personas; asserts ROM uses correct `buy_min_score` and `max_open_positions` for each

**Code targets:** `main.py`, `src/agent/trading_agent.py`, `src/risk/risk_manager.py`

---

#### S12.1.3 — Persona persistence in agent_state

**As a** system operator,  
**I want** the active persona written to `agent_state` table each cycle,  
**so that** the UI, API, and audit logs can reflect the persona that was active when a trade was made.

**Acceptance Criteria:**
- [ ] AC1: `main.py` writes `agent_state` key `active_persona` = persona name each cycle
- [ ] AC2: When `config["agent"]["concurrent_mode"]` is `true`, each persona process uses database `paper_trading_{persona}.db` (e.g., `paper_trading_medium.db`). When `false`, the standard `paper_trading.db` or `live_trading.db` is used
- [ ] AC3: `trades` table audit entry includes `persona` column for every new entry (schema migration required)
- [ ] AC4: Persona switch is logged: `[PERSONA] switched from {old} to {new} at cycle {cycle_id}`
- [ ] AC5: `Notifier.__init__` receives `persona_prefix: str` from `main.py`; when set, all Telegram messages prepend `[CONSERVATIVE]` / `[MEDIUM]` / `[HIGH]`
- [ ] AC6: Unit test: `concurrent_mode=true` for medium persona → DB path contains `paper_trading_medium.db`; `concurrent_mode=false` → standard path

**Code targets:** `main.py`, `src/storage/audit_logger.py`, `src/storage/database.py`, `src/notifications/notifier.py`

---

## E13 — QSA Agent — Data Resilience

**Goal:** Replace the static SMA volume floor with a Winsorized EMA and detect frozen data feeds.

---

### F13.1 — Winsorized EMA Volume Floor

#### S13.1.1 — Implement Winsorized EMA-14 in indicators.py

**As a** quantitative analyst,  
**I want** the volume floor to use a 14-period Winsorized EMA (95th percentile cap) instead of SMA-20,  
**so that** a historical liquidation spike does not inflate the floor and block organic accumulation.

**Acceptance Criteria:**
- [ ] AC1: `compute_indicators()` returns `winsorized_vol_ema` alongside existing `rolling_volume_p15`
- [ ] AC2: Winsorized EMA computation: cap each candle volume at p95 of last 100 candles; apply EMA-14 smoothing (`alpha = 2/15`)
- [ ] AC3: `config.yaml` controls: `qsa.volume_floor.algorithm` (`winsorized_ema` or `sma`); `period` (14); `winsorize_percentile` (95); `winsorize_lookback` (100)
- [ ] AC4: When `algorithm = sma`, behaviour is identical to v2 (backward compat mode)
- [ ] AC5: Volume Dead Zone veto in `signals.py` uses `winsorized_vol_ema` when `algorithm = winsorized_ema`, else `rolling_volume_p15`
- [ ] AC6: Unit tests (3): (a) spike neutralisation — one outlier volume does not lift floor above p75; (b) backward compat — `algorithm=sma` returns same result as v2; (c) edge case — fewer than 14 candles returns SMA fallback

**Code targets:** `src/analysis/indicators.py`, `src/analysis/signals.py`, `config.yaml`

---

#### S13.1.2 — Config-driven volume floor selection

**As a** system operator,  
**I want** the volume floor algorithm selectable in `config.yaml` without code changes,  
**so that** I can revert to SMA-20 instantly if Winsorized EMA causes unexpected behaviour.

**Acceptance Criteria:**
- [ ] AC1: `compute_indicators()` selects algorithm from `config["qsa"]["volume_floor"]["algorithm"]`
- [ ] AC2: Default is `winsorized_ema`; setting `sma` restores v2 behaviour exactly
- [ ] AC3: Invalid algorithm value raises `ConfigError`

**Code targets:** `src/analysis/indicators.py`, `config.yaml`

---

### F13.2 — OHLCV Variance Feed Heartbeat

#### S13.2.1 — Per-cycle variance check per pair

**As a** system operator,  
**I want** the system to detect frozen WebSocket feeds per pair each cycle,  
**so that** bad data from a stale feed is never used to generate a live trade signal.

**Acceptance Criteria:**
- [ ] AC1: After loading candles per pair, `compute_indicators()` calculates variance of OHLCV values across last 3 completed candles
- [ ] AC2: If variance == 0.0 across all OHLCV columns for a pair, `indicators["feed_status"] = "FROZEN"` else `"OK"`
- [ ] AC3: In `signals.py`, if `feed_status == "FROZEN"`, the signal is forced to `HOLD` regardless of score; reason = `"feed_frozen"`
- [ ] AC4: `[QSA] FEED_FROZEN {pair} — signal suppressed` logged at WARNING level
- [ ] AC5: Unit test: `test_feed_heartbeat.py` — feeds 3 identical candles; asserts `FROZEN` status; asserts signal forced to HOLD

**Code targets:** `src/analysis/indicators.py`, `src/analysis/signals.py`

---

#### S13.2.2 — Telegram alert on sustained feed freeze

**As a** system operator,  
**I want** a Telegram notification when a pair's feed is frozen for ≥ 3 consecutive cycles,  
**so that** I can investigate the WebSocket connection without waiting for a daily report.

**Acceptance Criteria:**
- [ ] AC1: `main.py` tracks `freeze_cycle_count[pair]` in loop state
- [ ] AC2: When `freeze_cycle_count[pair] >= config["qsa"]["feed_heartbeat"]["freeze_alert_cycles"]` (3), send Telegram via `notifier.send_alert()`
- [ ] AC3: Alert is sent once per freeze episode (not every cycle); repeat threshold resets when feed recovers
- [ ] AC4: If BTC/USD is frozen: trigger failover sequence (S13.2.3)
- [ ] AC5: Unit test: freeze_count increments correctly; alert sent on cycle 3; not sent again on cycle 4

**Code targets:** `main.py`, `src/notifications/notifier.py`

---

#### S13.2.3 — BTC/USD failover to secondary price source

**As a** trading agent,  
**I want** the system to fall back to CoinGecko for BTC/USD price when the Kraken feed is frozen,  
**so that** macro context (BTC price for regime detection) remains valid even during Kraken WS outages.

**Acceptance Criteria:**
- [ ] AC1: `qsa.failover.enabled: true` in config; `secondary: coingecko`; `failover_pairs: [BTC/USD]`
- [ ] AC2: When BTC/USD is FROZEN, system calls CoinGecko `/api/v3/simple/price?ids=bitcoin&vs_currencies=usd`
- [ ] AC3: Failover price is used only for regime classification and macro context; BTC/USD signal remains HOLD until feed recovers
- [ ] AC4: CoinGecko call is cached for 60 seconds (reuse existing `_btc_dom_cache` pattern)
- [ ] AC5: `[QSA] BTC/USD failover → CoinGecko price {price}` logged at INFO
- [ ] AC6: Unit test: mock frozen Kraken feed + live CoinGecko → asserts failover price used in regime context

**Code targets:** `main.py`, `src/exchange/websocket_feed.py`, `src/analysis/features.py`

---

### F13.3 — Volume Dead Zone Momentum Bypass

#### S13.3.1 — Suspend volume veto on confirmed momentum geometry (Medium/High)

**As a** quantitative analyst,  
**I want** the Volume Dead Zone veto suspended when MACD registers a fresh positive crossover AND price is above the upper Bollinger Band,  
**so that** the agent enters confirmed momentum breakouts where volume is intentionally low in the early accumulation phase.

**Acceptance Criteria:**
- [ ] AC1: `compute_indicators()` returns `macd_hist_prev` (prior candle MACD histogram value) alongside existing `macd_hist`
- [ ] AC2: In `signals.py`, for Medium and High personas: if `price > bb_upper` AND `macd_hist_prev < 0` AND `macd_hist >= 0`, set `vol_veto_active = False` for this pair this cycle regardless of volume ratio
- [ ] AC3: Conservative persona: volume veto always enforced; `volume_bypass_enabled = false` in config prevents bypass path execution
- [ ] AC4: When bypass fires, reason string `"vol_bypass_momentum_geometry"` appended to `signal["reasons"]`; logged at INFO `[QSA] VOL_BYPASS {pair} — MACD crossover + price > BB upper; veto suspended`
- [ ] AC5: Bypass does NOT disable OHLCV feed-freeze check (FR-Q04); `FEED_FROZEN` still forces HOLD
- [ ] AC6: Config flag `personas.{medium|high}.volume_bypass_enabled: true/false` controls bypass eligibility; default `true` for medium/high, `false` for conservative
- [ ] AC7: Unit test (4): medium persona + crossover + price > BB upper → bypass active; medium persona + crossover + price ≤ BB upper → no bypass; medium persona + no crossover (both candles positive) → no bypass; conservative persona + crossover + price > BB upper → veto still fires

**Code targets:** `src/analysis/indicators.py`, `src/analysis/signals.py`, `config.yaml`

---

## E14 — AIE Agent — Context Engineering

**Goal:** Transform the LLM prompt from a single-layer signal dump into a state-aware,
persona-specific context block using pipe-separated format within a 6,000 token budget.

---

### F14.1 — Pipe-Separated Prompt Format

#### S14.1.1 — Pipe-format signal block builder

**As a** trading agent,  
**I want** each pair's signal data encoded in pipe-separated format instead of JSON,  
**so that** the LLM prompt uses ≤ 90 tokens per pair rather than ~350.

**Acceptance Criteria:**
- [ ] AC1: New function `build_pipe_signal_block(signal: dict) -> str` in `src/agent/prompts.py`
- [ ] AC2: Output format: `pair|{pair}|score|{n}/28|direction|{BUY/SELL}|rsi|{rsi:.0f}|adx|{adx:.0f}|macd_hist|{h:.4f}|bb_pos|{b:.2f}|regime|{r}|price|{p:.4f}|tp_pct|{t}|sl_pct|5|max_buy_usd|{m:.0f}`
- [ ] AC3: Floating point values rounded to avoid token waste (price 4dp, percentages 1dp, scores integers)
- [ ] AC4: Old JSON format removed from `build_cycle_prompt()`; pipe format replaces it
- [ ] AC5: Unit test: `test_pipe_format.py` — 5 pairs; asserts output is pipe-separated; asserts token count per block < 100 (using tiktoken or character estimate)

**Code targets:** `src/agent/prompts.py`

---

#### S14.1.2 — Token estimator and pair count limiter

**As a** trading agent,  
**I want** the system to estimate prompt token count before sending the LLM call and trim signal pairs if needed,  
**so that** the 6,000 token budget is never exceeded.

**Acceptance Criteria:**
- [ ] AC1: `estimate_tokens(prompt: str) -> int` function using character count ÷ 4 approximation (no external tokenizer dependency)
- [ ] AC2: `build_cycle_prompt()` calls `estimate_tokens` after assembling all blocks; if > 5800, removes lowest-score BUY pairs one at a time until budget met
- [ ] AC3: SELL pairs are never removed (they protect capital)
- [ ] AC4: If even 1 pair pushes over budget: log `[AIE] Token budget exceeded; trimmed {n} pairs to fit {tokens}` at WARNING
- [ ] AC5: `prompt_tokens` field in `CycleContext` and `agent-llm-prompts.log`
- [ ] AC6: Unit test: construct 30-pair prompt; assert estimator triggers and produces ≤ 5800 estimated tokens

**Code targets:** `src/agent/prompts.py`, `src/agent/trading_agent.py`

---

### F14.2 — State-Aware Context Injection

#### S14.2.1 — Portfolio state block in prompt

**As an** LLM advisor,  
**I want** my prompt to include the current open positions with entry price, PnL, sector cluster, ADX, and distance to SL/TP,  
**so that** I never propose a buy for a pair already held or a position that is near stop-loss.

**Acceptance Criteria:**
- [ ] AC1: `build_cycle_prompt()` receives `open_positions: list` (from PaperBroker/KrakenClient)
- [ ] AC2: Each position encoded as pipe row: `pos|{pair}|entry|{e}|pnl_pct|{n}|pnl_usd|{n}|tp_dist_pct|{t}|sl_dist_pct|{s}|adx|{a}|cluster|{c}`
- [ ] AC3: Portfolio state block placed before signal blocks; prefixed with `## CURRENT PORTFOLIO ##`
- [ ] AC4: System prompt rule: "Do NOT propose_buy for any pair listed in CURRENT PORTFOLIO"
- [ ] AC5: Unit test: open ETH position; build prompt; assert prompt contains portfolio block; assert prompt rule present

**Code targets:** `src/agent/prompts.py`, `src/agent/trading_agent.py`

---

#### S14.2.2 — Risk constraints block in prompt

**As an** LLM advisor,  
**I want** a single-row risk constraints summary in my prompt (cash, positions used/max, kill switch, circuit, playbook, persona),  
**so that** I can adapt my strategy based on actual portfolio capacity rather than discovering limits at execution time.

**Acceptance Criteria:**
- [ ] AC1: Risk constraints row: `cash_usd|{c}|positions_open|{o}|positions_max|{m}|kill_switch|{0/1}|circuit_open|{0/1}|playbook|{p}|persona|{pe}`
- [ ] AC2: `positions_max` sourced from persona config (`max_open_positions`)
- [ ] AC3: When `positions_open >= positions_max`, prompt adds instruction: `"Portfolio at capacity. Only propose sells or reallocation candidates."`
- [ ] AC4: Unit test: build prompt with positions_open == positions_max; assert capacity-reached instruction present

**Code targets:** `src/agent/prompts.py`

---

#### S14.2.3 — Unfilled cluster context injection

**As an** LLM advisor,  
**I want** the prompt to list which sector clusters still have open slots under the Correlation Guard,  
**so that** I prioritise signals from diversified sectors rather than doubling down on already-saturated clusters.

**Acceptance Criteria:**
- [ ] AC1: `build_cycle_prompt()` receives `unfilled_clusters: list[str]` — sectors with < cluster capacity used
- [ ] AC2: Unfilled clusters encoded: `open_sectors|{sector1},{sector2},...`; empty if all clusters full
- [ ] AC3: When all clusters full: prompt adds `"All sector clusters at capacity — reallocation only"`
- [ ] AC4: Unit test: build prompt with 2 of 4 clusters available; assert clusters listed in prompt

**Code targets:** `src/agent/prompts.py`, `main.py`

---

#### S14.2.4 — Persona system role injection

**As a** trading agent,  
**I want** the LLM system prompt to use the active persona's role and condensed rules,  
**so that** LLM reasoning aligns with the risk appetite the operator has selected.

**Acceptance Criteria:**
- [ ] AC1: `SYSTEM_PROMPT` in `prompts.py` replaced with `build_system_prompt(persona_config: dict) -> str`
- [ ] AC2: System prompt includes: `persona_role` + condensed trading rules (≤ 400 tokens total)
- [ ] AC3: Conservative rules emphasise "protect capital" and "avoid early buys"
- [ ] AC4: Medium rules emphasise "balance momentum with protection" and "rotate sectors"
- [ ] AC5: High rules emphasise "capture breakouts" and "reallocation is authorised"  
- [ ] AC6: Unit test: generate system prompt for all 3 personas; assert correct role string; assert ≤ 400 tokens each

**Code targets:** `src/agent/prompts.py`

---

## E15 — ROM Agent — Capital Reallocation & Momentum Bypass

---

### F15.1 — Capital Reallocation Subroutine

#### S15.1.1 — Prune candidate identification

**As a** risk manager,  
**I want** to identify the weakest open position (lowest ADX, low PnL) when the portfolio is gridlocked,  
**so that** capital can be freed for a higher-conviction incoming signal.

**Acceptance Criteria:**
- [ ] AC1: `RiskManager.get_prune_candidate(open_positions, min_gain_pct, incoming_score) -> Optional[str]`
- [ ] AC2: Candidate eligibility: `adx < 25` AND `pnl_pct < persona.min_profit_floor_pct * 1.5` AND `pnl_pct > -stop_loss_pct / 2` (not in deep loss)
- [ ] AC3: Among eligible candidates, rank by `adx ASC NULLS LAST, pnl_pct ASC`; return first
- [ ] AC4: If `persona.reallocation_enabled == false`: always return `None`
- [ ] AC5: Unit test (3): no eligible candidates → None; one eligible candidate → correct pair; deep-loss position excluded

**Code targets:** `src/risk/risk_manager.py`

---

#### S15.1.2 — Capital reallocation execution flow

**As a** trading agent,  
**I want** the system to automatically close the prune candidate, free the capital, then execute the new buy,  
**so that** high-conviction signals are captured even when the portfolio is at capacity.

**Acceptance Criteria:**
- [ ] AC1: Trigger: `positions_open >= max_open_positions` AND `incoming_score >= 8` AND `adx_incoming > 25` AND `prune_candidate is not None`
- [ ] AC2: `close_position(prune_candidate, exit_reason='reallocation')` is called before `place_order(incoming_pair)`
- [ ] AC3: Reallocation executes silently (no Telegram confirmation message) for both Medium and High personas
- [ ] AC4: `[ROM] REALLOCATION: sold {prune} (ADX={a}, PnL={p}%) to fund {new} (score={s})` logged at INFO
- [ ] AC5: Medium persona 6-hour cap: `sum(usd_value for reallocation trades in past 6h) + prune.usd_value > portfolio_value * reallocation_max_pct_6h` → skip reallocation; log `[ROM] REALLOCATION cap reached (6h window)`
- [ ] AC6: Conservative persona: `reallocation_enabled=false` → reallocation always skipped; logged as `[ROM] Reallocation disabled for conservative persona`
- [ ] AC7: If prune close fails (exchange error): new buy is blocked; error logged; no orphaned position
- [ ] AC8: Unit test (5): full reallocation flow (paper mode); conservative disabled; incoming score < 8 skips; deep-loss protection; medium 6h cap blocks when limit reached

**Code targets:** `src/risk/risk_manager.py`, `main.py`

---

### F15.2 — Momentum Bypass RSI Rule

#### S15.2.1 — Persona-scoped RSI bypass in validate_buy

**As a** risk manager,  
**I want** the RSI overbought veto to relax when ADX indicates strong trend conditions for Medium and High personas,  
**so that** the agent participates in sustained institutional rallies rather than being blocked at RSI 70.

**Acceptance Criteria:**
- [ ] AC1: `validate_buy()` reads `persona_config["momentum_bypass_rsi"]` and `persona_config["momentum_bypass_adx"]`
- [ ] AC2: Bypass applies only when `playbook == 'momentum'`
- [ ] AC3: Conservative: `momentum_bypass_rsi = 70` (no change); veto fires at RSI ≥ 70 always
- [ ] AC4: Medium: `momentum_bypass_rsi = 75`, `momentum_bypass_adx = 25`; veto fires at RSI ≥ 75 when ADX > 25 (RSI 70–74 passes)
- [ ] AC5: High: `momentum_bypass_rsi = 80`, `momentum_bypass_adx = 25`; veto fires at RSI ≥ 80 when ADX > 25 (RSI 70–79 passes)
- [ ] AC6: Bypass only applies if `adx > persona.momentum_bypass_adx`; if ADX low, standard RSI 70 veto still applies
- [ ] AC7: Unit test (6): Conservative unchanged; Medium bypass active (RSI 72, ADX 28 → pass); Medium bypass inactive (RSI 72, ADX 18 → fail); High bypass active (RSI 76, ADX 32 → pass); High bypass inactive (RSI 76, ADX 20 → fail); non-momentum playbook → standard veto

**Code targets:** `src/risk/risk_manager.py`

---

#### S15.2.2 — Profit Factor escalation suspended in momentum playbook (Medium/High)

**As a** risk manager,  
**I want** the Profit Factor auto-escalation penalty suppressed globally when the active playbook is `momentum`,  
**so that** beaten-down altcoins recovering in a V-shaped rally are not doubly penalised by poor historical performance at the exact moment they are most likely to recover.

**Acceptance Criteria:**
- [ ] AC1: `RiskManager.get_effective_min_score(pair, playbook) -> int` applies PF delta of 0 when `playbook == 'momentum'` AND `persona_config["pf_escalation_momentum_suspend"] == true`
- [ ] AC2: In `ranging` and `risk_off` playbooks, PF escalation applies as before (`+1` when PF < 1.0; `+2` when PF < 0.7 with `>= min_trades` trades)
- [ ] AC3: Conservative persona: `pf_escalation_momentum_suspend = false`; PF escalation active in all playbooks
- [ ] AC4: Medium and High personas: `pf_escalation_momentum_suspend = true`; suspension fires on playbook=momentum
- [ ] AC5: Log `[ROM] PF_ESCALATION SUSPENDED — playbook=momentum; {pair} using persona default score {n}` at INFO when suppression applies to at least one pair
- [ ] AC6: `effective_min_score_used` column added to signal audit log so suppression is traceable
- [ ] AC7: Unit test (4): medium persona + momentum + pair PF=0.5 → no escalation (score threshold unchanged); medium persona + ranging + pair PF=0.5 → +2 escalation applies; conservative + momentum + pair PF=0.5 → +2 escalation applies; medium persona + momentum with playbook injected via CycleContext → correct branch taken

**Code targets:** `src/risk/risk_manager.py`, `src/analysis/signals.py`

---

#### S15.2.3 — Early Momentum Accumulation score reduction (Medium/High)

**As a** risk manager,  
**I want** a pair’s effective `buy_min_score` reduced by 1 when its RSI is in the accumulation range [50, 65] AND its ADX is above 25,  
**so that** pairs showing early institutional accumulation (trending but not yet overbought) can be entered before retail participation drives the RSI ceiling, front-running the move.

**Acceptance Criteria:**
- [ ] AC1: After PF suspension decision, `get_effective_min_score()` applies `−1` delta when `50 <= pair.rsi <= 65` AND `pair.adx > persona_config["early_momentum_adx_min"]` AND `persona_config["early_momentum_score_reduction"] > 0`
- [ ] AC2: Floor: `effective_min_score = max(1, effective_min_score - early_momentum_score_reduction)`
- [ ] AC3: Conservative persona: `early_momentum_score_reduction = 0`; no delta applied
- [ ] AC4: Medium/High personas: `early_momentum_score_reduction = 1`; `early_momentum_rsi_min = 50`; `early_momentum_rsi_max = 65`; `early_momentum_adx_min = 25`
- [ ] AC5: Log `[ROM] EARLY_MOMENTUM {pair} RSI={rsi:.0f} ADX={adx:.0f} — min_score reduced to {effective}` at INFO when reduction fires
- [ ] AC6: RSI and ADX range bounds are config-driven in `personas.{persona}.early_momentum_rsi_min/max` and `early_momentum_adx_min`
- [ ] AC7: Reduction is independent of PF suspension — both can apply in the same cycle (e.g., momentum playbook + eligible RSI/ADX → both fire); net effect is both PF not raised + score reduced by 1
- [ ] AC8: Unit test (5): medium + RSI=55 + ADX=28 → min_score reduced by 1; medium + RSI=48 + ADX=28 → no reduction (RSI below range); medium + RSI=55 + ADX=22 → no reduction (ADX below threshold); conservative + RSI=55 + ADX=28 → no reduction; high + RSI=64 + ADX=30 + PF suspension also active → both applied independently

**Code targets:** `src/risk/risk_manager.py`

---

### F15.3 — Velocity-Based Circuit Breaker

#### S15.3.1 — Loss velocity calculation and halt

**As a** risk manager,  
**I want** trading to halt when the hourly loss rate exceeds the persona's velocity threshold,  
**so that** the system stops absorbing losses during rapid adverse moves rather than waiting for the daily loss limit.

**Acceptance Criteria:**
- [ ] AC1: `RiskManager.check_velocity_circuit(trades_last_hour, portfolio_value) -> bool`
- [ ] AC2: `losses_last_hour = sum(pnl_usd for trades where closed_at > now-3600 AND pnl_usd < 0)`
- [ ] AC3: `loss_rate_pct = abs(losses_last_hour) / portfolio_value * 100`
- [ ] AC4: If `loss_rate_pct >= persona.velocity_circuit_breaker_pct`: return `True` (circuit open)
- [ ] AC5: Halt duration = `persona.velocity_halt_hours`; persisted to `agent_state` as `velocity_circuit_open_until`
- [ ] AC6: Halt state checked in main loop before LLM call; if open → skip cycle, log `[ROM] VELOCITY CIRCUIT OPEN until {timestamp}`
- [ ] AC7: Telegram alert sent on circuit open and on circuit clear
- [ ] AC8: Velocity circuit is independent of stop-loss circuit breaker (both can be simultaneously active)
- [ ] AC9: Unit test (3): threshold exceeded → circuit open; threshold not exceeded → normal; halt expiry → circuit clears

**Code targets:** `src/risk/risk_manager.py`, `main.py`, `src/notifications/notifier.py`

---

## E16 — Orchestrator Agent — Meta-Planner

---

### F16.1 — Playbook Selection

#### S16.1.1 — Regime-to-playbook classifier

**As a** trading agent,  
**I want** the Orchestrator to select a playbook (`ranging / momentum / risk_off`) each cycle based on regime and portfolio state,  
**so that** all agents apply the correct rule set for current market conditions.

**Acceptance Criteria:**
- [ ] AC1: `Orchestrator.select_playbook(regime_state, adx_median, daily_pnl_pct, kill_switch) -> str`
- [ ] AC2: `risk_off` when `daily_pnl_pct <= -3` OR `kill_switch_active`
- [ ] AC3: `momentum` when `adx_median >= 25` AND `regime_state in ['trending_up']`
- [ ] AC4: `ranging` all other cases (default)
- [ ] AC5: Playbook persisted to `agent_state` key `current_playbook`
- [ ] AC6: Playbook transition triggers log `[ORCH] Playbook: {old} → {new}` + Telegram alert (only on change, not every cycle)
- [ ] AC7: Unit test (6): all three playbook transitions; no double-alert on stable cycle

**Code targets:** `main.py` (or new `src/agent/orchestrator.py`)

---

#### S16.1.2 — Playbook injected into RiskManager and prompts

**As a** trading agent,  
**I want** the active playbook propagated to both the RiskManager (rule adjustments) and the LLM prompt (context),  
**so that** all layers apply the same regime-specific logic uniformly.

**Acceptance Criteria:**
- [ ] AC1: `CycleContext.playbook` field set by Orchestrator before QSA/AIE/ROM run
- [ ] AC2: `RiskManager.validate_buy()` applies playbook-based `buy_min_score` delta (Ranging +1, Risk-Off +2, Momentum 0)
- [ ] AC3: `RiskManager.validate_buy()` applies playbook-based `min_profit_floor_pct` delta (Momentum ×0.8, Risk-Off ×1.5)
- [ ] AC4: LLM prompt includes playbook in risk constraints block (existing pipe format)
- [ ] AC5: Unit test: risk_off playbook → buy_min_score raises by 2 + profit floor ×1.5

**Code targets:** `src/risk/risk_manager.py`, `src/agent/prompts.py`

---

### F16.2 — Exception Handler

#### S16.2.1 — Agent timeout detection and recovery

**As a** system operator,  
**I want** the Orchestrator to detect and recover from any agent taking > 30 seconds,  
**so that** a stuck LLM call or database deadlock does not freeze the entire trading loop.

**Acceptance Criteria:**
- [ ] AC1: Each agent coroutine wrapped with `asyncio.wait_for(agent.run(ctx), timeout=30.0)`
- [ ] AC2: On `asyncio.TimeoutError`: log `[ORCH] {agent_name} timed out after 30s — skipping cycle`
- [ ] AC3: On agent timeout: skip current cycle (no trades); SL/TP checks already ran (priority 0) so positions are protected
- [ ] AC4: On 2+ consecutive agent timeouts: force `risk_off` playbook; Telegram alert `[ORCH] Consecutive agent timeouts — entering risk-off`
- [ ] AC5: Counter resets when agent completes successfully
- [ ] AC6: Unit test: mock AIE timeout; assert cycle skipped; assert playbook not changed on first timeout; assert risk_off on second

**Code targets:** `main.py`, `src/agent/trading_agent.py`

---

## E17 — MCP Server

---

### F17.1 — kryptos-mcp HTTP server

#### S17.1.1 — MCP server with six read-only tools

**As a** developer or agent,  
**I want** to query Kryptos portfolio state, signals, universe, and persistence scores via MCP HTTP tools,  
**so that** Orchestrator, RAA, and ROM agents can query current state concurrently at runtime without interfering with the trading loop.

**Acceptance Criteria:**
- [ ] AC1: `src/mcp/server.py` implements HTTP-based MCP (JSON-RPC 2.0 over `POST /mcp`) on `127.0.0.1:8092`
- [ ] AC2: Tools: `get_portfolio_state`, `get_signal_snapshot`, `get_regime_state`, `get_agent_status`, `get_universe_state`, `get_persistence_scores`
- [ ] AC3: All tools return pipe-separated format strings
- [ ] AC4: Database connection is read-only (`sqlite3.connect(uri=True)` with `?mode=ro`)
- [ ] AC5: `python src/mcp/server.py --mode paper` starts the server; `--mode live` for live DB
- [ ] AC6: No authentication required; server MUST bind exclusively to `127.0.0.1`; never to `0.0.0.0`; access enforced at OS network layer
- [ ] AC7: `kryptos-mcp` and `/health` endpoint documented in `README.md` with example curl

---

## E18 — CLI / UI / API Changes

*(Detailed in `System-Interface-Changes-v3.md`; stories summarised here)*

#### S18.1.1 — `kryptos persona` CLI command group

**As a** system operator,  
**I want** CLI commands to view and switch the active persona,  
**so that** I can change risk profile interactively without editing config files.

**Acceptance Criteria:**
- [ ] AC1: `kryptos persona` — shows active persona + all persona parameter summaries
- [ ] AC2: `kryptos persona set conservative|medium|high` — updates `config.yaml` `agent.persona`
- [ ] AC3: Switch takes effect next cycle; prompt warns "Active cycle will complete under old persona"
- [ ] AC4: Switch logged to `kryptos-cli.log` with `actor=cli`
- [ ] AC5: Unit test: `test_nl_parser.py` — "switch to aggressive mode" → intent `persona_set`, entity `high`

---

#### S18.1.2 — `kryptos regime` CLI command

**As a** system operator,  
**I want** a CLI command showing the current detected regime and active playbook,  
**so that** I can understand why the agent is in conservative or aggressive mode.

**Acceptance Criteria:**
- [ ] AC1: `kryptos regime` — shows: persona, playbook, regime, ADX median, BTC dominance trend, daily PnL, velocity circuit state
- [ ] AC2: Data sourced from `agent_state` table
- [ ] AC3: Colour-coded display: `ranging` = yellow, `momentum` = green, `risk_off` = red

---

#### S18.1.3 — Kryptos API persona endpoint

**As a** UI developer,  
**I want** `GET /api/v2/persona` and `PUT /api/v2/persona` endpoints,  
**so that** the dashboard can display and update the active persona.

**Acceptance Criteria:**
- [ ] AC1: `GET /api/v2/persona` returns: `{"active": "conservative", "available": ["conservative","medium","high"], "config": {...}}`
- [ ] AC2: `PUT /api/v2/persona` with `{"persona": "medium"}` updates `agent_state` key `active_persona_override`
- [ ] AC3: `main.py` checks `active_persona_override` in `agent_state` each cycle; if present, uses it instead of config file
- [ ] AC4: Override persisted to `agent_state`; cleared by `DELETE /api/v2/persona/override`
- [ ] AC5: `PUT /api/v2/persona` with invalid value returns `400 Bad Request`
- [ ] AC6: Swagger/OpenAPI docs updated

---

#### S18.1.4 — Kryptos UI — Persona Panel

**As a** user,  
**I want** a persona selector panel on the dashboard,  
**so that** I can see and change my active risk profile without using the CLI.

**Acceptance Criteria:**
- [ ] AC1: Dashboard shows active persona as a labelled card (Conservative / Medium / High) with risk descriptor
- [ ] AC2: Clicking a persona card calls `PUT /api/v2/persona`; UI shows confirmation toast
- [ ] AC3: Dashboard header shows active playbook (`MODE: MOMENTUM`) with colour coding
- [ ] AC4: Agent status panel shows last cycle time, feed-frozen pairs, velocity circuit state

---

## E19 — Testing & Backtest Validation

---

#### S19.1.1 — Per-persona fast backtest

**As a** developer,  
**I want** `test_backtest.py --persona medium --no-llm` to run the backtest under Medium persona rules,  
**so that** I can compare win rates and PnL across all three personas before deploying changes.

**Acceptance Criteria:**
- [ ] AC1: `--persona` flag accepted; loads persona config before backtest run
- [ ] AC2: Output CSV includes `persona` column in trade results
- [ ] AC3: Summary report shows persona name prominently
- [ ] AC4: Separate summary rows for each persona in combined run (`--all-personas`)

---

#### S19.1.2 — Regression test: conservative persona = v2 baseline

**As a** developer,  
**I want** a regression test confirming that Conservative persona produces identical decisions to the v2 baseline configuration,  
**so that** I know the persona framework did not accidentally change existing behaviour.

**Acceptance Criteria:**
- [ ] AC1: Run fast backtest on same dataset with (a) Conservative persona, (b) v2 config
- [ ] AC2: Trade count, win rate, and PnL differ by < 0.1% (float precision only)
- [ ] AC3: Test documented in `tests/test_persona_regression.py`

---

---

## E20 — Shared Libraries

> Sprint allocation: S1 (Repo scaffolding), S2 (Audit + Logging), S3 (AI Client), S4 (Agent Bootstrap), S4 (Consuming project integration)

---

#### S20.0.1 — Library Repositories Scaffold

**As a** developer,  
**I want** each shared library created as its own independent git repository with standard packaging,  
**so that** the libraries can be installed in any project and versioned independently.

**Acceptance Criteria:**
- [ ] AC1: Four repositories created: `mocha-python-audit`, `mocha-python-logging`, `mocha-python-ai`, `mocha-python-agent`
- [ ] AC2: Each repo contains: `pyproject.toml` (hatchling build backend), `src/mocha_python_{name}/__init__.py`, `tests/`, `CHANGELOG.md`, `README.md`
- [ ] AC3: Each library is installable in a clean virtual environment via `pip install git+https://github.com/{org}/{repo}.git@v1.0.0` with no errors
- [ ] AC4: GitHub Actions CI workflow present in each repo; runs ruff lint + mypy + pytest on every push and pull request
- [ ] AC5: Initial semver tag `v1.0.0` applied to each repository after first passing CI run
- [ ] AC6: No library module imports from any project-specific path (`src/`, `config.yaml`); all dependencies injected at construction time
- [ ] AC7: All four libraries added to Kryptos `requirements.txt` with pinned `git+https@vX.Y.Z` entries

---

#### S20.1.1 — Audit Library

**As a** developer,  
**I want** a single `AuditLogger` class used by every agent and runtime component,  
**so that** audit records are consistent and no component writes raw SQL for audit purposes.

**Acceptance Criteria:**
- [ ] AC1: `mocha-python-audit` repository created with `pyproject.toml`; package installable via `pip install git+https://...@v1.0.0`; `AuditLogger` class present with all eight interface methods (`log_cycle`, `log_signal`, `log_trade`, `log_balance_snapshot`, `log_error`, `log_circuit_breaker`, `log_fulfillment`, `log_agent_card`)
- [ ] AC2: All QSA, AIE, ROM, and Orchestrator modules instantiate `AuditLogger`; no direct `INSERT INTO audit_*` calls remain outside this class
- [ ] AC3: `audit_events` table created in DB schema with all required columns (see §12.3)
- [ ] AC4: Concurrent write test: 5 threads calling `log_signal` simultaneously — no data corruption, all 5 records visible
- [ ] AC5: 500ms write timeout respected; test simulates locked DB and confirms timeout exception propagated cleanly
- [ ] AC6: `component` tag present on every record; filterable by `event_type` and `cycle_id`

---

#### S20.1.2 — Integration Logging Library

**As a** developer,  
**I want** every outbound network call automatically logged with latency and status,  
**so that** I can diagnose slow or failing integrations without adding instrumentation to each call site.

**Acceptance Criteria:**
- [ ] AC1: `mocha-python-logging` repository created with `pyproject.toml`; package installable via `pip install git+https://...@v1.0.0`; `IntegrationLogger` class and `@log_integration` decorator present
- [ ] AC2: All Groq calls, Kraken REST calls, CoinGecko calls, CoinGlass calls, and Telegram calls are wrapped with `@log_integration`
- [ ] AC3: Output written to `/logs/integration.log` as JSON lines; rotating 100 MB × 5
- [ ] AC4: API key fields and Authorization headers are redacted to `[REDACTED]` before logging
- [ ] AC5: Decorator correctly captures `duration_ms` for both sync and async functions
- [ ] AC6: Log record includes all required fields: `timestamp`, `component`, `service`, `operation`, `request_summary`, `response_status`, `duration_ms`, `status`, `error_detail`, `cycle_id`

---

#### S20.2.1 — AI Client Library

**As an** agent implementer,  
**I want** a single `AIClient` class that abstracts all LLM provider details,  
**so that** no agent needs to know whether it is calling Groq or Ollama, and retry/fallback logic is centralised.

**Acceptance Criteria:**
- [ ] AC1: `mocha-python-ai` repository created with `pyproject.toml`; package installable via `pip install git+https://...@v1.0.0`; `AIClient` and `ModelConfig` classes present
- [ ] AC2: `chat_with_tools(messages, tools, persona_params)` is the only public method agents call; provider selection is internal
- [ ] AC3: Retry logic implemented: 3 attempts, exponential backoff; attempt 3 uses fallback model
- [ ] AC4: qwen3 models receive `reasoning_effort: none` + `reasoning_format: hidden` in `extra_body`; this is not caller-configurable
- [ ] AC5: `<think>…</think>` blocks stripped from raw output before returning to caller
- [ ] AC6: Every LLM call logged via `IntegrationLogger` with latency and token counts
- [ ] AC7: Unit test: primary Groq call times out → fallback model used → `fallback=True` in response
- [ ] AC8: No agent module imports `groq`, `openai`, or `ollama` directly after this story is complete

---

#### S20.3.1 — Agent Bootstrap Library

**As a** developer deploying the agent mesh,  
**I want** each agent to self-register its Agent Card on startup,  
**so that** the Orchestrator and MCP server can discover live agents without hardcoded process lists.

**Acceptance Criteria:**
- [ ] AC1: `mocha-python-agent` repository created with `pyproject.toml`; package installable via `pip install git+https://...@v1.0.0`; `AgentCard` dataclass and `AgentBootstrap` class present
- [ ] AC2: `agent_registry` table created in DB schema with all required columns (see §12.5)
- [ ] AC3: `start()` writes Agent Card to `agent_registry`; `stop()` sets `status=stopped`
- [ ] AC4: `heartbeat()` updates `last_heartbeat`; called at the end of each agent cycle
- [ ] AC5: `get_live_agents()` returns only agents with `status=ready` and `last_heartbeat` within 5 minutes
- [ ] AC6: Orchestrator calls `get_live_agents()` at session start; aborts if any required agent is absent
- [ ] AC7: MCP `get_agent_status` tool reads from `agent_registry` and returns current status per agent

---

#### S20.4.1 — Library Integration into Consuming Projects

**As a** developer working in Kryptos (or any future project),  
**I want** all agents and runtime components importing from the installed library packages,  
**so that** the codebase has no embedded copies of shared library code and version management is explicit.

**Acceptance Criteria:**
- [ ] AC1: All four libraries present in `requirements.txt` with pinned `git+https@vX.Y.Z` entries; no unpinned `>=` references
- [ ] AC2: `grep -r "from src\.lib\|import src\.lib" src/` returns zero matches in the Kryptos repository
- [ ] AC3: All QSA, AIE, ROM, Orchestrator, DataCollector, and FulfillmentService modules use fully qualified package imports (e.g., `from mocha_python_audit import AuditLogger`, `from mocha_python_logging import log_integration`)
- [ ] AC4: `pip install -r requirements.txt` in a clean virtual environment completes without errors
- [ ] AC5: Full test suite passes with all four libraries installed from `git+https` pins (not from editable local installs)
- [ ] AC6: CI pipeline re-installs all dependencies from scratch on each run; no implicit local package discovery allowed

---

## E21 — Separate Runtime Components

> Sprint allocation: S3–S4 (DataCollector), S4–S5 (FulfillmentService)

---

#### S21.1.1 — DataCollector Runtime — WebSocket and Candle Buffer

**As a** developer,  
**I want** the Kraken WebSocket feed to run in an independent process writing to `candle_buffer`,  
**so that** candle history is preserved across agent restarts and the trading loop is decoupled from network I/O.

**Acceptance Criteria:**
- [ ] AC1: `src/runtime/data_collector.py` created; launches as standalone process with no agent dependencies
- [ ] AC2: `candle_buffer` table created in DB schema (pair, ts, OHLCV, is_closed, inserted_at)
- [ ] AC3: `orderbook_snapshots` table created in DB schema (pair, ts, best_bid, best_ask, OBI)
- [ ] AC4: DataCollector writes a completed candle row within 5 seconds of candle close for all active pairs
- [ ] AC5: `/health` endpoint responds within 200ms with `pairs_active` count and `last_write_ts`
- [ ] AC6: QSA Agent reads candles from `candle_buffer` table rather than maintaining its own `WebSocketFeed` instance
- [ ] AC7: Integration test: kill DataCollector → 3 minutes later restart → candle history intact; QSA resumes without data gap

---

#### S21.1.2 — DataCollector Runtime — Feed Freeze Detection

**As a** risk manager,  
**I want** the DataCollector to detect per-pair feed freezes and report them,  
**so that** the Orchestrator can exclude frozen pairs from the cycle without waiting for QSA variance checks.

**Acceptance Criteria:**
- [ ] AC1: Feed freeze detection checks OHLCV variance over last N candles (configurable, default N=5)
- [ ] AC2: Frozen pair status exposed via `/feed_status` REST endpoint as `ok` / `frozen` / `stale`
- [ ] AC3: Freeze event written via `AuditLogger.log_error("DataCollector", ...)` with pair name
- [ ] AC4: Orchestrator skips frozen pairs in the cycle preamble (reads `/feed_status` once per cycle)
- [ ] AC5: Unit test: candle buffer seeded with 5 identical close prices → pair correctly classified as `frozen`

---

#### S21.2.1 — FulfillmentService Runtime — Core REST API

**As a** ROM Agent,  
**I want** to submit buy and sell orders via a local REST API,  
**so that** order execution is decoupled from the trading agent and fully audited independently.

**Acceptance Criteria:**
- [ ] AC1: `src/runtime/fulfillment_service.py` created; launches with `--mode paper|live` flag
- [ ] AC2: `POST /fill` accepts `FillRequest` JSON; returns `FillResponse` JSON (schemas per §11.2)
- [ ] AC3: `GET /positions` returns list of open positions with pair, entry_price, usd_value, unrealised_pnl
- [ ] AC4: `GET /balance` returns `{cash_usd, total_usd, open_positions_count}`
- [ ] AC5: `GET /health` returns `{status, mode}` with no authentication required
- [ ] AC6: All endpoints bound to `127.0.0.1` only; connection from non-localhost IP returns 403
- [ ] AC7: Bearer token authentication enforced on all endpoints except `/health`; missing/invalid token returns 401

---

#### S21.2.2 — FulfillmentService Runtime — Fulfillment Audit

**As a** compliance reviewer,  
**I want** every order attempt — including rejections and timeouts — written to `fulfillment_audit` before the response is returned,  
**so that** there is a complete, tamper-evident record of every execution decision.

**Acceptance Criteria:**
- [ ] AC1: `fulfillment_audit` table created in DB schema with all required columns (see §12.4)
- [ ] AC2: Every `POST /fill` — regardless of outcome (filled, rejected, timeout, error) — produces one row in `fulfillment_audit` before the HTTP response is sent
- [ ] AC3: `fulfillment_id` is UUID4, unique, and included in both the DB record and the HTTP response
- [ ] AC4: `duration_ms` measured from request receipt to response send; accurate to ±5ms
- [ ] AC5: For live mode: `kraken_order_id` populated when Kraken confirms the order; null on error
- [ ] AC6: For paper mode: `kraken_order_id` is null; `execution_status` is `filled` or `rejected`
- [ ] AC7: `request_json` stores full `FillRequest`; `response_json` stores full `FillResponse`
- [ ] AC8: Unit test: Kraken REST times out after 5s → `execution_status=timeout` record written; caller receives 504 response

---

#### S21.2.3 — FulfillmentService Runtime — SL/TP Monitoring

**As a** risk manager,  
**I want** stop-loss and take-profit monitoring to run inside the FulfillmentService,  
**so that** position protection is active even when the trading agent cycle is paused or restarting.

**Acceptance Criteria:**
- [ ] AC1: SL/TP monitoring loop runs every 60 seconds independent of the agent cycle
- [ ] AC2: When SL or TP triggers: close position via executor, write `fulfillment_audit` record, write `AuditLogger.log_trade()` with correct `exit_reason` (`stop_loss` / `take_profit` / `trailing_stop`)
- [ ] AC3: Trailing stop raise logic (`highest_price_seen` tracking) preserved from current `PaperBroker.check_stops_and_tp()`
- [ ] AC4: Partial TP logic (50% close at 50% of TP target) preserved with `partial_exited` guard
- [ ] AC5: Integration test: paper mode position opened at $100; price fed to $95 (−5% SL) → position closed within next 60s SL/TP loop tick → `exit_reason=stop_loss` confirmed in `fulfillment_audit`

---

## E22 — Research Analyst Agent

**Goal:** Build the Research Analyst Agent (RAA) that continuously evaluates the broader crypto universe to identify emerging pairs with persistent relative strength and manages the tradeable pair list dynamically.

**Personas impacted:** All three (Conservative, Medium, High) — RAA runs independently of active persona; persona governs how aggressively RAA proposals are applied (position size, pruning rules).

---

### S22.1 — Trend Persistence Engine

#### S22.1.1 — Trend Persistence Database

**As a** developer,  
**I want** a `trend_persistence` SQLite table and a RAA process container that polls every 30 minutes,  
**so that** candidate pairs accumulate Persistence Score data over at least four consecutive cycles before any proposal is submitted.

**Acceptance Criteria:**
- [ ] AC1: `trend_persistence` table created with columns: `pair`, `classification` (FOUNDATIONAL/MEME), `persistence_score`, `cycles_sustained`, `first_seen_at`, `last_updated_at`, `status` (CANDIDATE/PROPOSED/REJECTED)
- [ ] AC2: `universe` table created with columns: `pair`, `classification`, `added_at`, `added_by`, `alpha_spread_at_entry`, `replace_target_if_any`
- [ ] AC3: `universe_events` table created with columns: `id`, `pair`, `event_type` (ADD_PAIR/REMOVE_PAIR/PROPOSE_REJECTED), `ts`, `processed` (0/1), `payload_json`
- [ ] AC4: RAA process polls Kraken `Ticker` REST and CoinGecko `Trending`/`Social` REST every 30 minutes as an independent process container (`src/runtime/research_analyst.py`)
- [ ] AC5: For each candidate, Ps is computed and persisted; consecutive-cycle counter resets to 0 when Ps drops below 1.5
- [ ] AC6: Unit test: simulated 4 consecutive 30-min cycles all with Ps=1.8 → `cycles_sustained=4`, `status=CANDIDATE`; then simulated Ps drop to 1.2 → `cycles_sustained` resets to 0

---

#### S22.1.2 — Universe Proposal API

**As a** developer,  
**I want** the RAA to submit `PROPOSE(pair, replace_target?)` to the Risk Manager API when all gates pass,  
**so that** the universe is extended only when statistical evidence of persistent strength is sufficient.

**Acceptance Criteria:**
- [ ] AC1: Proposal submitted only when Ps > 1.5 for ≥ 4 consecutive 30-min cycles
- [ ] AC2: Alpha spread gate: projected alpha must exceed +2.0% over replacement target's rolling 30-day return (or worst-performing current pair if N < 35)
- [ ] AC3: If N < 35: `replace_target` is optional; new pair added without displacement
- [ ] AC4: If N = 35: proposal MUST include `replace_target`; proposal blocked and logged if `replace_target` absent
- [ ] AC5: Risk Manager API validates all gates before writing to `universe` table; RAA never writes to `universe` directly
- [ ] AC6: Accepted proposal: `universe_events` row written with `event_type=ADD_PAIR`; displaced pair: row written with `event_type=REMOVE_PAIR`
- [ ] AC7: PSV context vector (`Pair|Price|RSI|ADX|IBS|Sector|State` for Medium; `Pair|Price|RSI|ADX|VWMA_Slope|Sector|State` for High) + LLM rationale string stored in `audit_events` per proposal
- [ ] AC8: Unit test: N=35, proposal submitted without `replace_target` → rejected with `"UNIVERSE_AT_CAP"` reason; no `universe_events` row written

---

### S22.2 — Guardrails

#### S22.2.1 — RAA Meme-Block Guardrail

**As a** risk manager,  
**I want** a hard-coded meme-block rule that prevents any `MEME`-classified pair from displacing a `FOUNDATIONAL` pair,  
**so that** core anchors (BTC, ETH, SOL) can never be liquidated to fund speculative tokens.

**Acceptance Criteria:**
- [ ] AC1: `target_class == MEME AND replace_class == FOUNDATIONAL` → proposal immediately rejected before reaching Risk Manager
- [ ] AC2: Rejection logged as `[RAA] MEME_BLOCK_REJECT: {pair}/{replace_target}` in `audit_events`
- [ ] AC3: Rule is enforced deterministically in Python code; no config flag or LLM instruction can override it
- [ ] AC4: FOUNDATIONAL classification includes at minimum: BTC, ETH, SOL and all established L1 chains in the configured `foundational` list
- [ ] AC5: Unit test: BONK/USD (MEME) + `replace_target=BTC/USD` (FOUNDATIONAL) → REJECT; no `universe_events` row written
- [ ] AC6: Unit test: BONK/USD (MEME) + `replace_target=PEPE/USD` (MEME) → allowed through to persistence gate check

---

#### S22.2.2 — SHIELDA Exception Management

**As a** developer,  
**I want** the RAA to self-correct on malformed pipe-data errors and halt safely on stale feed,  
**so that** bad data never silently corrupts the universe or causes a runtime crash.

**Acceptance Criteria:**
- [ ] AC1: Risk Manager API returning `422 Unprocessable Entity` triggers a self-correction prompt to RAA; self-correction reformats the PSV vector and resubmits
- [ ] AC2: After 3 consecutive 422 rejections for the same proposal: proposal dropped, `[RAA] SELF_CORRECT_FAILED: {pair}` logged in `audit_events`, no further retry until next 30-min cycle
- [ ] AC3: Kraken `Ticker` OHLCV variance == 0 for a candidate pair: all RAA proposals for that pair halted for the current cycle; logged as `[RAA] STALE_FEED_HALT: {pair}`
- [ ] AC4: Self-correction retry attempts do not consume or delay the main 30-minute trading cycle budget
- [ ] AC5: Unit test: 3 simulated 422 responses → `SELF_CORRECT_FAILED` in audit; 0 `universe_events` rows written
- [ ] AC6: Unit test: Kraken variance == 0 for SOL → SOL proposals halted for that cycle; other active candidates unaffected

---

### S22.3 — Persona Integration

#### S22.3.1 — Medium Persona RAA Integration

**As a** trader using the Medium persona,  
**I want** the RAA to apply conservative conviction gates before proposing a new pair,  
**so that** the tradeable universe only expands when a pair shows clear, sustained strength without entering overbought territory.

**Acceptance Criteria:**
- [ ] AC1: RAA reads active persona from Orchestrator cycle context; applies Medium-specific guardrails
- [ ] AC2: Medium RSI gate: candidate RSI must be 35–65 at time of proposal; proposal blocked outside this range
- [ ] AC3: Medium ADX gate: ADX must be < 25 at time of proposal (avoids pairs that spike briefly during choppy conditions)
- [ ] AC4: Prune eligibility: current held pair is only eligible for removal if ADX < 15 for > 12 consecutive cycles
- [ ] AC5: PSV telemetry format for Medium: `Pair|Price|RSI|ADX|IBS|Sector|State`; all fields populated before LLM rationale generation
- [ ] AC6: Unit test: candidate RSI = 68 → rejected with `"RSI_OUT_OF_RANGE"`; candidate RSI = 52, ADX = 22 → passes gate
- [ ] AC7: Unit test: held pair has ADX < 15 for only 10 consecutive cycles → NOT eligible for pruning; at 13 cycles → prune-eligible

---

#### S22.3.2 — High Persona RAA Integration

**As a** trader using the High persona,  
**I want** the RAA to apply aggressive conviction gates and momentum-driven pruning,  
**so that** the universe rapidly rotates towards highest-alpha opportunities when strong trend conditions are confirmed.

**Acceptance Criteria:**
- [ ] AC1: RAA reads active persona from Orchestrator cycle context; applies High-specific guardrails
- [ ] AC2: High RSI bypass: entry authorised up to RSI 85 IFF ADX > 35 AND VWMA_Slope > 0 at time of proposal
- [ ] AC3: Aggressive pruning: if proposed pair has composite Score > 8/28, RAA proposes immediate removal of the current lowest-ADX holding as `replace_target`
- [ ] AC4: PSV telemetry format for High: `Pair|Price|RSI|ADX|VWMA_Slope|Sector|State`; `VWMA_Slope` MUST be non-null for all High proposals
- [ ] AC5: Position size for High persona RAA additions: 3.0% with volatility scaling (ATR-based multiplier, same framework as existing dynamic TP)
- [ ] AC6: Unit test: RSI = 82, ADX = 38, VWMA_Slope = +0.004 → entry authorised; RSI = 82, ADX = 28 → blocked
- [ ] AC7: Unit test: proposed pair Score = 9/28 → lowest-ADX held pair automatically included as `replace_target` in proposal

---

## E23 — Closed-Loop Optimization: Audit Agent and Feedback Loops

**Epic goal:** Every agent in the mesh receives structured, PSV-formatted outcome feedback from a dedicated post-hoc Audit Agent. Agents adjust heuristics (thresholds, driver weights, prompt content) based on their own historical accuracy — without human intervention for routine cases. Human oversight is surfaced via HITL queue for policy-crossing violations.

**Dependencies:**
- E22 (RAA) must be delivered first — `audit_feedback` structure mirrors the RAA PSV format
- `fulfillment_audit`, `audit_events`, `universe`, `trend_persistence` tables must exist (from E17–E22)
- New tables: `audit_feedback`, `playbook_performance`, `signal_accuracy`, `llm_reflection_log`, `confidence_state`, `risk_decision_outcomes`, `hitl_queue` (§12.9–12.15)
- kryptos-api: `GET /hitl-queue`, `POST /hitl-queue/{id}/approve`, `POST /hitl-queue/{id}/reject` endpoints required before S10 gate

---

### F23.1 — Audit Agent Runtime

#### S23.1.1 — Audit Agent process container and outcome tracking

**As a** developer,  
**I want** an independent Audit Agent process that evaluates all trading outcomes post-hoc and writes feedback to structured DB tables,  
**so that** all trading agents receive continuous performance feedback without consuming cycle budget.

**Acceptance Criteria:**
- [ ] AC1: `src/runtime/audit_agent.py` launches as an independent process; REST health endpoint returns `{"status": "ok"}` on port 8094 (configurable via `services.audit_agent.port`)
- [ ] AC2: Validation Window (default 24h, configurable via `feedback.validation_window_h`) opened for every RAA proposal; PSV outcome vector written to `audit_feedback` on window close
- [ ] AC3: Reprimand Vector written immediately on every Risk Manager `422` / `MEME_BLOCK` rejection event
- [ ] AC4: 24h rollup populates `playbook_performance` (win_rate, PF, max_drawdown per playbook per regime) and `risk_decision_outcomes` (SL/TP hit rates per pair)
- [ ] AC5: 6h rollup populates `signal_accuracy` (accuracy_pct per driver per pair from last 30 days)
- [ ] AC6: Unit test: simulated RAA proposal with expected alpha +8%, actual -12% after 24h → `audit_feedback` row with `outcome=FAIL_PUMP_DETECTION`
- [ ] AC7: Unit test: simulated MEME_BLOCK rejection → `audit_feedback` reprimand row written within same sync cycle; `penalty_weight` = -2.0

#### S23.1.2 — RAA Self-Reflection Loop

**As a** developer,  
**I want** the RAA to read its last 50 outcome vectors and execute a four-phase reflection loop at each poll cycle start,  
**so that** the RAA adjusts persistence thresholds and avoids repeating classification errors.

**Acceptance Criteria:**
- [ ] AC1: RAA reads `SELECT * FROM audit_feedback WHERE agent='RAA' ORDER BY ts DESC LIMIT 50` at poll cycle start (before any classification LLM call)
- [ ] AC2: LLM `SELF_CRITIQUE` call identifies repeating failure patterns from feedback vectors; result (agent, pair, lesson_text) written to `llm_reflection_log`
- [ ] AC3: `confidence_state.ps_threshold_override` and `sector_multiplier_json` updated from reflection result (DB_UPSERT phase)
- [ ] AC4: META_PROMPT phase: updated `ps_threshold_override` is used in next `classify_pair` call's prompt context
- [ ] AC5: Unit test: 5 consecutive `FAIL_PUMP_DETECTION` outcomes for meme pairs → `ps_threshold_override` raised from 1.5 to 2.0 in `confidence_state`

#### S23.1.3 — SHIELDA Confidence Reset and HITL Lock

**As a** risk manager,  
**I want** automatic confidence reset when an agent's predictions are statistically inaccurate, and a HITL lock after repeated guardrail violations,  
**so that** a miscalibrated RAA cannot continuously degrade universe quality.

**Acceptance Criteria:**
- [ ] AC1: Audit Agent computes rolling 5-outcome std-dev of `(actual_alpha - expected_alpha)` per agent; if > 3σ → `confidence_state.confidence_reset_count` incremented + `CONFIDENCE_RESET` event written to `audit_feedback`
- [ ] AC2: RAA reads `CONFIDENCE_RESET` event at next poll start → clears `ps_threshold_override`, `sector_multiplier_json`, `driver_multiplier_json` to NULL (reverts to base config); logs `[RAA] CONFIDENCE_RESET applied`
- [ ] AC3: After 3 `FOUNDATIONAL_REPLACEMENT_BLOCK` reprimands within any 24h window: `confidence_state.substitution_tool_locked=1`; `locked_until_ts` set to `now + 24h`; Telegram alert sent
- [ ] AC4: While `substitution_tool_locked=1`: every RAA `PROPOSE_REPLACE` call → inserted into `hitl_queue` with `status=PENDING`; proposal NOT executed in `universe_events`; no trading pair change occurs
- [ ] AC5: kryptos-api `GET /hitl-queue` returns all `PENDING` rows; `POST /hitl-queue/{id}/approve` sets `status=APPROVED` and writes corresponding `universe_events` row; `POST /hitl-queue/{id}/reject` sets `status=REJECTED`
- [ ] AC6: Unit test: 3 `MEME_BLOCK` reprimands in sequence → `substitution_tool_locked=1`; next `PROPOSE_REPLACE` call → `hitl_queue` row created with `status=PENDING`; no `universe_events` row written until approved

---

### F23.2 — Per-Agent Feedback Integration

#### S23.2.1 — Orchestrator playbook bias from performance history

**As a** trader,  
**I want** the Orchestrator to prefer historically profitable playbooks in the current regime,  
**so that** playbook selection improves over time without human intervention for routine adjustments.

**Acceptance Criteria:**
- [ ] AC1: Orchestrator reads `playbook_performance WHERE regime = current_regime` at cycle start; if sample_count ≥ 10, applies +1 priority multiplier to playbooks with `profit_factor > 1.2`
- [ ] AC2: If no `playbook_performance` rows exist for current regime, default config playbook used (no change from v2 behaviour)
- [ ] AC3: Playbook selection is read-only at cycle start — no mid-cycle playbook change under any feedback condition
- [ ] AC4: Unit test: `trending_up` regime — `momentum` PF=1.45 (n=15), `ranging` PF=0.8 (n=12) → Orchestrator selects `momentum` for current cycle

#### S23.2.2 — QSA signal driver accuracy multipliers

**As a** developer,  
**I want** QSA to apply per-driver accuracy multipliers based on historical predictive quality,  
**so that** drivers with poor track records are de-weighted automatically over time.

**Acceptance Criteria:**
- [ ] AC1: QSA reads `signal_accuracy` for all active pairs at cycle start; merges `weight_multiplier` values into per-driver score computation
- [ ] AC2: Multiplier is applied to each driver's contribution score before summing composite score; multiplier is bounded to `[0.5, 1.5]` — hard vetoes (RSI ≥ 70, volume floor) are never affected
- [ ] AC3: Unit test: `rsi_oversold` accuracy = 28% for `BONK/USD` → `weight_multiplier = 0.5` applied; `macd_histogram_turn` accuracy = 78% for `ETH/USD` → `weight_multiplier = 1.3` applied
- [ ] AC4: Unit test: multiplier outside [0.5, 1.5] in DB → clamped at read time; no runtime exception

#### S23.2.3 — AIE negative few-shot injection

**As a** developer,  
**I want** AIE to include up to 3 recent loss-pattern examples from its reflection log in its system prompt,  
**so that** the LLM avoids documented failure patterns without requiring manual prompt engineering.

**Acceptance Criteria:**
- [ ] AC1: AIE fetches `SELECT * FROM llm_reflection_log WHERE agent='AIE' AND injected=1 ORDER BY ts DESC LIMIT 3` pre-prompt construction
- [ ] AC2: Lessons injected as "PATTERNS TO AVOID" block at end of system prompt; total additional tokens ≤ 200; if exceeded, oldest `injected=1` record is set to `injected=0` first
- [ ] AC3: If `llm_reflection_log` is empty or no `injected=1` rows: system prompt unchanged; no injection block rendered
- [ ] AC4: Unit test: 4 active lessons (`injected=1`) available → after injection budget enforcement, oldest record set to `injected=0`, only 3 remain active

#### S23.2.4 — ROM advisory feedback display

**As a** trader,  
**I want** the Kryptos UI Risk Management panel to show per-pair SL/TP calibration health, flagging pairs with poor outcomes,  
**so that** I can make informed decisions about manual SL/TP parameter adjustments.

**Acceptance Criteria:**
- [ ] AC1: `risk_decision_outcomes` populated by Audit Agent daily rollup for all pairs with ≥ 10 closed trades
- [ ] AC2: When a pair's `sl_hit_rate > 0.60` and `sample_count ≥ 20`: Telegram advisory sent with recommendation string (e.g., `TIGHTEN_SL or RAISE_MIN_SCORE`)
- [ ] AC3: ROM does NOT auto-adjust any parameter — advisory only; changes require `config.yaml` edit and system restart
- [ ] AC4: kryptos-api `GET /feedback/risk` returns `risk_decision_outcomes` table sorted by `sl_hit_rate DESC`

---

## E24 — Kryptos UI: Decision Intelligence and Copilot Q&A

**Epic goal:** Make every agent decision, trade outcome, and system state visible and explainable through kryptos-ui. A solo trader must be able to ask "Why did the bot buy SOL/USD on April 18?" in a chat input and receive a complete, plain-English explanation within 5 seconds.

**Dependencies on kryptos-api (new endpoints required before S11 gate):**

| Endpoint | Purpose | Primary DB sources |
|---|---|---|
| `GET /trades?mode=paper&limit=50` | Trade list with filters | `fulfillment_audit`, `audit_events` |
| `GET /trades/{id}/detail` | Full four-block audit chain per trade | `audit_events`, `fulfillment_audit` |
| `GET /trades/{id}/explain` | LLM-generated natural language explanation | `audit_events` → LLM → narrative |
| `GET /agents/status` | All 5 agents: heartbeat, state, last cycle | `audit_events`, `agent_state` |
| `GET /signals?pair={pair}&limit=100` | Signal score time-series per pair | `audit_events WHERE event_type='SIGNAL'` |
| `GET /universe` | Active pairs + RAA pipeline + recent proposals | `universe`, `trend_persistence`, `universe_events` |
| `GET /feedback/raa` | RAA outcome vectors and reflection log | `audit_feedback`, `llm_reflection_log`, `confidence_state` |
| `GET /feedback/agents` | Per-agent performance metrics | `playbook_performance`, `signal_accuracy`, `risk_decision_outcomes` |
| `GET /hitl-queue` | Pending HITL approvals | `hitl_queue WHERE status='PENDING'` |
| `POST /hitl-queue/{id}/approve` | Approve a queued RAA proposal | `hitl_queue`, `universe_events` |
| `POST /hitl-queue/{id}/reject` | Reject a queued RAA proposal | `hitl_queue` |

---

### F24.1 — Trade Explorer

#### S24.1.1 — Full audit trail per trade

**As a** trader,  
**I want** to click any trade in the trade history and see its complete four-block decision chain,  
**so that** I can understand exactly why the bot entered or exited a position without reading raw DB logs.

**Acceptance Criteria:**
- [ ] AC1: Trade list page shows all trades with: pair, entry price, exit price, PnL%, fees, duration, exit reason (SL / TP / trailing_stop / agent_sell / backtest_end)
- [ ] AC2: Clicking a trade opens a detail panel with four blocks: (1) QSA signal scores at entry cycle — each driver with value and score contribution; (2) AIE LLM reasoning excerpt — tool calls made, proposal confidence; (3) ROM guard outcomes — which guards passed/blocked and why; (4) FulfillmentService fill — slippage applied, fee charged, actual fill price
- [ ] AC3: Each detail block links to the raw `audit_events` row via `cycle_id` (shown as reference tag)
- [ ] AC4: All PnL figures include round-trip friction (entry slippage + entry fee + exit slippage + exit fee ≈ 0.62% for Tier-1 pairs)
- [ ] AC5: kryptos-api `GET /trades/{id}/detail` returns all four blocks in < 500ms (measured end-to-end)
- [ ] AC6: Unit test: paper trade with known `cycle_id` → `GET /trades/{id}/detail` response includes `signal_block`, `llm_block`, `guard_block`, `fill_block` keys with non-null data

#### S24.1.2 — Copilot Q&A: natural language trade explanation

**As a** trader,  
**I want** to type "Why was SOL/USD bought?" or "Why did BONK/USD hit the stop loss?" in a chat input and receive a plain-English explanation,  
**so that** I learn from the bot's decisions without reading raw audit logs.

**Acceptance Criteria:**
- [ ] AC1: kryptos-api `GET /trades/{id}/explain` fetches the trade's full audit context from `audit_events`; constructs a structured LLM prompt; calls Groq (primary) / Ollama (fallback); returns a 2–4 sentence narrative explanation
- [ ] AC2: Explanation always includes: (a) what signal indicators drove the entry score, (b) what LLM reasoning led to the proposal, (c) exit reason and whether outcome matched entry thesis
- [ ] AC3: A chat input box is rendered on the Trade Detail panel; free-text query triggers `/explain` with `trade_id` derived from current context
- [ ] AC4: Client-side SLA: response rendered within 5 seconds; loading spinner shown during LLM call
- [ ] AC5: Explanation LLM call is logged to `audit_events` with `component='CopilotQA'`; it MUST NOT influence any trading decisions or CycleContext
- [ ] AC6: Unit test: mocked audit context with known signal scores → `/explain` response contains entry reason, exit reason, and outcome assessment — all matching the mock context

---

### F24.2 — Live Agent Status Dashboard

#### S24.2.1 — Real-time agent heartbeat and last-cycle summary

**As an** operations engineer,  
**I want** a dashboard panel showing all 5 agents' status and last cycle timestamps,  
**so that** I immediately detect if any agent is stalled or degraded.

**Acceptance Criteria:**
- [ ] AC1: Dashboard shows Orchestrator, QSA, AIE, ROM, RAA each with: status badge (🟢 READY / ⚠️ DEGRADED / 🔴 STALE), last heartbeat timestamp, last cycle timestamp
- [ ] AC2: `STALE` = heartbeat > 5 min ago; `DEGRADED` = heartbeat live but no cycle event logged in > 35 min
- [ ] AC3: kryptos-api `GET /agents/status` polled every 30 seconds by UI via `usePolling` hook
- [ ] AC4: Unit test: `audit_events` row with `component='Orchestrator'` and `event_type='HEARTBEAT'` timestamp > 5 min ago → `GET /agents/status` returns `status: STALE` for Orchestrator

---

### F24.3 — Signal Intelligence

#### S24.3.1 — Per-pair signal score history and driver breakdown

**As a** trader,  
**I want** to view a pair's signal score time-series over the last 48 hours with driver-level breakdowns,  
**so that** I can validate the bot's signal logic and identify recurring entry patterns.

**Acceptance Criteria:**
- [ ] AC1: Signal Intelligence page includes pair selector (all active pairs) + time-series chart of composite signal score over last 96 cycles (48h at 30-min cadence)
- [ ] AC2: Clicking any point on the chart opens a driver breakdown panel: RSI, ADX, OBI, MACD histogram turn, OBV trend, BB squeeze, candlestick patterns — each with raw value and score contribution
- [ ] AC3: kryptos-api `GET /signals?pair=ETH%2FUSD&limit=96` returns time-ordered array of signal records parsed from `audit_events WHERE event_type='SIGNAL' AND pair='ETH/USD'`
- [ ] AC4: Unit test: 96 `SIGNAL` audit events for ETH/USD → API returns array of 96 records in ascending time order with `composite_score` and `driver_scores` fields

---

### F24.4 — Universe Manager

#### S24.4.1 — Active universe, RAA pipeline, and recent proposals

**As a** trader,  
**I want** to see all currently active pairs with their RAA metadata and the top candidates in the persistence pipeline,  
**so that** I understand which pairs are eligible for trading and what the RAA is considering for addition or removal.

**Acceptance Criteria:**
- [ ] AC1: Universe panel lists all active pairs with: classification (FOUNDATIONAL / MEME), date added, added by (bootstrap / raa), current `persistence_score` (Ps)
- [ ] AC2: Pipeline section lists top 10 RAA-tracked candidates sorted by current Ps descending, showing `cycles_sustained`, `estimated_cycles_to_gate`, and `alpha_spread_pct`
- [ ] AC3: Recent activity section shows last 5 `ACCEPTED` and last 5 `REJECTED` proposals from `universe_events`, with rejection reasons
- [ ] AC4: kryptos-api `GET /universe` returns all three sections (active, pipeline, recent_activity) in a single JSON response
- [ ] AC5: HITL lock banner displayed prominently when `confidence_state.substitution_tool_locked=1` for RAA — shows lock expiry countdown

---

### F24.5 — Feedback and Performance Dashboard

#### S24.5.1 — Audit Agent outcome visibility across all agents

**As a** trader,  
**I want** a Feedback dashboard showing per-agent performance metrics, RAA accuracy trends, and active learning state,  
**so that** I can see whether the closed-loop feedback system is improving decision quality over time.

**Acceptance Criteria:**
- [ ] AC1: **RAA section:** last 10 outcome vectors (pair, expected alpha, actual alpha, outcome), current `ps_threshold_override`, HITL lock status with countdown, `confidence_reset_count`
- [ ] AC2: **Orchestrator section:** `playbook_performance` table — win_rate, PF, avg_hold_hours per playbook per regime; rows sorted by PF descending
- [ ] AC3: **QSA section:** top 10 most-accurate and bottom 10 least-accurate signal drivers (by `accuracy_pct`); current `weight_multiplier` per driver
- [ ] AC4: **AIE section:** active "PATTERNS TO AVOID" lessons (`injected=1`) currently in system prompt — pair, outcome, lesson text; confirms count ≤ 3
- [ ] AC5: **ROM section:** `risk_decision_outcomes` per pair — `sl_hit_rate`, `tp_hit_rate`, `avg_exit_pct`; pairs with `sl_hit_rate > 0.60` highlighted in red with `recommendation` badge
- [ ] AC6: kryptos-api `GET /feedback/raa` and `GET /feedback/agents` each respond within 1 second for up to 30 days of history

---

### F24.6 — HITL Approval Queue

#### S24.6.1 — Human-in-the-loop universe proposal approval UI

**As a** trader,  
**I want** a dedicated HITL queue page listing all pending RAA proposals requiring human approval,  
**so that** I can review and approve or reject individual proposals during a HITL lock period without restarting the agent.

**Acceptance Criteria:**
- [ ] AC1: HITL queue page renders when `hitl_queue` has ≥ 1 `PENDING` row; shows per-proposal: pair, `replace_target`, current Ps, alpha spread, RAA classification rationale, reprimand history count
- [ ] AC2: Approve button calls `POST /hitl-queue/{id}/approve`; on success: corresponding `universe_events` row written with `event_type='ADD_PAIR'`; proposal status flips to `APPROVED`; item removed from pending list
- [ ] AC3: Reject button calls `POST /hitl-queue/{id}/reject`; on success: `universe_events` row written with `event_type='PROPOSE_REJECTED'`; proposal status flips to `REJECTED`
- [ ] AC4: Active HITL lock banner visible on all Kryptos UI pages when lock is active — shows lock expiry time and link to HITL Queue page
- [ ] AC5: Unit test: 3 PENDING items in `hitl_queue` — approve 2, reject 1 → `universe_events` has 2 `ADD_PAIR` rows + 1 `PROPOSE_REJECTED` row; all 3 `hitl_queue` rows updated with non-null `reviewed_by`, `reviewed_at`, `status`

---

## Squad Assignment and Story Points

**Squad composition:** 1 UI Developer, 2 Python Developers, 1 AI Engineer, 1 Tester, 1 Java Developer

> **Tester convention:** For every story below, the Tester adds a `## Test Scenarios` checklist as a sub-task in the GitHub issue. Test scenarios must cover: happy path, boundary conditions, failure/error paths, and regression guard for v2 behaviour.

### Role Legend

| Role label | Who | Responsibilities |
|---|---|---|
| `python-dev` | Python Developer (×2) | All `src/` runtimes, agents, shared libs, CLI |
| `ai-engineer` | AI Engineer (×1) | LLM integration, prompt engineering, AIE/RAA classify workflows |
| `java-dev` | Java Developer (×1) | `kryptos-api` Spring Boot endpoints |
| `ui-dev` | UI Developer (×1) | `kryptos-ui` React screens, components, hooks |
| `tester` | Tester (×1) | Per-story test scenarios, regression suites, backtest validation |

### Story Assignment Matrix

| Story ID | Title | Sprint | Role | Points |
|---|---|---|---|---|
| S12.1.1 | Persona config schema | S1 | python-dev | 3 |
| S12.1.2 | Persona loader and runtime injection | S1 | python-dev | 5 |
| S12.1.3 | Persona-aware signal gating | S2 | python-dev | 3 |
| S13.1.1 | Winsorized EMA-14 volume floor | S2 | python-dev | 3 |
| S13.1.2 | Variance heartbeat per pair | S2 | python-dev | 3 |
| S13.2.1 | Pipe-format QSA signal block | S2 | ai-engineer | 2 |
| S13.2.2 | PSV field schema and token budget | S3 | ai-engineer | 2 |
| S13.2.3 | Per-pair volume ratio in pipe format | S3 | ai-engineer | 2 |
| S13.3.1 | Trade context injection into QSA | S3 | python-dev | 3 |
| S14.1.1 | Pipe-format AIE prompt builder | S3 | ai-engineer | 3 |
| S14.1.2 | Pre-call token estimator | S3 | ai-engineer | 3 |
| S14.2.1 | Portfolio state block in prompt | S3 | ai-engineer | 3 |
| S14.2.2 | Regime state block in prompt | S3 | ai-engineer | 2 |
| S14.2.3 | Unfilled cluster context in prompt | S4 | ai-engineer | 2 |
| S14.2.4 | Persona system role injection | S4 | ai-engineer | 3 |
| S15.1.1 | Prune candidate identification | S4 | python-dev | 3 |
| S15.1.2 | Capital reallocation execution flow | S4 | python-dev | 5 |
| S15.2.1 | Persona-scoped RSI bypass in validate_buy | S4 | python-dev | 3 |
| S15.2.2 | PF escalation suspended in momentum playbook | S5 | python-dev | 2 |
| S15.2.3 | Early Momentum Accumulation score reduction | S5 | python-dev | 3 |
| S15.3.1 | Loss velocity calculation and halt | S5 | python-dev | 5 |
| S16.1.1 | Regime-to-playbook classifier | S5 | python-dev | 5 |
| S16.1.2 | Playbook injected into RiskManager and prompts | S5 | python-dev | 3 |
| S16.2.1 | Agent timeout detection and recovery | S5 | python-dev | 3 |
| S17.1.1 | MCP server with six read-only tools | S6 | python-dev | 8 |
| S18.1.1 | `kryptos persona` CLI command group | S6 | python-dev | 3 |
| S18.1.2 | `kryptos regime` CLI command | S6 | python-dev | 2 |
| S18.1.3 | Kryptos API persona endpoint | S6 | java-dev | 3 |
| S18.1.4 | Kryptos UI — Persona Panel | S7 | ui-dev | 3 |
| S19.1.1 | Per-persona fast backtest | S8 | tester | 3 |
| S19.1.2 | Regression test: conservative = v2 baseline | S8 | tester | 3 |
| S20.0.1 | Library Repositories Scaffold | S1 | python-dev | 5 |
| S20.1.1 | Audit Library | S2 | python-dev | 5 |
| S20.1.2 | Integration Logging Library | S2 | python-dev | 5 |
| S20.2.1 | AI Client Library | S3 | python-dev | 5 |
| S20.3.1 | Agent Bootstrap Library | S4 | python-dev | 5 |
| S20.4.1 | Library integration into consuming projects | S4 | python-dev | 3 |
| S21.1.1 | DataCollector Runtime — WebSocket + Candle Buffer | S3 | python-dev | 8 |
| S21.1.2 | DataCollector Runtime — Feed Freeze Detection | S4 | python-dev | 3 |
| S21.2.1 | FulfillmentService Runtime — Core REST API | S4 | python-dev | 8 |
| S21.2.2 | FulfillmentService Runtime — Fulfillment Audit | S5 | python-dev | 3 |
| S21.2.3 | FulfillmentService Runtime — SL/TP Monitoring | S5 | python-dev | 5 |
| S22.1.1 | Trend Persistence Engine — Database + Process | S9 | ai-engineer | 5 |
| S22.1.2 | Universe Proposal API | S9 | ai-engineer | 5 |
| S22.2.1 | RAA Meme-Block Guardrail | S9 | python-dev | 3 |
| S22.2.2 | SHIELDA Exception Management | S9 | python-dev | 3 |
| S22.3.1 | Medium Persona RAA Integration | S9 | ai-engineer | 3 |
| S22.3.2 | High Persona RAA Integration | S9 | ai-engineer | 3 |
| S23.1.1 | Audit Agent process container + outcome tracking | S10 | python-dev | 8 |
| S23.1.2 | RAA Self-Reflection Loop | S10 | ai-engineer | 5 |
| S23.1.3 | SHIELDA Confidence Reset + HITL Lock | S10 | python-dev | 5 |
| S23.2.1 | Orchestrator playbook bias from performance history | S10 | python-dev | 3 |
| S23.2.2 | QSA signal driver accuracy multipliers | S10 | python-dev | 3 |
| S23.2.3 | AIE negative few-shot injection | S10 | ai-engineer | 3 |
| S23.2.4 | ROM advisory feedback display | S10 | java-dev | 3 |
| S24.1.1 | Full audit trail per trade | S11 | java-dev | 5 |
| S24.1.2 | Copilot Q&A — natural language trade explanation | S11 | java-dev | 5 |
| S24.2.1 | Real-time agent heartbeat + last-cycle summary | S11 | ui-dev | 3 |
| S24.3.1 | Per-pair signal score history + driver breakdown | S11 | ui-dev | 5 |
| S24.4.1 | Active universe, RAA pipeline + recent proposals | S11 | ui-dev | 5 |
| S24.5.1 | Audit Agent outcome visibility across all agents | S11 | ui-dev | 5 |
| S24.6.1 | HITL approval queue UI | S11 | ui-dev | 3 |

### Sprint Load Summary

| Sprint | Stories | Total Points | Primary Squad |
|---|---|---|---|
| S1 | S12.1.1, S12.1.2, S20.0.1 | 13 | python-dev ×2 |
| S2 | S12.1.3, S13.1.1, S13.1.2, S13.2.1, S20.1.1, S20.1.2 | 21 | python-dev ×2, ai-engineer |
| S3 | S13.2.2, S13.2.3, S13.3.1, S14.1.1, S14.1.2, S14.2.1, S14.2.2, S20.2.1, S21.1.1 | 29 | python-dev ×2, ai-engineer |
| S4 | S14.2.3, S14.2.4, S15.1.1, S15.1.2, S15.2.1, S20.3.1, S20.4.1, S21.1.2, S21.2.1 | 40 | python-dev ×2, ai-engineer |
| S5 | S15.2.2, S15.2.3, S15.3.1, S16.1.1, S16.1.2, S16.2.1, S21.2.2, S21.2.3 | 29 | python-dev ×2 |
| S6 | S17.1.1, S18.1.1, S18.1.2, S18.1.3 | 16 | python-dev ×1, java-dev |
| S7 | S18.1.4 | 3 | ui-dev |
| S8 | S19.1.1, S19.1.2 | 6 | tester |
| S9 | S22.1.1, S22.1.2, S22.2.1, S22.2.2, S22.3.1, S22.3.2 | 22 | python-dev ×1, ai-engineer |
| S10 | S23.1.1, S23.1.2, S23.1.3, S23.2.1, S23.2.2, S23.2.3, S23.2.4 | 30 | python-dev ×1, ai-engineer, java-dev |
| S11 | S24.1.1, S24.1.2, S24.2.1, S24.3.1, S24.4.1, S24.5.1, S24.6.1 | 31 | ui-dev, java-dev |

---

## Sprint Acceptance Gates

| Sprint | Gate Condition |
|---|---|
| S1 | All S12.1.x passing; `conservative` persona in paper mode = v2 behaviour |
| S2 | Winsorized EMA unit tests passing; variance heartbeat suppresses frozen BTC signal in test; `AuditLogger` concurrent write test passing; `IntegrationLogger` redaction test passing |
| S3 | Pipe format generates ≤ 2200 tokens for 15 pairs; token estimator prevents budget breach; `AIClient` fallback test passing; DataCollector writes to `candle_buffer` within 5s of candle close |
| S4 | State-aware prompt test: ETH already held → LLM prompt explicitly shows ETH in portfolio block; `AgentBootstrap` heartbeat test passing; FulfillmentService `/health` responding; all endpoints bound to 127.0.0.1 |
| S5 | Reallocation unit test passing; velocity circuit breaker test passing; playbook selection test passing; `fulfillment_audit` write-before-response test passing; SL/TP monitor closes position within 60s in paper mode |
| S6 | MCP server responds to `get_portfolio_state` within 500ms; CLI persona switch updates config |
| S7 | UI persona panel renders on dashboard; playbook mode indicator displayed |
| S8 | Conservative regression test passes (< 0.1% deviation from v2); Medium backtest win rate > 50%; High backtest win rate > 40% with higher PnL |
| S9 | `trend_persistence`, `universe`, and `universe_events` tables created; RAA process container polls at 30-min cadence; persistence gate tests passing (S22.1.1 AC6); meme-block unit tests passing (S22.2.1 AC5, AC6); SHIELDA self-correction test passing (S22.2.2 AC5); Medium RSI/ADX gate tests passing (S22.3.1 AC6, AC7) |
| S10 | Audit Agent health endpoint responding on port 8094; PSV outcome vector written for simulated RAA proposal (S23.1.1 AC6); reprimand vector written on simulated MEME_BLOCK (S23.1.1 AC7); RAA Self-Reflection Loop test: 5 FAIL outcomes → `ps_threshold_override` raised (S23.1.2 AC5); HITL lock test: 3 violations → `substitution_tool_locked=1` + next proposal in `hitl_queue` (S23.1.3 AC6); per-agent feedback integration tests passing (S23.2.1 AC4, S23.2.2 AC3, S23.2.3 AC4) |
| S11 | kryptos-api `GET /trades/{id}/detail` returns all four audit blocks within 500ms (S24.1.1 AC5); `GET /trades/{id}/explain` returns LLM narrative within 5s (S24.1.2 AC4); `GET /universe` returns active pairs + pipeline + recent proposals (S24.4.1 AC4); HITL approve flow writes to `universe_events` correctly (S24.6.1 AC5); `GET /feedback/agents` and `GET /feedback/raa` respond within 1s (S24.5.1 AC6) |
