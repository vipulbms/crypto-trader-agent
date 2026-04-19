#!/usr/bin/env bash
# =============================================================================
# Kryptos — News Intelligence Backlog Issues Creator
# Creates 5 GitHub issues for the CryptoPanic news integration feature.
#
# Usage:    bash scripts/create_github_issues_news.sh
# Requires: gh CLI authenticated — run: gh auth status
# =============================================================================

set -e
REPO="vipulbms/crypto-trader-agent"

echo "==> Checking gh auth..."
gh auth status --hostname github.com 2>&1 | head -3

echo ""
echo "==> Creating label 'news-intelligence' (if not exists)..."
gh label create "news-intelligence" --color "#F9A825" \
  --description "News feed and news-context features" --repo "$REPO" 2>/dev/null || true

echo ""
echo "==> Creating label 'documentation' (if not exists)..."
gh label create "documentation" --color "#0075CA" \
  --description "Docs-only change" --repo "$REPO" 2>/dev/null || true

# ── Issue A: fetch layer ──────────────────────────────────────────────────────
echo ""
echo "==> Issue A: CryptoPanic news fetch layer..."
ISSUE_A_URL=$(gh issue create --repo "$REPO" \
  --label "enhancement,news-intelligence" \
  --title "[Feat] CryptoPanic news fetch layer (features.py)" \
  --body "## Summary
Add a \`fetch_news_for_pairs()\` function that pulls the latest headlines from the CryptoPanic free API for a given list of pairs and caches results in memory.

## Motivation
Enable news context to be injected into the LLM cycle prompt (Issue D) and the \`kryptos news\` CLI command (Issue B) without rebuilding the fetch logic twice.

## Acceptance Criteria
- [ ] \`news:\` config block added to \`config.yaml\` below \`sentiment:\`:
  \`\`\`yaml
  news:
    enabled: true
    api_key: \"your_cryptopanic_api_key_here\"
    url: \"https://cryptopanic.com/api/free/v1/posts/\"
    fetch_timeout_secs: 8
    cache_minutes: 30
    max_headlines: 3
    headline_max_chars: 120
    ticker_overrides: {}
  \`\`\`
- [ ] Module-level \`_news_cache: dict = {}\` added in \`src/analysis/features.py\`
- [ ] \`_format_news_age(published_at: str) -> str\` helper — returns \"30m ago\" / \"4h ago\" / \"3d ago\"
- [ ] \`fetch_news_for_pairs(pairs, config) -> dict[str, list[dict]]\`:
  - Returns \`{}\` immediately if \`news.enabled: false\` or api_key is placeholder/empty
  - One batch HTTP call: \`currencies=BTC,ETH,...\` for all stale pairs
  - Fan-out: each result article tagged to all its \`currencies[].code\` entries
  - Slices to \`max_headlines\`; truncates titles to \`headline_max_chars\`
  - On HTTP failure: logs WARNING, returns cached-only partial result (no raise)
  - 30-min in-memory TTL per pair
- [ ] 6 tests in \`tests/test_news_fetch.py\`:
  - disabled config → returns \`{}\`
  - placeholder api_key → returns \`{}\`
  - successful fetch → correct grouping by pair, max_headlines respected
  - cache hit (second call within TTL) → skips HTTP
  - API failure (exception) → returns \`{}\` gracefully
  - ticker_override applied correctly in currencies param

## Files
- \`config.yaml\`
- \`src/analysis/features.py\`
- \`tests/test_news_fetch.py\`

## Notes
- Follow exact same pattern as \`fetch_fear_greed()\`: module-level cache dict + bare \`except Exception\` → WARNING log → return None/{}
- CryptoPanic free tier: ~100 req/day; 30-min cache keeps usage ≤ 48/day
- \`RENDER\` is the correct post-2023 rebrand (not RNDR); \`ticker_overrides\` config handles any stragglers
- No DB persistence needed — in-memory cache is sufficient for 30-min cycles
- **Prerequisite for Issues B and D**")

ISSUE_A_NUM=$(echo "$ISSUE_A_URL" | grep -o '[0-9]*$')
echo "  Created Issue A: #${ISSUE_A_NUM} — ${ISSUE_A_URL}"

# ── Issue B: kryptos news CLI ─────────────────────────────────────────────────
echo ""
echo "==> Issue B: kryptos news CLI command..."
ISSUE_B_URL=$(gh issue create --repo "$REPO" \
  --label "enhancement,news-intelligence" \
  --title "[Feat] kryptos news — CLI command with optional LLM assessment" \
  --body "## Summary
New \`kryptos news\` CLI subcommand that shows latest CryptoPanic headlines per pair with optional LLM buy/sell assessment against Kryptos trading guardrails.

## Motivation
Give the operator a quick view of what's in the news for any pair before deciding to trade or as a research tool, without starting a full trading cycle.

## Acceptance Criteria
- [ ] \`cmd_news(params, config)\` added to \`src/cli/commands.py\`
  - \`pair\` param: comma-separated filter (default = all active pairs)
  - \`--assess\` flag: one focused LLM call per pair — given these headlines and Kryptos guardrails (buy_min_score, TP targets), state BUY / SELL / NEUTRAL + 1 sentence reasoning
  - \`--limit\` param (default 5 headlines per pair for CLI display)
- [ ] \`print_news_panel(pair, items, llm_verdict)\` added to \`src/cli/display.py\`
  - Per-pair Rich Panel, yellow border
  - Each headline row: \`[dim]{age}[/dim]  {title}  [green]▲{votes.positive}[/green] [red]▼{votes.negative}[/red]\`
  - Optional \`[cyan]LLM: {verdict}[/cyan]\` block at bottom when --assess is used
- [ ] NL parser (\`src/cli/nl_parser.py\`): add \`fetch_news\` to \`INTENTS\`, keyword clause on \`\"news\"\` / \`\"headlines\"\` / \`\"what's happening\"\`
- [ ] Direct subcommand \`news\` registered in \`kryptos.py\` with args: \`--pair\`, \`--assess\`, \`--limit\`

## Usage
\`\`\`bash
python kryptos.py news                            # all pairs, no LLM
python kryptos.py news --pair ETH/USD,BTC/USD     # filter to 2 pairs
python kryptos.py news --assess                   # + LLM verdict per pair
python kryptos.py news --pair DOGE/USD --limit 10 --assess
\`\`\`

## Files
- \`src/cli/commands.py\`
- \`src/cli/display.py\`
- \`src/cli/nl_parser.py\`
- \`kryptos.py\`

## Dependencies
- **Requires Issue A** (fetch layer) to be merged first")

ISSUE_B_NUM=$(echo "$ISSUE_B_URL" | grep -o '[0-9]*$')
echo "  Created Issue B: #${ISSUE_B_NUM} — ${ISSUE_B_URL}"

# ── Issue C: kryptos dryrun CLI ───────────────────────────────────────────────
echo ""
echo "==> Issue C: kryptos dryrun CLI command..."
ISSUE_C_URL=$(gh issue create --repo "$REPO" \
  --label "enhancement,news-intelligence" \
  --title "[Feat] kryptos dryrun — full cycle simulation with chain of thought, no trade execution" \
  --body "## Summary
New \`kryptos dryrun\` CLI command that simulates an entire trading cycle — SL/TP scan, signal scoring, news fetch, LLM reasoning — and displays each step as a Rich panel, without writing any trade to the database.

## Motivation
Operator needs a safe way to validate agent behaviour before restarting it, or to reason about the current state of signals and positions without risk. Particularly useful after resets or config changes.

## Acceptance Criteria

### Seven displayed phases (Rich Rule + Panel each):

| Phase | Content |
|---|---|
| 1. SL/TP Scan | Read open positions; show which would trigger at current price (read-only) |
| 2. Signal Scoring | \`compute_indicators()\` + \`generate_signal()\` for all pairs; score breakdown table |
| 3. Market Context | Regime, Fear & Greed, BTC dominance %, cycle-top guard state |
| 4. News Headlines | Up to 3 headlines per BUY/SELL pair (calls \`fetch_news_for_pairs\`) |
| 5. Prompt Preview | Exact cycle prompt (truncated to 500 chars; \`--full-prompt\` for complete text) |
| 6. LLM Reasoning | LLM called via DryRunBroker stub; show raw_output + tool calls |
| 7. Would-be Trades | Table: pair, action, size, guardrail gate (pass/block), reason |

- [ ] \`DryRunBroker\` wrapper class:
  - \`place_order()\` and \`close_position()\` log \`[DRYRUN] Would {buy|sell} {pair}\` — no DB writes
  - \`get_balance()\` and \`get_open_positions()\` — read-only pass-through to real DB
- [ ] Price source: Kraken public REST ticker (\`GET /0/public/Ticker\`; no API key required). Fallback: last close from \`history/\` JSON files
- [ ] \`cmd_dryrun(params, config)\` in \`src/cli/commands.py\`
- [ ] Direct subcommand \`dryrun\` in \`kryptos.py\` with args: \`--mode paper|live\`, \`--pair\`, \`--no-llm\`, \`--full-prompt\`
- [ ] NL parser: add \`dryrun\` intent, keyword clause on \`\"dryrun\"\` / \`\"dry run\"\` / \`\"simulate\"\`
- [ ] \`--no-llm\` flag skips phases 5–7 (signal check only, zero LLM cost)

## Usage
\`\`\`bash
python kryptos.py dryrun                    # full 7-phase simulation
python kryptos.py dryrun --no-llm           # phases 1-4 only (no LLM cost)
python kryptos.py dryrun --pair ETH/USD     # single pair focus
python kryptos.py dryrun --full-prompt      # show complete prompt text
\`\`\`

## Files
- \`src/cli/commands.py\`
- \`src/cli/display.py\`
- \`src/cli/nl_parser.py\`
- \`kryptos.py\`

## Dependencies
- **Requires Issue A** (fetch layer) for news phase
- **Requires Issue D** (prompt injection) for prompt preview phase")

ISSUE_C_NUM=$(echo "$ISSUE_C_URL" | grep -o '[0-9]*$')
echo "  Created Issue C: #${ISSUE_C_NUM} — ${ISSUE_C_URL}"

# ── Issue D: cycle prompt injection ──────────────────────────────────────────
echo ""
echo "==> Issue D: cycle prompt injection + 6000-token ceiling..."
ISSUE_D_URL=$(gh issue create --repo "$REPO" \
  --label "enhancement,news-intelligence" \
  --title "[Feat] Inject CryptoPanic headlines into cycle LLM prompt (6000-token ceiling)" \
  --body "## Summary
Wire \`fetch_news_for_pairs()\` into the live trading cycle so CryptoPanic headlines appear in the per-pair block of the LLM cycle prompt. A token-budget guard ensures the total prompt never exceeds 6000 estimated tokens.

## Motivation
News context helps the LLM make better-informed BUY/SELL decisions — especially for news-driven pairs (XRP, DOGE, HYPE, SOL). Headlines only; no signal score change. The LLM decides the weight.

## Acceptance Criteria
- [ ] \`build_cycle_prompt()\` in \`src/agent/prompts.py\`: add \`news_by_pair: dict | None = None\` parameter
  - After \`Reasons:\` line in per-pair block, append for BUY/SELL pairs only:
    \`\`\`
    News:          \"Headline truncated to 120 chars…\" (2h ago)
                   \"Second headline\" (5h ago)
    \`\`\`
  - Silently skipped if pair not in dict or list is empty
- [ ] **6000-token ceiling guard**: after building the full prompt string, estimate \`len(prompt) // 4\`. If > 6000: rebuild without news blocks, log \`WARNING: Cycle prompt exceeded token budget (~N tokens), dropping news headlines\`
- [ ] \`TradingAgent.run_cycle()\` in \`src/agent/trading_agent.py\`: add \`news_by_pair: dict | None = None\` parameter; forward to \`build_cycle_prompt()\`
- [ ] \`main.py\`: after \`apply_cycle_top_guard()\` (~line 737), before \`agent.run_cycle()\` (line 756):
  \`\`\`python
  actionable = [s[\"pair\"] for s in signals if s[\"signal\"] in (\"BUY\", \"SELL\")]
  news_by_pair = fetch_news_for_pairs(actionable, config) if not is_backtest else {}
  \`\`\`
  Pass \`news_by_pair=news_by_pair\` into \`agent.run_cycle()\`
- [ ] 4 tests in \`tests/test_news_prompt.py\`:
  - No news dict → prompt identical to baseline (no regression)
  - With headlines → \`News:\` lines appear correctly in per-pair blocks
  - Token ceiling fires (~7000 token prompt) → news stripped, WARNING logged
  - \`is_backtest=True\` → \`{}\` passed, no HTTP call made

## Files
- \`src/agent/prompts.py\`
- \`src/agent/trading_agent.py\`
- \`main.py\`
- \`tests/test_news_prompt.py\`

## Notes
- No change to \`signals.py\` — this is prompt context only, not signal scoring
- No DB persistence for news — 30-min in-memory cache is sufficient for 30-min cycles
- Backtest always receives \`{}\` — no historical news data available

## Dependencies
- **Requires Issue A** (fetch layer) to be merged first")

ISSUE_D_NUM=$(echo "$ISSUE_D_URL" | grep -o '[0-9]*$')
echo "  Created Issue D: #${ISSUE_D_NUM} — ${ISSUE_D_URL}"

# ── Issue E: docs ─────────────────────────────────────────────────────────────
echo ""
echo "==> Issue E: docs update (setup.sh, SETUP.md, README.md)..."
ISSUE_E_URL=$(gh issue create --repo "$REPO" \
  --label "documentation,news-intelligence" \
  --title "[Chore] Document CryptoPanic news feature in setup.sh, SETUP.md, README.md" \
  --body "## Summary
Update the three onboarding documents so new operators know how to get a CryptoPanic API key and enable the news feature.

## Acceptance Criteria
- [ ] \`setup.sh\`: add optional prompt:
  \`\`\`
  Enter CryptoPanic API key (optional, press Enter to skip):
  \`\`\`
  Write \`CRYPTOPANIC_API_KEY=\${key}\` to \`.env\` (writes empty value if skipped, feature stays disabled)
- [ ] \`SETUP.md\`: add new section **11. CryptoPanic News Feed (Optional)**:
  - Get free API key at https://cryptopanic.com/developers
  - Add \`CRYPTOPANIC_API_KEY=...\` to \`.env\` or set \`news.api_key\` directly in \`config.yaml\`
  - Set \`news.enabled: true\` in \`config.yaml\`
  - Rate limits: ~100 req/day free tier; 30-min cache keeps usage ≤ 48/day
  - Describe the \`ticker_overrides\` config map for any symbol mismatches
- [ ] \`README.md\`:
  - Add \`kryptos news\` and \`kryptos dryrun\` to CLI Commands reference table with usage examples
  - Add one-liner in the LLM Decision Cycle section: *\"CryptoPanic headlines are injected per BUY/SELL pair into the cycle prompt when enabled\"*

## Files
- \`setup.sh\`
- \`SETUP.md\`
- \`README.md\`

## Dependencies
- **Should follow** Issues A, B, C, D being merged")

ISSUE_E_NUM=$(echo "$ISSUE_E_URL" | grep -o '[0-9]*$')
echo "  Created Issue E: #${ISSUE_E_NUM} — ${ISSUE_E_URL}"

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
echo "============================================================"
echo "✓ All 5 news intelligence issues created in backlog:"
echo "  A (fetch layer):      #${ISSUE_A_NUM}"
echo "  B (kryptos news):     #${ISSUE_B_NUM}"
echo "  C (kryptos dryrun):   #${ISSUE_C_NUM}"
echo "  D (prompt injection): #${ISSUE_D_NUM}"
echo "  E (docs):             #${ISSUE_E_NUM}"
echo ""
echo "Dependency order: A → B (parallel with D) → C → E"
echo "============================================================"
