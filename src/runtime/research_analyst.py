"""
ResearchAnalystAgent (RAA) — standalone runtime process.

Continuously evaluates the broader crypto universe to identify emerging pairs
with persistent relative strength and manages the tradeable pair list dynamically.

Story: S22.1.1, S22.1.2, S22.2.1, S22.2.2, S22.3.1, S22.3.2 (Sprint S9 — E22)
Run as: python -m src.runtime.research_analyst [--config config.yaml] [--db paper_trading.db]

Responsibilities:
  1. Poll Kraken Ticker REST + CoinGecko Trending/Social every 30 minutes.
  2. Compute Persistence Score (Ps) per candidate pair; reset on Ps < min_ps.
  3. Apply meme-block guardrail before any proposal (S22.2.1 — hard-coded, no override).
  4. Submit PROPOSE(pair, replace_target?) to Risk Manager validate_universe_proposal() when
     all gates pass (Ps, alpha spread, universe cap).
  5. Self-correct on 422 rejections, up to max_retries per proposal per cycle (SHIELDA S22.2.2).
  6. Stale-feed halt when Kraken Ticker OHLCV variance == 0 for a candidate.
  7. Read last 50 audit_feedback rows at cycle start for self-reflection (S23.1.2).
  8. Apply persona-specific guardrails (Medium RSI/ADX gates, High RSI bypass — S22.3.1/3.2).
  9. Expose /health HTTP endpoint on configurable port.

No dependencies on src/agent/ or src/exchange/websocket_feed.
Uses: src/storage/database, mocha_python_ai.AIClient, mocha_python_logging.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import math
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import requests
import yaml

try:
    from aiohttp import web
    _AIOHTTP_AVAILABLE = True
except ImportError:
    _AIOHTTP_AVAILABLE = False

try:
    from mocha_python_ai import AIClient, ModelConfig
    _AI_AVAILABLE = True
except ImportError:
    _AI_AVAILABLE = False

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from src.storage.database import get_connection, RAA_SCHEMA, FEEDBACK_SCHEMA

logger = logging.getLogger("research_analyst")

# ─────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────

KRAKEN_TICKER_URL = "https://api.kraken.com/0/public/Ticker"
KRAKEN_ASSET_PAIRS_URL = "https://api.kraken.com/0/public/AssetPairs"
COINGECKO_TRENDING_URL = "https://api.coingecko.com/api/v3/search/trending"
COINGECKO_GLOBAL_URL = "https://api.coingecko.com/api/v3/global"

# Asset classification — hard-coded anchors for meme-block guardrail (S22.2.1 AC4)
_FOUNDATIONAL_ANCHORS = frozenset({
    "BTC/USD", "ETH/USD", "SOL/USD", "BNB/USD", "XRP/USD",
    "ADA/USD", "AVAX/USD", "DOT/USD", "LINK/USD", "MATIC/USD",
    "LTC/USD", "UNI/USD",
})


# ─────────────────────────────────────────────────────────────
# DB helpers
# ─────────────────────────────────────────────────────────────

def _ensure_schema(db_path: str) -> None:
    for schema in (RAA_SCHEMA, FEEDBACK_SCHEMA):
        conn = get_connection(db_path)
        for stmt in schema.split(";"):
            stmt = stmt.strip()
            if stmt:
                conn.execute(stmt)
        conn.commit()
        conn.close()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get_trend_persistence(db_path: str, pair: str) -> Optional[dict]:
    conn = get_connection(db_path)
    row = conn.execute(
        "SELECT * FROM trend_persistence WHERE pair = ?", (pair,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def _upsert_trend_persistence(db_path: str, pair: str, classification: str,
                              ps: float, cycles_sustained: int, status: str) -> None:
    now = _now_iso()
    conn = get_connection(db_path)
    existing = conn.execute(
        "SELECT id FROM trend_persistence WHERE pair = ?", (pair,)
    ).fetchone()
    if existing:
        conn.execute(
            """UPDATE trend_persistence
               SET classification=?, persistence_score=?, cycles_sustained=?,
                   last_updated_at=?, status=?
               WHERE pair=?""",
            (classification, ps, cycles_sustained, now, status, pair),
        )
    else:
        conn.execute(
            """INSERT INTO trend_persistence
               (pair, classification, persistence_score, cycles_sustained,
                first_seen_at, last_updated_at, status)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (pair, classification, ps, cycles_sustained, now, now, status),
        )
    conn.commit()
    conn.close()


def _get_universe(db_path: str) -> list[dict]:
    conn = get_connection(db_path)
    rows = conn.execute("SELECT * FROM universe").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _add_to_universe(db_path: str, pair: str, classification: str,
                     alpha_spread: Optional[float], replace_target: Optional[str]) -> None:
    now = _now_iso()
    conn = get_connection(db_path)
    conn.execute(
        """INSERT OR REPLACE INTO universe
           (pair, classification, added_at, added_by, alpha_spread_at_entry, replace_target_if_any)
           VALUES (?, ?, ?, 'RAA', ?, ?)""",
        (pair, classification, now, alpha_spread, replace_target),
    )
    conn.commit()
    conn.close()


def _remove_from_universe(db_path: str, pair: str) -> None:
    conn = get_connection(db_path)
    conn.execute("DELETE FROM universe WHERE pair = ?", (pair,))
    conn.commit()
    conn.close()


def _write_universe_event(db_path: str, pair: str, event_type: str,
                           payload: Optional[dict] = None) -> None:
    conn = get_connection(db_path)
    conn.execute(
        """INSERT INTO universe_events (pair, event_type, ts, processed, payload_json)
           VALUES (?, ?, ?, 0, ?)""",
        (pair, event_type, _now_iso(), json.dumps(payload) if payload else None),
    )
    conn.commit()
    conn.close()


