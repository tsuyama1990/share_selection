import unittest
import pandas as pd
import numpy as np
from src.analyzer import (
    _check_gatekeeper, 
    _score_growth, 
    _score_value, 
    _score_technical, 
    analyze_stock_data
)
from src.config import CFG

# Mock Config
CFG['gatekeeper'] = {'equity_ratio_min': 0.40, 'operating_margin_min': 0.10, 'psr_cap': 2.5}
CFG['scoring'] = {
    'sales_growth_threshold': 1.0, 'sales_growth_points': 3,
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
        # Growth: (200 / 80) - 1 = 1.5 (150%) >= 1.0 threshold
        self.assertEqual(res['Score_Growth'], 3)
        self.assertEqual(res['Sales_Growth_4Y(%)'], 150.0)

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
        self.assertNotIn('Sales_Growth_4Y(%)', res)

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
        dates = pd.date_range(end='2024-01-01', periods=30, freq='ME')
        # Prices increasing linearly
        closes = np.linspace(100, 200, 30) 
        hist = pd.DataFrame({'Close': closes}, index=dates)
        
        res = {'Score_Safety': 0}
        # Trend is Up. Current 200. MA12 < 200. MA24 < 200.
        _score_technical(hist, current_price=200, result=res)
        
        self.assertEqual(res['Chart_Trend'], 'Strong Bull')
        self.assertEqual(res['Score_Safety'], 2)

if __name__ == '__main__':
    unittest.main()
