"""
TradingAgent — orchestrates one decision cycle using a local Ollama LLM.
Uses the Ollama Python client directly with tool/function calling.

Decision model: ONE LLM call per cycle across ALL pairs.
The LLM reviews all signals simultaneously, ranks BUY candidates, and
selects at most max_buys_per_cycle (default: 7) to propose buying.
Sell candidates are evaluated against open positions.
All other pairs are implicitly held and logged as HOLD in the audit trail.

The LLM decides; the risk manager enforces; the broker executes.
Stop-loss exits are fully autonomous via the risk manager — outside this flow.
"""

import json
import logging
import os
import re
import time
import uuid
from datetime import datetime, timezone
from typing import Optional

from ..utils.tz import now_sgt
from ..utils.timing import timed, set_cycle_id, set_request_id, current_cycle_id
from ..utils.llm_logger import log_llm_interaction

import httpx
import ollama

from .prompts import SYSTEM_PROMPT, build_cycle_prompt
from .tools import TradingTools

logger = logging.getLogger(__name__)


class TradingAgent:
    """
    Runs one decision cycle per call to run_cycle().
    A single LLM call evaluates ALL pairs and selects the top candidates to act on.
    """

    def __init__(
        self,
        tools: TradingTools,
        config: dict,
        mode: str,
        audit_logger,
        session_id: str = "",
    ):
        self._tools       = tools
        self._config      = config
        self._mode        = mode
        self._audit       = audit_logger
        self._session_id  = session_id
        llm_cfg           = config.get("llm", {})
        self._provider    = llm_cfg.get("provider", "ollama")
        self._model       = llm_cfg.get("model", "qwen2.5:14b")
        self._fallback    = llm_cfg.get("fallback_model", "llama3.1:8b")
        self._timeout     = llm_cfg.get("timeout_seconds", 120)
        self._max_rsn     = llm_cfg.get("max_reasoning_chars", 500)
        self._request_delay = llm_cfg.get("request_delay_seconds", 0)
        self._max_buys    = config.get("trading", {}).get("max_buys_per_cycle", 2)
        self._min_order_usd = config.get("risk", {}).get("min_order_usd", 20.0)
        self._disable_thinking = llm_cfg.get("disable_thinking", False)
        self._system_prompt = llm_cfg.get("system_prompt") or SYSTEM_PROMPT
        self._current_ctx = None  # set per cycle by run_cycle() (S12.1.2 AC4)
        if not llm_cfg.get("system_prompt"):
            logger.warning("[AGENT] llm.system_prompt not found in config — using fallback")

        if self._provider == "openai_compat":
            from openai import OpenAI
            api_key = os.environ.get(llm_cfg.get("api_key_env", "OPENAI_API_KEY"), "")
            self._client = OpenAI(
                api_key=api_key,
                base_url=llm_cfg.get("base_url"),
                timeout=self._timeout,
            )
        else:
            self._client = ollama.Client(
                host=llm_cfg.get("base_url", "http://localhost:11434"),
                timeout=self._timeout,
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
                "description": "Propose buying a crypto pair. Only call for the top-ranked BUY signals (max 2 per cycle). Risk manager may cap or reject the amount.",
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
                "description": "Close an existing open position. Only call if Signal=SELL with clear momentum reversal, or position is near take-profit showing reversal.",
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
                "description": "Explicitly hold a pair. Only use this if you need to record a hold decision with a reason. Most pairs are implicitly held by not calling any tool.",
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
    # Main cycle — single LLM call for all pairs
    # ──────────────────────────────────────────────

    @timed("cycle_id")
    def run_cycle(
        self,
        cycle_id: int,
        portfolio: dict,
        signals: list,
        ai_context: dict = None,
        cycle_context=None,
    ) -> list:
        """
        Run one full decision cycle across all pairs with a single LLM call.
        Returns list of action summaries.
        """
        self._current_ctx = cycle_context  # persona LLM params (S12.1.2 AC4)
        set_cycle_id(cycle_id)
        self._tools.set_cycle_context(cycle_id)
        self._tools.set_dynamic_tp_values((ai_context or {}).get("dynamic_tp_values", {}))
        self._tools.set_pair_max_usd({
            sig["pair"]: sig.get("pair_max_usd")
            for sig in signals
            if sig.get("pair_max_usd") is not None
        })
        self._tools.set_signal_scores({
            sig["pair"]: sig.get("score", 0)
            for sig in signals
            if sig.get("signal") == "BUY"
        })
        cycle_time = now_sgt().strftime("%Y-%m-%d %H:%M:%S")

        cycle_prompt = build_cycle_prompt(
            cycle_time=cycle_time,
            portfolio=portfolio,
            signals=signals,
            mode=self._mode,
            pair_tp_config=self._pair_tp,
            ai_context=ai_context,
            max_buys_per_cycle=self._max_buys,
            min_order_usd=self._min_order_usd,
        )

        return self._run_cycle_decision(
            cycle_id=cycle_id,
            cycle_prompt=cycle_prompt,
            signals=signals,
        )

    # ──────────────────────────────────────────────
    # Single LLM call covering all pairs
    # ──────────────────────────────────────────────

    def _run_cycle_decision(
        self,
        cycle_id: int,
        cycle_prompt: str,
        signals: list,
    ) -> list:
        """
        Make one LLM call for the entire cycle.
        The LLM returns multiple tool calls — one per pair it chooses to act on.
        All other pairs are automatically logged as HOLD.
        """
        messages = [
            {"role": "system", "content": self._system_prompt},
            {"role": "user",   "content": cycle_prompt},
        ]

        logger.info("[LLM] Initiating cycle decision — model=%s pairs=%d max_buys=%d",
                    self._model, len(signals), self._max_buys)

        start = time.time()
        raw_output = ""
        tool_calls_made = []
        model_used = self._model
        prompt_tokens = None
        completion_tokens = None

        logger.debug("[LLM PROMPT]\n--- SYSTEM ---\n%s\n--- USER ---\n%s",
                     self._system_prompt, cycle_prompt)

        for attempt in [self._model, self._fallback]:
            try:
                logger.debug("[LLM REQUEST] model=%s provider=%s", attempt, self._provider)

                if self._provider == "openai_compat":
                    tool_calls_made, raw_output, prompt_tokens, completion_tokens = \
                        self._call_openai_compat(attempt, messages)
                else:
                    tool_calls_made, raw_output, prompt_tokens, completion_tokens = \
                        self._call_ollama(attempt, messages)

                model_used = attempt
                logger.debug("[LLM RESPONSE] model=%s tool_calls=%d tokens(prompt=%s,completion=%s)\ncontent: %s",
                             model_used, len(tool_calls_made),
                             prompt_tokens, completion_tokens, raw_output)
                break
            except httpx.TimeoutException as e:
                logger.error("[LLM] Timeout after %ds — model=%s: %s", self._timeout, attempt, e)
                self._audit.log_error("llm", "LLMTimeout",
                                      f"Timeout after {self._timeout}s — model={attempt}: {e}")
                if attempt == self._fallback:
                    raw_output = f"LLM timeout after {self._timeout}s"
            except Exception as e:
                logger.warning("LLM attempt with %s failed: %s", attempt, e)
                if attempt == self._fallback:
                    self._audit.log_error("llm", type(e).__name__, str(e))
                    raw_output = f"LLM error: {e}"

        latency_ms = int((time.time() - start) * 1000)
        logger.info("[LLM] Cycle decision completed — model=%s tool_calls=%d latency=%dms",
                    model_used, len(tool_calls_made), latency_ms)

        if self._request_delay > 0:
            logger.debug("[LLM] Rate limit delay: %.1fs", self._request_delay)
            time.sleep(self._request_delay)

        # Safety net 1: zero tool calls = entire cycle silently held — warn loudly
        if not tool_calls_made:
            buy_count_in_signals = sum(1 for s in signals if s.get("signal") == "BUY")
            logger.warning(
                "[AGENT] LLM returned ZERO tool calls — all %d pairs will be held this cycle "
                "(%d BUY signals present). Model may have failed to use tools.",
                len(signals), buy_count_in_signals,
            )
            self._audit.log_error(
                "agent", "ZeroToolCalls",
                f"LLM returned no tool calls — {len(signals)} pairs held, {buy_count_in_signals} BUY signals missed",
            )

        # Build signal lookup for safety net 2
        signal_by_pair = {s["pair"]: s.get("signal", "HOLD") for s in signals}

        # ── Process tool calls from LLM ───────────────────────────
        actioned_pairs: set = set()
        buy_count = 0
        results = []

        for tc in tool_calls_made:
            tool_called = tc.function.name
            tool_args   = dict(tc.function.arguments)
            llm_pair    = tool_args.get("pair", "")

            # Hard cap on buys — safety net in case LLM ignores the prompt limit
            if tool_called == "propose_buy":
                if buy_count >= self._max_buys:
                    logger.warning(
                        "[AGENT] LLM proposed more than %d buys — skipping %s",
                        self._max_buys, llm_pair,
                    )
                    continue
                buy_count += 1

            # Resolve pair against known signals (hallucination guard)
            matched_pair = self._resolve_pair(llm_pair, signals)
            if not matched_pair:
                logger.warning(
                    "[AGENT] LLM called %s with unknown pair '%s' — skipping",
                    tool_called, llm_pair,
                )
                continue

            # Safety net 2: signal mismatch — LLM proposed BUY on a non-BUY signal pair
            if tool_called == "propose_buy":
                actual_signal = signal_by_pair.get(matched_pair, "HOLD")
                if actual_signal != "BUY":
                    logger.warning(
                        "[AGENT] LLM proposed BUY for %s but signal is %s — skipping",
                        matched_pair, actual_signal,
                    )
                    buy_count -= 1  # undo the increment
                    continue

            actioned_pairs.add(matched_pair)

            decision_type = (
                "BUY"  if tool_called == "propose_buy"  else
                "SELL" if tool_called == "propose_sell" else
                "HOLD"
            )
            hold_reason = tool_args.get("reason") if tool_called == "hold" else None

            decision_id = self._audit.log_llm_decision(
                cycle_id=cycle_id,
                pair=matched_pair,
                model_name=model_used,
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

            try:
                if tool_called == "propose_buy":
                    result = self._tools.propose_buy(
                        pair=matched_pair,
                        usd_amount=float(tool_args.get("usd_amount", 0)),
                    )
                elif tool_called == "propose_sell":
                    result = self._tools.propose_sell(
                        pair=matched_pair,
                        reason=tool_args.get("reason", "Agent decision"),
                    )
                else:
                    result = self._tools.hold(
                        pair=matched_pair,
                        reason=tool_args.get("reason", "LLM hold"),
                    )
            except Exception as e:
                self._audit.log_error("agent", type(e).__name__, str(e))
                logger.error("Tool execution error for %s: %s", matched_pair, e)
                result = self._tools.hold(pair=matched_pair, reason=f"Error fallback: {e}")

            results.append({"pair": matched_pair, "result": result})

        # ── Implicit HOLD for all pairs not explicitly actioned ───
        for sig in signals:
            pair = sig["pair"]
            if pair in actioned_pairs:
                continue

            hold_args = {"pair": pair, "reason": "Not selected this cycle"}
            decision_id = self._audit.log_llm_decision(
                cycle_id=cycle_id,
                pair=pair,
                model_name=model_used,
                decision_type="HOLD",
                tool_called="hold",
                raw_llm_output="",
                tool_args=hold_args,
                hold_reason="Not selected this cycle",
                latency_ms=0,
                max_reasoning_chars=self._max_rsn,
            )
            self._tools.set_llm_decision_id(decision_id)
            result = self._tools.hold(pair=pair, reason="Not selected this cycle")
            results.append({"pair": pair, "result": result})

        return results

    # ──────────────────────────────────────────────
    # Provider-specific LLM call helpers
    # ──────────────────────────────────────────────

    def _call_ollama(self, model: str, messages: list) -> tuple:
        """Call Ollama and return (tool_calls, raw_output, prompt_tokens, completion_tokens)."""
        request_id = str(uuid.uuid4())
        call_start_utc = datetime.now(timezone.utc).isoformat()
        call_start = time.time()
        set_request_id(request_id)

        response = self._client.chat(
            model=model,
            messages=messages,
            tools=self._TOOL_DEFS,
            options={"temperature": self._current_ctx.llm_temperature if self._current_ctx else 0.1},
        )
        latency_ms = int((time.time() - call_start) * 1000)

        msg = response.message
        tool_calls = msg.tool_calls or []
        raw_output = msg.content or ""
        prompt_tokens     = getattr(response, "prompt_eval_count", None)
        completion_tokens = getattr(response, "eval_count", None)

        system_msg = next((m["content"] for m in messages if m["role"] == "system"), "")
        user_msg   = next((m["content"] for m in messages if m["role"] == "user"), "")
        log_llm_interaction(
            request_id=request_id,
            session_id=self._session_id,
            cycle_id=current_cycle_id.get(),
            model_id=model,
            system_prompt=system_msg,
            user_message=user_msg,
            raw_output=raw_output,
            tool_calls=[{"name": tc.function.name, "args": dict(tc.function.arguments)} for tc in tool_calls],
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            latency_ms=latency_ms,
            call_start_utc=call_start_utc,
        )

        return tool_calls, raw_output, prompt_tokens, completion_tokens

    def _call_openai_compat(self, model: str, messages: list) -> tuple:
        """
        Call any OpenAI-compatible endpoint (Gemini, OpenRouter, Groq, etc.)
        and normalise the response to the same tuple as _call_ollama.
        Returns (tool_calls, raw_output, prompt_tokens, completion_tokens)
        where tool_calls is a list of objects with .function.name and .function.arguments.

        For qwen3-class reasoning models on Groq: when disable_thinking=True,
        extra_body={"reasoning_effort": "none"} is passed to suppress the <think> block
        that would otherwise cause a 400 tool_use_failed error. Applied only to qwen3
        models so the llama fallback is unaffected.
        <think> blocks are additionally stripped from raw_output as defence-in-depth.
        """
        request_id = str(uuid.uuid4())
        call_start_utc = datetime.now(timezone.utc).isoformat()
        call_start = time.time()
        set_request_id(request_id)

        kwargs = dict(
            model=model,
            messages=messages,
            tools=self._TOOL_DEFS,
            tool_choice="required",
            temperature=self._current_ctx.llm_temperature if self._current_ctx else 0.1,
            max_tokens=self._current_ctx.llm_max_tokens if self._current_ctx else 1024,
        )
        # For qwen3-class reasoning models on Groq: disable thinking via reasoning_effort.
        # Without this, qwen3 generates a <think> block before the tool call JSON, which
        # causes Groq's function-call parser to return tool_use_failed (failed_generation='').
        # reasoning_effort="none" is the correct Groq parameter (not Anthropic's
        # extra_body{"thinking"} which was reverted in #216 as it caused 400 for all models).
        # reasoning_format="hidden" is ALSO required: Groq docs state this must be set to
        # "parsed" or "hidden" when tool calling is enabled — the default "raw" is incompatible
        # with function calling and causes a 400 error even when reasoning_effort=none. (#228)
        # Applied only when disable_thinking=True AND model is qwen3, so the fallback
        # llama-3.3-70b-versatile is unaffected. Closes #223, #228.
        if self._disable_thinking and "qwen3" in model.lower():
            kwargs["extra_body"] = {"reasoning_effort": "none", "reasoning_format": "hidden"}
        response = self._client.chat.completions.create(**kwargs)
        latency_ms = int((time.time() - call_start) * 1000)

        choice = response.choices[0]
        msg = choice.message
        raw_output = msg.content or ""
        # Defence-in-depth: strip any <think>…</think> blocks that leaked into content
        raw_output = re.sub(r"<think>.*?</think>", "", raw_output, flags=re.DOTALL).strip()
        prompt_tokens = getattr(response.usage, "prompt_tokens", None)
        completion_tokens = getattr(response.usage, "completion_tokens", None)

        # Normalise OpenAI tool_calls to the same duck-typed interface as Ollama
        tool_calls = []
        serialisable_tool_calls = []
        for tc in (msg.tool_calls or []):
            args = tc.function.arguments
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except Exception:
                    args = {}

            class _Fn:
                pass

            fn = _Fn()
            fn.name = tc.function.name
            fn.arguments = args

            class _TC:
                pass

            wrapped = _TC()
            wrapped.function = fn
            tool_calls.append(wrapped)
            serialisable_tool_calls.append({"name": fn.name, "args": dict(args)})

        system_msg = next((m["content"] for m in messages if m["role"] == "system"), "")
        user_msg   = next((m["content"] for m in messages if m["role"] == "user"), "")
        log_llm_interaction(
            request_id=request_id,
            session_id=self._session_id,
            cycle_id=current_cycle_id.get(),
            model_id=model,
            system_prompt=system_msg,
            user_message=user_msg,
            raw_output=raw_output,
            tool_calls=serialisable_tool_calls,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            latency_ms=latency_ms,
            call_start_utc=call_start_utc,
        )

        return tool_calls, raw_output, prompt_tokens, completion_tokens

    # ──────────────────────────────────────────────
    # Helpers
    # ──────────────────────────────────────────────

    def _resolve_pair(self, llm_pair: str, signals: list) -> Optional[str]:
        """
        Return the canonical pair name from the signals list matching llm_pair.
        Case-insensitive. Returns None if not found (hallucinated pair).
        """
        llm_upper = llm_pair.upper().strip()
        for sig in signals:
            if sig["pair"].upper() == llm_upper:
                return sig["pair"]
        return None
