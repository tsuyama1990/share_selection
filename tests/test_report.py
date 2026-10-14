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


def row(ticker, cls, yld=None, psr=1.0, flags=""):
    return {
        "Ticker": ticker,
        "Improvement_Class": cls,
        "Improvement_Yield(%)": yld,
        "Real_PSR": psr,
        "Quality_Flags": flags,
    }


class TestPrioritize(unittest.TestCase):
    def test_orders_by_class_yield_then_psr_and_flags_clear_candidates(self):
        rows = [
            row("none", "none", yld=-1.0),
            row("sig", "signal", yld=9.0),  # a higher yield never beats a better class
            row("clear_no_yield", "clear"),
            row("clear_lo", "clear", yld=2.0),
            row("clear_hi_psr", "clear", yld=5.0, psr=0.9),
            row("clear_lo_psr", "clear", yld=5.0, psr=0.3),
            row("unk", "unknown"),
        ]
        prioritize(rows, 3)
        ranked = sorted(rows, key=lambda r: r["Priority_Rank"])
        self.assertEqual(
            [r["Ticker"] for r in ranked],
            ["clear_lo_psr", "clear_hi_psr", "clear_lo", "clear_no_yield", "sig", "none", "unk"],
        )
        self.assertEqual([r["Stage2_Candidate"] for r in ranked], [True, True, True, False, False, False, False])

    def test_candidates_are_clear_only_even_within_n(self):
        rows = [row("a", "clear", yld=5.0), row("b", "signal", yld=5.0)]
        prioritize(rows, 5)
        self.assertEqual([r["Stage2_Candidate"] for r in rows], [True, False])

    def test_flagged_rows_keep_rank_but_are_skipped_and_slots_refilled(self):
        rows = [
            row("flagged", "clear", yld=9.0, flags="quarter_spike"),
            row("a", "clear", yld=5.0),
            row("b", "clear", yld=4.0),
            row("c", "clear", yld=3.0),
        ]
        prioritize(rows, 2)
        ranked = sorted(rows, key=lambda r: r["Priority_Rank"])
        self.assertEqual([r["Ticker"] for r in ranked], ["flagged", "a", "b", "c"])
        self.assertEqual([r["Stage2_Candidate"] for r in ranked], [False, True, True, False])
