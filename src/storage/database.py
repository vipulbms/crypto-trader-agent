"""
Database initialisation for paper_trading.db, live_trading.db, and audit.db.
Call init_all_databases() once at startup to ensure all tables exist.
"""

import sqlite3
import os
import logging
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)

# Module-level data directory path — tests may monkeypatch this to a tmp_path.
DATA_DIR_PATH: str = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data",
)


def _get_db_path(db_filename: str) -> str:
    """Return absolute path to a DB file in DATA_DIR_PATH (overrideable by tests)."""
    import src.storage.database as _self
    data_dir = _self.DATA_DIR_PATH
    os.makedirs(data_dir, exist_ok=True)
    return os.path.join(data_dir, db_filename)


def get_db_path(db_filename: str) -> str:
    """Public alias for _get_db_path. Returns absolute path to a DB file in data/."""
    return _get_db_path(db_filename)


def resolve_trading_db(config: dict, mode: str) -> str:
    """
    Return the bare trading DB filename for the current mode and persona.

    When ``agent.concurrent_mode`` is True, the active persona name is embedded
    in the filename so each persona operates on its own isolated database::

        paper_trading_conservative.db
        paper_trading_medium.db
        paper_trading_high.db

    When ``concurrent_mode`` is False (default for S1), the canonical name is
    used unchanged::

        paper_trading.db  /  live_trading.db

    Story: S12.1.3 — Persona persistence (concurrent_mode DB naming)
    """
    storage_cfg = config.get("storage", {})
    agent_cfg   = config.get("agent", {})
    concurrent  = bool(agent_cfg.get("concurrent_mode", False))

    base_name = (
        storage_cfg.get("paper_db", "paper_trading.db")
        if mode == "paper"
        else storage_cfg.get("live_db", "live_trading.db")
    )

    if not concurrent:
        return base_name

    persona = agent_cfg.get("persona", "conservative")
    stem, ext = os.path.splitext(base_name)
    return f"{stem}_{persona}{ext}"


def get_connection(db_filename: str) -> sqlite3.Connection:
    """Open and return a SQLite connection with foreign keys enabled."""
    path = _get_db_path(db_filename)
    try:
        conn = sqlite3.connect(path, check_same_thread=False, timeout=10)
        conn.execute("PRAGMA foreign_keys = ON")
        conn.row_factory = sqlite3.Row
        return conn
    except sqlite3.OperationalError as e:
        if "locked" in str(e).lower():
            logger.error("Database timeout — %s is locked after 10s: %s", db_filename, e)
        else:
            logger.error("Database connection error for %s: %s", db_filename, e)
        raise


