import datetime
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from src.report import write_report

RESULTS = [
    {'Ticker': 'A.T', 'Total_Score': 1, 'Extra': 'x'},
    {'Ticker': 'B.T', 'Total_Score': 5, 'Extra': 'y'},
]


class TestReport(unittest.TestCase):

    def test_writes_configured_dir_filename_and_columns(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp) / 'nested' / 'results'  # created if missing
            path = write_report(RESULTS, out_dir, 'out_{date}.csv', ['Total_Score', 'Ticker', 'Missing'], 1)
            today = datetime.datetime.now().strftime('%Y-%m-%d')
            self.assertEqual(path, out_dir / f'out_{today}.csv')
            df = pd.read_csv(path)
            self.assertEqual(df.columns.tolist(), ['Total_Score', 'Ticker'])
            self.assertEqual(df['Ticker'].tolist(), ['B.T', 'A.T'])  # sorted by score


if __name__ == '__main__':
    unittest.main()
