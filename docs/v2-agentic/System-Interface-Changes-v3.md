# Kryptos v3 — System Interface Changes

**Document Type:** Interface Change Specification  
**Version:** 3.0  
**Date:** 19 April 2026  
**Reference:** docs/v2-agentic/BRD-v3.md, docs/v2-agentic/Architecture-Design-v3.md  
**Status:** Draft

Covers required changes to three surface areas:
1. **Kryptos CLI** (`kryptos.py` + `src/cli/`)
2. **Kryptos API** (`kryptos-api` — Spring Boot)
3. **Kryptos UI** (`kryptos-ui` — React/TypeScript)

> All changes are additive. No existing endpoints, commands, or UI screens are removed.

---

## 1. Kryptos CLI Changes

### 1.1 New Command: `persona`

#### `kryptos persona`

Displays the current active persona and a summary of all three persona parameter profiles.

**Output (Rich table):**
```
 Active Persona: MEDIUM
 ┌──────────────────────┬──────────────┬────────────┬─────────────────┐
 │ Parameter            │ Conservative │ Medium ★   │ High            │
 ├──────────────────────┼──────────────┼────────────┼─────────────────┤
 │ Buy min score        │ 5            │ 4          │ 3               │
 │ Max positions        │ 10           │ 12         │ 15              │
 │ Max position pct     │ 20%          │ 25%        │ 30%             │
 │ Profit floor         │ 1.0%         │ 0.5%       │ 0.0%            │
 │ RSI bypass           │ Disabled     │ 75 (ADX≥25)│ 80 (ADX≥25)     │
 │ Reallocation         │ Disabled     │ Enabled    │ Enabled (auto)  │
 │ Velocity CB          │ 2%/hr → 4h  │ 3%/hr → 2h │ 5%/hr → 1h     │
 │ LLM temperature      │ 0.1          │ 0.3        │ 0.5             │
 └──────────────────────┴──────────────┴────────────┴─────────────────┘
```

#### `kryptos persona set <name>`

Switches the active persona. Valid values: `conservative`, `medium`, `high`.

**Behaviour:**
1. Validates input (case-insensitive)
2. Writes `agent.persona: <name>` to `config.yaml`
3. Also writes `active_persona_override = <name>` to `agent_state` (DB) for immediate pick-up without restart
4. Prints confirmation: `Persona switched to MEDIUM. Takes effect next cycle.`

> Note: `persona set` is for single-instance mode. When running concurrent personas (`concurrent_mode: true`), each process owns its persona and DB independently; switching does not apply cross-process.

**Natural Language Aliases (handled by `nl_parser.py`):**

| User Input | Parsed Intent | Entity |
|---|---|---|
| "switch to medium risk" | `persona_set` | `medium` |
| "go aggressive" | `persona_set` | `high` |
| "be more conservative" | `persona_set` | `conservative` |
| "what persona am I on" | `persona_show` | — |
| "show risk profiles" | `persona_show` | — |

---

### 1.2 New Command: `regime`

#### `kryptos regime`

Displays the current market regime, active playbook, and all signal-affecting state.

**Output:**
```
 Market Regime & Playbook
 ┌──────────────────────────────────┬────────────────┐
 │ Active Persona                   │ Medium         │
 │ Active Playbook                  │ MOMENTUM 📈    │
 │ Regime State                     │ trending_up    │
 │ ADX Median (all pairs)           │ 27.4           │
 │ BTC Dominance Trend              │ Rising ▲       │
 │ Daily P&L                        │ +1.42%         │
 │ Kill Switch                      │ OFF            │
 │ Consecutive Stop-Loss Circuit    │ CLOSED         │
 │ Velocity Circuit                 │ CLOSED         │
 │ Drawdown Recovery Mode           │ OFF            │
 │ Last Cycle                       │ 2026-04-19 14:30 SGT │
 └──────────────────────────────────┴────────────────┘
 
 Feed Status
 All 29 pairs: OK
```

