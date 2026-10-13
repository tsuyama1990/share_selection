import unittest

import numpy as np
import pandas as pd

from src.rules import (
    EquityRatioRule,
    LiquidityRule,
    MarketCapRule,
    OperatingCashFlowRule,
    OperatingMarginRule,
    PsrRule,
    build_rules,
)
from src.stock_data import StockData


def gatekeeper(turnover_min=0):
    return [
        MarketCapRule(1e8),
        LiquidityRule(turnover_min, 60),
        EquityRatioRule(0.40),
        OperatingMarginRule(0.10),
        PsrRule(2.5),
        OperatingCashFlowRule(0),
    ]


def check(data, rules=None):
    """Run rules in order like the Screener; return merged metrics or None."""
    metrics = {}
    for rule in rules or gatekeeper():
        res = rule.evaluate(data, metrics)
        if not res.passed:
            return None
        metrics.update(res.metrics)
    return metrics


def make(**overrides):
    """StockData that passes the gatekeeper unless overridden."""
    d = {
        "fast_info": {"market_cap": 2e9, "last_price": 1000},
        "balance_sheet": pd.DataFrame({"2023-03-31": {"Total Assets": 100, "Stockholders Equity": 50}}),
        "financials": pd.DataFrame({"2023-03-31": {"Total Revenue": 1e9, "Operating Income": 0.15e9}}),
        "cashflow": pd.DataFrame({"2023-03-31": {"Operating Cash Flow": 100}}),
    }
    d.update(overrides)
    return StockData.from_dict("T.T", d)


class TestRules(unittest.TestCase):
    def test_gatekeeper_pass(self):
        # Total Equity Gross Minority Interest (consolidated statements)
        bs = pd.DataFrame({"2023-03-31": {"Total Assets": 100, "Total Equity Gross Minority Interest": 50}})
        res = check(make(balance_sheet=bs))
        self.assertIsNotNone(res)
        self.assertEqual(res["Equity_Ratio"], 50.0)
        self.assertEqual(res["Operating_Margin(%)"], 15.0)

    def test_gatekeeper_fail_margin(self):
        fin = pd.DataFrame({"2023-03-31": {"Total Revenue": 1e9, "Operating Income": 0.05e9}})  # 5% < 10%
        self.assertIsNone(check(make(financials=fin, cashflow=pd.DataFrame())))

    def test_gatekeeper_fail_ocf(self):
        cf = pd.DataFrame({"2023-03-31": {"Operating Cash Flow": -100}})
        self.assertIsNone(check(make(cashflow=cf)))

    def test_cf_extraction(self):
        cf = pd.DataFrame(
            {"2023-03-31": {"Operating Cash Flow": 500, "Investing Cash Flow": -200, "Financing Cash Flow": -100}}
        )
        res = check(make(cashflow=cf))
        self.assertIsNotNone(res)
        self.assertEqual(res["Operating_Cash_Flow"], 500)
        self.assertEqual(res["Investing_Cash_Flow"], -200)
        self.assertEqual(res["Financing_Cash_Flow"], -100)

    def test_gatekeeper_nan_equity_falls_through_to_next_key(self):
        # NaN in the first key must not shadow a valid later key (`a or b` bug)
        bs = pd.DataFrame(
            {
                "2023-03-31": {
                    "Total Assets": 100,
                    "Stockholders Equity": np.nan,
                    "Total Equity Gross Minority Interest": 30,
                }
            }
        )
        self.assertIsNone(check(make(balance_sheet=bs)))  # 30% < 40%

    def test_gatekeeper_prefers_stockholders_equity(self):
        # Non-controlling interests must not inflate the equity ratio
        bs = pd.DataFrame(
            {"2023-03-31": {"Total Assets": 100, "Stockholders Equity": 35, "Total Equity Gross Minority Interest": 50}}
        )
        self.assertIsNone(check(make(balance_sheet=bs)))  # 35% < 40%

    def test_gatekeeper_fail_nan_metrics(self):
        nan_cases = {
            "equity": {
                "balance_sheet": pd.DataFrame({"2023-03-31": {"Total Assets": 100, "Stockholders Equity": np.nan}})
            },
            "op_income": {
                "financials": pd.DataFrame({"2023-03-31": {"Total Revenue": 1e9, "Operating Income": np.nan}})
            },
            "ocf": {"cashflow": pd.DataFrame({"2023-03-31": {"Operating Cash Flow": np.nan}})},
            "market_cap": {"fast_info": {"market_cap": np.nan, "last_price": 1000}},
        }
        for name, override in nan_cases.items():
            with self.subTest(name):
                self.assertIsNone(check(make(**override)))

    def test_gatekeeper_fail_missing_ocf(self):
        self.assertIsNone(check(make(cashflow=pd.DataFrame())))

    def test_gatekeeper_liquidity(self):
        dates = pd.date_range(start="2023-01-02", periods=60, freq="B")
        liquid = pd.DataFrame({"Close": 1000.0, "Volume": 20000.0}, index=dates)  # 20M JPY/day
        illiquid = pd.DataFrame({"Close": 1000.0, "Volume": 5000.0}, index=dates)  # 5M JPY/day
        rules = gatekeeper(turnover_min=1e7)

        res = check(make(history=liquid), rules)
        self.assertIsNotNone(res)
        self.assertEqual(res["Avg_Turnover(M JPY)"], 20.0)
        self.assertIsNone(check(make(history=illiquid), rules))
        self.assertIsNone(check(make(), rules))

    def test_gatekeeper_skips_unreported_latest_period(self):
        # A not-yet-reported fiscal year (all NaN) falls back to the previous one
        fin = pd.DataFrame(
            {
                "2026-06-30": {"Total Revenue": np.nan, "Operating Income": np.nan},
                "2025-06-30": {"Total Revenue": 1e9, "Operating Income": 0.15e9},
            }
        )
        res = check(make(financials=fin))
        self.assertIsNotNone(res)
        self.assertEqual(res["Operating_Margin(%)"], 15.0)

    def test_psr_cap(self):
        fin = pd.DataFrame({"2023-03-31": {"Total Revenue": 0.5e9, "Operating Income": 0.15e9}})  # PSR 4
        self.assertIsNone(check(make(financials=fin)))

    def test_build_rules_order(self):
        cfg = {
            "gatekeeper": {
                "equity_ratio_min": 0.4,
                "operating_margin_min": 0.1,
                "psr_cap": 2.5,
                "operating_cash_flow_min": 0,
                "market_cap_min": 1e8,
                "turnover_min": 0,
                "turnover_days": 60,
            }
        }
        self.assertEqual(
            [type(r).__name__ for r in build_rules(cfg)],
            [
                "MarketCapRule",
                "LiquidityRule",
                "EquityRatioRule",
                "OperatingMarginRule",
                "PsrRule",
                "OperatingCashFlowRule",
            ],
        )


if __name__ == "__main__":
    unittest.main()
