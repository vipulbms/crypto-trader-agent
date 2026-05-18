"""
nl_parser.py — Natural-language to intent parser for the Kryptos CLI.

Primary strategy: ask the local Ollama LLM to classify the user input as a
structured JSON intent.

Fallback strategy: keyword matching (used when Ollama is unavailable).
"""

import json
import logging
import re
import time
from typing import Optional

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────
# Intent catalogue
# ──────────────────────────────────────────────────────────────
# Each intent has a name and an optional parameter set.

INTENTS = {
    "start_agent":      "Start the Kryptos trading agent",
    "stop_agent":       "Stop the running trading agent",
    "agent_status":     "Show whether the agent is running and basic stats",
    "next_schedule":    "Show when the next trading cycle will run",
    "view_report":      "Show trade history / performance report",
    "trade_details":    "Show details (incl. LLM reasoning) for specific trades",
    "llm_decisions":    "Show LLM decision patterns and reasoning",
    "daily_summary":    "Show summary of trading activity for a specific day",
    "daily_report":     "Show the full rich daily P&L report including per-pair stats and error count",
    "review":           "Show a multi-day performance review with win rate, drawdown, and a live-trading readiness verdict",
    "win_rate":         "Show win/loss stats and performance metrics",
    "open_positions":   "Show currently open positions",
    "signal_drivers":   "Show top blocking signal reasons per pair",
    "tail_log":         "Show the last lines of the agent log",
    "persona":          "Show active persona and all persona parameter summaries",
    "persona_set":      "Change the active risk persona (conservative, medium, high)",
    "regime":           "Show current detected market regime and active playbook",
    "help":             "Show available commands",
    "exit":             "Exit the Kryptos CLI",
}

PAIRS = [
    "BTC/USD", "ETH/USD", "BNB/USD", "SOL/USD", "XRP/USD", "TRX/USD", "DOGE/USD",
    "ADA/USD", "LTC/USD", "RAILS/USD", "AVAX/USD", "SUI/USD", "HYPE/USD", "UNI/USD", "INJ/USD",
    "WIF/USD", "TON/USD", "OP/USD", "ARB/USD", "JUP/USD", "PEPE/USD", "TIA/USD",
    "RENDER/USD", "FET/USD", "STX/USD",
    "PENDLE/USD", "ONDO/USD", "BONK/USD", "MOVR/USD",
    "BTC", "ETH", "BNB", "SOL", "XRP", "TRX", "DOGE", "XDG", "ADA", "LTC", "RAILS",
    "AVAX", "SUI", "HYPE", "UNI", "INJ",
    "WIF", "TON", "OP", "ARB", "JUP", "PEPE", "TIA", "RENDER", "FET", "STX",
    "PENDLE", "ONDO", "BONK", "MOVR",
]

_SYSTEM_PROMPT = """You are an intent-classification assistant for a crypto trading CLI called Kryptos.

The user types natural-language commands. You MUST respond with ONLY a JSON object — no extra text, no markdown.

Available intents:
{intents}

Parameters you can extract:
- mode: "paper" or "live"  (default: "paper")
- pair: one of BTC/USD, ETH/USD, BNB/USD, SOL/USD, XRP/USD, TRX/USD, DOGE/USD, ADA/USD, LTC/USD, RAILS/USD, AVAX/USD, SUI/USD, HYPE/USD, UNI/USD, INJ/USD, WIF/USD, TON/USD, OP/USD, ARB/USD, JUP/USD, PEPE/USD, TIA/USD, RENDER/USD, FET/USD, STX/USD, PENDLE/USD, ONDO/USD, BONK/USD, MOVR/USD  (or null)
- days: integer number of days  (default: 7 for decisions, 30 for trades, 14 for review)
- days_ago: integer offset from today for daily_report (0=today, 1=yesterday, etc.)
- count: integer number of records to show
- date: ISO date string YYYY-MM-DD  (or null)
- decision_type: "BUY", "SELL", or "HOLD"  (or null)
- detail: "summary" or "detailed"  (default: "summary")
- lines: integer number of log lines to show  (default: 30)

Response format (strict JSON, nothing else):
{{
  "intent": "<intent_name>",
  "params": {{
    "mode": "paper",
    "pair": null,
    "days": 7,
    "days_ago": 0,
    "count": null,
    "date": null,
    "decision_type": null,
    "detail": "summary",
    "lines": 30
  }}
}}

Classify the user input below.
""".format(intents="\n".join(f"- {k}: {v}" for k, v in INTENTS.items()))


