"""E3: `fetch` with some Yahoo failures caches the successes, lists the failures and does not abort."""

import pandas as pd

import main
from src.cache import StockCache
from tests.e2e.conftest import CFG


class FlakyYahoo:
    """Stands in for YahooClient: fails for the tickers in FAILING."""

    FAILING = {"2.T"}

    def __init__(self, *_args):
        pass

    def download(self, ticker):
        if ticker in self.FAILING:
            raise RuntimeError(f"boom {ticker}")
        return {"info": {"longName": ticker}}


def test_fetch_caches_successes_and_lists_failures(project, monkeypatch, capsys):
    monkeypatch.setattr(main, "YahooClient", FlakyYahoo)
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
