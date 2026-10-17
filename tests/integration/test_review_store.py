"""I-C5-3: `ReviewStore` in its own DB file with its own Parquet directory (reviews quote web articles)."""

import json

import duckdb

from src import fields as F
from src.review_eval import EvalResult
from src.review_store import ReviewRow, ReviewStore

RUN = "run1"
ROW = ReviewRow(
    "1.T",
    F.ReviewStatus.OK,
    "採用",
    "P2",
    "見えにくさ",
    {"T5": {"suggestion": "採用"}},
    {"T5": [{"field": "suggestion", "claim": "c", "quote": "q", "doc_id": "d"}]},
    1.0,
    False,
    None,
    ["d"],
    ["fake/model"],
    "v1",
)
RESULT = EvalResult(3, 3, 0, 1.0, 0, True)
MODEL = "model"


def parquet(path):
    return duckdb.sql(f"SELECT * FROM read_parquet('{path}')").df()


def test_a_review_round_trips_and_a_retry_replaces_the_row(tmp_path):
    with ReviewStore(tmp_path / "v.duckdb", tmp_path / "rev") as store:
        store.record_review(RUN, ROW)
        rows = store.reviews(RUN)
        assert list(rows) == ["1.T"] and rows["1.T"]["status"] == "ok"
        assert rows["1.T"]["answers"]["T5"]["suggestion"] == "採用" and rows["1.T"]["verified_ratio"] == 1.0
        assert store.reviewed(RUN) == {"1.T"}
        store.record_review(RUN, ROW.__class__(**{**ROW.__dict__, "status": F.ReviewStatus.BAD_JSON}))
        assert store.reviewed(RUN) == set()
        assert store.con.execute("SELECT count(*) FROM reviews").fetchone() == (1,)


def test_reviews_are_exported_only_to_the_review_directory(tmp_path):
    with ReviewStore(tmp_path / "v.duckdb", tmp_path / "rev") as store:
        store.record_review(RUN, ROW)
    assert parquet(tmp_path / "rev" / RUN / "reviews.parquet")["ticker"].tolist() == ["1.T"]
    assert sorted(p.name for p in tmp_path.iterdir()) == ["rev", "v.duckdb"]


def test_the_latest_eval_of_a_prompt_and_model_decides_and_is_exported(tmp_path):
    with ReviewStore(tmp_path / "v.duckdb", tmp_path / "rev") as store:
        assert not store.passed_eval("v1", MODEL)
        store.record_eval("v1", MODEL, RESULT, [{"ticker": "1.T", "hit": True}])
        assert store.passed_eval("v1", MODEL)
        assert not store.passed_eval("v1", "other") and not store.passed_eval("v0", MODEL)
        failed = EvalResult(3, 0, 0, 0.0, 0, False)
        store.record_eval("v1", MODEL, failed, [])
        assert not store.passed_eval("v1", MODEL)
        summary = store.con.execute('SELECT summary FROM review_evals ORDER BY "at"').fetchall()
    assert json.loads(summary[0][0]) == [{"ticker": "1.T", "hit": True}]
    assert parquet(tmp_path / "rev" / "review_evals.parquet")["passed"].tolist() == [True, False]
