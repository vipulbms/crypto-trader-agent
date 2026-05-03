# Kryptos — AI Crypto Trading Agent

<!-- Shared context — applies to all contributors and Claude sessions -->
@.claude/memory/project_kryptos.md
@.claude/memory/feedback_coding_style.md
@.claude/memory/feedback_testing.md
@.claude/memory/feedback_github_traceability.md

## Project Overview

Kryptos is an automated crypto trading agent that uses a local LLM (Ollama) to make trading decisions on Kraken exchange. It operates in paper mode (virtual money) or live mode (real money).

**Entry points:**
- `python main.py --paper` — background trading loop
- `python kryptos.py` — interactive CLI

---

## Architecture

```
main.py                    — trading loop runner
kryptos.py                 — interactive CLI entry point
config.yaml                — all tunable parameters
src/
  agent/
    trading_agent.py       — LLM call loop, retry, fallback model
    tools.py               — propose_buy / propose_sell / hold tools
    prompts.py             — SYSTEM_PROMPT + build_cycle_prompt()
  analysis/
    indicators.py          — RSI, MACD, ATR, Bollinger Bands
    signals.py             — BUY/SELL/HOLD signal generation
    features.py            — regime, sentiment, patterns, exit_timing, sizing, dynamic_tp
  exchange/
    paper_broker.py        — virtual order execution, SL/TP monitoring
    kraken_client.py       — live Kraken REST API client
    websocket_feed.py      — Kraken WS v2 price feed + candle buffer
  risk/
    risk_manager.py        — position sizing, config validation, TP/SL config
  storage/
    database.py            — SQLite connection helper (audit.db, paper_trading.db)
    audit_logger.py        — full audit trail: cycles, signals, trades, balance snapshots
  notifications/
    notifier.py            — Telegram alerts for trades, errors, daily summary
  cli/
    commands.py            — CLI command handlers
    display.py             — rich terminal display
    nl_parser.py           — natural language CLI input parser
  reports/
    trade_report.py        — P&L and trade history reports
    daily_report.py        — Full daily P&L report (run_daily_report)
    review_report.py       — N-day performance review with verdict (run_review)
  utils/
    tz.py                  — Singapore timezone helpers
    timing.py              — @timed decorator, cycle_id propagation
```

---

## Key Design Decisions

### Stop-loss / Take-profit
- SL is always 5% below entry (non-negotiable, enforced by broker)
- TP is configurable per pair (5 / 8 / 12 / 16 / 20%)
- `check_stops_and_tp()` runs on every loop iteration **before** the LLM cycle — highest priority
- SL/TP are price-tick based in paper mode (no order book); they fire when `current_price` crosses the stored level

### LLM Decision Cycle
- Single LLM call per cycle covering all pairs (ranked multi-pair prompt)
- Agent may call `propose_buy` for top-3 signals only; `propose_sell` only with strong conditions
- **Early sell guardrails (critical):** agent cannot call `propose_sell` unless P&L > +2%; for early TP capture, position must be at ≥60% of TP target with confirmed reversal
- Fallback model configured in `config.yaml → llm.fallback_model` if primary times out

