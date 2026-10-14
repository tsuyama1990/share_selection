import datetime
import json
import sys
from unittest import mock

import duckdb
import pandas as pd
import pytest
import yaml

import main
from src import records
from src.cache import StockCache
from src.config import load_config
from src.records import NO_CACHE, RecordStore, evaluate
from src.screener import Screener
from src.yahoo import YahooClient
from tests.test_regression import load_sample

CFG = load_config()
INFO = {
    "issue": "2026-10",
    "git_sha": "abc",
    "config": {"a": 1},
    "ticker_list_date": datetime.date(2026, 10, 1),
    "data_fetched_min": datetime.datetime(2026, 10, 2),
    "data_fetched_max": datetime.datetime(2026, 10, 3),
}
ROWS = [
    {
        "ticker": "1.T",
        "stage1_pass": True,
        "stage1_fail_rule": None,
        "improvement_class": "clear",
        "next_earnings_date": "2026-11-05",
        "quality_flags": ["quarter_spike", "oi_divergence"],
        "metrics": {"PSR": 1.5, "Name": "x"},
    },
    {
        "ticker": "2.T",
        "stage1_pass": False,
        "stage1_fail_rule": "PsrCap",
        "improvement_class": "none",
        "next_earnings_date": None,
        "quality_flags": [],
        "metrics": {"PSR": float("nan")},
    },
    {
        "ticker": "3.T",
        "stage1_pass": False,
        "stage1_fail_rule": NO_CACHE,
        "improvement_class": None,
        "next_earnings_date": None,
        "quality_flags": None,
        "metrics": {},
    },
]


def parquet(path, table):
    return duckdb.sql(f"SELECT * FROM read_parquet('{path / table}.parquet')").df()


def test_record_run_round_trip_and_parquet(tmp_path):
    with RecordStore(tmp_path / "r.duckdb", tmp_path / "rec") as store:
        run_id = store.record_run(INFO, ROWS)
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
    assert json.loads(res[0][3]) == {"PSR": 1.5, "Name": "x"}
    assert json.loads(res[1][3]) == {"PSR": None}
    assert flags == ['["quarter_spike", "oi_divergence"]', "[]", None]
    assert [r[4] for r in res] == ["clear", "none", None]
    out = tmp_path / "rec" / run_id
    assert parquet(out, "runs")["git_sha"].tolist() == ["abc"]
    assert parquet(out, "screen_results")["ticker"].tolist() == ["1.T", "2.T", "3.T"]


def test_next_earnings_date_is_stored(tmp_path):
    with RecordStore(tmp_path / "r.duckdb", tmp_path / "rec") as store:
        store.record_run(INFO, ROWS)
        dates = store.con.execute("SELECT next_earnings_date FROM screen_results ORDER BY ticker").fetchall()
    assert [d for (d,) in dates] == [datetime.date(2026, 11, 5), None, None]


@pytest.mark.parametrize(
    ("today", "issue"),
    [
        (datetime.date(2026, 10, 14), "2026-09"),
        (datetime.date(2026, 9, 14), "2026-06"),
        (datetime.date(2026, 9, 15), "2026-09"),
        (datetime.date(2026, 12, 15), "2026-12"),
        (datetime.date(2027, 1, 1), "2026-12"),
        (datetime.date(2027, 3, 14), "2026-12"),
        (datetime.date(2027, 3, 15), "2027-03"),
    ],
)
def test_latest_issue_boundaries(today, issue):
    rec = CFG["records"]
    assert records.latest_issue(today, rec["shikiho_issue_months"], rec["shikiho_release_day"]) == issue


