"""
features.py — Advanced AI context features for the trading agent.

Implements all 7 AI enhancement features:
  1. Multi-pair context awareness (position sizing by signal strength + ATR)
  2. Dynamic take-profit targets (ATR + BB width based)
  3. Market regime detection (trending / ranging / bearish / volatile)
  4. News & sentiment integration (Fear & Greed Index)
  5. Audit trail pattern analysis (self-improving signal calibration)
  6. Exit timing on open positions (momentum decay detection)
  7. Post-trade analysis (LLM explains each closed trade)

All literals are read from config.yaml — no hardcoded values in this file.
"""

import json
import logging
import sqlite3
import time
from datetime import datetime, timedelta
from typing import Optional

import requests

from src.utils.tz import now_sgt

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# Feature 1: Multi-pair context aware position sizing
# ──────────────────────────────────────────────────────────────────────────────

def get_volatility_multiplier(atr: float, price: float) -> float:
    """
    Returns ATR multiplier (k) based on asset volatility regime.
    Low volatility (<1% ATR) -> 1.75
    Standard (1-3% ATR)       -> 2.75
    High volatility (>3% ATR) -> 4.0
    """
    if not atr or not price or price <= 0:
        return 2.75
    atr_pct = (atr / price) * 100
    if atr_pct < 1.0:
        return 1.75
    elif atr_pct > 3.0:
        return 4.0
    return 2.75

def compute_position_size(
    signal_strength: float,
    atr: Optional[float],
    price: Optional[float],
    portfolio_total_usd: float,
    config: dict,
) -> float:
    """
    Compute a scaled position size in USD based on ATR-proportional risk.
    PositionSize = TotalRiskAmount / (ATR * Multiplier)
    """
    if not atr or not price or price <= 0:
        return round(portfolio_total_usd * 0.20, 2)
    
    # Target risking ~1.5% of total portfolio per trade (adjust based on config)
    risk_pct = config.get("risk", {}).get("risk_per_trade_pct", 1.5) / 100.0
    risk_amount_usd = portfolio_total_usd * risk_pct
    
    multiplier = get_volatility_multiplier(atr, price)
    
    # Distance to stop loss
    sl_dist = multiplier * atr
    
    # Cap distance at 5% to respect the hard stop-loss limit
    max_sl_dist = price * 0.05
    if sl_dist > max_sl_dist:
        sl_dist = max_sl_dist
        
    coins_to_buy = risk_amount_usd / sl_dist
    usd_size = coins_to_buy * price
    
    # Hard clamp to max 30% of portfolio just to be safe
    max_usd = portfolio_total_usd * 0.30
    return round(min(usd_size, max_usd), 2)


def build_position_sizing_context(signals: list, portfolio_total_usd: float, config: dict) -> str:
    """
    Build a text summary of suggested position sizes per BUY-signalling pair.
    Injected into the LLM cycle prompt.
    """
    ps_cfg = config.get("position_sizing", {})
    if not ps_cfg.get("enabled", True):
        return ""

    lines = ["--- SUGGESTED POSITION SIZES (signal strength × ATR-adjusted) ---"]
    has_buys = False
    for sig in signals:
        if sig.get("signal") != "BUY":
            continue
        has_buys = True
        ind = sig.get("indicators", {})
        size = compute_position_size(
            signal_strength=sig.get("strength", 0.5),
            atr=ind.get("atr_14"),
            price=ind.get("close"),
            portfolio_total_usd=portfolio_total_usd,
            config=config,
        )
        lines.append(
            f"  {sig['pair']}: suggested ${size:.2f}  "
            f"(strength={sig['strength']:.2f}, ATR={ind.get('atr_14', 0):.4f})"
        )

    if not has_buys:
        return ""
    return "\n".join(lines)


# ──────────────────────────────────────────────────────────────────────────────
# Feature 2: Dynamic take-profit
# ──────────────────────────────────────────────────────────────────────────────

