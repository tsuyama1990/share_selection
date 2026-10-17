"""I-C4-5: review, score and judge the eval cases with a fake LLM; the result is recorded per prompt and model."""

import datetime
import json
from pathlib import Path

import duckdb
import pytest

from src import fields as F
from src.docstore import DocStore, Document
from src.records import RecordStore
from src.research import load_prompts
from src.review import ReviewDeps, ReviewSettings, review_candidates
from src.review_eval import EvalResult, judge, load_eval_cases, score_case
from tests.fixtures.config import CFG
from tests.fixtures.review_flow import GOOD_ANSWERS, MODEL, PROMPT_DIR, FakeLLM, clueless, fabricating, not_json, reply

REV = CFG["review"]
CASES = load_eval_cases(Path(__file__).resolve().parents[2] / REV["eval"]["cases_file"])
VERSION = REV["prompt_version"]
THRESHOLDS = {**REV["eval"], "min_verified_ratio": REV["min_verified_ratio"]}
RUN = "eval-1"
TEXT = "セメントの値上げで営業利益が増加。半導体向けの需要。"


def correct(messages):
    """Answers every eval case as expected (the suggestion is one of the expected words)."""
    return reply(messages, {**GOOD_ANSWERS, "T5": {**GOOD_ANSWERS["T5"], "suggestion": "監視"}})


@pytest.fixture
def stores(tmp_path):
    with (
        DocStore(tmp_path / "d.duckdb") as docs,
        RecordStore(tmp_path / "r.duckdb", tmp_path / "rec", tmp_path / "rev") as rec,
    ):
        for case in CASES:
            doc = Document(
                f"edinet:{case.ticker}", case.ticker, "edinet", "ref", "t", datetime.datetime(2026, 10, 1), TEXT
            )
            docs.put(doc)
        yield rec, docs, tmp_path


def evaluate(stores, respond, run_id=RUN) -> EvalResult:
    """What `review-eval` does after collecting the documents."""
    rec, docs, _ = stores
    candidates = [(c.ticker, {F.NAME: c.name, F.PRIORITY_RANK: i}) for i, c in enumerate(CASES, 1)]
    deps = ReviewDeps(FakeLLM(respond), load_prompts(PROMPT_DIR), rec, docs)
    review_candidates(run_id, candidates, None, ReviewSettings.from_config(CFG), deps)
    rows = rec.reviews(run_id)
    results = [(c, score_case(c, rows[c.ticker])) for c in CASES]
    result = judge(results, list(rows.values()), THRESHOLDS, f"fake/{MODEL}")
    summary = [{"ticker": c.ticker, "hit": hit} for c, hit in results]
    rec.record_eval(VERSION, MODEL, result, summary)
    return result


def test_the_eval_file_holds_the_three_checked_cases():
    assert [(c.ticker, c.name, c.task, c.field) for c in CASES] == [
        ("5232.T", "住友大阪セメント", "T1", "source_type"),
        ("6599.T", "エブレン", "T1", "demand_wave"),
        ("6430.T", "ダイコク電機", "T5", "suggestion"),
    ]
    assert [c.expect_any for c in CASES] == [["値上げ", "価格改定", "販売価格"], ["半導体"], ["落選", "監視"]]
    assert all(c.basis for c in CASES) and {c.task for c in CASES} <= set(REV["tasks"])


def test_correct_answers_pass_and_the_pass_is_recorded_for_this_prompt_and_model(stores):
    rec = stores[0]
    assert not rec.passed_eval(VERSION, MODEL)
    result = evaluate(stores, correct)
    assert result == EvalResult(3, 3, 0, 1.0, 0, True)
    assert rec.passed_eval(VERSION, MODEL)
    assert not rec.passed_eval(VERSION, "another-model") and not rec.passed_eval("v0", MODEL)
    row = rec.con.execute(
        "SELECT passed, hit_rate, parse_failures, min_verified_ratio, summary FROM review_evals"
    ).fetchone()
    assert row[:4] == (True, 1.0, 0, 1.0) and json.loads(row[4])[0] == {"ticker": "5232.T", "hit": True}


@pytest.mark.parametrize("respond", [clueless, fabricating, not_json])
def test_wrong_answers_fail_and_the_failure_is_recorded(stores, respond):
    result = evaluate(stores, respond)
    assert not result.passed and result.hits == 0
    assert not stores[0].passed_eval(VERSION, MODEL)
    assert stores[0].con.execute("SELECT passed FROM review_evals").fetchall() == [(False,)]


def test_parse_failures_are_counted(stores):
    assert evaluate(stores, not_json).parse_failures == 3


def test_the_latest_eval_of_a_prompt_and_model_decides(stores):
    rec = stores[0]
    evaluate(stores, correct, "eval-1")
    evaluate(stores, clueless, "eval-2")
    assert not rec.passed_eval(VERSION, MODEL)
    evaluate(stores, correct, "eval-3")
    assert rec.passed_eval(VERSION, MODEL)


def test_evals_are_exported_to_the_review_directory(stores):
    evaluate(stores, correct)
    path = stores[2] / "rev" / "review_evals.parquet"
    assert duckdb.sql(f"SELECT passed, model FROM read_parquet('{path}')").fetchall() == [(True, MODEL)]
