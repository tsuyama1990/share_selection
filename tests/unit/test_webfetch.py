import httpx
import pytest

from src.docstore import Document
from src.webfetch import download, extract_text, fetch_page, web_doc_id
from tests.fixtures.web import html_page, pdf_bytes

PAGE = html_page("Results 2026", "<p>Profit rose by 20%.</p>").encode()
MAX_BYTES = 10000
OWNER = "flow:20261018"


class FakeDocStore:
    """Stand-in for ``DocStore``: remembers the documents and errors instead of writing them."""

    def __init__(self, stored: bool = False) -> None:
        self.stored = stored
        self.documents: list[Document] = []
        self.errors: list[tuple[str, str, str, str]] = []

    def has(self, _doc_id: str) -> bool:
        return self.stored

    def put(self, document: Document) -> None:
        self.documents.append(document)
        self.stored = True

    def record_error(self, ticker: str, source: str, url: str, reason: str) -> None:
        self.errors.append((ticker, source, url, reason))


def page_client(page: bytes, content_type: str = "text/html; charset=utf-8", status: int = 200) -> httpx.Client:
    """A client that answers every request with ``status`` and ``page``."""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, content=page, headers={"content-type": content_type})

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_web_doc_id_ignores_case_of_scheme_and_host_and_fragment():
    a = web_doc_id("HTTPS://Example.COM/ir/a.html#top")
    assert a == web_doc_id("https://example.com/ir/a.html")
    assert a.startswith("web:") and len(a) == len("web:") + 16
    assert a != web_doc_id("https://example.com/ir/A.html")
    assert a != web_doc_id("https://example.com/ir/a.html?x=1")


def test_extract_text_html_title_and_body_without_script_and_navigation():
    body = html_page(
        " Results  2026 ",
        "<nav>menu</nav><header>head</header><script>var x = 1;</script>"
        "<noscript>no js</noscript><p>Profit  rose\n by 20%.</p><footer>foot</footer>",
    ).encode()
    assert extract_text(body, "text/html; charset=utf-8") == ("Results 2026", "Profit rose by 20%.")


def test_extract_text_decodes_shift_jis_declared_in_meta():
    page = html_page("決算短信", "<p>経常利益が増加</p>", meta='<meta charset="Shift_JIS">')
    assert extract_text(page.encode("shift_jis"), "text/html") == ("決算短信", "経常利益が増加")


def test_extract_text_uses_the_content_type_charset_first():
    page = html_page("決算", "<p>増益</p>").encode("euc_jp")
    assert extract_text(page, "text/html; charset=EUC-JP") == ("決算", "増益")


def test_extract_text_pdf_by_content_type_or_signature():
    pdf = pdf_bytes("Operating profit up")
    assert extract_text(pdf, "application/pdf")[1] == "Operating profit up"
    assert extract_text(pdf, "application/octet-stream")[1] == "Operating profit up"


def test_extract_text_rejects_other_types():
    with pytest.raises(ValueError, match="unsupported content type"):
        extract_text(b"{}", "application/json")


def test_download_returns_the_final_url_content_type_and_body():
    with page_client(PAGE) as http:
        final_url, content_type, body = download("https://example.com/ir/a.html", http, MAX_BYTES)
    assert (final_url, content_type, body) == ("https://example.com/ir/a.html", "text/html; charset=utf-8", PAGE)


def test_download_follows_a_redirect_and_returns_the_final_url():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/ir/old":
            return httpx.Response(301, headers={"location": "https://example.com/ir/new"})
        return httpx.Response(200, content=PAGE, headers={"content-type": "text/html"})

    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        final_url, _content_type, body = download("https://example.com/ir/old", http, MAX_BYTES)
    assert final_url == "https://example.com/ir/new"
    assert body == PAGE


def test_download_raises_a_value_error_on_an_error_status():
    with page_client(b"missing", status=404) as http, pytest.raises(ValueError, match="HTTP 404"):
        download("https://example.com/ir/missing.html", http, MAX_BYTES)


def test_download_raises_a_value_error_when_the_body_is_over_max_bytes():
    with page_client(b"x" * (MAX_BYTES + 1)) as http, pytest.raises(ValueError, match="too large"):
        download("https://example.com/ir/big.html", http, MAX_BYTES)


def test_fetch_page_stores_a_page_under_the_owner_and_returns_its_doc_id():
    store = FakeDocStore()
    with page_client(PAGE) as http:
        doc_id = fetch_page("https://example.com/news/a.html", http, store, MAX_BYTES, OWNER)
    assert doc_id == web_doc_id("https://example.com/news/a.html")
    assert [(d.doc_id, d.ticker) for d in store.documents] == [(doc_id, OWNER)]
    assert store.errors == []


def test_fetch_page_keeps_a_page_that_names_no_company():
    store = FakeDocStore()
    page = html_page("Market news", "<p>Semiconductor demand is rising.</p>").encode()
    with page_client(page) as http:
        assert fetch_page("https://example.com/news/market.html", http, store, MAX_BYTES, OWNER) is not None
    assert len(store.documents) == 1  # no company match: fetch_document would drop it


def test_fetch_page_returns_the_stored_doc_id_without_storing_again():
    store = FakeDocStore(stored=True)
    with page_client(PAGE) as http:
        doc_id = fetch_page("https://example.com/news/a.html", http, store, MAX_BYTES, OWNER)
    assert doc_id == web_doc_id("https://example.com/news/a.html")
    assert store.documents == []


def test_fetch_page_records_an_empty_page_under_the_owner():
    store = FakeDocStore()
    with page_client(html_page("", "<nav>menu</nav>").encode()) as http:
        assert fetch_page("https://example.com/news/empty.html", http, store, MAX_BYTES, OWNER) is None
    assert store.errors == [(OWNER, "web", "https://example.com/news/empty.html", "empty text")]
    assert store.documents == []


def test_fetch_page_records_a_failed_fetch_under_the_owner():
    store = FakeDocStore()
    with page_client(b"gone", status=500) as http:
        assert fetch_page("https://example.com/news/gone.html", http, store, MAX_BYTES, OWNER) is None
    assert store.errors == [(OWNER, "web", "https://example.com/news/gone.html", "HTTP 500")]
    assert store.documents == []
