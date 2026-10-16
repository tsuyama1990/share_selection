import unittest

import pandas as pd

from src.improvement import ImprovementSignal
from src.quality import EpsQualityFlags
from src.rules import RuleResult
from src.screener import Screener
from tests.fixtures.stock import make_stock


class FakeRule:
    def __init__(self, passed, metrics=None):
        self.passed, self.metrics, self.calls = passed, metrics or {}, 0

    def evaluate(self, data, metrics):
        self.calls += 1
        return RuleResult(self.passed, self.metrics)


class FakeIndicator:
    def __init__(self, metrics=None):
        self.metrics = metrics or {}

    def compute(self, data, metrics):
        return self.metrics


NO_IMPROVEMENT = ImprovementSignal(0.4, 20, 200)
NO_QUALITY = EpsQualityFlags(0.5)
DATA = make_stock("1234.T", {"info": {"longName": "Foo"}})


class TestScreener(unittest.TestCase):
    CFG = {
        "gatekeeper": {
            "equity_ratio_min": 0.4,
            "operating_margin_min": 0.1,
            "psr_cap": 2.5,
            "operating_cash_flow_min": 0,
            "market_cap_min": 1e8,
            "turnover_min": 0,
            "turnover_days": 60,
        },
        "indicators": {
            "ma_short": 12,
            "ma_long": 24,
            "sales_cagr_years_back": 4,
            "sales_cagr_min_years": 3,
            "shock_lows": {"lehman": ["2008-09-01", "2009-03-31"]},
        },
        "quality": {"max_quarter_share_of_annual": 0.5},
        "improvement": {"clear_threshold": 0.4, "same_quarter_tolerance_days": 20, "max_quarter_age_days": 200},
    }

    def test_all_rules_run_and_fail_rule_is_the_first_failure(self):
        after = FakeRule(False, {"PBR": 2.0})
        screener = Screener(
            NO_IMPROVEMENT,
            NO_QUALITY,
            [FakeRule(True, {"PSR": 1.0}), FakeRule(False), after],
            [FakeIndicator({"Dividend_Yield(%)": 3.0})],
        )
        res = screener.screen(DATA)
        self.assertEqual((res.passed, res.fail_rule, after.calls), (False, "FakeRule", 1))
        self.assertEqual((res.row["PSR"], res.row["PBR"], res.row["Dividend_Yield(%)"]), (1.0, 2.0, 3.0))
        self.assertEqual(res.row["Improvement_Class"], "unknown")

    def test_first_rule_failure_keeps_later_rule_and_indicator_metrics(self):
        data = make_stock(
            "1234.T",
            {
                "fast_info": {"market_cap": 5e7, "last_price": 1000},  # below market_cap_min
                "info": {"dividendYield": 4.0},
                "balance_sheet": pd.DataFrame(
                    {"2023": {"Total Assets": 100, "Stockholders Equity": 50, "Cash And Cash Equivalents": 20}}
                ),
                "financials": pd.DataFrame({"2023": {"Total Revenue": 1e9, "Operating Income": 0.15e9}}),
            },
        )
        res = Screener.from_config(self.CFG).screen(data)
        self.assertEqual((res.passed, res.fail_rule), (False, "MarketCapRule"))
        self.assertEqual(
            (res.row["PSR"], res.row["Equity_Ratio"], res.row["Real_PSR"], res.row["Dividend_Yield(%)"]),
            (0.05, 50.0, 0.05, 4.0),
        )

    def test_missing_market_cap_skips_dependent_metrics_without_raising(self):
        data = make_stock(
            "1234.T",
            {
                "balance_sheet": pd.DataFrame(
                    {"2023": {"Total Assets": 100, "Stockholders Equity": 50, "Cash And Cash Equivalents": 20}}
                ),
                "financials": pd.DataFrame({"2023": {"Total Revenue": 1e9, "Operating Income": 0.15e9}}),
            },
        )
        res = Screener.from_config(self.CFG).screen(data)
        self.assertEqual((res.passed, res.fail_rule), (False, "MarketCapRule"))
        self.assertEqual((res.row["Equity_Ratio"], res.row["Net_Cash(Billion)"]), (50.0, 0.0))
        self.assertTrue({"PSR", "Real_PSR", "PBR", "Cash_to_MarketCap_Ratio"}.isdisjoint(res.row))

    def test_row_has_identity_and_merged_metrics(self):
        res = (
            Screener(
                NO_IMPROVEMENT,
                NO_QUALITY,
                [FakeRule(True, {"PSR": 1.0})],
                [FakeIndicator({"Chart_Trend": "Bull"})],
            )
            .screen(DATA)
            .row
        )
        self.assertEqual((res["Ticker"], res["Name"]), ("1234.T", "Foo"))
        self.assertEqual((res["PSR"], res["Chart_Trend"]), (1.0, "Bull"))
        self.assertNotIn("Total_Score", res)
        self.assertNotIn("Recommendation_Type", res)

    def test_from_config_wires_improvement_and_quality(self):
        screener = Screener.from_config(self.CFG)
        self.assertEqual(screener.improvement, ImprovementSignal(0.4, 20, 200))
        self.assertEqual(screener.quality, NO_QUALITY)

    def test_improvement_metrics_present_for_gate_failing_ticker(self):
        data = make_stock(
            "1234.T",
            {
                "quarterly_income": pd.DataFrame(
                    {"2025-12-31": {"Diluted EPS": 12.0}, "2024-12-31": {"Diluted EPS": 10.0}}
                )
            },
        )
        res = Screener.from_config(self.CFG).screen(data)  # no market cap -> fails the first rule
        self.assertFalse(res.passed)
        self.assertEqual(
            (res.row["EPS_Q_YoY(%)"], res.row["Improvement_Class"]), (20.0, "signal")
        )  # 20% < clear_threshold 40%
