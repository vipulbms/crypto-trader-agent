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
import os
import sqlite3
import time
from datetime import datetime, timedelta, timezone
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
    min_order = config.get("risk", {}).get("min_order_usd", 20.0)
    return round(max(min(usd_size, max_usd), min_order), 2)


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

def detect_market_regime(signals: list, config: dict, btc_dominance: Optional[dict] = None) -> dict:
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
            "caution_factor": float,       (1.0 = normal, <1 = reduce position sizes)
            "btc_dominance_trend": str,    "rising"|"falling"|"flat"|"unknown"
            "btc_dominance_pct": float,    current BTC dominance % (0 if unavailable)
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

    # BTC dominance overlay — append to summary when trend is notable (#206)
    dom_trend   = "unknown"
    dom_pct     = 0.0
    dom_change  = 0.0
    if btc_dominance:
        dom_trend  = btc_dominance.get("btc_dominance_trend", "flat")
        dom_pct    = btc_dominance.get("btc_dominance_pct", 0.0)
        dom_change = btc_dominance.get("trend_change_pp", 0.0)
        if dom_trend == "rising":
            summary += (
                f" | BTC DOMINANCE RISING ({dom_pct:.1f}%, +{dom_change:.1f}pp) — "
                f"capital rotating to BTC/ETH; altcoin caution elevated."
            )
        elif dom_trend == "falling":
            summary += (
                f" | BTC DOMINANCE FALLING ({dom_pct:.1f}%, {dom_change:.1f}pp) — "
                f"altseason signal; altcoins may outperform."
            )

    return {
        "regime": regime,
        "bullish_count": bullish_count,
        "bearish_count": bearish_count,
        "volatile_count": volatile_count,
        "ranging_count": ranging_count,
        "summary": summary,
        "caution_factor": caution,
        "btc_dominance_trend": dom_trend,
        "btc_dominance_pct": dom_pct,
    }


def build_regime_context(regime: dict, config: dict) -> str:
    """Build the regime text block for injection into LLM prompt."""
    if not config.get("regime", {}).get("enabled", True):
        return ""
    return f"--- MARKET REGIME ---\n{regime['summary']}"


def compute_pair_regime_caps(
    signals: list,
    portfolio_max_per_trade: float,
    regime_data: dict,
    config: dict,
) -> dict:
    """
    Compute per-pair tier metadata and regime-adjusted max buy sizes.

    #203 adds sector tiers so rising BTC dominance can cut speculative tiers
    harder than majors. This function is intentionally independent from the
    fetch path — if `btc_dominance_trend` is absent, no tier overlay is applied.

    Returns:
        {
            "PAIR/USD": {
                "pair_tier": int,
                "pair_max_usd": Optional[float],
                "pair_caution": float,
                "dominance_multiplier": float,
            },
            ...
        }
    """
    trading_pairs_cfg = config.get("trading", {}).get("pairs", [])
    pair_cfg_map = {p.get("pair"): p for p in trading_pairs_cfg}
    reg_cfg = config.get("regime", {})

    regime = regime_data.get("regime", "unknown")
    global_caution = regime_data.get("caution_factor", 1.0)
    btc_dom_trend = regime_data.get("btc_dominance_trend", "unknown")

    dom_general_mult = reg_cfg.get("btc_dominance_rising_caution_multiplier", 0.7)
    tier3_mult = reg_cfg.get("tier3_dominance_rising_multiplier", 0.5)
    tier4_mult = reg_cfg.get("tier4_dominance_rising_multiplier", 0.3)

    pair_caps = {}
    for sig in signals:
        pair = sig.get("pair")
        pair_cfg = pair_cfg_map.get(pair, {})
        pair_tier = int(pair_cfg.get("pair_tier", 0) or 0)
        pair_caution = pair_cfg.get("caution_factor_bearish", global_caution)

        dominance_multiplier = 1.0
        if regime == "bearish" and btc_dom_trend == "rising":
            if pair_tier == 3:
                dominance_multiplier = tier3_mult
            elif pair_tier == 4:
                dominance_multiplier = tier4_mult
            elif pair not in ("BTC/USD", "ETH/USD", "BNB/USD"):
                dominance_multiplier = dom_general_mult

        pair_max_usd = None
        if regime == "bearish":
            pair_max_usd = round(
                portfolio_max_per_trade * pair_caution * dominance_multiplier,
                2,
            )

        pair_caps[pair] = {
            "pair_tier": pair_tier,
            "pair_max_usd": pair_max_usd,
            "pair_caution": pair_caution,
            "dominance_multiplier": dominance_multiplier,
        }

    return pair_caps


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


