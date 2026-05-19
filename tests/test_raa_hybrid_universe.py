"""
Test Option 2 RAA Integration: Hybrid Universe (Core + RAA-Approved Pairs).

Tests the integration of research analyst agent (RAA) approved pairs
with core trading pairs from config.yaml.
"""

import sqlite3
import uuid
from datetime import datetime, timezone, timedelta

import pytest

from src.storage.database import (
    get_connection,
    get_trading_universe_hybrid,
    is_pair_approved_by_raa,
    init_paper_db,
)


@pytest.fixture
def temp_db():
    """Create a temporary test database."""
    db_path = f"test_raa_{uuid.uuid4().hex[:8]}.db"
    init_paper_db(db_path, starting_balance=1000.0)
    yield db_path
    # Cleanup
    import os
    if os.path.exists(db_path):
        os.remove(db_path)


@pytest.fixture
def test_config():
    """Test config with core trading pairs."""
    return {
        "trading": {
            "pairs": [
                {"pair": "BTC/USD", "take_profit_pct": 8},
                {"pair": "ETH/USD", "take_profit_pct": 12},
                {"pair": "BNB/USD", "take_profit_pct": 12},
            ]
        }
    }


class TestHybridUniverse:
    """Test core + RAA hybrid universe composition."""

    def test_core_pairs_only_no_raa(self, temp_db, test_config):
        """
        Given: No RAA-approved pairs in universe table
        When: get_trading_universe_hybrid() is called
        Then: Return core pairs from config only
        """
        pairs, composition = get_trading_universe_hybrid(test_config, temp_db)

        assert pairs == ["BTC/USD", "ETH/USD", "BNB/USD"]
        assert composition["core_count"] == 3
        assert composition["raa_count"] == 0
        assert composition["total"] == 3

    def test_core_plus_raa_active(self, temp_db, test_config):
        """
        Given: RAA has added active pairs to universe table
        When: get_trading_universe_hybrid() is called
        Then: Return core + RAA-approved pairs combined
        """
        # Add active RAA pair to universe
        conn = get_connection(temp_db)
        conn.execute(
            """
            INSERT INTO universe (pair, classification, added_at, added_by, status)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                "SOL/USD",
                "solana_ecosystem",
                datetime.now(timezone.utc).isoformat(),
                "RAA",
                "active",
            ),
        )
        conn.commit()
        conn.close()

        pairs, composition = get_trading_universe_hybrid(test_config, temp_db)

        assert "SOL/USD" in pairs
        assert pairs == ["BTC/USD", "ETH/USD", "BNB/USD", "SOL/USD"]
        assert composition["core_count"] == 3
        assert composition["raa_count"] == 1
        assert composition["total"] == 4

    def test_deduplication_core_and_raa(self, temp_db, test_config):
        """
        Given: Same pair exists in both core and RAA universe
        When: get_trading_universe_hybrid() is called
        Then: Return deduplicated list (no duplicates)
        """
        # Try to add BTC/USD (already in core) as RAA pair
        conn = get_connection(temp_db)
        conn.execute(
            """
            INSERT INTO universe (pair, classification, added_at, added_by, status)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                "BTC/USD",
                "macro_core",
                datetime.now(timezone.utc).isoformat(),
                "RAA",
                "active",
            ),
        )
        conn.commit()
        conn.close()

        pairs, composition = get_trading_universe_hybrid(test_config, temp_db)

        # BTC should appear only once
        assert pairs.count("BTC/USD") == 1
        assert len(pairs) == 3
        assert composition["total"] == 3

    def test_grace_period_blocks_proposed_pairs(self, temp_db, test_config):
        """
        Given: Proposed RAA pair within grace period (1 hour)
        When: get_trading_universe_hybrid() is called
        Then: Exclude the pair (grace period not yet expired)
        """
        # Add proposed pair with grace period that hasn't expired
        now = datetime.now(timezone.utc)
        recent_time = (now - timedelta(minutes=30)).isoformat()  # 30 min ago

        conn = get_connection(temp_db)
        conn.execute(
            """
            INSERT INTO universe (pair, classification, added_at, added_by, status, grace_period_hours)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                "XRP/USD",
                "xrpl_ecosystem",
                recent_time,
                "RAA",
                "proposed",
                1,  # 1 hour grace period
            ),
        )
        conn.commit()
        conn.close()

        pairs, composition = get_trading_universe_hybrid(test_config, temp_db)

        # XRP should be excluded (grace period not expired)
        assert "XRP/USD" not in pairs
        assert composition["raa_count"] == 0

    def test_grace_period_includes_expired_proposed_pairs(self, temp_db, test_config):
        """
        Given: Proposed RAA pair past grace period (1+ hour old)
        When: get_trading_universe_hybrid() is called
        Then: Include the pair (grace period expired)
        """
        # Add proposed pair with grace period that HAS expired
        now = datetime.now(timezone.utc)
        old_time = (now - timedelta(hours=2)).isoformat()  # 2 hours ago

        conn = get_connection(temp_db)
        conn.execute(
            """
            INSERT INTO universe (pair, classification, added_at, added_by, status, grace_period_hours)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                "ADA/USD",
                "cardano_ecosystem",
                old_time,
                "RAA",
                "proposed",
                1,  # 1 hour grace period (expired)
            ),
        )
        conn.commit()
        conn.close()

        pairs, composition = get_trading_universe_hybrid(test_config, temp_db)

        # ADA should be included (grace period expired)
        assert "ADA/USD" in pairs
        assert composition["raa_count"] == 1