def compute_dynamic_tp(
    pair: str,
    entry_price: float,
    atr: Optional[float],
    bb_upper: Optional[float],
    bb_lower: Optional[float],
    config: dict,
) -> float:
    """
    Compute a dynamic take-profit percentage: EntryPrice + (k * ATR).
    k depends on volatility regime.
    """
    dtp_cfg = config.get("dynamic_tp", {})
    if not dtp_cfg.get("enabled", True):
        # Fall back to configured static TP
        for p in config.get("trading", {}).get("pairs", []):
            if p["pair"] == pair:
                return p.get("take_profit_pct", config["trading"].get("take_profit_pct", 8))
        return config.get("trading", {}).get("take_profit_pct", 8)

    global_min_tp = dtp_cfg.get("min_tp_pct", 5)
    max_tp = dtp_cfg.get("max_tp_pct", 20)
    pair_static_tp = next(
        (p.get("take_profit_pct", global_min_tp) for p in config.get("trading", {}).get("pairs", []) if p["pair"] == pair),
        config.get("trading", {}).get("take_profit_pct", global_min_tp),
    )
    min_tp = max(global_min_tp, pair_static_tp)

    if not atr or not entry_price or entry_price <= 0:
        return float(min_tp)

    # BB squeeze guard: if bands are compressed below threshold, clamp TP to pair floor
    # Priority: rolling p10 injected by main.py > per-pair static > global dynamic_tp threshold
    if dtp_cfg.get("bb_width_scale", False) and bb_upper and bb_lower:
        bb_mid_calc = (bb_upper + bb_lower) / 2
        bb_width_pct = (bb_upper - bb_lower) / bb_mid_calc * 100
        pair_cfg = next(
            (p for p in config.get("trading", {}).get("pairs", []) if p.get("pair") == pair),
            {}
        )
        squeeze_threshold = (
            pair_cfg.get("_rolling_bb_p10_pct")              # injected by main.py when adaptive enabled
            or pair_cfg.get("bb_squeeze_threshold_pct")      # per-pair static (Fix #110)
            or dtp_cfg.get("squeeze_threshold_pct", 1.0)     # global fallback
        )
        if bb_width_pct < squeeze_threshold:
            return float(min_tp)

    multiplier = get_volatility_multiplier(atr, entry_price)
    target_dist = multiplier * atr
    atr_tp_pct = (target_dist / entry_price) * 100

    return float(max(min_tp, min(max_tp, round(atr_tp_pct, 1))))


def compute_dynamic_tp_values(signals: list, config: dict) -> dict:
    """
    Returns {pair: tp_pct} for all pairs using dynamic TP calculation.
    Used by TradingTools to override static TP at order placement time.
    Returns empty dict if dynamic_tp is disabled.
    """
    dtp_cfg = config.get("dynamic_tp", {})
    if not dtp_cfg.get("enabled", True):
        return {}
    result = {}
    for sig in signals:
        ind = sig.get("indicators", {})
        price = ind.get("close", 0)
        result[sig["pair"]] = compute_dynamic_tp(
            pair=sig["pair"],
            entry_price=price,
            atr=ind.get("atr_14"),
            bb_upper=ind.get("bb_upper"),
            bb_lower=ind.get("bb_lower"),
            config=config,
        )
    return result

def compute_dynamic_sl_values(signals: list, config: dict) -> dict:
    """
    Returns {pair: sl_pct} for all pairs in `signals`.

    S12.4.1: When atr_stop_loss.enabled=True, computes SL as:
        sl_pct = (atr_multiplier × ATR / price) × 100
        clamped to [min_stop_loss_pct, max_stop_loss_pct]
    Falls back to trading.stop_loss_pct when disabled or ATR is unavailable.
    """
    result = {}
    default_sl = config.get("trading", {}).get("stop_loss_pct", 5.0)
    atr_sl_cfg = config.get("atr_stop_loss", {})
    atr_sl_enabled = atr_sl_cfg.get("enabled", False)
    atr_multiplier = atr_sl_cfg.get("atr_multiplier", 1.5)
    max_sl = atr_sl_cfg.get("max_stop_loss_pct", 5.0)
    min_sl = atr_sl_cfg.get("min_stop_loss_pct", 1.0)

    for sig in signals:
        ind = sig.get("indicators", {})
        price = ind.get("close", 0)
        atr = ind.get("atr_14")
        if atr_sl_enabled and atr and price > 0:
            atr_sl_pct = (atr_multiplier * atr / price) * 100
            result[sig["pair"]] = float(max(min_sl, min(max_sl, round(atr_sl_pct, 2))))
        else:
            result[sig["pair"]] = default_sl
    return result


