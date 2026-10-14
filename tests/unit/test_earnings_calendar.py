import datetime

import pandas as pd

from src.earnings_calendar import merge_calendars, parse_calendar
from tests.fixtures.calendar_workbook import TODAY, row, workbook


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
