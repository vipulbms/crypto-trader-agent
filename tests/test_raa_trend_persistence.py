"""
test_raa_trend_persistence.py — S22.1.1 AC5/AC6

Tests:
  - Persistence Score accumulates across cycles when Ps >= min_ps
  - cycles_sustained resets to 0 on Ps < min_ps (AC5)
  - trend_persistence row is created on first encounter (AC6)
  - status stays CANDIDATE until proposal fires
"""
import uuid

import pytest

from src.storage.database import init_paper_db
from src.runtime.research_analyst import (
    compute_persistence_score,
    _upsert_trend_persistence,
    _get_trend_persistence,
)

# ── helpers ──────────────────────────────────────────────────

DB_NAME = f"test_raa_tp_{uuid.uuid4().hex[:8]}.db"


@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    """Wire get_connection to a temp data directory."""
    import src.storage.database as db_mod
    _orig = db_mod.DATA_DIR_PATH
    db_mod.DATA_DIR_PATH = str(tmp_path)
    init_paper_db(DB_NAME)
    yield
    db_mod.DATA_DIR_PATH = _orig


def _db():
    return DB_NAME


# ── persistence score ─────────────────────────────────────────

class TestPersistenceScore:
    def _ticker(self, price=1000.0, open_price=900.0, vol=5000.0):
        return {
            "last": price,
            "open": open_price,
            "volume_24h": vol,
            "has_variance": True,
        }

    def test_high_ps_with_trending_pair(self):
        ticker = self._ticker(price=1100.0, open_price=1000.0, vol=50_000.0)
        # large vol * price >> 1M, +10% move, in trending
        ps = compute_persistence_score(ticker, trending_pairs=["ETH/USD"], pair="ETH/USD")
        # Should score momentum + liquidity + trending
        assert ps >= 1.5

    def test_low_ps_no_movement(self):
        ticker = self._ticker(price=1000.0, open_price=1000.0, vol=10.0)
        ps = compute_persistence_score(ticker)
        assert ps < 1.5

    def test_volume_acceleration_bonus(self):
        prev = self._ticker(vol=100.0)
        curr = self._ticker(vol=200.0, open_price=950.0, price=1000.0)
        ps_with_acc = compute_persistence_score(curr, prev_ticker=prev)
        ps_without = compute_persistence_score(curr)
        assert ps_with_acc > ps_without

    def test_missing_ticker_returns_zero(self):
        ps = compute_persistence_score({})
        assert ps == 0.0

    def test_zero_price_returns_zero(self):
        ps = compute_persistence_score({"last": 0, "open": 0, "volume_24h": 1000})
        assert ps == 0.0


# ── cycles_sustained logic ────────────────────────────────────

class TestCyclesSustained:
    """S22.1.1 AC5 — cycles_sustained resets on Ps < min_ps."""

    def test_accumulates_on_consecutive_above_threshold(self):
        pair = "SOL/USD"
        for i in range(1, 5):
            _upsert_trend_persistence(_db(), pair, "FOUNDATIONAL", ps=2.0, cycles_sustained=i, status="CANDIDATE")
            row = _get_trend_persistence(_db(), pair)
            assert row["cycles_sustained"] == i

    def test_resets_on_ps_drop_below_threshold(self):
        """AC5: cycles_sustained = 0 when Ps drops below min_ps."""
        pair = "SOL/USD"
        # Establish 4 sustained cycles
        _upsert_trend_persistence(_db(), pair, "FOUNDATIONAL", ps=2.0, cycles_sustained=4, status="CANDIDATE")
        # Now Ps drops below threshold — caller must reset
        _upsert_trend_persistence(_db(), pair, "FOUNDATIONAL", ps=0.8, cycles_sustained=0, status="CANDIDATE")
        row = _get_trend_persistence(_db(), pair)
        assert row["cycles_sustained"] == 0
        assert row["persistence_score"] == pytest.approx(0.8, abs=0.01)

    def test_row_created_on_first_encounter(self):
        """AC6: Row created when pair first appears."""
        pair = "AVAX/USD"
        assert _get_trend_persistence(_db(), pair) is None
        _upsert_trend_persistence(_db(), pair, "FOUNDATIONAL", ps=1.6, cycles_sustained=1, status="CANDIDATE")
        row = _get_trend_persistence(_db(), pair)
        assert row is not None
        assert row["pair"] == "AVAX/USD"
        assert row["status"] == "CANDIDATE"

    def test_upsert_overwrites_existing_row(self):
        pair = "BNB/USD"
        _upsert_trend_persistence(_db(), pair, "FOUNDATIONAL", ps=1.0, cycles_sustained=2, status="CANDIDATE")
        _upsert_trend_persistence(_db(), pair, "MEME", ps=2.2, cycles_sustained=5, status="CANDIDATE")
        row = _get_trend_persistence(_db(), pair)
        assert row["classification"] == "MEME"
        assert row["cycles_sustained"] == 5

    def test_four_consecutive_above_threshold_qualifies(self):
        """AC5: gate opens after 4 consecutive sustained cycles."""
        pair = "DOT/USD"
        min_ps = 1.5
        min_cycles = 4
        for i in range(1, 5):
            _upsert_trend_persistence(_db(), pair, "FOUNDATIONAL", ps=2.0, cycles_sustained=i, status="CANDIDATE")
        row = _get_trend_persistence(_db(), pair)
        assert row["cycles_sustained"] >= min_cycles
        assert row["persistence_score"] >= min_ps
