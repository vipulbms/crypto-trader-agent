"""
display.py — Rich terminal output for the Kryptos CLI.

Colour scheme:
  green    → positive P&L / wins / running / BUY
  red      → negative P&L / losses / stopped / SELL
  yellow   → neutral / warnings / HOLD
  cyan     → info / pair names / headers
  magenta  → LLM reasoning text
  white    → general body text
"""

from datetime import datetime
from typing import Optional

from src.utils.tz import to_sgt

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich import box
from rich.text import Text
from rich.rule import Rule
from rich.padding import Padding

console = Console()

_LOGO = r"""
  _  __                 _
 | |/ /_ __ _   _ _ __ | |_ ___  ___
 | ' /| '__| | | | '_ \| __/ _ \/ __|
 | . \| |  | |_| | |_) | || (_) \__ \
 |_|\_\_|   \__, | .__/ \__\___/|___/
             |___/|_|
"""


# ──────────────────────────────────────────────────────────────
# Welcome / branding
# ──────────────────────────────────────────────────────────────

def print_welcome(mode: str = "paper") -> None:
    console.print(Text(_LOGO, style="bold cyan"))
    mode_style = "yellow" if mode == "paper" else "bold red"
    console.print(
        Panel(
            f"[bold white]AI-powered crypto trading agent[/bold white]\n"
            f"Mode: [{mode_style}]{mode.upper()}[/{mode_style}]  •  "
            f"Pairs: BTC ETH BNB SOL XRP TRX DOGE ADA LTC RAILS AVAX SUI HYPE UNI INJ\n"
            f"[dim]Type a question or command. Try [bold]help[/bold] to see what I can do.[/dim]",
            border_style="cyan",
            title="[bold cyan]Kryptos[/bold cyan]",
        )
    )


def print_help() -> None:
    table = Table(box=box.SIMPLE, show_header=True, header_style="bold cyan")
    table.add_column("What you can say", style="white", no_wrap=False)
    table.add_column("What it does", style="dim white")

    rows = [
        ("start [paper|live]",               "Start the trading agent"),
        ("stop",                              "Stop the running agent"),
        ("status",                            "Check if the agent is running"),
        ("next schedule",                     "When does the next cycle run?"),
        ("show my report",                    "Trade history with performance metrics"),
        ("show report for BTC last 7 days",   "Filtered trade history"),
        ("trade details [last 5]",            "Closed trades with LLM reasoning"),
        ("why did it hold ETH?",              "LLM HOLD decisions for a pair"),
        ("show BUY decisions",                "All LLM BUY decisions"),
        ("today's summary",                   "Daily P&L and cycle overview"),
        ("win rate",                          "Performance metrics and drawdown"),
        ("open positions",                    "Currently held positions"),
        ("show log [last 50 lines]",          "Recent agent log output"),
        ("exit / quit",                       "Leave Kryptos"),
    ]
    for what, does in rows:
        table.add_row(what, does)

    console.print(Panel(table, title="[bold cyan]Available Commands[/bold cyan]", border_style="cyan"))


# ──────────────────────────────────────────────────────────────
# Agent status
# ──────────────────────────────────────────────────────────────

def print_agent_status(data: dict) -> None:
    running      = data.get("running", False)
    status_text  = "[bold green]RUNNING[/bold green]" if running else "[bold red]STOPPED[/bold red]"
    mode         = (data.get("mode") or "unknown").upper()
    pid          = data.get("pid") or "—"
    uptime       = data.get("uptime_human") or "—"
    started      = data.get("started_at") or "—"

    lines = [
        f"Status:      {status_text}",
        f"Mode:        [cyan]{mode}[/cyan]",
        f"PID:         {pid}",
        f"Uptime:      {uptime}",
        f"Started at:  [dim]{started}[/dim]",
    ]

    last = data.get("last_cycle")
    if last:
        lines += [
            "",
            "[bold white]Last Cycle[/bold white]",
            f"  Time:       [dim]{last.get('cycle_at','—')}[/dim]",
            f"  Portfolio:  [green]${last.get('portfolio_balance_usd', 0):.2f}[/green]",
            f"  Open pos:   {last.get('open_positions_count', 0)}",
            f"  Daily P&L:  {_pnl_str(last.get('daily_pnl_usd', 0))}",
        ]

    border = "green" if running else "red"
    console.print(Panel("\n".join(lines), title="[bold cyan]Agent Status[/bold cyan]", border_style=border))


