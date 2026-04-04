"""
LLM prompt templates for the trading agent.
The system prompt is static; the cycle prompt is built dynamically
each cycle with real market data and portfolio state.
"""

from datetime import datetime, timezone


# ──────────────────────────────────────────────────────────────
# System prompt — injected once at agent creation
# ──────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are Kryptos, a quantitative AI crypto trading agent managing a real investment portfolio on Kraken exchange.

RULES (non-negotiable — enforced by the risk manager):
- Position Sizes are volatility-adjusted (ATR-proportional) to keep Dollar Risk constant
- Stop-loss is dynamically set based on Volatility (Multiplier * ATR) but strictly capped at 5% maximum
- Take-profit targets are mathematically set as EntryPrice + (k * ATR) based on the asset's current volatility regime
- All orders must be LIMIT orders placed at the Bid price
- Trades are completely BLOCKED if Order Book Imbalance (OBI) is negative or if Price is below EMA 50
- Never open more than 3 positions at the same time across all pairs
- Always keep at least 10% of portfolio as cash reserve
- If daily losses exceed 10% of starting balance, do NOT trade

YOUR ROLE:
- You receive a market summary and portfolio state every 15 minutes
- You monitor 15 pairs: BTC/USD, ETH/USD, BNB/USD, SOL/USD, XRP/USD, TRX/USD, DOGE/USD, ADA/USD, LTC/USD, RAILS/USD, AVAX/USD, SUI/USD, HYPE/USD, UNI/USD, INJ/USD
- You have 3 tools: propose_buy, propose_sell, hold
- Your goal is capital PRESERVATION first, gains second. You are a CONSERVATIVE agent.

DECISION STYLE — RANKED MULTI-PAIR:
- Review all signals. You may call propose_buy AT MOST 3 times per cycle — only for the strongest BUY signals that have positive OBI.
- Rank BUY candidates by: signal strength, OBI positivity, momentum (EMA 9 > 21), and MACD histogram magnitude.
- You may call propose_sell for ANY open position where:
    a. Signal = SELL with clear momentum reversal (MACD crossed negative, RSI overbought above 65), AND the position P&L is above +2%, OR
    b. Position has already reached at least 80% of its dynamic ATR take-profit target AND is showing a confirmed reversal.
- Stop-loss exits are handled automatically by the risk manager — never call propose_sell just because price dropped.

OVERRIDE RULES:
- Do not propose_buy if: already holding, cash below reserve, max positions reached, or OBI is negative.
- Do NOT propose_sell on a position with P&L below +2% for any reason — let the dynamic stop-loss handle it.
- If no pairs meet your quality bar for BUY, make zero calls.

MANDATORY TOOL CALLING:
- Call tools ONLY for pairs you are acting on. All others are implicitly held.
- Explain your reasoning in 1-2 sentences BEFORE each tool call.
"""


def build_cycle_prompt(
    cycle_time: str,
    portfolio: dict,
    signals: list,
    mode: str = "paper",
    pair_tp_config: dict = None,
    ai_context: dict = None,
) -> str:
    """
    Build the per-cycle user message injected into the LLM context.

    portfolio: {
        "total_usd": float,
        "available_cash_usd": float,
        "open_positions_count": int,
        "daily_pnl_usd": float,
        "daily_pnl_pct": float,
        "open_positions": list of dicts,
        "max_per_trade": float,
    }
    signals: list of signal dicts (one per pair)
    pair_tp_config: {"BTC/USD": 8, "ETH/USD": 12, ...}
    ai_context: dict of context blocks from features.build_ai_context()
    """
    mode_label = "[PAPER TRADING — virtual money]" if mode == "paper" else "[LIVE TRADING — real money]"
    pair_tp = pair_tp_config or {}
    ctx = ai_context or {}

    # Count BUY signals for the task header
    buy_signals = [s for s in signals if s.get("signal") == "BUY"]
    sell_signals = [s for s in signals if s.get("signal") == "SELL"]

    lines = [
        f"=== CYCLE: {cycle_time} SGT {mode_label} ===",
        "",
        "--- PORTFOLIO STATE ---",
        f"Total Balance:        ${portfolio['total_usd']:.2f}",
        f"Available Cash:       ${portfolio['available_cash_usd']:.2f}",
        f"Open Positions:       {portfolio['open_positions_count']}",
        f"Daily P&L:            ${portfolio['daily_pnl_usd']:+.2f} ({portfolio['daily_pnl_pct']:+.2f}%)",
        f"Max per new trade:    ${portfolio['max_per_trade']:.2f}  (30% of ${portfolio['total_usd']:.2f})",
    ]

    if portfolio.get("open_positions"):
        lines.append("")
        for pos in portfolio["open_positions"]:
            lines.append(
                f"  {pos.get('pair','?')}: {pos.get('volume',0):.6f} | "
                f"USD: ${pos.get('usd_value',0):.2f} | "
                f"Entry: ${pos.get('entry_price',0):.2f} | "
                f"SL: ${pos.get('stop_loss_price',0):.2f} | "
                f"TP: ${pos.get('take_profit_price',0):.2f}"
            )

    # ── AI Context blocks (features 1–6) ──────────────────────────
    for block_key in ("regime", "sentiment", "patterns", "exit_timing",
                      "position_sizing", "dynamic_tp"):
        block = ctx.get(block_key, "")
        if block:
            lines += ["", block]

    lines += ["", "--- TAKE-PROFIT TARGETS ---"]
    for pair, tp_pct in pair_tp.items():
        lines.append(f"  {pair}: +{tp_pct}% above entry | Stop-loss: -5%")

    # ── Per-pair signal data ──────────────────────────────────────
    for sig in signals:
        pair      = sig["pair"]
        signal    = sig["signal"]
        strength  = sig["strength"]
        price     = sig["price"]
        indicators= sig.get("indicators", {})
        reasons   = sig.get("reasons", [])

        rsi  = indicators.get("rsi_14")
        macd = indicators.get("macd_histogram")
        atr  = indicators.get("atr_14")
        bb_l = indicators.get("bb_lower")
        bb_u = indicators.get("bb_upper")

        lines += [
            "",
            f"--- {pair} ---",
            f"Price:         ${price:.4f}",
            f"RSI(14):       {f'{rsi:.1f}' if rsi else 'N/A'}",
            f"MACD Hist:     {f'{macd:.4f}' if macd else 'N/A'}",
            f"BB Lower/Upper: ${f'{bb_l:.2f}' if bb_l else 'N/A'} / ${f'{bb_u:.2f}' if bb_u else 'N/A'}",
            f"ATR(14):       {f'{atr:.4f}' if atr else 'N/A'}",
            f"Signal:        {signal}  (strength: {strength:.2f})",
            f"Reasons:       {', '.join(reasons) if reasons else 'None'}",
        ]

    # ── Ranking task instructions ─────────────────────────────────
    lines += [
        "",
        "--- YOUR TASK THIS CYCLE ---",
        f"You have {len(signals)} pairs above. {len(buy_signals)} have BUY signals. {len(sell_signals)} have SELL signals.",
        "1. Rank all BUY-signalling pairs by strength (highest), RSI depth below 30, and MACD histogram magnitude.",
        "2. Call propose_buy for your TOP 3 picks only — skip weaker signals even if they are BUY.",
        "3. Review all open positions. Call propose_sell for any with Signal=SELL and clear momentum reversal.",
        "4. Do NOT call any tool for pairs you are not acting on — they are automatically held.",
        "5. Reason briefly (1-2 sentences) before each tool call.",
        "6. If no pairs meet your quality bar, make zero calls — do not force trades.",
    ]

    return "\n".join(lines)
