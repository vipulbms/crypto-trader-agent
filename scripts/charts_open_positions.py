#!/usr/bin/env python3
"""
charts_open_positions.py
------------------------
Generate candlestick charts for every currently-open paper position,
fetch live candles from Kraken REST (15-min interval, last 720 candles),
overlay buy markers, SL/TP levels, and key EMAs/BBs.

Also prints a signal analysis for each pair explaining why SELL has not fired.

Output: charts/<CRYPTONAME>.<YYYYMMDD-HHMM>.png
"""

import json
import os
import sys
import time
import sqlite3
import datetime
from pathlib import Path
from typing import Optional

import requests
import numpy as np
import pandas as pd
import yaml

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.lines as mlines
import matplotlib.patches as mpatches
import mplfinance as mpf

# ── paths ────────────────────────────────────────────────────────────────────
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from src.analysis.indicators import compute_indicators
from src.analysis.signals import generate_signal

DB_PATH      = ROOT / "data" / "paper_trading.db"
CONFIG_PATH  = ROOT / "config.yaml"
CHARTS_DIR   = ROOT / "charts"
KRAKEN_OHLC  = "https://api.kraken.com/0/public/OHLC"
SGT          = datetime.timezone(datetime.timedelta(hours=8))

# Pairs that are not in the standard PAIR→rest-name config can be added here
PAIR_REST_OVERRIDE = {
    "BTC/USD": "XBTUSD",
    "DOGE/USD": "XDGUSD",
}


# ── helpers ───────────────────────────────────────────────────────────────────

def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


def load_open_positions() -> list[dict]:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT * FROM paper_positions ORDER BY opened_at"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_rest_name(pair: str, config: dict) -> str:
    """Resolve Kraken REST symbol from config or override map."""
    if pair in PAIR_REST_OVERRIDE:
        return PAIR_REST_OVERRIDE[pair]
    for p in config.get("trading", {}).get("pairs", []):
        if p["pair"] == pair:
            return p.get("rest_name", pair.replace("/", ""))
    return pair.replace("/", "")


