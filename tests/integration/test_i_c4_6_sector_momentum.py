"""I-C4-6: industry momentum over the run's daily closes, stored with a review and shown in its memo."""

import datetime
import json
from contextlib import ExitStack
from dataclasses import replace

import pandas as pd
import pytest

from src import fields as F
from src.cache import StockCache
from src.docstore import DocStore, Document
from src.records import RecordStore, RunInfo
from src.review import ReviewDeps, ReviewSettings, review_candidates
from src.screener import ScreenResult
from src.sector import Peers
from tests.fixtures.config import CFG
from tests.fixtures.review_flow import PROMPT_DIR, FakeLLM, good

TICKERS = ("1.T", "2.T", "3.T", "4.T", "5.T")
SECTORS = {"1.T": "水産", "2.T": "水産", "3.T": "水産", "4.T": "鉱業", "5.T": "鉱業"}
INFO = RunInfo("2026-10", "abc", {}, datetime.date(2026, 10, 1), None, None)
RESULTS = {
    ticker: ScreenResult(True, None, {F.NAME: f"会社{n}", F.PRIORITY_RANK: n, F.PBR: 1.0, F.STAGE2_CANDIDATE: True})
    for n, ticker in enumerate(TICKERS, 1)
}
CFG_MOMENTUM = {
    **CFG,
    "system": {**CFG["system"], "db_file": "cache.duckdb"},
    "docstore": {"db_file": "docs.duckdb"},
    "review": {
        **CFG["review"],
        "db_file": "reviews.duckdb",
        "export_dir": "reviews_export",
        "prompt_dir": str(PROMPT_DIR),
    },
    "sector": {**CFG["sector"], "min_peers": 1, "momentum_note_top_share": 0.5},
    "memo": {**CFG["memo"], "dir": "memos"},
}


def _put_histories(root, cfg) -> None:
    """Two sectors, one of them up; 3.T has no close before the start and is left out."""
    today = datetime.date.today()
    start = (pd.Timestamp(today) - pd.DateOffset(months=3)).date()
    prices = {
        "1.T": {start: 100.0, today: 110.0},
        "2.T": {start: 100.0, today: 200.0},
        "3.T": {today: 100.0},
        "4.T": {start: 100.0, today: 150.0},
        "5.T": {start: 100.0, today: 100.0},
    }
    with StockCache.from_config(cfg, root) as cache:
        for ticker, closes in prices.items():
            index = pd.to_datetime(list(closes))
            cache.put(ticker, {"history": pd.DataFrame({"Close": list(closes.values())}, index=index)})


def _comparison(reviews, run_id: str, ticker: str) -> dict:
    sql = "SELECT sector_comparison FROM reviews WHERE run_id = ? AND ticker = ?"
    return json.loads(reviews.con.execute(sql, [run_id, ticker]).fetchone()[0])


def test_momentum_is_stored_with_the_review_and_annotated_in_the_memo(tmp_path):
    cfg = CFG_MOMENTUM
    with DocStore(tmp_path / "docs.duckdb") as docs:
        for ticker in ("1.T", "3.T"):
            doc = Document(
                f"edinet:{ticker}:X",
                ticker,
                "edinet",
                f"S{ticker[0]}:X",
                "t",
                datetime.datetime(2026, 10, 1),
                f"text of {ticker}",
            )
            docs.put(doc)
    with RecordStore(tmp_path / "run.duckdb", tmp_path / "records") as records:
        run_id = records.record_run(INFO, RESULTS)
    _put_histories(tmp_path, cfg)

    peers = Peers({}, SECTORS, [F.PBR], TICKERS)
    with ExitStack() as stack:
        deps = ReviewDeps.from_config(cfg, tmp_path, {"DEEPSEEK_API_KEY": "test"}, stack, peers)
        deps = replace(deps, llm=FakeLLM(good))
        candidates = [("1.T", {F.NAME: "会社1", F.PBR: 1.0}), ("3.T", {F.NAME: "会社3", F.PBR: 1.0})]
        summary = review_candidates(run_id, candidates, None, ReviewSettings.from_config(cfg), deps)
        assert summary.reviewed == 2

        stored = _comparison(deps.reviews, run_id, "1.T")["momentum"]
        assert stored["months"] == cfg["sector"]["momentum_months"]
        assert stored["industries"] == 2
        assert stored["industry_rank"] == 1
        assert stored["industry_excess"] == pytest.approx(0.15)
        assert stored["position"] == pytest.approx(1.0)
        assert stored["note"] is True

        short = _comparison(deps.reviews, run_id, "3.T")["momentum"]
        assert short["position"] is None
        assert short["note"] is False

        memo = tmp_path / "memos" / cfg["memo"]["filename"].format(run_id=run_id, ticker="1.T")
        text = memo.read_text(encoding="utf-8")
        assert "業種の勢い（3 か月）: 超過リターン +15.00%、全業種の中の順位 1 / 2、業種の中の位置 1.0" in text
        assert "先に上がった会社はその後負けやすい（有意ではない）" in text

        memo3 = tmp_path / "memos" / cfg["memo"]["filename"].format(run_id=run_id, ticker="3.T")
        assert "先に上がった会社はその後負けやすい（有意ではない）" not in memo3.read_text(encoding="utf-8")
