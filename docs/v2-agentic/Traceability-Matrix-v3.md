# Kryptos v3 — Traceability Matrix

**Document Type:** Requirements Traceability  
**Version:** 1.0  
**Date:** 19 April 2026  
**References:** BRD-v3.md, Architecture-Design-v3.md, User-Stories-Sprint-Plan-v3.md

---

## Purpose

This matrix links every BRD Functional Requirement (FR) to its Architecture section and one or more User Stories. Any row marked **GAP** requires a new story or AC update before the sprint gate closes.

---

## Traceability Matrix

### §5.1 — Persona Framework

| BRD FR | Requirement (summary) | Architecture § | User Story | Status |
|---|---|---|---|---|
| FR-P01 | Three risk personas (Conservative / Medium / High) with full config schema | §2.1 | S12.1.1, S12.1.2 | ✅ Covered |
| FR-P02 | Active persona governs all thresholds at runtime; CLI + API switch | §2.1 | S12.1.3, S18.1.1, S18.1.2 | ✅ Covered |
| FR-P03 | `PUT /api/v2/persona` API endpoint; override persisted to `agent_state` | §2.1, §8 | S18.1.3 | ✅ Covered |
| FR-P04 | UI persona selector panel on dashboard | §2.1, §9 | S18.1.4 | ✅ Covered |
| FR-P05 | Persona switch logged with `actor`, `from_persona`, `to_persona`, `timestamp` | §2.1, §4 | S12.1.2, S18.1.1 | ✅ Covered |

### §5.2 — QSA Agent — Data Resilience

| BRD FR | Requirement (summary) | Architecture § | User Story | Status |
|---|---|---|---|---|
| FR-Q01 | Winsorized EMA-14 replaces rolling p15 volume floor | §2.2 | S13.1.1 | ✅ Covered |
| FR-Q02 | Per-pair OHLCV variance heartbeat; zero-variance = frozen-pair flag | §2.2 | S13.1.2, S21.1.2 | ✅ Covered |
| FR-Q03 | QSA signals emitted as pipe-separated format (PSV) | §2.2, §5 | S13.2.1 | ✅ Covered |
| FR-Q04 | PSV field schema defined; per-pair token budget enforced | §2.2, §5 | S13.2.2 | ✅ Covered |
| FR-Q05 | Per-pair volume ratio included in PSV signal block | §2.2 | S13.2.3 | ✅ Covered |
| FR-Q06 | Trade history context (last trade per pair) injected into QSA computation | §2.2 | S13.3.1 | ✅ Covered |
| FR-Q07 | Per-pair OHLCV data sourced from DataCollector `candle_buffer` (not in-process) | §2.7 | S21.1.1, S13.3.1 | ✅ Covered |

### §5.3 — AIE Agent — Context Engineering

| BRD FR | Requirement (summary) | Architecture § | User Story | Status |
|---|---|---|---|---|
| FR-A01 | AIE prompt uses pipe-format signal blocks; ≤ 15 BUY/SELL pairs per cycle | §2.3, §5 | S14.1.1 | ✅ Covered |
| FR-A02 | Pre-call token estimator enforces ≤ 2200-token budget before LLM call | §2.3 | S14.1.2 | ✅ Covered |
| FR-A03 | Portfolio state block in prompt (current holdings, unrealised PnL, SL/TP dist) | §2.3 | S14.2.1 | ✅ Covered |
| FR-A04 | Regime state block in prompt (regime, playbook, BTC dominance, ADX median) | §2.3 | S14.2.2 | ✅ Covered |
| FR-A05 | Unfilled sector cluster context exposed in prompt | §2.3 | S14.2.3 | ✅ Covered |
| FR-A06 | Persona system role injection: `build_system_prompt(persona_config)` | §2.3 | S14.2.4 | ✅ Covered |
| FR-A07 | LLM tool calls validated against persona rules before execution | §2.3 | S14.2.4, S12.1.3 | ✅ Covered |
| FR-A08 | AIE injects up to 3 negative few-shot lessons from feedback (CLO) | §2.3, §2.10 | S23.2.3 | ✅ Covered |

