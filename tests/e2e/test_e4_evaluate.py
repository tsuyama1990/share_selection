"""E4: `evaluate` with recorded runs and mocked prices computes only the horizons that have elapsed."""

import datetime
from unittest import mock

import duckdb
import pandas as pd

import main
from src import fields as F
from src.records import RecordStore, RunInfo
from src.screener import ScreenResult
from tests.fixtures.config import CFG

RUN_AGE_DAYS = 200  # between the 6 and 12 month horizons
ROW = {F.IMPROVEMENT_CLASS: "clear", F.QUALITY_FLAGS: []}
INFO = RunInfo("2026-03", "abc", {}, datetime.date(2026, 1, 1), None, None)


class FakeYahoo:
    @classmethod
    def from_config(cls, _cfg):
        return cls()

    def adjusted_close(self, ticker, start):
        days = pd.bdate_range(start, datetime.date.today())
        slope = {"1.T": 1.0, "2.T": -0.1, "1306.T": 0.5}[ticker]
        return pd.Series([100.0 + slope * i for i in range(len(days))], index=days)


def record_old_run(project) -> str:
    run_at = datetime.datetime.now() - datetime.timedelta(days=RUN_AGE_DAYS)
    with RecordStore.from_config(CFG, project.root) as store, mock.patch("src.records.datetime.datetime") as dt:
        dt.now.return_value = run_at
        return store.record_run(INFO, {t: ScreenResult(True, None, dict(ROW)) for t in ("1.T", "2.T")})


def test_evaluate_adds_only_elapsed_horizons(project, monkeypatch, capsys):
    monkeypatch.setattr(main, "YahooClient", FakeYahoo)
    run_id = record_old_run(project)

    project.run("evaluate")

    assert "Added 2 outcome rows." in capsys.readouterr().out
    rows = project.query("SELECT ticker, horizon_months, price_t0, price_t1 FROM outcomes ORDER BY ticker")
    assert [r[:2] for r in rows] == [("1.T", 6), ("2.T", 6)]
    assert all(t0 is not None and t1 is not None for _, _, t0, t1 in rows)
    exported = project.root / CFG["records"]["export_dir"] / run_id / "outcomes.parquet"
    assert duckdb.sql(f"SELECT count(*) FROM read_parquet('{exported}')").fetchone() == (2,)

    project.run("evaluate")
    assert "Added 0 outcome rows." in capsys.readouterr().out
