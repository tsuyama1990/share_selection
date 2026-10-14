"""E2: `calendar` then `analyze` puts announcement dates into the result CSV and the records."""

import datetime
from pathlib import Path
from unittest import mock

import pandas as pd

from tests.e2e.conftest import CFG
from tests.unit.test_earnings_calendar import row, workbook

GOLDEN = Path(__file__).parent.parent / "fixtures" / "golden_screening.csv"
DATE = datetime.datetime(2099, 1, 5)
WORKBOOK_URL = "https://www.jpx.co.jp/a/k08.xlsx"


def run_calendar(project, codes: list[int]) -> None:
    files = {
        CFG["calendar"]["page_url"]: b'<a href="/a/k08.xlsx"></a>',
        WORKBOOK_URL: workbook([row(DATE, c) for c in codes]),
    }
    with mock.patch("src.earnings_calendar._download", side_effect=lambda url, _ua: files[url]):
        project.run("calendar")


def test_calendar_dates_reach_csv_and_records(project):
    tickers = project.seed_sample()
    dated = pd.read_csv(GOLDEN)["Ticker"].iloc[0]  # a ticker that passes the gatekeeper, so it is in the CSV
    run_calendar(project, [int(dated.removesuffix(".T"))])
    project.run("analyze")

    dates = dict(project.query("SELECT ticker, next_earnings_date FROM screen_results"))
    assert set(dates) == set(tickers)
    assert dates[dated] == DATE.date()
    assert [t for t, d in dates.items() if d is not None] == [dated]
    (out,) = (project.root / CFG["output"]["dir"]).glob("*.csv")
    report = pd.read_csv(out, dtype=str).set_index("Ticker")
    assert report.loc[dated, "Next_Earnings_Date"] == "2099-01-05"
    assert report.loc[dated, "Earnings_Period"] == "Second quarter"
    assert report.drop(index=dated)["Next_Earnings_Date"].isna().all()


def test_dates_are_empty_without_calendar_entry(project, capsys):
    project.seed_sample()
    project.run("analyze")

    assert capsys.readouterr().out.count("earnings calendar not found") == 1
    (out,) = (project.root / CFG["output"]["dir"]).glob("*.csv")
    report = pd.read_csv(out)
    assert report["Next_Earnings_Date"].isna().all()
    assert report["Earnings_Period"].isna().all()
    assert all(d is None for _, d in project.query("SELECT ticker, next_earnings_date FROM screen_results"))