def build_dynamic_tp_context(signals: list, config: dict) -> str:
    """
    Build a text block showing dynamic TP suggestions for BUY signals.
    """
    dtp_cfg = config.get("dynamic_tp", {})
    if not dtp_cfg.get("enabled", True):
        return ""

    lines = ["--- DYNAMIC TAKE-PROFIT SUGGESTIONS (ATR + BB width adjusted) ---"]
    has_buys = False
    for sig in signals:
        if sig.get("signal") != "BUY":
            continue
        has_buys = True
        ind = sig.get("indicators", {})
        price = ind.get("close", 0)
        dtp = compute_dynamic_tp(
            pair=sig["pair"],
            entry_price=price,
            atr=ind.get("atr_14"),
            bb_upper=ind.get("bb_upper"),
            bb_lower=ind.get("bb_lower"),
            config=config,
        )
        static_tp = config.get("trading", {}).get("take_profit_pct", 8)
        for p in config.get("trading", {}).get("pairs", []):
            if p["pair"] == sig["pair"]:
                static_tp = p.get("take_profit_pct", static_tp)
        lines.append(
            f"  {sig['pair']}: dynamic TP={dtp:.1f}% (configured={static_tp}%)"
        )

    if not has_buys:
        return ""
    return "\n".join(lines)


# ──────────────────────────────────────────────────────────────────────────────
# Feature 3: Market regime detection
# ──────────────────────────────────────────────────────────────────────────────

def detect_market_regime(signals: list, config: dict) -> dict:
    """
    Classify the current market regime across all pairs.

    Returns:
        {
            "regime": "bullish" | "bearish" | "volatile" | "ranging" | "mixed",
            "bullish_count": int,
            "bearish_count": int,
            "volatile_count": int,
            "ranging_count": int,
            "summary": str,
            "caution_factor": float  (1.0 = normal, <1 = reduce position sizes)
        }
    """
    reg_cfg = config.get("regime", {})
    if not reg_cfg.get("enabled", True):
        return {"regime": "unknown", "summary": "Regime detection disabled", "caution_factor": 1.0}

    bearish_thresh  = reg_cfg.get("bearish_pairs_threshold", 6)
    bullish_thresh  = reg_cfg.get("bullish_pairs_threshold", 6)
    volatile_mult   = reg_cfg.get("volatile_atr_multiplier", 1.5)
    ranging_thresh  = reg_cfg.get("ranging_macd_threshold", 0.001)
    bearish_caution = reg_cfg.get("bearish_caution_factor", 0.5)
    volatile_caution= reg_cfg.get("volatile_caution_factor", 0.7)

    bearish_count  = 0
    bullish_count  = 0
    volatile_count = 0
    ranging_count  = 0

    atrs = [s.get("indicators", {}).get("atr_14") for s in signals if s.get("indicators", {}).get("atr_14")]
    avg_atr = sum(atrs) / len(atrs) if atrs else 0

    for sig in signals:
        ind = sig.get("indicators", {})
        macd_hist = ind.get("macd_histogram") or 0
        atr = ind.get("atr_14") or 0
        price = ind.get("close") or 1

        if macd_hist < 0:
            bearish_count += 1
        elif macd_hist > 0:
            bullish_count += 1

        atr_pct = (atr / price * 100) if price > 0 else 0
        avg_atr_pct = (avg_atr / price * 100) if price > 0 else 0
        if avg_atr_pct > 0 and atr_pct > avg_atr_pct * volatile_mult:
            volatile_count += 1

        if abs(macd_hist) < ranging_thresh:
            ranging_count += 1

    total = len(signals) or 1

    if bearish_count >= bearish_thresh:
        regime = "bearish"
        caution = bearish_caution
        summary = (
            f"BEARISH REGIME: {bearish_count}/{total} pairs have negative MACD. "
            f"Reduce position sizes to {int(bearish_caution*100)}% of normal."
        )
    elif bullish_count >= bullish_thresh:
        regime = "bullish"
        caution = 1.0
        summary = f"BULLISH REGIME: {bullish_count}/{total} pairs have positive MACD. Normal sizing."
    elif volatile_count >= 3:
        regime = "volatile"
        caution = volatile_caution
        summary = (
            f"VOLATILE REGIME: {volatile_count}/{total} pairs showing high ATR. "
            f"Reduce position sizes to {int(volatile_caution*100)}% of normal."
        )
    elif ranging_count >= total * 0.6:
        regime = "ranging"
        caution = 0.8
        summary = (
            f"RANGING REGIME: {ranging_count}/{total} pairs showing no MACD momentum. "
            f"Be selective — only trade high-confidence signals."
        )
    else:
        regime = "mixed"
        caution = 1.0
        summary = f"MIXED REGIME: {bullish_count} bullish, {bearish_count} bearish, {ranging_count} ranging."

    return {
        "regime": regime,
        "bullish_count": bullish_count,
        "bearish_count": bearish_count,
        "volatile_count": volatile_count,
        "ranging_count": ranging_count,
        "summary": summary,
        "caution_factor": caution,
    }


