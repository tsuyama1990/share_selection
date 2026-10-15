"""E7: `docs` stores the stage 2 candidates' EDINET sections; a failing ticker is recorded and the run goes on.

EDINET is mocked with httpx.MockTransport. The Gemini search and web part of E7 arrives with feat/docs-web.
"""

import datetime

import duckdb
import httpx

import main
from src.records import RecordStore
from tests.fixtures.config import CFG
from tests.fixtures.edinet import csv_zip, listing, listing_doc

KEY = "SECRET-KEY-VALUE"
CFG_DOCS = {
    **CFG,
    "edinet": {**CFG["edinet"], "index_days": 1, "request_interval_s": 0},
    "docstore": {"db_file": "docs_test.duckdb"},
}
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
        "metrics": {},
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


def test_docs_stores_candidates_and_survives_a_failure(project, monkeypatch, capsys):
    real_client = httpx.Client
    monkeypatch.setattr(
        main.httpx, "Client", lambda **kw: real_client(transport=httpx.MockTransport(edinet_handler), **kw)
    )
    monkeypatch.setenv("EDINET_API_KEY", KEY)
    rec = CFG_DOCS["records"]
    with RecordStore(project.root / rec["db_file"], project.root / rec["export_dir"]) as store:
        store.record_run(INFO, [result("1.T", True), result("2.T", True), result("3.T", True), result("4.T", False)])

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
