import datetime
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from src.report import prioritize, write_report

RESULTS = [
    {"Ticker": "A.T", "Priority_Rank": 2, "Stage2_Candidate": False, "Extra": "x"},
    {"Ticker": "B.T", "Priority_Rank": 1, "Stage2_Candidate": True, "Extra": "y"},
]


class TestReport(unittest.TestCase):
    def test_writes_configured_dir_filename_and_columns(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp) / "nested" / "results"  # created if missing
            path = write_report(RESULTS, out_dir, "out_{date}.csv", ["Priority_Rank", "Ticker", "Missing"])
            today = datetime.datetime.now().strftime("%Y-%m-%d")
            self.assertEqual(path, out_dir / f"out_{today}.csv")
            df = pd.read_csv(path)
            self.assertEqual(df.columns.tolist(), ["Priority_Rank", "Ticker"])
            self.assertEqual(df["Ticker"].tolist(), ["B.T", "A.T"])  # sorted by rank


def row(ticker, cls, eps=None, oi=None, psr=1.0):
    return {"Ticker": ticker, "Improvement_Class": cls, "EPS_Q_YoY(%)": eps, "OI_YoY(%)": oi, "Real_PSR": psr}


class TestPrioritize(unittest.TestCase):
    def test_orders_by_class_growth_then_psr_and_flags_clear_candidates(self):
        rows = [
            row("none", "none", eps=-5.0),
            row("sig", "signal", eps=10.0),
            row("oi", "clear", oi=60.0),
            row("eps_hi_psr", "clear", eps=80.0, oi=500.0, psr=0.9),
            row("eps_lo_psr", "clear", eps=80.0, psr=0.3),
            row("unk", "unknown"),
        ]
        prioritize(rows, 3)
        ranked = sorted(rows, key=lambda r: r["Priority_Rank"])
        self.assertEqual([r["Ticker"] for r in ranked], ["eps_lo_psr", "eps_hi_psr", "oi", "sig", "none", "unk"])
        self.assertEqual([r["Stage2_Candidate"] for r in ranked], [True, True, True, False, False, False])

    def test_candidates_are_clear_only_even_within_n(self):
        rows = [row("a", "clear", eps=50.0), row("b", "signal", eps=5.0)]
        prioritize(rows, 5)
        self.assertEqual([r["Stage2_Candidate"] for r in rows], [True, False])


if __name__ == "__main__":
    unittest.main()
