# Kryptos: Autonomous Crypto Trading System Architecture & BRD

## 1. Business Requirement
**Objective:** Develop a fully autonomous, high-frequency cryptocurrency trading agent capable of operating on the Kraken exchange. The system aims for capital preservation first, combined with a convex return profile targeting consistent weekly net gains.
**Key Requirements:**
*   **Dual Mode:** Must support Zero-Risk Paper Trading and Real-Money Live Trading.
*   **Asset Coverage:** Multi-symbol concurrent watchlist (15 pairs including BTC, ETH, SOL, etc.).
*   **Fee Mitigation:** Must interact exclusively as a "Maker" using Post-Only Limit orders to capture exchange fee rebates/discounts.
*   **LLM Orchestration:** Leverage a local/cloud LLM to synthesize technical indicators and sentiment, but *never* allow the LLM to control absolute risk parameters (Stop Loss).
*   **Risk First:** Must survive flash crashes, API anomalies, "dust" increment limits, and high-volatility "whipsaw" market dead-zones.

---

## 2. Conceptual Design
Kryptos uses a **Layered, Deterministic Swarm Architecture** to prevent LLM hallucinations from causing financial ruin.
1.  **Data Ingestion Layer:** Streams L2 Order Book Imbalance (OBI) and 15-min OHLCV candles via WebSockets/REST.
2.  **Quantitative Layer:** Normalizes market data into technical metrics (EMA, MACD, RSI, ATR, Volume SMA).
3.  **Cognitive Layer (LLM):** Ingests purely normalized statistical data (not raw prices) and output standard JSON tool-calls (`propose_buy`, `propose_sell`, `hold`).
4.  **Risk & Compliance Guard Layer (The Veto):** A hard-coded mathematical firewall. Intercepts the LLM's `propose_buy/sell` and dynamically approves, resizes, or outright rejects the execution based on strict bounds.
5.  **Execution Layer:** Translates approved intents into precise Exchange API calls respecting exchange tick/lot increments.
6.  **Audit Layer:** Logs every signal, LLM thought, risk rejection, and balance snapshot into SQLite.

---

## 3. Detailed Design

### 3.1 Database Schema (SQLite)
*   `audit_signals`: Raw technicals (MACD, RSI, volume ratio) per cycle.
*   `audit_llm_decisions`: Reconstructed chain-of-thought and JSON tool-calls.
*   `audit_risk_checks`: Rejection/Approval reasons for every intent.
*   `paper_positions` / `live_positions`: Active trade state (ID, pair, entry, qty, SL, TP).

### 3.2 Quantitative & Risk Framework
*   **Trend & Momentum:** Price > EMA 50 (Macro Trend). EMA 9 > EMA 21 (Micro Momentum).
*   **Volatility Regime (ATR):** Sizing = `Risk Amount / (ATR * Multiplier)`. Dynamic Take Profit = `Entry + (k * ATR)`.
*   **Stop Loss (Hard Capped):** `min(Entry * 0.95, Entry - (ATR * Multiplier))`. LLM cannot override this 5% trapdoor.
*   **Time-of-Day Filter:** Trading permitted *only* between 16:00 and 20:00 UTC (New York/London overlap) to avoid low-volume fakeouts.
*   **Minimum Profit Floor:** Hard 1.0% expected PNL gate before manual sales are authorized to ensure Maker/Taker fees + slippage are completely covered.
*   **Global Kill Switch:** If daily portfolio drawdown hits `-7.0%`, system halts all agent activity and market-sells all bags.
*   **Fat Finger Guard:** No trades authorized utilizing > 98% of available cash buffer; prevents API `Insufficient Funds` crashes.

### 3.3 LLM Aspects
*   **Context:** `application/json` output enforced. The prompt is injected with the rules from `.claude/skills/trading-rules/SKILL.md`.
*   **Tools:** Standardized function calling via Pydantic schemas.

---

## 4 & 5. Epics, User Stories, AC, and Code Association

| Epic | User Story | Acceptance Criteria (AC) | Associated Code |
| :--- | :--- | :--- | :--- |
| **E1: Market Data** | As a system, I need L2 data to find entry points. | WS connects to `ticker` & `ohlc`. Computes OBI = (BidV-AskV)/(BidV+AskV). | `exchange/websocket_feed.py` |
| **E2: Quant Indicators** | As an analyst, I need RSI, MACD, and Volume SMA. | Returns normalized dictionary of signals. Rejects if Vol drops >50%. | `analysis/indicators.py`, `signals.py` |
| **E3: AI Engine** | As an agent, I want to rank pairs and propose trades. | Uses `propose_buy/sell/hold`. Prompt rejects raw conversational text. | `agent/prompts.py`, `agent/tools.py` |
| **E4: Risk Manager** | As a compliance bot, I intercept all LLM requests. | Blocks out-of-hours, sub-minimum profit (1%), and fat finger sizes. | `risk/risk_manager.py` |
| **E5: Execution** | As a broker, I want to minimize taker fees. | Uses `postOnly: True`. 60-second limit chase logic implemented. Applies exchange increments precisely. | `exchange/kraken_client.py` |
| **E6: Telemetry** | As a user, I want status guarantees. | 15-min HTTP Webhook pings. 2-hr Telegram heartbeat. 6-hr PNL report. | `notifications/notifier.py`, `main.py` |

---

## 7. Setup Document

### Native Python Setup
1. Define environment variables in `.env` (`KRAKEN_API_KEY`, `KRAKEN_API_SECRET`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `OLLAMA_BASE_URL`).
2. Install locked dependencies: `pip install -r requirements.txt`
3. Set up Ollama with the desired model (e.g., `ollama pull qwen2.5:14b`).
4. Configure `config.yaml` risk limits and trading pairs.
5. Run Paper: `python main.py --paper`
6. Run Live: `python main.py --live`

### Standard Containerized Setup (Target Architecture)
Create a `Dockerfile`:
```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["python", "main.py", "--live"]
```
Run detached:
```bash
docker build -t kryptos-agent .
docker run -d --env-file .env kryptos-agent
```

---

## 8. Bug Report and Status

| Bug / Vulnerability | Status | Mitigation Applied |
| :--- | :--- | :--- |
| **Execution Gap Latency** | CLOSED | Price is re-fetched at exact millisecond of tool execution native to Python. |
| **"Dust" Increment Errors** | CLOSED | CCXT `amount_to_precision()` and `price_to_precision` strictly truncate floating decimals to match Kraken exchange rules constraints. |
| **Limit Instant Fill Crash** | CLOSED | Native SL/TP creation is dynamically deferred until the parent Post-Only Limit entry reports `status == 'closed'`. |
| **Fallback Abandonment** | CLOSED | If fallback SL/TP hits locally, code explicitly cancels pending native limits and fires Market orders. |
| **Historical Backtest Clock** | CLOSED | Time-Of-Day guard now evaluates the historical `candle_timestamp` instead of the user's `datetime.now()` clock. |
| **Fat Finger / Missing Buffer**| CLOSED | `RiskManager` actively prevents trades utilizing over 98% of available capital remaining (2% dedicated fee buffer). |