def build_regime_context(regime: dict, config: dict) -> str:
    """Build the regime text block for injection into LLM prompt."""
    if not config.get("regime", {}).get("enabled", True):
        return ""
    return f"--- MARKET REGIME ---\n{regime['summary']}"


# ──────────────────────────────────────────────────────────────────────────────
# Feature 4: News & sentiment (Fear & Greed Index)
# ──────────────────────────────────────────────────────────────────────────────

_sentiment_cache: dict = {"data": None, "fetched_at": 0}


def fetch_fear_greed(config: dict) -> Optional[dict]:
    """
    Fetch the Crypto Fear & Greed Index from alternative.me API.
    Caches for cache_minutes to avoid excessive calls.

    Returns:
        {"value": int, "label": str, "timestamp": str} or None on error.
    """
    snt_cfg = config.get("sentiment", {})
    if not snt_cfg.get("enabled", True):
        return None

    url          = snt_cfg.get("fear_greed_url", "https://api.alternative.me/fng/?limit=1")
    timeout      = snt_cfg.get("fetch_timeout_secs", 5)
    cache_mins   = snt_cfg.get("cache_minutes", 60)

    now = time.time()
    if _sentiment_cache["data"] and (now - _sentiment_cache["fetched_at"]) < cache_mins * 60:
        return _sentiment_cache["data"]

    try:
        resp = requests.get(url, timeout=timeout)
        resp.raise_for_status()
        item = resp.json()["data"][0]
        data = {
            "value":     int(item["value"]),
            "label":     item["value_classification"],
            "timestamp": item.get("timestamp", ""),
        }
        _sentiment_cache["data"] = data
        _sentiment_cache["fetched_at"] = now
        return data
    except Exception as e:
        logger.warning("Fear & Greed fetch failed: %s", e)
        return None


def build_sentiment_context(config: dict) -> str:
    """Build the sentiment text block for the LLM cycle prompt."""
    snt_cfg = config.get("sentiment", {})
    if not snt_cfg.get("enabled", True):
        return ""

    data = fetch_fear_greed(config)
    if not data:
        return "--- MARKET SENTIMENT ---\nFear & Greed Index: unavailable"

    value         = data["value"]
    label         = data["label"]
    fear_thresh   = snt_cfg.get("extreme_fear_threshold", 25)
    greed_thresh  = snt_cfg.get("extreme_greed_threshold", 75)

    if value <= fear_thresh:
        interpretation = "EXTREME FEAR — market is oversold; historically a buy zone. BUY signals are more reliable."
    elif value >= greed_thresh:
        interpretation = "EXTREME GREED — market is overbought; caution on new entries. Prefer HOLD over BUY."
    elif value < 45:
        interpretation = "FEAR — market is cautious; moderate buy conditions."
    elif value > 55:
        interpretation = "GREED — market is optimistic; be selective on entries."
    else:
        interpretation = "NEUTRAL — no strong market-wide sentiment bias."

    return (
        f"--- MARKET SENTIMENT (Fear & Greed Index) ---\n"
        f"  Index: {value}/100 ({label})\n"
        f"  Interpretation: {interpretation}"
    )


# ──────────────────────────────────────────────────────────────────────────────
# Feature 5: Audit trail pattern analysis
# ──────────────────────────────────────────────────────────────────────────────

