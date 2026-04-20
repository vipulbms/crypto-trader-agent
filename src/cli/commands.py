"""
commands.py — Executes parsed intents for the Kryptos CLI.

Each cmd_* function receives an intent dict produced by NLParser.parse()
and calls the appropriate report queries + display functions.
"""

import logging
import os
from typing import Optional

from src.cli import agent_manager as am
from src.cli import display as d
from src.reports import trade_report as rpt

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────
# Agent lifecycle
# ──────────────────────────────────────────────────────────────

def cmd_start(params: dict) -> None:
    mode = params.get("mode", "paper")
    d.print_info(f"Starting agent in [bold]{mode.upper()}[/bold] mode …")
    result = am.start(mode)
    if result["ok"]:
        d.print_ok(result["message"])
        d.print_info(f"Logs → {result.get('log_file', 'agent.log')}")
    else:
        d.print_error(result["message"])


def cmd_stop(_params: dict) -> None:
    d.print_info("Sending stop signal to agent …")
    result = am.stop()
    if result["ok"]:
        d.print_ok(result["message"])
    else:
        d.print_error(result["message"])


def cmd_status(params: dict, config: Optional[dict] = None) -> None:
    data = am.status(config)
    d.print_agent_status(data)


def cmd_next_schedule(_params: dict, config: Optional[dict] = None) -> None:
    data = am.get_next_schedule(config)
    d.print_next_schedule(data)


# ──────────────────────────────────────────────────────────────
# Reports
# ──────────────────────────────────────────────────────────────

def cmd_view_report(params: dict, config: Optional[dict] = None) -> None:
    if config is None:
        d.print_error("No config loaded — cannot query databases.")
        return

    mode   = params.get("mode", "paper")
    days   = params.get("days") or 30
    pair   = params.get("pair")
    limit  = params.get("count") or 50
    detail = params.get("detail", "summary")

    # Portfolio summary first
    portfolio = rpt.get_portfolio_summary(mode, config)
    if portfolio:
        d.print_portfolio_summary(portfolio)
        pf_data = rpt.get_profit_factors(mode, config)
        if pf_data:
            d.print_profit_factor_table(pf_data)

    # Trades
    trades = rpt.get_trades_with_decisions(mode, config, days=days, pair=pair, limit=limit)
    show_llm = (detail == "detailed")
    d.print_trades_table(trades, show_llm=show_llm)

    # Summary metrics
    metrics = rpt.get_performance_metrics(mode, config, days=days)
    if metrics and metrics.get("total_trades", 0) > 0:
        d.print_performance_metrics(metrics)


def cmd_trade_details(params: dict, config: Optional[dict] = None) -> None:
    if config is None:
        d.print_error("No config loaded.")
        return

    mode  = params.get("mode", "paper")
    pair  = params.get("pair")
    days  = params.get("days") or 7
    count = params.get("count") or 5

    trades = rpt.get_trades_with_decisions(mode, config, days=days, pair=pair, limit=count)

    if not trades:
        d.print_warn("No closed trades found for those filters.")
        return

    for trade in trades:
        d.print_trade_detail(trade)


def cmd_llm_decisions(params: dict, config: Optional[dict] = None) -> None:
    if config is None:
        d.print_error("No config loaded.")
        return

    mode     = params.get("mode", "paper")
    pair     = params.get("pair")
    days     = params.get("days") or 7
    limit    = params.get("count") or 20
    dtype    = params.get("decision_type")
    detail   = params.get("detail", "summary")

    decisions = rpt.get_llm_decision_detail(
        mode, config, pair=pair, decision_type=dtype, days=days, limit=limit
    )

    if detail == "detailed":
        for dec in decisions:
            d.print_llm_decision(dec, compact=False)
    else:
        d.print_llm_decisions_table(decisions)

    # Append patterns summary
    patterns = rpt.get_llm_decision_patterns(mode, config, days=days)
    if patterns:
        d.print_llm_patterns(patterns)


def cmd_win_rate(params: dict, config: Optional[dict] = None) -> None:
    if config is None:
        d.print_error("No config loaded.")
        return
    mode = params.get("mode", "paper")
    days = params.get("days") or 14
    metrics = rpt.get_performance_metrics(mode, config, days=days)
    d.print_performance_metrics(metrics)


