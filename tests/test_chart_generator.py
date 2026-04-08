"""
Tests for src/reports/chart_generator.py  (issues #99, #100).

We avoid real matplotlib rendering by patching `fig.savefig` and
`mplfinance.plot`, so the tests run headless and fast.
"""

import json
import os
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch
import sys

import numpy as np
import pandas as pd
import pytest

# Make sure the src package is on the path when running from project root.
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.reports.chart_generator import (
    DEFAULT_WINDOW,
    EXIT_COLOURS,
    _candle_window,
    _parse_ts,
    generate_charts,
    load_candles,
    load_trades,
    render_trade_chart,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _make_db(path: str = ":memory:") -> sqlite3.Connection:
    """Create a paper_trades table with all columns chart_generator expects."""
    conn = sqlite3.connect(path)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS paper_trades (
            id          INTEGER PRIMARY KEY,
            pair        TEXT,
            side        TEXT,
            entry_price REAL,
            exit_price  REAL,
            pnl_pct     REAL,
            pnl_usd     REAL,
            opened_at   TEXT,
            closed_at   TEXT,
            exit_reason TEXT,
            amount      REAL
        )
        """
    )
    conn.commit()
    return conn


def _insert_trade(conn: sqlite3.Connection, **kwargs) -> None:
    defaults = dict(
        pair="ETH/USD",
        side="buy",
        entry_price=2000.0,
        exit_price=2100.0,
        pnl_pct=5.0,
        pnl_usd=100.0,
        opened_at="2025-03-01T10:00:00",
        closed_at="2025-03-01T12:00:00",
        exit_reason="take_profit",
        amount=0.05,
    )
    defaults.update(kwargs)
    conn.execute(
        """
        INSERT INTO paper_trades
            (pair, side, entry_price, exit_price, pnl_pct, pnl_usd,
             opened_at, closed_at, exit_reason, amount)
        VALUES
            (:pair, :side, :entry_price, :exit_price, :pnl_pct, :pnl_usd,
             :opened_at, :closed_at, :exit_reason, :amount)
        """,
        defaults,
    )
    conn.commit()


def _make_candle_df(n: int = 200) -> pd.DataFrame:
    """Return a small OHLCV DataFrame spanning *n* 15-min candles."""
    start = pd.Timestamp("2025-03-01T09:00:00", tz="UTC")
    idx   = pd.date_range(start, periods=n, freq="15min", tz="UTC")
    rng   = np.random.default_rng(42)
    close = 2000.0 + rng.normal(0, 20, n).cumsum()
    data  = {
        "open":   close - rng.uniform(0, 5, n),
        "high":   close + rng.uniform(0, 10, n),
        "low":    close - rng.uniform(0, 10, n),
        "close":  close,
        "volume": rng.uniform(1, 100, n),
    }
    return pd.DataFrame(data, index=idx)


def _make_candle_json(pair_key: str, n: int = 200) -> dict:
    """Return a Kraken-style candle JSON dict suitable for load_candles."""
    start = 1740823200  # 2025-03-01 09:00 UTC
    rows  = []
    rng   = np.random.default_rng(0)
    price = 2000.0
    for i in range(n):
        ts    = start + i * 900
        close = price + rng.normal(0, 5)
        rows.append([ts, price, close + 5, close - 5, close, close, 10.0, 5])
        price = close
    return {"result": {pair_key: rows, "last": start + n * 900}}


# ── load_trades ───────────────────────────────────────────────────────────────

class TestLoadTrades:
    def test_returns_empty_when_no_trades(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            conn = _make_db(db_path)
            conn.close()
            assert load_trades(db_path) == []
        finally:
            os.unlink(db_path)

    def test_returns_open_positions_excluded(self):
        """Only closed trades (closed_at IS NOT NULL) should be returned."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            conn = _make_db(db_path)
            # One closed trade, one open trade
            _insert_trade(conn, closed_at="2025-03-01T12:00:00")
            _insert_trade(conn, closed_at=None)
            conn.close()
            trades = load_trades(db_path)
            assert len(trades) == 1
            assert trades[0]["closed_at"] == "2025-03-01T12:00:00"
        finally:
            os.unlink(db_path)

    def test_pair_filter(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            conn = _make_db(db_path)
            _insert_trade(conn, pair="ETH/USD", closed_at="2025-03-01T12:00:00")
            _insert_trade(conn, pair="BTC/USD", closed_at="2025-03-02T12:00:00")
            conn.close()
            trades = load_trades(db_path, pair_filter="ETH/USD")
            assert len(trades) == 1
            assert trades[0]["pair"] == "ETH/USD"
        finally:
            os.unlink(db_path)

    def test_returns_dict_rows(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            conn = _make_db(db_path)
            _insert_trade(conn, closed_at="2025-03-01T12:00:00")
            conn.close()
            trades = load_trades(db_path)
            assert isinstance(trades[0], dict)
            assert "pair" in trades[0]
            assert "pnl_pct" in trades[0]
        finally:
            os.unlink(db_path)


# ── load_candles ──────────────────────────────────────────────────────────────

class TestLoadCandles:
    def test_raises_for_unknown_pair(self, tmp_path):
        with pytest.raises(ValueError, match="No history file mapping"):
            load_candles("FAKE/USD", str(tmp_path))

    def test_raises_when_file_missing(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_candles("ETH/USD", str(tmp_path))

    def test_returns_dataframe_with_ohlcv(self, tmp_path):
        candle_json = _make_candle_json("ETHUSD")
        (tmp_path / "ETHUSD_candle.json").write_text(json.dumps(candle_json))
        df = load_candles("ETH/USD", str(tmp_path))
        assert isinstance(df, pd.DataFrame)
        assert list(df.columns) == ["open", "high", "low", "close", "volume"]
        assert len(df) > 0
        assert df.index.tz is not None  # UTC-aware

    def test_index_is_sorted(self, tmp_path):
        candle_json = _make_candle_json("ETHUSD")
        (tmp_path / "ETHUSD_candle.json").write_text(json.dumps(candle_json))
        df = load_candles("ETH/USD", str(tmp_path))
        assert df.index.is_monotonic_increasing


# ── _parse_ts ─────────────────────────────────────────────────────────────────

class TestParseTs:
    def test_naive_string_gets_utc(self):
        ts = _parse_ts("2025-03-01T10:00:00")
        assert ts.tz is not None

    def test_tz_aware_string_preserved(self):
        ts = _parse_ts("2025-03-01T10:00:00+00:00")
        assert ts.tz is not None

    def test_returns_pandas_timestamp(self):
        ts = _parse_ts("2025-03-01T10:00:00")
        assert isinstance(ts, pd.Timestamp)


# ── _candle_window ────────────────────────────────────────────────────────────

class TestCandleWindow:
    def setup_method(self):
        self.df = _make_candle_df(200)

    def test_returns_subset_of_df(self):
        entry = pd.Timestamp("2025-03-01T12:00:00", tz="UTC")
        exit_ = pd.Timestamp("2025-03-01T14:00:00", tz="UTC")
        window = _candle_window(self.df, entry, exit_, 10)
        assert len(window) <= len(self.df)
        assert len(window) > 0

    def test_window_includes_padding(self):
        # Pick mid-range timestamps so padding has room on both sides
        entry = pd.Timestamp("2025-03-01T18:00:00", tz="UTC")  # ~36 candles in
        exit_ = pd.Timestamp("2025-03-01T20:00:00", tz="UTC")  # ~8 candles later
        window_small = _candle_window(self.df, entry, exit_, 5)
        window_large = _candle_window(self.df, entry, exit_, 15)
        assert len(window_large) > len(window_small)

    def test_clamps_to_df_bounds(self):
        # Request padding that would go before index start
        entry = self.df.index[1]
        exit_ = self.df.index[3]
        window = _candle_window(self.df, entry, exit_, 1000)
        assert len(window) <= len(self.df)


# ── render_trade_chart ────────────────────────────────────────────────────────

class TestRenderTradeChart:
    """Verify render_trade_chart writes a file without doing real rendering."""

    def _make_trade(self, exit_reason: str = "take_profit") -> dict:
        return dict(
            pair="ETH/USD",
            entry_price=2000.0,
            exit_price=2100.0,
            pnl_pct=5.0,
            pnl_usd=100.0,
            opened_at="2025-03-01T12:00:00",
            closed_at="2025-03-01T14:00:00",
            exit_reason=exit_reason,
            amount=0.05,
        )

    def test_creates_output_file(self, tmp_path):
        df = _make_candle_df(200)
        trade = self._make_trade()
        out_path = tmp_path / "chart.png"

        # Patch mpf.plot to avoid real matplotlib rendering
        mock_fig  = MagicMock()
        mock_axes = [MagicMock(), MagicMock()]
        mock_axes[0].axhline = MagicMock()
        mock_axes[0].legend  = MagicMock()

        with patch("src.reports.chart_generator.mpf.plot", return_value=(mock_fig, mock_axes)):
            render_trade_chart(df, trade, 1, 1, out_path)

        mock_fig.savefig.assert_called_once()
        # Verify the path argument contains our out_path
        call_args = mock_fig.savefig.call_args
        assert str(out_path) in str(call_args)

    def test_uses_correct_sell_colour_for_each_exit_reason(self, tmp_path):
        """The sell series marker should reflect the exit reason colour."""
        df = _make_candle_df(200)

        for reason, expected_colour in EXIT_COLOURS.items():
            trade = self._make_trade(exit_reason=reason)
            out_path = tmp_path / f"chart_{reason}.png"

            mock_fig  = MagicMock()
            mock_axes = [MagicMock(), MagicMock()]
            mock_axes[0].axhline = MagicMock()
            mock_axes[0].legend  = MagicMock()

            captured_addplots = []

            def capturing_plot(*args, **kwargs):
                captured_addplots.extend(kwargs.get("addplot") or [])
                return (mock_fig, mock_axes)

            with patch("src.reports.chart_generator.mpf.plot", side_effect=capturing_plot):
                with patch("src.reports.chart_generator.mpf.make_addplot",
                           side_effect=lambda *a, **kw: kw) as mock_addplot:
                    render_trade_chart(df, trade, 1, 1, out_path)
                    # Check that a sell addplot was requested with the right colour
                    calls = mock_addplot.call_args_list
                    sell_calls = [c for c in calls if c.kwargs.get("color") == expected_colour]
                    assert len(sell_calls) >= 1, (
                        f"No addplot with colour {expected_colour} for exit_reason={reason}"
                    )

    def test_legend_contains_all_marker_types(self, tmp_path):
        """Legend should have handles for all 5 exit types + 2 price lines."""
        df = _make_candle_df(200)
        trade = self._make_trade()
        out_path = tmp_path / "chart.png"

        mock_fig  = MagicMock()
        mock_axes = [MagicMock(), MagicMock()]
        mock_axes[0].axhline = MagicMock()
        legend_call_kwargs: dict = {}

        def capture_legend(handles=None, **kwargs):
            legend_call_kwargs["handles"] = handles

        mock_axes[0].legend = capture_legend

        with patch("src.reports.chart_generator.mpf.plot", return_value=(mock_fig, mock_axes)):
            render_trade_chart(df, trade, 1, 1, out_path)

        handles = legend_call_kwargs.get("handles", [])
        assert handles is not None, "legend() was never called"
        labels = [h.get_label() for h in handles]

        assert any("BUY" in lbl for lbl in labels), f"BUY label missing, got: {labels}"
        assert any("Take Profit" in lbl for lbl in labels), f"TP label missing, got: {labels}"
        assert any("Stop Loss" in lbl for lbl in labels), f"SL label missing, got: {labels}"
        assert any("Agent Sell" in lbl for lbl in labels), f"Agent Sell label missing, got: {labels}"
        assert any("Partial" in lbl for lbl in labels), f"Partial TP label missing, got: {labels}"
        # Two dashed price lines in legend
        price_line_labels = [lbl for lbl in labels if "price" in lbl.lower()]
        assert len(price_line_labels) >= 2, f"Expected 2 price lines in legend, got: {price_line_labels}"


# ── generate_charts ───────────────────────────────────────────────────────────

class TestGenerateCharts:
    def test_raises_when_db_missing(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="DB not found"):
            generate_charts(str(tmp_path / "nonexistent.db"))

    def test_returns_empty_list_when_no_trades(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        conn = _make_db(db_path)
        conn.close()
        result = generate_charts(db_path, quiet=True)
        assert result == []

    def test_returns_chart_paths_for_trades(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        conn = _make_db(db_path)
        _insert_trade(conn, pair="ETH/USD", closed_at="2025-03-01T14:00:00")
        conn.close()

        # Write fake candle file for ETH/USD
        candle_json = _make_candle_json("ETHUSD")
        (tmp_path / "ETHUSD_candle.json").write_text(json.dumps(candle_json))

        out_dir = str(tmp_path / "charts")

        mock_fig  = MagicMock()
        mock_axes = [MagicMock(), MagicMock()]
        mock_axes[0].axhline = MagicMock()
        mock_axes[0].legend  = MagicMock()

        with patch("src.reports.chart_generator.mpf.plot", return_value=(mock_fig, mock_axes)):
            result = generate_charts(
                db_path,
                out_dir=out_dir,
                history_dir=str(tmp_path),
                quiet=True,
            )

        assert len(result) == 1
        assert result[0].name == "ETHUSD_001.png"

    def test_skips_pair_without_history(self, tmp_path):
        """Pairs with no history file should be skipped gracefully (no crash)."""
        db_path = str(tmp_path / "test.db")
        conn = _make_db(db_path)
        _insert_trade(conn, pair="ETH/USD", closed_at="2025-03-01T14:00:00")
        conn.close()
        # No candle file written — history_dir is empty
        result = generate_charts(
            db_path,
            out_dir=str(tmp_path / "charts"),
            history_dir=str(tmp_path),
            quiet=True,
        )
        assert result == []

    def test_pair_filter_limits_output(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        conn = _make_db(db_path)
        _insert_trade(conn, pair="ETH/USD", closed_at="2025-03-01T14:00:00")
        _insert_trade(conn, pair="BTC/USD", closed_at="2025-03-02T14:00:00")
        conn.close()

        # Only write ETH candles
        candle_json = _make_candle_json("ETHUSD")
        (tmp_path / "ETHUSD_candle.json").write_text(json.dumps(candle_json))

        mock_fig  = MagicMock()
        mock_axes = [MagicMock(), MagicMock()]
        mock_axes[0].axhline = MagicMock()
        mock_axes[0].legend  = MagicMock()

        with patch("src.reports.chart_generator.mpf.plot", return_value=(mock_fig, mock_axes)):
            result = generate_charts(
                db_path,
                out_dir=str(tmp_path / "charts"),
                history_dir=str(tmp_path),
                pair_filter="ETH/USD",
                quiet=True,
            )

        assert all("ETH" in str(p) for p in result)
        assert len(result) == 1

    def test_multiple_trades_same_pair_numbered(self, tmp_path):
        """Multiple trades for one pair should produce sequentially numbered files."""
        db_path = str(tmp_path / "test.db")
        conn = _make_db(db_path)
        _insert_trade(conn, pair="ETH/USD", opened_at="2025-03-01T10:00:00",
                      closed_at="2025-03-01T14:00:00")
        _insert_trade(conn, pair="ETH/USD", opened_at="2025-03-02T10:00:00",
                      closed_at="2025-03-02T14:00:00")
        conn.close()

        candle_json = _make_candle_json("ETHUSD", n=400)
        (tmp_path / "ETHUSD_candle.json").write_text(json.dumps(candle_json))

        mock_fig  = MagicMock()
        mock_axes = [MagicMock(), MagicMock()]
        mock_axes[0].axhline = MagicMock()
        mock_axes[0].legend  = MagicMock()

        with patch("src.reports.chart_generator.mpf.plot", return_value=(mock_fig, mock_axes)):
            result = generate_charts(
                db_path,
                out_dir=str(tmp_path / "charts"),
                history_dir=str(tmp_path),
                quiet=True,
            )

        names = [p.name for p in result]
        assert "ETHUSD_001.png" in names
        assert "ETHUSD_002.png" in names
