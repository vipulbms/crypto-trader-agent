# Business Requirements Document
## Kryptos — AI Crypto Trading Agent

| Field | Value |
|---|---|
| Document version | 3.0 |
| Date | 19 April 2026 |
| Author | Vipul Sanghrajka |
| Status | Draft — awaiting clarifications |
| Supersedes | docs/business_requirements.md (v2.4) |

| Revision | Change summary |
|---|---|
| 3.0 | **Persona-Based Multi-Agent Architecture**: three risk personas (Conservative / Medium / High); multi-agent framework (Orchestrator + QSA + AIE + ROM agents); Winsorized EMA volume floor; OHLCV variance-based feed heartbeat; state-aware LLM context engineering; capital reallocation subroutine; velocity-based circuit breaker; regime-switching playbooks; MCP server for external agent integration; pipe-separated LLM payload format (≤6000 tokens/call) |

---

## 1. Executive Summary

The April 18, 2026 market event exposed a systemic architectural failure in Kryptos v2: a **coordination gap between three independently operating layers** (Signal Engine, LLM Advisor, Risk Manager). During a significant BTC/ETH price surge, the agent executed zero new long entries despite eighteen pairs producing mathematically valid buy signals. Root causes:

1. **Layer 1 — Signal Engine:** Stale SMA-20 volume floor inflated by historical liquidation spikes; BTC/USD WebSocket feed delivering identical candles for thirty consecutive cycles (zero variance, undetected).
2. **Layer 2 — LLM Advisor:** No awareness of Risk Manager constraints; squandered its quota on already-open positions (ETH/SOL) while valid altcoin signals (SUI, PENDLE, ONDO) were discarded.
3. **Layer 3 — Risk Manager:** Hard `+1.0%` profit floor blocked reallocation; `13/10` position gridlock with `$265` available cash; Correlation Guard blocking sector entries already occupied by stagnant holders.

Version 3 restructures Kryptos into a **Persona-Based Multi-Agent System** where each persona inherits a different risk tolerance, signal threshold, and capital allocation strategy — while all personas share the same audited deterministic safeguards.

---

## 2. Business Objectives

Unchanged objectives from v2 are retained. The following are added or revised:

| ID | Objective | New/Changed |
|---|---|---|
| BO-01 | Automate cryptocurrency trading without manual oversight | Unchanged |
| BO-02 | **Protect invested capital** as primary goal for Conservative persona; **balance alpha capture with protection** for Medium persona; **maximise alpha with managed risk** for High persona | Changed — now persona-scoped |
| BO-03 | Validate persona behaviour in paper mode before live deployment | Unchanged |
| BO-04 | Provide full transparency into every agent decision | Unchanged |
| BO-05 | AI inference remains local or via pre-approved cloud providers (Groq) only | Unchanged |
| BO-06 | Real-time Telegram alerts per persona | Unchanged |
| BO-07 | Operate as Maker via Post-Only Limit orders | Unchanged |
| BO-08 | Survive API anomalies, feed freezes, and exchange errors autonomously | Changed — adds feed variance detection |
| BO-09 | Full backtesting pipeline per persona | Unchanged |
| **BO-10** | **Support three distinct risk personas that can run concurrently or be switched at runtime** | **New** |
| **BO-11** | **Multi-agent coordination — each logical agent (QSA, AIE, ROM) has a defined role, isolated context, and audited input/output** | **New** |
| **BO-12** | **Capital reallocation logic: when the portfolio is at capacity and a high-score signal appears, stagnant positions can be pruned per persona policy** | **New** |
| **BO-13** | **LLM call token budget ≤ 6,000 per cycle, enforced via pipe-separated key-value payload format** | **New** |
| **BO-14** | **Expose Kryptos agent state via MCP server so external AI clients (Claude Desktop, VS Code Copilot) can query portfolio and signal data** | **New** |

---

## 3. Stakeholders

| Role | Responsibility | New/Changed |
|---|---|---|
| Product Owner | Defines requirements; selects active persona; reviews paper results | Changed — now selects persona |
| Trading Agent — Orchestrator | Meta-planner; selects playbook; routes to specialist agents | **New** |
| Trading Agent — QSA | Data layer; signal engine; regime detection; feed validation | **New** |
| Trading Agent — AIE | Context engineering; state-aware prompt construction; LLM delegation | **New** |
| Trading Agent — ROM | Risk enforcement; position sizing; liquidity pruning; circuit breaker | Changed — expanded role |
| Kraken Exchange | Executes orders; provides market data | Unchanged |
| healthchecks.io | Uptime monitoring | Unchanged |
| External AI Client (optional) | Queries portfolio state via MCP server | **New** |

