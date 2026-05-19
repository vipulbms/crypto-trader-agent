"""
LLM prompt templates for the trading agent.
The system prompt is built dynamically per persona (S14.2.4);
the cycle prompt is built dynamically each cycle with real market data and
portfolio state.

Story: S14.2.3 (unfilled cluster context), S14.2.4 (persona system role)
Sprint: S4
Author: Kryptos Squad
"""

import logging
import os
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────
# S14.2.4 — Persona-scoped system prompt builder
# (Replaces static SYSTEM_PROMPT)
# ──────────────────────────────────────────────────────────────

# Kept for backward-compat import in trading_agent.py during transition
SYSTEM_PROMPT = (
    "You are Kryptos, a quantitative AI crypto trading agent. "
    "Position accumulation is permitted under specific conditions (see POSITION ACCUMULATION LOGIC)."
)

_PERSONA_ROLES = {
    "conservative": (
        "You are Kryptos operating in CONSERVATIVE mode — Capital Preservation Advisor.\n"
        "Your primary mandate is to protect the portfolio against drawdown.\n"
        "Avoid early buys. Only enter positions when confluence is unambiguous.\n"
        "Never override the minimum profit floor. Prefer fewer, higher-conviction trades.\n"
    ),
    "medium": (
        "You are Kryptos operating in MEDIUM mode — Balanced Portfolio Manager.\n"
        "Balance momentum capture with capital protection.\n"
        "Prioritise sector rotation — avoid doubling down on correlated pairs.\n"
        "Enter trending moves confidently but respect the risk constraints block.\n"
    ),
    "high": (
        "You are Kryptos operating in HIGH mode — Alpha-Seeking Fund Manager.\n"
        "Capture breakouts aggressively. Reallocation of weaker positions is authorised.\n"
        "Front-run institutional accumulation by entering early on strong ADX/MACD signals.\n"
        "Maximise deployed capital but never exceed per-pair size caps.\n"
    ),
}

_SHARED_RULES = (
    "HARD RULES (non-negotiable):\n"
    "1. Do NOT propose_buy when kill_switch=1 or circuit_open=1.\n"
    "2. Never pass less than the min_order_usd shown in RISK CONSTRAINTS.\n"
    "3. Call propose_sell only when P&L > +2% AND reversal is confirmed.\n"
    "4. Reason briefly (1 sentence) before each tool call.\n"
    "5. If cycle top warning is active, treat Tier 3/4 BUYs as blocked.\n"
    "6. Use POSITION ACCUMULATION LOGIC to decide when to buy existing portfolio pairs.\n"
    "\n"
    "POSITION ACCUMULATION LOGIC (proposal_buy intent parameter):\n"
    "• If pair is in CURRENT PORTFOLIO with P&L > +5% AND tp_dist_pct > 30%: use intent='accumulate' to scale in.\n"
    "• If pair is in CURRENT PORTFOLIO with P&L < 0% OR tp_dist_pct < 15%: SKIP proposal_buy (wait for exit).\n"
    "• If pair is in CURRENT PORTFOLIO with 0% ≤ P&L ≤ +5% OR 15% ≤ tp_dist_pct ≤ 30%: HOLD (no decision).\n"
    "• If pair NOT in CURRENT PORTFOLIO: use intent='new_entry' (normal buy).\n"
    "• Never accumulate if position size > 60% of max per-pair size shown in CURRENT PORTFOLIO.\n"
)


def build_system_prompt(persona_config: dict) -> str:
    """
    Build a persona-specific LLM system prompt (S14.2.4, AC1–AC5).

    Args:
        persona_config: The dict at config["personas"][active_persona].

    Returns:
        Full system prompt string ≤ 400 tokens.
    """
    role_key = persona_config.get("llm_system_role", "medium")
    # Match by key; fall back to medium if unknown variant
    role_text = _PERSONA_ROLES.get(role_key, _PERSONA_ROLES["medium"])
    prompt = role_text + "\n" + _SHARED_RULES
    # Sanity-log if over 400 token estimate
    if len(prompt) // 4 > 400:
        logger.warning(
            "[AIE] build_system_prompt: estimated %d tokens for role=%s (target ≤ 400)",
            len(prompt) // 4, role_key,
        )
    return prompt


