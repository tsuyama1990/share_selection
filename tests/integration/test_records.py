import datetime
import json
from unittest import mock

import duckdb
import pandas as pd
import pytest

from src import fields as F
from src.config import load_config
from src.records import RecordStore, RunInfo, evaluate
from src.screener import NO_CACHE, ScreenResult

CFG = load_config()
INFO = RunInfo(
    "2026-10",
    "abc",
    {"a": 1},
    datetime.date(2026, 10, 1),
    datetime.datetime(2026, 10, 2),
    datetime.datetime(2026, 10, 3),
)
RESULTS = {
    "1.T": ScreenResult(
        True,
        None,
        {
            F.IMPROVEMENT_CLASS: "clear",
            F.STAGE2_CANDIDATE: True,
            F.NEXT_EARNINGS_DATE: "2026-11-05",
            F.QUALITY_FLAGS: ["quarter_spike", "oi_divergence"],
            "PSR": 1.5,
            "Name": "x",
        },
    ),
    "2.T": ScreenResult(
        False,
        "PsrCap",
        {F.IMPROVEMENT_CLASS: "none", F.STAGE2_CANDIDATE: False, F.QUALITY_FLAGS: [], "PSR": float("nan")},
    ),
    "3.T": ScreenResult(False, NO_CACHE, {F.NEXT_EARNINGS_DATE: None}),
}


def parquet(path, table):
    return duckdb.sql(f"SELECT * FROM read_parquet('{path / table}.parquet')").df()


def test_record_run_round_trip_and_parquet(tmp_path):
    with RecordStore(tmp_path / "r.duckdb", tmp_path / "rec") as store:
        run_id = store.record_run(INFO, RESULTS)
        run = store.con.execute("SELECT issue, git_sha, config, ticker_list_date FROM runs").fetchall()
        res = store.con.execute(
            "SELECT ticker, stage1_pass, stage1_fail_rule, metrics, improvement_class FROM screen_results"
        ).fetchall()
        flags = [
            r for (r,) in store.con.execute("SELECT rebuttal_flags FROM screen_results ORDER BY ticker").fetchall()
        ]
        assert store.tickers(run_id) == ["1.T", "2.T"]
    assert run == [("2026-10", "abc", '{"a": 1}', datetime.date(2026, 10, 1))]
    assert [r[:3] for r in res] == [("1.T", True, None), ("2.T", False, "PsrCap"), ("3.T", False, NO_CACHE)]
    assert json.loads(res[0][3]) == RESULTS["1.T"].row
    assert json.loads(res[1][3])["PSR"] is None
    assert flags == ['["quarter_spike", "oi_divergence"]', "[]", None]
    assert [r[4] for r in res] == ["clear", "none", None]
    out = tmp_path / "rec" / run_id
    assert parquet(out, "runs")["git_sha"].tolist() == ["abc"]
    assert parquet(out, "screen_results")["ticker"].tolist() == ["1.T", "2.T", "3.T"]


def test_candidates_select_by_the_stage2_candidate_column(tmp_path):
    with RecordStore(tmp_path / "r.duckdb", tmp_path / "rec") as store:
        run_id = store.record_run(INFO, RESULTS)
        assert store.candidates(run_id) == [("1.T", RESULTS["1.T"].row)]
        flags = store.con.execute("SELECT stage2_candidate FROM screen_results ORDER BY ticker").fetchall()
    assert [f for (f,) in flags] == [True, False, False]


def closes(values: dict[str, float]) -> pd.Series:
    return pd.Series(list(values.values()), index=pd.to_datetime(list(values)), dtype=float)


HISTORY = {
    "1.T": closes({"2025-01-03": 100.0, "2025-07-04": 130.0, "2025-12-30": 150.0}),
    "2.T": closes({"2025-01-03": 50.0, "2025-07-04": 40.0, "2025-12-30": 60.0}),
    "1306.T": closes({"2025-01-03": 200.0, "2025-07-04": 210.0, "2025-12-30": 240.0}),
}


def make_run(store, run_at):
    with mock.patch("src.records.datetime.datetime") as dt:
        dt.now.return_value = run_at
        return store.record_run(INFO, RESULTS)


def test_evaluate_computes_elapsed_horizons_only(tmp_path):
    with RecordStore(tmp_path / "r.duckdb", tmp_path / "rec") as store:
        run_id = make_run(store, datetime.datetime(2025, 1, 5, 12))  # Sunday: t0 uses Friday's close
        added = evaluate(store, HISTORY.__getitem__, [6, 12], "1306.T", datetime.datetime(2026, 1, 1))
        assert added == 2  # 6 months elapsed (2025-07-05 -> close of 07-04); 12 months (2026-01-05) not yet
        assert evaluate(store, HISTORY.__getitem__, [6, 12], "1306.T", datetime.datetime(2026, 1, 1)) == 0
        rows = store.con.execute(
            'SELECT ticker, horizon_months, price_t0, price_t1, "return", benchmark_return, excess '
            "FROM outcomes ORDER BY ticker"
        ).fetchall()
        assert evaluate(store, HISTORY.__getitem__, [6, 12], "1306.T", datetime.datetime(2026, 2, 1)) == 2
        assert store.con.execute("SELECT count(*) FROM outcomes WHERE horizon_months = 12").fetchone() == (2,)
    assert rows[0][:5] == ("1.T", 6, 100.0, 130.0, pytest.approx(0.3))
    assert rows[0][5:] == (pytest.approx(0.05), pytest.approx(0.25))
    assert rows[1][:5] == ("2.T", 6, 50.0, 40.0, pytest.approx(-0.2))
    assert len(parquet(tmp_path / "rec" / run_id, "outcomes")) == 4


def test_evaluate_tolerates_missing_history(tmp_path):
    def history(ticker):
        if ticker == "2.T":
            raise KeyError("Close")
        return HISTORY[ticker]

    with RecordStore(tmp_path / "r.duckdb", tmp_path / "rec") as store:
        make_run(store, datetime.datetime(2025, 1, 5))
        assert evaluate(store, history, [6], "1306.T", datetime.datetime(2026, 1, 1)) == 2
        row = store.con.execute('SELECT price_t0, "return", excess FROM outcomes WHERE ticker = ?', ["2.T"]).fetchone()
    assert row == (None, None, None)
