"""E3: `fetch` with some Yahoo failures caches the successes, lists the failures and does not abort."""

import runpy

import pandas as pd
import pytest

import main
from src import flows
from src.cache import StockCache
from tests.fixtures.config import CFG


class FlakyYahoo:
    """Stands in for YahooClient: fails for the tickers in FAILING."""

    FAILING = {"2.T"}

    @classmethod
    def from_config(cls, _cfg):
        return cls()

    def download(self, ticker):
        if ticker in self.FAILING:
            raise RuntimeError(f"boom {ticker}")
        return {"info": {"longName": ticker}}


def test_fetch_caches_successes_and_lists_failures(project, monkeypatch, capsys):
    monkeypatch.setattr(flows, "YahooClient", FlakyYahoo)
    project.write_tickers(["1.T", "2.T", "3.T"])

    project.run("fetch")

    with StockCache(str(project.root / CFG["system"]["db_file"]), CFG["system"]["market_timezone"]) as cache:
        cached = {t: cache.get(t) for t in ("1.T", "2.T", "3.T")}
    assert cached["1.T"].info["longName"] == "1.T"
    assert cached["3.T"].info["longName"] == "3.T"
    assert cached["2.T"] is None
    (path,) = (project.root / CFG["output"]["dir"]).glob("fetch_failures_*.csv")
    assert pd.read_csv(path).to_dict("records") == [{"ticker": "2.T", "error": "boom 2.T"}]
    assert "fetched 2 / 3" in capsys.readouterr().out


def test_fetch_without_failures_writes_no_failure_csv(project, monkeypatch, capsys):
    monkeypatch.setattr(flows, "YahooClient", FlakyYahoo)
    project.write_tickers(["1.T", "3.T"])
    project.run("fetch")
    assert "fetched 2 / 2" in capsys.readouterr().out
    assert not list((project.root / CFG["output"]["dir"]).glob("fetch_failures_*.csv"))


def test_fetch_and_analyze_need_the_ticker_csv(project, capsys):
    for command in ("fetch", "analyze"):
        with pytest.raises(SystemExit) as e:
            project.run(command)
        assert e.value.code == 1
    csv_path = project.root / CFG["system"]["input_csv"]
    assert capsys.readouterr().out == f"Error: ticker CSV not found: {csv_path} (run `tickers`)\n" * 2


def test_tickers_saves_the_csv_the_downloader_wrote(project, monkeypatch, capsys):
    monkeypatch.setattr(main, "update_ticker_csv", lambda out_csv, url, markets, timeout: 3)
    project.run("tickers")
    assert capsys.readouterr().out == f"Saved 3 tickers to {project.root / CFG['system']['input_csv']}\n"


def test_main_without_a_command_prints_the_help(project, capsys, monkeypatch):
    monkeypatch.setattr("sys.argv", ["main.py"])
    runpy.run_path(main.__file__, run_name="__main__")
    assert "usage: main.py" in capsys.readouterr().out