### Paper Broker
- `place_order()`: applies entry slippage (0.05%, now symmetric with exit #140), deducts `actual_cost + fee_usd` from cash
- `usd_value` stored in `paper_positions` = `actual_cost` (entry cost, fee excluded)
- `close_position()`: applies exit slippage (0.05%) + exit fee (0.26% hardcoded in method)
- `get_balance()`: `total_usd = cash + Σ(usd_value of open positions)`

### Audit Trail
- Every cycle, signal, trade, balance snapshot, and error is written to `audit.db`
- Balance snapshots are taken **after** trades execute (post-trade re-fetch)

---

## Pairs and Take-Profit Targets

| Pair | TP% | Notes |
|---|---|---|
| BTC/USD | 8% | Slow mover |
| ETH/USD | 12% | |
| BNB/USD | 12% | |
| SOL/USD | 16% | Volatile |
| XRP/USD | 12% | News-driven |
| TRX/USD | 12% | |
| DOGE/USD | 20% | Meme coin |
| ADA/USD | 12% | |
| LTC/USD | 8% | |
| ~~RAILS/USD~~ | ~~20%~~ | **Disabled** — 25% win rate, 3/4 stop losses (#132) |
| AVAX/USD | 12% | |
| SUI/USD | 16% | |
| HYPE/USD | 20% | |
| UNI/USD | 12% | |
| INJ/USD | 16% | |
| WIF/USD | 20% | Solana meme; buy_min_score=6; caution=0.40 (#145) |
| TON/USD | 16% | Telegram blockchain; clean RSI cycles (#146) |
| OP/USD | 16% | Optimism L2; buy_min_score=6 (#147) |
| ARB/USD | 16% | Arbitrum L2; largest ETH L2 by TVL (#148) |
| JUP/USD | 20% | Jupiter DEX (Solana); buy_min_score=7; caution=0.35 (#149) |
| PEPE/USD | 20% | Extreme meme; buy_min_score=8; caution=0.25 (#150) |
| TIA/USD | 20% | Celestia modular; buy_min_score=7; caution=0.35 (#151) |
| RENDER/USD | 16% | AI GPU compute; caution=0.50 (#152) |
| FET/USD | 16% | ASI Alliance AI; caution=0.45 (#153) |
| STX/USD | 16% | Bitcoin L2 (Stacks); caution=0.50 (#154) |
| PENDLE/USD | 20% | Pendle Finance DeFi yield protocol; buy_min_score=7; caution=0.40; trailing 7%/5% (#186) |
| ONDO/USD | 16% | Ondo Finance RWA tokenisation; buy_min_score=6; caution=0.50 (#187) |
| BONK/USD | 25% | Solana memecoin (extreme); buy_min_score=9; caution=0.20; trailing 7%/5% (#188) |
| MOVR/USD | 20% | Moonriver (Moonbeam/Polkadot parachain); buy_min_score=6; caution=0.40; trailing 6%/4% |

All pairs use 5% stop-loss.

---

## Risk Rules (enforced)
- Max position size: 30% of portfolio per trade
- Max open positions: 3 simultaneously
- Min cash reserve: 10% of portfolio
- Daily loss limit: 10% — halts all trading for the day

---

## Environment Variables

```
KRAKEN_API_KEY        # Live mode only
KRAKEN_API_SECRET     # Live mode only
TELEGRAM_BOT_TOKEN    # Optional — notifications
TELEGRAM_CHAT_ID      # Optional — notifications
```

---

## Common Commands

```bash
# Run paper trading
python main.py --paper

# Interactive CLI
python kryptos.py

# View recent trades
python kryptos.py report

# Check balance
python kryptos.py balance
```

---

## Session Notes

Development history is documented in `docs/sessions/`. Each file covers one session's changes:

| File | Summary |
|---|---|
| session_2026_03_30b–d | Early architecture, WebSocket feed, paper broker |
| session_2026_03_31a | LLM INFO logging; TP tuning |
| session_2026_03_31b | Multi-pair ranked prompt; signal confluence |
| session_2026_03_31c | Position sizing; regime detection |
| session_2026_03_31d | Dynamic TP; sentiment; pattern analysis |
| session_2026_03_31e | Exit timing; post-trade analysis |
| session_2026_03_31f | Timeout handling across LLM/DB/WebSocket |
| session_2026_03_31g | Telegram notification: add invested USD amount |
| session_2026_03_31h | Balance mismatch fix (fee visibility, stale snapshot); SL priority; early-sell guardrails |
| session_2026_04_01a | caution_factor code-enforced; dynamic TP wired to place_order(); 18 tests added; commit skill extended |
| session_2026_04_01b | LLM switched to deepseek-r1:7b; KrakenClient full live broker parity rewrite |
| session_2026_04_01c | Backtesting pipeline added; 5 bugs identified; 7.5-day backtest run and reported |
| session_2026_04_04a | Volatility-Adaptive Quant Migration; OBI implementation; Limit orders |
| session_2026_04_05a | Minimum Profit Floor implementation; extracted trading rules to SKILL.md |
| session_2026_04_05b | Multi-indicator confluence scoring; circuit breaker (DB-backed); heartbeat |
| session_2026_04_05c | Live API Limit orders / fallbacks; 2-hour heartbeat, 6-hour PnL report |
| session_2026_04_05d | Post-only limit chase orders, volume/time-of-day filters, healthcheck webhook |
| session_2026_04_05e | Global kill switch (-7% daily drawdown); backtest clean-slate teardown; audit_rejections.py |
| session_2026_04_05f | Documentation: BRD, detailed solution design (10 sections, 9 Mermaid diagrams, 7 ADRs), epics/stories/AC; removed stale scripts |
| session_2026_04_05g | Documentation: README rewrite; BRD v2.0 formal rewrite; new docs/codebase.md (developer reference); new docs/how_to_debug.md; commit SKILL.md expanded to 6 docs; model references generalised |
| session_2026_04_06a | Backtest analysis (3,931 cycles): root-caused early-sell bug + 5 SL/TP improvements; GitHub issues shell script (E1–E12, 28 stories, sub-issues API) |
| session_2026_04_06b | Fix GitHub Sub-Issues API headers in `create_story()`; create `link_epics.sh` retroactive linker |
| session_2026_04_06c | Fix: ATR floor decoupled (atr_tp_min_pct=0.3); rsi_overbought raised 60→65; validate_sell 80% TP proximity guard; 5 new tests; closes #83 |
| session_2026_04_06d | S12.3.1: Breakeven stop tests (3 tests); closes #85 |
| session_2026_04_06e | S12.5.1: Partial take-profit (paper + live broker, 5 tests, closes #87); all 51 tests pass |
| session_2026_04_07a | Fix: trading hours window corrected to 06:00–04:00 SGT (22:00–20:00 UTC cross-midnight) |
| session_2026_04_07b | Chore: migrate Claude memory files to project scope (.claude/memory/); closes #91 |
| session_2026_04_07c | Fix: HistoricalFeed timestamp-based price lookup — shorter pairs (BNB/AVAX/UNI) were stuck at last candle price forever |
| session_2026_04_08a | Integrate daily_report + review_report into src/reports/ and kryptos CLI (daily/review subcommands) |
| session_2026_04_08b | Fix backtest timestamps (#98), add full chart legend (#99), charts integral to reports (#100); 80 tests passing |
| session_2026_04_08c | Fix trailing stop thresholds (#102), ATR floor 0.3→1.0% (#103), BB squeeze TP (#104), dynamic TP pair min (#95), trading hours 03:00–04:00 SGT (#105) |
| session_2026_04_09a | Per-pair atr_tp_min_pct/RSI/BB squeeze/volume ratio; backtest hours fix (#106); 20 new tests; analysis scripts; 12 GitHub issues #107–#118 created |
| session_2026_04_09b | Adaptive ATR floor (#108), adaptive BB/volume injection (#113,#114), MACD decay normalised (#112), candle timestamps (#115), 90% capital deployment (#116), signal driver report (#117), calibrate_params.py (#118) |
| session_2026_04_09c | Chore: disable time-of-day trading hours guard (#121); volume floor remains always-on |
| session_2026_04_09d | Fix: backtest clean-slate teardown — get_db_path(), pre-run validation (#122) |
| session_2026_04_09e | Fix: trailing stop exits mislabelled as stop_loss — trailing_stop label + circuit breaker exclusion (#123) |
| session_2026_04_09f | Feat: per-pair caution_factor_bearish (#124), per-pair buy_min_score (#128), aggressive position sizing 20%/5% reserve (#130) |
| session_2026_04_09g | Fix: trailing_stop in display/reporting (#125); min_order_usd raised to $20 + Guard 0.5 (#126); force_close_all at backtest end (#127); overdraw guard in place_order() (#129) |
| session_2026_04_10a | Fix: RAILS buy_min_score=7, caution_factor_bearish 0.40→0.25; unambiguous propose_sell gate (all three conditions required, not disjunctive); SKILL.md frontmatter fix (#131) |
| session_2026_04_10b | Chore: disable RAILS/USD (25% win rate, 3/4 stops); reset paper trading to clean $1,000 slate (#132) |
| session_2026_04_10c | Fix: total value in balance report used stale audit snapshot — now computed live for paper mode (#133) |
| session_2026_04_10d | Fix: early-sell TP proximity guard reduced from 80% to 60% — avoids asymmetric trap; configurable via `early_sell_min_tp_proximity_pct` (#138) |
| session_2026_04_11a | Feat: ADX trend strength filter (#134); RSI divergence detection (#135); fast backtest `--no-llm` flag (signal-only, seconds vs 2h) |
| session_2026_04_11b | Feat: OBV accumulation signal +1 BUY (#136); BB squeeze release +2 BUY (#137); per-pair obv_trend_period; max_score 22→25; 96 tests |
| session_2026_04_11c | Fix: Shorten adaptive lookback 400→200 (#141); enable partial TP (#142); correlation cluster guard (#139); graduated circuit breaker 1h/2h/4h (#143); 169 tests |
| session_2026_04_11d | Fix: Entry slippage added to place_order() (#140); prompt "TOP 3" → dynamic max_buys_per_cycle (#144); 172 tests |
| session_2026_04_11e | Fix: max_open_positions 13→5, compute_position_size floor at min_order_usd, config sanity warning, prompt min_order guard (#159); 180 tests |
| session_2026_04_11f | Feat: add 10 new trading pairs WIF/TON/OP/ARB/JUP/PEPE/TIA/RENDER/FET/STX (#145–#154); backtest 55% win; WIF+OP buy_min_score→7, TIA→8; 174 tests |
| session_2026_04_11g | Chore: add-pair skill updated — step 5(i) trailing_stop tier table, step 5(j) correlation_clusters review; closes #162 |
| session_2026_04_11h | Chore: add scripts/reset_paper.py — reset paper_trading.db + audit.db paper rows to clean $1,000 slate; closes #163 |
| session_2026_04_11i | Fix: position gate uses remaining cash — max_open_positions count cap now only fires when count≥max AND deployable<min_order_usd; max_per_trade uses cash_usd not total_usd (#165) |
| session_2026_04_11j | Fix: cash guards as primary gate — min cash reserve + deployable check run before count ceiling; max_open_positions raised 5→10 (safety ceiling only); sanity warning uses max_position_pct (#167) |
| session_2026_04_11k | Chore: commit skill updated — always create feature/defect branch, push branch, raise PR to main (#168) |
| session_2026_04_11l | Fix: DB-persisted start-of-day balance prevents false daily loss notification (#170); reset_paper.py running-agent guard (#171) |
| session_2026_04_11m | Chore: switch LLM to Groq qwen3-32b / llama-3.3-70b fallback (#173); commit backtest_status.sh chart flags (retro #101) |
| session_2026_04_11n | Chore: clarify reset_paper.py output — rename 'Current state' label to 'State before reset' (#175) |
| session_2026_04_11o | Fix: qwen3-32b thinking mode safeguards — disable_thinking config flag (Option A) + strip `<think>` from raw_output (Option B); 7 new tests (#177) |
| session_2026_04_11p | Fix: SOD balance DB-persisted in live mode — `agent_state` added to LIVE_SCHEMA + PAPER_SCHEMA; `_get_or_set_sod_balance` generalised to paper+live; midnight rollover works in live mode; 9 new tests (#178) |
| session_2026_04_11q | Fix: per-pair `obv_noise_threshold` — meme/volatile pairs (DOGE/WIF/PEPE/HYPE/JUP) set to 2% so only meaningful OBV moves count; large caps 0.2%; mid-tier 0.5%; 3 new tests; 202 total (#185) |
| session_2026_04_11r | Feat: candlestick pattern signals — hammer +1, bullish engulfing +2, doji at BB lower +1; max_score 25→28; 7 new tests; 209 total (#184) |
| session_2026_04_11s | Feat: add PENDLE/USD (TP 20%, buy_min_score=7), ONDO/USD (TP 16%, buy_min_score=6), BONK/USD (TP 25%, buy_min_score=9); TP whitelist extended to include 25%; 27 active pairs (#186–#188) |
| session_2026_04_11t | Feat: drawdown recovery mode — restrict to major pairs + half size when daily loss ≥ -3%; hysteresis exit at -1.5%; Telegram alerts; 7 tests; 216 total (#182) |
| session_2026_04_11u | Feat: profit factor auto-escalation — raise buy_min_score +1 (PF<1.0) or +2 (PF<0.7) for underperforming pairs; injected per cycle from 30-day trade history; PF table in CLI report; 10 tests; 219 total (#183) |
| session_2026_04_11v | Fix: backtest loader bare-list JSON format for BONK/PENDLE/ONDO candle files; closes #198 |
| session_2026_04_11w | Feat: tiered per-pair slippage in paper broker — Tier 1/2/3/4 → 0.05%/0.10%/0.20%/0.40%; `pair_tier` added to all 27 pairs; `_get_pair_slippage()` helper; 9 new tests (12 total); closes #204 |
| session_2026_04_11x | Docs: update `add-pair` and `trading-rules` skills for `slippage_pct` onboarding (#204) and BTC dominance macro overlay guidance (#206); closes #212 |
| session_2026_04_11y | Feat: BTC dominance trend as macro regime input — CoinGecko fetch + cache + DB trend lookback; injected into regime summary and AI context; 15 tests; closes #206 |
| session_2026_04_11z | Chore: merge `origin/main` into `feature/206`; resolve PR #210 conflicts in `config.yaml`, `CLAUDE.md`, `CHANGELOG.md`, and same-day session-note collision (`x` → `y`) |
| session_2026_04_11aa | Feat: sector rotation tier caps — Tier 3=0.5x, Tier 4=0.3x, non-core Tier 2=0.7x when bearish + rising BTC dominance; prompt shows pair tier; propose_buy now enforces pair_max_usd; 4 new tests; closes #203 |
| session_2026_04_11ab | Chore: merge `origin/main` into `feature/203`; resolve PR #214 conflicts by preserving existing X/Y/Z docs history and moving the #203 note to Part AA |
| session_2026_04_11ac | Feat: on-chain cycle-top guard via CoinGlass MVRV Z-Score + NUPL — block Tier 3/4 buys at macro peak, add prompt warning and Telegram alerts; 7 new tests; closes #205 |
| session_2026_04_12a | Analysis: H4 gate hypothesis disproven — confirmed_down win rate 43.9% vs 41.4% overall; analyse_h4_gate.py committed (vectorised, ~6min for 16-month window); closes #180 |
| session_2026_04_12b | Fix: cycle prompt token reduction (HOLD pairs filtered, BB/ATR/redundant blocks removed, ~1,015 tokens saved, refs #217); feat: structured LLM JSON logging /logs/agent-llm-prompts.log + session_id/request_id tracing + kryptos-cli.log CLI audit, closes #219; fix: duplicate log lines (root handler accumulation); fix: CoinGlass 1h failure back-off; fix: @timed("config") noise on compute_indicators |
| session_2026_04_12c | Fix: qwen3-32b tool_use_failed — apply `reasoning_effort: none` via Groq API (correct Groq parameter, replaces Anthropic-style `thinking` which was reverted in #216); 8 tests; closes #223 |
| session_2026_04_12d | Fix: duplicate log lines — `console_handler` skipped when `sys.stdout` is not a TTY (background subprocess has stdout redirected to `agent.log`); closes #226 |
| session_2026_04_12e | Fix: qwen3-32b tool_use_failed — add `reasoning_format=hidden` to `extra_body` for tool calling (Groq requires explicit non-raw format); closes #228 |
| session_2026_04_13a | Fix: test_circuit_breaker + test_correlation_guard hardcoded production `paper_trading.db` — `_seed_positions()` DELETE wiped live positions mid-cycle, triggering false -60% kill switch; UUID DB isolation applied; closes #234 |
| session_2026_04_13b | Docs: comprehensive README rewrite (19 sections, 1,474 lines, 68K) — BUY/SELL complete reference, 4 Mermaid sequence diagrams, defence mechanisms; new SETUP.md (10-section install guide) + setup.sh (automated setup script); closes #240 |
| session_2026_04_17a | Fix: display.py PF tuple crash (#252); CI simplified — remove copilot-review gate, tests run unconditionally (#181); README Telegram Setup + Market Sentiment walkthrough sections (#253); UI design docs committed: docs/ui-designer.md + docs/user-interface/ (#251) |
| session_2026_04_17b | Fix: volume dead-zone guard uses partial in-progress candle instead of last completed candle — dynamic `_vol_idx` via candle_interval config + timestamp comparison; closes #262 |
| session_2026_04_17c | Fix: null macro data causes LLM to over-hold — stale carry-forward for Fear & Greed (4h) + BTC dominance (24h); cold-cache prompt says "treat as neutral"; prompt rule 6 for null-macro; 11 tests; closes #259 |
| session_2026_04_17d | Chore: raise max_position_pct 20% → 30%; drawdown recovery override 10% → 15%; prompt label updated; closes #265 |
| session_2026_04_18e | Feat: heartbeat open-position detail (pair, unrealised P&L, SL/TP dist) + missed-signal Telegram alert for score≥8 BUY rejections; `set_signal_scores()` in tools + trading_agent; `send_missed_signal()` in notifier; closes #268 |
| session_2026_04_18f | Fix: concurrent HTTP fetches — `fetch_fear_greed`/`fetch_btc_dominance`/`fetch_cycle_top_indicators` moved to `asyncio.gather(asyncio.to_thread(...))` to prevent event loop stall on cache expiry; Feat: add MOVR/USD (Moonriver, TP 20%, buy_min_score=6, caution=0.40, trailing 6%/4%); 28 active pairs; closes #274 |
| session_2026_04_19a | Docs: v3 agentic architecture design — BRD v3.0, Architecture-Design-v3, System-Interface-Changes-v3, Traceability-Matrix-v3 (75 FRs), User-Stories-Sprint-Plan-v3 (62 stories, 11 sprints); root-cause problem statement; 6 new specialist skill files; 62 GitHub issues #279–#340 created (labels + milestones); utility scripts |
| session_2026_04_19b | Chore: story signoff workflow added to all 6 squad skill files — Tester executes Test Scenarios → walks results with PO → PO signs off → SA signs off (if technically impactful); mandatory before issue close; `## Handoff on Completion` section added to all developer skills |
| session_2026_04_19c | Feat: Sprint S1 E12 persona infrastructure — S12.1.1 personas config block + validate_config (#279); S12.1.2 CycleContext dataclass + apply_persona_config() runtime injection (#280); S12.1.3 resolve_trading_db() concurrent-mode DB naming + persona column in trades + notifier prefix (#281); ADR-008/ADR-009 in arch doc; 370 tests |
| session_2026_04_19d | Feat: Sprint S2 QSA data resilience — S13.1.1 Winsorized EMA-14 volume floor; S13.1.2 config-driven algorithm with ValueError guard; S13.2.1 OHLCV variance heartbeat (feed_status FROZEN → force HOLD in signals.py); 15 new tests; 385 total |
| session_2026_04_19e | Feat: Sprint S3 — S13.2.2 feed-frozen Telegram alert; S13.2.3 BTC spot failover; S13.3.1 vol bypass (momentum breakout, medium/high persona only); S14.1.1 pipe-format signal blocks; S14.1.2 token budget trimming; S14.2.1 CURRENT PORTFOLIO block; S14.2.2 RISK CONSTRAINTS block; S20.2.1 AIClient + ModelConfig in mocha-python-ai; S21.1.1 DataCollector standalone runtime + COLLECTOR_SCHEMA; 63 new tests; 448 kryptos + 11 mocha |
| session_2026_04_20a | Fix: tz_mod stubs missing `to_sgt` caused full-suite `ImportError` pollution (4 test files patched); fix: `import os` missing in `commands.py`; fix: NL `persona_set` keyword extended to include `"aggressive/conservative/medium mode"`; Feat: Sprint S6 — S17.1.1 MCP HTTP server (6 read-only tools, `src/mcp/server.py`), S18.1.1 persona CLI + `cmd_persona_set`, S18.1.2 regime CLI (`cmd_regime`), S18.1.3 Java API `GET/PUT/DELETE /api/v2/persona` + `PersonaController/Service/Dtos`; AC3 `active_persona_override` checked each cycle in `main.py`; `get_connection_ro()` added to `database.py`; 22 new Python tests + 9 Java tests; 574 Python + 116 Java passing; closes #303 #304 #305 #306 |
| session_2026_04_21a | Chore: Sprint S6-S8 AC gap fixes — S17.1.1 AC5 MCP `--mode` CLI entrypoint + AC7 README section; S18.1.3 AC6 Swagger/OpenAPI on PersonaController (springdoc 2.5.0); S18.1.4 AC4 feed-frozen pairs surfaced end-to-end (main.py → AgentStatusDto → AgentService → types.ts → AgentStatusPanel); S19.1.1 AC2/AC4 `--all-personas` + `--csv` + `--output` flags in test_backtest.py; S19.1.2 AC1/AC2 `TestConservativeVsV2Baseline` (4 tests) in test_persona_regression.py; 39 tests pass; closes #303 #306 #307 #308 #309 |
| session_2026_04_21b | Feat: Sprint S11 E24 Java API — TradesV2 (detail+explain), Agents, Signals, Universe, Feedback (raa+agents), HITL (proposals+approve/reject); 6 new modules + DTOs; 167 Java tests pass; fix: IFeedbackService interface extraction (Byte Buddy / Java 25 mockability); fix: mock-maker-inline for record mocking; fix: FeedbackService.java complete rewrite (was corrupted); fix: @MockBean FeedbackService in AuthControllerTest; closes #334 #335 #336 #337 #338 #339 #340 |
| session_2026_04_21c | Feat: Sprint S9/S10 E22/E23 — RAA ResearchAnalyst (trend persistence, universe proposal, guardrails, persona gates); AuditAgent (outcome tracking, HITL lock, pump detection, ShieldA confidence reset); feedback driver multipliers; orchestrator playbook bias; 8 new DB tables; `self._config` fix in RiskManager; strict alpha spread gate; 73 new tests; 671 total; closes #321 #322 #323 #324 #325 #326 #327 #328 #329 #330 #331 #332 #333 |
| session_2026_04_18d | Fix: `send_daily_summary()` never called — `_get_or_set_sod_balance()` returns `(float, bool)` tuple; `is_new_day=True` triggers `get_performance_metrics` + daily summary Telegram at midnight rollover; wins/losses split in message; closes #249 |
| session_2026_04_18c | Fix: html.escape all dynamic fields in `notifier.py` — exception messages with `<`/`>` broke Telegram HTML parser; `import html` added; `component`, `error`, `reason` escaped; manual `&amp;` replaced; closes #247 |
| session_2026_04_18b | Fix: missing pnl_pct in Telegram trade close message — `send_trade_executed()` now shows `(+8.12%)` alongside USD P&L; closes #248 |
| session_2026_05_03a | Feat: RAA LLM-delegated universe decisions — `propose_universe_addition()` replaced by `_run_llm_universe_decision()` + `_RAA_MCP_TOOLS` (kraken_ticker/get_universe/get_trend_persistence/get_confidence_state/universe_decision); meme-block + HITL lock remain hard Python guards; full HTTP + LLM call logging on every outbound request; closes #354 |
| session_2026_05_03b | Feat: RAA batch LLM evaluation — all candidates in one call (#357); `_run_llm_universe_decision` replaced by `_run_llm_batch_universe_decision` + `_apply_llm_decision`; `_RAA_BATCH_TOOLS` (decision only); pre-injected ticker/persistence data; `write_raa_cycle_report` in cycle_logger.py; RAA logging infrastructure wired (llm_logger, cycle_logger, agent.log RotatingFileHandler) |

---

## Known Behaviours / Gotchas

- **RAA batch LLM evaluation (#357)**: All candidate pairs are evaluated in a **single** LLM conversation via `_run_llm_batch_universe_decision()`. Ticker and persistence data are pre-injected into the user message — the LLM uses only `universe_decision` tool (`_RAA_BATCH_TOOLS`), no data-fetching tools. This eliminates rate-limit-triggering round trips. The LLM calls `universe_decision` once per candidate; the tool loop collects all calls until all candidates are decided or `max_rounds` is reached. `_apply_llm_decision()` applies each individual decision (enforces HITL lock + meme-block hard guards, commits to DB). Any candidate the LLM skips gets a synthetic HOLD + `LLM_NO_DECISION` audit row. `RiskManager.validate_universe_proposal()` is unused by RAA but kept intact.
- **RAA HTTP + LLM call logging**: Every outbound HTTP request logs `[RAA] HTTP GET <url>` before and `[RAA] HTTP <status> <url> (<ms>ms)` after. Every LLM call logs `[RAA] LLM call|<tool>|...|prompt_chars=N` before and `[RAA] LLM response|<tool>|tool_calls=...` after. All goes to standard Python logger (→ `agent.log` when running alongside main agent).
- **Test DB isolation (critical)**: All test files MUST use a UUID-based temp DB name — `DB_PATH = f"test_paper_{uuid.uuid4().hex[:8]}.db"` — instead of hardcoding `"paper_trading.db"`. The `get_connection()` helper resolves any bare filename to `data/<filename>`, so `"paper_trading.db"` silently points at the production paper trading database. Running `test_correlation_guard.py` with a hardcoded `"paper_trading.db"` caused `_seed_positions()` to `DELETE FROM paper_positions WHERE pair LIKE '%/USD'`, wiping 6 live positions and triggering a false -60% kill switch (#234). Pattern established in `test_sod_balance.py`; enforced in all new test files.
- **LLM prompt only contains BUY + SELL pairs**: HOLD-signal pairs are never sent to the LLM — they are implicitly held by `_run_cycle_decision`'s post-loop. This saves ~540 tokens per cycle. The `build_cycle_prompt()` `signals` parameter still receives all 27 pairs for counting; only the per-pair blocks are filtered to `actionable = BUY + SELL`.
- **LLM interaction log**: Every cycle's full LLM request/response is written as a JSON record to `/logs/agent-llm-prompts.log` (100 MB × 5 files). Fields: request_id, session_id, timestamp, model, system_prompt, user_message, raw_output, tool_calls, prompt_tokens, completion_tokens, estimated_cost_usd, latency_ms. `time_to_first_token_ms` and `tool_call_latency_ms` are always null (sync SDK / local tools). Pricing table in `src/utils/llm_logger.py` — update when model pricing changes.
- **session_id / request_id tracing**: `session_id` (UUID4) is generated once at agent startup in `main.py` and appears as `[S:xxxxxxxx]` on every `agent.log` line. `request_id` (UUID4) is generated per LLM call in `trading_agent.py` and set via ContextVar for the duration of that call. Both are included in `agent-llm-prompts.log` JSON records.
- **log_dir is config-driven**: `storage.log_dir` in `config.yaml` controls where `agent.log`, `agent-llm-prompts.log`, and `kryptos-cli.log` are written (default `/logs`). Directory is auto-created at startup.
- **CLI audit log**: Every `kryptos.py` command (REPL input, single command, direct subcommand) is appended to `/logs/kryptos-cli.log` as `timestamp | 'command' | intent=X | source=Y`. Rotation: 100 MB × 5 files.
- **CoinGlass failure back-off**: When the CoinGlass API returns a 5xx error, `fetch_cycle_top_indicators` records `failed_at` in `_cycle_top_cache` and silently returns `None` for the next 1 hour without retrying or logging. After 1 hour, one retry is made.
- **Volume dead-zone guard uses last completed candle (#262)**: `compute_indicators()` now uses a dynamic `_vol_idx` (`-1` or `-2`) to select the volume candle. The WebSocket feed mutates `candles[-1]` in-place while it is open, so comparing its partial volume against `rolling_volume_p15` (computed from 400 completed candles) caused systematic false blocks. Fix: `_candle_interval_secs = config["trading"]["candle_interval"] * 60`; if `candles[-1]["timestamp"] + interval ≤ time.time()` use `iloc[-1]` (closed), else `iloc[-2]` (last completed). Only `volume` and `volume_sma_20` use `_vol_idx`; all other indicators remain on `iloc[-1]`.
- **Realized P&L at TP is slightly below configured %**: full round-trip friction = entry slippage (0.05%) + entry fee (0.26%) + exit slippage (0.05%) + exit fee (0.26%) ≈ 0.62% per trade. This is intentional simulation of real Kraken maker-fee trading costs (#140).
- **`usd_value` ≠ cash deducted**: `usd_value` in DB = entry cost only; actual cash deducted = entry cost + entry fee. The fee is shown in Telegram notifications but not in `paper_positions.usd_value`.
- **`agent_sell` vs `take_profit`**: `exit_reason` in DB distinguishes LLM-initiated sells from automatic TP hits. If you see small-gain exits, check if `exit_reason = agent_sell` — means the LLM sold early.
- **Cycle interval**: 30 minutes. SL/TP checks happen every cycle start, not on every price tick. Price can blow past SL between cycles without firing.
- **caution_factor is now per-pair (#124)**: In bearish regime, `main.py` injects `sig["pair_max_usd"]` per signal using `pair_cfg.get("caution_factor_bearish", global_caution)`. Winners (ETH/BNB/DOGE) = 1.0 (buy the dip, full size). Underperformers (INJ/SUI) = 0.35. RAILS = 0.25 (#131, was 0.40 — 3/4 stop losses in production). HYPE = 0.40. Global fallback (`bearish_caution_factor: 0.5`) applies for pairs without an explicit override. The LLM sees per-pair "Max buy size" in the prompt. Volatile regime still applies global caution uniformly.
- **Dynamic TP is now order-level**: `TradingTools.propose_buy()` uses ATR/BB-adjusted TP from `ai_context["dynamic_tp_values"]` instead of static config. Falls back to static if `dynamic_tp.enabled: false` or pair not in values. Logged as `[DYNAMIC_TP]`.
- **Reasoning model `<think>` blocks**: some models (e.g. DeepSeek-R1, QwQ, qwen3) emit chain-of-thought `<think>…</think>` before their response. Ollama strips these before populating `msg.tool_calls`, so tool dispatch is unaffected. For Groq's OpenAI-compat API (qwen3-32b), thinking mode is disabled via `llm.disable_thinking: true` which passes `extra_body={"reasoning_effort": "none", "reasoning_format": "hidden"}` — `reasoning_effort: none` disables thinking tokens (#223); `reasoning_format: hidden` is required because Groq returns 400 when tool calling is enabled with the default `raw` format (#228). Only applies to models whose name contains `qwen3`; the llama fallback is unaffected. Note: Anthropic-style `extra_body={"thinking": {"type": "disabled"}}` was tried in #177 and reverted in #216 as Groq returned 400 for all models. As defence-in-depth, `_call_openai_compat` always strips `<think>` blocks from `raw_output` via `re.sub`. Without these guards, thinking content causes `tool_use_failed` with empty `failed_generation` → agent falls back to llama every cycle.
- **Live broker parity**: `KrakenClient` now has the same interface as `PaperBroker` — `get_balance()`, `get_open_positions()`, `close_position()`, `check_stops_and_tp()` all implemented. Positions are tracked in `live_trading.db` (same SQLite pattern as paper mode).
- **Minimum Profit Floor**: The agent is blocked by `validate_sell` from closing a trade manually if the PNL is below `min_profit_floor_pct` (1.0%), guarding against net losses from Kraken exit fees.
- **Signal scoring is confluence-based**: No single indicator triggers a BUY. Score must reach `buy_min_score` (5) from up to 10 contributors. The two hard vetoes are RSI ≥ 70 and ATR-based TP < profit floor. See `signals.py` for full weight table.
- **MACD histogram turn vs positive**: `indicators.py` returns both `macd_histogram` (current) and `macd_histogram_prev` (previous candle). A turn from negative to positive scores +3; merely being positive scores +1.
- **Fear & Greed injected into signals**: `main.py` fetches Fear & Greed once per cycle and injects it as `fear_greed_index` into each pair's indicators dict before `generate_signal()` runs. Scores +1 (fear ≤ 40) or +2 (extreme fear ≤ 25).
- **Circuit breaker reads trade history**: `RiskManager.is_circuit_open()` uses a graduated backoff (#143): fires are counted in `tier_reset_hours` (24h) via `_count_circuit_fires_in_window()`. Pause = `pause_tiers_hours[fires-1]` clamped to max tier (1h → 2h → 4h). No new DB tables — derived from trade history. Backward compat: if `pause_hours` present without `pause_tiers_hours`, uses flat override.
- **Heartbeat (live mode only)**: Every 60 minutes, `notifier.send_heartbeat()` sends a Telegram summary: balance, hourly P&L, cycles, buys/sells, circuit breaker state. Skipped in backtest mode.
- **Volatility Windows & Dead Zones**: Time-of-day guard is **disabled** (`allowed_trading_hours.enabled: false`) — agent trades at any hour. Volume dead zone check in `signals.py` is always active regardless of `enabled` flag. **`min_volume_ratio` is per-pair**: BNB/UNI/INJ=0.30, TRX/DOGE/ADA/LTC/AVAX=0.40, BTC/ETH/SOL/XRP/SUI=0.50. `end_hour_utc` is exclusive (retained in config for easy re-enable). Backtest also bypasses time guard since `enabled=False`.
- **Per-pair signal thresholds**: As of session_2026_04_09a, `atr_tp_min_pct`, `rsi_oversold`, `rsi_overbought`, `bb_squeeze_threshold_pct`, `min_volume_ratio`, and `adaptive_atr_floor_lookback` are all configurable per pair in `trading.pairs[]`. Global values in `dynamic_tp` and `indicators` sections are fallbacks only. Per-pair values derived from 2025-01-01 rolling-window analysis.
- **ATR floor priority chain**: `indicators["adaptive_atr_floor_pct"]` (injected by main.py, rolling p25 ATR% × 0.8) → `pair_cfg["atr_tp_min_pct"]` → `dynamic_tp.atr_tp_min_pct` (0.30% fallback) → `trading.min_profit_floor_pct`. Adaptive injection enabled by `adaptive_atr_floor.enabled: true`; lookback=**200** candles global (was 400, #141), overrideable per-pair via `adaptive_atr_floor_lookback`.
- **MACD decay threshold is now % of price**: `exit_timing.macd_decay_threshold_pct: -0.005` replaces old absolute `-0.0005`. `check_exit_timing()` computes `macd_hist / price × 100` before comparing. This makes the threshold price-scale agnostic (works for both TRX and BTC).
- **Adaptive BB squeeze and volume floor**: `main.py` also injects `_rolling_bb_p10_pct` (p10 BB width per pair, 400-candle lookback) and `rolling_volume_p15` (p15 raw volume, 400-candle lookback) each cycle. `features.py compute_dynamic_tp()` uses `_rolling_bb_p10_pct` first; `signals.py Hard Blocker 3` uses `rolling_volume_p15` first.
- **Position sizing updated (Fix #130, revised #159, #165, #167, #265)**: `max_open_positions: 10` (was 5 — cash guards are now the primary gate; 10 is a safety ceiling unreachable in normal operation). `max_position_pct: 30%` (was 20%), `max_buys_per_cycle: 7` (was 5), `base_position_pct: 16%` (was 12%), `min_cash_reserve_pct: 5%` (was 10%). `max_per_trade` is computed as `cash_usd × max_position_pct` so the LLM sees the ceiling proportional to remaining cash. Guard order in `validate_buy()`: min cash reserve → deployable < min_order_usd → count ceiling (10) → cluster guard → size checks. The count ceiling only fires when an unusual number of tiny caution-factor positions exhaust all 10 slots before cash is depleted — this is a last-resort safety net, not the routine blocker.
- **Per-pair buy_min_score (#128, updated #131)**: `signals.py` reads `pair_cfg.get("buy_min_score", global_min_score)`. INJ=7, RAILS=7 (3/4 stop-loss rate in production — #131), SOL/UNI=6 (underperformers per 2026-04-09 backtest). ETH/BNB/DOGE=5 (explicit). Global default = 5.
- **Signal driver report**: `python kryptos.py drivers [--days 30] [--top 10]` shows top blocking reasons per pair and globally. Backed by `get_signal_driver_report()` in `trade_report.py` and `print_signal_driver_report()` in `display.py`.
- **Parameter calibration utility**: `scripts/calibrate_params.py --start-date 2025-01-01 --output rec.yaml` analyses historical candles and outputs recommended config YAML changes for all 5 per-pair signal parameters.
- **`trailing_stop` exit reason (#125)**: Exit Reasons panel in `kryptos.py report` now shows both count and total P&L per exit reason (green/red). `trailing_stop` is a distinct reason from `stop_loss` — these are profitable exits where the trailing SL had been raised above entry and then hit. `backtest_end` is used for positions force-closed at the final candle (mark-to-market).
- **Minimum order floor is $20 (#126)**: `risk.min_order_usd` raised from $5 to $20. Guard 0.5 in `validate_buy()` fires first (before Guard 1) when deployable cash < `min_order_usd`, logging `[RISK] Skipping BUY {pair} — deployable cash $X below min_order_usd $Y`. Hardcoded `capped < 5.0` replaced by `capped < self._min_order_usd`.
- **Backtest mark-to-market close (#127)**: After `asyncio.run(run_agent(...))`, `tests/test_backtest.py` calls `PaperBroker.force_close_all(last_prices)` to close all remaining open positions with `exit_reason='backtest_end'` at the last candle price. The summary prints forced-close count and total P&L.
- **Overdraw guard (#129)**: `PaperBroker.place_order()` now raises `ValueError("Insufficient funds: need $X, have $Y")` if `new_cash < 0` after deducting `actual_cost + fee_usd`. Logged at ERROR level with `[PAPER] OVERDRAW BLOCKED`. This is independent of `validate_buy()`'s pre-check and closes the TOCTOU gap.
- **Partial Take-Profit**: Enabled (#142). Fires once per position (guarded by `partial_exited` DB column). Closes `close_fraction` (50%) of volume at `trigger_pct_of_tp`% (50%) of the way to full TP. Remaining half continues with original SL/TP. If `move_sl_to_breakeven: true`, SL is moved to entry after partial close. `close_position(volume_override=...)` handles partial math; P&L is proportional to the fraction closed.
- **Stop-Loss execution order** in `check_stops_and_tp()`: (1) update highest_price_seen, (2a) trailing SL raise OR (2b) breakeven SL OR none, (3) partial TP check, (4) full SL/TP check. Trailing and breakeven are mutually exclusive (ConfigError if both enabled).
- **`trailing_stop` vs `stop_loss` exit labels**: When trailing stop is enabled and `stop_loss_price` has been raised above the original hard floor (`entry_price × (1 - sl_pct/100)`), a SL hit is labelled `trailing_stop` not `stop_loss`. Hard floor hits remain `stop_loss`. Circuit breaker only counts `stop_loss` and `fallback_stop_loss` — `trailing_stop` exits (which are often profitable) do not contribute to the consecutive-stop streak.
- **ADX trend filter (#134)**: `compute_indicators()` now returns `adx_14` (ADX period 14 via `ta.trend.ADXIndicator`). `signals.py` applies a soft ±1 BUY score modifier: ADX > 40 → +1 (strong trend); ADX < 20 → −1 (ranging, choppy). Not a hard veto — strong confluence can still fire BUY in a ranging market. `max_score` updated from 16 to 22 to account for all new signals.
- **RSI divergence (#135)**: `compute_indicators()` returns `rsi_series` and `close_series` (last 30 candles as lists). `detect_rsi_divergence(prices, rsi, lookback)` in `indicators.py` uses a split-half swing detection approach. `signals.py` scores: bullish_regular +2 BUY, hidden_bullish +1 BUY, bearish_regular +2 SELL. Per-pair `rsi_divergence_lookback` override: BTC/LTC=25 (slow movers), TRX/DOGE/HYPE=15 (fast/noisy), global default=20.
- **Fast backtest `--no-llm`**: `tests/test_backtest.py --no-llm` replaces the LLM with a deterministic rule engine (Signal=BUY → place_order, Signal=SELL → close_position). Runs in ~30 seconds vs ~2 hours. Use for signal parameter calibration. Full pipeline with LLM is still available without the flag. `tests/test_backtest_fast.py` is the underlying implementation.
- **OBV trend signal (#136)**: `indicators.py` returns `obv_series` (last 30 values). `signals.py` calls `_compute_obv_trend(obv_series, period, noise_threshold)` — compares OBV[now] vs OBV[now-period] with a configurable noise floor. OBV rising → +1 BUY. OBV falling → distribution warning in reasons (no penalty). Per-pair `obv_trend_period` override in `trading.pairs[]`; global default `indicators.obv_trend_period: 10`. Estimation: BTC/LTC=14, mid-tier=10, meme=7. **Per-pair `obv_noise_threshold` (#185):** meme/volatile pairs (DOGE/WIF/PEPE/HYPE/JUP) use 0.020 (2%) so only genuine accumulation moves credit the +1 vote; large caps (BTC/ETH/BNB/SOL) use 0.002 (0.2%); mid-tier 0.005 (0.5%); INJ/TIA 0.010 (1.0%). Global fallback `indicators.obv_noise_threshold: 0.001`.
- **BB squeeze release (#137)**: `indicators.py` returns `bb_width_series` (last 10 values, % of price). `detect_bb_squeeze_release()` in `indicators.py` checks: (1) prior `lookback` candles in squeeze (width < per-pair `bb_squeeze_threshold_pct`), (2) current width > threshold × `bb_squeeze_release_expansion_factor` (1.2), (3) price > `bb_mid` (upward only). Awards +2 BUY. Downward breakouts explicitly rejected. Config: `bb_squeeze_release_weight: 2`, `bb_squeeze_release_lookback: 3`, `bb_squeeze_release_expansion_factor: 1.2`.
- **Candlestick patterns (#184)**: `detect_candlestick_patterns(opens, highs, lows, closes, atr)` in `indicators.py` returns `{"hammer", "bullish_engulfing", "doji_at_support"}`. Hammer = lower_wick > 2×body AND upper_wick < 0.3×body AND bullish close. Bullish engulfing = current body engulfs prior bearish body. Doji = body < 10% of ATR (scale-agnostic). Scores: hammer +1, engulfing +2. Doji scores +1 only when `near_lower` is also True in `signals.py` (price ≤ bb_lower × 1.005). All are additive bonuses — never standalone signals. Config: `hammer_weight`, `engulfing_weight`, `doji_support_weight`. `max_score` is now 28.
- **DB-persisted start-of-day balance (#170, #178)**: `main.py` no longer captures `start_of_day_bal` once at startup. `_get_or_set_sod_balance(db_path, current_balance)` is called at the start of each main loop iteration for **both paper and live mode** (skipped only in backtest). It reads the `agent_state` key `start_of_day_balance_YYYY-MM-DD` (UTC) from the appropriate DB (`paper_trading.db` or `live_trading.db`). If absent (new UTC day or `agent_state` was cleared by `reset_paper.py`), it writes `current_balance` and uses it. This prevents the false 40%+ daily loss notification that fires when `reset_paper.py` runs while the agent is alive, and also handles midnight rollovers automatically in both modes. The `agent_state` table is now codified in both `PAPER_SCHEMA` and `LIVE_SCHEMA` (previously it existed in production paper DB from an ad-hoc migration but was not in the schema DDL).
- **`reset_paper.py` running-agent guard (#171)**: `reset_paper.py` now checks if `paper_trading.db` was modified within the last 120 seconds before performing the reset. If so (agent likely running), it prints a warning and exits unless `--force` is passed. Use `python scripts/reset_paper.py --yes --force` to bypass if you are certain the agent is stopped.
- **Drawdown recovery mode (#182)**: When `daily_pnl_pct ≤ -3%`, the agent enters recovery mode — only `BTC/USD`, `ETH/USD`, `BNB/USD` are allowed for new buys, and position size is capped at `available_cash × 10%` (instead of normal 20%). Exit hysteresis: recovery mode stays active until daily pnl > -1.5%, preventing oscillation in the -3% to -1.5% band. State is tracked in `loop_state["drawdown_recovery_active"]` in `main.py`. Telegram alerts sent on entry (⚠️) and exit (✅). Config: `risk.drawdown_recovery.{enabled, trigger_pct, exit_pct, allowed_pairs, max_position_pct_override}`.
- **Profit factor auto-escalation (#183)**: Every cycle, `main.py` queries the last 30-day closed trades per pair and injects `indicators["profit_factor"]` before `generate_signal()` runs. `signals.py` reads this: PF < `pf_severe_threshold` (0.7) → `buy_min_score += 2`; PF < `pf_warn_threshold` (1.0) → `buy_min_score += 1`. No change when PF ≥ 1.0 or fewer than `min_trades` (10) records exist. The reason string is appended to `signal["reasons"]`. `kryptos report` now includes a profit factor table showing per-pair PF, n_trades, and status (colour-coded). Config: `signals.profit_factor_escalation.{enabled, lookback_days, min_trades, pf_warn_threshold, pf_severe_threshold}`.
- **Cycle-top guard (#205)**: `main.py` now fetches BTC `MVRV Z-Score` and `NUPL` from CoinGlass once per cycle via `fetch_cycle_top_indicators(config, db_path=...)`, with a 24-hour cache persisted in `agent_state`. When both thresholds are breached (`mvrv_z_danger` and `nupl_danger`), the prompt shows a `[CYCLE TOP WARNING]` block, Tier 3 / Tier 4 raw BUY signals are downgraded to HOLD before the LLM acts, and `RiskManager.validate_buy()` hard-blocks those pairs even if proposed. `Notifier` emits Telegram alerts on guard activation/deactivation.
- **Sector rotation tier caps (#203)**: `pair_tier` is now used at runtime, not only stored in config. In `main.py`, bearish regime sizing still starts from `caution_factor_bearish`, but when `btc_dominance_trend == rising`, additional caps apply: Tier 3 speculative alts use `tier3_dominance_rising_multiplier` (default `0.5`), Tier 4 meme pairs use `tier4_dominance_rising_multiplier` (default `0.3`), and non-core Tier 2 alts may use `btc_dominance_rising_caution_multiplier` (default `0.7`). The per-pair signal block shows the tier, and `TradingTools.propose_buy()` now enforces `pair_max_usd` before calling the risk manager so the regime cap is not prompt-only.
- **BTC dominance trend context (#206)**: `main.py` fetches BTC dominance once per cycle via `fetch_btc_dominance(config, db_path=_trading_db)` (CoinGecko `/api/v3/global`, cached in-memory). Daily values are persisted in `agent_state` with key `btc_dom_YYYY-MM-DD`; trend is computed versus `trend_lookback_days` ago and classified as `rising/falling/flat` using `trend_min_change_pp`. `detect_market_regime()` appends dominance interpretation to summary and returns `btc_dominance_trend` + `btc_dominance_pct`; `build_ai_context()` forwards both values into prompt context.
- **Per-pair tiered slippage (#204)**: `PaperBroker._get_pair_slippage(pair)` looks up `trading.pairs[].slippage_pct` and converts to fraction; falls back to `self._slippage` (global 0.05%). Applied on both entry (`place_order`) and exit (`close_position`). Tiers: Tier 1 BTC=0.05%, Tier 2 L1s=0.05–0.10%, Tier 3 alts=0.20%, Tier 4 memes=0.40%. The `pair_tier` field also added to all pairs in config (serves #203 sector rotation). Round-trip friction for BONK/WIF (0.8%) is 8× that of BTC (0.1%).
- **Persona infrastructure (#279–#281)**: The agent supports three risk personas — `conservative`, `medium`, `high` — each defined in `config.yaml → personas:`. `config["agent"]["persona"]` sets the active profile; `config["agent"]["concurrent_mode"]` enables isolated DB naming. `CycleContext.from_config(config, cycle_id)` in `src/core/cycle_context.py` resolves the active persona each cycle and exposes 8 convenience properties. `RiskManager.apply_persona_config(persona_config)` hot-patches `_max_open_positions`, `_max_position_pct`, and `_min_profit_floor_pct` at cycle start. **Concurrent mode DB naming**: `resolve_trading_db(config, mode)` returns `paper_trading_conservative.db` when `concurrent_mode: true`, `paper_trading.db` otherwise — prevents multi-instance DB collisions. **Notifier prefix**: `[PAPER|CONSERVATIVE] ` in concurrent mode, `[PAPER] ` in normal mode. **Trade attribution**: `persona TEXT NOT NULL DEFAULT ''` column in both `paper_trades` and `live_trades` — every closed trade is stamped with the active persona at time of close. **agent_state write**: `run_cycle()` writes `active_persona` key to `agent_state` table each cycle so in-flight persona is queryable. `validate_config()` enforces all 13 persona keys are present across all 3 profiles — missing key raises `ConfigError`.
- **Persona CLI + active_persona_override (S18.1.1–S18.1.3)**: `kryptos persona` and `kryptos persona set <name>` CLI commands display/change the active persona. `cmd_persona_set()` writes `agent.persona` to `config.yaml` via `yaml.dump`; requires `import os` (added). The Java API `PUT /api/v2/persona` writes key `active_persona_override` to `agent_state`; `main.py` reads this at the start of each cycle and temporarily patches `config["agent"]["persona"]` for that cycle only (no file write). `DELETE /api/v2/persona/override` clears the key. This allows the dashboard to override persona on-the-fly without restarting the agent. Invalid persona values return 400 from both the CLI and the Java endpoint.
- **MCP HTTP server (S17.1.1)**: `src/mcp/server.py` — `MCPServer(config, db_path)` starts an `aiohttp` server on `127.0.0.1:8092`. Six read-only tools: `get_portfolio_state`, `get_signal_snapshot`, `get_regime_state`, `get_agent_status`, `get_universe_state`, `get_persistence_scores`. All tool responses are pipe-separated strings. All DB access uses `get_connection_ro()` (URI mode, no write capability). `aiohttp` import is guarded by `_AIOHTTP_AVAILABLE` flag so the agent starts cleanly even if `aiohttp` is absent. The server persists 5 `agent_state` keys each cycle: `current_regime`, `adx_median_last`, `daily_pnl_pct_last`, `btc_dom_trend_current`, `last_cycle_ts`.
- **`get_connection_ro()` in database.py**: Reads the DB via SQLite URI `file:...?mode=ro`. If the DB file does not exist yet (e.g. test environment before first cycle), falls back to an in-memory connection so callers don't crash on startup. Caller must check data existence in application logic.
- **tz_mod stubs missing `to_sgt` (test pollution gotcha)**: `test_coinglass_v4.py`, `test_stale_macro.py`, `test_cycle_top_guard.py`, and `test_btc_dominance.py` inject a stub `src.utils.tz` at module level. The stub must include `to_sgt = lambda dt: dt` or any subsequent import of `display.py` will fail with `ImportError: cannot import name 'to_sgt'`. Always add `to_sgt` when extending these stubs.
- **QSA Winsorized EMA volume floor (S13.1.1–S13.1.2)**: `compute_indicators()` now returns `winsorized_vol_ema` (float or None). When `qsa.volume_floor.algorithm = winsorized_ema`, the last `winsorize_lookback` (100) candles' volume is p95-capped (spike-resistant winsorization), then an EWM with α = 2/(period+1) is applied. This replaces the noisy rolling-p15 floor as the highest-priority volume veto in Hard Blocker 3 of `signals.py`. When `algorithm = sma`, `winsorized_vol_ema = None` and the legacy `volume_sma_20` path is used (backward-compat). Invalid `algorithm` values raise `ValueError` immediately. Config: `qsa.volume_floor.{algorithm, period, winsorize_percentile, winsorize_lookback}`.
- **QSA feed heartbeat (S13.2.1)**: `compute_indicators()` also returns `feed_status` ("OK" | "FROZEN"). Enabled by `qsa.feed_heartbeat.enabled: true`. Checks whether all five OHLCV columns have zero variance (`ddof=0`) across the last `variance_lookback` (3) candles. If yes → `"FROZEN"`. `generate_signal()` in `signals.py` reads this value first; when FROZEN it immediately returns `HOLD` with `reason="feed_frozen"` and `strength=0.0`, skipping all scoring. Config: `qsa.feed_heartbeat.{enabled, variance_lookback, freeze_alert_cycles}`.
- **QSA feed-frozen alert (S13.2.2)**: `Notifier.send_feed_frozen_alert(pair, n_cycles)` sends one Telegram ⚠️ alert when a pair's feed stays FROZEN for ≥ `freeze_alert_cycles` consecutive cycles. `main.py` tracks `_freeze_alert_sent` dict; resets to False on thaw so next freeze triggers a fresh alert.
- **QSA BTC failover (S13.2.3)**: When BTC/USD feed is FROZEN for ≥ `min_freeze_cycles`, `fetch_btc_spot_price(config)` in `features.py` falls back to CoinGecko REST (`/api/v3/simple/price?ids=bitcoin&vs_currencies=usd`). Used by `main.py` for portfolio valuation. Config: `qsa.btc_failover.{enabled, min_freeze_cycles}`.
- **QSA volume bypass (S13.3.1)**: `signals.py` inserts a bypass block between the `vol_blocked` computation and the early-return. Bypass fires when `volume_bypass_enabled AND bb_upper is not None AND price > bb_upper AND macd_hist >= 0 AND macd_hist_prev < 0` (price breaking above upper BB with MACD turning positive). Conservative persona: bypass disabled. Medium/high: enabled. `main.py` injects `volume_bypass_enabled` from the active persona block before calling `generate_signal()`. Bypass appends `"vol_bypass_momentum_geometry"` to signal reasons.
- **Pipe-format signal blocks (S14.1.1)**: `build_pipe_signal_block(signal, pair_tp_config, regime)` in `prompts.py` replaces the old verbose multi-line block. Format: `pair|X|score|N/28|direction|BUY|rsi|N|adx|N|macd_hist|N.NNNN|bb_pos|N.NN|regime|X|price|N.NNNN|tp_pct|N|sl_pct|5|max_buy_usd|N`. Tier label was removed; `max_buy_usd` carries the per-pair cap.
- **Token budget trimming (S14.1.2)**: `estimate_tokens(prompt) -> int` uses `len(prompt) // 4`. `build_cycle_prompt()` trims weakest BUY signals (by `buy_score`) when estimated tokens > `llm.max_prompt_tokens` (default 3500). Trimmed pairs become implicitly HOLD. Logged at INFO.
- **Current portfolio block (S14.2.1)**: `build_cycle_prompt()` always emits `## CURRENT PORTFOLIO ##` with a pipe summary row and one sub-row per open position. `SYSTEM_PROMPT` includes "Do NOT propose_buy for any pair listed in CURRENT PORTFOLIO."
- **Risk constraints block (S14.2.2)**: `build_cycle_prompt()` emits `## RISK CONSTRAINTS ##` pipe row when `risk_state` dict is passed: `cash_usd|X|positions_open|N|positions_max|M|kill_switch|0|circuit_open|0|playbook|standard|persona|Y`.
- **AIClient in mocha-python-ai (S20.2.1)**: `mocha-python-libraries/packages/mocha_python_ai/src/mocha_python_ai/ai_client.py` — `ModelConfig` dataclass (base_url, model, fallback_model, api_key, temperature, max_tokens) + `AIClient` class with `chat_with_tools()`. Retry: 3 attempts; attempt 3 uses `fallback_model`, sets `result["fallback"]=True`. `openai` is lazy-imported inside `_get_openai_client()`. Exported from package `__init__.py`.
- **DataCollector standalone runtime (S21.1.1)**: `src/runtime/data_collector.py` — standalone asyncio process subscribing to Kraken WS v2 ohlc + book. `COLLECTOR_SCHEMA` in `database.py` creates `candle_buffer` (UNIQUE INDEX on `(pair, ts)`) and `orderbook_snapshots` (INDEX on `(pair, ts)`). Backfill via REST on startup (INSERT OR IGNORE preserves newer WS rows). `/health` HTTP endpoint at `qsa.collector_port` (default 9100) via aiohttp. No dependency on `src/agent/` or `src/risk/`. Run: `python -m src.runtime.data_collector --config config.yaml --db paper_trading.db`.