**Natural Language Aliases:**

| User Input | Parsed Intent |
|---|---|
| "what mode is the bot in" | `regime_show` |
| "what playbook is active" | `regime_show` |
| "is reallocation enabled" | `regime_show` |

---

### 1.3 New Command: `agents`

#### `kryptos agents`

Displays the status of each logical agent in the multi-agent pipeline.

**Output:**
```
 Agent Pipeline Status
 ┌──────────────────┬────────────┬──────────────────────┬──────────────┐
 │ Agent            │ Status     │ Last Run             │ Last Latency │
 ├──────────────────┼────────────┼──────────────────────┼──────────────┤
 │ Orchestrator     │ OK         │ 2026-04-19 14:30 SGT │ 12ms         │
 │ QSA              │ OK         │ 2026-04-19 14:30 SGT │ 847ms        │
 │ AIE (LLM)        │ OK         │ 2026-04-19 14:30 SGT │ 3421ms       │
 │ ROM              │ OK         │ 2026-04-19 14:30 SGT │ 38ms         │
 └──────────────────┴────────────┴──────────────────────┴──────────────┘
 
 Frozen Feeds (this cycle): None
 Reallocation Executed: 0 (today)
```

---

### 1.4 Modified Command: `report`

The existing `kryptos report` adds a **Persona History** section showing which persona was active for each trade.

```
 Persona Trade Distribution (last 30 days)
 ┌──────────────────┬────────┬──────────┬─────────────┐
 │ Persona          │ Trades │ Win Rate │ Avg P&L     │
 ├──────────────────┼────────┼──────────┼─────────────┤
 │ Conservative     │ 47     │ 62%      │ +1.8%       │
 │ Medium           │ 12     │ 58%      │ +2.4%       │
 │ High             │ 3      │ 67%      │ +3.1%       │
 └──────────────────┴────────┴──────────┴─────────────┘
```

---

### 1.5 CLI Implementation Files

| File | Change |
|---|---|
| `src/cli/commands.py` | Add `cmd_persona_show()`, `cmd_persona_set()`, `cmd_regime_show()`, `cmd_agents_status()` |
| `src/cli/display.py` | Add `print_persona_summary()`, `print_regime_status()`, `print_agent_pipeline()`, `print_persona_trade_distribution()` |
| `src/cli/nl_parser.py` | Extend intent mapping for `persona_set`, `regime_show`, `agents_status` |
| `kryptos.py` | Route new commands: `persona`, `regime`, `agents` |

### 1.6 New Command: `concurrent`

#### `kryptos concurrent start`

Launches all three personas as independent background processes, each with its own DB.

**Behaviour:**
1. Reads `config.yaml` to confirm `concurrent_mode: true`
2. Spawns three subprocesses: `python main.py --paper --persona conservative`, `--persona medium`, `--persona high`
3. Each writes a PID to `data/kryptos_{persona}.pid`
4. Prints status table:
```
 Concurrent Persona Runtimes Started
 Conservative  PID 12341  DB: paper_trading_conservative.db
 Medium        PID 12342  DB: paper_trading_medium.db
 High          PID 12343  DB: paper_trading_high.db
```

#### `kryptos concurrent stop`

Sends SIGTERM to all three PID files; waits for clean shutdown.

#### `kryptos concurrent status`

Shows alive/stopped state from PID files + last cycle time from each DB's `agent_state`.

---

### 2.1 New Endpoint Group: `/api/v2/persona`

#### `GET /api/v2/persona`

Returns the current active persona and all persona configurations.

**Response:**
```json
{
  "active": "medium",
  "available": ["conservative", "medium", "high"],
  "config": {
    "buy_min_score": 4,
    "max_open_positions": 12,
    "max_position_pct": 0.25,
    "min_profit_floor_pct": 0.5,
    "rsi_overbought_veto": 70,
    "momentum_bypass_rsi": 75,
    "momentum_bypass_adx": 25,
    "reallocation_enabled": true,
    "llm_temperature": 0.3,
    "llm_system_role": "Balanced Portfolio Manager",
    "velocity_circuit_breaker_pct": 3.0,
    "velocity_halt_hours": 2
  }
}
```

