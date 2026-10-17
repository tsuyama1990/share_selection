import datetime
from unittest import mock

import duckdb
import pandas as pd
import pytest

from src import fields as F
from src.outcomes import evaluate
from src.records import RecordStore, RunInfo
from src.screener import ScreenResult

INFO = RunInfo("2026-10", "abc", {}, datetime.date(2026, 10, 1), None, None)
RESULTS = {t: ScreenResult(True, None, {F.IMPROVEMENT_CLASS: "clear"}) for t in ("1.T", "2.T")}


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
    assert len(duckdb.sql(f"SELECT * FROM read_parquet('{tmp_path / 'rec' / run_id / 'outcomes.parquet'}')").df()) == 4


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
