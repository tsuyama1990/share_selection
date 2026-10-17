"""I-C4-3: the real prompts, `run_task` and the quote check with a fake LLM (one re-ask, unsupported items dropped)."""

import pytest

from src.research import SYSTEM, ReplyError, build_messages, load_prompts, run_task
from tests.fixtures.config import CFG
from tests.fixtures.review_flow import PROMPT_DIR, FakeLLM, clueless, fabricating, good, not_json

PROMPTS = load_prompts(PROMPT_DIR)
TASKS = CFG["review"]["tasks"]
DOCS = {"edinet:S1:Risk": "事業等のリスク。原材料価格の高騰。", "web:abc": "セメントの値上げで営業利益が増加した。"}


def test_every_task_has_a_prompt_that_names_its_answer_items():
    assert {SYSTEM, "user", "retry", *(t.lower() for t in TASKS)} == set(PROMPTS)
    for task, fields in TASKS.items():
        prompt = PROMPTS[task.lower()]
        assert prompt.startswith(f"# {task} ")
        assert [f for f in fields if f not in prompt] == []


def test_prompts_fix_the_rules_of_the_reply():
    system = PROMPTS[SYSTEM]
    for rule in ("逐語", "unknown", '"claims"', '"answer"', "doc_id"):
        assert rule in system
    assert "{error}" in PROMPTS["retry"]
    assert PROMPTS["retry"].format(error="E").count("E") >= 1
    assert all(word in PROMPTS["t5"] for word in ("採用", "落選", "監視"))


def test_run_task_verifies_every_task_against_the_documents():
    llm = FakeLLM(good)
    for task_fields in TASKS.items():
        result = run_task(llm, PROMPTS, task_fields, DOCS, {"name": "A"})
        assert result.claims == len(result.evidence) > 0
        assert {c["field"] for c in result.evidence} <= set(task_fields[1])
        assert result.providers == ["fake/fake-model"]
    first_user = llm.calls[0][1]["content"]
    assert '<document id="edinet:S1:Risk">' in first_user and first_user.rstrip().endswith(PROMPTS["t1"].rstrip())


def test_run_task_replaces_items_that_no_document_supports_with_unknown():
    result = run_task(FakeLLM(fabricating), PROMPTS, ("T1", TASKS["T1"]), DOCS, {})
    assert result.evidence == [] and result.claims > 0
    assert set(result.answer.values()) == {"unknown"}


def test_run_task_with_unknown_answers_has_no_claims_to_verify():
    result = run_task(FakeLLM(clueless), PROMPTS, ("T4", TASKS["T4"]), DOCS, {})
    assert (result.answer, result.evidence, result.claims) == ({"reason_forgotten": "unknown"}, [], 0)


def test_run_task_asks_again_once_with_the_error():
    seen = []

    def respond(messages):
        seen.append(len(messages))
        return not_json(messages) if len(seen) == 1 else good(messages)

    llm = FakeLLM(respond)
    result = run_task(llm, PROMPTS, ("T2", TASKS["T2"]), DOCS, {})
    assert seen == [2, 4] and result.providers == ["fake/fake-model"] * 2
    assert "not valid JSON" in llm.calls[1][-1]["content"]


def test_run_task_gives_up_after_the_second_invalid_reply():
    llm = FakeLLM(not_json)
    with pytest.raises(ReplyError):
        run_task(llm, PROMPTS, ("T2", TASKS["T2"]), DOCS, {})
    assert len(llm.calls) == 2


def test_documents_are_what_the_model_sees():
    system, user = build_messages(PROMPTS, "T1", DOCS, {"ticker": "1.T"})
    assert system["content"] == PROMPTS[SYSTEM] and "セメントの値上げ" in user["content"]
