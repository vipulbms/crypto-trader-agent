"""
Tests for #177/#223 — qwen3 thinking-mode safeguards in TradingAgent._call_openai_compat().

1. <think> blocks stripped from raw_output (defence-in-depth, all models)
2. disable_thinking=True + qwen3 model passes extra_body={"reasoning_effort": "none"} (#223)
3. disable_thinking=True + non-qwen3 model does NOT pass extra_body (llama fallback unaffected)
4. disable_thinking=False sends no extra_body
5. Tool calls dispatched correctly even when content contains a <think> prefix
"""
import json
import sys
import os
import re
import types
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# ── stub heavy optional dependencies ────────────────────────────────────────
for _mod in ("ollama", "httpx"):
    if _mod not in sys.modules:
        sys.modules[_mod] = types.ModuleType(_mod)

# Stub src.utils.timing
timing_mod = types.ModuleType("src.utils.timing")
timing_mod.timed = lambda *a, **kw: (lambda fn: fn)
timing_mod.set_cycle_id = lambda *a: None
timing_mod.set_request_id = lambda *a: None
timing_mod.current_cycle_id = MagicMock(get=lambda: 0)
sys.modules.setdefault("src.utils.timing", timing_mod)

# Stub src.utils.llm_logger (avoids file I/O in tests)
llm_logger_mod = types.ModuleType("src.utils.llm_logger")
llm_logger_mod.log_llm_interaction = lambda **kw: None
sys.modules.setdefault("src.utils.llm_logger", llm_logger_mod)

# Stub src.utils.tz (only if not already imported — avoids polluting sys.modules for other tests)
if "src.utils.tz" not in sys.modules:
    tz_mod = types.ModuleType("src.utils.tz")
    from datetime import datetime, timezone, timedelta
    tz_mod.now_sgt = lambda: datetime.utcnow()
    tz_mod.SGT = timezone(timedelta(hours=8), name="SGT")
    tz_mod.now_sgt_iso = lambda: datetime.utcnow().isoformat()
    sys.modules["src.utils.tz"] = tz_mod

# Stub src.agent.prompts (avoids heavy LLM-prompt imports)
prompts_mod = types.ModuleType("src.agent.prompts")
prompts_mod.SYSTEM_PROMPT = "system"
prompts_mod.build_cycle_prompt = lambda **kw: "prompt"
sys.modules.setdefault("src.agent.prompts", prompts_mod)

# Stub openai (avoid network dependency at import time)
openai_mod = types.ModuleType("openai")
openai_mod.OpenAI = MagicMock()
sys.modules.setdefault("openai", openai_mod)


def _make_tools_stub():
    """Create a minimal stub that satisfies TradingAgent's tools interface."""
    stub = MagicMock()
    stub.set_cycle_context = MagicMock()
    stub.set_dynamic_tp_values = MagicMock()
    stub.set_llm_decision_id = MagicMock()
    stub.propose_buy = MagicMock(return_value="buy")
    stub.propose_sell = MagicMock(return_value="sell")
    stub.hold = MagicMock(return_value="hold")
    return stub


def _make_agent(disable_thinking: bool = False, provider: str = "openai_compat"):
    """Create a minimal TradingAgent with a mocked OpenAI client."""
    from src.agent.trading_agent import TradingAgent

    config = {
        "llm": {
            "provider": provider,
            "model": "qwen/qwen3-32b",
            "fallback_model": "llama-3.3-70b-versatile",
            "base_url": "https://api.groq.com/openai/v1/",
            "api_key_env": "GROQ_API_KEY",
            "timeout_seconds": 30,
            "max_reasoning_chars": 500,
            "request_delay_seconds": 0,
            "disable_thinking": disable_thinking,
        },
        "trading": {"max_buys_per_cycle": 2, "take_profit_pct": 10, "pairs": []},
        "risk": {"min_order_usd": 20.0},
    }
    audit = MagicMock()
    agent = TradingAgent(
        tools=_make_tools_stub(),
        config=config,
        mode="paper",
        audit_logger=audit,
    )
    # Replace client with a fresh mock after construction
    agent._client = MagicMock()
    return agent


def _build_mock_response(content: str, tool_calls=None):
    """Build a minimal object that mimics openai.types.chat.ChatCompletion."""
    mock_response = MagicMock()
    mock_choice = MagicMock()
    mock_msg = MagicMock()
    mock_msg.content = content
    mock_msg.tool_calls = tool_calls or []
    mock_choice.message = mock_msg
    mock_response.choices = [mock_choice]
    mock_response.usage.prompt_tokens = 100
    mock_response.usage.completion_tokens = 50
    return mock_response


def _build_tool_call(name: str, args: dict):
    """Build a mock tool_call like openai returns."""
    tc = MagicMock()
    tc.function.name = name
    tc.function.arguments = json.dumps(args)
    return tc


# ──────────────────────────────────────────────────────────────────────────────


