"""Mocked EDINET, Gemini and web pages of the `docs` flow, and three candidates (2.T has a failing EDINET download)."""

import datetime

import httpx

from src import fields as F
from src.records import RecordStore, RunInfo
from src.screener import ScreenResult
from tests.fixtures.config import CFG
from tests.fixtures.edinet import csv_zip, listing, listing_doc
from tests.fixtures.web import html_page, pdf_bytes

KEY = "SECRET-KEY-VALUE"
GEMINI_KEY = "SECRET-GEMINI-VALUE"
ANSWER = "ANSWER-TEXT-FROM-THE-MODEL"
GEMINI_HOST = "generativelanguage.googleapis.com"
EDINET_HOST = "api.edinet-fsa.go.jp"
HTML_HEADERS = {"content-type": "text/html; charset=utf-8"}
FAILING_DOC = "S2"
CANDIDATES = [(f"{n}.T", {F.NAME: f"Company {n}.T", F.PRIORITY_RANK: n}) for n in (1, 2, 3)]
INFO = RunInfo("2026-10", "abc", {}, datetime.date(2026, 10, 1), None, None)


def record_candidates(root) -> str:
    """Record a run in which the three CANDIDATES are the stage 2 candidates; returns its run id."""
    results = {
        ticker: ScreenResult(True, None, {**metrics, F.IMPROVEMENT_CLASS: "clear", F.STAGE2_CANDIDATE: True})
        for ticker, metrics in CANDIDATES
    }
    with RecordStore.from_config(CFG, root) as store:
        return store.record_run(INFO, results)


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
    if request.url.host == EDINET_HOST:
        return edinet_handler(request)
    return page_handler(request)