class TestPairApprovalCheck:
    """Test is_pair_approved_by_raa() gatekeeper function."""

    def test_active_pair_is_approved(self, temp_db):
        """
        Given: Pair with status='active' in universe table
        When: is_pair_approved_by_raa() is called
        Then: Return True (always approved)
        """
        conn = get_connection(temp_db)
        conn.execute(
            """
            INSERT INTO universe (pair, classification, added_at, added_by, status)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                "BTC/USD",
                "macro_core",
                datetime.now(timezone.utc).isoformat(),
                "RAA",
                "active",
            ),
        )
        conn.commit()
        conn.close()

        assert is_pair_approved_by_raa("BTC/USD", temp_db) is True

    def test_proposed_pair_within_grace_period_not_approved(self, temp_db):
        """
        Given: Pair with status='proposed' within grace period
        When: is_pair_approved_by_raa() is called
        Then: Return False (grace period not expired)
        """
        now = datetime.now(timezone.utc)
        recent = (now - timedelta(minutes=20)).isoformat()

        conn = get_connection(temp_db)
        conn.execute(
            """
            INSERT INTO universe (pair, classification, added_at, added_by, status, grace_period_hours)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                "SOL/USD",
                "solana_ecosystem",
                recent,
                "RAA",
                "proposed",
                1,
            ),
        )
        conn.commit()
        conn.close()

        assert is_pair_approved_by_raa("SOL/USD", temp_db) is False

    def test_proposed_pair_past_grace_period_approved(self, temp_db):
        """
        Given: Pair with status='proposed' past grace period
        When: is_pair_approved_by_raa() is called
        Then: Return True (grace period expired)
        """
        now = datetime.now(timezone.utc)
        old = (now - timedelta(hours=2)).isoformat()

        conn = get_connection(temp_db)
        conn.execute(
            """
            INSERT INTO universe (pair, classification, added_at, added_by, status, grace_period_hours)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                "ETH/USD",
                "ethereum_ecosystem",
                old,
                "RAA",
                "proposed",
                1,
            ),
        )
        conn.commit()
        conn.close()

        assert is_pair_approved_by_raa("ETH/USD", temp_db) is True

    def test_unknown_pair_not_approved(self, temp_db):
        """
        Given: Pair not in universe table
        When: is_pair_approved_by_raa() is called
        Then: Return False (not RAA-approved)
        """
        assert is_pair_approved_by_raa("UNKNOWN/USD", temp_db) is False

    def test_deprecated_pair_not_approved(self, temp_db):
        """
        Given: Pair with status='deprecated' (removed from universe)
        When: is_pair_approved_by_raa() is called
        Then: Return False (no longer active)
        """
        conn = get_connection(temp_db)
        conn.execute(
            """
            INSERT INTO universe (pair, classification, added_at, added_by, status)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                "RAILS/USD",
                "defi_ecosystem",
                datetime.now(timezone.utc).isoformat(),
                "RAA",
                "deprecated",
            ),
        )
        conn.commit()
        conn.close()

        assert is_pair_approved_by_raa("RAILS/USD", temp_db) is False


