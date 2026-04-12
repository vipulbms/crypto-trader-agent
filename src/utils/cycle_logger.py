"""
cycle_logger.py — Human-readable per-cycle decision trace log.

Every decision cycle is written as a structured text block to
logs/cycle_decisions.log, making it easy to understand why each pair
was bought, sold, or held — without running SQL queries against audit.db.

Format per cycle:
    ════ CYCLE #N  timestamp  Balance $X  Cash $Y  Open N  P&L +X.XX% ════
    MACRO
      Regime     : bearish | neutral | bullish
      Fear&Greed : 38 (fear)
      BTC Dom    : 52.3% rising
      Cycle-top  : active / inactive

    ─ BTC/USD  $65000.0000  →  BUY  score=7/28  min=5 ─
      RSI=28.40  MACD-hist=+0.000120 ← BULLISH TURN  ADX=35.2  BB=at-lower
      EMA9 > EMA21  Price > EMA50($64000)  Vol-ratio=1.12x
      REASONS:
        + RSI oversold (28.4 < 30)                         [+3]
        + MACD histogram turned positive                   [+3]
      VERDICT: BUY candidate → LLM: BUY executed $180.00

    ─ SOL/USD  $140.5200  →  HOLD  VETOED ─
      RSI=72.10 ...
      REASONS:
        ✗ BLOCKED: RSI 72.1 >= 70 — overbought, no entry
      VERDICT: HOLD (hard veto) — not sent to LLM

    ─ ETH/USD  $3000.0000  →  HOLD  score=4/28(need 5) ─
      REASONS:
        + ADX 45.0 > 40 — strong trend confirmed           [+1]
      VERDICT: HOLD (score 4 < min 5, gap 1) — not sent to LLM

    ════ SUMMARY  BUY:3 SELL:1 HOLD:23(2 vetoed)  Sent to LLM:4  Duration:4.2s ════

Public API:
    init_cycle_logger(log_dir, config)       — call once at startup
    write_cycle_report(config, cycle_id, ...) — call at end of run_cycle()
    format_cycle_report(...)                  — pure function, returns str (testable)
"""

from __future__ import annotations

import logging
import logging.handlers
import os
from datetime import datetime, timezone
from typing import Any

# Internal logger — writes only to the cycle_decisions.log handler
_cycle_log: logging.Logger = logging.getLogger("cycle_decisions")
_cycle_log.propagate = False  # never bubble to root / agent.log

_WIDTH = 72  # visual width of separator lines
_DOUBLE = "═" * _WIDTH
_SINGLE = "─" * _WIDTH


def init_cycle_logger(log_dir: str, config: dict) -> None:
    """
    Initialise the rotating cycle_decisions.log handler.

    Call once at agent startup (before the first decision cycle).
    Safe to call multiple times — handlers are cleared before re-adding.
    """
    storage_cfg  = config.get("storage", {})
    max_bytes    = storage_cfg.get("cycle_log_max_bytes",   20 * 1024 * 1024)  # 20 MB
    backup_count = storage_cfg.get("cycle_log_backup_count", 4)

    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, "cycle_decisions.log")

    # Remove any stale handlers (e.g. from setup_logging being called twice in tests)
    for h in _cycle_log.handlers[:]:
        _cycle_log.removeHandler(h)
        h.close()

    handler = logging.handlers.RotatingFileHandler(
        log_path, maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8"
    )
    # Plain text — no timestamp prefix; the cycle header already has the time
    handler.setFormatter(logging.Formatter("%(message)s"))
    _cycle_log.addHandler(handler)
    _cycle_log.setLevel(logging.DEBUG)


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

