import numpy as np
import pandas as pd

from src.indicators import (
    CashRatio,
    DividendYield,
    NetCash,
    Pbr,
    SalesCagr,
    ShockLow,
    Trend,
    build_indicators,
)
from tests.fixtures.stock import make_stock

WINDOWS = {"Lehman": ("2008-09-01", "2009-03-31"), "Corona": ("2020-02-01", "2020-04-30")}


def _sales(values_by_year):
    fin = pd.DataFrame({y: {"Total Revenue": v} for y, v in values_by_year.items()})
    fin.columns = pd.to_datetime(fin.columns, format="%Y")
    return make_stock("T", {"financials": fin})


class TestIndicators:
    def test_sales_cagr(self):
        # 5 periods (4-year growth); (200 / 80) ** (1/4) - 1 = 25.74%
        data = _sales({"2023": 200, "2022": 150, "2021": 120, "2020": 100, "2019": 80})
        out = SalesCagr(4, 3).compute(data, {})
        assert out == ({"Sales_CAGR(%)": 25.74, "Sales_Growth_Years": 4})

    def test_sales_cagr_insufficient_data(self):
        assert (SalesCagr(4, 3).compute(_sales({"2023": 200, "2022": 150, "2021": 120}), {})) == {}

    def test_cash_ratio(self):
        bs = pd.DataFrame({"2023": {"Cash And Cash Equivalents": 200}})
        out = CashRatio().compute(make_stock("T", {"balance_sheet": bs}), {"Market_Cap": 150})
        assert out == ({"Cash_to_MarketCap_Ratio": 1.33})

    def test_cash_ratio_fallback_key_and_missing_inputs(self):
        bs = pd.DataFrame({"2023": {"Cash Cash Equivalents And Short Term Investments": 75}})
        out = CashRatio().compute(make_stock("T", {"balance_sheet": bs}), {"Market_Cap": 150})
        assert out["Cash_to_MarketCap_Ratio"] == 0.5
        # no cash and no balance sheet -> nothing
        for d in ({"balance_sheet": pd.DataFrame({"2023": {"Total Assets": 1}})}, {}):
            assert (CashRatio().compute(make_stock("T", d), {"Market_Cap": 150})) == {}

    def _net_cash(self, bs_items, mcap=100e9):
        bs = pd.DataFrame({"2023": bs_items})
        fin = pd.DataFrame({"2023": {"Total Revenue": 100e9}})
        data = make_stock("T", {"balance_sheet": bs, "financials": fin})
        return NetCash().compute(data, {"Market_Cap": mcap})

    def test_net_cash_missing_debt_is_zero(self):
        out = self._net_cash({"Cash And Cash Equivalents": 40e9})
        assert out["Net_Cash(Billion)"] == 40.0
        assert out["Real_PSR"] == 0.6  # (100 - 40) / 100

    def test_net_debt_raises_real_psr(self):
        out = self._net_cash({"Cash And Cash Equivalents": 10e9, "Total Debt": 50e9})
        assert out["Net_Cash(Billion)"] == -40.0
        assert out["Real_PSR"] == 1.4  # (100 + 40) / 100

    def test_net_cash_requires_cash(self):
        assert (self._net_cash({"Total Debt": 50e9})) == {}

    def test_net_cash_without_revenue_omits_real_psr(self):
        bs = pd.DataFrame({"2023": {"Cash And Cash Equivalents": 40e9}})
        out = NetCash().compute(make_stock("T", {"balance_sheet": bs}), {"Market_Cap": 100e9})
        assert "Real_PSR" not in out

    def test_trend_strong_bull(self):
        dates = pd.date_range(start="2021-08-31", periods=30, freq="ME")
        hist = pd.DataFrame({"Close": np.linspace(100, 200, 30)}, index=dates)
        data = make_stock("T", {"history_monthly": hist})
        # Trend is up. Current 200 > MA3 > MA5
        out = Trend(3, 5).compute(data, {"Current_Price": 200})
        assert out["Chart_Trend"] == ("Strong Bull")

    def test_dividend_yield_units(self):
        indicator = DividendYield()
        # forward dividendYield is in percent: 3.44 means 3.44%
        data = make_stock("T", {"info": {"dividendYield": 3.44, "trailingAnnualDividendYield": 0.01}})
        assert (indicator.compute(data, {})) == ({"Dividend_Yield(%)": 3.44})
        # trailing fallback is a fraction
        data = make_stock("T", {"info": {"trailingAnnualDividendYield": 0.0327}})
        assert (indicator.compute(data, {})) == ({"Dividend_Yield(%)": 3.27})
        # neither
        assert (indicator.compute(make_stock("T", {}), {})) == {}

    def test_pbr_from_equity_fallback(self):
        bs = pd.DataFrame({"2023": {"Stockholders Equity": 100}})
        out = Pbr().compute(make_stock("T", {"balance_sheet": bs}), {"Market_Cap": 150})
        assert out == ({"PBR": 1.5})

    def test_pbr_prefers_info(self):
        out = Pbr().compute(make_stock("T", {"info": {"priceToBook": 0.8}}), {"Market_Cap": 150})
        assert out == ({"PBR": 0.8})

    def test_shock_low(self):
        idx = pd.to_datetime(["2008-10-31", "2008-11-30", "2019-12-31", "2020-03-31"])
        hist = pd.DataFrame({"Low": [60.0, 50.0, 120.0, 80.0], "Close": 1.0}, index=idx)
        data = make_stock("T", {"history_monthly": hist})
        out = ShockLow(WINDOWS).compute(data, {"Current_Price": 100})
        assert out == ({"Downside_to_Lehman_Low(%)": -50.0, "Downside_to_Corona_Low(%)": -20.0})

    def test_shock_low_missing_window_or_price(self):
        idx = pd.to_datetime(["2020-03-31"])
        data = make_stock("T", {"history_monthly": pd.DataFrame({"Low": [80.0]}, index=idx)})
        assert (ShockLow(WINDOWS).compute(data, {"Current_Price": 100})) == ({"Downside_to_Corona_Low(%)": -20.0})
        assert (ShockLow(WINDOWS).compute(data, {})) == {}
        assert (ShockLow(WINDOWS).compute(make_stock("T", {}), {"Current_Price": 100})) == {}

    def test_build_indicators(self):
        cfg = {
            "indicators": {
                "sales_cagr_years_back": 4,
                "sales_cagr_min_years": 3,
                "ma_short": 12,
                "ma_long": 24,
                "shock_lows": {"lehman": ["2008-09-01", "2009-03-31"]},
            }
        }
        built = build_indicators(cfg)
        assert built[-1].windows == ({"Lehman": ("2008-09-01", "2009-03-31")})
