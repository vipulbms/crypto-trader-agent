"""
Database initialisation for paper_trading.db, live_trading.db, and audit.db.
Call init_all_databases() once at startup to ensure all tables exist.
"""

import sqlite3
import os
import logging

logger = logging.getLogger(__name__)


def _get_db_path(db_filename: str) -> str:
    """Return absolute path to a DB file in the project root data/ directory."""
    base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    data_dir = os.path.join(base, "data")
    os.makedirs(data_dir, exist_ok=True)
    return os.path.join(data_dir, db_filename)


def get_connection(db_filename: str) -> sqlite3.Connection:
    """Open and return a SQLite connection with foreign keys enabled."""
    path = _get_db_path(db_filename)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    return conn


# ──────────────────────────────────────────────────────────────
# Paper trading DB schema
# ──────────────────────────────────────────────────────────────

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
    status              TEXT NOT NULL DEFAULT 'open'
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
    take_profit_pct     REAL NOT NULL
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
    exit_order_id           TEXT
);

CREATE TABLE IF NOT EXISTS daily_pnl (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    date                TEXT NOT NULL UNIQUE,
    starting_balance    REAL NOT NULL,
    ending_balance      REAL,
    pnl_usd             REAL,
    pnl_pct             REAL
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
    """
    storage = config.get("storage", {})
    audit_db = storage.get("audit_db", "audit.db")
    init_audit_db(audit_db)
    logger.info("Audit DB ready: %s", audit_db)

    if mode == "paper":
        paper_db = storage.get("paper_db", "paper_trading.db")
        starting_balance = config.get("paper", {}).get("starting_balance_usd", 1000.0)
        init_paper_db(paper_db, starting_balance)
        logger.info("Paper trading DB ready: %s", paper_db)
    else:
        live_db = storage.get("live_db", "live_trading.db")
        init_live_db(live_db)
        logger.info("Live trading DB ready: %s", live_db)
