import unittest

import pandas as pd

from src.cache import StockCache, refresh
from src.rules import RuleResult
from src.screener import Screener
from src.scorers import ScoreResult
from src.stock_data import StockData


class FakeRule:
    def __init__(self, passed, metrics=None):
        self.passed, self.metrics, self.calls = passed, metrics or {}, 0

    def evaluate(self, data, metrics):
        self.calls += 1
        return RuleResult(self.passed, self.metrics)


class FakeScorer:
    def __init__(self, category, points, metrics=None, recommendation=None):
        self.result = ScoreResult(category, points, metrics or {}, recommendation)

    def score(self, data, metrics):
        return self.result


DATA = StockData.from_dict('1234.T', {'info': {'longName': 'Foo'}})


class TestScreener(unittest.TestCase):

    CFG = {
            'gatekeeper': {'equity_ratio_min': 0.4, 'operating_margin_min': 0.1, 'psr_cap': 2.5,
                           'operating_cash_flow_min': 0, 'market_cap_min': 1e8, 'turnover_min': 0, 'turnover_days': 60},
            'scoring': {'sales_cagr_threshold': 0.189, 'sales_growth_points': 3,
                        'psr_super_cheap': 0.5, 'psr_super_cheap_points': 3, 'psr_cheap': 1.0,
                        'psr_cheap_points': 2, 'psr_fair_points': 1, 'net_net_bonus': 5, 'net_cash_points': 1,
                        'pbr_cheap': 1.0, 'pbr_points': 1, 'dividend_yield_target': 0.03,
                        'dividend_points': 1, 'per_growth_points': 2, 'equity_ratio_ideal': 0.7,
                        'equity_ideal_points': 1, 'ma_short': 12, 'ma_long': 24, 'technical_points': 2,
                        'sales_cagr_years_back': 4, 'sales_cagr_min_years': 3, 'net_net_ratio': 1.0,
                        'shock_lows': {'lehman': ['2008-09-01', '2009-03-31']}},
           'recommendation': {'quality_growth_min_growth_score': 3, 'quality_value_min_value_score': 4}}

    def test_failing_rule_short_circuits(self):
        after = FakeRule(True)
        scorer = FakeScorer('Value', 1)
        screener = Screener([FakeRule(True), FakeRule(False), after], [scorer], 3, 4)
        self.assertIsNone(screener.evaluate(DATA))
        self.assertEqual(after.calls, 0)

    def test_scores_and_recommendation(self):
        rules = [FakeRule(True, {'PSR': 1.0})]
        res = Screener(rules, [FakeScorer('Growth', 3), FakeScorer('Value', 1),
                               FakeScorer('Safety', 2, {'Chart_Trend': 'Bull'})], 3, 4).evaluate(DATA)
        self.assertEqual(res['Ticker'], '1234.T')
        self.assertEqual(res['Name'], 'Foo')
        self.assertEqual((res['Score_Growth'], res['Score_Value'], res['Score_Safety']), (3, 1, 2))
        self.assertEqual(res['Total_Score'], 6)
        self.assertEqual(res['Recommendation_Type'], 'Quality Growth')
        self.assertEqual(res['PSR'], 1.0)
        self.assertEqual(res['Chart_Trend'], 'Bull')

    def test_recommendation_precedence(self):
        def rec(*scorers):
            return Screener([], list(scorers), 3, 4).evaluate(DATA)['Recommendation_Type']
        self.assertEqual(rec(FakeScorer('Value', 4)), 'Quality Value')
        self.assertEqual(rec(FakeScorer('Value', 3)), 'Watch')
        self.assertEqual(rec(FakeScorer('Growth', 3), FakeScorer('Value', 5, recommendation='NET-NET')), 'NET-NET')

    def test_recommendation_thresholds_are_injected(self):
        def rec(growth_min, value_min, *scorers):
            return Screener([], list(scorers), growth_min, value_min).evaluate(DATA)['Recommendation_Type']
        self.assertEqual(rec(5, 4, FakeScorer('Growth', 3)), 'Watch')
        self.assertEqual(rec(2, 4, FakeScorer('Growth', 2)), 'Quality Growth')
        self.assertEqual(rec(3, 6, FakeScorer('Value', 4)), 'Watch')
        self.assertEqual(rec(3, 2, FakeScorer('Value', 2)), 'Quality Value')

    def test_from_config_reads_recommendation_section(self):
        cfg = dict(self.CFG, recommendation={'quality_growth_min_growth_score': 7,
                                             'quality_value_min_value_score': 9})
        screener = Screener.from_config(cfg)
        self.assertEqual(screener.quality_growth_min_growth_score, 7)
        self.assertEqual(screener.quality_value_min_value_score, 9)

    def test_from_config_end_to_end(self):
        cfg = self.CFG
        data = StockData.from_dict('1234.T', {
            'fast_info': {'market_cap': 2e9, 'last_price': 1000},
            'balance_sheet': pd.DataFrame({'2023': {'Total Assets': 100, 'Stockholders Equity': 50}}),
            'financials': pd.DataFrame({'2023': {'Total Revenue': 1e9, 'Operating Income': 0.15e9}}),
            'cashflow': pd.DataFrame({'2023': {'Operating Cash Flow': 100}}),
        })
        res = Screener.from_config(cfg).evaluate(data)
        self.assertEqual(res['PSR'], 2.0)
        self.assertEqual(res['PBR'], 40000000.0)
        self.assertEqual(res['Total_Score'], 1)
        self.assertEqual(res['Recommendation_Type'], 'Watch')


class FakeClient:
    def download(self, ticker):
        return {
            'info': {'longName': 'Foo'}, 'fast_info': {'market_cap': 5.0},
            'financials': pd.DataFrame({'2023': {'Total Revenue': 10.0}}),
            'history': pd.DataFrame({'Close': [1.0, 2.0]},
                                    index=pd.to_datetime(['2024-01-01', '2024-01-02']).tz_localize('Asia/Tokyo')),
        }


class TestStockCache(unittest.TestCase):

    def test_put_get_roundtrip(self):
        import tempfile, pathlib
        with tempfile.TemporaryDirectory() as tmp, StockCache(str(pathlib.Path(tmp) / 'c.duckdb')) as cache:
            self.assertIsNone(cache.get('1234.T'))
            self.assertFalse(cache.is_fresh('1234.T', 3))
            self.assertTrue(refresh(cache, FakeClient(), '1234.T', 3))
            self.assertTrue(cache.is_fresh('1234.T', 3))
            data = cache.get('1234.T')
            self.assertEqual(data.info['longName'], 'Foo')
            self.assertEqual(data.fast_info['market_cap'], 5.0)
            self.assertEqual(data.financials.loc['Total Revenue'].iloc[0], 10.0)
            self.assertEqual(list(data.history['Close']), [1.0, 2.0])
            self.assertIsNone(data.history.index.tz)
            self.assertTrue(data.balance_sheet.empty)


if __name__ == '__main__':
    unittest.main()