def cmd_daily_summary(params: dict, config: Optional[dict] = None) -> None:
    if config is None:
        d.print_error("No config loaded.")
        return
    mode = params.get("mode", "paper")
    date = params.get("date")  # None == today
    data = rpt.get_daily_summary(mode, config, date_str=date)
    d.print_daily_summary(data)


def cmd_daily_report(params: dict, config: Optional[dict] = None) -> None:
    """Run the full daily P&L report (from src/reports/daily_report.py)."""
    if config is None:
        d.print_error("No config loaded.")
        return
    from src.reports.daily_report import run_daily_report
    mode      = params.get("mode", "paper")
    days_ago  = params.get("days_ago") or 0
    run_daily_report(mode, days_ago, config)
    if params.get("charts"):
        cmd_charts(params, config)


def cmd_review(params: dict, config: Optional[dict] = None) -> None:
    """Run the N-day performance review with live-trading readiness verdict."""
    if config is None:
        d.print_error("No config loaded.")
        return
    from src.reports.review_report import run_review
    mode = params.get("mode", "paper")
    days = params.get("days") or 14
    run_review(mode, days, config)
    if params.get("charts"):
        cmd_charts(params, config)


def cmd_charts(params: dict, config: Optional[dict] = None) -> None:
    """Generate candlestick charts for all closed trades."""
    if config is None:
        d.print_error("No config loaded.")
        return
    from src.reports.chart_generator import generate_charts
    mode    = params.get("mode", "paper")
    storage = (config or {}).get("storage", {})
    if mode == "live":
        db_path = storage.get("live_db", "live_trading.db")
    else:
        db_path = storage.get("paper_db", "paper_trading.db")
    out_dir     = params.get("out") or "charts"
    pair_filter = params.get("pair")
    window      = params.get("window") or 80
    try:
        paths = generate_charts(
            db_path=db_path,
            out_dir=out_dir,
            pair_filter=pair_filter,
            window=window,
        )
        if paths:
            d.print_ok(f"{len(paths)} chart(s) saved to {out_dir}/")
        else:
            d.print_warn("No closed trades found — no charts generated.")
    except FileNotFoundError as exc:
        d.print_error(str(exc))


def cmd_open_positions(params: dict, config: Optional[dict] = None) -> None:
    if config is None:
        d.print_error("No config loaded.")
        return
    mode     = params.get("mode", "paper")
    portfolio = rpt.get_portfolio_summary(mode, config)
    d.print_portfolio_summary(portfolio)


def cmd_signal_drivers(params: dict, config: Optional[dict] = None) -> None:
    """Show which parameters are most frequently blocking or driving BUY signals (Fix #117)."""
    if config is None:
        d.print_error("No config loaded.")
        return
    days  = int(params.get("days", 30))
    top_n = int(params.get("top_n", 10))
    data  = rpt.get_signal_driver_report(config, days=days, top_n=top_n)
    d.print_signal_driver_report(data)


def cmd_tail_log(params: dict) -> None:
    lines_count = params.get("lines") or 30
    lines = am.tail_log(lines_count)
    d.print_log_tail(lines)


def cmd_help(_params: dict) -> None:
    d.print_help()


# ──────────────────────────────────────────────────────────────
# Persona commands (S18.1.1)
# ──────────────────────────────────────────────────────────────

def cmd_persona(params: dict, config: Optional[dict] = None) -> None:
    """Show active persona and all persona parameter summaries."""
    if config is None:
        d.print_error("No config loaded.")
        return
    d.print_persona_summary(config)