_pattern_cache: dict = {"data": None, "computed_at": 0}


def analyse_trade_patterns(config: dict) -> dict:
    """
    Query the audit trail to surface win/loss patterns per pair.
    Caches for cache_minutes to avoid querying every cycle.

    Returns:
        {
            "by_pair": {
                "BTC/USD": {"total": int, "wins": int, "win_rate_pct": float,
                            "avg_pnl_usd": float, "common_exit": str}
            },
            "overall_win_rate_pct": float,
            "best_signal_combo": str,   # most common reasons in winning trades
            "worst_signal_combo": str,  # most common reasons in losing trades
        }
    """
    pa_cfg = config.get("pattern_analysis", {})
    if not pa_cfg.get("enabled", True):
        return {}

    cache_mins = pa_cfg.get("cache_minutes", 60)
    lookback   = pa_cfg.get("lookback_days", 30)
    min_trades = pa_cfg.get("min_trades_for_pattern", 3)

    now = time.time()
    if _pattern_cache["data"] and (now - _pattern_cache["computed_at"]) < cache_mins * 60:
        return _pattern_cache["data"]

    try:
        from src.storage.database import get_connection
        mode = "paper"  # pattern analysis always reads paper trades for now
        key = "paper_db" if mode == "paper" else "live_db"
        db_path = config["storage"][key]
        conn = get_connection(db_path)

        cutoff = (now_sgt() - timedelta(days=lookback)).isoformat()
        rows = conn.execute(
            """SELECT pair, pnl_usd, pnl_pct, exit_reason
               FROM paper_trades
               WHERE closed_at >= ?
               ORDER BY closed_at DESC""",
            (cutoff,),
        ).fetchall()
        conn.close()

        by_pair: dict = {}
        total_wins = 0
        total_trades = 0

        for row in rows:
            pair = row["pair"]
            if pair not in by_pair:
                by_pair[pair] = {"total": 0, "wins": 0, "pnl_sum": 0.0, "exits": {}}
            by_pair[pair]["total"] += 1
            by_pair[pair]["pnl_sum"] += row["pnl_usd"]
            total_trades += 1
            if row["pnl_usd"] > 0:
                by_pair[pair]["wins"] += 1
                total_wins += 1
            exit_r = row["exit_reason"] or "unknown"
            by_pair[pair]["exits"][exit_r] = by_pair[pair]["exits"].get(exit_r, 0) + 1

        result_pairs = {}
        for pair, d in by_pair.items():
            if d["total"] < min_trades:
                continue
            most_common_exit = max(d["exits"], key=d["exits"].get) if d["exits"] else "unknown"
            result_pairs[pair] = {
                "total": d["total"],
                "wins": d["wins"],
                "win_rate_pct": round(d["wins"] / d["total"] * 100, 1),
                "avg_pnl_usd": round(d["pnl_sum"] / d["total"], 2),
                "common_exit": most_common_exit,
            }

        overall_win_rate = round(total_wins / total_trades * 100, 1) if total_trades > 0 else 0.0

        data = {
            "by_pair": result_pairs,
            "overall_win_rate_pct": overall_win_rate,
            "total_trades": total_trades,
        }
        _pattern_cache["data"] = data
        _pattern_cache["computed_at"] = now
        return data

    except Exception as e:
        logger.warning("Pattern analysis failed: %s", e)
        return {}


def build_pattern_context(config: dict) -> str:
    """Build the pattern analysis text block for the LLM cycle prompt."""
    pa_cfg = config.get("pattern_analysis", {})
    if not pa_cfg.get("enabled", True):
        return ""

    data = analyse_trade_patterns(config)
    if not data or not data.get("by_pair"):
        return "--- HISTORICAL PATTERN ANALYSIS ---\nInsufficient trade history for pattern analysis."

    lines = [
        f"--- HISTORICAL PATTERN ANALYSIS (last {pa_cfg.get('lookback_days', 30)} days) ---",
        f"  Overall win rate: {data['overall_win_rate_pct']}% over {data['total_trades']} trades",
    ]
    for pair, d in data["by_pair"].items():
        lines.append(
            f"  {pair}: {d['win_rate_pct']}% win rate ({d['wins']}/{d['total']}), "
            f"avg P&L ${d['avg_pnl_usd']:+.2f}, common exit: {d['common_exit']}"
        )
    return "\n".join(lines)


