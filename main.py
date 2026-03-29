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
from datetime import datetime, timezone

import yaml
from dotenv import load_dotenv

logger = logging.getLogger("main")


def load_config(path: str = "config.yaml") -> dict:
    with open(path, "r") as f:
        return yaml.safe_load(f)


def setup_logging(config: dict) -> None:
    storage_cfg = config.get("storage", {})
    max_bytes   = storage_cfg.get("log_max_bytes", 100 * 1024 * 1024)
    backup_count= storage_cfg.get("log_backup_count", 4)
    os.makedirs("logs", exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.handlers.RotatingFileHandler(
                "logs/agent.log",
                maxBytes=max_bytes,
                backupCount=backup_count,
            ),
        ],
    )


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


async def run_agent(config: dict, mode: str) -> None:
    from src.storage.database import init_all_databases
    from src.storage.audit_logger import AuditLogger
    from src.exchange.websocket_feed import WebSocketFeed
    from src.analysis.indicators import compute_indicators
    from src.analysis.signals import generate_signal
    from src.risk.risk_manager import RiskManager, validate_config
    from src.notifications.notifier import Notifier
    from src.agent.tools import TradingTools
    from src.agent.trading_agent import TradingAgent

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

    ws_feed     = WebSocketFeed(config)
    risk        = RiskManager(config)
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
        broker      = PaperBroker(paper_db=paper_db, slippage_pct=slippage, maker_fee_pct=maker_fee)
    else:
        from src.exchange.kraken_client import KrakenClient
        api_key    = os.getenv("KRAKEN_API_KEY")
        api_secret = os.getenv("KRAKEN_API_SECRET")
        if not api_key or not api_secret:
            logger.error("KRAKEN_API_KEY and KRAKEN_API_SECRET required for live mode")
            sys.exit(1)
        broker = KrakenClient(api_key=api_key, api_secret=api_secret)

    # ── Get starting balance ───────────────────────────────────
    balance_data       = broker.get_balance()
    start_of_day_bal   = balance_data["total_usd"]

    # ── Print startup banner ───────────────────────────────────
    print_banner(mode, start_of_day_bal, pairs)

    tools = TradingTools(
        broker=broker,
        risk_manager=risk,
        audit_logger=audit,
        notifier=notifier,
        ws_feed=ws_feed,
        mode=mode,
        config=config,
        start_of_day_balance=start_of_day_bal,
    )

    agent = TradingAgent(
        tools=tools,
        config=config,
        mode=mode,
        audit_logger=audit,
    )

    notifier.send_agent_started(start_of_day_bal, pairs, mode)

    # ── Start WebSocket feed ───────────────────────────────────
    logger.info("Starting WebSocket price feed...")
    await ws_feed.start()

    ind_cfg_startup  = config.get("indicators", {})
    min_candles      = ind_cfg_startup.get("min_candles_to_start", 220)
    buf_timeout      = ind_cfg_startup.get("buffer_fill_timeout_secs", 300)
    buf_check        = ind_cfg_startup.get("buffer_check_interval_secs", 5)

    logger.info("Waiting for candle buffer to fill (min %d candles per pair)...", min_candles)
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
    try:
        while True:
            cycle_start = time.time()

            try:
                await run_cycle(
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
                )
            except Exception as e:
                tb = traceback.format_exc()
                logger.error("Cycle error: %s\n%s", e, tb)
                audit.log_error("main_loop", type(e).__name__, str(e), tb, recovered=True)
                notifier.send_error_alert("main_loop", str(e)[:200])

            # Also check stop/TP on each pair after cycle (paper mode)
            if mode == "paper":
                from src.exchange.paper_broker import PaperBroker
                for pair in pairs:
                    current_price = ws_feed.get_latest_price(pair)
                    if current_price:
                        closed = broker.check_stops_and_tp(pair, current_price, audit)
                        for trade in closed:
                            notifier.send_trade_executed(trade, mode)

            elapsed   = time.time() - cycle_start
            sleep_for = max(0, interval_s - elapsed)
            logger.info(
                "Cycle complete in %.1fs. Next cycle in %.0fs.",
                elapsed, sleep_for,
            )
            await asyncio.sleep(sleep_for)

    except asyncio.CancelledError:
        pass
    except KeyboardInterrupt:
        logger.info("Shutdown requested")
    finally:
        logger.info("Stopping WebSocket feed...")
        await ws_feed.stop()
        logger.info("Agent stopped cleanly")


async def run_cycle(
    broker, agent, ws_feed, audit, notifier, risk, config,
    pairs, mode, start_of_day_balance
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
    max_per_trade   = total_usd * (config.get("trading", {}).get("max_position_pct", 30) / 100)

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
    daily_limit_pct = risk_cfg.get("daily_loss_limit_pct", 10)
    if (daily_pnl["pnl_usd"] < 0 and start_of_day_balance > 0 and
            abs(daily_pnl["pnl_usd"]) / start_of_day_balance * 100 >= daily_limit_pct):
        logger.warning("Daily loss limit reached. Skipping trade decisions this cycle.")
        notifier.send_daily_loss_limit_reached(
            abs(daily_pnl["pnl_usd"]) / start_of_day_balance * 100
        )
        return

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

        sig = generate_signal(pair, indicators, config)
        sig["indicators"] = indicators  # attach raw indicators for prompt

        # Audit signal
        audit.log_signal(
            cycle_id=cycle_id,
            pair=pair,
            price=indicators.get("close", 0.0),
            indicators=indicators,
            signal_direction=sig["signal"],
            signal_strength=sig["strength"],
            signal_reasons=sig["reasons"],
        )

        signals.append(sig)
        logger.info(
            "Signal [%s]: %s (strength=%.2f) @ $%.4f",
            pair, sig["signal"], sig["strength"], sig["price"],
        )

    if not signals:
        logger.warning("No signals computed this cycle")
        return

    # Run LLM agent
    results = agent.run_cycle(
        cycle_id=cycle_id,
        portfolio=portfolio,
        signals=signals,
    )

    for r in results:
        logger.info("Agent result [%s]: %s", r["pair"], r["result"])

    # Audit balance snapshot
    audit.log_balance_snapshot(
        total_usd=total_usd,
        cash_usd=cash_usd,
        holdings=balance_data.get("holdings", {}),
        unrealised_pnl_usd=0.0,
    )

    # Update cycle duration
    cycle_duration_ms = int(time.time() * 1000) - cycle_start_ms
    audit.update_cycle_duration(cycle_id, cycle_duration_ms)


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
