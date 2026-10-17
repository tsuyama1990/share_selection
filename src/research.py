"""One research task: prompt, LLM call, JSON check with a single re-ask, and quote verification."""

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import fields as F
from .llm import LLMClient
from .verify import check_claims

VERSION_HEX = 12  # hex digits of the prompt hash kept as the version
SYSTEM = "system"
RETRY = "retry"
CLAIM_KEYS = ("field", "claim", "quote", "doc_id")


class ReplyError(ValueError):
    """The model's reply is not the JSON object the task asks for."""


@dataclass(frozen=True)
class TaskResult:
    task: str
    answer: dict[str, Any]
    evidence: list[dict[str, str]]
    unknown: list[str]
    claims: int  # claims made, verified or not (``evidence`` holds the verified ones)
    providers: list[str]  # "<provider>/<model>" of every call made, in order


def load_prompts(prompt_dir: Path) -> dict[str, str]:
    """File stem -> text of every ``*.md`` in ``prompt_dir`` (``system``, ``t1``..``t5``, ``retry``)."""
    return {p.stem: p.read_text(encoding="utf-8") for p in sorted(prompt_dir.glob("*.md"))}


def prompt_version(prompts: dict[str, str]) -> str:
    """Hash of the prompt texts: any edit is a new version that needs its own passed review-eval."""
    digest = hashlib.sha256("\0".join(f"{name}\0{text}" for name, text in sorted(prompts.items())).encode())
    return digest.hexdigest()[:VERSION_HEX]


def build_messages(
    system: str, task_prompt: str, docs: dict[str, str], context: dict[str, Any]
) -> list[dict[str, str]]:
    documents = "\n".join(f'<document id="{doc_id}">\n{text}\n</document>' for doc_id, text in docs.items())
    user = f"{task_prompt}\n\n{json.dumps(context, ensure_ascii=False)}\n\n{documents}"
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def _claims_of(claims: Any) -> list[dict[str, str]]:
    if not isinstance(claims, list):
        raise ReplyError("claims must be a list")
    for c in claims:
        if not isinstance(c, dict) or not all(isinstance(c.get(k), str) for k in CLAIM_KEYS):
            raise ReplyError(f"every claim needs the string items {list(CLAIM_KEYS)}")
    return [{k: c[k] for k in CLAIM_KEYS} for c in claims]


def parse_reply(text: str, fields: list[str]) -> dict[str, Any]:
    """The reply as ``{"answer", "claims", "unknown"}`` (answer limited to ``fields``); else ``ReplyError``."""
    try:
        data = json.loads(text)
    except ValueError as e:
        raise ReplyError(f"the reply is not valid JSON ({e})") from e
    if not isinstance(data, dict) or not isinstance(data.get("answer"), dict):
        raise ReplyError("the reply must be an object with an answer object")
    if missing := [f for f in fields if f not in data["answer"]]:
        raise ReplyError(f"answer lacks the items {missing}")
    unknown = data.get(F.UNKNOWN, [])
    if not isinstance(unknown, list):
        raise ReplyError("unknown must be a list")
    return {
        "answer": {f: data["answer"][f] for f in fields},
        "claims": _claims_of(data.get("claims")),
        F.UNKNOWN: [str(u) for u in unknown],
    }


def run_task(
    llm: LLMClient,
    prompts: dict[str, str],
    task_fields: tuple[str, list[str]],
    docs: dict[str, str],
    context: dict[str, Any],
) -> TaskResult:
    """Run one task (name, answer items); ask once more with the error after an invalid reply, then ``ReplyError``."""
    task, fields = task_fields
    messages = build_messages(prompts[SYSTEM], prompts[task.lower()], docs, context)
    reply = llm.chat(messages, json_mode=True)
    providers = [f"{reply.provider}/{reply.model}"]
    try:
        data = parse_reply(reply.text, fields)
    except ReplyError as e:
        messages += [
            {"role": "assistant", "content": reply.text},
            {"role": "user", "content": prompts[RETRY].format(error=e)},
        ]
        reply = llm.chat(messages, json_mode=True)
        providers.append(f"{reply.provider}/{reply.model}")
        data = parse_reply(reply.text, fields)
    answer, evidence = check_claims(data["answer"], data["claims"], docs)
    return TaskResult(task, answer, evidence, data[F.UNKNOWN], len(data["claims"]), providers)