---

## 4. Scope

### 4.1 In Scope — Unchanged from v2.4
- All 29 active trading pairs (30 configured, RAILS/USD disabled)
- Technical analysis indicators: RSI, MACD, EMA 9/21/50, ATR, Bollinger Bands, ADX, OBV, RSI divergence, candlestick patterns
- Real-time Order Book Imbalance (OBI) streaming
- SQLite audit database, Telegram notifications, healthchecks.io ping
- Backtesting pipeline, paper mode, live Kraken execution

### 4.2 In Scope — New for v3

| Feature | Description |
|---|---|
| Three Risk Personas | Conservative (current rules), Medium Risk, High Risk / High Reward |
| Persona Config | Each persona has its own `config.yaml` profile section with independent thresholds |
| QSA Agent | Winsorized EMA-14 volume floor; OHLCV 3-cycle variance heartbeat; automatic failover to CoinGecko/Binance on feed freeze |
| AIE Agent | State-aware prompt: portfolio_state + risk_constraints + unfilled_clusters; sub-agent delegation pattern |
| ROM Agent | Capital Reallocation Subroutine (ADX-based pruning); Momentum Bypass RSI thresholds; velocity-based circuit breaker |
| Orchestrator Agent | Regime-switching meta-planner; playbook selection (Ranging / Momentum / Risk-Off); exception / deadlock handler |
| Pipe-Separated LLM Payload | All LLM prompts use `key\|value\|key\|value` format instead of JSON; token budget ≤ 6,000 per cycle |
| MCP Server | `kryptos-mcp` server exposing portfolio, signals, and regime state to external AI clients via JSON-RPC 2.0 |
| Regime Detection | Markov two-state regime classifier: Stable (Regime-0) vs Turbulent (Regime-1) based on ADX + ATR volatility |
| Research Analyst Agent | Continuously evaluates the broader crypto universe; computes rolling Persistence Score per candidate pair; submits `PROPOSE(pair, replace_target?)` with alpha-spread validation; enforces hard-coded meme-block guardrail; manages universe cap (≤ 35 pairs) |

### 4.3 Out of Scope — v3
- Changing the underlying exchange from Kraken
- Order book depth beyond current OBI implementation
- Cross-exchange arbitrage
- Derivatives / futures / margin trading
- Shared capital pools across runtimes (each concurrent persona has its own isolated DB and independent capital)
- Real-time price feed for MCP (MCP provides last-cycle snapshot only)

---

## 5. Functional Requirements

### 5.1 Persona Management

| ID | Requirement |
|---|---|
| FR-P01 | The system MUST support exactly three personas: `conservative`, `medium`, `high` |
| FR-P02 | The active persona MUST be selectable via: (a) `config.yaml → agent.persona`, (b) CLI `kryptos persona set <name>`, (c) Kryptos API `PUT /api/v2/persona` |
| FR-P03 | Switching persona MUST take effect at the start of the next trading cycle; mid-cycle switches are not permitted |
| FR-P04 | When personas run concurrently (paper testing), each MUST use an isolated SQLite database: `paper_trading_conservative.db`, `paper_trading_medium.db`, `paper_trading_high.db`. When a single persona is active (live or focused paper), the standard `live_trading.db` or `paper_trading.db` is used |
| FR-P05 | Each persona MUST define values for: `buy_min_score`, `max_position_pct`, `max_open_positions`, `min_profit_floor_pct`, `rsi_overbought_veto`, `llm_temperature`, `momentum_bypass_adx_threshold`, `reallocation_enabled`, `velocity_circuit_breaker_pct_per_hour` |

### 5.2 QSA Agent (Data Resilience)

