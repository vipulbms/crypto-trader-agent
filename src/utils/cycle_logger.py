"""
cycle_logger.py — Per-cycle decision trace log (JSON Lines / NDJSON format).

Every decision cycle is written as a single JSON record (one line) to
logs/cycle_decisions.log, making it easy to parse, filter, and ingest
into external tools without SQL queries against audit.db.

Schema per record (one compact JSON object per line):
    {
      "cycle_id": 42,
      "timestamp": "2026-04-12T14:30:00+00:00",
      "duration_ms": 4200,
      "portfolio": {
        "total_usd": 1234.56, "available_cash_usd": 456.78,
        "open_positions_count": 2, "daily_pnl_usd": 12.34, "daily_pnl_pct": 1.02
      },
      "macro": {
        "regime": "neutral", "caution_factor": 1.0,
        "fear_greed_value": 38, "fear_greed_label": "fear",
        "btc_dominance_pct": 52.3, "btc_dominance_trend": "rising",
        "cycle_top_active": false, "mvrv_z_score": 1.2, "nupl": 0.45
      },
      "pairs": [
        {
          "pair": "ETH/USD", "signal": "BUY", "price": 3000.0,
          "strength": 0.25, "buy_score": 7, "sell_score": 0,
          "buy_min_score": 5, "sell_min_score": 3, "max_score": 28,
          "is_vetoed": false, "sent_to_llm": true,
          "llm_result": "BUY executed $180.00", "verdict": "BUY candidate",
          "reasons": ["RSI oversold (28.4 < 30)"],
          "indicators": {
            "rsi_14": 28.4, "macd_histogram": 0.00012,
            "macd_histogram_prev": -0.00008, "macd_turn": "bullish",
            "adx_14": 35.2, "bb_zone": "lower", "bb_width": 2.1,
            "atr_14": 45.2, "ema9_above_ema21": true,
            "price_above_ema50": true, "ema_50": 2980.0, "volume_ratio": 1.12
          }
        }
      ],
      "summary": {"n_buy": 1, "n_sell": 0, "n_hold": 0, "n_vetoed": 0, "n_sent_to_llm": 1}
    }

Public API:
    init_cycle_logger(log_dir, config)        — call once at startup
    write_cycle_report(config, cycle_id, ...) — call at end of run_cycle()
    format_cycle_report(...)                  — pure function, returns JSON str (testable)
"""

from __future__ import annotations

import json
import logging
import logging.handlers
import os
from datetime import datetime, timezone
from typing import Any

# Internal logger — writes only to the cycle_decisions.log handler
_cycle_log: logging.Logger = logging.getLogger("cycle_decisions")
_cycle_log.propagate = False  # never bubble to root / agent.log

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
    # Plain text — no timestamp prefix; the JSON record contains the timestamp
    handler.setFormatter(logging.Formatter("%(message)s"))
    _cycle_log.addHandler(handler)
    _cycle_log.setLevel(logging.DEBUG)


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

