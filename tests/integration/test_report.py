import datetime
import tempfile
from pathlib import Path

import pandas as pd

from src.report import write_report

RESULTS = [
    {"Ticker": "A.T", "Priority_Rank": 2, "Stage2_Candidate": False, "Extra": "x"},
    {"Ticker": "B.T", "Priority_Rank": 1, "Stage2_Candidate": True, "Extra": "y"},
]


class TestReport:
    def test_writes_configured_dir_filename_and_columns(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp) / "nested" / "results"  # created if missing
            path = write_report(RESULTS, out_dir, "out_{date}.csv", ["Priority_Rank", "Ticker", "Missing"])
            today = datetime.datetime.now().strftime("%Y-%m-%d")
            assert path == (out_dir / f"out_{today}.csv")
            df = pd.read_csv(path)
            assert df.columns.tolist() == (["Priority_Rank", "Ticker"])
            assert df["Ticker"].tolist() == (["B.T", "A.T"])  # sorted by rank
