import datetime
import json

import duckdb
import pytest

from src import fields as F
from src.config import load_config
from src.records import RecordStore, RunInfo
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
            F.PRIORITY_RANK: 1,
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


def test_candidates_come_best_priority_rank_first(tmp_path):
    ranked = {
        t: ScreenResult(True, None, {F.STAGE2_CANDIDATE: True, F.PRIORITY_RANK: rank})
        for t, rank in (("1.T", 3), ("2.T", 1), ("3.T", 2))
    }
    with RecordStore(tmp_path / "r.duckdb", tmp_path / "rec") as store:
        run_id = store.record_run(INFO, ranked)
        assert [t for t, _ in store.candidates(run_id)] == ["2.T", "3.T", "1.T"]


def test_resolve_run_is_the_given_run_else_the_latest(tmp_path):
    with RecordStore(tmp_path / "r.duckdb", tmp_path / "rec") as store:
        first = store.record_run(INFO, RESULTS)
        latest = store.record_run(INFO, RESULTS)
        assert store.resolve_run(first) == first
        assert store.resolve_run(None) == latest != first


def test_run_metrics_cover_the_tickers_with_metrics(tmp_path):
    with RecordStore(tmp_path / "r.duckdb", tmp_path / "rec") as store:
        run_id = store.record_run(INFO, RESULTS)
        assert sorted(store.run_metrics(run_id)) == ["1.T", "2.T", "3.T"]


def test_screen_row_flattens_the_metrics_of_a_passing_ticker(tmp_path):
    with RecordStore(tmp_path / "r.duckdb", tmp_path / "rec") as store:
        run_id = store.record_run(INFO, RESULTS)
        row = store.screen_row(run_id, "1.T")
    assert row["stage1_pass"] is True
    assert row["stage1_fail_rule"] is None
    assert row["Improvement_Class"] == "clear"
    assert row["PSR"] == 1.5
    assert row["Name"] == "x"


def test_screen_row_keeps_the_failed_rule_and_a_missing_value_as_none(tmp_path):
    with RecordStore(tmp_path / "r.duckdb", tmp_path / "rec") as store:
        run_id = store.record_run(INFO, RESULTS)
        row = store.screen_row(run_id, "2.T")
    assert row["stage1_pass"] is False
    assert row["stage1_fail_rule"] == "PsrCap"
    assert row["PSR"] is None


def test_screen_row_of_an_unknown_ticker_is_empty(tmp_path):
    with RecordStore(tmp_path / "r.duckdb", tmp_path / "rec") as store:
        run_id = store.record_run(INFO, RESULTS)
        assert store.screen_row(run_id, "9.T") == {}


def test_resolve_run_without_any_run_says_to_run_analyze_first(tmp_path):
    """The first `flow-memo` or `docs` on a fresh checkout hit an IndexError (live check, 2026-10-20)."""
    with RecordStore(tmp_path / "r.duckdb", tmp_path / "rec") as store, pytest.raises(ValueError, match="analyze"):
        store.resolve_run(None)