def print_next_schedule(data: dict) -> None:
    interval = data.get("interval_minutes", 15)
    wait     = data.get("wait_human", "unknown")
    nxt      = data.get("next_cycle_at") or "—"
    last     = data.get("last_cycle_at") or "Never"
    overdue  = data.get("is_overdue", False)

    wait_style = "bold red" if overdue else "bold green"
    console.print(Panel(
        f"Last cycle:    [dim]{last}[/dim]\n"
        f"Next cycle:    [cyan]{nxt}[/cyan]\n"
        f"Interval:      {interval} minutes\n"
        f"Wait time:     [{wait_style}]{wait}[/{wait_style}]"
        + ("\n[yellow]Note: Agent appears overdue — is it running?[/yellow]" if overdue else ""),
        title="[bold cyan]Next Schedule[/bold cyan]",
        border_style="cyan",
    ))


# ──────────────────────────────────────────────────────────────
# Portfolio summary
# ──────────────────────────────────────────────────────────────

def print_portfolio_summary(data: dict) -> None:
    mode     = data.get("mode", "paper").upper()
    total    = data.get("total_usd", 0)
    cash     = data.get("cash_usd", 0)
    n_pos    = data.get("open_positions_count", 0)
    daily    = data.get("daily_pnl_usd", 0)
    unreal   = data.get("unrealised_pnl_usd", 0)
    snap_at  = data.get("snapshot_at", "—")

    lines = [
        f"[bold white]Mode:[/bold white]        [cyan]{mode}[/cyan]",
        f"[bold white]Total value:[/bold white] [bold green]${total:,.2f}[/bold green]",
        f"[bold white]Available:[/bold white]   ${cash:,.2f}",
        f"[bold white]Open pos:[/bold white]    {n_pos}",
        f"[bold white]Daily P&L:[/bold white]   {_pnl_str(daily)}",
        f"[bold white]Unrealised:[/bold white]  {_pnl_str(unreal)}",
        f"[dim]Snapshot:    {snap_at}[/dim]",
    ]

    positions = data.get("open_positions", [])
    if positions:
        lines.append("")
        lines.append("[bold white]Open Positions[/bold white]")
        for p in positions:
            lines.append(
                f"  [cyan]{p.get('pair','?')}[/cyan]  "
                f"${p.get('usd_value',0):,.2f}  "
                f"entry ${p.get('entry_price',0):,.4f}  "
                f"SL ${p.get('stop_loss_price',0):,.4f}  "
                f"TP ${p.get('take_profit_price',0):,.4f}"
            )

    console.print(Panel("\n".join(lines), title="[bold cyan]Portfolio[/bold cyan]", border_style="cyan"))


# ──────────────────────────────────────────────────────────────
# Trade tables
# ──────────────────────────────────────────────────────────────

