"""Live E2E (L1 section 7.1): the CLI against the real JPX, Yahoo, EDINET, Gemini and LLM APIs.

Manual only: `uv run pytest -m live --no-cov tests/live`. Everything is written to a scratch directory; the repo's
`.env` is only read and the repo's `stocks_cache.duckdb` only by `analyze` (LV4). Scenarios run top to bottom and a
scenario whose prerequisite did not pass is skipped.
"""

import copy
import functools
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import duckdb
import pandas as pd
import pytest
import yaml
from dotenv import dotenv_values

from src.cache import StockCache
from src.docstore import Company
from src.tickers import read_column

ROOT = Path(__file__).resolve().parents[2]
REAL_CACHE = ROOT / "stocks_cache.duckdb"
TIMEOUT_S = {
    "tickers": 180,
    "calendar": 180,
    "fetch": 900,
    "analyze": 900,
    "evaluate": 600,
    "llm-check": 180,
    "docs": 1800,
    "review-eval": 3600,
    "review": 3600,
}
CANDIDATES_N = 3
FETCH_TICKERS_N = 3
MIN_TICKERS = 3000
MISSING_KEY_ENV = "LIVE_E2E_MISSING_KEY"
EDITED_PROMPT = "system.md"
MDNA = "ManagementAnalysisOfFinancialPositionOperatingResultsAndCashFlowsTextBlock"
REFUSAL = "no passed review-eval"
TICKER_COLUMNS = {"code", "name", "market", "sector33", "size"}


@dataclass(frozen=True)
class Result:
    code: int
    out: str
    err: str


@dataclass(frozen=True)
class Scratch:
    root: Path
    configs: dict[str, Path]
    base: dict

    def path(self, section: str, key: str) -> Path:
        return Path(self.base[section][key])


OUTPUTS: list[Result] = []
PASSED: set[int] = set()
STATE: dict[str, object] = {}


@pytest.fixture(scope="session")
def scratch(tmp_path_factory: pytest.TempPathFactory) -> Scratch:
    root = tmp_path_factory.mktemp("live")
    base = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    base["system"].update(input_csv=str(root / "tickers.csv"), db_file=str(REAL_CACHE))
    base["calendar"]["out_csv"] = str(root / "calendar.csv")
    base["output"]["dir"] = str(root / "results")
    base["records"].update(db_file=str(root / "records.duckdb"), export_dir=str(root / "records"))
    base["docstore"]["db_file"] = str(root / "documents.duckdb")
    base["review"]["export_dir"] = str(root / "reviews")
    base["selection"]["candidates_n"] = CANDIDATES_N

    fetch = copy.deepcopy(base)
    fetch["system"].update(input_csv=str(root / "fetch_tickers.csv"), db_file=str(root / "fetch_cache.duckdb"))

    shutil.copytree(ROOT / base["review"]["prompt_dir"], root / "prompts_edited")
    with open(root / "prompts_edited" / EDITED_PROMPT, "a", encoding="utf-8") as f:
        f.write("x")
    edited = copy.deepcopy(base)
    edited["review"]["prompt_dir"] = str(root / "prompts_edited")

    nokey = copy.deepcopy(base)
    nokey["edinet"]["key_env"] = nokey["llm"]["search"]["key_env"] = MISSING_KEY_ENV
    for provider in nokey["llm"]["providers"]:
        provider["key_env"] = MISSING_KEY_ENV

    configs = {}
    for name, cfg in {"main": base, "fetch": fetch, "edited": edited, "nokey": nokey}.items():
        configs[name] = root / f"config_{name}.yaml"
        configs[name].write_text(yaml.safe_dump(cfg), encoding="utf-8")
    return Scratch(root, configs, base)


