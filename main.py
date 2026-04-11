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
from datetime import datetime, timezone, timedelta

import yaml
from dotenv import load_dotenv

logger = logging.getLogger("main")


def load_config(path: str = "config.yaml") -> dict:
    with open(path, "r") as f:
        return yaml.safe_load(f)


def setup_logging(config: dict) -> None:
    storage_cfg  = config.get("storage", {})
    max_bytes    = storage_cfg.get("log_max_bytes", 100 * 1024 * 1024)
    backup_count = storage_cfg.get("log_backup_count", 4)
    llm_debug    = storage_cfg.get("llm_debug_logging", False)
    os.makedirs("logs", exist_ok=True)

    fmt = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"

    # File handler — DEBUG when llm_debug_logging enabled, else INFO
    file_handler = logging.handlers.RotatingFileHandler(
        "logs/agent.log", maxBytes=max_bytes, backupCount=backup_count,
    )
    file_handler.setLevel(logging.DEBUG if llm_debug else logging.INFO)
    file_handler.setFormatter(logging.Formatter(fmt))

    # Console handler — always INFO (avoid flooding terminal with prompts)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(logging.Formatter(fmt))

    root = logging.getLogger()
    root.setLevel(logging.DEBUG if llm_debug else logging.INFO)
    root.addHandler(file_handler)
    root.addHandler(console_handler)


def _get_or_set_sod_balance(db_path: str, current_balance: float) -> float:
    """
    Return today's start-of-day balance from agent_state DB.
    Works for both paper (paper_trading.db) and live (live_trading.db) modes.

    Key: start_of_day_balance_YYYY-MM-DD (UTC date).
    - If the key exists for today → return it (stable across cycles).
    - If absent (new day or DB was reset) → store current_balance and return it.

    This makes the daily P&L baseline self-healing: a reset_paper.py run while
    the agent is alive will clear agent_state, so the next cycle writes a fresh
    $1,000 baseline instead of using the stale in-memory value.
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
            return float(row["value"])
        # New day or post-reset — write and return current balance
        conn.execute(
            "INSERT OR REPLACE INTO agent_state (key, value) VALUES (?, ?)",
            (today_key, str(current_balance)),
        )
        conn.commit()
        conn.close()
        logger.info("[SOD] Wrote start-of-day balance $%.2f to agent_state (key=%s)",
                    current_balance, today_key)
    except Exception as exc:
        logger.warning("[SOD] Could not persist start-of-day balance: %s — falling back to current", exc)
    return current_balance


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


async def run_agent(config: dict, mode: str, feed=None) -> None:
    """
    feed : optional HistoricalFeed for back-testing.
           When provided, the live WebSocket is not started and the main loop
           steps through candles via feed.advance() instead of sleeping.
    """
    from src.storage.database import init_all_databases
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
    _trading_db = storage_cfg.get("paper_db" if mode == "paper" else "live_db", "paper_trading.db")
    risk        = RiskManager(config, db_path=_trading_db)
    notifier    = Notifier(config, mode)

    trading_cfg = config.get("trading", {})
    pairs       = [p["pair"] for p in trading_cfg.get("pairs", [])]
    interval_s  = trading_cfg.get("cycle_interval_minutes", 15) * 60

    # ── Broker setup ───────────────────────────────────────────
    if mode == "paper":
        from src.exchange.paper_broker import PaperBroker
        paper_cfg   = config.get("paper", {})
        slippage    = paper_cfg.get("slippage_pct", 0.05)
        maker_fee   = paper_cfg.get("maker_fee_pct", 0.26)
        paper_db    = storage_cfg.get("paper_db", "paper_trading.db")
        broker      = PaperBroker(paper_db=paper_db, slippage_pct=slippage, maker_fee_pct=maker_fee, config=config)
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
                start_of_day_bal = _get_or_set_sod_balance(sod_db_path, current_bal_for_sod)

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
                notifier.send_heartbeat({
                    "balance_usd":          bal["total_usd"],
                    "hourly_pnl_usd":       round(hourly_pnl_usd, 2),
                    "hourly_pnl_pct":       round(hourly_pnl_pct, 2),
                    "cycles_completed":     loop_state["cycles_since_heartbeat"],
                    "open_positions":       len([p for p in open_pos if p.get("status") == "open"]),
                    "buys_last_hour":       loop_state["buys_since_heartbeat"],
                    "sells_last_hour":      loop_state["sells_since_heartbeat"],
                    "circuit_breaker_active": cb_active,
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

    # Fetch Fear & Greed once per cycle — injected into each pair's indicators dict
    from src.analysis.features import (
        fetch_fear_greed,
        fetch_btc_dominance,
        fetch_cycle_top_indicators,
    )
    fear_greed_data = fetch_fear_greed(config)
    fear_greed_index = fear_greed_data["value"] if fear_greed_data else None

    # Fetch BTC dominance trend once per cycle (#206)
    btc_dom_data = fetch_btc_dominance(config, db_path=trading_db_path) if not is_backtest else None
    cycle_top_data = fetch_cycle_top_indicators(config, db_path=trading_db_path) if not is_backtest else None
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
    results = agent.run_cycle(
        cycle_id=cycle_id,
        portfolio=portfolio,
        signals=signals,
        ai_context=ai_context,
    )

    buys = sells = 0
    for r in results:
        logger.info("Agent result [%s]: %s", r["pair"], r["result"])
        action = r.get("result", "")
        if "BUY" in action or "buy" in action.lower():
            buys += 1
        elif "SELL" in action or "sell" in action.lower():
            sells += 1

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

    mode   = "paper" if args.paper else "live"
    config = load_config(args.config)
    setup_logging(config)

    asyncio.run(run_agent(config, mode))


if __name__ == "__main__":
    main()