def print_trades_table(trades: list, show_llm: bool = False) -> None:
    if not trades:
        console.print("[yellow]No trades found for the selected filters.[/yellow]")
        return

    table = Table(box=box.MARKDOWN, show_header=True, header_style="bold cyan",
                  title=f"Trade History  ({len(trades)} trades)")
    table.add_column("#",        style="dim",     width=4, no_wrap=True)
    table.add_column("Pair",     style="cyan",    width=9, no_wrap=True)
    table.add_column("Opened",   style="dim",     width=20, no_wrap=True)
    table.add_column("Duration", style="white",   width=9,  no_wrap=True)
    table.add_column("Entry $",  style="white",   width=12, no_wrap=True)
    table.add_column("Exit $",   style="white",   width=12, no_wrap=True)
    table.add_column("P&L",      style="white",   width=12, no_wrap=True)
    table.add_column("P&L %",    style="white",   width=8,  no_wrap=True)
    table.add_column("Exit",     style="white",   width=12, no_wrap=True)
    if show_llm:
        table.add_column("LLM Reason", style="magenta", no_wrap=False, max_width=40)

    for i, t in enumerate(trades, 1):
        pnl      = t.get("pnl_usd", 0)
        pnl_pct  = t.get("pnl_pct", 0)
        pnl_style = "green" if pnl > 0 else "red"
        dur      = t.get("hold_duration_human") or _fmt_secs(t.get("hold_duration_secs", 0))
        exit_r   = t.get("exit_reason", "—").replace("_", " ")
        opened   = _short_dt(t.get("opened_at", ""))

        row = [
            str(i),
            t.get("pair", "?"),
            opened,
            dur,
            f"${t.get('entry_price',0):,.4f}",
            f"${t.get('exit_price',0):,.4f}",
            f"[{pnl_style}]${pnl:+,.2f}[/{pnl_style}]",
            f"[{pnl_style}]{pnl_pct:+.2f}%[/{pnl_style}]",
            exit_r,
        ]

        if show_llm:
            llm = t.get("llm_decision")
            reason = ""
            if llm:
                reason = llm.get("reasoning_summary") or llm.get("hold_reason") or ""
                reason = reason[:80] + "..." if len(reason) > 80 else reason
            row.append(reason or "—")

        table.add_row(*row)

    console.print(table)


def print_trade_detail(trade: dict) -> None:
    """Print a single trade with full LLM reasoning."""
    pnl       = trade.get("pnl_usd", 0)
    pnl_style = "green" if pnl > 0 else "red"
    dur       = trade.get("hold_duration_human") or _fmt_secs(trade.get("hold_duration_secs", 0))

    body = (
        f"[bold white]Pair:[/bold white]         [cyan]{trade.get('pair','?')}[/cyan]\n"
        f"[bold white]Opened:[/bold white]       {_short_dt(trade.get('opened_at',''))}\n"
        f"[bold white]Closed:[/bold white]       {_short_dt(trade.get('closed_at',''))}\n"
        f"[bold white]Duration:[/bold white]     {dur}\n"
        f"[bold white]Entry price:[/bold white]  ${trade.get('entry_price',0):,.4f}\n"
        f"[bold white]Exit price:[/bold white]   ${trade.get('exit_price',0):,.4f}\n"
        f"[bold white]Volume:[/bold white]       {trade.get('volume',0):.8f}\n"
        f"[bold white]Invested:[/bold white]     ${trade.get('usd_invested',0):,.2f}\n"
        f"[bold white]P&L:[/bold white]          [{pnl_style}]${pnl:+,.2f}  ({trade.get('pnl_pct',0):+.2f}%)[/{pnl_style}]\n"
        f"[bold white]Exit reason:[/bold white]  {trade.get('exit_reason','—').replace('_',' ')}\n"
        f"[bold white]Fee:[/bold white]          ${trade.get('fee_usd',0):.4f}\n"
        f"[bold white]SL / TP:[/bold white]      {trade.get('stop_loss_pct',0)}% / {trade.get('take_profit_pct',0)}%"
    )

    title_style = "green" if pnl > 0 else "red"
    console.print(Panel(body, title=f"[bold {title_style}]Trade Detail[/bold {title_style}]",
                        border_style=title_style))

    llm = trade.get("llm_decision")
    if llm:
        print_llm_decision(llm, compact=False)


# ──────────────────────────────────────────────────────────────
# LLM decisions
# ──────────────────────────────────────────────────────────────