# ──────────────────────────────────────────────────────────────────────────────
# Feature 4b: BTC Dominance trend (#206)
# ──────────────────────────────────────────────────────────────────────────────

_btc_dom_cache: dict = {"data": None, "fetched_at": 0}
_cycle_top_cache: dict = {"data": None, "fetched_at": 0, "failed_at": 0}


def _coerce_float(value) -> Optional[float]:
    """Best-effort float coercion for API payload values."""
    if value is None or isinstance(value, bool):
        return None
    try:
        if isinstance(value, str):
            value = value.replace(",", "").strip()
        return float(value)
    except (TypeError, ValueError):
        return None


def _extract_latest_indicator_value(node, candidate_keys: list[str]) -> Optional[float]:
    """Extract the most recent numeric indicator value from nested API payloads."""
    if isinstance(node, dict):
        for key in candidate_keys:
            if key in node:
                value = _extract_latest_indicator_value(node[key], candidate_keys)
                if value is not None:
                    return value
        for key in ("data", "result", "list", "series", "items", "rows"):
            if key in node:
                value = _extract_latest_indicator_value(node[key], candidate_keys)
                if value is not None:
                    return value
        for key, value in node.items():
            if key.lower() in {"time", "timestamp", "date", "t"}:
                continue
            coerced = _coerce_float(value)
            if coerced is not None:
                return coerced
            nested = _extract_latest_indicator_value(value, candidate_keys)
            if nested is not None:
                return nested
        return None

    if isinstance(node, list):
        if len(node) >= 2:
            last_numeric = _coerce_float(node[-1])
            if last_numeric is not None:
                return last_numeric
        for item in reversed(node):
            value = _extract_latest_indicator_value(item, candidate_keys)
            if value is not None:
                return value
        return None

    return _coerce_float(node)


