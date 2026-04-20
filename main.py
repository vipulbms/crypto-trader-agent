"""
main.py — Kryptos trading agent runner.

This file runs the background trading loop.
For the interactive CLI, use:  python kryptos.py

Usage:
    python main.py --paper     # Paper trading (no API keys needed)
    python main.py --live      # Live trading (requires KRAKEN_API_KEY + SECRET)

The agent:
  1. Initialises databases
  2. Validates config
  3. Starts WebSocket feed (public, no auth)
  4. Runs decision cycles every N minutes
  5. Logs everything to audit.db
"""

import argparse
import asyncio
import logging
import logging.handlers
import os
import sys
import time
import traceback
import uuid
from datetime import datetime, timezone, timedelta

import yaml
from dotenv import load_dotenv

logger = logging.getLogger("main")


class _TraceFilter(logging.Filter):
    """Injects session_id_short and request_id_short into every log record."""

    def __init__(self, session_id: str) -> None:
        super().__init__()
        self._session_id_short = session_id[:8] if session_id else "--------"

    def filter(self, record: logging.LogRecord) -> bool:
        from src.utils.timing import get_request_id
        rid = get_request_id()
        record.session_id_short = self._session_id_short
        record.request_id_short = rid[:8] if rid else "--------"
        return True


def load_config(path: str = "config.yaml") -> dict:
    with open(path, "r") as f:
        return yaml.safe_load(f)


def setup_logging(config: dict, session_id: str = "") -> None:
    storage_cfg  = config.get("storage", {})
    log_dir      = storage_cfg.get("log_dir", "/logs")
    max_bytes    = storage_cfg.get("log_max_bytes", 100 * 1024 * 1024)
    backup_count = storage_cfg.get("log_backup_count", 4)
    llm_debug    = storage_cfg.get("llm_debug_logging", False)
    os.makedirs(log_dir, exist_ok=True)

    fmt = "%(asctime)s [%(levelname)s] [S:%(session_id_short)s] %(name)s: %(message)s"
    trace_filter = _TraceFilter(session_id)

    # File handler — DEBUG when llm_debug_logging enabled, else INFO
    file_handler = logging.handlers.RotatingFileHandler(
        os.path.join(log_dir, "agent.log"), maxBytes=max_bytes, backupCount=backup_count,
    )
    file_handler.setLevel(logging.DEBUG if llm_debug else logging.INFO)
    file_handler.setFormatter(logging.Formatter(fmt))
    file_handler.addFilter(trace_filter)

    # Console handler — always INFO (avoid flooding terminal with prompts)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(logging.Formatter(fmt))
    console_handler.addFilter(trace_filter)

    root = logging.getLogger()
    root.setLevel(logging.DEBUG if llm_debug else logging.INFO)
    # Remove any handlers already attached (e.g. from logging.basicConfig elsewhere)
    # to prevent duplicate log lines when setup_logging is called more than once.
    for h in root.handlers[:]:
        root.removeHandler(h)
        h.close()
    root.addHandler(file_handler)
    # Only attach a console handler when stdout is an interactive terminal.
    # When started as a background subprocess by agent_manager, stdout is
    # redirected to agent.log — adding a StreamHandler there would cause every
    # log line to be written twice (once by file_handler, once via stdout).
    if sys.stdout.isatty():
        root.addHandler(console_handler)


def _get_or_set_sod_balance(db_path: str, current_balance: float) -> tuple:
    """
    Return today's start-of-day balance from agent_state DB.
    Works for both paper (paper_trading.db) and live (live_trading.db) modes.

    Key: start_of_day_balance_YYYY-MM-DD (UTC date).
    - If the key exists for today → return (balance, False).
    - If absent (new day or DB was reset) → store current_balance, return (balance, True).

    The boolean being True signals the caller that midnight just rolled over and a
    daily summary should be sent.
    """
    from src.storage.database import get_connection
    today_key = f"start_of_day_balance_{datetime.now(timezone.utc).strftime('%Y-%m-%d')}"
    try:
        conn = get_connection(db_path)
        row = conn.execute(
            "SELECT value FROM agent_state WHERE key = ?", (today_key,)
        ).fetchone()
        if row:
            conn.close()
            return float(row["value"]), False
        # New day or post-reset — write and return current balance
        conn.execute(
            "INSERT OR REPLACE INTO agent_state (key, value) VALUES (?, ?)",
            (today_key, str(current_balance)),
        )
        conn.commit()
        conn.close()
        logger.info("[SOD] Wrote start-of-day balance $%.2f to agent_state (key=%s)",
                    current_balance, today_key)
        return current_balance, True
    except Exception as exc:
        logger.warning("[SOD] Could not persist start-of-day balance: %s — falling back to current", exc)
    return current_balance, False


def print_banner(mode: str, balance: float, pairs: list) -> None:
    print("\n" + "═" * 60)
    print("  KRYPTOS — AI Crypto Trading Agent")
    print("═" * 60)
    if mode == "paper":
        print("  PAPER TRADING MODE — NO REAL ORDERS WILL BE PLACED")
        print(f"  Starting virtual balance: ${balance:.2f}")
        print("  Kraken private API: NOT REQUIRED")
    else:
        print("  ⚠  LIVE TRADING MODE — REAL MONEY AT RISK")
    print(f"  Pairs: {', '.join(pairs)}")
    print("  Public price feed: wss://ws.kraken.com/v2 (no auth)")
    print("  CLI:  python kryptos.py")
    print("═" * 60 + "\n")