def print_llm_decisions_table(decisions: list) -> None:
    if not decisions:
        console.print("[yellow]No LLM decisions found for the selected filters.[/yellow]")
        return

    table = Table(box=box.MARKDOWN, show_header=True, header_style="bold magenta",
                  title=f"LLM Decisions  ({len(decisions)} records)")
    table.add_column("#",          style="dim",      width=4)
    table.add_column("When",       style="dim",      width=20, no_wrap=True)
    table.add_column("Pair",       style="cyan",     width=9,  no_wrap=True)
    table.add_column("Decision",   style="white",    width=8,  no_wrap=True)
    table.add_column("Model",      style="dim",      width=14, no_wrap=True)
    table.add_column("Latency",    style="dim",      width=9,  no_wrap=True)
    table.add_column("Risk OK",    style="white",    width=8,  no_wrap=True)
    table.add_column("Summary / Reason", style="magenta", no_wrap=False, max_width=50)

    for i, d in enumerate(decisions, 1):
        dt        = d.get("decision_type", "?")
        dt_colour = {"BUY": "green", "SELL": "red", "HOLD": "yellow"}.get(dt, "white")
        risk_ok   = d.get("approved")
        risk_str  = ("[green]YES[/green]" if risk_ok else "[red]NO[/red]") if risk_ok is not None else "[dim]—[/dim]"
        lat_ms    = d.get("latency_ms")
        lat_str   = f"{lat_ms}ms" if lat_ms else "—"
        summary   = d.get("reasoning_summary") or d.get("hold_reason") or ""
        summary   = summary[:70] + "…" if len(summary) > 70 else summary

        table.add_row(
            str(i),
            _short_dt(d.get("decided_at", "")),
            d.get("pair", "?"),
            f"[{dt_colour}]{dt}[/{dt_colour}]",
            d.get("model_name", "?"),
            lat_str,
            risk_str,
            summary or "—",
        )

    console.print(table)


def print_llm_decision(decision: dict, compact: bool = True) -> None:
    """Print one LLM decision with full reasoning."""
    dt        = decision.get("decision_type", "?")
    dt_colour = {"BUY": "green", "SELL": "red", "HOLD": "yellow"}.get(dt, "white")

    body = (
        f"[bold white]Pair:[/bold white]        [cyan]{decision.get('pair','?')}[/cyan]\n"
        f"[bold white]Decision:[/bold white]    [{dt_colour}]{dt}[/{dt_colour}]\n"
        f"[bold white]Model:[/bold white]       {decision.get('model_name','?')}\n"
        f"[bold white]At:[/bold white]          {_short_dt(decision.get('decided_at',''))}\n"
        f"[bold white]Latency:[/bold white]     {decision.get('latency_ms','—')}ms\n"
    )

    if decision.get("hold_reason"):
        body += f"\n[yellow]Hold reason:[/yellow] {decision['hold_reason']}\n"

    if decision.get("reasoning_summary"):
        body += f"\n[bold magenta]Summary:[/bold magenta]\n{decision['reasoning_summary']}\n"

    if not compact and decision.get("raw_llm_output"):
        trimmed = decision["raw_llm_output"][:800]
        if len(decision["raw_llm_output"]) > 800:
            trimmed += "\n[dim]… (truncated)[/dim]"
        body += f"\n[bold white]Full LLM output:[/bold white]\n[dim]{trimmed}[/dim]\n"

    if decision.get("rejection_reason"):
        body += f"\n[red]Risk rejected:[/red] {decision['rejection_reason']}\n"

    console.print(Panel(body, title=f"[bold {dt_colour}]LLM Decision[/bold {dt_colour}]",
                        border_style=dt_colour))


# ──────────────────────────────────────────────────────────────
# LLM pattern analysis
# ──────────────────────────────────────────────────────────────