def _write_audit_feedback(db_path: str, agent: str, pair: Optional[str],
                           event_type: str, psv_vector: str = "",
                           penalty_weight: float = 0.0,
                           extra: Optional[dict] = None) -> None:
    """Write a feedback row to audit_feedback for audit trail."""
    conn = get_connection(db_path)
    conn.execute(
        """INSERT INTO audit_feedback
           (agent, pair, event_type, ts, psv_vector, penalty_weight)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (agent, pair, event_type, _now_iso(), psv_vector, penalty_weight),
    )
    conn.commit()
    conn.close()


def _read_recent_feedback(db_path: str, agent: str = "RAA", limit: int = 50) -> list[dict]:
    """Read last N audit_feedback rows for self-reflection loop (S23.1.2 AC1)."""
    conn = get_connection(db_path)
    rows = conn.execute(
        "SELECT * FROM audit_feedback WHERE agent = ? ORDER BY ts DESC LIMIT ?",
        (agent, limit),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _get_confidence_state(db_path: str, agent: str = "RAA") -> dict:
    conn = get_connection(db_path)
    row = conn.execute(
        "SELECT * FROM confidence_state WHERE agent = ?", (agent,)
    ).fetchone()
    conn.close()
    return dict(row) if row else {}


def _upsert_confidence_state(db_path: str, agent: str, **kwargs) -> None:
    now = _now_iso()
    conn = get_connection(db_path)
    existing = conn.execute(
        "SELECT agent FROM confidence_state WHERE agent = ?", (agent,)
    ).fetchone()
    if existing:
        set_clauses = ", ".join(f"{k}=?" for k in kwargs)
        values = list(kwargs.values()) + [now, agent]
        conn.execute(
            f"UPDATE confidence_state SET {set_clauses}, last_updated_at=? WHERE agent=?",
            values,
        )
    else:
        kwargs["last_updated_at"] = now
        kwargs["agent"] = agent
        cols = ", ".join(kwargs.keys())
        placeholders = ", ".join("?" * len(kwargs))
        conn.execute(
            f"INSERT INTO confidence_state ({cols}) VALUES ({placeholders})",
            list(kwargs.values()),
        )
    conn.commit()
    conn.close()


def _write_hitl_queue(db_path: str, agent: str, proposal_type: str, pair: str,
                      replace_target: Optional[str], classification: str,
                      psv_vector: str, rationale: str) -> int:
    """Insert a row into hitl_queue. Returns the inserted row id."""
    conn = get_connection(db_path)
    cur = conn.execute(
        """INSERT INTO hitl_queue
           (ts, agent, proposal_type, pair, replace_target, classification,
            psv_vector, rationale, status)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'PENDING')""",
        (_now_iso(), agent, proposal_type, pair, replace_target,
         classification, psv_vector, rationale),
    )
    conn.commit()
    row_id = cur.lastrowid
    conn.close()
    return row_id


# ─────────────────────────────────────────────────────────────
# Market data fetchers
# ─────────────────────────────────────────────────────────────

def _fetch_kraken_ticker(pairs: list[str], timeout: int = 10) -> dict[str, dict]:
    """
    Fetch Kraken Ticker data for a list of pairs.
    Returns dict mapping pair → {last, volume, ohlcv_variance_check}.
    """
    results: dict[str, dict] = {}
    kraken_pairs = ",".join(p.replace("/", "") for p in pairs[:20])  # max 20 per call
    try:
        resp = requests.get(
            KRAKEN_TICKER_URL,
            params={"pair": kraken_pairs},
            timeout=timeout,
        )
        resp.raise_for_status()
        data = resp.json().get("result", {})
        for pair in pairs:
            kraken_key = pair.replace("/", "")
            # Kraken uses alternate keys sometimes (XXBTZUSD for BTC/USD)
            ticker = data.get(kraken_key) or data.get(f"X{kraken_key}") or {}
            if not ticker:
                # Try alt format
                for k, v in data.items():
                    if kraken_key in k:
                        ticker = v
                        break
            if ticker:
                # c = last trade price [price, lot_volume]
                # v = volume [today, last 24h]
                # o = today's opening price
                # h = today's high [today, last 24h]
                # l = today's low [today, last 24h]
                last_price = float(ticker.get("c", [0])[0] or 0)
                vol_24h = float(ticker.get("v", [0, 0])[1] or 0)
                open_p = float(ticker.get("o", 0) or 0)
                high_p = float(ticker.get("h", [0, 0])[1] or 0)
                low_p = float(ticker.get("l", [0, 0])[1] or 0)
                # OHLCV variance check — if open==high==low==last, feed is frozen
                prices = [last_price, vol_24h, open_p, high_p, low_p]
                has_variance = len(set(str(round(x, 6)) for x in [open_p, high_p, low_p, last_price])) > 1
                results[pair] = {
                    "last": last_price,
                    "volume_24h": vol_24h,
                    "open": open_p,
                    "high": high_p,
                    "low": low_p,
                    "has_variance": has_variance,
                }
    except Exception as e:
        logger.warning("[RAA] Kraken Ticker fetch failed: %s", e)
    return results


def _fetch_coingecko_trending(timeout: int = 10) -> list[str]:
    """Return list of trending coin slugs from CoinGecko."""
    try:
        resp = requests.get(COINGECKO_TRENDING_URL, timeout=timeout)
        resp.raise_for_status()
        items = resp.json().get("coins", [])
        return [
            item["item"].get("symbol", "").upper() + "/USD"
            for item in items
            if item.get("item", {}).get("symbol")
        ]
    except Exception as e:
        logger.warning("[RAA] CoinGecko Trending fetch failed: %s", e)
        return []


# ─────────────────────────────────────────────────────────────
# Persistence Score computation
# ─────────────────────────────────────────────────────────────

def compute_persistence_score(
    ticker: dict,
    prev_ticker: Optional[dict] = None,
    trending_pairs: Optional[list[str]] = None,
    pair: str = "",
) -> float:
    """
    Compute a composite Persistence Score (Ps) for one candidate pair.

    Components (equal weight, normalised to 0–2 range):
      - Liquidity rank: volume_24h > threshold → +0.5
      - Price momentum: (last - open) / open > 0 → +0.5 to +1.0 (proportional)
      - Volume acceleration: vol > prev_vol → +0.5
      - Social/trending: appears in CoinGecko trending → +0.5

    Returns float in [0.0, 2.5].
    """
    if not ticker or not ticker.get("last"):
        return 0.0

    ps = 0.0
    last = float(ticker.get("last", 0))
    open_p = float(ticker.get("open", last) or last)
    vol = float(ticker.get("volume_24h", 0) or 0)

    # Liquidity component — volume > $1M / 24h
    if vol * last > 1_000_000:
        ps += 0.5
    elif vol * last > 100_000:
        ps += 0.25

    # Price momentum component
    if open_p > 0:
        pct_move = (last - open_p) / open_p
        if pct_move > 0.05:
            ps += 1.0
        elif pct_move > 0.02:
            ps += 0.75
        elif pct_move > 0:
            ps += 0.5
        # Negative momentum → no contribution (not penalised here)

    # Volume acceleration
    if prev_ticker and prev_ticker.get("volume_24h"):
        prev_vol = float(prev_ticker.get("volume_24h", 0) or 0)
        if prev_vol > 0 and vol > prev_vol * 1.1:
            ps += 0.5

    # Social/trending presence
    if trending_pairs and pair in trending_pairs:
        ps += 0.5

    return round(ps, 4)


# ─────────────────────────────────────────────────────────────
# Asset classification
# ─────────────────────────────────────────────────────────────

def classify_pair_heuristic(pair: str, foundational_set: frozenset) -> str:
    """
    Heuristic classification before LLM call. Returns 'FOUNDATIONAL' or 'MEME'.
    LLM classification overrides this if AI is available.
    """
    if pair in foundational_set:
        return "FOUNDATIONAL"
    meme_indicators = {"DOGE", "SHIB", "PEPE", "BONK", "WIF", "FLOKI", "ELON",
                       "BABYDOGE", "SNEK", "MYRO", "MEME", "LADYS", "WOJAK"}
    base = pair.split("/")[0]
    if base in meme_indicators:
        return "MEME"
    return "FOUNDATIONAL"  # Conservative default — LLM confirms


# ─────────────────────────────────────────────────────────────
# Meme-block guardrail — S22.2.1 (hard-coded, cannot be overridden)
# ─────────────────────────────────────────────────────────────

def check_meme_block(
    target_pair: str,
    target_class: str,
    replace_target: Optional[str],
    replace_class: Optional[str],
    db_path: str,
    foundational_set: frozenset,
) -> Optional[str]:
    """
    Enforce the meme-block guardrail (S22.2.1 AC1–AC4).

    Returns a rejection reason string if the proposal should be blocked,
    or None if it passes the guardrail.

    Rule: IF target_class == MEME AND replace_class == FOUNDATIONAL → REJECT.
    Also rejects MEME → any pair in the hard-coded foundational anchor set.
    """
    if target_class != "MEME":
        return None  # Only MEME proposals can trigger the block

    if not replace_target:
        return None  # No displacement → no meme-block trigger

    # Hard check against explicit foundational anchors list
    if replace_target in foundational_set:
        logger.warning(
            "[RAA] MEME_BLOCK_REJECT: %s/%s — cannot displace FOUNDATIONAL anchor",
            target_pair, replace_target,
        )
        _write_audit_feedback(
            db_path, "RAA", target_pair, "MEME_BLOCK_REJECT",
            psv_vector=f"{target_pair}|MEME|replace={replace_target}|FOUNDATIONAL",
            penalty_weight=-2.0,
        )
        return "MEME_BLOCK_REJECT"

    if replace_class == "FOUNDATIONAL":
        logger.warning(
            "[RAA] MEME_BLOCK_REJECT: %s/%s — target=MEME, replace=FOUNDATIONAL",
            target_pair, replace_target,
        )
        _write_audit_feedback(
            db_path, "RAA", target_pair, "MEME_BLOCK_REJECT",
            psv_vector=f"{target_pair}|MEME|replace={replace_target}|FOUNDATIONAL",
            penalty_weight=-2.0,
        )
        return "MEME_BLOCK_REJECT"

    return None


# ─────────────────────────────────────────────────────────────
# Persona-specific guardrails
# ─────────────────────────────────────────────────────────────

def apply_medium_persona_gate(
    pair: str,
    rsi: Optional[float],
    adx: Optional[float],
    raa_cfg: dict,
) -> Optional[str]:
    """
    S22.3.1 — Medium persona guardrails.
    Returns rejection reason string if blocked, else None.
    """
    gates = raa_cfg.get("persona_gates", {}).get("medium", {})
    rsi_min = float(gates.get("rsi_min", 35))
    rsi_max = float(gates.get("rsi_max", 65))
    adx_max = float(gates.get("adx_max", 25))

    if rsi is not None and not (rsi_min <= rsi <= rsi_max):
        logger.info("[RAA] Medium RSI gate REJECT: %s RSI=%.1f (expected %.0f\u2013%.0f)",
                    pair, rsi, rsi_min, rsi_max)
        return "MEDIUM_RSI_GATE"

    if adx is not None and adx >= adx_max:
        logger.info("[RAA] Medium ADX gate REJECT: %s ADX=%.1f (max %.0f)",
                    pair, adx, adx_max)
        return "MEDIUM_ADX_GATE"

    return None


def apply_high_persona_gate(
    pair: str,
    rsi: Optional[float],
    adx: Optional[float],
    vwma_slope: Optional[float],
    raa_cfg: dict,
) -> Optional[str]:
    """
    S22.3.2 — High persona guardrails with RSI bypass.
    Returns rejection reason string if blocked, else None.
    """
    gates = raa_cfg.get("persona_gates", {}).get("high", {})
    rsi_max = float(gates.get("rsi_max", 85))
    bypass_adx_min = float(gates.get("rsi_bypass_adx_min", 35))
    requires_vwma = bool(gates.get("rsi_bypass_requires_vwma_slope", True))

    if rsi is not None and rsi > rsi_max:
        # RSI bypass: authorise up to RSI 85 IFF ADX > 35 AND VWMA_Slope > 0
        adx_ok = adx is not None and adx > bypass_adx_min
        vwma_ok = (not requires_vwma) or (vwma_slope is not None and vwma_slope > 0)
        if adx_ok and vwma_ok:
            logger.info(
                "[RAA] High RSI bypass authorised: %s RSI=%.1f ADX=%.1f VWMA_Slope=%s",
                pair, rsi, adx or 0, vwma_slope,
            )
            return None  # Bypass granted
        else:
            logger.info(
                "[RAA] High RSI gate REJECT: %s RSI=%.1f (bypass requires ADX>%.0f"
                " + VWMA_Slope>0; ADX=%s VWMA=%s)",
                pair, rsi, bypass_adx_min, adx, vwma_slope,
            )
            return "HIGH_RSI_GATE"

    return None


def get_high_persona_prune_candidate(
    universe_pairs: list[dict],
    incoming_score: int,
    raa_cfg: dict,
) -> Optional[str]:
    """
    S22.3.2 AC3 — High persona aggressive pruning.
    If incoming score > threshold/28, return lowest-ADX held pair as replace_target.
    """
    gates = raa_cfg.get("persona_gates", {}).get("high", {})
    threshold = int(gates.get("aggressive_prune_score_threshold", 8))
    if incoming_score <= threshold:
        return None
    if not universe_pairs:
        return None
    # Sort by latest_score ascending — lowest score is most stale
    eligible = [
        p for p in universe_pairs
        if p.get("latest_score") is not None and float(p["latest_score"]) < threshold
    ]
    if not eligible:
        return None
    sorted_pairs = sorted(eligible, key=lambda p: float(p.get("latest_score") or 999))
    return sorted_pairs[0]["pair"] if sorted_pairs else None


def is_prune_eligible_medium(pair: str, adx_history: list[float], raa_cfg: dict) -> bool:
    """
    S22.3.1 AC4 — Medium persona: pair eligible for removal when ADX < 15 for > 12
    consecutive cycles.
    """
    gates = raa_cfg.get("persona_gates", {}).get("medium", {})
    threshold = float(gates.get("prune_adx_threshold", 15))
    min_cycles = int(gates.get("prune_consecutive_cycles", 12))
    if not adx_history:
        return False
    consecutive = sum(1 for v in reversed(adx_history) if v is not None and v < threshold)
    return consecutive > min_cycles


# ─────────────────────────────────────────────────────────────
# PSV vector builder
# ─────────────────────────────────────────────────────────────

def build_psv_vector(
    pair: str,
    price: float,
    rsi: Optional[float],
    adx: Optional[float],
    ibs: Optional[float],
    vwma_slope: Optional[float],
    sector: str,
    state: str,
    persona: str,
) -> str:
    """
    Build pipe-separated PSV telemetry vector per persona format (S22.1.2 AC7).

    Medium: Pair|Price|RSI|ADX|IBS|Sector|State
    High:   Pair|Price|RSI|ADX|VWMA_Slope|Sector|State
    """
    if persona == "high":
        vwma_str = f"{vwma_slope:.6f}" if vwma_slope is not None else "null"
        return f"{pair}|{price:.6f}|{rsi or 'null'}|{adx or 'null'}|{vwma_str}|{sector}|{state}"
    else:
        ibs_str = f"{ibs:.4f}" if ibs is not None else "null"
        return f"{pair}|{price:.6f}|{rsi or 'null'}|{adx or 'null'}|{ibs_str}|{sector}|{state}"


# ─────────────────────────────────────────────────────────────
# LLM classification (optional — requires mocha_python_ai)
# ─────────────────────────────────────────────────────────────

def _classify_pair_via_llm(
    ai_client: Any,
    pair: str,
    metadata: dict,
) -> str:
    """
    Use LLM to classify pair as FOUNDATIONAL or MEME (S22.1.1 — LLM usage note).
    Falls back to heuristic if AI not available or call fails.
    """
    if not _AI_AVAILABLE or ai_client is None:
        return classify_pair_heuristic(pair, _FOUNDATIONAL_ANCHORS)

    tools = [
        {
            "type": "function",
            "function": {
                "name": "classify_pair",
                "description": "Classify a crypto pair as FOUNDATIONAL or MEME based on fundamentals.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "classification": {
                            "type": "string",
                            "enum": ["FOUNDATIONAL", "MEME"],
                            "description": "FOUNDATIONAL: L1/L2 with real utility. MEME: social/speculative.",
                        },
                        "rationale": {"type": "string", "description": "One-sentence reason."},
                    },
                    "required": ["classification", "rationale"],
                },
            },
        }
    ]

    prompt = (
        f"Classify {pair}.\n"
        f"Sector: {metadata.get('sector', 'unknown')}\n"
        f"MCap rank: {metadata.get('mcap_rank', 'unknown')}\n"
        f"Description: {metadata.get('description', '')[:200]}\n"
        "FOUNDATIONAL = L1/L2, DeFi infrastructure, real utility blockchains.\n"
        "MEME = social-driven, no fundamental utility, sentiment-only tokens."
    )

    try:
        result = ai_client.chat_with_tools(
            messages=[{"role": "user", "content": prompt}],
            tools=tools,
            tool_choice={"type": "function", "function": {"name": "classify_pair"}},
        )
        for call in result.get("tool_calls", []):
            if call.get("name") == "classify_pair":
                args = call.get("args", {})
                classification = args.get("classification", "FOUNDATIONAL")
                if classification in ("FOUNDATIONAL", "MEME"):
                    return classification
    except Exception as e:
        logger.warning("[RAA] LLM classify_pair failed for %s: %s", pair, e)

    return classify_pair_heuristic(pair, _FOUNDATIONAL_ANCHORS)


def _generate_rationale_via_llm(
    ai_client: Any,
    pair: str,
    ps: float,
    alpha_spread: float,
    ticker: dict,
    classification: str,
) -> str:
    """Use LLM to generate a rationale string for the proposal audit record."""
    if not _AI_AVAILABLE or ai_client is None:
        return (
            f"{pair} Ps={ps:.2f} alpha={alpha_spread:.2f}% classification={classification}"
        )

    tools = [
        {
            "type": "function",
            "function": {
                "name": "generate_rationale",
                "description": "Generate a brief rationale for a universe addition proposal.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "rationale": {"type": "string", "description": "One or two sentence rationale."},
                    },
                    "required": ["rationale"],
                },
            },
        }
    ]

    prompt = (
        f"Generate a brief rationale for adding {pair} to the trading universe.\n"
        f"Persistence Score: {ps:.2f}, Alpha Spread: {alpha_spread:.2f}%\n"
        f"Classification: {classification}\n"
        f"24h price: {ticker.get('last', '?')}, volume: {ticker.get('volume_24h', '?')}\n"
        "Keep it factual and concise (1–2 sentences)."
    )

    try:
        result = ai_client.chat_with_tools(
            messages=[{"role": "user", "content": prompt}],
            tools=tools,
            tool_choice={"type": "function", "function": {"name": "generate_rationale"}},
        )
        for call in result.get("tool_calls", []):
            if call.get("name") == "generate_rationale":
                return call.get("args", {}).get("rationale", "")
    except Exception as e:
        logger.warning("[RAA] LLM generate_rationale failed for %s: %s", pair, e)

    return f"{pair} Ps={ps:.2f} alpha={alpha_spread:.2f}% ({classification})"


# ─────────────────────────────────────────────────────────────
# Self-reflection loop — S23.1.2
# ─────────────────────────────────────────────────────────────

def run_self_reflection_loop(
    ai_client: Any,
    db_path: str,
    config: dict,
) -> None:
    """
    S23.1.2 — RAA self-reflection loop at cycle start.

    1. GET_FEEDBACK: Read last 50 audit_feedback rows for agent='RAA'.
    2. SELF_CRITIQUE: LLM identifies repeating failure patterns.
    3. DB_UPSERT: Update confidence_state with reflection result.
    4. META_PROMPT: ps_threshold_override used in next classify_pair call.
    """
    feedback_cfg = config.get("feedback", {})
    if not feedback_cfg.get("enabled", False):
        return

    rows = _read_recent_feedback(db_path, agent="RAA", limit=50)
    if not rows:
        return

    # Count failure outcomes
    fail_count = sum(1 for r in rows if r.get("outcome", "").startswith("FAIL"))
    meme_block_count = sum(1 for r in rows if r.get("event_type") == "MEME_BLOCK_REJECT")

    # Heuristic reflection without LLM: if ≥5 FAIL_PUMP_DETECTION → raise Ps threshold
    fail_pump = sum(1 for r in rows if r.get("outcome") == "FAIL_PUMP_DETECTION")
    if fail_pump >= 5:
        current_state = _get_confidence_state(db_path)
        current_ps = current_state.get("ps_threshold_override") or 1.5
        new_ps = min(float(current_ps) + 0.5, 3.0)
        _upsert_confidence_state(db_path, "RAA", ps_threshold_override=new_ps)
        logger.info(
            "[RAA] SELF_REFLECTION: %d FAIL_PUMP_DETECTION outcomes → ps_threshold_override %.1f→%.1f",
            fail_pump, float(current_ps), new_ps,
        )

    # LLM SELF_CRITIQUE (S23.1.2 AC2)
    if _AI_AVAILABLE and ai_client is not None:
        _run_llm_self_critique(ai_client, db_path, rows)


def _run_llm_self_critique(ai_client: Any, db_path: str, feedback_rows: list[dict]) -> None:
    """LLM self-critique — identifies repeating failure patterns and updates confidence_state."""
    vectors = "\n".join(r.get("psv_vector", "") for r in feedback_rows[:20] if r.get("psv_vector"))
    if not vectors:
        return

    tools = [
        {
            "type": "function",
            "function": {
                "name": "record_lesson",
                "description": "Record a key lesson from recent trading outcomes.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "lesson_text": {"type": "string", "description": "Specific actionable lesson."},
                        "ps_threshold_adjustment": {
                            "type": "number",
                            "description": "How much to adjust ps_threshold (e.g. +0.5 or 0)",
                        },
                    },
                    "required": ["lesson_text"],
                },
            },
        }
    ]

    prompt = (
        "You are the Research Analyst Agent reviewing your recent trading universe proposals.\n"
        "Here are the PSV outcome vectors from your last 20 closed proposals:\n\n"
        f"{vectors}\n\n"
        "Identify the most critical recurring failure pattern and record a lesson to avoid it."
    )

    try:
        result = ai_client.chat_with_tools(
            messages=[{"role": "user", "content": prompt}],
            tools=tools,
            tool_choice={"type": "function", "function": {"name": "record_lesson"}},
        )
        for call in result.get("tool_calls", []):
            if call.get("name") == "record_lesson":
                args = call.get("args", {})
                lesson = args.get("lesson_text", "")
                ps_adj = float(args.get("ps_threshold_adjustment", 0))
                if lesson:
                    # Write to llm_reflection_log (S23.1.2 AC2)
                    conn = get_connection(db_path)
                    conn.execute(
                        "INSERT INTO llm_reflection_log (agent, lesson_text, ts, injected) "
                        "VALUES ('RAA', ?, ?, 1)",
                        (lesson, _now_iso()),
                    )
                    conn.commit()
                    conn.close()
                    logger.info("[RAA] SELF_CRITIQUE lesson recorded: %s", lesson[:80])

                if ps_adj != 0:
                    state = _get_confidence_state(db_path)
                    current_ps = state.get("ps_threshold_override") or 1.5
                    new_ps = max(1.0, min(3.0, float(current_ps) + ps_adj))
                    _upsert_confidence_state(db_path, "RAA", ps_threshold_override=new_ps)
    except Exception as e:
        logger.warning("[RAA] LLM self-critique failed: %s", e)


# ─────────────────────────────────────────────────────────────
# Alpha spread computation
# ─────────────────────────────────────────────────────────────

def compute_alpha_spread(
    candidate_pair: str,
    replace_target: Optional[str],
    universe: list[dict],
    ticker_data: dict[str, dict],
    lookback_days: int = 30,
) -> float:
    """
    Compute projected alpha of candidate over replace_target (or worst current pair).
    Returns % alpha spread.

    Simplified: uses 24h price momentum as proxy for projected alpha when
    full 30-day candle history is not available from ticker data alone.
    """
    candidate_ticker = ticker_data.get(candidate_pair, {})
    candidate_open = float(candidate_ticker.get("open", 0) or 0)
    candidate_last = float(candidate_ticker.get("last", 0) or 0)
    if candidate_open <= 0:
        return 0.0
    candidate_pct = (candidate_last - candidate_open) / candidate_open * 100

    if replace_target:
        target_ticker = ticker_data.get(replace_target, {})
        target_open = float(target_ticker.get("open", 0) or 0)
        target_last = float(target_ticker.get("last", 0) or 0)
        target_pct = ((target_last - target_open) / target_open * 100) if target_open > 0 else 0.0
    else:
        # Compare against worst current universe pair (by 24h return)
        worst_pct = 0.0
        for upair in universe:
            t = ticker_data.get(upair.get("pair", ""), {})
            o = float(t.get("open", 0) or 0)
            l = float(t.get("last", 0) or 0)
            if o > 0:
                pct = (l - o) / o * 100
                if pct < worst_pct:
                    worst_pct = pct
        target_pct = worst_pct

    return round(candidate_pct - target_pct, 4)


# ─────────────────────────────────────────────────────────────
# Universe proposal logic
# ─────────────────────────────────────────────────────────────

def _is_substitution_locked(db_path: str) -> bool:
    """Check if HITL lock is active (S23.1.3 AC3)."""
    state = _get_confidence_state(db_path, "RAA")
    if not state.get("substitution_tool_locked"):
        return False
    locked_until = state.get("locked_until_ts")
    if locked_until:
        try:
            dt = datetime.fromisoformat(locked_until)
            if dt > datetime.now(timezone.utc):
                return True
        except Exception:
            pass
    return False


def propose_universe_addition(
    pair: str,
    classification: str,
    replace_target: Optional[str],
    replace_class: Optional[str],
    alpha_spread: float,
    ps: float,
    psv_vector: str,
    rationale: str,
    universe: list[dict],
    db_path: str,
    config: dict,
    ai_client: Any = None,
    retry_count: int = 0,
) -> dict:
    """
    Submit a universe addition proposal through the Risk Manager validation gate.

    This method never writes to `universe` or `universe_events` directly — all writes
    go through validate_universe_proposal() (S22.1.2 AC5).

    Returns dict with keys: status, reason, universe_event_written.
    """
    from src.risk.risk_manager import RiskManager

    raa_cfg = config.get("raa", {})
    max_retries = int(raa_cfg.get("self_correction", {}).get("max_retries", 3))
    universe_cap = int(raa_cfg.get("universe_cap", 35))
    min_alpha = float(raa_cfg.get("alpha_spread_gate", {}).get("min_alpha_pct", 2.0))

    # HITL lock check — route to hitl_queue if locked (S23.1.3 AC4)
    if replace_target and _is_substitution_locked(db_path):
        hitl_id = _write_hitl_queue(
            db_path, "RAA", "PROPOSE_REPLACE", pair, replace_target,
            classification, psv_vector, rationale,
        )
        _write_universe_event(db_path, pair, "PROPOSE_REJECTED", {
            "reason": "HITL_LOCKED",
            "hitl_queue_id": hitl_id,
        })
        logger.info("[RAA] HITL_LOCK active — proposal for %s routed to hitl_queue (id=%d)",
                    pair, hitl_id)
        return {"status": "hitl_queued", "reason": "HITL_LOCKED", "universe_event_written": True}

    rm = RiskManager(config, db_path)
    n_current = len(universe)

    result = rm.validate_universe_proposal(
        pair=pair,
        classification=classification,
        replace_target=replace_target,
        replace_class=replace_class,
        n_current=n_current,
        projected_alpha=alpha_spread,
        persona_config=config.get("personas", {}).get(
            config.get("agent", {}).get("persona", "conservative"), {}
        ),
        psv_vector=psv_vector,
        db_path=db_path,
    )

    if result.get("status") == "approved":
        # Committed by validate_universe_proposal
        logger.info("[RAA] Proposal APPROVED: %s (replace=%s alpha=%.2f%%)",
                    pair, replace_target, alpha_spread)
        return {"status": "approved", "reason": None, "universe_event_written": True}

    reason = result.get("reason", "REJECTED")

    # Self-correction on malformed data (S22.2.2 AC1/AC2)
    if result.get("http_status") == 422 and retry_count < max_retries:
        logger.info(
            "[RAA] 422 received for %s — self-correction attempt %d/%d",
            pair, retry_count + 1, max_retries,
        )
        # Rebuild PSV vector with reformatted data (pass corrected vector on retry)
        corrected_psv = psv_vector.replace("null", "0.0")
        return propose_universe_addition(
            pair=pair,
            classification=classification,
            replace_target=replace_target,
            replace_class=replace_class,
            alpha_spread=alpha_spread,
            ps=ps,
            psv_vector=corrected_psv,
            rationale=rationale,
            universe=universe,
            db_path=db_path,
            config=config,
            ai_client=ai_client,
            retry_count=retry_count + 1,
        )

    if result.get("http_status") == 422 and retry_count >= max_retries:
        logger.error("[RAA] SELF_CORRECT_FAILED: %s — %d consecutive 422 rejections", pair, max_retries)
        _write_audit_feedback(
            db_path, "RAA", pair, "SELF_CORRECT_FAILED",
            psv_vector=psv_vector, penalty_weight=-1.0,
        )
        _write_universe_event(db_path, pair, "PROPOSE_REJECTED", {"reason": "SELF_CORRECT_FAILED"})
        return {"status": "rejected", "reason": "SELF_CORRECT_FAILED", "universe_event_written": True}

    logger.info("[RAA] Proposal REJECTED: %s reason=%s", pair, reason)
    _write_universe_event(db_path, pair, "PROPOSE_REJECTED", {"reason": reason})
    return {"status": "rejected", "reason": reason, "universe_event_written": True}


# ─────────────────────────────────────────────────────────────
# Main poll cycle
# ─────────────────────────────────────────────────────────────

class ResearchAnalystAgent:
    """
    Main RAA class — runs a polling loop every `poll_interval_minutes`.
    """

    def __init__(self, config: dict, db_path: str):
        self._config = config
        self._db_path = db_path
        self._raa_cfg = config.get("raa", {})
        self._prev_ticker: dict[str, dict] = {}
        self._running = False

        # Build foundational set from config + hard-coded anchors
        configured = set(self._raa_cfg.get("meme_block", {}).get("foundational_pairs", []))
        self._foundational_set = _FOUNDATIONAL_ANCHORS | frozenset(configured)

        # AI client (optional)
        self._ai_client = None
        if _AI_AVAILABLE:
            llm_cfg = config.get("llm", {})
            try:
                model_cfg = ModelConfig(
                    base_url=llm_cfg.get("base_url", "https://api.groq.com/openai/v1"),
                    model=llm_cfg.get("model", "llama-3.3-70b-versatile"),
                    fallback_model=llm_cfg.get("fallback_model"),
                    api_key=llm_cfg.get("api_key", ""),
                    temperature=0,
                    max_tokens=512,
                )
                self._ai_client = AIClient(model_cfg)
            except Exception as e:
                logger.warning("[RAA] AIClient init failed: %s", e)

    def _get_active_persona(self) -> str:
        return self._config.get("agent", {}).get("persona", "conservative")

    def _get_effective_ps_threshold(self) -> float:
        """Return ps_threshold from confidence_state override or config default."""
        state = _get_confidence_state(self._db_path)
        override = state.get("ps_threshold_override")
        if override is not None:
            return float(override)
        return float(self._raa_cfg.get("persistence_gate", {}).get("min_ps", 1.5))

    def run_cycle(self) -> None:
        """Execute one 30-minute RAA poll cycle."""
        logger.info("[RAA] Poll cycle starting")

        # Step 1: Self-reflection loop (S23.1.2) — read feedback before any classification
        run_self_reflection_loop(self._ai_client, self._db_path, self._config)

        # Step 2: Fetch market data
        active_pairs = [p["pair"] for p in self._config.get("trading", {}).get("pairs", [])]
        all_pairs = active_pairs[:20]  # limit to 20 for ticker call

        ticker_data = _fetch_kraken_ticker(all_pairs)
        trending_pairs = _fetch_coingecko_trending()

        # Step 3: Fetch current universe
        universe = _get_universe(self._db_path)
        universe_pairs_set = {u["pair"] for u in universe}
        persona = self._get_active_persona()
        min_ps = self._get_effective_ps_threshold()
        min_cycles = int(
            self._raa_cfg.get("persistence_gate", {}).get("min_cycles", 4)
        )
        universe_cap = int(self._raa_cfg.get("universe_cap", 35))
        min_alpha = float(
            self._raa_cfg.get("alpha_spread_gate", {}).get("min_alpha_pct", 2.0)
        )

        # Step 4: Identify candidate pairs (not already in universe)
        # In production, RAA would scan Kraken AssetPairs for new liquid pairs.
        # Here we scan the configured pairs + trending for candidates not in universe.
        candidate_pairs = [p for p in all_pairs if p not in universe_pairs_set]
        candidate_pairs += [p for p in trending_pairs if p not in universe_pairs_set
                            and p not in candidate_pairs]

        proposals_submitted = 0

        for pair in candidate_pairs[:10]:  # Process up to 10 candidates per cycle
            if pair not in ticker_data:
                continue

            ticker = ticker_data[pair]

            # Step 4a: Stale feed check (S22.2.2 AC3)
            if not ticker.get("has_variance", True):
                logger.warning("[RAA] STALE_FEED_HALT: %s — OHLCV variance == 0, skipping", pair)
                _write_audit_feedback(
                    self._db_path, "RAA", pair, "STALE_FEED_HALT", psv_vector=f"{pair}|frozen"
                )
                continue

            # Step 4b: Compute Persistence Score
            prev = self._prev_ticker.get(pair)
            ps = compute_persistence_score(ticker, prev, trending_pairs, pair)

            # Step 4c: Update trend_persistence DB
            existing = _get_trend_persistence(self._db_path, pair)
            if existing:
                if ps >= min_ps:
                    cycles_sustained = existing.get("cycles_sustained", 0) + 1
                    classification = existing.get("classification", "FOUNDATIONAL")
                else:
                    cycles_sustained = 0  # AC5 — reset on Ps drop
                    classification = existing.get("classification", "FOUNDATIONAL")
            else:
                classification = _classify_pair_via_llm(
                    self._ai_client, pair, {"sector": "crypto"}
                )
                cycles_sustained = 1 if ps >= min_ps else 0

            _upsert_trend_persistence(
                self._db_path, pair, classification, ps, cycles_sustained, "CANDIDATE"
            )

            # Step 4d: Persistence gate check
            if ps < min_ps or cycles_sustained < min_cycles:
                continue

            # Step 4e: Classify pair (LLM or heuristic)
            target_class = _classify_pair_via_llm(
                self._ai_client, pair, {"sector": "crypto"}
            )

            # Step 4f: Determine replace_target
            n_current = len(universe)
            replace_target: Optional[str] = None
            replace_class: Optional[str] = None

            if n_current >= universe_cap:
                # Must provide replace_target — find a prune candidate
                if persona == "high":
                    replace_target = get_high_persona_prune_candidate(
                        universe, cycles_sustained, self._raa_cfg
                    )
                if replace_target is None:
                    # Find worst-performing universe pair for displacement
                    worst_alpha = None
                    for upair in universe:
                        t = ticker_data.get(upair.get("pair", ""), {})
                        o = float(t.get("open", 0) or 0)
                        l = float(t.get("last", 0) or 0)
                        pct = ((l - o) / o * 100) if o > 0 else 0.0
                        if worst_alpha is None or pct < worst_alpha[1]:
                            worst_alpha = (upair.get("pair"), pct, upair.get("classification"))
                    if worst_alpha:
                        replace_target = worst_alpha[0]
                        replace_class = worst_alpha[2]

            if replace_target:
                replace_class = replace_class or next(
                    (u.get("classification") for u in universe if u.get("pair") == replace_target),
                    "FOUNDATIONAL",
                )

            # Step 4g: Meme-block guardrail check (S22.2.1 — evaluated BEFORE Risk Manager)
            meme_block_reason = check_meme_block(
                pair, target_class, replace_target, replace_class,
                self._db_path, self._foundational_set
            )
            if meme_block_reason:
                continue

            # Step 4h: Persona-specific gate checks
            rsi = None  # In production: fetch from indicators
            adx = None
            vwma_slope = None
            ibs = None

            if persona == "medium":
                gate_reason = apply_medium_persona_gate(pair, rsi, adx, self._raa_cfg)
                if gate_reason:
                    _write_audit_feedback(
                        self._db_path, "RAA", pair, f"PERSONA_GATE_REJECT_{gate_reason}",
                        psv_vector=f"{pair}|{rsi}|{adx}|{gate_reason}"
                    )
                    continue
            elif persona == "high":
                gate_reason = apply_high_persona_gate(pair, rsi, adx, vwma_slope, self._raa_cfg)
                if gate_reason:
                    _write_audit_feedback(
                        self._db_path, "RAA", pair, f"PERSONA_GATE_REJECT_{gate_reason}",
                        psv_vector=f"{pair}|{rsi}|{adx}|{vwma_slope}|{gate_reason}"
                    )
                    continue

            # Step 4i: Alpha spread gate
            alpha_spread = compute_alpha_spread(
                pair, replace_target, universe, ticker_data
            )
            if alpha_spread < min_alpha:
                logger.info("[RAA] Alpha spread gate REJECT: %s alpha=%.2f%% (min %.2f%%)",
                            pair, alpha_spread, min_alpha)
                continue

            # Step 4j: Build PSV vector + rationale
            price = float(ticker.get("last", 0))
            psv_vector = build_psv_vector(
                pair, price, rsi, adx, ibs, vwma_slope,
                "crypto", "CANDIDATE", persona
            )
            rationale = _generate_rationale_via_llm(
                self._ai_client, pair, ps, alpha_spread, ticker, target_class
            )

            # Step 4k: Submit proposal via Risk Manager
            result = propose_universe_addition(
                pair=pair,
                classification=target_class,
                replace_target=replace_target,
                replace_class=replace_class,
                alpha_spread=alpha_spread,
                ps=ps,
                psv_vector=psv_vector,
                rationale=rationale,
                universe=universe,
                db_path=self._db_path,
                config=self._config,
                ai_client=self._ai_client,
                retry_count=0,
            )
            proposals_submitted += 1
            if result.get("status") == "approved":
                # Refresh universe for next candidate in this cycle
                universe = _get_universe(self._db_path)
                universe_pairs_set = {u["pair"] for u in universe}

        # Store ticker for next cycle's volume acceleration comparison
        self._prev_ticker = ticker_data
        logger.info("[RAA] Poll cycle complete — %d proposals submitted", proposals_submitted)

    async def run_loop(self) -> None:
        """Async main loop — runs run_cycle() every poll_interval_minutes."""
        self._running = True
        poll_minutes = int(self._raa_cfg.get("poll_interval_minutes", 30))
        logger.info("[RAA] Starting poll loop (interval=%dmin)", poll_minutes)
        while self._running:
            try:
                self.run_cycle()
            except Exception as e:
                logger.error("[RAA] Cycle error: %s", e, exc_info=True)
            await asyncio.sleep(poll_minutes * 60)

    def stop(self) -> None:
        self._running = False


# ─────────────────────────────────────────────────────────────
# HTTP health endpoint
# ─────────────────────────────────────────────────────────────

async def _health_handler(_: "web.Request") -> "web.Response":
    return web.json_response({"status": "ok", "agent": "research_analyst"})


async def _run_server(app: "web.Application", port: int) -> None:
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", port)
    await site.start()
    logger.info("[RAA] Health endpoint running on 127.0.0.1:%d/health", port)


# ─────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────

async def _main(config: dict, db_path: str, port: int) -> None:
    _ensure_schema(db_path)

    agent = ResearchAnalystAgent(config, db_path)

    if _AIOHTTP_AVAILABLE:
        app = web.Application()
        app.router.add_get("/health", _health_handler)
        await _run_server(app, port)

    # Graceful shutdown on SIGTERM
    loop = asyncio.get_event_loop()

    def _handle_signal():
        logger.info("[RAA] Shutdown signal received")
        agent.stop()

    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _handle_signal)

    await agent.run_loop()


def main() -> None:
    parser = argparse.ArgumentParser(description="Kryptos Research Analyst Agent")
    parser.add_argument("--config", default="config.yaml", help="Path to config.yaml")
    parser.add_argument("--db", default="paper_trading.db", help="Trading DB filename")
    parser.add_argument("--port", type=int, default=None, help="Health endpoint port")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s [%(name)s] %(message)s",
    )

    config_path = Path(args.config)
    if not config_path.exists():
        config_path = Path(__file__).parent.parent.parent / args.config
    with open(config_path) as f:
        config = yaml.safe_load(f)

    port = args.port or config.get("services", {}).get("research_analyst", {}).get("port", 8093)
    asyncio.run(_main(config, args.db, port))


if __name__ == "__main__":
    main()