# ──────────────────────────────────────────────────────────────
# S14.1.2 — Token estimator (character ÷ 4 approximation, no external dep)
# ──────────────────────────────────────────────────────────────

def estimate_tokens(prompt: str) -> int:
    """Estimate LLM token count using character count ÷ 4 approximation (S14.1.2 AC1)."""
    return len(prompt) // 4


# ──────────────────────────────────────────────────────────────
# S14.1.1 — Pipe-format signal block builder
# ──────────────────────────────────────────────────────────────

def build_pipe_signal_block(
    signal: dict,
    pair_tp_config: dict = None,
    regime: str = "N/A",
) -> str:
    """
    Encode a single pair's signal as a pipe-separated line (S14.1.1).
    Output: pair|{p}|score|{n}/28|direction|{d}|rsi|{r}|adx|{a}|macd_hist|{h}|
            bb_pos|{b}|regime|{r}|price|{p}|tp_pct|{t}|sl_pct|5|max_buy_usd|{m}
    """
    pair = signal["pair"]
    direction = signal["signal"]
    inds = signal.get("indicators", {})

    max_score = signal.get("max_score", 28)
    score = signal.get("buy_score", 0) if direction == "BUY" else signal.get("sell_score", 0)

    rsi = inds.get("rsi_14")
    adx = inds.get("adx_14")
    macd_hist = inds.get("macd_histogram")
    price = signal.get("price", 0) or 0
    bb_lower = inds.get("bb_lower")
    bb_upper = inds.get("bb_upper")

    # BB position: 0.0 = at lower band, 1.0 = at upper band
    if bb_upper and bb_lower and bb_upper != bb_lower and price:
        bb_pos: float | None = (price - bb_lower) / (bb_upper - bb_lower)
    else:
        bb_pos = None

    tp_pct = (pair_tp_config or {}).get(pair, "N/A")
    max_buy_usd = signal.get("pair_max_usd") or 0

    def _v(val, fmt: str) -> str:
        return fmt.format(val) if val is not None else "N/A"

    return (
        f"pair|{pair}|score|{score}/{max_score}"
        f"|direction|{direction}"
        f"|rsi|{_v(rsi, '{:.0f}')}"
        f"|adx|{_v(adx, '{:.0f}')}"
        f"|macd_hist|{_v(macd_hist, '{:.4f}')}"
        f"|bb_pos|{_v(bb_pos, '{:.2f}')}"
        f"|regime|{regime}"
        f"|price|{price:.4f}"
        f"|tp_pct|{tp_pct}"
        f"|sl_pct|5"
        f"|max_buy_usd|{max_buy_usd:.0f}"
    )


# ──────────────────────────────────────────────────────────────
# Main cycle prompt builder
# ──────────────────────────────────────────────────────────────

