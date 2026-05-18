"""
Tests for S16.1.1 — Orchestrator playbook selection.

Verifies:
  1. kill_switch=True → risk_off
  2. daily_pnl_pct ≤ -3 → risk_off
  3. ADX ≥ 25 AND trending_up → momentum
  4. ADX < 25 AND trending_up → ranging
  5. ADX ≥ 25 but regime != trending_up → ranging
  6. Playbook transition fires notifier.send_playbook_changed
"""

import sys
import os
import uuid
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.agent.orchestrator import Orchestrator
from src.storage.database import init_paper_db

DB_PATH = f"test_paper_{uuid.uuid4().hex[:8]}.db"

BASE_CONFIG = {
    "orchestrator": {
        "risk_off_daily_pnl_pct": -3.0,
        "momentum_adx_min": 25.0,
    }
}


def _make_orch(notifier=None):
    init_paper_db(DB_PATH)
    return Orchestrator(BASE_CONFIG, DB_PATH, notifier=notifier)


def test_kill_switch_returns_risk_off():
    orch = _make_orch()
    playbook = orch.select_playbook("trending_up", 30.0, 0.0, kill_switch=True)
    assert playbook == "risk_off"


def test_large_daily_loss_returns_risk_off():
    orch = _make_orch()
    playbook = orch.select_playbook("trending_up", 30.0, -4.0, kill_switch=False)
    assert playbook == "risk_off"


def test_exact_threshold_returns_risk_off():
    """daily_pnl_pct == -3.0 (exactly at boundary) → risk_off."""
    orch = _make_orch()
    playbook = orch.select_playbook("trending_up", 30.0, -3.0)
    assert playbook == "risk_off"


def test_high_adx_trending_up_returns_momentum():
    orch = _make_orch()
    playbook = orch.select_playbook("trending_up", 30.0, 0.0)
    assert playbook == "momentum"


def test_low_adx_returns_ranging():
    """ADX below momentum threshold → ranging even when trending_up."""
    orch = _make_orch()
    playbook = orch.select_playbook("trending_up", 20.0, 0.0)
    assert playbook == "ranging"


def test_non_trending_regime_returns_ranging():
    """ADX ≥ 25 but regime is bearish → ranging."""
    orch = _make_orch()
    playbook = orch.select_playbook("bearish", 30.0, 0.0)
    assert playbook == "ranging"


def test_playbook_change_fires_notifier():
    """Transitioning playbook calls send_playbook_changed exactly once."""
    notifier = MagicMock()
    orch = _make_orch(notifier=notifier)
    # First selection sets playbook (no "old" → no alert)
    orch.select_playbook("trending_up", 30.0, 0.0)  # momentum
    # Second selection changes playbook → alert fired
    orch.select_playbook("ranging", 20.0, 0.0)       # ranging
    notifier.send_playbook_changed.assert_called_once_with("momentum", "ranging")
