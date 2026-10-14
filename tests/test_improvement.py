import pandas as pd
import pytest

from src.improvement import ImprovementSignal
from src.stock_data import StockData

SIGNAL = ImprovementSignal(clear_threshold=0.40, same_quarter_tolerance_days=20, max_quarter_age_days=200)


def quarterly(**eps: float | None) -> pd.DataFrame:
    return pd.DataFrame({date: {"Diluted EPS": v} for date, v in eps.items()})


def annual(oi: float, oi_prev: float, rev: float = 100.0, rev_prev: float = 100.0) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "2025": {"Total Revenue": rev, "Operating Income": oi},
            "2024": {"Total Revenue": rev_prev, "Operating Income": oi_prev},
        }
    )


def evaluate(quarterly_income=None, financials=None):
    data = StockData.from_dict("1.T", {"quarterly_income": quarterly_income, "financials": financials})
    return SIGNAL.evaluate(data)


def q(latest: float, prev: float | None, prev_date: str = "2024-12-31") -> pd.DataFrame:
    return quarterly(**{"2025-12-31": latest, prev_date: prev})


@pytest.mark.parametrize(
    ("latest", "prev", "expected"),
    [
        (14.0, 10.0, "clear"),
        (13.99, 10.0, "signal"),
        (10.0, 10.0, "signal"),
        (9.0, 10.0, "none"),
        (5.0, 0.0, "clear"),
        (5.0, -2.0, "clear"),
    ],
)
def test_eps_class_boundaries(latest, prev, expected):
    assert evaluate(q(latest, prev))["Improvement_Class"] == expected


def test_eps_metrics_and_raw_values():
    out = evaluate(q(12.0, 10.0))
    assert (out["EPS_Q_Latest"], out["EPS_Q_Latest_Date"], out["EPS_Q_Prev_Year"], out["EPS_Q_YoY(%)"]) == (
        12.0,
        "2025-12-31",
        10.0,
        20.0,
    )


def test_turnaround_has_no_yoy_percentage():
    out = evaluate(q(5.0, -2.0))
    assert out["EPS_Q_YoY(%)"] is None
    assert out["EPS_Q_Prev_Year"] == -2.0


def test_missing_prev_year_is_unknown_but_keeps_latest():
    out = evaluate(quarterly(**{"2025-12-31": 5.0}))
    assert (out["Improvement_Class"], out["EPS_Q_Latest"], out["EPS_Q_Prev_Year"]) == ("unknown", 5.0, None)


@pytest.mark.parametrize(
    ("prev_date", "found"), [("2024-12-11", True), ("2025-01-20", True), ("2024-12-10", False), ("2025-01-21", False)]
)
def test_same_quarter_tolerance_window_edges(prev_date, found):
    # 2025-12-31 minus 365 days = 2024-12-31; tolerance 20 days -> 2024-12-11 .. 2025-01-20
    assert (evaluate(q(12.0, 10.0, prev_date))["EPS_Q_Prev_Year"] is not None) is found


def test_latest_is_newest_non_nan_column():
    out = evaluate(quarterly(**{"2026-03-31": None, "2025-12-31": 12.0, "2024-12-31": 10.0}))
    assert (out["EPS_Q_Latest_Date"], out["EPS_Q_YoY(%)"]) == ("2025-12-31", 20.0)


def test_operating_income_growth_and_margin_change():
    out = evaluate(financials=annual(oi=24.0, oi_prev=20.0, rev=100.0, rev_prev=160.0))
    assert (out["OI_YoY(%)"], out["Op_Margin_Change(pt)"], out["Improvement_Class"]) == (20.0, 11.5, "signal")


def test_operating_income_prev_not_positive_gives_no_yoy():
    out = evaluate(financials=annual(oi=5.0, oi_prev=-1.0))
    assert (out["OI_YoY(%)"], out["Op_Margin_Change(pt)"], out["Improvement_Class"]) == (None, 6.0, "unknown")


def test_quarterly_decides_even_if_annual_is_strong():
    assert evaluate(q(9.0, 10.0), annual(oi=30.0, oi_prev=20.0))["Improvement_Class"] == "none"


