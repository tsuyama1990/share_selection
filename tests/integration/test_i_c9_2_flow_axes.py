"""I-C9-2: the axes of a flow come from its documents. A reply that is not JSON is asked once more, a claim no
document supports leaves its axis unknown, and the verified ratio is recorded with the axes (L2 C9 section 7)."""

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from src import fields as F
from src.flow import FlowDeps, FlowSettings, Throttles, flow_memo
from src.research import load_prompts
from tests.fixtures.config import CFG
from tests.fixtures.review_flow import FakeLLM, documents_of

PROMPT_DIR = Path(__file__).resolve().parents[2] / CFG["flow"]["prompts_dir"]
PROMPTS = load_prompts(PROMPT_DIR)
NAME = "半導体補助金"
DEMAND = "半導体工場への補助金"
SECTOR = "水産・農林業"
DOC = "半導体工場への補助金が拡充される。"
AXES = tuple(CFG["flow"]["axes"])
ANSWER = {axis: f"{axis} の答え" for axis in AXES}
FABRICATED_AXIS = AXES[-1]
FABRICATED = "NOT IN ANY DOCUMENT"
NO_SELL = {"sells": False, "tier": F.UNKNOWN, "exposure": F.UNKNOWN}


@dataclass(frozen=True)
class Doc:
    doc_id: str
    text: str
    source: str = "edinet"


class NoWait:
    """A rate limiter that never waits."""

    def acquire(self) -> None:
        pass


class NoSource:
    """The search answer of a flow whose sources are given on the command line only."""

    sources: list[tuple[str, str]] = []

    def search(self, _query: str) -> "NoSource":
        return self


@dataclass
class FakeStore:
    """The document store as `flow_memo` reads it: the documents of the flow and the profile text per ticker."""

    docs: list[Doc]
    text_by_ticker: dict[str, str]

    def documents(self, _owner: str) -> list[Doc]:
        return self.docs

    def profiles(self) -> dict[str, str]:
        return self.text_by_ticker


class FakeRecords:
    """The run record with no metrics, so no company reaches the map."""

    def resolve_run(self, _run: str | None) -> str:
        return "run-1"

    def run_metrics(self, _run_id: str) -> dict[str, dict[str, Any]]:
        return {}

    def screen_row(self, _run_id: str, _ticker: str) -> dict[str, Any]:
        return {}


class FakeFlows:
    """Keeps what `flow_memo` records: the flow row, its axes and its companies."""

    def __init__(self) -> None:
        self.axes: list[Any] = []
        self.companies: list[Any] = []

    def save_flow(self, _row: Any) -> str:
        return "flow-1"

    def record_axes(self, _flow_id: str, rows: list[Any]) -> None:
        self.axes = list(rows)

    def record_companies(self, _flow_id: str, rows: list[Any]) -> None:
        self.companies = list(rows)


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


def flow_reply(messages: list[dict[str, str]], answer: dict[str, Any], fabricated: tuple[str, ...] = ()) -> str:
    """One claim per answered item, quoting the start of the first document shown (or a text no document has)."""
    doc_id, text = next(iter(documents_of(messages).items()))
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


class Lab:
    """A `FlowDeps` with stubs: the LLM answers through ``respond`` and everything recorded stays in memory."""

    def __init__(self, respond) -> None:  # noqa: ANN001 - a callable the tests write inline
        self.tasks: list[str] = []
        self.flows = FakeFlows()

        def answer(messages: list[dict[str, str]]) -> str:
            task = task_of(messages)
            self.tasks.append(task)
            return respond(task, messages)

        self.deps = FlowDeps(
            llm=FakeLLM(answer),
            prompts=PROMPTS,
            search=NoSource(),  # type: ignore[arg-type]
            store=FakeStore([Doc("d1", DOC)], {"1.T": DOC}),  # type: ignore[arg-type]
            flows=self.flows,  # type: ignore[arg-type]
            records=FakeRecords(),  # type: ignore[arg-type]
            history=lambda _ticker: pd.Series(dtype="float64"),
            sectors={"1.T": SECTOR},
            names={"1.T": "会社1"},
            http=None,  # type: ignore[arg-type]
            throttles=Throttles(NoWait(), NoWait()),  # type: ignore[arg-type]
        )


@pytest.fixture
def settings(tmp_path: Path) -> FlowSettings:
    cfg = {
        **CFG,
        "flow": {**CFG["flow"], "memo_dir": "memos", "prompts_dir": str(PROMPT_DIR)},
        "sector": {**CFG["sector"], "min_peers": 1},
    }
    return FlowSettings.from_config(cfg, tmp_path)


def test_invalid_json_is_asked_once_more_and_unverified_claims_leave_the_axis_unknown(settings: FlowSettings) -> None:
    def respond(task: str, messages: list[dict[str, str]]) -> str:
        if task == "terms":
            return json.dumps({"terms": ["半導体"]}, ensure_ascii=False)
        if task == "confirm":
            return flow_reply(messages, NO_SELL)
        if lab.tasks.count("axes") == 1:
            return "this is not JSON"
        return flow_reply(messages, ANSWER, (FABRICATED_AXIS,))

    lab = Lab(respond)
    summary = flow_memo(NAME, DEMAND, (), settings, lab.deps)

    assert lab.tasks.count("axes") == 2  # the invalid reply and the one re-ask, no more
    assert summary.unknown_axes == [FABRICATED_AXIS]
    assert [row.axis for row in lab.flows.axes] == list(AXES)
    assert lab.flows.axes[-1].answer == {"value": F.UNKNOWN}
    assert all(0.0 < row.verified_ratio < 1.0 for row in lab.flows.axes)
    assert summary.memo_path.exists()
    assert summary.companies == lab.flows.companies == []


def test_verified_claims_answer_every_axis(settings: FlowSettings) -> None:
    def respond(task: str, messages: list[dict[str, str]]) -> str:
        if task == "terms":
            return json.dumps({"terms": ["半導体"]}, ensure_ascii=False)
        if task == "confirm":
            return flow_reply(messages, NO_SELL)
        return flow_reply(messages, ANSWER)

    lab = Lab(respond)
    summary = flow_memo(NAME, DEMAND, (), settings, lab.deps)

    assert summary.unknown_axes == []
    assert [row.answer for row in lab.flows.axes] == [{"value": ANSWER[axis]} for axis in AXES]
    assert all(row.verified_ratio == 1.0 for row in lab.flows.axes)
    assert FABRICATED not in summary.memo_path.read_text(encoding="utf-8")
