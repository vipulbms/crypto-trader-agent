"""
LLM prompt templates for the trading agent.
The system prompt is static; the cycle prompt is built dynamically
each cycle with real market data and portfolio state.
"""

import os
from datetime import datetime, timezone


# ──────────────────────────────────────────────────────────────
# System prompt — fallback only; real value sourced from config.yaml llm.system_prompt
# ──────────────────────────────────────────────────────────────

SYSTEM_PROMPT = "You are Kryptos, a quantitative AI crypto trading agent."

def build_cycle_prompt(
    cycle_time: str,
    portfolio: dict,
    signals: list,
    mode: str = "paper",
    pair_tp_config: dict = None,
    ai_context: dict = None,
    max_buys_per_cycle: int = 7,
    min_order_usd: float = 20.0,
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

    # Only actionable signals go to the LLM — HOLDs are implicit, no LLM input needed
    buy_signals  = [s for s in signals if s.get("signal") == "BUY"]
    sell_signals = [s for s in signals if s.get("signal") == "SELL"]
    hold_count   = len(signals) - len(buy_signals) - len(sell_signals)
    actionable   = buy_signals + sell_signals

    lines = [
        f"=== CYCLE: {cycle_time} SGT {mode_label} ===",
        "",
        "--- PORTFOLIO STATE ---",
        f"Total Balance:        ${portfolio['total_usd']:.2f}",
        f"Available Cash:       ${portfolio['available_cash_usd']:.2f}",
        f"Open Positions:       {portfolio['open_positions_count']}",
        f"Daily P&L:            ${portfolio['daily_pnl_usd']:+.2f} ({portfolio['daily_pnl_pct']:+.2f}%)",
        f"Max per new trade:    ${portfolio['max_per_trade']:.2f}  (30% of ${portfolio['total_usd']:.2f}, regime-adjusted)",
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

    # ── AI Context blocks — actionable context only ────────────────
    # patterns / position_sizing / dynamic_tp omitted (redundant with per-pair data)
    for block_key in ("regime", "cycle_top", "sentiment", "exit_timing"):
        block = ctx.get(block_key, "")
        if block:
            lines += ["", block]

    # ── Per-pair signal data (BUY + SELL only — HOLDs omitted) ────
    for sig in actionable:
        pair      = sig["pair"]
        signal    = sig["signal"]
        strength  = sig["strength"]
        price     = sig["price"]
        indicators= sig.get("indicators", {})
        reasons   = sig.get("reasons", [])

        rsi  = indicators.get("rsi_14")
        macd = indicators.get("macd_histogram")

        pair_max_usd = sig.get("pair_max_usd")
        pair_tier = sig.get("pair_tier")
        tier_label = {
            1: "macro reserve",
            2: "core infrastructure",
            3: "speculative altcoin",
            4: "meme/momentum",
        }.get(pair_tier)
        tier_max_line = (
            f"Tier {pair_tier} ({tier_label}) | Max buy: ${pair_max_usd:.2f}"
            if pair_tier and tier_label and pair_max_usd is not None
            else (f"Tier {pair_tier} ({tier_label})" if pair_tier and tier_label else None)
        )

        pair_block = [
            "",
            f"--- {pair} ---",
            f"Price:         ${price:.4f}",
            f"RSI(14):       {f'{rsi:.1f}' if rsi else 'N/A'}",
            f"MACD Hist:     {f'{macd:.4f}' if macd else 'N/A'}",
            tier_max_line,
            f"Signal:        {signal}  (strength: {strength:.2f})",
            f"Reasons:       {', '.join(reasons) if reasons else 'None'}",
        ]
        pair_block = [line for line in pair_block if line is not None]
        lines += pair_block

    # ── Task instructions ──────────────────────────────────────────
    lines += [
        "",
        "--- YOUR TASK THIS CYCLE ---",
        f"{len(buy_signals)} BUY and {len(sell_signals)} SELL signals shown. {hold_count} HOLD pairs omitted.",
        "1. Rank BUY pairs by strength, RSI depth below oversold, and MACD histogram magnitude.",
        f"2. Call propose_buy for your top {max_buys_per_cycle} picks. Use the Max buy size shown per pair. Never pass less than ${min_order_usd:.0f}.",
        "3. Call propose_sell for SELL-signal open positions with confirmed momentum reversal.",
        "4. Reason briefly (1 sentence) before each tool call. Make zero calls if no pairs meet your bar.",
        "5. If a [CYCLE TOP WARNING] block is present, treat Tier 3 / Tier 4 BUYs as blocked.",
        "6. If any macro block shows 'unavailable', rely on the technical signal scores and reasons alone. Missing macro data is NOT a reason to hold.",
    ]

    return "\n".join(lines)
