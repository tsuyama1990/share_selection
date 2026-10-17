"""E1: `analyze` on the fixture cache (tests/fixtures/sample_cache.json.gz, exported by fixtures/export_sample.py).

After an intended change of the screening behavior or ``config.yaml``, regenerate the golden CSV with::

    UPDATE_GOLDEN=1 uv run pytest tests/e2e/test_e1_analyze.py

and review the diff of ``tests/fixtures/golden_screening.csv`` before committing.
"""

import json
import os
from pathlib import Path

import duckdb
import pandas as pd
import pytest

import main
from src.screener import NO_CACHE
from tests.fixtures.config import CFG

GOLDEN = Path(__file__).parent.parent / "fixtures" / "golden_screening.csv"
CALENDAR_COLUMNS = ["Next_Earnings_Date", "Earnings_Period"]  # filled by E2, not part of the golden file


def result_csv(project) -> pd.DataFrame:
    (out,) = (project.root / CFG["output"]["dir"]).glob("*.csv")
    return pd.read_csv(out)


def test_result_csv_has_configured_columns_and_matches_golden(project):
    project.seed_sample()
    project.run("analyze")

    report = result_csv(project)
    assert report.columns.tolist() == CFG["output"]["columns"]
    actual = report.drop(columns=CALENDAR_COLUMNS).sort_values("Ticker").reset_index(drop=True)
    if os.environ.get("UPDATE_GOLDEN"):
        actual.to_csv(GOLDEN, index=False)
        pytest.skip(f"golden regenerated: {GOLDEN}")
    expected = pd.read_csv(GOLDEN)
    assert len(actual) > 0
    pd.testing.assert_frame_equal(
        actual.fillna({"Quality_Flags": ""}), expected.fillna({"Quality_Flags": ""}), rtol=1e-6
    )


def test_every_ticker_is_recorded_with_its_fail_rule_and_exported(project):
    tickers = [*project.seed_sample(), "9999.T"]
    project.write_tickers(tickers)

    project.run("analyze")

    rows = project.query("SELECT ticker, stage1_pass, stage1_fail_rule, metrics, improvement_class FROM screen_results")
    (run_id,) = project.query("SELECT run_id FROM runs")[0]
    assert sorted(r[0] for r in rows) == sorted(tickers)
    assert {r[0]: r[1:3] for r in rows}["9999.T"] == (False, NO_CACHE)
    failed = [r for r in rows if not r[1] and r[2] != NO_CACHE]
    assert failed
    assert all(r[2] and json.loads(r[3]) is not None for r in failed)
    assert any(r[1] for r in rows)
    assert all((r[4] is None) == (r[0] == "9999.T") for r in rows)
    assert all(r[4] == json.loads(r[3])["Improvement_Class"] for r in rows if r[0] != "9999.T")
    assert all(isinstance(json.loads(r[3])["Quality_Flags"], list) for r in rows if r[1])
    exported = project.root / CFG["records"]["export_dir"] / run_id / "screen_results.parquet"
    assert duckdb.sql(f"SELECT count(*) FROM read_parquet('{exported}')").fetchone() == (len(tickers),)
    assert len(list((project.root / CFG["output"]["dir"]).glob("*.csv"))) == 1


def test_issue_defaults_to_latest_shikiho_issue(project, monkeypatch):
    project.write_tickers(["1.T"])
    monkeypatch.setattr(main, "default_issue", lambda cfg: "2099-03")
    for argv, expected in ((["analyze"], "2099-03"), (["analyze", "--issue", "2020-06"], "2020-06")):
        project.run(*argv)
        assert project.query("SELECT issue FROM runs ORDER BY run_id")[-1] == (expected,)


def test_stage2_candidates_are_recorded_in_the_column_and_flags_as_lists(project):
    project.seed_sample()
    project.run("analyze")

    expected = int(result_csv(project)["Stage2_Candidate"].sum())
    assert expected > 0
    ((recorded,),) = project.query("SELECT count(*) FROM screen_results WHERE stage2_candidate")
    assert recorded == expected
    ((not_passed_candidates,),) = project.query(
        "SELECT count(*) FROM screen_results WHERE stage2_candidate AND NOT stage1_pass"
    )
    assert not_passed_candidates == 0
    flags = project.query("SELECT rebuttal_flags FROM screen_results WHERE stage1_pass")
    assert all(isinstance(json.loads(f), list) for (f,) in flags)
