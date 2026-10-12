import unittest

import numpy as np
import pandas as pd

from src.scorers import (
    NetNetScorer, DividendScorer, PbrMetric, PsrScorer, SalesGrowthScorer, TrendScorer,
    build_scorers,
)
from src.stock_data import StockData


def total(scorers, data, metrics):
    """Run scorers; return (points by category, merged metrics, recommendations)."""
    pts, out, recs = {}, {}, []
    for s in scorers:
        r = s.score(data, metrics)
        pts[r.category] = pts.get(r.category, 0) + r.points
        out.update(r.metrics)
        if r.recommendation:
            recs.append(r.recommendation)
    return pts, out, recs


class TestScorers(unittest.TestCase):

    def test_score_growth(self):
        # 5 periods (4-year growth); metrics are the index, dates the columns
        fin = pd.DataFrame({
            '2023': {'Total Revenue': 200},
            '2022': {'Total Revenue': 150},
            '2021': {'Total Revenue': 120},
            '2020': {'Total Revenue': 100},
            '2019': {'Total Revenue': 80}
        })
        fin.columns = pd.to_datetime(fin.columns, format='%Y')
        res = SalesGrowthScorer(0.189, 3).score(StockData.from_dict('T', {'financials': fin}), {})
        # CAGR: (200 / 80) ** (1/4) - 1 = 25.74% >= 18.9% threshold
        self.assertEqual(res.category, 'Growth')
        self.assertEqual(res.points, 3)
        self.assertEqual(res.metrics['Sales_CAGR(%)'], 25.74)
        self.assertEqual(res.metrics['Sales_Growth_Years'], 4)

    def test_score_growth_insufficient_data(self):
        fin = pd.DataFrame({
            '2023': {'Total Revenue': 200},
            '2022': {'Total Revenue': 150},
            '2021': {'Total Revenue': 120}
        })
        fin.columns = pd.to_datetime(fin.columns, format='%Y')
        res = SalesGrowthScorer(0.189, 3).score(StockData.from_dict('T', {'financials': fin}), {})
        self.assertEqual(res.points, 0)
        self.assertNotIn('Sales_CAGR(%)', res.metrics)

    def test_score_value_net_net(self):
        bs = pd.DataFrame({'2023': {'Current Assets': 300, 'Total Liabilities Net Minority Interest': 100}})
        data = StockData.from_dict('T', {'balance_sheet': bs})
        # market cap 150 < NCAV 200; psr=0.4 (<0.5) -> +3 points
        pts, _, recs = total([PsrScorer(0.5, 3, 1), NetNetScorer(5)], data,
                             {'Market_Cap': 150, 'PSR': 0.4})
        # Super Cheap PSR (3) + NetNet (5) = 8
        self.assertEqual(pts['Value'], 8)
        self.assertEqual(recs, ['NET-NET'])

    def test_net_net_subtracts_liabilities(self):
        # Plenty of current assets but heavy liabilities is not a net-net
        bs = pd.DataFrame({'2023': {'Current Assets': 300, 'Total Liabilities Net Minority Interest': 250}})
        res = NetNetScorer(5).score(StockData.from_dict('T', {'balance_sheet': bs}), {'Market_Cap': 150})
        self.assertEqual(res.points, 0)
        self.assertIsNone(res.recommendation)
        self.assertEqual(res.metrics['NCAV_to_MarketCap_Ratio'], 0.33)

    def test_score_technical_bull(self):
        dates = pd.date_range(start='2021-08-31', periods=30, freq='ME')
        hist = pd.DataFrame({'Close': np.linspace(100, 200, 30)}, index=dates)
        data = StockData.from_dict('T', {'history_monthly': hist})
        # Trend is up. Current 200 > MA3 > MA5
        res = TrendScorer(3, 5, 2).score(data, {'Current_Price': 200})
        self.assertEqual(res.category, 'Safety')
        self.assertEqual(res.metrics['Chart_Trend'], 'Strong Bull')
        self.assertEqual(res.points, 2)

    def test_dividend_yield_units(self):
        bs = pd.DataFrame({'2023': {'Cash And Cash Equivalents': 0}})
        scorers = [PsrScorer(0.5, 3, 1), NetNetScorer(5), DividendScorer(0.03, 1)]
        metrics = {'Market_Cap': 150, 'PSR': 1.0}
        # trailingAnnualDividendYield is a fraction
        data = StockData.from_dict('T', {
            'balance_sheet': bs, 'info': {'trailingAnnualDividendYield': 0.0327, 'dividendYield': 3.44}})
        pts, out, _ = total(scorers, data, metrics)
        self.assertEqual(out['Dividend_Yield(%)'], 3.27)
        self.assertEqual(pts['Value'], 1 + 1)  # PSR fair + dividend
        # dividendYield fallback is in percent: 2.2 means 2.2%, below 3%
        data = StockData.from_dict('T', {'balance_sheet': bs, 'info': {'dividendYield': 2.2}})
        pts, out, _ = total(scorers, data, metrics)
        self.assertEqual(out['Dividend_Yield(%)'], 2.2)
        self.assertEqual(pts['Value'], 1)

    def test_pbr_from_equity_fallback(self):
        bs = pd.DataFrame({'2023': {'Stockholders Equity': 100}})
        res = PbrMetric().score(StockData.from_dict('T', {'balance_sheet': bs}), {'Market_Cap': 150})
        self.assertEqual(res.points, 0)
        self.assertEqual(res.metrics['PBR'], 1.5)

    def test_build_scorers(self):
        cfg = {'scoring': {
            'sales_cagr_threshold': 0.189, 'sales_growth_points': 3,
            'psr_super_cheap': 0.5, 'psr_cheap_points': 3, 'psr_fair_points': 1,
            'net_net_bonus': 5, 'dividend_yield_target': 0.03, 'dividend_points': 1,
            'per_growth_points': 2, 'ma_short': 12, 'ma_long': 24, 'technical_points': 2}}
        self.assertEqual(len(build_scorers(cfg)), 7)


if __name__ == '__main__':
    unittest.main()