class TestThinkBlockStripping:
    """Option B: <think> blocks stripped from raw_output."""

    def test_think_block_stripped_from_content(self):
        """
        Given raw content = '<think>internal reasoning</think>\\nDone'
        When _call_openai_compat processes the response
        Then raw_output should be 'Done' (think block removed)
        """
        agent = _make_agent()
        mock_resp = _build_mock_response(
            content="<think>internal chain-of-thought here</think>\nDone"
        )
        agent._client.chat.completions.create.return_value = mock_resp

        _, raw_output, _, _ = agent._call_openai_compat("qwen/qwen3-32b", [])

        assert "<think>" not in raw_output
        assert "internal chain-of-thought here" not in raw_output
        assert raw_output == "Done"

    def test_multiline_think_block_stripped(self):
        """<think> blocks spanning multiple lines are fully removed."""
        agent = _make_agent()
        content = "<think>\nline 1\nline 2\nline 3\n</think>\nActual output"
        mock_resp = _build_mock_response(content=content)
        agent._client.chat.completions.create.return_value = mock_resp

        _, raw_output, _, _ = agent._call_openai_compat("qwen/qwen3-32b", [])

        assert raw_output == "Actual output"

    def test_no_think_block_content_unchanged(self):
        """Content without <think> blocks is returned as-is."""
        agent = _make_agent()
        mock_resp = _build_mock_response(content="Clean response with no thinking")
        agent._client.chat.completions.create.return_value = mock_resp

        _, raw_output, _, _ = agent._call_openai_compat("qwen/qwen3-32b", [])

        assert raw_output == "Clean response with no thinking"

    def test_think_block_stripped_tool_calls_still_dispatched(self):
        """
        Given content with <think> prefix AND valid tool_calls
        When _call_openai_compat processes the response
        Then tool_calls are returned intact and <think> block is stripped
        """
        agent = _make_agent()
        tc = _build_tool_call("propose_buy", {"pair": "ETH/USD", "usd_amount": 50.0})
        mock_resp = _build_mock_response(
            content="<think>I should buy ETH</think>",
            tool_calls=[tc],
        )
        agent._client.chat.completions.create.return_value = mock_resp

        tool_calls, raw_output, _, _ = agent._call_openai_compat("qwen/qwen3-32b", [])

        assert len(tool_calls) == 1
        assert tool_calls[0].function.name == "propose_buy"
        assert tool_calls[0].function.arguments["pair"] == "ETH/USD"
        assert "<think>" not in raw_output


class TestDisableThinking:
    """reasoning_effort='none' + reasoning_format='hidden' disables qwen3 thinking on Groq. #223 #228"""

    def test_disable_thinking_true_qwen3_passes_reasoning_effort(self):
        """
        Given disable_thinking=True and model is qwen/qwen3-32b
        When _call_openai_compat is called
        Then extra_body with reasoning_effort=none AND reasoning_format=hidden is passed (#223 #228).
        reasoning_format=hidden is required because Groq requires parsed or hidden when tool
        calling is enabled — the default raw causes 400 tool_use_failed (#228).
        """
        agent = _make_agent(disable_thinking=True)
        mock_resp = _build_mock_response(content="response")
        agent._client.chat.completions.create.return_value = mock_resp

        agent._call_openai_compat("qwen/qwen3-32b", [])

        call_kwargs = agent._client.chat.completions.create.call_args[1]
        assert "extra_body" in call_kwargs, "extra_body must be sent for qwen3 with disable_thinking=True"
        assert call_kwargs["extra_body"] == {"reasoning_effort": "none", "reasoning_format": "hidden"}

    def test_disable_thinking_true_llama_no_extra_body(self):
        """
        Given disable_thinking=True but model is llama-3.3-70b-versatile (fallback)
        When _call_openai_compat is called
        Then extra_body is NOT passed — reasoning_effort is qwen3-specific
        """
        agent = _make_agent(disable_thinking=True)
        mock_resp = _build_mock_response(content="response")
        agent._client.chat.completions.create.return_value = mock_resp

        agent._call_openai_compat("llama-3.3-70b-versatile", [])

        call_kwargs = agent._client.chat.completions.create.call_args[1]
        assert "extra_body" not in call_kwargs, "extra_body must NOT be sent for llama fallback"

    def test_disable_thinking_false_no_extra_body(self):
        """
        Given disable_thinking=False (default)
        When _call_openai_compat is called
        Then no extra_body key is passed to the API
        """
        agent = _make_agent(disable_thinking=False)
        mock_resp = _build_mock_response(content="response")
        agent._client.chat.completions.create.return_value = mock_resp

        agent._call_openai_compat("qwen/qwen3-32b", [])

        call_kwargs = agent._client.chat.completions.create.call_args[1]
        assert "extra_body" not in call_kwargs, "extra_body should NOT be present when disable_thinking=False"

    def test_disable_thinking_default_is_false(self):
        """
        Given no disable_thinking in config
        When TradingAgent is constructed
        Then _disable_thinking is False
        """
        from src.agent.trading_agent import TradingAgent

        config = {
            "llm": {
                "provider": "openai_compat",
                "model": "test-model",
                "fallback_model": "test-model",
                "base_url": "http://localhost",
                "api_key_env": "TEST_KEY",
                "timeout_seconds": 10,
                # no disable_thinking key
            },
            "trading": {"max_buys_per_cycle": 2, "take_profit_pct": 10, "pairs": []},
            "risk": {"min_order_usd": 20.0},
        }
        agent = TradingAgent(tools=_make_tools_stub(), config=config, mode="paper",
                             audit_logger=MagicMock())
        assert agent._disable_thinking is False
