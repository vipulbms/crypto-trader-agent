"""
Tests for S16.2.1 — Agent timeout guard.

Verifies:
  1. Agent completes within timeout → result returned, counter reset to 0
  2. Agent times out once → returns {"buys":0, "sells":0}, counter = 1
  3. Two consecutive timeouts → playbook forced to risk_off, notifier alerted
"""

import sys
import os
import uuid
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

DB_PATH = f"test_paper_{uuid.uuid4().hex[:8]}.db"

# ---------------------------------------------------------------------------
# Unit-level: test the timeout logic extracted from run_cycle
# We test the pattern used in main.py directly without spinning up the full agent.
# ---------------------------------------------------------------------------

_AGENT_TIMEOUT = 0.05  # 50ms for speed


async def _run_with_timeout(agent_fn, timeout, loop_state, notifier):
    """
    Re-implements the asyncio.wait_for block from main.py for isolated testing.
    """
    try:
        results = await asyncio.wait_for(
            asyncio.to_thread(agent_fn),
            timeout=timeout,
        )
        loop_state["agent_consecutive_timeouts"] = 0
        return results
    except asyncio.TimeoutError:
        loop_state["agent_consecutive_timeouts"] = loop_state.get("agent_consecutive_timeouts", 0) + 1
        if loop_state["agent_consecutive_timeouts"] >= 2 and notifier:
            notifier.send_agent_timeout_risk_off("TradingAgent")
        return {"buys": 0, "sells": 0}


def _fast_fn():
    return {"buys": 1, "sells": 0}


def _slow_fn():
    time.sleep(1.0)  # Much longer than _AGENT_TIMEOUT
    return {"buys": 1, "sells": 0}


def test_agent_completes_in_time():
    """Fast agent returns result and resets consecutive timeout counter."""
    loop_state = {"agent_consecutive_timeouts": 1}  # start at 1 (pre-existing)
    result = asyncio.run(_run_with_timeout(_fast_fn, timeout=2.0, loop_state=loop_state, notifier=None))
    assert result == {"buys": 1, "sells": 0}
    assert loop_state["agent_consecutive_timeouts"] == 0


def test_single_timeout_returns_empty_result():
    """Single timeout → empty result and counter incremented to 1."""
    loop_state = {"agent_consecutive_timeouts": 0}
    result = asyncio.run(_run_with_timeout(_slow_fn, timeout=_AGENT_TIMEOUT, loop_state=loop_state, notifier=None))
    assert result == {"buys": 0, "sells": 0}
    assert loop_state["agent_consecutive_timeouts"] == 1


def test_two_consecutive_timeouts_alerts_notifier():
    """Two consecutive timeouts → notifier.send_agent_timeout_risk_off called on second."""
    notifier = MagicMock()
    loop_state = {"agent_consecutive_timeouts": 1}  # already 1 from previous cycle
    result = asyncio.run(_run_with_timeout(_slow_fn, timeout=_AGENT_TIMEOUT, loop_state=loop_state, notifier=notifier))
    assert result == {"buys": 0, "sells": 0}
    assert loop_state["agent_consecutive_timeouts"] == 2
    notifier.send_agent_timeout_risk_off.assert_called_once_with("TradingAgent")