def _indicator_summary(ind: dict) -> str:
    """Return a compact one-line indicator snapshot for a pair."""
    parts: list[str] = []

    rsi = ind.get("rsi_14")
    if rsi is not None:
        parts.append(f"RSI={rsi:.2f}")

    macd_hist = ind.get("macd_histogram")
    macd_prev = ind.get("macd_histogram_prev")
    if macd_hist is not None:
        hist_str = f"MACD-hist={macd_hist:+.6f}"
        if macd_prev is not None:
            if macd_prev <= 0 < macd_hist:
                hist_str += " \u2190 BULLISH TURN"
            elif macd_prev >= 0 > macd_hist:
                hist_str += " \u2190 BEARISH TURN"
        parts.append(hist_str)

    adx = ind.get("adx_14")
    if adx is not None:
        parts.append(f"ADX={adx:.1f}")

    close  = ind.get("close")
    bb_lo  = ind.get("bb_lower")
    bb_hi  = ind.get("bb_upper")
    if close and bb_lo and bb_hi:
        mid = (bb_lo + bb_hi) / 2
        band_range = bb_hi - bb_lo
        if band_range > 0:
            pct_pos = (close - bb_lo) / band_range
        else:
            pct_pos = 0.5
        if pct_pos <= 0.20:
            bb_zone = "BB=at-lower(\u2193 BUY zone)"
        elif pct_pos >= 0.80:
            bb_zone = "BB=at-upper(\u2191 SELL zone)"
        else:
            bb_zone = "BB=mid"
        parts.append(bb_zone)

    bb_width = ind.get("bb_width")
    if bb_width is not None:
        parts.append(f"BB-width={bb_width:.2f}%")

    atr = ind.get("atr_14")
    if atr is not None:
        parts.append(f"ATR={atr:.5f}")

    return "  ".join(parts) if parts else ""


def _ema_summary(ind: dict) -> str:
    """Return EMA relationship string."""
    parts: list[str] = []
    close = ind.get("close")
    ema9  = ind.get("ema_9")
    ema21 = ind.get("ema_21")
    ema50 = ind.get("ema_50")

    if ema9 is not None and ema21 is not None:
        parts.append("EMA9 > EMA21" if ema9 > ema21 else "EMA9 < EMA21")

    if close is not None and ema50 is not None:
        if close > ema50:
            parts.append(f"Price > EMA50(${ema50:,.4f})")
        else:
            parts.append(f"Price < EMA50(${ema50:,.4f}) [VETO]")

    vol_ratio = ind.get("volume_ratio")
    if vol_ratio is not None:
        parts.append(f"Vol-ratio={vol_ratio:.2f}x")

    return "  ".join(parts) if parts else ""


def _format_reason(r: str) -> str:
    """Prefix reason lines with +, ✗, or ~ based on content."""
    rl = r.lower()
    if any(k in rl for k in ("blocked", "veto", "skip", "halted", "hard stop",
                              "below", "insufficient", "< min", "overbought",
                              "no entry", "no candle", "< 0", "dead zone",
                              "circuit", "loss limit", "drawdown", "cycle top")):
        return f"    \u2717 {r}"
    elif any(k in rl for k in ("+ ", "oversold", "turn", "bullish", "strong",
                                "macd", "rsi", "ema", "fear", "obv", "squeeze")):
        return f"    + {r}"
    else:
        return f"    ~ {r}"


def _lpad(text: str, width: int = _WIDTH) -> str:
    """Return text left-padded to width (truncated if over)."""
    if len(text) > width:
        return text[:width - 3] + "..."
    return text


# ─────────────────────────────────────────────────────────────────────────────
# Public formatter (pure function — testable without I/O)
# ─────────────────────────────────────────────────────────────────────────────

