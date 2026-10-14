import datetime
from unittest import mock

from src.earnings_calendar import CSV_COLUMNS, load_calendar, merge_calendars, parse_calendar, update_calendar_csv
from tests.unit.test_earnings_calendar import TODAY, row, workbook


def test_calendar_csv_round_trip_and_missing_file(tmp_path, capsys):
    frame = merge_calendars(
        [parse_calendar(workbook([row(datetime.datetime(2026, 10, 15), 2753), row("未定", "130A")]))], TODAY
    )
    path = tmp_path / "cal.csv"
    frame[CSV_COLUMNS].to_csv(path, index=False, date_format="%Y-%m-%d")
    cal = load_calendar(path)
    assert cal["2753.T"] == ("2026-10-15", "Second quarter")
    assert cal["130A.T"] == (None, "Second quarter")
    assert load_calendar(tmp_path / "none.csv") == {}
    assert "not found" in capsys.readouterr().out


def test_update_downloads_every_linked_workbook(tmp_path):
    files = {
        "https://x/index.html": b'<a href="/a/k08.xlsx"></a><a href="/a/k09.xlsx"></a><a href="/a/k09.xlsx"></a>',
        "https://x/a/k08.xlsx": workbook([row(datetime.datetime(2099, 1, 5), 1111)]),
        "https://x/a/k09.xlsx": workbook([row(datetime.datetime(2099, 1, 4), 1111), row("未定", 2222)]),
    }
    out = tmp_path / "cal.csv"
    with mock.patch("src.earnings_calendar._download", side_effect=lambda url, _ua: files[url]):
        count = update_calendar_csv(out, "https://x/index.html", r'href="([^"]+\.xlsx)"', "UA")
    assert count == 2
    assert load_calendar(out)["1111.T"][0] == "2099-01-04"
