"""I-C9-5: `collect_profiles` stores every ticker's EDINET sections, records failures and skips stored reports."""

import datetime

import httpx

from src.collect import CollectClients, CollectSettings, CollectSummary, collect_profiles
from src.docstore import DocStore
from src.edinet import EdinetClient
from src.throttle import RateLimiter
from tests.fixtures.config import CFG
from tests.fixtures.docs_flow import EDINET_HOST, KEY, all_handler

TICKERS = ["1.T", "2.T", "3.T", "4.T"]
SETTINGS = CollectSettings.from_config(
    {**CFG, "edinet": {**CFG["edinet"], "index_days": 1, "sections": ["BusinessRisksTextBlock"]}}
)
CALLS_PER_WINDOW = 1000  # no waiting in the tests


def clients(handler) -> CollectClients:
    http = httpx.Client(transport=httpx.MockTransport(handler))
    edinet = EdinetClient(CFG["edinet"]["base_url"], KEY, http, RateLimiter(CALLS_PER_WINDOW, 1))
    return CollectClients(edinet, None, http, RateLimiter(CALLS_PER_WINDOW, 1), RateLimiter(CALLS_PER_WINDOW, 1))


def test_profiles_stores_sections_records_failures_and_skips_stored_reports(tmp_path):
    downloads: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == EDINET_HOST and "/documents/S" in request.url.path:
            downloads.append(request.url.path.rsplit("/", 1)[-1])
        return all_handler(request)

    with DocStore(tmp_path / "d.duckdb") as store:
        first = collect_profiles(TICKERS, SETTINGS, clients(handler), store, datetime.date.today())
        docs = store.con.execute("SELECT ticker, doc_id, text FROM documents ORDER BY doc_id").fetchall()
        errors = store.con.execute("SELECT ticker, source, ref, error FROM fetch_errors").fetchall()
        downloads.clear()
        second = collect_profiles(TICKERS, SETTINGS, clients(handler), store, datetime.date.today())
    assert first == CollectSummary(edinet_docs=3, edinet_failed=1, web_docs=0, searches_left=0)
    assert docs == [
        ("1.T", "edinet:S1:BusinessRisksTextBlock", "risk of S1"),
        ("3.T", "edinet:S3:BusinessRisksTextBlock", "risk of S3"),
        ("4.T", "edinet:S4:BusinessRisksTextBlock", "risk of S4"),
    ]
    assert errors == [("2.T", "edinet", "S2", "RuntimeError HTTP 500")]
    assert second == CollectSummary(edinet_docs=3, edinet_failed=1, web_docs=0, searches_left=0)
    assert downloads == ["S2"]
