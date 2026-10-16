"""EDINET API v2: filing index by submission day and the text sections of the latest annual securities report."""

import csv
import datetime
import fnmatch
import html
import io
import re
import zipfile
from typing import Any

import httpx

from src.docstore import DocStore, Document
from src.throttle import RateLimiter
from src.tickers import TICKER_SUFFIX

BODY_CSV = "XBRL_TO_CSV/jpcrp*asr*.csv"
BODY_ENCODING = "utf-16"
TAG = re.compile(r"<[^>]+>")


class EdinetClient:
    """The key travels in the URL query, so errors carry only the status code or the exception class."""

    def __init__(self, base_url: str, api_key: str, http: httpx.Client, limiter: RateLimiter):
        self._base_url, self._api_key, self._http, self._limiter = base_url.rstrip("/"), api_key, http, limiter

    def _get(self, path: str, **params: Any) -> httpx.Response:
        self._limiter.acquire()
        try:
            resp = self._http.get(f"{self._base_url}/{path}", params={**params, "Subscription-Key": self._api_key})
        except httpx.TransportError as e:
            raise RuntimeError(type(e).__name__) from None
        if resp.is_error:
            raise RuntimeError(f"HTTP {resp.status_code}")
        return resp

    def list_documents(self, day: datetime.date) -> dict:
        try:
            return self._get("documents.json", date=day.isoformat(), type=2).json()
        except ValueError:
            raise RuntimeError("invalid JSON") from None

    def download_csv_zip(self, doc_id: str) -> bytes:
        return self._get(f"documents/{doc_id}", type=5).content


def sec_code(ticker: str) -> str:
    """EDINET's 5 character code: the ticker code plus ``0`` (``"130A.T"`` -> ``"130A0"``)."""
    return ticker.removesuffix(TICKER_SUFFIX) + "0"


def parse_index(listing: dict, submit_date: datetime.date) -> list[dict]:
    """``edinet_index`` rows of a day's listing; filings without a secCode (funds, individuals) are dropped."""
    return [
        {
            "doc_id": d["docID"],
            "sec_code": d["secCode"],
            "edinet_code": d["edinetCode"],
            "doc_type_code": d["docTypeCode"],
            "period_end": d["periodEnd"],
            "submit_date": submit_date,
        }
        for d in listing.get("results", [])
        if d.get("secCode")
    ]


def extract_sections(zip_bytes: bytes, elements: list[str]) -> dict[str, str]:
    """Text (tags removed) of the listed elements, e.g. ``BusinessRisksTextBlock``, from the body CSV of the ZIP."""
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
        name = next((n for n in z.namelist() if fnmatch.fnmatch(n, BODY_CSV)), None)
        if name is None:
            return {}
        content = z.read(name).decode(BODY_ENCODING)
    sections: dict[str, str] = {}
    for row in csv.DictReader(io.StringIO(content), delimiter="\t"):
        element = row["要素ID"].rsplit(":", 1)[-1]
        if element in elements and element not in sections:
            sections[element] = " ".join(html.unescape(TAG.sub(" ", row["値"])).split())
    return sections


def update_index(client: EdinetClient, store: DocStore, today: datetime.date, index_days: int) -> int:
    """Index the days after the last indexed one (or the last ``index_days``) up to ``today``; stops at a failure."""
    last = store.index_last_date()
    day = today - datetime.timedelta(days=index_days) if last is None else last + datetime.timedelta(days=1)
    scanned = 0
    while day <= today:
        try:
            listing = client.list_documents(day)
        except RuntimeError as e:
            store.record_error("", "edinet", day.isoformat(), str(e))
            break
        store.add_index(parse_index(listing, day))
        scanned += 1
        day += datetime.timedelta(days=1)
    return scanned


def fetch_annual_report(
    client: EdinetClient, store: DocStore, ticker: str, doc_type_code: str, elements: list[str]
) -> list[str]:
    """Store the listed sections of the ticker's latest report; returns their doc_ids (empty after a failure)."""
    doc_id = store.latest_annual_report(sec_code(ticker), doc_type_code)
    if doc_id is None:
        store.record_error(ticker, "edinet", sec_code(ticker), "not in index")
        return []
    stored = [f"edinet:{doc_id}:{e}" for e in elements if store.has(f"edinet:{doc_id}:{e}")]
    if stored:
        return stored
    try:
        sections = extract_sections(client.download_csv_zip(doc_id), elements)
    except (RuntimeError, zipfile.BadZipFile, UnicodeError, KeyError) as e:
        store.record_error(ticker, "edinet", doc_id, f"{type(e).__name__} {e}".strip())
        return []
    if not sections:
        store.record_error(ticker, "edinet", doc_id, "no listed section")
        return []
    now = datetime.datetime.now()
    for element, text in sections.items():
        store.put(Document(f"edinet:{doc_id}:{element}", ticker, "edinet", f"{doc_id}:{element}", element, now, text))
    return [f"edinet:{doc_id}:{e}" for e in sections]