def fetch_btc_dominance(config: dict, db_path: Optional[str] = None) -> Optional[dict]:
    """
    Fetch BTC market-cap dominance from CoinGecko /api/v3/global.
    Caches in-memory for cache_minutes. Optionally persists daily readings
    to the agent_state table in db_path for trend calculation.

    Returns:
        {
            "btc_dominance_pct": float,
            "btc_dominance_trend": "rising" | "falling" | "flat",
            "trend_change_pp": float,   # positive = rising
        }
        or None on error / disabled.
    """
    dom_cfg = config.get("regime", {}).get("btc_dominance", {})
    if not dom_cfg.get("enabled", True):
        return None

    url          = dom_cfg.get("url", "https://api.coingecko.com/api/v3/global")
    timeout      = dom_cfg.get(
        "fetch_timeout_secs",
        config.get("regime", {}).get("fetch_timeout_secs", 8),
    )
    cache_mins   = dom_cfg.get("cache_minutes", 60)
    min_change   = dom_cfg.get("trend_min_change_pp", 0.5)
    lookback_days = dom_cfg.get("trend_lookback_days", 3)

    now = time.time()
    if _btc_dom_cache["data"] and (now - _btc_dom_cache["fetched_at"]) < cache_mins * 60:
        return _btc_dom_cache["data"]

    try:
        resp = requests.get(url, timeout=timeout)
        resp.raise_for_status()
        global_data = resp.json().get("data", {})
        btc_dom_pct = float(global_data.get("market_cap_percentage", {}).get("btc", 0.0))
    except Exception as e:
        logger.warning("[BTC_DOM] Fetch failed: %s", e)
        return None

    # Persist today's reading to DB for trend calculation
    today_key = "btc_dom_" + datetime.now(timezone.utc).strftime("%Y-%m-%d")
    prev_dom_pct = None
    if db_path:
        try:
            import sqlite3 as _sqlite3
            conn = _sqlite3.connect(db_path)
            # Ensure agent_state table exists
            conn.execute(
                "CREATE TABLE IF NOT EXISTS agent_state "
                "(key TEXT PRIMARY KEY, value TEXT)"
            )
            conn.execute(
                "INSERT OR IGNORE INTO agent_state (key, value) VALUES (?, ?)",
                (today_key, str(btc_dom_pct)),
            )
            conn.commit()
            # Look up the reading from `lookback_days` ago for trend
            past_key = "btc_dom_" + (
                datetime.now(timezone.utc) - timedelta(days=lookback_days)
            ).strftime("%Y-%m-%d")
            row = conn.execute(
                "SELECT value FROM agent_state WHERE key=?", (past_key,)
            ).fetchone()
            if row:
                prev_dom_pct = float(row[0])
            conn.close()
        except Exception as db_err:
            logger.debug("[BTC_DOM] DB persistence failed: %s", db_err)

    # Compute trend
    if prev_dom_pct is not None:
        change_pp = round(btc_dom_pct - prev_dom_pct, 3)
    else:
        change_pp = 0.0

    if change_pp >= min_change:
        trend = "rising"
    elif change_pp <= -min_change:
        trend = "falling"
    else:
        trend = "flat"

    data = {
        "btc_dominance_pct":   round(btc_dom_pct, 2),
        "btc_dominance_trend": trend,
        "trend_change_pp":     change_pp,
    }
    _btc_dom_cache["data"]       = data
    _btc_dom_cache["fetched_at"] = now
    logger.info(
        "[BTC_DOM] Dominance=%.2f%% trend=%s (Δ%.2fpp vs %dd ago)",
        btc_dom_pct, trend, change_pp, lookback_days,
    )
    return data


