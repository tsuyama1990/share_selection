"""A fake LLM for the review flow: it reads the task from the prompt's heading (``# T1 ...``) and the documents from
their ``<document id=...>`` tags, and answers in the JSON the real prompts ask for."""

import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx

from src.llm import Provider, Reply
from tests.fixtures.config import CFG

PROMPT_DIR = Path(__file__).resolve().parents[2] / CFG["review"]["prompt_dir"]
PROMPT_VERSION = CFG["review"]["prompt_version"]
MODEL = "fake-model"
FABRICATED = "NOT IN ANY DOCUMENT"
GOOD_ANSWERS: dict[str, dict[str, Any]] = {
    "T1": {
        "source_type": "P2 値上げの浸透",
        "demand_wave": "半導体",
        "tier": "unknown",
        "chokepoint": "unknown",
        "exposure_pct": "unknown",
    },
    "T2": {"one_off_items": "なし", "recurring_view": "持続"},
    "T3": {"capital_actions": "自社株買い", "n2_risk": "unknown"},
    "T4": {"reason_forgotten": "見えにくさ"},
    "T5": {"suggestion": "採用", "open_questions": ["顧客の集中"]},
}
UNKNOWN_ANSWERS = {task: {item: "unknown" for item in answer} for task, answer in GOOD_ANSWERS.items()}

Respond = Callable[[list[dict[str, str]]], str]


def task_of(messages: list[dict[str, str]]) -> str:
    return re.search(r"^# (T\d)", messages[1]["content"], re.M).group(1)  # type: ignore[union-attr]


def documents_of(messages: list[dict[str, str]]) -> dict[str, str]:
    return dict(re.findall(r'<document id="([^"]+)">\n(.*?)\n</document>', messages[1]["content"], re.S))


def reply(messages: list[dict[str, str]], answers: dict[str, dict[str, Any]], fabricate: bool = False) -> str:
    """One claim for every answered item, quoting the start of the first document (or a text no document has)."""
    doc_id, text = next(iter(documents_of(messages).items()))
    answer = answers[task_of(messages)]
    quote = FABRICATED if fabricate else text[:6]
    claims = [
        {"field": item, "claim": f"{item} is {value}", "quote": quote, "doc_id": doc_id}
        for item, value in answer.items()
        if value != "unknown"
    ]
    return json.dumps({"answer": answer, "claims": claims, "unknown": []}, ensure_ascii=False)


def good(messages: list[dict[str, str]]) -> str:
    return reply(messages, GOOD_ANSWERS)


def fabricating(messages: list[dict[str, str]]) -> str:
    return reply(messages, GOOD_ANSWERS, fabricate=True)


def clueless(messages: list[dict[str, str]]) -> str:
    return reply(messages, UNKNOWN_ANSWERS)


def not_json(messages: list[dict[str, str]]) -> str:
    return "this is not JSON"


class FakeLLM:
    """Stands in for ``LLMClient``; ``calls`` keeps a copy of the messages of every call."""

    primary = Provider("fake", "", MODEL, "")

    def __init__(self, respond: Respond = good):
        self.respond = respond
        self.calls: list[list[dict[str, str]]] = []

    def chat(self, messages: list[dict[str, str]], json_mode: bool = False) -> Reply:
        self.calls.append(list(messages))
        return Reply(self.respond(messages), "fake", MODEL)


def chat_handler(respond: Respond, fallback: Callable[[httpx.Request], httpx.Response]):
    """HTTP handler answering chat/completions requests with ``respond``; other requests go to ``fallback``."""

    def handler(request: httpx.Request) -> httpx.Response:
        if not request.url.path.endswith("chat/completions"):
            return fallback(request)
        text = respond(json.loads(request.content)["messages"])
        return httpx.Response(200, json={"choices": [{"message": {"content": text}}]})

    return handler