def build_cycle_prompt(
    cycle_time: str,
    portfolio: dict,
    signals: list,
    mode: str = "paper",
    pair_tp_config: dict = None,
    ai_context: dict = None,
    max_buys_per_cycle: int = 7,
    min_order_usd: float = 20.0,
    risk_state: dict = None,
    unfilled_clusters: list = None,
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
    risk_state: {kill_switch, circuit_open, playbook, persona, positions_max} (S14.2.2)
    unfilled_clusters: list of cluster names with open slots (S14.2.3)
    """
    mode_label = "[PAPER TRADING — virtual money]" if mode == "paper" else "[LIVE TRADING — real money]"
    pair_tp = pair_tp_config or {}
    ctx = ai_context or {}
    rs = risk_state or {}

    # Only actionable signals go to the LLM — HOLDs are implicit, no LLM input needed
    buy_signals  = [s for s in signals if s.get("signal") == "BUY"]
    sell_signals = [s for s in signals if s.get("signal") == "SELL"]
    hold_count   = len(signals) - len(buy_signals) - len(sell_signals)
    actionable   = buy_signals + sell_signals

    # Dedup guard: ensure no duplicate pairs reach the LLM
    seen_pairs = set()
    actionable_dedup = []
    for sig in actionable:
        pair = sig.get("pair", "")
        if pair in seen_pairs:
            logger.warning("[PROMPT] Duplicate pair in actionable signals: %s — skipping", pair)
            continue
        seen_pairs.add(pair)
        actionable_dedup.append(sig)

    if len(actionable_dedup) < len(actionable):
        logger.warning(
            "[PROMPT] Removed %d duplicate pairs from LLM prompt (%d → %d actionable)",
            len(actionable) - len(actionable_dedup), len(actionable), len(actionable_dedup),
        )
    actionable = actionable_dedup

    lines = [
        f"=== CYCLE: {cycle_time} SGT {mode_label} ===",
        "",
    ]

    # ── S14.2.2 — Risk constraints block (persona-driven) ──────────────────────────
    positions_open = portfolio.get("open_positions_count", 0)
    positions_max  = rs.get("positions_max", 10)
    kill_switch    = 1 if rs.get("kill_switch") else 0
    circuit_open   = 1 if rs.get("circuit_open") else 0
    playbook       = rs.get("playbook", "standard")
    persona        = rs.get("persona", "medium")
    persona_config = rs.get("persona_config", {})
    cash_usd       = portfolio.get("available_cash_usd", 0)

    # Persona-driven constraints
    max_pos_pct    = persona_config.get("max_position_pct", 30)
    min_profit_floor = persona_config.get("min_profit_floor_pct", 1.0)
    buy_min_score  = persona_config.get("buy_min_score", 5)

    lines += [
        "## RISK CONSTRAINTS (Persona-Driven) ##",
        (
            f"persona|{persona}"
            f"|cash_usd|{cash_usd:.2f}"
            f"|positions_open|{positions_open}"
            f"|positions_max|{positions_max}"
            f"|max_per_trade_pct|{max_pos_pct}%"
            f"|min_profit_floor|{min_profit_floor:.1f}%"
            f"|buy_min_score|{buy_min_score}"
            f"|kill_switch|{kill_switch}"
            f"|circuit_open|{circuit_open}"
            f"|playbook|{playbook}"
        ),
        "",
    ]

    if positions_open >= positions_max:
        lines += [
            "Portfolio at capacity. Only propose sells or reallocation candidates.",
            "",
        ]

    # ── S14.2.1 — Portfolio state block (pipe format) ─────────────
    open_positions = portfolio.get("open_positions", [])
    lines += [
        "## CURRENT PORTFOLIO ##",
        f"Total:${portfolio['total_usd']:.2f}  Cash:${cash_usd:.2f}  "
        f"OpenPos:{positions_open}  DailyPnL:{portfolio['daily_pnl_pct']:+.2f}%"
        f"  MaxPerTrade:${portfolio['max_per_trade']:.2f}",
    ]
    if open_positions:
        for pos in open_positions:
            entry  = pos.get("entry_price", 0) or 0
            sl     = pos.get("stop_loss_price", 0) or 0
            tp     = pos.get("take_profit_price", 0) or 0
            # Compute SL/TP distances relative to entry
            sl_dist = ((sl - entry) / entry * 100) if entry else 0
            tp_dist = ((tp - entry) / entry * 100) if entry else 0
            # Current P&L — available if position was enriched with current_price
            cur_price = pos.get("current_price")
            if cur_price and entry:
                pnl_pct = (cur_price - entry) / entry * 100
                usd_val = pos.get("usd_value", 0) or 0
                pnl_usd = usd_val * pnl_pct / 100
            else:
                pnl_pct = None
                pnl_usd = None
            adx_val  = pos.get("adx", None)
            cluster  = pos.get("cluster", "N/A")

            # Accumulation eligibility check
            accum_eligible = "yes" if (pnl_pct and pnl_pct > 5.0 and tp_dist > 30) else "no"
            max_pair_size = portfolio.get("max_per_trade", 0)
            pos_size_pct = (usd_val / max_pair_size * 100) if max_pair_size and usd_val else 0

            lines.append(
                f"pos|{pos.get('pair','?')}"
                f"|entry|{entry:.4f}"
                f"|pnl_pct|{'N/A' if pnl_pct is None else f'{pnl_pct:.2f}'}"
                f"|pnl_usd|{'N/A' if pnl_usd is None else f'{pnl_usd:.2f}'}"
                f"|tp_dist_pct|{tp_dist:.1f}"
                f"|sl_dist_pct|{sl_dist:.1f}"
                f"|pos_size_pct|{pos_size_pct:.0f}"
                f"|accum_eligible|{accum_eligible}"
                f"|adx|{'N/A' if adx_val is None else f'{adx_val:.0f}'}"
                f"|cluster|{cluster}"
            )
    lines.append("")

    # ── S14.2.3 — Unfilled cluster context injection ───────────────
    _unfilled = unfilled_clusters or []
    if _unfilled:
        lines += [
            "## OPEN SECTORS ##",
            f"open_sectors|{','.join(_unfilled)}",
            "",
        ]
    else:
        lines += [
            "## OPEN SECTORS ##",
            "All sector clusters at capacity — reallocation only",
            "",
        ]

    # ── AI Context blocks — actionable context only ────────────────
    # patterns / position_sizing / dynamic_tp omitted (redundant with per-pair data)
    for block_key in ("regime", "cycle_top", "sentiment", "exit_timing"):
        block = ctx.get(block_key, "")
        if block:
            lines += ["", block]

    # ── S14.1.1 — Per-pair signal data in pipe format (BUY + SELL only) ──
    # Extract regime label for pipe blocks (first word of regime block, e.g. "BULL")
    regime_label = "N/A"
    regime_block = ctx.get("regime", "")
    if regime_block:
        first_line = regime_block.split("\n")[0] if regime_block else ""
        # Look for BULL/BEAR/NEUTRAL keyword
        for keyword in ("BULL", "BEAR", "NEUTRAL", "SIDEWAYS"):
            if keyword in first_line.upper():
                regime_label = keyword
                break

    if actionable:
        lines += ["", "## SIGNALS ##"]
    for sig in actionable:
        lines.append(build_pipe_signal_block(sig, pair_tp, regime_label))
        reasons = sig.get("reasons", [])
        if reasons:
            lines.append(f"  reasons|{'; '.join(reasons)}")

    # ── S14.1.2 — Token budget guard: trim lowest-score BUY pairs ─
    _TOKEN_BUDGET = 5800
    partial = "\n".join(lines)
    if estimate_tokens(partial) > _TOKEN_BUDGET:
        # Sort BUY signals ascending by score so we drop weakest first
        sorted_buys = sorted(buy_signals, key=lambda s: s.get("buy_score", 0))
        trimmed = 0
        for weakest in sorted_buys:
            # Remove the pipe block line(s) for this pair
            pair_line = build_pipe_signal_block(weakest, pair_tp, regime_label)
            reasons_line = f"  reasons|{'; '.join(weakest.get('reasons', []))}"
            if pair_line in lines:
                lines.remove(pair_line)
            if reasons_line in lines:
                lines.remove(reasons_line)
            trimmed += 1
            if estimate_tokens("\n".join(lines)) <= _TOKEN_BUDGET:
                break
        if trimmed:
            logger.warning(
                "[AIE] Token budget exceeded; trimmed %d BUY pairs to fit %d estimated tokens",
                trimmed, estimate_tokens("\n".join(lines)),
            )

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

    # Summary: log final prompt composition
    buy_count = len([s for s in actionable if s.get("signal") == "BUY"])
    sell_count = len([s for s in actionable if s.get("signal") == "SELL"])
    all_unique_pairs = [s.get("pair") for s in actionable]
    logger.info(
        "[PROMPT] LLM prompt ready: %d unique pairs (BUY=%d, SELL=%d, HOLD=%d) | "
        "estimated tokens=%d",
        len(all_unique_pairs), buy_count, sell_count, hold_count,
        estimate_tokens("\n".join(lines)),
    )

    return "\n".join(lines)
