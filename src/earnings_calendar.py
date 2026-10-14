"""JPX earnings announcement calendar (stage 4 input): one xlsx per quarter-end month, merged to a CSV."""

import datetime
import io
import re
import urllib.request
from collections.abc import Sequence
from pathlib import Path
from urllib.parse import urljoin

import pandas as pd

from .tickers import TICKER_SUFFIX

CODE_PATTERN = re.compile(r"^\d{3}[0-9A-Z]$")
# JPX workbook columns: announcement date, code, fiscal year end, English period
DATE_COL, CODE_COL, FISCAL_YEAR_END_COL, PERIOD_COL = 0, 1, 4, 8
CSV_COLUMNS = ["code", "announce_date", "period_en", "fiscal_year_end"]


def parse_calendar(xlsx: bytes) -> pd.DataFrame:
    """Data rows of one JPX workbook (title rows skipped); undecided dates become NaT."""
    raw = pd.read_excel(io.BytesIO(xlsx), header=None, dtype=object)
    codes = raw[CODE_COL].astype(str).str.strip()
    rows = raw[codes.str.match(CODE_PATTERN)]
    return pd.DataFrame(
        {
            "code": codes[rows.index],
            "announce_date": pd.to_datetime(rows[DATE_COL], errors="coerce"),
            "period_en": rows[PERIOD_COL],
            "fiscal_year_end": pd.to_datetime(rows[FISCAL_YEAR_END_COL], errors="coerce"),
        }
    ).reset_index(drop=True)


def merge_calendars(frames: Sequence[pd.DataFrame], today: datetime.date) -> pd.DataFrame:
    """One row per code: the earliest announcement date from today on, else undecided; past-only codes are dropped."""
    df = pd.concat(frames, ignore_index=True)
    df = df[df["announce_date"].isna() | (df["announce_date"] >= pd.Timestamp(today))]
    return df.sort_values(["code", "announce_date"], na_position="last").drop_duplicates("code").reset_index(drop=True)


def _download(url: str, user_agent: str, timeout_s: float) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": user_agent})
    with urllib.request.urlopen(request, timeout=timeout_s) as res:
        return res.read()


def update_calendar_csv(out_csv: Path, page_url: str, link_pattern: str, user_agent: str, timeout_s: float) -> int:
    """Download every workbook linked on the JPX page, write the merged CSV, return the number of codes."""
    page = _download(page_url, user_agent, timeout_s).decode("utf-8", errors="replace")
    links = sorted({urljoin(page_url, href) for href in re.findall(link_pattern, page)})
    merged = merge_calendars(
        [parse_calendar(_download(link, user_agent, timeout_s)) for link in links], datetime.date.today()
    )
    merged[CSV_COLUMNS].to_csv(out_csv, index=False, encoding="utf-8", date_format="%Y-%m-%d")
    return len(merged)


def load_calendar(path: Path) -> dict[str, tuple[str | None, str | None]]:
    """Ticker -> (announce date ``YYYY-MM-DD`` or None, English period or None); empty if no file."""
    if not path.exists():
        print(f"Warning: earnings calendar not found: {path} (run `calendar`); Next_Earnings_Date left empty.")
        return {}
    df = pd.read_csv(path, dtype=str)
    return {
        code + TICKER_SUFFIX: (_text(date), _text(period))
        for code, date, period in zip(df["code"], df["announce_date"], df["period_en"], strict=True)
    }


def _text(value: object) -> str | None:
    return value if isinstance(value, str) else None