| ID | Requirement |
|---|---|
| FR-Q01 | The volume floor calculation MUST use a 14-period Winsorized EMA (95th percentile cap) instead of SMA-20 |
| FR-Q02 | Per-pair `obv_trend_period` and `obv_noise_threshold` continue to apply; Winsorized EMA replaces only the `rolling_volume_p15` floor |
| FR-Q03 | The system MUST compute OHLCV variance across the last 3 completed candles per pair each cycle |
| FR-Q04 | If variance == 0 for a pair, the system MUST flag that pair as `FEED_FROZEN` and suppress its signal from the current cycle |
| FR-Q05 | If BTC/USD is `FEED_FROZEN`, the Orchestrator MUST attempt failover to CoinGecko `/simple/price` or Binance public REST within 60 seconds |
| FR-Q06 | The QSA MUST output a `regime_state` per pair: `stable`, `trending_up`, `trending_down`, or `turbulent` |
| FR-Q07 | Volume Dead Zone Momentum Bypass: when `price > bb_upper` AND the MACD histogram registers a fresh positive crossover (prior candle `macd_hist < 0`, current candle `macd_hist ≥ 0`), the Volume Dead Zone veto MUST be suspended for that pair in that cycle. This bypass MUST only activate for Medium and High personas; Conservative persona retains the unmodified volume veto. The bypass is computed in `signals.py`; QSA injects `macd_hist_prev` alongside `macd_hist` so the crossover is detectable without additional indicator calls. |

### 5.3 AIE Agent (Context Engineering)

| ID | Requirement |
|---|---|
| FR-A01 | The LLM prompt MUST include `portfolio_state` (pipe-separated open positions: entry price, current PnL, sector cluster) |
| FR-A02 | The LLM prompt MUST include `risk_constraints` (max_positions remaining, cash available, kill switch state) |
| FR-A03 | The LLM prompt MUST include `unfilled_clusters` (sectors with available correlation slots) |
| FR-A04 | The LLM MUST receive a persona-specific system role: Conservative = "Capital Preservation Advisor", Medium = "Balanced Portfolio Manager", High = "Alpha-Seeking Fund Manager" |
| FR-A05 | The maximum token count per LLM call (prompt + completion) MUST NOT exceed 6,000 tokens |
| FR-A06 | All per-pair signal data sent to the LLM MUST use pipe-separated format: `pair\|{pair}\|score\|{score}\|rsi\|{rsi}\|adx\|{adx}\|regime\|{regime}\|...` |
| FR-A07 | HOLD-signal pairs continue to be excluded from the LLM prompt (no change from v2) |
| FR-A08 | The AIE MUST produce a `ranked_reallocation_strategy` when ROM signals capital gridlock: a sorted list of prune candidates by lowest ADX + lowest current PnL |

### 5.4 ROM Agent (Capital Protection + Reallocation)

| ID | Requirement |
|---|---|
| FR-R01 | Capital Reallocation Subroutine: if `open_positions >= max_open_positions` AND an incoming signal score >= `reallocation_trigger_score` (8) AND ADX > 25, the ROM MUST evaluate pruning the weakest position |
| FR-R02 | Prune candidate = position with lowest ADX + current PnL in range `[-stop_loss_pct, +min_profit_floor_pct * 1.5]`; positions in strong drawdown recovery (-3%+) are protected from pruning |
| FR-R03 | Momentum Bypass: per persona, RSI overbought veto is raised when ADX is rising between 30 and persona-specific bypass threshold (Conservative=70, Medium=75, High=80) |
| FR-R04 | Velocity-based circuit breaker: if portfolio loss rate exceeds `velocity_circuit_breaker_pct_per_hour` within a rolling 60-minute window, trading is halted for `velocity_halt_hours` |
| FR-R05 | Reallocation is DISABLED for Conservative persona; ENABLED for Medium and High. Medium persona reallocation is subject to a rolling 6-hour cap: total value reallocated within any 6-hour window must not exceed 20% of current portfolio value |
| FR-R06 | Profit Factor Escalation Suspension: when the active playbook is `momentum`, the PF auto-escalation penalty (`+1` when PF < 1.0; `+2` when PF < 0.7) MUST be suppressed globally for all pairs in that cycle. The ROM MUST use the persona default `buy_min_score` without PF adjustments. PF escalation resumes automatically when the playbook reverts to `ranging` or `risk_off`. Applies to Medium and High personas only; Conservative persona retains PF escalation in all playbooks. Rationale: pairs with depressed PF are disproportionately beaten-down altcoins — the first to recover in a V-shaped rally. Adding +2 to their entry bar during momentum onset creates a policy collision with the momentum playbook's intent. |
| FR-R07 | Early Momentum Accumulation Score Reduction: if a pair's RSI is in the range [50, 65] AND its ADX > 25, the ROM MUST apply a −1 delta to that pair's effective `buy_min_score` for that cycle. Applies to Medium and High personas only; Conservative persona is unaffected. This delta is applied after persona default and after any PF suspension decision; it is not additive with the PF escalation penalty (when FR-R06 suppresses PF, FR-R07 still applies independently). Floor: effective score cannot be reduced below 1. Rationale: RSI 50–65 with rising ADX identifies early institutional accumulation before retail participation — the optimal front-run window that the RSI overbought bypass (FR-R03) cannot capture. |