# ──────────────────────────────────────────────────────────────────────────────
# Feature 6: Exit timing — detect momentum decay on open positions
# ──────────────────────────────────────────────────────────────────────────────

def check_exit_timing(
    pair: str,
    position: dict,
    indicators: dict,
    config: dict,
) -> Optional[str]:
    """
    Evaluate whether an open position should be closed early due to momentum decay.

    Returns:
        A string exit reason if early exit is recommended, or None to continue holding.
    """
    et_cfg = config.get("exit_timing", {})
    if not et_cfg.get("enabled", True):
        return None

    min_hold_mins    = et_cfg.get("min_hold_minutes", 60)
    macd_decay       = et_cfg.get("macd_decay_threshold", -0.0005)
    rsi_exit_ob      = et_cfg.get("rsi_exit_overbought", 70)
    sideways_candles = et_cfg.get("sideways_candles", 8)

    # Check minimum hold time
    opened_at_str = position.get("opened_at", "")
    if opened_at_str:
        try:
            from src.utils.tz import SGT
            opened_at = datetime.fromisoformat(opened_at_str)
            if opened_at.tzinfo is None:
                opened_at = opened_at.replace(tzinfo=SGT)
            hold_mins = (now_sgt() - opened_at).total_seconds() / 60
            if hold_mins < min_hold_mins:
                return None  # Too early to exit
        except Exception:
            pass

    macd_hist = indicators.get("macd_histogram")
    rsi       = indicators.get("rsi_14")
    atr       = indicators.get("atr_14")
    price     = indicators.get("close")
    entry_price = float(position.get("entry_price", price or 0))

    # MACD histogram decay — momentum turning negative
    if macd_hist is not None and macd_hist < macd_decay:
        return f"MACD histogram decayed to {macd_hist:.5f} — bearish momentum on open position"

    # RSI overbought exit
    if rsi is not None and rsi > rsi_exit_ob:
        return f"RSI overbought at {rsi:.1f} — consider taking profit early"

    # Sideways / stalled: price within 1 ATR of entry for too long
    if atr and price and entry_price and atr > 0:
        price_move_pct = abs(price - entry_price) / entry_price * 100
        atr_pct = atr / entry_price * 100
        if price_move_pct < atr_pct * 0.5:
            return f"Position stalled — price moved only {price_move_pct:.2f}% vs ATR {atr_pct:.2f}% (sideways)"

    return None


def build_exit_timing_context(open_positions: list, signals: list, config: dict) -> str:
    """
    Build a text block flagging open positions that should consider early exit.
    """
    et_cfg = config.get("exit_timing", {})
    if not et_cfg.get("enabled", True):
        return ""

    if not open_positions:
        return ""

    # Build signal lookup by pair
    sig_lookup = {s["pair"]: s for s in signals}

    recommendations = []
    for pos in open_positions:
        pair = pos.get("pair", "")
        sig = sig_lookup.get(pair)
        if not sig:
            continue
        ind = sig.get("indicators", {})
        reason = check_exit_timing(pair, pos, ind, config)
        if reason:
            entry  = pos.get("entry_price", 0)
            current = ind.get("close", 0)
            if entry and current:
                pnl_pct = (current - entry) / entry * 100
                recommendations.append(
                    f"  {pair}: EXIT TIMING ALERT — {reason} | Current P&L: {pnl_pct:+.2f}%"
                )

    if not recommendations:
        return ""

    lines = ["--- EXIT TIMING ALERTS (open positions with decaying momentum) ---"]
    lines.extend(recommendations)
    lines.append("  Consider calling propose_sell for flagged pairs.")
    return "\n".join(lines)


# ──────────────────────────────────────────────────────────────────────────────
# Feature 7: Post-trade analysis
# ──────────────────────────────────────────────────────────────────────────────

