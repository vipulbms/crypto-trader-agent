"""
Structured JSON logging for LLM interactions.

Every LLM call (one per cycle) is written as a single JSON record to
logs/agent-llm-prompts.log, with rotation at 100 MB and a maximum of 5
files (1 active + 4 backups).

Public API:
    init_llm_logger(log_dir, config)  — call once at startup
    log_llm_interaction(...)          — call once per LLM response
"""

import json
import logging
import os
import time
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from typing import Any, Dict, List, Optional

# ──────────────────────────────────────────────────────────────
# Pricing table (Groq pay-as-you-go, USD per 1M tokens, April 2026)
# Update when model pricing changes.
# Local Ollama models have zero cost.
# ──────────────────────────────────────────────────────────────
_PRICING: Dict[str, Dict[str, float]] = {
    "qwen/qwen3-32b":            {"input": 0.29,  "output": 0.59},
    "qwen3-32b":                 {"input": 0.29,  "output": 0.59},
    "llama-3.3-70b-versatile":   {"input": 0.59,  "output": 0.79},
    "llama3.3-70b-versatile":    {"input": 0.59,  "output": 0.79},
    # Gemini (fallback provider)
    "gemini-2.5-flash":          {"input": 0.15,  "output": 0.60},
    # Ollama local — always free
    "deepseek-r1:7b":            {"input": 0.0,   "output": 0.0},
}

_DEFAULT_PRICING: Dict[str, float] = {"input": 0.0, "output": 0.0}

# Internal logger (writes to the JSON handler only)
_llm_log: logging.Logger = logging.getLogger("llm_prompts")
_llm_log.propagate = False  # do not bubble up to root logger / agent.log


def _estimate_cost(model_id: str, prompt_tokens: Optional[int], completion_tokens: Optional[int]) -> Optional[float]:
    """Return estimated USD cost, or None if token counts are unavailable."""
    if prompt_tokens is None and completion_tokens is None:
        return None
    pricing = _PRICING.get(model_id, _DEFAULT_PRICING)
    input_cost  = ((prompt_tokens or 0) / 1_000_000) * pricing["input"]
    output_cost = ((completion_tokens or 0) / 1_000_000) * pricing["output"]
    return round(input_cost + output_cost, 8)


def init_llm_logger(log_dir: str = "/logs", config: Optional[Dict] = None) -> None:
    """
    Set up the RotatingFileHandler for agent-llm-prompts.log.
    Call once at agent startup, after the main log handlers are configured.

    File limits: 100 MB per file, 5 files maximum (backupCount=4).
    Each log record is written as a single JSON line.
    """
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, "agent-llm-prompts.log")

    cfg_storage = (config or {}).get("storage", {})
    max_bytes    = cfg_storage.get("log_max_bytes", 104_857_600)  # 100 MB
    backup_count = 4  # 1 active + 4 rotated = 5 total

    handler = RotatingFileHandler(
        log_path,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    # Each record body is already a JSON string; the formatter just passes it through.
    handler.setFormatter(logging.Formatter("%(message)s"))
    handler.setLevel(logging.DEBUG)

    _llm_log.setLevel(logging.DEBUG)
    if not _llm_log.handlers:
        _llm_log.addHandler(handler)


def log_llm_interaction(
    *,
    request_id: str,
    session_id: str,
    cycle_id: int,
    model_id: str,
    system_prompt: str,
    user_message: str,
    raw_output: str,
    tool_calls: List[Dict[str, Any]],
    prompt_tokens: Optional[int],
    completion_tokens: Optional[int],
    latency_ms: int,
    call_start_utc: str,
    user_id: str = "kryptos",
    prompt_template: str = "build_cycle_prompt_v1",
) -> None:
    """
    Write one JSON record to agent-llm-prompts.log.

    Fields logged:
    1. Request metadata: request_id, session_id, timestamp_utc, model_id, user_id, cycle_id
    2. Prompt & content: system_prompt, user_message, raw_output, tool_calls, prompt_template
    3. Token telemetry: prompt_tokens, completion_tokens, total_tokens, estimated_cost_usd
    4. Performance: latency_ms, time_to_first_token_ms, generation_time_ms, tool_call_latency_ms

    Notes:
    - time_to_first_token_ms is null — synchronous SDK returns full response at once;
      populate if streaming is enabled in future.
    - tool_call_latency_ms is null — tools are local Python functions, not network calls.
    - generation_time_ms is null — not separately measurable from synchronous SDK.
    """
    total_tokens = (
        (prompt_tokens or 0) + (completion_tokens or 0)
        if (prompt_tokens is not None or completion_tokens is not None)
        else None
    )

    record: Dict[str, Any] = {
        # 1. Request metadata
        "request_id":      request_id,
        "session_id":      session_id,
        "timestamp_utc":   call_start_utc,
        "model_id":        model_id,
        "user_id":         user_id,
        "cycle_id":        cycle_id,
        # 2. Prompt & content
        "prompt_template": prompt_template,
        "system_prompt":   system_prompt,
        "user_message":    user_message,
        "raw_output":      raw_output,
        "tool_calls":      tool_calls,
        # 3. Token telemetry
        "prompt_tokens":        prompt_tokens,
        "completion_tokens":    completion_tokens,
        "total_tokens":         total_tokens,
        "estimated_cost_usd":   _estimate_cost(model_id, prompt_tokens, completion_tokens),
        # 4. Performance metrics
        "latency_ms":               latency_ms,
        "time_to_first_token_ms":   None,   # not available from sync SDK
        "generation_time_ms":       None,   # not separately measurable
        "tool_call_latency_ms":     None,   # local functions, no network latency
    }

    _llm_log.info(json.dumps(record, ensure_ascii=False))
