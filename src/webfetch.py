import datetime
import hashlib
import io
import logging
import re
from html.parser import HTMLParser
from urllib.parse import urlsplit

import httpx
from pypdf import PdfReader
from pypdf.errors import PyPdfError

from src.docstore import Company, DocStore, Document

SKIPPED_TAGS = {"script", "style", "noscript", "nav", "header", "footer"}
SNIFF_BYTES = 2048
DEFAULT_CHARSET = "utf-8"
NOT_ABOUT_COMPANY = "not about the company"
PDF_LOG_LEVEL = logging.ERROR  # pypdf warns about fonts on many valid PDFs
CHARSET = re.compile(rb"charset\s*=\s*[\"']?([\w-]+)", re.IGNORECASE)
# pypdf also raises TypeError, AttributeError and AssertionError on broken files [推論]; a bad page must not stop a flow
FETCH_ERRORS: tuple[type[BaseException], ...] = (
    httpx.HTTPError,
    ValueError,
    LookupError,
    PyPdfError,
    TypeError,
    AttributeError,
    AssertionError,
)

logging.getLogger("pypdf").setLevel(PDF_LOG_LEVEL)


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.skipped, self.in_title = 0, False
        self.title: list[str] = []
        self.text: list[str] = []

    def handle_starttag(self, tag, _attrs):
        self.skipped += tag in SKIPPED_TAGS
        self.in_title = self.in_title or tag == "title"

    def handle_endtag(self, tag):
        self.skipped -= tag in SKIPPED_TAGS and self.skipped > 0
        self.in_title = self.in_title and tag != "title"

    def handle_data(self, data):
        if self.in_title:
            self.title.append(data)
        elif not self.skipped:
            self.text.append(data)


def web_doc_id(final_url: str) -> str:
    parts = urlsplit(final_url)
    normalized = parts._replace(scheme=parts.scheme.lower(), netloc=parts.netloc.lower(), fragment="").geturl()
    return "web:" + hashlib.sha256(normalized.encode()).hexdigest()[:16]


def _collapse(text: str) -> str:
    return " ".join(text.split())


def extract_text(body: bytes, content_type: str) -> tuple[str, str]:
    """``(title, text)`` of an HTML page or PDF; the HTML charset is the header's, else the page's meta, else UTF-8."""
    if "pdf" in content_type or body.startswith(b"%PDF"):
        reader = PdfReader(io.BytesIO(body))
        return "", _collapse(" ".join(page.extract_text() for page in reader.pages))
    if "html" not in content_type:
        raise ValueError("unsupported content type")
    found = CHARSET.search(content_type.encode()) or CHARSET.search(body[:SNIFF_BYTES])
    charset = found.group(1).decode() if found else DEFAULT_CHARSET
    parser = _TextExtractor()
    parser.feed(body.decode(charset, errors="replace"))
    return _collapse("".join(parser.title)), _collapse(" ".join(parser.text))


def download(url: str, http: httpx.Client, max_bytes: int) -> tuple[str, str, bytes]:
    """``(final_url, content_type, body)``; raises ValueError on an error status or a body over ``max_bytes``."""
    with http.stream("GET", url, follow_redirects=True) as resp:
        if resp.is_error:
            raise ValueError(f"HTTP {resp.status_code}")
        body = bytearray()
        for chunk in resp.iter_bytes():
            body += chunk
            if len(body) > max_bytes:
                raise ValueError("too large")
        return str(resp.url), resp.headers.get("content-type", ""), bytes(body)


def _error_reason(error: BaseException) -> str:
    """The reason to record: the message of a ValueError, else the exception's class name."""
    return str(error) if isinstance(error, ValueError) else type(error).__name__


def fetch_document(url: str, company: Company, http: httpx.Client, store: DocStore, max_bytes: int) -> str | None:
    """Store the page behind ``url`` (first fetch of a final URL wins).

    A failure, or a page that does not name the company, is recorded and gives None.
    """
    try:
        final_url, content_type, body = download(url, http, max_bytes)
        doc_id = web_doc_id(final_url)
        if store.has(doc_id):
            return doc_id
        title, text = extract_text(body, content_type)
        if not text:
            raise ValueError("empty text")
    except FETCH_ERRORS as e:
        store.record_error(company.ticker, "web", url, _error_reason(e))
        return None
    if not company.mentioned_in(title + text):
        store.record_error(company.ticker, "web", url, NOT_ABOUT_COMPANY)
        return None
    store.put(Document(doc_id, company.ticker, "web", final_url, title, datetime.datetime.now(), text))
    return doc_id


def fetch_page(url: str, http: httpx.Client, store: DocStore, max_bytes: int, owner: str) -> str | None:
    """Store the page behind ``url`` under ``owner`` (first fetch of a final URL wins).

    The page is not matched to a company: it is the source of a flow memo, not of a ticker. A failure is recorded
    under ``owner`` and gives None.
    """
    try:
        final_url, content_type, body = download(url, http, max_bytes)
        doc_id = web_doc_id(final_url)
        if store.has(doc_id):
            return doc_id
        title, text = extract_text(body, content_type)
        if not text:
            raise ValueError("empty text")
    except FETCH_ERRORS as e:
        store.record_error(owner, "web", url, _error_reason(e))
        return None
    store.put(Document(doc_id, owner, "web", final_url, title, datetime.datetime.now(), text))
    return doc_id
