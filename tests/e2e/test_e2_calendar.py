import datetime

import duckdb
import pandas as pd

import main
from src.cache import StockCache
from src.config import load_config
from src.screener import Screener
from tests.fixtures.sample import load_sample

CFG = load_config()


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


def test_analyze_warns_once_without_calendar(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(main, "ROOT", tmp_path)
    (tmp_path / CFG["system"]["input_csv"]).write_text("code\n", encoding="utf-8")
    with StockCache(str(tmp_path / "c.duckdb"), CFG["system"]["market_timezone"]) as cache:
        main.run_analyze(CFG, load_sample(cache), cache, Screener.from_config(CFG), None)
    assert capsys.readouterr().out.count("earnings calendar not found") == 1
    (out,) = (tmp_path / CFG["output"]["dir"]).glob("*.csv")
    assert pd.read_csv(out)["Next_Earnings_Date"].isna().all()
