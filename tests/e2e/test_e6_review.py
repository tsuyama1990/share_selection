"""E6: `review-eval` gates `review`, which records LLM research on the stage 2 candidates.

EDINET and the LLM are mocked with httpx.MockTransport (the fake LLM answers from the documents it is shown); no key
may appear in the output, the databases or the Parquet exports. The flow itself is tested at integration level
(tests/integration/test_i_c4_4_review_one.py, test_i_c4_5_review_eval.py). The live gate (real models) is run by hand.
"""

import httpx
import pytest
import yaml

import main
from tests.fixtures.config import CFG
from tests.fixtures.docs_flow import GEMINI_KEY, KEY, all_handler, record_candidates
from tests.fixtures.review_flow import PROMPT_DIR, PROMPT_VERSION, chat_handler, clueless, good

CASES = {
    "cases": [
        {
            "ticker": "1.T",
            "name": "Company 1.T",
            "task": "T1",
            "field": "source_type",
            "expect_any": ["値上げ"],
            "basis": "b1",
        },
        {
            "ticker": "3.T",
            "name": "Company 3.T",
            "task": "T5",
            "field": "suggestion",
            "expect_any": ["採用"],
            "basis": "b3",
        },
    ]
}
CFG_REVIEW = {
    **CFG,
    "edinet": {**CFG["edinet"], "index_days": 1, "request_interval_s": 0},
    "docstore": {"db_file": "docs_test.duckdb"},
    "docs": {**CFG["docs"], "search": False},
    "llm": {**CFG["llm"], "max_calls_per_minute": 1000},
    "review": {**CFG["review"], "prompt_dir": str(PROMPT_DIR), "export_dir": "reviews_test"},
}
MODEL = "gemini-3.5-flash-lite"
REFUSAL = f"Error: no passed review-eval for prompt {PROMPT_VERSION} / {MODEL}; run `review-eval` first.\n"


@pytest.fixture
def setup(project, monkeypatch):
    """Candidates recorded, the eval cases written, keys set; ``llm(respond)`` mocks HTTP with a fake LLM."""
    cases_path = project.root / "cases.yaml"
    cases_path.write_text(yaml.safe_dump(CASES, allow_unicode=True), encoding="utf-8")
    cfg = {
        **CFG_REVIEW,
        "review": {**CFG_REVIEW["review"], "eval": {**CFG["review"]["eval"], "cases_file": str(cases_path)}},
    }
    monkeypatch.setenv("EDINET_API_KEY", KEY)
    monkeypatch.setenv("GEMINI_API_KEY", GEMINI_KEY)
    for name in ("GROQ_API_KEY", "DEEPSEEK_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    run_id = record_candidates(project.root)

    def llm(respond):
        real_client = httpx.Client
        handler = chat_handler(respond, all_handler)
        monkeypatch.setattr(
            main.httpx, "Client", lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw)
        )

    return project, cfg, run_id, llm


def run_cmd(project, cfg, *args) -> int:
    try:
        project.run(*args, cfg=cfg)
    except SystemExit as e:
        return e.code
    return 0


def review_rows(project, cfg, run_id):
    sql = f"SELECT ticker, status FROM reviews WHERE run_id = '{run_id}' ORDER BY ticker"
    return project.query(sql, cfg)


def test_review_refuses_until_review_eval_has_passed(setup, capsys):
    project, cfg, run_id, llm = setup
    llm(good)
    assert run_cmd(project, cfg, "review") == 1
    assert capsys.readouterr().out == REFUSAL
    assert review_rows(project, cfg, run_id) == []


def test_review_eval_passes_with_correct_answers_and_review_then_records(setup, capsys):
    project, cfg, run_id, llm = setup
    llm(good)
    assert run_cmd(project, cfg, "review-eval") == 0
    out = capsys.readouterr().out
    runs = CFG["review"]["eval"]["repeats"]
    assert all(
        f"{n}: hit  1.T T1.source_type" in out and f"{n}: hit  3.T T5.suggestion" in out for n in range(1, runs + 1)
    )
    overall = f"review-eval {MODEL}, {runs} runs: {2 * runs}/{2 * runs} cases, 0 parse failures"
    assert f"{overall}, lowest verified ratio 1.00, 0 answered by a fallback: PASSED" in out
    assert project.query("SELECT prompt_version, model, passed FROM review_evals", cfg) == [
        (PROMPT_VERSION, MODEL, True)
    ]

    assert run_cmd(project, cfg, "review") == 0
    assert "2 reviewed, 1 failed, 0 need attention." in capsys.readouterr().out
    assert review_rows(project, cfg, run_id) == [("1.T", "ok"), ("2.T", "no_documents"), ("3.T", "ok")]
    sql = f"SELECT ticker, suggestion, verified_ratio FROM reviews WHERE run_id = '{run_id}' AND status = 'ok'"
    assert project.query(sql, cfg) == [("1.T", "採用", 1.0), ("3.T", "採用", 1.0)]
    assert sorted(p.name for p in (project.root / "reviews_test" / run_id).iterdir()) == ["reviews.parquet"]
    assert (project.root / "reviews_test" / "review_evals.parquet").exists()


def test_review_eval_fails_with_wrong_answers_and_review_stays_refused(setup, capsys):
    project, cfg, run_id, llm = setup
    llm(clueless)
    assert run_cmd(project, cfg, "review-eval") == 1
    out = capsys.readouterr().out
    assert "1: MISS 1.T T1.source_type" in out and "1: 0/2 cases" in out and out.rstrip().endswith("FAILED")
    assert project.query("SELECT passed FROM review_evals", cfg) == [(False,)]

    assert run_cmd(project, cfg, "review") == 1
    assert capsys.readouterr().out == REFUSAL
    assert review_rows(project, cfg, run_id) == []


def test_review_limits_to_the_given_tickers(setup):
    project, cfg, run_id, llm = setup
    llm(good)
    run_cmd(project, cfg, "review-eval")
    assert run_cmd(project, cfg, "review", "--run", run_id, "--tickers", "3.T") == 0
    assert review_rows(project, cfg, run_id) == [("3.T", "ok")]


def test_no_key_reaches_the_output_databases_or_exports(setup, capsys):
    project, cfg, run_id, llm = setup
    llm(good)
    run_cmd(project, cfg, "review-eval")
    run_cmd(project, cfg, "review")
    captured = capsys.readouterr()
    dump = captured.out + captured.err + repr(project.query("SELECT * FROM reviews", cfg))
    dump += repr(project.query("SELECT * FROM review_evals", cfg))
    dump += repr(project.query("SELECT * FROM runs", cfg))
    for path in (project.root / "reviews_test").rglob("*.parquet"):
        dump += path.read_bytes().decode("latin-1")
    assert dump and KEY not in dump and GEMINI_KEY not in dump


def test_review_requires_an_llm_key(setup, monkeypatch, capsys):
    project, cfg, _, llm = setup
    llm(good)
    monkeypatch.delenv("GEMINI_API_KEY")
    assert run_cmd(project, cfg, "review") == 1
    assert capsys.readouterr().out == "Error: set the API key of an LLM provider (environment or .env).\n"
