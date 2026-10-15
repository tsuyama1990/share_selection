"""E7: `docs` stores the stage 2 candidates' EDINET sections and the web sources a Gemini search cites.

A failing ticker or page is recorded and the run goes on. EDINET, Gemini and the pages are mocked with
httpx.MockTransport; no key may appear in the output or the document store.
"""

import datetime

import duckdb
import httpx
import pytest

import main
from src import fields as F
from src.records import RecordStore
from tests.fixtures.config import CFG
from tests.fixtures.edinet import csv_zip, listing, listing_doc
from tests.fixtures.web import html_page, pdf_bytes

KEY = "SECRET-KEY-VALUE"
GEMINI_KEY = "SECRET-GEMINI-VALUE"
ANSWER = "ANSWER-TEXT-FROM-THE-MODEL"
CFG_DOCS = {
    **CFG,
    "edinet": {**CFG["edinet"], "index_days": 1, "request_interval_s": 0},
    "docstore": {"db_file": "docs_test.duckdb"},
    "docs": {**CFG["docs"], "search": False},
}
CFG_SEARCH = {
    **CFG_DOCS,
    "docs": {**CFG["docs"], "search": True, "max_sources": 2},
    "webfetch": {**CFG["webfetch"], "request_interval_s": 0},
    "llm": {**CFG["llm"], "max_calls_per_minute": 1000},
}
GEMINI_HOST = "generativelanguage.googleapis.com"
HTML_HEADERS = {"content-type": "text/html; charset=utf-8"}
INFO = {
    "issue": "2026-10",
    "git_sha": "abc",
    "config": {},
    "ticker_list_date": datetime.date(2026, 10, 1),
    "data_fetched_min": None,
    "data_fetched_max": None,
}
FAILING_DOC = "S2"


def result(ticker: str, candidate: bool) -> dict:
    return {
        "ticker": ticker,
        "stage1_pass": True,
        "stage1_fail_rule": None,
        "improvement_class": "clear",
        "stage2_candidate": candidate,
        "next_earnings_date": None,
        "quality_flags": [],
        "metrics": {F.NAME: f"Company {ticker}"},
    }


def edinet_handler(request: httpx.Request) -> httpx.Response:
    assert request.url.params["Subscription-Key"] == KEY
    if request.url.path.endswith("documents.json"):
        yesterday = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
        docs = [listing_doc(f"S{n}", f"{n}0") for n in (1, 2, 3, 4)] if request.url.params["date"] == yesterday else []
        return httpx.Response(200, json=listing(*docs))
    doc_id = request.url.path.rsplit("/", 1)[-1]
    if doc_id == FAILING_DOC:
        return httpx.Response(500)
    return httpx.Response(200, content=csv_zip({"jpcrp_cor:BusinessRisksTextBlock": f"<p>risk of {doc_id}</p>"}))


def gemini_response(request: httpx.Request) -> httpx.Response:
    assert request.headers["x-goog-api-key"] == GEMINI_KEY
    prompt = request.content.decode()
    if "Company 3.T" in prompt:
        return httpx.Response(500)
    code = "1" if "Company 1.T" in prompt else "2"
    uris = [
        f"https://redirect.example/{code}/page",
        f"https://redirect.example/{code}/broken",
        "https://ir.example/3rd",
    ]
    chunks = [{"web": {"title": "t", "uri": uri}} for uri in uris]
    candidate = {"content": {"parts": [{"text": ANSWER}]}, "groundingMetadata": {"groundingChunks": chunks}}
    return httpx.Response(200, json={"candidates": [candidate]})


def page_handler(request: httpx.Request) -> httpx.Response:
    url = request.url
    if url.path == "/1/page":
        return httpx.Response(302, headers={"location": "https://ir.example/1/final.html"})
    if url.path == "/1/final.html":
        return httpx.Response(200, headers=HTML_HEADERS, content=html_page("IR 1", "<p>profit of 1</p>").encode())
    if url.path == "/2/page":
        return httpx.Response(200, headers={"content-type": "application/pdf"}, content=pdf_bytes("profit of 2"))
    return httpx.Response(404)


