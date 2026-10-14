import datetime
import io
from unittest import mock

import pandas as pd

from src.earnings_calendar import CSV_COLUMNS, load_calendar, merge_calendars, parse_calendar, update_calendar_csv

TODAY = datetime.date(2026, 10, 14)


def workbook(rows: list[list]) -> bytes:
    titles = [
        ["９月に四半期末を迎えた決算発表予定会社の一覧"],
        ["List of companies"],
        ["2026年10月8日 現在"],
        ["As of 2026/10/8"],
    ]
    header = [
        "決算発表予定日",
        "コード",
        "会社名",
        "Issue Name",
        "決算期末",
        "業種名",
        "Industry",
        "種別",
        "Period",
        "市場",
        "Market",
    ]
    buf = io.BytesIO()
    pd.DataFrame([*titles, header, *rows]).to_excel(buf, header=False, index=False)
    return buf.getvalue()


def row(date, code, period="Second quarter", fye=datetime.datetime(2027, 3, 31)):
    return [date, code, "名", "Name", fye, "小売業", "Retail", "第２四半期", period, "プライム", "Prime"]


def test_parse_skips_titles_and_keeps_undecided_and_alphanumeric_codes():
    xlsx = workbook(
        [
            row(datetime.datetime(2026, 10, 15), 2753),
            row("未定_Undecided", "130A", "Third quarter"),
        ]
    )
    df = parse_calendar(xlsx)
    assert df["code"].tolist() == ["2753", "130A"]
    assert df["announce_date"].iloc[0] == pd.Timestamp("2026-10-15")
    assert pd.isna(df["announce_date"].iloc[1])
    assert df["period_en"].tolist() == ["Second quarter", "Third quarter"]
    assert df["fiscal_year_end"].iloc[0] == pd.Timestamp("2027-03-31")


def test_merge_keeps_earliest_future_date_and_prefers_dated_over_undecided():
    a = parse_calendar(
        workbook([row(datetime.datetime(2026, 10, 1), 1111), row("未定_Undecided", 2222), row("未定_Undecided", 4444)])
    )
    b = parse_calendar(
        workbook(
            [
                row(datetime.datetime(2026, 11, 20), 1111),
                row(datetime.datetime(2026, 12, 1), 2222),
                row(datetime.datetime(2026, 11, 5), 1111),
            ]
        )
    )
    merged = merge_calendars([a, b], TODAY).set_index("code")
    assert merged.loc["1111", "announce_date"] == pd.Timestamp("2026-11-05")
    assert merged.loc["2222", "announce_date"] == pd.Timestamp("2026-12-01")
    assert pd.isna(merged.loc["4444", "announce_date"])


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