### 5.5 Orchestrator Agent (Meta-Planner)

| ID | Requirement |
|---|---|
| FR-O01 | The Orchestrator MUST classify each cycle into one of three playbooks: `ranging`, `momentum`, `risk_off` |
| FR-O02 | Playbook selection logic: ADX < 20 → `ranging`; ADX ≥ 25 + regime = `trending_up` → `momentum`; regime = `turbulent` OR daily_pnl ≤ -3% → `risk_off` |
| FR-O03 | The Orchestrator MUST inject the active playbook into the ROM agent context so it applies the correct rule set |
| FR-O04 | The Orchestrator MUST detect agent deadlock (any agent non-responsive for > 30 seconds) and execute recovery: skip that cycle, log ERROR, send Telegram alert |
| FR-O05 | The Orchestrator MUST persist `playbook_state`, `active_persona`, and `regime_state` in `agent_state` table each cycle for observability |

### 5.6 Pipe-Separated LLM Payload Format

| ID | Requirement |
|---|---|
| FR-T01 | Per-pair signal block format: `pair\|{pair}\|score\|{n}/28\|direction\|{BUY/SELL}\|rsi\|{n}\|adx\|{n}\|macd_hist\|{n}\|bb_pos\|{n}\|regime\|{r}\|price\|{p}\|tp_pct\|{n}\|sl_pct\|5\|max_buy_usd\|{n}` |
| FR-T02 | Portfolio state block format: `pos\|{pair}\|entry\|{p}\|pnl_pct\|{n}\|pnl_usd\|{n}\|tp_dist_pct\|{n}\|sl_dist_pct\|{n}\|adx\|{n}\|cluster\|{c}` |
| FR-T03 | Risk constraints block format: `cash_usd\|{n}\|positions_open\|{n}\|positions_max\|{n}\|kill_switch\|{0/1}\|circuit_open\|{0/1}\|playbook\|{ranging/momentum/risk_off}\|persona\|{conservative/medium/high}` |
| FR-T04 | Token estimation MUST be performed before each LLM call; if estimated tokens > 5,800, HOLD-signal pairs are further filtered until the budget is met |
| FR-T05 | System prompt MUST be condensed to ≤ 400 tokens; persona role injection replaces verbose instructions |

### 5.7 MCP Server

| ID | Requirement |
|---|---|
| FR-M01 | A `kryptos-mcp` server MUST be implemented exposing the following tools: `get_portfolio_state`, `get_signal_snapshot`, `get_regime_state`, `get_agent_status` |
| FR-M02 | MCP transport: HTTP (127.0.0.1:8092, no auth — accessible to local processes only); supports multiple concurrent agent callers; used by Orchestrator, RAA, and ROM agents at runtime |
| FR-M03 | All MCP tool outputs MUST be read-only; no execution tools (buy/sell) are exposed via MCP in v3 |
| FR-M04 | MCP server MUST read from the SQLite database (paper or live) as configured; it does not interface with the live trading loop |

### 5.8 Shared Libraries

