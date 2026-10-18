"""E12: `review-eval`, then `review` on a cache with price history.

The memo and `sector_comparison` carry the industry's 3-month excess return, its rank among industries and the
candidate's position in its industry; the stage 2 candidates and their order stay the same.
"""

import datetime
import json

import httpx
import pandas as pd
import pytest
import yaml

from src import fields as F
from src.cache import StockCache
from src.records import RecordStore
from src.screener import ScreenResult
from tests.fixtures.config import CFG
from tests.fixtures.docs_flow import CANDIDATES, COMPANIES, GEMINI_KEY, INFO, KEY, SECTOR, all_handler
from tests.fixtures.review_flow import PROMPT_DIR, chat_handler, good

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
    "review": {
        **CFG["review"],
        "prompt_dir": str(PROMPT_DIR),
        "db_file": "reviews_test.duckdb",
        "export_dir": "reviews_test",
    },
    "sector": {**CFG["sector"], "min_peers": 1, "momentum_note_top_share": 0.5},
}
EXTRA = {"4.T": "会社4", "5.T": "会社5"}
SECTORS = {"1.T": SECTOR, "2.T": SECTOR, "3.T": SECTOR, "4.T": "鉱業", "5.T": "鉱業"}
NAMES = {company.ticker: company.name for company in COMPANIES} | EXTRA


def _results() -> dict:
    results = {
        ticker: ScreenResult(True, None, {**metrics, F.IMPROVEMENT_CLASS: "clear", F.STAGE2_CANDIDATE: True})
        for ticker, metrics in CANDIDATES
    }
    for ticker, name in EXTRA.items():
        results[ticker] = ScreenResult(False, "rule", {F.NAME: name, F.PBR: 1.5})
    return results


def _write_tickers(root, cfg) -> None:
    rows = "".join(f"{ticker.removesuffix('.T')},{NAMES[ticker]},{SECTORS[ticker]}\n" for ticker in SECTORS)
    (root / cfg["system"]["input_csv"]).write_text("code,name,sector33\n" + rows, encoding="utf-8")


def _put_histories(root, cfg) -> None:
    """Two sectors, one up; 3.T has no close before the start and is left out."""
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


def _record(root, cfg) -> str:
    _write_tickers(root, cfg)
    with RecordStore.from_config(cfg, root) as store:
        run_id = store.record_run(INFO, _results())
    _put_histories(root, cfg)
    return run_id


@pytest.fixture
def setup(project, monkeypatch):
    """Candidates recorded, the eval cases written, a price cache, keys set; ``llm(respond)`` mocks HTTP."""
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
    run_id = _record(project.root, cfg)

    def llm(respond):
        real_client = httpx.Client
        handler = chat_handler(respond, all_handler)
        monkeypatch.setattr(httpx, "Client", lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw))

    return project, cfg, run_id, llm


def run_cmd(project, cfg, *args) -> int:
    try:
        project.run(*args, cfg=cfg)
    except SystemExit as e:
        return e.code
    return 0


def _comparison(project, cfg, run_id: str, ticker: str) -> dict:
    sql = f"SELECT sector_comparison FROM reviews WHERE run_id = '{run_id}' AND ticker = '{ticker}'"
    return json.loads(project.query(sql, cfg, "review")[0][0])


def test_review_memo_and_sector_comparison_carry_the_industry_momentum(setup, capsys):
    project, cfg, run_id, llm = setup
    llm(good)
    assert run_cmd(project, cfg, "docs") == 0
    capsys.readouterr()
    assert run_cmd(project, cfg, "review-eval") == 0
    capsys.readouterr()
    with RecordStore.from_config(cfg, project.root) as store:
        before = store.candidates(run_id)

    assert run_cmd(project, cfg, "review") == 0
    out = capsys.readouterr().out
    assert "2 reviewed, 1 failed, 0 need attention." in out
    with RecordStore.from_config(cfg, project.root) as store:
        assert store.candidates(run_id) == before

    stored = _comparison(project, cfg, run_id, "1.T")["momentum"]
    assert stored["months"] == cfg["sector"]["momentum_months"]
    assert stored["industries"] == 2
    assert stored["industry_rank"] == 1
    assert stored["industry_excess"] == pytest.approx(0.15)
    assert stored["position"] == pytest.approx(1.0)
    assert stored["note"] is True

    short = _comparison(project, cfg, run_id, "3.T")["momentum"]
    assert short["position"] is None
    assert short["note"] is False

    memo = project.root / cfg["memo"]["dir"] / cfg["memo"]["filename"].format(run_id=run_id, ticker="1.T")
    text = memo.read_text(encoding="utf-8")
    assert "業種の勢い（3 か月）: 超過リターン +15.00%、全業種の中の順位 1 / 2、業種の中の位置 1.0" in text
    assert "先に上がった会社はその後負けやすい（有意ではない）" in text

    memo3 = project.root / cfg["memo"]["dir"] / cfg["memo"]["filename"].format(run_id=run_id, ticker="3.T")
    assert "先に上がった会社はその後負けやすい（有意ではない）" not in memo3.read_text(encoding="utf-8")