### §5.4 — ROM Agent — Capital Reallocation & Momentum Bypass

| BRD FR | Requirement (summary) | Architecture § | User Story | Status |
|---|---|---|---|---|
| FR-R01 | Capital reallocation: sell weakest position to fund high-conviction signal | §2.4 | S15.1.1, S15.1.2 | ✅ Covered |
| FR-R02 | Deep-loss positions never eligible for pruning | §2.4 | S15.1.1 | ✅ Covered |
| FR-R03 | Momentum RSI bypass: relax RSI veto when ADX > threshold (Medium/High only) | §2.4 | S15.2.1 | ✅ Covered |
| FR-R04 | Velocity circuit breaker: halt when hourly loss rate exceeds persona threshold | §2.4 | S15.3.1 | ✅ Covered |
| FR-R05 | Reallocation 6h cap for Medium persona; no cap for High; disabled for Conservative | §2.4 | S15.1.2 | ✅ Covered |
| FR-R06 | PF escalation suppressed in momentum playbook for Medium/High | §2.4 | S15.2.2 | ✅ Covered |
| FR-R07 | Early Momentum score reduction (RSI 50–65 AND ADX > 25) for Medium/High | §2.4 | S15.2.3 | ✅ Covered |

### §5.5 — Orchestrator Agent

| BRD FR | Requirement (summary) | Architecture § | User Story | Status |
|---|---|---|---|---|
| FR-O01 | Orchestrator selects playbook (ranging / momentum / risk_off) each cycle | §2.5 | S16.1.1 | ✅ Covered |
| FR-O02 | Playbook propagated to RiskManager validate_buy and LLM prompt | §2.5 | S16.1.2 | ✅ Covered |
| FR-O03 | Agent timeout detection (30s per agent); 2 consecutive → force risk_off | §2.5 | S16.2.1 | ✅ Covered |
| FR-O04 | Orchestrator biases playbook selection using `playbook_performance` history | §2.5, §2.10 | S23.2.1 | ✅ Covered |
| FR-O05 | Playbook transition logged and Telegram alert on change | §2.5 | S16.1.1 | ✅ Covered |

### §5.6 — Token Format

| BRD FR | Requirement (summary) | Architecture § | User Story | Status |
|---|---|---|---|---|
| FR-T01 | QSA PSV field separator is `|`; no quotes; Boolean as `1`/`0` | §5 | S13.2.1, S13.2.2 | ✅ Covered |
| FR-T02 | AIE token estimator uses tiktoken `cl100k_base`; triggers HOLD-filter if budget exceeded | §5 | S14.1.2 | ✅ Covered |
| FR-T03 | Max 15 BUY/SELL pairs in any single LLM prompt; excess filtered to HOLD | §5 | S14.1.1 | ✅ Covered |
| FR-T04 | Pipe format applies to QSA, AIE, and ROM signal blocks uniformly | §5 | S13.2.1, S14.1.1 | ✅ Covered |
| FR-T05 | System prompt generated by `build_system_prompt(persona_config)` ≤ 400 tokens | §2.3 | S14.2.4 | ✅ Covered |

### §5.7 — MCP Server

| BRD FR | Requirement (summary) | Architecture § | User Story | Status |
|---|---|---|---|---|
| FR-M01 | MCP server implements JSON-RPC 2.0 HTTP on `127.0.0.1:8092` | §2.6 | S17.1.1 | ✅ Covered |
| FR-M02 | Six read-only tools: `get_portfolio_state`, `get_signal_snapshot`, `get_regime_state`, `get_agent_status`, `get_universe_state`, `get_persistence_scores` | §2.6 | S17.1.1 | ✅ Covered |
| FR-M03 | Binds to `127.0.0.1` only; no external exposure | §2.6 | S17.1.1 | ✅ Covered |
| FR-M04 | SQLite connections are read-only (`?mode=ro`); no writes from MCP | §2.6 | S17.1.1 | ✅ Covered |

### §5.8 — Shared Libraries