| ID | Requirement |
|---|---|
| FR-L01 | **Audit Library** (repo: `mocha-python-audit`, package: `mocha_python_audit`): A shared, side-effect-free audit module MUST be used by every agent and every runtime component to write structured records to the audit database. All callers MUST go through this library; direct SQL inserts for audit purposes are forbidden outside this module. |
| FR-L02 | The audit library MUST expose: `log_cycle(cycle_context)`, `log_signal(pair, score, direction, reasons, cycle_id)`, `log_trade(trade_record)`, `log_balance_snapshot(balance, cycle_id)`, `log_error(component, error, cycle_id)`, `log_fulfillment(fulfillment_record)`. All calls MUST be synchronous with a 500ms write timeout. |
| FR-L03 | **Integration Logging Library** (repo: `mocha-python-logging`, package: `mocha_python_logging`): Every outbound integration call (Groq API, Kraken REST, Kraken WebSocket, CoinGecko, CoinGlass, healthchecks.io, Telegram) MUST be logged via this library with: `component`, `operation`, `request_payload` (sanitised — no API keys), `response_status`, `response_payload_summary`, `duration_ms`, `timestamp`, `cycle_id`. Log destination: `/logs/integration.log` (100 MB × 5 rotating files). |
| FR-L04 | The integration logging library MUST provide a `@log_integration(component, operation)` decorator applicable to any async/sync function, extracting duration automatically. Manual call sites are also supported via `IntegrationLogger.log(...)`. |
| FR-L05 | **AI Library** (repo: `mocha-python-ai`, package: `mocha_python_ai`): All LLM calls MUST route exclusively through a single `AIClient` class. The library encapsulates Groq API connection details, model selection, retry logic (3 attempts, exponential backoff), fallback model switching, and `reasoning_effort`/`reasoning_format` header injection. No agent or component may instantiate a Groq or Ollama client directly. |
| FR-L06 | `AIClient` MUST support: `chat_with_tools(messages, tools, persona_params) -> ToolCallResponse`; internally logs every call via the integration logging library (FR-L03) before returning. Connection credentials read exclusively from environment variables (`GROQ_API_KEY`); never from config files. |
| FR-L07 | **Agent Bootstrap Library** (repo: `mocha-python-agent`, package: `mocha_python_agent`): Every agent process MUST call `AgentBootstrap.start(agent_name, version, capabilities)` at startup. This registers the agent's **Agent Card** — a JSON document describing the agent's name, version, capabilities, input/output schema, health endpoint, and discovery URL — in the `agent_registry` table of the shared SQLite DB. |
| FR-L08 | The agent bootstrap library MUST expose: `register_agent_card(agent_card: AgentCard)`, `deregister_on_shutdown()`, `get_live_agents() -> List[AgentCard]`, `health_check() -> bool`. Agent cards MUST be discoverable by the Orchestrator and by external MCP clients via `get_agent_status`. |
| FR-L09 | Each of the four shared libraries MUST be maintained in its own independent git repository with a `pyproject.toml`, semantic versioning (`MAJOR.MINOR.PATCH`), and a `CHANGELOG.md`. Libraries MUST be installable in any Python project via `pip install git+https://<repo>.git@vX.Y.Z` or from a private package registry. No library may import from any Kryptos project module; all configuration must be injected at construction time. |
| FR-L10 | All consuming projects (including Kryptos) MUST declare all four shared library dependencies as **exact-version** entries in `requirements.txt`. All imports MUST use the installed package namespace (e.g., `from mocha_python_audit import AuditLogger`). Relative imports (`from src.lib.*`) and unpinned version ranges (`>=`) are forbidden. |

### 5.9 Separate Runtime Components

| ID | Requirement |
|---|---|
| FR-RT01 | **Data Collector Runtime** (`src/runtime/data_collector.py`): WebSocket price feed and OHLCV candle buffering MUST run as an independent OS process, fully decoupled from the trading agent loop. It writes candle data to the shared SQLite DB table `candle_buffer` every completed candle. The trading agent reads from this table rather than embedding the WebSocket connection inside the trading loop. |
| FR-RT02 | The Data Collector MUST expose a `/health` HTTP endpoint (port configurable, default 8091) returning `{"status": "ok", "pairs": N, "last_candle_ts": T}` so the Orchestrator can verify feed health independently. |
| FR-RT03 | **Fulfillment Service Runtime** (`src/runtime/fulfillment_service.py`): All trade execution (buy/sell on Kraken in live mode; simulated fills in paper mode) MUST be performed by an independent Fulfillment Service process. The trading agent MUST call the Fulfillment Service via a local REST API (`POST /fill`, `POST /cancel`, `GET /positions`, `GET /balance`) rather than executing orders directly. |
| FR-RT04 | The Fulfillment Service REST API MUST run on a locally-bound port (default 8090, configurable). It MUST NOT be accessible from external networks (bind to `127.0.0.1` only). Authentication: Bearer token from environment variable `FULFILLMENT_SERVICE_TOKEN`. |
| FR-RT05 | Every fulfillment request handled by the Fulfillment Service MUST be written to the `fulfillment_audit` table in the audit DB before returning the response. The audit record MUST include: `fulfillment_id` (UUID), `requested_at`, `pair`, `side` (BUY/SELL), `requested_usd`, `actual_price`, `actual_quantity`, `fee_usd`, `slippage_pct`, `execution_mode` (live/paper), `execution_status` (filled/rejected/partial), `kraken_order_id` (live only), `cycle_id`, `duration_ms`. |
| FR-RT06 | The paper-mode Fulfillment Service MUST replicate current `PaperBroker` logic (slippage, fee deduction, SL/TP monitoring) without change. The live-mode Fulfillment Service MUST replicate current `KrakenClient` logic. Both modes MUST share the same REST API contract so the calling agent is mode-agnostic. |