def print_llm_patterns(data: dict) -> None:
    days = data.get("days", 14)
    total = data.get("total_decisions", 0)
    console.print(Rule(f"[bold magenta]LLM Decision Patterns — Last {days} Days[/bold magenta]"))

    # Per-pair matrix
    matrix = data.get("pair_matrix", {})
    if matrix:
        tbl = Table(box=box.SIMPLE, show_header=True, header_style="bold cyan")
        tbl.add_column("Pair",          style="cyan",   width=10)
        tbl.add_column("LLM Buy",       style="green",  width=9)
        tbl.add_column("LLM Sell",      style="red",    width=9)
        tbl.add_column("LLM Hold",      style="yellow", width=9)
        tbl.add_column("Risk ✓",        style="green",  width=8)
        tbl.add_column("Risk ✗",        style="red",    width=8)
        tbl.add_column("Executed",      style="green",  width=10)
        tbl.add_column("Final Hold",    style="yellow", width=11)
        for pair, c in matrix.items():
            tbl.add_row(
                pair,
                str(c.get("LLM_BUY",  0)),
                str(c.get("LLM_SELL", 0)),
                str(c.get("LLM_HOLD", 0)),
                str(c.get("RISK_APPROVED", 0)),
                str(c.get("RISK_REJECTED", 0)),
                str(c.get("FINAL_EXECUTED", 0)),
                str(c.get("FINAL_HOLD", 0)),
            )
        console.print(Panel(tbl, title="Decision Breakdown by Pair", border_style="cyan"))

    # Models
    models = data.get("models_used", {})
    lats   = data.get("avg_latency_ms", {})
    if models:
        lines = [f"[bold white]Total decisions:[/bold white] {total}",
                 f"[bold white]Risk rejection rate:[/bold white] {data.get('rejection_rate_pct',0):.1f}%", ""]
        for m, cnt in models.items():
            lat = lats.get(m)
            lat_str = f"  avg {lat}ms" if lat else ""
            lines.append(f"  [cyan]{m}[/cyan]: {cnt} calls{lat_str}")
        console.print(Panel("\n".join(lines), title="Model Usage", border_style="magenta"))

    # Top hold reasons
    hold_reasons = data.get("top_hold_reasons", [])
    if hold_reasons:
        tbl2 = Table(box=box.SIMPLE, show_header=True, header_style="bold yellow")
        tbl2.add_column("Count", style="yellow", width=7)
        tbl2.add_column("Hold Reason", style="white")
        for r in hold_reasons:
            tbl2.add_row(str(r.get("cnt", 0)), r.get("hold_reason") or "—")
        console.print(Panel(tbl2, title="Top Hold Reasons", border_style="yellow"))


# ──────────────────────────────────────────────────────────────
# Performance metrics
# ──────────────────────────────────────────────────────────────

def print_performance_metrics(data: dict) -> None:
    days   = data.get("days", 14)
    total  = data.get("total_trades", 0)
    wins   = data.get("wins", 0)
    losses = data.get("losses", 0)
    wr     = data.get("win_rate_pct", 0)
    pnl    = data.get("total_pnl_usd", 0)
    dd     = data.get("max_drawdown_pct", 0)
    avg_h  = data.get("avg_hold_human", "—")

    wr_style  = "green" if wr >= 50 else "red"
    dd_style  = "green" if dd < 10 else ("yellow" if dd < 15 else "red")
    pnl_style = "green" if pnl > 0 else "red"

    console.print(Rule(f"[bold cyan]Performance — Last {days} Days[/bold cyan]"))
    console.print(
        Panel(
            f"[bold white]Total trades:[/bold white]   {total}\n"
            f"[bold white]Wins / Losses:[/bold white]  [green]{wins}[/green] / [red]{losses}[/red]\n"
            f"[bold white]Win rate:[/bold white]       [{wr_style}]{wr:.1f}%[/{wr_style}]\n"
            f"[bold white]Total P&L:[/bold white]      [{pnl_style}]${pnl:+,.2f}[/{pnl_style}]\n"
            f"[bold white]Max drawdown:[/bold white]   [{dd_style}]{dd:.2f}%[/{dd_style}]\n"
            f"[bold white]Avg hold:[/bold white]       {avg_h}",
            title="[bold cyan]Overall Metrics[/bold cyan]",
            border_style="cyan",
        )
    )

    by_pair = data.get("by_pair", {})
    if by_pair:
        tbl = Table(box=box.SIMPLE, show_header=True, header_style="bold cyan")
        tbl.add_column("Pair",     style="cyan",  width=10)
        tbl.add_column("Trades",   style="white", width=8)
        tbl.add_column("Win %",    style="white", width=8)
        tbl.add_column("P&L",      style="white", width=12)
        for pair, stats in by_pair.items():
            wr_p = stats.get("win_rate_pct", 0)
            pnl_p = stats.get("pnl_usd", 0)
            wr_s  = "green" if wr_p >= 50 else "red"
            pnl_s = "green" if pnl_p > 0 else "red"
            tbl.add_row(
                pair, str(stats.get("total", 0)),
                f"[{wr_s}]{wr_p:.1f}%[/{wr_s}]",
                f"[{pnl_s}]${pnl_p:+,.2f}[/{pnl_s}]",
            )
        console.print(Panel(tbl, title="Per-Pair Breakdown", border_style="cyan"))

    best  = data.get("best_trade")
    worst = data.get("worst_trade")
    if best or worst:
        lines = []
        if best:
            lines.append(
                f"[bold white]Best:[/bold white]   [cyan]{best.get('pair','?')}[/cyan]  "
                f"[green]${best.get('pnl_usd',0):+,.2f}[/green]  "
                f"({_short_dt(best.get('opened_at',''))})"
            )
        if worst:
            lines.append(
                f"[bold white]Worst:[/bold white]  [cyan]{worst.get('pair','?')}[/cyan]  "
                f"[red]${worst.get('pnl_usd',0):+,.2f}[/red]  "
                f"({_short_dt(worst.get('opened_at',''))})"
            )
        console.print(Panel("\n".join(lines), title="Best / Worst Trade", border_style="dim"))

    exit_counts = data.get("exit_reason_counts", {})
    exit_pnl    = data.get("exit_reason_pnl", {})
    if exit_counts:
        lines2 = []
        for k, v in exit_counts.items():
            pnl_v = exit_pnl.get(k, 0.0)
            pnl_style = "green" if pnl_v >= 0 else "red"
            lines2.append(
                f"  [bold white]{k.replace('_', ' ')}:[/bold white] {v}  "
                f"[{pnl_style}]${pnl_v:+,.2f}[/{pnl_style}]"
            )
        console.print(Panel("\n".join(lines2), title="Exit Reasons", border_style="dim"))