| BRD FR | Requirement (summary) | Architecture § | User Story | Status |
|---|---|---|---|---|
| FR-L01 | Four `mocha-python-*` libraries as independent repos with CI | §2.7 | S20.0.1 | ✅ Covered |
| FR-L02 | `AuditLogger` used by all agents; no direct SQL in agent code | §2.7 | S20.1.1 | ✅ Covered |
| FR-L03 | `IntegrationLogger` / `@log_integration` wraps all outbound network calls | §2.7 | S20.1.2 | ✅ Covered |
| FR-L04 | `AIClient.chat_with_tools()` abstracts all LLM providers; retry + fallback centralised | §2.7 | S20.2.1 | ✅ Covered |
| FR-L05 | `AgentBootstrap` self-registers Agent Cards; Orchestrator discovers via `get_live_agents()` | §2.7 | S20.3.1 | ✅ Covered |
| FR-L06 | All consuming projects import from installed packages; no embedded copies | §2.7 | S20.4.1 | ✅ Covered |
| FR-L07 | Concurrent write safety: `AuditLogger` tested with 5-thread simultaneous writes | §2.7 | S20.1.1 | ✅ Covered |
| FR-L08 | qwen3 models receive `reasoning_effort: none` + `reasoning_format: hidden`; handled in `AIClient` | §2.7 | S20.2.1 | ✅ Covered |
| FR-L09 | DataCollector is an independent process; WebSocket no longer in-process | §2.8 | S21.1.1 | ✅ Covered |
| FR-L10 | FulfillmentService is an independent process; broker calls no longer in-process | §2.8 | S21.2.1 | ✅ Covered |

### §5.9 — Runtime Components

| BRD FR | Requirement (summary) | Architecture § | User Story | Status |
|---|---|---|---|---|
| FR-RT01 | Agent mesh runs as separate process containers communicating via IPC | §2.8 | S16.1.1, S21.1.1 | ✅ Covered |
| FR-RT02 | DataCollector writes complete candles to `candle_buffer` within 5s of close | §2.8 | S21.1.1 | ✅ Covered |
| FR-RT03 | Feed freeze detection per pair; Orchestrator excludes frozen pairs | §2.8 | S21.1.2 | ✅ Covered |
| FR-RT04 | FulfillmentService REST API: `POST /fill`, `GET /positions`, `GET /balance` | §2.8, §11 | S21.2.1 | ✅ Covered |
| FR-RT05 | SL/TP monitoring in FulfillmentService; runs every 60s independent of agent cycle | §2.8 | S21.2.3 | ✅ Covered |
| FR-RT06 | Every `POST /fill` attempt logged to `fulfillment_audit` before response returned | §2.8, §12.4 | S21.2.2 | ✅ Covered |

### §5.10 — Research Analyst Agent (RAA)

| BRD FR | Requirement (summary) | Architecture § | User Story | Status |
|---|---|---|---|---|
| FR-RAA01 | RAA polls Kraken + CoinGecko every 30 minutes; accumulates Persistence Score | §2.9 | S22.1.1 | ✅ Covered |
| FR-RAA02 | `PROPOSE(pair, replace_target?)` submitted after Ps > 1.5 for ≥ 4 consecutive cycles and alpha spread > +2.0% | §2.9 | S22.1.2 | ✅ Covered |
| FR-RAA03 | Meme-block: MEME pair cannot displace FOUNDATIONAL pair | §2.9 | S22.2.1 | ✅ Covered |
| FR-RAA04 | SHIELDA self-correction: 3× 422 rejection → drop proposal; stale feed → halt pair | §2.9 | S22.2.2 | ✅ Covered |
| FR-RAA05 | Medium persona RSI gate (35–65) + ADX gate (< 25) for RAA proposals | §2.9 | S22.3.1 | ✅ Covered |
| FR-RAA06 | Hard-coded meme-block enforced in Python; no config or LLM override possible | §2.9 | S22.2.1 | ✅ Covered |
| FR-RAA07 | Kraken OHLCV variance == 0 halts RAA proposals for that pair | §2.9 | S22.2.2 | ✅ Covered |
| FR-RAA08 | High persona RSI bypass up to 85 (IFF ADX > 35 AND VWMA_Slope > 0) + aggressive pruning | §2.9 | S22.3.2 | ✅ Covered |