### 5.10 Research Analyst Agent — Universe Management

| ID | Requirement |
|---|---|
| FR-RAA01 | The Research Analyst Agent (RAA) MUST run as an independent process container (`src/runtime/research_analyst.py`) polling every 30 minutes, aligned with the trading cycle cadence. It MUST be fully decoupled from the 30-minute trading cycle; a RAA computation timeout MUST NOT delay or block the trading cycle. |
| FR-RAA02 | The RAA MUST compute a **Persistence Score (Ps)** per candidate pair using Kraken `AssetPairs`/`Ticker` and CoinGecko `Trending`/`Social` REST data. A PROPOSE event MUST only be submitted when Ps > 1.5 is sustained for ≥ 4 consecutive 30-minute cycles (≥ 2 hours). Any cycle where Ps ≤ 1.5 resets the consecutive counter to zero. |
| FR-RAA03 | Every proposal MUST satisfy an **Alpha Spread Gate**: projected alpha > 2.0% over the replacement target's rolling 30-day return (or worst-performing current pair when no replacement target is specified). Proposals failing this gate MUST be rejected and logged in `audit_events`. |
| FR-RAA04 | The tradeable universe is capped at **35 pairs**. When N = 35, any PROPOSE event MUST include a valid `replace_target`. The Risk Manager MUST reject proposals that omit `replace_target` when the cap is reached. |
| FR-RAA05 | Every candidate pair MUST be classified as `FOUNDATIONAL` (L1/L2 commodities: BTC, ETH, SOL, established chains) or `MEME` (socially-driven collectibles) before a proposal is submitted. Classification is driven by LLM reasoning with deterministic post-validation. |
| FR-RAA06 | **RAI Meme-Block (hard-coded; cannot be overridden by LLM or config):** A `MEME`-classified pair MUST NEVER be proposed as a replacement for a `FOUNDATIONAL` pair. This rule MUST be evaluated deterministically in Python code before any LLM call. Violations are blocked and logged as `[RAA] MEME_BLOCK_REJECT`. |
| FR-RAA07 | **SHIELDA Exception Management:** (a) Malformed pipe-data — Risk Manager returning `422 Unprocessable Entity` triggers a self-correction prompt; up to 3 retry attempts before the proposal is dropped and `[RAA] SELF_CORRECT_FAILED` is logged. (b) Stale feed — Kraken `Ticker` OHLCV variance = 0 for a candidate pair halts all RAA proposals for that pair in the current cycle; logged as `[RAA] STALE_FEED_HALT`. |
| FR-RAA08 | Every RAA proposal MUST store a **PSV context vector** (Medium: `Pair\|Price\|RSI\|ADX\|IBS\|Sector\|State`; High: `Pair\|Price\|RSI\|ADX\|VWMA_Slope\|Sector\|State`) and an LLM-generated `rationale` string in the `audit_events` table. Proposals without a complete PSV context vector MUST be rejected. |

---

### 5.11 Closed-Loop Optimization — Audit Agent and Feedback Loops

