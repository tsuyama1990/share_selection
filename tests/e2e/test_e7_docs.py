"""E7: `docs` stores the stage 2 candidates' EDINET sections and the web sources a Gemini search cites.

A failing ticker or page is recorded and the run goes on. EDINET, Gemini and the pages are mocked with
httpx.MockTransport; no key may appear in the output or the document store. The loop logic (skipping, priority, quota
stop) is tested at integration level in tests/integration/test_collect.py.
"""

import duckdb
import httpx
import pytest

from tests.fixtures.config import CFG
from tests.fixtures.docs_flow import ANSWER, GEMINI_HOST, GEMINI_KEY, KEY, all_handler, record_candidates

CFG_SEARCH = {
    **CFG,
    "edinet": {**CFG["edinet"], "index_days": 1, "request_interval_s": 0},
    "docstore": {"db_file": "docs_test.duckdb"},
    "docs": {**CFG["docs"], "search": True, "max_sources": 2},
    "webfetch": {**CFG["webfetch"], "request_interval_s": 0},
    "llm": {**CFG["llm"], "max_calls_per_minute": 1000},
}
CFG_EDINET_ONLY = {**CFG_SEARCH, "docs": {**CFG_SEARCH["docs"], "search": False}}


def mock_http(monkeypatch) -> None:
    real_client = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kw: real_client(transport=httpx.MockTransport(all_handler), **kw))


def test_docs_stores_edinet_and_web_documents_and_survives_failures(project, monkeypatch, capsys):
    mock_http(monkeypatch)
    monkeypatch.setenv("EDINET_API_KEY", KEY)
    monkeypatch.setenv("GEMINI_API_KEY", GEMINI_KEY)
    record_candidates(project.root)

    project.run("docs", cfg=CFG_SEARCH)

    out = capsys.readouterr().out
    assert "2 documents stored for 2 tickers; 1 tickers failed. 2 web documents stored." in out
    with duckdb.connect(str(project.root / "docs_test.duckdb")) as con:
        sources = con.execute("SELECT source, count(*) FROM documents GROUP BY source ORDER BY source").fetchall()
        dump = repr(
            con.execute("SELECT * FROM documents").fetchall() + con.execute("SELECT * FROM fetch_errors").fetchall()
        )
    assert sources == [("edinet", 2), ("web", 2)]
    assert ANSWER not in out + dump
    assert KEY not in out + dump and GEMINI_KEY not in out + dump


def test_docs_without_search_reports_only_edinet(project, monkeypatch, capsys):
    mock_http(monkeypatch)
    monkeypatch.setenv("EDINET_API_KEY", KEY)
    record_candidates(project.root)

    project.run("docs", cfg=CFG_EDINET_ONLY)

    assert capsys.readouterr().out.endswith("2 documents stored for 2 tickers; 1 tickers failed.\n")


def test_docs_requires_the_api_key(project, monkeypatch, capsys):
    monkeypatch.delenv("EDINET_API_KEY", raising=False)
    with pytest.raises(SystemExit) as e:
        project.run("docs", cfg=CFG_EDINET_ONLY)
    assert e.value.code == 1
    assert "Error: set EDINET_API_KEY (environment or .env)." in capsys.readouterr().out


def test_docs_search_requires_the_gemini_key(project, monkeypatch, capsys):
    monkeypatch.setenv("EDINET_API_KEY", KEY)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(SystemExit) as e:
        project.run("docs", cfg=CFG_SEARCH)
    assert e.value.code == 1
    assert "GEMINI_API_KEY" in capsys.readouterr().out


def test_docs_reports_the_candidates_left_when_the_search_quota_is_used_up(project, monkeypatch, capsys):
    def handler(request):
        if request.url.host == GEMINI_HOST:
            return httpx.Response(429)
        return all_handler(request)

    real_client = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw))
    monkeypatch.setenv("EDINET_API_KEY", KEY)
    monkeypatch.setenv("GEMINI_API_KEY", GEMINI_KEY)
    record_candidates(project.root)

    project.run("docs", cfg=CFG_SEARCH)

    assert "Search quota used up: 3 candidates left for the next `docs` run." in capsys.readouterr().out