async def run_agent(config: dict, mode: str, feed=None, session_id: str = "") -> None:
    """
    feed : optional HistoricalFeed for back-testing.
           When provided, the live WebSocket is not started and the main loop
           steps through candles via feed.advance() instead of sleeping.
    """
    from src.storage.database import init_all_databases, resolve_trading_db
    from src.storage.audit_logger import AuditLogger
    from src.exchange.websocket_feed import WebSocketFeed
    from src.analysis.indicators import compute_indicators
    from src.analysis.signals import generate_signal
    from src.risk.risk_manager import RiskManager, validate_config
    from src.notifications.notifier import Notifier
    from src.agent.tools import TradingTools
    from src.agent.trading_agent import TradingAgent

    is_backtest = feed is not None

    # ── Validate config ────────────────────────────────────────
    try:
        validate_config(config)
    except ValueError as e:
        logger.error("Config validation failed: %s", e)
        sys.exit(1)

    # ── Init databases ─────────────────────────────────────────
    init_all_databases(config, mode)

    # ── Setup components ───────────────────────────────────────
    storage_cfg = config.get("storage", {})
    audit_db    = storage_cfg.get("audit_db", "audit.db")
    audit       = AuditLogger(audit_db=audit_db, mode=mode)

    ws_feed     = feed if is_backtest else WebSocketFeed(config)
    _trading_db = resolve_trading_db(config, mode)   # S12.1.3: persona-aware DB naming
    risk        = RiskManager(config, db_path=_trading_db)

    # Persona resolved once at startup (disk re-read per cycle handles runtime switches)
    _agent_cfg      = config.get("agent", {})
    _active_persona = _agent_cfg.get("persona", "conservative")
    _concurrent     = bool(_agent_cfg.get("concurrent_mode", False))
    notifier    = Notifier(config, mode, persona=_active_persona if _concurrent else "")

    trading_cfg = config.get("trading", {})
    pairs       = [p["pair"] for p in trading_cfg.get("pairs", [])]
    interval_s  = trading_cfg.get("cycle_interval_minutes", 15) * 60

    # ── Broker setup ───────────────────────────────────────────
    if mode == "paper":
        from src.exchange.paper_broker import PaperBroker
        paper_cfg   = config.get("paper", {})
        slippage    = paper_cfg.get("slippage_pct", 0.05)
        maker_fee   = paper_cfg.get("maker_fee_pct", 0.26)
        broker      = PaperBroker(
            paper_db=_trading_db,
            slippage_pct=slippage,
            maker_fee_pct=maker_fee,
            config=config,
            persona=_active_persona,
        )
    else:
        from src.exchange.kraken_client import KrakenClient
        api_key    = os.getenv("KRAKEN_API_KEY")
        api_secret = os.getenv("KRAKEN_API_SECRET")
        if not api_key or not api_secret:
            logger.error("KRAKEN_API_KEY and KRAKEN_API_SECRET required for live mode")
            sys.exit(1)
        live_db = storage_cfg.get("live_db", "live_trading.db")
        broker = KrakenClient(api_key=api_key, api_secret=api_secret, config=config, live_db=live_db)

    # ── Get starting balance ───────────────────────────────────
    balance_data       = broker.get_balance()
    start_of_day_bal   = balance_data["total_usd"]

    # ── Print startup banner ───────────────────────────────────
    print_banner(mode, start_of_day_bal, pairs)

    _llm_cfg      = config.get("llm", {})
    _llm_provider = _llm_cfg.get("provider", "ollama")
    if _llm_provider == "openai_compat":
        _llm_client = None   # TradingAgent builds the openai client itself
    else:
        import ollama as _ollama
        _llm_client = _ollama.Client(host=_llm_cfg.get("base_url", "http://localhost:11434"))

    tools = TradingTools(
        broker=broker,
        risk_manager=risk,
        audit_logger=audit,
        notifier=notifier,
        ws_feed=ws_feed,
        mode=mode,
        config=config,
        start_of_day_balance=start_of_day_bal,
        llm_client=_llm_client,
    )

    agent = TradingAgent(
        tools=tools,
        config=config,
        mode=mode,
        audit_logger=audit,
        session_id=session_id,
    )

    notifier.send_agent_started(start_of_day_bal, pairs, mode)

    # ── Start feed ────────────────────────────────────────────
    await ws_feed.start()

    ind_cfg_startup  = config.get("indicators", {})
    min_candles      = ind_cfg_startup.get("min_candles_to_start", 220)

    if not is_backtest:
        buf_timeout = ind_cfg_startup.get("buffer_fill_timeout_secs", 300)
        buf_check   = ind_cfg_startup.get("buffer_check_interval_secs", 5)
        logger.info("Starting WebSocket price feed. Waiting for candle buffer (min %d)...", min_candles)
        wait_start = time.time()
        while True:
            ready = all(ws_feed.is_ready(pair, min_candles=min_candles) for pair in pairs)
            if ready:
                break
            if time.time() - wait_start > buf_timeout:
                logger.warning("Buffer not fully filled after %ds — proceeding anyway", buf_timeout)
                break
            await asyncio.sleep(buf_check)

    logger.info("Candle buffers ready. Starting decision cycles.")

    # ── Main cycle loop ────────────────────────────────────────
    loop_state = {
        "daily_loss_notified_date": None,
        "last_heartbeat_time": time.time(),
        "cycles_since_heartbeat": 0,
        "buys_since_heartbeat": 0,
        "sells_since_heartbeat": 0,
        "balance_at_heartbeat": start_of_day_bal,
        # S13.2.2 — per-pair OHLCV freeze tracking
        "freeze_cycle_count": {},   # {pair: int} consecutive FROZEN cycles
        "freeze_alert_sent":  {},   # {pair: bool} alert emitted for current episode
    }
    try:
        while True:
            cycle_start = time.time()

            # ── Refresh start-of-day balance from DB (paper + live mode) ───────
            # Guards against stale in-memory value after reset_paper.py runs
            # while the agent is alive, and handles midnight rollovers. (#170, #178)
            if not is_backtest:
                if mode == "paper":
                    sod_db_path = config.get("storage", {}).get("paper_db", "paper_trading.db")
                else:
                    sod_db_path = config.get("storage", {}).get("live_db", "live_trading.db")
                current_bal_for_sod = broker.get_balance()["total_usd"]
                start_of_day_bal, is_new_day = _get_or_set_sod_balance(sod_db_path, current_bal_for_sod)
                if is_new_day:
                    # Midnight rollover — send yesterday's daily summary (#249)
                    try:
                        from src.reports.trade_report import get_performance_metrics
                        yesterday_metrics = get_performance_metrics(mode, config, days=1)
                        sod_prev = current_bal_for_sod  # balance at SOD transition
                        pnl_usd = yesterday_metrics.get("total_pnl_usd", 0.0)
                        pnl_pct = (pnl_usd / sod_prev * 100) if sod_prev else 0.0
                        notifier.send_daily_summary({
                            "balance": current_bal_for_sod,
                            "pnl_usd": pnl_usd,
                            "pnl_pct": pnl_pct,
                            "trades_today": yesterday_metrics.get("total_trades", 0),
                            "wins": yesterday_metrics.get("wins", 0),
                            "losses": yesterday_metrics.get("losses", 0),
                            "win_rate_pct": yesterday_metrics.get("win_rate_pct", 0.0),
                        })
                    except Exception as _summary_exc:
                        logger.warning("[SOD] send_daily_summary failed: %s", _summary_exc)

            # Stop-loss / take-profit checks run FIRST — highest priority, before LLM decisions
            # In backtest mode, pass the candle timestamp so closed trades record candle time.
            candle_ts_for_check = ws_feed.current_candle_time if is_backtest else 0
            for pair in pairs:
                current_price = ws_feed.get_latest_price(pair)
                if current_price:
                    closed = broker.check_stops_and_tp(pair, current_price, audit,
                                                       candle_ts=candle_ts_for_check)
                    for trade in closed:
                        notifier.send_trade_executed(trade, mode)
                        tools._run_post_trade_analysis(trade)
                        # Update circuit breaker state
                        if trade.get("exit_reason") == "stop_loss":
                            tripped = risk.record_stop_loss(trade.get("pair", pair))
                            if tripped:
                                notifier.send_circuit_breaker_tripped(
                                    risk._cb_consecutive_stops,
                                    risk._cb_pause_secs / 3600,
                                )
                        elif trade.get("pnl_usd", 0) > 0:
                            risk.record_profitable_exit()

            try:
                cycle_result = await run_cycle(
                    broker=broker,
                    agent=agent,
                    ws_feed=ws_feed,
                    audit=audit,
                    notifier=notifier,
                    risk=risk,
                    config=config,
                    pairs=pairs,
                    mode=mode,
                    start_of_day_balance=start_of_day_bal,
                    loop_state=loop_state,
                    is_backtest=is_backtest,
                    trading_db_path=_trading_db,
                )
                loop_state["cycles_since_heartbeat"] += 1
                if cycle_result:
                    loop_state["buys_since_heartbeat"]  += cycle_result.get("buys", 0)
                    loop_state["sells_since_heartbeat"] += cycle_result.get("sells", 0)
            except Exception as e:
                tb = traceback.format_exc()
                logger.error("Cycle error: %s\n%s", e, tb)
                audit.log_error("main_loop", type(e).__name__, str(e), tb, recovered=True)
                notifier.send_error_alert("main_loop", str(e)[:200])

            # ── 2-Hourly heartbeat ──────────────────────────────────────────
            heartbeat_interval = config.get("notifications", {}).get("heartbeat_interval_minutes", 120) * 60
            if not is_backtest and (time.time() - loop_state["last_heartbeat_time"]) >= heartbeat_interval:
                bal = broker.get_balance()
                hourly_pnl_usd = bal["total_usd"] - loop_state["balance_at_heartbeat"]
                hourly_pnl_pct = (hourly_pnl_usd / loop_state["balance_at_heartbeat"] * 100) if loop_state["balance_at_heartbeat"] else 0
                open_pos = broker.get_open_positions()
                cb_active, _ = risk.is_circuit_open()
                # Build per-position detail for heartbeat (#268)
                open_active = [p for p in open_pos if p.get("status", "open") == "open"]
                positions_detail = []
                for _p in open_active:
                    _cprice = ws_feed.get_latest_price(_p["pair"])
                    if _cprice and _p.get("volume") and _p.get("usd_value"):
                        _unreal_pnl = round(_cprice * _p["volume"] - _p["usd_value"], 2)
                        _unreal_pct = round(_unreal_pnl / _p["usd_value"] * 100, 1) if _p["usd_value"] else 0.0
                        _sl_dist = round((_cprice - _p["stop_loss_price"]) / _cprice * 100, 1) if _p.get("stop_loss_price") else None
                        _tp_dist = round((_p["take_profit_price"] - _cprice) / _cprice * 100, 1) if _p.get("take_profit_price") else None
                        positions_detail.append({
                            "pair": _p["pair"],
                            "pnl_usd": _unreal_pnl,
                            "pnl_pct": _unreal_pct,
                            "sl_dist_pct": _sl_dist,
                            "tp_dist_pct": _tp_dist,
                        })
                notifier.send_heartbeat({
                    "balance_usd":          bal["total_usd"],
                    "hourly_pnl_usd":       round(hourly_pnl_usd, 2),
                    "hourly_pnl_pct":       round(hourly_pnl_pct, 2),
                    "cycles_completed":     loop_state["cycles_since_heartbeat"],
                    "open_positions":       len(open_active),
                    "buys_last_hour":       loop_state["buys_since_heartbeat"],
                    "sells_last_hour":      loop_state["sells_since_heartbeat"],
                    "circuit_breaker_active": cb_active,
                    "positions_detail":     positions_detail,
                })
                loop_state["last_heartbeat_time"]    = time.time()
                loop_state["cycles_since_heartbeat"] = 0
                loop_state["buys_since_heartbeat"]   = 0
                loop_state["sells_since_heartbeat"]  = 0
                loop_state["balance_at_heartbeat"]   = bal["total_usd"]

            # ── 6-Hour PnL Report ─────────────────────────────────────────
            if "last_6h_report_time" not in loop_state:
                loop_state["last_6h_report_time"] = time.time()
                
            report_interval = config.get("notifications", {}).get("pnl_report_interval_minutes", 360) * 60
            if not is_backtest and (time.time() - loop_state["last_6h_report_time"]) >= report_interval:
                bal = broker.get_balance()
                net_pnl_usd = bal["total_usd"] - start_of_day_bal
                net_pnl_pct = (net_pnl_usd / start_of_day_bal * 100) if start_of_day_bal else 0
                notifier.send_pnl_report(bal["total_usd"], net_pnl_usd, net_pnl_pct)
                loop_state["last_6h_report_time"] = time.time()

            if is_backtest:
                if not ws_feed.advance():
                    logger.info("Backtest complete — history exhausted (%s)", ws_feed.progress)
                    break
            else:
                elapsed   = time.time() - cycle_start
                sleep_for = max(0, interval_s - elapsed)
                logger.info(
                    "Cycle complete in %.1fs. Next cycle in %.0fs.",
                    elapsed, sleep_for,
                )
                notifier.ping_healthcheck()
                await asyncio.sleep(sleep_for)

    except asyncio.CancelledError:
        pass
    except KeyboardInterrupt:
        logger.info("Shutdown requested")
    finally:
        logger.info("Stopping WebSocket feed...")
        await ws_feed.stop()
        notifier.send_agent_stopped(mode)
        logger.info("Agent stopped cleanly")


