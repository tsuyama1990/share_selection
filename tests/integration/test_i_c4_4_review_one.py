"""I-C4-4: `review_candidates` with a temporary document store and record DB and a fake LLM."""

import datetime
import json
from dataclasses import replace

import duckdb
import pytest

from src import fields as F
from src.docstore import DocStore, Document
from src.llm import LLMError
from src.records import RecordStore
from src.research import load_prompts
from src.review import VERIFIED_ANSWERS, ReviewDeps, ReviewSettings, ReviewSummary, review_candidates
from tests.fixtures.config import CFG
from tests.fixtures.review_flow import PROMPT_DIR, PROMPT_VERSION, FakeLLM, fabricating, good, not_json, task_of

SETTINGS = ReviewSettings.from_config(CFG)
CANDIDATES = [
    ("1.T", {F.NAME: "Company 1", F.PRIORITY_RANK: 2, F.PBR: 0.8}),
    ("2.T", {F.NAME: "Company 2", F.PRIORITY_RANK: 1}),
    ("3.T", {F.NAME: "Company 3", F.PRIORITY_RANK: 3}),
]
TEXT = "営業利益は46億円増加した。セメントの値上げの効果が大きい。"
RUN = "run1"


def doc(ticker: str, text: str = TEXT) -> Document:
    return Document(f"edinet:{ticker}:X", ticker, "edinet", ticker, "t", datetime.datetime(2026, 10, 1), text)


@pytest.fixture
def stores(tmp_path):
    with (
        DocStore(tmp_path / "d.duckdb") as docs,
        RecordStore(tmp_path / "r.duckdb", tmp_path / "rec", tmp_path / "rev") as rec,
    ):
        for ticker in ("1.T", "2.T", "3.T"):
            docs.put(doc(ticker))
        yield rec, docs, tmp_path


def run(stores, llm=None, tickers=None, memo_dir=None, **options):
    """``options``: ``settings`` and ``candidates`` replacing SETTINGS and CANDIDATES."""
    rec, docs, _ = stores
    deps = ReviewDeps(llm or FakeLLM(good), load_prompts(PROMPT_DIR), rec, docs, None, memo_dir)
    return review_candidates(
        RUN, options.get("candidates", CANDIDATES), tickers, options.get("settings", SETTINGS), deps
    )


def row(rec, ticker, run_id=RUN):
    sql = (
        "SELECT status, suggestion, source_type, reason_forgotten, answers, evidence, verified_ratio, needs_attention,"
        " sector_comparison, doc_ids, llm_providers, prompt_version FROM reviews WHERE run_id = ? AND ticker = ?"
    )
    return rec.con.execute(sql, [run_id, ticker]).fetchone()


def test_a_candidate_gets_one_row_with_the_verified_answers_and_evidence(stores):
    summary = run(stores, tickers=["1.T"])
    (
        status,
        suggestion,
        source_type,
        reason,
        answers,
        evidence,
        ratio,
        attention,
        sector,
        doc_ids,
        providers,
        version,
    ) = row(stores[0], "1.T")
    assert summary == ReviewSummary(reviewed=1, failed=0, needs_attention=0)
    assert (status, suggestion, source_type, reason) == ("ok", "採用", "P2 値上げ・価格転嫁の浸透", "見えにくさ")
    answers, evidence = json.loads(answers), json.loads(evidence)
    assert list(answers) == list(CFG["review"]["tasks"]) and answers["T1"]["demand_wave"] == "半導体"
    assert all(c["quote"] in TEXT for claims in evidence.values() for c in claims)
    assert {c["doc_id"] for claims in evidence.values() for c in claims} == {"edinet:1.T:X"}
    assert (ratio, attention, sector) == (1.0, False, None)
    assert json.loads(doc_ids) == ["edinet:1.T:X"] and json.loads(providers) == ["fake/fake-model"]
    assert version == PROMPT_VERSION


def test_fabricated_quotes_leave_nothing_but_unknown_and_flag_the_ticker(stores):
    summary = run(stores, FakeLLM(fabricating), tickers=["1.T"])
    status, suggestion, source_type, _, answers, evidence, ratio, attention, *_ = row(stores[0], "1.T")
    assert summary == ReviewSummary(reviewed=1, failed=0, needs_attention=1)
    assert (status, suggestion, source_type, ratio, attention) == ("ok", "unknown", "unknown", 0.0, True)
    assert all(claims == [] for claims in json.loads(evidence).values())
    assert all(v == "unknown" for answer in json.loads(answers).values() for v in answer.values())


def test_tasks_run_in_order_and_only_the_last_sees_the_verified_answers(stores):
    llm = FakeLLM(good)
    run(stores, llm, tickers=["1.T"])
    users = [c[1]["content"] for c in llm.calls]
    assert [task_of([{}, {"content": u}]) for u in users] == list(CFG["review"]["tasks"])
    contexts = [json.loads(next(line for line in u.splitlines() if line.startswith("{"))) for u in users]
    assert [VERIFIED_ANSWERS in c for c in contexts] == [False, False, False, False, True]
    last = contexts[-1]
    assert last[VERIFIED_ANSWERS]["T1"]["source_type"] == "P2 値上げ・価格転嫁の浸透"
    assert last["ticker"] == "1.T" and last["name"] == "Company 1" and last[F.PBR] == 0.8
    assert F.REAL_PSR not in last  # metrics the candidate lacks are left out