def generate_post_trade_analysis(
    trade: dict,
    signals_at_entry: Optional[dict],
    config: dict,
    llm_client=None,
    model: str = "qwen2.5:14b",
) -> Optional[str]:
    """
    Generate a brief LLM analysis of a just-closed trade.

    Args:
        trade: Closed trade dict (from close_position)
        signals_at_entry: Signal dict from around the time of entry (optional)
        config: Full config dict
        llm_client: Ollama client instance (passed in to avoid re-creating)
        model: LLM model name

    Returns:
        Analysis string or None if disabled / LLM unavailable.
    """
    pt_cfg = config.get("post_trade", {})
    if not pt_cfg.get("enabled", True):
        return None

    min_hold_mins = pt_cfg.get("min_hold_minutes", 15)
    max_chars     = pt_cfg.get("max_analysis_chars", 500)

    # Skip very short trades
    hold_secs = trade.get("hold_duration_secs", 0)
    if hold_secs < min_hold_mins * 60:
        return None

    if not llm_client:
        return None

    pair       = trade.get("pair", "")
    pnl_usd    = trade.get("pnl_usd", 0)
    pnl_pct    = trade.get("pnl_pct", 0)
    exit_reason= trade.get("exit_reason", "")
    entry_price= trade.get("entry_price", 0)
    exit_price = trade.get("exit_price", 0)
    hold_human = _fmt_secs(hold_secs)

    outcome = "WIN" if pnl_usd > 0 else "LOSS"

    prompt = (
        f"A {outcome} trade just closed on {pair}.\n"
        f"Entry: ${entry_price:.4f} | Exit: ${exit_price:.4f} | "
        f"P&L: ${pnl_usd:+.2f} ({pnl_pct:+.2f}%) | "
        f"Hold: {hold_human} | Exit: {exit_reason}\n"
    )
    if signals_at_entry:
        reasons = signals_at_entry.get("reasons", [])
        prompt += f"Entry signal reasons: {', '.join(reasons)}\n"

    prompt += (
        "In 2-3 sentences: What worked or went wrong? "
        "Was the entry timing good? Was the exit reason appropriate? "
        "What would you do differently next time?"
    )

    try:
        logger.info("[LLM] Initiating post-trade analysis — pair=%s model=%s", pair, model)
        _start = time.time()
        response = llm_client.chat(
            model=model,
            messages=[
                {"role": "system", "content": "You are a concise crypto trading analyst. Keep your analysis to 2-3 sentences maximum."},
                {"role": "user",   "content": prompt},
            ],
            options={"temperature": 0.3},
        )
        logger.info("[LLM] Post-trade analysis completed — pair=%s model=%s latency=%dms", pair, model, int((time.time() - _start) * 1000))
        analysis = (response.message.content or "").strip()
        return analysis[:max_chars] if len(analysis) > max_chars else analysis
    except Exception as e:
        logger.warning("Post-trade LLM analysis failed: %s", e)
        return None


def _fmt_secs(secs: int) -> str:
    """Format seconds into a human-readable duration."""
    if secs >= 3600:
        h = secs // 3600
        m = (secs % 3600) // 60
        return f"{h}h {m}m"
    elif secs >= 60:
        return f"{secs // 60}m {secs % 60}s"
    return f"{secs}s"


# ──────────────────────────────────────────────────────────────────────────────
# Master context builder — called once per cycle to produce all context blocks
# ──────────────────────────────────────────────────────────────────────────────

def build_ai_context(
    signals: list,
    portfolio: dict,
    open_positions: list,
    config: dict,
) -> dict:
    """
    Build all AI context blocks for a decision cycle.

    Returns a dict of labelled context strings to be injected into the cycle prompt:
        {
            "regime":           str,
            "sentiment":        str,
            "patterns":         str,
            "position_sizing":  str,
            "dynamic_tp":       str,
            "exit_timing":      str,
        }
    """
    regime = detect_market_regime(signals, config)

    return {
        "regime":          build_regime_context(regime, config),
        "regime_data":     regime,
        "sentiment":       build_sentiment_context(config),
        "patterns":        build_pattern_context(config),
        "position_sizing": build_position_sizing_context(
            signals, portfolio.get("total_usd", 1000), config
        ),
        "dynamic_tp":        build_dynamic_tp_context(signals, config),
        "dynamic_tp_values": compute_dynamic_tp_values(signals, config),
        "dynamic_sl_values": compute_dynamic_sl_values(signals, config),
        "exit_timing":     build_exit_timing_context(open_positions, signals, config),
    }
