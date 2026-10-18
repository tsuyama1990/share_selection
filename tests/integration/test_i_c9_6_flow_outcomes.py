"""I-C9-6: only decisions past the horizon are scored; the control is the same-sector median laggard.

L2 C9 section 7: a decision's excess is measured over the equal-weight mean of the tickers under test
(the decisions and their controls); the control's excess is the mean of the same-sector companies whose
past gain and PBR are at or below the sector's median.
"""

import datetime

import pandas as pd

from src import fields as F
from src.flow_store import DecisionRow, FlowRow, FlowStore
from src.outcomes import _select_controls, evaluate_decisions
from src.records import RecordStore, RunInfo
from src.screener import ScreenResult

DECIDED = datetime.datetime(2026, 1, 10, 9, 30)
NOW = datetime.datetime(2026, 8, 10)
T0 = pd.Timestamp(DECIDED).normalize()
RATES = {"1.T": 0.25, "2.T": 0.05, "3.T": 0.10}


def flat_then_jump(ticker):
    """Flat at 100 up to the decision, then 100 * (1 + rate) from the decision on.

    The 6-month return from the decision is therefore exactly ``RATES[ticker]`` (within floating-point
    tolerance), and the series is defined only from one week before the decision, so a lookback from earlier
    would fail."""
    days = pd.bdate_range(T0 - pd.Timedelta(days=7), NOW)
    rate = RATES[ticker]
    prices = [100.0 if d <= T0 else 100.0 * (1 + rate) for d in days]
    return pd.Series(prices, index=days)


def ramp_before_decision(ticker):
    """Flat at 100 until three months before the decision, then straight up to 100 * (1 + rate) at the
    decision, then flat again. The 3-month gain up to the decision is therefore exactly ``RATES[ticker]``."""

    days = pd.bdate_range(T0 - pd.DateOffset(months=6), NOW)
    rate = RATES[ticker]
    start = T0 - pd.DateOffset(months=3)
    span = max((T0 - start).days, 1)
    prices = []
    for d in days:
        if d <= start:
            prices.append(100.0)
        elif d <= T0:
            prices.append(100.0 * (1 + rate * (d - start).days / span))
        else:
            prices.append(100.0 * (1 + rate))
    return pd.Series(prices, index=days)


def picks_3(_ticker, _date):
    return ["3.T"]


def test_only_elapsed_horizons_are_stored(tmp_path):
    with FlowStore(tmp_path / "flow.duckdb") as flows:
        flow_id = flows.save_flow(FlowRow("f", "d", [], "pv", "prov"))
        flows.record_decision(DecisionRow(flow_id, "1.T", DECIDED, "buy", "why", None))

        assert evaluate_decisions(flows, flat_then_jump, picks_3, [6, 12], NOW) == 1
        rows = flows.con.execute("SELECT ticker, months FROM flow_outcomes ORDER BY ticker").fetchall()
        assert [r[:2] for r in rows] == [("1.T", 6)]

        # A second pass sees the 6-month row and skips it; the 12-month horizon has not elapsed.
        assert evaluate_decisions(flows, flat_then_jump, picks_3, [6, 12], NOW) == 0


def test_excess_is_measured_over_the_tickers_under_test(tmp_path):
    with FlowStore(tmp_path / "flow.duckdb") as flows:
        flow_id = flows.save_flow(FlowRow("f", "d", [], "pv", "prov"))
        flows.record_decision(DecisionRow(flow_id, "1.T", DECIDED, "buy", "why", None))

        evaluate_decisions(flows, flat_then_jump, picks_3, [6], NOW)
        excess, control_excess, control_n = flows.con.execute(
            "SELECT excess, control_excess, control_n FROM flow_outcomes"
        ).fetchone()

    # Universe = {1.T, 3.T}; returns 0.25 and 0.10, so the benchmark is 0.175.
    assert abs(excess - 0.075) < 1e-9
    assert abs(control_excess - (-0.075)) < 1e-9
    assert control_n == 1


def test_controls_are_same_sector_median_laggards(tmp_path):
    (tmp_path / "tickers.csv").write_text(
        "code,name,sector33\n1,A,sec-a\n2,B,sec-a\n3,C,sec-a\n4,D,sec-b\n", encoding="utf-8"
    )
    cfg = {
        "system": {"input_csv": "tickers.csv"},
        "records": {"db_file": "records.duckdb", "export_dir": "records"},
        "flow": {"control": {"past_months": 3}},
    }
    with RecordStore.from_config(cfg, tmp_path) as store:
        store.record_run(
            RunInfo("2026-03", "abc", {}, datetime.date(2026, 1, 1), None, None),
            {
                "1.T": ScreenResult(True, None, {F.PBR: 2.0}),  # fastest riser, expensive: excluded
                "2.T": ScreenResult(True, None, {F.PBR: 0.5}),  # laggard, cheap: a control
                "3.T": ScreenResult(True, None, {F.PBR: 0.8}),  # middle, cheap enough: a control
                "4.T": ScreenResult(True, None, {F.PBR: 2.0}),  # different sector
            },
        )
        controls = _select_controls(cfg, tmp_path, store, ramp_before_decision)
        assert sorted(controls("1.T", DECIDED.date())) == ["2.T", "3.T"]
