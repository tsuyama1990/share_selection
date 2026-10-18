"""E10: `flow-memo` gathers the sources of a flow the user names, extracts the axes, maps the beneficiary companies
and writes the research memo (E10a); it stops with guidance before `profiles` (E10b), and no key reaches the output,
the memo or the databases (E10c). L1 section 7.2.

EDINET, the Gemini search, the cited pages and the LLM are mocked with httpx.MockTransport. The fake LLM reads the
task from the prompt's heading (``# axes``) and the documents from their ``<document id=...>`` tags."""

import datetime
import json
import re
from pathlib import Path

import duckdb
import httpx
import pytest

from src import fields as F
from tests.fixtures.config import CFG
from tests.fixtures.docs_flow import EDINET_HOST, GEMINI_HOST, GEMINI_KEY, HTML_HEADERS, KEY, SECTOR, record_candidates
from tests.fixtures.edinet import csv_zip, listing, listing_doc
from tests.fixtures.review_flow import chat_handler, documents_of
from tests.fixtures.web import html_page

NAME = "半導体補助金"
DEMAND = "半導体工場への補助金"
SOURCE_URL = "https://example.com/report"
CITED_URL = "https://ir.example/flow.html"
PAGE_TEXT = "政府が半導体工場への補助金を拡充する方針を示した"
TERMS = ["半導体", "検査装置"]
PROFILES = {
    "S1": "半導体検査装置を製造している。",
    "S2": "半導体材料を扱う商社。",
    "S3": "検査装置向けの部材を供給する。",
}
TICKERS = ("1.T", "2.T", "3.T")
SELLS = {"1.T": True, "2.T": False, "3.T": True}
AXES = tuple(CFG["flow"]["axes"])
ANSWERS = {axis: f"{axis} の答え" for axis in AXES}
FABRICATED_AXIS = AXES[-1]
FABRICATED = "NOT IN ANY DOCUMENT"
SECTION = "jpcrp_cor:DescriptionOfBusinessTextBlock"
FLOW_PROMPT_DIR = Path(__file__).resolve().parents[2] / CFG["flow"]["prompts_dir"]
CFG_FLOW = {
    **CFG,
    "edinet": {**CFG["edinet"], "index_days": 1, "request_interval_s": 0},
    "docstore": {"db_file": "docs_test.duckdb"},
    "flow": {**CFG["flow"], "db_file": "flow_test.duckdb", "prompts_dir": str(FLOW_PROMPT_DIR)},
    "llm": {**CFG["llm"], "max_calls_per_minute": 1000},
    "webfetch": {**CFG["webfetch"], "request_interval_s": 0},
    "sector": {**CFG["sector"], "min_peers": 1},
}


def task_of(messages: list[dict[str, str]]) -> str:
    """The task from the context the caller passes (``ticker`` for a confirmation, ``name`` for the axes), or
    from the prompt's heading (``# axes``) when the prompts carry one."""
    text = "\n".join(message["content"] for message in messages)
    if '"ticker":' in text:
        return "confirm"
    if '"name":' in text:
        return "axes"
    match = re.search(r"^# (axes|confirm)\b", text, re.M)
    if match:
        return match.group(1)
    return "confirm" if "sells" in text else "terms"


def ticker_of(messages: list[dict[str, str]]) -> str:
    """The company the prompt is about, from the context the caller passes to the task."""
    text = "\n".join(message["content"] for message in messages)
    return next((ticker for ticker in TICKERS if ticker in text), "")


def reply(docs: dict[str, str], answer: dict[str, object], fabricated: tuple[str, ...] = ()) -> str:
    """One claim per answered item, quoting the start of the first document shown (or a text no document has)."""
    doc_id, text = next(iter(docs.items()))
    claims = [
        {
            "field": field,
            "claim": f"{field} は {value}",
            "quote": FABRICATED if field in fabricated else text[:6],
            "doc_id": doc_id,
        }
        for field, value in answer.items()
        if value != F.UNKNOWN
    ]
    return json.dumps({"answer": answer, "claims": claims, "unknown": []}, ensure_ascii=False)


def respond_with(task: str, messages: list[dict[str, str]]) -> str:
    """The fake LLM: search terms, the confirmation of a company, or the axes; one axis quotes a text nobody wrote."""
    if task == "terms":
        return json.dumps({"terms": TERMS}, ensure_ascii=False)
    docs = documents_of(messages)
    if not docs:
        return json.dumps({"answer": {}, "claims": [], "unknown": []}, ensure_ascii=False)
    if task == "confirm":
        if SELLS.get(ticker_of(messages)):
            return reply(docs, {"sells": True, "tier": "1次", "exposure": "売上の1割"})
        return reply(docs, {"sells": False, "tier": F.UNKNOWN, "exposure": F.UNKNOWN})
    return reply(docs, ANSWERS, (FABRICATED_AXIS,))


def search_response(request: httpx.Request) -> httpx.Response:
    assert request.headers["x-goog-api-key"] == GEMINI_KEY
    chunks = [{"web": {"title": "補助金の報道", "uri": CITED_URL}}]
    candidate = {"content": {"parts": [{"text": "…"}]}, "groundingMetadata": {"groundingChunks": chunks}}
    return httpx.Response(200, json={"candidates": [candidate]})