def get_connection_ro(db_filename: str) -> sqlite3.Connection:
    """Open a SQLite connection in read-only mode (S17.1.1 AC4).

    Uses URI mode with ``?mode=ro`` so writes are rejected at the SQLite layer.
    Falls back to a regular connection if the DB file does not exist yet
    (returns empty results rather than erroring).
    """
    path = _get_db_path(db_filename)
    try:
        import urllib.parse
        uri = "file:" + urllib.parse.quote(str(path)) + "?mode=ro"
        conn = sqlite3.connect(uri, uri=True, check_same_thread=False, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn
    except sqlite3.OperationalError as e:
        if "unable to open database" in str(e).lower():
            # DB doesn't exist yet — return an in-memory stub that returns empty results
            conn = sqlite3.connect(":memory:", check_same_thread=False)
            conn.row_factory = sqlite3.Row
            return conn
        logger.error("Read-only DB connection error for %s: %s", db_filename, e)
        raise


# ──────────────────────────────────────────────────────────────
# DataCollector DB schema — shared by paper and live modes (S21.1.1)
# ──────────────────────────────────────────────────────────────

COLLECTOR_SCHEMA = """
CREATE TABLE IF NOT EXISTS candle_buffer (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    pair        TEXT NOT NULL,
    ts          INTEGER NOT NULL,   -- UNIX epoch seconds (candle open time)
    open_price  REAL NOT NULL,
    high        REAL NOT NULL,
    low         REAL NOT NULL,
    close       REAL NOT NULL,
    volume      REAL NOT NULL,
    is_closed   INTEGER NOT NULL DEFAULT 1,  -- 1 = completed candle
    inserted_at TEXT NOT NULL       -- ISO-8601 UTC timestamp
);
CREATE UNIQUE INDEX IF NOT EXISTS uix_candle_buffer_pair_ts ON candle_buffer(pair, ts);

CREATE TABLE IF NOT EXISTS orderbook_snapshots (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    pair        TEXT NOT NULL,
    ts          INTEGER NOT NULL,
    best_bid    REAL NOT NULL,
    best_ask    REAL NOT NULL,
    obi         REAL NOT NULL,      -- Order Book Imbalance: (bid-ask)/(bid+ask)
    inserted_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_ob_pair_ts ON orderbook_snapshots(pair, ts);
"""

# ──────────────────────────────────────────────────────────────
# Paper trading DB schema
# ──────────────────────────────────────────────────────────────

FULFILLMENT_AUDIT_SCHEMA = """
CREATE TABLE IF NOT EXISTS fulfillment_audit (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    fulfillment_id    TEXT NOT NULL UNIQUE,
    pair              TEXT NOT NULL,
    side              TEXT NOT NULL,
    requested_at      TEXT NOT NULL,
    filled_at         TEXT,
    duration_ms       INTEGER NOT NULL,
    execution_status  TEXT NOT NULL,
    request_json      TEXT NOT NULL,
    response_json     TEXT,
    kraken_order_id   TEXT,
    error_message     TEXT
);
"""

PAPER_SCHEMA = """
CREATE TABLE IF NOT EXISTS paper_wallet (
    id                  INTEGER PRIMARY KEY,
    updated_at          TEXT NOT NULL,
    cash_usd            REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS paper_positions (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    opened_at           TEXT NOT NULL,
    pair                TEXT NOT NULL,
    side                TEXT NOT NULL DEFAULT 'buy',
    entry_price         REAL NOT NULL,
    volume              REAL NOT NULL,
    usd_value           REAL NOT NULL,
    stop_loss_price     REAL NOT NULL,
    take_profit_price   REAL NOT NULL,
    stop_loss_pct       REAL NOT NULL,
    take_profit_pct     REAL NOT NULL,
    status              TEXT NOT NULL DEFAULT 'open',
    highest_price_seen  REAL,          -- S12.2.1: tracks peak price for trailing stop
    partial_exited      INTEGER DEFAULT 0  -- S12.5.1: 1 after first partial TP close
);

CREATE TABLE IF NOT EXISTS paper_trades (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    opened_at           TEXT NOT NULL,
    closed_at           TEXT NOT NULL,
    pair                TEXT NOT NULL,
    side                TEXT NOT NULL,
    entry_price         REAL NOT NULL,
    exit_price          REAL NOT NULL,
    volume              REAL NOT NULL,
    usd_invested        REAL NOT NULL,
    pnl_usd             REAL NOT NULL,
    pnl_pct             REAL NOT NULL,
    exit_reason         TEXT NOT NULL,
    hold_duration_secs  INTEGER NOT NULL,
    fee_usd             REAL NOT NULL DEFAULT 0.0,
    stop_loss_pct       REAL NOT NULL,
    take_profit_pct     REAL NOT NULL,
    persona             TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS agent_state (
    key     TEXT PRIMARY KEY,
    value   TEXT NOT NULL
);
"""

# ──────────────────────────────────────────────────────────────
# Live trading DB schema
# ──────────────────────────────────────────────────────────────

LIVE_SCHEMA = """
CREATE TABLE IF NOT EXISTS live_positions (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    opened_at               TEXT NOT NULL,
    pair                    TEXT NOT NULL,
    side                    TEXT NOT NULL DEFAULT 'buy',
    entry_price             REAL NOT NULL,
    volume                  REAL NOT NULL,
    usd_value               REAL NOT NULL,
    stop_loss_price         REAL NOT NULL,
    take_profit_price       REAL NOT NULL,
    stop_loss_pct           REAL NOT NULL,
    take_profit_pct         REAL NOT NULL,
    highest_price_seen      REAL,          -- S12.2.1: tracks peak price for trailing stop
    partial_exited          INTEGER DEFAULT 0,  -- S12.5.1: 1 after first partial TP close
    entry_order_id          TEXT,
    stop_loss_order_id      TEXT,
    take_profit_order_id    TEXT,
    status                  TEXT NOT NULL DEFAULT 'open'
);

CREATE TABLE IF NOT EXISTS live_trades (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    opened_at               TEXT NOT NULL,
    closed_at               TEXT NOT NULL,
    pair                    TEXT NOT NULL,
    side                    TEXT NOT NULL,
    entry_price             REAL NOT NULL,
    exit_price              REAL NOT NULL,
    volume                  REAL NOT NULL,
    usd_invested            REAL NOT NULL,
    pnl_usd                 REAL NOT NULL,
    pnl_pct                 REAL NOT NULL,
    exit_reason             TEXT NOT NULL,
    hold_duration_secs      INTEGER NOT NULL,
    fee_usd                 REAL NOT NULL DEFAULT 0.0,
    stop_loss_pct           REAL NOT NULL,
    take_profit_pct         REAL NOT NULL,
    entry_order_id          TEXT,
    exit_order_id           TEXT,
    persona                 TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS daily_pnl (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    date                TEXT NOT NULL UNIQUE,
    starting_balance    REAL NOT NULL,
    ending_balance      REAL,
    pnl_usd             REAL,
    pnl_pct             REAL
);

CREATE TABLE IF NOT EXISTS agent_state (
    key     TEXT PRIMARY KEY,
    value   TEXT NOT NULL
);
"""

# ──────────────────────────────────────────────────────────────
# Audit DB schema — append-only, immutable
# ──────────────────────────────────────────────────────────────

AUDIT_SCHEMA = """
CREATE TABLE IF NOT EXISTS audit_cycles (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    mode                    TEXT NOT NULL,
    cycle_at                TEXT NOT NULL,
    portfolio_balance_usd   REAL NOT NULL,
    available_cash_usd      REAL NOT NULL,
    open_positions_count    INTEGER NOT NULL,
    daily_pnl_usd           REAL NOT NULL DEFAULT 0.0,
    daily_pnl_pct           REAL NOT NULL DEFAULT 0.0,
    cycle_duration_ms       INTEGER
);

CREATE TABLE IF NOT EXISTS audit_signals (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    cycle_id            INTEGER NOT NULL REFERENCES audit_cycles(id),
    pair                TEXT NOT NULL,
    price               REAL NOT NULL,
    rsi_14              REAL,
    macd_line           REAL,
    macd_signal_line    REAL,
    macd_histogram      REAL,
    ema_20              REAL,
    ema_50              REAL,
    bb_upper            REAL,
    bb_mid              REAL,
    bb_lower            REAL,
    atr_14              REAL,
    signal_direction    TEXT NOT NULL,
    signal_strength     REAL NOT NULL,
    signal_reasons      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_llm_decisions (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    cycle_id            INTEGER NOT NULL REFERENCES audit_cycles(id),
    mode                TEXT NOT NULL,
    decided_at          TEXT NOT NULL,
    pair                TEXT NOT NULL,
    model_name          TEXT NOT NULL,
    decision_type       TEXT NOT NULL,
    tool_called         TEXT NOT NULL,
    tool_args           TEXT,
    hold_reason         TEXT,
    reasoning_summary   TEXT,
    raw_llm_output      TEXT NOT NULL,
    prompt_tokens       INTEGER,
    completion_tokens   INTEGER,
    latency_ms          INTEGER
);

CREATE TABLE IF NOT EXISTS audit_risk_checks (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    llm_decision_id         INTEGER NOT NULL REFERENCES audit_llm_decisions(id),
    checked_at              TEXT NOT NULL,
    proposed_action         TEXT NOT NULL,
    proposed_pair           TEXT NOT NULL,
    proposed_usd_amount     REAL,
    approved                INTEGER NOT NULL,
    rejection_reason        TEXT,
    adjusted_usd_amount     REAL
);

CREATE TABLE IF NOT EXISTS audit_orders (
    id                          INTEGER PRIMARY KEY AUTOINCREMENT,
    risk_check_id               INTEGER REFERENCES audit_risk_checks(id),
    mode                        TEXT NOT NULL,
    submitted_at                TEXT NOT NULL,
    pair                        TEXT NOT NULL,
    side                        TEXT NOT NULL,
    order_type                  TEXT NOT NULL,
    role                        TEXT NOT NULL,
    requested_volume            REAL,
    requested_price             REAL,
    exchange_order_id           TEXT,
    paper_fill_price            REAL,
    status                      TEXT NOT NULL,
    error_message               TEXT,
    configured_stop_loss_pct    REAL,
    configured_take_profit_pct  REAL
);

CREATE TABLE IF NOT EXISTS audit_fills (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id            INTEGER NOT NULL REFERENCES audit_orders(id),
    mode                TEXT NOT NULL,
    filled_at           TEXT NOT NULL,
    fill_price          REAL NOT NULL,
    fill_volume         REAL NOT NULL,
    fill_usd_value      REAL NOT NULL,
    fee_usd             REAL NOT NULL DEFAULT 0.0,
    slippage_pct        REAL NOT NULL DEFAULT 0.0
);

CREATE TABLE IF NOT EXISTS audit_position_events (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    mode                    TEXT NOT NULL,
    event_at                TEXT NOT NULL,
    pair                    TEXT NOT NULL,
    event_type              TEXT NOT NULL,
    entry_price             REAL NOT NULL,
    exit_price              REAL,
    pnl_usd                 REAL,
    pnl_pct                 REAL,
    hold_duration_seconds   INTEGER,
    exit_order_id           INTEGER REFERENCES audit_orders(id),
    take_profit_pct_used    REAL,
    stop_loss_pct_used      REAL
);

CREATE TABLE IF NOT EXISTS audit_balance_snapshots (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    mode                TEXT NOT NULL,
    snapshot_at         TEXT NOT NULL,
    total_usd           REAL NOT NULL,
    cash_usd            REAL NOT NULL,
    holdings_json       TEXT NOT NULL,
    unrealised_pnl_usd  REAL NOT NULL DEFAULT 0.0
);

CREATE TABLE IF NOT EXISTS audit_errors (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    mode                TEXT NOT NULL,
    error_at            TEXT NOT NULL,
    component           TEXT NOT NULL,
    error_type          TEXT NOT NULL,
    error_message       TEXT NOT NULL,
    stack_trace         TEXT,
    recovered           INTEGER NOT NULL DEFAULT 1
);
"""


# ──────────────────────────────────────────────────────────────
# RAA schema — Research Analyst Agent universe tables (S22.1.1)
# ──────────────────────────────────────────────────────────────

RAA_SCHEMA = """
CREATE TABLE IF NOT EXISTS trend_persistence (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    pair                TEXT NOT NULL UNIQUE,
    classification      TEXT NOT NULL,
    persistence_score   REAL NOT NULL DEFAULT 0.0,
    cycles_sustained    INTEGER NOT NULL DEFAULT 0,
    first_seen_at       TEXT NOT NULL,
    last_updated_at     TEXT NOT NULL,
    status              TEXT NOT NULL DEFAULT 'CANDIDATE'
);

CREATE TABLE IF NOT EXISTS universe (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    pair                    TEXT NOT NULL UNIQUE,
    classification          TEXT NOT NULL,
    added_at                TEXT NOT NULL,
    added_by                TEXT NOT NULL DEFAULT 'RAA',
    alpha_spread_at_entry   REAL,
    replace_target_if_any   TEXT
);

CREATE TABLE IF NOT EXISTS universe_events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    pair            TEXT NOT NULL,
    event_type      TEXT NOT NULL,
    ts              TEXT NOT NULL,
    processed       INTEGER NOT NULL DEFAULT 0,
    payload_json    TEXT
);
CREATE INDEX IF NOT EXISTS ix_universe_events_pair ON universe_events(pair, ts);
"""

# ──────────────────────────────────────────────────────────────
# Feedback schema — Audit Agent closed-loop tables (S23.1.1)
# ──────────────────────────────────────────────────────────────

FEEDBACK_SCHEMA = """
CREATE TABLE IF NOT EXISTS audit_feedback (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    agent           TEXT NOT NULL,
    pair            TEXT,
    event_type      TEXT NOT NULL,
    ts              TEXT NOT NULL,
    psv_vector      TEXT NOT NULL DEFAULT '',
    expected_alpha  REAL,
    actual_alpha    REAL,
    outcome         TEXT,
    penalty_weight  REAL NOT NULL DEFAULT 0.0
);
CREATE INDEX IF NOT EXISTS ix_audit_feedback_agent_ts ON audit_feedback(agent, ts);

CREATE TABLE IF NOT EXISTS playbook_performance (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    regime          TEXT NOT NULL,
    playbook        TEXT NOT NULL,
    sample_count    INTEGER NOT NULL DEFAULT 0,
    win_rate        REAL,
    profit_factor   REAL,
    max_drawdown    REAL,
    last_updated_at TEXT NOT NULL,
    UNIQUE(regime, playbook)
);

CREATE TABLE IF NOT EXISTS signal_accuracy (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    pair              TEXT NOT NULL,
    driver            TEXT NOT NULL,
    accuracy_pct      REAL NOT NULL DEFAULT 0.0,
    weight_multiplier REAL NOT NULL DEFAULT 1.0,
    sample_count      INTEGER NOT NULL DEFAULT 0,
    last_updated_at   TEXT NOT NULL,
    UNIQUE(pair, driver)
);

CREATE TABLE IF NOT EXISTS llm_reflection_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    agent       TEXT NOT NULL,
    pair        TEXT,
    lesson_text TEXT NOT NULL,
    ts          TEXT NOT NULL,
    injected    INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS ix_llm_reflection_agent ON llm_reflection_log(agent, ts);

CREATE TABLE IF NOT EXISTS confidence_state (
    id                       INTEGER PRIMARY KEY AUTOINCREMENT,
    agent                    TEXT NOT NULL UNIQUE,
    ps_threshold_override    REAL,
    sector_multiplier_json   TEXT,
    driver_multiplier_json   TEXT,
    confidence_reset_count   INTEGER NOT NULL DEFAULT 0,
    substitution_tool_locked INTEGER NOT NULL DEFAULT 0,
    locked_until_ts          TEXT,
    last_updated_at          TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS risk_decision_outcomes (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    pair            TEXT NOT NULL UNIQUE,
    sample_count    INTEGER NOT NULL DEFAULT 0,
    sl_hit_rate     REAL NOT NULL DEFAULT 0.0,
    tp_hit_rate     REAL NOT NULL DEFAULT 0.0,
    avg_hold_secs   REAL,
    last_updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS hitl_queue (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ts              TEXT NOT NULL,
    agent           TEXT NOT NULL,
    proposal_type   TEXT NOT NULL,
    pair            TEXT NOT NULL,
    replace_target  TEXT,
    classification  TEXT,
    psv_vector      TEXT,
    rationale       TEXT,
    status          TEXT NOT NULL DEFAULT 'PENDING',
    resolved_at     TEXT,
    resolved_by     TEXT
);
CREATE INDEX IF NOT EXISTS ix_hitl_queue_status ON hitl_queue(status, ts);
"""


def _init_db(conn: sqlite3.Connection, schema: str, db_name: str) -> None:
    """Execute a multi-statement schema string on the given connection."""
    try:
        conn.executescript(schema)
        conn.commit()
        logger.debug("Schema initialised: %s", db_name)
    except sqlite3.Error as e:
        logger.error("Failed to initialise %s: %s", db_name, e)
        raise


def init_paper_db(paper_db: str, starting_balance: float = 1000.0) -> None:
    """Initialise paper trading DB. Seeds wallet if first run."""
    conn = get_connection(paper_db)
    _init_db(conn, PAPER_SCHEMA, paper_db)
    _init_db(conn, COLLECTOR_SCHEMA, paper_db)  # S21.1.1: candle_buffer + orderbook_snapshots
    _init_db(conn, FULFILLMENT_AUDIT_SCHEMA, paper_db)  # S21.2.2: fulfillment audit trail
    _init_db(conn, RAA_SCHEMA, paper_db)      # S22.1.1: trend_persistence, universe, universe_events
    _init_db(conn, FEEDBACK_SCHEMA, paper_db) # S23.1.1: audit_feedback, hitl_queue, etc.
    # Idempotent migrations for columns/tables added after initial schema creation
    for col_ddl in [
        "ALTER TABLE paper_positions ADD COLUMN highest_price_seen REAL",
        "ALTER TABLE paper_positions ADD COLUMN partial_exited INTEGER DEFAULT 0",
        "CREATE TABLE IF NOT EXISTS agent_state (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
        "ALTER TABLE paper_trades ADD COLUMN persona TEXT NOT NULL DEFAULT ''",
        # Option 2 RAA architecture (S24.1.1)
        "ALTER TABLE universe ADD COLUMN status TEXT NOT NULL DEFAULT 'active'",
        "ALTER TABLE universe ADD COLUMN raa_confidence_score REAL DEFAULT 0.0",
        "ALTER TABLE universe ADD COLUMN grace_period_hours INTEGER DEFAULT 1",
        "ALTER TABLE universe ADD COLUMN promoted_at TEXT",
    ]:
        try:
            conn.execute(col_ddl)
            conn.commit()
        except sqlite3.OperationalError:
            pass  # Column already exists
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM paper_wallet")
    if cursor.fetchone()[0] == 0:
        from src.utils.tz import now_sgt_iso
        now = now_sgt_iso()
        cursor.execute(
            "INSERT INTO paper_wallet (updated_at, cash_usd) VALUES (?, ?)",
            (now, starting_balance)
        )
        conn.commit()
        logger.info("Paper wallet seeded with $%.2f", starting_balance)
    conn.close()


def init_live_db(live_db: str) -> None:
    """Initialise live trading DB."""
    conn = get_connection(live_db)
    _init_db(conn, LIVE_SCHEMA, live_db)
    _init_db(conn, COLLECTOR_SCHEMA, live_db)  # S21.1.1: candle_buffer + orderbook_snapshots
    _init_db(conn, FULFILLMENT_AUDIT_SCHEMA, live_db)  # S21.2.2: fulfillment audit trail
    _init_db(conn, RAA_SCHEMA, live_db)      # S22.1.1: trend_persistence, universe, universe_events
    _init_db(conn, FEEDBACK_SCHEMA, live_db) # S23.1.1: audit_feedback, hitl_queue, etc.
    for col_ddl in [
        "ALTER TABLE live_positions ADD COLUMN highest_price_seen REAL",
        "ALTER TABLE live_positions ADD COLUMN partial_exited INTEGER DEFAULT 0",
        "CREATE TABLE IF NOT EXISTS agent_state (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
        "ALTER TABLE live_trades ADD COLUMN persona TEXT NOT NULL DEFAULT ''",
        # Option 2 RAA architecture (S24.1.1)
        "ALTER TABLE universe ADD COLUMN status TEXT NOT NULL DEFAULT 'active'",
        "ALTER TABLE universe ADD COLUMN raa_confidence_score REAL DEFAULT 0.0",
        "ALTER TABLE universe ADD COLUMN grace_period_hours INTEGER DEFAULT 1",
        "ALTER TABLE universe ADD COLUMN promoted_at TEXT",
    ]:
        try:
            conn.execute(col_ddl)
            conn.commit()
        except sqlite3.OperationalError:
            pass  # Column already exists
    conn.close()


def init_audit_db(audit_db: str) -> None:
    """Initialise audit DB."""
    conn = get_connection(audit_db)
    _init_db(conn, AUDIT_SCHEMA, audit_db)
    conn.close()


def init_all_databases(config: dict, mode: str) -> None:
    """
    Initialise all required databases based on mode.
    mode: 'paper' or 'live'

    Uses resolve_trading_db() so that concurrent_mode personas get their own
    isolated DB file (e.g. paper_trading_conservative.db). Story: S12.1.3.
    """
    storage = config.get("storage", {})
    audit_db = storage.get("audit_db", "audit.db")
    init_audit_db(audit_db)
    logger.info("Audit DB ready: %s", audit_db)

    trading_db = resolve_trading_db(config, mode)
    if mode == "paper":
        starting_balance = config.get("paper", {}).get("starting_balance_usd", 1000.0)
        init_paper_db(trading_db, starting_balance)
        logger.info("Paper trading DB ready: %s", trading_db)
    else:
        init_live_db(trading_db)
        logger.info("Live trading DB ready: %s", trading_db)


# ──────────────────────────────────────────────────────────────
# Option 2 RAA Integration — Hybrid Universe (S24.1.1)
# ──────────────────────────────────────────────────────────────


def get_trading_universe_hybrid(config: dict, db_path: str) -> tuple[list[str], dict]:
    """
    Get hybrid trading universe: core pairs from config + RAA-approved additions.

    Returns:
        (pairs_list, composition_dict)
        pairs_list: ordered list of unique pairs [core + RAA-approved]
        composition_dict: {
            'core': [...],
            'raa_approved': [...],
            'total': int,
            'core_count': int,
            'raa_count': int,
        }
    """
    import logging
    logger = logging.getLogger("database")

    # Step 1: Get core pairs from config (always available)
    trading_cfg = config.get("trading", {})
    core_pairs_raw = [p["pair"] for p in trading_cfg.get("pairs", [])]
    core_pairs = list(dict.fromkeys(core_pairs_raw))  # deduplicate
    logger.info("[UNIVERSE] Core pairs from config: %d", len(core_pairs))

    # Step 2: Query RAA-approved pairs from universe table (status='active' or status='proposed' past grace period)
    try:
        conn = get_connection(db_path)
        cursor = conn.cursor()

        # Get all pairs marked as approved by RAA (status='active')
        # Plus 'proposed' pairs past grace period (added_at + grace_period_hours <= now)
        now = datetime.now(timezone.utc).isoformat()
        cursor.execute("""
            SELECT pair, status, raa_confidence_score, added_at, grace_period_hours
            FROM universe
            WHERE status='active'
               OR (status='proposed' AND
                   datetime(added_at) <= datetime('now', '-' || grace_period_hours || ' hours'))
            ORDER BY added_at ASC
        """)
        raa_rows = cursor.fetchall()
        conn.close()

        raa_approved = [row[0] for row in raa_rows]
        logger.info("[UNIVERSE] RAA-approved pairs (active + past grace): %d", len(raa_approved))

    except Exception as e:
        logger.error("[UNIVERSE] Error querying RAA universe: %s", e)
        raa_approved = []

    # Step 3: Merge core + RAA, preserving order and deduplicating
    all_pairs = []
    seen = set()

    # Add core pairs first (always prioritized)
    for p in core_pairs:
        if p not in seen:
            all_pairs.append(p)
            seen.add(p)

    # Add RAA pairs (only if not already in core)
    for p in raa_approved:
        if p not in seen:
            all_pairs.append(p)
            seen.add(p)

    composition = {
        "core": core_pairs,
        "raa_approved": raa_approved,
        "total": len(all_pairs),
        "core_count": len(core_pairs),
        "raa_count": len(raa_approved),
    }

    logger.info(
        "[UNIVERSE] Trading pairs: %d core + %d RAA-approved = %d total",
        len(core_pairs), len(raa_approved), len(all_pairs)
    )
    return all_pairs, composition


def is_pair_approved_by_raa(pair: str, db_path: str, grace_period_hours: int = 1) -> bool:
    """
    Check if a pair is RAA-approved and past grace period (eligible for trading).

    Returns:
        True if pair is in universe table with status='active' OR status='proposed' past grace period
        False otherwise
    """
    try:
        conn = get_connection(db_path)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT status, added_at, grace_period_hours
            FROM universe
            WHERE pair = ?
        """, (pair,))
        row = cursor.fetchone()
        conn.close()

        if not row:
            return False  # Pair not in RAA universe

        status, added_at_str, grace_hours = row

        # Active pairs are always approved
        if status == "active":
            return True

        # Proposed pairs are approved only after grace period
        if status == "proposed":
            added_at = datetime.fromisoformat(added_at_str)
            now = datetime.now(timezone.utc)
            grace_period = timedelta(hours=grace_hours or grace_period_hours)
            return (now - added_at) >= grace_period

        return False

    except Exception as e:
        import logging
        logger = logging.getLogger("database")
        logger.error("[UNIVERSE] Error checking pair approval for %s: %s", pair, e)
        return False