async def run_cycle(
    broker, agent, ws_feed, audit, notifier, risk, config,
    pairs, mode, start_of_day_balance, loop_state=None,
    is_backtest=False, trading_db_path=None,
) -> None:
    """Execute one decision cycle: collect data → build signals → run LLM → execute."""
    from src.analysis.indicators import compute_indicators
    from src.analysis.signals import generate_signal
    from src.utils.timing import set_cycle_id
    from src.core.cycle_context import CycleContext

    cycle_start_ms = int(time.time() * 1000)
    ind_cfg = config.get("indicators", {})

    # Collect portfolio state
    balance_data    = broker.get_balance()
    total_usd       = balance_data["total_usd"]
    cash_usd        = balance_data["available_cash_usd"]
    open_positions  = broker.get_open_positions()
    n_positions     = len([p for p in open_positions if p.get("status", "open") == "open"])

    daily_pnl       = broker.get_daily_pnl(start_of_day_balance)
    # max_per_trade: cap as % of available cash (not total portfolio) so the LLM
    # proposes sizes proportional to what can actually be deployed (#165)
    max_per_trade   = cash_usd * (config.get("trading", {}).get("max_position_pct", 30) / 100)

    portfolio = {
        "total_usd":           total_usd,
        "available_cash_usd":  cash_usd,
        "open_positions_count": n_positions,
        "daily_pnl_usd":       daily_pnl["pnl_usd"],
        "daily_pnl_pct":       daily_pnl["pnl_pct"],
        "open_positions":      open_positions,
        "max_per_trade":       max_per_trade,
    }

    # Log cycle start
    cycle_id = audit.log_cycle(
        portfolio_balance_usd=total_usd,
        available_cash_usd=cash_usd,
        open_positions_count=n_positions,
        daily_pnl_usd=daily_pnl["pnl_usd"],
        daily_pnl_pct=daily_pnl["pnl_pct"],
    )
    set_cycle_id(cycle_id)  # propagate to all @timed calls in this cycle

    # Build CycleContext — single source of truth for persona thresholds this cycle (S12.1.2)
    _btc_trend = ""
    ctx = CycleContext.from_config(
        config,
        cycle_id=str(cycle_id),
        open_positions=open_positions,
        btc_dominance_trend=_btc_trend,
    )
    risk.apply_persona_config(ctx.persona_config)
    logger.info(
        "[PERSONA] Active: %s | buy_min_score=%d | max_open=%d | max_pos=%.0f%% | floor=%.2f%%",
        ctx.persona, ctx.buy_min_score, ctx.max_open_positions,
        ctx.max_position_pct, ctx.min_profit_floor_pct,
    )

    # Persist active persona to agent_state for traceability and hot-reload detection (S12.1.3 AC1)
    if trading_db_path:
        try:
            from src.storage.database import get_connection
            _conn = get_connection(trading_db_path)
            _conn.execute(
                "INSERT OR REPLACE INTO agent_state (key, value) VALUES (?, ?)",
                ("active_persona", ctx.persona),
            )
            _conn.commit()
            _conn.close()
        except Exception as _pe:
            logger.warning("[PERSONA] Failed to persist active_persona to agent_state: %s", _pe)

    # Check daily loss limit
    trading_cfg     = config.get("trading", {})
    risk_cfg        = config.get("risk", {})
    
    # ── Global Kill Switch ─────────────────────────────────────
    global_max_daily_loss_pct = risk_cfg.get("global_max_daily_loss_pct", 7.0)
    if daily_pnl["pnl_pct"] <= -global_max_daily_loss_pct:
        open_pos = [p for p in open_positions if p.get("status", "open") == "open"]
        if open_pos:
            logger.critical("🚨 GLOBAL KILL SWITCH TRIGGERED: Drawdown %.2f%% exceeds %.2f%%. Panic selling all positions!", 
                            abs(daily_pnl["pnl_pct"]), global_max_daily_loss_pct)
            audit_logger = audit  # for local reference
            for pos in open_pos:
                try:
                    current_price = ws_feed.get_latest_price(pos["pair"])
                    # Emergency market sell
                    broker.close_position(
                        position_id=pos["id"],
                        current_price=current_price or 0.0,
                        exit_reason="global_kill_switch"
                    )
                    notifier.send_error_alert(
                        "kill_switch",
                        f"Emergency closed {pos['pair']} due to {abs(daily_pnl['pnl_pct']):.2f}% portfolio drawdown."
                    )
                except Exception as ex:
                    logger.error("Failed to panic sell %s: %s", pos["pair"], ex)
            
            # Recalculate daily_pnl after dumping
            balance_data = broker.get_balance()
            daily_pnl = broker.get_daily_pnl(start_of_day_balance)
            total_usd = balance_data["total_usd"]

        # Kill switch implies trading is done for the day
        logger.warning("Global Kill Switch is active. Halting all new trades.")
        today = datetime.now(timezone.utc).date()
        if loop_state is not None and loop_state.get("daily_loss_notified_date") != today:
            notifier.send_daily_loss_limit_reached(abs(daily_pnl["pnl_pct"]))
            loop_state["daily_loss_notified_date"] = today
        return {"buys": 0, "sells": len(open_pos)}

    daily_limit_pct = risk_cfg.get("daily_loss_limit_pct", 10)
    if (daily_pnl["pnl_usd"] < 0 and start_of_day_balance > 0 and
            abs(daily_pnl["pnl_usd"]) / start_of_day_balance * 100 >= daily_limit_pct):
        logger.warning("Daily loss limit reached. Skipping trade decisions this cycle.")
        today = datetime.now(timezone.utc).date()
        if loop_state is not None and loop_state.get("daily_loss_notified_date") != today:
            notifier.send_daily_loss_limit_reached(
                abs(daily_pnl["pnl_usd"]) / start_of_day_balance * 100
            )
            loop_state["daily_loss_notified_date"] = today
        return

    # Drawdown recovery mode state tracking (#182)
    recovery_cfg = risk_cfg.get("drawdown_recovery", {})
    if recovery_cfg.get("enabled", False) and loop_state is not None:
        was_in_recovery = loop_state.get("drawdown_recovery_active", False)
        trigger_pct = recovery_cfg.get("trigger_pct", 3.0)
        exit_pct    = recovery_cfg.get("exit_pct", 1.5)
        now_in_recovery = (
            daily_pnl["pnl_pct"] <= -trigger_pct
            or (was_in_recovery and daily_pnl["pnl_pct"] <= -exit_pct)
        )
        if now_in_recovery and not was_in_recovery:
            logger.warning(
                "[RECOVERY] Drawdown recovery mode activated — daily P&L %.1f%%",
                daily_pnl["pnl_pct"],
            )
            notifier.send_drawdown_recovery_entered(
                daily_pnl["pnl_pct"],
                recovery_cfg.get("allowed_pairs", ["BTC/USD", "ETH/USD", "BNB/USD"]),
            )
            loop_state["drawdown_recovery_active"] = True
        elif not now_in_recovery and was_in_recovery:
            logger.info(
                "[RECOVERY] Drawdown recovery mode lifted — daily P&L %.1f%%",
                daily_pnl["pnl_pct"],
            )
            notifier.send_drawdown_recovery_exited(daily_pnl["pnl_pct"])
            loop_state["drawdown_recovery_active"] = False

    # Fetch Fear & Greed, BTC dominance, and cycle-top indicators once per cycle.
    # Each function uses synchronous requests.get() internally. In live/paper mode,
    # offload all three to asyncio.to_thread() and run concurrently so a slow
    # CoinGecko or CoinGlass response on a cache-miss cycle cannot block the event
    # loop (which previously caused 13–20 s cycles and stalled the WebSocket feed).
    from src.analysis.features import (
        fetch_fear_greed,
        fetch_btc_dominance,
        fetch_cycle_top_indicators,
    )
    if is_backtest:
        fear_greed_data = fetch_fear_greed(config)
        btc_dom_data    = None
        cycle_top_data  = None
    else:
        fear_greed_data, btc_dom_data, cycle_top_data = await asyncio.gather(
            asyncio.to_thread(fetch_fear_greed, config),
            asyncio.to_thread(fetch_btc_dominance, config, trading_db_path),
            asyncio.to_thread(fetch_cycle_top_indicators, config, trading_db_path),
        )
    fear_greed_index = fear_greed_data["value"] if fear_greed_data else None
    cycle_top_active = bool(cycle_top_data and cycle_top_data.get("cycle_top_active"))
    risk.set_cycle_top_state(cycle_top_active, cycle_top_data)

    if loop_state is not None and cycle_top_data is not None:
        was_cycle_top_active = loop_state.get("cycle_top_guard_active", False)
        if cycle_top_active and not was_cycle_top_active:
            notifier.send_cycle_top_guard_activated(
                cycle_top_data.get("mvrv_z_score", 0.0),
                cycle_top_data.get("nupl", 0.0),
            )
        elif was_cycle_top_active and not cycle_top_active:
            notifier.send_cycle_top_guard_deactivated(
                cycle_top_data.get("mvrv_z_score", 0.0),
                cycle_top_data.get("nupl", 0.0),
            )
        loop_state["cycle_top_guard_active"] = cycle_top_active

    # Compute indicators and signals for each pair
    signals = []
    for pair in pairs:
        candles = ws_feed.get_candles(pair)
        if not candles:
            logger.warning("No candles for %s — skipping", pair)
            continue

        indicators = compute_indicators(candles, config)
        if not indicators:
            logger.warning("Insufficient candles for %s indicators — skipping", pair)
            continue

        # S13.2.2 — Track per-pair OHLCV freeze and alert once per episode
        if loop_state is not None and not is_backtest:
            feed_status = indicators.get("feed_status", "OK")
            fh_cfg = config.get("qsa", {}).get("feed_heartbeat", {})
            freeze_alert_cycles = int(fh_cfg.get("freeze_alert_cycles", 3))
            if feed_status == "FROZEN":
                loop_state["freeze_cycle_count"][pair] = (
                    loop_state["freeze_cycle_count"].get(pair, 0) + 1
                )
                n_frozen = loop_state["freeze_cycle_count"][pair]
                if n_frozen >= freeze_alert_cycles and not loop_state["freeze_alert_sent"].get(pair, False):
                    notifier.send_feed_frozen_alert(pair, n_frozen)
                    loop_state["freeze_alert_sent"][pair] = True
                    logger.warning("[QSA] Feed frozen alert sent for %s (%d cycles)", pair, n_frozen)
                # S13.2.3 — BTC/USD failover price for regime context
                if pair == "BTC/USD":
                    from src.analysis.features import fetch_btc_spot_price as _fetch_btc_spot
                    btc_spot = _fetch_btc_spot(config)
                    if btc_spot:
                        indicators["btc_failover_price"] = btc_spot
            else:
                # Feed recovered — reset episode state
                if loop_state["freeze_cycle_count"].get(pair, 0) > 0:
                    logger.info("[QSA] Feed recovered for %s", pair)
                loop_state["freeze_cycle_count"][pair] = 0
                loop_state["freeze_alert_sent"][pair] = False

        # Inject sentiment so generate_signal() can score it
        if fear_greed_index is not None:
            indicators["fear_greed_index"] = fear_greed_index

        # Inject adaptive ATR floor — rolling p25 ATR% per pair (Fix #108)
        atr_floor_cfg = config.get("adaptive_atr_floor", {})
        if atr_floor_cfg.get("enabled", False):
            pair_entry = next(
                (p for p in config.get("trading", {}).get("pairs", []) if p.get("pair") == pair),
                {}
            )
            lookback       = pair_entry.get("adaptive_atr_floor_lookback",
                                            atr_floor_cfg.get("lookback_candles", 400))
            scaling_factor = atr_floor_cfg.get("scaling_factor", 0.8)
            min_cap        = atr_floor_cfg.get("min_cap_pct", 0.10)
            recent         = candles[-lookback:] if len(candles) >= lookback else candles
            atr_pct_vals   = [
                (c["high"] - c["low"]) / c["close"] * 100
                for c in recent
                if c.get("close", 0) > 0
            ]
            if atr_pct_vals:
                atr_pct_vals_sorted = sorted(atr_pct_vals)
                p25_idx  = max(0, int(len(atr_pct_vals_sorted) * 0.25) - 1)
                p25_atr  = atr_pct_vals_sorted[p25_idx]
                adaptive_floor = max(p25_atr * scaling_factor, min_cap)
                indicators["adaptive_atr_floor_pct"] = round(adaptive_floor, 4)
                logger.debug(
                    "[ADAPTIVE_ATR] %s: lookback=%d p25_atr%%=%.4f → floor=%.4f%%",
                    pair, lookback, p25_atr, adaptive_floor,
                )

        # Inject adaptive BB squeeze threshold — rolling p10 BB width% (Fix #113)
        bb_squeeze_cfg = config.get("adaptive_bb_squeeze", {})
        if bb_squeeze_cfg.get("enabled", False):
            lookback_bb   = bb_squeeze_cfg.get("lookback_candles", 400)
            pct_bb        = bb_squeeze_cfg.get("percentile", 10)
            recent_bb     = candles[-lookback_bb:] if len(candles) >= lookback_bb else candles
            bb_width_vals = [
                (c["high"] - c["low"]) / ((c["high"] + c["low"]) / 2) * 100
                for c in recent_bb
                if c.get("high", 0) > 0 and c.get("low", 0) > 0
            ]
            if bb_width_vals:
                bb_width_vals_sorted = sorted(bb_width_vals)
                p10_idx = max(0, int(len(bb_width_vals_sorted) * pct_bb / 100) - 1)
                indicators["_rolling_bb_p10_pct"] = round(bb_width_vals_sorted[p10_idx], 4)
                logger.debug(
                    "[ADAPTIVE_BB] %s: lookback=%d p10_bb_width%%=%.4f%%",
                    pair, lookback_bb, indicators["_rolling_bb_p10_pct"],
                )

        # Inject adaptive volume floor — rolling p15 raw volume (Fix #114)
        vol_floor_cfg = config.get("adaptive_volume_floor", {})
        if vol_floor_cfg.get("enabled", False):
            lookback_vol   = vol_floor_cfg.get("lookback_candles", 400)
            pct_vol        = vol_floor_cfg.get("percentile", 15)
            recent_vol     = candles[-lookback_vol:] if len(candles) >= lookback_vol else candles
            vol_vals       = [c["volume"] for c in recent_vol if c.get("volume", 0) > 0]
            if vol_vals:
                vol_vals_sorted = sorted(vol_vals)
                p15_idx = max(0, int(len(vol_vals_sorted) * pct_vol / 100) - 1)
                indicators["rolling_volume_p15"] = vol_vals_sorted[p15_idx]
                logger.debug(
                    "[ADAPTIVE_VOL] %s: lookback=%d p15_volume=%.2f",
                    pair, lookback_vol, indicators["rolling_volume_p15"],
                )

        # Inject profit factor — rolling 30-day trade history per pair (#183)
        pf_cfg = config.get("signals", {}).get("profit_factor_escalation", {})
        if pf_cfg.get("enabled", True):
            try:
                from src.analysis.features import compute_profit_factor
                from src.storage.database import get_connection
                from datetime import timezone as _tz
                _pf_days     = pf_cfg.get("lookback_days", 30)
                _min_trades  = pf_cfg.get("min_trades", 10)
                _pf_db_path  = config.get("storage", {}).get(
                    "paper_db" if mode == "paper" else "live_db",
                    "paper_trading.db" if mode == "paper" else "live_trading.db",
                )
                _trades_tbl  = "paper_trades" if mode == "paper" else "live_trades"
                _since       = (datetime.now(_tz.utc) - timedelta(days=_pf_days)).isoformat()
                _conn        = get_connection(_pf_db_path)
                _rows        = _conn.execute(
                    f"SELECT pnl_usd FROM {_trades_tbl} "
                    f"WHERE pair=? AND closed_at>=? AND pnl_usd IS NOT NULL",
                    (pair, _since),
                ).fetchall()
                _conn.close()
                _pf_trades = [{"pnl_usd": float(r["pnl_usd"])} for r in _rows]
                if len(_pf_trades) >= _min_trades:
                    pf_value = compute_profit_factor(pair, _pf_trades)
                    if pf_value is not None:
                        indicators["profit_factor"] = pf_value
                        logger.debug("[PF] %s: profit_factor=%.2f (n=%d)", pair, pf_value, len(_pf_trades))
            except Exception as _pf_err:
                logger.debug("[PF] %s: skipped — %s", pair, _pf_err)

        # S13.3.1 — Inject volume bypass flag from active persona config
        _active_persona = config.get("agent", {}).get("persona", "medium")
        _persona_vol_cfg = config.get("personas", {}).get(_active_persona, {})
        indicators["volume_bypass_enabled"] = _persona_vol_cfg.get("volume_bypass_enabled", True)

        sig = generate_signal(pair, indicators, config)
        sig["indicators"] = indicators  # attach raw indicators for prompt

        signals.append(sig)

    if not signals:
        logger.warning("No signals computed this cycle")
        return

    # Build AI context (regime, sentiment, patterns, exit timing, sizing, dynamic TP)
    from src.analysis.features import build_ai_context, compute_pair_regime_caps, apply_cycle_top_guard
    ai_context = build_ai_context(
        signals=signals,
        portfolio=portfolio,
        open_positions=open_positions,
        config=config,
        btc_dominance=btc_dom_data,
        cycle_top_data=cycle_top_data,
    )

    # Apply regime caution factor to max_per_trade (#124)
    regime_data    = ai_context.get("regime_data", {})
    regime         = regime_data.get("regime", "unknown")
    global_caution = regime_data.get("caution_factor", 1.0)
    trading_pairs_cfg = config.get("trading", {}).get("pairs", [])

    pair_caps = compute_pair_regime_caps(
        signals=signals,
        portfolio_max_per_trade=portfolio["max_per_trade"],
        regime_data=regime_data,
        config=config,
    )

    for sig in signals:
        cap_data = pair_caps.get(sig["pair"], {})
        sig["pair_tier"] = cap_data.get("pair_tier", 0)

    if regime == "bearish":
        # Per-pair caution_factor_bearish: inject pair_max_usd into each signal.
        # Winners (ETH/BNB/DOGE) keep caution=1.0 (buy the dip);
        # underperformers get cut harder. Global 0.5 is the fallback.
        base_max = portfolio["max_per_trade"]
        for sig in signals:
            cap_data = pair_caps.get(sig["pair"], {})
            sig["pair_max_usd"] = cap_data.get("pair_max_usd")
            logger.info(
                "[REGIME] bearish — %s tier=%s caution=%.2f dom_mult=%.2f pair_max=$%.2f",
                sig["pair"],
                cap_data.get("pair_tier", 0),
                cap_data.get("pair_caution", global_caution),
                cap_data.get("dominance_multiplier", 1.0),
                sig["pair_max_usd"],
            )
        # Set global max to the fallback-caution ceiling for the prompt header
        portfolio["max_per_trade"] = round(base_max * global_caution, 2)
    elif global_caution < 1.0:
        # Non-bearish regime (e.g. volatile) — apply global caution uniformly
        original_max = portfolio["max_per_trade"]
        portfolio["max_per_trade"] = round(original_max * global_caution, 2)
        logger.info(
            "[REGIME] %s regime — caution_factor=%.2f, max_per_trade scaled $%.2f → $%.2f",
            regime, global_caution, original_max, portfolio["max_per_trade"],
        )

    suppressed_buys = apply_cycle_top_guard(signals, config, cycle_top_data)
    if suppressed_buys:
        logger.warning(
            "[CYCLE_TOP] Suppressed %d Tier 3/4 BUY signals due to macro cycle-top guard",
            suppressed_buys,
        )

    for sig in signals:
        audit.log_signal(
            cycle_id=cycle_id,
            pair=sig["pair"],
            price=sig.get("price", sig.get("indicators", {}).get("close", 0.0)),
            indicators=sig.get("indicators", {}),
            signal_direction=sig["signal"],
            signal_strength=sig["strength"],
            signal_reasons=sig["reasons"],
        )
        logger.info(
            "Signal [%s]: %s (strength=%.2f) @ $%.4f",
            sig["pair"], sig["signal"], sig["strength"], sig["price"],
        )

    # Run LLM agent
    # Patch btc_dominance_trend into ctx now that macro data is available
    if btc_dom_data:
        ctx = CycleContext.from_config(
            config,
            cycle_id=str(cycle_id),
            open_positions=open_positions,
            btc_dominance_trend=btc_dom_data.get("trend", ""),
        )
        risk.apply_persona_config(ctx.persona_config)

    # S14.2.3 — inject unfilled correlation clusters so the LLM avoids doubling into saturated sectors
    _clusters_cfg = config.get("risk", {}).get("correlation_clusters", [])
    _max_cluster_pos = config.get("risk", {}).get("max_cluster_positions", 2)
    _open_pairs_set = {p["pair"] for p in open_positions}
    ai_context["unfilled_clusters"] = [
        c["name"]
        for c in _clusters_cfg
        if sum(1 for _p in c.get("pairs", []) if _p in _open_pairs_set) < _max_cluster_pos
    ]

    results = agent.run_cycle(
        cycle_id=cycle_id,
        portfolio=portfolio,
        signals=signals,
        ai_context=ai_context,
        cycle_context=ctx,
    )

    buys = sells = 0
    for r in results:
        logger.info("Agent result [%s]: %s", r["pair"], r["result"])
        action = r.get("result", "")
        if "BUY" in action or "buy" in action.lower():
            buys += 1
        elif "SELL" in action or "sell" in action.lower():
            sells += 1

    # Write human-readable decision trace (skipped in backtest)
    if not is_backtest:
        from src.utils.cycle_logger import write_cycle_report
        cycle_duration_ms_pre = int(time.time() * 1000) - cycle_start_ms
        write_cycle_report(
            config=config,
            cycle_id=cycle_id,
            portfolio=portfolio,
            signals=signals,
            ai_context=ai_context,
            results=results,
            duration_ms=cycle_duration_ms_pre,
        )

    # Audit balance snapshot — re-fetch to capture any trades that executed this cycle
    post_balance = broker.get_balance()
    audit.log_balance_snapshot(
        total_usd=post_balance["total_usd"],
        cash_usd=post_balance["available_cash_usd"],
        holdings=post_balance.get("holdings", {}),
        unrealised_pnl_usd=0.0,
    )

    # Update cycle duration
    cycle_duration_ms = int(time.time() * 1000) - cycle_start_ms
    audit.update_cycle_duration(cycle_id, cycle_duration_ms)

    return {"buys": buys, "sells": sells}


def main() -> None:
    load_dotenv()

    parser = argparse.ArgumentParser(description="Crypto Trading AI Agent")
    group  = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--paper", action="store_true", help="Run in paper trading mode (no real orders)")
    group.add_argument("--live",  action="store_true", help="Run in live trading mode (real money)")
    parser.add_argument("--config", default="config.yaml", help="Path to config file")
    args = parser.parse_args()

    mode       = "paper" if args.paper else "live"
    config     = load_config(args.config)
    session_id = str(uuid.uuid4())

    setup_logging(config, session_id=session_id)

    from src.utils.timing import set_session_id
    from src.utils.llm_logger import init_llm_logger
    from src.utils.cycle_logger import init_cycle_logger
    set_session_id(session_id)
    log_dir = config.get("storage", {}).get("log_dir", "/logs")
    init_llm_logger(log_dir=log_dir, config=config)
    init_cycle_logger(log_dir=log_dir, config=config)

    logger.info("[SESSION] Agent session started — id=%s mode=%s", session_id, mode)

    asyncio.run(run_agent(config, mode, session_id=session_id))


if __name__ == "__main__":
    main()
