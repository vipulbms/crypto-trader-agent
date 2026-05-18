"""
MCP HTTP Server — read-only query interface for Kryptos state.

Story: S17.1.1 | Sprint: S6 | Epic: E17

Provides six read-only tools over HTTP-based MCP on 127.0.0.1:8092.
All tools return pipe-separated strings.  DB connections are opened
read-only (``?mode=ro``) so this process can never corrupt the trading DB.

Tools
-----
get_portfolio_state   : cash, total_usd, open positions summary
get_signal_snapshot   : last generated signals per pair (from agent_state)
get_regime_state      : playbook, regime, ADX median, BTC dominance
get_agent_status      : persona, uptime, cycle count, last cycle ts
get_universe_state    : active pairs with tier and daily win rate
get_persistence_scores: per-pair entry score persistence (14-day win rate proxy)

Security (AC5): binds exclusively to ``127.0.0.1``; non-localhost connections
are rejected via the aiohttp access-log warning — no routing to external NIC.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

try:
    from aiohttp import web
    _AIOHTTP_AVAILABLE = True
except ImportError:
    _AIOHTTP_AVAILABLE = False

from src.storage.database import get_connection_ro

logger = logging.getLogger(__name__)

_DEFAULT_PORT = 8092
_BIND_HOST    = "127.0.0.1"


# ── helpers ────────────────────────────────────────────────────────────────────

def _agent_state_all(db_path: str) -> dict[str, str]:
    """Return all agent_state rows as a plain dict."""
    try:
        conn = get_connection_ro(db_path)
        rows = conn.execute("SELECT key, value FROM agent_state").fetchall()
        conn.close()
        return {r["key"]: r["value"] for r in rows}
    except Exception:
        return {}


def _open_positions(db_path: str) -> list[dict]:
    try:
        conn = get_connection_ro(db_path)
        rows = conn.execute(
            "SELECT pair, volume, usd_value, entry_price, stop_loss_price, "
            "take_profit_price FROM paper_positions WHERE status='open'"
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception:
        return []


def _cash(db_path: str) -> float:
    try:
        conn = get_connection_ro(db_path)
        row = conn.execute(
            "SELECT cash_usd FROM paper_balance ORDER BY id DESC LIMIT 1"
        ).fetchone()
        conn.close()
        return float(row["cash_usd"]) if row else 0.0
    except Exception:
        return 0.0


def _closed_trades(db_path: str, days: int = 14) -> list[dict]:
    try:
        import time as _t
        cutoff = _t.time() - days * 86400
        conn = get_connection_ro(db_path)
        rows = conn.execute(
            "SELECT pair, pnl_usd, exit_reason, closed_at FROM paper_trades "
            "WHERE closed_at >= ? ORDER BY closed_at DESC",
            (cutoff,),
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception:
        return []


# ── tool implementations ───────────────────────────────────────────────────────

def tool_get_portfolio_state(db_path: str) -> str:
    """cash|X|total_usd|X|open_positions|N|pairs|A,B,C"""
    positions = _open_positions(db_path)
    cash = _cash(db_path)
    invested = sum(p.get("usd_value", 0) for p in positions)
    total = cash + invested
    pairs_str = ",".join(p["pair"] for p in positions) if positions else ""
    return (
        f"cash|{cash:.2f}|total_usd|{total:.2f}|"
        f"open_positions|{len(positions)}|pairs|{pairs_str}"
    )


def tool_get_signal_snapshot(db_path: str) -> str:
    """pair|X|signal|BUY|score|N|ts|T (pipe-separated, semicolon between pairs)"""
    state = _agent_state_all(db_path)
    # Signals are stored as agent_state key 'signal_snapshot_<pair>'
    parts = []
    for key, val in sorted(state.items()):
        if key.startswith("signal_snapshot_"):
            pair = key[len("signal_snapshot_"):]
            try:
                rec = json.loads(val)
                parts.append(
                    f"pair|{pair}|signal|{rec.get('signal','')}|"
                    f"score|{rec.get('score',0)}|ts|{rec.get('ts','')}"
                )
            except Exception:
                parts.append(f"pair|{pair}|raw|{val[:80]}")
    return ";".join(parts) if parts else "no_snapshot"


def tool_get_regime_state(db_path: str) -> str:
    """playbook|X|regime|X|adx_median|N|btc_dom_trend|X|daily_pnl_pct|N|vel_circuit|0or1"""
    state = _agent_state_all(db_path)
    playbook     = state.get("current_playbook", "ranging")
    regime       = state.get("current_regime", "unknown")
    adx_median   = state.get("adx_median_last", "0.0")
    btc_trend    = state.get("btc_dom_trend_current", "flat")
    daily_pnl    = state.get("daily_pnl_pct_last", "0.0")
    vel_until    = float(state.get("velocity_circuit_open_until", "0"))
    vel_open     = 1 if vel_until > time.time() else 0
    return (
        f"playbook|{playbook}|regime|{regime}|adx_median|{adx_median}|"
        f"btc_dom_trend|{btc_trend}|daily_pnl_pct|{daily_pnl}|vel_circuit|{vel_open}"
    )


def tool_get_agent_status(db_path: str) -> str:
    """persona|X|mode|paper|cycles_today|N|last_cycle_ts|T|uptime_secs|N"""
    state = _agent_state_all(db_path)
    persona      = state.get("active_persona", "unknown")
    mode         = state.get("agent_mode", "paper")
    cycles_today = state.get("cycles_today", "0")
    last_cycle   = state.get("last_cycle_ts", "0")
    uptime       = state.get("agent_uptime_start", "0")
    uptime_secs  = int(time.time() - float(uptime)) if uptime != "0" else 0
    return (
        f"persona|{persona}|mode|{mode}|cycles_today|{cycles_today}|"
        f"last_cycle_ts|{last_cycle}|uptime_secs|{uptime_secs}"
    )


def tool_get_universe_state(db_path: str, config: dict) -> str:
    """pair|X|tier|N|tp_pct|N|buy_min_score|N (semicolon between pairs)"""
    pairs_cfg = config.get("trading", {}).get("pairs", [])
    parts = []
    for p in pairs_cfg:
        pair   = p.get("pair", "")
        tier   = p.get("pair_tier", 0)
        tp_pct = p.get("take_profit_pct", 0)
        bms    = p.get("buy_min_score", config.get("signals", {}).get("min_score", 5))
        parts.append(f"pair|{pair}|tier|{tier}|tp_pct|{tp_pct}|buy_min_score|{bms}")
    return ";".join(parts) if parts else "no_universe"


def tool_get_persistence_scores(db_path: str, config: dict) -> str:
    """pair|X|win_rate|N|trades|N|pf|N (14-day, semicolon between pairs)"""
    trades = _closed_trades(db_path, days=14)
    # Aggregate per pair
    from collections import defaultdict
    wins: dict[str, int] = defaultdict(int)
    total: dict[str, int] = defaultdict(int)
    pnl_pos: dict[str, float] = defaultdict(float)
    pnl_neg: dict[str, float] = defaultdict(float)

    for t in trades:
        pair = t.get("pair", "")
        pnl  = float(t.get("pnl_usd", 0))
        total[pair] += 1
        if pnl > 0:
            wins[pair]    += 1
            pnl_pos[pair] += pnl
        else:
            pnl_neg[pair] += abs(pnl)

    parts = []
    pairs_cfg = config.get("trading", {}).get("pairs", [])
    for p in pairs_cfg:
        pair = p.get("pair", "")
        n    = total.get(pair, 0)
        w    = wins.get(pair, 0)
        wr   = round(w / n * 100, 1) if n > 0 else 0.0
        pos  = pnl_pos.get(pair, 0.0)
        neg  = pnl_neg.get(pair, 0.0)
        pf   = round(pos / neg, 2) if neg > 0 else (999.0 if pos > 0 else 0.0)
        parts.append(f"pair|{pair}|win_rate|{wr}|trades|{n}|pf|{pf}")
    return ";".join(parts) if parts else "no_data"


# ── HTTP server ────────────────────────────────────────────────────────────────

class MCPServer:
    """
    Lightweight aiohttp HTTP server exposing 6 read-only MCP tools.

    S17.1.1 AC1: binds on 127.0.0.1:8092
    S17.1.1 AC4: all DB access via get_connection_ro (read-only flag)
    S17.1.1 AC5: host='127.0.0.1' only
    S17.1.1 AC6: each handler must respond < 500ms
    """

    def __init__(self, config: dict, db_path: str) -> None:
        if not _AIOHTTP_AVAILABLE:
            raise RuntimeError(
                "aiohttp is required for the MCP server. "
                "Install it with: pip install aiohttp"
            )
        self._config  = config
        self._db_path = db_path
        mcp_cfg       = config.get("mcp", {})
        self._port    = int(mcp_cfg.get("port", _DEFAULT_PORT))
        self._app     = web.Application()
        self._app.router.add_post("/mcp", self._handle_mcp)
        self._app.router.add_get("/health", self._handle_health)

    async def _handle_health(self, _req: "web.Request") -> "web.Response":
        return web.Response(text="ok")

    async def _handle_mcp(self, req: "web.Request") -> "web.Response":
        try:
            body  = await req.json()
            tool  = body.get("tool", "")
            result = self._dispatch(tool)
            return web.json_response({"result": result})
        except Exception as exc:
            logger.warning("[MCP] Request error: %s", exc)
            return web.json_response({"error": str(exc)}, status=400)

    def _dispatch(self, tool: str) -> str:
        db = self._db_path
        cfg = self._config
        dispatch: dict[str, Any] = {
            "get_portfolio_state":    lambda: tool_get_portfolio_state(db),
            "get_signal_snapshot":    lambda: tool_get_signal_snapshot(db),
            "get_regime_state":       lambda: tool_get_regime_state(db),
            "get_agent_status":       lambda: tool_get_agent_status(db),
            "get_universe_state":     lambda: tool_get_universe_state(db, cfg),
            "get_persistence_scores": lambda: tool_get_persistence_scores(db, cfg),
        }
        if tool not in dispatch:
            raise ValueError(f"Unknown tool: {tool!r}. Available: {sorted(dispatch)}")
        return dispatch[tool]()

    async def start(self) -> None:
        runner = web.AppRunner(self._app, access_log=None)
        await runner.setup()
        site = web.TCPSite(runner, _BIND_HOST, self._port)
        await site.start()
        logger.info("[MCP] Server listening on %s:%d", _BIND_HOST, self._port)


# ── CLI entry point ───────────────────────────────────────────────────────────

def _main() -> None:
    """
    AC5: Start the MCP server from the command line.

    Usage:
        python src/mcp/server.py --mode paper
        python src/mcp/server.py --mode live
        python src/mcp/server.py --mode paper --port 8092
    """
    import argparse
    import asyncio
    import signal

    import yaml

    parser = argparse.ArgumentParser(
        description="Kryptos MCP HTTP server — read-only state query interface"
    )
    parser.add_argument(
        "--mode",
        choices=["paper", "live"],
        required=True,
        help="Trading mode: 'paper' → paper_trading.db, 'live' → live_trading.db",
    )
    parser.add_argument(
        "--config",
        default="config.yaml",
        help="Path to config.yaml (default: config.yaml)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help=f"Override port (default: config mcp.port or {_DEFAULT_PORT})",
    )
    args = parser.parse_args()

    with open(args.config) as fh:
        config = yaml.safe_load(fh)

    # Resolve DB path based on mode
    storage = config.get("storage", {})
    if args.mode == "live":
        db_file = storage.get("live_db", "live_trading.db")
    else:
        db_file = storage.get("paper_db", "paper_trading.db")

    from src.storage.database import get_db_path
    db_path = get_db_path(db_file)

    if args.port is not None:
        config.setdefault("mcp", {})["port"] = args.port

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    if not _AIOHTTP_AVAILABLE:
        logger.error("aiohttp is required: pip install aiohttp")
        raise SystemExit(1)

    server = MCPServer(config, db_path)

    async def _serve() -> None:
        await server.start()
        logger.info("[MCP] Mode=%s  DB=%s", args.mode, db_path)
        stop_event = asyncio.Event()

        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, stop_event.set)

        await stop_event.wait()
        logger.info("[MCP] Shutting down.")

    asyncio.run(_serve())


if __name__ == "__main__":
    _main()