# ──────────────────────────────────────────────────────────────
# Daily summary
# ──────────────────────────────────────────────────────────────

def print_daily_summary(data: dict) -> None:
    date   = data.get("date", "today")
    mode   = data.get("mode", "paper").upper()
    cycles = data.get("cycles_run", 0)
    closed = data.get("trades_closed", 0)
    pnl    = data.get("total_pnl_usd", 0)
    wins   = data.get("wins", 0)
    losses = data.get("losses", 0)
    errs   = data.get("errors", 0)
    bal    = data.get("closing_balance")
    dec    = data.get("decision_counts", {})

    pnl_style = "green" if pnl >= 0 else "red"

    body = (
        f"[bold white]Date:[/bold white]          {date}  [cyan]{mode}[/cyan]\n"
        f"[bold white]Cycles run:[/bold white]    {cycles}\n"
        f"[bold white]Trades closed:[/bold white] {closed}  "
        f"([green]{wins} wins[/green] / [red]{losses} losses[/red])\n"
        f"[bold white]Day P&L:[/bold white]       [{pnl_style}]${pnl:+,.2f}[/{pnl_style}]\n"
    )
    if bal:
        body += f"[bold white]Closing bal:[/bold white]   [green]${bal:,.2f}[/green]\n"
    if dec:
        body += "\n[bold white]Decisions:[/bold white]\n"
        for dtype, cnt in dec.items():
            dc = {"BUY": "green", "SELL": "red", "HOLD": "yellow"}.get(dtype, "white")
            body += f"  [{dc}]{dtype}[/{dc}]: {cnt}\n"
    if errs:
        body += f"\n[yellow]Errors logged: {errs}[/yellow]\n"

    console.print(Panel(body.strip(), title=f"[bold cyan]Daily Summary — {date}[/bold cyan]",
                        border_style="cyan"))

    trades = data.get("trades", [])
    if trades:
        print_trades_table(trades, show_llm=False)


# ──────────────────────────────────────────────────────────────
# Cycle detail
# ──────────────────────────────────────────────────────────────

