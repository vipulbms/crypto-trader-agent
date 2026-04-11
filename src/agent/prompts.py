"""
LLM prompt templates for the trading agent.
The system prompt is static; the cycle prompt is built dynamically
each cycle with real market data and portfolio state.
"""

import os
from datetime import datetime, timezone


# ──────────────────────────────────────────────────────────────
# System prompt — injected once at agent creation
# ──────────────────────────────────────────────────────────────

# Dynamically load the trading rules from the SKILL.md file to avoid duplication
SKILL_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 
    ".claude", "skills", "trading-rules", "SKILL.md"
)

try:
    with open(SKILL_PATH, "r", encoding="utf-8") as f:
        TRADING_RULES = f.read().strip()
except FileNotFoundError:
    TRADING_RULES = "[WARNING: .claude/skills/trading-rules/SKILL.md file not found.]"

SYSTEM_PROMPT = f"""You are Kryptos, a quantitative AI crypto trading agent managing a real investment portfolio on Kraken exchange.

{TRADING_RULES}
"""

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
        f"Max per new trade:    ${portfolio['max_per_trade']:.2f}  (20% of ${portfolio['total_usd']:.2f}, regime-adjusted)",
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
    for block_key in ("regime", "cycle_top", "sentiment", "patterns", "exit_timing",
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

        pair_max_usd = sig.get("pair_max_usd")
        pair_tier = sig.get("pair_tier")
        tier_label = {
            1: "macro reserve",
            2: "core infrastructure",
            3: "speculative altcoin",
            4: "meme/momentum",
        }.get(pair_tier)
        pair_max_line = f"Max buy size:  ${pair_max_usd:.2f}  (regime-adjusted for this pair)" if pair_max_usd is not None else None
        pair_tier_line = f"Tier:          {pair_tier} ({tier_label})" if pair_tier and tier_label else None

        pair_block = [
            "",
            f"--- {pair} ---",
            f"Price:         ${price:.4f}",
            f"RSI(14):       {f'{rsi:.1f}' if rsi else 'N/A'}",
            f"MACD Hist:     {f'{macd:.4f}' if macd else 'N/A'}",
            f"BB Lower/Upper: ${f'{bb_l:.2f}' if bb_l else 'N/A'} / ${f'{bb_u:.2f}' if bb_u else 'N/A'}",
            f"ATR(14):       {f'{atr:.4f}' if atr else 'N/A'}",
            pair_tier_line,
            f"Signal:        {signal}  (strength: {strength:.2f})",
            f"Reasons:       {', '.join(reasons) if reasons else 'None'}",
        ]
        pair_block = [line for line in pair_block if line is not None]
        if pair_max_line:
            pair_block.append(pair_max_line)
        lines += pair_block

    # ── Ranking task instructions ─────────────────────────────────
    lines += [
        "",
        "--- YOUR TASK THIS CYCLE ---",
        f"You have {len(signals)} pairs above. {len(buy_signals)} have BUY signals. {len(sell_signals)} have SELL signals.",
        "1. Rank all BUY-signalling pairs by strength (highest), RSI depth below 30, and MACD histogram magnitude.",
        f"2. Call propose_buy for your top {max_buys_per_cycle} picks ranked by signal strength — skip weaker signals even if they are BUY. Use the suggested size from the POSITION SIZES block. Never pass less than ${min_order_usd:.0f} as usd_amount.",
        "3. Review all open positions. Call propose_sell for any with Signal=SELL and clear momentum reversal.",
        "4. Do NOT call any tool for pairs you are not acting on — they are automatically held.",
        "5. Reason briefly (1-2 sentences) before each tool call.",
        "6. If no pairs meet your quality bar, make zero calls — do not force trades.",
        "7. If a [CYCLE TOP WARNING] block is present, treat Tier 3 / Tier 4 BUYs as blocked even if their raw setup looks strong.",
    ]

    return "\n".join(lines)
