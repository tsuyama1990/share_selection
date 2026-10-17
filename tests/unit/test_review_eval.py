import pytest

from src.review_eval import EvalCase, EvalResult, judge, load_eval_cases, score_case

CASE = EvalCase("1.T", "A", "T1", "source_type", ["値上げ", "価格改定"], "basis")
THRESHOLDS = {"min_hit_rate": 0.8, "max_parse_failures": 0, "min_verified_ratio": 0.7}


def row(answer="unknown", quotes=(), status="ok", ratio=1.0):
    evidence = [{"field": "source_type", "claim": "c", "quote": q, "doc_id": "d"} for q in quotes]
    return {
        "status": status,
        "answers": {"T1": {"source_type": answer}},
        "evidence": {"T1": evidence},
        "verified_ratio": ratio,
    }


def test_score_case_looks_in_the_answer_and_in_the_quotes_of_the_field():
    assert score_case(CASE, row("P2 値上げの浸透"))
    assert score_case(CASE, row("P2", quotes=["販売価格の改定", "価格改定を実施"]))
    assert not score_case(CASE, row("P2 コスト削減", quotes=["人件費を削減"]))
    assert not score_case(CASE, row("unknown"))


def test_score_case_ignores_quotes_of_other_fields_and_other_tasks():
    other = row("P2")
    other["evidence"]["T1"].append({"field": "tier", "claim": "c", "quote": "値上げ", "doc_id": "d"})
    other["evidence"]["T2"] = [{"field": "source_type", "claim": "c", "quote": "値上げ", "doc_id": "d"}]
    assert not score_case(CASE, other)
    assert not score_case(CASE, {"status": "no_documents", "answers": {}, "evidence": {}, "verified_ratio": 0.0})


def test_score_case_without_expected_words_needs_a_known_item():
    open_case = EvalCase("1.T", "A", "T1", "source_type", [], "basis")
    assert score_case(open_case, row("anything"))
    assert not score_case(open_case, row("unknown"))


def results(*hits: bool):
    return [(CASE, hit) for hit in hits]


def test_judge_hit_rate_boundary():
    rows = [row()]
    assert judge(results(True, True, True, True, False), rows, THRESHOLDS) == EvalResult(5, 4, 0, 1.0, True)
    assert not judge(results(True, True, True, False, False), rows, THRESHOLDS).passed
    assert not judge([], rows, THRESHOLDS).passed


def test_judge_parse_failures_boundary():
    rows = [row(), row(status="bad_json")]
    assert judge(results(True), rows, THRESHOLDS).parse_failures == 1
    assert not judge(results(True), rows, THRESHOLDS).passed
    assert judge(results(True), rows, {**THRESHOLDS, "max_parse_failures": 1}).passed


def test_judge_lowest_verified_ratio_boundary():
    assert judge(results(True), [row(ratio=0.7), row(ratio=0.9)], THRESHOLDS).passed
    low = judge(results(True), [row(ratio=0.69), row(ratio=0.9)], THRESHOLDS)
    assert (low.min_verified_ratio, low.passed) == (0.69, False)


def test_eval_result_hit_rate():
    assert EvalResult(4, 3, 0, 1.0, True).hit_rate == 0.75
    assert EvalResult(0, 0, 0, 0.0, False).hit_rate == 0.0


def test_load_eval_cases_reads_the_yaml(tmp_path):
    path = tmp_path / "cases.yaml"
    path.write_text(
        "cases:\n  - {ticker: '1.T', name: A, task: T1, field: source_type, expect_any: [x, y], basis: b}\n",
        encoding="utf-8",
    )
    assert load_eval_cases(path) == [EvalCase("1.T", "A", "T1", "source_type", ["x", "y"], "b")]


def test_load_eval_cases_fails_on_a_missing_item(tmp_path):
    path = tmp_path / "cases.yaml"
    path.write_text("cases:\n  - {ticker: '1.T', name: A, task: T1, field: f, expect_any: []}\n", encoding="utf-8")
    with pytest.raises(TypeError):
        load_eval_cases(path)