def fetch_cycle_top_indicators(config: dict, db_path: Optional[str] = None) -> Optional[dict]:
    """
    Fetch BTC cycle-top indicators (MVRV Z-Score + NUPL) from CoinGlass.
    Cached in-memory and optionally persisted to agent_state with a 24h TTL.
    """
    guard_cfg = config.get("risk", {}).get("cycle_top_guard", {})
    if not guard_cfg.get("enabled", False):
        return None

    api_key = os.getenv("COINGLASS_API_KEY", "").strip()
    if not api_key:
        logger.info("[CYCLE_TOP] COINGLASS_API_KEY not set — skipping cycle-top guard fetch")
        return None

    cache_hours = guard_cfg.get("cache_hours", 24)
    cache_secs = cache_hours * 3600
    now = time.time()
    if _cycle_top_cache["data"] and (now - _cycle_top_cache["fetched_at"]) < cache_secs:
        return _cycle_top_cache["data"]
    # Back-off after fetch failure — retry at most once per hour to avoid log spam
    if _cycle_top_cache["failed_at"] and (now - _cycle_top_cache["failed_at"]) < 3600:
        return None

    payload_key = "cycle_top_guard_payload"
    fetched_key = "cycle_top_guard_fetched_at"
    if db_path:
        try:
            conn = sqlite3.connect(db_path)
            conn.execute(
                "CREATE TABLE IF NOT EXISTS agent_state (key TEXT PRIMARY KEY, value TEXT)"
            )
            rows = conn.execute(
                "SELECT key, value FROM agent_state WHERE key IN (?, ?)",
                (payload_key, fetched_key),
            ).fetchall()
            cached = {row[0]: row[1] for row in rows}
            cached_at = _coerce_float(cached.get(fetched_key))
            cached_payload = cached.get(payload_key)
            if cached_at and cached_payload and (now - cached_at) < cache_secs:
                data = json.loads(cached_payload)
                _cycle_top_cache["data"] = data
                _cycle_top_cache["fetched_at"] = cached_at
                conn.close()
                return data
            conn.close()
        except Exception as db_err:
            logger.debug("[CYCLE_TOP] DB cache read failed: %s", db_err)

    headers = {
        "Accept": "application/json",
        "coinglassSecret": api_key,
        "CG-API-KEY": api_key,
    }
    timeout = guard_cfg.get("fetch_timeout_secs", 8)
    try:
        mvrv_resp = requests.get(guard_cfg.get("mvrv_url"), headers=headers, timeout=timeout)
        mvrv_resp.raise_for_status()
        nupl_resp = requests.get(guard_cfg.get("nupl_url"), headers=headers, timeout=timeout)
        nupl_resp.raise_for_status()
    except Exception as exc:
        logger.warning("[CYCLE_TOP] Fetch failed: %s — will retry in 1h", exc)
        _cycle_top_cache["failed_at"] = now
        return None

    mvrv = _extract_latest_indicator_value(
        mvrv_resp.json(),
        ["mvrvZScore", "mvrv_zscore", "mvrv_z_score", "zscore", "z_score", "value"],
    )
    nupl = _extract_latest_indicator_value(nupl_resp.json(), ["nupl", "value"])
    if mvrv is None or nupl is None:
        logger.warning("[CYCLE_TOP] Could not parse MVRV/NUPL from CoinGlass responses")
        return None

    data = {
        "mvrv_z_score": round(mvrv, 3),
        "nupl": round(nupl, 3),
        "cycle_top_active": (
            mvrv >= guard_cfg.get("mvrv_z_danger", 7.0)
            and nupl >= guard_cfg.get("nupl_danger", 0.70)
        ),
    }
    if db_path:
        try:
            conn = sqlite3.connect(db_path)
            conn.execute(
                "CREATE TABLE IF NOT EXISTS agent_state (key TEXT PRIMARY KEY, value TEXT)"
            )
            conn.execute(
                "INSERT OR REPLACE INTO agent_state (key, value) VALUES (?, ?)",
                (payload_key, json.dumps(data)),
            )
            conn.execute(
                "INSERT OR REPLACE INTO agent_state (key, value) VALUES (?, ?)",
                (fetched_key, str(now)),
            )
            conn.commit()
            conn.close()
        except Exception as db_err:
            logger.debug("[CYCLE_TOP] DB cache write failed: %s", db_err)

    _cycle_top_cache["data"] = data
    _cycle_top_cache["fetched_at"] = now
    logger.info(
        "[CYCLE_TOP] MVRV=%.2f NUPL=%.2f active=%s",
        data["mvrv_z_score"], data["nupl"], data["cycle_top_active"],
    )
    return data


def build_cycle_top_context(cycle_top_data: Optional[dict], config: dict) -> str:
    """Build the cycle-top warning block shown in the cycle prompt."""
    if not cycle_top_data or not cycle_top_data.get("cycle_top_active"):
        return ""

    guard_cfg = config.get("risk", {}).get("cycle_top_guard", {})
    return (
        "--- [CYCLE TOP WARNING] ---\n"
        "  BTC on-chain metrics are in macro peak territory.\n"
        f"  MVRV Z-Score: {cycle_top_data.get('mvrv_z_score', 0.0):.2f} "
        f"(danger >= {guard_cfg.get('mvrv_z_danger', 7.0):.2f})\n"
        f"  NUPL:         {cycle_top_data.get('nupl', 0.0):.2f} "
        f"(danger >= {guard_cfg.get('nupl_danger', 0.70):.2f})\n"
        "  Action: Block new Tier 3 / Tier 4 BUYs. Prefer BTC/USD, ETH/USD, and BNB/USD."
    )