class NLParser:
    """
    Converts a free-text user query into a structured intent dict.
    Uses Ollama when available; falls back to keyword matching otherwise.
    """

    def __init__(self, model: str = "qwen2.5:14b", base_url: str = "http://localhost:11434"):
        self._model    = model
        self._base_url = base_url
        self._client   = None
        self._ollama_ok = True  # optimistic; set False on first failure

    def _get_client(self):
        if self._client is None:
            try:
                import ollama
                self._client = ollama.Client(host=self._base_url)
            except ImportError:
                self._ollama_ok = False
        return self._client

    # ──────────────────────────────────────────────
    # Public
    # ──────────────────────────────────────────────

    def parse(self, text: str) -> dict:
        """
        Parse natural language text into an intent dict:
        { "intent": str, "params": dict, "raw_text": str, "source": "llm"|"keyword" }
        """
        text = text.strip()
        if not text:
            return self._make(intent="help", params={}, source="keyword", raw=text)

        # Direct single-word commands bypass LLM
        lower = text.lower()
        if lower in ("exit", "quit", "q", "bye"):
            return self._make("exit", {}, "keyword", text)
        if lower in ("help", "?", "h"):
            return self._make("help", {}, "keyword", text)
        if lower in ("status",):
            return self._make("agent_status", {}, "keyword", text)
        if lower in ("stop",):
            return self._make("stop_agent", {}, "keyword", text)

        # Try LLM
        if self._ollama_ok:
            result = self._llm_parse(text)
            if result:
                result["raw_text"] = text
                result["source"]   = "llm"
                return result

        # Fallback to keyword matching
        result = self._keyword_parse(text)
        result["raw_text"] = text
        result["source"]   = "keyword"
        return result

    # ──────────────────────────────────────────────
    # LLM strategy
    # ──────────────────────────────────────────────

    def _llm_parse(self, text: str) -> Optional[dict]:
        try:
            client = self._get_client()
            if client is None:
                return None

            logger.info("[LLM] Initiating intent parse — model=%s", self._model)
            _start = time.time()
            resp = client.chat(
                model=self._model,
                options={"temperature": 0.0},
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user",   "content": text},
                ],
            )
            logger.info("[LLM] Intent parse completed — model=%s latency=%dms", self._model, int((time.time() - _start) * 1000))
            raw = resp.message.content.strip()

            # Strip markdown code fences if present
            raw = re.sub(r"```(?:json)?", "", raw).strip().rstrip("`").strip()

            parsed = json.loads(raw)
            if "intent" not in parsed or parsed["intent"] not in INTENTS:
                logger.debug("LLM returned unknown intent: %s", parsed.get("intent"))
                return None
            parsed.setdefault("params", {})
            parsed["params"] = self._normalise_params(parsed["params"])
            return parsed

        except json.JSONDecodeError as e:
            logger.debug("LLM intent JSON decode error: %s", e)
            return None
        except Exception as e:
            logger.debug("Ollama intent call failed: %s — switching to keyword fallback", e)
            self._ollama_ok = False
            return None

    # ──────────────────────────────────────────────
    # Keyword strategy
    # ──────────────────────────────────────────────

    def _keyword_parse(self, text: str) -> dict:
        lower = text.lower()
        params = self._extract_keyword_params(lower)

        # Start agent
        if any(kw in lower for kw in ("start", "run", "launch", "trade", "begin")):
            return self._make("start_agent", params, "keyword", text)

        # Stop agent
        if any(kw in lower for kw in ("stop", "halt", "kill", "pause agent")):
            return self._make("stop_agent", params, "keyword", text)

        # Status
        if any(kw in lower for kw in ("status", "running", "alive", "is the agent")):
            return self._make("agent_status", params, "keyword", text)

        # Next schedule
        if any(kw in lower for kw in ("next", "schedule", "when", "timer")):
            return self._make("next_schedule", params, "keyword", text)

        # Win rate / metrics
        if any(kw in lower for kw in ("win rate", "win/loss", "performance", "metric", "stats", "statistics")):
            return self._make("win_rate", params, "keyword", text)

        # Open positions
        if any(kw in lower for kw in ("open position", "holding", "current position", "what do i hold")):
            return self._make("open_positions", params, "keyword", text)

        # Daily summary
        if any(kw in lower for kw in ("today", "daily", "day", "yesterday", "this morning")):
            return self._make("daily_summary", params, "keyword", text)

        # LLM decisions / reasoning
        if any(kw in lower for kw in ("reasoning", "why", "decision", "llm", "ai chose", "model said", "hold reason")):
            return self._make("llm_decisions", params, "keyword", text)

        # Trade details
        if any(kw in lower for kw in ("trade detail", "specific trade", "show trade", "last trade", "recent trade")):
            return self._make("trade_details", params, "keyword", text)

        # Log tail
        if any(kw in lower for kw in ("log", "tail", "last log", "agent log")):
            return self._make("tail_log", params, "keyword", text)

        # Persona set
        if any(kw in lower for kw in ("set persona", "switch persona", "change persona", "persona set", "aggressive mode", "conservative mode", "medium mode")):
            for name in ("conservative", "medium", "high"):
                if name in lower:
                    params["persona"] = name
                    break
            return self._make("persona_set", params, "keyword", text)

        # Persona show
        if any(kw in lower for kw in ("persona", "risk profile", "trading style")):
            return self._make("persona", params, "keyword", text)

        # Regime / playbook
        if any(kw in lower for kw in ("regime", "playbook", "market regime", "current regime", "momentum mode", "ranging mode")):
            return self._make("regime", params, "keyword", text)

        # General report / trades
        if any(kw in lower for kw in ("report", "history", "show trade", "all trade", "closed trade", "how many")):
            return self._make("view_report", params, "keyword", text)

        # Help
        if any(kw in lower for kw in ("help", "what can", "commands", "how do i")):
            return self._make("help", params, "keyword", text)

        # Exit
        if any(kw in lower for kw in ("exit", "quit", "bye")):
            return self._make("exit", params, "keyword", text)

        # Default: show report
        return self._make("view_report", params, "keyword", text)

    def _extract_keyword_params(self, lower: str) -> dict:
        params: dict = {"mode": "paper"}

        # Mode
        if "live" in lower:
            params["mode"] = "live"

        # Pair
        for p in PAIRS:
            if p.lower() in lower:
                if "/" not in p:
                    p = p + "/USD"
                params["pair"] = p
                break

        # Days
        m = re.search(r"(\d+)\s*day", lower)
        if m:
            params["days"] = int(m.group(1))
        elif "week" in lower:
            params["days"] = 7
        elif "month" in lower:
            params["days"] = 30

        # Count / last N
        m = re.search(r"last\s+(\d+)", lower)
        if m:
            params["count"] = int(m.group(1))

        # Decision type
        for dt in ("buy", "sell", "hold"):
            if dt in lower:
                params["decision_type"] = dt.upper()
                break

        # Detail level
        if any(kw in lower for kw in ("detailed", "full", "everything", "raw")):
            params["detail"] = "detailed"

        # Log lines
        m = re.search(r"(\d+)\s*line", lower)
        if m:
            params["lines"] = int(m.group(1))

        return params

    # ──────────────────────────────────────────────
    # Helpers
    # ──────────────────────────────────────────────

    @staticmethod
    def _make(intent: str, params: dict, source: str, raw: str = "") -> dict:
        return {
            "intent": intent,
            "params": NLParser._normalise_params(params),
            "source": source,
            "raw_text": raw,
        }

    @staticmethod
    def _normalise_params(p: dict) -> dict:
        """Fill in defaults for any missing param keys."""
        defaults = {
            "mode": "paper",
            "pair": None,
            "days": None,
            "count": None,
            "date": None,
            "decision_type": None,
            "detail": "summary",
            "lines": 30,
        }
        defaults.update({k: v for k, v in (p or {}).items() if v is not None})
        return defaults
