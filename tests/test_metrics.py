import unittest

import numpy as np
import pandas as pd

from src.metrics import avg_turnover, first_valid, latest_valid_period, sales_cagr, to_num


class TestMetrics(unittest.TestCase):

    def test_sales_cagr_four_years(self):
        fin = pd.DataFrame({
            '2023': {'Total Revenue': 200},
            '2022': {'Total Revenue': 150},
            '2021': {'Total Revenue': 120},
            '2020': {'Total Revenue': 100},
            '2019': {'Total Revenue': 80}
        })
        fin.columns = pd.to_datetime(fin.columns, format='%Y')
        cagr, years = sales_cagr(fin, 4)
        # (200 / 80) ** (1/4) - 1 = 25.74%
        self.assertEqual(round(cagr * 100, 2), 25.74)
        self.assertEqual(years, 4)

    def test_sales_cagr_insufficient_data(self):
        fin = pd.DataFrame({
            '2023': {'Total Revenue': 200},
            '2022': {'Total Revenue': 150},
            '2021': {'Total Revenue': 120}
        })
        fin.columns = pd.to_datetime(fin.columns, format='%Y')
        self.assertEqual(sales_cagr(fin, 4), (None, None))

    def test_sales_cagr_uses_oldest_valid_period(self):
        # yfinance often leaves the oldest period NaN -> fall back to 3 years
        fin = pd.DataFrame({
            '2026': {'Total Revenue': 133.1},
            '2025': {'Total Revenue': 121},
            '2024': {'Total Revenue': 110},
            '2023': {'Total Revenue': 100},
            '2022': {'Total Revenue': np.nan}
        })
        cagr, years = sales_cagr(fin)
        self.assertEqual(years, 3)
        self.assertAlmostEqual(cagr, 0.10)

    def test_to_num(self):
        self.assertEqual(to_num('3'), 3.0)
        self.assertIsNone(to_num(None))
        self.assertIsNone(to_num(np.nan))
        self.assertIsNone(to_num('x'))

    def test_first_valid_skips_nan(self):
        row = pd.Series({'a': np.nan, 'b': 5})
        self.assertEqual(first_valid(row, ('a', 'b')), 5)
        self.assertIsNone(first_valid(row, ('a', 'c')))

    def test_latest_valid_period_skips_unreported(self):
        fin = pd.DataFrame({'2026': {'x': np.nan}, '2025': {'x': 1.0}})
        self.assertEqual(latest_valid_period(fin, ('x',)), 1)
        self.assertIsNone(latest_valid_period(fin, ('y',)))

    def test_avg_turnover(self):
        dates = pd.date_range(start='2023-01-02', periods=60, freq='B')
        hist = pd.DataFrame({'Close': 1000.0, 'Volume': 20000.0}, index=dates)
        self.assertEqual(avg_turnover(hist), 2e7)
        self.assertIsNone(avg_turnover(None))
        self.assertIsNone(avg_turnover(pd.DataFrame()))


if __name__ == '__main__':
    unittest.main()
