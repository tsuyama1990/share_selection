import unittest

import numpy as np
import pandas as pd

from src.scorers import (
    CashRatioScorer, DividendScorer, EquityScorer, NetCashScorer, PbrScorer, PsrScorer,
    SalesGrowthScorer, ShockLowMetric, TrendScorer, build_scorers,
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


WINDOWS = {'Lehman': ('2008-09-01', '2009-03-31'), 'Corona': ('2020-02-01', '2020-04-30')}


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
        res = SalesGrowthScorer(0.189, 3, 4, 3).score(StockData.from_dict('T', {'financials': fin}), {})
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
        res = SalesGrowthScorer(0.189, 3, 4, 3).score(StockData.from_dict('T', {'financials': fin}), {})
        self.assertEqual(res.points, 0)
        self.assertNotIn('Sales_CAGR(%)', res.metrics)

    def test_score_value_net_net(self):
        bs = pd.DataFrame({'2023': {'Cash And Cash Equivalents': 200}})
        data = StockData.from_dict('T', {'balance_sheet': bs})
        pts, out, recs = total([PsrScorer(0.5, 3, 1.0, 2, 1), CashRatioScorer(5, 1.0)], data,
                               {'Market_Cap': 150, 'PSR': 0.4})
        # Super cheap PSR (3) + NetNet (5) = 8
        self.assertEqual(pts['Value'], 8)
        self.assertEqual(recs, ['NET-NET'])
        self.assertEqual(out['Cash_to_MarketCap_Ratio'], 1.33)
        self.assertTrue(out['Net_Net_Flag(T/F)'])

    def test_cash_ratio_below_one_and_fallback_key(self):
        bs = pd.DataFrame({'2023': {'Cash Cash Equivalents And Short Term Investments': 75}})
        res = CashRatioScorer(5, 1.0).score(StockData.from_dict('T', {'balance_sheet': bs}), {'Market_Cap': 150})
        self.assertEqual(res.points, 0)
        self.assertIsNone(res.recommendation)
        self.assertEqual(res.metrics['Cash_to_MarketCap_Ratio'], 0.5)
        # no cash and no balance sheet -> nothing
        for d in ({'balance_sheet': pd.DataFrame({'2023': {'Total Assets': 1}})}, {}):
            res = CashRatioScorer(5, 1.0).score(StockData.from_dict('T', d), {'Market_Cap': 150})
            self.assertEqual((res.points, res.metrics), (0, {}))

    def _net_cash(self, bs_items, mcap=100e9):
        bs = pd.DataFrame({'2023': bs_items})
        fin = pd.DataFrame({'2023': {'Total Revenue': 100e9}})
        data = StockData.from_dict('T', {'balance_sheet': bs, 'financials': fin})
        return NetCashScorer(1).score(data, {'Market_Cap': mcap})

    def test_net_cash_missing_debt_is_zero(self):
        res = self._net_cash({'Cash And Cash Equivalents': 40e9})
        self.assertEqual(res.points, 1)
        self.assertEqual(res.metrics['Net_Cash(Billion)'], 40.0)
        self.assertEqual(res.metrics['Real_PSR'], 0.6)  # (100 - 40) / 100

    def test_net_debt_raises_real_psr(self):
        res = self._net_cash({'Cash And Cash Equivalents': 10e9, 'Total Debt': 50e9})
        self.assertEqual(res.points, 0)
        self.assertEqual(res.metrics['Net_Cash(Billion)'], -40.0)
        self.assertEqual(res.metrics['Real_PSR'], 1.4)  # (100 + 40) / 100

    def test_net_cash_requires_cash(self):
        res = self._net_cash({'Total Debt': 50e9})
        self.assertEqual((res.points, res.metrics), (0, {}))

    def test_net_cash_without_revenue_omits_real_psr(self):
        bs = pd.DataFrame({'2023': {'Cash And Cash Equivalents': 40e9}})
        res = NetCashScorer(1).score(StockData.from_dict('T', {'balance_sheet': bs}), {'Market_Cap': 100e9})
        self.assertEqual(res.points, 1)
        self.assertNotIn('Real_PSR', res.metrics)

    def test_psr_tiers(self):
        data = StockData.from_dict('T', {})
        scorer = PsrScorer(0.5, 3, 1.0, 2, 1)
        for psr, pts in [(0.5, 3), (0.51, 2), (1.0, 2), (1.01, 1)]:
            self.assertEqual(scorer.score(data, {'PSR': psr}).points, pts, psr)

    def test_psr_prefers_real_psr(self):
        res = PsrScorer(0.5, 3, 1.0, 2, 1).score(StockData.from_dict('T', {}), {'PSR': 1.5, 'Real_PSR': 0.4})
        self.assertEqual(res.points, 3)

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
        scorer = DividendScorer(0.03, 1)
        # forward dividendYield is in percent: 3.44 means 3.44%
        data = StockData.from_dict('T', {
            'info': {'dividendYield': 3.44, 'trailingAnnualDividendYield': 0.01}})
        res = scorer.score(data, {})
        self.assertEqual(res.metrics['Dividend_Yield(%)'], 3.44)
        self.assertEqual(res.points, 1)
        # below target in percent: 2.2 means 2.2%
        res = scorer.score(StockData.from_dict('T', {'info': {'dividendYield': 2.2}}), {})
        self.assertEqual(res.metrics['Dividend_Yield(%)'], 2.2)
        self.assertEqual(res.points, 0)
        # trailing fallback is a fraction
        res = scorer.score(StockData.from_dict('T', {'info': {'trailingAnnualDividendYield': 0.0327}}), {})
        self.assertEqual(res.metrics['Dividend_Yield(%)'], 3.27)
        self.assertEqual(res.points, 1)
        # neither
        res = scorer.score(StockData.from_dict('T', {}), {})
        self.assertEqual((res.points, res.metrics), (0, {}))

    def test_pbr_from_equity_fallback(self):
        bs = pd.DataFrame({'2023': {'Stockholders Equity': 100}})
        res = PbrScorer(1.0, 1).score(StockData.from_dict('T', {'balance_sheet': bs}), {'Market_Cap': 150})
        self.assertEqual(res.points, 0)
        self.assertEqual(res.metrics['PBR'], 1.5)

    def test_pbr_below_one_scores(self):
        scorer = PbrScorer(1.0, 1)
        res = scorer.score(StockData.from_dict('T', {'info': {'priceToBook': 0.8}}), {'Market_Cap': 150})
        self.assertEqual((res.category, res.points, res.metrics), ('Value', 1, {'PBR': 0.8}))
        res = scorer.score(StockData.from_dict('T', {'info': {'priceToBook': 1.0}}), {'Market_Cap': 150})
        self.assertEqual(res.points, 0)

    def test_equity_scorer(self):
        scorer = EquityScorer(0.70, 1)
        data = StockData.from_dict('T', {})
        self.assertEqual(scorer.score(data, {'Equity_Ratio': 70.0}).points, 1)
        self.assertEqual(scorer.score(data, {'Equity_Ratio': 69.9}).points, 0)
        self.assertEqual(scorer.score(data, {}).points, 0)
        self.assertEqual(scorer.score(data, {'Equity_Ratio': 80}).category, 'Safety')

    def test_shock_low(self):
        idx = pd.to_datetime(['2008-10-31', '2008-11-30', '2019-12-31', '2020-03-31'])
        hist = pd.DataFrame({'Low': [60.0, 50.0, 120.0, 80.0], 'Close': 1.0}, index=idx)
        data = StockData.from_dict('T', {'history_monthly': hist})
        res = ShockLowMetric(WINDOWS).score(data, {'Current_Price': 100})
        self.assertEqual(res.points, 0)
        self.assertEqual(res.metrics, {'Downside_to_Lehman_Low(%)': -50.0, 'Downside_to_Corona_Low(%)': -20.0})

    def test_shock_low_missing_window_or_price(self):
        idx = pd.to_datetime(['2020-03-31'])
        data = StockData.from_dict('T', {'history_monthly': pd.DataFrame({'Low': [80.0]}, index=idx)})
        res = ShockLowMetric(WINDOWS).score(data, {'Current_Price': 100})
        self.assertEqual(res.metrics, {'Downside_to_Corona_Low(%)': -20.0})
        self.assertEqual(ShockLowMetric(WINDOWS).score(data, {}).metrics, {})
        self.assertEqual(ShockLowMetric(WINDOWS).score(StockData.from_dict('T', {}), {'Current_Price': 100}).metrics, {})

    def test_build_scorers_shock_low_name_from_config(self):
        cfg = {'scoring': {
            'sales_cagr_threshold': 0.189, 'sales_growth_points': 3,
            'sales_cagr_years_back': 4, 'sales_cagr_min_years': 3, 'net_net_ratio': 1.0,
            'shock_lows': {'lehman': ['2008-09-01', '2009-03-31']},
            'psr_super_cheap': 0.5, 'psr_super_cheap_points': 3, 'psr_cheap': 1.0,
            'psr_cheap_points': 2, 'psr_fair_points': 1, 'net_net_bonus': 5, 'net_cash_points': 1,
            'pbr_cheap': 1.0, 'pbr_points': 1, 'dividend_yield_target': 0.03, 'dividend_points': 1,
            'per_growth_points': 2, 'equity_ratio_ideal': 0.7, 'equity_ideal_points': 1,
            'ma_short': 12, 'ma_long': 24, 'technical_points': 2}}
        shock = build_scorers(cfg)[-1]
        self.assertEqual(shock.windows, {'Lehman': ('2008-09-01', '2009-03-31')})

    def test_cash_ratio_threshold_from_field(self):
        bs = pd.DataFrame({'2023': {'Cash And Cash Equivalents': 100.0}})
        data = StockData.from_dict('T', {'balance_sheet': bs})
        self.assertEqual(CashRatioScorer(5, 0.5).score(data, {'Market_Cap': 150}).recommendation, 'NET-NET')
        self.assertIsNone(CashRatioScorer(5, 1.0).score(data, {'Market_Cap': 150}).recommendation)

    def test_build_scorers(self):
        cfg = {'scoring': {
            'sales_cagr_threshold': 0.189, 'sales_growth_points': 3,
            'sales_cagr_years_back': 4, 'sales_cagr_min_years': 3, 'net_net_ratio': 1.0,
            'shock_lows': {'lehman': ['2008-09-01', '2009-03-31']},
            'psr_super_cheap': 0.5, 'psr_super_cheap_points': 3, 'psr_cheap': 1.0,
            'psr_cheap_points': 2, 'psr_fair_points': 1, 'net_net_bonus': 5, 'net_cash_points': 1,
            'pbr_cheap': 1.0, 'pbr_points': 1, 'dividend_yield_target': 0.03, 'dividend_points': 1,
            'per_growth_points': 2, 'equity_ratio_ideal': 0.7, 'equity_ideal_points': 1,
            'ma_short': 12, 'ma_long': 24, 'technical_points': 2}}
        names = [type(x).__name__ for x in build_scorers(cfg)]
        self.assertEqual(len(names), 10)
        self.assertLess(names.index('NetCashScorer'), names.index('PsrScorer'))


if __name__ == '__main__':
    unittest.main()