class TestCoreAndRAAPriority:
    """Test that core pairs always take priority over RAA pairs."""

    def test_core_pairs_come_first(self, temp_db, test_config):
        """
        Given: Core pairs [BTC, ETH, BNB] and RAA pairs [SOL, XRP]
        When: get_trading_universe_hybrid() merges them
        Then: Core pairs appear first in returned list
        """
        # Add two RAA pairs
        conn = get_connection(temp_db)
        now = datetime.now(timezone.utc).isoformat()

        conn.execute(
            """
            INSERT INTO universe (pair, classification, added_at, added_by, status)
            VALUES (?, ?, ?, ?, ?)
            """,
            ("SOL/USD", "solana_ecosystem", now, "RAA", "active"),
        )
        conn.execute(
            """
            INSERT INTO universe (pair, classification, added_at, added_by, status)
            VALUES (?, ?, ?, ?, ?)
            """,
            ("XRP/USD", "xrpl_ecosystem", now, "RAA", "active"),
        )
        conn.commit()
        conn.close()

        pairs, _ = get_trading_universe_hybrid(test_config, temp_db)

        # Core pairs should come before RAA pairs
        core_indices = [pairs.index(p) for p in ["BTC/USD", "ETH/USD", "BNB/USD"]]
        raa_indices = [pairs.index(p) for p in ["SOL/USD", "XRP/USD"]]

        assert max(core_indices) < min(raa_indices)


class TestMultipleGracePeriods:
    """Test multiple proposed pairs with different grace periods."""

    def test_mixed_active_and_proposed(self, temp_db, test_config):
        """
        Given: Mix of active and proposed RAA pairs with different grace periods
        When: get_trading_universe_hybrid() is called
        Then: Include active + expired-grace-period pairs only
        """
        now = datetime.now(timezone.utc)
        conn = get_connection(temp_db)

        # Active pair (should be included)
        conn.execute(
            """
            INSERT INTO universe (pair, classification, added_at, added_by, status)
            VALUES (?, ?, ?, ?, ?)
            """,
            ("SOL/USD", "solana", now.isoformat(), "RAA", "active"),
        )

        # Proposed, expired grace period (should be included)
        old = (now - timedelta(hours=2)).isoformat()
        conn.execute(
            """
            INSERT INTO universe (pair, classification, added_at, added_by, status, grace_period_hours)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("ADA/USD", "cardano", old, "RAA", "proposed", 1),
        )

        # Proposed, active grace period (should be excluded)
        recent = (now - timedelta(minutes=15)).isoformat()
        conn.execute(
            """
            INSERT INTO universe (pair, classification, added_at, added_by, status, grace_period_hours)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("DOT/USD", "polkadot", recent, "RAA", "proposed", 1),
        )

        conn.commit()
        conn.close()

        pairs, composition = get_trading_universe_hybrid(test_config, temp_db)

        assert "SOL/USD" in pairs  # active
        assert "ADA/USD" in pairs  # proposed, grace expired
        assert "DOT/USD" not in pairs  # proposed, grace active
        assert composition["raa_count"] == 2
        assert composition["total"] == 5