def test_documents_are_cut_to_max_doc_chars_before_the_model_and_the_check(stores):
    rec, docs, _ = stores
    docs.put(doc("4.T", "ABCDEFGHIJ" + "x" * 50))
    settings = replace(SETTINGS, max_doc_chars=10)
    llm = FakeLLM(good)
    run(stores, llm, tickers=["4.T"], settings=settings)
    assert "ABCDEFGHIJ\n</document>" in llm.calls[0][1]["content"]
    assert row(rec, "4.T")[0] == "ok"


def test_targets_are_the_unreviewed_candidates_by_priority_rank_capped(stores):
    settings = replace(SETTINGS, max_tickers=2)
    llm = FakeLLM(good)
    summary = run(stores, llm, settings=settings)
    assert summary.reviewed == 2
    assert stores[0].reviewed(RUN) == {"2.T", "1.T"}  # ranks 1 and 2; rank 3 waits for the next run
    run(stores, llm, settings=settings)
    assert stores[0].reviewed(RUN) == {"1.T", "2.T", "3.T"}


def test_a_ticker_without_documents_or_with_a_failing_llm_is_recorded_and_the_flow_goes_on(stores):
    candidates = [*CANDIDATES, ("9.T", {F.NAME: "No docs", F.PRIORITY_RANK: 0})]

    class Failing(FakeLLM):
        def chat(self, messages, json_mode=False):
            if "Company 1" in messages[1]["content"]:
                raise LLMError("all LLM providers failed")
            return super().chat(messages, json_mode)

    summary = run(stores, Failing(good), candidates=candidates)
    rec = stores[0]
    assert [row(rec, t)[0] for t in ("9.T", "1.T", "2.T", "3.T")] == ["no_documents", "llm_failed", "ok", "ok"]
    assert summary == ReviewSummary(reviewed=2, failed=2, needs_attention=0)
    assert rec.reviewed(RUN) == {"2.T", "3.T"}
    assert row(rec, "9.T")[10] == "[]"


def test_invalid_json_after_the_re_ask_is_recorded_as_bad_json(stores):
    summary = run(stores, FakeLLM(not_json), tickers=["1.T"])
    assert summary == ReviewSummary(reviewed=0, failed=1, needs_attention=0)
    assert row(stores[0], "1.T")[0] == "bad_json"


def test_a_failed_ticker_is_reviewed_again_and_its_row_replaced(stores):
    rec = stores[0]
    run(stores, FakeLLM(not_json), tickers=["1.T"])
    assert rec.con.execute("SELECT count(*) FROM reviews").fetchone() == (1,)
    run(stores)
    assert rec.con.execute("SELECT status FROM reviews WHERE ticker = '1.T'").fetchall() == [("ok",)]
    assert rec.con.execute("SELECT count(*) FROM reviews").fetchone() == (3,)


def test_reviews_are_exported_only_to_the_review_directory(stores):
    run(stores, tickers=["1.T"])
    tmp = stores[2]
    assert duckdb.sql(f"SELECT ticker FROM read_parquet('{tmp / 'rev' / RUN / 'reviews.parquet'}')").fetchall() == [
        ("1.T",)
    ]
    assert not (tmp / "rec").exists()


def test_reviews_round_trip_through_the_records(stores):
    run(stores, tickers=["1.T"])
    rows = stores[0].reviews(RUN)
    assert list(rows) == ["1.T"] and rows["1.T"]["status"] == "ok"
    assert rows["1.T"]["answers"]["T5"]["suggestion"] == "採用" and rows["1.T"]["verified_ratio"] == 1.0


MEMO = CFG["memo"]["filename"]


def test_a_memo_is_written_per_ok_ticker_only_when_memo_dir_is_set(stores):
    memo_dir = stores[2] / "memos"
    run(stores, tickers=["1.T"])
    assert not memo_dir.exists()
    run(stores, tickers=["1.T", "9.T"], memo_dir=memo_dir)  # 9.T has no documents: no memo
    assert [p.name for p in memo_dir.iterdir()] == [MEMO.format(run_id=RUN, ticker="1.T")]
    memo = (memo_dir / MEMO.format(run_id=RUN, ticker="1.T")).read_text(encoding="utf-8")
    assert memo.startswith("# 1.T Company 1")
    assert "提案: 採用" in memo and "要注意" not in memo and "(1.T)" in memo  # source_ref of the document


def test_the_memo_marks_a_ticker_that_needs_attention(stores):
    memo_dir = stores[2] / "memos"
    run(stores, FakeLLM(fabricating), tickers=["1.T"], memo_dir=memo_dir)
    assert "要注意" in (memo_dir / MEMO.format(run_id=RUN, ticker="1.T")).read_text(encoding="utf-8")
