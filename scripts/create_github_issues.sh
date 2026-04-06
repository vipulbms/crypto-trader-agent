#!/usr/bin/env bash
# =============================================================================
# Kryptos — Full Epic & Story GitHub Issue Creator
# Covers Epics E1–E12 (E1–E11 from epics_stories_ac.md + E12 new)
# Stories are created as sub-issues under their parent Epic.
#
# Usage:    bash scripts/create_github_issues.sh
# Requires: gh CLI authenticated — run: gh auth status
# =============================================================================

set -e
REPO="vipulbms/crypto-trader-agent"

# Helper: create a story issue, register it as a sub-issue of the given epic number.
# Usage: create_story <epic_issue_num> <labels> <title> <body>
create_story() {
  local epic_num="$1"
  local labels="$2"
  local title="$3"
  local body="$4"

  local url
  url=$(gh issue create --repo "$REPO" --label "$labels" --title "$title" --body "$body")
  local story_num
  story_num=$(echo "$url" | grep -o '[0-9]*$')

  # Register as sub-issue of the epic
  gh api --method POST \
    "/repos/${REPO}/issues/${epic_num}/sub_issues" \
    --field sub_issue_id="$story_num" \
    --silent 2>/dev/null || \
    echo "    (sub-issue API unavailable — story #${story_num} created standalone)"

  echo "    Story #${story_num}: ${title}"
}

# -----------------------------------------------------------------------------
echo "==> Creating labels..."
gh label create "epic"               --color "#7B61FF" --description "Epic-level issue"                   --repo "$REPO" 2>/dev/null || true
gh label create "story"              --color "#0075CA" --description "User story with AC"                 --repo "$REPO" 2>/dev/null || true
gh label create "bug"                --color "#D93F0B" --description "Bug confirmed by backtest"          --repo "$REPO" 2>/dev/null || true
gh label create "enhancement"        --color "#84B6EB" --description "New feature or improvement"         --repo "$REPO" 2>/dev/null || true
gh label create "risk-management"    --color "#FBCA04" --description "Risk/compliance enforcement layer"  --repo "$REPO" 2>/dev/null || true
gh label create "backtest-validated" --color "#0E8A16" --description "Root cause evidenced in backtest"   --repo "$REPO" 2>/dev/null || true
gh label create "E1"  --color "#BFD4F2" --description "Epic E1:  Market Data Ingestion"                  --repo "$REPO" 2>/dev/null || true
gh label create "E2"  --color "#BFD4F2" --description "Epic E2:  Quantitative Signal Engine"             --repo "$REPO" 2>/dev/null || true
gh label create "E3"  --color "#BFD4F2" --description "Epic E3:  AI Cognitive Orchestrator"              --repo "$REPO" 2>/dev/null || true
gh label create "E4"  --color "#BFD4F2" --description "Epic E4:  Risk & Compliance Guard"                --repo "$REPO" 2>/dev/null || true
gh label create "E5"  --color "#BFD4F2" --description "Epic E5:  Trade Execution Engine"                 --repo "$REPO" 2>/dev/null || true
gh label create "E6"  --color "#BFD4F2" --description "Epic E6:  Paper Trading & Simulation"             --repo "$REPO" 2>/dev/null || true
gh label create "E7"  --color "#BFD4F2" --description "Epic E7:  Audit & Observability"                  --repo "$REPO" 2>/dev/null || true
gh label create "E8"  --color "#BFD4F2" --description "Epic E8:  Telegram Notification Framework"        --repo "$REPO" 2>/dev/null || true
gh label create "E9"  --color "#BFD4F2" --description "Epic E9:  Natural Language CLI"                   --repo "$REPO" 2>/dev/null || true
gh label create "E10" --color "#BFD4F2" --description "Epic E10: Backtesting & Validation"               --repo "$REPO" 2>/dev/null || true
gh label create "E11" --color "#BFD4F2" --description "Epic E11: DevOps & Resilience"                    --repo "$REPO" 2>/dev/null || true
gh label create "E12" --color "#E4E669" --description "Epic E12: Stop-Loss Protection & Gain Preservation" --repo "$REPO" 2>/dev/null || true

# =============================================================================
# EPIC E1 — Market Data Ingestion
# =============================================================================
echo ""
echo "==> Epic E1: Market Data Ingestion"
E1_URL=$(gh issue create --repo "$REPO" --label "epic,E1" \
  --title "[Epic E1] Market Data Ingestion" \
  --body "$(cat <<'EOF'
## Epic E1 — Market Data Ingestion

**Goal:** Stream real-time prices, L2 order book, and historical candles from Kraken so the downstream quantitative layer always has a consistent, low-latency view of the market.

**BRD FRs:** FR-01, FR-02, FR-03, FR-04, FR-05, FR-06
**NFRs:** NFR-02 (Availability), NFR-03 (Reliability)
**DSD:** §1 Conceptual Design, §2 Class Diagram
**Code:** `src/exchange/websocket_feed.py`, `src/exchange/kraken_client.py`, `src/exchange/historical_feed.py`

**Sub-issues (Stories):**
- S1.1.1 — WebSocket OHLC Candle Stream
- S1.2.1 — L2 Order Book Imbalance (OBI)
- S1.3.1 — Historical Feed for Backtesting
EOF
)")
E1_NUM=$(echo "$E1_URL" | grep -o '[0-9]*$')
echo "  Epic #${E1_NUM}: E1 — Market Data Ingestion"

create_story "$E1_NUM" "story,E1" \
  "[S1.1.1] WebSocket OHLC Candle Stream — rolling 15-min buffer for all pairs" \
  "$(cat <<SBODY
