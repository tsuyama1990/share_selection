import unittest
import pandas as pd
import numpy as np
from src.analyzer import (
    _check_gatekeeper, 
    get_sales_cagr,
    _score_growth, 
    _score_value, 
    _score_technical, 
    analyze_stock_data
)
from src.config import CFG

# Mock Config
CFG['gatekeeper'] = {'equity_ratio_min': 0.40, 'operating_margin_min': 0.10, 'psr_cap': 2.5}
CFG['scoring'] = {
    'sales_cagr_threshold': 0.189, 'sales_growth_points': 3,
    'psr_super_cheap': 0.5, 'psr_cheap_points': 3, 'psr_fair_points': 1,
    'net_net_bonus': 5, 'dividend_yield_target': 0.03, 'dividend_points': 1,
    'per_growth_points': 2, 'ma_short': 3, 'ma_long': 5, 'technical_points': 2,
    'safety_buffer_pct': 20, 'safety_points': 2
}

class TestAnalyzer(unittest.TestCase):

    def setUp(self):
        # Patch the module-level SC and GK to ensure our mock config is used
        import src.analyzer
        src.analyzer.GK = CFG['gatekeeper']
        src.analyzer.SC = CFG['scoring']

    def test_gatekeeper_pass(self):
        fast_info = {'market_cap': 2e9, 'last_price': 1000}
        # Use Total Equity Gross Minority Interest (correct for consolidated statements)
        bs = pd.DataFrame({'2023-03-31': {
            'Total Assets': 100, 
            'Total Equity Gross Minority Interest': 50
        }})
        # Fix: Revenue high enough so PSR < 2.5. 2e9 / 1e9 = 2.0
        fin = pd.DataFrame({'2023-03-31': {'Total Revenue': 1e9, 'Operating Income': 0.15e9}})
        cf = pd.DataFrame({'2023-03-31': {'Operating Cash Flow': 100}}) # Positive OCF
        
        res = _check_gatekeeper(fast_info, bs, fin, cf)
        self.assertIsNotNone(res)
        self.assertEqual(res['Equity_Ratio'], 50.0)
        self.assertEqual(res['Operating_Margin(%)'], 15.0)

    def test_gatekeeper_fail_margin(self):
        fast_info = {'market_cap': 2e9, 'last_price': 1000}
        bs = pd.DataFrame({'2023-03-31': {'Total Assets': 100, 'Stockholders Equity': 50}})
        fin = pd.DataFrame({'2023-03-31': {'Total Revenue': 1e9, 'Operating Income': 0.05e9}}) # 5% < 10%
        
        res = _check_gatekeeper(fast_info, bs, fin, pd.DataFrame())
        self.assertIsNone(res)

    def test_gatekeeper_fail_ocf(self):
        fast_info = {'market_cap': 2e9, 'last_price': 1000}
        bs = pd.DataFrame({'2023-03-31': {'Total Assets': 100, 'Stockholders Equity': 50}})
        fin = pd.DataFrame({'2023-03-31': {'Total Revenue': 1e9, 'Operating Income': 0.15e9}})
        # Negative OCF
        cf = pd.DataFrame({'2023-03-31': {'Operating Cash Flow': -100}})
        
        res = _check_gatekeeper(fast_info, bs, fin, cf)
        self.assertIsNone(res)

    def test_cf_extraction(self):
        fast_info = {'market_cap': 2e9, 'last_price': 1000}
        bs = pd.DataFrame({'2023-03-31': {'Total Assets': 100, 'Stockholders Equity': 50}})
        fin = pd.DataFrame({'2023-03-31': {'Total Revenue': 1e9, 'Operating Income': 0.15e9}})
        cf = pd.DataFrame({'2023-03-31': {
            'Operating Cash Flow': 500,
            'Investing Cash Flow': -200,
            'Financing Cash Flow': -100
        }})
        
        res = _check_gatekeeper(fast_info, bs, fin, cf)
        self.assertIsNotNone(res)
        self.assertEqual(res['Operating_Cash_Flow'], 500)
        self.assertEqual(res['Investing_Cash_Flow'], -200)
        self.assertEqual(res['Financing_Cash_Flow'], -100)

    def test_score_growth(self):
        # Fix: Data shape should have Metrics as Index, Dates as Columns (standard yfinance)
        # Test with exactly 5 periods (4-year growth)
        fin = pd.DataFrame({
            '2023': {'Total Revenue': 200},
            '2022': {'Total Revenue': 150},
            '2021': {'Total Revenue': 120},
            '2020': {'Total Revenue': 100},
            '2019': {'Total Revenue': 80} 
        })
        fin.columns = pd.to_datetime(fin.columns, format='%Y')
        
        res = {'Score_Growth': 0}
        _score_growth(fin, res)
        # CAGR: (200 / 80) ** (1/4) - 1 = 25.74% >= 18.9% threshold
        self.assertEqual(res['Score_Growth'], 3)
        self.assertEqual(res['Sales_CAGR(%)'], 25.74)
        self.assertEqual(res['Sales_Growth_Years'], 4)

    def test_score_growth_insufficient_data(self):
        # Only 3 periods - should return None
        fin = pd.DataFrame({
            '2023': {'Total Revenue': 200},
            '2022': {'Total Revenue': 150},
            '2021': {'Total Revenue': 120}
        })
        fin.columns = pd.to_datetime(fin.columns, format='%Y')
        
        res = {'Score_Growth': 0}
        _score_growth(fin, res)
        # Should not add points due to insufficient data
        self.assertEqual(res['Score_Growth'], 0)
        self.assertNotIn('Sales_CAGR(%)', res)

    def test_score_value_net_net(self):
        # Fix: Metrics as Index
        bs = pd.DataFrame({'2023': {'Cash And Cash Equivalents': 200}}).T.T 
        # Double transpose or just dict: {'2023': {Key:Val}} is Col: {Idx:Val} which is correct.
        bs = pd.DataFrame({'2023': {'Cash And Cash Equivalents': 200}})
        
        market_cap = 150 # Cash > Market Cap
        res = {'Score_Value': 0}
        _score_value({}, bs, market_cap, psr=0.4, result=res) # psr=0.4 (<0.5) -> +3 points
        
        # Super Cheap PSR (3) + NetNet (5) = 8
        self.assertEqual(res['Score_Value'], 8)
        self.assertEqual(res['Recommendation_Type'], 'NET-NET')

    def test_score_technical_bull(self):
        # Create dummy history (Dates as Index, Columns as Metrics) - This is correct for History
        # Fix: Provide enough data points (e.g. 30) for ma_long=24 default (test logic used ma_long=5 but importing logic was tricky)
        # But we patched SC in setUp, so ma_long should be 5. Let's make it 30 anyway to be safe.
        dates = pd.date_range(start='2021-08-31', periods=30, freq='ME')
        # Prices increasing linearly
        closes = np.linspace(100, 200, 30) 
        hist = pd.DataFrame({'Close': closes}, index=dates)
        
        res = {'Score_Safety': 0}
        # Trend is Up. Current 200. MA12 < 200. MA24 < 200.
        _score_technical(hist, current_price=200, result=res)
        
        self.assertEqual(res['Chart_Trend'], 'Strong Bull')
        self.assertEqual(res['Score_Safety'], 2)

    def _gatekeeper_inputs(self, **overrides):
        """Inputs that pass the gatekeeper unless overridden."""
        inputs = {
            'fast_info': {'market_cap': 2e9, 'last_price': 1000},
            'bs': pd.DataFrame({'2023-03-31': {'Total Assets': 100, 'Stockholders Equity': 50}}),
            'fin': pd.DataFrame({'2023-03-31': {'Total Revenue': 1e9, 'Operating Income': 0.15e9}}),
            'cf': pd.DataFrame({'2023-03-31': {'Operating Cash Flow': 100}}),
        }
        inputs.update(overrides)
        return inputs

    def test_gatekeeper_nan_equity_falls_through_to_next_key(self):
        # NaN in the first key must not shadow a valid later key (`a or b` bug)
        bs = pd.DataFrame({'2023-03-31': {
            'Total Assets': 100,
            'Stockholders Equity': np.nan,
            'Total Equity Gross Minority Interest': 30
        }})
        res = _check_gatekeeper(**self._gatekeeper_inputs(bs=bs))
        self.assertIsNone(res)  # 30% < 40%

    def test_gatekeeper_prefers_stockholders_equity(self):
        # Non-controlling interests must not inflate the equity ratio
        bs = pd.DataFrame({'2023-03-31': {
            'Total Assets': 100,
            'Stockholders Equity': 35,
            'Total Equity Gross Minority Interest': 50
        }})
        res = _check_gatekeeper(**self._gatekeeper_inputs(bs=bs))
        self.assertIsNone(res)  # 35% < 40%

    def test_gatekeeper_fail_nan_metrics(self):
        nan_cases = {
            'equity': {'bs': pd.DataFrame({'2023-03-31': {'Total Assets': 100, 'Stockholders Equity': np.nan}})},
            'op_income': {'fin': pd.DataFrame({'2023-03-31': {'Total Revenue': 1e9, 'Operating Income': np.nan}})},
            'ocf': {'cf': pd.DataFrame({'2023-03-31': {'Operating Cash Flow': np.nan}})},
            'market_cap': {'fast_info': {'market_cap': np.nan, 'last_price': 1000}},
        }
        for name, override in nan_cases.items():
            with self.subTest(name):
                self.assertIsNone(_check_gatekeeper(**self._gatekeeper_inputs(**override)))

    def test_gatekeeper_fail_missing_ocf(self):
        self.assertIsNone(_check_gatekeeper(**self._gatekeeper_inputs(cf=pd.DataFrame())))

    def test_gatekeeper_liquidity(self):
        import src.analyzer
        src.analyzer.GK = {**CFG['gatekeeper'], 'turnover_min': 1e7}
        dates = pd.date_range(start='2023-01-02', periods=60, freq='B')
        liquid = pd.DataFrame({'Close': 1000.0, 'Volume': 20000.0}, index=dates)   # 20M JPY/day
        illiquid = pd.DataFrame({'Close': 1000.0, 'Volume': 5000.0}, index=dates)  # 5M JPY/day

        res = _check_gatekeeper(**self._gatekeeper_inputs(), hist_daily=liquid)
        self.assertIsNotNone(res)
        self.assertEqual(res['Avg_Turnover_60D(M JPY)'], 20.0)
        self.assertIsNone(_check_gatekeeper(**self._gatekeeper_inputs(), hist_daily=illiquid))
        self.assertIsNone(_check_gatekeeper(**self._gatekeeper_inputs(), hist_daily=None))

    def test_gatekeeper_skips_unreported_latest_period(self):
        # A not-yet-reported fiscal year (all NaN) falls back to the previous one
        fin = pd.DataFrame({
            '2026-06-30': {'Total Revenue': np.nan, 'Operating Income': np.nan},
            '2025-06-30': {'Total Revenue': 1e9, 'Operating Income': 0.15e9}
        })
        res = _check_gatekeeper(**self._gatekeeper_inputs(fin=fin))
        self.assertIsNotNone(res)
        self.assertEqual(res['Operating_Margin(%)'], 15.0)

    def test_sales_cagr_uses_oldest_valid_period(self):
        # yfinance often leaves the oldest period NaN -> fall back to 3 years
        fin = pd.DataFrame({
            '2026': {'Total Revenue': 133.1},
            '2025': {'Total Revenue': 121},
            '2024': {'Total Revenue': 110},
            '2023': {'Total Revenue': 100},
            '2022': {'Total Revenue': np.nan}
        })
        cagr, years = get_sales_cagr(fin)
        self.assertEqual(years, 3)
        self.assertAlmostEqual(cagr, 0.10)

    def test_dividend_yield_units(self):
        bs = pd.DataFrame({'2023': {'Cash And Cash Equivalents': 0}})
        # trailingAnnualDividendYield is a fraction
        res = {'Score_Value': 0}
        _score_value({'trailingAnnualDividendYield': 0.0327, 'dividendYield': 3.44}, bs, 150, psr=1.0, result=res)
        self.assertEqual(res['Dividend_Yield(%)'], 3.27)
        self.assertEqual(res['Score_Value'], 1 + 1)  # PSR fair + dividend
        # dividendYield fallback is in percent: 2.2 means 2.2%, below 3%
        res = {'Score_Value': 0}
        _score_value({'dividendYield': 2.2}, bs, 150, psr=1.0, result=res)
        self.assertEqual(res['Dividend_Yield(%)'], 2.2)
        self.assertEqual(res['Score_Value'], 1)

if __name__ == '__main__':
    unittest.main()
