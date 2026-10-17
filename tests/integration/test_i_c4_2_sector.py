"""I-C4-2: sector medians over all tickers of a recorded run (also those that failed the gate) and the comparison
stored with a review."""

import datetime
import json

import pytest

from src import fields as F
from src.docstore import DocStore, Document
from src.records import RecordStore, RunInfo
from src.research import load_prompts
from src.review import ReviewDeps, ReviewSettings, review_candidates
from src.screener import NO_CACHE, ScreenResult
from src.sector import Peers, sector_medians
from tests.fixtures.config import CFG
from tests.fixtures.review_flow import PROMPT_DIR, FakeLLM, good

METRICS = [F.PBR, F.REAL_PSR]
MIN_PEERS = 3
SECTORS = {"1.T": "水産", "2.T": "水産", "3.T": "水産", "4.T": "水産", "5.T": "鉱業", "6.T": "鉱業", "7.T": "鉱業"}
INFO = RunInfo("2026-10", "abc", {}, datetime.date(2026, 10, 1), None, None)
# 1.T is the candidate; 2.T and 3.T failed the gate but have metrics; 4.T and 7.T had no cache; B has too few values
RESULTS = {
    "1.T": ScreenResult(True, None, {F.NAME: "会社1", F.PRIORITY_RANK: 1, F.STAGE2_CANDIDATE: True, F.PBR: 1.0}),
    "2.T": ScreenResult(False, "rule", {F.PBR: 3.0, F.REAL_PSR: 0.5}),
    "3.T": ScreenResult(False, "rule", {F.PBR: 2.0}),
    "4.T": ScreenResult(False, NO_CACHE, {}),
    "5.T": ScreenResult(False, "rule", {F.PBR: 9.0}),
    "6.T": ScreenResult(False, "rule", {F.PBR: 1.0}),
    "7.T": ScreenResult(False, NO_CACHE, {}),
}


@pytest.fixture
def stores(tmp_path):
    with (
        DocStore(tmp_path / "d.duckdb") as docs,
        RecordStore(tmp_path / "r.duckdb", tmp_path / "rec", tmp_path / "rev") as rec,
    ):
        text = "営業利益は46億円増加した。"
        docs.put(Document("edinet:1.T:X", "1.T", "edinet", "S1:X", "t", datetime.datetime(2026, 10, 1), text))
        yield rec, docs, rec.record_run(INFO, RESULTS)


def test_the_population_is_every_ticker_of_the_run_not_only_the_candidates(stores):
    rec, _, run_id = stores
    assert set(rec.run_metrics(run_id)) == set(RESULTS)
    assert [t for t, _ in rec.candidates(run_id)] == ["1.T"]


def test_medians_use_tickers_that_failed_the_gate_and_thin_sectors_are_none(stores):
    rec, _, run_id = stores
    medians = sector_medians(rec.run_metrics(run_id), SECTORS, METRICS, MIN_PEERS)
    assert medians["水産"] == {F.PBR: 2.0, F.REAL_PSR: None}  # PBR of 1.T, 2.T, 3.T; one Real_PSR is too few
    assert medians["鉱業"] == {F.PBR: None, F.REAL_PSR: None}  # two PBR values


def test_the_comparison_is_stored_with_the_review(stores):
    rec, docs, run_id = stores
    peers = Peers(sector_medians(rec.run_metrics(run_id), SECTORS, METRICS, MIN_PEERS), SECTORS, METRICS)
    deps = ReviewDeps(FakeLLM(good), load_prompts(PROMPT_DIR), rec, docs, peers, None)
    review_candidates(run_id, rec.candidates(run_id), None, ReviewSettings.from_config(CFG), deps)
    sql = "SELECT sector_comparison FROM reviews WHERE run_id = ? AND ticker = '1.T'"
    stored = json.loads(rec.con.execute(sql, [run_id]).fetchone()[0])
    assert stored["sector"] == "水産"
    assert stored["metrics"][F.PBR] == {"value": 1.0, "median": 2.0, "ratio": 0.5}
    assert stored["metrics"][F.REAL_PSR] == {"value": None, "median": None, "ratio": None}