def fetch_live_candles(rest_name: str, since: Optional[int] = None) -> Optional[pd.DataFrame]:
    """
    Fetch up to 720 15-min candles from Kraken REST API.
    Returns a DataFrame with DatetimeIndex (UTC) and OHLCV columns.
    """
    params: dict = {"pair": rest_name, "interval": 15}
    if since is not None:
        params["since"] = since
    try:
        resp = requests.get(
            KRAKEN_OHLC,
            params=params,
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("error"):
            print(f"  Kraken API error for {rest_name}: {data['error']}")
            return None
        result = data.get("result", {})
        candle_key = next((k for k in result if k != "last"), None)
        if not candle_key:
            return None
        raw = result[candle_key]
        df = pd.DataFrame(raw, columns=["time","open","high","low","close","vwap","volume","count"])
        df = df.astype({"time": int, "open": float, "high": float,
                        "low": float, "close": float, "volume": float})
        df["datetime"] = pd.to_datetime(df["time"], unit="s", utc=True)
        df = df.set_index("datetime").sort_index()
        return df[["open","high","low","close","volume"]]
    except Exception as e:
        print(f"  ERROR fetching {rest_name}: {e}")
        return None


def compute_buy_pnl(entry_price: float, current_price: float) -> float:
    return ((current_price - entry_price) / entry_price) * 100


# ── chart rendering ──────────────────────────────────────────────────────────

MC = mpf.make_marketcolors(
    up="#26a69a", down="#ef5350", edge="inherit",
    wick="inherit", volume={"up": "#26a69a", "down": "#ef5350"},
)
STYLE = mpf.make_mpf_style(
    marketcolors=MC, gridstyle="--", gridcolor="#3a3a3a",
    facecolor="#1a1a2e", edgecolor="#cccccc", figcolor="#1a1a2e",
    y_on_right=True,
    rc={"axes.labelcolor": "#cccccc", "xtick.color": "#cccccc", "ytick.color": "#cccccc",
        "axes.titlecolor": "#ffffff"},
)


def render_chart(
    df: pd.DataFrame,
    pos: dict,
    buy_times: list[pd.Timestamp],
    buy_prices: list[float],
    indicators: Optional[dict],
    signal: Optional[dict],
    out_path: Path,
) -> None:
    pair = pos["pair"]
    entry_px = pos["entry_price"]
    sl_px    = pos["stop_loss_price"]
    tp_px    = pos["take_profit_price"]
    try:
        opened_at = datetime.datetime.fromisoformat(pos["opened_at"])
    except Exception:
        opened_at = None

    current_px = float(df["close"].iloc[-1])
    pnl_pct    = compute_buy_pnl(entry_px, current_px)
    pnl_sign   = "+" if pnl_pct >= 0 else ""

    # Build buy marker series — one per buy time
    buy_series = pd.Series(np.nan, index=df.index)
    for bt in buy_times:
        pos_idx = df.index.get_indexer([bt], method="nearest")[0]
        if 0 <= pos_idx < len(df):
            buy_series.iloc[pos_idx] = df["low"].iloc[pos_idx] * 0.992

    # EMA overlays
    addplots = []
    if buy_series.notna().any():
        addplots.append(mpf.make_addplot(
            buy_series, type="scatter", marker="^",
            markersize=180, color="#00e676", panel=0
        ))

    if indicators:
        for ema_key, color, lw in [("ema_9", "#ff9800", 1.0), ("ema_21", "#29b6f6", 0.8), ("ema_50", "#ab47bc", 0.8)]:
            val = indicators.get(ema_key)
            if val:
                ema_series = pd.Series(val, index=df.index)
                # Flat line is wrong — use TA-computed series if available, else skip
        # We'll annotate instead

    safe_pair_name = pair.replace("/", "")
    now_sgt = datetime.datetime.now(SGT).strftime("%Y%m%d-%H%M")
    def ds(v): return f"{v:,.4f}".replace("$", "")  # dollar-safe formatter
    title = (
        f"{pair}  |  Entry: USD {entry_px:,.4f}  |  Now: USD {current_px:,.4f}  |  "
        f"P&L: {pnl_sign}{pnl_pct:.2f}pct  |  TP: USD {tp_px:,.4f} ({pos['take_profit_pct']}pct)  |  SL: USD {sl_px:,.4f}"
    )

    fig, axes = mpf.plot(
        df, type="candle", style=STYLE,
        addplot=addplots if addplots else None,
        volume=True, title=title, figsize=(18, 9),
        returnfig=True, tight_layout=True,
        datetime_format="%m-%d %H:%M", xrotation=30,
    )

    ax = axes[0]

    # Horizontal reference lines
    ax.axhline(entry_px, color="#00e676", linewidth=1.2, linestyle="--", alpha=0.9, label=f"Entry {entry_px:,.4f}")
    ax.axhline(sl_px,    color="#ff1744", linewidth=1.2, linestyle=":",  alpha=0.9, label=f"SL {sl_px:,.4f}")
    ax.axhline(tp_px,    color="#00bcd4", linewidth=1.2, linestyle=":",  alpha=0.9, label=f"TP {tp_px:,.4f}")
    ax.axhline(current_px, color="#ffeb3b", linewidth=0.8, linestyle="-", alpha=0.6, label=f"Now {current_px:,.4f}")

    # Signal annotation box
    if signal:
        sig_text_lines = [
            f"Signal: {signal['signal']}  (buy_score={signal.get('buy_score',0)}  sell_score={signal.get('sell_score',0)})",
            f"Buy min: {signal.get('buy_min_score','?')}  Sell min: {signal.get('sell_min_score','?')}",
        ]
        # Show top 5 reasons
        reasons = signal.get("reasons", [])
        for r in reasons[:8]:
            sig_text_lines.append(f"  • {r}")
        sig_text = "\n".join(sig_text_lines)
        ax.text(
            0.01, 0.01, sig_text, transform=ax.transAxes,
            fontsize=6.5, color="#ffffff", verticalalignment="bottom",
            bbox=dict(boxstyle="round,pad=0.4", facecolor="#1a1a1a", alpha=0.85, edgecolor="#555555"),
        )

    # Sell guard annotation
    tp_pct       = pos["take_profit_pct"]
    proximity_pct = tp_pct * 0.60
    pnl_status   = "SELL BLOCKED" if pnl_pct < proximity_pct else "SELL ELIGIBLE"
    guard_text = (
        f"Early Exit Guard: need >={proximity_pct:.1f}pct P&L (60pct of {tp_pct}pct TP)\n"
        f"Current P&L: {pnl_sign}{pnl_pct:.2f}pct  ->  {pnl_status}"
    )
    ax.text(
        0.99, 0.01, guard_text, transform=ax.transAxes,
        fontsize=7, color="#ffffff", verticalalignment="bottom", horizontalalignment="right",
        bbox=dict(boxstyle="round,pad=0.4", facecolor="#1a0000" if pnl_pct < proximity_pct else "#001a00",
                  alpha=0.9, edgecolor="#ff1744" if pnl_pct < proximity_pct else "#00c853"),
    )

    # Legend
    legend_elements = [
        mlines.Line2D([0],[0], marker="^", color="w", markerfacecolor="#00e676", markersize=10, label="BUY"),
        mlines.Line2D([0],[0], linestyle="--", color="#00e676", linewidth=1.2, label=f"Entry {entry_px:,.4f}"),
        mlines.Line2D([0],[0], linestyle=":", color="#ff1744", linewidth=1.2, label=f"SL {sl_px:,.4f} (-{pos['stop_loss_pct']}pct)"),
        mlines.Line2D([0],[0], linestyle=":", color="#00bcd4", linewidth=1.2, label=f"TP {tp_px:,.4f} (+{pos['take_profit_pct']}pct)"),
        mlines.Line2D([0],[0], linestyle="-", color="#ffeb3b", linewidth=0.8, label=f"Now {current_px:,.4f} ({pnl_sign}{pnl_pct:.2f}pct)"),
    ]
    ax.legend(handles=legend_elements, loc="upper left", fontsize=7,
              facecolor="#2a2a3e", labelcolor="#cccccc", framealpha=0.85)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(str(out_path), dpi=120, bbox_inches="tight", facecolor="#1a1a2e")
    plt.close(fig)
    print(f"  → {out_path.relative_to(ROOT)}")


# ── signal analysis ──────────────────────────────────────────────────────────

def analyze_sell_block(pos: dict, signal: Optional[dict], indicators: Optional[dict]) -> dict:
    """Return a dict summarising what is blocking a sell for this position."""
    pair = pos["pair"]
    entry_px = pos["entry_price"]
    tp_pct   = pos["take_profit_pct"]
    sl_pct   = pos["stop_loss_pct"]

    blocks = []
    info   = {}

    if indicators:
        current_px = indicators.get("close", 0)
        pnl_pct = compute_buy_pnl(entry_px, current_px)
        info["current_px"] = current_px
        info["pnl_pct"]    = pnl_pct

        # Guard 1: Min profit floor
        if pnl_pct < 1.0:
            blocks.append(f"MIN PROFIT FLOOR: P&L {pnl_pct:+.2f}% < 1.0% (covers exchange fees)")

        # Guard 2: Early exit guard (60% of TP)
        threshold = tp_pct * 0.60
        if pnl_pct < threshold:
            blocks.append(
                f"EARLY EXIT GUARD: P&L {pnl_pct:+.2f}% < {threshold:.1f}% (60% of {tp_pct}% TP target)"
            )

        # Signal sell score
        if signal:
            sell_score    = signal.get("sell_score", 0)
            sell_min      = signal.get("sell_min_score", 3)
            info["signal"] = signal["signal"]
            info["sell_score"] = sell_score
            info["sell_min_score"] = sell_min
            if sell_score < sell_min:
                blocks.append(
                    f"SIGNAL: sell_score={sell_score} < sell_min={sell_min} "
                    f"(need RSI>{pos.get('rsi_overbought','?')} or MACD-/BB upper)"
                )

        # Indicator values
        rsi = indicators.get("rsi_14")
        macd_hist = indicators.get("macd_histogram")
        bb_upper = indicators.get("bb_upper")
        bb_lower = indicators.get("bb_lower")
        price    = indicators.get("close")
        info["rsi"]       = rsi
        info["macd_hist"] = macd_hist
        info["bb_upper"]  = bb_upper
        info["bb_lower"]  = bb_lower
        info["ema_9"]     = indicators.get("ema_9")
        info["ema_21"]    = indicators.get("ema_21")
        info["ema_50"]    = indicators.get("ema_50")
        info["adx"]       = indicators.get("adx_14")
        info["atr"]       = indicators.get("atr_14")

    info["blocks"] = blocks
    return info


# ── main ─────────────────────────────────────────────────────────────────────

def main():
    config   = load_config()
    positions = load_open_positions()

    if not positions:
        print("No open positions.")
        return

    now_sgt  = datetime.datetime.now(SGT)
    now_ts   = int(now_sgt.timestamp())
    today_str = now_sgt.strftime("%Y-%m-%d")

    print(f"\n{'='*70}")
    print(f"  OPEN POSITION CANDLE CHARTS  —  {now_sgt.strftime('%Y-%m-%d %H:%M')} SGT")
    print(f"{'='*70}\n")

    CHARTS_DIR.mkdir(exist_ok=True)

    # Group positions by pair (multiple buys on same pair → same chart)
    by_pair: dict[str, list[dict]] = {}
    for p in positions:
        by_pair.setdefault(p["pair"], []).append(p)

    # Sentiment: Fear & Greed
    try:
        fg_resp = requests.get("https://api.alternative.me/fng/?limit=1", timeout=8)
        fg_data = fg_resp.json()
        fg_val  = int(fg_data["data"][0]["value"])
        fg_cls  = fg_data["data"][0]["value_classification"]
    except Exception:
        fg_val, fg_cls = None, "unknown"

    # BTC dominance from CoinGecko
    try:
        cg_resp = requests.get("https://api.coingecko.com/api/v3/global", timeout=10)
        cg_data = cg_resp.json()
        btc_dom = round(cg_data["data"]["market_cap_percentage"]["btc"], 2)
    except Exception:
        btc_dom = None

    print(f"🌡  Market Sentiment")
    print(f"   Fear & Greed Index : {fg_val if fg_val is not None else 'N/A'} — {fg_cls}")
    print(f"   BTC Dominance      : {btc_dom if btc_dom is not None else 'N/A'}%")
    print()

    sell_analysis_rows = []

    for pair, pair_positions in by_pair.items():
        print(f"── {pair} ({len(pair_positions)} position(s)) ──────────────────────────")

        rest_name = get_rest_name(pair, config)

        # Use the earliest buy as the start anchor, then go 2 hours further back
        earliest_opened_at = min(
            datetime.datetime.fromisoformat(p["opened_at"]) for p in pair_positions
        )
        # Fetch the most recent 720 candles (720 × 15min = 180h / 7.5 days).
        # This always covers the buy time AND gives enough history for indicator computation (220+ candles).
        print(f"   Fetching latest 720 live candles for {rest_name} …")
        df = fetch_live_candles(rest_name)  # no since → Kraken returns latest 720
        if df is None or df.empty:
            print(f"   ERROR: no candle data — skipping chart")
            continue

        # Trim chart window: 2h before earliest buy → latest candle
        chart_start_ts = pd.Timestamp(
            int(earliest_opened_at.timestamp()) - 2 * 3600, unit='s', tz='UTC'
        )
        df_window = df[df.index >= chart_start_ts].copy()

        if len(df_window) < 5:
            print(f"   WARN: only {len(df_window)} candles in window — skipping")
            continue

        last_candle_time = df_window.index[-1].tz_convert(SGT).strftime('%Y-%m-%d %H:%M SGT')
        print(f"   Candles: {len(df_window)} | Window: {df_window.index[0].tz_convert(SGT).strftime('%m-%d %H:%M')} → {last_candle_time}")

        # Build buy markers list (all buys for this pair)
        buy_times: list[pd.Timestamp] = []
        buy_prices: list[float] = []
        for p in pair_positions:
            bt = pd.Timestamp(datetime.datetime.fromisoformat(p["opened_at"])).tz_convert("UTC")
            buy_times.append(bt)
            buy_prices.append(p["entry_price"])

        # Compute indicators on the full fetched data (720 candles).
        # Override min_candles_to_start to match actual available data.
        candle_list = [
            {
                "open":   row["open"],
                "high":   row["high"],
                "low":    row["low"],
                "close":  row["close"],
                "volume": row["volume"],
            }
            for _, row in df.iterrows()
        ]
        cfg_for_ind = dict(config)
        cfg_for_ind["indicators"] = dict(config.get("indicators", {}))
        cfg_for_ind["indicators"]["min_candles_to_start"] = min(len(candle_list) - 10, 220)

        indicators = compute_indicators(candle_list, cfg_for_ind)
        signal     = None

        if indicators:
            # Inject fear & greed
            if fg_val is not None:
                indicators["fear_greed_index"] = fg_val
            signal = generate_signal(pair, indicators, config)

            current_px = indicators.get("close", buy_prices[-1])
            pnl_pct = compute_buy_pnl(pair_positions[0]["entry_price"], current_px)

            rsi_v  = indicators.get('rsi_14') or 0.0
            macd_v = indicators.get('macd_histogram') or 0.0
            adx_v  = indicators.get('adx_14') or 0.0
            print(f"   RSI={rsi_v:.1f}  MACD_hist={macd_v:.5f}  "
                  f"ADX={adx_v:.1f}  Current=USD{current_px:.4f}  P&L={pnl_pct:+.2f}pct")
            print(f"   Signal: {signal['signal']}  buy_score={signal.get('buy_score',0)}  sell_score={signal.get('sell_score',0)}  "
                  f"(need buy>={signal.get('buy_min_score','?')} / sell>={signal.get('sell_min_score','?')})")
        else:
            print(f"   WARN: insufficient candles to compute indicators ({len(candle_list)} fetched)")

        # Render chart
        safe_name = pair.replace("/", "")
        chart_ts  = now_sgt.strftime("%Y%m%d-%H%M")
        out_path  = CHARTS_DIR / f"{safe_name}.{chart_ts}.png"

        # Use the representative position for the chart metadata (first/largest)
        rep_pos = pair_positions[0]
        render_chart(df_window, rep_pos, buy_times, buy_prices, indicators, signal, out_path)

        # Collect sell analysis
        analysis = analyze_sell_block(rep_pos, signal, indicators)
        analysis["pair"] = pair
        sell_analysis_rows.append(analysis)
        print()

    # ── Summary: Why are sells not happening? ────────────────────────────────
    print(f"\n{'='*70}")
    print("  SELL ANALYSIS — WHY IS SELL NOT TRIGGERING?")
    print(f"{'='*70}")

    total_blocks: dict[str, int] = {}

    for row in sell_analysis_rows:
        pair = row["pair"]
        blocks = row.get("blocks", [])
        pnl   = row.get("pnl_pct", 0)
        rsi   = row.get("rsi") or 0.0
        macd  = row.get("macd_hist") or 0.0
        adx   = row.get("adx") or 0.0
        ema9  = row.get("ema_9") or 0.0
        ema21 = row.get("ema_21") or 0.0
        bb_up = row.get("bb_upper") or 0.0

        print(f"\n  {pair:15s}  P&L={pnl:+.2f}pct  RSI={rsi:.1f}  "
              f"MACD_hist={macd:.5f}  ADX={adx:.1f}")

        if blocks:
            for b in blocks:
                print(f"    [BLOCK] {b}")
                key = b.split(":")[0]
                total_blocks[key] = total_blocks.get(key, 0) + 1
        else:
            print(f"    [OK] No risk-manager blocks (signal is {row.get('signal','?')})")

        sell_sc = row.get("sell_score", 0)
        sell_mn = row.get("sell_min_score", 3)
        print(f"    INFO sell_score={sell_sc}/{sell_mn}  ema9={ema9:.4f}  "
              f"ema21={ema21:.4f}  bb_upper={bb_up:.4f}")

    print(f"\n{'='*70}")
    print("  ROOT CAUSE SUMMARY")
    print(f"{'='*70}")
    for reason, count in sorted(total_blocks.items(), key=lambda x: -x[1]):
        print(f"  {count:2d} pair(s) blocked by: {reason}")

    print(f"  SELL TRIGGERS (what would unlock a sell):")
    print(f"  * SIGNAL:     RSI > rsi_overbought (pair-specific, global=75)")
    print(f"                + MACD hist < 0 (+2)  + Price >= BB upper (+2) -> sell_score >= 3")
    print(f"  * GUARD:      P&L must reach 60pct of TP target  (pair-specific)")
    print(f"  * GUARD:      P&L must be >= +1.0pct (minimum profit floor)")
    print()
    print(f"  MARKET SENTIMENT:")
    print(f"  * Fear & Greed: {fg_val} -- {fg_cls}")
    print(f"  * BTC Dominance: {btc_dom}pct")
    if fg_val is not None:
        if fg_val <= 25:
            print(f"  WARNING: EXTREME FEAR -- favours buys, not sells. Agent unlikely to propose sells.")
        elif fg_val <= 40:
            print(f"  WARNING: FEAR zone -- still supportive for long positions.")
        elif fg_val >= 70:
            print(f"  NOTE: GREED zone -- more likely to hit RSI overbought -> SELL signal possible.")
    print()
    print(f"  Charts saved to: charts/")
    print()


if __name__ == "__main__":
    main()
