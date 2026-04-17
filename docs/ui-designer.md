# Kryptos Terminal — UI Design Document

**Version:** 1.0  
**Date:** 14 April 2026  
**Architecture:** React 18 SPA + Java 21 / Spring Boot 3.5 REST API  
**Theme:** Cyber-Institutional dark mode

---

## Table of Contents

1. [Design System](#1-design-system)
2. [Application Architecture](#2-application-architecture)
3. [Screen Inventory](#3-screen-inventory)
4. [Screen Designs](#4-screen-designs)
   - 4.1 [Login Screen](#41-login-screen)
   - 4.2 [Dashboard](#42-dashboard)
   - 4.3 [My Holdings](#43-my-holdings)
   - 4.4 [Trade History](#44-trade-history)
   - 4.5 [Pair Detail View](#45-pair-detail-view)
   - 4.6 [Audit Logs](#46-audit-logs)
   - 4.7 [System Config](#47-system-config)
5. [Navigation & Routing](#5-navigation--routing)
6. [Component Library](#6-component-library)
7. [State Management](#7-state-management)
8. [API Contract](#8-api-contract)
   - 8.1 [Authentication](#81-authentication)
   - 8.2 [Dashboard](#82-dashboard)
   - 8.3 [Positions](#83-positions)
   - 8.4 [Trades](#84-trades)
   - 8.5 [Pairs & Chart Data](#85-pairs--chart-data)
   - 8.6 [Audit Log](#86-audit-log)
   - 8.7 [Agent Status](#87-agent-status)
   - 8.8 [Market Sentiment](#88-market-sentiment)
   - 8.9 [System Config](#89-system-config)
9. [Error Handling & Loading States](#9-error-handling--loading-states)
10. [Security Model](#10-security-model)

---

## 1. Design System

### 1.1 Color Palette

```css
/* Core palette — Cyber-Institutional dark mode */
--bg-dark:        #0f172a   /* page background */
--bg-surface:     #1e293b   /* cards, panels */
--bg-elevated:    #293548   /* hover states, selected rows */
--border:         #334155   /* dividers, card borders */
--border-focus:   #475569   /* input focus ring */

/* Semantic colors */
--accent-cyan:    #22d3ee   /* primary CTA, active nav, links */
--accent-cyan-dim:#0891b2   /* secondary CTA hover */

--signal-buy:     #10b981   /* BUY signal, positive P&L */
--signal-sell:    #ef4444   /* SELL signal, negative P&L, stop-loss */
--signal-hold:    #f59e0b   /* HOLD neutral / warning */
--signal-veto:    #6b7280   /* Vetoed signal (gray circle) */

/* Text */
--text-primary:   #f8fafc   /* main content */
--text-secondary: #cbd5e1   /* labels, headings */
--text-muted:     #94a3b8   /* metadata, timestamps */
--text-disabled:  #475569   /* inactive / unavailable */

/* Exit reason taxonomy */
--exit-tp:              #10b981   /* take_profit — green */
--exit-partial-tp:      #34d399   /* partial_take_profit — light green */
--exit-stop-loss:       #ef4444   /* stop_loss — red */
--exit-trailing-stop:   #f59e0b   /* trailing_stop — amber */
--exit-agent-sell:      #818cf8   /* agent_sell — indigo */
--exit-backtest-end:    #64748b   /* backtest_end — slate */
```

### 1.2 Typography

```css
/* Google Font: Inter (weights 400, 500, 600, 700) */
--font-family:          'Inter', 'JetBrains Mono', sans-serif;
--font-mono:            'JetBrains Mono', 'Fira Code', monospace;

/* Scale */
--text-xs:    0.75rem   /* 12px — timestamps, metadata */
--text-sm:    0.875rem  /* 14px — table cells, labels */
--text-base:  1rem      /* 16px — body text */
--text-lg:    1.125rem  /* 18px — section headings */
--text-xl:    1.25rem   /* 20px — card titles */
--text-2xl:   1.5rem    /* 24px — portfolio value */
--text-3xl:   1.875rem  /* 30px — hero stat */
```

### 1.3 Spacing (8-point grid)

- xs: 4px, sm: 8px, md: 16px, lg: 24px, xl: 32px, 2xl: 48px

### 1.4 Border Radius

- sm: 4px (table rows), md: 8px (cards), lg: 12px (modal), pill: 9999px (badges)

### 1.5 Iconography

Use `lucide-react` icon set (tree-shakeable, consistent stroke weight).  
Key icons: `LayoutDashboard`, `Wallet`, `History`, `BookOpen`, `Settings`, `LogOut`, `TrendingUp`, `TrendingDown`, `Shield`, `Activity`, `Zap`, `AlertTriangle`, `ChevronRight`, `RefreshCw`.

---

## 2. Application Architecture

```
kryptos-ui/
├── public/
│   └── index.html
├── src/
│   ├── main.tsx                  # react entry point
│   ├── App.tsx                   # router + auth guard
│   ├── api/
│   │   ├── client.ts             # axios instance, JWT interceptor
│   │   ├── auth.ts               # Telegram OAuth helpers
│   │   ├── dashboard.ts          # dashboard API calls
│   │   ├── positions.ts          # positions API calls
│   │   ├── trades.ts             # trades API calls
│   │   ├── pairs.ts              # pairs + chart API calls
│   │   ├── audit.ts              # audit log API calls
│   │   ├── agent.ts              # agent status API calls
│   │   └── types.ts              # shared TypeScript interfaces
│   ├── components/
│   │   ├── layout/
│   │   │   ├── AppShell.tsx      # sidebar + header wrapper
│   │   │   ├── Sidebar.tsx       # nav links + watchlist + sentiment
│   │   │   ├── Header.tsx        # brand + agent stats + user menu
│   │   │   └── TickerBar.tsx     # scrolling price ticker (optional)
│   │   ├── common/
│   │   │   ├── Badge.tsx         # signal/exit reason badges
│   │   │   ├── Card.tsx          # surface card wrapper
│   │   │   ├── DataTable.tsx     # sortable/filterable table
│   │   │   ├── EmptyState.tsx    # empty data placeholder
│   │   │   ├── ErrorBoundary.tsx # React error boundary
│   │   │   ├── LoadingSpinner.tsx
│   │   │   ├── Pagination.tsx
│   │   │   ├── PnlDisplay.tsx    # colored P&L value with icon
│   │   │   ├── SignalScoreBar.tsx # 0–28 pts visual bar
│   │   │   └── StatCard.tsx      # metric card (label + value + delta)
│   │   ├── charts/
│   │   │   ├── CandlestickChart.tsx  # lightweight-charts wrapper
│   │   │   ├── PriceMarker.tsx       # BUY/SELL/VETO SVG markers
│   │   │   └── PortfolioChart.tsx    # area chart of balance over time
│   │   └── screens/
│   │       ├── Login/
│   │       │   ├── LoginScreen.tsx
│   │       │   └── TelegramButton.tsx
│   │       ├── Dashboard/
│   │       │   ├── DashboardScreen.tsx
│   │       │   ├── PortfolioSummaryCard.tsx
│   │       │   ├── OpenPositionsList.tsx
│   │       │   └── RecentTradesTable.tsx
│   │       ├── Holdings/
│   │       │   ├── HoldingsScreen.tsx
│   │       │   └── PositionRow.tsx
│   │       ├── TradeHistory/
│   │       │   ├── TradeHistoryScreen.tsx
│   │       │   └── TradeRow.tsx
│   │       ├── PairDetail/
│   │       │   ├── PairDetailScreen.tsx
│   │       │   ├── SignalBreakdownPanel.tsx
│   │       │   └── LlmDecisionPanel.tsx
│   │       ├── AuditLogs/
│   │       │   ├── AuditLogsScreen.tsx
│   │       │   └── CycleDetailModal.tsx
│   │       └── Config/
│   │           └── ConfigScreen.tsx
│   ├── hooks/
│   │   ├── useAuth.ts            # auth state + JWT helpers
│   │   ├── usePolling.ts         # configurable auto-refresh
│   │   └── useToast.ts           # notification toasts
│   ├── store/
│   │   └── authStore.ts          # Zustand auth slice
│   └── utils/
│       ├── format.ts             # currency, %, date formatters
│       └── constants.ts          # pair list, tier labels, colors
```

---

## 3. Screen Inventory

| # | Screen | Route | Auth Required | Refresh |
|---|---|---|---|---|
| 1 | Login | `/login` | No | — |
| 2 | Dashboard | `/` | Yes | 30 s |
| 3 | My Holdings | `/holdings` | Yes | 30 s |
| 4 | Trade History | `/trades` | Yes | 60 s |
| 5 | Pair Detail | `/pairs/:pair` | Yes | 30 s |
| 6 | Audit Logs | `/audit` | Yes | Manual |
| 7 | System Config | `/config` | Yes | Manual |

---

## 4. Screen Designs

### 4.1 Login Screen

**URL:** `/login`  
**Purpose:** Telegram OAuth handshake — the only entry point into the terminal.

**Layout:**
```
┌─────────────────────────────────────────┐
│           [KRYPTOS LOGO]                │
│                                         │
│     KRYPTOS // AI Crypto Trading        │
│              Agent                      │
│                                         │
│    Secure terminal access required.     │
│    Authenticate via Telegram.           │
│                                         │
│   ┌───────────────────────────────┐    │
│   │  [Telegram Logo] Continue     │    │
│   │       with Telegram           │    │
│   └───────────────────────────────┘    │
│                                         │
│     v1.0 — Paper Trading Mode           │
└─────────────────────────────────────────┘
```

**Behaviour:**
- On page load: check `localStorage` for valid JWT. If present and not expired → redirect to `/`.
- On Telegram button click: open Telegram OAuth widget. On success, POST `/api/auth/telegram` with the signed callback data. Store returned JWT in `localStorage`.
- On auth failure: display inline error message. Do NOT expose error details.
- Background: subtle animated grid pattern using CSS `background-image`.

---

### 4.2 Dashboard

**URL:** `/`  
**Purpose:** At-a-glance portfolio health, macro sentiment, open positions summary, recent trades.

**Layout:**
```
┌─ Header ─────────────────────────────────────────────────────────┐
│  KRYPTOS // Agent    Cycle: 4128 | LLM: 12,842 | ● ACTIVE        │
│                                              Welcome, Vipul | Logout│
├─ Ticker Bar (scrolling live prices) ────────────────────────────┤
├─ Sidebar ─┬─ Main Content ────────────────────────────────────────┤
│           │                                                        │
│ Dashboard │  ┌── Portfolio Summary ──────────────────────────┐    │
│ Holdings  │  │  $1,245.50 (+$245.50 / +24.55% all time)     │    │
│ Trades    │  │  Daily P&L: +$12.40 (+1.0%)                  │    │
│ ── Pairs──│  │  Cash: $320.20 | Positions: 10 open          │    │
│ BTC/USD   │  │  [Balance area chart — 30 days]              │    │
│ ETH/USD   │  └───────────────────────────────────────────────┘   │
│ SOL/USD   │                                                        │
│ ...       │  ┌── Macro Sentiment ──┐  ┌── Agent State ─────────┐  │
│           │  │  Fear & Greed: 12   │  │  Circuit Breaker: OFF  │  │
│ ── Macro ─│  │  [EXTREME FEAR]     │  │  Kill Switch:    OFF   │  │
│ F&G: 12   │  │  BTC Dom: 57.29%   │  │  Recovery Mode:  OFF   │  │
│ BTC D: ↑  │  │  Trend: ↑ RISING   │  │  Pairs Active:   27    │  │
│           │  └─────────────────────┘  └────────────────────────┘ │
│ Audit     │                                                        │
│ Config    │  ┌── Open Positions (10) ──────────────────────────┐  │
│           │  │ Pair  │Entry │Current│ P&L  │TP% │SL%│Progress │  │
│           │  │BTC/USD│42000 │43120  │+2.7% │8%  │5% │▓▓░░░░░░ │  │
│           │  │ETH/USD│1800  │1810   │+0.1% │12% │5% │▓░░░░░░░ │  │
│           │  │...    │      │       │      │    │   │         │  │
│           │  └────────────────────────────────────────────────┘  │
│           │                                                        │
│           │  ┌── Recent Trades (last 10) ─────────────────────┐  │
│           │  │ Time │ Pair │ Action │ P&L  │ Exit Reason       │  │
│           │  │ ...  │ ...  │ ...    │ ...  │  ...              │  │
│           │  └────────────────────────────────────────────────┘  │
└───────────┴───────────────────────────────────────────────────────┘
```

**Data Sources:**
- `GET /api/dashboard/summary` — portfolio totals, daily P&L
- `GET /api/agent/status` — cycle count, LLM count, heartbeat, circuit breaker, kill switch
- `GET /api/market/sentiment` — Fear & Greed, BTC dominance
- `GET /api/positions` — open positions list
- `GET /api/trades?limit=10` — recent closed trades
- `GET /api/dashboard/balance-history?days=30` — area chart data

**Auto-refresh:** every 30 seconds via `usePolling` hook.

---

### 4.3 My Holdings

**URL:** `/holdings`  
**Purpose:** Full detail view of all open positions with real-time P&L, SL/TP levels, and last LLM decision per pair.

**Layout:**
```
┌─ My Holdings ─────────────────────────────────────────────────────┐
│                                                                     │
│  Invested: $925.30  |  Current Value: $951.18  |  P&L: +$25.88    │
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │ Pair   │ Side │ Entry  │ Current │ P&L%  │ SL     │ TP      │   │
│  │        │      │ Price  │ Price   │       │ Price  │ Price   │   │
│  ├────────┼──────┼────────┼─────────┼───────┼────────┼─────────┤   │
│  │BTC/USD │ BUY  │$42,000 │$43,120  │+2.67% │$39,900 │$45,360  │   │
│  │        │      │ 14 Apr │ LIVE    │[████▌]│  -5%   │  +8%    │   │
│  │        │ Last LLM Decision: HOLD — "Let the trade mature"   │   │
│  ├────────┼──────┼────────┼─────────┼───────┼────────┼─────────┤   │
│  │ETH/USD │ BUY  │ $1,800 │ $1,810  │+0.09% │ $1,710 │  $2,016 │   │
│  │        │      │        │         │[█░░░░]│  -5%   │  +12%   │   │
│  │        │ Last LLM: HOLD — Gate 2 BLOCKED (P&L 0.09% < 7.2%)│   │
│  └─────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
```

**Progress bar:** fills cyan from 0% to TP target. If trailing stop was raised, show a second amber notch on the bar at the new SL level.

**Last LLM Decision:** rendered inline below each row. If sell was rejected, show the gate number and reason in amber text: `SELL BLOCKED: Gate 2 — P&L 1.46% below 12.0% proximity guard`.

**Data Sources:**
- `GET /api/positions` — full position list with live prices
- `GET /api/positions/{id}/last-decision` — last LLM decision per position

---

### 4.4 Trade History

**URL:** `/trades`  
**Purpose:** Full paginated closed trade history with filtering, sorting, and P&L summary bar.

**Layout:**
```
┌─ Trade History ────────────────────────────────────────────────────┐
│                                                                      │
│  [Filter: Pair ▼] [Filter: Exit Reason ▼] [Date Range: ______]     │
│  [Search pair...]                   [Export CSV]                    │
│                                                                      │
│  Summary: 142 trades | Win Rate: 55% | Avg P&L: +2.1% | PF: 1.34  │
│  ████████████████████████████████████░░░░░░░░░░░░░░░░░░░░░░        │
│  ← wins (78)                                  losses (64) →         │
│                                                                      │
│  ┌────────────────────────────────────────────────────────────┐    │
│  │ # │ Opened     │ Closed     │ Pair    │ P&L%  │Exit Reason │    │
│  ├───┼────────────┼────────────┼─────────┼───────┼────────────┤    │
│  │ 1 │2026-04-13  │2026-04-14  │BTC/USD  │+7.66% │take_profit │    │
│  │   │  22:01 SGT │  10:32 SGT │         │       │[green badge]│   │
│  │ 2 │2026-04-12  │2026-04-12  │DOGE/USD │-5.0%  │stop_loss   │    │
│  │   │            │            │         │       │[red badge]  │   │
│  └────────────────────────────────────────────────────────────┘    │
│                                                                      │
│  [← Prev]  Page 1 of 15  [Next →]             10 / 25 / 50 per page│
└──────────────────────────────────────────────────────────────────────┘
```

**Exit Reason Badges (color-coded):**
- `take_profit` → green badge
- `partial_take_profit` → light-green badge
- `stop_loss` → red badge
- `trailing_stop` → amber badge
- `agent_sell` → indigo badge
- `backtest_end` → gray badge

**Data Sources:**
- `GET /api/trades?page=1&size=10&pair=&exitReason=&fromDate=&toDate=` — paginated trades
- `GET /api/trades/summary` — win rate, avg P&L, profit factor

---

### 4.5 Pair Detail View

**URL:** `/pairs/:pair` (e.g. `/pairs/BTC-USD`)  
**Purpose:** Full candlestick chart with BUY/SELL/VETO markers, signal breakdown, and LLM reasoning history.

**Layout:**
```
┌─ BTC/USD ─ $43,120 ▲+0.32%  ─────────────────────────────────────┐
│ Tier 1 | TP: 8% | SL: 5% | Min Score: 5 | Slippage: 0.05%        │
│                                                                     │
│ ┌─ Candlestick Chart ──────────────────────────────────────────┐  │
│ │                                                               │  │
│ │  [15-min OHLCV candles, last 300]                            │  │
│ │  ▲ BUY markers (cyan triangle up)                            │  │
│ │  ▼ SELL markers (red triangle down)                          │  │
│ │  ● VETO markers (gray circle — hard veto HOLD)               │  │
│ │  ──── SL line (red dashed)                                   │  │
│ │  ─ ─  TP line (green dashed)                                 │  │
│ │  ─ ─  Partial TP line (teal dashed, if active)              │  │
│ │                                                               │  │
│ └──────────────────────────────────────────────────────────────┘  │
│                                                                     │
│ ┌─ Current Signal Score ─────────────────────────────────────────┐ │
│ │  Signal: BUY  Score: 9/28  Min Required: 5                     │ │
│ │  ████████░░░░░░░░░░░░░░░░░░░░  9 pts                          │ │
│ │                                                                 │ │
│ │  Contributors:                                                  │ │
│ │  [+3] RSI Oversold (RSI=27.0)                                  │ │
│ │  [+2] Fear & Greed Extreme Fear (F&G=12)                       │ │
│ │  [+2] EMA(9) > EMA(21)                                         │ │
│ │  [+1] MACD Histogram Positive (cont.)                          │ │
│ │  [+1] OBV Accumulation                                         │ │
│ │                                                                 │ │
│ │  Vetoes Active: none                                            │ │
│ └─────────────────────────────────────────────────────────────────┘ │
│                                                                     │
│ ┌─ LLM Decision History ──────────────────────────────────────┐   │
│ │ 14 Apr 23:41 | HOLD | "Portfolio fully allocated, holding"   │   │
│ │ 14 Apr 23:11 | BUY  | propose_buy(BTC/USD, $105.30)         │   │
│ │ 14 Apr 22:41 | HOLD | "Score 4 < min 5 — score miss"        │   │
│ └──────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
```

**Chart library:** `lightweight-charts` (TradingView) — fast canvas-based rendering.  
**Trade markers:** injected as `createSeriesMarkers()` with shape `arrowUp` (BUY, cyan), `arrowDown` (SELL, red), `circle` (VETO, gray).

**Data Sources:**
- `GET /api/pairs/{pair}/candles?interval=15m&limit=300` — OHLCV data from `history/` candle files (refreshed from WebSocket)
- `GET /api/pairs/{pair}/trades` — trade fills for the pair (to place markers on chart)
- `GET /api/pairs/{pair}/signals?limit=20` — recent signal history
- `GET /api/pairs/{pair}/decisions?limit=20` — LLM decision history
- `GET /api/pairs/{pair}/info` — tier, TP%, SL%, min score, slippage info

---

### 4.6 Audit Logs

**URL:** `/audit`  
**Purpose:** Full LLM cycle log — every cycle's decisions, risk-check verdicts, and raw LLM reasoning.

**Layout:**
```
┌─ Audit Logs ──────────────────────────────────────────────────────┐
│                                                                     │
│  [Filter: Mode ▼] [Filter: Decision ▼] [Date Range]               │
│                                                                     │
│  ┌─ Cycles ────────────────────────────────────────────────────┐  │
│  │ Cycle # │ Time (SGT) │ Balance │ Pairs │ Buys │ Sells │ ms  │  │
│  ├─────────┼────────────┼─────────┼───────┼──────┼───────┼─────┤  │
│  │  4128   │ 14 Apr ... │$1245.50 │  27   │  2   │  0    │ 8.2s│  │
│  │  4127   │ 14 Apr ... │$1240.10 │  27   │  0   │  1    │ 7.9s│  │
│  └──────────────────────────────────────────────────────────────┘  │
│                                                                     │
│  ┌─ Expanded Cycle 4128 (click row to expand) ──────────────────┐  │
│  │  ┌─ Decisions ───────────────────────────────────────────┐  │  │
│  │  │ Pair    │ Action │ Tool Called │ Risk Check │ Latency  │  │  │
│  │  │BTC/USD  │ BUY    │propose_buy  │ APPROVED   │  1.2s   │  │  │
│  │  │ETH/USD  │ HOLD   │hold         │ —          │  0.1s   │  │  │
│  │  │SOL/USD  │ BUY    │propose_buy  │ REJECTED   │  0.8s   │  │  │
│  │  │         │        │             │ Gate 4: corr cluster │  │  │
│  │  └───────────────────────────────────────────────────────┘  │  │
│  │                                                               │  │
│  │  [View Raw LLM Output]  [View Prompt]                        │  │
│  └───────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
```

**Data Sources:**
- `GET /api/audit/cycles?page=1&size=20` — paginated cycle list
- `GET /api/audit/cycles/{id}/decisions` — decisions for a specific cycle
- `GET /api/audit/cycles/{id}/risk-checks` — risk verdicts for a cycle
- `GET /api/audit/decisions/{id}` — full LLM decision record (incl. raw output)

---

### 4.7 System Config

**URL:** `/config`  
**Purpose:** Read-only view of the active runtime configuration (sanitized — no API keys exposed).

**Layout:**
```
┌─ System Config ───────────────────────────────────────────────────┐
│  ⚠ Read-only view — changes require direct config.yaml edit       │
│                                                                     │
│  ┌─ Trading ─────────────────┐  ┌─ Risk ────────────────────────┐  │
│  │ Start Capital: $1,000     │  │ Max Position: 20%             │  │
│  │ Max Open Pos:  10         │  │ Min Cash Reserve: 5%          │  │
│  │ Max Buys/Cycle: 7         │  │ Daily Loss Limit: 10%         │  │
│  │ Min Order: $20            │  │ Kill Switch: -7%              │  │
│  └───────────────────────────┘  └───────────────────────────────┘  │
│                                                                     │
│  ┌─ LLM ─────────────────────┐  ┌─ Pairs (27 Active) ──────────┐  │
│  │ Model:  qwen3-32b         │  │ [Expandable table with       │  │
│  │ Provider: Groq            │  │  per-pair TP/SL/min score/   │  │
│  │ Fallback: llama-3.3-70b   │  │  slippage/tier]              │  │
│  │ Timeout: 120s             │  │                              │  │
│  └───────────────────────────┘  └───────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
```

**Data Sources:**
- `GET /api/config` — sanitized config (no API keys, no secrets)

---

## 5. Navigation & Routing

```tsx
// App.tsx routing
<Routes>
  <Route path="/login" element={<LoginScreen />} />
  <Route element={<AuthGuard />}>          {/* redirects to /login if no JWT */}
    <Route element={<AppShell />}>         {/* sidebar + header layout */}
      <Route path="/"         element={<DashboardScreen />} />
      <Route path="/holdings" element={<HoldingsScreen />} />
      <Route path="/trades"   element={<TradeHistoryScreen />} />
      <Route path="/pairs/:pair" element={<PairDetailScreen />} />
      <Route path="/audit"    element={<AuditLogsScreen />} />
      <Route path="/config"   element={<ConfigScreen />} />
    </Route>
  </Route>
</Routes>
```

**Auth Guard:** reads JWT from `localStorage`, verifies expiry client-side (`jwt-decode`). If invalid/expired → redirect to `/login`.

---

## 6. Component Library

### 6.1 `Badge`
```tsx
<Badge variant="buy">BUY</Badge>      // cyan, dark bg
<Badge variant="sell">SELL</Badge>    // red
<Badge variant="hold">HOLD</Badge>    // amber
<Badge variant="vetoed">VETOED</Badge>// gray
<Badge variant="take_profit">TP</Badge>    // green
<Badge variant="stop_loss">SL</Badge>      // red
<Badge variant="trailing_stop">TSL</Badge> // amber
<Badge variant="agent_sell">SELL</Badge>   // indigo
```

### 6.2 `PnlDisplay`
```tsx
// Renders P&L with color and direction icon
<PnlDisplay value={7.66} suffix="%" />    // +7.66% in green with TrendingUp
<PnlDisplay value={-5.0} suffix="%" />    // -5.00% in red with TrendingDown
```

### 6.3 `SignalScoreBar`
```tsx
// Visual 0–28 point bar with threshold marker
<SignalScoreBar score={9} maxScore={28} minScore={5} direction="BUY" />
```

### 6.4 `StatCard`
```tsx
<StatCard label="Portfolio Value" value="$1,245.50" delta="+24.55%" positive />
```

### 6.5 `DataTable`
```tsx
// Generic sortable + paginating table
<DataTable columns={columns} data={rows} onSort={...} pagination={...} />
```

### 6.6 `CandlestickChart`
```tsx
// Wraps TradingView lightweight-charts
<CandlestickChart
  candles={ohlcvData}      // CandleData[]
  markers={tradeMarkers}   // TradeMarker[]
  levels={[                // horizontal lines
    { price: 39900, color: '#ef4444', label: 'SL', style: 'dashed' },
    { price: 45360, color: '#10b981', label: 'TP', style: 'dashed' },
  ]}
/>
```

---

## 7. State Management

**Zustand** (lightweight) for global state. React Query for server state (caching, auto-refresh, loading/error states).

```ts
// authStore.ts
interface AuthState {
  token: string | null;
  user: { id: string; username: string; photoUrl: string } | null;
  login: (token: string, user: TelegramUser) => void;
  logout: () => void;
  isAuthenticated: () => boolean;
}
```

**React Query setup:**
```ts
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,         // 30 s
      refetchOnWindowFocus: true,
      retry: 2,
    },
  },
});
```

**Auto-polling hooks:**
```ts
// Dashboard — poll every 30s
const { data } = useQuery({
  queryKey: ['dashboard-summary'],
  queryFn: () => api.getDashboardSummary(),
  refetchInterval: 30_000,
});
```

---

## 8. API Contract

**Base URL:** `http://localhost:8080/api`  
**Content-Type:** `application/json`  
**Authentication:** `Authorization: Bearer <JWT>` header on all protected endpoints.  
**Versioning:** all endpoints prefixed `/api/v1/`

### Common Error Response

```json
{
  "error": "UNAUTHORIZED",
  "message": "JWT token is expired or invalid",
  "timestamp": "2026-04-14T15:41:00Z",
  "path": "/api/v1/positions"
}
```

HTTP Status codes: `200 OK`, `400 Bad Request`, `401 Unauthorized`, `403 Forbidden`, `404 Not Found`, `500 Internal Server Error`.

---

### 8.1 Authentication

#### `POST /api/v1/auth/telegram`

Verifies Telegram Login Widget callback data, issues a JWT.

**Request Body:**
```json
{
  "id": 987654321,
  "first_name": "Vipul",
  "username": "vipulbms",
  "photo_url": "https://t.me/i/userpic/...",
  "auth_date": 1713103260,
  "hash": "abc123def456..."
}
```

**Response 200:**
```json
{
  "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "expiresIn": 86400,
  "user": {
    "id": "987654321",
    "firstName": "Vipul",
    "username": "vipulbms",
    "photoUrl": "https://t.me/i/userpic/..."
  }
}
```

**Response 401:**
```json
{
  "error": "TELEGRAM_AUTH_FAILED",
  "message": "Hash verification failed or auth_date too old"
}
```

**Security notes:**
- Server MUST verify HMAC-SHA256 hash using `BOT_TOKEN` as key before issuing JWT.
- Reject if `auth_date` is older than 300 seconds.
- JWT payload: `{ sub: telegramUserId, exp: ..., iat: ... }`. Sign with HS256.

---

#### `POST /api/v1/auth/logout`

**Required:** `Authorization: Bearer <token>`  
**Response 200:** `{ "message": "Logged out successfully" }`

---

### 8.2 Dashboard

#### `GET /api/v1/dashboard/summary`

Returns current portfolio snapshot for the header stat cards.

**Response 200:**
```json
{
  "mode": "paper",
  "portfolioValueUsd": 1245.50,
  "cashUsd": 320.20,
  "investedUsd": 925.30,
  "allTimePnlUsd": 245.50,
  "allTimePnlPct": 24.55,
  "dailyPnlUsd": 12.40,
  "dailyPnlPct": 1.00,
  "openPositionsCount": 10,
  "startingBalance": 1000.00,
  "lastUpdatedAt": "2026-04-14T15:41:00Z"
}
```

---

#### `GET /api/v1/dashboard/balance-history`

Returns portfolio balance snapshots for the area chart.

**Query Parameters:**
| Name | Type | Default | Description |
|------|------|---------|-------------|
| `days` | int | 30 | Number of days of history |

**Response 200:**
```json
{
  "series": [
    { "timestamp": "2026-03-15T00:00:00Z", "balanceUsd": 1012.30 },
    { "timestamp": "2026-03-16T00:00:00Z", "balanceUsd": 1018.50 }
  ]
}
```

*Source: `audit_cycles.portfolio_balance_usd` grouped by day (latest value per day).*

---

### 8.3 Positions

#### `GET /api/v1/positions`

Returns all currently open positions with live P&L.

**Response 200:**
```json
{
  "positions": [
    {
      "id": 42,
      "pair": "BTC/USD",
      "side": "buy",
      "entryPrice": 42000.00,
      "currentPrice": 43120.00,
      "volume": 0.0025,
      "usdInvested": 105.00,
      "currentValueUsd": 107.80,
      "pnlUsd": 2.80,
      "pnlPct": 2.67,
      "stopLossPrice": 39900.00,
      "takeProfitPrice": 45360.00,
      "stopLossPct": 5.0,
      "takeProfitPct": 8.0,
      "highestPriceSeen": 43250.00,
      "partialExited": false,
      "openedAt": "2026-04-13T22:01:00Z",
      "holdDurationSecs": 63540,
      "tpProgressPct": 33.75,
      "tier": 1,
      "slippagePct": 0.05
    }
  ],
  "totalCount": 10,
  "totalInvestedUsd": 925.30,
  "totalCurrentValueUsd": 951.18,
  "totalUnrealizedPnlUsd": 25.88,
  "totalUnrealizedPnlPct": 2.80
}
```

*`tpProgressPct` = `(pnlPct / takeProfitPct) × 100` — used to render the progress bar.*  
*Source: `paper_positions` JOIN `paper_wallet`; current price fetched from latest `audit_signals` or candle file.*

---

#### `GET /api/v1/positions/{id}/last-decision`

Returns the most recent LLM decision for the pair held in this position.

**Response 200:**
```json
{
  "positionId": 42,
  "pair": "BTC/USD",
  "decidedAt": "2026-04-14T15:41:00Z",
  "decisionType": "hold",
  "toolCalled": "hold",
  "holdReason": "Trade maturing well, no exit signal",
  "reasoningSummary": "BTC at +2.67% — still well below 4.8% Gate 2 threshold (60% of 8% TP)",
  "sellBlocked": false,
  "sellBlockedGate": null,
  "sellBlockedReason": null
}
```

*Source: `audit_llm_decisions` WHERE `pair = position.pair` ORDER BY `decided_at` DESC LIMIT 1.*

---

### 8.4 Trades

#### `GET /api/v1/trades`

Returns paginated closed trade history.

**Query Parameters:**
| Name | Type | Default | Description |
|------|------|---------|-------------|
| `page` | int | 1 | Page number (1-based) |
| `size` | int | 10 | Items per page (max 100) |
| `pair` | string | — | Filter by pair (e.g. `BTC/USD`) |
| `exitReason` | string | — | Filter by exit reason |
| `fromDate` | ISO date | — | Filter: opened after this date |
| `toDate` | ISO date | — | Filter: closed before this date |
| `sortBy` | string | `closedAt` | Sort field |
| `sortDir` | string | `desc` | `asc` or `desc` |

**Response 200:**
```json
{
  "trades": [
    {
      "id": 101,
      "pair": "BTC/USD",
      "side": "buy",
      "openedAt": "2026-04-13T14:01:00Z",
      "closedAt": "2026-04-14T10:32:00Z",
      "entryPrice": 42000.00,
      "exitPrice": 45360.00,
      "volume": 0.0025,
      "usdInvested": 105.00,
      "pnlUsd": 8.05,
      "pnlPct": 7.66,
      "exitReason": "take_profit",
      "holdDurationSecs": 73260,
      "feeUsd": 0.58,
      "stopLossPct": 5.0,
      "takeProfitPct": 8.0
    }
  ],
  "pagination": {
    "page": 1,
    "size": 10,
    "totalElements": 142,
    "totalPages": 15
  }
}
```

*Source: `paper_trades`.*

---

#### `GET /api/v1/trades/summary`

Returns aggregate trade statistics.

**Query Parameters:** `days` (int, default 30), `pair` (optional filter).

**Response 200:**
```json
{
  "totalTrades": 142,
  "wins": 78,
  "losses": 64,
  "winRatePct": 54.93,
  "avgPnlPct": 2.14,
  "avgWinPct": 6.82,
  "avgLossPct": -4.91,
  "profitFactor": 1.34,
  "grossWinsUsd": 421.30,
  "grossLossesUsd": 314.20,
  "netPnlUsd": 107.10,
  "exitReasonBreakdown": [
    { "reason": "take_profit",         "count": 62, "pnlUsd": 385.20 },
    { "reason": "stop_loss",           "count": 58, "pnlUsd": -289.60 },
    { "reason": "trailing_stop",       "count": 8,  "pnlUsd": 36.10 },
    { "reason": "agent_sell",          "count": 10, "pnlUsd": 24.60 },
    { "reason": "partial_take_profit", "count": 4,  "pnlUsd": 11.90 }
  ]
}
```

---

### 8.5 Pairs & Chart Data

#### `GET /api/v1/pairs`

Returns the list of all configured trading pairs with metadata.

**Response 200:**
```json
{
  "pairs": [
    {
      "pair": "BTC/USD",
      "tier": 1,
      "takeProfitPct": 8.0,
      "stopLossPct": 5.0,
      "buyMinScore": 5,
      "slippagePct": 0.05,
      "cautionFactorBearish": 1.0,
      "trailingStopEnabled": true,
      "partialTpEnabled": true,
      "active": true,
      "hasOpenPosition": true,
      "currentPrice": 43120.00
    }
  ]
}
```

*Source: `config.yaml` → `trading.pairs[]`. Current price from latest `audit_signals` or candle file.*

---

#### `GET /api/v1/pairs/{pair}/info`

Returns extended metadata for a single pair.

**Path parameter:** `pair` — URL-encoded, e.g. `BTC-USD` (hyphen separator in path, converted to `BTC/USD` internally).

**Response 200:**
```json
{
  "pair": "BTC/USD",
  "tier": 1,
  "takeProfitPct": 8.0,
  "stopLossPct": 5.0,
  "buyMinScore": 5,
  "slippagePct": 0.05,
  "rsiOversold": 30,
  "rsiOverbought": 75,
  "minVolumeRatio": 0.50,
  "obvNoise": 0.002,
  "trailingStop": {
    "enabled": true,
    "activateAfterPct": 3.0,
    "trailPct": 5.0
  },
  "cautionFactorBearish": 1.0,
  "correlationCluster": "btc",
  "currentPrice": 43120.00,
  "hasOpenPosition": true,
  "openPositionId": 42
}
```

---

#### `GET /api/v1/pairs/{pair}/candles`

Returns OHLCV candle data for charting.

**Query Parameters:**
| Name | Type | Default | Description |
|------|------|---------|-------------|
| `interval` | string | `15m` | Candle interval (only `15m` supported) |
| `limit` | int | 300 | Number of candles (max 500) |

**Response 200:**
```json
{
  "pair": "BTC/USD",
  "interval": "15m",
  "candles": [
    {
      "time": 1713052800,
      "open": 41980.00,
      "high": 42150.00,
      "low": 41820.00,
      "close": 42055.00,
      "volume": 1234.56
    }
  ]
}
```

*Source: `history/{PAIR}USD_candle.json` (or `BTCUSD_candle.json` format). Time = Unix timestamp (seconds).*

---

#### `GET /api/v1/pairs/{pair}/trades`

Returns all closed trades for a pair (for chart markers).

**Response 200:**
```json
{
  "pair": "BTC/USD",
  "trades": [
    {
      "id": 101,
      "time": 1713052800,
      "side": "buy",
      "price": 42000.00,
      "exitTime": 1713126720,
      "exitPrice": 45360.00,
      "exitReason": "take_profit",
      "pnlPct": 7.66
    }
  ]
}
```

---

#### `GET /api/v1/pairs/{pair}/signals`

Returns recent signal history for the pair.

**Query Parameters:** `limit` (int, default 20, max 100).

**Response 200:**
```json
{
  "pair": "BTC/USD",
  "signals": [
    {
      "id": 8801,
      "cycleId": 4128,
      "cycleAt": "2026-04-14T15:41:00Z",
      "price": 43120.00,
      "rsi14": 27.0,
      "macdLine": 45.2,
      "macdHistogram": 12.3,
      "ema9": 42900.00,
      "ema21": 42700.00,
      "ema50": 42100.00,
      "bbUpper": 44200.00,
      "bbMid": 43000.00,
      "bbLower": 41800.00,
      "atr14": 280.00,
      "signalDirection": "BUY",
      "signalStrength": 9.0,
      "signalReasons": "[+3] RSI oversold | [+2] F&G extreme | [+2] EMA uptrend | [+1] MACD pos | [+1] OBV acc"
    }
  ]
}
```

*Source: `audit_signals` WHERE `pair = ?` ORDER BY `id` DESC.*

---

#### `GET /api/v1/pairs/{pair}/decisions`

Returns LLM decision history for a pair.

**Query Parameters:** `limit` (int, default 20).

**Response 200:**
```json
{
  "pair": "BTC/USD",
  "decisions": [
    {
      "id": 5512,
      "cycleId": 4128,
      "decidedAt": "2026-04-14T15:41:00Z",
      "decisionType": "hold",
      "toolCalled": "hold",
      "holdReason": "Trade maturing, no exit signal",
      "reasoningSummary": "BTC holding well...",
      "promptTokens": 1840,
      "completionTokens": 120,
      "latencyMs": 1245
    }
  ]
}
```

---

### 8.6 Audit Log

#### `GET /api/v1/audit/cycles`

Returns paginated list of trading cycles.

**Query Parameters:** `page` (int, default 1), `size` (int, default 20, max 100), `mode` (string, optional), `fromDate`, `toDate`.

**Response 200:**
```json
{
  "cycles": [
    {
      "id": 4128,
      "mode": "paper",
      "cycleAt": "2026-04-14T15:41:00Z",
      "portfolioBalanceUsd": 1245.50,
      "availableCashUsd": 320.20,
      "openPositionsCount": 10,
      "dailyPnlUsd": 12.40,
      "dailyPnlPct": 1.00,
      "cycleDurationMs": 8210,
      "buyCount": 2,
      "sellCount": 0,
      "holdCount": 25
    }
  ],
  "pagination": { "page": 1, "size": 20, "totalElements": 4128, "totalPages": 207 }
}
```

---

#### `GET /api/v1/audit/cycles/{id}/decisions`

Returns all LLM decisions recorded in a specific cycle.

**Response 200:**
```json
{
  "cycleId": 4128,
  "decisions": [
    {
      "id": 5512,
      "pair": "BTC/USD",
      "decisionType": "buy",
      "toolCalled": "propose_buy",
      "toolArgs": "{\"pair\": \"BTC/USD\", \"usd_amount\": 105.30}",
      "reasoningSummary": "Strong oversold signal",
      "rawLlmOutput": "...",
      "promptTokens": 1840,
      "completionTokens": 120,
      "latencyMs": 1245,
      "riskCheck": {
        "approved": true,
        "rejectionReason": null,
        "adjustedUsdAmount": 105.30
      }
    }
  ]
}
```

---

#### `GET /api/v1/audit/decisions/{id}`

Returns a single LLM decision record (full raw output).

**Response 200:** Full `AuditLlmDecision` object including `rawLlmOutput`.

---

### 8.7 Agent Status

#### `GET /api/v1/agent/status`

Returns current agent health and operational state.

**Response 200:**
```json
{
  "mode": "paper",
  "isRunning": true,
  "lastCycleAt": "2026-04-14T15:41:00Z",
  "lastCycleId": 4128,
  "totalCycles": 4128,
  "totalLlmCalls": 12842,
  "circuitBreakerOpen": false,
  "circuitBreakerTier": 0,
  "killSwitchActive": false,
  "drawdownRecoveryActive": false,
  "dailyPnlPct": 1.00,
  "consecutiveStopLosses": 0,
  "heartbeatStatus": "ACTIVE",
  "lastHeartbeatAt": "2026-04-14T15:00:00Z",
  "uptimeSecs": 3600,
  "version": "1.0"
}
```

*Source: `agent_state` table keys + `audit_cycles` latest row + `paper_trades` for stop-loss count.*

---

### 8.8 Market Sentiment

#### `GET /api/v1/market/sentiment`

Returns cached macro sentiment values.

**Response 200:**
```json
{
  "fearGreedIndex": 12,
  "fearGreedLabel": "Extreme Fear",
  "btcDominancePct": 57.29,
  "btcDominanceTrend": "rising",
  "btcDominanceChangePp": 1.2,
  "mvrvZScore": null,
  "nupl": null,
  "cycleTopGuardActive": false,
  "fetchedAt": "2026-04-14T15:41:00Z"
}
```

*Source: `agent_state` keys `btc_dom_YYYY-MM-DD`, last `audit_cycles` row for F&G (or direct CoinGecko/alternative.me fetch with cache).*

---

### 8.9 System Config

#### `GET /api/v1/config`

Returns sanitized runtime configuration (no secrets, no API keys).

**Response 200:**
```json
{
  "trading": {
    "startingBalance": 1000.00,
    "maxOpenPositions": 10,
    "maxPositionPct": 20.0,
    "maxBuysPerCycle": 7,
    "minOrderUsd": 20.0,
    "minCashReservePct": 5.0,
    "cycleIntervalSecs": 900,
    "earlySellMinTpProximityPct": 60.0,
    "minProfitFloorPct": 1.0
  },
  "risk": {
    "stopLossGlobalPct": 5.0,
    "dailyLossLimitPct": 10.0,
    "killSwitchPct": -7.0,
    "drawdownRecovery": {
      "enabled": true,
      "triggerPct": -3.0,
      "exitPct": -1.5,
      "allowedPairs": ["BTC/USD", "ETH/USD", "BNB/USD"],
      "maxPositionPctOverride": 10.0
    }
  },
  "llm": {
    "model": "qwen3-32b",
    "provider": "groq",
    "fallbackModel": "llama-3.3-70b-versatile",
    "timeoutSecs": 120
  },
  "pairs": [
    {
      "pair": "BTC/USD",
      "tier": 1,
      "takeProfitPct": 8.0,
      "stopLossPct": 5.0,
      "buyMinScore": 5,
      "slippagePct": 0.05,
      "cautionFactorBearish": 1.0,
      "active": true
    }
  ]
}
```

---

## 9. Error Handling & Loading States

### Loading States
- **Skeleton loaders:** all table rows and stat cards render a gray animated shimmer while data loads.
- **Spinner:** full-screen spinner overlay for initial page load (auth check + first data fetch).

### Error States
- **API error:** inline error card with message and "Retry" button.
- **Auth expiry:** middleware detects 401 response → clear JWT → redirect to `/login`.
- **Empty state:** custom `EmptyState` component per screen (e.g. "No open positions" with icon).

### Toast Notifications
- Auto-refresh success: no toast (silent).
- Auth error: toast `"Session expired — please log in again"`.
- 500 errors: toast `"Server error — data may be stale"`.

---

## 10. Security Model

| Concern | Implementation |
|---|---|
| Authentication | Telegram OAuth; HMAC-SHA256 hash verification on server |
| Session token | JWT (HS256); 24-hour expiry; stored in `localStorage` |
| Auth guard | Client-side route guard + server-side JWT validation on every request |
| Secrets in config | `GET /api/v1/config` strips `api_key`, `api_secret`, `bot_token`, `chat_id` |
| CORS | Spring CORS config: allow only `http://localhost:3000` (configurable) |
| HTTPS | Enforce in production via reverse proxy (Nginx/Caddy) |
| SQL injection | All DB queries use prepared statements (Spring Data / named parameters) |
| Input validation | All query params validated and bounded (`size ≤ 100`, `days ≤ 365`) |
| Rate limiting | Spring Boot rate limiter on `/api/v1/auth/telegram` (5 req/min per IP) |
| No write endpoints | UI is read-only monitoring — no trade execution endpoints exposed |