def all_handler(request: httpx.Request) -> httpx.Response:
    if request.url.host == GEMINI_HOST:
        return gemini_response(request)
    if request.url.host == "api.edinet-fsa.go.jp":
        return edinet_handler(request)
    return page_handler(request)


def mock_http(monkeypatch, handler) -> None:
    real_client = httpx.Client
    monkeypatch.setattr(main.httpx, "Client", lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw))


def record_candidates(project) -> None:
    rec = CFG_DOCS["records"]
    with RecordStore(project.root / rec["db_file"], project.root / rec["export_dir"]) as store:
        store.record_run(INFO, [result("1.T", True), result("2.T", True), result("3.T", True), result("4.T", False)])


def test_docs_stores_candidates_and_survives_a_failure(project, monkeypatch, capsys):
    mock_http(monkeypatch, edinet_handler)
    monkeypatch.setenv("EDINET_API_KEY", KEY)
    record_candidates(project)

    project.run("docs", cfg=CFG_DOCS)

    out = capsys.readouterr().out
    assert "2 documents stored for 2 tickers; 1 tickers failed." in out
    with duckdb.connect(str(project.root / "docs_test.duckdb")) as con:
        docs = con.execute("SELECT doc_id, ticker, text FROM documents ORDER BY doc_id").fetchall()
        errors = con.execute("SELECT ticker, source, ref, error FROM fetch_errors").fetchall()
        dump = repr(
            con.execute("SELECT * FROM documents").fetchall() + con.execute("SELECT * FROM fetch_errors").fetchall()
        )
    assert docs == [
        ("edinet:S1:BusinessRisksTextBlock", "1.T", "risk of S1"),
        ("edinet:S3:BusinessRisksTextBlock", "3.T", "risk of S3"),
    ]
    assert errors == [("2.T", "edinet", "S2", "RuntimeError HTTP 500")]
    assert KEY not in out + dump


def test_docs_requires_the_api_key(project, monkeypatch, capsys):
    monkeypatch.delenv("EDINET_API_KEY", raising=False)
    try:
        project.run("docs", cfg=CFG_DOCS)
    except SystemExit as e:
        assert e.code == 1
    assert "EDINET_API_KEY" in capsys.readouterr().out


def test_docs_search_stores_web_sources_without_the_answer_or_keys(project, monkeypatch, capsys):
    mock_http(monkeypatch, all_handler)
    monkeypatch.setenv("EDINET_API_KEY", KEY)
    monkeypatch.setenv("GEMINI_API_KEY", GEMINI_KEY)
    record_candidates(project)

    project.run("docs", cfg=CFG_SEARCH)

    out = capsys.readouterr().out
    assert "2 documents stored for 2 tickers; 1 tickers failed. 2 web documents stored." in out
    with duckdb.connect(str(project.root / "docs_test.duckdb")) as con:
        web = con.execute("SELECT ticker, source_ref, title, text FROM documents WHERE source = 'web' ORDER BY ticker")
        web_rows = web.fetchall()
        errors = con.execute("SELECT ticker, source, ref, error FROM fetch_errors WHERE source = 'web'").fetchall()
        dump = repr(
            con.execute("SELECT * FROM documents").fetchall() + con.execute("SELECT * FROM fetch_errors").fetchall()
        )
    assert web_rows == [
        ("1.T", "https://ir.example/1/final.html", "IR 1", "profit of 1"),
        ("2.T", "https://redirect.example/2/page", "", "profit of 2"),
    ]
    assert sorted(errors) == [
        ("1.T", "web", "https://redirect.example/1/broken", "HTTP 404"),
        ("2.T", "web", "https://redirect.example/2/broken", "HTTP 404"),
        ("3.T", "web", "search", "Gemini search failed: HTTP 500"),
    ]
    assert ANSWER not in out + dump
    assert KEY not in out + dump and GEMINI_KEY not in out + dump


def test_docs_search_requires_the_gemini_key(project, monkeypatch, capsys):
    monkeypatch.setenv("EDINET_API_KEY", KEY)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(SystemExit) as e:
        project.run("docs", cfg=CFG_SEARCH)
    assert e.value.code == 1
    assert "GEMINI_API_KEY" in capsys.readouterr().out