## Traceability
- **Epic:** E1 — Market Data Ingestion (#${E1_NUM})
- **BRD:** FR-02, FR-05, FR-06
- **DSD:** §1 Conceptual Design, §2 Class Diagram
- **NFR:** NFR-02 (Availability), NFR-03 (Reliability)
- **Code:** \`src/exchange/websocket_feed.py::WsOhlcFeed._handle_message\`, \`src/exchange/historical_feed.py::HistoricalFeed.load\`

## User Story
**As a** quantitative analyst,
**I want** the system to maintain a rolling buffer of 15-minute OHLCV candles for all 15 pairs,
**so that** indicators have a consistent, live data source without polling REST every cycle.

## Acceptance Criteria
- [ ] AC1: WebSocket subscribes to \`ohlc-15\` channel for every pair listed in \`config.yaml\`.
- [ ] AC2: On each incoming message, the buffer is updated and \`get_candles(pair)\` returns a \`pd.DataFrame\` with columns \`[timestamp, open, high, low, close, volume]\`.
- [ ] AC3: If WS disconnects, the system attempts reconnection up to 5 times before raising an alert.
- [ ] AC4: Historical candles are pre-loaded via \`HistoricalFeed\` on startup to fill the warm-up period.
- [ ] AC5: Buffer maintains exactly 300 candles per pair (75 hours). Oldest candle evicted on new arrival.
SBODY
)"

create_story "$E1_NUM" "story,E1" \
  "[S1.2.1] L2 Order Book Imbalance — compute OBI from live bid/ask spread" \
  "$(cat <<SBODY
## Traceability
- **Epic:** E1 — Market Data Ingestion (#${E1_NUM})
- **BRD:** FR-03
- **DSD:** §1 Conceptual Design
- **NFR:** NFR-05 (Determinism)
- **Code:** \`src/exchange/websocket_feed.py::WsOhlcFeed.get_obi\`

## User Story
**As a** risk manager,
**I want** to compute Order Book Imbalance from the live bid/ask spread,
**so that** the system only enters trades when genuine buying pressure exists.

## Acceptance Criteria
- [ ] AC1: System subscribes to \`ticker\` channel alongside \`ohlc\`.
- [ ] AC2: OBI computed as \`(BidVol - AskVol) / (BidVol + AskVol)\` stored per pair.
- [ ] AC3: \`get_obi(pair)\` returns a float in range \`[-1.0, +1.0]\`.
- [ ] AC4: A positive OBI (> 0) is a prerequisite for any \`propose_buy\` execution to proceed.
SBODY
)"

create_story "$E1_NUM" "story,E1" \
  "[S1.3.1] Historical Feed for Backtesting — replay candles from JSON files" \
  "$(cat <<SBODY
## Traceability
- **Epic:** E1 — Market Data Ingestion (#${E1_NUM})
- **BRD:** FR-04
- **DSD:** §1 Conceptual Design
- **NFR:** NFR-03 (Reliability)
- **Code:** \`src/exchange/historical_feed.py\`, \`tests/test_backtest.py\`

## User Story
**As a** developer,
**I want** to replay historical candle data from JSON files,
**so that** I can run backtests without a live exchange connection.

## Acceptance Criteria
- [ ] AC1: \`HistoricalFeed\` reads from \`history/<PAIR>_candle.json\` files in Kraken OHLC format.
- [ ] AC2: Feed exposes the same \`get_candles(pair)\` interface as \`WsOhlcFeed\`.
- [ ] AC3: OBI defaults to \`0.5\` (neutral) in backtest mode as real L2 data is unavailable.
- [ ] AC4: Missing history files raise a clear \`FileNotFoundError\` with the expected path.
SBODY
)"

# =============================================================================
# EPIC E2 — Quantitative Signal Engine
# =============================================================================
echo ""
echo "==> Epic E2: Quantitative Signal Engine"
E2_URL=$(gh issue create --repo "$REPO" --label "epic,E2" \
  --title "[Epic E2] Quantitative Signal Engine" \
  --body "$(cat <<'EOF'
## Epic E2 — Quantitative Signal Engine

**Goal:** Transform raw OHLCV candles into normalised, scored, per-pair signals that the LLM can reason about without ever seeing raw prices or noisy indicator arrays.

**BRD FRs:** FR-07 through FR-14
**NFRs:** NFR-05 (Determinism), NFR-07 (Configurability)
**DSD:** §3 Technical Decisions, §2 Class Diagram
**Code:** `src/analysis/indicators.py`, `src/analysis/signals.py`, `src/analysis/features.py`

**Sub-issues (Stories):**
- S2.1.1 — Trend & Momentum Indicators
- S2.2.1 — Confluence Score & Signal Generation
- S2.3.1 — Hard Buy Gates (Volume Dead Zone)
- S2.4.1 — Volatility-Adaptive Sizing & TP
EOF
)")
E2_NUM=$(echo "$E2_URL" | grep -o '[0-9]*$')
echo "  Epic #${E2_NUM}: E2 — Quantitative Signal Engine"

create_story "$E2_NUM" "story,E2" \
  "[S2.1.1] Trend & Momentum Indicators — RSI, MACD, EMA, ATR, BB per pair" \
  "$(cat <<SBODY
## Traceability
- **Epic:** E2 — Quantitative Signal Engine (#${E2_NUM})
- **BRD:** FR-07, FR-08
- **DSD:** §2 Class Diagram, §3 Technical Decisions
- **NFR:** NFR-05 (Determinism), NFR-07 (Configurability)
- **Code:** \`src/analysis/indicators.py::compute_indicators\`

## User Story
**As an** AI agent,
**I want** computed EMA, MACD, RSI, ATR and Bollinger Band values per pair,
**so that** I can identify bullish or bearish momentum without interpreting raw prices.

## Acceptance Criteria
- [ ] AC1: \`compute_indicators()\` returns: \`ema_9\`, \`ema_21\`, \`ema_50\`, \`macd_histogram\`, \`macd_histogram_prev\`, \`rsi\`, \`atr_14\`, \`bb_upper\`, \`bb_mid\`, \`bb_lower\`, \`volume_sma_20\`, \`volume_ratio\`.
- [ ] AC2: EMA 9 > EMA 21 crossover produces \`ema_cross_bullish: True\` flag.
- [ ] AC3: RSI calculated over 14 periods; value bounded \`[0, 100]\`.
- [ ] AC4: ATR calculated over 14 periods using Wilder smoothing.
- [ ] AC5: \`macd_histogram_prev\` is the second-to-last histogram value (turn detection: negative→positive = +3 vs merely positive = +1).
- [ ] AC6: If fewer than 220 candles are available, indicators raise \`InsufficientDataError\` and the pair is skipped.
SBODY
)"

create_story "$E2_NUM" "story,E2" \
  "[S2.2.1] Confluence Score & Signal Generation — 10-point additive BUY scoring" \
  "$(cat <<SBODY
## Traceability
- **Epic:** E2 — Quantitative Signal Engine (#${E2_NUM})
- **BRD:** FR-09, FR-10, FR-11, FR-13
- **DSD:** §3 Technical Decisions
- **NFR:** NFR-05 (Determinism), NFR-07 (Configurability)
- **Code:** \`src/analysis/signals.py::generate_signal\`

## User Story
**As a** risk manager,
**I want** each pair evaluated by a weighted confluence score,
**so that** only statistically strong setups are presented to the LLM as BUY candidates.

## Acceptance Criteria
- [ ] AC1: Score accumulates from contributors: MACD turn positive (+3), MACD positive (+1), RSI oversold <30 (+3), RSI mild 30–40 (+1), near BB lower (+2), EMA9 > EMA21 (+2), price > EMA50 (+1), Fear & Greed fear ≤40 (+1), extreme ≤25 (+1 stacked).
- [ ] AC2: Score ≥ \`signals.buy_min_score\` (default 5) required to generate BUY direction.
- [ ] AC3: Two hard vetoes: RSI ≥ 70 and ATR-based TP < profit floor — either forces HOLD regardless of score.
- [ ] AC4: All scoring decisions and veto reasons returned as \`reasons: list[str]\` alongside the signal.
- [ ] AC5: \`generate_signal()\` returns \`{"direction": "BUY|SELL|HOLD", "score": int, "reasons": list}\`.
- [ ] AC6: All score weights configurable under \`config.yaml → signals:\`. Never hardcoded.
SBODY
)"

create_story "$E2_NUM" "story,E2" \
  "[S2.3.1] Hard Buy Gates — Volume Dead Zone and Time-of-Day filters" \
  "$(cat <<SBODY
## Traceability
- **Epic:** E2 — Quantitative Signal Engine (#${E2_NUM})
- **BRD:** FR-12, FR-37
- **DSD:** §3 Technical Decisions
- **NFR:** NFR-05 (Determinism)
- **Code:** \`src/analysis/signals.py::generate_signal\`, \`src/risk/risk_manager.py::validate_buy\`

## User Story
**As a** compliance system,
**I want** automatic blocking of BUY signals during dead-zone market conditions,
**so that** the system avoids false breakout entries.

## Acceptance Criteria
- [ ] AC1: Volume ratio < \`signals.min_volume_ratio\` (default 0.5) forces \`BLOCKED: Volume dead zone\`.
- [ ] AC2: All block reasons visible in \`audit_signals\` database table.
- [ ] AC3: Time-of-Day gate blocks buys outside 16:00–20:00 UTC; uses candle timestamp in backtesting.
- [ ] AC4: Gates apply identically to both live and backtest modes.
SBODY
)"

create_story "$E2_NUM" "story,E2" \
  "[S2.4.1] Volatility-Adaptive Sizing & TP — ATR-scaled position size and dynamic take-profit" \
  "$(cat <<SBODY
## Traceability
- **Epic:** E2 — Quantitative Signal Engine (#${E2_NUM})
- **BRD:** FR-26, FR-27, FR-35
- **DSD:** §3 Technical Decisions
- **NFR:** NFR-07 (Configurability), NFR-05 (Determinism)
- **Code:** \`src/analysis/features.py::get_volatility_multiplier\`, \`src/analysis/features.py::compute_dynamic_sl_values\`, \`src/agent/tools.py::propose_buy\`

## User Story
**As a** portfolio manager,
**I want** position sizes and take-profit levels to dynamically scale with ATR,
**so that** trades capture more profit during high-volatility regimes and preserve capital during calm markets.

## Acceptance Criteria
- [ ] AC1: Volatility regime classified as Low/Standard/High based on \`atr / price\` ratio.
- [ ] AC2: ATR multiplier \`k\` ranges from \`1.75x\` (low vol) to \`4.0x\` (high vol).
- [ ] AC3: Dynamic TP = \`Entry + (k * ATR)\`. Static TP from config is the fallback if \`dynamic_tp.enabled: false\`.
- [ ] AC4: Dynamic SL = \`min(Entry * 0.95, Entry - (ATR * Multiplier))\`. Can never exceed 5%.
- [ ] AC5: Both values logged per-trade as \`dynamic_sl\` and \`dynamic_tp\` in \`paper_positions\`.
- [ ] AC6: In bearish regime, per-trade maximum scaled by \`caution_factor: 0.5\` in \`main.py\` — LLM cannot override this cap.
SBODY
)"

# =============================================================================
# EPIC E3 — AI Cognitive Orchestrator
# =============================================================================
echo ""
echo "==> Epic E3: AI Cognitive Orchestrator"
E3_URL=$(gh issue create --repo "$REPO" --label "epic,E3" \
  --title "[Epic E3] AI Cognitive Orchestrator" \
  --body "$(cat <<'EOF'
## Epic E3 — AI Cognitive Orchestrator

**Goal:** Use a local LLM to reason over normalised market data and produce structured trade decisions (buy, sell, hold) without ever having direct access to execution or risk parameters.

**BRD FRs:** FR-15 through FR-23
**NFRs:** NFR-01 (Privacy), NFR-05 (Determinism), NFR-07 (Configurability)
**DSD:** §3a LLM Architecture (all subsections)
**Code:** `src/agent/trading_agent.py`, `src/agent/prompts.py`, `src/agent/tools.py`, `.claude/skills/trading-rules/SKILL.md`

**Sub-issues (Stories):**
- S3.1.1 — SKILL.md Dynamic Rule Injection
- S3.2.1 — Normalised Multi-Pair Cycle Prompt
- S3.3.1 — JSON Tool-Call Enforcement
- S3.4.1 — LLM Fallback & Timeout Handling
EOF
)")
E3_NUM=$(echo "$E3_URL" | grep -o '[0-9]*$')
echo "  Epic #${E3_NUM}: E3 — AI Cognitive Orchestrator"

create_story "$E3_NUM" "story,E3" \
  "[S3.1.1] SKILL.md Dynamic Rule Injection — trading rules loaded at runtime from file" \
  "$(cat <<SBODY
## Traceability
- **Epic:** E3 — AI Cognitive Orchestrator (#${E3_NUM})
- **BRD:** FR-23
- **DSD:** §3a.2 The Trading Skill, §10.1 Skill: trading-rules
- **NFR:** NFR-07 (Configurability), NFR-01 (Privacy)
- **Code:** \`src/agent/prompts.py::TRADING_RULES\`, \`.claude/skills/trading-rules/SKILL.md\`

## User Story
**As a** product owner,
**I want** trading rules externalised to a SKILL.md file loaded at runtime,
**so that** I can update the agent's constraints without modifying Python code or redeploying.

## Acceptance Criteria
- [ ] AC1: On startup, \`prompts.py\` reads \`.claude/skills/trading-rules/SKILL.md\` and embeds it into \`SYSTEM_PROMPT\`.
- [ ] AC2: If \`SKILL.md\` is missing, a clear \`FileNotFoundError\` is raised with a warning in logs.
- [ ] AC3: Changes to \`SKILL.md\` take effect on next agent restart without code changes.
- [ ] AC4: \`SYSTEM_PROMPT\` contains: agent identity, all trading rules, tool documentation.
- [ ] AC5: SKILL.md is kept in sync with code-level enforcement — any rule enforced in code must also be stated in SKILL.md.
SBODY
)"

create_story "$E3_NUM" "story,E3" \
  "[S3.2.1] Normalised Multi-Pair Cycle Prompt — compact context for all 15 pairs under 2000 tokens" \
  "$(cat <<SBODY
## Traceability
- **Epic:** E3 — AI Cognitive Orchestrator (#${E3_NUM})
- **BRD:** FR-16
- **DSD:** §3a.4 Cycle Prompt Engineering
- **NFR:** NFR-10 (Performance)
- **Code:** \`src/agent/prompts.py::build_cycle_prompt\`

## User Story
**As an** LLM,
**I want** to receive a compact, normalised summary of all 15 pairs in a single prompt,
**so that** I can rank opportunities and make decisions without exceeding token limits.

## Acceptance Criteria
- [ ] AC1: \`build_cycle_prompt()\` produces a prompt under 2,000 tokens for all 15 pairs.
- [ ] AC2: Each pair entry includes: \`score\`, \`direction\`, \`regime\`, \`ema_cross_bullish\`, \`obi\`, \`reasons\`, \`open_position\` flag.
- [ ] AC3: Raw OHLCV prices never included — only derived metrics.
- [ ] AC4: Portfolio state (cash, open positions, daily PNL%) included in every prompt.
- [ ] AC5: Time-of-day (UTC) and Fear & Greed index included per cycle.
SBODY
)"

create_story "$E3_NUM" "story,E3" \
  "[S3.3.1] JSON Tool-Call Enforcement — LLM responds only via structured tool-calls" \
  "$(cat <<SBODY
## Traceability
- **Epic:** E3 — AI Cognitive Orchestrator (#${E3_NUM})
- **BRD:** FR-17, FR-18, FR-19
- **DSD:** §3a.5 Tool Calling Schema, §3a.6 Tool Dispatch & Audit Flow
- **NFR:** NFR-05 (Determinism)
- **Code:** \`src/agent/trading_agent.py::run_cycle\`, \`src/agent/tools.py\`

## User Story
**As a** developer,
**I want** the LLM to respond only via structured tool-calls,
**so that** conversational text never reaches the execution layer.

## Acceptance Criteria
- [ ] AC1: Three tools registered: \`propose_buy(pair, usd_amount, reason)\`, \`propose_sell(pair, reason)\`, \`hold(reason)\`.
- [ ] AC2: Python execution only triggers on \`message.tool_calls\` — \`message.content\` logged but never parsed.
- [ ] AC3: Unrecognised tool names raise a \`ValueError\` logged to \`audit_errors\`.
- [ ] AC4: \`propose_buy\` limited to at most 3 calls per cycle.
- [ ] AC5: LLM decisions (tool name, pair, reason, raw content) written to \`audit_llm_decisions\`.
- [ ] AC6: Tool execution always uses the signal \`pair\` from the feed — never \`tool_args["pair"]\` (guards against LLM hallucinating pair names).
SBODY
)"

create_story "$E3_NUM" "story,E3" \
  "[S3.4.1] LLM Fallback & Timeout Handling — fall back to secondary model on timeout" \
  "$(cat <<SBODY
## Traceability
- **Epic:** E3 — AI Cognitive Orchestrator (#${E3_NUM})
- **BRD:** FR-21, FR-22
- **DSD:** §3a.1 Model Selection, §5 Exception Management
- **NFR:** NFR-03 (Reliability), NFR-10 (Performance)
- **Code:** \`src/agent/trading_agent.py::_call_llm_with_retry\`

## User Story
**As an** ops engineer,
**I want** the agent to fall back to a secondary model on timeout,
**so that** a slow primary model does not halt the trading loop.

## Acceptance Criteria
- [ ] AC1: Primary model timeout configurable via \`llm.timeout_seconds\` in \`config.yaml\`.
- [ ] AC2: On timeout, agent retries once with fallback model defined in \`llm.fallback_model\`.
- [ ] AC3: Timeout event written to \`audit_errors\` and triggers a Telegram error alert.
- [ ] AC4: If both models fail, the cycle exits gracefully with all signals treated as HOLD.
SBODY
)"

# =============================================================================
# EPIC E4 — Risk & Compliance Guard
# =============================================================================
echo ""
echo "==> Epic E4: Risk & Compliance Guard"
E4_URL=$(gh issue create --repo "$REPO" --label "epic,E4" \
  --title "[Epic E4] Risk & Compliance Guard" \
  --body "$(cat <<'EOF'
## Epic E4 — Risk & Compliance Guard

**Goal:** Act as a deterministic mathematical firewall between LLM proposals and actual exchange execution. Every proposed order must pass all guards or be rejected with a logged reason.

**BRD FRs:** FR-24 through FR-36
**NFRs:** NFR-05 (Determinism), NFR-04 (Auditability), NFR-07 (Configurability)
**DSD:** §7.6 Global Kill Switch, §7.7 Circuit Breaker, §3a.5 Tool Calling
**Code:** `src/risk/risk_manager.py`

**Sub-issues (Stories):**
- S4.1.1 — Buy Validation Guards (all 9 checks)
- S4.2.1 — Sell Validation (Minimum Profit Floor)
- S4.3.1 — Position Sizing Cap
EOF
)")
E4_NUM=$(echo "$E4_URL" | grep -o '[0-9]*$')
echo "  Epic #${E4_NUM}: E4 — Risk & Compliance Guard"

create_story "$E4_NUM" "story,E4,risk-management" \
  "[S4.1.1] Buy Validation Guards — 9-layer deterministic gate before any order executes" \
  "$(cat <<SBODY
## Traceability
- **Epic:** E4 — Risk & Compliance Guard (#${E4_NUM})
- **BRD:** FR-28, FR-29, FR-30, FR-31, FR-32, FR-34, FR-36, FR-37
- **DSD:** §7.6 Global Kill Switch, §7.7 Circuit Breaker
- **NFR:** NFR-05 (Determinism), NFR-04 (Auditability)
- **Code:** \`src/risk/risk_manager.py::validate_buy\`

## User Story
**As a** compliance system,
**I want** every \`propose_buy\` validated against a strict set of rules before execution,
**so that** no order is placed unless all risk parameters are fully satisfied.

## Acceptance Criteria
- [ ] AC1: **Circuit Breaker** — If last 3 trades (within 4h) are all \`stop_loss\`, all buys blocked for 4h. Derived from trade history — no separate state table.
- [ ] AC2: **Daily Loss Limit** — If daily PNL ≤ \`-10%\`, all buys blocked for the remainder of the day.
- [ ] AC3: **Global Kill Switch** — If drawdown ≥ 7%, all positions market-sold and trading halts entirely.
- [ ] AC4: **Max Open Positions** — Blocked if open positions ≥ 3.
- [ ] AC5: **Cash Reserve** — Blocked if available cash ≤ 10% of portfolio.
- [ ] AC6: **Fat Finger Guard** — Blocked if proposed USD > \`available_cash * 0.98\`.
- [ ] AC7: **Minimum Order Size** — Blocked if proposed USD < \$5.
- [ ] AC8: **Time-of-Day Gate** — Blocked outside 16:00–20:00 UTC. Backtest uses candle timestamp.
- [ ] AC9: All rejections written to \`audit_risk_checks\` with the specific rule that triggered.
SBODY
)"

create_story "$E4_NUM" "story,E4,risk-management" \
  "[S4.2.1] Sell Validation — Minimum Profit Floor blocks LLM exits below fee break-even" \
  "$(cat <<SBODY
## Traceability
- **Epic:** E4 — Risk & Compliance Guard (#${E4_NUM})
- **BRD:** FR-33
- **DSD:** §7.4 Sell Flow
- **NFR:** NFR-05 (Determinism), NFR-04 (Auditability)
- **Code:** \`src/risk/risk_manager.py::validate_sell\` (line 339)

## User Story
**As a** fee protection system,
**I want** to block any LLM sell where projected PNL is below the profit floor,
**so that** fees and slippage never cause a net loss on voluntary exits.

## Acceptance Criteria
- [ ] AC1: \`validate_sell()\` computes \`est_pnl_pct = ((current_price - entry_price) / entry_price) * 100\`.
- [ ] AC2: If \`est_pnl_pct < trading.min_profit_floor_pct\` (default 1.0%), the sell is rejected.
- [ ] AC3: Rejection reason includes the exact projected PNL percentage.
- [ ] AC4: Automatic SL/TP exits bypass the profit floor — only agent-initiated sells are checked.
- [ ] AC5: Rejection written to \`audit_risk_checks\`.
SBODY
)"

create_story "$E4_NUM" "story,E4,risk-management" \
  "[S4.3.1] Position Sizing Cap — automatically resize oversized orders, never reject" \
  "$(cat <<SBODY
## Traceability
- **Epic:** E4 — Risk & Compliance Guard (#${E4_NUM})
- **BRD:** FR-27, FR-35
- **DSD:** §3 Technical Decisions
- **NFR:** NFR-05 (Determinism), NFR-07 (Configurability)
- **Code:** \`src/risk/risk_manager.py::validate_buy\`, \`src/analysis/features.py::compute_position_size\`

## User Story
**As a** portfolio manager,
**I want** position size automatically capped and resized,
**so that** no single trade exceeds defined risk limits even if the LLM requests more.

## Acceptance Criteria
- [ ] AC1: Max trade USD = \`portfolio_balance * (max_position_pct / 100)\` (default 30%).
- [ ] AC2: If proposed amount exceeds cap, silently reduced (not rejected) and cap reason logged.
- [ ] AC3: Final capped amount returned alongside approval in tuple \`(True, reason, capped_amount)\`.
- [ ] AC4: Capped trades use ATR-proportional formula: \`RiskAmount / (ATR * Multiplier)\`.
SBODY
)"

# =============================================================================
# EPIC E5 — Trade Execution Engine
# =============================================================================
echo ""
echo "==> Epic E5: Trade Execution Engine"
E5_URL=$(gh issue create --repo "$REPO" --label "epic,E5" \
  --title "[Epic E5] Trade Execution Engine" \
  --body "$(cat <<'EOF'
## Epic E5 — Trade Execution Engine

**Goal:** Translate approved trade intents into precise, fee-optimised Kraken API calls using Maker-only Limit orders with a chase mechanism.

**BRD FRs:** FR-44 through FR-51
**NFRs:** NFR-06 (Crash resilience), NFR-12 (Exchange precision)
**DSD:** §7.1 Autonomous Buy Flow, §7.9 Limit Order Chase
**Code:** `src/exchange/kraken_client.py`, `src/exchange/paper_broker.py`

**Sub-issues (Stories):**
- S5.1.1 — Post-Only Maker Limit Orders
- S5.2.1 — 60-Second Limit Order Chase
- S5.3.1 — Deferred SL/TP Placement
EOF
)")
E5_NUM=$(echo "$E5_URL" | grep -o '[0-9]*$')
echo "  Epic #${E5_NUM}: E5 — Trade Execution Engine"

create_story "$E5_NUM" "story,E5" \
  "[S5.1.1] Post-Only Maker Limit Orders — all entries at best bid with postOnly flag" \
  "$(cat <<SBODY
## Traceability
- **Epic:** E5 — Trade Execution Engine (#${E5_NUM})
- **BRD:** FR-46, FR-50
- **DSD:** §7.1 Autonomous Buy Flow, §7.9 Limit Order Chase
- **NFR:** NFR-12 (Exchange precision)
- **Code:** \`src/exchange/kraken_client.py::place_order\`

## User Story
**As a** trader,
**I want** all entries placed as Post-Only Limit orders at the current Best Bid,
**so that** I always pay Maker fees (~0.16%) rather than Taker fees (~0.26%).

## Acceptance Criteria
- [ ] AC1: \`place_order()\` always calls \`create_limit_buy_order()\` with \`params={"postOnly": True}\`.
- [ ] AC2: Entry price sourced from \`get_latest_price(pair)\` at the moment of tool execution (JIT re-fetch).
- [ ] AC3: Volume computed as \`usd_amount / current_price\` and rounded via \`amount_to_precision()\`.
- [ ] AC4: Price rounded via \`price_to_precision()\` to match Kraken tick size rules.
- [ ] AC5: Entry order ID stored in \`live_positions\` as \`entry_order_id\` for status polling.
SBODY
)"

create_story "$E5_NUM" "story,E5" \
  "[S5.2.1] 60-Second Limit Order Chase — cancel and re-place unfilled orders at new best bid" \
  "$(cat <<SBODY
## Traceability
- **Epic:** E5 — Trade Execution Engine (#${E5_NUM})
- **BRD:** FR-47
- **DSD:** §7.9 Maker Feature Limit Order Chase
- **NFR:** NFR-03 (Reliability)
- **Code:** \`src/exchange/kraken_client.py::check_stops_and_tp\`

## User Story
**As a** trading engine,
**I want** unfilled limit orders cancelled and replaced at the new Best Bid after 60 seconds,
**so that** the order always stays competitive without crossing the spread.

## Acceptance Criteria
- [ ] AC1: \`check_stops_and_tp()\` checks \`placed_at\` timestamp for every \`pending_fill\` position.
- [ ] AC2: If \`now - placed_at > 60s\` and order still \`open\`, cancel and re-place at \`current_price\`.
- [ ] AC3: If primary order was \`canceled\` by Kraken, position removed from DB and no SL/TP placed.
- [ ] AC4: Chased orders reset the \`placed_at\` timestamp.
- [ ] AC5: Chase events logged with \`[LIMIT_CHASE]\` prefix.
SBODY
)"

create_story "$E5_NUM" "story,E5" \
  "[S5.3.1] Deferred SL/TP Placement — SL/TP orders placed only after entry confirms filled" \
  "$(cat <<SBODY
## Traceability
- **Epic:** E5 — Trade Execution Engine (#${E5_NUM})
- **BRD:** FR-48, FR-49
- **DSD:** §7.1 Autonomous Buy Flow, §7.5 Stop Loss & Take Profit
- **NFR:** NFR-06 (Crash resilience)
- **Code:** \`src/exchange/kraken_client.py::_place_sl_tp_orders\`, \`src/exchange/kraken_client.py::close_position\`

## User Story
**As a** risk system,
**I want** SL and TP orders placed only after the entry order confirms filled,
**so that** Kraken never receives SL/TP orders for positions that don't yet exist.

## Acceptance Criteria
- [ ] AC1: SL/TP placement deferred until \`fetch_order(entry_order_id)\` returns \`status == "closed"\`.
- [ ] AC2: On each tick, unfilled pending orders polled via REST.
- [ ] AC3: Once filled, SL placed as stop-market at \`dynamic_sl_price\`; TP as limit at \`dynamic_tp_price\`.
- [ ] AC4: If native SL/TP fire on Kraken, position marked \`closed\` in DB with appropriate \`exit_reason\`.
- [ ] AC5: Fallback fires \`create_market_sell_order()\` with \`exit_reason = "fallback_stop_loss"\` if polling is unreliable.
SBODY
)"

# =============================================================================
# EPIC E6 — Paper Trading & Simulation
# =============================================================================
echo ""
echo "==> Epic E6: Paper Trading & Simulation"
E6_URL=$(gh issue create --repo "$REPO" --label "epic,E6" \
  --title "[Epic E6] Paper Trading & Simulation" \
  --body "$(cat <<'EOF'
## Epic E6 — Paper Trading & Simulation

**Goal:** Allow full end-to-end strategy validation with zero financial risk using a virtual balance that mirrors live execution logic faithfully.

**BRD FRs:** FR-38 through FR-43
**NFRs:** NFR-03 (Reliability), NFR-07 (Configurability)
**DSD:** §7.2 Paper Buy Flow, §7.5 SL/TP
**Code:** `src/exchange/paper_broker.py`

**Sub-issues (Stories):**
- S6.1.1 — Virtual Order Execution with fee simulation
- S6.2.1 — SL/TP Monitoring in Paper Mode
- S6.3.1 — Backtesting Clean Slate Teardown
EOF
)")
E6_NUM=$(echo "$E6_URL" | grep -o '[0-9]*$')
echo "  Epic #${E6_NUM}: E6 — Paper Trading & Simulation"

create_story "$E6_NUM" "story,E6" \
  "[S6.1.1] Virtual Order Execution — paper trades against live prices with realistic fees" \
  "$(cat <<SBODY
## Traceability
- **Epic:** E6 — Paper Trading & Simulation (#${E6_NUM})
- **BRD:** FR-38, FR-39, FR-40, FR-41
- **DSD:** §7.2 Paper Buy Flow
- **NFR:** NFR-03 (Reliability)
- **Code:** \`src/exchange/paper_broker.py::place_order\`, \`src/exchange/paper_broker.py::get_balance\`

## User Story
**As a** developer,
**I want** paper trades to execute against live public WebSocket prices with realistic fee simulation,
**so that** the simulation reflects real market conditions without touching real funds.

## Acceptance Criteria
- [ ] AC1: \`PaperBroker.place_order()\` deducts \`actual_cost + maker_fee\` from virtual cash balance.
- [ ] AC2: Entry slippage of 0.05% applied to simulate order fill price.
- [ ] AC3: Maker fee is 0.16% (Post-Only fills). Taker fee fallback 0.26%.
- [ ] AC4: Virtual positions persisted to \`data/paper_trading.db\` — survives restarts.
- [ ] AC5: \`get_balance()\` returns \`{"total_usd": cash + Σ(usd_value of open positions), "available_cash_usd": cash}\`.
- [ ] AC6: \`usd_value\` stored in DB = entry cost only (fee excluded).
SBODY
)"

create_story "$E6_NUM" "story,E6" \
  "[S6.2.1] SL/TP Monitoring in Paper Mode — auto-close positions on price trigger every cycle" \
  "$(cat <<SBODY
## Traceability
- **Epic:** E6 — Paper Trading & Simulation (#${E6_NUM})
- **BRD:** FR-42, FR-43
- **DSD:** §7.5 Stop Loss & Take Profit
- **NFR:** NFR-05 (Determinism)
- **Code:** \`src/exchange/paper_broker.py::check_stops_and_tp\`, \`src/exchange/paper_broker.py::close_position\`

## User Story
**As a** paper trading system,
**I want** stop-loss and take-profit levels monitored on every cycle tick,
**so that** positions close automatically at the correct price levels.

## Acceptance Criteria
- [ ] AC1: \`check_stops_and_tp()\` runs on every cycle before the LLM is called — highest priority.
- [ ] AC2: If \`current_price ≤ stop_loss_price\`, position closes with \`exit_reason = "stop_loss"\`.
- [ ] AC3: If \`current_price ≥ take_profit_price\`, position closes with \`exit_reason = "take_profit"\`.
- [ ] AC4: Exit slippage of 0.05% and exit fee of 0.26% applied to proceeds.
- [ ] AC5: Closed trade PNL written to \`paper_trades\` table.
SBODY
)"

create_story "$E6_NUM" "story,E6" \
  "[S6.3.1] Backtesting Clean Slate Teardown — delete all backtest DBs and logs before each run" \
  "$(cat <<SBODY
## Traceability
- **Epic:** E6 — Paper Trading & Simulation (#${E6_NUM})
- **BRD:** FR-38
- **DSD:** §1 Conceptual Design
- **NFR:** NFR-03 (Reliability)
- **Code:** \`tests/test_backtest.py\`

## User Story
**As a** developer,
**I want** backtest runs to start with a fully clean database and log,
**so that** previous runs don't contaminate results.

## Acceptance Criteria
- [ ] AC1: \`tests/test_backtest.py\` deletes \`data/backtest_paper.db\` and \`data/backtest_audit.db\` before each run.
- [ ] AC2: \`backtest_run.log\` truncated to empty at the start of each run.
- [ ] AC3: Production databases (\`data/paper_trading.db\`, \`data/audit.db\`) never touched by backtest teardown.
- [ ] AC4: Teardown logged with \`[BACKTEST INIT] Cleansing state...\` prefix.
SBODY
)"

# =============================================================================
# EPIC E7 — Audit & Observability
# =============================================================================
echo ""
echo "==> Epic E7: Audit & Observability"
E7_URL=$(gh issue create --repo "$REPO" --label "epic,E7" \
  --title "[Epic E7] Audit & Observability" \
  --body "$(cat <<'EOF'
## Epic E7 — Audit & Observability

**Goal:** Record every signal, decision, trade, and error with sufficient detail to reconstruct exactly why the agent made any decision at any point in time.

**BRD FRs:** FR-52 through FR-58
**NFRs:** NFR-04 (Auditability), NFR-09 (Observability)
**DSD:** §4 Database Design, §8 Component Dependencies & Traceability
**Code:** `src/storage/audit_logger.py`, `src/storage/database.py`

**Sub-issues (Stories):**
- S7.1.1 — Full Decision Audit Trail
- S7.2.1 — Balance Snapshots after every trade
- S7.3.1 — Rejection Analysis Script
EOF
)")
E7_NUM=$(echo "$E7_URL" | grep -o '[0-9]*$')
echo "  Epic #${E7_NUM}: E7 — Audit & Observability"

create_story "$E7_NUM" "story,E7" \
  "[S7.1.1] Full Decision Audit Trail — every cycle, signal, LLM decision, and risk check logged" \
  "$(cat <<SBODY
## Traceability
- **Epic:** E7 — Audit & Observability (#${E7_NUM})
- **BRD:** FR-52, FR-53, FR-54, FR-55, FR-56, FR-57
- **DSD:** §4 Database Design, §8.1 Component Drilldown
- **NFR:** NFR-04 (Auditability), NFR-09 (Observability)
- **Code:** \`src/storage/audit_logger.py\`

## User Story
**As an** auditor,
**I want** every cycle's signals, LLM decisions, risk checks, and trades logged in SQLite,
**so that** I can reconstruct any trading decision long after it was made.

## Acceptance Criteria
- [ ] AC1: Every cycle writes to \`audit_cycles\` (start time, end time, cycle ID).
- [ ] AC2: Every pair signal written to \`audit_signals\` (pair, score, direction, reasons, all indicator values).
- [ ] AC3: Every LLM tool call written to \`audit_llm_decisions\` (tool, pair, reason, raw content).
- [ ] AC4: Every risk check written to \`audit_risk_checks\` (action, pair, approved, rejection_reason).
- [ ] AC5: Every HOLD decision (including implicit holds) audited.
- [ ] AC6: Errors written to \`audit_errors\` (component, message, stack trace).
- [ ] AC7: Audit logger NEVER raises exceptions — all writes wrapped in try/except.
- [ ] AC8: Audit DB is append-only; no records deleted or updated after creation.
SBODY
)"

create_story "$E7_NUM" "story,E7" \
  "[S7.2.1] Balance Snapshots — post-trade equity curve snapshots after every fill" \
  "$(cat <<SBODY
## Traceability
- **Epic:** E7 — Audit & Observability (#${E7_NUM})
- **BRD:** FR-58
- **DSD:** §4 Database Design
- **NFR:** NFR-04 (Auditability)
- **Code:** \`src/storage/audit_logger.py::log_balance_snapshot\`

## User Story
**As a** portfolio manager,
**I want** balance snapshots taken after every trade executes,
**so that** I have a precise equity curve for performance analysis.

## Acceptance Criteria
- [ ] AC1: Balance snapshot taken immediately after \`close_position()\` completes.
- [ ] AC2: Snapshot includes: \`total_usd\`, \`cash_usd\`, \`open_positions_count\`, \`timestamp\`.
- [ ] AC3: Snapshots written to \`audit_balance_snapshots\` table.
- [ ] AC4: \`daily_pnl\` table updated with realised PNL after every closed trade.
SBODY
)"

create_story "$E7_NUM" "story,E7" \
  "[S7.3.1] Rejection Analysis Script — CLI tool to explain why trades were blocked" \
  "$(cat <<SBODY
## Traceability
- **Epic:** E7 — Audit & Observability (#${E7_NUM})
- **BRD:** FR-52
- **DSD:** §8.2 Traceability to Acceptance Criteria
- **NFR:** NFR-09 (Observability), NFR-11 (CLI usability)
- **Code:** \`scripts/audit_rejections.py\`

## User Story
**As a** developer,
**I want** a CLI script that summarises exactly why trades were blocked,
**so that** I can diagnose when the bot is over-filtering or under-trading.

## Acceptance Criteria
- [ ] AC1: \`scripts/audit_rejections.py\` queries \`audit_signals\`, \`audit_llm_decisions\`, \`audit_risk_checks\`.
- [ ] AC2: Output groups block reasons by layer (Indicator → LLM → Risk Manager).
- [ ] AC3: Prints count per reason, session totals, and win/loss/hold summary.
- [ ] AC4: Script supports optional \`--mode paper|backtest|live\` flag.
SBODY
)"

# =============================================================================
# EPIC E8 — Telegram Notification Framework
# =============================================================================
echo ""
echo "==> Epic E8: Telegram Notification Framework"
E8_URL=$(gh issue create --repo "$REPO" --label "epic,E8" \
  --title "[Epic E8] Telegram Notification Framework" \
  --body "$(cat <<'EOF'
## Epic E8 — Telegram Notification Framework

**Goal:** Provide real-time operational awareness via Telegram so the owner can monitor the bot's health, trades, and P&L without tailing logs.

**BRD FRs:** FR-59 through FR-64
**NFRs:** NFR-09 (Observability), NFR-03 (Reliability)
**DSD:** §6 Notification Framework, §7.8 Notification Framework Flow
**Code:** `src/notifications/notifier.py`

**Sub-issues (Stories):**
- S8.1.1 — Trade Lifecycle Alerts
- S8.2.1 — 2-Hour Heartbeat
- S8.3.1 — 6-Hour P&L Report
- S8.4.1 — Start/Stop/Error Alerts + Healthcheck Webhook
EOF
)")
E8_NUM=$(echo "$E8_URL" | grep -o '[0-9]*$')
echo "  Epic #${E8_NUM}: E8 — Telegram Notification Framework"

create_story "$E8_NUM" "story,E8" \
  "[S8.1.1] Trade Lifecycle Alerts — Telegram messages for every buy and sell event" \
  "$(cat <<SBODY
## Traceability
- **Epic:** E8 — Telegram Notification Framework (#${E8_NUM})
- **BRD:** FR-59, FR-60, FR-61
- **DSD:** §6 Notification Framework, §7.8 Notification Framework Flow
- **NFR:** NFR-09 (Observability), NFR-03 (Reliability)
- **Code:** \`src/notifications/notifier.py::send_buy_alert\`, \`src/notifications/notifier.py::send_sell_alert\`

## User Story
**As a** trader,
**I want** Telegram messages for every buy and sell event,
**so that** I am immediately informed of capital movements.

## Acceptance Criteria
- [ ] AC1: BUY alert includes: pair, entry price, quantity, invested USD, dynamic SL price, dynamic TP price, fee paid.
- [ ] AC2: SELL alert includes: pair, exit reason, exit price, gross PNL%, net PNL USD, hold duration.
- [ ] AC3: Messages sent asynchronously; do not block the trading loop on failure.
- [ ] AC4: If Telegram API fails, the error is logged but the trade still executes.
- [ ] AC5: All paper trading alerts prefixed with \`[PAPER]\`.
SBODY
)"

create_story "$E8_NUM" "story,E8" \
  "[S8.2.1] 2-Hour Heartbeat — Telegram summary every 2 hours confirming agent is alive" \
  "$(cat <<SBODY
## Traceability
- **Epic:** E8 — Telegram Notification Framework (#${E8_NUM})
- **BRD:** FR-62
- **DSD:** §6 Notification Framework
- **NFR:** NFR-09 (Observability)
- **Code:** \`src/notifications/notifier.py::send_heartbeat\`, \`main.py\`

## User Story
**As an** operator,
**I want** a Telegram heartbeat every 2 hours,
**so that** I know the bot is alive even during periods of no trading activity.

## Acceptance Criteria
- [ ] AC1: Heartbeat fires every 120 minutes (8 cycles at 15-min interval).
- [ ] AC2: Message contains: uptime, current balance, hourly PNL%, open positions, circuit breaker status.
- [ ] AC3: Live mode only — heartbeat suppressed in paper and backtest modes.
SBODY
)"

create_story "$E8_NUM" "story,E8" \
  "[S8.3.1] 6-Hour P&L Report — cumulative performance summary sent every 6 hours" \
  "$(cat <<SBODY
## Traceability
- **Epic:** E8 — Telegram Notification Framework (#${E8_NUM})
- **BRD:** FR-63
- **DSD:** §6 Notification Framework
- **NFR:** NFR-09 (Observability)
- **Code:** \`src/notifications/notifier.py::send_pnl_report\`

## User Story
**As a** portfolio manager,
**I want** a P&L summary every 6 hours,
**so that** I can track whether the session is on track for the weekly target.

## Acceptance Criteria
- [ ] AC1: PNL report fires every 360 minutes (24 cycles).
- [ ] AC2: Report includes: start-of-day balance, current balance, realised PNL USD, PNL%, win/loss trade count.
- [ ] AC3: Report sent in both paper and live modes.
SBODY
)"

create_story "$E8_NUM" "story,E8" \
  "[S8.4.1] Start/Stop/Error Alerts + Healthcheck Webhook — operational lifecycle notifications" \
  "$(cat <<SBODY
## Traceability
- **Epic:** E8 — Telegram Notification Framework (#${E8_NUM})
- **BRD:** FR-59, FR-64
- **DSD:** §6 Notification Framework, §7.8 Notification Framework Flow
- **NFR:** NFR-09 (Observability), NFR-02 (Availability)
- **Code:** \`src/notifications/notifier.py\`, \`main.py\`

## User Story
**As an** operator,
**I want** Telegram alerts when the bot starts, stops, or crashes, plus a 15-minute healthcheck ping,
**so that** I can immediately investigate unexpected shutdowns and silent failures.

## Acceptance Criteria
- [ ] AC1: \`send_agent_started(mode)\` sent immediately after successful initialisation.
- [ ] AC2: \`send_agent_stopped(mode)\` sent in the \`finally\` block — fires on both clean exits and crashes.
- [ ] AC3: \`send_error_alert(component, message)\` triggered on any unhandled exception with first 200 chars of error.
- [ ] AC4: HTTP Webhook (\`healthcheck_url\`) pinged every 15 minutes via \`ping_healthcheck()\`.
- [ ] AC5: If \`healthcheck_url\` is empty in config, the feature is silently disabled.
SBODY
)"

# =============================================================================
# EPIC E9 — Natural Language CLI
# =============================================================================
echo ""
echo "==> Epic E9: Natural Language CLI"
E9_URL=$(gh issue create --repo "$REPO" --label "epic,E9" \
  --title "[Epic E9] Natural Language CLI" \
  --body "$(cat <<'EOF'
## Epic E9 — Natural Language CLI

**Goal:** Allow the owner to interrogate the running agent, view reports, and manage the bot via natural English commands rather than raw database queries.

**BRD FRs:** (Implied operational requirement)
**NFRs:** NFR-11 (CLI usability)
**DSD:** §1 Conceptual Design
**Code:** `src/cli/nl_parser.py`, `src/cli/commands.py`, `src/cli/display.py`, `src/reports/trade_report.py`

**Sub-issues (Stories):**
- S9.1.1 — Natural Language Command Parsing
- S9.2.1 — Trade Report & P&L Display
EOF
)")
E9_NUM=$(echo "$E9_URL" | grep -o '[0-9]*$')
echo "  Epic #${E9_NUM}: E9 — Natural Language CLI"

create_story "$E9_NUM" "story,E9" \
  "[S9.1.1] Natural Language Command Parsing — plain-English CLI without SQL queries" \
  "$(cat <<SBODY
## Traceability
- **Epic:** E9 — Natural Language CLI (#${E9_NUM})
- **BRD:** Implied operational requirement
- **DSD:** §1 Conceptual Design
- **NFR:** NFR-11 (CLI usability)
- **Code:** \`src/cli/nl_parser.py\`, \`src/cli/commands.py\`

## User Story
**As a** trader,
**I want** to type commands like "show me BTC trades this week" in the CLI,
**so that** I don't need to write SQL queries to interrogate the audit database.

## Acceptance Criteria
- [ ] AC1: \`nl_parser.py\` maps natural language intents to structured CLI commands.
- [ ] AC2: Supported intents: \`report\`, \`balance\`, \`positions\`, \`trades [pair] [period]\`, \`start\`, \`stop\`.
- [ ] AC3: Unrecognised inputs display a help menu rather than crashing.
- [ ] AC4: CLI supports both interactive REPL mode and single-command mode (\`python kryptos.py balance\`).
SBODY
)"

create_story "$E9_NUM" "story,E9" \
  "[S9.2.1] Trade Report & P&L Display — rich terminal table with win rate and exit breakdown" \
  "$(cat <<SBODY
## Traceability
- **Epic:** E9 — Natural Language CLI (#${E9_NUM})
- **BRD:** FR-52 (Audit trail accessibility)
- **DSD:** §4 Database Design
- **NFR:** NFR-11 (CLI usability), NFR-04 (Auditability)
- **Code:** \`src/reports/trade_report.py\`, \`src/cli/display.py\`, \`src/utils/tz.py\`

## User Story
**As a** trader,
**I want** a formatted trade report with per-trade P&L, win rate, and exit reasons,
**so that** I can evaluate system performance without opening the SQLite database.

## Acceptance Criteria
- [ ] AC1: \`report\` command displays rich terminal table with: Trade ID, pair, entry/exit dates, invested USD, entry/exit price, PNL%, PNL USD, exit reason.
- [ ] AC2: Win rate (wins/total) and average PNL% per trade shown as summary row.
- [ ] AC3: Times displayed in Singapore timezone (SGT) via \`utils/tz.py\`.
- [ ] AC4: \`report mode=backtest\` queries \`data/backtest_paper.db\` instead of the live database.
SBODY
)"

# =============================================================================
# EPIC E10 — Backtesting & Validation
# =============================================================================
echo ""
echo "==> Epic E10: Backtesting & Validation"
E10_URL=$(gh issue create --repo "$REPO" --label "epic,E10" \
  --title "[Epic E10] Backtesting & Validation" \
  --body "$(cat <<'EOF'
## Epic E10 — Backtesting & Validation

**Goal:** Allow strategy validation over historical data to verify that quantitative rules produce positive expectancy before risking real capital.

**BRD FRs:** FR-37, FR-38
**NFRs:** NFR-05 (Determinism), NFR-07 (Configurability)
**DSD:** §1 Conceptual Design
**Code:** `tests/test_backtest.py`, `tests/trades_to_candle_converter.py`, `src/exchange/historical_feed.py`

**Sub-issues (Stories):**
- S10.1.1 — Historical Candle Conversion from Kraken CSV
- S10.2.1 — Full Strategy Backtest with metrics
EOF
)")
E10_NUM=$(echo "$E10_URL" | grep -o '[0-9]*$')
echo "  Epic #${E10_NUM}: E10 — Backtesting & Validation"

create_story "$E10_NUM" "story,E10" \
  "[S10.1.1] Historical Candle Conversion — Kraken trade CSV to OHLCV JSON for backtesting" \
  "$(cat <<SBODY
## Traceability
- **Epic:** E10 — Backtesting & Validation (#${E10_NUM})
- **BRD:** FR-38
- **DSD:** §1 Conceptual Design
- **NFR:** NFR-05 (Determinism)
- **Code:** \`tests/trades_to_candle_converter.py\`

## User Story
**As a** developer,
**I want** to convert raw Kraken trade CSV exports into the OHLCV JSON format consumed by the backtester,
**so that** I can backtest over real 12-month exchange data.

## Acceptance Criteria
- [ ] AC1: \`tests/trades_to_candle_converter.py\` accepts \`<source.csv>|<target.json>\` batch arguments.
- [ ] AC2: Input CSV format is \`unix_timestamp,price,volume\` (headerless or headered auto-detected).
- [ ] AC3: Output JSON matches Kraken OHLC format: \`[time, open, high, low, close, vwap, volume, count]\` per 15-min interval.
- [ ] AC4: VWAP computed as \`Σ(price*volume) / Σ(volume)\` per interval.
- [ ] AC5: Pair key inferred from target filename (e.g. \`SOLUSD_candle.json\` → \`SOLUSD\`).
SBODY
)"

create_story "$E10_NUM" "story,E10" \
  "[S10.2.1] Full Strategy Backtest — replay historical candles through complete agent loop" \
  "$(cat <<SBODY
## Traceability
- **Epic:** E10 — Backtesting & Validation (#${E10_NUM})
- **BRD:** FR-37, FR-38
- **DSD:** §1 Conceptual Design
- **NFR:** NFR-05 (Determinism), NFR-07 (Configurability)
- **Code:** \`tests/test_backtest.py\`, \`src/exchange/historical_feed.py\`

## User Story
**As a** quant analyst,
**I want** to run the full agent loop over historical data,
**so that** I can measure win rate, expectancy, and drawdown before going live.

## Acceptance Criteria
- [ ] AC1: \`tests/test_backtest.py --candles N\` replays N candles from \`history/\` JSON files.
- [ ] AC2: LLM cycle runs for each candle using \`HistoricalFeed\`. All risk rules apply identically to live mode.
- [ ] AC3: Time-of-Day guard uses candle timestamp, not system clock.
- [ ] AC4: Output written to \`backtest_run.log\` (auto-cleared at start). Never writes to production databases.
- [ ] AC5: Final summary includes: total cycles, total trades, win rate, net PNL%, max drawdown%.
SBODY
)"

# =============================================================================
# EPIC E11 — DevOps & Resilience
# =============================================================================
echo ""
echo "==> Epic E11: DevOps & Resilience"
E11_URL=$(gh issue create --repo "$REPO" --label "epic,E11" \
  --title "[Epic E11] DevOps & Resilience" \
  --body "$(cat <<'EOF'
## Epic E11 — DevOps & Resilience

**Goal:** Ensure the bot can be reliably deployed, monitored, and restarted without data loss or financial exposure.

**BRD FRs:** FR-44, FR-64
**NFRs:** NFR-02 (Availability), NFR-06 (Crash resilience), NFR-08 (Security)
**DSD:** §5 Exception Management
**Code:** `requirements.txt`, `src/exchange/paper_broker.py`, `src/storage/database.py`, `src/notifications/notifier.py`

**Sub-issues (Stories):**
- S11.1.1 — Dependency Locking
- S11.2.1 — Crash Recovery & Position Persistence
- S11.3.1 — Health Check Webhook
EOF
)")
E11_NUM=$(echo "$E11_URL" | grep -o '[0-9]*$')
echo "  Epic #${E11_NUM}: E11 — DevOps & Resilience"

create_story "$E11_NUM" "story,E11" \
  "[S11.1.1] Dependency Locking — all Python deps pinned to exact versions in requirements.txt" \
  "$(cat <<SBODY
## Traceability
- **Epic:** E11 — DevOps & Resilience (#${E11_NUM})
- **BRD:** Implied operational requirement
- **DSD:** §5 Exception Management
- **NFR:** NFR-08 (Security), NFR-03 (Reliability)
- **Code:** \`requirements.txt\`

## User Story
**As a** DevOps engineer,
**I want** all Python dependencies pinned to exact versions,
**so that** the bot behaves identically across all environments.

## Acceptance Criteria
- [ ] AC1: \`requirements.txt\` contains fully pinned versions (e.g. \`pandas==2.2.1\`) from \`pip freeze\`.
- [ ] AC2: Installation via \`pip install -r requirements.txt\` produces no version conflicts.
- [ ] AC3: \`requirements.txt\` validated in CI before merge.
SBODY
)"

create_story "$E11_NUM" "story,E11" \
  "[S11.2.1] Crash Recovery & Position Persistence — resume monitoring open positions on restart" \
  "$(cat <<SBODY
## Traceability
- **Epic:** E11 — DevOps & Resilience (#${E11_NUM})
- **BRD:** FR-44
- **DSD:** §5 Exception Management
- **NFR:** NFR-06 (Crash resilience), NFR-02 (Availability)
- **Code:** \`src/exchange/paper_broker.py::get_open_positions\`, \`src/storage/database.py\`

## User Story
**As a** trader,
**I want** the bot to resume monitoring all open positions after a power loss or crash,
**so that** no position is left unmonitored.

## Acceptance Criteria
- [ ] AC1: On startup, \`broker.get_open_positions()\` queries \`paper_positions\` / \`live_positions\` for all \`status='open'\` rows.
- [ ] AC2: Recovered positions immediately enter the \`check_stops_and_tp()\` monitoring loop.
- [ ] AC3: Startup log line: \`"Recovered N open positions for monitoring."\` emitted.
- [ ] AC4: SQLite WAL mode enabled to protect against mid-write corruption on power loss.
SBODY
)"

create_story "$E11_NUM" "story,E11" \
  "[S11.3.1] Health Check Webhook — external uptime monitor pinged every 15 minutes" \
  "$(cat <<SBODY
## Traceability
- **Epic:** E11 — DevOps & Resilience (#${E11_NUM})
- **BRD:** FR-64
- **DSD:** §6 Notification Framework
- **NFR:** NFR-02 (Availability), NFR-09 (Observability)
- **Code:** \`src/notifications/notifier.py::ping_healthcheck\`, \`main.py\`

## User Story
**As an** operator,
**I want** an external uptime monitor pinged every 15 minutes,
**so that** I receive an alert if the trading loop silently deadlocks.

## Acceptance Criteria
- [ ] AC1: \`notifier.ping_healthcheck()\` makes a \`GET\` request to \`notifications.healthcheck_url\` after every cycle.
- [ ] AC2: Ping timeout is 5 seconds — never blocks the trading loop.
- [ ] AC3: If \`healthcheck_url\` is empty in config, the feature is silently disabled.
- [ ] AC4: Compatible with healthchecks.io and any HTTP-based uptime monitor.
SBODY
)"

# =============================================================================
# EPIC E12 — Stop-Loss Protection & Gain Preservation  (NEW — backtest-driven)
# =============================================================================
echo ""
echo "==> Epic E12: Stop-Loss Protection & Gain Preservation (NEW)"
E12_URL=$(gh issue create --repo "$REPO" --label "epic,E12" \
  --title "[Epic E12] Stop-Loss Protection & Gain Preservation" \
  --body "$(cat <<'EOF'
## Epic E12 — Stop-Loss Protection & Gain Preservation

**Goal:** Eliminate the two structural causes of capital loss identified in backtesting (3,931 cycles, Apr 5–6 2026):
1. The LLM exits profitable positions too early via `propose_sell`, leaving gains on the table.
2. The fixed 5% stop-loss never moves — a trade that peaked at +8% can still close at -5%.

**Evidence from backtest:**
| Exit Reason | Trades | Total P&L |
|---|---|---|
| agent_sell (LLM early exit) | 14 | +$56.94 (avg +$4.07) |
| take_profit (full target hit) | 2 | +$28.10 (avg +$14.05) |
| stop_loss | 6 | -$96.24 (avg -$16.04) |

The LLM leaves ~3× gains per trade on the table. 6 stop-losses erase all wins combined.

**BRD FRs:** FR-20 (80% TP proximity), FR-24 (SL), FR-26 (dynamic TP), FR-36 (deterministic enforcement)
**NFRs:** NFR-05 (Determinism), NFR-04 (Auditability), NFR-07 (Configurability)
**DSD:** §7.4 Sell Flow, §7.5 SL/TP Flow, §4 Database Design, §3a.5 Tool Calling

**Sub-issues (Stories):**
- S12.1.1 — Bug Fix: Code-enforce 80% TP proximity in validate_sell
- S12.2.1 — Trailing stop: move SL upward as price rises
- S12.3.1 — Breakeven stop: jump SL to entry once in profit
- S12.4.1 — ATR-based SL: volatility-proportional stop-loss at entry
- S12.5.1 — Partial take-profit: lock 50% at mid-target, let rest run
EOF
)")
E12_NUM=$(echo "$E12_URL" | grep -o '[0-9]*$')
echo "  Epic #${E12_NUM}: E12 — Stop-Loss Protection & Gain Preservation"

create_story "$E12_NUM" "story,E12,bug,risk-management,backtest-validated" \
  "[S12.1.1] Bug: LLM exits early via propose_sell — enforce 80% TP proximity in validate_sell" \
  "$(cat <<SBODY
## Traceability
- **Epic:** E12 — Stop-Loss Protection & Gain Preservation (#${E12_NUM})
- **BRD:** FR-20, FR-33, FR-36
- **DSD:** §7.4 Sell Flow, §3a.5 Tool Calling Schema
- **NFR:** NFR-05 (Determinism), NFR-04 (Auditability)
- **Code:** \`src/risk/risk_manager.py::validate_sell\` (line 339)

## User Story
**As a** risk manager,
**I want** \`validate_sell()\` to block the LLM from exiting a position unless its P&L is ≥ 80% of the configured TP target,
**so that** the LLM cannot prematurely capture small gains and must let winning trades run toward their full target.

## Problem (Backtest Evidence)
14 of 16 profitable trades exited via \`agent_sell\` at 2–4% despite TP targets of 5–20%. \`validate_sell()\` only enforces a 1% minimum floor — the 80% TP proximity condition in BRD FR-20 is a prompt instruction only, not code-enforced.

**Audit log (every agent_sell):** *"RSI overbought and price near upper BB with SELL signal, P&L above floor."*

## Acceptance Criteria
- [ ] AC1: \`validate_sell()\` reads \`take_profit_pct\` from the open position record in \`paper_positions\`.
- [ ] AC2: Proximity threshold = \`take_profit_pct × (early_sell_min_tp_proximity_pct / 100)\`. Example: TP=5%, proximity=80% → threshold=4%.
- [ ] AC3: If \`est_pnl_pct < proximity_threshold\`, sell rejected: \`"Early sell blocked: P&L +X.XX% is below Y.Y% (80% of TP target Z%)"\`.
- [ ] AC4: Threshold configurable: \`config.yaml → trading.early_sell_min_tp_proximity_pct: 80\`.
- [ ] AC5: Automatic SL/TP exits bypass \`validate_sell\` — LLM-initiated exits only.
- [ ] AC6: Rejection written to \`audit_risk_checks\` with check_name \`"early_sell_proximity_guard"\`.
- [ ] AC7: Backtest re-run shows zero \`agent_sell\` exits below 80% of TP target.
- [ ] AC8: Unit test \`tests/test_risk_manager.py\`: (a) sell allowed at 85% of TP, (b) blocked at 50%, (c) always allowed above 100%.

## Files to Change
- \`src/risk/risk_manager.py\` — \`validate_sell()\` line 339
- \`config.yaml\` — add \`early_sell_min_tp_proximity_pct: 80\` under \`trading:\`
- \`.claude/skills/trading-rules/SKILL.md\` — note 80% condition is now code-enforced
SBODY
)"

create_story "$E12_NUM" "story,E12,enhancement,risk-management" \
  "[S12.2.1] Feat: Trailing stop — move SL upward as price rises to protect gains" \
  "$(cat <<SBODY
## Traceability
- **Epic:** E12 — Stop-Loss Protection & Gain Preservation (#${E12_NUM})
- **BRD:** FR-24, FR-36
- **DSD:** §7.5 Stop Loss & Take Profit, §4 Database Design
- **NFR:** NFR-05 (Determinism), NFR-04 (Auditability), NFR-07 (Configurability)
- **Code:** \`src/exchange/paper_broker.py::check_stops_and_tp\` (line 254)

## User Story
**As a** portfolio manager,
**I want** the stop-loss to automatically move upward as price rises (trailing % from peak price),
**so that** a winning trade that later reverses locks in most of the gain instead of exiting at -5%.

## How It Works
Example with trail_pct=3%:
- Entry \$100 → SL=\$95 → Price \$120 → SL moves to \$116.40 → falls to \$116.40 → exit +\$16.40

## Acceptance Criteria
- [ ] AC1: \`highest_price_seen\` tracked per position; updated to \`max(stored, current_price)\` each cycle.
- [ ] AC2: Trailing SL = \`highest_price_seen × (1 - trail_pct / 100)\`.
- [ ] AC3: Only activates once \`current_price >= entry_price × (1 + activate_after_pct / 100)\`.
- [ ] AC4: \`stop_loss_price\` updated only if \`trailing_sl > current stop_loss_price\` (never decreases).
- [ ] AC5: Feature enabled/disabled via \`config.yaml → trailing_stop.enabled\`.
- [ ] AC6: Per-pair \`trail_pct\` overrides supported (DOGE, RAILS, HYPE, SUI → wider trail).
- [ ] AC7: Every SL update logged with \`[TRAILING_SL]\` prefix: old SL, new SL, peak price.
- [ ] AC8: \`paper_positions\` table gains \`highest_price_seen\` column (nullable, migrated).
- [ ] AC9: Trailing stop and breakeven stop (S12.3.1) are mutually exclusive — config validation at startup.
- [ ] AC10: Unit test \`tests/test_trailing_stop.py\`: (a) moves up on rise, (b) does not move on fall, (c) does not activate before threshold, (d) fires at trailing level.

## Config
\`\`\`yaml
trailing_stop:
  enabled: true
  trail_pct: 3.0
  activate_after_pct: 1.5
  per_pair_overrides:
    DOGE/USD: 5.0
    RAILS/USD: 5.0
    HYPE/USD: 5.0
    SUI/USD: 4.0
\`\`\`

## Files to Change
- \`src/exchange/paper_broker.py\` — \`check_stops_and_tp()\`
- \`src/exchange/kraken_client.py\` — mirror for live mode
- \`src/storage/database.py\` — add \`highest_price_seen\` column migration
- \`config.yaml\` — add \`trailing_stop:\` block
SBODY
)"

create_story "$E12_NUM" "story,E12,enhancement,risk-management" \
  "[S12.3.1] Feat: Breakeven stop — move SL to entry once position reaches profit threshold" \
  "$(cat <<SBODY
## Traceability
- **Epic:** E12 — Stop-Loss Protection & Gain Preservation (#${E12_NUM})
- **BRD:** FR-24, FR-36
- **DSD:** §7.5 Stop Loss & Take Profit
- **NFR:** NFR-05 (Determinism), NFR-07 (Configurability)
- **Code:** \`src/exchange/paper_broker.py::check_stops_and_tp\` (line 254)

## User Story
**As a** trader,
**I want** the SL to jump to entry price once a position rises above a configurable profit threshold,
**so that** I can never lose money on a trade that was once profitable.

## Note
Trailing stop (S12.2.1) is preferred — both must NOT be enabled simultaneously. Config validation enforces mutual exclusion at startup.

## Acceptance Criteria
- [ ] AC1: Once \`current_price >= entry_price × (1 + breakeven_trigger_pct / 100)\`, update \`stop_loss_price\` to \`entry_price\`.
- [ ] AC2: SL only moves upward — never below configured floor.
- [ ] AC3: Only fires once per position.
- [ ] AC4: Feature enabled/disabled via \`config.yaml → breakeven_stop.enabled\`.
- [ ] AC5: Startup raises \`ConfigError\` if both trailing and breakeven are enabled simultaneously.
- [ ] AC6: SL update logged with \`[BREAKEVEN_SL]\` prefix.
- [ ] AC7: No schema change required.
- [ ] AC8: Unit test \`tests/test_breakeven_stop.py\`: (a) moves to entry on threshold, (b) does not fire before, (c) does not re-fire after.

## Config
\`\`\`yaml
breakeven_stop:
  enabled: false
  trigger_pct: 2.0
\`\`\`

## Files to Change
- \`src/exchange/paper_broker.py\` — \`check_stops_and_tp()\`
- \`src/exchange/kraken_client.py\` — mirror for live mode
- \`config.yaml\` — add \`breakeven_stop:\` block
- \`src/risk/risk_manager.py\` — mutual exclusion in \`validate_config()\`
SBODY
)"

create_story "$E12_NUM" "story,E12,enhancement,risk-management" \
  "[S12.4.1] Feat: ATR-based SL — set stop-loss proportional to volatility at entry, not fixed 5%" \
  "$(cat <<SBODY
## Traceability
- **Epic:** E12 — Stop-Loss Protection & Gain Preservation (#${E12_NUM})
- **BRD:** FR-24, FR-36
- **DSD:** §7.1 Autonomous Buy Flow, §4 Database Design
- **NFR:** NFR-07 (Configurability), NFR-05 (Determinism)
- **Code:** \`src/risk/risk_manager.py::get_stop_loss_pct\` (line 186), \`src/analysis/indicators.py::compute_indicators\`

## User Story
**As a** risk manager,
**I want** the stop-loss percentage computed from the pair's ATR at entry (not a fixed 5%),
**so that** volatile pairs like DOGE/RAILS get a wider SL that won't trigger on normal noise, and stable pairs like BTC get a tighter SL that reduces capital-at-risk.

## Acceptance Criteria
- [ ] AC1: \`get_stop_loss_pct(pair, atr, price)\` computes \`atr_sl_pct = (atr_multiplier × atr / price) × 100\`.
- [ ] AC2: Result bounded: \`min_stop_loss_pct ≤ atr_sl_pct ≤ max_stop_loss_pct\` (hard cap at 5% maintained).
- [ ] AC3: Falls back to \`trading.stop_loss_pct\` (5%) when disabled or when \`atr\`/\`price\` is None.
- [ ] AC4: ATR sourced from \`indicators.compute_indicators()\` field \`atr_14\` — no new indicator work.
- [ ] AC5: Computed SL% passed to \`place_order()\` and stored as \`stop_loss_pct\` in \`paper_positions\`.
- [ ] AC6: Logged per-trade with \`[ATR_SL]\` prefix: ATR value and resulting SL%.
- [ ] AC7: \`allowed_take_profit_pcts\` whitelist does NOT apply to ATR-based SL.
- [ ] AC8: Unit test \`tests/test_atr_sl.py\`: (a) BTC ATR 1% → SL ~1.5%, (b) DOGE ATR 9% → capped at 5%, (c) disabled → 5%.

## Config
\`\`\`yaml
atr_stop_loss:
  enabled: true
  atr_multiplier: 1.5
  max_stop_loss_pct: 5.0
  min_stop_loss_pct: 1.0
\`\`\`

## Files to Change
- \`src/risk/risk_manager.py\` — \`get_stop_loss_pct()\` line 186
- \`main.py\` — pass \`atr\` and \`price\` from indicators dict
- \`config.yaml\` — add \`atr_stop_loss:\` block
SBODY
)"

create_story "$E12_NUM" "story,E12,enhancement,risk-management" \
  "[S12.5.1] Feat: Partial take-profit — close 50% at mid-target and let the rest run to full TP" \
  "$(cat <<SBODY
## Traceability
- **Epic:** E12 — Stop-Loss Protection & Gain Preservation (#${E12_NUM})
- **BRD:** FR-24, FR-26, FR-36
- **DSD:** §7.4 Sell Flow, §7.5 SL/TP Flow, §4 Database Design
- **NFR:** NFR-05 (Determinism), NFR-04 (Auditability), NFR-07 (Configurability)
- **Code:** \`src/exchange/paper_broker.py::check_stops_and_tp\`, \`src/exchange/paper_broker.py::close_position\`

## User Story
**As a** portfolio manager,
**I want** 50% of a position closed automatically when price reaches 50% of the TP target,
**so that** some profit is always locked in even if price reverses before reaching the full TP.

## Trade-Off
| Scenario | Without Partial TP | With Partial TP |
|---|---|---|
| Full TP hit | 100% of gain | ~75% of gain |
| Reversal after mid-point | Full SL loss possible | Half locked in, other half at breakeven |
| SL before mid-point | Full SL loss | Full SL loss (unchanged) |

## Acceptance Criteria
- [ ] AC1: If \`current_price >= partial_trigger_price\` AND \`pos["partial_exited"] == 0\` → execute partial exit.
- [ ] AC2: Partial trigger = \`entry_price × (1 + (take_profit_pct × trigger_pct_of_tp / 100) / 100)\`. Example: TP=12%, trigger=50% → fires at +6%.
- [ ] AC3: Partial close volume = \`pos["volume"] × close_fraction\` (0.5). Remaining volume updated in \`paper_positions\`.
- [ ] AC4: Partial exit recorded in \`paper_trades\` with \`exit_reason = "partial_take_profit"\`.
- [ ] AC5: \`paper_positions.partial_exited\` set to 1 after partial close — prevents re-triggering.
- [ ] AC6: If \`move_sl_to_breakeven: true\`, \`stop_loss_price\` updated to \`entry_price\` after partial close.
- [ ] AC7: Remaining position continues to full TP or SL; recorded as a second row in \`paper_trades\`.
- [ ] AC8: Feature enabled/disabled via \`config.yaml → partial_take_profit.enabled\`.
- [ ] AC9: Logged with \`[PARTIAL_TP]\` prefix: volume closed, price, P&L%, remaining volume.
- [ ] AC10: \`paper_positions\` gains \`partial_exited INTEGER DEFAULT 0\` column via migration.
- [ ] AC11: \`src/reports/trade_report.py\` handles \`"partial_take_profit"\` exit reason in P&L summaries.
- [ ] AC12: Unit test \`tests/test_partial_tp.py\`: (a) fires at trigger, (b) does not re-fire, (c) remaining hits full TP, (d) remaining hits SL.

## Config
\`\`\`yaml
partial_take_profit:
  enabled: true
  trigger_pct_of_tp: 50
  close_fraction: 0.5
  move_sl_to_breakeven: true
\`\`\`

## Files to Change
- \`src/exchange/paper_broker.py\` — \`check_stops_and_tp()\`, \`close_position()\`
- \`src/exchange/kraken_client.py\` — mirror for live mode
- \`src/storage/database.py\` — add \`partial_exited\` column migration
- \`config.yaml\` — add \`partial_take_profit:\` block
- \`src/reports/trade_report.py\` — handle new exit reason
SBODY
)"

# =============================================================================
echo ""
echo "==> All issues created successfully."
echo ""
echo "Epic index:"
echo "  E1  (#${E1_NUM})  Market Data Ingestion"
echo "  E2  (#${E2_NUM})  Quantitative Signal Engine"
echo "  E3  (#${E3_NUM})  AI Cognitive Orchestrator"
echo "  E4  (#${E4_NUM})  Risk & Compliance Guard"
echo "  E5  (#${E5_NUM})  Trade Execution Engine"
echo "  E6  (#${E6_NUM})  Paper Trading & Simulation"
echo "  E7  (#${E7_NUM})  Audit & Observability"
echo "  E8  (#${E8_NUM})  Telegram Notification Framework"
echo "  E9  (#${E9_NUM})  Natural Language CLI"
echo "  E10 (#${E10_NUM}) Backtesting & Validation"
echo "  E11 (#${E11_NUM}) DevOps & Resilience"
echo "  E12 (#${E12_NUM}) Stop-Loss Protection & Gain Preservation  ← NEW"
echo ""
echo "View all issues: https://github.com/${REPO}/issues"