| ID | Requirement |
|---|---|
| FR-CLO01 | A dedicated **Audit Agent** (`src/runtime/audit_agent.py`) MUST run as an independent process container on port 8094. It MUST NOT participate in trading cycle decisions — it is a post-hoc evaluator only. |
| FR-CLO02 | The Audit Agent MUST evaluate RAA trend proposals over a configurable **Validation Window** (default 24h) and write a PSV outcome vector (`Pair\|RAA_Expected_Alpha\|Actual_Alpha\|RAA_Persistence_Score\|Actual_Persistence\|Outcome`) to `audit_feedback` when the window closes. |
| FR-CLO03 | On every Risk Manager rejection (422 or MEME_BLOCK), the Audit Agent MUST immediately write a Reprimand Vector (`Pair\|Action\|Violation_Type\|Rule_Reference\|Penalty_Weight`) to `audit_feedback`. |
| FR-CLO04 | The RAA MUST read the last 50 outcome vectors from `audit_feedback` at the start of each 30-min poll cycle and execute a four-phase Self-Reflection Loop: INGESTION → SELF_CRITIQUE → DB_UPSERT → META_PROMPT. Reflection results MUST be stored in `llm_reflection_log`. |
| FR-CLO05 | **SHIELDA Confidence Reset:** If any agent's actual outcome deviates > 3 standard deviations from its expected outcome over any 5 consecutive events, the Audit Agent MUST write a `confidence_reset` event to `audit_feedback`. The affected agent MUST revert to base config heuristics at next cycle start. |
| FR-CLO06 | **HITL Lock:** After 3 `FOUNDATIONAL_REPLACEMENT_BLOCK` reprimands within any 24-hour window for RAA, the RAA Substitution Tool MUST be locked. All subsequent RAA proposals MUST be inserted into `hitl_queue` with `status=PENDING` and require explicit human approval via kryptos-ui or kryptos-api before execution. Lock duration: 24h from last violation, or until all pending HITL items are resolved. |
| FR-CLO07 | The Orchestrator MUST read `playbook_performance` at each cycle start. If the current regime has ≥ 10 historical cycles, Orchestrator MUST bias playbook selection toward playbooks with `profit_factor > 1.2`. Playbook MUST NOT change mid-cycle. |
| FR-CLO08 | QSA MUST read per-driver accuracy multipliers from `signal_accuracy` at cycle start. Multipliers are applied as weights to driver contribution scores and MUST be bounded to `[0.5, 1.5]` — no driver may be fully zeroed out by feedback alone. |
| FR-CLO09 | AIE MUST include up to 3 negative few-shot examples from `llm_reflection_log` (`injected=1`) in the system prompt as a "PATTERNS TO AVOID" block. Injection MUST NOT increase total prompt tokens by more than 200. When budget exceeded, oldest record is deactivated (`injected=0`) first. |
| FR-CLO10 | ROM feedback is **advisory only**. `risk_decision_outcomes` MUST be populated by the Audit Agent on a 24h rollup. When a pair's `sl_hit_rate` exceeds 60% over ≥ 20 trades, a Telegram advisory MUST be generated. Automatic SL or TP parameter adjustment is explicitly prohibited — changes require manual `config.yaml` edit and system restart. |

---

## 6. Non-Functional Requirements

| ID | Requirement |
|---|---|
| NFR-01 | A full cycle (QSA → AIE → ROM → Orchestrator) MUST complete within the 30-minute cycle interval |
| NFR-02 | Each agent's input and output MUST be written to the LLM interaction log (`agent-llm-prompts.log`) |
| NFR-03 | Persona switch MUST be reflected in audit logs with `actor=cli\|api`, `from_persona`, `to_persona`, `timestamp` |
| NFR-04 | Winsorized EMA computation MUST add < 5ms to per-pair indicator calculation time |
| NFR-05 | MCP server MUST respond to tool calls within 500ms (SQLite read latency) |
| NFR-06 | Capital Reallocation is auto-executed for Medium and High personas — no Telegram confirmation message is sent. Medium persona: limited to 20% of portfolio value per rolling 6-hour window. High persona: no cap. Conservative persona: disabled entirely |

---

## 7. Risk and Mitigation

| Risk | Impact | Mitigation |
|---|---|---|
| High persona incurs large drawdown | High | Daily loss limit, velocity circuit breaker, kill switch all remain active regardless of persona |
| Capital reallocation sells a position just before recovery | Medium | Prune candidate must be in low-ADX + low-gain zone; positions in deep loss are never pruned (ROM rule FR-R02) |
| Persona switch mid-adverse-market | Medium | Switching persona does not change open positions; only new entries follow new persona rules |
| LLM token budget exceeded despite pipe format | Low | Pre-call token estimator + pair count limiter; maximum 15 BUY/SELL pairs ever sent |
| MCP server exposes portfolio data | Low | MCP binds to 127.0.0.1 only; Bearer auth required; read-only tools only; no external network exposure |
| Feed freeze undetected | Medium | OHLCV variance heartbeat per pair per cycle; zero variance = immediate flag |
| PF escalation suspends momentum entries for recovering pairs | Medium | Suspension applies to Medium/High only; Conservative still enforces PF penalty always; ADX and RSI gates still active |
| Early momentum score reduction triggers false entry in low-conviction regime | Low | Requires RSI ≥ 50 AND ADX > 25 simultaneously; net threshold still ≥ 2 after reduction; SL/TP unchanged |
| Stale CoinGecko trending data causes false Persistence Score inflation | Medium | Per-cycle Kraken OHLCV variance check (FR-RAA07b) halts proposals when feed variance = 0; stale candidates are not promoted |
| Meme-block bypass via parameter exploit or LLM instruction | High | Rule is hard-coded in Python deterministic pre-validation; no config flag or LLM prompt can override it (FR-RAA06) |

