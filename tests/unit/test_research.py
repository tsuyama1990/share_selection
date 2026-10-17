import json

import pytest

from src.llm import Reply
from src.research import ReplyError, TaskResult, build_messages, load_prompts, parse_reply, prompt_version, run_task

PROMPTS = {"system": "SYSTEM", "user": "{documents}\n{context}\n{task}", "t1": "# T1 task", "retry": "again: {error}"}
DOCS = {"d1": "営業利益は46億円増加した。"}
FIELDS = ["a", "b"]


def reply_json(answer=None, claims=None, **extra) -> str:
    claim = {"field": "a", "claim": "c", "quote": "46億円", "doc_id": "d1"}
    data = {"answer": answer or {"a": "x", "b": "y"}, "claims": [claim] if claims is None else claims, **extra}
    return json.dumps(data, ensure_ascii=False)


class Scripted:
    """An LLM answering with the given texts in order."""

    def __init__(self, *texts: str):
        self.texts, self.calls = list(texts), []

    def chat(self, messages, json_mode=False):
        self.calls.append((list(messages), json_mode))
        return Reply(self.texts.pop(0), "p", "m")


def test_build_messages_tags_documents_and_carries_instructions_and_context():
    prompts = {"system": "SYS", "user": "{documents}|{context}|{task}", "t1": "TASK"}
    system, user = build_messages(prompts, "T1", {"d1": "text one", "d2": "text two"}, {"name": "会社"})
    assert system == {"role": "system", "content": "SYS"}
    assert user["role"] == "user"
    assert user["content"].startswith('<document id="d1">') and user["content"].endswith("|TASK")
    assert '"name": "会社"' in user["content"]
    assert '<document id="d1">\ntext one\n</document>' in user["content"]
    assert '<document id="d2">\ntext two\n</document>' in user["content"]


def test_load_prompts_keys_by_file_stem(tmp_path):
    (tmp_path / "system.md").write_text("S", encoding="utf-8")
    (tmp_path / "t1.md").write_text("one", encoding="utf-8")
    (tmp_path / "ignored.txt").write_text("x", encoding="utf-8")
    assert load_prompts(tmp_path) == {"system": "S", "t1": "one"}


def test_parse_reply_returns_answer_limited_to_fields_claims_and_unknown():
    text = reply_json(answer={"a": 1, "b": 2, "extra": 3}, unknown=["z"])
    parsed = parse_reply(text, FIELDS)
    assert parsed["answer"] == {"a": 1, "b": 2}
    assert parsed["claims"] == [{"field": "a", "claim": "c", "quote": "46億円", "doc_id": "d1"}]
    assert parsed["unknown"] == ["z"]
    assert parse_reply(reply_json(), FIELDS)["unknown"] == []


@pytest.mark.parametrize(
    "text",
    [
        "not json",
        "[1]",
        json.dumps({"claims": []}),
        reply_json(answer={"a": "x"}),
        json.dumps({"answer": {"a": 1, "b": 2}}),
        reply_json(claims="no"),
        reply_json(claims=[{"field": "a", "claim": "c", "quote": "q"}]),
        reply_json(claims=[{"field": "a", "claim": "c", "quote": 5, "doc_id": "d1"}]),
        reply_json(claims=["text"]),
        reply_json(unknown="z"),
    ],
)
def test_parse_reply_rejects_what_the_task_did_not_ask_for(text):
    with pytest.raises(ReplyError):
        parse_reply(text, FIELDS)


def test_run_task_verifies_claims_and_records_the_provider():
    llm = Scripted(reply_json(claims=[{"field": "a", "claim": "c", "quote": "46 億円", "doc_id": "d1"}]))
    result = run_task(llm, PROMPTS, ("T1", FIELDS), DOCS, {})
    assert result == TaskResult(
        "T1",
        {"a": "x", "b": "unknown"},
        [{"field": "a", "claim": "c", "quote": "46 億円", "doc_id": "d1"}],
        [],
        1.0,
        ["p/m"],
    )
    assert llm.calls[0][1] is True  # JSON mode


def test_run_task_drops_claims_not_in_the_documents():
    llm = Scripted(reply_json(claims=[{"field": "a", "claim": "c", "quote": "存在しない", "doc_id": "d1"}]))
    result = run_task(llm, PROMPTS, ("T1", FIELDS), DOCS, {})
    assert (result.answer, result.evidence, result.claims) == ({"a": "unknown", "b": "unknown"}, [], 1)


def test_run_task_asks_once_more_with_the_error_after_an_invalid_reply():
    llm = Scripted("garbage", reply_json())
    result = run_task(llm, PROMPTS, ("T1", FIELDS), DOCS, {})
    assert result.providers == ["p/m", "p/m"]
    assert len(llm.calls) == 2
    second = llm.calls[1][0]
    assert second[-2] == {"role": "assistant", "content": "garbage"}
    assert second[-1]["content"].startswith("again: the reply is not valid JSON")


def test_run_task_raises_when_the_second_reply_is_invalid_too():
    llm = Scripted("garbage", "garbage again")
    with pytest.raises(ReplyError):
        run_task(llm, PROMPTS, ("T1", FIELDS), DOCS, {})
    assert len(llm.calls) == 2


def test_prompt_version_changes_with_any_prompt_text():
    base = {"system": "S", "t1": "one"}
    assert prompt_version(base) == prompt_version(dict(reversed(base.items())))
    assert prompt_version(base) != prompt_version({**base, "t1": "one!"})