def run(scratch: Scratch, *args: str, config: str = "main") -> Result:
    cmd = ["uv", "run", "python", "main.py", "--config", str(scratch.configs[config]), *args]
    proc = subprocess.run(
        cmd,
        cwd=ROOT,
        env=os.environ,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=TIMEOUT_S[args[0]],
    )
    result = Result(proc.returncode, proc.stdout, proc.stderr)
    OUTPUTS.append(result)
    return result


def query(db: Path, sql: str, *params: object) -> list[tuple]:
    with duckdb.connect(str(db), read_only=True) as con:
        return con.execute(sql, list(params)).fetchall()


def scenario(*needs: int):
    """Skip the test unless the scenarios `needs` passed; record its own pass."""

    def decorate(fn):
        @functools.wraps(fn)
        def inner(*args, **kwargs):
            if missing := [f"LV{n}" for n in needs if n not in PASSED]:
                pytest.skip(f"prerequisite not passed: {missing}")
            fn(*args, **kwargs)
            PASSED.add(int(fn.__name__.split("_")[1].removeprefix("lv")))

        return inner

    return decorate


def latest_run(scratch: Scratch) -> str:
    return query(scratch.path("records", "db_file"), "SELECT max(run_id) FROM runs")[0][0]


def candidates(scratch: Scratch, run_id: str) -> list[str]:
    sql = "SELECT ticker FROM screen_results WHERE run_id = ? AND stage2_candidate ORDER BY ticker"
    return [t for (t,) in query(scratch.path("records", "db_file"), sql, run_id)]


def review_rows(scratch: Scratch, run_id: str) -> int:
    sql = "SELECT count(*) FROM reviews WHERE run_id = ? AND status IS NOT NULL"
    return query(scratch.path("records", "db_file"), sql, run_id)[0][0]


def eval_rows(scratch: Scratch) -> list[tuple]:
    return query(scratch.path("records", "db_file"), 'SELECT passed FROM review_evals ORDER BY "at"')


@scenario()
def test_lv1_tickers(scratch):
    result = run(scratch, "tickers")
    assert result.code == 0, result.err
    df = pd.read_csv(scratch.path("system", "input_csv"), dtype=str)
    assert len(df) >= MIN_TICKERS
    assert set(df.columns) >= TICKER_COLUMNS


@scenario()
def test_lv2_calendar(scratch):
    result = run(scratch, "calendar")
    assert result.code == 0, result.err
    df = pd.read_csv(scratch.path("calendar", "out_csv"), dtype=str)
    assert len(df) >= 1
    assert pd.to_datetime(df["announce_date"], errors="coerce").notna().any()


@scenario(1)
def test_lv3_fetch(scratch):
    codes = pd.read_csv(scratch.path("system", "input_csv"), dtype=str)["code"].head(FETCH_TICKERS_N).tolist()
    (scratch.root / "fetch_tickers.csv").write_text("\n".join(["code", *codes]) + "\n", encoding="utf-8")
    result = run(scratch, "fetch", config="fetch")
    assert result.code == 0, result.err
    fetch_cache = scratch.root / "fetch_cache.duckdb"
    with StockCache(str(fetch_cache), scratch.base["system"]["market_timezone"]) as cache:
        for code in codes:
            data = cache.get(f"{code}.T")
            assert data is not None, f"{code} not cached"
            assert not data.quarterly_income.empty, f"{code} has no quarterly income"


@scenario(1)
def test_lv4_analyze(scratch):
    if not REAL_CACHE.exists():
        pytest.skip("no stocks_cache.duckdb in the repo (run `fetch` there first)")
    result = run(scratch, "analyze")
    assert result.code == 0, result.err
    csvs = sorted(scratch.path("output", "dir").glob("emin_screening_result_*.csv"))
    assert csvs, "no results CSV"
    flags = pd.read_csv(csvs[-1], dtype=str)["Stage2_Candidate"]
    run_id = latest_run(scratch)
    recorded = len(candidates(scratch, run_id))
    assert recorded == int(flags.eq("True").sum())
    assert recorded <= CANDIDATES_N
    STATE["run_id"] = run_id