def edinet_response(request: httpx.Request) -> httpx.Response:
    assert request.url.params["Subscription-Key"] == KEY
    if request.url.path.endswith("documents.json"):
        yesterday = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
        docs = [listing_doc(f"S{n}", f"{n}0") for n in (1, 2, 3)] if request.url.params["date"] == yesterday else []
        return httpx.Response(200, json=listing(*docs))
    doc_id = request.url.path.rsplit("/", 1)[-1]
    return httpx.Response(200, content=csv_zip({SECTION: f"<p>{PROFILES[doc_id]}</p>"}))


def page_response(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/robots.txt":
        return httpx.Response(404)
    return httpx.Response(200, headers=HTML_HEADERS, content=html_page("補助金", f"<p>{PAGE_TEXT}</p>").encode())


def fallback(request: httpx.Request) -> httpx.Response:
    if request.url.host == GEMINI_HOST:
        return search_response(request)
    if request.url.host == EDINET_HOST:
        return edinet_response(request)
    return page_response(request)


@pytest.fixture
def setup(project, monkeypatch):
    """A recorded run, keys set and ``llm`` mocked; ``tasks`` keeps the task of every LLM call."""
    for name in ("GROQ_API_KEY", "DEEPSEEK_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("EDINET_API_KEY", KEY)
    monkeypatch.setenv("GEMINI_API_KEY", GEMINI_KEY)
    run_id = record_candidates(project.root)
    tasks: list[str] = []

    def respond(messages: list[dict[str, str]]) -> str:
        task = task_of(messages)
        tasks.append(task)
        return respond_with(task, messages)

    real_client = httpx.Client
    handler = chat_handler(respond, fallback)
    monkeypatch.setattr(httpx, "Client", lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw))
    return project, run_id, tasks


def run_cmd(project, *args: str) -> int:
    try:
        project.run(*args, cfg=CFG_FLOW)
    except SystemExit as e:
        return e.code
    return 0


def memo_path(project) -> Path:
    return project.root / CFG_FLOW["flow"]["memo_dir"] / f"{NAME}-{datetime.date.today():%Y-%m-%d}.md"


def table_dump(project, cfg: dict, section: str) -> str:
    """Every row of every table of the DB file of ``section``, as text."""
    with duckdb.connect(str(project.root / cfg[section]["db_file"])) as con:
        names = [name for (name,) in con.execute("SHOW TABLES").fetchall()]
        return repr([con.execute(f"SELECT * FROM {name}").fetchall() for name in names])


def test_flow_memo_writes_the_axes_the_map_and_the_numbers(setup, capsys):
    project, run_id, tasks = setup
    assert run_cmd(project, "profiles") == 0
    capsys.readouterr()

    assert run_cmd(project, "flow-memo", "--name", NAME, "--demand", DEMAND, "--url", SOURCE_URL) == 0
    path = memo_path(project)
    assert capsys.readouterr().out == f"Flow memo written to {path}: 2 companies, 1 axes unknown.\n"

    text = path.read_text(encoding="utf-8")
    assert text.startswith(f"# {NAME}") and f"- 需要: {DEMAND}" in text
    assert all(f"### {axis}" in text for axis in AXES)
    assert ANSWERS[FABRICATED_AXIS] not in text and F.UNKNOWN in text and FABRICATED not in text
    assert "1.T" in text and "3.T" in text and "2.T" not in text
    assert SECTOR in text and "clear" in text and "○" in text and "1次" in text
    assert project.query("SELECT name, demand FROM flows", CFG_FLOW, "flow") == [(NAME, DEMAND)]
    axes = project.query("SELECT DISTINCT axis FROM flow_axes", CFG_FLOW, "flow")
    assert sorted(axis for (axis,) in axes) == sorted(AXES)
    assert F.UNKNOWN in repr(project.query("SELECT axis, answer FROM flow_axes", CFG_FLOW, "flow"))
    rows = project.query("SELECT ticker, tier FROM flow_companies ORDER BY ticker", CFG_FLOW, "flow")
    assert rows == [("1.T", "1次"), ("3.T", "1次")]
    assert tasks.count("terms") == 1 and tasks.count("confirm") == len(TICKERS) and tasks.count("axes") <= 2


def test_flow_memo_stops_with_guidance_before_profiles(setup, capsys):
    project, _, _ = setup
    assert run_cmd(project, "flow-memo", "--name", NAME, "--demand", DEMAND) == 1
    assert capsys.readouterr().out == "Error: the document store holds no profile text. Run `profiles` first.\n"
    assert not memo_path(project).exists()
    assert project.query("SELECT ticker FROM flow_companies", CFG_FLOW, "flow") == []


def test_no_key_reaches_the_output_the_memo_or_the_databases(setup, capsys):
    project, _, _ = setup
    run_cmd(project, "profiles")
    assert run_cmd(project, "flow-memo", "--name", NAME, "--demand", DEMAND) == 0
    captured = capsys.readouterr()
    dump = captured.out + captured.err + memo_path(project).read_text(encoding="utf-8")
    dump += table_dump(project, CFG_FLOW, "flow") + table_dump(project, CFG_FLOW, "docstore")
    assert dump and KEY not in dump and GEMINI_KEY not in dump