#### `PUT /api/v2/persona`

Switches the active persona at runtime.

**Request:**
```json
{ "persona": "high" }
```

**Response (200):**
```json
{ "previous": "medium", "active": "high", "effective": "next_cycle" }
```

**Response (400):**
```json
{ "error": "Invalid persona. Must be one of: conservative, medium, high" }
```

**Implementation:** Writes `active_persona_override` to `agent_state` table in the trading DB. The `main.py` loop reads this override at cycle start.

---

### 2.2 New Endpoint: `GET /api/v2/regime`

Returns the current market regime, playbook, and circuit states.

**Response:**
```json
{
  "persona": "medium",
  "playbook": "momentum",
  "regime_state": "trending_up",
  "adx_median": 27.4,
  "btc_dominance_trend": "rising",
  "daily_pnl_pct": 1.42,
  "kill_switch_active": false,
  "consecutive_stop_circuit_open": false,
  "velocity_circuit_open": false,
  "velocity_circuit_open_until": null,
  "drawdown_recovery_active": false,
  "last_cycle_at": "2026-04-19T06:30:00Z",
  "frozen_pairs": []
}
```

**Implementation:** Reads from `agent_state` table keys: `current_playbook`, `active_persona`, `regime_state`, `velocity_circuit_open_until`, `frozen_pairs_json`.

---

### 2.3 New Endpoint: `GET /api/v2/agents/status`

Returns latency and status for each agent in the pipeline.

**Response (single-persona mode):**
```json
{
  "mode": "single",
  "active_persona": "medium",
  "orchestrator": { "status": "ok", "last_run_at": "...", "latency_ms": 12 },
  "qsa": { "status": "ok", "last_run_at": "...", "latency_ms": 847 },
  "aie": { "status": "ok", "last_run_at": "...", "latency_ms": 3421, "prompt_tokens": 1840, "completion_tokens": 420 },
  "rom": { "status": "ok", "last_run_at": "...", "latency_ms": 38, "reallocation_today": 0 }
}
```

**Response (concurrent-persona mode):**
```json
{
  "mode": "concurrent",
  "personas": {
    "conservative": { "process_alive": true, "last_cycle_at": "...", "qsa_ms": 841, "aie_ms": 3102, "rom_ms": 35 },
    "medium":       { "process_alive": true, "last_cycle_at": "...", "qsa_ms": 854, "aie_ms": 3521, "rom_ms": 42 },
    "high":         { "process_alive": false, "last_cycle_at": "..." }
  }
}
```

**Implementation:** In single mode, reads `agent_latency_json` from `agent_state`. In concurrent mode, reads all three `paper_trading_{persona}.db` files and checks PID liveness from `data/kryptos_{persona}.pid`.

---

### 2.4 Modified Endpoint: `GET /api/v1/dashboard` (extended)

Adds `persona`, `playbook`, and `regime` fields to existing dashboard response to avoid a separate call for the main page.

```json
{
  "...existing fields...",
  "persona": "medium",
  "playbook": "momentum",
  "regime_state": "trending_up",
  "velocity_circuit_open": false
}
```

---

### 2.5 API Implementation Files

All new endpoints in the `kryptos-api` Spring Boot project:

| File | Change |
|---|---|
| `PersonaController.java` (new) | GET/PUT `/api/v2/persona` |
| `PersonaService.java` (new) | Reads/writes `agent_state` for persona override |
| `RegimeController.java` (new) | GET `/api/v2/regime` |
| `RegimeService.java` (new) | Query `agent_state` for regime state keys |
| `AgentStatusController.java` (new) | GET `/api/v2/agents/status` |
| `DashboardService.java` (modified) | Add `persona`, `playbook`, `regime_state` to dashboard DTO |
| `DashboardDto.java` (modified) | Add new fields |
| `OpenAPIConfig.java` (modified) | Register new controllers in Swagger |

