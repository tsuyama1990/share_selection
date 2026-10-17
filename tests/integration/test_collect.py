"""I-C2-3/I-C2-4 flow of `collect_documents`: EDINET sections, web search and sources, skipping and the quota stop."""

import datetime

import httpx

from src.collect import CollectClients, CollectSettings, CollectSummary, collect_documents
from src.docstore import DocStore
from src.edinet import EdinetClient
from src.llm import GeminiSearch
from src.throttle import RateLimiter
from tests.fixtures.config import CFG
from tests.fixtures.docs_flow import ANSWER, CANDIDATES, GEMINI_HOST, GEMINI_KEY, KEY, all_handler

SETTINGS = CollectSettings.from_config(
    {**CFG, "edinet": {**CFG["edinet"], "index_days": 1}, "docs": {**CFG["docs"], "max_sources": 2}}
)
CALLS_PER_WINDOW = 1000  # no waiting in the tests


def clients(handler=all_handler, search: bool = True) -> CollectClients:
    http = httpx.Client(transport=httpx.MockTransport(handler))
    gemini = GeminiSearch(CFG["llm"]["search"]["base_url"], "m", GEMINI_KEY, http) if search else None
    edinet = EdinetClient(CFG["edinet"]["base_url"], KEY, http, RateLimiter(CALLS_PER_WINDOW, 1))
    return CollectClients(edinet, gemini, http, RateLimiter(CALLS_PER_WINDOW, 1), RateLimiter(CALLS_PER_WINDOW, 1))


def test_collects_edinet_sections_and_survives_a_failure(tmp_path):
    with DocStore(tmp_path / "d.duckdb") as store:
        summary = collect_documents(CANDIDATES, SETTINGS, clients(search=False), store, datetime.date.today())
        docs = store.con.execute("SELECT doc_id, ticker, text FROM documents ORDER BY doc_id").fetchall()
        errors = store.con.execute("SELECT ticker, source, ref, error FROM fetch_errors").fetchall()
    assert summary == CollectSummary(edinet_docs=2, edinet_failed=1, web_docs=0, searches_left=0)
    assert docs == [
        ("edinet:S1:BusinessRisksTextBlock", "1.T", "risk of S1"),
        ("edinet:S3:BusinessRisksTextBlock", "3.T", "risk of S3"),
    ]
    assert errors == [("2.T", "edinet", "S2", "RuntimeError HTTP 500")]


def test_search_stores_web_sources_without_the_answer_or_keys(tmp_path):
    with DocStore(tmp_path / "d.duckdb") as store:
        summary = collect_documents(CANDIDATES, SETTINGS, clients(), store, datetime.date.today())
        sql = "SELECT ticker, source_ref, title, text FROM documents WHERE source = 'web' ORDER BY ticker"
        web = store.con.execute(sql).fetchall()
        errors = store.con.execute("SELECT ticker, source, ref, error FROM fetch_errors WHERE source = 'web'")
        errors = errors.fetchall()
        everything = store.con.execute("SELECT * FROM documents").fetchall()
        everything += store.con.execute("SELECT * FROM fetch_errors").fetchall()
    assert (summary.web_docs, summary.searches_left) == (2, 0)
    assert web == [
        ("1.T", "https://ir.example/1/final.html", "IR 1", "profit of 1"),
        ("2.T", "https://redirect.example/2/page", "", "profit of 2"),
    ]
    assert sorted(errors) == [
        ("1.T", "web", "https://redirect.example/1/broken", "HTTP 404"),
        ("2.T", "web", "https://redirect.example/2/broken", "HTTP 404"),
        ("3.T", "web", "search", "Gemini search failed: HTTP 500"),
    ]
    text = repr(everything)
    assert ANSWER not in text
    assert KEY not in text and GEMINI_KEY not in text


def test_search_skips_searched_candidates_and_stops_at_the_quota(tmp_path):
    searched: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == GEMINI_HOST:
            searched.append(request.content.decode())
            if "Company 2.T" in searched[-1]:
                return httpx.Response(429)
        return all_handler(request)

    shuffled = [CANDIDATES[2], CANDIDATES[1], CANDIDATES[0]]
    with DocStore(tmp_path / "d.duckdb") as store:
        first = collect_documents(shuffled, SETTINGS, clients(handler), store, datetime.date.today())
        assert first.searches_left == 2
        assert ["Company 1.T" in s for s in searched] == [True, False]  # Priority_Rank order; 3.T never searched

        searched.clear()
        second = collect_documents(shuffled, SETTINGS, clients(handler), store, datetime.date.today())
        assert ["Company 2.T" in s for s in searched] == [True]  # 1.T already has web documents
        assert second.searches_left == 2