def test_fetch_writes_failures_csv(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(main, "ROOT", tmp_path)
    client = mock.Mock()
    client.download.side_effect = lambda t: {} if t == "1.T" else (_ for _ in ()).throw(RuntimeError("boom"))
    with StockCache(str(tmp_path / "c.duckdb"), CFG["system"]["market_timezone"]) as cache:
        main.run_fetch(CFG, ["1.T", "2.T"], cache, client)
    (path,) = (tmp_path / CFG["output"]["dir"]).glob("fetch_failures_*.csv")
    assert pd.read_csv(path).to_dict("records") == [{"ticker": "2.T", "error": "boom"}]
    assert "1 fetch failures saved" in capsys.readouterr().out


def test_head_commit_none_when_unavailable():
    with mock.patch("src.records.subprocess.run", side_effect=OSError):
        assert records.git_sha() is None


def test_analyze_records_every_ticker(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "ROOT", tmp_path)
    (tmp_path / CFG["system"]["input_csv"]).write_text("code\n", encoding="utf-8")
    with StockCache(str(tmp_path / "c.duckdb"), CFG["system"]["market_timezone"]) as cache:
        tickers = [*load_sample(cache), "9999.T"]
        main.run_analyze(CFG, tickers, cache, Screener.from_config(CFG), "2026-10")
    rec = CFG["records"]
    with duckdb.connect(str(tmp_path / rec["db_file"])) as con:
        rows = con.execute(
            "SELECT ticker, stage1_pass, stage1_fail_rule, metrics, improvement_class FROM screen_results"
        ).fetchall()
        (run_id,) = con.execute("SELECT run_id FROM runs").fetchone()
    assert sorted(r[0] for r in rows) == sorted(tickers)
    assert {r[0]: r[1:3] for r in rows}["9999.T"] == (False, NO_CACHE)
    failed = [r for r in rows if not r[1] and r[2] != NO_CACHE]
    assert failed and all(r[2] and json.loads(r[3]) is not None for r in failed)
    assert any(r[1] for r in rows)
    assert all((r[4] is None) == (r[0] == "9999.T") for r in rows)
    assert all(r[4] == json.loads(r[3])["Improvement_Class"] for r in rows if r[0] != "9999.T")
    assert len(parquet(tmp_path / rec["export_dir"] / run_id, "screen_results")) == len(tickers)
    assert len(list((tmp_path / CFG["output"]["dir"]).glob("*.csv"))) == 1


def test_fetched_range(tmp_path):
    with StockCache(str(tmp_path / "c.duckdb"), "Asia/Tokyo") as cache:
        assert cache.fetched_range() == (None, None)
        cache.put("1.T", {})
        lo, hi = cache.fetched_range()
        assert lo == hi and lo is not None


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
        return store.record_run(INFO, ROWS)


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


def test_adjusted_close_uses_adjusted_naive_dates():
    index = pd.DatetimeIndex(["2025-01-06", "2025-01-07"], tz="Asia/Tokyo")
    ticker = mock.MagicMock()
    ticker.history.return_value = pd.DataFrame({"Close": [1.0, 2.0]}, index=index)
    with mock.patch("src.yahoo.yf.Ticker", return_value=ticker):
        series = YahooClient(0.0, "1y", "max").adjusted_close("1.T", datetime.date(2025, 1, 1))
    ticker.history.assert_called_once_with(start=datetime.date(2025, 1, 1), auto_adjust=True)
    assert series.index.tz is None and list(series.index.strftime("%Y-%m-%d")) == ["2025-01-06", "2025-01-07"]


def test_config_option_redirects_thresholds_and_outputs(tmp_path, monkeypatch):
    alt = {
        **CFG,
        "gatekeeper": {**CFG["gatekeeper"], "psr_cap": 99.0},
        "output": {**CFG["output"], "dir": "alt_out"},
        "system": {**CFG["system"], "db_file": "alt_cache.duckdb"},
        "records": {**CFG["records"], "db_file": "alt_records.duckdb", "export_dir": "alt_records"},
    }
    cfg_path = tmp_path / "alt.yaml"
    cfg_path.write_text(yaml.safe_dump(alt), encoding="utf-8")
    monkeypatch.setattr(main, "ROOT", tmp_path)
    with StockCache(str(tmp_path / "alt_cache.duckdb"), CFG["system"]["market_timezone"]) as cache:
        tickers = load_sample(cache)
    (tmp_path / CFG["system"]["input_csv"]).write_text("\n".join(["code", *tickers]), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["main.py", "--config", str(cfg_path), "analyze"])
    main.main()
    with duckdb.connect(str(tmp_path / "alt_records.duckdb")) as con:
        (stored,) = con.execute("SELECT config FROM runs").fetchone()
    assert json.loads(stored)["gatekeeper"]["psr_cap"] == 99.0
    assert (tmp_path / "alt_records").is_dir()
    assert list((tmp_path / "alt_out").glob("*.csv"))
    assert not (tmp_path / CFG["output"]["dir"]).exists()


def test_analyze_fills_earnings_columns_from_calendar(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "ROOT", tmp_path)
    (tmp_path / CFG["system"]["input_csv"]).write_text("code\n", encoding="utf-8")
    with StockCache(str(tmp_path / "c.duckdb"), CFG["system"]["market_timezone"]) as cache:
        tickers = load_sample(cache)
        code = tickers[0].removesuffix(".T")
        cal = f"code,announce_date,period_en,fiscal_year_end\n{code},2026-11-05,Second quarter,2027-03-31\n"
        (tmp_path / CFG["calendar"]["out_csv"]).write_text(cal, encoding="utf-8")
        main.run_analyze(CFG, tickers, cache, Screener.from_config(CFG), None)
    with duckdb.connect(str(tmp_path / CFG["records"]["db_file"])) as con:
        dates = dict(con.execute("SELECT ticker, next_earnings_date FROM screen_results").fetchall())
    assert dates[tickers[0]] == datetime.date(2026, 11, 5)
    assert [t for t, d in dates.items() if d is not None] == [tickers[0]]
    (out,) = (tmp_path / CFG["output"]["dir"]).glob("*.csv")
    report = pd.read_csv(out, dtype=str).set_index("Ticker")
    if tickers[0] in report.index:
        assert report.loc[tickers[0], "Next_Earnings_Date"] == "2026-11-05"
        assert report.loc[tickers[0], "Earnings_Period"] == "Second quarter"
    assert report.drop(index=tickers[0], errors="ignore")["Next_Earnings_Date"].isna().all()


def test_analyze_issue_defaults_to_latest_shikiho_issue(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "ROOT", tmp_path)
    (tmp_path / CFG["system"]["input_csv"]).write_text("code\n1.T\n", encoding="utf-8")
    cfg_path = tmp_path / "c.yaml"
    cfg_path.write_text(yaml.safe_dump(CFG), encoding="utf-8")
    calls = []
    monkeypatch.setattr(main, "run_analyze", lambda *a: calls.append(a[-1]))
    monkeypatch.setattr(main, "default_issue", lambda cfg: "2099-03")
    for argv, expected in ((["analyze"], "2099-03"), (["analyze", "--issue", "2020-06"], "2020-06")):
        monkeypatch.setattr(sys, "argv", ["main.py", "--config", str(cfg_path), *argv])
        main.main()
        assert calls[-1] == expected


def test_analyze_warns_once_without_calendar(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(main, "ROOT", tmp_path)
    (tmp_path / CFG["system"]["input_csv"]).write_text("code\n", encoding="utf-8")
    with StockCache(str(tmp_path / "c.duckdb"), CFG["system"]["market_timezone"]) as cache:
        main.run_analyze(CFG, load_sample(cache), cache, Screener.from_config(CFG), None)
    assert capsys.readouterr().out.count("earnings calendar not found") == 1
    (out,) = (tmp_path / CFG["output"]["dir"]).glob("*.csv")
    assert pd.read_csv(out)["Next_Earnings_Date"].isna().all()