### §5.11 — Closed-Loop Optimization (Audit Agent and Feedback Loops)

| BRD FR | Requirement (summary) | Architecture § | User Story | Status |
|---|---|---|---|---|
| FR-CLO01 | Audit Agent runs as independent process on port 8094; post-hoc evaluator only | §2.10 | S23.1.1 | ✅ Covered |
| FR-CLO02 | 24h Validation Window; PSV outcome vector written to `audit_feedback` on close | §2.10 | S23.1.1 | ✅ Covered |
| FR-CLO03 | Reprimand Vector written immediately on every RM 422 / MEME_BLOCK rejection | §2.10 | S23.1.1 | ✅ Covered |
| FR-CLO04 | RAA reads last 50 outcome vectors; four-phase Self-Reflection Loop per poll cycle | §2.10 | S23.1.2 | ✅ Covered |
| FR-CLO05 | SHIELDA Confidence Reset: > 3σ deviation over 5 events → agent reverts to base config | §2.10 | S23.1.3 | ✅ Covered |
| FR-CLO06 | HITL Lock: 3 FOUNDATIONAL_REPLACEMENT_BLOCKs in 24h → RAA proposals routed to `hitl_queue` | §2.10 | S23.1.3 | ✅ Covered |
| FR-CLO07 | Orchestrator biases playbook using `playbook_performance` (≥ 10 samples) | §2.10 | S23.2.1 | ✅ Covered |
| FR-CLO08 | QSA reads per-driver `weight_multiplier` from `signal_accuracy`; bounded [0.5, 1.5] | §2.10 | S23.2.2 | ✅ Covered |
| FR-CLO09 | AIE injects up to 3 negative few-shot lessons; ≤ 200 token budget | §2.10 | S23.2.3 | ✅ Covered |
| FR-CLO10 | ROM advisory only: `sl_hit_rate > 60%` over ≥ 20 trades → Telegram advisory; no auto-adjust | §2.10 | S23.2.4 | ✅ Covered |

---

## Summary

| BRD Section | FR Count | Covered | Gaps |
|---|---|---|---|
| §5.1 Persona Framework | 5 | 5 | 0 |
| §5.2 QSA Data Resilience | 7 | 7 | 0 |
| §5.3 AIE Context Engineering | 8 | 8 | 0 |
| §5.4 ROM Reallocation & Momentum | 7 | 7 | 0 |
| §5.5 Orchestrator | 5 | 5 | 0 |
| §5.6 Token Format | 5 | 5 | 0 |
| §5.7 MCP Server | 4 | 4 | 0 |
| §5.8 Shared Libraries | 10 | 10 | 0 |
| §5.9 Runtime Components | 6 | 6 | 0 |
| §5.10 RAA | 8 | 8 | 0 |
| §5.11 Closed-Loop Optimization | 10 | 10 | 0 |
| **Total** | **75** | **75** | **0** |

**Traceability status: COMPLETE — all 75 BRD functional requirements are covered by user stories.**

---

## NFR Coverage

| NFR | Requirement | Covered by |
|---|---|---|
| NFR-01 | Full agent cycle ≤ 30 min | S16.2.1 (timeout detection), S14.1.2 (token estimator) |
| NFR-02 | Every agent LLM input/output logged to `agent-llm-prompts.log` | S20.1.2 (IntegrationLogger), S20.2.1 (AIClient) |
| NFR-03 | Persona switch logged with actor + from/to fields | S12.1.2, S18.1.1 |
| NFR-04 | Winsorized EMA adds < 5ms to per-pair indicator time | S13.1.1 (AC includes performance validation) |
| NFR-05 | MCP responds within 500ms | S17.1.1 (S6 gate condition) |
| NFR-06 | Capital reallocation: no Telegram confirm for Medium/High; Medium capped to 20%/6h | S15.1.2 |
