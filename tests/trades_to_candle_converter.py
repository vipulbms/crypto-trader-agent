"""Convert raw Kraken trade exports into Kraken-style OHLC candle JSON.

Examples:
    python tests/trades_to_candle_converter.py \
        /path/to/kraken_trades_12months.csv|history/XXBTZUSD_candle.json

    python tests/trades_to_candle_converter.py \
        /path/to/sol.csv|history/SOLUSD_candle.json \
        /path/to/xrp.csv|history/XRPUSD_candle.json

Default 3-column CSV layout:
    timestamp,price,volume

Example row:
    1538142307,0.3,0.00031847
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path

import pandas as pd


TIMESTAMP_ALIASES = ("timestamp", "time", "datetime", "date", "ts")
PRICE_ALIASES = ("price", "trade_price", "rate")
VOLUME_ALIASES = ("volume", "qty", "quantity", "amount", "size")


@dataclass(frozen=True)
class ConversionJob:
    input_path: Path
    pair_key: str
    output_path: Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Convert Kraken trade CSV exports into Kraken-style candle JSON. "
            "Headerless 3-column files default to timestamp,price,volume. "
            "Pass one or more <source>|<target> job specs for batch conversion."
        )
    )
    parser.add_argument(
        "job_specs",
        nargs="+",
        help="One or more conversion jobs in the form <source file>|<target file>.",
    )
    parser.add_argument(
        "--interval-minutes",
        type=int,
        default=15,
        help="Candle interval in minutes. Default: 15",
    )
    parser.add_argument(
        "--timestamp-column",
        help="Timestamp column name or 0-based column index override",
    )
    parser.add_argument(
        "--price-column",
        help="Price column name or 0-based column index override",
    )
    parser.add_argument(
        "--volume-column",
        help="Volume column name or 0-based column index override",
    )
    parser.add_argument(
        "--timestamp-unit",
        choices=("s", "ms", "us", "ns"),
        help="Force numeric timestamp unit instead of auto-detecting",
    )
    parser.add_argument(
        "--sparse",
        action="store_true",
        help="Do not fill empty candle intervals between the first and last trade",
    )
    return parser.parse_args()


def normalize_name(value: object) -> str:
    return str(value).strip().lower().replace(" ", "_")


def resolve_column(
    df: pd.DataFrame,
    override: str | None,
    aliases: tuple[str, ...],
    fallback_index: int,
) -> object:
    if override is not None:
        if override.isdigit():
            index = int(override)
            if index >= len(df.columns):
                raise ValueError(f"Column index {index} is out of range")
            return df.columns[index]

        normalized = {normalize_name(column): column for column in df.columns}
        key = normalize_name(override)
        if key not in normalized:
            raise ValueError(f"Column '{override}' was not found in the CSV")
        return normalized[key]

    normalized = {normalize_name(column): column for column in df.columns}
    for alias in aliases:
        if alias in normalized:
            return normalized[alias]

    if fallback_index >= len(df.columns):
        raise ValueError("CSV does not contain enough columns to infer timestamp, price, and volume")
    return df.columns[fallback_index]


def infer_timestamp_unit(series: pd.Series) -> str:
    sample = pd.to_numeric(series, errors="coerce").dropna()
    if sample.empty:
        return "s"

    magnitude = abs(sample.iloc[0])
    if magnitude >= 10**18:
        return "ns"
    if magnitude >= 10**15:
        return "us"
    if magnitude >= 10**12:
        return "ms"
    return "s"


def parse_timestamps(series: pd.Series, forced_unit: str | None) -> pd.Series:
    numeric = pd.to_numeric(series, errors="coerce")
    if numeric.notna().all():
        unit = forced_unit or infer_timestamp_unit(numeric)
        return pd.to_datetime(numeric, unit=unit, utc=True, errors="coerce")

    return pd.to_datetime(series, utc=True, errors="coerce")


def looks_like_header(first_row: pd.Series) -> bool:
    normalized = {normalize_name(value) for value in first_row.tolist()}
    return (
        any(alias in normalized for alias in TIMESTAMP_ALIASES)
        and any(alias in normalized for alias in PRICE_ALIASES)
        and any(alias in normalized for alias in VOLUME_ALIASES)
    )


def parse_job_spec(job_spec: str) -> tuple[Path, Path]:
    source_value, separator, target_value = job_spec.partition("|")
    if separator != "|" or not source_value.strip() or not target_value.strip():
        raise ValueError(
            f"Invalid job spec '{job_spec}'. Expected format: <source file>|<target file>"
        )
    return Path(source_value.strip()), Path(target_value.strip())


def infer_pair_key(output_path: Path) -> str:
    stem = output_path.stem
    if stem.endswith("_candle"):
        stem = stem[: -len("_candle")]
    if not stem:
        raise ValueError(f"Could not infer pair key from output path: {output_path}")
    return stem


def build_jobs(args: argparse.Namespace) -> list[ConversionJob]:
    jobs: list[ConversionJob] = []
    for job_spec in args.job_specs:
        input_path, output_path = parse_job_spec(job_spec)
        jobs.append(
            ConversionJob(
                input_path=input_path,
                pair_key=infer_pair_key(output_path),
                output_path=output_path,
            )
        )
    return jobs


def load_trades(args: argparse.Namespace, input_path: str | Path | None = None) -> pd.DataFrame:
    if input_path is not None:
        resolved_input = Path(input_path)
    elif hasattr(args, "inputs") and args.inputs:
        resolved_input = Path(args.inputs[0])
    else:
        resolved_input, _ = parse_job_spec(args.job_specs[0])
    if not resolved_input.exists():
        raise FileNotFoundError(f"Input CSV not found: {resolved_input}")

    frame = pd.read_csv(resolved_input, header=None)
    if not frame.empty and looks_like_header(frame.iloc[0]):
        frame.columns = [str(value) for value in frame.iloc[0].tolist()]
        frame = frame.iloc[1:].reset_index(drop=True)

    timestamp_column = resolve_column(frame, args.timestamp_column, TIMESTAMP_ALIASES, 0)
    price_column = resolve_column(frame, args.price_column, PRICE_ALIASES, 1)
    volume_column = resolve_column(frame, args.volume_column, VOLUME_ALIASES, 2)

    trades = pd.DataFrame(
        {
            "timestamp": parse_timestamps(frame[timestamp_column], args.timestamp_unit),
            "price": pd.to_numeric(frame[price_column], errors="coerce"),
            "volume": pd.to_numeric(frame[volume_column], errors="coerce"),
        }
    )

    trades = trades.dropna(subset=["timestamp", "price", "volume"])
    trades = trades[trades["volume"] >= 0]
    trades = trades.sort_values("timestamp")
    if trades.empty:
        raise ValueError("No valid trade rows were found after parsing the CSV")

    return trades.set_index("timestamp")


def build_candles(trades: pd.DataFrame, interval_minutes: int, sparse: bool) -> pd.DataFrame:
    rule = f"{interval_minutes}min"
    volume = trades["volume"].resample(rule, label="left", closed="left").sum()
    count = trades["price"].resample(rule, label="left", closed="left").count()

    candles = trades.resample(rule, label="left", closed="left").agg(
        open=("price", "first"),
        high=("price", "max"),
        low=("price", "min"),
        close=("price", "last"),
    )
    candles["volume"] = volume
    candles["count"] = count.astype(int)

    weighted_price = (trades["price"] * trades["volume"]).resample(rule, label="left", closed="left").sum()
    candles["vwap"] = weighted_price.div(candles["volume"].where(candles["volume"] != 0))

    if not sparse:
        full_index = pd.date_range(
            start=candles.index.min(),
            end=candles.index.max(),
            freq=rule,
            tz="UTC",
        )
        candles = candles.reindex(full_index)
        previous_close = candles["close"].ffill()
        candles["open"] = candles["open"].fillna(previous_close)
        candles["high"] = candles["high"].fillna(previous_close)
        candles["low"] = candles["low"].fillna(previous_close)
        candles["close"] = candles["close"].fillna(previous_close)
        candles["vwap"] = candles["vwap"].fillna(0.0)
        candles["volume"] = candles["volume"].fillna(0.0)
        candles["count"] = candles["count"].fillna(0).astype(int)

    candles = candles.dropna(subset=["open", "high", "low", "close"])
    return candles


def format_number(value: float, precision: int) -> str:
    text = f"{value:.{precision}f}".rstrip("0").rstrip(".")
    if "." not in text:
        return f"{text}.0"
    return text


def build_payload(pair_key: str, candles: pd.DataFrame) -> dict:
    rows = []
    for timestamp, candle in candles.iterrows():
        rows.append(
            [
                int(timestamp.timestamp()),
                format_number(float(candle["open"]), 10),
                format_number(float(candle["high"]), 10),
                format_number(float(candle["low"]), 10),
                format_number(float(candle["close"]), 10),
                format_number(float(candle["vwap"]), 10),
                format_number(float(candle["volume"]), 8),
                int(candle["count"]),
            ]
        )

    last = rows[-1][0] if rows else 0
    return {
        "error": [],
        "result": {
            pair_key: rows,
            "last": last,
        },
    }


def convert_file(args: argparse.Namespace, job: ConversionJob) -> dict:
    trades = load_trades(args, input_path=job.input_path)
    candles = build_candles(trades, args.interval_minutes, args.sparse)
    payload = build_payload(job.pair_key, candles)

    job.output_path.parent.mkdir(parents=True, exist_ok=True)
    job.output_path.write_text(json.dumps(payload, separators=(",", ":")))
    return payload


def main() -> None:
    args = parse_args()
    jobs = build_jobs(args)
    for job in jobs:
        payload = convert_file(args, job)
        print(
            f"Wrote {len(payload['result'][job.pair_key])} candles for {job.pair_key} "
            f"to {job.output_path}"
        )


if __name__ == "__main__":
    main()