---

## 8. Personas Reference Table

| Parameter | Conservative | Medium | High |
|---|---|---|---|
| `buy_min_score` (global default) | 5 | 4 | 3 |
| `max_open_positions` | 10 | 12 | 15 |
| `max_position_pct` | 20% | 25% | 30% |
| `min_profit_floor_pct` | 1.0% | 0.5% | 0.0% (fee cover only) |
| `rsi_overbought_veto` (base) | 70 | 70 | 70 |
| Momentum bypass RSI threshold | 70 (no change) | 75 | 80 |
| Momentum bypass ADX trigger | N/A | ≥ 25 | ≥ 25 |
| `max_position_pct` (drawdown recovery) | 10% | 15% | 20% |
| Capital reallocation | Disabled | Enabled (auto, ≤20% of portfolio / 6h window) | Enabled (auto, no cap) |
| LLM temperature | 0.1 | 0.3 | 0.5 |
| LLM max_tokens | 1500 | 2000 | 2500 |
| System role | "Capital Preservation Advisor" | "Balanced Portfolio Manager" | "Alpha-Seeking Fund Manager" |
| Velocity circuit breaker (%/hr) | 2% | 3% | 5% |
| Velocity halt duration (hours) | 4h | 2h | 1h |
| Volume floor algorithm | Winsorized EMA-14 | Winsorized EMA-14 | Winsorized EMA-14 |
| Feed freeze failover | Yes | Yes | Yes |
| Playbook: Ranging | Mean-reversion rules | Mixed | Mixed |
| Playbook: Momentum | Conservatively participates | Full participation | Aggressive participation |
| Playbook: Risk-Off | Halt all new entries | Restrict to Tier-1 pairs | Restrict to Tier-1/2 pairs |
| Volume Dead Zone bypass (MACD crossover + price > BB upper) | Disabled | Enabled | Enabled |
| PF escalation suspension in Momentum playbook | Disabled | Enabled | Enabled |
| Early Momentum score reduction (RSI 50–65 AND ADX > 25) | None (0) | −1 | −1 |
| ADX ranging penalty (−1 when ADX < 20, per pair) | Active in all playbooks | Active in all playbooks | Active in all playbooks |

---

## 9. Assumptions and Dependencies

| ID | Assumption |
|---|---|
| ASS-01 | When running concurrently (paper testing all three), each persona uses its own SQLite database (`paper_trading_{persona}.db`). When only one persona is active (live or focused paper), the standard `paper_trading.db` or `live_trading.db` is used |
| ASS-02 | Open positions are not reassigned when persona is switched; persona governs new entry behaviour only |
| ASS-03 | Groq remains the LLM provider; model continues to be `qwen3-32b` with `llama-3.3-70b` fallback |
| ASS-04 | Winsorized EMA replaces `rolling_volume_p15`; all existing per-pair `min_volume_ratio` thresholds remain valid |
| ASS-05 | MCP server is optional/additive; the trading loop does not depend on it |
| ASS-06 | QSA, AIE, and ROM agents run as **separate process containers** communicating with the Orchestrator via IPC (Unix sockets). Each concurrent persona runtime is also an independent process tree with its own agent containers |
| ASS-07 | Volume Dead Zone bypass, PF escalation suspension, and early momentum score reduction are activated only for Medium and High personas. Conservative persona operates at full v2 production safeguard behaviour with no bypasses or reductions |
| ASS-08 | ADX ranging penalty (−1 per pair when ADX < 20) is intentionally retained in all playbooks including momentum. Macro momentum (portfolio-wide ADX median ≥ 25) does not guarantee local pair trend quality; individual pairs can be ranging locally even when the Orchestrator selects the momentum playbook |
| ASS-09 | The RAA runs as an advisory process only — it proposes universe changes but never directly modifies trading state, open positions, or config files. All changes are enacted by the Risk Manager after full gate validation. The 30-minute trading cycle is never blocked by a RAA computation timeout. |
