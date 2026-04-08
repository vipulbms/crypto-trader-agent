"""
chart_generator.py — Core charting engine for Kryptos trade visualisation.

Extracts the chart-rendering logic originally in scripts/chart_trades.py so
that daily/review/CLI report commands can embed charts without shelling out.

Public API
----------
generate_charts(db_path, out_dir, history_dir, pair_filter, window) -> list[Path]
    Render one PNG per closed trade and return the list of generated paths.
"""

import json
import sqlite3
from pathlib import Path
from typing import Optional

import matplotlib
matplotlib.use("Agg")  # headless — no display needed
import matplotlib.pyplot as plt
import matplotlib.lines as mlines
import mplfinance as mpf
import numpy as np
import pandas as pd

# ── Candle field positions ────────────────────────────────────────────────────
PAIR_FILE_MAP = {
    "BTC/USD":   "XBTUSD_candle.json",
    "ETH/USD":   "ETHUSD_candle.json",
    "SOL/USD":   "SOLUSD_candle.json",
    "XRP/USD":   "XRPUSD_candle.json",
    "ADA/USD":   "ADAUSD_candle.json",
    "DOGE/USD":  "XDGUSD_candle.json",
    "BNB/USD":   "BNBUSD_candle.json",
    "AVAX/USD":  "AVAXUSD_candle.json",
    "LTC/USD":   "LTCUSD_candle.json",
    "TRX/USD":   "TRXUSD_candle.json",
    "UNI/USD":   "UNIUSD_candle.json",
    "SUI/USD":   "SUIUSD_candle.json",
    "INJ/USD":   "INJUSD_candle.json",
    "RAILS/USD": "RAILSUSD_candle.json",
    "HYPE/USD":  "HYPEUSD_candle.json",
}

EXIT_COLOURS = {
    "take_profit": "#00c853",
    "stop_loss":   "#d50000",
    "agent_sell":  "#ff6d00",
    "partial_tp":  "#00bcd4",
}
EXIT_LABEL = {
    "take_profit": "TP",
    "stop_loss":   "SL",
    "agent_sell":  "SELL",
    "partial_tp":  "PARTIAL TP",
}

DEFAULT_WINDOW  = 80
DEFAULT_HISTORY = "history"


# ── Candle loading ────────────────────────────────────────────────────────────

def load_candles(pair: str, history_dir: str) -> pd.DataFrame:
    """Load OHLCV candles for *pair* from *history_dir*.  Returns a UTC DatetimeIndex DataFrame."""
    fname = PAIR_FILE_MAP.get(pair)
    if fname is None:
        raise ValueError(f"No history file mapping for pair {pair!r}")
    path = Path(history_dir) / fname
    if not path.exists():
        raise FileNotFoundError(f"History file not found: {path}")

    with open(path) as f:
        data = json.load(f)

    result     = data.get("result", {})
    candle_key = [k for k in result if k != "last"][0]
    raw        = result[candle_key]

    df = pd.DataFrame(raw, columns=["time", "open", "high", "low", "close", "vwap", "volume", "count"])
    df = df.astype({"time": int, "open": float, "high": float, "low": float,
                    "close": float, "volume": float})
    df["datetime"] = pd.to_datetime(df["time"], unit="s", utc=True)
    df = df.set_index("datetime").sort_index()
    return df[["open", "high", "low", "close", "volume"]]


# ── Trade loading ─────────────────────────────────────────────────────────────