def apply_cycle_top_guard(signals: list, config: dict, cycle_top_data: Optional[dict]) -> int:
    """Suppress Tier 3 / Tier 4 BUY signals when the cycle-top guard is active."""
    if not cycle_top_data or not cycle_top_data.get("cycle_top_active"):
        return 0

    pair_cfg_map = {
        pair_cfg.get("pair"): pair_cfg
        for pair_cfg in config.get("trading", {}).get("pairs", [])
    }
    suppressed = 0
    for sig in signals:
        pair_tier = sig.get("pair_tier") or int(pair_cfg_map.get(sig.get("pair"), {}).get("pair_tier", 0) or 0)
        if sig.get("signal") == "BUY" and pair_tier in (3, 4):
            sig["signal"] = "HOLD"
            sig["cycle_top_buy_suppressed"] = True
            reasons = list(sig.get("reasons", []))
            if "Cycle top guard active" not in reasons:
                reasons.append("Cycle top guard active")
            sig["reasons"] = reasons
            suppressed += 1
    return suppressed


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

    min_hold_mins         = et_cfg.get("min_hold_minutes", 60)
    macd_decay_pct        = et_cfg.get("macd_decay_threshold_pct", -0.005)  # % of price (Fix #112)
    rsi_exit_ob           = et_cfg.get("rsi_exit_overbought", 70)
    sideways_candles      = et_cfg.get("sideways_candles", 8)

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

    # MACD histogram decay — normalised to % of price so threshold is pair-agnostic (Fix #112)
    if macd_hist is not None and price and price > 0:
        macd_hist_pct = macd_hist / price * 100
        if macd_hist_pct < macd_decay_pct:
            return (
                f"MACD histogram decayed to {macd_hist_pct:.4f}% of price "
                f"(threshold {macd_decay_pct}%) — bearish momentum on open position"
            )

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
# Feature 8: Profit factor auto-escalation (#183)
# ──────────────────────────────────────────────────────────────────────────────

def compute_profit_factor(pair: str, trades: list) -> Optional[float]:
    """
    Compute the rolling profit factor for a pair from a list of closed trade dicts.

    Profit factor = Gross wins / Gross losses.
    Returns None when fewer than min_trades records are available (insufficient history).

    Args:
        pair:   pair name (used only for logging)
        trades: list of dicts with at least {"pnl_usd": float}
    """
    if len(trades) < 10:
        return None  # insufficient history — no escalation
    wins   = sum(t["pnl_usd"] for t in trades if t["pnl_usd"] > 0)
    losses = abs(sum(t["pnl_usd"] for t in trades if t["pnl_usd"] < 0))
    if losses == 0:
        return float("inf")  # all wins, no losses
    pf = round(wins / losses, 2)
    logger.debug("[PROFIT_FACTOR] %s: pf=%.2f (wins=$%.2f losses=$%.2f n=%d)", pair, pf, wins, losses, len(trades))
    return pf


# ──────────────────────────────────────────────────────────────────────────────
# Master context builder — called once per cycle to produce all context blocks
# ──────────────────────────────────────────────────────────────────────────────

def build_ai_context(
    signals: list,
    portfolio: dict,
    open_positions: list,
    config: dict,
    btc_dominance: Optional[dict] = None,
    cycle_top_data: Optional[dict] = None,
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
            "cycle_top":        str,
            "btc_dominance_trend": str,   "rising"|"falling"|"flat"|"unknown"
            "btc_dominance_pct":   float,
        }
    """
    regime = detect_market_regime(signals, config, btc_dominance=btc_dominance)

    return {
        "regime":          build_regime_context(regime, config),
        "regime_data":     regime,
        "cycle_top":       build_cycle_top_context(cycle_top_data, config),
        "sentiment":       build_sentiment_context(config),
        "patterns":        build_pattern_context(config),
        "position_sizing": build_position_sizing_context(
            signals, portfolio.get("total_usd", 1000), config
        ),
        "dynamic_tp":        build_dynamic_tp_context(signals, config),
        "dynamic_tp_values": compute_dynamic_tp_values(signals, config),
        "dynamic_sl_values": compute_dynamic_sl_values(signals, config),
        "exit_timing":     build_exit_timing_context(open_positions, signals, config),
        "btc_dominance_trend": regime.get("btc_dominance_trend", "unknown"),
        "btc_dominance_pct":   regime.get("btc_dominance_pct", 0.0),
    }
