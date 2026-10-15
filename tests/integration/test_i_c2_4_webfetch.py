"""I-C2-4: web pages -> document store (httpx.MockTransport, temporary DuckDB file)."""

import httpx
import pytest

from src.docstore import DocStore
from src.webfetch import fetch_document, web_doc_id
from tests.fixtures.web import html_page, pdf_bytes

MAX_BYTES = 10_000
REDIRECT = "https://vertexaisearch.example/redirect/abc"
FINAL = "https://ir.example.co.jp/q1.html"


def pages(request: httpx.Request) -> httpx.Response:
    url = str(request.url)
    html = {"content-type": "text/html; charset=utf-8"}
    if url == REDIRECT:
        return httpx.Response(302, headers={"location": FINAL})
    if url == FINAL:
        return httpx.Response(200, headers=html, content=html_page("Q1", "<p>Profit rose</p>").encode())
    if url.endswith("/report.pdf"):
        return httpx.Response(200, headers={"content-type": "application/pdf"}, content=pdf_bytes("PDF profit"))
    if url.endswith("/huge.html"):
        return httpx.Response(200, headers=html, content=b"x" * (MAX_BYTES + 1))
    if url.endswith("/data.json"):
        return httpx.Response(200, headers={"content-type": "application/json"}, content=b"{}")
    if url.endswith("/empty.html"):
        return httpx.Response(200, headers=html, content=b"<html><script>x</script></html>")
    return httpx.Response(404)


@pytest.fixture
def env(tmp_path):
    http = httpx.Client(transport=httpx.MockTransport(pages))
    with DocStore(tmp_path / "docs.duckdb") as store:
        yield http, store


def fetch(env, url: str) -> str | None:
    http, store = env
    return fetch_document(url, "1.T", http, store, MAX_BYTES)


def rows(env, sql: str) -> list:
    _, store = env
    return store.con.execute(sql).fetchall()


def test_redirect_is_followed_and_the_final_url_stored(env):
    doc_id = fetch(env, REDIRECT)

    assert doc_id == web_doc_id(FINAL)
    assert rows(env, "SELECT doc_id, ticker, source, source_ref, title, text FROM documents") == [
        (doc_id, "1.T", "web", FINAL, "Q1", "Profit rose")
    ]


def test_pdf_text_is_stored(env):
    doc_id = fetch(env, "https://ir.example.co.jp/report.pdf")

    assert rows(env, f"SELECT text FROM documents WHERE doc_id = '{doc_id}'") == [("PDF profit",)]


@pytest.mark.parametrize(
    ("path", "reason"),
    [
        ("missing.html", "HTTP 404"),
        ("huge.html", "too large"),
        ("data.json", "unsupported content type"),
        ("empty.html", "empty text"),
    ],
)
def test_failures_are_recorded_and_nothing_stored(env, path, reason):
    url = f"https://ir.example.co.jp/{path}"

    assert fetch(env, url) is None
    assert rows(env, "SELECT ticker, source, ref, error FROM fetch_errors") == [("1.T", "web", url, reason)]
    assert rows(env, "SELECT count(*) FROM documents") == [(0,)]


def test_transport_error_is_recorded_by_class_name(tmp_path):
    def refuse(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("secret detail")

    http = httpx.Client(transport=httpx.MockTransport(refuse))
    with DocStore(tmp_path / "d.duckdb") as store:
        assert fetch_document("https://x.example/a", "1.T", http, store, MAX_BYTES) is None
        assert store.con.execute("SELECT error FROM fetch_errors").fetchall() == [("ConnectError",)]


def test_existing_doc_id_is_not_rewritten(env):
    first = fetch(env, FINAL)
    http, store = env
    changed = httpx.Client(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(
                200, headers={"content-type": "text/html"}, content=html_page("Q1", "<p>Changed</p>").encode()
            )
        )
    )

    assert fetch_document(FINAL, "2.T", changed, store, MAX_BYTES) == first
    assert rows(env, "SELECT ticker, text FROM documents") == [("1.T", "Profit rose")]
    assert rows(env, "SELECT count(*) FROM fetch_errors") == [(0,)]
