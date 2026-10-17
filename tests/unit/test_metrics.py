import numpy as np
import pandas as pd
import pytest

from src.metrics import avg_turnover, first_valid, latest_valid_period, latest_values, sales_cagr, to_num


def test_sales_cagr_four_years():
    fin = pd.DataFrame(
        {
            "2023": {"Total Revenue": 200},
            "2022": {"Total Revenue": 150},
            "2021": {"Total Revenue": 120},
            "2020": {"Total Revenue": 100},
            "2019": {"Total Revenue": 80},
        }
    )
    fin.columns = pd.to_datetime(fin.columns, format="%Y")
    cagr, years = sales_cagr(fin, 4, 3)
    # (200 / 80) ** (1/4) - 1 = 25.74%
    assert round(cagr * 100, 2) == 25.74
    assert years == 4


def test_sales_cagr_insufficient_data():
    fin = pd.DataFrame({"2023": {"Total Revenue": 200}, "2022": {"Total Revenue": 150}, "2021": {"Total Revenue": 120}})
    fin.columns = pd.to_datetime(fin.columns, format="%Y")
    assert sales_cagr(fin, 4, 3) == (None, None)


def test_sales_cagr_uses_oldest_valid_period():
    # yfinance often leaves the oldest period NaN -> fall back to 3 years
    fin = pd.DataFrame(
        {
            "2026": {"Total Revenue": 133.1},
            "2025": {"Total Revenue": 121},
            "2024": {"Total Revenue": 110},
            "2023": {"Total Revenue": 100},
            "2022": {"Total Revenue": np.nan},
        }
    )
    cagr, years = sales_cagr(fin, 4, 3)
    assert years == 3
    assert cagr == pytest.approx(0.10)


def test_to_num():
    assert to_num("3") == 3.0
    assert to_num(None) is None
    assert to_num(np.nan) is None
    assert to_num("x") is None


def test_first_valid_skips_nan():
    row = pd.Series({"a": np.nan, "b": 5})
    assert first_valid(row, ("a", "b")) == 5
    assert first_valid(row, ("a", "c")) is None


def test_latest_valid_period_skips_unreported():
    fin = pd.DataFrame({"2026": {"x": np.nan}, "2025": {"x": 1.0}})
    assert latest_valid_period(fin, ("x",)) == 1
    assert latest_valid_period(fin, ("y",)) is None


def test_latest_values_reads_all_keys_at_the_same_period():
    fin = pd.DataFrame({"2026": {"x": 9.0, "y": np.nan}, "2025": {"x": 1.0, "y": 2.0}})
    assert latest_values(fin, ("x", "y")) == (1.0, 2.0)
    assert latest_values(fin, ("x",)) == (9.0,)
    assert latest_values(fin, ("z",)) is None


def test_avg_turnover():
    dates = pd.date_range(start="2023-01-02", periods=60, freq="B")
    hist = pd.DataFrame({"Close": 1000.0, "Volume": 20000.0}, index=dates)
    assert avg_turnover(hist, 60) == 2e7
    assert avg_turnover(None, 60) is None
    assert avg_turnover(pd.DataFrame(), 60) is None


def test_sales_cagr_needs_positive_current_sales():
    fin = pd.DataFrame({"2023": {"Total Revenue": 0.0}, "2022": {"Total Revenue": 150.0}})
    assert sales_cagr(fin, 4, 1) == (None, None)