def cmd_persona_set(params: dict, config: Optional[dict] = None) -> None:
    """Set the active persona in config.yaml — takes effect next cycle.

    S18.1.1 AC2: writes 'agent.persona' in config.yaml
    S18.1.1 AC3: warns that the change takes effect next cycle
    S18.1.1 AC4: logged via CLI audit (caller writes the audit line)
    """
    if config is None:
        d.print_error("No config loaded.")
        return
    target = params.get("persona", "").strip().lower()
    valid = {"conservative", "medium", "high"}
    if target not in valid:
        d.print_error(
            f"Invalid persona '{target}'. "
            f"Choose from: {', '.join(sorted(valid))}"
        )
        return

    import yaml
    import os
    config_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "config.yaml"
    )
    try:
        with open(config_path) as fh:
            raw = yaml.safe_load(fh)
        if "agent" not in raw:
            raw["agent"] = {}
        raw["agent"]["persona"] = target
        with open(config_path, "w") as fh:
            yaml.dump(raw, fh, default_flow_style=False, allow_unicode=True)
        config["agent"]["persona"] = target
        d.print_ok(
            f"Persona set to [bold]{target}[/bold]. "
            "Takes effect on the next trading cycle."
        )
        d.print_warn("If the agent is running, it will pick up the new persona at cycle start.")
    except Exception as exc:
        d.print_error(f"Failed to update config.yaml: {exc}")
        logger.exception("cmd_persona_set error")


# ──────────────────────────────────────────────────────────────
# Regime command (S18.1.2)
# ──────────────────────────────────────────────────────────────

def cmd_regime(params: dict, config: Optional[dict] = None) -> None:
    """Show current detected regime and active playbook from agent_state.

    S18.1.2 AC1: persona, playbook, regime, ADX median, BTC dominance trend,
                 daily PnL, velocity circuit state
    S18.1.2 AC2: data from agent_state table
    S18.1.2 AC3: colour-coded: ranging=yellow, momentum=green, risk_off=red
    """
    if config is None:
        d.print_error("No config loaded.")
        return
    from src.storage.database import get_connection_ro, resolve_trading_db
    mode     = params.get("mode", "paper")
    db_path  = resolve_trading_db(config, mode)
    try:
        conn  = get_connection_ro(db_path)
        rows  = conn.execute("SELECT key, value FROM agent_state").fetchall()
        conn.close()
        state = {r["key"]: r["value"] for r in rows}
    except Exception as exc:
        d.print_error(f"Could not read agent_state: {exc}")
        return
    d.print_regime_state(state, config)


# ──────────────────────────────────────────────────────────────
# Intent dispatcher
# ──────────────────────────────────────────────────────────────

def dispatch(intent_obj: dict, config: Optional[dict] = None) -> bool:
    """
    Dispatch a parsed intent dict to the correct command function.
    Returns False if intent is 'exit', True otherwise.
    """
    intent = intent_obj.get("intent", "help")
    params = intent_obj.get("params", {})

    if intent == "exit":
        d.print_info("Goodbye from Kryptos.")
        return False

    dispatch_map = {
        "start_agent":    lambda: cmd_start(params),
        "stop_agent":     lambda: cmd_stop(params),
        "agent_status":   lambda: cmd_status(params, config),
        "next_schedule":  lambda: cmd_next_schedule(params, config),
        "view_report":    lambda: cmd_view_report(params, config),
        "trade_details":  lambda: cmd_trade_details(params, config),
        "llm_decisions":  lambda: cmd_llm_decisions(params, config),
        "daily_summary":  lambda: cmd_daily_summary(params, config),
        "daily_report":   lambda: cmd_daily_report(params, config),
        "review":         lambda: cmd_review(params, config),
        "charts":         lambda: cmd_charts(params, config),
        "win_rate":       lambda: cmd_win_rate(params, config),
        "open_positions":  lambda: cmd_open_positions(params, config),
        "signal_drivers":  lambda: cmd_signal_drivers(params, config),
        "tail_log":        lambda: cmd_tail_log(params),
        "persona":         lambda: cmd_persona(params, config),
        "persona_set":     lambda: cmd_persona_set(params, config),
        "regime":          lambda: cmd_regime(params, config),
        "help":           lambda: cmd_help(params),
    }

    fn = dispatch_map.get(intent)
    if fn:
        try:
            fn()
        except Exception as exc:
            d.print_error(f"Command failed: {exc}")
            logger.exception("Dispatch error for intent '%s'", intent)
    else:
        d.print_warn(f"Unknown intent: '{intent}'. Type [bold]help[/bold] to see commands.")

    return True