def _round(v: Any, n: int) -> Any:
    """Safely round a float; return None if v is None."""
    return round(v, n) if v is not None else None


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
    Build and return the cycle report as a compact JSON string (one line).

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
    # ── Portfolio ───────────────────────────────────────────────
    portfolio_block = {
        "total_usd":            _round(portfolio.get("total_usd", 0.0), 2),
        "available_cash_usd":   _round(portfolio.get("available_cash_usd", 0.0), 2),
        "open_positions_count": portfolio.get("open_positions_count", 0),
        "daily_pnl_usd":        _round(portfolio.get("daily_pnl_usd", 0.0), 2),
        "daily_pnl_pct":        _round(portfolio.get("daily_pnl_pct", 0.0), 4),
    }

    # ── Macro ────────────────────────────────────────────────────
    regime_data  = ai_context.get("regime_data", {})
    regime       = regime_data.get("regime", "unknown")
    caution      = regime_data.get("caution_factor", 1.0)
    fg_index     = ai_context.get("fear_greed", {})
    if isinstance(fg_index, dict):
        fg_val   = fg_index.get("value")
        fg_label = fg_index.get("label", "")
    else:
        fg_val = fg_label = None

    btc_dom       = ai_context.get("btc_dominance", {}) or {}
    btc_dom_pct   = btc_dom.get("btc_dominance_pct", btc_dom.get("dominance"))
    btc_dom_trend = btc_dom.get("btc_dominance_trend", btc_dom.get("trend", "unknown"))

    cycle_top = ai_context.get("cycle_top_data") or {}
    ct_active = cycle_top.get("cycle_top_active", False)
    mvrv      = cycle_top.get("mvrv_z_score")
    nupl      = cycle_top.get("nupl")

    macro_block = {
        "regime":              regime,
        "caution_factor":      _round(caution, 4),
        "fear_greed_value":    fg_val,
        "fear_greed_label":    fg_label,
        "btc_dominance_pct":   _round(btc_dom_pct, 2) if btc_dom_pct is not None else None,
        "btc_dominance_trend": btc_dom_trend,
        "cycle_top_active":    ct_active,
        "mvrv_z_score":        _round(mvrv, 4) if mvrv is not None else None,
        "nupl":                _round(nupl, 4) if nupl is not None else None,
    }

    # ── Build a lookup from pair → LLM result string ───────────
    result_map: dict[str, str] = {r["pair"]: r["result"] for r in results}

    # ── Per-pair entries ────────────────────────────────────────
    pairs_list: list[dict] = []
    n_buy = n_sell = n_hold = n_vetoed = n_sent_to_llm = 0

    for sig in signals:
        pair       = sig["pair"]
        signal     = sig["signal"]
        price      = sig.get("price", 0.0)
        strength   = sig.get("strength", 0.0)
        buy_score  = sig.get("buy_score", 0)
        sell_score = sig.get("sell_score", 0)
        buy_min    = sig.get("buy_min_score", 5)
        sell_min   = sig.get("sell_min_score", 3)
        max_sc     = sig.get("max_score", 28)
        reasons    = sig.get("reasons", [])
        ind        = sig.get("indicators", {})

        # ── Veto detection ──────────────────────────────────────
        is_vetoed = any(
            any(k in r.lower() for k in ("blocked", "veto", "hard stop",
                                          "overbought", "no entry", "dead zone",
                                          "circuit", "below.*ema50"))
            for r in reasons
        )

        # ── Derived indicator fields ────────────────────────────
        macd_hist = ind.get("macd_histogram")
        macd_prev = ind.get("macd_histogram_prev")
        if macd_hist is not None and macd_prev is not None:
            if macd_prev <= 0 < macd_hist:
                macd_turn = "bullish"
            elif macd_prev >= 0 > macd_hist:
                macd_turn = "bearish"
            else:
                macd_turn = None
        else:
            macd_turn = None

        close = ind.get("close")
        bb_lo = ind.get("bb_lower")
        bb_hi = ind.get("bb_upper")
        bb_zone = None
        if close and bb_lo and bb_hi and (bb_hi - bb_lo) > 0:
            pct_pos = (close - bb_lo) / (bb_hi - bb_lo)
            if pct_pos <= 0.20:
                bb_zone = "lower"
            elif pct_pos >= 0.80:
                bb_zone = "upper"
            else:
                bb_zone = "mid"

        ema9  = ind.get("ema_9")
        ema21 = ind.get("ema_21")
        ema50 = ind.get("ema_50")
        ema9_above_ema21  = (ema9 > ema21)   if ema9  is not None and ema21 is not None else None
        price_above_ema50 = (close > ema50)  if close is not None and ema50 is not None else None

        indicators_block = {
            "rsi_14":              _round(ind.get("rsi_14"), 4),
            "macd_histogram":      _round(macd_hist, 8),
            "macd_histogram_prev": _round(macd_prev, 8),
            "macd_turn":           macd_turn,
            "adx_14":              _round(ind.get("adx_14"), 2),
            "bb_zone":             bb_zone,
            "bb_width":            _round(ind.get("bb_width"), 4),
            "atr_14":              _round(ind.get("atr_14"), 6),
            "ema9_above_ema21":    ema9_above_ema21,
            "price_above_ema50":   price_above_ema50,
            "ema_50":              _round(ema50, 4),
            "volume_ratio":        _round(ind.get("volume_ratio"), 4),
        }

        # ── Counts, verdict, and LLM interaction ───────────────
        sent_to_llm = signal in ("BUY", "SELL")
        llm_result  = result_map.get(pair)

        if signal == "BUY":
            n_buy += 1
            n_sent_to_llm += 1
            verdict = "BUY candidate"
        elif signal == "SELL":
            n_sell += 1
            n_sent_to_llm += 1
            verdict = "SELL candidate"
        else:
            n_hold += 1
            if is_vetoed:
                n_vetoed += 1
                verdict = "HOLD (hard veto)"
            else:
                gap = buy_min - buy_score
                verdict = f"HOLD (score {buy_score} < min {buy_min}, gap {gap})"

        pairs_list.append({
            "pair":           pair,
            "signal":         signal,
            "price":          _round(price, 4),
            "strength":       _round(strength, 4),
            "buy_score":      buy_score,
            "sell_score":     sell_score,
            "buy_min_score":  buy_min,
            "sell_min_score": sell_min,
            "max_score":      max_sc,
            "is_vetoed":      is_vetoed,
            "sent_to_llm":    sent_to_llm,
            "llm_result":     llm_result,
            "verdict":        verdict,
            "reasons":        reasons,
            "indicators":     indicators_block,
        })

    # ── Summary ─────────────────────────────────────────────────
    summary_block = {
        "n_buy":         n_buy,
        "n_sell":        n_sell,
        "n_hold":        n_hold,
        "n_vetoed":      n_vetoed,
        "n_sent_to_llm": n_sent_to_llm,
    }

    # ── Assemble and serialise ───────────────────────────────────
    record = {
        "cycle_id":    cycle_id,
        "timestamp":   timestamp.isoformat(),
        "duration_ms": duration_ms,
        "portfolio":   portfolio_block,
        "macro":       macro_block,
        "pairs":       pairs_list,
        "summary":     summary_block,
    }

    return json.dumps(record, default=str)


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