@scenario(4)
def test_lv5_evaluate(scratch):
    result = run(scratch, "evaluate")
    assert result.code == 0, result.err
    assert "Added 0 outcome rows." in result.out


@scenario()
def test_lv6_llm_check(scratch):
    result = run(scratch, "llm-check")
    if result.code != 0 and "429" in result.out + result.err:
        pytest.skip("search quota")
    assert result.code == 0, result.err
    assert "chat:" in result.out
    assert "search:" in result.out


@scenario(4)
def test_lv7_docs(scratch):
    run_id = str(STATE["run_id"])
    tickers = candidates(scratch, run_id)
    result = run(scratch, "docs", "--run", run_id)
    assert result.code == 0, result.err
    db = scratch.path("docstore", "db_file")
    names = read_column(scratch.path("system", "input_csv"), "name")
    sql = "SELECT title FROM documents WHERE source = 'edinet' AND ticker = ?"
    sections = {t: [title for (title,) in query(db, sql, t)] for t in tickers}
    assert all(sections.values()), f"candidates without EDINET documents: {[t for t in tickers if not sections[t]]}"
    assert any(MDNA in titles for titles in sections.values())
    for ticker, title, text in query(db, "SELECT ticker, title, text FROM documents WHERE source = 'web'"):
        assert Company(ticker, names[ticker]).mentioned_in(f"{title}\n{text}"), f"{ticker}: web page {title!r}"


@scenario(7)
def test_lv8_review_eval(scratch):
    before = len(eval_rows(scratch))
    result = run(scratch, "review-eval")
    assert result.code in (0, 1), result.err
    rows = eval_rows(scratch)
    assert len(rows) == before + 1
    assert rows[-1][0] is (result.code == 0)
    STATE["eval_passed"] = result.code == 0


@scenario(8)
def test_lv9_review(scratch):
    run_id = str(STATE["run_id"])
    result = run(scratch, "review", "--run", run_id)
    if STATE["eval_passed"]:
        assert result.code == 0, result.err
        assert review_rows(scratch, run_id) == len(candidates(scratch, run_id))
    else:
        assert result.code == 1
        assert REFUSAL in result.out
        assert review_rows(scratch, run_id) == 0


@scenario(9)
def test_lv10_review_rerun(scratch):
    if not STATE["eval_passed"]:
        pytest.skip("review-eval did not pass")
    run_id = str(STATE["run_id"])
    before = review_rows(scratch, run_id)
    result = run(scratch, "review", "--run", run_id)
    assert result.code == 0, result.err
    assert "0 reviewed" in result.out
    assert review_rows(scratch, run_id) == before


@scenario(8)
def test_lv11_edited_prompt(scratch):
    result = run(scratch, "review", "--run", str(STATE["run_id"]), config="edited")
    assert result.code == 1
    assert REFUSAL in result.out


@scenario()
def test_lv12_missing_keys(scratch):
    for command in ("docs", "review"):
        result = run(scratch, command, config="nokey")
        assert result.code == 1, command
        assert "Error: set" in result.out, command
        assert "Traceback" not in result.err, command


def key_values(scratch: Scratch) -> dict[str, str]:
    cfg = scratch.base
    providers = [p["key_env"] for p in cfg["llm"]["providers"]]
    env = {**dotenv_values(ROOT / ".env"), **os.environ}
    return {
        name: env[name]
        for name in [cfg["edinet"]["key_env"], cfg["llm"]["search"]["key_env"], *providers]
        if env.get(name)
    }


def test_lv13_no_key_leak(scratch):
    keys = key_values(scratch)
    if not keys:
        pytest.skip("no API key set")
    for name, value in keys.items():
        for result in OUTPUTS:
            assert value not in result.out + result.err, f"{name} in command output"
        for path in scratch.root.rglob("*"):
            if path.is_file():
                assert value.encode() not in path.read_bytes(), f"{name} in {path}"