**New DTOs:**
```java
// PersonaDto.java
public record PersonaDto(
    String active,
    List<String> available,
    Map<String, Object> config
) {}

// RegimeDto.java  
public record RegimeDto(
    String persona,
    String playbook,
    String regimeState,
    Double adxMedian,
    String btcDominanceTrend,
    Double dailyPnlPct,
    boolean killSwitchActive,
    boolean velocityCircuitOpen,
    String velocityCircuitOpenUntil,
    boolean drawdownRecoveryActive,
    String lastCycleAt,
    List<String> frozenPairs
) {}
```

---

## 3. Kryptos UI Changes

### 3.1 Dashboard — Persona + Regime Panel (New Component)

A new section at the top of the Dashboard screen showing the active persona and playbook.

**Component:** `src/components/trading/PersonaRegimePanel.tsx`

**Layout:**
```
┌────────────────────────────────────────────────────────────────┐
│  PERSONA  [Conservative] [Medium ●] [High]          [Switch]   │
│           Balanced Portfolio Manager                            │
│                                                                 │
│  MARKET MODE                    REGIME                          │
│  ████ MOMENTUM                  trending_up                     │
│  ADX: 27.4  │  BTC Dom: Rising  │  Daily P&L: +1.42%          │
│                                                                 │
│  Circuits: All Clear  │  Velocity: CLOSED  │  Kill Switch: OFF  │
└────────────────────────────────────────────────────────────────┘
```

**Interactions:**
- Clicking a persona button shows a **confirmation modal** before switching:
  ```
  Switch to HIGH persona?
  This changes buy thresholds, position size, and capital reallocation behaviour.
  Current open positions are NOT affected.
  [Cancel]  [Confirm Switch]
  ```
- Modal confirms: `PUT /api/v2/persona` is called only on "Confirm Switch"
- Mode badge colour: `momentum` = green, `ranging` = yellow, `risk_off` = red
- Tooltip on each persona button shows key differences

**Data source:** `GET /api/v2/persona` + `GET /api/v2/regime` (polled every 30s)

---

### 3.2 Dashboard — Agent Status Panel (New Component)

A collapsible panel at the bottom of the Dashboard showing agent pipeline health.

**Component:** `src/components/trading/AgentStatusPanel.tsx`

**Layout:**
```
▼ Agent Pipeline                               Last cycle: 14:30 SGT
  Orchestrator  ✓ 12ms    QSA  ✓ 847ms    AIE  ✓ 3421ms    ROM  ✓ 38ms
  Tokens: 1840 prompt / 420 completion    Frozen feeds: None
  Reallocation today: 0 executed
```

**Data source:** `GET /api/v2/agents/status` (polled every 60s)

---

### 3.3 Holdings Screen — Prune Candidate Indicator

Positions identified as potential reallocation prune candidates (low ADX + low PnL) are visually flagged.

**Component:** `src/screens/Holdings/` (modify `HoldingsScreen.tsx`)

**Change:**
- Add `prune_candidate: boolean` to position data (derived: `adx < 25 AND pnl_pct < persona_floor_pct * 1.5`)
- For candidate positions: show a subtle amber badge `⚡ Reallocation candidate`
- Tooltip: "This position may be closed to fund a high-conviction signal (Medium/High persona)"

---

### 3.4 Trade History Screen — Persona Column

Add `persona` column to the Trade History table showing which persona was active when the trade was executed.

**Component:** `src/screens/TradeHistory/` (modify `TradeHistoryScreen.tsx`)

**Change:**
- Add `persona` column in trade table (after `exit_reason`)
- Colour-coded badges: Conservative = blue, Medium = teal, High = orange
- Filter chips: `All | Conservative | Medium | High`

---

### 3.5 New Screen: Pair Detail — Regime Overlay

