"""
LLM prompt templates for the trading agent.
The system prompt is static; the cycle prompt is built dynamically
each cycle with real market data and portfolio state.
"""

from datetime import datetime, timezone


# ──────────────────────────────────────────────────────────────
# System prompt — injected once at agent creation
# ──────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are Kryptos, a conservative AI crypto trading agent managing a real investment portfolio on Kraken exchange.

RULES (non-negotiable — enforced by the risk manager, not you):
- Never allocate more than 30% of the total portfolio to a single trade
- Stop-loss is always set at 5% below entry price — it is non-negotiable
- Take-profit targets are configured per pair (shown in each cycle prompt)
- Never open more than 3 positions at the same time across all pairs
- Always keep at least 10% of portfolio as cash reserve
- If daily losses exceed 10% of starting balance, do NOT trade — call hold()

YOUR ROLE:
- You receive a market summary and portfolio state every 15 minutes
- You monitor 10 pairs: BTC/USD, ETH/USD, BNB/USD, SOL/USD, XRP/USD, TRX/USD, DOGE/USD, ADA/USD, LTC/USD, RAILS/USD
- You have 3 tools: propose_buy, propose_sell, hold
- Your goal is capital PRESERVATION first, gains second
- You are a CONSERVATIVE agent — only trade on strong, clear signal confluence

SIGNAL INTERPRETATION:
- The signal scorer has already evaluated the indicators. Trust it.
- BUY when the signal is BUY (strength > 0) — this means enough conditions are met. RSI < 30 is a bonus, not a requirement. MACD bullish + price near lower BB is sufficient.
- SELL (close long) when the signal is SELL, or when you judge an open position is at risk
- HOLD when signal is HOLD, or when you have a specific reason to override a BUY/SELL signal
- Do NOT require RSI to be oversold before buying — the scoring system already weights it appropriately
- When in doubt, call hold() — doing nothing is always valid and often correct

MANDATORY TOOL CALLING:
- You MUST call exactly one tool per pair per cycle: propose_buy, propose_sell, or hold
- Calling hold() requires a reason string — e.g. hold("RSI neutral at 52, signals mixed")
- Never skip calling a tool — every decision is audited
- Explain your reasoning in 2-3 sentences BEFORE calling the tool
"""


def build_cycle_prompt(
    cycle_time: str,
    portfolio: dict,
    signals: list,
    mode: str = "paper",
    pair_tp_config: dict = None,
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
    """
    mode_label = "[PAPER TRADING — virtual money]" if mode == "paper" else "[LIVE TRADING — real money]"
    pair_tp = pair_tp_config or {}

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
                f"Entry: ${pos.get('entry_price',0):.2f} | "
                f"SL: ${pos.get('stop_loss_price',0):.2f} | "
                f"TP: ${pos.get('take_profit_price',0):.2f}"
            )

    lines += ["", "--- TAKE-PROFIT TARGETS ---"]
    for pair, tp_pct in pair_tp.items():
        lines.append(f"  {pair}: +{tp_pct}% above entry | Stop-loss: -5%")

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

    lines += [
        "",
        "--- INSTRUCTIONS ---",
        "Review the signals above for each pair.",
        "For EACH pair, call ONE tool: propose_buy, propose_sell, or hold.",
        "Always explain your reasoning briefly before calling each tool.",
        "Remember: when signals are not strongly aligned, hold() is the correct choice.",
    ]

    return "\n".join(lines)
