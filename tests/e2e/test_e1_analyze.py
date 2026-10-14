"""Golden-file regression test: screener output on a fixed cached sample.

The sample (``tests/fixtures/sample_cache.json.gz``) is exported from the full
cache by ``tests/fixtures/export_sample.py``. After an intended change of the
screening behavior or ``config.yaml``, regenerate the golden CSV with::

    UPDATE_GOLDEN=1 uv run pytest tests/e2e/test_e1_analyze.py

and review the diff of ``tests/fixtures/golden_screening.csv`` before committing.
"""

import json
import os
import sys
from pathlib import Path

import duckdb
import pandas as pd
import pytest
import yaml

import main
from src.cache import StockCache
from src.config import load_config
from src.records import NO_CACHE
from src.report import prioritize
from src.screener import Screener
from tests.fixtures.sample import load_sample

CFG = load_config()
FIXTURES = Path(__file__).parent.parent / "fixtures"
GOLDEN = FIXTURES / "golden_screening.csv"


def screen_sample(tmp_path: Path) -> pd.DataFrame:
    """Run the configured screener on the sample and return the report frame."""
    with StockCache(str(tmp_path / "sample.duckdb"), CFG["system"]["market_timezone"]) as cache:
        tickers = load_sample(cache)
        screener = Screener.from_config(CFG)
        screened = [screener.screen(d) for t in tickers if (d := cache.get(t)) is not None]
        results = [r.row for r in screened if r.passed]
    prioritize(results, CFG["selection"]["candidates_n"])
    df = pd.DataFrame(results).sort_values("Ticker").reset_index(drop=True)
    return df[[c for c in CFG["output"]["columns"] if c in df.columns]]


def test_screener_matches_golden(tmp_path):
    actual = screen_sample(tmp_path)
    if os.environ.get("UPDATE_GOLDEN"):
        actual.to_csv(GOLDEN, index=False)
        pytest.skip(f"golden regenerated: {GOLDEN}")
    expected = pd.read_csv(GOLDEN).fillna({"Quality_Flags": ""})  # empty flags read back as NaN
    assert len(actual) > 0
    pd.testing.assert_frame_equal(actual.reset_index(drop=True), expected, check_dtype=False, rtol=1e-6)


def test_analyze_records_every_ticker(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "ROOT", tmp_path)
    (tmp_path / CFG["system"]["input_csv"]).write_text("code\n", encoding="utf-8")
    with StockCache(str(tmp_path / "c.duckdb"), CFG["system"]["market_timezone"]) as cache:
        tickers = [*load_sample(cache), "9999.T"]
        main.run_analyze(CFG, tickers, cache, Screener.from_config(CFG), "2026-10")
    rec = CFG["records"]
    with duckdb.connect(str(tmp_path / rec["db_file"])) as con:
        rows = con.execute(
            "SELECT ticker, stage1_pass, stage1_fail_rule, metrics, improvement_class FROM screen_results"
        ).fetchall()
        (run_id,) = con.execute("SELECT run_id FROM runs").fetchone()
    assert sorted(r[0] for r in rows) == sorted(tickers)
    assert {r[0]: r[1:3] for r in rows}["9999.T"] == (False, NO_CACHE)
    failed = [r for r in rows if not r[1] and r[2] != NO_CACHE]
    assert failed and all(r[2] and json.loads(r[3]) is not None for r in failed)
    assert any(r[1] for r in rows)
    assert all((r[4] is None) == (r[0] == "9999.T") for r in rows)
    assert all(r[4] == json.loads(r[3])["Improvement_Class"] for r in rows if r[0] != "9999.T")
    exported = tmp_path / rec["export_dir"] / run_id / "screen_results.parquet"
    assert duckdb.sql(f"SELECT count(*) FROM read_parquet('{exported}')").fetchone() == (len(tickers),)
    assert len(list((tmp_path / CFG["output"]["dir"]).glob("*.csv"))) == 1


def test_analyze_issue_defaults_to_latest_shikiho_issue(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "ROOT", tmp_path)
    (tmp_path / CFG["system"]["input_csv"]).write_text("code\n1.T\n", encoding="utf-8")
    cfg_path = tmp_path / "c.yaml"
    cfg_path.write_text(yaml.safe_dump(CFG), encoding="utf-8")
    calls = []
    monkeypatch.setattr(main, "run_analyze", lambda *a: calls.append(a[-1]))
    monkeypatch.setattr(main, "default_issue", lambda cfg: "2099-03")
    for argv, expected in ((["analyze"], "2099-03"), (["analyze", "--issue", "2020-06"], "2020-06")):
        monkeypatch.setattr(sys, "argv", ["main.py", "--config", str(cfg_path), *argv])
        main.main()
        assert calls[-1] == expected