On the existing `PairDetail` screen, add a "Regime" section showing the pair's QSA output.

**Component:** `src/screens/PairDetail/` (modify screen)

**Addition:**
```
Pair Regime                     Feed Status
├── Regime: trending_up         ├── Status: OK
├── ADX: 28.4                   ├── Last candle: 14:15 SGT
├── Volume floor: Winsorized EMA├── OHLCV variance: 0.0042
└── Signal: BUY (score 8/28)    └── Freeze count: 0
```

---

### 3.6 Config Screen — Persona Editor (Read-Only in v3)

Extend the existing Config screen to display persona values. Editing is done via CLI or API in v3; the UI shows them read-only as a reference panel.

**Component:** `src/screens/Config/` (modify `ConfigScreen.tsx`)

**Addition:**
- New tab "Personas" showing all three persona config tables side-by-side
- Highlight the currently active persona
- Link to documentation

---

### 3.7 UI Implementation Summary

| File | Change |
|---|---|
| `src/components/trading/PersonaRegimePanel.tsx` | New component |
| `src/components/trading/AgentStatusPanel.tsx` | New component |
| `src/screens/Dashboard/DashboardScreen.tsx` | Add PersonaRegimePanel and AgentStatusPanel |
| `src/screens/Holdings/HoldingsScreen.tsx` | Add prune candidate badge |
| `src/screens/TradeHistory/TradeHistoryScreen.tsx` | Add persona column + filter chips |
| `src/screens/PairDetail/PairDetailScreen.tsx` | Add regime overlay section |
| `src/screens/Config/ConfigScreen.tsx` | Add Personas tab (read-only) |
| `src/api/types.ts` | Add `PersonaDto`, `RegimeDto`, `AgentStatusDto` types |
| `src/api/index.ts` | Add `getPersona()`, `setPersona()`, `getRegime()`, `getAgentStatus()` |
| `src/hooks/usePolling.ts` | Persona poll: 30s interval; agent status poll: 60s |

---

## 4. Database Schema Changes

Two changes are required in the SQLite schemas (both `paper_trading.db` and `live_trading.db`):

### 4.1 `trades` table — add `persona` column

```sql
ALTER TABLE paper_trades ADD COLUMN persona TEXT DEFAULT 'conservative';
```

Applied as migration on startup in `src/storage/database.py` (existing migration pattern).

### 4.2 New `agent_state` keys (no schema change — existing key-value table)

| Key | Value Type | Set By | Description |
|---|---|---|---|
| `active_persona` | string | `main.py` | Persona active for current/last cycle |
| `active_persona_override` | string | API / CLI | Override from UI/API (takes precedence over config file) |
| `current_playbook` | string | Orchestrator | `ranging / momentum / risk_off` |
| `regime_state` | string | QSA Agent | `stable / trending_up / trending_down / turbulent` |
| `adx_median` | float string | QSA Agent | Median ADX across all non-frozen pairs |
| `frozen_pairs_json` | JSON array | QSA Agent | List of currently frozen pair names |
| `velocity_circuit_open_until` | ISO timestamp | ROM Agent | Null if closed |
| `agent_latency_json` | JSON object | main.py | Per-agent latency dict |

---

## 5. Breaking Change Assessment

| Component | Breaking Change? | Notes |
|---|---|---|
| Existing CLI commands | No | All current commands unchanged |
| Existing API endpoints (`/api/v1/*`) | No | All v1 endpoints unchanged |
| `paper_trades` table | Migration only | `ALTER TABLE ... ADD COLUMN persona` — non-destructive |
| `config.yaml` format | Additive only | New `personas:`, `qsa:`, `orchestrator:`, `mcp:` sections; existing keys unchanged |
| LLM prompt format | Yes — internal | Breaking change to `build_cycle_prompt()` output; no external API change |
| `rolling_volume_p15` | Internal change | Replaced by `winsorized_vol_ema`; signal behaviour changes (feature, not bug) |