def print_cycle_detail(data: dict) -> None:
    cycle = data.get("cycle", {})
    console.print(Rule(f"[bold cyan]Cycle #{cycle.get('id','?')}  {cycle.get('cycle_at','?')}[/bold cyan]"))
    console.print(
        f"  Portfolio: [green]${cycle.get('portfolio_balance_usd',0):,.2f}[/green]  "
        f"Cash: ${cycle.get('available_cash_usd',0):,.2f}  "
        f"Open positions: {cycle.get('open_positions_count',0)}  "
        f"Daily P&L: {_pnl_str(cycle.get('daily_pnl_usd',0))}\n"
    )

    for d in data.get("decisions", []):
        print_llm_decision(d, compact=False)


# ──────────────────────────────────────────────────────────────
# Log tail
# ──────────────────────────────────────────────────────────────

def print_log_tail(lines: list) -> None:
    text = "\n".join(lines) if lines else "[dim]No log output.[/dim]"
    console.print(Panel(text, title="[bold cyan]Agent Log[/bold cyan]", border_style="dim"))


# ──────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────

def print_ok(msg: str) -> None:
    console.print(f"[bold green]✓[/bold green]  {msg}")


def print_error(msg: str) -> None:
    console.print(f"[bold red]✗[/bold red]  {msg}")


def print_info(msg: str) -> None:
    console.print(f"[cyan]ℹ[/cyan]  {msg}")


def print_warn(msg: str) -> None:
    console.print(f"[yellow]⚠[/yellow]  {msg}")


def _pnl_str(val: float) -> str:
    style = "green" if val >= 0 else "red"
    return f"[{style}]${val:+,.2f}[/{style}]"


def _short_dt(iso: str) -> str:
    if not iso:
        return "—"
    try:
        dt = to_sgt(datetime.fromisoformat(iso.replace("Z", "+00:00")))
        return dt.strftime("%Y-%m-%d %H:%M")
    except Exception:
        return iso[:16]


def _fmt_secs(secs: int) -> str:
    if not secs:
        return "—"
    h = secs // 3600
    m = (secs % 3600) // 60
    s = secs % 60
    return f"{h}h {m}m" if h else (f"{m}m {s}s" if m else f"{s}s")


def print_signal_driver_report(data: dict) -> None:
    """Display parameter driver report — top blockers and BUY drivers per pair (Fix #117)."""
    from rich.table import Table

    days = data.get("period_days", 30)
    console.print(f"\n[bold cyan]Signal Driver Report — last {days} days[/bold cyan]")

    # Global blockers
    g_blockers = data.get("global_top_blockers", [])
    if g_blockers:
        console.print("\n[bold yellow]Top blockers (global)[/bold yellow]")
        t = Table(show_header=True, header_style="bold")
        t.add_column("Reason", style="yellow", no_wrap=False)
        t.add_column("Count", justify="right")
        for row in g_blockers:
            t.add_row(row["reason"][:100], str(row["count"]))
        console.print(t)

    # Global drivers
    g_drivers = data.get("global_top_drivers", [])
    if g_drivers:
        console.print("\n[bold green]Top BUY drivers (global)[/bold green]")
        t = Table(show_header=True, header_style="bold")
        t.add_column("Reason", style="green", no_wrap=False)
        t.add_column("Count", justify="right")
        for row in g_drivers:
            t.add_row(row["reason"][:100], str(row["count"]))
        console.print(t)

    # Per-pair summary
    by_pair = data.get("by_pair", {})
    if by_pair:
        console.print("\n[bold]Per-pair signal summary[/bold]")
        t = Table(show_header=True, header_style="bold")
        t.add_column("Pair")
        t.add_column("BUY", justify="right", style="green")
        t.add_column("HOLD", justify="right", style="yellow")
        t.add_column("Top blocker (count)")
        for pair, entry in sorted(by_pair.items()):
            top_blocker = entry["top_blockers"][0]["reason"][:60] if entry["top_blockers"] else "—"
            top_count   = f" ({entry['top_blockers'][0]['count']})" if entry["top_blockers"] else ""
            t.add_row(pair, str(entry["buy_count"]), str(entry["hold_count"]),
                      f"{top_blocker}{top_count}")
        console.print(t)
