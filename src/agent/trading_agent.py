"""
TradingAgent — orchestrates one decision cycle using a local Ollama LLM.
Uses the Ollama Python client directly with tool/function calling.
The LLM decides; the risk manager enforces; the broker executes.
"""

import json
import logging
import time
from typing import Optional

from ..utils.tz import now_sgt
from ..utils.timing import timed, set_cycle_id

import ollama

from .prompts import SYSTEM_PROMPT, build_cycle_prompt
from .tools import TradingTools

logger = logging.getLogger(__name__)


class TradingAgent:
    """
    Runs one decision cycle per call to run_cycle().
    For each configured pair, the LLM is invoked with the market context
    and calls one of: propose_buy, propose_sell, hold.
    """

    def __init__(
        self,
        tools: TradingTools,
        config: dict,
        mode: str,
        audit_logger,
    ):
        self._tools       = tools
        self._config      = config
        self._mode        = mode
        self._audit       = audit_logger
        llm_cfg           = config.get("llm", {})
        self._model       = llm_cfg.get("model", "qwen3.5:27b")
        self._fallback    = llm_cfg.get("fallback_model", "llama3.1:8b")
        self._timeout     = llm_cfg.get("timeout_seconds", 120)
        self._max_rsn     = llm_cfg.get("max_reasoning_chars", 500)
        self._client      = ollama.Client(
            host=llm_cfg.get("base_url", "http://localhost:11434")
        )

        # Build pair → TP % map for prompt
        trading = config.get("trading", {})
        global_tp = trading.get("take_profit_pct", 10)
        self._pair_tp = {
            p["pair"]: p.get("take_profit_pct", global_tp)
            for p in trading.get("pairs", [])
        }

    # ──────────────────────────────────────────────
    # Tool definitions for Ollama function calling
    # ──────────────────────────────────────────────

    _TOOL_DEFS = [
        {
            "type": "function",
            "function": {
                "name": "propose_buy",
                "description": "Propose buying a crypto pair. Risk manager may cap or reject the amount.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "pair":       {"type": "string", "description": "Trading pair e.g. 'BTC/USD'"},
                        "usd_amount": {"type": "number", "description": "USD amount to invest"},
                    },
                    "required": ["pair", "usd_amount"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "propose_sell",
                "description": "Close an existing open position for a pair.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "pair":   {"type": "string", "description": "Trading pair to close"},
                        "reason": {"type": "string", "description": "Why you are closing"},
                    },
                    "required": ["pair", "reason"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "hold",
                "description": "Do nothing for this pair this cycle. Requires a reason.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "pair":   {"type": "string", "description": "Trading pair"},
                        "reason": {"type": "string", "description": "Why you are holding"},
                    },
                    "required": ["pair", "reason"],
                },
            },
        },
    ]

    # ──────────────────────────────────────────────
    # Main cycle
    # ──────────────────────────────────────────────

    @timed("cycle_id")
    def run_cycle(
        self,
        cycle_id: int,
        portfolio: dict,
        signals: list,
        ai_context: dict = None,
    ) -> list:
        """
        Run one full decision cycle across all pairs.
        Returns list of action summaries.
        """
        set_cycle_id(cycle_id)
        self._tools.set_cycle_context(cycle_id)
        cycle_time = now_sgt().strftime("%Y-%m-%d %H:%M:%S")

        cycle_prompt = build_cycle_prompt(
            cycle_time=cycle_time,
            portfolio=portfolio,
            signals=signals,
            mode=self._mode,
            pair_tp_config=self._pair_tp,
            ai_context=ai_context,
        )

        results = []

        # Process each pair with an individual LLM call
        for sig in signals:
            pair = sig["pair"]
            action_result = self._run_pair_decision(
                cycle_id=cycle_id,
                pair=pair,
                cycle_prompt=cycle_prompt,
                signal=sig,
            )
            results.append({"pair": pair, "result": action_result})

        return results

    @timed("cycle_id", "pair")
    def _run_pair_decision(
        self,
        cycle_id: int,
        pair: str,
        cycle_prompt: str,
        signal: dict,
    ) -> str:
        """Run LLM decision for a single pair."""
        pair_prompt = (
            f"{cycle_prompt}\n\n"
            f"Now make your decision for {pair} only. "
            f"Call ONE tool: propose_buy, propose_sell, or hold."
        )

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": pair_prompt},
        ]

        model = self._model
        start = time.time()
        raw_output = ""
        tool_called = "hold"
        tool_args = {"pair": pair, "reason": "LLM did not respond"}
        decision_type = "HOLD"
        prompt_tokens = None
        completion_tokens = None

        # Log outgoing prompt
        logger.debug(
            "[LLM PROMPT] pair=%s\n--- SYSTEM ---\n%s\n--- USER ---\n%s",
            pair, SYSTEM_PROMPT, pair_prompt,
        )

        logger.info("[LLM] Initiating call — pair=%s model=%s", pair, self._model)

        for attempt in [self._model, self._fallback]:
            try:
                logger.debug("[LLM REQUEST] model=%s pair=%s", attempt, pair)
                response = self._client.chat(
                    model=attempt,
                    messages=messages,
                    tools=self._TOOL_DEFS,
                    options={"temperature": 0.1},
                )
                model = attempt
                msg = response.message
                raw_output = msg.content or ""
                prompt_tokens    = getattr(response, "prompt_eval_count", None)
                completion_tokens= getattr(response, "eval_count", None)

                if msg.tool_calls:
                    tc = msg.tool_calls[0]
                    tool_called = tc.function.name
                    tool_args   = dict(tc.function.arguments)
                    decision_type = (
                        "BUY"  if tool_called == "propose_buy"  else
                        "SELL" if tool_called == "propose_sell" else
                        "HOLD"
                    )

                logger.debug(
                    "[LLM RESPONSE] model=%s pair=%s tool=%s args=%s tokens(prompt=%s,completion=%s)\ncontent: %s",
                    model, pair, tool_called, tool_args,
                    prompt_tokens, completion_tokens, raw_output,
                )
                break
            except Exception as e:
                logger.warning("LLM attempt with %s failed: %s", attempt, e)
                if attempt == self._fallback:
                    self._audit.log_error(
                        "llm", type(e).__name__, str(e)
                    )
                    raw_output = f"LLM error: {e}"

        latency_ms = int((time.time() - start) * 1000)
        logger.info("[LLM] Completed — pair=%s model=%s decision=%s latency=%dms", pair, model, decision_type, latency_ms)

        # Audit LLM decision (BUY, SELL, or HOLD — all logged)
        hold_reason = tool_args.get("reason") if tool_called == "hold" else None
        decision_id = self._audit.log_llm_decision(
            cycle_id=cycle_id,
            pair=pair,
            model_name=model,
            decision_type=decision_type,
            tool_called=tool_called,
            raw_llm_output=raw_output,
            tool_args=tool_args,
            hold_reason=hold_reason,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            latency_ms=latency_ms,
            max_reasoning_chars=self._max_rsn,
        )

        self._tools.set_llm_decision_id(decision_id)

        # Execute the tool — always use the known pair from signals, never the LLM's
        # tool_args pair (which may be hallucinated)
        try:
            if tool_called == "propose_buy":
                return self._tools.propose_buy(
                    pair=pair,
                    usd_amount=float(tool_args.get("usd_amount", 0)),
                )
            elif tool_called == "propose_sell":
                return self._tools.propose_sell(
                    pair=pair,
                    reason=tool_args.get("reason", "Agent decision"),
                )
            else:
                return self._tools.hold(
                    pair=pair,
                    reason=tool_args.get("reason", "No reason given"),
                )
        except Exception as e:
            self._audit.log_error("agent", type(e).__name__, str(e))
            logger.error("Tool execution error for %s: %s", pair, e)
            # Fallback to hold on any execution error
            return self._tools.hold(pair=pair, reason=f"Error fallback: {e}")
