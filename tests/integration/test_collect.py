"""I-C2-3/I-C2-4 flow of `collect_documents`: EDINET sections, web search and sources, skipping and the quota stop."""

import datetime

import httpx

from src.collect import CollectClients, CollectSettings, CollectSummary, collect_documents
from src.docstore import DocStore
from src.edinet import EdinetClient
from src.llm import GeminiSearch
from src.throttle import RateLimiter
from tests.fixtures.config import CFG
from tests.fixtures.docs_flow import ANSWER, COMPANIES, GEMINI_HOST, GEMINI_KEY, KEY, all_handler

SETTINGS = CollectSettings.from_config(
    {**CFG, "edinet": {**CFG["edinet"], "index_days": 1}, "docs": {**CFG["docs"], "max_sources": 3}}
)
CALLS_PER_WINDOW = 1000  # no waiting in the tests


def clients(handler=all_handler, search: bool = True) -> CollectClients:
    http = httpx.Client(transport=httpx.MockTransport(handler))
    gemini = GeminiSearch(CFG["llm"]["search"]["base_url"], "m", GEMINI_KEY, http) if search else None
    edinet = EdinetClient(CFG["edinet"]["base_url"], KEY, http, RateLimiter(CALLS_PER_WINDOW, 1))
    return CollectClients(edinet, gemini, http, RateLimiter(CALLS_PER_WINDOW, 1), RateLimiter(CALLS_PER_WINDOW, 1))


def test_collects_edinet_sections_and_survives_a_failure(tmp_path):
    with DocStore(tmp_path / "d.duckdb") as store:
        summary = collect_documents(COMPANIES, SETTINGS, clients(search=False), store, datetime.date.today())
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
        summary = collect_documents(COMPANIES, SETTINGS, clients(), store, datetime.date.today())
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
        ("1.T", "web", "https://redirect.example/1/other", "not about the company"),
        ("2.T", "web", "https://redirect.example/2/broken", "HTTP 404"),
        ("2.T", "web", "https://redirect.example/2/other", "not about the company"),
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
            if "会社2" in searched[-1]:
                return httpx.Response(429)
        return all_handler(request)

    ordered = [COMPANIES[2], COMPANIES[0], COMPANIES[1]]
    with DocStore(tmp_path / "d.duckdb") as store:
        first = collect_documents(ordered, SETTINGS, clients(handler), store, datetime.date.today())
        assert [next(n for n in ("会社3", "会社1", "会社2") if n in s) for s in searched] == ["会社3", "会社1", "会社2"]
        assert first.searches_left == 1  # the given order, not the ticker order; 2.T hit the quota

        searched.clear()
        second = collect_documents(ordered, SETTINGS, clients(handler), store, datetime.date.today())
        assert [next(n for n in ("会社3", "会社2") if n in s) for s in searched] == ["会社3", "会社2"]  # not 1.T
        assert second.searches_left == 1


def test_search_prompt_names_the_company_in_japanese_with_the_code(tmp_path):
    prompts: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == GEMINI_HOST:
            prompts.append(request.content.decode())
        return all_handler(request)

    with DocStore(tmp_path / "d.duckdb") as store:
        collect_documents(COMPANIES[:1], SETTINGS, clients(handler), store, datetime.date.today())
    assert "会社1" in prompts[0] and "証券コード1" in prompts[0]