def test_annual_is_the_fallback_when_quarterly_is_missing():
    assert evaluate(financials=annual(oi=29.0, oi_prev=20.0))["Improvement_Class"] == "clear"
    assert evaluate(financials=annual(oi=21.0, oi_prev=20.0))["Improvement_Class"] == "signal"
    assert evaluate(financials=annual(oi=19.0, oi_prev=20.0))["Improvement_Class"] == "none"


def test_turnaround_is_clear_regardless_of_annual():
    assert evaluate(q(5.0, -2.0), annual(oi=10.0, oi_prev=20.0))["Improvement_Class"] == "clear"


def test_all_missing_is_unknown():
    out = evaluate()
    assert out["Improvement_Class"] == "unknown"
    assert out["EPS_Q_YoY(%)"] is None and "EPS_Q_Latest" not in out


def test_eps_row_with_only_nan_is_unknown():
    out = evaluate(quarterly_income=quarterly(**{"2025-12-31": None, "2024-12-31": None}))
    assert out["Improvement_Class"] == "unknown" and "EPS_Q_Latest" not in out


def test_margin_change_needs_both_revenues():
    fin = pd.DataFrame(
        {
            "2025": {"Total Revenue": 100.0, "Operating Income": 12.0},
            "2024": {"Total Revenue": None, "Operating Income": 10.0},
        }
    )
    out = evaluate(financials=fin)
    assert out["OI_YoY(%)"] == 20.0 and out["Op_Margin_Change(pt)"] is None


def with_price(quarterly_income=None, financials=None, price=None, mcap=None):
    data = StockData.from_dict(
        "1.T",
        {
            "quarterly_income": quarterly_income,
            "financials": financials,
            "fast_info": {"last_price": price, "market_cap": mcap},
        },
    )
    return SIGNAL.evaluate(data)


def test_yield_is_annualized_quarterly_eps_change_over_price():
    out = with_price(quarterly_income=q(12.0, 10.0), price=400.0)
    assert out["Improvement_Yield(%)"] == 2.0  # (12 - 10) * 4 / 400


def test_yield_falls_back_to_operating_income_change_over_market_cap():
    out = with_price(financials=annual(oi=15.0, oi_prev=10.0), mcap=100.0)
    assert out["Improvement_Class"] == "clear" and out["Improvement_Yield(%)"] == 5.0


def test_small_base_growth_does_not_inflate_yield():
    big = with_price(quarterly_income=q(7.7, 0.1), price=1000.0)  # +7600%
    steady = with_price(quarterly_income=q(60.0, 40.0), price=1000.0)  # +50%
    assert big["EPS_Q_YoY(%)"] > steady["EPS_Q_YoY(%)"]
    assert big["Improvement_Yield(%)"] < steady["Improvement_Yield(%)"]


@pytest.mark.parametrize(
    ("latest", "prev", "expected"),
    [(-1.0, -3.0, "signal"), (-3.0, -1.0, "none"), (-2.0, -2.0, "none"), (1.0, -2.0, "clear")],
)
def test_loss_quarter_is_decided_by_quarterly_eps_not_annual(latest, prev, expected):
    out = with_price(quarterly_income=q(latest, prev), financials=annual(oi=30.0, oi_prev=10.0), price=100.0)
    assert out["Improvement_Class"] == expected


def test_stale_latest_quarter_falls_back_to_annual():
    daily = pd.DataFrame({"Close": [1.0]}, index=pd.DatetimeIndex(["2026-10-01"]))
    data = StockData.from_dict(
        "1.T",
        {"quarterly_income": q(30.0, 10.0), "financials": annual(oi=9.0, oi_prev=10.0), "history": daily},
    )  # latest quarter 2025-12-31 is 274 days before the price data end
    out = SIGNAL.evaluate(data)
    assert out["Improvement_Class"] == "none" and out["EPS_Q_YoY(%)"] is None
    assert out["EPS_Q_Latest"] == 30.0  # raw value still recorded for the history