def load_trades(db_path: str, pair_filter: Optional[str] = None) -> list[dict]:
    """Load closed trades from the *paper_trades* table in *db_path*."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    query  = "SELECT * FROM paper_trades WHERE closed_at IS NOT NULL"
    params: list = []
    if pair_filter:
        query += " AND pair = ?"
        params.append(pair_filter)
    query += " ORDER BY opened_at"
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_ts(ts_str: str) -> pd.Timestamp:
    ts = pd.Timestamp(ts_str)
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    return ts.tz_convert("UTC").as_unit("s")


def _candle_window(df: pd.DataFrame, entry_ts: pd.Timestamp,
                   exit_ts: pd.Timestamp, window: int) -> pd.DataFrame:
    entry_pos = df.index.searchsorted(entry_ts, side="left")
    exit_pos  = df.index.searchsorted(exit_ts,  side="right")
    return df.iloc[max(0, entry_pos - window): min(len(df), exit_pos + window)]


# ── Single-trade chart ────────────────────────────────────────────────────────

def render_trade_chart(
    df_window:  pd.DataFrame,
    trade:      dict,
    trade_num:  int,
    pair_total: int,
    out_path:   Path,
) -> None:
    """Render a candlestick + marker chart for one trade and write to *out_path*."""
    entry_ts    = _parse_ts(trade["opened_at"])
    exit_ts     = _parse_ts(trade["closed_at"])
    exit_reason = trade.get("exit_reason", "unknown")
    pnl_pct     = trade["pnl_pct"]
    pnl_usd     = trade["pnl_usd"]
    pair        = trade["pair"]
    entry_px    = trade["entry_price"]
    exit_px     = trade["exit_price"]

    sell_colour = EXIT_COLOURS.get(exit_reason, "#e040fb")
    sell_label  = EXIT_LABEL.get(exit_reason, exit_reason.upper())

    buy_series  = pd.Series(np.nan, index=df_window.index)
    sell_series = pd.Series(np.nan, index=df_window.index)

    buy_pos  = df_window.index.get_indexer([entry_ts], method="nearest")[0]
    sell_pos = df_window.index.get_indexer([exit_ts],  method="nearest")[0]
    if 0 <= buy_pos < len(df_window):
        buy_series.iloc[buy_pos]  = df_window["low"].iloc[buy_pos] * 0.995
    if 0 <= sell_pos < len(df_window):
        sell_series.iloc[sell_pos] = df_window["high"].iloc[sell_pos] * 1.005

    addplots = []
    if buy_series.notna().any():
        addplots.append(mpf.make_addplot(buy_series, type="scatter", marker="^",
                                         markersize=120, color="#00e676", panel=0))
    if sell_series.notna().any():
        addplots.append(mpf.make_addplot(sell_series, type="scatter", marker="v",
                                         markersize=120, color=sell_colour, panel=0))

    pnl_sign = "+" if pnl_pct >= 0 else ""
    title = (
        f"{pair}  [{trade_num}/{pair_total}]  |  "
        f"Entry: ${entry_px:,.4f}  →  Exit: ${exit_px:,.4f}  |  "
        f"P&L: {pnl_sign}{pnl_pct:.2f}% (${pnl_sign}{pnl_usd:.2f})  |  {sell_label}"
    )

    mc = mpf.make_marketcolors(
        up="#26a69a", down="#ef5350", edge="inherit",
        wick="inherit", volume={"up": "#26a69a", "down": "#ef5350"},
    )
    style = mpf.make_mpf_style(
        marketcolors=mc, gridstyle="--", gridcolor="#3a3a3a",
        facecolor="#1a1a2e", edgecolor="#cccccc", figcolor="#1a1a2e",
        y_on_right=True,
        rc={"axes.labelcolor": "#cccccc", "xtick.color": "#cccccc", "ytick.color": "#cccccc"},
    )

    fig, axes = mpf.plot(
        df_window, type="candle", style=style,
        addplot=addplots if addplots else None,
        volume=True, title=title, figsize=(16, 8),
        returnfig=True, tight_layout=True,
        datetime_format="%m-%d %H:%M", xrotation=30,
    )

    ax_main = axes[0]
    ax_main.axhline(entry_px, color="#00e676", linewidth=0.8, linestyle="--", alpha=0.6)
    ax_main.axhline(exit_px,  color=sell_colour, linewidth=0.8, linestyle="--", alpha=0.6)

    legend_elements = [
        mlines.Line2D([0], [0], marker="^", color="w", markerfacecolor="#00e676",
                      markersize=10, label="BUY entry"),
        mlines.Line2D([0], [0], marker="v", color="w",
                      markerfacecolor=EXIT_COLOURS["take_profit"],
                      markersize=10, label="Take Profit exit"),
        mlines.Line2D([0], [0], marker="v", color="w",
                      markerfacecolor=EXIT_COLOURS["stop_loss"],
                      markersize=10, label="Stop Loss exit"),
        mlines.Line2D([0], [0], marker="v", color="w",
                      markerfacecolor=EXIT_COLOURS["agent_sell"],
                      markersize=10, label="Agent Sell exit"),
        mlines.Line2D([0], [0], marker="v", color="w",
                      markerfacecolor=EXIT_COLOURS["partial_tp"],
                      markersize=10, label="Partial TP exit"),
        mlines.Line2D([0], [0], linestyle="--", color="#00e676", linewidth=1.2,
                      label=f"Entry price ${entry_px:,.4f}"),
        mlines.Line2D([0], [0], linestyle="--", color=sell_colour, linewidth=1.2,
                      label=f"Exit price ${exit_px:,.4f}"),
    ]
    ax_main.legend(handles=legend_elements, loc="upper left", fontsize=7,
                   facecolor="#2a2a3e", labelcolor="#cccccc", framealpha=0.8)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(str(out_path), dpi=120, bbox_inches="tight", facecolor="#1a1a2e")
    plt.close(fig)


# ── Public entry point ────────────────────────────────────────────────────────

def generate_charts(
    db_path:     str,
    out_dir:     str  = "charts",
    history_dir: str  = DEFAULT_HISTORY,
    pair_filter: Optional[str] = None,
    window:      int  = DEFAULT_WINDOW,
    quiet:       bool = False,
) -> list[Path]:
    """Generate one chart PNG per closed trade.

    Args:
        db_path:     SQLite DB path (paper_trading.db or backtest_paper.db).
        out_dir:     Directory to write charts into.
        history_dir: Directory containing ``*_candle.json`` files.
        pair_filter: If set, only render charts for this pair (e.g. "ETH/USD").
        window:      Candles of padding before/after each trade.
        quiet:       Suppress progress prints when True.

    Returns:
        List of Path objects for every chart successfully written.
    """
    if not Path(db_path).exists():
        raise FileNotFoundError(f"DB not found: {db_path}")

    trades = load_trades(db_path, pair_filter)
    if not trades:
        if not quiet:
            print("No closed trades found — no charts generated.")
        return []

    if not quiet:
        print(f"Generating charts for {len(trades)} trade(s) …")

    # Group by pair
    from collections import defaultdict
    by_pair: dict[str, list[dict]] = defaultdict(list)
    for t in trades:
        by_pair[t["pair"]].append(t)

    candle_cache: dict[str, pd.DataFrame] = {}
    for pair in by_pair:
        try:
            candle_cache[pair] = load_candles(pair, history_dir)
        except (ValueError, FileNotFoundError) as e:
            if not quiet:
                print(f"  WARNING: {e} — skipping {pair}")

    out_root  = Path(out_dir)
    generated: list[Path] = []

    for pair, pair_trades in by_pair.items():
        if pair not in candle_cache:
            continue
        df_all = candle_cache[pair]

        for idx, trade in enumerate(pair_trades, start=1):
            entry_ts = _parse_ts(trade["opened_at"])
            exit_ts  = _parse_ts(trade["closed_at"])
            df_window = _candle_window(df_all, entry_ts, exit_ts, window)

            if len(df_window) < 5:
                if not quiet:
                    print(f"  WARN: too few candles for {pair} trade #{idx} — skipping")
                continue

            safe_pair = pair.replace("/", "")
            out_path  = out_root / f"{safe_pair}_{idx:03d}.png"
            render_trade_chart(df_window, trade, idx, len(pair_trades), out_path)
            generated.append(out_path)
            if not quiet:
                print(f"  → {out_path}  ({trade['exit_reason']}  {trade['pnl_pct']:+.2f}%)")

    if not quiet:
        print(f"Done. {len(generated)} chart(s) saved to {out_root}/")
    return generated