def format_cycle_report(
    cycle_id: int,
    timestamp: datetime,
    portfolio: dict,
    signals: list[dict],
    ai_context: dict,
    results: list[dict],
    duration_ms: int = 0,
) -> str:
    """
    Build and return the full cycle report as a string.

    Parameters
    ----------
    cycle_id    : integer cycle counter from audit_logger
    timestamp   : UTC datetime of cycle
    portfolio   : dict with total_usd, available_cash_usd, open_positions_count,
                  daily_pnl_usd, daily_pnl_pct
    signals     : list of signal dicts (each has pair, signal, price, reasons,
                  buy_score, sell_score, buy_min_score, max_score, indicators)
    ai_context  : dict from build_ai_context() — has regime_data, fear_greed etc.
    results     : list of {"pair": str, "result": str} from agent.run_cycle()
    duration_ms : cycle duration in milliseconds
    """
    lines: list[str] = []

    # ── Header ─────────────────────────────────────────────────
    ts_str = timestamp.strftime("%Y-%m-%d %H:%M:%S UTC")
    total  = portfolio.get("total_usd", 0.0)
    cash   = portfolio.get("available_cash_usd", 0.0)
    n_open = portfolio.get("open_positions_count", 0)
    dpnl_u = portfolio.get("daily_pnl_usd", 0.0)
    dpnl_p = portfolio.get("daily_pnl_pct", 0.0)
    sign   = "+" if dpnl_u >= 0 else ""
    header = (
        f"CYCLE #{cycle_id}  {ts_str}  "
        f"Balance ${total:,.2f}  Cash ${cash:,.2f}  "
        f"Open {n_open}  Daily P&L {sign}${dpnl_u:.2f} ({sign}{dpnl_p:.2f}%)"
    )
    lines.append(_DOUBLE)
    lines.append(_lpad(header, _WIDTH))
    lines.append(_DOUBLE)

    # ── Macro section ──────────────────────────────────────────
    regime_data  = ai_context.get("regime_data", {})
    regime       = regime_data.get("regime", "unknown")
    caution      = regime_data.get("caution_factor", 1.0)
    fg_index     = ai_context.get("fear_greed", {})
    if isinstance(fg_index, dict):
        fg_val   = fg_index.get("value")
        fg_label = fg_index.get("label", "")
    else:
        fg_val = fg_label = None

    btc_dom = ai_context.get("btc_dominance", {}) or {}
    btc_dom_pct   = btc_dom.get("btc_dominance_pct", btc_dom.get("dominance"))
    btc_dom_trend = btc_dom.get("btc_dominance_trend", btc_dom.get("trend", "unknown"))

    cycle_top = ai_context.get("cycle_top_data") or {}
    ct_active = cycle_top.get("cycle_top_active", False)

    lines.append("MACRO")
    lines.append(
        f"  Regime       : {regime}"
        + (f"  (caution={caution:.2f})" if caution < 1.0 else "")
    )
    if fg_val is not None:
        lines.append(f"  Fear & Greed : {fg_val} ({fg_label})")
    if btc_dom_pct is not None:
        lines.append(f"  BTC Dom      : {btc_dom_pct:.1f}% {btc_dom_trend}")
    mvrv = cycle_top.get("mvrv_z_score")
    nupl = cycle_top.get("nupl")
    ct_label = "ACTIVE" if ct_active else "inactive"
    ct_suffix = f"  mvrv={mvrv:.2f} nupl={nupl:.2f}" if mvrv is not None and nupl is not None else ""
    lines.append(f"  Cycle-top    : {ct_label}{ct_suffix}")
    lines.append("")

    # ── Build a lookup from pair → LLM result string ───────────
    result_map: dict[str, str] = {r["pair"]: r["result"] for r in results}

    # ── Per-pair blocks ────────────────────────────────────────
    n_buy = n_sell = n_hold = n_vetoed = 0
    n_sent_to_llm = 0

    for sig in signals:
        pair       = sig["pair"]
        signal     = sig["signal"]
        price      = sig.get("price", 0.0)
        buy_score  = sig.get("buy_score", 0)
        sell_score = sig.get("sell_score", 0)
        buy_min    = sig.get("buy_min_score", 5)
        sell_min   = sig.get("sell_min_score", 3)
        max_sc     = sig.get("max_score", 28)
        reasons    = sig.get("reasons", [])
        ind        = sig.get("indicators", {})

        # Has a hard-veto reason?
        is_vetoed = any(
            any(k in r.lower() for k in ("blocked", "veto", "hard stop",
                                          "overbought", "no entry", "dead zone",
                                          "circuit", "below.*ema50"))
            for r in reasons
        )

        if signal == "BUY":
            n_buy += 1
            active_score = buy_score
            score_label  = f"score={buy_score}/{max_sc}  min={buy_min}"
        elif signal == "SELL":
            n_sell += 1
            active_score = sell_score
            score_label  = f"sell_score={sell_score}/{max_sc}  min={sell_min}"
        else:
            n_hold += 1
            if is_vetoed:
                n_vetoed += 1
            active_score = buy_score  # show for context even on HOLD
            gap = buy_min - buy_score
            if is_vetoed:
                score_label = "VETOED"
            else:
                score_label = f"score={buy_score}/{max_sc}(need {buy_min}) gap={gap}"

        # ── Sub-header ──
        sep_label = f"  {pair}  ${price:,.4f}  \u2192  {signal}  {score_label}  "
        sep_left  = "\u2500\u2500"
        sep_right = "\u2500" * max(0, _WIDTH - len(sep_label) - len(sep_left))
        lines.append(sep_left + sep_label + sep_right)

        # ── Indicator line 1 ──
        ind_line = _indicator_summary(ind)
        if ind_line:
            lines.append(f"  {ind_line}")

        # ── Indicator line 2: EMAs + volume ──
        ema_line = _ema_summary(ind)
        if ema_line:
            lines.append(f"  {ema_line}")

        # ── Reasons ──
        if reasons:
            lines.append("  REASONS:")
            for r in reasons:
                lines.append(_format_reason(r))

        # ── Verdict / LLM outcome ──
        llm_result = result_map.get(pair)
        if signal == "BUY":
            n_sent_to_llm += 1
            if llm_result:
                lines.append(f"  VERDICT: BUY candidate \u2192 LLM: {llm_result}")
            else:
                lines.append("  VERDICT: BUY candidate \u2192 LLM: not reported")
        elif signal == "SELL":
            n_sent_to_llm += 1
            if llm_result:
                lines.append(f"  VERDICT: SELL candidate \u2192 LLM: {llm_result}")
            else:
                lines.append("  VERDICT: SELL candidate \u2192 LLM: not reported")
        else:
            if is_vetoed:
                lines.append("  VERDICT: HOLD (hard veto) \u2014 not sent to LLM")
            else:
                gap2 = buy_min - buy_score
                lines.append(
                    f"  VERDICT: HOLD (score {buy_score} < min {buy_min}, gap {gap2})"
                    " \u2014 not sent to LLM"
                )

        lines.append("")

    # ── Footer summary ─────────────────────────────────────────
    dur_str = f"{duration_ms / 1000:.1f}s" if duration_ms else "?s"
    summary = (
        f"SUMMARY  "
        f"BUY:{n_buy}  SELL:{n_sell}  HOLD:{n_hold}({n_vetoed} vetoed)  "
        f"Sent to LLM:{n_sent_to_llm}  "
        f"Duration:{dur_str}"
    )
    lines.append(_SINGLE)
    lines.append(_lpad(summary, _WIDTH))
    lines.append(_DOUBLE)
    lines.append("")

    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# Writer
# ─────────────────────────────────────────────────────────────────────────────

def write_cycle_report(
    config: dict,
    cycle_id: int,
    portfolio: dict,
    signals: list[dict],
    ai_context: dict,
    results: list[dict],
    duration_ms: int = 0,
) -> None:
    """
    Format and append a cycle report to logs/cycle_decisions.log.

    Call at the end of run_cycle() (skip in backtest mode).
    init_cycle_logger() must have been called first.
    """
    now = datetime.now(timezone.utc)
    try:
        report = format_cycle_report(
            cycle_id=cycle_id,
            timestamp=now,
            portfolio=portfolio,
            signals=signals,
            ai_context=ai_context,
            results=results,
            duration_ms=duration_ms,
        )
        _cycle_log.info(report)
    except Exception as exc:  # never crash the trading loop
        logging.getLogger("main").warning(
            "[CYCLE_LOG] Failed to write cycle report: %s", exc
        )
