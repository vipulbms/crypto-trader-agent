import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from trades_to_candle_converter import build_candles, build_jobs, build_payload, load_trades


class TradeConverterTests(unittest.TestCase):
    def test_headerless_timestamp_price_volume_csv_converts_to_15m_kraken_json(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            csv_path = Path(tmp_dir) / "sol_trades.csv"
            output_path = Path(tmp_dir) / "SOLUSD_candle.json"
            csv_path.write_text(
                "1711929600,91.82,100\n"
                "1711929660,92.10,50\n"
                "1711930500,91.75,25\n"
            )

            args = Namespace(
                job_specs=[f"{csv_path}|{output_path}"],
                interval_minutes=15,
                timestamp_column=None,
                price_column=None,
                volume_column=None,
                timestamp_unit="s",
                sparse=False,
            )

            trades = load_trades(args, input_path=csv_path)
            candles = build_candles(trades, args.interval_minutes, args.sparse)
            payload = build_payload("SOLUSD", candles)

            self.assertEqual(payload["error"], [])
            self.assertIn("SOLUSD", payload["result"])
            self.assertEqual(payload["result"]["last"], 1711930500)
            self.assertEqual(
                payload["result"]["SOLUSD"],
                [
                    [1711929600, "91.82", "92.1", "91.82", "92.1", "91.9133333333", "150.0", 2],
                    [1711930500, "91.75", "91.75", "91.75", "91.75", "91.75", "25.0", 1],
                ],
            )

    def test_batch_job_builder_maps_each_job_spec_to_pair_and_output(self):
        args = Namespace(
            job_specs=[
                "/tmp/sol.csv|history/SOLUSD_candle.json",
                "/tmp/xrp.csv|history/XRPUSD_candle.json",
            ],
            interval_minutes=15,
            timestamp_column=None,
            price_column=None,
            volume_column=None,
            timestamp_unit="s",
            sparse=False,
        )

        jobs = build_jobs(args)

        self.assertEqual(len(jobs), 2)
        self.assertEqual(str(jobs[0].input_path), "/tmp/sol.csv")
        self.assertEqual(jobs[0].pair_key, "SOLUSD")
        self.assertEqual(jobs[0].output_path, Path("history") / "SOLUSD_candle.json")
        self.assertEqual(str(jobs[1].input_path), "/tmp/xrp.csv")
        self.assertEqual(jobs[1].pair_key, "XRPUSD")
        self.assertEqual(jobs[1].output_path, Path("history") / "XRPUSD_candle.json")


if __name__ == "__main__":
    unittest.main()